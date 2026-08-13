"""Hintergrund-Wächter: sieht regelmäßig im Eingang nach neuen Dateien.

Nextcloud kann nicht von sich aus anklopfen, also fragt ImmoCalc nach. Der
Takt ist bewusst gemächlich — neue Belege haben keine Eile, und jeder Lauf
kostet eine WebDAV-Abfrage je Objekt.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable
from datetime import datetime

from sqlmodel import Session

from .db import engine

log = logging.getLogger("immocalc")

TAKT_SEKUNDEN = 15 * 60

# N290 — der Abgleich läuft in einem EIGENEN, schnellen Takt.
#
# Der Nutzer sortiert und benennt seine Dateien im Windows-Explorer um und
# will sie danach „relativ in Echtzeit" wieder verknüpft sehen, nicht erst
# nach einer Viertelstunde. Der Abgleich ist dafür der richtige Lauf: er
# liest nur (PROPFIND je Ordner) und schreibt nichts in die Cloud. Die teuren
# Läufe — Texterkennung, Autoversand, Aufräumen — bleiben beim ruhigen
# 15-Minuten-Takt; sie kosten Rechenzeit und haben keine Eile.
ABGLEICH_TAKT_SEKUNDEN = 2 * 60

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
    # N290: wie oft eine Verknüpfung einer im Explorer bewegten Datei gefolgt ist.
    "nachgezogen_gesamt": 0,
    "letzter_abgleich": None,
    "laeuft": False,
}


def zustand() -> dict:
    letzter = _zustand["letzter_lauf"]
    abgleich = _zustand["letzter_abgleich"]
    return {
        "aktiv": bool(_zustand["laeuft"]),
        "takt_minuten": TAKT_SEKUNDEN // 60,
        # N290 — der Abgleich hat seinen eigenen, schnellen Takt.
        "abgleich_takt_minuten": ABGLEICH_TAKT_SEKUNDEN // 60,
        "letzter_abgleich": abgleich.isoformat() if abgleich else None,
        "nachgezogen_gesamt": _zustand["nachgezogen_gesamt"],
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


def _kontakte_lauf() -> dict:
    """N309 — das Kontaktbuch aus dem Bestand nachführen.

    Rein rechnend auf der eigenen Datenbank, ohne Cloud-Zugriff: neue Belege,
    neue Renovierungsrechnungen und neue Versicherungen bringen von selbst ihre
    Firma und ihre Kundennummer mit. Wiederholbar und rein ergänzend — von Hand
    Gepflegtes bleibt unangetastet."""
    from . import kontakte                            # spät, wegen Zirkel

    try:
        with Session(engine) as session:
            return kontakte.ernte(session)
    except Exception as fehler:                       # noqa: BLE001
        log.info("Kontakt-Ernte übersprungen: %s", fehler)
        return {"neu": 0, "nummern": 0}


def _pruefsummen_lauf() -> dict:
    """N303 — ein Häppchen Prüfsummen nachrechnen. Teilt sich die Sperre mit
    den anderen Läufen; prüft der Nutzer gerade selbst, tritt der Wächter
    zurück und holt es im nächsten Takt nach."""
    from .routers.dokumente import pruefsummen_nachtragen  # spät, wegen Zirkel

    if not sperre.acquire(blocking=False):
        return {"nachgetragen": 0}
    try:
        with Session(engine) as session:
            return pruefsummen_nachtragen(session)
    except Exception as fehler:                       # noqa: BLE001
        log.info("Prüfsummen-Lauf übersprungen: %s", fehler)
        return {"nachgetragen": 0}
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


# ---------------------------------------------------------------------------
# Die Schritte eines Taktes — jeder für sich, keiner vom anderen abhängig.
#
# Sie standen einmal alle hintereinander in EINEM ``try`` in `schleife`. Das war
# der Fehler: `einmal_scannen` reicht jede Ausnahme ausser HTTPException 409
# weiter, und `_scanne` fragt in seiner ersten Zeile die Cloud-Verbindung ab.
# Ist die Nextcloud nicht eingerichtet oder gerade nicht erreichbar, wirft sie
# HTTPException(400) — und damit war der ganze Takt zu Ende, bevor er begonnen
# hatte. Texterkennung, Prüfsummen, Kontaktbuch und vor allem der Autoversand
# der E-Tankstellen-Abrechnung liefen dann nie, obwohl keiner von ihnen die
# Cloud überhaupt braucht. Ein gescheiterter Schritt darf die folgenden nicht
# mitreissen; deshalb hat hier jeder sein eigenes ``try``.
# ---------------------------------------------------------------------------


def _scan_schritt() -> None:
    """Eingang prüfen und den Stand fortschreiben."""
    neu = einmal_scannen()
    _zustand["letzter_lauf"] = datetime.now()
    _zustand["letzter_fehler"] = None
    if neu:
        _zustand["gefunden_gesamt"] = int(_zustand["gefunden_gesamt"]) + neu
        log.info("Eingang: %d neue Datei(en)", neu)


def _ocr_schritt() -> None:
    """CCXXVII: liegen gebliebene Scans nachpflegen. RapidOCR kostet Sekunden
    je Beleg — das darf den Nutzer beim Hochladen nie warten lassen, deshalb
    hier statt im Upload."""
    ergaenzt = int(_ocr_lauf().get("ergaenzt", 0))
    if ergaenzt:
        _zustand["ocr_ergaenzt_gesamt"] = \
            int(_zustand["ocr_ergaenzt_gesamt"]) + ergaenzt
        log.info("Textschicht ergänzt: %d Beleg(e)", ergaenzt)


def _pruefsummen_schritt() -> None:
    """N303: Prüfsummen für den Bestand nachrechnen — ein Häppchen je Takt.
    Nextcloud liefert die Prüfsumme nur für Dateien, die ein Client mit
    entsprechender Kopfzeile hochgeladen hat; ohne dieses Nachrechnen bliebe der
    grösste Teil der Ablage ohne Kennzeichen, und damit ohne Duplikatserkennung
    und ohne Auslese-Speicher. Kostet je Beleg einen Download, gehört deshalb in
    den RUHIGEN Takt und nicht in den zweiminütigen Abgleich."""
    summen = _pruefsummen_lauf()
    if summen.get("nachgetragen"):
        log.info("Prüfsummen nachgetragen: %d (noch offen: %d)",
                 summen["nachgetragen"], summen.get("noch_offen", 0))


def _kontakte_schritt() -> None:
    """N309: das Kontaktbuch nachführen — neue Belege bringen ihre Firma und
    ihre Kundennummer von selbst mit."""
    stand = _kontakte_lauf()
    if stand.get("neu") or stand.get("nummern"):
        log.info("Kontaktbuch: %d neue Firmen, %d neue Nummern",
                 stand.get("neu", 0), stand.get("nummern", 0))


def _immocalc_schritt() -> None:
    """N30: verwaiste `.immocalc`-Steckbriefe aufräumen."""
    weg = int(_immocalc_lauf().get("geloescht", 0))
    if weg:
        _zustand["immocalc_aufgeraeumt_gesamt"] = \
            int(_zustand["immocalc_aufgeraeumt_gesamt"]) + weg
        log.info("Verwaiste .immocalc entfernt: %d", weg)


def _autoversand_schritt() -> None:
    """N165 — einen Tag nach Quartalsende die E-Tankstellen-Abrechnungen der
    Objekte mit eingeschaltetem Autoversand verschicken. Prüft selbst auf
    Fälligkeit und doppelten Versand; läuft ins Leere, wo nichts ansteht.

    Braucht die Cloud nicht — genau deshalb steht er hinter seinem eigenen
    Riegel und nicht mehr hinter der Eingangsprüfung."""
    from .routers import tankstelle          # spät, wegen Zirkelbezug

    tankstelle.autoversand_lauf()


# N310 — das Einsortieren in Jahresordner läuft hier BEWUSST NICHT mit. Es war
# eine Karte in den Einstellungen und ist dort zu Recht verschwunden, aber der
# Wächtertest `test_der_wachdienst_zieht_nie_selbst_um` hält eine ältere, gute
# Entscheidung fest: „echte Unterlagen wandern nicht nebenbei alle 15 Minuten".
# Dateien im Ordner des Nutzers zu bewegen ist schwer umkehrbar; das gehört
# nicht in einen stillen Takt. Der Rückstand wurde einmalig aufgeräumt, und NEUE
# Belege landen seit [N285] ohnehin gleich richtig — es entsteht also kein neuer.
def _schritte() -> list[tuple[str, Callable[[], None]]]:
    """Die Reihenfolge eines Taktes. Als Liste, damit `takt` jeden Schritt
    gleich behandeln kann — und damit keiner beim Anbau vergessen wird."""
    return [
        ("Eingangsprüfung", _scan_schritt),
        ("Textschicht", _ocr_schritt),
        ("Prüfsummen", _pruefsummen_schritt),
        ("Kontaktbuch", _kontakte_schritt),
        ("Verwaiste .immocalc", _immocalc_schritt),
        ("Autoversand", _autoversand_schritt),
    ]


async def takt() -> None:
    """Ein voller Durchgang: jeder Schritt gekapselt, keiner reisst die
    folgenden mit. Blockierendes WebDAV läuft im Threadpool, damit die API
    antwortbereit bleibt."""
    for name, schritt in _schritte():
        try:
            await asyncio.to_thread(schritt)
        except asyncio.CancelledError:
            raise
        except Exception as fehler:           # noqa: BLE001 - Wächter darf nie sterben
            _zustand["letzter_fehler"] = f"{name}: {fehler}"
            _zustand["letzter_lauf"] = datetime.now()
            log.warning("Wachdienst — %s fehlgeschlagen: %s", name, fehler)


async def abgleich_schleife() -> None:
    """N290 — der schnelle Takt: nur der Abgleich, alle zwei Minuten.

    Er stellt die Verknüpfung wieder her, nachdem der Nutzer im Explorer
    umbenannt oder verschoben hat, und nimmt extern gelöschte Belege aus der
    Ablage (N248). Rein lesend gegenüber der Cloud, deshalb darf er oft laufen.

    Der Wächter darf nie sterben: jeder Fehler wird vermerkt, nicht geworfen.
    Läuft gerade ein anderer Lauf, tritt er zurück — dafür ist die Sperre da,
    und in zwei Minuten ist er wieder da."""
    while True:
        await asyncio.sleep(ABGLEICH_TAKT_SEKUNDEN)
        try:
            ergebnis = await asyncio.to_thread(_abgleich_lauf)
            entfernt = len(ergebnis.get("entfernt", []))
            if entfernt:
                _zustand["entfernt_gesamt"] = \
                    int(_zustand["entfernt_gesamt"]) + entfernt
                log.info("Extern gelöschte Belege entfernt: %d", entfernt)
            bewegt = len(ergebnis.get("verschoben", [])) \
                + len(ergebnis.get("umbenannt", []))
            if bewegt:
                _zustand["nachgezogen_gesamt"] = \
                    int(_zustand["nachgezogen_gesamt"]) + bewegt
                log.info("Verknüpfung nachgezogen: %d Beleg(e)", bewegt)
            _zustand["letzter_abgleich"] = datetime.now()
        except asyncio.CancelledError:
            raise
        except Exception as e:                    # Wächter darf nie sterben
            _zustand["letzter_fehler"] = str(e)
            log.warning("Abgleich fehlgeschlagen: %s", e)


async def schleife() -> None:
    """Läuft neben der API und arbeitet in festem Takt die Schritte ab."""
    _zustand["laeuft"] = True
    try:
        while True:
            await asyncio.sleep(TAKT_SEKUNDEN)
            await takt()
    except asyncio.CancelledError:
        _zustand["laeuft"] = False
        raise
