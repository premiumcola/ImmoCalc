"""N270 — Renovierung je Objekt: Zeitraum, betroffene Einheiten, Budget mit
laufendem Restbudget, und die Rechnungen (Posten) dazu.

Routen-Reihenfolge: `/objekte/{slug}/renovierungen` muss VOR dem
Stammdaten-Fänger `/objekte/{slug}/{bereich}` registriert werden (siehe
main.py, Vorbild `zaehler`).
"""
import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from .. import renovierung as logik
from ..db import get_session
from ..deps import objekt_holen
from ..models import Objekt, Renovierung, Renovierungsposten

log = logging.getLogger("immocalc")
router = APIRouter(prefix="/api", tags=["renovierung"])


class RenovierungEingabe(BaseModel):
    name: str
    von: Optional[date] = None
    bis: Optional[date] = None
    budget: Optional[float] = None
    einheiten: list[str] = []
    notiz: str = ""
    abgeschlossen: bool = False


class RenovierungAenderung(BaseModel):
    """Alle Felder optional — PATCH aendert nur, was mitgeschickt wird."""
    name: Optional[str] = None
    von: Optional[date] = None
    bis: Optional[date] = None
    budget: Optional[float] = None
    einheiten: Optional[list[str]] = None
    notiz: Optional[str] = None
    abgeschlossen: Optional[bool] = None


class PostenEingabe(BaseModel):
    datum: Optional[date] = None
    betrag: float = 0.0
    firma: str = ""
    gewerk: str = ""
    notiz: str = ""
    quelle_dokument_id: Optional[int] = None


class PostenAenderung(BaseModel):
    datum: Optional[date] = None
    betrag: Optional[float] = None
    firma: Optional[str] = None
    gewerk: Optional[str] = None
    notiz: Optional[str] = None
    quelle_dokument_id: Optional[int] = None


def _renovierung_holen(rid: int, session: Session = Depends(get_session)) -> Renovierung:
    r = session.get(Renovierung, rid)
    if not r:
        raise HTTPException(404, "Renovierung nicht gefunden")
    return r


def _posten_holen(pid: int, session: Session = Depends(get_session)) -> Renovierungsposten:
    p = session.get(Renovierungsposten, pid)
    if not p:
        raise HTTPException(404, "Posten nicht gefunden")
    return p


def _posten_der_renovierung(session: Session, rid: int) -> list[Renovierungsposten]:
    return list(session.exec(
        select(Renovierungsposten).where(Renovierungsposten.renovierung_id == rid)).all())


def _summe(posten: list[Renovierungsposten]) -> float:
    return round(sum(p.betrag or 0.0 for p in posten), 2)


def _zeige_uebersicht(r: Renovierung, posten: list[Renovierungsposten]) -> dict:
    """Zeile der Listenansicht — schlank, ohne die einzelnen Posten."""
    stand = logik.budget_stand(r.budget, _summe(posten))
    return {
        "id": r.id, "name": r.name, "von": r.von, "bis": r.bis,
        "budget": r.budget, "einheiten": logik.einheiten_liste(r.einheiten),
        "notiz": r.notiz, "abgeschlossen": r.abgeschlossen,
        "summe": stand["ausgegeben"], "anzahl_posten": len(posten),
        "rest": stand["rest"], "ueberzogen": stand["ueberzogen"],
    }


def _zeige_posten(p: Renovierungsposten) -> dict:
    return {"id": p.id, "renovierung_id": p.renovierung_id, "datum": p.datum,
            "betrag": p.betrag, "firma": p.firma, "gewerk": p.gewerk,
            "notiz": p.notiz, "quelle_dokument_id": p.quelle_dokument_id}


def _zeige_detail(r: Renovierung, posten: list[Renovierungsposten]) -> dict:
    # Ohne Datum ans Ende — bei Rechnungen ohne erfasstes Datum soll der
    # Zeitstrahl im Frontend nicht mit `None` an den Anfang rutschen.
    sortiert = sorted(posten, key=lambda p: (p.datum is None, p.datum))
    return {
        "id": r.id, "name": r.name, "von": r.von, "bis": r.bis,
        "budget": r.budget, "einheiten": logik.einheiten_liste(r.einheiten),
        "notiz": r.notiz, "abgeschlossen": r.abgeschlossen,
        "posten": [_zeige_posten(p) for p in sortiert],
        "gewerke": logik.gewerk_summen(posten),
        "summe": _summe(posten),
        "budget_stand": logik.budget_stand(r.budget, _summe(posten)),
    }


