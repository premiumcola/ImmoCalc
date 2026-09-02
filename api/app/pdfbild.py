"""N440 — ein PNG mit Transparenz als PDF-Bild einbetten.

Gebraucht für die hinterlegte Unterschrift auf der Abrechnung: sie soll über
der Unterschriftslinie liegen, als wäre wirklich unterschrieben worden — also
freigestellt, ohne weißen Kasten drumherum.

PDF kann Transparenz nicht im Bild selbst: ein Bild trägt nur Farbkanäle. Die
Durchsichtigkeit kommt über eine **SMask** — ein zweites, graustufiges Bild
gleicher Größe, dessen Helligkeit die Deckung angibt (0 = unsichtbar,
255 = voll). Deshalb wird das PNG hier in zwei Teile zerlegt: Farbe nach
`daten`, Alphakanal nach `alpha`. Beides Flate-gepackt, wie es das
PDF-Bildobjekt erwartet.

Pillow steht dafür ausdrücklich in `requirements.txt`. Es war vorher schon im
Image, aber nur als Beifang von `rapidocr-onnxruntime` — und das ist laut
CLAUDE.md optional („ohne tesseract einfach stumm"). Eine Kernfunktion darf
nicht an einer optionalen Abhängigkeit hängen; ein schlankeres Image ohne OCR
hätte die Unterschrift sonst stillschweigend verloren.
"""
from __future__ import annotations

import io
import logging
import zlib

log = logging.getLogger("immocalc")

# Mehr Pixel bringen auf einer Unterschrift von ~5 cm Breite nichts mehr,
# blähen das PDF aber auf — jede Abrechnung geht als Mailanhang raus.
MAX_KANTE = 1200


class BildFehler(ValueError):
    """Das Bild lässt sich nicht verwenden — mit einem Satz für den Nutzer."""


def lade_png(rohdaten: bytes) -> dict:
    """Ein PNG in die Teile zerlegen, die ein PDF-Bildobjekt braucht.

    Gibt `{breite, hoehe, daten, alpha}` zurück; `alpha` ist `None`, wenn das
    Bild keinerlei Transparenz trägt (dann braucht es auch keine SMask).
    """
    try:
        from PIL import Image                       # noqa: PLC0415
    except ImportError as fehler:                   # pragma: no cover
        raise BildFehler("Bildverarbeitung steht auf dem Server nicht "
                         "bereit.") from fehler

    try:
        bild = Image.open(io.BytesIO(rohdaten))
        bild.load()
    except Exception as fehler:                     # noqa: BLE001
        raise BildFehler("Die Datei ließ sich nicht als Bild lesen.") from fehler

    if bild.width < 2 or bild.height < 2:
        raise BildFehler("Das Bild ist zu klein.")

    # Verkleinern, bevor die Kanäle getrennt werden — spart Speicher und
    # hält den Mailanhang klein.
    if max(bild.width, bild.height) > MAX_KANTE:
        bild.thumbnail((MAX_KANTE, MAX_KANTE))

    bild = bild.convert("RGBA")
    alpha_kanal = bild.getchannel("A")
    # Ein Bild ohne jede Transparenz braucht keine Maske.
    hat_transparenz = alpha_kanal.getextrema()[0] < 255

    return {
        "breite": bild.width,
        "hoehe": bild.height,
        "daten": zlib.compress(bild.convert("RGB").tobytes(), 6),
        "alpha": zlib.compress(alpha_kanal.tobytes(), 6) if hat_transparenz
                 else None,
    }


def auf_weiss_gelegt(rohdaten: bytes) -> bytes:
    """Das Bild ohne Alphakanal, auf Weiß gerechnet — für die Vorschau in der
    Oberfläche, wo Transparenz auf hellem Grund ohnehin weiß aussieht."""
    from PIL import Image                           # noqa: PLC0415

    bild = Image.open(io.BytesIO(rohdaten)).convert("RGBA")
    grund = Image.new("RGB", bild.size, (255, 255, 255))
    grund.paste(bild, mask=bild.getchannel("A"))
    puffer = io.BytesIO()
    grund.save(puffer, format="PNG")
    return puffer.getvalue()


# Kantenlänge des Familienlogos. Es erscheint als 42-px-Kachel in der Liste
# und auf dem Anmeldescreen — 256 px reichen auch auf einem scharfen Display
# und halten die Data-URL in der Datenbankzeile klein.
LOGO_KANTE = 256


def als_logo(rohdaten: bytes) -> bytes:
    """N444 — ein beliebiges Bild zu einem quadratischen PNG-Logo machen.

    Quadratisch, weil die Kachel quadratisch ist: ein Querformat würde sonst
    entweder verzerrt oder mit Rändern angezeigt. Zugeschnitten wird mittig
    auf das größtmögliche Quadrat — der übliche Bildausschnitt, wenn niemand
    etwas anderes sagt. Transparenz bleibt erhalten (PNG mit Alphakanal),
    damit ein freigestelltes Wappen nicht plötzlich einen weißen Kasten
    bekommt."""
    from PIL import Image                            # noqa: PLC0415

    try:
        bild = Image.open(io.BytesIO(rohdaten))
        bild.load()
    except Exception as fehler:                      # noqa: BLE001
        raise BildFehler("Die Datei ließ sich nicht als Bild lesen.") from fehler

    bild = bild.convert("RGBA")
    kante = min(bild.width, bild.height)
    if kante < 2:
        raise BildFehler("Das Bild ist zu klein.")
    links = (bild.width - kante) // 2
    oben = (bild.height - kante) // 2
    bild = bild.crop((links, oben, links + kante, oben + kante))
    if kante > LOGO_KANTE:
        bild = bild.resize((LOGO_KANTE, LOGO_KANTE), Image.LANCZOS)

    puffer = io.BytesIO()
    bild.save(puffer, format="PNG", optimize=True)
    return puffer.getvalue()
