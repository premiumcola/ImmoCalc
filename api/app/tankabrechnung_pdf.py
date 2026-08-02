"""N165 — die Quartalsabrechnung der E-Tankstelle als PDF, ohne Fremdbibliothek.

Vorbild ist :mod:`abrechnung_pdf` (die Betriebskostenabrechnung): ein PDF ist
eine Folge nummerierter Objekte plus Querverweistabelle, für eine Seite reichen
Katalog, Seitenbaum, Seite, Inhaltsstrom und zwei der 14 Standardschriften.

Anders als dort steht hier auch **Vektorgrafik** im Inhaltsstrom — das Diagramm
der geladenen Energie je Monat, gestapelt aus Netz, PV und Akku. In PDF sind
das schlichte Rechtecke (``x y w h re`` + ``f``); Text läuft in ``BT … ET``.

Der Inhalt ist bewusst auf **den einen Nutzer** zugeschnitten: seine Anschrift,
sein Quartal, seine kWh je Monat mit der Aufteilung Netz/PV/Akku, der Satz je
kWh mit Herkunft und der Rechnungsbetrag. Keine Objektfinanzen, keine anderen
Nutzer, keine Mieter-Nebenkosten.

Umlaute laufen wie im Vorbild über WinAnsiEncoding (cp1252) — Gedankenstrich und
typografische Anführungszeichen gibt es nur dort.
"""
from __future__ import annotations

from datetime import date

SEITE_B, SEITE_H = 595.28, 841.89        # A4 in Punkt
RAND_L = 56.0
RAND_R = SEITE_B - 56.0

# Die drei Kostenblöcke in den Farben der Seite: Netz (amber, zugekauft),
# PV (teal, direkt vom Dach), Akku (heller Teal-Ton, aus dem Speicher).
NETZ = (0.569, 0.380, 0.071)             # --amber #916212
PV = (0.059, 0.431, 0.361)               # --teal  #0F6E5C
AKKU = (0.420, 0.651, 0.592)             # heller Teal-Ton #6BA697
EIGEN = PV                               # PV + Akku, wenn nicht trennbar
INK = (0.086, 0.149, 0.173)              # --ink   #16262C
SOFT = (0.42, 0.47, 0.49)               # gedeckter Grauton für Beiwerk
PAPER = (0.910, 0.925, 0.925)            # --paper #E8ECEC
TEAL_L = (0.847, 0.918, 0.898)           # heller Teal-Grund für die Betragskarte
LINIE = (0.839, 0.863, 0.867)            # dünne Trennlinie #D6DCDD


def _escape(text: str) -> bytes:
    """Klammern und Rückstriche sind in PDF-Zeichenketten Steuerzeichen."""
    roh = (text or "").replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
    return roh.encode("cp1252", "replace")


def _eur(betrag: float | None) -> str:
    text = f"{betrag or 0:,.2f}".replace(",", "#").replace(".", ",").replace("#", ".")
    return text + " EUR"


def _zahl(wert: float | None, stellen: int = 2) -> str:
    if wert is None:
        return "-"
    return f"{wert:,.{stellen}f}".replace(",", "#").replace(".", ",").replace("#", ".")


def _kwh(wert: float | None, stellen: int = 2) -> str:
    return "-" if wert is None else _zahl(wert, stellen) + " kWh"


def _proz(wert: float | None) -> str:
    return "-" if wert is None else _zahl(wert, 1) + " %"


