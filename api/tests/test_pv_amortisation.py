"""N428 — Nutzer-Fund: die genaue Prognose (`_prognose`, nur echte Ertrags-
jahre ohne Vorlauf) rechnete bei einer echten Anlage über einen fast leeren
Schnitt (die laufenden Abrechnungsjahre trugen nur E-Tankstelle-Cent-Beträge,
PV-Strom/Einspeisung waren dort noch nicht gepflegt) und landete jenseits von
60 Jahren — „eine Jahreszahl wäre hier ohne Aussage", obwohl real schon rund
2.800 € über gut drei Jahre hereingekommen waren. „Kannst du ja schon für eine
Hochrechnung hernehmen."

`_grobe_prognose` ist der Fallback: der Schnitt aus ALLEM Bisherigen
(Vorlauf eingeschlossen) über die seit der Inbetriebnahme tatsächlich
verstrichene Zeit — ungenauer, aber ehrlicher als eine 60-Jahre-Fehlanzeige.
"""
import os
import sys
import tempfile
from datetime import date

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_pv_amortisation.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.pv.amortisation import _grobe_prognose  # noqa: E402


def test_realer_fall_liefert_eine_jahreszahl_statt_60_jahre_fehlanzeige():
    """Anschaffung 35.800 €, bisher 2.829,07 € (Vorlauf eingeschlossen),
    Inbetriebnahme 30.06.2023, heute 19.08.2026 — der genaue Weg (nur echte
    Ertragsjahre) scheiterte hier, weil die laufenden Jahre real nur ein paar
    hundert Euro E-Tanken trugen."""
    heute = date(2026, 8, 19)
    tage = (heute - date(2023, 6, 30)).days
    schnitt_erwartet = 2829.07 / (tage / 365.25)
    ergebnis = _grobe_prognose(kumuliert=2829.07, anschaffung=35800.0,
                               offen=35800.0 - 2829.07,
                               inbetriebnahme=date(2023, 6, 30), heute=heute)
    assert ergebnis is not None
    assert ergebnis["schnitt"] == round(schnitt_erwartet, 2)
    assert ergebnis["in_jahren"] > 0
    assert ergebnis["break_even_jahr"] == heute.year + ergebnis["in_jahren"]
    # Deutlich sinnvoller als „in 60 Jahren nicht abbezahlt".
    assert ergebnis["in_jahren"] < 60


def test_ohne_inbetriebnahme_keine_schaetzung():
    assert _grobe_prognose(1000.0, 10000.0, 9000.0, None,
                           heute=date(2026, 1, 1)) is None


def test_schon_abbezahlt_keine_schaetzung_noetig():
    assert _grobe_prognose(10000.0, 10000.0, 0.0, date(2020, 1, 1),
                           heute=date(2026, 1, 1)) is None


def test_unter_einem_halben_jahr_laufzeit_waere_nur_geraten():
    ergebnis = _grobe_prognose(500.0, 30000.0, 29500.0,
                               inbetriebnahme=date(2026, 6, 1),
                               heute=date(2026, 8, 19))
    assert ergebnis is None


def test_jenseits_des_60_jahre_horizonts_bleibt_es_bei_none():
    """Ein paar Euro im Jahr bei hoher Anschaffung — auch der grobe Schnitt
    hilft dann nicht, die Warnung bleibt zu Recht bestehen."""
    ergebnis = _grobe_prognose(kumuliert=50.0, anschaffung=35800.0,
                               offen=35750.0,
                               inbetriebnahme=date(2020, 1, 1),
                               heute=date(2026, 1, 1))
    assert ergebnis is None
