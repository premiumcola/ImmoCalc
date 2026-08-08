"""N288-B5 — die gemeinsamen PDF-Bausteine.

`abrechnung_pdf` und `tankabrechnung_pdf` hielten `_escape`, `_pdf`, `UMLAUTE`
und den Dateinamen-Filter je einmal wortgleich; die Breitenrechnung war
zusätzlich auseinandergedriftet (exakte Tabelle hier, Schätzung dort). Diese
Tests halten fest, dass beide Module denselben Kern benutzen und dass die
Breiten wirklich nach der Helvetica-Tabelle gerechnet werden.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import abrechnung_pdf as ab  # noqa: E402
from app import pdfkern  # noqa: E402
from app import tankabrechnung_pdf as tank  # noqa: E402


def test_beide_module_teilen_denselben_kern():
    """Ein Baustein, nicht zwei Kopien — geprüft an der Objekt-Identität."""
    for modul in (ab, tank):
        assert modul._escape is pdfkern.escape
        assert modul._pdf is pdfkern.pdf
        assert modul._breite is pdfkern.breite
        assert modul.sauber is pdfkern.sauber
        assert modul.UMLAUTE is pdfkern.UMLAUTE
        assert (modul.SEITE_B, modul.SEITE_H) == (pdfkern.SEITE_B,
                                                  pdfkern.SEITE_H)


def test_escape_entschaerft_die_steuerzeichen():
    """Klammern und Rückstriche beenden sonst die PDF-Zeichenkette."""
    assert pdfkern.escape("Haus (Hof) 50%") == rb"Haus \(Hof\) 50%"
    assert pdfkern.escape(r"C:\Pfad") == rb"C:\\Pfad"
    assert pdfkern.escape(None) == b""


def test_escape_schreibt_cp1252_nicht_utf8():
    """WinAnsiEncoding ist cp1252: Gedankenstrich und Euro haben dort ein
    einzelnes Byte — als UTF-8 stünden zwei bzw. drei im Strom."""
    assert pdfkern.escape("2025 – 80,75 €") == b"2025 \x96 80,75 \x80"


def test_breite_rechnet_nach_der_helvetica_tabelle():
    """Exakt, nicht geschätzt: 'Kosten' in Helvetica-Bold 8 pt misst
    (722+611+556+333+556+611)/1000 × 8 = 27,112 pt."""
    assert round(pdfkern.breite("Kosten", 8, True), 3) == 27.112
    # Ein 'i' ist deutlich schmaler als ein 'm' — eine Schätzung mit festem
    # Faktor kann das nicht abbilden.
    assert pdfkern.breite("i", 10) == 2.22
    assert pdfkern.breite("m", 10) == 8.33
    assert pdfkern.breite("", 10) == 0.0


def test_breite_kennt_die_deutschen_sonderzeichen():
    """Umlaute und Gedankenstrich stehen in jeder Abrechnung — sie dürfen
    nicht auf den Ersatzwert 556 fallen."""
    assert pdfkern.breite("Ä", 10) == 6.67
    assert pdfkern.breite("ß", 10) == 6.11
    assert pdfkern.breite("–", 10) == 5.56


def test_breite_waechst_linear_mit_dem_schriftgrad():
    assert round(pdfkern.breite("Summe", 20), 4) == round(
        pdfkern.breite("Summe", 10) * 2, 4)


def test_pdf_ist_ein_gueltiger_einseitiger_bogen():
    roh = pdfkern.pdf(b"BT /F1 10 Tf 1 0 0 1 50 50 Tm (Hallo) Tj ET", "Titel")
    assert roh.startswith(b"%PDF-1.4\n")
    assert roh.rstrip().endswith(b"%%EOF")
    assert b"/Count 1" in roh
    assert roh.count(b"/Type /Page ") == 1
    assert b"/Encoding /WinAnsiEncoding" in roh
    assert b"(Titel)" in roh


def test_pdf_querverweistabelle_zeigt_auf_die_objekte():
    """Ohne stimmige xref-Offsets öffnet kein Betrachter die Datei."""
    roh = pdfkern.pdf(b"", "Prüfung")
    start = int(roh.split(b"startxref\n")[1].split(b"\n")[0])
    assert roh[start:start + 4] == b"xref"
    zeilen = roh[start:].split(b"\n")
    anzahl = int(zeilen[1].split()[1])
    for nummer, zeile in enumerate(zeilen[3:anzahl + 2], start=1):
        stelle = int(zeile.split()[0])
        assert roh[stelle:].startswith(b"%d 0 obj" % nummer)


def test_pdf_meldet_die_stromlaenge_korrekt():
    strom = b"1 0 0 1 0 0 cm"
    roh = pdfkern.pdf(strom, "x")
    assert b"<< /Length %d >>" % len(strom) in roh


def test_sauber_ersetzt_umlaute_und_sonderzeichen():
    assert pdfkern.sauber("Größenstraße (Hinterhaus)") == \
        "Groessenstrasse-Hinterhaus"
    assert pdfkern.sauber("Müller & Söhne") == "Mueller-Soehne"
    assert pdfkern.sauber("") == ""
    assert pdfkern.sauber("---") == ""


def test_dateinamen_beider_module_nutzen_denselben_filter():
    assert ab.pdf_dateiname("Größenstraße", "01.01.2025 – 31.12.2025",
                            "Müller & Söhne") == \
        "Abrechnung_Groessenstrasse_2025_Mueller-Soehne.pdf"
    assert tank.tank_pdf_dateiname("Größenstraße", "Q3 2025", "Müller") == \
        "E-Tankstelle_Groessenstrasse_Q3-2025_Mueller.pdf"


def test_tankabrechnung_setzt_spalten_exakt_buendig():
    """Die Tankabrechnung schätzte ihre Textbreiten und ließ die
    rechtsbündigen Spalten ausfransen. Jetzt endet jeder Wert der Spalte
    auf demselben Punkt."""
    blatt = tank.Blatt()
    kante = 500.0
    for wert in ("1.234,56 EUR", "9,99 EUR", "Kosten"):
        blatt.rechts(kante, 100.0, wert, 9.5, False)
    for teil, wert in zip(blatt.teile, ("1.234,56 EUR", "9,99 EUR", "Kosten")):
        x = float(teil.split(b" Tm ")[0].split()[-2])
        assert abs(x + pdfkern.breite(wert, 9.5) - kante) < 0.01
