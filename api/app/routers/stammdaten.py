"""CRUD für Immobilien-Informationen jenseits der Nebenkosten:
Versicherungen, Mieten, Kredite, Zahlungen.

Alle vier verhalten sich gleich, deshalb eine generische Fabrik statt
vierfach kopierter Endpunkte."""
from typing import Type

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, SQLModel, select

from ..db import get_session
from ..felder import bereinige
from ..models import Kredit, Miete, Objekt, Versicherung, Zahlung
from ..turnus import VORGABE, auswahl_fuer

router = APIRouter(prefix="/api", tags=["stammdaten"])

ENTITAETEN: dict[str, Type[SQLModel]] = {
    "versicherungen": Versicherung,
    "mieten": Miete,
    "kredite": Kredit,
    "zahlungen": Zahlung,
}


def _objekt(session: Session, slug: str) -> Objekt:
    o = session.exec(select(Objekt).where(Objekt.slug == slug)).first()
    if not o:
        raise HTTPException(404, "Objekt nicht gefunden")
    return o


def _modell(bereich: str) -> Type[SQLModel]:
    modell = ENTITAETEN.get(bereich)
    if modell is None:
        raise HTTPException(404, f"Unbekannter Bereich '{bereich}'")
    return modell


@router.get("/turnus/{bereich}")
def turnus_auswahl(bereich: str) -> dict:
    """Zahlungsturnus-Optionen eines Bereichs — speist die Auswahlfelder."""
    _modell(bereich)                     # unbekannter Bereich -> 404
    return {"bereich": bereich, "vorgabe": VORGABE.get(bereich, "jaehrlich"),
            "optionen": auswahl_fuer(bereich)}


# response_model=None: der Typ steht erst zur Laufzeit fest. Ohne das wuerde
# FastAPI gegen die Basisklasse SQLModel serialisieren und alle Felder schlucken.
@router.get("/objekte/{slug}/{bereich}", response_model=None)
def liste(slug: str, bereich: str,
          session: Session = Depends(get_session)) -> list:
    modell = _modell(bereich)
    o = _objekt(session, slug)
    return session.exec(select(modell).where(modell.objekt_id == o.id)).all()


@router.post("/objekte/{slug}/{bereich}", status_code=201)
def anlegen(slug: str, bereich: str, data: dict,
            session: Session = Depends(get_session)) -> dict:
    modell = _modell(bereich)
    o = _objekt(session, slug)
    # model_validate statt modell(**data): nur so werden Datumsstrings aus JSON
    # zu echten date-Objekten konvertiert, die SQLite akzeptiert.
    # bereinige davor: ein im Formular leer gelassenes Betragsfeld kommt als
    # null an und liesse sonst das ganze Anlegen scheitern — samt Mieter,
    # Kaltmiete und Anschrift, die daneben schon eingetragen waren.
    eintrag = modell.model_validate({**bereinige(modell, data), "objekt_id": o.id})
    session.add(eintrag)
    session.commit()
    session.refresh(eintrag)
    return {"id": eintrag.id}


@router.patch("/{bereich}/{eintrag_id}")
def aendern(bereich: str, eintrag_id: int, data: dict,
            session: Session = Depends(get_session)) -> dict:
    modell = _modell(bereich)
    eintrag = session.get(modell, eintrag_id)
    if not eintrag:
        raise HTTPException(404, "Eintrag nicht gefunden")
    felder = bereinige(modell, {k: v for k, v in data.items()
                                if k not in ("id", "objekt_id")
                                and hasattr(eintrag, k)})
    geprueft = modell.model_validate({**eintrag.model_dump(), **felder})
    for k in felder:
        setattr(eintrag, k, getattr(geprueft, k))
    session.add(eintrag)
    session.commit()
    return {"ok": True}


@router.delete("/{bereich}/{eintrag_id}")
def loeschen(bereich: str, eintrag_id: int,
             session: Session = Depends(get_session)) -> dict:
    modell = _modell(bereich)
    eintrag = session.get(modell, eintrag_id)
    if not eintrag:
        raise HTTPException(404, "Eintrag nicht gefunden")
    session.delete(eintrag)
    session.commit()
    return {"ok": True}
