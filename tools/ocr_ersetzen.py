#!/usr/bin/env python3
"""Scan-PDFs durch durchsuchbare Varianten ersetzen (CXCV).

Legt eine UNSICHTBARE Textschicht über die Originalseiten — die Optik bleibt
Pixel für Pixel erhalten, es kommt nur ein durchsuchbarer/kopierbarer Text
dazu. OCR über RapidOCR (ONNX, keine System-Abhängigkeit); der Text wird an
den erkannten Wortkästen platziert.

SICHERHEIT — immo_DATA ist der Master:
  * Vorgabe ist ein TROCKENLAUF. Nur mit --wirklich wird etwas ersetzt.
  * Vor jeder Ersetzung wandert das Original unverändert in den Backup-Ordner.
  * Die neue Datei wird geprüft (öffnet, gleiche Seitenzahl, trägt jetzt Text),
    bevor sie das Original atomar ersetzt. Scheitert die Prüfung, bleibt das
    Original unangetastet.
  * Text-PDFs (haben schon eine Textschicht) werden übersprungen — dadurch ist
    der Lauf wiederaufsetzbar: ein zweiter Durchlauf fasst nur noch die an, die
    beim ersten scheiterten.

Aufruf:
  python tools/ocr_ersetzen.py [ordner] [--wirklich] [--grenze N]
    ordner    Vorgabe: das immo_DATA neben diesem Repo
    --wirklich  ersetzt wirklich (sonst nur Bericht)
    --grenze N  höchstens N Dateien bearbeiten (für einen Testlauf)
"""
from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
import time
from pathlib import Path

import fitz  # PyMuPDF
import numpy as np
from rapidocr_onnxruntime import RapidOCR

HIER = Path(__file__).resolve().parent
REPO = HIER.parent
STD_ORDNER = REPO / "immo_DATA"
BACKUP = REPO / "analyse" / "ocr-backup"          # git-ignoriert
LOG = HIER / "ocr_ersetzen.log"                    # git-ignoriert

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s  %(message)s",
    handlers=[logging.FileHandler(LOG, encoding="utf-8"),
              logging.StreamHandler(sys.stdout)])
log = logging.getLogger("ocr-ersetzen")

DPI = 220
MIN_ZEICHEN = 12          # so viel Text muss die neue Datei mindestens tragen

_ocr: RapidOCR | None = None


def ocr_engine() -> RapidOCR:
    global _ocr
    if _ocr is None:
        _ocr = RapidOCR()
    return _ocr


def hat_textschicht(pfad: Path) -> bool:
    """Trägt die PDF schon durchsuchbaren Text? Dann nichts zu tun."""
    try:
        with fitz.open(pfad) as d:
            return sum(len(s.get_text().strip()) for s in d) >= MIN_ZEICHEN
    except Exception:                              # noqa: BLE001
        return False


def _durchsuchbar_machen(quelle: Path, ziel: Path) -> int:
    """Baut aus `quelle` eine durchsuchbare Kopie nach `ziel`.

    Die Originalseiten bleiben unverändert; je Seite wird ihr gerendertes Bild
    per OCR gelesen und der Text unsichtbar (render_mode 3) an den Wortkästen
    eingefügt. Gibt die Zahl der insgesamt geschriebenen Zeichen zurück."""
    engine = ocr_engine()
    zeichen = 0
    with fitz.open(quelle) as doc:
        for seite in doc:
            pm = seite.get_pixmap(dpi=DPI)
            arr = np.frombuffer(pm.samples, dtype=np.uint8).reshape(
                pm.height, pm.width, pm.n)
            if pm.n == 4:                          # RGBA -> RGB
                arr = arr[:, :, :3]
            treffer, _ = engine(np.ascontiguousarray(arr))
            if not treffer:
                continue
            # Bildpixel -> PDF-Punkte
            skala = 72.0 / DPI
            for box, text, score in treffer:
                if not text or score < 0.3:
                    continue
                xs = [p[0] for p in box]
                ys = [p[1] for p in box]
                x0, y1 = min(xs) * skala, max(ys) * skala
                hoehe = (max(ys) - min(ys)) * skala
                fs = max(hoehe * 0.85, 4)
                try:
                    seite.insert_text((x0, y1 - hoehe * 0.15), text,
                                      fontsize=fs, render_mode=3,
                                      color=(0, 0, 0))
                    zeichen += len(text)
                except Exception:                  # noqa: BLE001
                    pass
        doc.save(ziel, garbage=3, deflate=True)
    return zeichen