class Blatt:
    """Sammelt Text- und Grafikoperatoren einer Seite. Koordinaten werden von
    **oben** gezählt (`y_oben`); umgerechnet wird erst beim Setzen — das liest
    sich näher an der Vorstellung „so weit von der Oberkante"."""

    def __init__(self) -> None:
        self.teile: list[bytes] = []

    def _y(self, oben: float) -> float:
        return SEITE_H - oben

    def text(self, x: float, oben: float, s: str, groesse: float = 10.5,
             fett: bool = False, farbe: tuple = INK) -> None:
        schrift = b"/F2" if fett else b"/F1"
        r, g, b = farbe
        self.teile.append(
            b"BT %.3f %.3f %.3f rg %s %.1f Tf 1 0 0 1 %.2f %.2f Tm (%s) Tj ET"
            % (r, g, b, schrift, groesse, x, self._y(oben), _escape(s)))

    def rechts(self, rechts_x: float, oben: float, s: str, groesse: float = 10.5,
               fett: bool = False, farbe: tuple = INK) -> None:
        """Rechtsbündiger Text — der Betrag endet an `rechts_x`."""
        breite = _textbreite(s, groesse, fett)
        self.text(rechts_x - breite, oben, s, groesse, fett, farbe)

    def rechteck(self, x: float, oben: float, breite: float, hoehe: float,
                 farbe: tuple) -> None:
        """Ein gefülltes Rechteck; `oben` ist die **Ober**kante, `hoehe` läuft
        nach unten."""
        r, g, b = farbe
        self.teile.append(b"%.3f %.3f %.3f rg %.2f %.2f %.2f %.2f re f"
                          % (r, g, b, x, self._y(oben + hoehe), breite, hoehe))

    def linie(self, x1: float, oben: float, x2: float,
              farbe: tuple = LINIE, dicke: float = 0.8) -> None:
        r, g, b = farbe
        y = self._y(oben)
        self.teile.append(b"%.3f %.3f %.3f RG %.2f w %.2f %.2f m %.2f %.2f l S"
                          % (r, g, b, dicke, x1, y, x2, y))

    def strom(self) -> bytes:
        return b"\n".join(self.teile)


def _textbreite(s: str, groesse: float, fett: bool) -> float:
    """Grobe Breitenschätzung für Helvetica — Ziffern und Grossbuchstaben
    breiter, schmale Zeichen schmaler. Reicht für rechtsbündige Beträge."""
    schmal = sum(1 for c in s if c in "il.,:;'|! ")
    breit = sum(1 for c in s if c in "mwMW")
    normal = len(s) - schmal - breit
    faktor = 0.52 if fett else 0.5
    return groesse * (normal * faktor + schmal * 0.28 + breit * 0.82)


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
    ausgabe += (b"trailer\n<< /Size %d /Root 1 0 R /Info %d 0 R >>\n"
                b"startxref\n%d\n%%%%EOF\n"
                % (len(objekte) + 1, len(objekte), xref))
    return bytes(ausgabe)


def _diagramm(blatt: Blatt, oben: float, monate: list[dict],
              dreiteilig: bool) -> float:
    """Das Balkendiagramm: je Monat ein gestapelter Balken. Gibt die Unterkante
    (y_oben) zurück, damit der Text darunter weitergesetzt werden kann."""
    if not monate:
        return oben
    hoehe = 130.0
    padU = 16.0                            # Platz für die Monatsbeschriftung
    nutz = hoehe - padU
    grund = oben + nutz                    # y_oben der Grundlinie
    max_kwh = max([1.0] + [m.get("kwh") or 0.0 for m in monate])
    feld = (RAND_R - RAND_L) / len(monate)
    bw = min(46.0, feld * 0.5)

    # Achse mit dem Höchstwert
    blatt.text(RAND_L, oben - 2, _zahl(max_kwh, 0) + " kWh", 8, False, SOFT)
    blatt.linie(RAND_L, grund, RAND_R, LINIE, 0.8)

    for i, m in enumerate(monate):
        mitte = RAND_L + i * feld + feld / 2
        x = mitte - bw / 2
        kwh = m.get("kwh") or 0.0
        gesamt_h = kwh / max_kwh * nutz
        if not m.get("aufteilung"):
            teile = [(kwh, PAPER)]
        elif dreiteilig and m.get("dreiteilig"):
            teile = [(m.get("extern_kwh"), NETZ), (m.get("pv_kwh"), PV),
                     (m.get("speicher_kwh"), AKKU)]
        else:
            teile = [(m.get("extern_kwh"), NETZ), (m.get("eigen_kwh"), EIGEN)]
        # Von unten nach oben stapeln (Grundlinie ist die Unterkante).
        unten = grund
        for menge, farbe in teile:
            hh = max(0.0, menge or 0.0) / max_kwh * nutz
            if hh > 0:
                blatt.rechteck(x, unten - hh, bw, hh, farbe)
                unten -= hh
        if gesamt_h <= 0:                  # Monat ohne Ladung: nur ein Strich
            blatt.linie(x, grund, x + bw, LINIE, 0.6)
        blatt.text(mitte - _textbreite(m.get("kurz", ""), 8, False) / 2,
                   grund + 12, m.get("kurz", ""), 8, False, SOFT)
    return oben + hoehe + 6


