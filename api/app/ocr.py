"""Texterkennung für Belege — zwei Wege, der billige zuerst.

Ein maschinengeschriebenes PDF trägt seinen Text schon in sich; den liest
`pdftext` direkt aus der Datei. Erst wo nichts drinsteht — ein Foto, ein
eingescanntes Blatt — kommt das Programm `tesseract` an die Reihe, falls es im
Image liegt. Fehlt beides, liefern die Funktionen einfach nichts: der Scan
funktioniert weiter, nur ohne Vorschlag für Betrag und Datum. Deshalb bewusst
kein harter Import.

Ausgewertet wird in beiden Fällen derselbe Text von denselben Funktionen —
`betrag_aus_text`, `datum_aus_text`, `kategorie_aus_text`. Zwei Wege herein,
eine Auswertung.

Vorgeschlagen wird nur, nie gesetzt — der Nutzer bestätigt jeden Wert.
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from datetime import date

from . import pdftext

log = logging.getLogger("immocalc")

SPRACHE = "deu"
ZEITLIMIT = 25.0

# Ein Betrag in deutscher Schreibweise: 1.234,56 oder 89,90
_BETRAG = re.compile(r"(?<![\d,.])(\d{1,3}(?:\.\d{3})+|\d+),(\d{2})(?![\d])")
# Derselbe Betrag mit Punkt: 104.15, 1,234.56. Nicht jeder Beleg schreibt
# deutsch — die Schornsteinfeger-Rechnung im Bestand druckt ihren
# Rechnungsbetrag fett als „104.15", und die Bilderkennung liest ein Komma
# ohnehin gern als Punkt.
#
# Nach den zwei Nachkommastellen darf keine Ziffer und kein Punkt folgen:
# sonst wäre „12.02" aus dem Datum 12.02.2026 ein Betrag und „1.234" aus
# 1.234,56 auch. Ein deutscher Tausenderblock hat drei Stellen, nie zwei.
_BETRAG_PUNKT = re.compile(
    r"(?<![\d,.])(\d{1,3}(?:,\d{3})+|\d+)\.(\d{2})(?![\d.])")
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

# Wort -> (Dokumentart, Sache). Die Arten entsprechen ZIELORDNER in
# routers/dokumente.py; spezifische Begriffe stehen vor allgemeinen.
#
# Die Art sagt, in welchen Ordner der Beleg gehört. Die *Sache* sagt, worum es
# geht, und wird der Dateiname (CXXIII): „Heizöl" statt „Heizkosten", denn im
# Ordner 60_Nebenkosten liegen zwanzig Belege, die alle Heizkosten sind.
#
# Wo die Sache leer bleibt, heisst der Ordner schon so wie der Begriff —
# „Nebenkosten" im Ordner 60_Nebenkosten wäre die Doppelnennung aus CXXII.
# Dann trägt die Bezeichnung aus dem ursprünglichen Namen den Namen.
#
# Gesucht wird ab Wortanfang, nie mitten im Wort: „Berggasse" ist kein Gas,
# „Elgassner" auch nicht, „Wassermann" kein Wasser. Das war folgenlos, solange
# nur ein Vorschlag daran hing — seit die Automatik Dateien ungefragt
# verschiebt, ist es das nicht mehr.
_KATEGORIEWORTE = [
    ("grundsteuer", "Steuer", "Grundsteuer"),
    ("finanzamt", "Steuer", "Finanzamt"),
    ("steuerbescheid", "Steuer", "Steuerbescheid"),
    ("einkommensteuer", "Steuer", "Einkommensteuer"),
    ("steuernummer", "Steuer", "Finanzamt"),
    ("darlehen", "Kredit", "Darlehen"), ("tilgung", "Kredit", "Tilgung"),
    ("zinsbindung", "Kredit", "Zinsbindung"),
    ("annuität", "Kredit", "Annuität"), ("annuitaet", "Kredit", "Annuität"),
    ("versicherungsschein", "Versicherung", "Versicherungsschein"),
    ("police", "Versicherung", "Police"),
    # Was der Nutzer im Bestand wirklich schreibt: „WWK-Haftpflicht",
    # „WWK-Gebäudeversicherung". „\bversicherung" trifft das Kompositum nicht.
    ("gebäudeversicherung", "Versicherung", "Gebäudeversicherung"),
    ("gebaeudeversicherung", "Versicherung", "Gebäudeversicherung"),
    ("haftpflicht", "Versicherung", "Haftpflicht"),
    ("versicherung", "Versicherung", ""),
    ("mietvertrag", "Mietvertrag", ""),
    ("mieterhöhung", "Mietvertrag", "Mieterhöhung"),
    ("kaution", "Mietvertrag", "Kaution"),
    ("hausverwaltung", "Hausverwaltung", ""),
    ("wohngeld", "Hausverwaltung", "Wohngeld"),
    ("eigentümerversammlung", "Hausverwaltung", "Eigentümerversammlung"),
    ("heizkosten", "Nebenkosten", "Heizkosten"),
    ("betriebskosten", "Nebenkosten", "Betriebskosten"),
    # Brennstoff wird als Ganzes geliefert und gehoert zu den Heizkosten. Eine
    # Oelrechnung nennt sich selbst fast nie „Heizkosten“ — sie spricht von
    # Heizoel, Litern und dem Tank.
    ("heizöl", "Nebenkosten", "Heizöl"), ("heizoel", "Nebenkosten", "Heizöl"),
    # Der Nutzer schreibt seine Ölrechnungen kurz: „2025-10-oel-2729,91€",
    # „Öl-suft-2025". Ohne diese beiden bliebe der grösste Posten der
    # Heizkosten unerkannt.
    ("öl", "Nebenkosten", "Heizöl"), ("oel", "Nebenkosten", "Heizöl"),
    ("brennstoff", "Nebenkosten", "Brennstoff"),
    ("flüssiggas", "Nebenkosten", "Flüssiggas"),
    ("fluessiggas", "Nebenkosten", "Flüssiggas"),
    ("pellets", "Nebenkosten", "Pellets"),
    ("nebenkosten", "Nebenkosten", ""),
    ("stadtwerke", "Nebenkosten", "Stadtwerke"),
    ("abwasser", "Nebenkosten", "Abwasser"),
    ("trinkwasser", "Nebenkosten", "Trinkwasser"),
    ("kaltwasser", "Nebenkosten", "Kaltwasser"),
    ("warmwasser", "Nebenkosten", "Warmwasser"),
    ("wasser", "Nebenkosten", "Wasser"),
    ("heizstrom", "Nebenkosten", "Heizstrom"),
    ("strom", "Nebenkosten", "Strom"),
    ("gas", "Nebenkosten", "Gas"),
    ("müll", "Nebenkosten", "Müll"), ("muell", "Nebenkosten", "Müll"),
    ("abfall", "Nebenkosten", "Abfall"),
    ("schornstein", "Nebenkosten", "Schornsteinfeger"),
    ("kaminkehrer", "Nebenkosten", "Kaminkehrer"),
    ("kaminfeger", "Nebenkosten", "Kaminfeger"),
    ("hausmeister", "Nebenkosten", "Hausmeister"),
    ("winterdienst", "Nebenkosten", "Winterdienst"),
    ("grundbesitzabgaben", "Nebenkosten", "Grundbesitzabgaben"),
]

# Was hinter einem Sachbegriff stehen darf, damit er noch derselbe Begriff ist:
# grammatische Endungen und die Wörter, die aus einer Sache einen Beleg machen.
# „Stromabrechnung" zählt, „Wassermann" nicht.
_ENDUNGEN = ("", "e", "n", "en", "s", "es", "er")

_BELEGWOERTER = (
    "rechnung", "rechnungen", "abrechnung", "abrechnungen",
    "jahresabrechnung", "kosten", "kostenabrechnung",
    "gebühr", "gebühren", "gebuehr", "gebuehren",
    "bescheid", "bescheide", "beitrag", "beitraege", "beiträge",
    "zahlung", "zahlungen", "abschlag", "abschläge", "abschlaege",
    "ablesung", "ablesungen", "vertrag", "vertrages", "verträge", "vertraege",
    "schein", "scheine", "geld", "werke", "versorgung", "verbrauch",
    # Mit Fugen-s: „Darlehensvertrag", „Versicherungsbescheid". Einzeln
    # aufgeführt statt als generisches „s?" — sonst wäre „Gasse" ein Gas.
    "svertrag", "svertrages", "sverträge", "svertraege", "sbescheid",
    "srechnung", "srechnungen", "sabrechnung", "skosten", "sabschlag",
)

_ANHAENGE = _ENDUNGEN + _BELEGWOERTER

# Begriffe, die mit einer harmlosen Endung ein ganz anderes Wort ergeben:
# „Müller" ist kein Müll, „Mueller" auch nicht, „Öle" kein Beleg. Sie zählen
# nur nackt oder vor einem Belegwort — „Müllgebühren" ja, „Müller" nein.
# Dieselbe Regel wie XCIII, nur eine Silbe später: kein Treffer am Wortende.
_KEINE_ENDUNG = {"müll", "muell", "öl", "oel", "gas"}

# Mindestens so viele Treffer, bevor ein Dateiname eine Ablage auslöst. Ein
# einziges Wort reicht — aber nur, wenn es eindeutig ist (siehe unten).
MINDESTPUNKTE = 1
# Zu kurze Sachbegriffe treffen in einem Dateinamen zu leicht etwas anderes.
# Zwei Buchstaben hat in der ganzen Liste nur „öl" — und ein deutsches Wort,
# das mit „öl" anfängt, handelt von Öl. Kürzeres gibt es nicht.
MINDESTLAENGE = 2

def _anhang_teil(anhaenge: tuple[str, ...]) -> str:
    """Die Anhänge als Alternative, längste zuerst — sonst gewänne „e" vor
    „en" und der Wortgrenzen-Anker schlüge fehl."""
    return "|".join(sorted((re.escape(a) for a in anhaenge),
                           key=len, reverse=True))


