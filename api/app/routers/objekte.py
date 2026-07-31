"""Objekte, Zeiträume, Positionen, Abrechnung."""
import json
import logging
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlmodel import Session, select

from ..belegposten import (belege_je_position, handanteil, kurz,
                           anlegen as position_bauen)
from ..db import get_session
from ..deps import objekt_holen
from ..bezeichnung import anzeigename
from ..export import als_datei, dateiname, exportiere, importiere, loesche
from ..felder import bereinige
from ..engine import Position, abrechnung
from ..erinnerungen import beleg_erinnerung, frist_erinnerung, in_sicht
from ..frist import frist_tage
from ..nachpflege import hinweise, zusammenfassung
from ..models import (GRUNDSTUECK, Bewohner, Dokument, Einheit, Kostenart,
                      Kostenposition, Kredit, Miete, Notarvertrag, Objekt,
                      Partei, Versicherung, Vorauszahlung, Zahlung, Zeitraum,
                      ist_grundstueck)
from ..turnus import jahresbetrag
from ..verteilung import (SCHLUESSEL, VORGABE, UnbekannterSchluessel, ableiten,
                          ableiten_einheit, fehlende_angaben, stammdaten,
                          vorauszahlung_je_partei, vorschau)

log = logging.getLogger("immocalc")
router = APIRouter(prefix="/api", tags=["objekte"])

# Sicherungen liegen im Home-Ordner, nicht bei den Unterlagen einer Immobilie —
# die bleibt beim Löschen ja gerade bestehen.
SICHERUNGSORDNER = "00_ImmoCalc_Sicherungen"

# CCLXIII: Genau diese Stammdaten gehen über die Vorlage in den Ordnernamen ein
# (siehe cloud.ordner_fuer → bezeichnung.nach_vorlage). Nur wenn sich eines von
# ihnen ändert, lohnt der Cloud-Round-Trip zum Prüfen/Umbenennen — ein Umschalten
# von `aktiv` oder ein neuer Kaufpreis lässt den Ordner unberührt.
_ORDNER_FELDER = {"name", "ort", "strasse", "plz", "typ", "nutzung",
                  "gemarkung", "flurstueck"}


def _slugify(name: str) -> str:
    umlaute = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}
    s = name.lower()
    for k, v in umlaute.items():
        s = s.replace(k, v)
    s = "".join(c if c.isalnum() else "-" for c in s)
    return "-".join(t for t in s.split("-") if t) or "objekt"


def _freier_slug(session: Session, name: str) -> str:
    basis = _slugify(name)
    slug, n = basis, 2
    while session.exec(select(Objekt).where(Objekt.slug == slug)).first():
        slug = f"{basis}-{n}"
        n += 1
    return slug


class EinheitIn(BaseModel):
    bezeichnung: str
    nutzungsart: str = "Wohnen"
    flaeche: Optional[float] = None
    partei: str = ""
    personen: int = 1


class ObjektIn(BaseModel):
    name: str
    ort: str = ""
    strasse: str = ""
    plz: str = ""
    typ: str = "lg-mfhA"
    nutzung: str = "Wohnen"
    turnus: str = "kalender"
    start_monat: int = 1
    flaeche: Optional[float] = None
    kaufpreis: Optional[float] = None
    verkehrswert: Optional[float] = None
    # CCVIII: beim Anlegen wählbar, ob das Objekt Teil einer WEG ist. Ein
    # Grundstück kann keine WEG sein — das wird beim Anlegen erzwungen.
    weg: bool = False
    kostenarten: list[str] = []
    einheiten: list[EinheitIn] = []


def _je_objekt(zeilen: list, ids: list[int]) -> dict[int, list]:
    """Ordnet Zeilen ihrem Objekt zu — jedes Objekt kommt vor, auch leer."""
    eimer: dict[int, list] = {i: [] for i in ids}
    for zeile in zeilen:
        eimer.setdefault(zeile.objekt_id, []).append(zeile)
    return eimer


def _miete_je_einheit(mieten: list[Miete], einheiten: list[Einheit],
                      heute: date) -> dict[str, float]:
    """Was jede Einheit heute im Monat einbringt — aus den bereits geladenen
    Mietzeilen, ohne weitere Abfrage.

    Beträge stehen *je Turnus* (`models.Miete`): eine vierteljährlich gezahlte
    Pacht ist nicht das Monatsergebnis. Ohne die Umrechnung über
    `jahresbetrag` stünde in der Blase das Dreifache.

    Eine Miete, die keiner Einheit zuzuordnen ist (Objektmiete bei mehreren
    Einheiten), bleibt draußen — sie mehrfach voll auszuweisen wäre falsch."""
    je_einheit: dict[str, float] = {}
    for m in mieten:
        if not _laeuft(m, heute):
            continue
        ziel = _zuordnung(m, einheiten)
        if not ziel:
            continue
        monat = jahresbetrag(m.kaltmiete + m.stellplatz + m.sonstige,
                             m.turnus) / 12
        je_einheit[ziel] = je_einheit.get(ziel, 0.0) + monat
    return je_einheit


def _miete_felder(e: Einheit, je_einheit: dict[str, float]) -> dict:
    """CCCLXVII — Monatsmiete und Miete je m² für eine Einheit.

    `miete_qm` teilt durch DIESELBE Fläche, die die Kachel als m² zeigt (die
    Wohn-/Nutzfläche der Einheit) — sonst stünden in einer Blase zwei nicht
    zusammenpassende Zahlen. Die effektive Fläche (mit Gemeinschaftsanteilen)
    ist die Bezugsgröße der Kostenverteilung, nicht des Miet-Quadratmeterpreises.
    `miete_qm` bleibt `None`, wo nichts zu rechnen ist — „keine Angabe" ist
    etwas anderes als „0 €/m²". Bewusst nicht `kaltmiete` genannt: das Feld gibt
    es im Detail-Payload bereits mit anderer Bedeutung."""
    monat = round(je_einheit.get(e.bezeichnung.strip(), 0.0), 2)
    flaeche = e.flaeche or 0.0
    return {
        "miete_monat": monat,
        "miete_qm": round(monat / flaeche, 2) if monat and flaeche else None,
    }


@router.get("/objekte")
def objekte(session: Session = Depends(get_session)) -> list[dict]:
    """Die Objektliste der Startseite — mit den Einheiten je Objekt.

    Geholt wird in wenigen Abfragen für alle Objekte zusammen und danach in
    Python zugeordnet: je Objekt einzeln nachzuladen ergäbe bei zwanzig
    Immobilien hundert Abfragen für eine einzige Seite."""
    alle = session.exec(select(Objekt)).all()
    ids = [o.id for o in alle if o.id is not None]
    if not ids:
        return []

    zeitraeume = _je_objekt(session.exec(
        select(Zeitraum).where(Zeitraum.objekt_id.in_(ids))).all(), ids)
    einheiten = _je_objekt(session.exec(
        select(Einheit).where(Einheit.objekt_id.in_(ids))).all(), ids)
    mieten = _je_objekt(session.exec(
        select(Miete).where(Miete.objekt_id.in_(ids))).all(), ids)

    # CCCXV — sind mehrere Abrechnungen offen, zeigt die Kachel die *nächst-
    # fällige* (kleinste § 556-Restfrist), nicht die erste in der Datenbank —
    # sonst stünde oben eine Frist von 800 Tagen, während eine andere längst
    # drängt. `frist_tage` ist die Zahl der Tage bis zur Frist (klein = eilig).
    def _naechste(zs: list) -> Zeitraum | None:
        offen = [z for z in zs if z.status == "in Arbeit"]
        return min(offen, key=frist_tage) if offen else None
    aktive = {oid: _naechste(zs) for oid, zs in zeitraeume.items()}
    zids = [z.id for z in aktive.values() if z is not None]
    offene: dict[int, int] = {}
    if zids:
        for p in session.exec(select(Kostenposition).where(
                Kostenposition.zeitraum_id.in_(zids))).all():
            if p.status == "offen":
                offene[p.zeitraum_id] = offene.get(p.zeitraum_id, 0) + 1

    out = []
    heute = date.today()
    for o in alle:
        aktiv = aktive.get(o.id)
        # CCCLXXVIII — dieselbe Definition von „läuft heute" wie in
        # `_einheit_zeile`/`_miete_je_einheit`: Einzug berücksichtigen und ein
        # befristetes, aber laufendes Mietverhältnis als vermietet zählen (nicht
        # jedes gesetzte `bis_datum` als beendet).
        laufend = [m for m in mieten[o.id] if _laeuft(m, heute)]
        # Eine Miete ohne Einheitsangabe meint das ganze Objekt — dann gilt
        # jede Einheit als vermietet, sonst keine einzige.
        ganzes_objekt = any(not m.einheit.strip() for m in laufend)
        belegt = {m.einheit.strip() for m in laufend if m.einheit.strip()}
        je_einheit = _miete_je_einheit(mieten[o.id], einheiten[o.id], heute)
        out.append({
            "id": o.id, "slug": o.slug, "name": o.name, "ort": o.ort,
            "anzeigename": anzeigename(o.name, o.ort, o.strasse, o.plz),
            "strasse": o.strasse, "plz": o.plz,
            "typ": o.typ, "turnus": o.turnus, "aktiv": o.aktiv,
            "einheiten": len(einheiten[o.id]),
            # Die Einheiten selbst — die Startseite zeigt sie als Bubbles.
            # `einheiten` bleibt die Anzahl, damit bestehende Aufrufer bleiben.
            "einheiten_liste": [
                {"id": e.id, "bezeichnung": e.bezeichnung,
                 "nutzungsart": e.nutzungsart, "flaeche": e.flaeche,
                 "vermietet": ganzes_objekt or e.bezeichnung.strip() in belegt,
                 # CCCLXVII — die Blase auf der Startseite nennt die laufende
                 # Monatsmiete und was sie je m² bedeutet. Beides additiv;
                 # 0.0 / None heißt „nicht gepflegt" und wird nicht gezeigt.
                 **_miete_felder(e, je_einheit)}
                for e in einheiten[o.id]],
            "offene_positionen": offene.get(aktiv.id, 0) if aktiv else 0,
            "frist_tage": frist_tage(aktiv) if aktiv else None,
            "miete_monatlich": round(sum(m.kaltmiete for m in laufend), 2),
            # CCCV — beim Grundstück trägt die Kachel die Flurnummer statt
            # einer Nebenkostenfrist, die es dort nicht gibt.
            "flurstueck": o.flurstueck, "gemarkung": o.gemarkung,
        })
    return out


