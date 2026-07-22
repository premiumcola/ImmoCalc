"""Texterkennung: das Herauslesen von Betrag und Datum.

Ein Bild braucht Tesseract; ein maschinengeschriebenes PDF nicht — dessen Text
steht in der Datei. Geprüft wird hier beides: das Auswerten des Textes (der
Teil, der falsch liegen kann) und der Weg vom PDF zum Vorschlag.
"""
import io
import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import ocr, pdftext  # noqa: E402
from app.ocr import (betrag_aus_text, datum_aus_text,  # noqa: E402
                     erkenne, kategorie_aus_text, text_aus_beleg)

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


# --------------------------------------------------------------------------
# CLXX: der Betrag stand fett auf dem Blatt — und wurde nicht erkannt
#
# Die Rechnung war ein maschinengeschriebenes PDF, kein Scan. Ihr Text stand
# als Zeichenstrom in der Datei; die Erkennung schickte sie trotzdem durch die
# Bilderkennung, fand kein Tesseract und meldete nichts.
# --------------------------------------------------------------------------

def mini_pdf(zeilen: list[str]) -> bytes:
    """Ein winziges PDF mit bekanntem Inhalt — von Hand gebaut.

    Keine Bibliothek und keine Beispieldatei im Repo: der Test soll die Kette
    prüfen, nicht einen Fundus pflegen. Eine Seite, eine Standardschrift, die
    Zeilen untereinander.
    """
    inhalt = "BT /F1 11 Tf 40 780 Td 15 TL\n" + "".join(
        "({}) Tj T*\n".format(z.replace("\\", r"\\").replace("(", r"\(")
                               .replace(")", r"\)"))
        for z in zeilen) + "ET"
    strom = inhalt.encode("latin-1", "replace")
    objekte = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]"
        b"/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica"
        b"/Encoding/WinAnsiEncoding>>",
        b"<</Length %d>>stream\n" % len(strom) + strom + b"\nendstream",
    ]
    datei = bytearray(b"%PDF-1.4\n")
    stellen = []
    for nr, koerper in enumerate(objekte, 1):
        stellen.append(len(datei))
        datei += b"%d 0 obj\n" % nr + koerper + b"\nendobj\n"
    tabelle = len(datei)
    datei += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objekte) + 1)
    for stelle in stellen:
        datei += b"%010d 00000 n \n" % stelle
    datei += (b"trailer\n<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF\n"
              % (len(objekte) + 1, tabelle))
    return bytes(datei)


# --------------------------------------------------------------------------
# CLXXIX: ein reiner Scan trägt keinen Text — nur ein Bild der Seite. Tesseract
# liest aber keine PDFs, nur Bilder. Es fehlte der Schritt Seite -> Bild ->
# Tesseract. Gerastert wird mit pypdfium2; die echte Erkennung greift erst im
# Container mit Tesseract, hier wird nur die Verdrahtung geprüft.
# --------------------------------------------------------------------------

def bild_pdf(breite: int = 200, hoehe: int = 120) -> bytes:
    """Ein winziges PDF ganz ohne Textschicht — nur ein Bild-XObject.

    So sieht ein Scan aus: `pdftext.text_aus_pdf` findet darin keinen Text und
    der Beleg nimmt den Rasterweg. Von Hand gebaut wie `mini_pdf`, ohne
    Bibliothek und ohne Beispieldatei — ein 2×2-Bild, über die ganze Seite
    gezogen."""
    pixel = bytes([200, 200, 200,  40, 40, 40,
                    40, 40, 40,   200, 200, 200])   # 2×2 RGB
    inhalt = ("q %d 0 0 %d 0 0 cm /Im0 Do Q" % (breite, hoehe)).encode("latin-1")
    objekte = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 %d %d]"
        b"/Resources<</XObject<</Im0 4 0 R>>>>/Contents 5 0 R>>" % (breite, hoehe),
        b"<</Type/XObject/Subtype/Image/Width 2/Height 2/ColorSpace/DeviceRGB"
        b"/BitsPerComponent 8/Length %d>>stream\n" % len(pixel)
        + pixel + b"\nendstream",
        b"<</Length %d>>stream\n" % len(inhalt) + inhalt + b"\nendstream",
    ]
    datei = bytearray(b"%PDF-1.4\n")
    stellen = []
    for nr, koerper in enumerate(objekte, 1):
        stellen.append(len(datei))
        datei += b"%d 0 obj\n" % nr + koerper + b"\nendobj\n"
    tabelle = len(datei)
    datei += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objekte) + 1)
    for stelle in stellen:
        datei += b"%010d 00000 n \n" % stelle
    datei += (b"trailer\n<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF\n"
              % (len(objekte) + 1, tabelle))
    return bytes(datei)


