#!/usr/bin/env python3
"""Bestandene Scans nachziehen: welcher Betrag, welches Datum käme per OCR?

Der Bestand des Nutzers enthält Hunderte Belege. Ein grosser Teil davon sind
reine Scans — PDFs ganz ohne Textschicht. Für sie hat CLXXIX den Weg Seite ->
Bild -> Tesseract gebaut. Dieses Werkzeug geht einen Ordner durch, findet die
Scans (die Text-PDFs überspringt es — die liest schon `pdftext`), und berichtet
je Datei, was die Erkennung herauslesen würde: Betrag, Datum, Art und Sache.

ABSOLUT BINDEND — der Ordner ist der Master des Nutzers:
  * Originale werden **nur gelesen**. Kein Schreiben, Überschreiben,
    Verschieben oder Löschen an irgendeiner PDF im Bestand.
  * Vorgabe ist ein **Trockenlauf**, der nur auf die Konsole berichtet.
  * Erst `--schreiben` legt die Ergebnisse ab — und dann NUR in eine getrennte
    JSON-Sidecar-Datei neben diesem Skript, nie am Ort des Originals.

Ohne Tesseract (etwa in der Devbox) bleibt die Erkennung stumm: das Werkzeug
findet die Scans und meldet sie, liest aber nichts heraus. Die echte Erkennung
greift erst im Container mit Tesseract.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime

# Das Werkzeug liegt in tools/; die Engine in api/. Ohne diesen Pfad findet der
# Import `app` nicht.
_HIER = os.path.dirname(os.path.abspath(__file__))
_API = os.path.join(os.path.dirname(_HIER), "api")
if _API not in sys.path:
    sys.path.insert(0, _API)

from app import ocr, pdftext  # noqa: E402

log = logging.getLogger("immocalc")

# Die Vorgabe: der Bestand des Nutzers, der neue Master.
STANDARD_ORDNER = os.path.join(os.path.dirname(_HIER), "immo_DATA")

# Wohin --schreiben die Ergebnisse legt: eine Sidecar-Datei neben dem Skript,
# nie im Bestand.
SIDECAR = os.path.join(_HIER, "ocr_nachziehen.json")


def finde_pdfs(wurzel: str) -> list[str]:
    """Alle PDFs unterhalb eines Ordners — nur lesend aufgelistet."""
    treffer: list[str] = []
    for ordner, _, dateien in os.walk(wurzel):
        for name in dateien:
            if name.lower().endswith(".pdf"):
                treffer.append(os.path.join(ordner, name))
    return sorted(treffer)


def hat_textschicht(rohdaten: bytes) -> bool:
    """Trägt das PDF schon Text? Dann ist es kein Scan und wird übersprungen —
    `pdftext` liest es ohnehin ohne Umweg über die Bilderkennung."""
    return bool(pdftext.text_aus_pdf(rohdaten).strip())


def pruefe_datei(pfad: str) -> dict:
    """Ein Scan, durch die Erkennung geschickt — rein lesend.

    `erkenne` nimmt genau den Weg, den auch der Upload nimmt: erst der
    eingebettete Text, dann die gerasterten Seiten durch Tesseract. Hier ist
    der Text leer (sonst wäre die Datei kein Scan), also greift der Rasterweg.
    """
    with open(pfad, "rb") as datei:          # nur lesen, nie schreiben
        rohdaten = datei.read()
    ergebnis = ocr.erkenne(rohdaten)
    return {
        "datei": pfad,
        "betrag": ergebnis.get("betrag"),
        "datum": ergebnis.get("datum"),
        "kategorie": ergebnis.get("kategorie"),
        "sache": ergebnis.get("sache"),
        "zeichen": ergebnis.get("zeichen", 0),
        "hinweis": ergebnis.get("hinweis", ""),
    }


def _zeile(fund: dict) -> str:
    """Eine Fundzeile für die Konsole — knapp und ausgerichtet."""
    name = os.path.basename(fund["datei"])
    betrag = f"{fund['betrag']:.2f} €" if fund["betrag"] is not None else "—"
    datum = fund["datum"] or "—"
    art = fund["kategorie"] or "—"
    sache = fund["sache"] or "—"
    return f"  {name[:48]:48}  {betrag:>12}  {datum:>10}  {art:12}  {sache}"


def laufe(wurzel: str, schreiben: bool, grenze: int | None) -> dict:
    """Geht den Ordner durch, berichtet je Scan. Ändert nie ein Original."""
    if not os.path.isdir(wurzel):
        raise SystemExit(f"Ordner nicht gefunden: {wurzel}")

    if not pdftext.kann_rastern():
        print("Hinweis: pypdfium2 fehlt — Scans lassen sich nicht rastern. "
              "Es wird nur gezählt, nicht gelesen.")
    if not ocr.verfuegbar():
        print("Hinweis: Tesseract fehlt (z. B. in der Devbox) — die echte "
              "Erkennung greift erst im Container. Es wird nur gezählt.")

    pdfs = finde_pdfs(wurzel)
    scans: list[str] = []
    mit_text = 0
    for pfad in pdfs:
        with open(pfad, "rb") as datei:      # nur lesen
            rohdaten = datei.read()
        if hat_textschicht(rohdaten):
            mit_text += 1
        else:
            scans.append(pfad)

    if grenze is not None:
        scans = scans[:grenze]

    print(f"\n{len(pdfs)} PDF(s) in {wurzel}")
    nachsatz = " (auf Grenze gekürzt)" if grenze is not None else ""
    print(f"  {mit_text} mit Textschicht (übersprungen), "
          f"{len(scans)} Scan(s) ohne Text{nachsatz}\n")
    print(f"  {'Datei':48}  {'Betrag':>12}  {'Datum':>10}  "
          f"{'Art':12}  Sache")
    print(f"  {'-' * 48}  {'-' * 12}  {'-' * 10}  {'-' * 12}  {'-' * 12}")

    funde: list[dict] = []
    erkannt = 0
    for pfad in scans:
        try:
            fund = pruefe_datei(pfad)
        except Exception as fehler:                        # noqa: BLE001
            log.warning("%s nicht lesbar: %s", pfad, fehler)
            fund = {"datei": pfad, "betrag": None, "datum": None,
                    "kategorie": "", "sache": "", "zeichen": 0,
                    "hinweis": f"nicht lesbar: {fehler}"}
        funde.append(fund)
        if fund["betrag"] is not None or fund["datum"]:
            erkannt += 1
        print(_zeile(fund))

    print(f"\n{erkannt} von {len(scans)} Scan(s) lieferten Betrag oder Datum.")

    bericht = {
        "erzeugt": datetime.now().isoformat(timespec="seconds"),
        "ordner": wurzel,
        "pdfs_gesamt": len(pdfs),
        "mit_textschicht": mit_text,
        "scans": len(scans),
        "erkannt": erkannt,
        "funde": funde,
    }

    if schreiben:
        # NUR in die Sidecar-Datei neben dem Skript — nie in den Bestand.
        with open(SIDECAR, "w", encoding="utf-8") as ziel:
            json.dump(bericht, ziel, ensure_ascii=False, indent=2)
        print(f"Ergebnisse geschrieben: {SIDECAR}")
        print("Kein Original wurde angefasst.")
    else:
        print("Trockenlauf — nichts geschrieben. Mit --schreiben landet der "
              f"Bericht in {os.path.basename(SIDECAR)} (nie im Bestand).")

    return bericht


def main() -> None:
    logging.basicConfig(level=logging.WARNING,
                        format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(
        description="Findet Scan-PDFs ohne Textschicht und berichtet, welchen "
                    "Betrag und welches Datum OCR herauslesen würde. Vorgabe "
                    "ist ein Trockenlauf; Originale werden nie verändert.")
    parser.add_argument("ordner", nargs="?", default=STANDARD_ORDNER,
                        help=f"Zu durchsuchender Ordner (Vorgabe: {STANDARD_ORDNER})")
    parser.add_argument("--schreiben", action="store_true",
                        help="Bericht zusätzlich als JSON-Sidecar neben dem "
                             "Skript ablegen (nie im Bestand).")
    parser.add_argument("--grenze", type=int, default=None,
                        help="Nur die ersten N Scans prüfen — für einen "
                             "schnellen Blick statt des ganzen Bestands.")
    args = parser.parse_args()
    laufe(args.ordner, args.schreiben, args.grenze)


if __name__ == "__main__":
    main()