@router.post("/objekte", status_code=201)
def objekt_anlegen(data: ObjektIn, session: Session = Depends(get_session)) -> dict:
    # Ein Grundstück hat keine Mieter und keine WEG-Nebenkostenverteilung —
    # die WEG-Ebene ergäbe dort keinen Sinn und bleibt aus.
    weg = data.weg and data.typ != GRUNDSTUECK
    o = Objekt(
        slug=_freier_slug(session, data.name), name=data.name, ort=data.ort,
        strasse=data.strasse, plz=data.plz, typ=data.typ, nutzung=data.nutzung,
        turnus=data.turnus, start_monat=data.start_monat, flaeche=data.flaeche,
        kaufpreis=data.kaufpreis, verkehrswert=data.verkehrswert, weg=weg,
    )
    session.add(o)
    session.commit()
    session.refresh(o)

    for e in data.einheiten:
        session.add(Einheit(objekt_id=o.id, bezeichnung=e.bezeichnung,
                            nutzungsart=e.nutzungsart, flaeche=e.flaeche))
        if e.partei:
            session.add(Partei(objekt_id=o.id, name=e.partei, personen=e.personen))
    for name in data.kostenarten:
        session.add(Kostenart(objekt_id=o.id, name=name, aktiv=True))

    # Erster Zeitraum ergibt sich aus dem Turnus — sonst hat das Objekt nichts
    # zu tun. Ein Grundstück bekommt keinen: es hat keine Mieter, über die
    # abzurechnen wäre, und bekäme sonst eine Frist nach § 556 BGB, die es für
    # einen Acker nicht gibt (auf der Startseite stand dann „Frist in 528 T").
    if not ist_grundstueck(o):
        heute = date.today()
        start = date(heute.year if data.start_monat <= heute.month else heute.year - 1,
                     data.start_monat, 1)
        ende = date(start.year + 1, start.month, 1) - timedelta(days=1)
        session.add(Zeitraum(objekt_id=o.id, start=start, ende=ende,
                             typ="regulär", status="in Arbeit"))
    session.commit()
    return {"slug": o.slug, "id": o.id, "name": o.name}


@router.get("/objekte/{slug}")
def objekt(slug: str, session: Session = Depends(get_session)) -> dict:
    o = session.exec(select(Objekt).where(Objekt.slug == slug)).first()
    if not o:
        raise HTTPException(404, "Objekt nicht gefunden")
    einheiten = session.exec(select(Einheit).where(Einheit.objekt_id == o.id)).all()
    parteien = session.exec(select(Partei).where(Partei.objekt_id == o.id)).all()
    zeitraeume = session.exec(select(Zeitraum).where(Zeitraum.objekt_id == o.id)).all()
    mieten = session.exec(select(Miete).where(Miete.objekt_id == o.id)).all()
    offen = hinweise(o, einheiten, mieten)
    return {
        "objekt": o, "einheiten": einheiten, "parteien": parteien,
        # Aus den Einheiten summiert — die maßgebliche Wohnfläche und die
        # Stellplätze des Objekts. Single Source of Truth fürs Frontend: die
        # manuelle Objektfläche (o.flaeche) wird nur noch als mögliche
        # Abweichung dagegen geprüft, nicht mehr als primäre Angabe geführt.
        "wohnflaeche_summe": round(sum(e.flaeche or 0 for e in einheiten), 2),
        "stellplaetze_summe": sum(e.stellplaetze or 0 for e in einheiten),
        "einheiten_mit_flaeche": sum(1 for e in einheiten if e.flaeche),
        "nachpflege": {**zusammenfassung(offen), "offen": offen},
        "zeitraeume": [{"id": z.id, "label": f"{z.start:%d.%m.%Y} – {z.ende:%d.%m.%Y}",
                        "typ": z.typ, "status": z.status,
                        "frist_tage": frist_tage(z) if z.status == "in Arbeit" else None}
                       for z in zeitraeume],
    }


@router.patch("/objekte/{slug}")
def objekt_aendern(slug: str, data: dict, session: Session = Depends(get_session)) -> dict:
    o = session.exec(select(Objekt).where(Objekt.slug == slug)).first()
    if not o:
        raise HTTPException(404, "Objekt nicht gefunden")
    erlaubt = {"name", "ort", "strasse", "plz", "typ", "nutzung", "turnus",
               "start_monat", "flaeche", "kaufpreis", "kaufdatum", "verkehrswert",
               "aktiv", "nc_ordner", "bank", "iban", "kontoinhaber",
               # CCCXXXIV / CCCXXX — Objektart (Anzeige) und Baujahr/Baudatum
               "objektart", "baudatum",
               # CCCXLII — Verkehrswert je Einheit anzeigen (Schalter)
               "einheit_verkehrswert",
               # CCCLVI — Verkehrswert-Modus: ganzes Objekt oder je Einheit
               "verkehrswert_modus",
               # Grundstück — bleibt bei jedem anderen Objekttyp einfach leer
               "grundstueck_flaeche", "grundstueck_m2_preis",
               "grundstueck_nutzungsart",
               "grundstueck_wirtschaftsart", "gemarkung", "flurstueck",
               "grundsteuerwert", "grundsteuer_messbetrag",
               "grundsteuer_hebesatz",
               # CCIX — Rücklagenkonto
               "ruecklage_saldo", "ruecklage_monatlich",
               # CCVIII — WEG-Ebene
               "weg", "hausgeld_monatlich", "weg_ruecklage_zufuehrung",
               "weg_verwalter",
               # CCXXXV — Erwerbsart und Nießbrauch
               "erwerbsart", "afa_basis_uebernommen",
               "niessbrauch_aktiv", "niessbrauch_berechtigt", "niessbrauch_bis"}
    felder = bereinige(Objekt, {k: v for k, v in data.items() if k in erlaubt})
    if not felder.get("name", "x"):
        raise HTTPException(400, "Der Name darf nicht leer sein")
    # Ein Grundstück kann keine WEG sein — dort gibt es keine Mieter, über die
    # eine Hausverwaltung Nebenkosten verteilen würde.
    if felder.get("weg") and (felder.get("typ", o.typ) == GRUNDSTUECK):
        raise HTTPException(400, "Ein Grundstück kann nicht Teil einer WEG sein.")
    # ueber model_validate, damit Datumsstrings aus JSON zu echten date-Objekten
    # werden — als Zeichenkette gespeichert liesse sich das Feld nicht mehr lesen.
    # CCLXIII: ändert sich ein Feld, das in den Ordnernamen eingeht, zieht der
    # Nextcloud-Ordner automatisch nach — ohne eigenen Knopf. Der Vorlagenname
    # aus den *alten* Werten wird noch vor dem Überschreiben festgehalten: nur
    # ein Ordner, der ihm bisher folgte, wird umbenannt (ein selbst benannter
    # bleibt). Setzt der Nutzer `nc_ordner` in derselben Anfrage selbst, hat das
    # Vorrang — dann keine automatische Umbenennung.
    benennt_um = bool(felder.keys() & _ORDNER_FELDER
                      and "nc_ordner" not in felder and o.nc_ordner)
    war_name = ""
    if benennt_um:
        from .cloud import ordner_fuer                 # zirkelfrei zur Laufzeit
        war_name = ordner_fuer(session, o)             # aus den alten Stammdaten

    geprueft = Objekt.model_validate({**o.model_dump(), **felder})
    for k in felder:
        setattr(o, k, getattr(geprueft, k))
    # CCXCVII — beim Grundstück den Grundstückswert aus dem geschätzten m²-Preis
    # errechnen (Preis × Fläche). So bleibt `verkehrswert` die eine Quelle für
    # die Vermögensübersicht, ohne dass sie vom m²-Preis wissen muss.
    if o.grundstueck_m2_preis and o.grundstueck_flaeche:
        o.verkehrswert = round(o.grundstueck_m2_preis * o.grundstueck_flaeche, 2)
    session.add(o)
    session.commit()

    antwort = {"ok": True, "slug": o.slug}
    if benennt_um:
        from .cloud import ordner_nachziehen          # zirkelfrei zur Laufzeit
        try:
            ergebnis = ordner_nachziehen(session, o, war_name=war_name)
        except Exception as fehler:      # noqa: BLE001 — Stammdaten sind sicher
            log.warning("Ordner-Umbenennung fehlgeschlagen: %s", fehler)
            session.rollback()
            ergebnis = {"umbenannt": False, "fehler": str(fehler)}
        if ergebnis.get("umbenannt"):
            antwort["ordner_umbenannt"] = ergebnis
        elif ergebnis.get("fehler"):
            antwort["ordner_hinweis"] = ergebnis
    return antwort


@router.get("/objekte/{slug}/export")
def objekt_export(slug: str, session: Session = Depends(get_session)) -> Response:
    """Vollständige Sicherung als JSON-Datei zum Herunterladen."""
    o = session.exec(select(Objekt).where(Objekt.slug == slug)).first()
    if not o:
        raise HTTPException(404, "Objekt nicht gefunden")
    daten = exportiere(session, o)
    return Response(
        content=als_datei(daten), media_type="application/json",
        headers={"Content-Disposition":
                 f'attachment; filename="{dateiname(o)}"'})