def _pruefe(original: Path, neu: Path) -> tuple[bool, str]:
    """Ist die neue Datei brauchbar und wirklich durchsuchbar geworden?"""
    if not neu.exists() or neu.stat().st_size < 1024:
        return False, "neue Datei fehlt oder ist zu klein"
    try:
        with fitz.open(original) as a, fitz.open(neu) as b:
            if b.page_count != a.page_count:
                return False, f"Seitenzahl {b.page_count} != {a.page_count}"
            text = sum(len(s.get_text().strip()) for s in b)
    except Exception as fehler:                    # noqa: BLE001
        return False, f"nicht lesbar: {fehler}"
    if text < MIN_ZEICHEN:
        return False, "keine Textschicht entstanden (nichts erkannt)"
    return True, f"{text} Zeichen"


def ersetze(pfad: Path, wirklich: bool) -> str:
    """Eine Datei bearbeiten. Gibt ein Kürzel des Ergebnisses zurück."""
    tmp = pfad.with_suffix(pfad.suffix + ".ocrtmp")
    try:
        _durchsuchbar_machen(pfad, tmp)
    except Exception as fehler:                    # noqa: BLE001
        tmp.unlink(missing_ok=True)
        log.warning("  FEHLER beim Erzeugen: %s — %s", pfad.name, fehler)
        return "fehler"

    ok, grund = _pruefe(pfad, tmp)
    if not ok:
        tmp.unlink(missing_ok=True)
        log.warning("  übersprungen (%s): %s", grund, pfad.name)
        return "verworfen"

    if not wirklich:
        tmp.unlink(missing_ok=True)
        log.info("  wäre ersetzt (%s): %s", grund, pfad.name)
        return "trocken"

    # Original zuerst sichern, dann atomar tauschen.
    rel = pfad.relative_to(STAMM)
    sicher = BACKUP / rel
    sicher.parent.mkdir(parents=True, exist_ok=True)
    if not sicher.exists():                        # Backup nie überschreiben
        shutil.copy2(pfad, sicher)
    os.replace(tmp, pfad)
    log.info("  ersetzt (%s, Backup: %s): %s", grund,
             sicher.relative_to(REPO), pfad.name)
    return "ersetzt"


STAMM = STD_ORDNER


def main() -> None:
    global STAMM
    ap = argparse.ArgumentParser()
    ap.add_argument("ordner", nargs="?", default=str(STD_ORDNER))
    ap.add_argument("--wirklich", action="store_true")
    ap.add_argument("--grenze", type=int, default=0)
    args = ap.parse_args()

    STAMM = Path(args.ordner).resolve()
    if not STAMM.is_dir():
        log.error("Ordner nicht gefunden: %s", STAMM)
        sys.exit(1)

    pdfs = sorted(STAMM.rglob("*.pdf"))
    scans = [p for p in pdfs if not hat_textschicht(p)]
    log.info("=== %s ===", "ERSETZEN (wirklich)" if args.wirklich
             else "TROCKENLAUF — es wird nichts verändert")
    log.info("%d PDFs, davon %d mit Textschicht (übersprungen), %d Scans",
             len(pdfs), len(pdfs) - len(scans), len(scans))
    if args.grenze:
        scans = scans[:args.grenze]
        log.info("Grenze: nur die ersten %d Scans", len(scans))

    zaehler: dict[str, int] = {}
    t0 = time.time()
    for i, pfad in enumerate(scans, 1):
        log.info("[%d/%d] %s", i, len(scans), pfad.relative_to(STAMM))
        erg = ersetze(pfad, args.wirklich)
        zaehler[erg] = zaehler.get(erg, 0) + 1

    dauer = time.time() - t0
    log.info("=== fertig in %.0f s · %s ===", dauer,
             " · ".join(f"{k}: {v}" for k, v in sorted(zaehler.items())))


if __name__ == "__main__":
    main()
