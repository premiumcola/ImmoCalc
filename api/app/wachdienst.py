"""Hintergrund-Wächter: sieht regelmäßig im Eingang nach neuen Dateien.

Nextcloud kann nicht von sich aus anklopfen, also fragt ImmoCalc nach. Der
Takt ist bewusst gemächlich — neue Belege haben keine Eile, und jeder Lauf
kostet eine WebDAV-Abfrage je Objekt.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime

from sqlmodel import Session

from .db import engine

log = logging.getLogger("immocalc")

TAKT_SEKUNDEN = 15 * 60

# Nur eine Eingangsprüfung zur Zeit. Der Wachdienst läuft in einem eigenen
# Thread, während der Nutzer „Ordner prüfen" drücken kann — ohne diese Sperre
# sehen beide Sitzungen dieselbe Datei als neu und legen sie doppelt an.
# Liegt hier statt im Router, weil der Wachdienst der zweite Rufer ist.
sperre = threading.Lock()

_zustand: dict[str, object] = {
    "letzter_lauf": None,
    "letzter_fehler": None,
    "gefunden_gesamt": 0,
    "laeuft": False,
}


def zustand() -> dict:
    letzter = _zustand["letzter_lauf"]
    return {
        "aktiv": bool(_zustand["laeuft"]),
        "takt_minuten": TAKT_SEKUNDEN // 60,
        "letzter_lauf": letzter.isoformat() if letzter else None,
        "letzter_fehler": _zustand["letzter_fehler"],
        "gefunden_gesamt": _zustand["gefunden_gesamt"],
    }


def einmal_scannen() -> int:
    """Ein Durchlauf. Gibt die Zahl neu aufgenommener Dateien zurück.

    Prüft der Nutzer gerade selbst, tritt der Wachdienst zurück: das ist kein
    Fehler, sondern genau die Aufgabe der Sperre."""
    from fastapi import HTTPException                # noqa: PLC0415
    from .routers.dokumente import scan              # spät, wegen Zirkelbezug

    with Session(engine) as session:
        try:
            ergebnis = scan(session=session)
        except HTTPException as fehler:
            if fehler.status_code == 409:
                log.info("Eingangsprüfung übersprungen: %s", fehler.detail)
                return 0
            raise
    return int(ergebnis.get("neu", 0))


async def schleife() -> None:
    """Läuft neben der API und prüft den Eingang in festem Takt."""
    _zustand["laeuft"] = True
    while True:
        await asyncio.sleep(TAKT_SEKUNDEN)
        try:
            # blockierendes WebDAV im Threadpool, damit die API antwortbereit bleibt
            neu = await asyncio.to_thread(einmal_scannen)
            _zustand["letzter_lauf"] = datetime.now()
            _zustand["letzter_fehler"] = None
            if neu:
                _zustand["gefunden_gesamt"] = int(_zustand["gefunden_gesamt"]) + neu
                log.info("Eingang: %d neue Datei(en)", neu)
        except asyncio.CancelledError:
            _zustand["laeuft"] = False
            raise
        except Exception as e:                    # Wächter darf nie sterben
            _zustand["letzter_fehler"] = str(e)
            _zustand["letzter_lauf"] = datetime.now()
            log.warning("Eingangsprüfung fehlgeschlagen: %s", e)