def _sicherung_in_die_cloud(session: Session, objekt: Objekt,
                            daten: dict) -> dict:
    """Legt die Sicherung neben den Unterlagen ab — best effort.

    Scheitert das (keine Verbindung, kein Home-Ordner), wird trotzdem
    gelöscht: die Sicherung geht ohnehin auch an den Browser."""
    from .cloud import S_HOME, _lies, verbindung          # zirkelfrei zur Laufzeit
    home = _lies(session, S_HOME)
    if not home:
        return {"gesichert": False, "grund": "Kein Home-Ordner gewählt"}
    ordner = f"{home.strip('/')}/{SICHERUNGSORDNER}"
    ziel = f"{ordner}/{dateiname(objekt)}"
    try:
        client = verbindung(session)
        client.ordner_anlegen(ordner)
        name, n = ziel, 2
        while client.existiert(name):        # nie überschreiben
            name = ziel[:-5] + f"_{n}.json"
            n += 1
        client.lege_ab(name, als_datei(daten), typ="application/json")
        return {"gesichert": True, "pfad": "/" + name}
    except Exception as fehler:              # noqa: BLE001 — Löschen soll laufen
        log.warning("Sicherung in die Cloud fehlgeschlagen: %s", fehler)
        return {"gesichert": False, "grund": str(fehler)}


@router.delete("/objekte/{slug}")
def objekt_loeschen(slug: str, session: Session = Depends(get_session)) -> dict:
    """Löscht eine Immobilie samt allem, was in der Datenbank daran hängt.

    Vorher wird eine JSON-Sicherung in die Nextcloud geschrieben. Die dort
    liegenden Unterlagen bleiben unberührt — sie gehören dem Nutzer."""
    o = session.exec(select(Objekt).where(Objekt.slug == slug)).first()
    if not o:
        raise HTTPException(404, "Objekt nicht gefunden")
    daten = exportiere(session, o)
    sicherung = _sicherung_in_die_cloud(session, o, daten)
    name, ordner = o.name, o.nc_ordner
    entfernt = loesche(session, o)
    return {"ok": True, "name": name, "entfernt": entfernt,
            "sicherung": sicherung,
            "cloud_ordner_bleibt": ordner or None}


@router.post("/objekte/import", status_code=201)
def objekt_import(daten: dict, session: Session = Depends(get_session)) -> dict:
    """Legt aus einer Sicherung wieder ein Objekt an — immer als neuer Eintrag."""
    if not isinstance(daten.get("objekt"), dict):
        raise HTTPException(400, "Keine ImmoCalc-Sicherung: 'objekt' fehlt")
    o = importiere(session, daten, _freier_slug)
    return {"slug": o.slug, "id": o.id, "name": o.name}


@router.get("/objekte/{slug}/kostenarten")
def kostenarten(slug: str, session: Session = Depends(get_session)) -> list[Kostenart]:
    o = session.exec(select(Objekt).where(Objekt.slug == slug)).first()
    if not o:
        raise HTTPException(404, "Objekt nicht gefunden")
    return session.exec(select(Kostenart).where(Kostenart.objekt_id == o.id)).all()


@router.patch("/kostenarten/{kid}")
def kostenart_aendern(kid: int, data: dict,
                      session: Session = Depends(get_session)) -> dict:
    """Ändert eine Kostenart — und zieht einen neuen Namen in den Positionen
    nach.

    Zwei Dinge hängen daran, die ohne diesen Weg nicht zu erreichen waren:

    * **umlagefähig** (CLX) entscheidet, ob eine Kostenart in der
      Mieterabrechnung landet oder beim Eigentümer bleibt. Das Feld stand im
      Modell, war aber nirgends änderbar — damit galt faktisch alles als
      umlagefähig und die ganze Trennung war eine Behauptung.
    * **Der Name** (CXC) verbindet `Kostenposition.kostenart` mit dem Katalog.
      Er ist Freitext, kein Fremdschlüssel; wird er nur hier geändert, zeigen
      die Positionen auf einen Namen, den es nicht mehr gibt. Deshalb wandern
      sie mit — so wie `Miete.einheit` beim Umbenennen einer Einheit.

    Gelöscht wird eine Kostenart nicht: der Katalog kennt dafür `aktiv=False`.
    Eine gelöschte Art nähme die Geschichte ihrer Positionen mit.
    """
    k = session.get(Kostenart, kid)
    if not k:
        raise HTTPException(404, "Kostenart nicht gefunden")
    erlaubt = {"name", "aktiv", "umlagefaehig", "s35", "beleg_monat",
               "erinnerung_tage", "lieferant", "kundennummer", "turnus",
               "schluessel", "notiz"}
    felder = bereinige(Kostenart, {a: b for a, b in data.items() if a in erlaubt})

    alt = k.name
    if "name" in felder:
        neu = (felder["name"] or "").strip()
        if not neu:
            raise HTTPException(400, "Die Kostenart braucht einen Namen")
        doppelt = session.exec(select(Kostenart).where(
            Kostenart.objekt_id == k.objekt_id, Kostenart.name == neu)).all()
        if any(a.id != k.id for a in doppelt):
            raise HTTPException(
                409, f"„{neu}“ gibt es an dieser Immobilie schon")
        felder["name"] = neu

    geprueft = Kostenart.model_validate({**k.model_dump(), **felder})
    for feld in felder:
        setattr(k, feld, getattr(geprueft, feld))
    session.add(k)

    nachgezogen = 0
    if k.name != alt:
        zids = [z.id for z in session.exec(
            select(Zeitraum).where(Zeitraum.objekt_id == k.objekt_id)).all()]
        if zids:
            for p in session.exec(select(Kostenposition).where(
                    Kostenposition.zeitraum_id.in_(zids),
                    Kostenposition.kostenart == alt)).all():
                p.kostenart = k.name
                session.add(p)
                nachgezogen += 1
        for d in session.exec(select(Dokument).where(
                Dokument.objekt_id == k.objekt_id,
                Dokument.kostenart == alt)).all():
            d.kostenart = k.name
            session.add(d)
    session.commit()
    return {"ok": True, "name": k.name, "umlagefaehig": k.umlagefaehig,
            "positionen_nachgezogen": nachgezogen}


# --------------------------------------------------------------------------
# Einheiten — die Wohnungen, Büros und Stellplätze eines Hauses
#
# `Miete.einheit` verweist über die Bezeichnung hierher, nicht über eine id.
# Deshalb ist die Bezeichnung je Objekt eindeutig und wird beim Umbenennen in
# den Mietverhältnissen mitgezogen: sonst zeigte die Miete ins Leere, und die
# Partei fiele stumm aus der Kostenverteilung (Fund XCII).
# --------------------------------------------------------------------------

class EinheitNeu(BaseModel):
    """Was eine Einheit ausmacht. Nur die Bezeichnung ist Pflicht — Flächen und
    Stellplätze trägt man oft erst nach, wenn der Grundriss vorliegt."""
    bezeichnung: str
    nutzungsart: str = "Wohnen"
    flaeche: Optional[float] = None
    terrasse: Optional[float] = None
    nebenflaeche: Optional[float] = None
    # Optional, obwohl das Modell eine Zahl erwartet: ein leer gelassenes Feld
    # kommt aus dem Formular als null und darf das Anlegen nicht scheitern lassen.
    stellplaetze: Optional[int] = 0
    # CLXXXVI: ein Verkehrswert je Einheit — nur gepflegt, wo er bekannt ist.
    verkehrswert: Optional[float] = None
    # CCCXXVII: Gemeinschaftsflächen [{bezeichnung, flaeche, personen}, …].
    gemeinflaechen: Optional[list] = None
    # CCCXXIX: zusätzliche Nutzflächen [{bezeichnung, flaeche}, …] — voll gezählt.
    nutzflaechen: Optional[list] = None
    # CCCXXXIII: €/m²-Ansätze je Flächenart — Grundlage der hergeleiteten
    # Kaltmiete (Vorschlag im Miet-Formular). Alle optional/None.
    miete_qm_wohn: Optional[float] = None
    miete_qm_neben: Optional[float] = None
    miete_qm_gemein: Optional[float] = None


def _einheit(session: Session, eid: int) -> Einheit:
    e = session.get(Einheit, eid)
    if not e:
        raise HTTPException(404, "Einheit nicht gefunden")
    return e


def _zuordnung(m: Miete, einheiten: list[Einheit]) -> str:
    """Auf welche Einheit ein Mietverhältnis zeigt — wie in `verteilung.bezuege`:
    ohne Angabe gehört es bei einem Objekt mit genau einer Einheit zu dieser."""
    if m.einheit.strip():
        return m.einheit.strip()
    return einheiten[0].bezeichnung if len(einheiten) == 1 else ""


def _laeuft(m: Miete, heute: date) -> bool:
    """Gilt dieses Mietverhältnis heute? Ein geplanter Stand gilt noch nicht,
    ein beendeter nicht mehr."""
    return m.ab_datum <= heute and (m.bis_datum is None or m.bis_datum >= heute)


def _einheit_zeile(e: Einheit, mieten: list[Miete], einheiten: list[Einheit],
                   heute: date, lageplaene: Optional[dict] = None) -> dict:
    """Eine Einheit mit dem, was heute darin wohnt.

    `vermietet` ist die eine Auskunft, die man auf einen Blick braucht — sie
    entscheidet, ob die Blase in der Oberfläche als „frei" erscheint.

    `lageplaene` ist die vorab gebündelte Zuordnung Einheit-ID → Lagepläne
    (CCCXXVI); ohne sie bleibt die Liste leer, damit die Zeile auch ohne diese
    Vorarbeit funktioniert."""
    eigene = [m for m in mieten if _zuordnung(m, einheiten) == e.bezeichnung]
    laufend = [m for m in eigene if _laeuft(m, heute)]
    return {
        **e.model_dump(),
        # CCCXXVII — die Gemeinschaftsflächen als Liste (nicht als roher JSON-
        # Text) und der daraus errechnete anteilige Flächenbeitrag.
        "gemeinflaechen": _gemeinflaechen_liste(e),
        "gemein_flaeche": e.gemein_flaeche(),
        # CCCXXIX — die zusätzlichen Nutzflächen als Liste und ihr voller
        # Flächenbeitrag.
        "nutzflaechen": _nutzflaechen_liste(e),
        "nutz_flaeche": e.nutz_flaeche(),
        "vermietet": bool(laufend),
        "mieter": ", ".join(sorted({m.partei for m in laufend if m.partei})),
        # CCCLXXVIII b — auf den Monatsbetrag normalisieren (Turnus heraus-
        # rechnen); die Einheit zeigt „… €/M" und leitet daraus €/m² ab, sonst
        # verdreifachte eine vierteljährliche Miete den Quadratmeterpreis.
        "kaltmiete": round(sum(jahresbetrag(m.kaltmiete, m.turnus) / 12
                               for m in laufend), 2),
        "mietverhaeltnisse": len(eigene),
        # CCCXXVI — die hinterlegten Lagepläne dieser Einheit als
        # [{id, dateiname}]. Defensiv (leer, wenn keine); die Vorschau läuft
        # über die bestehenden Dokument-Endpunkte.
        "lageplaene": (lageplaene or {}).get(e.id, []),
    }