_ANHANG_TEIL = _anhang_teil(_ANHAENGE)
_ANHANG_KNAPP = _anhang_teil(("",) + _BELEGWOERTER)

# Wortanfang + erlaubter Anhang, je Sachbegriff einmal übersetzt.
_ENG = [(re.compile(r"\b" + re.escape(wort) + r"(?:"
                    + (_ANHANG_KNAPP if wort in _KEINE_ENDUNG else _ANHANG_TEIL)
                    + r")\b"), art, sache)
        for wort, art, sache in _KATEGORIEWORTE if len(wort) >= MINDESTLAENGE]

# Für gelesenen Text genügt der Wortanfang: dort steht „Wasserverbrauch je
# Wohneinheit" in beliebiger Beugung, und ein Anhang lässt sich nicht auflisten.
# Nur die heiklen Kurzwörter bleiben auch hier eng — ein Absender „Müller
# Immobilien" darf keine Müllabfuhr aus einer Rechnung machen.
_WEIT = [(re.compile(r"\b" + re.escape(wort) + (r"(?:" + _ANHANG_KNAPP + r")\b"
                                                if wort in _KEINE_ENDUNG else "")),
          art, sache)
         for wort, art, sache in _KATEGORIEWORTE]

# Dieselben Muster, einmal nach der Art und einmal nach der Sache gebündelt —
# gezählt wird mit derselben Funktion.
_MUSTER: list[tuple[re.Pattern[str], str]] = [(r, art) for r, art, _ in _ENG]
_MUSTER_WEIT: list[tuple[re.Pattern[str], str]] = [(r, art) for r, art, _ in _WEIT]
_SACHE_MUSTER: list[tuple[re.Pattern[str], str]] = [
    (r, sache) for r, _, sache in _ENG if sache]
