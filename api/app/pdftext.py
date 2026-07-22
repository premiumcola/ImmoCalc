"""Text aus einem PDF — der billige Weg, bevor die Bilderkennung anläuft.

Ein maschinengeschriebenes PDF trägt seinen Text als Zeichenstrom in der Datei.
Ihn erst zu rastern und dann mühsam wiederzuerkennen, wäre Umweg und Verlust:
der Betrag steht schon da. Deshalb steht dieses Modul in `ocr.erkenne` *vor*
Tesseract — und deshalb scheitert eine Rechnung, die als PDF hereinkommt, nicht
mehr daran, dass auf dem Server keine Bilderkennung eingerichtet ist.

Gelesen wird mit `pypdf`: reines Python, keine weiteren Abhängigkeiten. Selbst
zu dekomprimieren und die Tj/TJ-Operatoren zu lesen wäre kein kleines Stück
Arbeit — die Rechnungen im Bestand nutzen Type0-Schriften mit
Identity-Kodierung. Deren Zeichencodes im Stream bedeuten nichts ohne die
ToUnicode-Tabelle der eingebetteten Schrift, und die Seiten selbst liegen in
komprimierten Objektströmen.

Fehlt die Bibliothek, bleibt das Modul stumm — wie `ocr` ohne Tesseract: kein
Fehler, nur kein Vorschlag. Der Import ist deshalb bewusst weich.

Ein reiner Scan trägt gar keinen Text — nur ein Bild der Seite. Für ihn gibt es
`seiten_als_bilder`: jede Seite wird zu einem Rasterbild, das dann Tesseract
liest (CLXXIX). Gerendert wird mit `pypdfium2` — ein kleines Wheel ohne
System-Abhängigkeit (kein poppler, kein Ghostscript), das die eigentliche
PDFium-Engine schon mitbringt. Auch dieser Import ist weich: fehlt die
Bibliothek, kann eben nicht gerastert werden, und ein Scan bleibt stumm wie
zuvor.
"""
from __future__ import annotations

import io
import logging
import re
from typing import Any

log = logging.getLogger("immocalc")

# Ein Beleg hat ein paar Seiten. Ein Vertrag mit hundert soll die Erkennung
# nicht minutenlang beschäftigen — Betrag und Datum stehen ohnehin vorn.
MAX_SEITEN = 30

# So weit vorn muss der PDF-Kopf stehen. Manche Erzeuger schreiben davor noch
# eine Handvoll Bytes; alles danach ist kein PDF mehr.
KOPF_FENSTER = 1024

# Auflösung, mit der eine Scan-Seite zum Bild wird. 200 dpi ist der übliche
# Zielwert für Texterkennung: fein genug, dass Tesseract auch kleine Beträge
# liest, grob genug, dass ein mehrseitiger Beleg nicht Hunderte Megabyte wird.
# Der Skalierungsfaktor bezieht sich auf die PDF-Grundauflösung von 72 dpi.
RASTER_DPI = 200
RASTER_SKALIERUNG = RASTER_DPI / 72

try:  # pragma: no cover - hängt davon ab, was im Image liegt
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    PdfReader = None
    log.info("pypdf ist nicht installiert — PDFs werden nicht gelesen")

try:  # pragma: no cover - hängt davon ab, was im Image liegt
    import pypdfium2 as pdfium
except ImportError:  # pragma: no cover
    pdfium = None
    log.info("pypdfium2 ist nicht installiert — Scans werden nicht gerastert")


def verfuegbar() -> bool:
    """Lässt sich überhaupt ein PDF lesen?"""
    return PdfReader is not None


def kann_rastern() -> bool:
    """Lässt sich eine Scan-Seite überhaupt zu einem Bild rendern?

    Ohne `pypdfium2` bleibt ein reiner Scan stumm — der eingebettete Text
    eines Text-PDF wird trotzdem weiter gelesen."""
    return pdfium is not None


def ist_pdf(rohdaten: bytes) -> bool:
    """Trägt die Datei einen PDF-Kopf?

    Auf den Dateinamen ist kein Verlass — was über `/erkennen` hereinkommt,
    heisst immer „seite.jpg". Der Kopf lügt nicht."""
    return bool(rohdaten) and b"%PDF" in rohdaten[:KOPF_FENSTER]


# Ab so vielen Wortteilen wird eine Zeile überhaupt auf Sperrsatz geprüft, und
# ab diesem Anteil einzelner Zeichen gilt sie als gesperrt. Beides grosszügig:
# eine normale Rechnungszeile („Rechnungsbetrag € 104.15") hat drei Teile und
# wird nie angefasst.
_SPERR_TEILE = 8
_SPERR_ANTEIL = 0.5

_KLEINE_LUECKE = re.compile(r"(?<=\S) {1,2}(?=\S)")


def _entspreizt(zeile: str) -> str:
    """Repariert gesperrt gesetzte Zeilen.

    Manche Blätter setzen jedes Zeichen einzeln — Blocksatz, oder die
    Texterkennung, die einem Scan nachträglich eine Textschicht untergelegt
    hat. Der Layout-Modus nimmt die Zeichen dann beim Wort und macht aus
    „1.225,68 EUR" ein „1. 2 2 5 , 6 8   E U R". Aus dem Betrag ist damit
    keiner mehr.

    Erkannt wird das an der Zeile selbst: viele Teile, die meisten davon ein
    einziges Zeichen lang. Nur dann fallen die kleinen Lücken von ein bis zwei
    Leerzeichen — grössere bleiben stehen, denn sie trennen im Layout die
    Spalten. Zeilen mit normalem Satz bleiben unberührt; sie erfüllen die
    Bedingung nie.
    """
    teile = zeile.split()
    if len(teile) < _SPERR_TEILE:
        return zeile
    einzeln = sum(1 for t in teile if len(t) == 1)
    if einzeln < _SPERR_ANTEIL * len(teile):
        return zeile
    return _KLEINE_LUECKE.sub("", zeile)


