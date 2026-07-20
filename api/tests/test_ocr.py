"""Texterkennung: das Herauslesen von Betrag und Datum.

Die Erkennung selbst braucht Tesseract; geprüft wird hier das Auswerten des
Textes — das ist der Teil, der falsch liegen kann.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.ocr import betrag_aus_text, datum_aus_text, erkenne  # noqa: E402

RECHNUNG = """
Stadtwerke Musterstadt
Rechnungsdatum 14.03.2025
Kundennummer 4711

Verbrauch Wasser              812,40
Grundpreis                     87,60
Zwischensumme                 900,00
Umsatzsteuer 19 %             171,00
Gesamtbetrag                1.071,00
"""


def test_endbetrag_schlaegt_die_teilsummen():
    """Ohne Schlüsselwort gewänne 900,00 nicht — aber 1.071,00 ist der Endbetrag."""
    assert betrag_aus_text(RECHNUNG) == 1071.00


def test_tausenderpunkt_wird_richtig_gelesen():
    assert betrag_aus_text("Gesamtbetrag 12.345,67") == 12345.67
    assert betrag_aus_text("Summe 89,90") == 89.90


def test_ohne_schluesselwort_gewinnt_der_groesste_betrag():
    assert betrag_aus_text("Posten A 120,00\nPosten B 450,50") == 450.50


def test_ohne_betrag_kommt_nichts():
    assert betrag_aus_text("Kein Geld weit und breit") is None
    assert betrag_aus_text("") is None


def test_rechnungsdatum_wird_erkannt():
    assert datum_aus_text(RECHNUNG) == date(2025, 3, 14)


def test_unsinnige_datumsangaben_werden_verworfen():
    """Seitenzahlen und Telefonnummern dürfen kein Datum ergeben."""
    assert datum_aus_text("Seite 1.2.3") is None          # Jahr 2003 -> zu alt
    assert datum_aus_text("32.13.2025") is None           # gibt es nicht


def test_zweistelliges_jahr_wird_ergaenzt():
    assert datum_aus_text("Beleg vom 05.06.24") == date(2024, 6, 5)


def test_erkenne_liefert_ohne_tesseract_eine_klare_antwort():
    """Fehlt das Programm, ist das kein Fehler — nur kein Vorschlag."""
    ergebnis = erkenne(b"kein echtes bild")
    assert set(ergebnis) >= {"moeglich", "betrag", "datum"}
    if not ergebnis["moeglich"]:
        assert ergebnis["betrag"] is None
        assert "eingerichtet" in ergebnis["hinweis"]