_SACHE_MUSTER_WEIT: list[tuple[re.Pattern[str], str]] = [
    (r, sache) for r, _, sache in _WEIT if sache]


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
    """Der Ganzteil kann Tausendertrenner tragen — Punkt oder Komma, je nach
    Schreibweise. Beide fliegen raus; getrennt wurde schon im Muster."""
    return float(re.sub(r"[.,]", "", ganz) + "." + nachkomma)


def _betraege_der_zeile(zeile: str) -> list[float]:
    """Alle Beträge einer Zeile — in beiden Schreibweisen.

    Eine Schreibweise je Blatt zu bestimmen wäre naheliegend, hält aber nicht:
    auf der Kaminfeger-Rechnung im Bestand stehen die Beträge mit Punkt
    („Rechnungsbetrag 106.12"), und ein einziges Leistungsdatum „22,09" mit
    Komma kippte die ganze Entscheidung.

    Nebeneinander ist gefahrlos, weil sich die beiden Muster ausschliessen:
    „1.234,56" findet nur das Komma-Muster (dem Punkt folgen dort drei
    Ziffern), „104.15" nur das Punkt-Muster. Was der Punkt zusätzlich
    aufliest, sind Anzahlen wie „1.00" und Prozentwerte wie „19.00" — beide
    zu klein, um gegen eine Endsumme zu gewinnen.
    """
    return [_zu_zahl(g, n)
            for muster in (_BETRAG, _BETRAG_PUNKT)
            for g, n in muster.findall(zeile)]


def betrag_aus_text(text: str) -> float | None:
    """Der wahrscheinlichste Rechnungsbetrag.

    Zuerst wird in Zeilen mit einem Schlüsselwort gesucht — dort steht der
    Endbetrag. Findet sich keine, gilt der größte Betrag im Dokument; das
    trifft bei Rechnungen fast immer die Endsumme."""
    treffer_mit_wort: list[float] = []
    alle: list[float] = []
    for zeile in (text or "").splitlines():
        betraege = _betraege_der_zeile(zeile)
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


def _beste_sache(punkte: dict[str, int]) -> str:
    """Der Sachbegriff mit den meisten Treffern.

    Bei Gleichstand gewinnt der zuerst gefundene — die Wortliste steht von
    spezifisch nach allgemein, „Heizöl" also vor „Heizkosten"."""
    if not punkte:
        return ""
    return max(punkte.items(), key=lambda p: p[1])[0]


