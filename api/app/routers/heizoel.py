"""N79 — Heizöl-Lieferungen und FIFO-Bewertung des Verbrauchs.

Heizöl-Lieferungen hängen am Objekt; die Rechenlogik (FIFO) lebt in der Engine
(`app.heizoel`). Die Endpunkte bleiben dünn: sie sammeln die Lieferungen und
reichen sie an die Engine weiter.

Routen-Reihenfolge: `/objekte/{slug}/heizoel` steht vor dem Stammdaten-Fänger
`/objekte/{slug}/{bereich}` — der Router wird in `main.py` entsprechend früh
eingehängt (analog zu `zaehler`).
"""
import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from .. import ablesung, heizoel
from ..db import get_session
from ..deps import objekt_holen
from ..models import Ablesung, Heizoellieferung, Objekt, Zaehler, Zeitraum

log = logging.getLogger("immocalc")
router = APIRouter(prefix="/api", tags=["heizoel"])


class LieferungIn(BaseModel):
    datum: date
    liter: float
    wert: float
    ist_anfangsbestand: bool = False
    notiz: str = ""


def _lieferung(session: Session, lid: int) -> Heizoellieferung:
    l = session.get(Heizoellieferung, lid)
    if not l:
        raise HTTPException(404, "Heizöl-Lieferung nicht gefunden")
    return l


def _zeige(l: Heizoellieferung) -> dict:
    """Eine Lieferung als JSON — inkl. abgeleitetem Preis je Liter."""
    preis = round(l.wert / l.liter, 4) if l.liter else 0.0
    return {"id": l.id, "datum": l.datum.isoformat(), "liter": l.liter,
            "wert": l.wert, "preis_liter": preis,
            "ist_anfangsbestand": l.ist_anfangsbestand, "notiz": l.notiz}


def _lieferungen(session: Session, objekt_id: int) -> list[Heizoellieferung]:
    """Lieferungen eines Objekts, FIFO-sortiert (Datum, dann id)."""
    return session.exec(
        select(Heizoellieferung)
        .where(Heizoellieferung.objekt_id == objekt_id)
        .order_by(Heizoellieferung.datum, Heizoellieferung.id)).all()


# --------------------------------------------------------------------------
# Lieferungen je Objekt
# --------------------------------------------------------------------------

@router.get("/objekte/{slug}/heizoel")
def liste(slug: str, session: Session = Depends(get_session),
          o: Objekt = Depends(objekt_holen)) -> dict:
    """Alle Heizöl-Lieferungen des Objekts (sortiert) plus Gesamtbestand/-wert."""
    lieferungen = _lieferungen(session, o.id)
    bestand = heizoel.gesamtbestand(lieferungen)
    return {"lieferungen": [_zeige(l) for l in lieferungen], **bestand}


@router.post("/objekte/{slug}/heizoel", status_code=201)
def anlegen(slug: str, data: LieferungIn, session: Session = Depends(get_session),
            o: Objekt = Depends(objekt_holen)) -> dict:
    """Eine Lieferung (oder den Anfangsbestand) anlegen."""
    l = Heizoellieferung(objekt_id=o.id, **data.model_dump())
    session.add(l)
    session.commit()
    session.refresh(l)
    return _zeige(l)


@router.patch("/heizoel/{lid}")
def aendern(lid: int, data: dict, session: Session = Depends(get_session)) -> dict:
    """Eine Lieferung ändern — z. B. eine Fehleingabe korrigieren."""
    l = _lieferung(session, lid)
    for feld in ("datum", "liter", "wert", "ist_anfangsbestand", "notiz"):
        if feld in data:
            wert = data[feld]
            if feld == "datum" and isinstance(wert, str):
                wert = date.fromisoformat(wert)
            setattr(l, feld, wert)
    session.add(l)
    session.commit()
    session.refresh(l)
    return _zeige(l)


@router.delete("/heizoel/{lid}")
def loeschen(lid: int, session: Session = Depends(get_session)) -> dict:
    """Eine Lieferung entfernen — bewusste Nutzeraktion an genau diesem
    Zusatz-Datensatz (kein Objekt, keine NK), nötig zur Korrektur einer
    Fehleingabe."""
    l = _lieferung(session, lid)
    session.delete(l)
    session.commit()
    return {"ok": True}


# --------------------------------------------------------------------------
# FIFO-Bewertung eines Verbrauchs
# --------------------------------------------------------------------------