def _legende(blatt: Blatt, oben: float, dreiteilig: bool) -> float:
    posten = ([("Netz", NETZ), ("PV direkt", PV), ("Akku", AKKU)] if dreiteilig
              else [("Netz", NETZ), ("Eigener Strom (PV + Akku)", EIGEN)])
    x = RAND_L
    for name, farbe in posten:
        blatt.rechteck(x, oben - 7, 9, 9, farbe)
        blatt.text(x + 14, oben, name, 9, False, SOFT)
        x += 14 + _textbreite(name, 9, False) + 22
    return oben + 8


def _tabelle(blatt: Blatt, oben: float, monate: list[dict], summe: dict,
             dreiteilig: bool) -> float:
    """Die Monatstabelle: Monat · Geladen · Netz · (PV · Akku | Eigen)."""
    spalten = ([("Netz", "extern_kwh"), ("PV", "pv_kwh"), ("Akku", "speicher_kwh")]
               if dreiteilig else [("Netz", "extern_kwh"), ("Eigen", "eigen_kwh")])
    # Rechte Kanten der Wertspalten, gleichmäßig verteilt.
    n = len(spalten) + 1                    # + Spalte „Geladen"
    rechte = [RAND_R - (n - 1 - k) * ((RAND_R - (RAND_L + 150)) / max(1, n - 1))
              for k in range(n)]
    kopf_y = oben
    blatt.text(RAND_L, kopf_y, "Monat", 8.5, True, SOFT)
    blatt.rechts(rechte[0], kopf_y, "Geladen", 8.5, True, SOFT)
    for k, (name, _) in enumerate(spalten):
        blatt.rechts(rechte[k + 1], kopf_y, name, 8.5, True, SOFT)
    y = kopf_y + 6
    blatt.linie(RAND_L, y, RAND_R, LINIE, 0.8)
    y += 14

    def zeile(bez: str, m: dict, fett: bool) -> None:
        farbe = INK
        blatt.text(RAND_L, y, bez, 10, fett, farbe)
        blatt.rechts(rechte[0], y, _zahl(m.get("kwh")), 10, fett, farbe)
        for k, (_, feld) in enumerate(spalten):
            blatt.rechts(rechte[k + 1], y, _zahl(m.get(feld)), 10, fett,
                         SOFT if not fett else farbe)

    for m in monate:
        zeile(m.get("label", ""), m, False)
        y += 15
    blatt.linie(RAND_L, y - 4, RAND_R, LINIE, 1.0)
    zeile("Summe", {**summe, "label": "Summe"}, True)
    return y + 16


