"""Gemeinsame FastAPI-Dependencies, von mehreren Routern geteilt.

CCXV: `_objekt(session, slug)` gab es dreifach identisch in stammdaten.py,
besitz.py und objekte.py — hier als eine Dependency statt drei Kopien.

N374: dasselbe für den Zeitraum. „Zeitraum nicht gefunden" stand wörtlich in
neun Modulen, teils fünfmal in derselben Datei — und an drei Stellen fehlte
die Prüfung ganz, sodass der Code mit `None` weiterrechnete. Ein Nachschlagen,
eine Fehlermeldung.
"""
from fastapi import Depends, HTTPException
from sqlmodel import Session, select

from .db import get_session
from .models import Objekt, Zeitraum


def objekt_holen(slug: str, session: Session = Depends(get_session)) -> Objekt:
    o = session.exec(select(Objekt).where(Objekt.slug == slug)).first()
    if not o:
        raise HTTPException(404, "Objekt nicht gefunden")
    return o


def zeitraum_holen(zid: int, session: Session = Depends(get_session)) -> Zeitraum:
    """Der Zeitraum zu einer id — oder 404.

    Als Dependency verwendbar (`z: Zeitraum = Depends(zeitraum_holen)`) und
    ebenso als schlichter Aufruf `zeitraum_holen(zid, session)`, weil viele
    Stellen ihn mitten in einer Funktion brauchen."""
    z = session.get(Zeitraum, zid)
    if not z:
        raise HTTPException(404, "Zeitraum nicht gefunden")
    return z


def objekt_zum_zeitraum(z: Zeitraum, session: Session) -> Objekt:
    """Das Objekt eines Zeitraums — mit Prüfung.

    N374 — mehrere Stellen machten `session.get(Objekt, z.objekt_id)` und
    griffen sofort auf `o.name` zu. Über den regulären Löschweg ist das nicht
    erreichbar (die Zeiträume gehen mit), aber eine fehlende Absicherung bleibt
    eine: ein verwaister Zeitraum ergäbe einen 500er ohne erkennbare Ursache."""
    o = session.get(Objekt, z.objekt_id)
    if not o:
        raise HTTPException(404, "Objekt zu diesem Zeitraum nicht gefunden")
    return o
