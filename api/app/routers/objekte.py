"""Objekte, Zeiträume, Positionen, Abrechnung."""
import logging
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlmodel import Session, select

from ..belegposten import (belege_je_position, handanteil, kurz,
                           anlegen as position_bauen)
from ..db import get_session
from ..bezeichnung import anzeigename
from ..export import als_datei, dateiname, exportiere, importiere, loesche
from ..felder import bereinige
from ..engine import Position, abrechnung
from ..erinnerungen import beleg_erinnerung, frist_erinnerung, in_sicht
from ..frist import frist_tage
from ..nachpflege import hinweise, zusammenfassung
from ..models import (Dokument, Einheit, Kostenart, Kostenposition, Miete,
                      Objekt, Partei, Vorauszahlung, Zeitraum, ist_grundstueck)
from ..verteilung import (SCHLUESSEL, VORGABE, UnbekannterSchluessel, ableiten,
                          fehlende_angaben, stammdaten, vorschau)

log = logging.getLogger("immocalc")
router = APIRouter(prefix="/api", tags=["objekte"])

# Sicherungen liegen im Home-Ordner, nicht bei den Unterlagen einer Immobilie —
# die bleibt beim Löschen ja gerade bestehen.
SICHERUNGSORDNER = "00_ImmoCalc_Sicherungen"


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
    kostenarten: list[str] = []
    einheiten: list[EinheitIn] = []


def _je_objekt(zeilen: list, ids: list[int]) -> dict[int, list]:
    """Ordnet Zeilen ihrem Objekt zu — jedes Objekt kommt vor, auch leer."""
    eimer: dict[int, list] = {i: [] for i in ids}
    for zeile in zeilen:
        eimer.setdefault(zeile.objekt_id, []).append(zeile)
    return eimer


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

    aktive = {oid: next((z for z in zs if z.status == "in Arbeit"), None)
              for oid, zs in zeitraeume.items()}
    zids = [z.id for z in aktive.values() if z is not None]
    offene: dict[int, int] = {}
    if zids:
        for p in session.exec(select(Kostenposition).where(
                Kostenposition.zeitraum_id.in_(zids))).all():
            if p.status == "offen":
                offene[p.zeitraum_id] = offene.get(p.zeitraum_id, 0) + 1

    out = []
    for o in alle:
        aktiv = aktive.get(o.id)
        laufend = [m for m in mieten[o.id] if m.bis_datum is None]
        # Eine Miete ohne Einheitsangabe meint das ganze Objekt — dann gilt
        # jede Einheit als vermietet, sonst keine einzige.
        ganzes_objekt = any(not m.einheit.strip() for m in laufend)
        belegt = {m.einheit.strip() for m in laufend if m.einheit.strip()}
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
                 "vermietet": ganzes_objekt or e.bezeichnung.strip() in belegt}
                for e in einheiten[o.id]],
            "offene_positionen": offene.get(aktiv.id, 0) if aktiv else 0,
            "frist_tage": frist_tage(aktiv) if aktiv else None,
            "miete_monatlich": round(sum(m.kaltmiete for m in laufend), 2),
        })
    return out


@router.post("/objekte", status_code=201)
def objekt_anlegen(data: ObjektIn, session: Session = Depends(get_session)) -> dict:
    o = Objekt(
        slug=_freier_slug(session, data.name), name=data.name, ort=data.ort,
        strasse=data.strasse, plz=data.plz, typ=data.typ, nutzung=data.nutzung,
        turnus=data.turnus, start_monat=data.start_monat, flaeche=data.flaeche,
        kaufpreis=data.kaufpreis, verkehrswert=data.verkehrswert,
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
               # Grundstück — bleibt bei jedem anderen Objekttyp einfach leer
               "grundstueck_flaeche", "grundstueck_nutzungsart",
               "grundstueck_wirtschaftsart", "gemarkung", "flurstueck",
               "grundsteuerwert", "grundsteuer_messbetrag",
               "grundsteuer_hebesatz"}
    felder = bereinige(Objekt, {k: v for k, v in data.items() if k in erlaubt})
    if not felder.get("name", "x"):
        raise HTTPException(400, "Der Name darf nicht leer sein")
    # ueber model_validate, damit Datumsstrings aus JSON zu echten date-Objekten
    # werden — als Zeichenkette gespeichert liesse sich das Feld nicht mehr lesen.
    geprueft = Objekt.model_validate({**o.model_dump(), **felder})
    for k in felder:
        setattr(o, k, getattr(geprueft, k))
    session.add(o)
    session.commit()
    return {"ok": True, "slug": o.slug}


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


