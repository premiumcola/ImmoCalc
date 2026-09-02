"""N458 — wer bei einem Schlüssel leer ausgeht, muss gemeldet werden.

Gefunden bei der Prüfung in der Nacht auf den 03.09.2026. `vorschau` nannte
unter `parteien_ohne_einheit` nur Parteien, deren Mietverhältnis auf **keine
Einheit** zeigt. Eine Einheit, die es gibt, deren FLÄCHE aber fehlt (oder 0
ist), rutschte durch: `zugeordnet` prüft nur, ob der Name im Flächen-Verzeichnis
steht — nicht, ob dort auch ein Wert steht.

Folge: `_gewicht` macht aus der fehlenden Fläche `None`, die Partei
verschwindet aus dem Schlüssel, bekommt keine Kosten und ihre Vorauszahlung
voll erstattet — während `ableitbar: True` behauptet, der Schlüssel sei
sauber. Genau der Ausgang, vor dem der Docstring von `_gesamtflaeche` warnt.

Die Frage ist jetzt am Ergebnis gestellt: wer trotz Bezug ohne Gewicht
dasteht, wird genannt — unabhängig davon, WARUM.
"""
import os
import sys
import tempfile
from datetime import date

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(),
                                     "test_ohne_flaeche_meldung.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.models import Einheit, Miete  # noqa: E402
from app.verteilung import bezuege, vorschau  # noqa: E402

START, ENDE = date(2025, 1, 1), date(2025, 12, 31)


def _welt(flaeche_og):
    einheiten = [Einheit(id=1, objekt_id=1, bezeichnung="EG", flaeche=60.0),
                 Einheit(id=2, objekt_id=1, bezeichnung="OG",
                         flaeche=flaeche_og)]
    mieten = [
        Miete(id=1, objekt_id=1, einheit="EG", partei="Meier",
              ab_datum=START, bis_datum=None),
        Miete(id=2, objekt_id=1, einheit="OG", partei="Schulz",
              ab_datum=START, bis_datum=None),
    ]
    return bezuege(einheiten, mieten, [], START, ENDE)


def _flaeche(bez):
    return next(e for e in vorschau(bez, START, ENDE) if e["wert"] == "flaeche")


def test_einheit_ohne_flaeche_wird_gemeldet():
    """Ohne Flächenangabe darf „nach Fläche" nicht als sauber gelten."""
    eintrag = _flaeche(_welt(flaeche_og=None))

    assert "Schulz" in eintrag["parteien_ohne_einheit"], (
        "die Partei ohne Flächenangabe fehlt in der Meldung: "
        f"{eintrag['parteien_ohne_einheit']}")
    assert eintrag["ableitbar"] is False, \
        "der Schlüssel gilt als ableitbar, obwohl eine Partei leer ausgeht"


def test_flaeche_null_zaehlt_genauso():
    """Ausdrücklich eingetragene 0 m² ist derselbe Fall — und war noch
    stiller, weil `nachpflege` eine 0 als gepflegt ansieht."""
    eintrag = _flaeche(_welt(flaeche_og=0.0))

    assert "Schulz" in eintrag["parteien_ohne_einheit"]
    assert eintrag["ableitbar"] is False


def test_vollstaendige_daten_bleiben_ableitbar():
    """Gegenprobe: sind alle Flächen da, ändert sich nichts."""
    eintrag = _flaeche(_welt(flaeche_og=40.0))

    assert eintrag["parteien_ohne_einheit"] == []
    assert eintrag["ableitbar"] is True
    assert eintrag["gewichte"] == {"Meier": 60.0, "Schulz": 40.0}


def test_nicht_ableitbare_schluessel_bleiben_unveraendert():
    """„Verbrauch" und „Prozent" haben von Haus aus keine Gewichte — sie
    dürfen nicht plötzlich jede Partei als vermisst melden."""
    bez = _welt(flaeche_og=40.0)
    for eintrag in vorschau(bez, START, ENDE):
        if eintrag["wert"] in ("verbrauch", "prozent", "individuell"):
            assert eintrag["parteien_ohne_einheit"] == [], eintrag["wert"]
            assert eintrag["ableitbar"] is False