def _lageplaene_je_einheit(session: Session, einheit_ids: list[int]) -> dict:
    """CCCXXVI — die Lagepläne aller genannten Einheiten in einer Abfrage,
    nach Einheit-ID gebündelt. Ein Lageplan ist ein `Dokument` mit
    `kategorie="Lageplan"`, das über `info_zu_*` an der Einheit hängt — dieselbe
    Definition wie im Listen-Endpunkt in `dokumente.py`."""
    if not einheit_ids:
        return {}
    treffer = session.exec(select(Dokument).where(
        Dokument.kategorie == "Lageplan",
        Dokument.info_zu_typ == "einheit",
        Dokument.info_zu_id.in_(einheit_ids))).all()
    eimer: dict[int, list] = {}
    for d in treffer:
        eimer.setdefault(d.info_zu_id, []).append(
            {"id": d.id, "dateiname": d.dateiname})
    return eimer


def _gemeinflaechen_liste(e: Einheit) -> list:
    """Die Gemeinschaftsflächen einer Einheit als Liste — leer bei kaputtem
    oder fehlendem JSON, damit die Oberfläche nie über einen String stolpert."""
    try:
        wert = json.loads(e.gemeinflaechen or "[]")
        return wert if isinstance(wert, list) else []
    except (ValueError, TypeError):
        return []


def _gemein_bereinigt(posten: list) -> list:
    """Nur die drei Felder je Gemeinschaftsfläche, sauber getypt. Zeilen ohne
    Fläche werden verworfen — eine leere Zeile aus dem Formular ist kein Posten."""
    sauber = []
    for p in posten:
        if not isinstance(p, dict):
            continue
        try:
            flaeche = float(p.get("flaeche") or 0)
            personen = int(float(p.get("personen") or 0))
        except (ValueError, TypeError):
            continue
        if flaeche <= 0:
            continue
        sauber.append({"bezeichnung": str(p.get("bezeichnung") or "").strip(),
                       "flaeche": flaeche, "personen": max(personen, 0)})
    return sauber


def _nutzflaechen_liste(e: Einheit) -> list:
    """CCCXXIX — die zusätzlichen Nutzflächen einer Einheit als Liste — leer
    bei kaputtem oder fehlendem JSON, damit die Oberfläche nie über einen
    String stolpert."""
    try:
        wert = json.loads(e.nutzflaechen or "[]")
        return wert if isinstance(wert, list) else []
    except (ValueError, TypeError):
        return []


def _nutz_bereinigt(posten: list) -> list:
    """CCCXXIX — nur {bezeichnung, flaeche} je Nutzfläche, sauber getypt. Zeilen
    ohne Fläche werden verworfen — eine leere Zeile aus dem Formular ist kein
    Posten. Personen gibt es hier nicht: die Nutzfläche zählt voll."""
    sauber = []
    for p in posten:
        if not isinstance(p, dict):
            continue
        try:
            flaeche = float(p.get("flaeche") or 0)
        except (ValueError, TypeError):
            continue
        if flaeche <= 0:
            continue
        sauber.append({"bezeichnung": str(p.get("bezeichnung") or "").strip(),
                       "flaeche": flaeche})
    return sauber


@router.get("/objekte/{slug}/einheiten")
def einheiten_liste(slug: str,
                    session: Session = Depends(get_session),
                    o: Objekt = Depends(objekt_holen)) -> list[dict]:
    """Die Einheiten eines Objekts, jede mit ihrem heutigen Mieter."""
    einheiten = list(session.exec(
        select(Einheit).where(Einheit.objekt_id == o.id)).all())
    mieten = list(session.exec(select(Miete).where(Miete.objekt_id == o.id)).all())
    heute = date.today()
    lageplaene = _lageplaene_je_einheit(
        session, [e.id for e in einheiten if e.id is not None])
    return [_einheit_zeile(e, mieten, einheiten, heute, lageplaene)
            for e in einheiten]


def _bezeichnung_frei(session: Session, objekt_id: int, bezeichnung: str,
                      ausser: Optional[int] = None) -> None:
    """Zwei gleichnamige Einheiten wären nicht auseinanderzuhalten — weder für
    den Nutzer noch für `Miete.einheit`."""
    for e in session.exec(select(Einheit).where(Einheit.objekt_id == objekt_id)).all():
        if e.id != ausser and e.bezeichnung.strip().casefold() == bezeichnung.casefold():
            raise HTTPException(409, f"„{bezeichnung}“ gibt es in diesem Objekt "
                                     f"schon. Wähle eine andere Bezeichnung.")


@router.post("/objekte/{slug}/einheiten", status_code=201)
def einheit_anlegen(slug: str, data: EinheitNeu,
                    session: Session = Depends(get_session),
                    o: Objekt = Depends(objekt_holen)) -> dict:
    if ist_grundstueck(o):
        raise HTTPException(400, "Ein Grundstück hat keine Einheiten — "
                                 "Fläche und Nutzungsart stehen am Objekt.")
    bezeichnung = data.bezeichnung.strip()
    if not bezeichnung:
        raise HTTPException(400, "Die Einheit braucht eine Bezeichnung")
    _bezeichnung_frei(session, o.id, bezeichnung)
    e = Einheit(objekt_id=o.id, bezeichnung=bezeichnung,
                nutzungsart=data.nutzungsart.strip() or "Wohnen",
                flaeche=data.flaeche, terrasse=data.terrasse,
                nebenflaeche=data.nebenflaeche,
                stellplaetze=data.stellplaetze or 0,
                verkehrswert=data.verkehrswert,
                gemeinflaechen=json.dumps(_gemein_bereinigt(data.gemeinflaechen or []),
                                          ensure_ascii=False),
                nutzflaechen=json.dumps(_nutz_bereinigt(data.nutzflaechen or []),
                                        ensure_ascii=False),
                # CCCXXXIII — €/m²-Ansätze je Flächenart (optional).
                miete_qm_wohn=data.miete_qm_wohn,
                miete_qm_neben=data.miete_qm_neben,
                miete_qm_gemein=data.miete_qm_gemein)
    session.add(e)
    session.commit()
    session.refresh(e)
    return {"id": e.id, "bezeichnung": e.bezeichnung}


@router.patch("/einheiten/{eid}")
def einheit_aendern(eid: int, data: dict,
                    session: Session = Depends(get_session)) -> dict:
    """Ändert eine Einheit — und zieht eine neue Bezeichnung in den
    Mietverhältnissen nach.

    Ohne das Nachziehen zeigte `Miete.einheit` nach dem Umbenennen auf eine
    Einheit, die es nicht mehr gibt: die Partei bekäme keine Kosten mehr und
    ihre Vorauszahlung voll erstattet, ohne dass es irgendwo auffiele."""
    e = _einheit(session, eid)
    erlaubt = {"bezeichnung", "nutzungsart", "flaeche", "terrasse",
               "nebenflaeche", "stellplaetze", "nk_abrechnung", "verkehrswert",
               "gemeinflaechen", "nutzflaechen",
               # CCCXXXIII — €/m²-Ansätze je Flächenart
               "miete_qm_wohn", "miete_qm_neben", "miete_qm_gemein"}
    daten = dict(data)
    # CCCXXVII — die Gemeinschaftsflächen kommen als Liste und werden als JSON
    # gespeichert (das Modell hält eine Zeichenkette).
    if isinstance(daten.get("gemeinflaechen"), list):
        daten["gemeinflaechen"] = json.dumps(_gemein_bereinigt(daten["gemeinflaechen"]),
                                             ensure_ascii=False)
    # CCCXXIX — dasselbe für die zusätzlichen Nutzflächen.
    if isinstance(daten.get("nutzflaechen"), list):
        daten["nutzflaechen"] = json.dumps(_nutz_bereinigt(daten["nutzflaechen"]),
                                           ensure_ascii=False)
    felder = bereinige(Einheit, {k: v for k, v in daten.items() if k in erlaubt})
    if "bezeichnung" in felder:
        neu = (felder["bezeichnung"] or "").strip()
        if not neu:
            raise HTTPException(400, "Die Einheit braucht eine Bezeichnung")
        _bezeichnung_frei(session, e.objekt_id, neu, ausser=e.id)
        felder["bezeichnung"] = neu
    alt = e.bezeichnung
    geprueft = Einheit.model_validate({**e.model_dump(), **felder})
    for k in felder:
        setattr(e, k, getattr(geprueft, k))
    session.add(e)

    umbenannt = 0
    if e.bezeichnung != alt:
        for m in session.exec(select(Miete).where(Miete.objekt_id == e.objekt_id,
                                                  Miete.einheit == alt)).all():
            m.einheit = e.bezeichnung
            session.add(m)
            umbenannt += 1
    session.commit()
    return {"ok": True, "bezeichnung": e.bezeichnung, "mieten_umbenannt": umbenannt}


@router.delete("/einheiten/{eid}")
def einheit_loeschen(eid: int, session: Session = Depends(get_session)) -> dict:
    """Entfernt eine Einheit — aber nur, solange nichts daran hängt.

    Ein Mietverhältnis ohne Einheit ist genau der stille Fehler aus XCII.
    Deshalb wird hier lieber abgewiesen und gesagt, wer im Weg steht."""
    e = _einheit(session, eid)
    einheiten = list(session.exec(
        select(Einheit).where(Einheit.objekt_id == e.objekt_id)).all())
    mieten = [m for m in session.exec(
        select(Miete).where(Miete.objekt_id == e.objekt_id)).all()
        if _zuordnung(m, einheiten) == e.bezeichnung]
    if mieten:
        namen = sorted({m.partei for m in mieten if m.partei})
        eins = len(mieten) == 1
        raise HTTPException(
            409, f"An „{e.bezeichnung}“ "
                 + ("hängt noch ein Mietverhältnis" if eins
                    else f"hängen noch {len(mieten)} Mietverhältnisse")
                 + (f" ({', '.join(namen)})" if namen else "")
                 + ". Entferne " + ("es" if eins else "sie")
                 + " zuerst — sonst gehört die Miete zu keiner Einheit mehr.")
    bezeichnung = e.bezeichnung
    session.delete(e)
    session.commit()
    return {"ok": True, "bezeichnung": bezeichnung}


