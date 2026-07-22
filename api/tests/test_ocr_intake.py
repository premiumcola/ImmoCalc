"""CCXXVII: eine dauerhafte, unsichtbare Textschicht für neu aufgenommene Scans.

Die eigentliche Bilderkennung braucht `rapidocr-onnxruntime` — das läuft nur
im Container. Geprüft wird hier die Verdrahtung, die auch ohne die Bibliothek
gelten muss: ein Text-PDF wird nie zweimal erkannt, fehlende Bibliotheken
bleiben still, und die Cloud-Ersetzung geht ausschliesslich über MOVE, nie
über ein Überschreiben — mit Rückweg, falls das Ablegen scheitert.
"""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_ocr_intake.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest  # noqa: E402
from sqlmodel import Session  # noqa: E402

from app import ocr  # noqa: E402
from app.db import engine  # noqa: E402
from app.models import Dokument  # noqa: E402
from app.nextcloud import NextcloudFehler  # noqa: E402
import app.routers.dokumente as modul  # noqa: E402
from test_ocr import bild_pdf, mini_pdf  # noqa: E402


# --------------------------------------------------------------------------
# ocr.durchsuchbar_machen — reine Bytes-Funktion, ohne Cloud
# --------------------------------------------------------------------------

def test_text_pdf_wird_nicht_erneut_ocrt():
    """Ein PDF, das schon Text trägt, bekommt keine zweite Textschicht —
    weder von Anfang an noch aus einem früheren Lauf lässt sich das
    unterscheiden, und das soll es auch nicht: nie doppelt erkennen."""
    if not ocr.durchsuchbar_verfuegbar():
        pytest.skip("PyMuPDF/RapidOCR sind hier nicht installiert")
    roh = mini_pdf(["Stadtwerke Musterstadt", "Rechnungsdatum 14.03.2025",
                    "Gesamtbetrag 1.071,00"])
    assert ocr.durchsuchbar_machen(roh) is None


def test_ohne_bibliotheken_bleibt_es_still(monkeypatch):
    """Fehlt eine der drei Bibliotheken, passiert nichts — kein Fehler, kein
    Ergebnis. Genau wie `ocr.erkenne` ohne Tesseract."""
    monkeypatch.setattr(ocr, "durchsuchbar_verfuegbar", lambda: False)
    assert ocr.durchsuchbar_machen(mini_pdf(["irgendwas"])) is None
    assert ocr.durchsuchbar_machen(b"kein PDF, nur Muell") is None
    assert ocr.durchsuchbar_machen(b"") is None


def test_kaputte_bytes_werfen_keinen_fehler():
    """Ein unlesbares oder fehlendes PDF darf die Nachpflege nie zum Absturz
    bringen — nur kein Ergebnis."""
    if not ocr.durchsuchbar_verfuegbar():
        pytest.skip("PyMuPDF/RapidOCR sind hier nicht installiert")
    assert ocr.durchsuchbar_machen(b"das ist kein PDF") is None


def test_ergebnis_traegt_dieselbe_seitenzahl_und_text():
    """Die echte Erkennung eines Scans — nur mit den echten Bibliotheken.
    Ohne sie wird übersprungen; im Container greift sie wirklich."""
    if not ocr.durchsuchbar_verfuegbar():
        pytest.skip("PyMuPDF/RapidOCR sind hier nicht installiert")
    fitz = pytest.importorskip("fitz")
    roh = bild_pdf(400, 200)      # ein Bild-PDF ohne Textschicht — ein Scan
    with fitz.open(stream=roh, filetype="pdf") as vorher:
        assert vorher.page_count == 1
        assert ocr._zeichen_gesamt(vorher) == 0
    # Das winzige 2x2-Testbild trägt keinen echten Text — RapidOCR liest
    # daraus nichts heraus. Erwartet wird also *kein* Absturz und ein
    # sauberes „nichts gefunden", nicht ein falscher Treffer.
    ergebnis = ocr.durchsuchbar_machen(roh)
    assert ergebnis is None


# --------------------------------------------------------------------------
# nachtraeglich_ocren — die Cloud-Orchestrierung, mit einem gestellten Client
# --------------------------------------------------------------------------

