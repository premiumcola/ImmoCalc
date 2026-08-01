"""N14 — das Abrechnungsjahr (der abgerechnete Zeitraum) bestimmt die Ablage,
nicht das Rechnungs-/Briefdatum.

Der Müll-Bescheid „Abrechnung 2025, Grundgebühr 2026" war am 30.01.2026 datiert
und landete deshalb im Jahr 2026 — falsch, er rechnet 2025 ab.
"""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(),
                                     "test_abrechnungsjahr.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import kiauslese, ocr  # noqa: E402


def test_jahr_parser():
    assert kiauslese._jahr(2025) == 2025
    assert kiauslese._jahr("2025") == 2025
    assert kiauslese._jahr("2025-06") == 2025
    assert kiauslese._jahr(1500) is None          # zu weit in der Vergangenheit
    assert kiauslese._jahr("Unfug") is None
    assert kiauslese._jahr(True) is None           # bool ist kein Jahr


def _leeres_ergebnis():
    return {"jahr": None, "monat": None, "datum": None, "kategorie": "",
            "ist_kosten": True, "sache": "", "betrag": None}


def test_abrechnungsjahr_schlaegt_das_rechnungsdatum(monkeypatch):
    monkeypatch.setattr(kiauslese, "verfuegbar", lambda *a, **k: True)
    monkeypatch.setattr(kiauslese, "lies_beleg", lambda *a, **k: {
        "datum": "2026-01-30", "abrechnungsjahr": 2025, "betrag": 256.36,
        "kategorie": "Nebenkosten"})
    erg = _leeres_ergebnis()
    ocr._ki_ergaenzen(erg, "beliebiger belegtext", ki_key="x")
    assert erg["datum"] == "2026-01-30"    # Rechnungsdatum bleibt erhalten
    assert erg["jahr"] == 2025             # Ablage folgt dem Abrechnungsjahr


def test_ohne_abrechnungsjahr_bleibt_das_rechnungsjahr(monkeypatch):
    monkeypatch.setattr(kiauslese, "verfuegbar", lambda *a, **k: True)
    monkeypatch.setattr(kiauslese, "lies_beleg", lambda *a, **k: {
        "datum": "2025-03-15", "abrechnungsjahr": None})
    erg = _leeres_ergebnis()
    ocr._ki_ergaenzen(erg, "text", ki_key="x")
    assert erg["jahr"] == 2025             # Fallback: Jahr aus dem Datum