@router.get("/erinnerungen")
def erinnerungen(session: Session = Depends(get_session)) -> dict:
    """Was ansteht: Abrechnungsfristen und erwartete Jahresabrechnungen.
    Grundlage für Benachrichtigungen."""
    heute = date.today()
    offen = []
    for o in session.exec(select(Objekt)).all():
        # Ein Grundstück rechnet mit niemandem ab — weder eine Frist nach
        # § 556 BGB noch ein erwarteter Versorgerbeleg ergibt dort einen Sinn.
        # Bestandsgrundstücke haben noch einen Zeitraum aus früheren Anlagen.
        if not o.aktiv or ist_grundstueck(o):
            continue
        for z in session.exec(select(Zeitraum).where(Zeitraum.objekt_id == o.id)).all():
            if z.status != "in Arbeit":
                continue
            label = f"{z.start:%d.%m.%Y} – {z.ende:%d.%m.%Y}"
            hinweis = frist_erinnerung(label, frist_tage(z),
                                       zeitraum_beendet=z.ende <= heute)
            if in_sicht(hinweis):
                offen.append({"objekt": o.slug, "name": o.name, **hinweis})

            vorhanden = {p.kostenart for p in session.exec(
                select(Kostenposition).where(
                    Kostenposition.zeitraum_id == z.id)).all()
                if p.status == "erledigt"}
            for k in session.exec(
                    select(Kostenart).where(Kostenart.objekt_id == o.id)).all():
                if not k.aktiv:
                    continue
                hinweis = beleg_erinnerung(k.name, k.beleg_monat, k.erinnerung_tage,
                                           k.name in vorhanden, heute)
                if in_sicht(hinweis):
                    offen.append({"objekt": o.slug, "name": o.name, **hinweis})

    offen.sort(key=lambda e: (not e["faellig"], e["tage"]))
    return {"heute": heute.isoformat(),
            "faellig": sum(1 for e in offen if e["faellig"]),
            "erinnerungen": offen}


@router.get("/zeitraeume/{zid}/positionen")
def positionen(zid: int, session: Session = Depends(get_session)) -> list[Kostenposition]:
    return session.exec(
        select(Kostenposition).where(Kostenposition.zeitraum_id == zid)).all()


@router.get("/zeitraeume/{zid}")
def zeitraum(zid: int, session: Session = Depends(get_session)) -> dict:
    """Checkliste eines Abrechnungszeitraums: was liegt vor, was fehlt.

    Jede aktive Kostenart des Objekts ist eine Zeile. Ohne Position gilt sie
    als offen — so sieht man auch, was noch gar nicht erfasst wurde."""
    z = session.get(Zeitraum, zid)
    if not z:
        raise HTTPException(404, "Zeitraum nicht gefunden")
    o = session.get(Objekt, z.objekt_id)

    positionen = session.exec(
        select(Kostenposition).where(Kostenposition.zeitraum_id == zid)).all()
    arten = session.exec(select(Kostenart).where(Kostenart.objekt_id == o.id)).all()
    dokumente = session.exec(
        select(Dokument).where(Dokument.zeitraum_id == zid)).all()
    vzs = session.exec(select(Vorauszahlung).where(Vorauszahlung.zeitraum_id == zid)).all()
    # CCCLVII — Einheiten, Mieten und Bewohner, um den Kostenfluss-Sankey rechts
    # strikt auf Einheiten zu aggregieren (nie Partei- oder Bewohnernamen, wie
    # beim Nebenkosten-Sankey). Bewohner tragen die Schlüssel bei „bewohner-
    # monate"; auch sie zählen über ihre Miete zu einer Einheit.
    einheiten = session.exec(select(Einheit).where(Einheit.objekt_id == o.id)).all()
    mieten = session.exec(select(Miete).where(Miete.objekt_id == o.id)).all()
    _mieten_ids = [m.id for m in mieten]
    bewohner = (session.exec(select(Bewohner).where(Bewohner.miete_id.in_(_mieten_ids))).all()
                if _mieten_ids else [])

    nach_art = {p.kostenart: p for p in positionen}
    # CLXXXIII: der Rückweg. Welche Belege in eine Position eingerechnet sind,
    # steht an ihnen selbst (`Dokument.position_id`) — nicht am Dateinamen und
    # nicht an der Kostenart, die sich umbenennen liesse.
    beleg_map = belege_je_position(session, list(positionen))

    def _verteilung(p: Optional[Kostenposition]) -> dict:
        """Wie die Position verteilt wird — und ob sie das überhaupt tut.

        `ohne_verteilung` ist der ehrliche Hinweis: eine erledigte Position
        ohne Gewichte fällt aus der Abrechnung heraus, ohne dass es jemand
        merkt. Die Zeile sieht fertig aus, ihr Betrag taucht aber nirgends
        wieder auf."""
        anteile = (p.anteile or {}) if p else {}
        meta = SCHLUESSEL.get((p.schluessel if p else "") or "", {})
        return {
            "anteile": anteile,
            "anteile_einheit": meta.get("einheit", ""),
            "anteile_summe": round(sum(anteile.values()), 4),
            # CCCLIX — Vorab-Anteil direkt auf eine Einheit (für Anzeige + Sankey)
            "vorab_betrag": round(p.vorab_betrag or 0, 2) if p else 0,
            "vorab_einheit": (p.vorab_einheit if p else "") or "",
            "vorab_s35": bool(p and p.vorab_s35),
            "vorab_netto": round(p.vorab_netto or 0, 2) if p else 0,
            "ohne_verteilung": bool(
                p and p.status == "erledigt" and (p.betrag or 0) != 0
                and sum(anteile.values()) <= 0),
        }

    belege = {}
    for d in dokumente:
        belege.setdefault(d.kategorie or "", []).append(
            {"id": d.id, "dateiname": d.dateiname, "pfad": d.pfad})

    def _zusammensetzung(p: Optional[Kostenposition]) -> dict:
        """Woraus der Betrag besteht — und welche Belege dahinterstehen.

        Vier Abschlagsrechnungen ergeben eine Position (CLXXXII); ohne diese
        Aufschlüsselung stünde dort nur eine Summe, die niemand mehr auf ihre
        Belege zurückführen kann."""
        eigene = beleg_map.get(p.id, []) if p else []
        return {
            "belege": [kurz(d) for d in eigene],
            "beleg_summe": round((p.beleg_summe or 0.0) if p else 0.0, 2),
            "handanteil": handanteil(p) if p else 0.0,
        }

    checkliste = []
    for k in arten:
        if not k.aktiv:
            continue
        p = nach_art.get(k.name)
        erledigt = bool(p and p.status == "erledigt")
        checkliste.append({
            "kostenart": k.name, "s35": k.s35 or (p.s35 if p else False),
            "erledigt": erledigt,
            "betrag": p.betrag if p else None,
            "schluessel": p.schluessel if p else None,
            "nur_einheit": p.nur_einheit if p else "",
            "wertquelle": p.wertquelle if p else None,
            **_verteilung(p),
            **_zusammensetzung(p),
            "position_id": p.id if p else None,
            # CCLXXVIII: eine vorläufige (orange) Position wartet auf Bestätigung.
            "vorlaeufig": bool(p and p.vorlaeufig),
            "quelle_dokument_id": p.quelle_dokument_id if p else None,
            "beleg_monat": k.beleg_monat,
            # CCCLXIII — Anbieter/Gewerk der Kostenart (z. B. WWK, Zweckverband),
            # für den Tag in der Zeitraum-Zeile. Feld `lieferant` gibt es schon.
            # Die Kostenart-ID, damit sich der Anbieter dort setzen lässt.
            "anbieter": k.lieferant or "", "kostenart_id": k.id,
            "zustand": "erledigt" if erledigt else ("offen" if p else "fehlt"),
        })
    # Positionen zu Kostenarten, die nicht im Katalog stehen, gehen sonst verloren.
    # CCCXCVI — ausgeblendete (inaktive) Kostenarten bleiben aber ausgeblendet,
    # auch wenn sie schon eine Position tragen (sonst käme die Zeile als Waise zurück).
    inaktiv = {k.name for k in arten if not k.aktiv}
    sichtbar = {k["kostenart"] for k in checkliste}
    for p in positionen:
        if p.kostenart in sichtbar or p.kostenart in inaktiv:
            continue
        checkliste.append({
            "kostenart": p.kostenart, "s35": p.s35,
            "erledigt": p.status == "erledigt", "betrag": p.betrag,
            "schluessel": p.schluessel, "nur_einheit": p.nur_einheit,
            "wertquelle": p.wertquelle,
            **_verteilung(p),
            **_zusammensetzung(p),
            "position_id": p.id,
            # CCLXXVIII: eine vorläufige (orange) Position wartet auf Bestätigung.
            "vorlaeufig": bool(p.vorlaeufig),
            "quelle_dokument_id": p.quelle_dokument_id,
            "beleg_monat": None,
            "zustand": "erledigt" if p.status == "erledigt" else "offen",
        })

    fertig = sum(1 for k in checkliste if k["erledigt"])
    # Fluss fuer das Diagramm: erledigte Kostenarten -> Abrechnung -> Parteien
    summe_erledigt = sum(k["betrag"] or 0 for k in checkliste if k["erledigt"])
    knoten = [{"name": "Abrechnung", "spalte": 1}]
    fluss = []
    for k in sorted((k for k in checkliste if k["erledigt"] and (k["betrag"] or 0) > 0),
                    key=lambda k: -(k["betrag"] or 0)):
        knoten.append({"name": k["kostenart"], "spalte": 0})
        fluss.append({"von": len(knoten) - 1, "nach": 0, "wert": round(k["betrag"], 2)})
    if summe_erledigt > 0:
        # CCCLVII — rechts stehen nur Einheiten, nie Partei- oder Bewohnernamen.
        # Jede Partei (Miete) und jeder Bewohner zählt über seine Miete zu einer
        # Einheit; ein Schlüssel, der schon ein Einheitsname ist (leerstehende
        # Einheit), bleibt; alles Unzuordenbare sammelt sich unter „Ohne Einheit"
        # (dieselbe Regel wie CCCXLI). So erscheint keine Einheit doppelt als
        # Einheit UND als Partei und kein Personenname als eigener Empfänger.
        einheit_kanon = {e.bezeichnung.strip().lower(): e.bezeichnung
                         for e in einheiten if (e.bezeichnung or "").strip()}

        def _miete_einheit(m) -> str:
            return (einheit_kanon.get((m.einheit or "").strip().lower())
                    or (m.einheit.strip() if (m.einheit or "").strip() else "Ohne Einheit"))

        partei_zu_einheit = {m.partei.strip(): _miete_einheit(m)
                             for m in mieten if (m.partei or "").strip()}
        miete_einheit = {m.id: _miete_einheit(m) for m in mieten}
        bewohner_zu_einheit = {b.name.strip(): miete_einheit.get(b.miete_id, "Ohne Einheit")
                               for b in bewohner if (b.name or "").strip()}

        def zu_einheit(schluessel: str) -> str:
            p = (schluessel or "").strip()
            if p in partei_zu_einheit:
                return partei_zu_einheit[p]
            if p in bewohner_zu_einheit:
                return bewohner_zu_einheit[p]
            if p.lower() in einheit_kanon:
                return einheit_kanon[p.lower()]
            return "Ohne Einheit"

        gewichte = {}
        for k in checkliste:
            if not k["erledigt"]:
                continue
            # CCCLIX — ein Vorab-Anteil geht direkt auf seine Einheit; nur der
            # Rest (Betrag − Vorab) wird über den Schlüssel verteilt.
            vorab = k.get("vorab_betrag") or 0
            veinheit = (k.get("vorab_einheit") or "").strip()
            if vorab > 0 and veinheit:
                ziel = zu_einheit(veinheit)
                gewichte[ziel] = gewichte.get(ziel, 0.0) + vorab
            rest = (k["betrag"] or 0) - (vorab if veinheit else 0)
            gesamt_anteil = sum(k["anteile"].values()) or 1
            for partei, anteil in (k["anteile"] or {}).items():
                ziel = zu_einheit(partei)
                gewichte[ziel] = gewichte.get(ziel, 0.0) + \
                    rest * anteil / gesamt_anteil
        for ziel, betrag in sorted(gewichte.items(), key=lambda p: -p[1]):
            knoten.append({"name": ziel, "spalte": 2})
            fluss.append({"von": 0, "nach": len(knoten) - 1, "wert": round(betrag, 2)})

    return {
        "id": z.id, "objekt": o.slug, "objekt_name": o.name,
        # CCVIII: ist das Objekt Teil einer WEG, verteilt die Hausverwaltung —
        # die Abrechnungsseite bietet dann den Mieter-Direkteintrag an, statt
        # selbst über einen Schlüssel zu verteilen.
        "weg": bool(o.weg),
        "label": f"{z.start:%d.%m.%Y} – {z.ende:%d.%m.%Y}",
        "start": z.start.isoformat(), "ende": z.ende.isoformat(),
        "typ": z.typ, "status": z.status,
        "frist_tage": frist_tage(z) if z.status == "in Arbeit" else None,
        "fortschritt": {"fertig": fertig, "gesamt": len(checkliste),
                        "summe": round(summe_erledigt, 2)},
        # Was an diesem Zeitraum wirklich hängt. Ist alles null, gilt er als
        # leer und wird automatisch entfernt — kein Löschknopf nötig.
        "verknuepft": {"positionen": len(positionen), "belege": len(dokumente),
                       "vorauszahlungen": len(vzs)},
        "checkliste": checkliste,
        "sankey": {"knoten": knoten, "fluss": fluss},
        "dokumente": [{"id": d.id, "dateiname": d.dateiname, "pfad": d.pfad,
                       "kategorie": d.kategorie} for d in dokumente],
        "belege_je_art": belege,
        "vorauszahlungen": [{"partei": v.partei, "betrag": v.betrag} for v in vzs],
    }


