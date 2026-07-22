"""Gemeinsame FastAPI-Dependencies, von mehreren Routern geteilt.

CCXV: `_objekt(session, slug)` gab es dreifach identisch in stammdaten.py,
besitz.py und objekte.py — hier als eine Dependency statt drei Kopien.
"""
from fastapi import Depends, HTTPException
from sqlmodel import Session, select

from .db import get_session
from .models import Objekt


def objekt_holen(slug: str, session: Session = Depends(get_session)) -> Objekt:
    o = session.exec(select(Objekt).where(Objekt.slug == slug)).first()
    if not o:
        raise HTTPException(404, "Objekt nicht gefunden")
    return o
