"""N492 — wo auf dem Blatt steht, was die Erkennung herausgelesen hat.

Nutzer: „vielleicht könntest du die Elemente, die erkannt wurden, als Kategorie
bunt färben — dann hast du das Datum, dann den Betrag, und der Nutzer sieht:
bam, bam, bam, diese Werte hat das KI-Tool jetzt rausgenommen aus dem Blatt."

Dafür braucht es Koordinaten, und die gab es im Projekt nirgends: der
KI-Prompt fordert keine an, `ocr.py` ruft `tesseract datei stdout` ohne Boxen
auf, das Datenmodell speichert keine.

**Warum das Sprachmodell sie nicht liefern soll.** Man könnte den Prompt um
Bounding-Boxen erweitern. Sprachmodelle schätzen die aber, statt sie zu
messen — ein Kasten, der zwei Zentimeter neben dem Betrag liegt, ist
schlimmer als gar keiner, weil er eine Genauigkeit behauptet, die er nicht
hat. Tesseract misst sie: dasselbe Programm, das ohnehin im Image liegt,
gibt mit `tsv` statt `stdout` je Wort Ort und Größe aus.

**Warum ein zweiter Lauf und nicht der bestehende.** Der Textlauf in `ocr.py`
bleibt unangetastet. Aus TSV rekonstruierter Text unterscheidet sich subtil
vom heutigen (Zeilenumbrüche, Spaltenlayout), und daran hängen die
Heuristiken für Datum, Betrag und Kostenart samt ihren Referenztests. Ein
eigener, rein optionaler Lauf kann dagegen jederzeit ausfallen — dann fehlen
nur die Markierungen.

**Worauf gemessen wird.** Auf dem ZUGESCHNITTENEN Blatt, nicht auf dem
Originalfoto. Die Auslese läuft aus Zeitgründen auf dem Original (parallel zum
Zuschnitt), die Vorschau zeigt aber die entzerrte Seite — Koordinaten vom
Original lägen daneben. Der Aufrufer schickt deshalb genau das Bild, das er
auch anzeigt.
"""
from __future__ import annotations

import csv
import io
import logging
import re
import subprocess
import tempfile

log = logging.getLogger("immocalc")

SPRACHE = "deu"
ZEITLIMIT = 25
# Wie viele nebeneinanderliegende Wörter höchstens zu einem Fund verschmelzen.
# „Tauchersreuther Str. 7, 90542 Eckental-Eschenau" sind sechs; darüber hinaus
# würde eine Zeile als Ganzes markiert, und das sagt nichts mehr aus.
MAX_WORTE = 6
# Unter diesem Wert hat Tesseract selbst kein Vertrauen in das Wort. Solche
# Lesungen als Fundstelle zu markieren, führt den Nutzer in die Irre.
MIN_VERTRAUEN = 40.0


def verfuegbar() -> bool:
    """Ohne Tesseract gibt es keine Fundstellen — und das ist in Ordnung."""
    import shutil                                   # noqa: PLC0415
    return shutil.which("tesseract") is not None


def _worte(rohdaten: bytes) -> tuple[list[dict], int, int]:
    """Alle erkannten Wörter mit Ort und Größe, plus die Bildmaße.

    Rückgabe `([{text, x, y, b, h, zeile}], breite, hoehe)`. Bei jedem Fehler
    eine leere Liste — die Markierungen sind Beiwerk, nichts darf daran
    hängenbleiben.
    """
    if not verfuegbar() or not rohdaten:
        return [], 0, 0
    with tempfile.NamedTemporaryFile(suffix=".img") as quelle:
        quelle.write(rohdaten)
        quelle.flush()
        try:
            ergebnis = subprocess.run(
                ["tesseract", quelle.name, "stdout", "-l", SPRACHE, "tsv"],
                capture_output=True, timeout=ZEITLIMIT, check=False)
        except (OSError, subprocess.SubprocessError) as fehler:
            log.info("Fundstellen: tesseract nicht gelaufen (%s)", fehler)
            return [], 0, 0
    if ergebnis.returncode != 0:
        log.info("Fundstellen: tesseract meldete %s", ergebnis.returncode)
        return [], 0, 0

    text = ergebnis.stdout.decode("utf-8", "replace")
    worte: list[dict] = []
    breite = hoehe = 0
    leser = csv.DictReader(io.StringIO(text), delimiter="\t",
                           quoting=csv.QUOTE_NONE)
    for zeile in leser:
        try:
            stufe = int(zeile.get("level") or 0)
            links = int(zeile.get("left") or 0)
            oben = int(zeile.get("top") or 0)
            b = int(zeile.get("width") or 0)
            h = int(zeile.get("height") or 0)
        except (TypeError, ValueError):
            continue
        # Stufe 1 ist die Seite selbst — daher kommen die Bildmaße.
        if stufe == 1:
            breite, hoehe = b, h
            continue
        if stufe != 5:                               # 5 = ein einzelnes Wort
            continue
        wort = (zeile.get("text") or "").strip()
        if not wort:
            continue
        try:
            vertrauen = float(zeile.get("conf") or -1)
        except (TypeError, ValueError):
            vertrauen = -1
        if vertrauen < MIN_VERTRAUEN:
            continue
        worte.append({
            "text": wort, "x": links, "y": oben, "b": b, "h": h,
            # Zeilenkennung aus Block/Absatz/Zeile — nur Wörter derselben Zeile
            # dürfen zu einem Fund verschmelzen.
            "zeile": (zeile.get("block_num"), zeile.get("par_num"),
                      zeile.get("line_num")),
        })
    return worte, breite, hoehe


