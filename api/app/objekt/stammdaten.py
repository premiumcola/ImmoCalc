"""Objekt-CRUD: Liste, Detail, Anlegen, Ändern, Export/Import.

Hier lebt die Kernpflege der Immobilie selbst — Adresse, Modell (N213), WEG,
Kaufdaten. Das Löschen (mit Sicherung) liegt in `loeschen.py` daneben.
"""
import logging
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import Session, select

from ..bezeichnung import anzeigename, objekt_titel
from ..db import get_session
from ..export import als_datei, dateiname, exportiere, importiere
from ..felder import bereinige
from ..frist import frist_tage
from ..models import (GRUNDSTUECK, Dokument, Einheit, Kostenart,
                      Kostenposition, Miete, Objekt, Partei, PVAnlage,
                      Stromjahr, Vorauszahlung, Zeitraum, ist_grundstueck)
from ..nachpflege import hinweise, zusammenfassung
from ..turnus import jahresbetrag
from .zeitraeume import zeitraum_label_jahr

log = logging.getLogger("immocalc")
router = APIRouter(tags=["objekte"])

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


def _laeuft(m: Miete, heute: date) -> bool:
    """Gilt dieses Mietverhältnis heute? Ein geplanter Stand gilt noch nicht,
    ein beendeter nicht mehr."""
    return m.ab_datum <= heute and (m.bis_datum is None or m.bis_datum >= heute)


def _zuordnung(m: Miete, einheiten: list[Einheit]) -> str:
    """Auf welche Einheit ein Mietverhältnis zeigt — wie in `verteilung.bezuege`:
    ohne Angabe gehört es bei einem Objekt mit genau einer Einheit zu dieser."""
    if m.einheit.strip():
        return m.einheit.strip()
    return einheiten[0].bezeichnung if len(einheiten) == 1 else ""


def _laufende(mieten: list[Miete], heute: date) -> list[Miete]:
    """Die heute laufenden Mietverhältnisse aus einer Mietliste — dieselbe
    Filterung, die die Objektübersicht und die Einheiten-Detailliste beide
    brauchen (N316a: geteilt, statt an beiden Stellen einzeln nachgebaut)."""
    return [m for m in mieten if _laeuft(m, heute)]


def _ganzes_objekt_vermietet(laufend: list[Miete]) -> bool:
    """Läuft eine Miete ohne Einheitsangabe? `Miete.einheit` ist dann leer und
    meint das GANZE Objekt (siehe `models.Miete.einheit`) — dann gilt jede
    Einheit als vermietet, unabhängig davon, wem `_zuordnung` die Miete
    zuordnet (die eine solche Miete bei mehreren Einheiten bewusst KEINER
    einzelnen zuordnet, um sie nicht mehrfach als Monatsmiete auszuweisen —
    siehe `_miete_je_einheit`).

    N316a: Startseite und Einheiten-Detail bauten dieselbe Frage früher
    unabhängig und gegensätzlich nach — hier einmal, geteilt genutzt von
    `objekte()` und `einheiten._einheit_zeile`."""
    return any(not m.einheit.strip() for m in laufend)


def _monatsbetrag(m: Miete) -> float:
    """Was EIN Mietverhältnis heute im Monat einbringt: Kaltmiete, Stellplatz
    und Sonstiges zusammen, auf den Monat umgerechnet.

    Beträge stehen *je Turnus* (`models.Miete`): eine vierteljährlich gezahlte
    Pacht ist nicht das Monatsergebnis. Ohne die Umrechnung über
    `jahresbetrag` stünde in der Blase das Dreifache.

    N316a: dieselbe Summe wie die „Monatsmiete" der Startseiten-Blase — die
    Einheiten-Detailliste zeigte hier früher nur die reine Kaltmiete ohne
    Stellplatz/Sonstiges, ein zweiter, stiller Widerspruch neben `vermietet`."""
    return jahresbetrag(m.kaltmiete + m.stellplatz + m.sonstige, m.turnus) / 12


