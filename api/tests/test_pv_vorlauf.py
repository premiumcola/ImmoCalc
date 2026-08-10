"""N335 — der Vorlauf der PV-Anlage steht in der Zeit, in der sie lief.

Nutzer-Fund: „Die Anlage wurde erst 2023 installiert, das heißt es macht keinen
Sinn, dass die Abschreibungen 2018 plötzlich anfangen. Bitte ein Drittel auf
2023 und zwei Drittel auf 2024 — 2025 ist die erste vollständige Abrechnung."

Die Immobilie rechnet seit Jahren ab, die Anlage steht erst seit Mitte 2023.
Der Vorlauf landete deshalb im Jahr vor der ersten *Objekt*-Abrechnung (2018),
fünf Jahre bevor es die Anlage gab, mit sieben leeren Zeilen davor.
"""
import os
import sys
import tempfile
from datetime import date

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_pv_vorlauf.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.pv.ertrag import (erstes_ertragsjahr,  # noqa: E402
                           vorlauf_verteilung)

LEER = {"pv_strom": 0.0, "einspeisung": 0.0, "tanken": 0.0}


def _quellen(**jahre) -> dict[int, dict]:
    """Jahre mit Ertrag als {jahr: betrag}, alles andere leer."""
    return {int(j): {**LEER, "tanken": b} for j, b in jahre.items()}


def test_ein_drittel_auf_das_anlaufjahr_zwei_drittel_auf_das_volle():
    """Der Fall des Nutzers, Zahl für Zahl: Inbetriebnahme 30.06.2023, erste
    Erträge 2025. 2023 lief die Anlage ein halbes Jahr, 2024 ganz — Gewichte
    0,5 und 1,0, also ein Drittel und zwei Drittel."""
    verteilung = vorlauf_verteilung(date(2023, 6, 30),
                                    _quellen(**{"2025": 322.49, "2026": 147.38}),
                                    fallback_jahr=2018)
    assert sorted(verteilung) == [2023, 2024]
    assert round(verteilung[2023], 4) == round(1 / 3, 4)
    assert round(verteilung[2024], 4) == round(2 / 3, 4)


def test_erstes_ertragsjahr_ist_das_erste_mit_echtem_geld():
    """Nicht das erste Abrechnungsjahr des Objekts — das liegt Jahre davor."""
    assert erstes_ertragsjahr(_quellen(**{"2025": 322.49, "2026": 147.38})) == 2025
    assert erstes_ertragsjahr({2019: dict(LEER), 2020: dict(LEER)}) is None


def test_ohne_inbetriebnahme_bleibt_alles_wie_bisher():
    """Wer das Datum nicht gepflegt hat, rechnet unverändert weiter: alles auf
    das Jahr vor der ersten Abrechnung (N153b)."""
    assert vorlauf_verteilung(None, _quellen(**{"2025": 10.0}),
                              fallback_jahr=2024) == {2024: 1.0}
    assert vorlauf_verteilung(None, {}, fallback_jahr=None) == {}


def test_inbetriebnahme_im_januar_gibt_dem_ersten_jahr_volles_gewicht():
    """Läuft die Anlage ab Januar, ist das erste Jahr ein volles — dann
    verteilt sich der Vorlauf gleichmässig auf beide Jahre."""
    verteilung = vorlauf_verteilung(date(2023, 1, 1), _quellen(**{"2025": 10.0}),
                                    fallback_jahr=2018)
    assert round(verteilung[2023], 4) == round(verteilung[2024], 4) == 0.5


def test_inbetriebnahme_im_ertragsjahr_selbst_bleibt_eine_zeile():
    """Gab es keine Zeit vor dem ersten Ertrag, steht der Vorlauf im Jahr der
    Inbetriebnahme — nie in einem Jahr, in dem es die Anlage nicht gab."""
    verteilung = vorlauf_verteilung(date(2025, 3, 1), _quellen(**{"2025": 10.0}),
                                    fallback_jahr=2024)
    assert verteilung == {2025: 1.0}


def test_dezember_inbetriebnahme_faellt_nicht_auf_null():
    """Ein am 31.12. angeschlossenes Jahr trägt nichts mehr bei — der Vorlauf
    gehört dann ganz ins Folgejahr, nicht in eine Division durch null."""
    verteilung = vorlauf_verteilung(date(2023, 12, 31), _quellen(**{"2025": 10.0}),
                                    fallback_jahr=2018)
    assert verteilung == {2024: 1.0}