def _zeitraum_grenzen(objekt: Objekt, jahr: int) -> tuple[date, date]:
    """Start und Ende eines Abrechnungsjahres aus dem Turnus des Objekts.

    Ein Zeitraum läuft ab dem `start_monat` zwölf Monate lang — bei einem
    Kalenderjahr also vom 1.1. bis 31.12., bei Start im Oktober vom 1.10. bis
    zum 30.9. des Folgejahres. Diese eine Regel gilt fürs Anlegen wie fürs
    Erkennen, damit ein vorgeschlagener Zeitraum exakt dem entspricht, der beim
    Anlegen entsteht."""
    start = date(jahr, objekt.start_monat or 1, 1)
    ende = date(start.year + 1, start.month, 1) - timedelta(days=1)
    return start, ende


def _zeitraum_jahr(objekt: Objekt, datum: date) -> int:
    """In welches Abrechnungsjahr ein Datum fällt — nach dem Startmonat.

    Vor dem Startmonat gehört ein Datum noch zum vorigen Abrechnungsjahr: bei
    Start im Oktober fällt der 15.9.2026 in das Jahr, das am 1.10.2025 begann."""
    return datum.year if datum.month >= (objekt.start_monat or 1) else datum.year - 1


@router.get("/objekte/{slug}/zeitraum-fuer")
def zeitraum_fuer(slug: str, datum: date,
                  session: Session = Depends(get_session)) -> dict:
    """Welcher Abrechnungszeitraum zu einem Beleg-Datum passt.

    Der Dokumenteneingang fragt hier für den erkannten Beleg-Tag: gibt es
    bereits einen Zeitraum, der ihn umfasst, wird der vorgeschlagen und
    vorausgewählt (`vorschlag: false`, mit `id`). Gibt es keinen, kommen die
    Grenzen des passenden Jahres zurück (`vorschlag: true`) — der Eingang bietet
    sie als „…anlegen" an und legt sie über `POST /zeitraeume` an, bevor der
    Beleg dort eingruppiert wird. Anlegen und Erkennen nutzen dieselbe
    Grenzen-Regel (`_zeitraum_grenzen`), damit beides deckungsgleich ist."""
    o = session.exec(select(Objekt).where(Objekt.slug == slug)).first()
    if not o:
        raise HTTPException(404, "Objekt nicht gefunden")

    bestehende = session.exec(
        select(Zeitraum).where(Zeitraum.objekt_id == o.id)).all()
    treffer = next((z for z in bestehende if z.start <= datum <= z.ende), None)
    if treffer:
        return {"vorschlag": False, "id": treffer.id,
                "label": f"{treffer.start:%d.%m.%Y} – {treffer.ende:%d.%m.%Y}",
                "start": treffer.start.isoformat(), "ende": treffer.ende.isoformat()}

    jahr = _zeitraum_jahr(o, datum)
    start, ende = _zeitraum_grenzen(o, jahr)
    return {"vorschlag": True, "id": None, "jahr": jahr,
            "label": f"{start:%d.%m.%Y} – {ende:%d.%m.%Y}",
            "start": start.isoformat(), "ende": ende.isoformat()}


class ZeitraumIn(BaseModel):
    """Ein Jahr genügt — Start und Ende ergeben sich aus dem Turnus des Objekts.
    Wer abweichende Grenzen braucht, gibt sie direkt an."""
    jahr: Optional[int] = None
    start: Optional[date] = None
    ende: Optional[date] = None
    typ: str = "regulär"


@router.post("/objekte/{slug}/zeitraeume", status_code=201)
def zeitraum_anlegen(slug: str, data: ZeitraumIn,
                     session: Session = Depends(get_session)) -> dict:
    """Legt einen weiteren Abrechnungszeitraum an — typisch ein Vorjahr.

    Die Kostenarten stehen am Objekt, nicht am Zeitraum; die Checkliste des
    neuen Zeitraums ist damit sofort vollständig. Übernommen werden zusätzlich
    die Vorauszahlungen des Vorgängers, denn die ändern sich selten."""
    o = session.exec(select(Objekt).where(Objekt.slug == slug)).first()
    if not o:
        raise HTTPException(404, "Objekt nicht gefunden")

    if data.start and data.ende:
        start, ende = data.start, data.ende
    else:
        jahr = data.jahr or (date.today().year - 1)
        start, ende = _zeitraum_grenzen(o, jahr)
    if ende <= start:
        raise HTTPException(400, "Das Ende muss nach dem Start liegen")

    bestehende = session.exec(
        select(Zeitraum).where(Zeitraum.objekt_id == o.id)).all()
    if any(z.start == start and z.ende == ende for z in bestehende):
        raise HTTPException(409, "Diesen Zeitraum gibt es bereits")

    z = Zeitraum(objekt_id=o.id, start=start, ende=ende, typ=data.typ,
                 status="in Arbeit")
    session.add(z)
    session.commit()
    session.refresh(z)

    # Vorauszahlungen vom zeitlich nächsten Vorgänger übernehmen
    vorgaenger = sorted((b for b in bestehende if b.ende <= start),
                        key=lambda b: b.ende)
    uebernommen = 0
    if vorgaenger:
        for v in session.exec(select(Vorauszahlung).where(
                Vorauszahlung.zeitraum_id == vorgaenger[-1].id)).all():
            session.add(Vorauszahlung(zeitraum_id=z.id, partei=v.partei,
                                      betrag=v.betrag))
            uebernommen += 1
        session.commit()

    arten = [k for k in session.exec(
        select(Kostenart).where(Kostenart.objekt_id == o.id)).all() if k.aktiv]
    return {"id": z.id, "label": f"{z.start:%d.%m.%Y} – {z.ende:%d.%m.%Y}",
            "kostenarten": len(arten), "vorauszahlungen": uebernommen}


