"""Die Abrechnung als PDF — Aufbau, Umlaute, Einzelposten."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.abrechnung_pdf import abrechnung_pdf, pdf_dateiname  # noqa: E402

WERTE = {"kosten": 1240.55, "vorauszahlungen": 1500.0, "saldo": 259.45}
POSTEN = [{"kostenart": "Heizung", "betrag": 800.30},
          {"kostenart": "Wasser", "betrag": 440.25}]


def test_pdf_ist_ein_gueltiges_pdf():
    daten = abrechnung_pdf("Musterstraße 1", "01.01.2025 – 31.12.2025",
                           "Wohnung EG", WERTE, POSTEN)
    assert daten.startswith(b"%PDF-1.4")
    assert daten.rstrip().endswith(b"%%EOF")
    assert b"xref" in daten and b"trailer" in daten
    assert daten.count(b" obj") == 7          # Katalog, Seiten, Seite, Strom, 2 Fonts, Info


def test_umlaute_und_klammern_brechen_nichts():
    daten = abrechnung_pdf("Größenstraße (Hinterhaus)", "2025", "Müller & Söhne",
                           WERTE)
    assert b"Gr\xf6\xdfenstra\xdfe" in daten          # cp1252 = WinAnsi
    assert br"\(Hinterhaus\)" in daten                # Klammer maskiert


def test_gedankenstrich_im_zeitraum_bleibt_erhalten():
    """Der Zeitraum steht überall mit '–'. In latin-1 gäbe es dafür ein '?'."""
    daten = abrechnung_pdf("Haus", "01.01.2025 – 31.12.2025", "EG", WERTE)
    assert b"01.01.2025 \x96 31.12.2025" in daten
    assert b"?" not in daten


def test_einzelposten_stehen_im_pdf():
    daten = abrechnung_pdf("Haus", "2025", "EG", WERTE, POSTEN)
    assert b"Heizung" in daten and b"Wasser" in daten
    assert b"800,30 EUR" in daten                      # deutsche Schreibweise


def test_dateiname_ist_dateisystemtauglich():
    name = pdf_dateiname("Musterstraße 1 // Wohnung 2", "01.01.2025 – 31.12.2025",
                         "Müller, Anna")
    assert name.endswith("_2025_Mueller-Anna.pdf")
    assert name.isascii()
    assert not set(name) & set('<>:"/\\|?*')
