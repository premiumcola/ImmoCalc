"""Die Abrechnung als PDF — ohne Fremdbibliothek.

Ein PDF ist eine Folge nummerierter Objekte plus eine Querverweistabelle.
Für eine Textseite reichen Katalog, Seitenbaum, Seite, Inhaltsstrom und eine
der 14 Standardschriften; die muss nicht eingebettet werden.

Umlaute laufen über WinAnsiEncoding — das ist cp1252, nicht UTF-8 und auch
nicht latin-1: Gedankenstrich und typografische Anführungszeichen gibt es nur
in cp1252, und die stehen in jedem Zeitraum ("01.01.2025 – 31.12.2025").
"""
from __future__ import annotations

from datetime import date

SEITE_B, SEITE_H = 595.28, 841.89        # A4 in Punkt
RAND_L, RAND_O = 56.0, 56.0
ZEILE = 15.0


def _escape(text: str) -> bytes:
    """Klammern und Rückstriche sind in PDF-Zeichenketten Steuerzeichen."""
    roh = (text or "").replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
    return roh.encode("cp1252", "replace")


class Zeilen:
    """Sammelt Textzeilen mit Schriftgrad und Stil, bevor gesetzt wird."""

    def __init__(self) -> None:
        self.eintraege: list[tuple[str, float, bool, float]] = []

    def zeile(self, text: str = "", groesse: float = 10.5, fett: bool = False,
              abstand: float = ZEILE) -> "Zeilen":
        self.eintraege.append((text, groesse, fett, abstand))
        return self

    def leer(self, hoehe: float = ZEILE) -> "Zeilen":
        return self.zeile("", 10.5, False, hoehe)

    def paar(self, links: str, rechts: str, fett: bool = False) -> "Zeilen":
        """Beschriftung links, Betrag rechtsbündig — als eine Zeile gesetzt."""
        self.eintraege.append((f"\t{links}\t{rechts}", 10.5, fett, ZEILE))
        return self


def _inhaltsstrom(zeilen: Zeilen) -> bytes:
    """Textoperatoren der Seite. Tabulierte Zeilen bekommen einen zweiten
    Textblock, damit der Betrag am rechten Rand steht."""
    teile: list[bytes] = [b"BT"]
    y = SEITE_H - RAND_O
    for text, groesse, fett, abstand in zeilen.eintraege:
        y -= abstand
        if not text:
            continue
        schrift = b"/F2" if fett else b"/F1"
        if text.startswith("\t"):
            _, links, rechts = text.split("\t", 2)
            breite = len(rechts) * groesse * 0.5
            teile.append(b"1 0 0 1 %.2f %.2f Tm %s %.1f Tf (%s) Tj"
                         % (RAND_L, y, schrift, groesse, _escape(links)))
            teile.append(b"1 0 0 1 %.2f %.2f Tm %s %.1f Tf (%s) Tj"
                         % (SEITE_B - RAND_L - breite, y, schrift, groesse,
                            _escape(rechts)))
        else:
            teile.append(b"1 0 0 1 %.2f %.2f Tm %s %.1f Tf (%s) Tj"
                         % (RAND_L, y, schrift, groesse, _escape(text)))
    teile.append(b"ET")
    return b"\n".join(teile)


def _pdf(strom: bytes, titel: str) -> bytes:
    objekte = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %.2f %.2f] "
        b"/Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> /Contents 4 0 R >>"
        % (SEITE_B, SEITE_H),
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(strom), strom),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        b"/Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold "
        b"/Encoding /WinAnsiEncoding >>",
        b"<< /Title (%s) /Producer (ImmoCalc) >>" % _escape(titel),
    ]

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


def _eur(betrag: float | None) -> str:
    text = f"{betrag or 0:,.2f}".replace(",", "#").replace(".", ",").replace("#", ".")
    return text + " EUR"


def abrechnung_pdf(objekt_name: str, zeitraum: str, partei: str,
                   werte: dict, positionen: list[dict] | None = None,
                   absender: str = "") -> bytes:
    """Eine Seite je Partei: Kopf, Einzelposten, Saldo."""
    saldo = werte.get("saldo") or 0
    z = Zeilen()
    z.zeile("Betriebskostenabrechnung", 18, True, 0)
    z.zeile(objekt_name, 12)
    z.zeile(f"Abrechnungszeitraum {zeitraum}", 10.5)
    z.leer(10)
    z.zeile(partei, 12, True)
    z.leer(14)

    if positionen:
        z.zeile("Ihr Anteil an den umlagefähigen Kosten", 11, True)
        z.leer(4)
        for p in positionen:
            z.paar(str(p.get("kostenart", "")), _eur(p.get("betrag")))
        z.leer(6)

    z.paar("Umlagefähige Kosten", _eur(werte.get("kosten")), fett=True)
    z.paar("Geleistete Vorauszahlungen", _eur(werte.get("vorauszahlungen")))
    z.leer(6)
    z.paar("Guthaben zu Ihren Gunsten" if saldo >= 0 else "Nachzahlung",
           _eur(abs(saldo)), fett=True)
    z.leer(20)
    z.zeile("Bei Rückfragen melden Sie sich gerne.", 10.5)
    if absender:
        z.leer(8)
        z.zeile(absender, 10.5)
    z.leer(16)
    z.zeile(f"Erstellt am {date.today():%d.%m.%Y} mit ImmoCalc", 8.5)

    return _pdf(_inhaltsstrom(z), f"Abrechnung {objekt_name} {zeitraum}")


UMLAUTE = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
                         "Ä": "Ae", "Ö": "Oe", "Ü": "Ue"})


def pdf_dateiname(objekt_name: str, zeitraum: str, partei: str) -> str:
    """Anhangsname ohne Sonderzeichen — Mailprogramme verstümmeln sie sonst."""
    def sauber(text: str) -> str:
        umgeschrieben = (text or "").translate(UMLAUTE)
        erlaubt = [c if (c.isascii() and c.isalnum()) or c == "_" else "-"
                   for c in umgeschrieben]
        return "-".join(t for t in "".join(erlaubt).split("-") if t)
    jahr = zeitraum[-4:] if zeitraum[-4:].isdigit() else ""
    return f"Abrechnung_{sauber(objekt_name)}_{jahr}_{sauber(partei)}.pdf"