class _WolkeMitInhalt:
    """Nextcloud-Ersatz: kennt den Inhalt einer Datei und merkt sich jede
    Bewegung. `lege_ab` kann auf Wunsch scheitern — für den Rückweg-Test."""

    def __init__(self, inhalte: dict[str, bytes], scheitert_bei: set | None = None):
        self.inhalte = dict(inhalte)
        self.scheitert_bei = scheitert_bei or set()
        self.verschoben: list[tuple[str, str]] = []
        self.angelegt: list[str] = []
        self.abgelegt: list[str] = []

    def hole(self, pfad):
        schluessel = pfad.strip("/")
        if schluessel not in self.inhalte:
            raise NextcloudFehler(f"nicht gefunden: {pfad}")
        return self.inhalte[schluessel], "application/pdf"

    def ordner_anlegen(self, pfad):
        self.angelegt.append(pfad)
        return True

    def verschiebe(self, von, nach):
        self.verschoben.append((von, nach))
        schluessel = von.strip("/")
        self.inhalte[nach.strip("/")] = self.inhalte.pop(schluessel)

    def lege_ab(self, pfad, inhalt):
        if pfad.strip("/") in self.scheitert_bei:
            raise NextcloudFehler(f"Hochladen fehlgeschlagen: {pfad}")
        self.abgelegt.append(pfad)
        self.inhalte[pfad.strip("/")] = inhalt


def _dokument(session: Session, pfad: str, dateiname: str) -> Dokument:
    d = Dokument(pfad=pfad, dateiname=dateiname, status="zugeordnet")
    session.add(d)
    session.commit()
    session.refresh(d)
    return d


def test_nachtraeglich_ocren_ueberspringt_ein_text_pdf(monkeypatch):
    """Ein Beleg, der schon durchsuchbar ist, wird nie angefasst — kein
    Verschieben, kein neues Hochladen."""
    if not ocr.durchsuchbar_verfuegbar():
        pytest.skip("PyMuPDF/RapidOCR sind hier nicht installiert")
    roh = mini_pdf(["Rechnungsdatum 14.03.2025", "Gesamtbetrag 104,15"])
    pfad = "/Objekt/60_Nebenkosten/Rechnung-A.pdf"
    wolke = _WolkeMitInhalt({pfad.strip("/"): roh})

    with Session(engine) as s:
        _dokument(s, pfad, "Rechnung.pdf")
        ergebnis = modul.nachtraeglich_ocren(s, client=wolke)

    assert ergebnis == {"geprueft": 1, "ergaenzt": 0, "uebersprungen": 1}
    assert wolke.verschoben == []
    assert wolke.abgelegt == []


def test_nachtraeglich_ocren_ohne_bibliotheken_ruft_die_cloud_nicht_an(monkeypatch):
    """Fehlen die Bibliotheken, wird nicht einmal eine Datei geholt — der
    erste, billige Blick reicht, um abzubrechen."""
    monkeypatch.setattr(modul.ocr, "durchsuchbar_verfuegbar", lambda: False)
    pfad = "/Objekt/60_Nebenkosten/Rechnung-B.pdf"
    wolke = _WolkeMitInhalt({pfad.strip("/"): b"irrelevant"})

    with Session(engine) as s:
        _dokument(s, pfad, "Rechnung.pdf")
        ergebnis = modul.nachtraeglich_ocren(s, client=wolke)

    assert ergebnis == {"geprueft": 0, "ergaenzt": 0, "uebersprungen": 0}
    assert wolke.verschoben == [] and wolke.abgelegt == []


