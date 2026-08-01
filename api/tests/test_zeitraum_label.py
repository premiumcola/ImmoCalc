"""N34 — das Abrechnungsjahr ist das Kalenderjahr mit den MEISTEN Tagen im
Zeitraum. Ein Wirtschaftsjahr Okt–Sep gehört damit zum Endjahr.

Die Regel gilt fürs Erkennen (`zeitraum_label_jahr`) wie fürs Anlegen
(`_zeitraum_grenzen`) — beide müssen deckungsgleich sein, sonst landet ein Beleg
in einem anderen Jahr als dem, das der Zeitraum trägt.
"""
import os
import sys
import tempfile
from datetime import date
from types import SimpleNamespace

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_zeitraum_label.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.routers.objekte import (_zeitraum_grenzen, _zeitraum_jahr,  # noqa: E402
                                 zeitraum_label_jahr)


def test_label_jahr_meiste_tage():
    assert zeitraum_label_jahr(date(2024, 10, 1), date(2025, 9, 30)) == 2025
    assert zeitraum_label_jahr(date(2025, 10, 1), date(2026, 9, 30)) == 2026
    assert zeitraum_label_jahr(date(2025, 1, 1), date(2025, 12, 31)) == 2025
    # Juli-Start: Jul–Dez (184 T) schlägt Jan–Jun (181 T) → Startjahr.
    assert zeitraum_label_jahr(date(2025, 7, 1), date(2026, 6, 30)) == 2025


def _obj(start_monat):
    return SimpleNamespace(start_monat=start_monat)


def test_grenzen_kalenderjahr():
    o = _obj(1)
    assert _zeitraum_grenzen(o, 2025) == (date(2025, 1, 1), date(2025, 12, 31))


def test_grenzen_wirtschaftsjahr_okt():
    o = _obj(10)
    # „2025" ist der Zeitraum, der die meisten Tage in 2025 hat: Okt2024–Sep2025.
    assert _zeitraum_grenzen(o, 2025) == (date(2024, 10, 1), date(2025, 9, 30))
    assert _zeitraum_grenzen(o, 2026) == (date(2025, 10, 1), date(2026, 9, 30))


def test_grenzen_und_label_sind_deckungsgleich():
    for monat in (1, 4, 7, 10, 12):
        o = _obj(monat)
        for jahr in (2024, 2025, 2026):
            start, ende = _zeitraum_grenzen(o, jahr)
            assert zeitraum_label_jahr(start, ende) == jahr, (monat, jahr, start, ende)


def test_zeitraum_jahr_eines_datums():
    o = _obj(10)
    # Ein Beleg vom 15.11.2024 fällt in den Zeitraum Okt2024–Sep2025 → Jahr 2025.
    assert _zeitraum_jahr(o, date(2024, 11, 15)) == 2025
    # 15.9.2025 gehört noch zum selben Zeitraum → 2025.
    assert _zeitraum_jahr(o, date(2025, 9, 15)) == 2025
    # 1.10.2025 beginnt den nächsten → 2026.
    assert _zeitraum_jahr(o, date(2025, 10, 1)) == 2026
