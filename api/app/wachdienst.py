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
    # CCXXVII: wie viele Belege der Wachdienst insgesamt schon eine
    # durchsuchbare Textschicht nachgetragen hat.
    "ocr_ergaenzt_gesamt": 0,
    # N30: wie viele verwaiste `.immocalc`-Steckbriefe insgesamt aufgeräumt.
    "immocalc_aufgeraeumt_gesamt": 0,
    # N248: wie viele extern gelöschte Belege aus der Ablage genommen wurden.
    "entfernt_gesamt": 0,
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
        "ocr_ergaenzt_gesamt": _zustand["ocr_ergaenzt_gesamt"],
        "immocalc_aufgeraeumt_gesamt": _zustand["immocalc_aufgeraeumt_gesamt"],
        "entfernt_gesamt": _zustand["entfernt_gesamt"],
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


def _ocr_lauf() -> dict:
    """Ein Nachpflege-Lauf: trägt liegen gebliebenen Scans ihre Textschicht
    nach (CCXXVII). Teilt sich die Sperre mit `einmal_scannen` — beide bewegen
    Dateien in der Cloud, und sollen das nie gleichzeitig tun.

    Prüft der Nutzer gerade selbst den Eingang, tritt der Wachdienst zurück:
    kein Fehler, der nächste Takt in 15 Minuten holt es nach."""
    from .routers.dokumente import nachtraeglich_ocren  # spät, wegen Zirkelbezug

    if not sperre.acquire(blocking=False):
        return {"ergaenzt": 0}
    try:
        with Session(engine) as session:
            return nachtraeglich_ocren(session)
    finally:
        sperre.release()


def _abgleich_lauf() -> dict:
    """N248 — den Stand der Cloud nachziehen: umgezogene Einträge folgen ihrer
    Datei, und was der Nutzer in der Nextcloud gelöscht hat, verschwindet auch
    aus der Ablage. Früher lief das nur auf ausdrückliches Anstossen; der
    Nutzer will es automatisch („ist die Datei halt weg, ist sie weg").

    Die Sicherung steckt im Abgleich selbst: entfernt wird ausschliesslich,
    was BEWEISBAR fehlt — der Ordner muss gelesen worden sein. Antwortet die
    Cloud nicht, überspringt `_abgleiche` die Immobilie und rührt keinen
    Eintrag an. Teilt sich die Sperre mit den anderen Läufen; prüft der Nutzer
    gerade selbst, tritt der Wachdienst zurück."""
    from .routers.dokumente import _abgleiche      # spät, wegen Zirkelbezug

    if not sperre.acquire(blocking=False):
        return {"entfernt": []}
    try:
        with Session(engine) as session:
            return _abgleiche(session, trocken=False)
    finally:
        sperre.release()


def _immocalc_lauf() -> dict:
    """N30 — verwaiste `.immocalc`-Steckbriefe aufräumen: löscht der Nutzer ein
    PDF/Bild von Hand in der Cloud, bleibt die Sidecar als Waise liegen. Teilt
    sich die Sperre mit den anderen Läufen (alle bewegen Dateien in der Cloud).
    Prüft der Nutzer gerade selbst, tritt der Wachdienst zurück."""
    from .routers.dokumente import verwaiste_immocalc_aufraeumen  # spät, Zirkel

    if not sperre.acquire(blocking=False):
        return {"geloescht": 0}
    try:
        with Session(engine) as session:
            return verwaiste_immocalc_aufraeumen(session)
    finally:
        sperre.release()


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
            # CCXXVII: im selben Takt liegen gebliebene Scans nachpflegen.
            # RapidOCR kostet Sekunden je Beleg — das darf den Nutzer beim
            # Hochladen nie warten lassen, deshalb hier statt im Upload.
            ocr_ergebnis = await asyncio.to_thread(_ocr_lauf)
            ergaenzt = int(ocr_ergebnis.get("ergaenzt", 0))
            if ergaenzt:
                _zustand["ocr_ergaenzt_gesamt"] = \
                    int(_zustand["ocr_ergaenzt_gesamt"]) + ergaenzt
                log.info("Textschicht ergänzt: %d Beleg(e)", ergaenzt)
            # N248: den Stand der Cloud nachziehen — extern gelöschte Belege
            # verschwinden dadurch von selbst aus der Ablage.
            abgeglichen = await asyncio.to_thread(_abgleich_lauf)
            entfernt = len(abgeglichen.get("entfernt", []))
            if entfernt:
                _zustand["entfernt_gesamt"] = \
                    int(_zustand["entfernt_gesamt"]) + entfernt
                log.info("Extern gelöschte Belege entfernt: %d", entfernt)
            # N30: verwaiste `.immocalc`-Steckbriefe im selben Takt aufräumen.
            aufgeraeumt = await asyncio.to_thread(_immocalc_lauf)
            weg = int(aufgeraeumt.get("geloescht", 0))
            if weg:
                _zustand["immocalc_aufgeraeumt_gesamt"] = \
                    int(_zustand["immocalc_aufgeraeumt_gesamt"]) + weg
                log.info("Verwaiste .immocalc entfernt: %d", weg)
            # N165 — einen Tag nach Quartalsende die E-Tankstellen-Abrechnungen
            # der Objekte mit eingeschaltetem Autoversand verschicken. Prueft
            # selbst auf Faelligkeit und doppelten Versand; laeuft ins Leere,
            # wo nichts ansteht.
            from .routers.tankstelle import autoversand_lauf
            await asyncio.to_thread(autoversand_lauf)
        except asyncio.CancelledError:
            _zustand["laeuft"] = False
            raise
        except Exception as e:                    # Wächter darf nie sterben
            _zustand["letzter_fehler"] = str(e)
            _zustand["letzter_lauf"] = datetime.now()
            log.warning("Eingangsprüfung fehlgeschlagen: %s", e)