def _seitentext(seite: Any) -> str:
    """Eine Seite, mit erhaltener Anordnung.

    Der Layout-Modus setzt die Wörter dorthin, wo sie auf dem Blatt stehen.
    Das ist keine Kosmetik: „Datum:" und „12.02.2026" stehen in zwei Spalten
    derselben Zeile, ebenso „Rechnungsbetrag" und der Betrag dahinter. Genau
    dort sucht `ocr` seine Schlüsselwörter — im Flusstext fielen Beschriftung
    und Wert auseinander und stünden untereinander.

    Kommt dabei nichts heraus, gilt der schlichte Modus: lieber Text ohne
    Anordnung als gar keiner.
    """
    try:
        text = seite.extract_text(extraction_mode="layout") or ""
    except Exception as fehler:                            # noqa: BLE001
        log.info("Layout-Lesung fehlgeschlagen: %s", fehler)
        text = ""
    if text.strip():
        return text
    try:
        return seite.extract_text() or ""
    except Exception as fehler:                            # noqa: BLE001
        log.warning("Seite nicht lesbar: %s", fehler)
        return ""


def text_aus_pdf(rohdaten: bytes) -> str:
    """Der eingebettete Text eines PDF.

    Leer heisst: da steht kein Text drin — dann ist es ein Scan oder ein Foto,
    und die Bilderkennung ist an der Reihe. Leer heisst auch: die Datei ist
    kein PDF oder liess sich nicht öffnen. Ein Fehler wird daraus nie; ein
    unlesbarer Beleg soll das Hochladen nicht verhindern.
    """
    if not verfuegbar() or not ist_pdf(rohdaten):
        return ""
    try:
        leser = PdfReader(io.BytesIO(rohdaten))
        seiten = list(leser.pages[:MAX_SEITEN])
    except Exception as fehler:                            # noqa: BLE001
        log.warning("PDF nicht lesbar: %s", fehler)
        return ""
    roh = "\n".join(_seitentext(s) for s in seiten)
    return "\n".join(_entspreizt(z) for z in roh.splitlines())


def _als_ppm(bitmap: Any) -> bytes:
    """Eine gerenderte Seite als PPM (P6) — ein Bild ohne fremde Bibliothek.

    Tesseract liest über Leptonica auch das schlichte PPM-Format; einen
    PNG-Kodierer und damit Pillow brauchen wir dafür nicht. `pypdfium2` liefert
    mit `rev_byteorder` schon RGB in Leserichtung, und die Zeilen liegen ohne
    Rand dicht beieinander (`stride == breite*3`) — der Puffer wandert dann in
    einem Stück in die Datei.
    """
    breite, hoehe, stride = bitmap.width, bitmap.height, bitmap.stride
    kanaele = len(bitmap.mode)          # "RGB" -> 3, "RGBA" -> 4
    puffer = bytes(bitmap.buffer)
    kopf = b"P6\n%d %d\n255\n" % (breite, hoehe)
    if kanaele == 3 and stride == breite * 3:
        return kopf + puffer
    # Der seltene Fall: eine Zeile trägt Randbytes oder einen Alphakanal. Dann
    # Zeile für Zeile die drei Farbkanäle herausschneiden.
    zeilen = bytearray()
    for y in range(hoehe):
        anfang = y * stride
        zeile = memoryview(puffer)[anfang:anfang + breite * kanaele]
        if kanaele == 3:
            zeilen += bytes(zeile)
        else:
            for x in range(breite):
                zeilen += bytes(zeile[x * kanaele:x * kanaele + 3])
    return kopf + bytes(zeilen)


def seiten_als_bilder(rohdaten: bytes, max_seiten: int = MAX_SEITEN) -> list[bytes]:
    """Jede Seite eines PDF als Rasterbild — der Weg für einen reinen Scan.

    Ein eingescanntes Blatt trägt keinen Text, nur ein Bild. Damit Tesseract
    es überhaupt sieht, muss die Seite erst zu Pixeln werden; genau das fehlte
    bisher (CLXXIX), denn Tesseract liest PDFs nicht, nur Bilder.

    Leer heisst: kein PDF, keine Rasterbibliothek, oder die Datei liess sich
    nicht öffnen. Ein Fehler wird daraus nie — ein unlesbarer Scan soll das
    Hochladen so wenig verhindern wie ein unlesbares Text-PDF."""
    if not kann_rastern() or not ist_pdf(rohdaten):
        return []
    try:
        doc = pdfium.PdfDocument(rohdaten)
    except Exception as fehler:                            # noqa: BLE001
        log.warning("PDF nicht zu rastern: %s", fehler)
        return []
    bilder: list[bytes] = []
    try:
        for nr in range(min(len(doc), max_seiten)):
            try:
                bitmap = doc[nr].render(scale=RASTER_SKALIERUNG,
                                        draw_annots=False, rev_byteorder=True)
                bilder.append(_als_ppm(bitmap))
            except Exception as fehler:                    # noqa: BLE001
                log.warning("Seite nicht zu rastern: %s", fehler)
    finally:
        try:
            doc.close()
        except Exception:                                  # noqa: BLE001
            pass
    return bilder
