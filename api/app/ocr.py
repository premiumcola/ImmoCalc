"""Texterkennung für abfotografierte Belege — optional.

Erkannt wird über das Programm `tesseract`, falls es im Image liegt. Fehlt es,
liefern die Funktionen einfach nichts: der Scan funktioniert weiter, nur ohne
Vorschlag für Betrag und Datum. Deshalb bewusst kein harter Import.

Vorgeschlagen wird nur, nie gesetzt — der Nutzer bestätigt jeden Wert.
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from datetime import date

log = logging.getLogger("immocalc")

SPRACHE = "deu"
ZEITLIMIT = 25.0

# Ein Betrag in deutscher Schreibweise: 1.234,56 oder 89,90
_BETRAG = re.compile(r"(?<![\d,.])(\d{1,3}(?:\.\d{3})+|\d+),(\d{2})(?![\d])")
_DATUM = re.compile(r"(?<!\d)(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2,4})(?!\d)")

# Zeilen mit diesen Wörtern tragen fast immer den Rechnungsendbetrag.
_SCHLUESSELWORTE = ("gesamtbetrag", "rechnungsbetrag", "endbetrag", "zu zahlen",
                    "gesamtsumme", "zahlbetrag", "summe brutto", "gesamt brutto",
                    "nachzahlung", "guthaben", "total", "brutto", "summe")

# Zeilen, die das Belegdatum benennen …
_BELEGDATUM = ("rechnungsdatum", "bescheiddatum", "belegdatum", "ausstellung",
               "rechnung vom", "beleg vom", "bescheid vom", "datum")
# … und Zeilen, die ausdrücklich etwas anderes datieren.
_KEIN_BELEGDATUM = ("zeitraum", "abrechnungszeitraum", "gültig", "gueltig",
                    "fällig", "faellig", "zahlbar", "überweisen", "ueberweisen",
                    "bis zum", "zahlungsziel", "ablesung", "zählerstand",
                    "zaehlerstand", "geboren", "vertrag vom")

# Wort -> Dokumentart. Die Arten entsprechen ZIELORDNER in routers/dokumente.py;
# spezifische Begriffe stehen vor allgemeinen.
_KATEGORIEWORTE = [
    ("grundsteuer", "Steuer"), ("finanzamt", "Steuer"), ("steuerbescheid", "Steuer"),
    ("einkommensteuer", "Steuer"), ("steuernummer", "Steuer"),
    ("darlehen", "Kredit"), ("tilgung", "Kredit"), ("zinsbindung", "Kredit"),
    ("annuität", "Kredit"), ("annuitaet", "Kredit"),
    ("versicherungsschein", "Versicherung"), ("police", "Versicherung"),
    ("versicherung", "Versicherung"),
    ("mietvertrag", "Mietvertrag"), ("mieterhöhung", "Mietvertrag"),
    ("kaution", "Mietvertrag"),
    ("hausverwaltung", "Hausverwaltung"), ("wohngeld", "Hausverwaltung"),
    ("eigentümerversammlung", "Hausverwaltung"),
    ("heizkosten", "Nebenkosten"), ("betriebskosten", "Nebenkosten"),
    ("nebenkosten", "Nebenkosten"), ("stadtwerke", "Nebenkosten"),
    ("abwasser", "Nebenkosten"), ("trinkwasser", "Nebenkosten"),
    ("wasser", "Nebenkosten"), ("strom", "Nebenkosten"), ("gas", "Nebenkosten"),
    ("müll", "Nebenkosten"), ("abfall", "Nebenkosten"),
    ("schornstein", "Nebenkosten"), ("kaminkehrer", "Nebenkosten"),
    ("hausmeister", "Nebenkosten"), ("winterdienst", "Nebenkosten"),
    ("grundbesitzabgaben", "Nebenkosten"),
]


def verfuegbar() -> bool:
    """Ist Tesseract installiert? Ohne das bleibt die Erkennung stumm."""
    return shutil.which("tesseract") is not None


def text_aus_bild(rohdaten: bytes) -> str:
    """Liest den Text eines Bildes. Leerer String, wenn es nicht geht."""
    if not verfuegbar() or not rohdaten:
        return ""
    with tempfile.NamedTemporaryFile(suffix=".img") as quelle:
        quelle.write(rohdaten)
        quelle.flush()
        try:
            ergebnis = subprocess.run(
                ["tesseract", quelle.name, "stdout", "-l", SPRACHE],
                capture_output=True, timeout=ZEITLIMIT, check=False)
        except (OSError, subprocess.SubprocessError) as fehler:
            log.warning("Texterkennung fehlgeschlagen: %s", fehler)
            return ""
    if ergebnis.returncode != 0:
        log.info("tesseract meldete %s", ergebnis.returncode)
        return ""
    return ergebnis.stdout.decode("utf-8", "replace")


def _zu_zahl(ganz: str, nachkomma: str) -> float:
    return float(ganz.replace(".", "") + "." + nachkomma)


def betrag_aus_text(text: str) -> float | None:
    """Der wahrscheinlichste Rechnungsbetrag.

    Zuerst wird in Zeilen mit einem Schlüsselwort gesucht — dort steht der
    Endbetrag. Findet sich keine, gilt der größte Betrag im Dokument; das
    trifft bei Rechnungen fast immer die Endsumme."""
    treffer_mit_wort: list[float] = []
    alle: list[float] = []
    for zeile in (text or "").splitlines():
        betraege = [_zu_zahl(g, n) for g, n in _BETRAG.findall(zeile)]
        if not betraege:
            continue
        alle += betraege
        if any(wort in zeile.lower() for wort in _SCHLUESSELWORTE):
            treffer_mit_wort += betraege
    kandidaten = treffer_mit_wort or alle
    return round(max(kandidaten), 2) if kandidaten else None


def _daten_der_zeile(zeile: str) -> list[date]:
    """Alle plausiblen Datumsangaben einer Zeile."""
    heute = date.today()
    treffer = []
    for tag, monat, jahr in _DATUM.findall(zeile or ""):
        j = int(jahr)
        if j < 100:
            j += 2000
        try:
            kandidat = date(j, int(monat), int(tag))
        except ValueError:
            continue
        # Belege liegen in der Vergangenheit, aber nicht in grauer Vorzeit
        if heute.year - 12 <= kandidat.year <= heute.year + 1:
            treffer.append(kandidat)
    return treffer


def datum_aus_text(text: str) -> date | None:
    """Das Rechnungsdatum.

    Nicht einfach das früheste Datum im Dokument: auf einer Rechnung steht der
    Beginn des Abrechnungszeitraums weiter vorn ("01.01.2024 – 31.12.2024"),
    und der ist nicht gemeint. Deshalb zuerst die Zeilen ansehen, die das
    Datum benennen — "Rechnungsdatum", "Bescheiddatum", schlicht "Datum".

    Zeilen, die ausdrücklich etwas anderes datieren (Zahlungsziel, Zeitraum,
    Zählerstand), bleiben aussen vor.
    """
    benannt: list[date] = []
    uebrig: list[date] = []

    for zeile in (text or "").splitlines():
        klein = zeile.lower()
        treffer = _daten_der_zeile(zeile)
        if not treffer:
            continue
        if any(wort in klein for wort in _KEIN_BELEGDATUM):
            continue
        if any(wort in klein for wort in _BELEGDATUM):
            benannt += treffer
        else:
            uebrig += treffer

    if benannt:
        return min(benannt)
    # Ohne Beschriftung: das späteste Datum ist eher das Rechnungsdatum als
    # der Anfang eines Zeitraums.
    return max(uebrig) if uebrig else None


def kategorie_aus_text(text: str) -> str:
    """Welche Art von Beleg das ist — aus dem gelesenen Text, nicht aus dem
    Dateinamen. Ein Kamerascan heisst schlicht "scan.pdf"; ohne den Inhalt
    gäbe es gar keinen Anhaltspunkt.

    Gewertet wird nach Häufigkeit: ein Wort im Briefkopf entscheidet nicht
    allein, wenn der Rest des Blattes von etwas anderem handelt.
    """
    klein = (text or "").lower()
    punkte: dict[str, int] = {}
    for wort, art in _KATEGORIEWORTE:
        anzahl = klein.count(wort)
        if anzahl:
            punkte[art] = punkte.get(art, 0) + anzahl
    if not punkte:
        return ""
    return max(punkte.items(), key=lambda p: p[1])[0]


def erkenne(rohdaten: bytes) -> dict:
    """Vorschlag aus einem Beleg-Bild: Betrag, Datum, Jahr."""
    if not verfuegbar():
        return {"moeglich": False, "betrag": None, "datum": None, "jahr": None,
                "hinweis": "Texterkennung ist auf diesem Server nicht "
                           "eingerichtet — Betrag bitte eintragen."}
    text = text_aus_bild(rohdaten)
    gefunden = datum_aus_text(text)
    return {
        "moeglich": True,
        "betrag": betrag_aus_text(text),
        "datum": gefunden.isoformat() if gefunden else None,
        "jahr": gefunden.year if gefunden else None,
        "kategorie": kategorie_aus_text(text),
        "zeichen": len(text.strip()),
    }
