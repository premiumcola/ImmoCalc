"""N304 — Text aus Office-Dateien holen, ohne eine Bibliothek und ohne API.

Von 125 Belegen ohne KI-Auslese haben nur 25 eine Textschicht. **56 sind
Office-Dateien** — Tabellen (`.xlsx`), Briefe (`.docx`), Präsentationen
(`.pptx`). Sie galten bisher als „kein Text", obwohl ihr Inhalt reiner Text
ist: die modernen Formate sind ZIP-Archive mit XML darin.

Genau das steht hier. Kein `openpyxl`, kein `python-docx` — `zipfile` und
`xml.etree` liegen in der Standardbibliothek, und das Projekt hält sich an
„keine Bibliotheken ausser dem Nötigsten".

Die alten Formate (`.doc`, `.xls`) sind ein OLE-Binärformat und lassen sich so
nicht lesen; sie bleiben aussen vor, und das sagt der Aufrufer ehrlich, statt
Bruchstücke zu liefern.

Absichtlich einfach: es geht nicht um eine originalgetreue Wiedergabe, sondern
darum, dass jemand — ein Mensch oder ein lesender Agent — erkennt, worum es in
dem Beleg geht. Zellen werden mit Tabulator getrennt, Zeilen mit Zeilenumbruch.
"""
from __future__ import annotations

import io
import logging
import re
import zipfile
from xml.etree import ElementTree

log = logging.getLogger("immocalc")

# Namensräume der OOXML-Formate. Nur die, die wir wirklich anfassen.
_NS_TABELLE = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_NS_TEXT = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_NS_PRAESENTATION = "{http://schemas.openxmlformats.org/drawingml/2006/main}"

# Ein ZIP fängt immer so an. Billiger als ein Öffnungsversuch.
_ZIP_MARKE = b"PK\x03\x04"


def ist_office(rohdaten: bytes) -> bool:
    """Sieht das nach einem OOXML-Dokument aus?"""
    return rohdaten[:4] == _ZIP_MARKE


def _sauber(text: str) -> str:
    """Leerzeilen und Wiederholungen ausdünnen — der Text soll lesbar sein."""
    zeilen = [re.sub(r"[ \t]+", lambda m: m.group(0)[0], z.strip())
              for z in text.splitlines()]
    ergebnis: list[str] = []
    for z in zeilen:
        if not z:
            if ergebnis and ergebnis[-1] == "":
                continue
            ergebnis.append("")
        else:
            ergebnis.append(z)
    return "\n".join(ergebnis).strip()


def _tabelle(archiv: zipfile.ZipFile) -> str:
    """`.xlsx`/`.xlsm` — Blätter mit ihren Zellen.

    Zeichenketten stehen in einer gemeinsamen Tabelle (`sharedStrings.xml`)
    und in den Blättern nur als Index; ohne diese Auflösung käme lauter „0"
    heraus."""
    gemeinsam: list[str] = []
    if "xl/sharedStrings.xml" in archiv.namelist():
        baum = ElementTree.fromstring(archiv.read("xl/sharedStrings.xml"))
        for si in baum.findall(f"{_NS_TABELLE}si"):
            gemeinsam.append("".join(t.text or "" for t in si.iter(f"{_NS_TABELLE}t")))

    stuecke: list[str] = []
    blaetter = sorted(n for n in archiv.namelist()
                      if n.startswith("xl/worksheets/sheet") and n.endswith(".xml"))
    for blatt in blaetter:
        baum = ElementTree.fromstring(archiv.read(blatt))
        stuecke.append(f"--- {blatt.rsplit('/', 1)[-1].removesuffix('.xml')} ---")
        for zeile in baum.iter(f"{_NS_TABELLE}row"):
            zellen: list[str] = []
            for c in zeile.findall(f"{_NS_TABELLE}c"):
                v = c.find(f"{_NS_TABELLE}v")
                wert = v.text if v is not None else None
                if wert is None:
                    # Zellen mit Inline-Text tragen ihn direkt.
                    wert = "".join(t.text or "" for t in c.iter(f"{_NS_TABELLE}t"))
                elif c.get("t") == "s":
                    try:
                        wert = gemeinsam[int(wert)]
                    except (ValueError, IndexError):
                        pass
                if (wert or "").strip():
                    zellen.append(str(wert).strip())
            if zellen:
                stuecke.append("\t".join(zellen))
    return "\n".join(stuecke)


def _dokument(archiv: zipfile.ZipFile) -> str:
    """`.docx` — Absätze in ihrer Reihenfolge."""
    if "word/document.xml" not in archiv.namelist():
        return ""
    baum = ElementTree.fromstring(archiv.read("word/document.xml"))
    absaetze = []
    for p in baum.iter(f"{_NS_TEXT}p"):
        text = "".join(t.text or "" for t in p.iter(f"{_NS_TEXT}t"))
        absaetze.append(text)
    return "\n".join(absaetze)


def _praesentation(archiv: zipfile.ZipFile) -> str:
    """`.pptx` — Folien der Reihe nach."""
    stuecke: list[str] = []
    folien = sorted(n for n in archiv.namelist()
                    if n.startswith("ppt/slides/slide") and n.endswith(".xml"))
    for nr, folie in enumerate(folien, 1):
        baum = ElementTree.fromstring(archiv.read(folie))
        text = "\n".join(t.text or "" for t in baum.iter(f"{_NS_PRAESENTATION}t"))
        if text.strip():
            stuecke.append(f"--- Folie {nr} ---\n{text}")
    return "\n".join(stuecke)


def text_aus_office(rohdaten: bytes) -> str:
    """Der Text einer Office-Datei — leer, wenn es keine ist oder nichts drin.

    Wirft nie: eine kaputte oder unbekannte Datei ist kein Fehler, sondern
    schlicht kein Text."""
    if not ist_office(rohdaten):
        return ""
    try:
        with zipfile.ZipFile(io.BytesIO(rohdaten)) as archiv:
            namen = set(archiv.namelist())
            if any(n.startswith("xl/") for n in namen):
                roh = _tabelle(archiv)
            elif "word/document.xml" in namen:
                roh = _dokument(archiv)
            elif any(n.startswith("ppt/slides/") for n in namen):
                roh = _praesentation(archiv)
            else:
                return ""
    except Exception as fehler:                            # noqa: BLE001
        log.info("Office-Datei nicht lesbar: %s", fehler)
        return ""
    return _sauber(roh)