def _ppm_groesse(daten: bytes) -> tuple[int, int]:
    """Breite und Höhe aus dem P6-Kopf: „P6\\n{breite} {hoehe}\\n255\\n…"."""
    assert daten.startswith(b"P6"), "kein PPM"
    _, masse, _rest = daten.split(b"\n", 2)
    breite, hoehe = masse.split()
    return int(breite), int(hoehe)


def test_scan_pdf_wird_zu_einem_bild_der_erwarteten_groesse():
    """Die Rasterstufe für sich — läuft ohne Tesseract.

    Ein Bild-PDF (keine Textschicht) wird Seite für Seite gerendert. Erwartet
    ist genau die Größe, die pypdfium2 direkt aus derselben Seite liefert, und
    sie ist deutlich größer als die Seite in Punkten — also hochskaliert."""
    if not pdftext.kann_rastern():
        pytest.skip("pypdfium2 ist hier nicht installiert")
    import pypdfium2 as pdfium

    roh = bild_pdf(200, 120)
    # Ein Scan: kein eingebetteter Text.
    assert pdftext.text_aus_pdf(roh).strip() == ""

    bilder = pdftext.seiten_als_bilder(roh)
    assert len(bilder) == 1

    doc = pdfium.PdfDocument(roh)
    bezug = doc[0].render(scale=pdftext.RASTER_SKALIERUNG, rev_byteorder=True)
    erwartet = (bezug.width, bezug.height)
    doc.close()

    assert _ppm_groesse(bilder[0]) == erwartet
    breite, hoehe = erwartet
    assert breite > 200 and hoehe > 120       # gegenüber den Punkten skaliert


def test_text_pdf_geht_nicht_ueber_die_rasterung(monkeypatch):
    """Verdrahtung: ein Text-PDF wird über `pdftext` gelesen — es wird nie
    gerastert. Gerufen würde die Rasterung nur, wenn kein Text da ist."""
    gerufen = []
    monkeypatch.setattr(pdftext, "seiten_als_bilder",
                        lambda *a, **k: gerufen.append(1) or [])
    roh = mini_pdf(["Stadtwerke Musterstadt", "Rechnungsdatum 14.03.2025",
                    "Gesamtbetrag 1.071,00"])
    text = ocr.text_aus_beleg(roh)
    assert "Gesamtbetrag" in text
    assert not gerufen                        # kein Rasterweg nötig


def test_bild_pdf_nimmt_den_rasterweg(monkeypatch):
    """Verdrahtung: ein PDF ohne Textschicht wird gerastert und Bild für Bild
    durch Tesseract gelesen. Ohne echtes Tesseract geprüft — die Bilderkennung
    ist gestellt, gerendert wird aber wirklich."""
    if not pdftext.kann_rastern():
        pytest.skip("pypdfium2 ist hier nicht installiert")
    roh = bild_pdf(200, 120)
    assert pdftext.text_aus_pdf(roh).strip() == ""

    # Tesseract vortäuschen, damit der Rasterweg auch ohne das Programm greift,
    # und seine Lesung durch eine bekannte Antwort ersetzen.
    monkeypatch.setattr(ocr, "verfuegbar", lambda: True)
    gelesen = []

    def gestelltes_tesseract(daten: bytes) -> str:
        gelesen.append(daten)
        return "Gesamtbetrag 555,00"

    monkeypatch.setattr(ocr, "text_aus_bild", gestelltes_tesseract)

    ergebnis = erkenne(roh)
    assert ergebnis["betrag"] == 555.00
    # Was Tesseract bekam, waren echte Rasterbilder — kein durchgereichtes PDF.
    assert gelesen and all(bild.startswith(b"P6") for bild in gelesen)


def test_tesseract_liest_den_gerasterten_scan():
    """Die echte Erkennung eines Scans — nur mit Tesseract. Die Devbox hat
    keins und überspringt; im Container greift sie wirklich.

    Ein Bild-PDF mit gemaltem Text (kein Zeichenstrom) wird gerastert und
    gelesen; erwartet ist der aufgedruckte Betrag."""
    if not ocr.verfuegbar():
        pytest.skip("Tesseract ist hier nicht installiert")
    if not pdftext.kann_rastern():
        pytest.skip("pypdfium2 ist hier nicht installiert")
    Image = pytest.importorskip("PIL.Image")     # nur zum Erzeugen des Fixtures
    ImageDraw = pytest.importorskip("PIL.ImageDraw")

    bild = Image.new("RGB", (1000, 240), "white")
    zeichner = ImageDraw.Draw(bild)
    zeichner.text((40, 90), "Gesamtbetrag  555,00 EUR", fill="black")
    puffer = io.BytesIO()
    bild.save(puffer, "PDF")                       # Bild-PDF, keine Textschicht
    roh = puffer.getvalue()
    assert pdftext.text_aus_pdf(roh).strip() == ""

    ergebnis = erkenne(roh)
    assert ergebnis["betrag"] == 555.00


