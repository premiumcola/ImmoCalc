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
#
# Gesucht wird ab Wortanfang, nie mitten im Wort: „Berggasse" ist kein Gas,
# „Elgassner" auch nicht, „Wassermann" kein Wasser. Das war folgenlos, solange
# nur ein Vorschlag daran hing — seit die Automatik Dateien ungefragt
# verschiebt, ist es das nicht mehr.
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

# Was hinter einem Sachbegriff stehen darf, damit er noch derselbe Begriff ist:
# grammatische Endungen und die Wörter, die aus einer Sache einen Beleg machen.
# „Stromabrechnung" zählt, „Wassermann" nicht.
_ANHAENGE = (
    "", "e", "n", "en", "s", "es", "er",
    "rechnung", "rechnungen", "abrechnung", "abrechnungen",
    "jahresabrechnung", "kosten", "kostenabrechnung",
    "gebühr", "gebühren", "gebuehr", "gebuehren",
    "bescheid", "bescheide", "beitrag", "beitraege", "beiträge",
    "zahlung", "zahlungen", "abschlag", "abschläge", "abschlaege",
    "ablesung", "ablesungen", "vertrag", "vertrages", "verträge", "vertraege",
    "schein", "scheine", "geld", "werke", "versorgung", "verbrauch",
)

# Mindestens so viele Treffer, bevor ein Dateiname eine Ablage auslöst. Ein
# einziges Wort reicht — aber nur, wenn es eindeutig ist (siehe unten).
MINDESTPUNKTE = 1
# Zu kurze Sachbegriffe treffen in einem Dateinamen zu leicht etwas anderes.
MINDESTLAENGE = 3

_ANHANG_TEIL = "|".join(sorted((re.escape(a) for a in _ANHAENGE),
                               key=len, reverse=True))

# Wortanfang + erlaubter Anhang, je Sachbegriff einmal übersetzt.
_MUSTER: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b" + re.escape(wort) + r"(?:" + _ANHANG_TEIL + r")\b"), art)
    for wort, art in _KATEGORIEWORTE if len(wort) >= MINDESTLAENGE
]

# Für gelesenen Text genügt der Wortanfang: dort steht „Wasserverbrauch je
# Wohneinheit" in beliebiger Beugung, und ein Anhang lässt sich nicht auflisten.
_MUSTER_WEIT: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b" + re.escape(wort)), art) for wort, art in _KATEGORIEWORTE
]


def _punkte(text: str, muster: list[tuple[re.Pattern[str], str]]) -> dict[str, int]:
    """Wie oft welche Art im Text vorkommt."""
    klein = (text or "").lower()
    gefunden: dict[str, int] = {}
    for regel, art in muster:
        anzahl = len(regel.findall(klein))
        if anzahl:
            gefunden[art] = gefunden.get(art, 0) + anzahl
    return gefunden


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
    allein, wenn der Rest des Blattes von etwas anderem handelt. Das Ergebnis
    ist ein Vorschlag, den der Nutzer bestätigt — deshalb hier die weite
    Suche ab Wortanfang.
    """
    punkte = _punkte(text, _MUSTER_WEIT)
    if not punkte:
        return ""
    return max(punkte.items(), key=lambda p: p[1])[0]


def kategorie_aus_dateiname(name: str) -> tuple[str, int]:
    """Art und Sicherheit aus einem Dateinamen — dieselbe Wortliste, strenger
    gelesen.

    Ein Dateiname ist kurz: „Notar Elgassner.pdf" hat genau eine Zeile, in der
    sich ein Zufallstreffer nicht wegmitteln kann. Deshalb zählt hier nur ein
    Sachbegriff mit erlaubtem Anhang, und nur, wenn eine einzige Art vorn
    liegt. Bei Gleichstand gilt: nicht erkannt — lieber liegen lassen als
    ungefragt falsch einsortieren.

    Gibt (Art, Punkte) zurück; ("", 0) heißt „keine Ahnung".
    """
    punkte = _punkte(name, _MUSTER)
    if not punkte:
        return "", 0
    beste = sorted(punkte.items(), key=lambda p: -p[1])
    if len(beste) > 1 and beste[0][1] == beste[1][1]:
        return "", 0
    return beste[0] if beste[0][1] >= MINDESTPUNKTE else ("", 0)


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