def _verknuepfungen(session: Session, zid: int) -> dict[str, int]:
    """Was an einem Zeitraum hängt: Kostenpositionen, Belege, Vorauszahlungen.
    Sind alle drei null, ist der Zeitraum leer und darf verschwinden."""
    return {
        "positionen": len(session.exec(select(Kostenposition)
                          .where(Kostenposition.zeitraum_id == zid)).all()),
        "belege": len(session.exec(select(Dokument)
                          .where(Dokument.zeitraum_id == zid)).all()),
        "vorauszahlungen": len(session.exec(select(Vorauszahlung)
                          .where(Vorauszahlung.zeitraum_id == zid)).all()),
    }


def _zeitraum_leer_entfernen(session: Session, zid: int,
                             commit: bool = True) -> bool:
    """Entfernt einen Zeitraum, wenn nichts mehr an ihm hängt — der
    automatische Ersatz für einen Löschknopf. War die entfernte Position der
    letzte Inhalt, verschwindet der leere Zeitraum von selbst. Ein Zeitraum
    mit auch nur einer Verknüpfung bleibt unangetastet.

    Gibt True zurück, wenn entfernt wurde. Löscht nur additiv-sicher: ein
    leerer Zeitraum hat weder Positionen noch Belege noch Vorauszahlungen, es
    kann also nichts verwaisen. `commit=False` staged nur — für Sammel-
    Aufräumen, das am Ende einmal committet."""
    if any(_verknuepfungen(session, zid).values()):
        return False
    z = session.get(Zeitraum, zid)
    if z:
        session.delete(z)
        if commit:
            session.commit()
    return True


@router.post("/zeitraeume/aufraeumen")
def zeitraeume_aufraeumen(session: Session = Depends(get_session)) -> dict:
    """Räumt alle leeren Abrechnungszeiträume weg — objektübergreifend.

    Nach einer Bestandsrücknahme (alle Belege wieder herausgenommen) bleiben
    Zeiträume ohne jeden Inhalt zurück. Statt sie einzeln zu löschen, wischt
    dieser Aufruf sie in einem Zug. Angefasst wird nur, was komplett leer ist —
    ein Zeitraum mit Position, Beleg oder Vorauszahlung bleibt."""
    entfernt = 0
    for z in session.exec(select(Zeitraum)).all():
        if not any(_verknuepfungen(session, z.id).values()):
            session.delete(z)
            entfernt += 1
    if entfernt:
        session.commit()
    logging.info("Leere Zeiträume aufgeräumt: %d entfernt", entfernt)
    return {"entfernt": entfernt}


def _zeitraum(session: Session, zid: int) -> Zeitraum:
    z = session.get(Zeitraum, zid)
    if not z:
        raise HTTPException(404, "Zeitraum nicht gefunden")
    return z


def _gewichte(session: Session, z: Zeitraum, schluessel: str) -> dict[str, float]:
    try:
        return ableiten(session, z, schluessel)
    except UnbekannterSchluessel as fehler:
        raise HTTPException(400, str(fehler)) from fehler


@router.get("/zeitraeume/{zid}/schluessel")
def schluessel_vorschau(zid: int, session: Session = Depends(get_session)) -> dict:
    """Welche Verteilungsschlüssel für dieses Objekt taugen — und welche
    Gewichte dabei herauskämen.

    Vorschau vor der Festlegung: `moeglich` sagt, ob sich der Schlüssel aus den
    Stammdaten ergibt. `unbekannte_vorauszahlungen` deckt den stillen Fehler
    auf, bei dem eine Vorauszahlung auf einen Parteinamen lautet, den die
    Verteilung gar nicht kennt — die Engine rechnet dann an ihr vorbei."""
    z = _zeitraum(session, zid)
    bezuege = stammdaten(session, z)
    parteien = sorted({b.partei for b in bezuege})
    vzs = session.exec(
        select(Vorauszahlung).where(Vorauszahlung.zeitraum_id == zid)).all()
    return {
        "zeitraum": zid, "vorgabe": VORGABE,
        "parteien": [{"partei": b.partei, "einheit": b.einheit,
                      "flaeche": b.flaeche, "personen": b.personen}
                     for b in bezuege],
        "schluessel": vorschau(bezuege, z.start, z.ende),
        "unbekannte_vorauszahlungen": sorted(
            {v.partei for v in vzs} - set(parteien)),
    }


class PositionNeu(BaseModel):
    """Ohne `anteile` werden die Gewichte aus dem Schlüssel abgeleitet.

    `nur_einheit` (CXCIV) macht daraus einen Sonderposten: ist eine Einheit
    genannt, geht die Position zu 100 % auf diese Einheit, der Schlüssel spielt
    keine Rolle mehr."""
    kostenart: str
    betrag: float = 0.0
    schluessel: str = VORGABE
    nur_einheit: str = ""
    wertquelle: str = "manuell"
    status: Optional[str] = None
    s35: Optional[bool] = None
    anteile: Optional[dict[str, float]] = None


@router.post("/zeitraeume/{zid}/positionen", status_code=201)
def position_anlegen(zid: int, data: PositionNeu,
                     session: Session = Depends(get_session)) -> dict:
    """Legt eine Kostenposition an — mit Gewichten, nicht ohne.

    Bisher entstanden Positionen nur beiläufig (Beleg-Scan) und blieben ohne
    `anteile`; ihr Betrag fiel damit aus der Abrechnung heraus.

    Eine zweite Position derselben Kostenart bleibt abgewiesen (CLXXXII): eine
    Kostenart, eine Zeile — sonst stünde „Wasser" zweimal in der Abrechnung und
    niemand wüsste, welche der beiden gilt. Dass trotzdem vier
    Abschlagsrechnungen auf dieselbe Zeile laufen, löst der Weg über den Beleg
    (`POST /api/dokumente/{id}/position`): dort addiert sich der Betrag in die
    vorhandene Position hinein, und es bleibt nachvollziehbar, aus welchen
    Belegen die Summe entstand."""
    z = _zeitraum(session, zid)
    if not data.kostenart.strip():
        raise HTTPException(400, "Die Kostenart darf nicht leer sein")
    vorhanden = session.exec(select(Kostenposition).where(
        Kostenposition.zeitraum_id == zid)).all()
    if any(p.kostenart == data.kostenart for p in vorhanden):
        raise HTTPException(409, f"'{data.kostenart}' ist in diesem Zeitraum "
                                 f"bereits erfasst. Ein weiterer Beleg wird "
                                 f"über „Als Kostenposition übernehmen“ "
                                 f"dazugerechnet.")

    # CXCIV: ein Sonderposten trägt seine Gewichte selbst — zu 100 % auf die
    # genannte Einheit. Der Schlüssel wird nicht abgeleitet.
    anteile = data.anteile
    if data.nur_einheit and anteile is None:
        anteile = ableiten_einheit(session, z, data.nur_einheit)
    try:
        p = position_bauen(session, z, data.kostenart, betrag=data.betrag,
                           schluessel=data.schluessel,
                           wertquelle=data.wertquelle, status=data.status,
                           s35=data.s35, anteile=anteile)
    except UnbekannterSchluessel as fehler:
        raise HTTPException(400, str(fehler)) from fehler
    if data.nur_einheit:
        p.nur_einheit = data.nur_einheit
        session.add(p)
    session.commit()
    session.refresh(p)
    return {"id": p.id, "kostenart": p.kostenart, "status": p.status,
            "anteile": p.anteile, "nur_einheit": p.nur_einheit,
            "abgeleitet": data.anteile is None}


class PositionIn(BaseModel):
    betrag: Optional[float] = None
    status: Optional[str] = None
    # CCCLXII — die Position auf eine andere Kostenart umhängen (z. B. generische
    # „Versicherung" → spezifische „Gebäudeversicherung"). Freitext wie im Modell;
    # eine noch unbekannte Art wird als Katalog-Eintrag angelegt, damit sie nicht
    # als namenlose Waise dasteht.
    kostenart: Optional[str] = None
    schluessel: Optional[str] = None
    nur_einheit: Optional[str] = None
    wertquelle: Optional[str] = None
    anteile: Optional[dict[str, float]] = None
    s35: Optional[bool] = None
    # CCCLIX — Vorab-Anteil direkt auf eine Einheit (mit eigenem §35a)
    vorab_betrag: Optional[float] = None
    vorab_einheit: Optional[str] = None
    vorab_s35: Optional[bool] = None
    vorab_netto: Optional[float] = None   # CCCLX — eingegebener Netto (Anzeige)