def _verbrauch_aus_zeitraum(session: Session, o: Objekt, zeitraum_id: int) -> float:
    """Optional: den Öl-Verbrauch (Liter) eines Zeitraums aus den Zählern ziehen.

    Summiert den interpolierten Verbrauch aller Liter-Zähler des Objekts für
    den Zeitraum (`ablesung.verbrauch_je_zaehler`). Ohne passende Zähler oder
    Ablesungen ergibt sich 0 — dann bewertet die Engine einen Nullverbrauch."""
    z = session.get(Zeitraum, zeitraum_id)
    if not z or z.objekt_id != o.id:
        raise HTTPException(404, "Zeitraum nicht gefunden")
    zaehler = session.exec(
        select(Zaehler).where(Zaehler.objekt_id == o.id, Zaehler.aktiv)).all()
    oel = [zae for zae in zaehler if (zae.messeinheit or "").lower() == "liter"]
    if not oel:
        return 0.0
    zma = [(zae, session.exec(select(Ablesung).where(
            Ablesung.zaehler_id == zae.id).order_by(Ablesung.datum)).all())
           for zae in oel]
    zeitraeume = session.exec(
        select(Zeitraum).where(Zeitraum.objekt_id == o.id)).all()
    # N105 - ohne die synthetische Vorlauf-Periode gilt die erste Ablesung als
    # Startablesung und der Verbrauch der ersten Abrechnung ist 0: der
    # Oelzaehler zeigte unten 3.431 L, oben stand 0 L. `_mit_vorlauf` macht
    # aus dem Anfangsstand den Randwert - genau wie in der Ablese-Maske.
    from .zaehler import _mit_vorlauf
    zeitraeume_i, _ = _mit_vorlauf(zeitraeume, zma)
    verb = ablesung.verbrauch_je_zaehler(zma, zeitraeume_i, zeitraum_id)
    return round(sum(v for v in verb.values() if v), 3)


@router.get("/objekte/{slug}/heizoel/bewertung")
def bewertung(slug: str, verbrauch_liter: float | None = None,
              zeitraum_id: int | None = None,
              session: Session = Depends(get_session),
              o: Objekt = Depends(objekt_holen)) -> dict:
    """FIFO-Bewertung eines Verbrauchs (das älteste Öl zuerst).

    Der Verbrauch kommt entweder direkt als `verbrauch_liter` (Vorrang) oder —
    wenn nur `zeitraum_id` gesetzt ist — aus dem Öl-Zähler-Verbrauch des
    Zeitraums. Ohne beide Angaben wird ein Nullverbrauch bewertet (Rest =
    Gesamtbestand). Gibt das Bewertungs-dict der Engine zurück."""
    if zeitraum_id is None:
        verbrauch_liter = verbrauch_liter or 0.0
        return heizoel.verbrauch_bewerten(_lieferungen(session, o.id),
                                          verbrauch_liter)
    # N100 — periodenbezogen: der Anfangsbestand einer Periode ist der REST der
    # Vorperioden. Dafür erst alle früheren Verbräuche vom Bestand abziehen,
    # dann den Verbrauch dieser Periode. Sonst tauchten Anfangsbestand und
    # Lieferungen des Vorjahres in jeder weiteren Abrechnung erneut auf.
    z = session.get(Zeitraum, zeitraum_id)
    if not z or z.objekt_id != o.id:
        raise HTTPException(404, "Zeitraum nicht gefunden")
    if verbrauch_liter is None:
        verbrauch_liter = _verbrauch_aus_zeitraum(session, o, zeitraum_id)
    verbrauch_liter = verbrauch_liter or 0.0

    alle = _lieferungen(session, o.id)
    frueher = [p for p in session.exec(
        select(Zeitraum).where(Zeitraum.objekt_id == o.id)).all()
        if p.id != z.id and p.ende < z.start]
    vorher = round(sum(_verbrauch_aus_zeitraum(session, o, p.id)
                       for p in frueher), 3)
    # Bestand zu Periodenbeginn: alle Lieferungen bis zum Periodenstart minus
    # das, was in den Vorperioden verbraucht wurde.
    bis_start = [l for l in alle if l.datum <= z.start]
    anfang = heizoel.verbrauch_bewerten(bis_start, vorher)
    # In der Periode: Restbestand + die Lieferungen dieser Periode, davon den
    # Perioden-Verbrauch FIFO abziehen.
    in_periode = [l for l in alle if z.start < l.datum <= z.ende]
    e = heizoel.verbrauch_bewerten(bis_start + in_periode,
                                   vorher + verbrauch_liter)
    e["verbrauch_liter"] = round(max(0.0, e["verbrauch_liter"] - vorher), 3)
    e["verbrauch_kosten"] = round(
        e["verbrauch_kosten"] - anfang["verbrauch_kosten"], 2)
    e["anfang_liter"] = anfang["rest_liter"]
    e["anfang_wert"] = anfang["rest_wert"]
    e["lieferungen_periode"] = [l.id for l in in_periode]
    e["vorher_verbraucht_liter"] = vorher
    return e