def _miete_je_einheit(mieten: list[Miete], einheiten: list[Einheit],
                      heute: date) -> dict[str, float]:
    """Was jede Einheit heute im Monat einbringt — aus den bereits geladenen
    Mietzeilen, ohne weitere Abfrage.

    Eine Miete, die keiner Einheit zuzuordnen ist (Objektmiete bei mehreren
    Einheiten), bleibt draußen — sie mehrfach voll auszuweisen wäre falsch."""
    je_einheit: dict[str, float] = {}
    for m in _laufende(mieten, heute):
        ziel = _zuordnung(m, einheiten)
        if not ziel:
            continue
        je_einheit[ziel] = je_einheit.get(ziel, 0.0) + _monatsbetrag(m)
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
    #
    # N71 — ein leerer, automatisch angelegter Zeitraum (0 Kostenpositionen)
    # ist keine echte laufende Abrechnung und darf die Kachel-Frist nicht
    # bestimmen; sonst meldet die Kachel „5420 T über Frist" aus dem ältesten
    # Rumpfjahr. Deshalb zählen nur „in Arbeit"-Zeiträume mit mindestens einer
    # Kostenposition. Bleibt keiner übrig, trägt die Kachel keine Frist.
    alle_in_arbeit = [z.id for zs in zeitraeume.values()
                      for z in zs if z.status == "in Arbeit"]
    mit_positionen: set[int] = set()
    if alle_in_arbeit:
        for zid in session.exec(
                select(Kostenposition.zeitraum_id)
                .where(Kostenposition.zeitraum_id.in_(alle_in_arbeit))
                .distinct()).all():
            mit_positionen.add(zid)

    def _naechste(zs: list) -> Zeitraum | None:
        offen = [z for z in zs
                 if z.status == "in Arbeit" and z.id in mit_positionen]
        return min(offen, key=frist_tage) if offen else None
    aktive = {oid: _naechste(zs) for oid, zs in zeitraeume.items()}
    zids = [z.id for z in aktive.values() if z is not None]
    offene: dict[int, int] = {}
    if zids:
        for p in session.exec(select(Kostenposition).where(
                Kostenposition.zeitraum_id.in_(zids))).all():
            if p.status == "offen":
                offene[p.zeitraum_id] = offene.get(p.zeitraum_id, 0) + 1

    # N87 — welche Objekte eine PV-Anlage tragen (ein Strom-Jahr mit Produktion
    # oder Anschaffung). Eine Abfrage für alle, kein N+1.
    pv_objekte = {sj.objekt_id for sj in session.exec(
        select(Stromjahr).where(Stromjahr.objekt_id.in_(ids))).all()
        if (sj.pv_produktion_kwh or 0) > 0 or (sj.anschaffung_eur or 0) > 0}
    # N139 — seit die Anschaffung in den Stammdaten der Anlage steht, darf die
    # Erkennung nicht mehr allein am Strom-Jahr haengen: eine Anlage, deren
    # Anschaffung nur dort gepflegt ist, waere sonst kein PV-Objekt mehr und
    # verschwaende von der Startseite wie aus der Auswahl der PV-Seite.
    pv_objekte |= {a.objekt_id for a in session.exec(
        select(PVAnlage).where(PVAnlage.objekt_id.in_(ids))).all()
        if (a.anschaffung_eur or 0) > 0 or (a.kwp or 0) > 0}

    out = []
    heute = date.today()
    for o in alle:
        aktiv = aktive.get(o.id)
        # CCCLXXVIII — dieselbe Definition von „läuft heute" wie in
        # `_einheit_zeile`/`_miete_je_einheit`: Einzug berücksichtigen und ein
        # befristetes, aber laufendes Mietverhältnis als vermietet zählen (nicht
        # jedes gesetzte `bis_datum` als beendet).
        laufend = _laufende(mieten[o.id], heute)
        # N316a — geteilt mit `einheiten._einheit_zeile`: eine Miete ohne
        # Einheitsangabe meint das ganze Objekt, dann gilt jede Einheit als
        # vermietet, sonst keine einzige.
        ganzes_objekt = _ganzes_objekt_vermietet(laufend)
        belegt = {m.einheit.strip() for m in laufend if m.einheit.strip()}
        je_einheit = _miete_je_einheit(mieten[o.id], einheiten[o.id], heute)
        out.append({
            "id": o.id, "slug": o.slug, "name": o.name, "ort": o.ort,
            "kuerzel": o.kuerzel,
            "anzeigename": anzeigename(o.name, o.ort, o.strasse, o.plz),
            # N70 — kanonischer Immobilientitel für die Anzeige, überall gleich.
            "titel": objekt_titel(o),
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
            # N87 — trägt das Objekt eine PV-Anlage (Add-on-Investment)? Die
            # Kachel zeigt dafür ein kleines Zeichen. Wahr, sobald für ein Jahr
            # Produktion oder eine Anschaffung erfasst ist.
            "hat_pv": o.id in pv_objekte,
            # N213 — Objektmodell (`standard` | `laufer_spezial`). Steuert im
            # Frontend, welche Laufer-spezifischen UI-Blöcke sichtbar sind.
            "modell": o.modell or "standard",
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
    # Wie viele Kostenpositionen und wie viele zugeordnete Belege hängen an jedem
    # Zeitraum? Zwei gruppierte Zählungen statt einer Abfrage je Zeitraum (kein
    # N+1). Das Frontend blendet leere Zeiträume (0 Positionen) aus und bietet
    # die mit Belegen dezent zum Öffnen an.
    zr_ids = [z.id for z in zeitraeume]
    pos_zahl: dict[int, int] = {}
    beleg_zahl: dict[int, int] = {}
    kosten_summe: dict[int, float] = {}     # erfasste NK je Zeitraum (Σ Positionsbeträge)
    abschlag_summe: dict[int, float] = {}   # eingezahlte Abschläge (Σ Vorauszahlungen)
    if zr_ids:
        for zid, n in session.exec(
                select(Kostenposition.zeitraum_id, func.count())
                .where(Kostenposition.zeitraum_id.in_(zr_ids))
                .group_by(Kostenposition.zeitraum_id)).all():
            pos_zahl[zid] = n
        for zid, n in session.exec(
                select(Dokument.zeitraum_id, func.count())
                .where(Dokument.zeitraum_id.in_(zr_ids))
                .group_by(Dokument.zeitraum_id)).all():
            beleg_zahl[zid] = n
        for zid, s in session.exec(
                select(Kostenposition.zeitraum_id, func.sum(Kostenposition.betrag))
                .where(Kostenposition.zeitraum_id.in_(zr_ids))
                .group_by(Kostenposition.zeitraum_id)).all():
            kosten_summe[zid] = round(s or 0.0, 2)
        for zid, s in session.exec(
                select(Vorauszahlung.zeitraum_id, func.sum(Vorauszahlung.betrag))
                .where(Vorauszahlung.zeitraum_id.in_(zr_ids))
                .group_by(Vorauszahlung.zeitraum_id)).all():
            abschlag_summe[zid] = round(s or 0.0, 2)
    return {
        # N70 — kanonischer Titel additiv im Objekt; `name` bleibt unangetastet.
        "objekt": {**o.model_dump(), "titel": objekt_titel(o)},
        "einheiten": einheiten, "parteien": parteien,
        # Aus den Einheiten summiert — die maßgebliche Wohnfläche und die
        # Stellplätze des Objekts. Single Source of Truth fürs Frontend: die
        # manuelle Objektfläche (o.flaeche) wird nur noch als mögliche
        # Abweichung dagegen geprüft, nicht mehr als primäre Angabe geführt.
        "wohnflaeche_summe": round(sum(e.flaeche or 0 for e in einheiten), 2),
        "stellplaetze_summe": sum(e.stellplaetze or 0 for e in einheiten),
        "einheiten_mit_flaeche": sum(1 for e in einheiten if e.flaeche),
        "nachpflege": {**zusammenfassung(offen), "offen": offen},
        "zeitraeume": [{"id": z.id, "label": f"{z.start:%d.%m.%Y} – {z.ende:%d.%m.%Y}",
                        "jahr": zeitraum_label_jahr(z.start, z.ende),   # N34
                        "typ": z.typ, "status": z.status,
                        # N35 — ISO-Grenzen fürs Umstellen-Werkzeug (Datumsfelder)
                        "start": z.start.isoformat(), "ende": z.ende.isoformat(),
                        # Additiv (N…): Anzahl Kostenpositionen bzw. zugeordneter
                        # Belege. Das Frontend blendet leere Zeiträume aus, außer
                        # dem laufenden, und bietet belegbehaftete dezent an.
                        "positionen": pos_zahl.get(z.id, 0),
                        "belege": beleg_zahl.get(z.id, 0),
                        # N49 — erfasste NK (Σ Positionen) und eingezahlte
                        # Abschläge (Σ Vorauszahlungen), damit man je Zeitraum den
                        # Stand + über-/unterlaufen sieht.
                        "kosten_summe": kosten_summe.get(z.id, 0.0),
                        "abschlag_summe": abschlag_summe.get(z.id, 0.0),
                        # N71 — leere Zeiträume (0 Positionen) tragen keine Frist.
                        "frist_tage": (frist_tage(z) if z.status == "in Arbeit"
                                       and pos_zahl.get(z.id, 0) else None)}
                       for z in zeitraeume],
    }


@router.patch("/objekte/{slug}")
def objekt_aendern(slug: str, data: dict, session: Session = Depends(get_session)) -> dict:
    o = session.exec(select(Objekt).where(Objekt.slug == slug)).first()
    if not o:
        raise HTTPException(404, "Objekt nicht gefunden")
    erlaubt = {"name", "kuerzel", "ort", "strasse", "plz", "typ", "nutzung", "turnus",
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
               "niessbrauch_aktiv", "niessbrauch_berechtigt", "niessbrauch_bis",
               # N213 — Objektmodell (`standard` | `laufer_spezial`)
               "modell"}
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
        from ..routers.cloud import ordner_fuer         # zirkelfrei zur Laufzeit
        war_name = ordner_fuer(session, o)              # aus den alten Stammdaten

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
        from ..routers.cloud import ordner_nachziehen  # zirkelfrei zur Laufzeit
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


@router.post("/objekte/import", status_code=201)
def objekt_import(daten: dict, session: Session = Depends(get_session)) -> dict:
    """Legt aus einer Sicherung wieder ein Objekt an — immer als neuer Eintrag."""
    if not isinstance(daten.get("objekt"), dict):
        raise HTTPException(400, "Keine ImmoCalc-Sicherung: 'objekt' fehlt")
    o = importiere(session, daten, _freier_slug)
    return {"slug": o.slug, "id": o.id, "name": o.name}
