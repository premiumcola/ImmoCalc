"""Zähler und Ablesewerte (CCXCIII).

Zähler hängen am Objekt, Ablesungen am Zähler. Die Eingabemaske schrittet je
Abrechnungszeitraum durch die Zähler; der Verbrauch wird linear auf Tagesbasis
interpoliert (`ablesung.py` → `engine`). Die eigentliche Geld-Verteilung bleibt
in den Kostenpositionen — hier entsteht nur der Verbrauch je Zähler.

Routen-Reihenfolge: `/objekte/{slug}/zaehler` muss VOR dem Stammdaten-Fänger
`/objekte/{slug}/{bereich}` registriert werden (siehe main.py).
"""
import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from .. import ablesung, belegposten, verteilung
from ..db import get_session
from ..deps import objekt_holen
from ..models import Ablesung, Objekt, Zaehler, Zeitraum

log = logging.getLogger("immocalc")
router = APIRouter(prefix="/api", tags=["zaehler"])


class ZaehlerIn(BaseModel):
    name: str
    kostenart: str = ""
    einheit_bezug: str = ""
    messeinheit: str = "m³"
    typ: str = "gemessen"
    hauptzaehler_id: int | None = None
    reihenfolge: int = 0
    aktiv: bool = True
    notiz: str = ""


class AblesungIn(BaseModel):
    datum: date
    stand: float
    zeitraum_id: int | None = None
    notiz: str = ""


class UebernahmeIn(BaseModel):
    kostenart: str
    schluessel: str = "verbrauch"


def _zaehler(session: Session, zid: int) -> Zaehler:
    z = session.get(Zaehler, zid)
    if not z:
        raise HTTPException(404, "Zähler nicht gefunden")
    return z


# --------------------------------------------------------------------------
# Zähler-Stammdaten je Objekt
# --------------------------------------------------------------------------

@router.get("/objekte/{slug}/zaehler")
def liste(slug: str, session: Session = Depends(get_session),
          o: Objekt = Depends(objekt_holen)) -> list[dict]:
    zaehler = session.exec(
        select(Zaehler).where(Zaehler.objekt_id == o.id)
        .order_by(Zaehler.reihenfolge, Zaehler.id)).all()
    return [_zeige(session, z) for z in zaehler]


@router.post("/objekte/{slug}/zaehler", status_code=201)
def anlegen(slug: str, data: ZaehlerIn, session: Session = Depends(get_session),
            o: Objekt = Depends(objekt_holen)) -> dict:
    z = Zaehler(objekt_id=o.id, **data.model_dump())
    session.add(z)
    session.commit()
    session.refresh(z)
    return {"id": z.id}


@router.patch("/zaehler/{zid}")
def aendern(zid: int, data: dict, session: Session = Depends(get_session)) -> dict:
    z = _zaehler(session, zid)
    for feld in ("name", "kostenart", "einheit_bezug", "messeinheit", "typ",
                 "hauptzaehler_id", "reihenfolge", "aktiv", "notiz"):
        if feld in data:
            setattr(z, feld, data[feld])
    session.add(z)
    session.commit()
    return {"ok": True}


@router.delete("/zaehler/{zid}")
def loeschen(zid: int, session: Session = Depends(get_session)) -> dict:
    z = _zaehler(session, zid)
    for a in session.exec(select(Ablesung).where(Ablesung.zaehler_id == zid)).all():
        session.delete(a)
    session.delete(z)
    session.commit()
    return {"ok": True}


# --------------------------------------------------------------------------
# Ablesungen je Zähler
# --------------------------------------------------------------------------

@router.get("/zaehler/{zid}/ablesungen")
def ablesungen(zid: int, session: Session = Depends(get_session)) -> list[dict]:
    _zaehler(session, zid)
    reihe = session.exec(select(Ablesung).where(Ablesung.zaehler_id == zid)
                         .order_by(Ablesung.datum)).all()
    return [{"id": a.id, "datum": a.datum.isoformat(), "stand": a.stand,
             "zeitraum_id": a.zeitraum_id, "notiz": a.notiz} for a in reihe]


@router.post("/zaehler/{zid}/ablesungen", status_code=201)
def ablesung_speichern(zid: int, data: AblesungIn,
                       session: Session = Depends(get_session)) -> dict:
    _zaehler(session, zid)
    # Idempotent je Zeitraum: eine bestehende Ablesung dieses Zeitraums wird
    # aktualisiert statt verdoppelt — so darf man im Wizard vor- und zurück.
    vorhanden = None
    if data.zeitraum_id is not None:
        vorhanden = session.exec(select(Ablesung).where(
            Ablesung.zaehler_id == zid,
            Ablesung.zeitraum_id == data.zeitraum_id)).first()
    a = vorhanden or Ablesung(zaehler_id=zid, datum=data.datum, stand=data.stand)
    a.datum, a.stand = data.datum, data.stand
    a.zeitraum_id, a.notiz = data.zeitraum_id, data.notiz
    session.add(a)
    session.commit()
    session.refresh(a)
    return {"id": a.id}


# --------------------------------------------------------------------------
# Eingabemaske je Abrechnungszeitraum — die Zähler in Reihenfolge mit Vorwert
# und (falls erfasst) interpoliertem Verbrauch.
# --------------------------------------------------------------------------