@router.get("/renovierungen/gewerke")
def gewerke() -> dict:
    """Die Gewerke-Liste — einzige Wahrheit, das Frontend hardcodet sie nicht."""
    return {"gewerke": logik.GEWERKE}


@router.get("/objekte/{slug}/renovierungen")
def liste(o: Objekt = Depends(objekt_holen),
         session: Session = Depends(get_session)) -> list[dict]:
    renovierungen = session.exec(
        select(Renovierung).where(Renovierung.objekt_id == o.id)).all()
    ergebnis = []
    for r in sorted(renovierungen, key=lambda r: (r.von is None, r.von), reverse=True):
        ergebnis.append(_zeige_uebersicht(r, _posten_der_renovierung(session, r.id)))
    return ergebnis


@router.post("/objekte/{slug}/renovierungen", status_code=201)
def anlegen(eingabe: RenovierungEingabe, o: Objekt = Depends(objekt_holen),
           session: Session = Depends(get_session)) -> dict:
    r = Renovierung(objekt_id=o.id, name=eingabe.name, von=eingabe.von,
                    bis=eingabe.bis, budget=eingabe.budget,
                    einheiten=logik.einheiten_text(eingabe.einheiten),
                    notiz=eingabe.notiz, abgeschlossen=eingabe.abgeschlossen)
    session.add(r)
    session.commit()
    session.refresh(r)
    log.info("Renovierung angelegt: %s (Objekt %s)", r.name, o.slug)
    return _zeige_uebersicht(r, [])


@router.get("/renovierungen/{rid}")
def detail(rid: int, session: Session = Depends(get_session)) -> dict:
    r = _renovierung_holen(rid, session)
    return _zeige_detail(r, _posten_der_renovierung(session, rid))


@router.patch("/renovierungen/{rid}")
def aendern(rid: int, aenderung: RenovierungAenderung,
           session: Session = Depends(get_session)) -> dict:
    r = _renovierung_holen(rid, session)
    daten = aenderung.model_dump(exclude_unset=True)
    if "einheiten" in daten:
        daten["einheiten"] = logik.einheiten_text(daten["einheiten"])
    for feld, wert in daten.items():
        setattr(r, feld, wert)
    session.add(r)
    session.commit()
    session.refresh(r)
    return _zeige_detail(r, _posten_der_renovierung(session, rid))


@router.delete("/renovierungen/{rid}")
def loeschen(rid: int, session: Session = Depends(get_session)) -> dict:
    """Löscht die Renovierung samt ihren Posten — bewusste Nutzeraktion, wie
    an der einzigen sonstigen Löschstelle (CLAUDE.md)."""
    r = _renovierung_holen(rid, session)
    for p in _posten_der_renovierung(session, rid):
        session.delete(p)
    session.delete(r)
    session.commit()
    log.info("Renovierung %d gelöscht (samt Posten)", rid)
    return {"ok": True}


@router.post("/renovierungen/{rid}/posten", status_code=201)
def posten_anlegen(rid: int, eingabe: PostenEingabe,
                   session: Session = Depends(get_session)) -> dict:
    _renovierung_holen(rid, session)  # 404, falls die Renovierung fehlt
    p = Renovierungsposten(renovierung_id=rid, datum=eingabe.datum,
                           betrag=eingabe.betrag, firma=eingabe.firma,
                           gewerk=eingabe.gewerk, notiz=eingabe.notiz,
                           quelle_dokument_id=eingabe.quelle_dokument_id)
    session.add(p)
    session.commit()
    session.refresh(p)
    return _zeige_posten(p)


@router.patch("/renovierungen/posten/{pid}")
def posten_aendern(pid: int, aenderung: PostenAenderung,
                   session: Session = Depends(get_session)) -> dict:
    p = _posten_holen(pid, session)
    for feld, wert in aenderung.model_dump(exclude_unset=True).items():
        setattr(p, feld, wert)
    session.add(p)
    session.commit()
    session.refresh(p)
    return _zeige_posten(p)


@router.delete("/renovierungen/posten/{pid}")
def posten_loeschen(pid: int, session: Session = Depends(get_session)) -> dict:
    p = _posten_holen(pid, session)
    session.delete(p)
    session.commit()
    return {"ok": True}
