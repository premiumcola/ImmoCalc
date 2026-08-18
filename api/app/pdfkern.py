"""N288 — die gemeinsamen Bausteine der handgeschriebenen PDFs.

Ein PDF ist eine Folge nummerierter Objekte plus eine Querverweistabelle. Für
eine Seite reichen Katalog, Seitenbaum, Seite, Inhaltsstrom und zwei der 14
Standardschriften; die müssen nicht eingebettet werden. Genau dieses Gerüst
brauchen die Betriebskostenabrechnung (:mod:`abrechnung_pdf`) und die
Quartalsabrechnung der E-Tankstelle (:mod:`tankabrechnung_pdf`) gleichermaßen —
es stand dort zweimal wortgleich und driftete auseinander: die Tankabrechnung
schätzte die Textbreiten („Zeichenzahl × 0,5"), wodurch ihre rechtsbündigen
Spalten sichtbar ausfransten, während die Nebenkostenabrechnung längst nach der
Helvetica-Breitentabelle rechnete. Hier liegt die exakte Rechnung — für beide.

Umlaute laufen über WinAnsiEncoding — das ist cp1252, nicht UTF-8 und auch
nicht latin-1: Gedankenstrich, Euro-Zeichen und typografische Anführungszeichen
gibt es nur in cp1252, und die stehen in jedem Zeitraum
("01.01.2025 – 31.12.2025").

Was hier **nicht** hingehört: alles Gestalterische. Seitenaufbau, Farben,
Zahlenformate und die `Blatt`-Klassen bleiben in den beiden Abrechnungen — die
zählen ihre Koordinaten bewusst unterschiedlich (von unten bzw. von oben).
"""
from __future__ import annotations

SEITE_B, SEITE_H = 595.28, 841.89        # A4 in Punkt


# ---------------------------------------------------------------- Zeichenbreiten
# Helvetica ist eine Standardschrift: ihre Breiten stehen fest und müssen nicht
# aus einer Datei gelesen werden. Ohne sie ließe sich keine Spalte rechtsbündig
# setzen — die alte Schätzung "Zeichenzahl × 0.5" ließ die Beträge ausfransen.
_HELV = (
    278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278,
    278, 556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584,
    584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556,
    833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278,
    278, 278, 469, 556, 333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222,
    500, 222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500,
    500, 334, 260, 334, 584,
)
_HELV_FETT = (
    278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278,
    278, 556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 333, 333, 584, 584,
    584, 611, 975, 722, 722, 722, 722, 667, 611, 778, 722, 278, 556, 722, 611,
    833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 333,
    278, 333, 584, 556, 333, 556, 611, 556, 611, 556, 333, 611, 611, 278, 278,
    556, 278, 889, 611, 611, 611, 611, 389, 556, 333, 611, 556, 778, 556, 556,
    500, 389, 280, 389, 584,
)
# Alles jenseits von ASCII, das in deutschen Abrechnungen wirklich vorkommt.
_EXTRA = {
    0x80: (556, 556), 0x85: (1000, 1000), 0x91: (222, 238), 0x92: (222, 238),
    0x93: (333, 500), 0x94: (333, 500), 0x96: (556, 556), 0x97: (1000, 1000),
    0xA0: (278, 278), 0xA7: (556, 556), 0xB0: (400, 400), 0xB7: (278, 278),
    0xC4: (667, 722), 0xD6: (778, 778), 0xDC: (722, 722), 0xDF: (611, 611),
    0xE0: (556, 556), 0xE4: (556, 556), 0xE9: (556, 556), 0xF6: (556, 611),
    0xFC: (556, 611),
}


def cp1252(text: str) -> bytes:
    return (text or "").encode("cp1252", "replace")


def breite(text: str, groesse: float, fett: bool = False) -> float:
    """Wie breit der Text gesetzt wird — in Punkt."""
    tabelle = _HELV_FETT if fett else _HELV
    summe = 0
    for b in cp1252(text):
        if 32 <= b <= 126:
            summe += tabelle[b - 32]
        else:
            summe += _EXTRA.get(b, (556, 556))[1 if fett else 0]
    return summe * groesse / 1000.0


# ---------------------------------------------------------------- Zeichenfläche
def escape(text: str) -> bytes:
    """Klammern und Rückstriche sind in PDF-Zeichenketten Steuerzeichen."""
    roh = (text or "").replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
    return cp1252(roh)


def pdf_seiten(stroeme: list[bytes], titel: str) -> bytes:
    """Der fertige Bogen: ein Inhaltsstrom je Seite, beliebig viele Seiten.

    Objektnummerierung: 1 Katalog, 2 Seitenbaum, dann je Seite ein Paar
    (Seite, Inhaltsstrom), zuletzt beide Fonts + Info. Mit genau einer Seite
    ergibt das dieselbe Nummerierung wie die frühere feste Fassung (3=Seite,
    4=Strom, 5/6=Fonts, 7=Info) — `pdf()` bleibt darüber byte-identisch."""
    n = max(1, len(stroeme))
    font1_num = 3 + 2 * n
    font2_num = font1_num + 1
    kids = b" ".join(b"%d 0 R" % (3 + 2 * i) for i in range(n))

    objekte = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, n),
    ]
    for strom in stroeme:
        objekte.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %.2f %.2f] "
            b"/Resources << /Font << /F1 %d 0 R /F2 %d 0 R >> >> /Contents %d 0 R >>"
            % (SEITE_B, SEITE_H, font1_num, font2_num, len(objekte) + 2))
        objekte.append(b"<< /Length %d >>\nstream\n%s\nendstream"
                       % (len(strom), strom))
    objekte.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
                   b"/Encoding /WinAnsiEncoding >>")
    objekte.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold "
                   b"/Encoding /WinAnsiEncoding >>")
    objekte.append(b"<< /Title (%s) /Producer (ImmoCalc) >>" % escape(titel))

    ausgabe = bytearray(b"%PDF-1.4\n")
    # Zweite Zeile mit hohen Bytes: der Hinweis "diese Datei ist binaer"
    ausgabe += bytes([0x25, 0xE2, 0xE3, 0xCF, 0xD3, 0x0A])
    stellen = []
    for nummer, koerper in enumerate(objekte, start=1):
        stellen.append(len(ausgabe))
        ausgabe += b"%d 0 obj\n" % nummer + koerper + b"\nendobj\n"

    xref = len(ausgabe)
    ausgabe += b"xref\n0 %d\n" % (len(objekte) + 1)
    ausgabe += b"0000000000 65535 f \n"
    for stelle in stellen:
        ausgabe += b"%010d 00000 n \n" % stelle
    ausgabe += (b"trailer\n<< /Size %d /Root 1 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
                % (len(objekte) + 1, len(objekte), xref))
    return bytes(ausgabe)


def pdf(strom: bytes, titel: str) -> bytes:
    """Der Einseiter-Fall von `pdf_seiten` — die bisherige Aufrufform bleibt,
    die Tankabrechnung braucht nie mehr als eine Seite."""
    return pdf_seiten([strom], titel)


# ---------------------------------------------------------------- Dateinamen
UMLAUTE = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
                         "Ä": "Ae", "Ö": "Oe", "Ü": "Ue"})


def sauber(text: str) -> str:
    """Ein Namensteil ohne Sonderzeichen — Mailprogramme verstümmeln sie sonst."""
    umgeschrieben = (text or "").translate(UMLAUTE)
    erlaubt = [c if (c.isascii() and c.isalnum()) or c == "_" else "-"
               for c in umgeschrieben]
    return "-".join(t for t in "".join(erlaubt).split("-") if t)
