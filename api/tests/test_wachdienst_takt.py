"""Der 15-Minuten-Takt darf nicht am ersten Schritt hängen bleiben.

Gefunden: `einmal_scannen` reicht jede Ausnahme ausser HTTPException 409 weiter,
und die Eingangsprüfung fragt in ihrer ersten Zeile die Cloud-Verbindung ab. Ist
die Nextcloud nicht eingerichtet oder gerade nicht erreichbar, wirft sie
HTTPException(400) — und weil alle Schritte in EINEM `try` standen, war der
Takt damit zu Ende, bevor er begonnen hatte. Texterkennung, Prüfsummen,
Kontaktbuch und vor allem der Autoversand der E-Tankstellen-Abrechnung liefen
dann nie, obwohl keiner von ihnen die Cloud braucht.
"""
import asyncio
import contextlib
import os
import sys
import tempfile
import time

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(),
                                     "test_wachdienst_takt.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi import HTTPException  # noqa: E402

from app import wachdienst  # noqa: E402
from app.routers import tankstelle  # noqa: E402

# In dieser Reihenfolge müssen die Schritte NACH der gescheiterten
# Eingangsprüfung noch drankommen.
DANACH = ["ocr", "pruefsummen", "kontakte", "immocalc", "autoversand"]


def _cloud_fehlt(monkeypatch, protokoll: list) -> None:
    """Ein Takt ohne echte Cloud: der erste Schritt scheitert genau so, wie er
    es beim Nutzer ohne eingerichtete Nextcloud tut, alle weiteren melden sich
    nur zu Protokoll."""
    def scan():
        raise HTTPException(400, "Nextcloud ist noch nicht eingerichtet")

    monkeypatch.setattr(wachdienst, "einmal_scannen", scan)
    monkeypatch.setattr(wachdienst, "_ocr_lauf",
                        lambda: protokoll.append("ocr") or {"ergaenzt": 0})
    monkeypatch.setattr(wachdienst, "_pruefsummen_lauf",
                        lambda: protokoll.append("pruefsummen")
                        or {"nachgetragen": 0})
    monkeypatch.setattr(wachdienst, "_kontakte_lauf",
                        lambda: protokoll.append("kontakte")
                        or {"neu": 0, "nummern": 0})
    monkeypatch.setattr(wachdienst, "_immocalc_lauf",
                        lambda: protokoll.append("immocalc")
                        or {"geloescht": 0})
    monkeypatch.setattr(tankstelle, "autoversand_lauf",
                        lambda: protokoll.append("autoversand") or {})


async def _bis_zum_autoversand(protokoll: list, grenze: float = 5.0) -> None:
    """Die echte Schleife anwerfen und warten, bis der letzte Schritt eines
    Taktes gelaufen ist — oder aufgeben. Ohne den Fix kommt er nie."""
    aufgabe = asyncio.create_task(wachdienst.schleife())
    ende = time.monotonic() + grenze
    while "autoversand" not in protokoll and time.monotonic() < ende:
        await asyncio.sleep(0.01)
    aufgabe.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await aufgabe


def test_gescheiterte_eingangspruefung_stoppt_den_takt_nicht(monkeypatch):
    """Der Kern: keine Cloud heisst nicht „kein Autoversand"."""
    protokoll: list = []
    _cloud_fehlt(monkeypatch, protokoll)
    monkeypatch.setattr(wachdienst, "TAKT_SEKUNDEN", 0.01)

    asyncio.run(_bis_zum_autoversand(protokoll))

    # Der erste volle Durchgang bringt alle Schritte nach der Eingangsprüfung.
    assert protokoll[:len(DANACH)] == DANACH


def test_ein_takt_kapselt_jeden_schritt_einzeln(monkeypatch):
    """Ein Durchgang ohne Schleife — der Fehler wird vermerkt, nicht geworfen."""
    protokoll: list = []
    _cloud_fehlt(monkeypatch, protokoll)

    asyncio.run(wachdienst.takt())

    assert protokoll == DANACH
    # Der Nutzer soll in der Statusanzeige sehen, WAS gescheitert ist.
    fehler = wachdienst.zustand()["letzter_fehler"]
    assert fehler and "Eingangsprüfung" in fehler


def test_ein_fehler_in_der_mitte_laesst_den_rest_laufen(monkeypatch):
    """Nicht nur der erste Schritt: auch ein Aussetzer mittendrin (etwa eine
    kaputte Textschicht) darf den Autoversand nicht mitnehmen."""
    protokoll: list = []
    _cloud_fehlt(monkeypatch, protokoll)

    def platzt():
        raise RuntimeError("RapidOCR ist nicht da")

    monkeypatch.setattr(wachdienst, "_ocr_lauf", platzt)

    asyncio.run(wachdienst.takt())

    assert protokoll == [s for s in DANACH if s != "ocr"]
