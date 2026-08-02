"""N80/N81 — Wärme-Endpunkte: Heizkostenverteiler (HKV), Öl-Split, Heizungs-
verteilung.

Die Rechenlogik lebt in der Engine (`app.waerme`); die Endpunkte bleiben dünn:
sie sammeln die HKV-Datensätze bzw. die Parameter und reichen sie weiter.

Routen-Reihenfolge: `/objekte/{slug}/heizverteiler`, `/objekte/{slug}/waerme/…`
und `/objekte/{slug}/heizung/…` stehen vor dem Stammdaten-Fänger
`/objekte/{slug}/{bereich}` — der Router wird in `main.py` entsprechend früh
eingehängt (analog zu `zaehler`/`heizoel`).
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from .. import waerme
from ..db import get_session
from ..deps import objekt_holen
from ..models import Heizverteiler, Objekt

log = logging.getLogger("immocalc")
router = APIRouter(prefix="/api", tags=["waerme"])


class HkvIn(BaseModel):
    einheit: str = ""
    nummer: str = ""
    raum: str = ""
    faktor: float = 1.0
    einheiten_stand: float = 0.0
    notiz: str = ""


def _hkv(session: Session, hid: int) -> Heizverteiler:
    h = session.get(Heizverteiler, hid)
    if not h:
        raise HTTPException(404, "Heizkostenverteiler nicht gefunden")
    return h


def _zeige(h: Heizverteiler) -> dict:
    """Ein HKV als JSON — inkl. abgeleitetem Gewicht (Faktor × Stand)."""
    return {"id": h.id, "einheit": h.einheit, "nummer": h.nummer,
            "raum": h.raum, "faktor": h.faktor,
            "einheiten_stand": h.einheiten_stand,
            "gewicht": round(h.faktor * h.einheiten_stand, 4), "notiz": h.notiz}


def _liste(session: Session, objekt_id: int) -> list[Heizverteiler]:
    """HKV eines Objekts, stabil sortiert (Einheit, Raum, id)."""
    return session.exec(
        select(Heizverteiler)
        .where(Heizverteiler.objekt_id == objekt_id)
        .order_by(Heizverteiler.einheit, Heizverteiler.raum,
                  Heizverteiler.id)).all()


# --------------------------------------------------------------------------
# Heizkostenverteiler je Objekt
# --------------------------------------------------------------------------

@router.get("/objekte/{slug}/heizverteiler")
def liste(slug: str, session: Session = Depends(get_session),
          o: Objekt = Depends(objekt_holen)) -> dict:
    """Alle Heizkostenverteiler des Objekts (sortiert)."""
    return {"heizverteiler": [_zeige(h) for h in _liste(session, o.id)]}


@router.post("/objekte/{slug}/heizverteiler", status_code=201)
def anlegen(slug: str, data: HkvIn, session: Session = Depends(get_session),
            o: Objekt = Depends(objekt_holen)) -> dict:
    """Einen Heizkostenverteiler anlegen."""
    h = Heizverteiler(objekt_id=o.id, **data.model_dump())
    session.add(h)
    session.commit()
    session.refresh(h)
    return _zeige(h)


@router.patch("/heizverteiler/{hid}")
def aendern(hid: int, data: dict, session: Session = Depends(get_session)) -> dict:
    """Einen HKV ändern — z. B. die jährliche Ablesung eintragen oder eine
    Fehleingabe korrigieren."""
    h = _hkv(session, hid)
    for feld in ("einheit", "nummer", "raum", "faktor", "einheiten_stand", "notiz"):
        if feld in data:
            setattr(h, feld, data[feld])
    session.add(h)
    session.commit()
    session.refresh(h)
    return _zeige(h)


@router.delete("/heizverteiler/{hid}")
def loeschen(hid: int, session: Session = Depends(get_session)) -> dict:
    """Einen HKV entfernen — bewusste Korrektur an genau diesem
    Zusatz-Datensatz (kein Objekt, keine NK)."""
    h = _hkv(session, hid)
    session.delete(h)
    session.commit()
    return {"ok": True}


# --------------------------------------------------------------------------
# N80 — Öl-Kosten in Warmwasser- und Heizungs-Anteil splitten (§9 HeizkostenV)
# --------------------------------------------------------------------------

@router.get("/objekte/{slug}/waerme/split")
def oel_split(slug: str, oel_kosten: float, oel_liter: float,
              ww_volumen_m3: float, temp_c: float = 60.0,
              heizwert: float = 10.0,
              o: Objekt = Depends(objekt_holen)) -> dict:
    """Öl-Kosten in Warmwasser- und Heizungs-Anteil aufteilen (`split_oel`)."""
    return waerme.split_oel(oel_kosten, oel_liter, ww_volumen_m3,
                            temp_c=temp_c, heizwert=heizwert)


# --------------------------------------------------------------------------
# N81 — Heizungs-Kosten über die HKV verteilen
# --------------------------------------------------------------------------

@router.get("/objekte/{slug}/heizung/verteilung")
def heizung_verteilung(slug: str, kosten: float,
                       session: Session = Depends(get_session),
                       o: Objekt = Depends(objekt_holen)) -> dict:
    """Heizungs-Kosten je Einheit über die HKV-Faktoren verteilen
    (`verteile_heizung`)."""
    return waerme.verteile_heizung(_liste(session, o.id), kosten)