def tankabrechnung_pdf(objekt_name: str, empfaenger: dict, label: str,
                       von: date, bis: date, monate: list[dict], summe: dict,
                       satz: dict, kwh: float, betrag: float,
                       absender: str = "") -> bytes:
    """Die Quartalsabrechnung eines Nutzers als einseitiges PDF.

    `empfaenger` trägt Name und Anschrift, `monate` die Verlaufszeilen des
    Quartals (aus :func:`tankstelle.verlauf`), `satz` den abgeleiteten Preis je
    kWh mit Herkunft, `betrag` den Rechnungsbetrag."""
    dreiteilig = bool(summe.get("dreiteilig"))
    b = Blatt()
    oben = 60.0

    b.text(RAND_L, oben, "Abrechnung E-Tankstelle", 20, True, INK)
    oben += 20
    b.text(RAND_L, oben, f"{objekt_name} · {label}", 11, False, SOFT)
    oben += 14
    b.text(RAND_L, oben,
           f"Ladezeitraum {von:%d.%m.%Y} – {bis:%d.%m.%Y}", 10, False, SOFT)
    oben += 30

    # Empfänger
    b.text(RAND_L, oben, empfaenger.get("name", ""), 12, True, INK)
    oben += 15
    for zeile_txt in (empfaenger.get("strasse", ""),
                      " ".join(x for x in (empfaenger.get("plz", ""),
                                           empfaenger.get("ort", "")) if x)):
        if zeile_txt.strip():
            b.text(RAND_L, oben, zeile_txt, 10, False, INK)
            oben += 14
    oben += 18

    # Diagramm + Legende + Tabelle
    b.text(RAND_L, oben, "Geladene Energie je Monat", 11, True, INK)
    oben += 12
    oben = _diagramm(b, oben, monate, dreiteilig)
    oben = _legende(b, oben, dreiteilig)
    oben += 12
    oben = _tabelle(b, oben, monate, summe, dreiteilig)
    oben += 8

    # Satz je kWh mit Herkunft
    b.text(RAND_L, oben, "Satz je kWh", 11, True, INK)
    oben += 15
    if satz.get("misch") is None:
        b.text(RAND_L, oben, satz.get("grund") or "Der Satz steht noch nicht fest.",
               9.5, False, SOFT)
        oben += 14
    else:
        b.text(RAND_L, oben, _zahl(satz["misch"], 4) + " EUR je kWh", 12, True, PV)
        oben += 15
        regel = (f"Netz {_zahl(satz.get('netz'), 4)} EUR · eigener Strom "
                 f"{_zahl(satz.get('eigen'), 4)} EUR je kWh")
        if satz.get("rabatt") is not None:
            regel += f" ({round(satz['rabatt'] * 100)} % darunter)"
        b.text(RAND_L, oben, regel, 9.5, False, INK)
        oben += 13
        for zeile_txt in _umbrechen(satz.get("herkunft", ""), 96):
            b.text(RAND_L, oben, zeile_txt, 8.5, False, SOFT)
            oben += 11
    oben += 12

    # Rechnungsbetrag — die Karte, um die es geht
    kh = 46.0
    b.rechteck(RAND_L, oben, RAND_R - RAND_L, kh, TEAL_L)
    b.text(RAND_L + 14, oben + 19, "Rechnungsbetrag", 10, True, INK)
    b.text(RAND_L + 14, oben + 34, _kwh(kwh) + " geladen", 9, False, SOFT)
    b.rechts(RAND_R - 14, oben + 30,
             _eur(betrag) if betrag is not None else "-", 20, True, PV)
    oben += kh + 26

    if absender.strip():
        for zeile_txt in absender.splitlines():
            b.text(RAND_L, oben, zeile_txt, 9.5, False, INK)
            oben += 13
        oben += 6
    b.text(RAND_L, oben, f"Erstellt am {date.today():%d.%m.%Y} mit ImmoCalc",
           8.5, False, SOFT)

    return _pdf(b.strom(), f"Abrechnung E-Tankstelle {label}")


def _umbrechen(text: str, breite: int) -> list[str]:
    """Einen langen Herkunftssatz auf mehrere Zeilen brechen (nach Wörtern)."""
    zeilen, akt = [], ""
    for wort in (text or "").split():
        if akt and len(akt) + 1 + len(wort) > breite:
            zeilen.append(akt)
            akt = wort
        else:
            akt = f"{akt} {wort}".strip()
    if akt:
        zeilen.append(akt)
    return zeilen


UMLAUTE = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
                         "Ä": "Ae", "Ö": "Oe", "Ü": "Ue"})


def tank_pdf_dateiname(objekt_name: str, label: str, name: str) -> str:
    """Anhangsname ohne Sonderzeichen — Mailprogramme verstümmeln sie sonst."""
    def sauber(text: str) -> str:
        umgeschrieben = (text or "").translate(UMLAUTE)
        erlaubt = [c if (c.isascii() and c.isalnum()) or c == "_" else "-"
                   for c in umgeschrieben]
        return "-".join(t for t in "".join(erlaubt).split("-") if t)
    return f"E-Tankstelle_{sauber(objekt_name)}_{sauber(label)}_{sauber(name)}.pdf"
