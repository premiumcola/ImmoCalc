"""Texterkennung: das Herauslesen von Betrag und Datum.

Die Erkennung selbst braucht Tesseract; geprüft wird hier das Auswerten des
Textes — das ist der Teil, der falsch liegen kann.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.ocr import (betrag_aus_text, datum_aus_text,  # noqa: E402
                     erkenne, kategorie_aus_text)

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


def test_abrechnungszeitraum_wird_nicht_fuer_das_belegdatum_gehalten():
    """Der belegte Fehlgriff: die Erkennung nahm den 01.01.2024 aus der Zeile
    'Abrechnungszeitraum' statt des Rechnungsdatums."""
    text = ("Rechnungsdatum 14.03.2025\n"
            "Abrechnungszeitraum 01.01.2024 - 31.12.2024\n"
            "Bitte ueberweisen Sie bis zum 28.03.2025.\n")
    assert datum_aus_text(text) == date(2025, 3, 14)


def test_ohne_beschriftung_gewinnt_das_spaeteste_datum():
    """Ein Zeitraumbeginn steht weiter vorn — gemeint ist er trotzdem nie."""
    assert datum_aus_text("01.01.2024 bis 31.12.2024\n05.02.2025\n") \
        == date(2025, 2, 5)


def test_zahlungsziel_gilt_nicht_als_belegdatum():
    assert datum_aus_text("Zahlbar bis 30.04.2025") is None


def test_kategorie_kommt_aus_dem_text():
    """Ein Kamerascan heisst 'scan.pdf' — nur der Inhalt verrät die Art."""
    assert kategorie_aus_text(RECHNUNG) == "Nebenkosten"
    assert kategorie_aus_text("Grundsteuerbescheid der Stadt") == "Steuer"
    assert kategorie_aus_text("Versicherungsschein Police 4412-9") == "Versicherung"
    assert kategorie_aus_text("Darlehen Nr. 77, Tilgung und Zinsbindung") == "Kredit"
    assert kategorie_aus_text("Mietvertrag über Wohnraum, Kaution") == "Mietvertrag"
    assert kategorie_aus_text("Irgendein Zettel ohne Anhaltspunkt") == ""


def test_haeufigkeit_entscheidet_nicht_der_briefkopf():
    """'Versicherung' im Absender darf eine Heizkostenabrechnung nicht kippen."""
    text = ("Allianz Versicherung AG\n"
            "Heizkostenabrechnung\nHeizkosten 2.880,00\n"
            "Heizkosten Verteilung nach Verbrauch\n")
    assert kategorie_aus_text(text) == "Nebenkosten"


def test_unsinnige_datumsangaben_werden_verworfen():
    """Seitenzahlen und Telefonnummern dürfen kein Datum ergeben."""
    assert datum_aus_text("Seite 1.2.3") is None          # Jahr 2003 -> zu alt
    assert datum_aus_text("32.13.2025") is None           # gibt es nicht


def test_zweistelliges_jahr_wird_ergaenzt():
    assert datum_aus_text("Beleg vom 05.06.24") == date(2024, 6, 5)


def test_erkenne_liefert_ohne_tesseract_eine_klare_antwort():
    """Fehlt das Programm, ist das kein Fehler — nur kein Vorschlag."""
    ergebnis = erkenne(b"kein echtes bild")
    # Dieselben Schlüssel in beiden Fällen — die Oberfläche liest immer gleich
    assert set(ergebnis) >= {"moeglich", "betrag", "datum", "jahr", "monat",
                             "kategorie", "sache"}
    if not ergebnis["moeglich"]:
        assert ergebnis["betrag"] is None
        assert "eingerichtet" in ergebnis["hinweis"]


# --------------------------------------------------------------------------
# CXXIII: nicht „Heizkosten", sondern die Sache selbst
# --------------------------------------------------------------------------

def test_sache_ist_spezifischer_als_die_art():
    """Wörtlich: „bitte macht die Benennung nicht Heizkosten, sondern am
    besten spezifischer Heizkosten-Öl."

    Die Art bestimmt den Ordner, die Sache den Dateinamen."""
    from app.ocr import sache_aus_text

    assert kategorie_aus_text("Rechnung über 3000 Liter Heizöl") == "Nebenkosten"
    assert sache_aus_text("Rechnung über 3000 Liter Heizöl") == "Heizöl"
    assert sache_aus_text("Abrechnung Kaltwasser je Wohneinheit") == "Kaltwasser"
    assert sache_aus_text("Bescheid über die Grundsteuer") == "Grundsteuer"
    assert sache_aus_text("Müllgebühren der Gemeinde") == "Müll"
    assert sache_aus_text("Irgendein Zettel ohne Anhaltspunkt") == ""


def test_sache_bleibt_leer_wo_schon_der_ordner_so_heisst():
    """CXXII: „Nebenkosten" im Ordner 60_Nebenkosten wäre die Doppelnennung.
    Dann trägt die Bezeichnung des Nutzers den Namen, nicht die Erkennung."""
    from app.ocr import sache_aus_dateiname, sache_aus_text

    assert kategorie_aus_text("Nebenkostenabrechnung 2024") == "Nebenkosten"
    assert sache_aus_text("Nebenkostenabrechnung 2024") == ""
    assert sache_aus_dateiname("nebenkosten 2024") == ""


def test_kurzwoerter_ergeben_mit_endung_keinen_treffer():
    """„Müller" ist kein Müll und „Mueller" auch nicht — dieselbe Regel wie
    XCIII, nur eine Silbe später. „Müllgebühren" zählt weiter."""
    from app.ocr import kategorie_aus_dateiname

    for name in ["Rechnung Mueller 2024.pdf", "Notar Müller.pdf",
                 "Kaufvertrag Berggasse 5.pdf", "Öle und Fette GmbH.pdf"]:
        lesbar = name.lower().replace("_", " ").replace("-", " ")
        assert kategorie_aus_dateiname(lesbar) == ("", 0), name

    for name, erwartet in [("2025-01-muell.pdf", "Müll"),
                           ("Müllgebühren 2024.pdf", "Müll"),
                           ("2025-10-oel-2729,91€.pdf", "Heizöl"),
                           ("Öl-suft-2025.pdf", "Heizöl")]:
        lesbar = name.lower().replace("_", " ").replace("-", " ")
        assert kategorie_aus_dateiname(lesbar)[0] == "Nebenkosten", name
        from app.ocr import sache_aus_dateiname
        assert sache_aus_dateiname(lesbar) == erwartet, name