def sache_aus_text(text: str) -> str:
    """Worum es auf dem Beleg geht — „Heizöl", „Müll", „Grundsteuer".

    Feiner als die Art: die Art bestimmt den Ordner, die Sache den Dateinamen
    (CXXIII). Leer heisst: nichts Spezifischeres als der Ordnername gefunden.
    """
    return _beste_sache(_punkte(text, _SACHE_MUSTER_WEIT))


def sache_aus_dateiname(name: str) -> str:
    """Dasselbe aus einem Dateinamen, streng gelesen.

    Ein Name ist kurz; ein Zufallstreffer mittelt sich dort nicht weg. Deshalb
    dieselbe enge Lesart wie bei `kategorie_aus_dateiname`."""
    return _beste_sache(_punkte(name, _SACHE_MUSTER))


def erkennung_moeglich() -> bool:
    """Kann dieser Server überhaupt etwas lesen?

    Zwei Wege, einer genügt: der eingebettete Text eines PDF oder die
    Bilderkennung. Ohne Tesseract bleibt ein Foto stumm — ein
    maschinengeschriebenes PDF nicht mehr."""
    return pdftext.verfuegbar() or verfuegbar()


def text_aus_beleg(rohdaten: bytes) -> str:
    """Der Text eines Belegs — der billigste Weg zuerst.

    Ein maschinengeschriebenes PDF trägt seinen Text schon in sich; ihn zu
    lesen kostet nichts und verliest sich nie. Erst wenn nichts drinsteht —
    ein Foto, ein eingescanntes Blatt —, kommt Tesseract an die Reihe. Ist
    auch das nicht eingerichtet, bleibt es ehrlich bei nichts.

    Der Fund CLXX war genau diese fehlende erste Stufe: eine Rechnung als
    Text-PDF ging durch die Bilderkennung, fand dort kein Tesseract und
    meldete „Betrag nicht erkannt" — obwohl der Betrag als Zeichenstrom in
    der Datei stand.
    """
    text = pdftext.text_aus_pdf(rohdaten)
    if text.strip():
        return text
    return text_aus_bild(rohdaten)


def _ohne_befund() -> dict:
    """Dieselben Schlüssel wie im Erfolgsfall — die Oberfläche soll nicht zwei
    Antwortformen kennen müssen."""
    return {"moeglich": erkennung_moeglich(), "betrag": None, "datum": None,
            "jahr": None, "monat": None, "kategorie": "", "sache": "",
            "zeichen": 0}


def _warum_nichts(rohdaten: bytes) -> str:
    """Warum auf diesem Beleg nichts zu lesen war — so genau wie möglich.

    „Nicht erkannt" ohne Grund lässt den Nutzer raten, ob der Server etwas
    nicht kann oder das Blatt nichts hergibt."""
    if not erkennung_moeglich():
        return ("Texterkennung ist auf diesem Server nicht eingerichtet — "
                "Betrag bitte eintragen.")
    if pdftext.ist_pdf(rohdaten) and not verfuegbar():
        return ("Dieses PDF enthält keinen Text, sondern nur ein Bild. Für "
                "eingescannte Belege ist auf diesem Server keine "
                "Bilderkennung eingerichtet — Betrag bitte eintragen.")
    return "Auf dem Beleg war kein Text zu finden — Betrag bitte eintragen."


def erkenne(rohdaten: bytes) -> dict:
    """Vorschlag aus einem Beleg: Betrag, Datum, Jahr, Art und Sache.

    Gleich, ob PDF oder Foto — der Text kommt aus `text_aus_beleg`, die
    Auswertung ist dieselbe. Vorgeschlagen wird nur, gesetzt nie."""
    text = text_aus_beleg(rohdaten)
    if not text.strip():
        return {**_ohne_befund(), "hinweis": _warum_nichts(rohdaten)}
    gefunden = datum_aus_text(text)
    return {
        "moeglich": True,
        "betrag": betrag_aus_text(text),
        "datum": gefunden.isoformat() if gefunden else None,
        "jahr": gefunden.year if gefunden else None,
        "kategorie": kategorie_aus_text(text),
        # Was in den Dateinamen wandert — „Heizöl", nicht „Heizkosten".
        "sache": sache_aus_text(text),
        "monat": gefunden.month if gefunden else None,
        # Ohne Leerraum gezählt: der Layout-Modus füllt jede Zeile bis zur
        # Spalte auf, ein einseitiger Beleg käme sonst auf Tausende Zeichen.
        "zeichen": len(re.sub(r"\s", "", text)),
    }