@router.get("/zeitraeume/{zid}/ablesung")
def maske(zid: int, session: Session = Depends(get_session)) -> dict:
    z = session.get(Zeitraum, zid)
    if not z:
        raise HTTPException(404, "Zeitraum nicht gefunden")
    zeitraeume = session.exec(
        select(Zeitraum).where(Zeitraum.objekt_id == z.objekt_id)).all()
    vorher = max((p for p in zeitraeume if p.ende < z.ende),
                 key=lambda p: p.ende, default=None)
    zaehler = session.exec(
        select(Zaehler).where(Zaehler.objekt_id == z.objekt_id, Zaehler.aktiv)
        .order_by(Zaehler.reihenfolge, Zaehler.id)).all()
    zma = [(zae, session.exec(select(Ablesung).where(Ablesung.zaehler_id == zae.id)
            .order_by(Ablesung.datum)).all()) for zae in zaehler]
    verb = ablesung.verbrauch_je_zaehler(zma, zeitraeume, zid)

    zeilen = []
    for zae, abls in zma:
        reihe = ablesung.verbrauchsreihe(abls, zeitraeume)
        vorwert = reihe.get(vorher.id) if vorher else None
        erfasst = next((a for a in abls if a.zeitraum_id == zid), None)
        zeilen.append({
            "id": zae.id, "name": zae.name, "messeinheit": zae.messeinheit,
            "kostenart": zae.kostenart, "einheit_bezug": zae.einheit_bezug,
            "typ": zae.typ, "hauptzaehler_id": zae.hauptzaehler_id,
            "vorwert": None if not vorwert else {
                "stand": round(vorwert["randwert"], 3),
                "datum": vorwert["datum"].isoformat()},
            "ablesung": None if not erfasst else {
                "id": erfasst.id, "datum": erfasst.datum.isoformat(),
                "stand": erfasst.stand},
            "verbrauch": None if verb.get(zae.id) is None
            else round(verb[zae.id], 3),
        })
    return {
        "zeitraum": {"id": z.id, "start": z.start.isoformat(),
                     "ende": z.ende.isoformat(),
                     "label": f"{z.start:%d.%m.%Y} – {z.ende:%d.%m.%Y}"},
        "vorheriges_ende": vorher.ende.isoformat() if vorher else None,
        "zaehler": zeilen,
        "schluessel_optionen": [
            {"wert": k, "titel": v["titel"], "ableitbar": v["ableitbar"]}
            for k, v in verteilung.SCHLUESSEL.items()],
    }


@router.post("/zeitraeume/{zid}/ablesung/uebernehmen")
def uebernehmen(zid: int, data: UebernahmeIn,
                session: Session = Depends(get_session)) -> dict:
    """Trägt den interpolierten Verbrauch einer Kostenart als Verteilung in die
    NK-Kostenposition ein. Bei `schluessel='verbrauch'` werden die Gewichte je
    Partei aus den Zählern gebildet (Untermesser/Rest, gruppiert nach
    `einheit_bezug`); bei jedem anderen Schlüssel werden sie aus den Stammdaten
    abgeleitet. Der Betrag (aus dem Beleg) bleibt unberührt — nur die Verteilung
    wird gesetzt. Eine bestehende Position wird aktualisiert, sonst angelegt."""
    z = session.get(Zeitraum, zid)
    if not z:
        raise HTTPException(404, "Zeitraum nicht gefunden")
    if data.schluessel not in verteilung.SCHLUESSEL:
        raise HTTPException(400, f"Unbekannter Schlüssel „{data.schluessel}“")

    zaehler = session.exec(select(Zaehler).where(
        Zaehler.objekt_id == z.objekt_id, Zaehler.kostenart == data.kostenart,
        Zaehler.aktiv)).all()
    if not zaehler:
        raise HTTPException(404, f"Keine Zähler für „{data.kostenart}“")

    # Gewichte je Partei aus dem Verbrauch — nur bei Verbrauchsschlüssel.
    anteile = None
    if data.schluessel == "verbrauch":
        zeitraeume = session.exec(
            select(Zeitraum).where(Zeitraum.objekt_id == z.objekt_id)).all()
        zma = [(zae, session.exec(select(Ablesung).where(
                Ablesung.zaehler_id == zae.id)).all()) for zae in zaehler]
        verb = ablesung.verbrauch_je_zaehler(zma, zeitraeume, zid)
        anteile = {}
        for zae in zaehler:
            # Der Gesamtzähler (ohne einheit_bezug) ist die Kontrollsumme, keine
            # Partei — nur die zugeordneten Unter-/Rest-Zähler tragen Gewicht.
            if zae.einheit_bezug and verb.get(zae.id):
                anteile[zae.einheit_bezug] = round(
                    anteile.get(zae.einheit_bezug, 0.0) + verb[zae.id], 4)

    pos = belegposten.finde(session, zid, data.kostenart)
    if pos:
        pos.schluessel = data.schluessel
        pos.wertquelle = "Zähler"
        pos.anteile = (anteile if anteile is not None
                       else verteilung.ableiten(session, z, data.schluessel))
        session.add(pos)
    else:
        pos = belegposten.anlegen(session, z, data.kostenart,
                                  schluessel=data.schluessel, wertquelle="Zähler",
                                  anteile=anteile)
    session.commit()
    session.refresh(pos)
    return {"ok": True, "kostenart": data.kostenart, "schluessel": pos.schluessel,
            "anteile": pos.anteile, "position_id": pos.id}


def _zeige(session: Session, z: Zaehler) -> dict:
    anzahl = len(session.exec(select(Ablesung).where(
        Ablesung.zaehler_id == z.id)).all())
    return {"id": z.id, "name": z.name, "kostenart": z.kostenart,
            "einheit_bezug": z.einheit_bezug, "messeinheit": z.messeinheit,
            "typ": z.typ, "hauptzaehler_id": z.hauptzaehler_id,
            "reihenfolge": z.reihenfolge, "aktiv": z.aktiv, "notiz": z.notiz,
            "ablesungen": anzahl}