def _objekt(session: Session, slug: str) -> Objekt:
    o = session.exec(select(Objekt).where(Objekt.slug == slug)).first()
    if not o:
        raise HTTPException(404, "Objekt nicht gefunden")
    return o


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
                   heute: date) -> dict:
    """Eine Einheit mit dem, was heute darin wohnt.

    `vermietet` ist die eine Auskunft, die man auf einen Blick braucht — sie
    entscheidet, ob die Blase in der Oberfläche als „frei" erscheint."""
    eigene = [m for m in mieten if _zuordnung(m, einheiten) == e.bezeichnung]
    laufend = [m for m in eigene if _laeuft(m, heute)]
    return {
        **e.model_dump(),
        "vermietet": bool(laufend),
        "mieter": ", ".join(sorted({m.partei for m in laufend if m.partei})),
        "kaltmiete": round(sum(m.kaltmiete for m in laufend), 2),
        "mietverhaeltnisse": len(eigene),
    }


@router.get("/objekte/{slug}/einheiten")
def einheiten_liste(slug: str,
                    session: Session = Depends(get_session)) -> list[dict]:
    """Die Einheiten eines Objekts, jede mit ihrem heutigen Mieter."""
    o = _objekt(session, slug)
    einheiten = list(session.exec(
        select(Einheit).where(Einheit.objekt_id == o.id)).all())
    mieten = list(session.exec(select(Miete).where(Miete.objekt_id == o.id)).all())
    heute = date.today()
    return [_einheit_zeile(e, mieten, einheiten, heute) for e in einheiten]


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
                    session: Session = Depends(get_session)) -> dict:
    o = _objekt(session, slug)
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
                stellplaetze=data.stellplaetze or 0)
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
               "nebenflaeche", "stellplaetze"}
    felder = bereinige(Einheit, {k: v for k, v in data.items() if k in erlaubt})
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
            "wertquelle": p.wertquelle if p else None,
            **_verteilung(p),
            **_zusammensetzung(p),
            "position_id": p.id if p else None,
            "beleg_monat": k.beleg_monat,
            "zustand": "erledigt" if erledigt else ("offen" if p else "fehlt"),
        })
    # Positionen zu Kostenarten, die nicht im Katalog stehen, gehen sonst verloren
    for p in positionen:
        if p.kostenart in {k["kostenart"] for k in checkliste}:
            continue
        checkliste.append({
            "kostenart": p.kostenart, "s35": p.s35,
            "erledigt": p.status == "erledigt", "betrag": p.betrag,
            "schluessel": p.schluessel, "wertquelle": p.wertquelle,
            **_verteilung(p),
            **_zusammensetzung(p),
            "position_id": p.id, "beleg_monat": None,
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
        gewichte = {}
        for k in checkliste:
            if not k["erledigt"]:
                continue
            gesamt_anteil = sum(k["anteile"].values()) or 1
            for partei, anteil in (k["anteile"] or {}).items():
                gewichte[partei] = gewichte.get(partei, 0.0) + \
                    (k["betrag"] or 0) * anteil / gesamt_anteil
        for partei, betrag in sorted(gewichte.items(), key=lambda p: -p[1]):
            knoten.append({"name": partei, "spalte": 2})
            fluss.append({"von": 0, "nach": len(knoten) - 1, "wert": round(betrag, 2)})

    return {
        "id": z.id, "objekt": o.slug, "objekt_name": o.name,
        "label": f"{z.start:%d.%m.%Y} – {z.ende:%d.%m.%Y}",
        "start": z.start.isoformat(), "ende": z.ende.isoformat(),
        "typ": z.typ, "status": z.status,
        "frist_tage": frist_tage(z) if z.status == "in Arbeit" else None,
        "fortschritt": {"fertig": fertig, "gesamt": len(checkliste),
                        "summe": round(summe_erledigt, 2)},
        "checkliste": checkliste,
        "sankey": {"knoten": knoten, "fluss": fluss},
        "dokumente": [{"id": d.id, "dateiname": d.dateiname, "pfad": d.pfad,
                       "kategorie": d.kategorie} for d in dokumente],
        "belege_je_art": belege,
        "vorauszahlungen": [{"partei": v.partei, "betrag": v.betrag} for v in vzs],
    }


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
        start = date(jahr, o.start_monat or 1, 1)
        ende = date(start.year + 1, start.month, 1) - timedelta(days=1)
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
    """Ohne `anteile` werden die Gewichte aus dem Schlüssel abgeleitet."""
    kostenart: str
    betrag: float = 0.0
    schluessel: str = VORGABE
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

    try:
        p = position_bauen(session, z, data.kostenart, betrag=data.betrag,
                           schluessel=data.schluessel,
                           wertquelle=data.wertquelle, status=data.status,
                           s35=data.s35, anteile=data.anteile)
    except UnbekannterSchluessel as fehler:
        raise HTTPException(400, str(fehler)) from fehler
    session.commit()
    session.refresh(p)
    return {"id": p.id, "kostenart": p.kostenart, "status": p.status,
            "anteile": p.anteile, "abgeleitet": data.anteile is None}


class PositionIn(BaseModel):
    betrag: Optional[float] = None
    status: Optional[str] = None
    schluessel: Optional[str] = None
    wertquelle: Optional[str] = None
    anteile: Optional[dict[str, float]] = None
    s35: Optional[bool] = None


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
    if data.betrag is not None:
        p.betrag = data.betrag
        # Ein eingetragener Betrag heisst: der Beleg liegt vor.
        if data.status is None and data.betrag > 0:
            p.status = "erledigt"
    if data.schluessel is not None and data.schluessel not in SCHLUESSEL:
        raise HTTPException(400, f"Unbekannter Verteilungsschlüssel "
                                 f"'{data.schluessel}'")
    umgestellt = data.schluessel is not None and data.schluessel != p.schluessel
    for feld in ("status", "schluessel", "wertquelle", "s35"):
        wert = getattr(data, feld)
        if wert is not None:
            setattr(p, feld, wert)
    if data.anteile is not None:
        p.anteile = data.anteile
    elif umgestellt:
        p.anteile = _gewichte(session, _zeitraum(session, p.zeitraum_id),
                              p.schluessel)
    session.add(p)
    session.commit()
    return {"ok": True, "betrag": p.betrag, "status": p.status,
            "schluessel": p.schluessel, "anteile": p.anteile}


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
    geloest = 0
    for d in session.exec(select(Dokument)
                          .where(Dokument.position_id == pid)).all():
        d.position_id = None
        session.add(d)
        geloest += 1
    session.delete(p)
    session.commit()
    return {"ok": True, "kostenart": kostenart, "belege_geloest": geloest}


@router.get("/zeitraeume/{zid}/abrechnung")
def abrechnung_endpoint(zid: int, session: Session = Depends(get_session)) -> dict:
    _zeitraum(session, zid)
    pos = session.exec(select(Kostenposition).where(Kostenposition.zeitraum_id == zid)).all()
    vzs = session.exec(select(Vorauszahlung).where(Vorauszahlung.zeitraum_id == zid)).all()
    # offene Positionen (Betrag noch nicht da) fließen nicht in die Rechnung ein
    positionen = [Position(p.kostenart, p.betrag, p.schluessel, p.anteile or {}, p.s35)
                  for p in pos if p.status == "erledigt"]
    res = abrechnung(positionen, {v.partei: v.betrag for v in vzs})
    # Erledigte Positionen ohne Gewichte gehören zu den offenen: ihr Betrag
    # verschwindet sonst lautlos, und der Abschluss übergeht sie.
    res.update(fehlende_angaben(list(pos)))
    return res
