"""Eigentümer, Beteiligungen in Tausendsteln und die Vermögensübersicht."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from ..db import get_session
from ..models import Anteil, Eigentuemer, Kredit, Kreditstand, Objekt
from ..vermoegen import gesamt, objekt_vermoegen

router = APIRouter(prefix="/api", tags=["besitz"])

VOLL = 1000.0        # ein ganzes Objekt in Promille
# Eine Nachkommastelle genuegt: 333,3 dreimal ergibt 999,9 und soll als
# vollstaendig gelten. Auf mehr Genauigkeit zu bestehen liesse sich bei
# Dritteln nie erfuellen.
TOLERANZ = 0.1


def _objekt(session: Session, slug: str) -> Objekt:
    o = session.exec(select(Objekt).where(Objekt.slug == slug)).first()
    if not o:
        raise HTTPException(404, "Objekt nicht gefunden")
    return o


def promille_von(a: Anteil) -> float:
    """Massgeblicher Anteil einer Beteiligung.

    Bestandszeilen haben noch kein `promille` — dort gilt weiter das
    ganzzahlige `tausendstel`. So ueberlebt jede eingegebene Beteiligung die
    Erweiterung auf Dezimalwerte."""
    return float(a.promille if a.promille is not None else (a.tausendstel or 0))


def rolle_von(promille: float) -> str:
    """Rolle aus dem Anteil ableiten statt sie waehlen zu lassen.

    Wer alles haelt, ist Alleineigentuemer; wer weniger haelt, teilt sich das
    Objekt mit jemandem. Von Hand gewaehlt koennte die Rolle den Tausendsteln
    widersprechen — abgeleitet kann sie das nie."""
    return "Alleineigentümer" if runde(promille) >= VOLL else "Miteigentümer"


def runde(wert: float) -> float:
    """Eine Nachkommastelle — 333,3 dreimal soll als vollstaendig gelten."""
    return round(wert + 0.0, 1)


class EigentuemerIn(BaseModel):
    name: str
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
                         "tausendstel": a.tausendstel,
                         "promille": runde(promille_von(a)),
                         "rolle": rolle_von(promille_von(a)),
                         "notiz": a.notiz}
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
    # `tausendstel` bleibt als Eingang bestehen, damit die Objektseite
    # unveraendert weiterschreiben kann; `promille` hat Vorrang.
    tausendstel: float = 1000
    promille: float | None = None
    notiz: str = ""


def _stand(zeilen: list[Anteil]) -> dict:
    """Verteilungsstand eines Objekts — auf eine Nachkommastelle genau."""
    vergeben = runde(sum(promille_von(a) for a in zeilen))
    return {"vergeben": vergeben,
            "frei": runde(VOLL - vergeben),
            "stimmig": bool(zeilen) and abs(VOLL - vergeben) <= TOLERANZ + 1e-9}


@router.get("/objekte/{slug}/anteile", response_model=None)
def anteile(slug: str, session: Session = Depends(get_session)) -> dict:
    """Beteiligungen an einem Objekt. `frei` zeigt, was noch nicht verteilt ist."""
    o = _objekt(session, slug)
    eigner = {e.id: e for e in session.exec(select(Eigentuemer)).all()}
    zeilen = session.exec(select(Anteil).where(Anteil.objekt_id == o.id)).all()
    return {
        "anteile": [{"id": a.id, "eigentuemer_id": a.eigentuemer_id,
                     "name": eigner[a.eigentuemer_id].name
                     if a.eigentuemer_id in eigner else "unbekannt",
                     "tausendstel": a.tausendstel,
                     "promille": runde(promille_von(a)),
                     "rolle": rolle_von(promille_von(a)),
                     "prozent": round(promille_von(a) / 10, 2),
                     "notiz": a.notiz}
                    for a in zeilen],
        **_stand(list(zeilen)),
    }


@router.get("/anteile/stand", response_model=None)
def anteilsstand(session: Session = Depends(get_session)) -> list:
    """Verteilungsstand aller aktiven Objekte — fuer die Eigentuemerseite.

    Bewusst auch Objekte ohne jede Beteiligung: gerade die fehlen sonst
    unbemerkt in der Uebersicht."""
    alle = session.exec(select(Anteil)).all()
    out = []
    for o in session.exec(select(Objekt)).all():
        if not o.aktiv:
            continue
        zeilen = [a for a in alle if a.objekt_id == o.id]
        out.append({"slug": o.slug, "name": o.name, "beteiligte": len(zeilen),
                    **_stand(zeilen)})
    out.sort(key=lambda z: (z["stimmig"], z["name"]))
    return out


@router.post("/objekte/{slug}/anteile", status_code=201)
def anteil_setzen(slug: str, data: AnteilIn,
                  session: Session = Depends(get_session)) -> dict:
    """Legt eine Beteiligung an oder ändert eine bestehende desselben Eigners.

    Bewusst kein zweiter Eintrag pro Person: sonst stünde dieselbe Beteiligung
    doppelt in der Liste und die Tausendstel gingen nicht mehr auf."""
    o = _objekt(session, slug)
    if not session.get(Eigentuemer, data.eigentuemer_id):
        raise HTTPException(404, "Eigentümer nicht gefunden")
    wert = runde(data.promille if data.promille is not None else data.tausendstel)
    if not 0 < wert <= VOLL:
        raise HTTPException(400, "Anteile müssen zwischen 0,1 und 1000 ‰ liegen")

    vorhanden = session.exec(
        select(Anteil).where(Anteil.objekt_id == o.id,
                             Anteil.eigentuemer_id == data.eigentuemer_id)).first()
    eintrag = vorhanden or Anteil(objekt_id=o.id,
                                  eigentuemer_id=data.eigentuemer_id)
    eintrag.promille = wert
    # Gerundet mitgefuehrt, damit Leser, die noch `tausendstel` erwarten,
    # weiterhin eine sinnvolle Zahl sehen.
    eintrag.tausendstel = int(round(wert))
    eintrag.rolle = rolle_von(wert)
    eintrag.notiz = data.notiz
    session.add(eintrag)
    session.commit()
    session.refresh(eintrag)
    return {"id": eintrag.id, "promille": eintrag.promille,
            "rolle": eintrag.rolle}


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
    """Wert, Restschuld und Eigenkapital je Objekt und in Summe.

    Die Jahresstände werden in einem Zug geladen und je Kredit zugeordnet —
    nicht je Kredit einzeln nachgeschlagen. Ohne sie nannte diese Übersicht
    den roh eingetragenen Wert, während die Objektseite den fortgeschriebenen
    zeigte: zwei Zahlen für dieselbe Restschuld."""
    kredite = session.exec(select(Kredit)).all()
    anteile_alle = session.exec(select(Anteil)).all()
    staende: dict[int, list[Kreditstand]] = {}
    for s in session.exec(select(Kreditstand)).all():
        staende.setdefault(s.kredit_id, []).append(s)
    zeilen = [
        objekt_vermoegen(o,
                         [k for k in kredite if k.objekt_id == o.id],
                         [a for a in anteile_alle if a.objekt_id == o.id],
                         staende=staende)
        for o in session.exec(select(Objekt)).all() if o.aktiv
    ]
    zeilen.sort(key=lambda z: -(z["wert"] or 0))
    return {"objekte": zeilen, "gesamt": gesamt(zeilen)}
