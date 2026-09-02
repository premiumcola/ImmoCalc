"""N440 — hinterlegte Unterschrift: speichern, prüfen, aufs PDF legen."""
import io
import math
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_unterschrift.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import base64  # noqa: E402
from datetime import date  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.abrechnung_pdf import abrechnung_pdf  # noqa: E402
from app.main import app  # noqa: E402
from app.pdfbild import BildFehler, lade_png  # noqa: E402


def _unterschrift_png(breite=600, hoehe=200) -> bytes:
    """Eine handschriftartige Linie auf durchsichtigem Grund."""
    from PIL import Image, ImageDraw

    bild = Image.new("RGBA", (breite, hoehe), (0, 0, 0, 0))
    stift = ImageDraw.Draw(bild)
    punkte = [(20 + i, hoehe / 2 - 40 * math.sin(i / 30.0))
              for i in range(breite - 40)]
    stift.line(punkte, fill=(16, 32, 90, 255), width=5)
    puffer = io.BytesIO()
    bild.save(puffer, format="PNG")
    return puffer.getvalue()


def _als_datenurl(rohdaten: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(rohdaten).decode("ascii")


# ---------------------------------------------------------------- Bildteil
def test_transparentes_png_wird_in_farbe_und_maske_zerlegt():
    teile = lade_png(_unterschrift_png())
    assert teile["breite"] == 600 and teile["hoehe"] == 200
    assert teile["daten"], "Farbkanäle fehlen"
    assert teile["alpha"], "ohne Maske wäre die Unterschrift ein weißer Kasten"


def test_bild_ohne_transparenz_braucht_keine_maske():
    from PIL import Image

    puffer = io.BytesIO()
    Image.new("RGB", (40, 20), (255, 255, 255)).save(puffer, format="PNG")
    assert lade_png(puffer.getvalue())["alpha"] is None


def test_kaputte_datei_wird_mit_klartext_abgelehnt():
    with pytest.raises(BildFehler):
        lade_png(b"das ist kein bild")


def test_grosses_bild_wird_verkleinert():
    """Ein Kamerafoto darf den Mailanhang nicht sprengen."""
    teile = lade_png(_unterschrift_png(4000, 1200))
    assert max(teile["breite"], teile["hoehe"]) <= 1200


# ---------------------------------------------------------------- PDF-Teil
def test_unterschrift_landet_als_bild_mit_maske_im_pdf():
    posten = [{"name": "Heizung", "schluessel": "Wärmemenge",
               "gesamtkosten": 100.0, "betrag": 50.0, "s35": False}]
    roh = abrechnung_pdf("Haus", "01.01.2025 – 31.12.2025", "Mieter",
                         {"kosten": 50.0, "vorauszahlungen": 40.0,
                          "saldo": -10.0, "s35": 0}, posten, "Vermieter",
                         erstellt_am=date(2026, 9, 2),
                         unterschrift_png=_unterschrift_png())
    assert roh.startswith(b"%PDF")
    assert b"/Subtype /Image" in roh
    assert b"/SMask" in roh, "ohne SMask wäre die Transparenz verloren"
    assert b"/ImSig Do" in roh, "das Bild wird nirgends gezeichnet"


def test_ohne_unterschrift_bleibt_das_pdf_ohne_bild():
    posten = [{"name": "Heizung", "schluessel": "Wärmemenge",
               "gesamtkosten": 100.0, "betrag": 50.0, "s35": False}]
    roh = abrechnung_pdf("Haus", "01.01.2025 – 31.12.2025", "Mieter",
                         {"kosten": 50.0, "vorauszahlungen": 40.0,
                          "saldo": -10.0, "s35": 0}, posten, "Vermieter",
                         erstellt_am=date(2026, 9, 2))
    assert b"/Subtype /Image" not in roh
    assert b"/XObject" not in roh


def test_eine_unbrauchbare_unterschrift_verhindert_die_abrechnung_nicht():
    """Wichtiger als die Unterschrift ist, dass die Abrechnung rausgeht."""
    posten = [{"name": "Heizung", "schluessel": "Wärmemenge",
               "gesamtkosten": 100.0, "betrag": 50.0, "s35": False}]
    roh = abrechnung_pdf("Haus", "01.01.2025 – 31.12.2025", "Mieter",
                         {"kosten": 50.0, "vorauszahlungen": 40.0,
                          "saldo": -10.0, "s35": 0}, posten, "Vermieter",
                         erstellt_am=date(2026, 9, 2),
                         unterschrift_png=b"kein bild")
    assert roh.startswith(b"%PDF")
    assert b"/Subtype /Image" not in roh


def test_das_pdf_bleibt_lesbar_und_zeigt_das_bild():
    """Gegenprobe mit einem echten PDF-Leser statt nur Byte-Suche."""
    fitz = pytest.importorskip("fitz")
    posten = [{"name": "Heizung", "schluessel": "Wärmemenge",
               "gesamtkosten": 100.0, "betrag": 50.0, "s35": False}]
    roh = abrechnung_pdf("Haus", "01.01.2025 – 31.12.2025", "Mieter",
                         {"kosten": 50.0, "vorauszahlungen": 40.0,
                          "saldo": -10.0, "s35": 0}, posten, "Vermieter",
                         erstellt_am=date(2026, 9, 2),
                         unterschrift_png=_unterschrift_png())
    doc = fitz.open(stream=roh, filetype="pdf")
    bilder = doc[0].get_images()
    assert len(bilder) == 1, f"erwartet genau ein Bild, bekam {bilder}"
    assert bilder[0][2:4] == (600, 200)


# ---------------------------------------------------------------- Endpunkte
def test_unterschrift_speichern_lesen_entfernen():
    with TestClient(app) as c:
        assert c.get("/api/unterschrift").json() == {"vorhanden": False,
                                                     "vorschau": ""}
        antwort = c.put("/api/unterschrift",
                        json={"png": _als_datenurl(_unterschrift_png())})
        assert antwort.status_code == 200, antwort.text
        assert antwort.json()["transparent"] is True

        stand = c.get("/api/unterschrift").json()
        assert stand["vorhanden"] is True
        assert stand["vorschau"].startswith("data:image/png;base64,")

        assert c.delete("/api/unterschrift").status_code == 204
        assert c.get("/api/unterschrift").json()["vorhanden"] is False


def test_unbrauchbare_datei_wird_beim_speichern_abgelehnt():
    """Sonst fiele es erst beim Versand auf — dann ginge der Brief still
    ohne Unterschrift raus."""
    with TestClient(app) as c:
        antwort = c.put("/api/unterschrift", json={
            "png": _als_datenurl(b"das ist kein bild")})
        assert antwort.status_code == 400
        assert c.get("/api/unterschrift").json()["vorhanden"] is False


def test_zu_grosse_datei_wird_abgelehnt():
    with TestClient(app) as c:
        antwort = c.put("/api/unterschrift",
                        json={"png": _als_datenurl(b"x" * (2 * 1024 * 1024 + 1))})
        assert antwort.status_code == 400
        assert "groß" in antwort.json()["detail"]
