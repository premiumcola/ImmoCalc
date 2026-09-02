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


def _radiale_maske(kante: int, innen: float, aussen: float):
    """Runde Maske: innen voll deckend, nach aussen weich auf null.

    `innen`/`aussen` sind Anteile des Radius — zwischen beiden liegt die
    weiche Rampe. Ohne diese Rampe hätte der Kreis eine harte, treppige
    Kante; genau die soll der Nutzer nicht sehen."""
    from PIL import Image                            # noqa: PLC0415

    # radial_gradient: schwarz in der Mitte, weiss nach aussen — also der
    # Abstand vom Mittelpunkt als Graustufe.
    abstand = Image.radial_gradient("L").resize((kante, kante), Image.BILINEAR)

    # `radial_gradient` erreicht 255 erst in den ECKEN, nicht an der Kante.
    # Für einen dem Quadrat eingeschriebenen Kreis muss deshalb auf den
    # Kantenabstand normiert werden (1/√2), sonst begänne die weiche Kante
    # ausserhalb des Bildes und der Rand bliebe hart deckend.
    ECKE = 0.7071067811865476

    def rampe(wert: int) -> int:
        x = (wert / 255.0) / ECKE
        if x <= innen:
            return 255
        if x >= aussen:
            return 0
        return int(round(255 * (1 - (x - innen) / (aussen - innen))))

    return abstand.point([rampe(i) for i in range(256)])


def als_logo(rohdaten: bytes) -> bytes:
    """N448 — ein beliebiges Foto zu einem RUNDEN Logo mit weichem Rand.

    Nutzer: „Familienlogo soll ein runder Ausschnitt eines gewählten Fotos
    sein, Blur am Rand, Fokus auf den Mittenbereich."

    Drei Schritte: mittig auf das grösstmögliche Quadrat zuschneiden (der
    übliche Ausschnitt, wenn niemand etwas anderes sagt), dann die scharfe
    Mitte über eine unscharfe Fassung legen — so wird der Rand weich, ohne
    dass die Mitte an Schärfe verliert —, und zuletzt ein runder Ausschnitt
    mit weich auslaufender Kante statt eines harten Kreises."""
    from PIL import Image, ImageChops, ImageFilter   # noqa: PLC0415

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
    if kante != LOGO_KANTE:
        bild = bild.resize((LOGO_KANTE, LOGO_KANTE), Image.LANCZOS)
    kante = LOGO_KANTE

    # 1) Scharfe Mitte, unscharfer Rand.
    unscharf = bild.filter(ImageFilter.GaussianBlur(kante / 36))
    bild = Image.composite(bild, unscharf,
                           _radiale_maske(kante, 0.50, 0.88))

    # 2) Runder Ausschnitt, weich auslaufend.
    weich = ImageChops.multiply(bild.getchannel("A"),
                                _radiale_maske(kante, 0.86, 1.0))
    bild.putalpha(weich)

    puffer = io.BytesIO()
    bild.save(puffer, format="PNG", optimize=True)
    return puffer.getvalue()