def _kern(text: str) -> str:
    """Vergleichsform: Kleinschreibung, nur Buchstaben und Ziffern.

    Absicht dahinter: „348,00 €" auf dem Blatt und „348,00 €" aus der Auslese
    sollen sich treffen, auch wenn Tesseract das Eurozeichen verschluckt oder
    einen Punkt für ein Komma hält. Deshalb fliegen ALLE Trennzeichen raus —
    verglichen wird „34800" mit „34800".
    """
    return re.sub(r"[^0-9a-zäöüß]", "", text.lower())


def _nadeln(wert: str) -> list[str]:
    """Wonach gesucht wird: der ganze Wert, dann seine Bestandteile.

    Dieselbe Regel wie bei der Markierung im Erklärtext
    (`belegbestaetigung.js::nadeln`) — an Leerzeichen UND am Bindestrich
    zerlegt, längstes zuerst. Ohne die zweite Zerlegung fände
    „Abfallwirtschaft-Anmeldung" nichts, obwohl „Abfallwirtschaft" auf dem
    Blatt steht.
    """
    stuecke = re.split(r"[\s,;()/–-]+", wert)
    teile = {t.strip(" .:") for t in stuecke if len(_kern(t)) >= 4}
    return [wert, *sorted(teile, key=len, reverse=True)]


def _suche(worte: list[dict], nadel: str) -> dict | None:
    """Der kleinste Wortlauf einer Zeile, dessen Text die Nadel enthält."""
    ziel = _kern(nadel)
    if len(ziel) < 3:
        return None
    for laenge in range(1, MAX_WORTE + 1):
        for i in range(len(worte) - laenge + 1):
            lauf = worte[i:i + laenge]
            if len({w["zeile"] for w in lauf}) > 1:
                continue                             # über Zeilengrenze hinweg
            zusammen = _kern("".join(w["text"] for w in lauf))
            if ziel in zusammen:
                x = min(w["x"] for w in lauf)
                y = min(w["y"] for w in lauf)
                x2 = max(w["x"] + w["b"] for w in lauf)
                y2 = max(w["y"] + w["h"] for w in lauf)
                return {"x": x, "y": y, "b": x2 - x, "h": y2 - y}
    return None


def finde(rohdaten: bytes, werte: list[dict]) -> list[dict]:
    """Zu jedem `{art, wert}` die Stelle im Bild — soweit sie zu finden ist.

    Die Kästen kommen RELATIV zurück (0…1 der Bildbreite/-höhe): die Vorschau
    skaliert das Bild auf die Spaltenbreite, absolute Pixel wären dort falsch.

    Angaben ohne Fundstelle fehlen einfach in der Antwort. Das ist der
    Normalfall und kein Fehler: „Sonstiges" als Kategorie ist eine Einordnung,
    kein Wort, das auf dem Blatt steht.
    """
    if not werte:
        return []
    worte, breite, hoehe = _worte(rohdaten)
    if not worte or not breite or not hoehe:
        return []

    aus: list[dict] = []
    belegt: list[tuple[int, int, int, int]] = []
    for eintrag in werte:
        wert = str(eintrag.get("wert") or "").strip()
        if not wert:
            continue
        for nadel in _nadeln(wert):
            kasten = _suche(worte, nadel)
            if not kasten:
                continue
            # Zwei Angaben auf denselben Kasten zu legen hilft niemandem —
            # der Nutzer sähe zwei Farben übereinander.
            schluessel = (kasten["x"], kasten["y"], kasten["b"], kasten["h"])
            if schluessel in belegt:
                break
            belegt.append(schluessel)
            aus.append({
                "art": eintrag.get("art") or "feld",
                "wert": wert,
                "x": round(kasten["x"] / breite, 5),
                "y": round(kasten["y"] / hoehe, 5),
                "b": round(kasten["b"] / breite, 5),
                "h": round(kasten["h"] / hoehe, 5),
            })
            break
    return aus