def test_pdf_mit_text_braucht_keine_bilderkennung():
    """Die dauerhafte Zusicherung zu CLXX: was als Text im PDF steht, wird
    gelesen — auch wo kein Tesseract eingerichtet ist."""
    roh = mini_pdf(["Stadtwerke Musterstadt", "Rechnungsdatum 14.03.2025",
                    "Verbrauch Wasser 812,40", "Gesamtbetrag 1.071,00"])
    assert pdftext.ist_pdf(roh)
    assert "Gesamtbetrag" in text_aus_beleg(roh)

    ergebnis = erkenne(roh)
    assert ergebnis["moeglich"] is True
    assert ergebnis["betrag"] == 1071.00
    assert ergebnis["datum"] == "2025-03-14"
    assert ergebnis["kategorie"] == "Nebenkosten"


def test_ohne_lesbaren_text_bleibt_es_bei_einer_begruendung():
    """Kein Vorschlag ist in Ordnung — kommentarlos nichts nicht."""
    ergebnis = erkenne(b"weder PDF noch Bild")
    assert ergebnis["betrag"] is None
    assert ergebnis["hinweis"]


def test_kein_pdf_wird_nicht_als_eines_gelesen():
    assert pdftext.ist_pdf(b"") is False
    assert pdftext.ist_pdf(b"\xff\xd8\xff irgendein JPEG") is False
    assert pdftext.text_aus_pdf(b"\xff\xd8\xff irgendein JPEG") == ""


def test_betrag_auch_mit_punkt_als_trennzeichen():
    """Die Rechnung aus CLXX druckt „104.15", nicht „104,15" — und die
    Bilderkennung liest ein Komma ohnehin gern als Punkt."""
    assert betrag_aus_text("Rechnungsbetrag EUR 104.15") == 104.15
    assert betrag_aus_text("Summe 1,234.56") == 1234.56


def test_ein_datum_ist_kein_betrag():
    """„12.02.2026" darf nie als 12,02 EUR durchgehen."""
    assert betrag_aus_text("Datum: 12.02.2026") is None
    assert betrag_aus_text("Zeitraum 01.01.2025 - 31.12.2025") is None


def test_deutsche_schreibweise_bleibt_unberuehrt():
    """Neben „1.234,56" steht auf derselben Rechnung die Anzahl „1.00". Der
    Punkt darf die deutsche Lesart nicht durcheinanderbringen."""
    assert betrag_aus_text("Anzahl 1.00\nGesamtbetrag 1.234,56") == 1234.56
    assert betrag_aus_text("Menge 3.00 Stueck\nSumme 89,90") == 89.90


def test_gesperrter_satz_wird_wieder_zu_einem_betrag():
    """Manche Blätter setzen jedes Zeichen einzeln; im Layout wird aus
    „1.225,68 EUR" dann „1. 2 2 5 , 6 8  E U R". Belegt an der
    Gebäudeversicherung im Bestand."""
    gesperrt = ("  vo  n     1. 2  2  5 , 6  8     E  U  R     "
                "p  l  u  s     G  e  b  ü  h  re  n")
    assert betrag_aus_text(pdftext._entspreizt(gesperrt)) == 1225.68
    # Eine normal gesetzte Zeile bleibt Zeichen für Zeichen dieselbe
    normal = "Rechnungsbetrag                    €           104.15"
    assert pdftext._entspreizt(normal) == normal


# --------------------------------------------------------------------------
# Der echte Beleg. Er liegt im Bestand des Nutzers, nicht im Repo — ohne ihn
# wird übersprungen, damit die Testreihe auch ohne die privaten Daten läuft.
# --------------------------------------------------------------------------

BESTAND = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "immo_DATA")
KAMINRECHNUNG = os.path.join(
    BESTAND, "Eschenau - Laufer Str. 5", "60_Nebenkosten", "2026",
    "Rechnung_2026_01.pdf")


def test_echte_kaminrechnung_gibt_betrag_und_datum_her():
    """CLXX am Original: Rechnungsbetrag 104,15 EUR, Datum 12.02.2026.

    Nicht 87,52 (netto), nicht 16,63 (MWSt) — und nicht der 26.02.2026, das
    ist das Zahlungsziel.
    """
    if not os.path.exists(KAMINRECHNUNG):
        pytest.skip("Bestandsdaten liegen hier nicht")
    ergebnis = erkenne(open(KAMINRECHNUNG, "rb").read())
    assert ergebnis["betrag"] == 104.15
    assert ergebnis["datum"] == "2026-02-12"
    assert ergebnis["kategorie"] == "Nebenkosten"
    assert ergebnis["sache"] == "Schornsteinfeger"


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
