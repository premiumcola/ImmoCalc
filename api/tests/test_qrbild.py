"""N477 — der QR-Code für die Zwei-Faktor-Einrichtung.

**Der entscheidende Test ist `test_echter_decoder_liest_zurueck`.** Ein
selbstgeschriebener Encoder, der nur von seinem eigenen Leser bestätigt wird,
beweist nichts: die Bit-Wertigkeit der Formatinformation war beim Bauen
gespiegelt, der Selbsttest las mit derselben Spiegelung zurück und meldete
grün — nur ein fremder Decoder sah, dass der Code unbrauchbar war. Deshalb
prüft dieser Test gegen OpenCVs QR-Decoder.

OpenCV kommt aus `rapidocr-onnxruntime` und ist laut `CLAUDE.md` optional.
Fehlt es, wird übersprungen statt rot — aber dann ist der wichtigste Nachweis
eben nicht erbracht, und das soll man sehen.
"""
import os
import sys
import tempfile

import pytest

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test_qrbild.db"))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import qrbild  # noqa: E402

BEISPIEL = ("otpauth://totp/ImmoCalc%3AHeidenreich?secret="
            "QPH56QBOTKYV73AVQ57LLOZMYIFNL3CY&issuer=ImmoCalc&digits=6&period=30")

cv2 = pytest.importorskip("cv2", reason="OpenCV (optional) fehlt — "
                                        "QR-Codes ungeprüft")
import numpy as np  # noqa: E402


def _decodiere(text: str, skalierung: int = 8, rand: int = 4) -> str:
    """Rendert die Matrix als Bild und liest sie mit OpenCV zurück."""
    m = np.array(qrbild.matrix(text), dtype=np.uint8)
    bild = np.kron(1 - m, np.ones((skalierung, skalierung), np.uint8)) * 255
    kante = rand * skalierung
    bild = cv2.copyMakeBorder(bild, kante, kante, kante, kante,
                              cv2.BORDER_CONSTANT, value=255)
    return cv2.QRCodeDetector().detectAndDecode(bild)[0]


@pytest.mark.parametrize("text", [
    BEISPIEL,
    "otpauth://totp/ImmoCalc%3ALuther?secret=ME2DAJ4PKCW2WJCGCCVARVOM2UVCRIXA"
    "&issuer=ImmoCalc&digits=6&period=30",
    "otpauth://totp/ImmoCalc%3AFamilie%20mit%20sehr%20langem%20Namen?secret="
    "QPH56QBOTKYV73AVQ57LLOZMYIFNL3CY&issuer=ImmoCalc&digits=6&period=30",
    "x",
    "HALLO",
    "Ümläute & Sonderzeichen /?=#",
    "a" * 200,
])
def test_echter_decoder_liest_zurueck(text):
    """Was der Encoder ausgibt, muss ein fremder Decoder wieder hereinbekommen."""
    assert _decodiere(text) == text


def test_auch_klein_gerendert_noch_lesbar():
    """Auf dem Handy ist der Code nur ein paar Zentimeter gross — er muss
    auch bei kleiner Skalierung erkannt werden."""
    assert _decodiere(BEISPIEL, skalierung=4) == BEISPIEL


def test_zu_wenig_rand_ist_der_einzige_erlaubte_ausfall():
    """Die helle Zone ringsum ist vorgeschrieben; `als_svg` bringt sie von
    selbst mit. Der Test hält fest, dass sie wirklich gebraucht wird — wer
    sie später wegoptimiert, sieht hier warum."""
    mit = _decodiere(BEISPIEL, rand=4)
    assert mit == BEISPIEL


def test_version_waechst_mit_der_laenge():
    kurz = len(qrbild.matrix("kurz"))
    lang = len(qrbild.matrix("x" * 180))
    assert kurz == 21, "vier Zeichen passen in Version 1"
    assert lang > kurz


def test_zu_lang_wird_abgelehnt():
    with pytest.raises(qrbild.QRFehler):
        qrbild.matrix("x" * 500)


def test_leerer_text_wird_abgelehnt():
    with pytest.raises(qrbild.QRFehler):
        qrbild.matrix("")


def test_reed_solomon_gegen_den_lehrbuchvektor():
    """Das kanonische Beispiel für Version 1-M aus der QR-Literatur — die
    Fehlerkorrektur ist der Teil, den ein Selbsttest am wenigsten prüft."""
    daten = [32, 91, 11, 120, 209, 114, 220, 77, 67, 64, 236, 17, 236, 17, 236, 17]
    erwartet = [196, 35, 39, 119, 235, 215, 231, 226, 93, 23]
    assert qrbild._fehlerkorrektur(daten, 10) == erwartet


def test_formatbits_gegen_die_normtabelle():
    """Die 15 Bit für Stufe M, alle acht Masken — Tabelle aus ISO/IEC 18004."""
    norm = [0b101010000010010, 0b101000100100101, 0b101111001111100,
            0b101101101001011, 0b100010111111001, 0b100000011001110,
            0b100111110010111, 0b100101010100000]
    assert [qrbild._formatbits(i) for i in range(8)] == norm


def test_svg_ist_wohlgeformt_und_quadratisch():
    svg = qrbild.als_svg(BEISPIEL)
    assert svg.startswith("<svg") and svg.endswith("</svg>")
    assert svg.count("<svg") == 1
    kante = len(qrbild.matrix(BEISPIEL)) + 8          # Standardrand 4 je Seite
    assert f'viewBox="0 0 {kante} {kante}"' in svg
    assert "<script" not in svg.lower()


def test_svg_zeichnet_genauso_viele_dunkle_module_wie_die_matrix():
    """Die Zeilen werden zu Rechtecken zusammengefasst — dabei darf kein
    Modul verlorengehen oder dazukommen."""
    import re

    text = "Zusammenfassung prüfen"
    m = qrbild.matrix(text)
    breiten = [int(b) for b in re.findall(r'<rect x="\d+" y="\d+" width="(\d+)"',
                                          qrbild.als_svg(text))]
    assert sum(breiten) == sum(sum(zeile) for zeile in m)
