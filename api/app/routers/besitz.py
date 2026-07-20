"""Eigentümer, Beteiligungen in Tausendsteln und die Vermögensübersicht."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from ..db import get_session
from ..models import Anteil, Eigentuemer, Kredit, Objekt
from ..vermoegen import gesamt, objekt_vermoegen

router = APIRouter(prefix="/api", tags=["besitz"])


def _objekt(session: Session, slug: str) -> Objekt:
    o = session.exec(select(Objekt).where(Objekt.slug == slug)).first()
    if not o:
        raise HTTPException(404, "Objekt nicht gefunden")
    return o


class EigentuemerIn(BaseModel):
    name: str
    rolle: str = "Eigentümer"
    email: str = ""
    telefon: str = ""
    anschrift: str = ""
    steuernummer: str = ""
    notiz: str = ""


@router.get("/eigentuemer", response_model=None)
def liste(session: Session = Depends(get_session)) -> list:
    """Alle Eigentümer mit ihren Beteiligungen — die Liste in den Einstellungen."""
    objekte = {o.id: o for o in session.exec(select(Objekt)).all()}
    anteile = session.exec(select(Anteil)).all()
    out = []
    for e in session.exec(select(Eigentuemer)).all():
        meine = [a for a in anteile if a.eigentuemer_id == e.id]
        out.append({
            **e.model_dump(),
            "objekte": [{"anteil_id": a.id, "slug": objekte[a.objekt_id].slug,
                         "name": objekte[a.objekt_id].name,
                         "tausendstel": a.tausendstel}
                        for a in meine if a.objekt_id in objekte],
        })
    return out


@router.post("/eigentuemer", status_code=201)
def anlegen(data: EigentuemerIn, session: Session = Depends(get_session)) -> dict:
    e = Eigentuemer.model_validate(data.model_dump())
    session.add(e)
    session.commit()
    session.refresh(e)
    return {"id": e.id, "name": e.name}


@router.patch("/eigentuemer/{eid}")
def aendern(eid: int, data: dict, session: Session = Depends(get_session)) -> dict:
    e = session.get(Eigentuemer, eid)
    if not e:
        raise HTTPException(404, "Eigentümer nicht gefunden")
    for k, v in data.items():
        if k not in ("id",) and hasattr(e, k):
            setattr(e, k, v)
    session.add(e)
    session.commit()
    return {"ok": True}


@router.delete("/eigentuemer/{eid}")
def loeschen(eid: int, session: Session = Depends(get_session)) -> dict:
    """Entfernt den Eigentümer und seine Beteiligungen. Objekte bleiben."""
    e = session.get(Eigentuemer, eid)
    if not e:
        raise HTTPException(404, "Eigentümer nicht gefunden")
    for a in session.exec(select(Anteil).where(Anteil.eigentuemer_id == eid)).all():
        session.delete(a)
    session.delete(e)
    session.commit()
    return {"ok": True}


class AnteilIn(BaseModel):
    eigentuemer_id: int
    tausendstel: int = 1000
    notiz: str = ""


@router.get("/objekte/{slug}/anteile", response_model=None)
def anteile(slug: str, session: Session = Depends(get_session)) -> dict:
    """Beteiligungen an einem Objekt. `frei` zeigt, was noch nicht verteilt ist."""
    o = _objekt(session, slug)
    eigner = {e.id: e for e in session.exec(select(Eigentuemer)).all()}
    zeilen = session.exec(select(Anteil).where(Anteil.objekt_id == o.id)).all()
    vergeben = sum(a.tausendstel or 0 for a in zeilen)
    return {
        "anteile": [{"id": a.id, "eigentuemer_id": a.eigentuemer_id,
                     "name": eigner[a.eigentuemer_id].name
                     if a.eigentuemer_id in eigner else "unbekannt",
                     "tausendstel": a.tausendstel,
                     "prozent": round((a.tausendstel or 0) / 10, 1),
                     "notiz": a.notiz}
                    for a in zeilen],
        "vergeben": vergeben,
        "frei": 1000 - vergeben,
        "stimmig": vergeben == 1000,
    }


@router.post("/objekte/{slug}/anteile", status_code=201)
def anteil_setzen(slug: str, data: AnteilIn,
                  session: Session = Depends(get_session)) -> dict:
    """Legt eine Beteiligung an oder ändert eine bestehende desselben Eigners.

    Bewusst kein zweiter Eintrag pro Person: sonst stünde dieselbe Beteiligung
    doppelt in der Liste und die Tausendstel gingen nicht mehr auf."""
    o = _objekt(session, slug)
    if not session.get(Eigentuemer, data.eigentuemer_id):
        raise HTTPException(404, "Eigentümer nicht gefunden")
    if not 0 < data.tausendstel <= 1000:
        raise HTTPException(400, "Tausendstel müssen zwischen 1 und 1000 liegen")

    vorhanden = session.exec(
        select(Anteil).where(Anteil.objekt_id == o.id,
                             Anteil.eigentuemer_id == data.eigentuemer_id)).first()
    eintrag = vorhanden or Anteil(objekt_id=o.id,
                                  eigentuemer_id=data.eigentuemer_id)
    eintrag.tausendstel = data.tausendstel
    eintrag.notiz = data.notiz
    session.add(eintrag)
    session.commit()
    session.refresh(eintrag)
    return {"id": eintrag.id}


@router.delete("/anteile/{aid}")
def anteil_loeschen(aid: int, session: Session = Depends(get_session)) -> dict:
    a = session.get(Anteil, aid)
    if not a:
        raise HTTPException(404, "Anteil nicht gefunden")
    session.delete(a)
    session.commit()
    return {"ok": True}


@router.get("/vermoegen")
def uebersicht(session: Session = Depends(get_session)) -> dict:
    """Wert, Restschuld und Eigenkapital je Objekt und in Summe."""
    kredite = session.exec(select(Kredit)).all()
    anteile_alle = session.exec(select(Anteil)).all()
    zeilen = [
        objekt_vermoegen(o,
                         [k for k in kredite if k.objekt_id == o.id],
                         [a for a in anteile_alle if a.objekt_id == o.id])
        for o in session.exec(select(Objekt)).all() if o.aktiv
    ]
    zeilen.sort(key=lambda z: -(z["wert"] or 0))
    return {"objekte": zeilen, "gesamt": gesamt(zeilen)}