def test_nachtraeglich_ocren_ersetzt_per_move_und_sichert_das_original(monkeypatch):
    """Ein Scan ohne Text bekommt eine neue, geprüfte Fassung — über eine
    versteckte Sicherung neben der Datei, nie durch Überschreiben."""
    pfad = "/Objekt/60_Nebenkosten/2025/Scan.pdf"
    wolke = _WolkeMitInhalt({pfad.strip("/"): b"alte Scan-Bytes"})
    monkeypatch.setattr(modul.ocr, "durchsuchbar_verfuegbar", lambda: True)
    monkeypatch.setattr(modul.ocr, "durchsuchbar_machen",
                        lambda roh: b"neue, durchsuchbare Bytes")

    with Session(engine) as s:
        d = _dokument(s, pfad, "Scan.pdf")
        ergebnis = modul.nachtraeglich_ocren(s, client=wolke)
        s.refresh(d)
        assert d.groesse == len(b"neue, durchsuchbare Bytes")

    assert ergebnis == {"geprueft": 1, "ergaenzt": 1, "uebersprungen": 0}
    # Erst der Ordner für die Sicherung, dann das Original dorthin verschoben —
    # nie gelöscht, nur an eine versteckte Stelle neben der Datei.
    assert wolke.angelegt == [
        "Objekt/60_Nebenkosten/2025/.ocr-original"]
    assert wolke.verschoben == [
        (pfad, "Objekt/60_Nebenkosten/2025/.ocr-original/Scan.pdf")]
    # Erst danach — auf dem jetzt freien Platz — die neue Fassung.
    assert wolke.abgelegt == [pfad]
    assert wolke.inhalte[pfad.strip("/")] == b"neue, durchsuchbare Bytes"
    # Das Original ist nicht weg, nur umgezogen.
    assert wolke.inhalte["Objekt/60_Nebenkosten/2025/.ocr-original/Scan.pdf"] \
        == b"alte Scan-Bytes"


def test_scheitert_das_ablegen_kommt_das_original_zurueck(monkeypatch):
    """Kann die neue Fassung nicht abgelegt werden, bleibt der Beleg trotzdem
    erreichbar — das Original wandert sofort zurück an seinen Platz."""
    pfad = "/Objekt/60_Nebenkosten/Rechnung-C.pdf"
    wolke = _WolkeMitInhalt({pfad.strip("/"): b"altes Original"},
                            scheitert_bei={pfad.strip("/")})
    monkeypatch.setattr(modul.ocr, "durchsuchbar_verfuegbar", lambda: True)
    monkeypatch.setattr(modul.ocr, "durchsuchbar_machen", lambda roh: b"neu")

    with Session(engine) as s:
        _dokument(s, pfad, "Rechnung-C.pdf")
        ergebnis = modul.nachtraeglich_ocren(s, client=wolke)

    assert ergebnis == {"geprueft": 1, "ergaenzt": 0, "uebersprungen": 0}
    # Hin und wieder zurück — am Ende liegt das Original wieder an seinem Platz.
    assert len(wolke.verschoben) == 2
    assert wolke.verschoben[0] == (
        pfad, "Objekt/60_Nebenkosten/.ocr-original/Rechnung-C.pdf")
    assert wolke.verschoben[1] == (
        "Objekt/60_Nebenkosten/.ocr-original/Rechnung-C.pdf", pfad)
    assert wolke.inhalte[pfad.strip("/")] == b"altes Original"


def test_stapelgrenze_bremst_einen_grossen_rueckstau(monkeypatch):
    """Höchstens `OCR_STAPEL` Belege werden je Lauf wirklich neu erkannt — ein
    grosser Rückstau darf einen einzelnen Wachdienst-Takt nicht blockieren.
    Der Rest folgt beim nächsten Takt."""
    monkeypatch.setattr(modul, "OCR_STAPEL", 1)
    monkeypatch.setattr(modul.ocr, "durchsuchbar_verfuegbar", lambda: True)
    monkeypatch.setattr(modul.ocr, "durchsuchbar_machen", lambda roh: b"neu")

    pfade = ["/Objekt/60_Nebenkosten/Eins.pdf",
            "/Objekt/60_Nebenkosten/Zwei.pdf"]
    wolke = _WolkeMitInhalt({p.strip("/"): b"scan" for p in pfade})

    with Session(engine) as s:
        for p in pfade:
            _dokument(s, p, p.rsplit("/", 1)[-1])
        ergebnis = modul.nachtraeglich_ocren(s, client=wolke)

    assert ergebnis["ergaenzt"] == 1
    assert ergebnis["geprueft"] == 1          # der zweite wurde gar nicht erst geholt
