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


def _einsortieren_lauf() -> dict:
    """N310 — Belege in ihren Jahresordner ziehen, ohne dass jemand einen Knopf
    drückt.

    Das war bis eben eine Karte in den Einstellungen („75 Belege liegen noch
    flach"). Der Nutzer will dort nichts mehr bedienen: „es sollte ja alles im
    Background laufen, ich will da nix einstellen". Es ist auch keine
    Einstellung, sondern eine Aufräumaktion — und eine, die seit [N285] nur
    noch die Nebenkosten und die Lagepläne betrifft.

    Verschoben wird kollisionssicher und nie überschreibend (derselbe Weg wie
    beim Knopf). Ein Beleg ohne Jahr bleibt liegen."""
    from .routers.cloud import unterordner_umzug_ausfuehren  # spät, Zirkel

    if not sperre.acquire(blocking=False):
        return {"verschoben": 0}
    try:
        with Session(engine) as session:
            return unterordner_umzug_ausfuehren(session=session)
    except Exception as fehler:                       # noqa: BLE001
        log.info("Einsortier-Lauf übersprungen: %s", fehler)
        return {"verschoben": 0}
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
            # N303: Prüfsummen für den Bestand nachrechnen — ein Häppchen je
            # Takt. Nextcloud liefert die Prüfsumme nur für Dateien, die ein
            # Client mit entsprechender Kopfzeile hochgeladen hat; ohne dieses
            # Nachrechnen bliebe der grösste Teil der Ablage ohne Kennzeichen,
            # und damit ohne Duplikatserkennung und ohne Auslese-Speicher.
            # Kostet je Beleg einen Download, gehört deshalb in den RUHIGEN
            # Takt und nicht in den zweiminütigen Abgleich.
            summen = await asyncio.to_thread(_pruefsummen_lauf)
            if summen.get("nachgetragen"):
                log.info("Prüfsummen nachgetragen: %d (noch offen: %d)",
                         summen["nachgetragen"], summen.get("noch_offen", 0))
            # N310: Belege in ihren Jahresordner ziehen — war eine Karte in den
            # Einstellungen, ist aber eine Aufräumaktion und keine Einstellung.
            einsortiert = await asyncio.to_thread(_einsortieren_lauf)
            if einsortiert.get("verschoben"):
                log.info("In Jahresordner einsortiert: %s",
                         einsortiert["verschoben"])
            # N309: das Kontaktbuch nachführen — neue Belege bringen ihre Firma
            # und ihre Kundennummer von selbst mit.
            kontakte_stand = await asyncio.to_thread(_kontakte_lauf)
            if kontakte_stand.get("neu") or kontakte_stand.get("nummern"):
                log.info("Kontaktbuch: %d neue Firmen, %d neue Nummern",
                         kontakte_stand.get("neu", 0),
                         kontakte_stand.get("nummern", 0))
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