@router.patch("/positionen/{pid}")
def position_aendern(pid: int, data: PositionIn,
                     session: Session = Depends(get_session)) -> dict:
    """Betrag nachtragen oder Zustand ändern — das Nachbearbeiten aus der App.

    Wird nur der Schlüssel umgestellt, werden die Gewichte neu abgeleitet:
    Fläche-Gewichte unter dem Schlüssel „Personen" stehen zu lassen wäre die
    unauffälligste Art, falsch abzurechnen."""
    p = session.get(Kostenposition, pid)
    if not p:
        raise HTTPException(404, "Position nicht gefunden")
    # CCCLXII — die Position auf eine andere Kostenart setzen. Nur diese eine
    # Position wandert (kein globales Umbenennen — das macht kostenart_aendern).
    if data.kostenart is not None:
        neu = data.kostenart.strip()
        if not neu:
            raise HTTPException(400, "Die Kostenart braucht einen Namen")
        if neu != p.kostenart:
            z = _zeitraum(session, p.zeitraum_id)
            # In einem Zeitraum bleibt eine Position je Kostenart die Regel
            # (CLXXXII) — sonst kollidieren zwei Zeilen auf denselben Namen.
            kollision = session.exec(select(Kostenposition).where(
                Kostenposition.zeitraum_id == p.zeitraum_id,
                Kostenposition.kostenart == neu,
                Kostenposition.id != p.id)).first()
            if kollision:
                raise HTTPException(
                    409, f"Zu „{neu}“ gibt es in diesem Zeitraum schon eine "
                         f"Position — trag den Betrag dort ein.")
            # Ist die Zielart im Katalog des Objekts noch unbekannt, wird sie
            # angelegt (additiv): so bleibt sie konfigurierbar und für kommende
            # Zeiträume wählbar, statt als namenlose Waise dazustehen.
            bekannt = session.exec(select(Kostenart).where(
                Kostenart.objekt_id == z.objekt_id,
                Kostenart.name == neu)).first()
            if not bekannt:
                session.add(Kostenart(objekt_id=z.objekt_id, name=neu,
                                      umlagefaehig=True, s35=p.s35, aktiv=True))
            p.kostenart = neu
    if data.betrag is not None:
        p.betrag = data.betrag
        # Ein eingetragener Betrag heisst: der Beleg liegt vor.
        if data.status is None and data.betrag > 0:
            p.status = "erledigt"
    if data.schluessel is not None and data.schluessel not in SCHLUESSEL:
        raise HTTPException(400, f"Unbekannter Verteilungsschlüssel "
                                 f"'{data.schluessel}'")
    umgestellt = data.schluessel is not None and data.schluessel != p.schluessel
    # CXCIV: die Einheit eines Sonderpostens wechseln — oder ihn wieder zum
    # normalen, über den Schlüssel verteilten Posten machen (leerer Wert).
    neue_einheit = (data.nur_einheit is not None
                    and data.nur_einheit != p.nur_einheit)
    for feld in ("status", "schluessel", "nur_einheit", "wertquelle", "s35",
                 "vorab_betrag", "vorab_einheit", "vorab_s35", "vorab_netto"):
        wert = getattr(data, feld)
        if wert is not None:
            setattr(p, feld, wert)
    if data.anteile is not None:
        p.anteile = data.anteile
    elif neue_einheit or umgestellt:
        z = _zeitraum(session, p.zeitraum_id)
        # Solange eine Einheit genannt ist, trägt sie zu 100 %; sonst zählt
        # wieder der Schlüssel über alle Parteien.
        p.anteile = (ableiten_einheit(session, z, p.nur_einheit)
                     if p.nur_einheit else _gewichte(session, z, p.schluessel))
    session.add(p)
    session.commit()
    return {"ok": True, "betrag": p.betrag, "status": p.status,
            "kostenart": p.kostenart,
            "schluessel": p.schluessel, "nur_einheit": p.nur_einheit,
            "anteile": p.anteile}


@router.delete("/positionen/{pid}")
def position_loeschen(pid: int, session: Session = Depends(get_session)) -> dict:
    """Entfernt eine Kostenposition — eine bewusste Nutzeraktion.

    Die Kostenart bleibt im Katalog des Objekts stehen; die Zeile taucht in der
    Checkliste danach wieder als „fehlt" auf, statt zu verschwinden.

    Belege, die auf die Position gezeigt haben, verlieren nur diese
    Verknüpfung: die Dateien bleiben in der Cloud, die Einträge bleiben am
    Zeitraum, und ein „Als Kostenposition übernehmen" legt die Zeile jederzeit
    wieder an. Ein Beleg, der auf eine gelöschte Position zeigt, wäre dagegen
    ein Verweis ins Leere."""
    p = session.get(Kostenposition, pid)
    if not p:
        raise HTTPException(404, "Position nicht gefunden")
    kostenart = p.kostenart
    zid = p.zeitraum_id
    geloest = 0
    for d in session.exec(select(Dokument)
                          .where(Dokument.position_id == pid)).all():
        d.position_id = None
        session.add(d)
        geloest += 1
    session.delete(p)
    session.commit()
    # War das die letzte Position und hängt sonst nichts mehr am Zeitraum,
    # verschwindet der leere Zeitraum von selbst — kein Löschknopf nötig.
    zeitraum_entfernt = _zeitraum_leer_entfernen(session, zid)
    return {"ok": True, "kostenart": kostenart, "belege_geloest": geloest,
            "zeitraum_entfernt": zeitraum_entfernt}


def _engine_positionen(session: Session, z: Zeitraum,
                       p: Kostenposition) -> list[Position]:
    """CCCLIX — eine Kostenposition in die zu rechnenden Engine-Positionen
    übersetzen. Trägt sie einen Vorab-Anteil direkt auf eine Einheit, entstehen
    zwei: der Vorab-Betrag zu 100 % auf diese Einheit (mit eigenem §35a) und der
    Rest (Betrag − Vorab) nach dem gewählten Schlüssel. Ohne Vorab bleibt es die
    eine Position wie bisher."""
    vorab = round(p.vorab_betrag or 0, 2)
    if vorab > 0 and (p.vorab_einheit or "").strip():
        aus = [Position(p.kostenart, vorab, "individuell",
                        ableiten_einheit(session, z, p.vorab_einheit), p.vorab_s35)]
        rest = round((p.betrag or 0) - vorab, 2)
        if rest > 0.005:
            aus.append(Position(p.kostenart, rest, p.schluessel, p.anteile or {}, p.s35))
        return aus
    return [Position(p.kostenart, p.betrag, p.schluessel, p.anteile or {}, p.s35)]


@router.get("/zeitraeume/{zid}/abrechnung")
def abrechnung_endpoint(zid: int, session: Session = Depends(get_session)) -> dict:
    z = _zeitraum(session, zid)
    pos = session.exec(select(Kostenposition).where(Kostenposition.zeitraum_id == zid)).all()
    vzs = session.exec(select(Vorauszahlung).where(Vorauszahlung.zeitraum_id == zid)).all()
    # offene Positionen (Betrag noch nicht da) fließen nicht in die Rechnung ein
    positionen = [ep for p in pos if p.status == "erledigt"
                  for ep in _engine_positionen(session, z, p)]
    # CCCLXIV — Vorauszahlungen aus der Miete ableiten (monatliche NK × belegte
    # Monate); separat erfasste Vorauszahlungs-Datensätze haben Vorrang.
    vorausz = {**vorauszahlung_je_partei(session, z),
               **{v.partei: v.betrag for v in vzs}}
    res = abrechnung(positionen, vorausz)
    # Erledigte Positionen ohne Gewichte gehören zu den offenen: ihr Betrag
    # verschwindet sonst lautlos, und der Abschluss übergeht sie.
    res.update(fehlende_angaben(list(pos)))
    return res


# --------------------------------------------------------------------------
# CCLXXVIII: Orange-Entwürfe bestätigen oder verwerfen
#
# Ein aus einem Beleg vorläufig angelegter Datensatz (`vorlaeufig=True`) ist
# orange — der Nutzer entscheidet, ob er stimmt. „Bestätigen" macht ihn zum
# regulären Datensatz; „Verwerfen" löscht ihn wieder, aber nur solange er
# vorläufig ist — ein bestätigter Datensatz wird hier nie gelöscht. Das
# Quell-Dokument bleibt in beiden Fällen unangetastet: nach dem Verwerfen steht
# der Beleg wieder im Prüfmodus und kann neu zugeordnet werden.
# --------------------------------------------------------------------------

_ENTWURF_MODELLE = {
    "kostenposition": Kostenposition,
    "miete": Miete,
    "bewohner": Bewohner,
    "versicherung": Versicherung,
    "kredit": Kredit,
    "notarvertrag": Notarvertrag,
    "zahlung": Zahlung,
}


def _entwurf(session: Session, typ: str, eintrag_id: int):
    """Der vorläufige Datensatz — mit sauberem 404 statt eines Fehlerkaskade."""
    modell = _ENTWURF_MODELLE.get((typ or "").strip().lower())
    if modell is None:
        raise HTTPException(404, f"Unbekannter Entwurfstyp „{typ}“")
    eintrag = session.get(modell, eintrag_id)
    if not eintrag:
        raise HTTPException(404, "Entwurf nicht gefunden")
    return eintrag


@router.post("/entwuerfe/{typ}/{eintrag_id}/bestaetigen")
def entwurf_bestaetigen(typ: str, eintrag_id: int,
                        session: Session = Depends(get_session)) -> dict:
    """Macht aus einem vorläufigen (orange) Datensatz einen regulären.

    Setzt nur `vorlaeufig=False` — alle übrigen Werte bleiben, wie der Beleg sie
    ergab. Ein bereits bestätigter Datensatz bleibt einfach bestätigt."""
    eintrag = _entwurf(session, typ, eintrag_id)
    eintrag.vorlaeufig = False
    session.add(eintrag)
    session.commit()
    log.info("Entwurf bestätigt: %s#%s", typ, eintrag_id)
    return {"ok": True, "typ": typ.lower(), "id": eintrag_id, "vorlaeufig": False}


@router.post("/entwuerfe/{typ}/{eintrag_id}/verwerfen")
def entwurf_verwerfen(typ: str, eintrag_id: int,
                      session: Session = Depends(get_session)) -> dict:
    """Löscht einen vorläufigen (orange) Datensatz — nur, wenn er vorläufig ist.

    Ein bestätigter Datensatz wird nie gelöscht (409). Das Quell-Dokument bleibt
    bestehen und geht damit „zurück in den Prüfmodus"."""
    eintrag = _entwurf(session, typ, eintrag_id)
    if not eintrag.vorlaeufig:
        raise HTTPException(409, "Dieser Datensatz ist bereits bestätigt und "
                                 "wird nicht gelöscht.")
    quelle = eintrag.quelle_dokument_id
    session.delete(eintrag)
    session.commit()
    log.info("Entwurf verworfen: %s#%s (Beleg %s zurück im Prüfmodus)",
             typ, eintrag_id, quelle)
    return {"ok": True, "typ": typ.lower(), "id": eintrag_id, "verworfen": True,
            "quelle_dokument_id": quelle}


# --------------------------------------------------------------------------
# CCCXXVI: Lageplan je Einheit — die Endpunkte (`/api/einheiten/{id}/lageplan`,
# `…/lageplaene`) leben in `dokumente.py`, wo die Upload-/Ablagelogik zu Hause
# ist. Ihr Router trägt nur `/einheiten`; hier wird er unter den `/api`-Router
# gehängt, damit `/api/einheiten/…` entsteht — ohne die Ablagelogik zu doppeln
# und ohne `main.py` anzufassen.
# --------------------------------------------------------------------------
from .dokumente import lageplan_router  # noqa: E402  (zirkelfrei: dokumente ist
router.include_router(lageplan_router)  # beim Laden von main.py schon importiert)
