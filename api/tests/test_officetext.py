"""N304 — Text aus Office-Dateien, ohne Bibliothek und ohne KI-Aufruf.

Von 125 Belegen ohne Auslese hatten nur 25 eine Textschicht — **56 waren
Office-Dateien**. Sie galten als „kein Text", obwohl ihr Inhalt reiner Text
ist: die modernen Formate sind ZIP-Archive mit XML darin.
"""
import io
import os
import sys
import tempfile
import zipfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_officetext.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import ocr  # noqa: E402
from app.officetext import ist_office, text_aus_office  # noqa: E402

_XL = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _xlsx(zeilen: list[list[str]]) -> bytes:
    """Eine Tabelle im echten Format: Texte in `sharedStrings`, Blatt mit Index."""
    texte: list[str] = []
    for zeile in zeilen:
        for wert in zeile:
            if wert not in texte:
                texte.append(wert)
    si = "".join(f"<si><t>{t}</t></si>" for t in texte)
    rows = ""
    for nr, zeile in enumerate(zeilen, 1):
        zellen = "".join(
            f'<c r="A{nr}" t="s"><v>{texte.index(w)}</v></c>' for w in zeile)
        rows += f'<row r="{nr}">{zellen}</row>'
    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("xl/sharedStrings.xml",
                   f'<sst xmlns="{_XL}">{si}</sst>')
        z.writestr("xl/worksheets/sheet1.xml",
                   f'<worksheet xmlns="{_XL}"><sheetData>{rows}</sheetData></worksheet>')
    return puffer.getvalue()


def _docx(absaetze: list[str]) -> bytes:
    ps = "".join(f"<w:p><w:r><w:t>{a}</w:t></w:r></w:p>" for a in absaetze)
    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml",
                   f'<w:document xmlns:w="{_W}"><w:body>{ps}</w:body></w:document>')
    return puffer.getvalue()


def test_tabelle_wird_lesbar():
    roh = _xlsx([["Kostenart", "Betrag"], ["Wasser", "250,98"]])
    text = text_aus_office(roh)
    assert "Kostenart" in text and "Wasser" in text and "250,98" in text
    # Zellen einer Zeile stehen nebeneinander, nicht untereinander.
    assert "Wasser\t250,98" in text


def test_gemeinsame_zeichenkette_wird_aufgeloest():
    """Ohne `sharedStrings` käme lauter „0" heraus — der Blatt-Eintrag ist
    nur ein Index."""
    text = text_aus_office(_xlsx([["Mieter"], ["Mieter"]]))
    assert text.count("Mieter") == 2
    assert "0" not in text.replace("sheet1", "")


def test_brief_wird_lesbar():
    text = text_aus_office(_docx(["Sehr geehrte Damen und Herren,",
                                  "anbei die Abrechnung 2025."]))
    assert "Sehr geehrte" in text
    assert "Abrechnung 2025" in text


def test_keine_office_datei_ergibt_leer():
    assert text_aus_office(b"%PDF-1.4 kein Office") == ""
    assert text_aus_office(b"") == ""


def test_kaputtes_archiv_wirft_nicht():
    """Eine beschädigte Datei ist kein Fehler, sondern schlicht kein Text."""
    assert text_aus_office(b"PK\x03\x04 kaputt und abgeschnitten") == ""


def test_zip_ohne_office_inhalt_ergibt_leer():
    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w") as z:
        z.writestr("beliebig.txt", "nur ein ZIP")
    assert text_aus_office(puffer.getvalue()) == ""


def test_ist_office_erkennt_die_zip_marke():
    assert ist_office(_docx(["x"]))
    assert not ist_office(b"%PDF-1.4")


def test_die_kette_nimmt_office_mit():
    """`text_aus_beleg` ist der Weg, den alle Ausleser gehen — dort muss die
    neue Stufe hängen, nicht nur im eigenen Modul."""
    roh = _xlsx([["Hausgeld"], ["244,00"]])
    assert "Hausgeld" in ocr.text_aus_beleg(roh)


def test_pdf_bleibt_dem_pdf_weg_treu():
    """Die neue Stufe darf sich nie vor die bestehenden drängen."""
    assert ocr.text_aus_beleg(b"%PDF-1.4\nkein echtes PDF") is not None


# --------------------------------------------------------------------------
# N306 — Dateien, die schon Text sind
# --------------------------------------------------------------------------

def test_klartext_wird_gelesen():
    from app.officetext import text_aus_klartext
    assert "Wasser;250,98" in text_aus_klartext(
        "Kostenart;Betrag\nWasser;250,98\n".encode())
    assert "Betreff: Abrechnung" in text_aus_klartext(
        b"From: amt@example.de\nBetreff: Abrechnung 2025\n")


def test_umlaute_ueberleben_beide_kodierungen():
    from app.officetext import text_aus_klartext
    assert "Müllgebühren" in text_aus_klartext("Müllgebühren\n".encode("utf-8"))
    assert "Müllgebühren" in text_aus_klartext("Müllgebühren\n".encode("cp1252"))


def test_svg_wird_lesbar_wenn_auch_mit_marken():
    from app.officetext import text_aus_klartext
    text = text_aus_klartext(
        b'<svg xmlns="http://www.w3.org/2000/svg"><text>Lageplan Nord</text></svg>')
    assert "Lageplan Nord" in text


def test_binaeres_wird_nicht_als_text_ausgegeben():
    """Latin-1 dekodiert jedes Byte — erkannt wird an den Steuerzeichen."""
    from app.officetext import text_aus_klartext
    assert text_aus_klartext(bytes(range(256)) * 20) == ""
    assert text_aus_klartext(b"\x89PNG\r\n\x1a\n" + bytes(range(200))) == ""


def test_pdf_und_office_gehen_ihren_eigenen_weg():
    """Die Klartext-Stufe darf sich nie vor die spezialisierten drängen."""
    from app.officetext import text_aus_klartext
    assert text_aus_klartext(b"%PDF-1.4 irgendwas") == ""
    assert text_aus_klartext(_docx(["Brief"])) == ""


def test_die_kette_nimmt_klartext_mit():
    assert "Schornsteinfeger" in ocr.text_aus_beleg(
        "Rechnung Schornsteinfeger 2025\n".encode())


# --------------------------------------------------------------------------
# N305 — XFA-Formulare tragen nur einen Platzhalter
# --------------------------------------------------------------------------

_XFA = ("Please wait...\nIf this message is not eventually replaced by the "
        "proper contents of the document, your PDF viewer may not be able to "
        "display this type of document.\nYou can upgrade to the latest version "
        "of Adobe Reader.")


def test_xfa_platzhalter_gilt_nicht_als_text():
    """Der Platzhalter machte `text.strip()` wahr — die Kette hielt den Beleg
    für gelesen und sprang gar nicht erst in die Rasterung."""
    from app.pdftext import _nur_xfa_platzhalter
    assert _nur_xfa_platzhalter(_XFA)


def test_echter_beleg_wird_nicht_verworfen():
    """Ein Dokument, das den Satz zufällig zitiert, muss durchkommen."""
    from app.pdftext import _nur_xfa_platzhalter
    echt = _XFA + "\n" + ("Rechnung Nr. 4711 über 1.250,98 EUR. " * 40)
    assert not _nur_xfa_platzhalter(echt)


def test_leerer_und_normaler_text_bleiben_unberuehrt():
    from app.pdftext import _nur_xfa_platzhalter
    assert not _nur_xfa_platzhalter("")
    assert not _nur_xfa_platzhalter("Stadtwerke Eckental, Wasserabrechnung 2025")
