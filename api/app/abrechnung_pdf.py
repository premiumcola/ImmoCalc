"""Die Abrechnung als PDF — ohne Fremdbibliothek.

Das PDF-Gerüst (Objekte, Querverweistabelle, WinAnsiEncoding) und die exakte
Helvetica-Breitenrechnung stehen in :mod:`pdfkern`, gemeinsam mit der
Tankabrechnung. Hier steht nur, wie diese Seiten aussehen.

N419 — kompletter Neubau. Die frühere Fassung (Onepager, ein großer
PAPER-Kasten, kräftige Heatmap) wirkte auf echtem Papier „kindisch": große
farbige Flächen statt eines Briefs. Jetzt ein DIN-Brief:

* **Seite 1** — Briefkopf mit kleinem Vektor-Logo (dasselbe Motiv wie
  `public/icons/icon.svg`, ohne Bild-Einbettung), Absender-/Empfängerzeile,
  Betreff, kurzer Fließtext, eine Verteilerschlüssel-Tabelle je Kostenart
  (Schlüssel · Gesamtkosten · eigener Anteil, nur ein blasser Zeilenakzent
  statt einer kräftigen Heatmap), Summenblock, Ergebniszeile und ein
  Unterschriftsfeld für den Vermieter.
* **Seite 2** (nur wenn `heiznachweis` mitgegeben wird) — der Heizkosten-
  Nachweis: eigene Zählerstände, eigener Verbrauch, eigener Kostenanteil —
  **nie** die Werte einzelner anderer Mietparteien, nur deren Summe
  (`heizkosten.nachweis_fuer_einheit`).

Farbsprache bewusst zurückhaltender als zuvor: die Seite bleibt weiß, Farbe
markiert nur noch Ergebnis (Pos/Neg) und die Größenordnung einer Position
(schwacher Zeilenakzent, keine Fläche mehr)."""
from __future__ import annotations

import logging
import re
from datetime import date

from .pdfkern import SEITE_B, SEITE_H, UMLAUTE  # noqa: F401  (SEITE_B: Layout)
from .pdfkern import breite as _breite
from .pdfkern import escape as _escape
from .pdfkern import pdf_seiten as _pdf_seiten
from .pdfkern import sauber
from .zahlen import fehlt as _fehlt
from .zahlen import geschrieben

log = logging.getLogger("immocalc")

RAND = 48.0
UNTEN_MIN = 42.0                         # darunter darf kein INHALT mehr stehen
# N438 — die Seitenzahl ist die eine bewusste Ausnahme davon: sie gehört wie
# in jedem Brief in den unteren Rand, unterhalb des Textspiegels. 26 pt sind
# gut 9 mm über der Blattkante und liegen damit sicher im Druckbereich.
FUSS_Y = 26.0

# N438 — Untertitel der Marke im Briefkopf, dieselbe Aussage wie auf dem
# Anmeldescreen (`public/anmeldung.html`), nur gekürzt: im Brief steht sie
# in 7,5 pt neben einem 24-pt-Logo und darf die Zeile nicht sprengen.
MARKE_UNTERTITEL = "Nebenkosten · Wertentwicklung · Dokumente"

# Erste Falzmarke eines A4-Briefs nach DIN 5008: 105 mm ab Oberkante.
# 1 mm = 72/25.4 pt; gerechnet ab OBEN, das PDF zählt aber von unten.
FALZ_Y = SEITE_H - 105.0 * 72.0 / 25.4

# Farbsprache der App (CLAUDE.md) als 0..1-Tripel
INK = (0.086, 0.149, 0.173)              # #16262C
TEAL = (0.059, 0.431, 0.361)             # #0F6E5C
AMBER = (0.569, 0.384, 0.071)            # #916212
POS = (0.180, 0.490, 0.310)              # #2E7D4F
NEG = (0.698, 0.259, 0.161)              # #B24229
MATT = (0.404, 0.463, 0.482)             # INK aufgehellt, für Nebentext
WEISS = (1.0, 1.0, 1.0)
LINIE = (0.812, 0.839, 0.847)            # zarte Trennlinie auf weißem Grund

# Wie stark der größte Posten den Zeilenakzent bekommt — ein blasser Hauch,
# keine Fläche: 0.14 ist die Deckung des kräftigsten Postens.
AKZENT_MAX = 0.14
AKZENT_MIN = 0.02


# ---------------------------------------------------------------- Textmaße
def _kuerzen(text: str, max_breite: float, groesse: float,
             fett: bool = False) -> str:
    """Lange Kostenarten (»Mieter Rauchwarnmelder/Prüfung Rauchwarnmelder«)
    werden am Ende gekappt, statt in die Betragsspalte zu laufen."""
    if _breite(text, groesse, fett) <= max_breite:
        return text
    gekappt = text
    while gekappt and _breite(gekappt + "…", groesse, fett) > max_breite:
        gekappt = gekappt[:-1]
    return (gekappt.rstrip() + "…") if gekappt else ""


def _umbruch(text: str, max_breite: float, groesse: float,
             fett: bool = False) -> list[str]:
    """Fließtext (Anschrift, Anschreiben, Hinweise) auf mehrere Zeilen
    verteilen."""
    zeilen: list[str] = []
    aktuell = ""
    for wort in (text or "").split():
        probe = f"{aktuell} {wort}".strip()
        if aktuell and _breite(probe, groesse, fett) > max_breite:
            zeilen.append(aktuell)
            aktuell = wort
        else:
            aktuell = probe
    if aktuell:
        zeilen.append(aktuell)
    return zeilen


# ---------------------------------------------------------------- Zeichenfläche
def _mische(a: tuple[float, float, float], b: tuple[float, float, float],
            anteil: float) -> tuple[float, float, float]:
    t = max(0.0, min(1.0, anteil))
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t,
            a[2] + (b[2] - a[2]) * t)


class Blatt:
    """Sammelt Zeichenbefehle für den Inhaltsstrom EINER Seite.

    Text steht in PDF zwischen BT/ET, Flächen außerhalb. Jeder Textbaustein
    bekommt deshalb seinen eigenen BT/ET-Block — das kostet ein paar Bytes und
    erspart jede Reihenfolgeregel beim Aufbau der Seite."""

    def __init__(self) -> None:
        self.ops: list[bytes] = []

    def flaeche(self, x: float, y: float, breite: float, hoehe: float,
                farbe: tuple[float, float, float], radius: float = 0.0) -> None:
        """Rechteck, auf Wunsch mit runden Ecken (CLAUDE.md: min. 8 px)."""
        self.ops.append(b"%.3f %.3f %.3f rg" % farbe)
        r = max(0.0, min(radius, breite / 2, hoehe / 2))
        if r <= 0.01:
            self.ops.append(b"%.2f %.2f %.2f %.2f re f" % (x, y, breite, hoehe))
            return
        k = r * 0.5523                       # Bezier-Näherung des Viertelkreises
        x2, y2 = x + breite, y + hoehe
        self.ops.append(
            b"%.2f %.2f m %.2f %.2f l %.2f %.2f %.2f %.2f %.2f %.2f c "
            b"%.2f %.2f l %.2f %.2f %.2f %.2f %.2f %.2f c "
            b"%.2f %.2f l %.2f %.2f %.2f %.2f %.2f %.2f c "
            b"%.2f %.2f l %.2f %.2f %.2f %.2f %.2f %.2f c f"
            % (x + r, y, x2 - r, y, x2 - r + k, y, x2, y + r - k, x2, y + r,
               x2, y2 - r, x2, y2 - r + k, x2 - r + k, y2, x2 - r, y2,
               x + r, y2, x + r - k, y2, x, y2 - r + k, x, y2 - r,
               x, y + r, x, y + r - k, x + r - k, y, x + r, y))

    def strich(self, x1: float, x2: float, y: float, dicke: float,
               farbe: tuple[float, float, float] = LINIE) -> None:
        self.ops.append(b"%.3f %.3f %.3f RG %.2f w %.2f %.2f m %.2f %.2f l S"
                        % (farbe + (dicke, x1, y, x2, y)))

    def pfad(self, punkte: list[tuple[float, float]], dicke: float,
             farbe: tuple[float, float, float]) -> None:
        """Offener Streckenzug — für das Logo (Dach, Hauskontur)."""
        teile = [b"%.3f %.3f %.3f RG %.2f w" % (farbe + (dicke,))]
        x0, y0 = punkte[0]
        teile.append(b"%.2f %.2f m" % (x0, y0))
        for x, y in punkte[1:]:
            teile.append(b"%.2f %.2f l" % (x, y))
        teile.append(b"S")
        self.ops.append(b" ".join(teile))

    def kreis(self, cx: float, cy: float, r: float,
             farbe: tuple[float, float, float]) -> None:
        """Gefüllter Kreis (Bezier-Näherung) — für den Logo-Türpunkt."""
        k = r * 0.5523
        self.ops.append(b"%.3f %.3f %.3f rg" % farbe)
        self.ops.append(
            b"%.2f %.2f m "
            b"%.2f %.2f %.2f %.2f %.2f %.2f c "
            b"%.2f %.2f %.2f %.2f %.2f %.2f c "
            b"%.2f %.2f %.2f %.2f %.2f %.2f c "
            b"%.2f %.2f %.2f %.2f %.2f %.2f c f"
            % (cx + r, cy,
               cx + r, cy + k, cx + k, cy + r, cx, cy + r,
               cx - k, cy + r, cx - r, cy + k, cx - r, cy,
               cx - r, cy - k, cx - k, cy - r, cx, cy - r,
               cx + k, cy - r, cx + r, cy - k, cx + r, cy))

    def text(self, x: float, y: float, inhalt: str, groesse: float,
             fett: bool = False, farbe: tuple[float, float, float] = INK) -> None:
        if not inhalt:
            return
        self.ops.append(
            b"%.3f %.3f %.3f rg BT /%s %.2f Tf 1 0 0 1 %.2f %.2f Tm (%s) Tj ET"
            % (farbe + (b"F2" if fett else b"F1", groesse, x, y,
                        _escape(inhalt))))

    def text_rechts(self, rechts: float, y: float, inhalt: str, groesse: float,
                    fett: bool = False,
                    farbe: tuple[float, float, float] = INK) -> None:
        self.text(rechts - _breite(inhalt, groesse, fett), y, inhalt, groesse,
                  fett, farbe)

    def logo(self, x: float, y: float, s: float) -> None:
        """Kleines Hausmotiv wie `public/icons/icon.svg` — Dach + Kontur als
        Linie, Tür als Punkt. Reine Vektor-Ops statt Bild-Einbettung."""
        self.pfad([(x, y + s * 0.42), (x + s * 0.5, y + s * 0.94),
                   (x + s, y + s * 0.42)], s * 0.09, INK)
        self.pfad([(x + s * 0.16, y + s * 0.36), (x + s * 0.16, y),
                   (x + s * 0.84, y), (x + s * 0.84, y + s * 0.36)],
                  s * 0.09, INK)
        self.kreis(x + s * 0.5, y + s * 0.2, s * 0.085, TEAL)

    def strom(self) -> bytes:
        return b"\n".join(self.ops)


# ---------------------------------------------------------------- Zahlen & Text
def _zahl(betrag: float | None, vorzeichen: bool = False) -> str:
    """Deutsche Schreibweise. Die Währung steht einmal im Kopf der Spalte,
    nicht an jeder der fünfzehn Zeilen (roter Faden: jede Information einmal)."""
    return geschrieben(betrag, vorzeichen=vorzeichen)


_DATUM = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")


def _grenzen(zeitraum: str) -> tuple[date, date] | None:
    """Start und Ende aus dem Zeitraumtext — er kommt immer als
    "01.01.2023 – 31.12.2023" aus `versand.py`."""
    treffer = _DATUM.findall(zeitraum or "")
    if len(treffer) < 2:
        return None
    try:
        a = date(int(treffer[0][2]), int(treffer[0][1]), int(treffer[0][0]))
        b = date(int(treffer[-1][2]), int(treffer[-1][1]), int(treffer[-1][0]))
    except ValueError:
        return None
    return (a, b) if b >= a else None


def _monate_aus(zeitraum: str) -> int | None:
    """Wie viele Monate der Zeitraum umfasst — abgeleitet statt abgefragt
    (roter Faden: was sich ableiten lässt, wird nicht eingetippt)."""
    grenzen = _grenzen(zeitraum)
    if not grenzen:
        return None
    tage = (grenzen[1] - grenzen[0]).days + 1
    return max(1, round(tage / 30.44))


def _jahr_aus(zeitraum: str) -> str:
    grenzen = _grenzen(zeitraum)
    if grenzen:
        return f"{grenzen[1].year}"
    jahre = re.findall(r"(?<!\d)(\d{4})(?!\d)", zeitraum or "")
    return jahre[-1] if jahre else ""


def _posten(positionen: list[dict] | None) -> list[dict]:
    """Die übergebenen Positionen vereinheitlichen.

    Die Engine nennt den Betrag `kosten` (engine.py) und den §-35a-Status
    `s35`; `versand._einzelposten` reicht ihn als `betrag` weiter, die
    KI-Auslese als `s35a`. Hier werden alle drei Schreibweisen akzeptiert,
    statt an einer Stelle eine zweite Wahrheit zu erfinden. `schluessel`/
    `gesamtkosten` sind seit N419 optional dabei (Verteilerschlüssel-Tabelle)."""
    fertig: list[dict] = []
    for p in positionen or []:
        name = str(p.get("kostenart") or p.get("name") or "").strip()
        roh = p.get("betrag")
        if roh is None:
            roh = p.get("kosten")
        try:
            betrag = float(roh or 0)
        except (TypeError, ValueError):
            betrag = 0.0
        if name or betrag:
            fertig.append({
                "name": name, "betrag": betrag,
                "s35": bool(p.get("s35") or p.get("s35a")),
                "schluessel": (p.get("schluessel") or "").strip(),
                "gesamtkosten": p.get("gesamtkosten"),
            })
    return fertig


# ---------------------------------------------------------------- Tabellen
def _tabellenkopf(blatt: Blatt, links: float, y: float,
                  spalten: list[tuple[str, float, str]]) -> None:
    """`spalten`: [(titel, kante_relativ_zu_links, ausrichtung)] — bei "l" die
    linke Kante der Spalte, bei "r" ihre rechte Kante (Text endet dort)."""
    for titel, kante, ausrichtung in spalten:
        if ausrichtung == "r":
            blatt.text_rechts(links + kante - 6, y, titel, 8.5, True, MATT)
        else:
            blatt.text(links + kante + (6 if kante else 0), y, titel, 8.5,
                      True, MATT)
    blatt.strich(links, links + spalten[-1][1], y - 5, 0.8, LINIE)


# ---------------------------------------------------------------- Seite 1: Brief
def _seite_eins(objekt_name: str, zeitraum: str, partei: str, werte: dict,
                posten: list[dict], absender: str, adresse: str,
                kasten_titel: str, jahr: str, monate: int | None,
                monatsbetrag: float | None, anlage_hinweis: str,
                abschlag_hinweis: str, erstellt_am: date,
                hinweis_seite_zwei: bool) -> Blatt:
    blatt = Blatt()
    links, rechts = RAND, SEITE_B - RAND
    breite = rechts - links
    empfaenger = (partei or "").strip()

    # ---- Briefkopf: nur die Marke, kein Datum
    # N438 — Nutzer: „Logo größer mit Untertitel wie die App", „kein Datum
    # oben, Datum nur unten". Das Datum steht weiterhin über der
    # Unterschriftslinie; oben rechts wäre es dieselbe Angabe zweimal
    # (roter Faden: jede Information genau einmal).
    y = SEITE_H - RAND
    blatt.logo(links, y - 24, 24)
    blatt.text(links + 32, y - 10, "ImmoCalc", 14, True, INK)
    blatt.text(links + 32, y - 21, MARKE_UNTERTITEL, 7.5, False, MATT)
    y -= 34
    blatt.strich(links, rechts, y, 0.8, LINIE)
    y -= 26

    # ---- Empfänger
    # N438 — die Absenderzeile („Vermieter · Objekt") ist entfallen: der
    # Nutzer will seine Anschrift nicht im Brief stehen haben. Der Name
    # bleibt allein an der Unterschrift.
    if empfaenger:
        blatt.text(links, y, empfaenger, 11.5, True, INK)
        y -= 15
    if kasten_titel and kasten_titel != empfaenger:
        blatt.text(links, y, kasten_titel, 10, False, MATT)
        y -= 13
    for zeile in _umbruch(adresse, breite * 0.6, 10)[:2]:
        blatt.text(links, y, zeile, 10, False, MATT)
        y -= 13

    # ---- Falz: alles Weitere beginnt UNTER der ersten Falzmarke
    # N438 — Nutzer: „mehr Abstand von Anschrift zu Tabelle, damit man den
    # Briefkopf in einen Brief falten könnte". Nach DIN 5008 wird ein
    # A4-Brief bei 105 mm ab Oberkante das erste Mal gefaltet; liegt dort
    # Text, knickt es mitten hinein. Die Anschrift bleibt oben im Fenster-
    # bereich, Betreff und Tabelle rücken unter den Falz, dazwischen steht
    # bewusst Weißraum. Die kleine Marke am linken Rand ist die übliche
    # Falzhilfe und zeigt, wo geknickt wird.
    #
    # Der Falz kostet gut 130 pt Höhe. Bei sehr vielen Kostenarten (ab etwa
    # 30) reicht das Blatt dann nicht mehr, und die Tabelle liefe ins
    # Unterschriftsfeld. Deshalb ist der Abstand nachgiebig: passt der Brief
    # unter dem Falz nicht mehr mit lesbarer Zeilenhöhe, rückt er wieder
    # hoch. Ein lesbarer Brief schlägt eine bequeme Falzhilfe.
    blatt.strich(links - 12, links - 4, FALZ_Y, 0.6, LINIE)
    kosten = float(werte.get("kosten") or 0)
    vz = float(werte.get("vorauszahlungen") or 0)
    s35_summe = float(werte.get("s35") or 0)
    if posten:
        rest_unter_falz = ((FALZ_Y - 22) - _KOPFHOEHE_UNTER_BETREFF
                          - (RAND + UNTEN_MIN)
                          - _platz_nach_tabelle(kosten, monate, s35_summe, vz,
                                                monatsbetrag, posten,
                                                anlage_hinweis, abschlag_hinweis))
        falz_moeglich = rest_unter_falz / len(posten) >= _ZEILE_LESBAR
    else:
        falz_moeglich = True
    y = min(y - 20, FALZ_Y - 22) if falz_moeglich else y - 20

    # ---- Betreff + Anrede
    titel = f"Betriebskostenabrechnung {jahr}".strip()
    blatt.text(links, y, titel, 13.5, True, INK)
    y -= 16
    blatt.text(links, y, f"Zeitraum {zeitraum}", 9.5, False, MATT)
    y -= 26
    blatt.text(links, y, f"Guten Tag {empfaenger}," if empfaenger
               else "Sehr geehrte Damen und Herren,", 10, False, INK)
    y -= 18

    saldo = float(werte.get("saldo") or 0)
    richtung = "ein Guthaben" if saldo >= 0 else "eine Nachzahlung"
    satz2 = (" Die Berechnungsgrundlage der Heizkosten finden Sie auf der "
             "folgenden Seite." if hinweis_seite_zwei else "")
    text = (f"anbei erhalten Sie die Betriebskostenabrechnung für den oben "
            f"genannten Zeitraum. Aus den angefallenen Kosten und Ihren "
            f"Vorauszahlungen ergibt sich {richtung} von "
            f"{_zahl(abs(saldo))} €. Die einzelnen Kostenarten mit ihrem "
            f"Verteilerschlüssel finden Sie in der Tabelle unten.{satz2}")
    for zeile in _umbruch(text, breite, 10):
        blatt.text(links, y, zeile, 10, False, INK)
        y -= 13.5
    y -= 14

    # ---- Verteilerschlüssel-Tabelle (kosten/vz/s35_summe stehen oben, sie
    # entscheiden schon über den Falz-Abstand)
    if posten:
        s_breite, g_breite, a_breite = 78.0, 76.0, 76.0
        name_breite = breite - s_breite - g_breite - a_breite
        spalten = [
            ("Kostenart", 0, "l"),
            ("Schlüssel", name_breite, "l"),
            ("Gesamtkosten", name_breite + s_breite + g_breite, "r"),
            ("Ihr Anteil", breite, "r"),
        ]
        _tabellenkopf(blatt, links, y, spalten)
        y -= 8

        # Zeilenhöhe: großzügig, aber gedeckelt, damit die Tabelle auch bei
        # vielen Kostenarten nicht ins Unterschriftsfeld läuft.
        fest_danach = _platz_nach_tabelle(kosten, monate, s35_summe, vz,
                                          monatsbetrag, posten, anlage_hinweis,
                                          abschlag_hinweis)
        frei = y - (RAND + UNTEN_MIN) - fest_danach
        zeile_h = min(15.0, max(8.0, frei / len(posten)))
        groesse = min(9.5, max(6.5, zeile_h * 0.62))

        # N438 — Nutzer: „Tabelle ist so komplett gefärbt und unschön, vielleicht
        # nur die ‚Ihr Anteil'-Spalte färben". Der Größenvergleich bleibt damit
        # erhalten (die Spalte liest sich jetzt wie ein kleines Balkenbild),
        # aber das Blatt wirkt wieder wie ein Brief und nicht wie eine
        # eingefärbte Tabelle. Gefärbt wird nur noch die letzte Spalte.
        anteil_links = links + name_breite + s_breite + g_breite
        anteil_breite = rechts - anteil_links
        groesster = max((abs(p["betrag"]) for p in posten), default=0.0)
        for p in posten:
            anteil = (abs(p["betrag"]) / groesster) if groesster else 0.0
            akzent = _mische(WEISS, TEAL, AKZENT_MIN + (AKZENT_MAX - AKZENT_MIN) * anteil)
            blatt.flaeche(anteil_links, y - zeile_h + 2, anteil_breite,
                          zeile_h - 2, akzent, 2)
            basis = y - zeile_h + (zeile_h - groesse) / 2 + 1.5
            blatt.text(links + 6, basis,
                      _kuerzen(p["name"] + (" *" if p["s35"] else ""),
                               name_breite - 10, groesse), groesse, False, INK)
            blatt.text(links + name_breite + 6, basis,
                      _kuerzen(p["schluessel"] or "–", s_breite - 8, groesse),
                      groesse, False, MATT)
            if p["gesamtkosten"] is not None:
                blatt.text_rechts(links + name_breite + s_breite + g_breite - 6,
                                  basis, _zahl(p["gesamtkosten"]), groesse,
                                  False, MATT)
            blatt.text_rechts(rechts - 6, basis, _zahl(p["betrag"]), groesse,
                              True, INK)
            y -= zeile_h
        y -= 6
        blatt.strich(links, rechts, y, 0.8, LINIE)
        y -= 20
    else:
        blatt.text(links, y, "Für diesen Zeitraum liegen keine Kostenpositionen vor.",
                   9.5, False, MATT)
        y -= 30

    # ---- Summen
    for beschriftung, wert, fett, farbe in _summenzeilen(
            kosten, monate, s35_summe, vz, monatsbetrag):
        blatt.text(links, y, beschriftung, 10, fett, farbe)
        blatt.text_rechts(rechts, y, wert, 10, fett, farbe)
        y -= 15.5

    # ---- Ergebnis: Doppelstrich, farbiger Text — keine Fläche mehr
    y -= 6
    blatt.strich(links, rechts, y + 5, 0.8, INK)
    blatt.strich(links, rechts, y + 2.5, 0.8, INK)
    y -= 12
    ergebnis_farbe = POS if saldo >= 0 else NEG
    blatt.text(links, y, "Nachzahlung (-) / Guthaben (+)", 11, True, INK)
    blatt.text_rechts(rechts, y, _zahl(saldo, vorzeichen=True), 13.5, True,
                      ergebnis_farbe)
    y -= 26

    # ---- Fußnoten
    if any(p["s35"] for p in posten):
        blatt.text(links, y, "*  haushaltsnahe Dienstleistungen nach § 35a EStG",
                   8.5, False, MATT)
        y -= 13
    if anlage_hinweis:
        for zeile in _umbruch(anlage_hinweis, breite, 9):
            blatt.text(links, y, zeile, 9, False, INK)
            y -= 13.5
    if abschlag_hinweis:
        blatt.text(links, y, abschlag_hinweis, 9, False, AMBER)
        y -= 13.5

    # ---- Unterschriftsfeld
    sig_y = UNTEN_MIN + 34
    blatt.text(links, sig_y + 16, f"{erstellt_am:%d.%m.%Y}", 9.5, False, MATT)
    blatt.strich(links, links + 190, sig_y, 0.8, INK)
    unterschrift_titel = " · ".join(x for x in [
        "Unterschrift Vermieter", absender.strip()] if x)
    blatt.text(links, sig_y - 12, unterschrift_titel, 8, False, MATT)

    return blatt


# Ab welcher Zeilenhöhe eine Tabellenzeile noch als lesbar gilt — darunter
# wird lieber der Falz-Abstand geopfert als die Tabelle zusammengequetscht.
_ZEILE_LESBAR = 11.0
# Was zwischen Falzmarke und erster Tabellenzeile steht (Betreff, Zeitraum,
# Anrede, vier Zeilen Fließtext). Bewusst großzügig geschätzt: die Zahl
# entscheidet nur, OB gefalzt wird, nicht wo etwas gezeichnet wird.
_KOPFHOEHE_UNTER_BETREFF = 130.0


def _platz_nach_tabelle(kosten: float, monate: int | None, s35_summe: float,
                        vz: float, monatsbetrag: float | None,
                        posten: list[dict], anlage_hinweis: str,
                        abschlag_hinweis: str) -> float:
    """Höhe alles dessen, was UNTER der Tabelle noch kommt: Summenblock,
    Ergebniszeile, Fußnoten und der Abstand zum Unterschriftsfeld.

    Eine Quelle für zwei Verwender — die Zeilenhöhe der Tabelle und die
    Entscheidung über den Falz-Abstand (N438). Zwei Kopien derselben Formel
    wären früher oder später auseinandergelaufen."""
    return (18 + len(_summenzeilen(kosten, monate, s35_summe, vz,
                                   monatsbetrag)) * 15.5
            + 34 + _fussnoten_hoehe(posten, anlage_hinweis, abschlag_hinweis)
            + 58)


def _seitenzahl(blatt: Blatt, nummer: int, gesamt: int) -> None:
    """N438 — „Seitenanzahl auch immer unten rechts". Auf jeder Seite, mit
    Gesamtzahl: bei einem Brief, der aus dem Umschlag kommt, soll man sehen,
    ob ein Blatt fehlt. Wird erst gezeichnet, wenn feststeht, wie viele
    Seiten es insgesamt gibt — deshalb nicht in `_seite_eins`/`_seite_zwei`,
    sondern am Ende in `abrechnung_pdf`."""
    blatt.text_rechts(SEITE_B - RAND, FUSS_Y,
                      f"Seite {nummer} von {gesamt}", 8, False, MATT)


def _summenzeilen(kosten: float, monate: int | None, s35_summe: float,
                  vz: float, monatsbetrag: float | None
                  ) -> list[tuple[str, str, bool, tuple[float, float, float]]]:
    zeilen: list[tuple[str, str, bool, tuple[float, float, float]]] = []
    zeilen.append(("Ihre angefallenen Nebenkosten", _zahl(kosten), True, INK))
    if monate:
        zeilen.append(("entspricht monatlich", _zahl(kosten / monate), False, MATT))
    if s35_summe:
        zeilen.append(("davon haushaltsnah nach § 35a EStG", _zahl(s35_summe),
                       False, AMBER))
    if monate:
        pro_monat = monatsbetrag if monatsbetrag is not None else vz / monate
        zeilen.append((f"Vorauszahlungen {monate} Monate à {_zahl(pro_monat)} €/mtl",
                       _zahl(vz), False, INK))
    else:
        zeilen.append(("Geleistete Vorauszahlungen", _zahl(vz), False, INK))
    return zeilen


def _fussnoten_hoehe(posten: list[dict], anlage_hinweis: str,
                     abschlag_hinweis: str) -> float:
    hoehe = 0.0
    if any(p["s35"] for p in posten):
        hoehe += 13
    if anlage_hinweis:
        hoehe += len(_umbruch(anlage_hinweis, SEITE_B - 2 * RAND, 9)) * 13.5
    if abschlag_hinweis:
        hoehe += 13.5
    return hoehe


# ---------------------------------------------------------------- Seite 2: Heizkosten
def _seite_zwei(kasten_titel: str, zeitraum: str, jahr: str,
                nachweis: dict | None, strom: list[dict] | None) -> Blatt:
    blatt = Blatt()
    links, rechts = RAND, SEITE_B - RAND
    breite = rechts - links
    y = SEITE_H - RAND

    # N438 — die Seitenzahl steht jetzt unten rechts auf JEDER Seite
    # (`_seitenzahl`), oben bleibt nur noch die Einordnung des Blattes.
    blatt.text(links, y, kasten_titel or "Nachweis", 9, False, MATT)
    blatt.text_rechts(rechts, y, jahr, 9, False, MATT)
    y -= 20
    blatt.strich(links, rechts, y, 0.8, LINIE)
    y -= 30

    if nachweis:
        y = _heizkosten_nachweis(blatt, links, rechts, breite, y, zeitraum, nachweis)
    if strom:
        if nachweis:
            y -= 16
        y = _strom_zusammensetzung(blatt, links, rechts, breite, y, zeitraum, strom)

    return blatt


def _rechenbeispiel(blatt: Blatt, links: float, rechts: float, breite: float,
                    y: float, zeilen: list[dict], preis: float | None) -> float:
    """N429 — der Weg an EINEM echten Heizkörper vorgerechnet.

    „Wie aus den Zählwerten der Liter-Öl-Wert für jeden einzelnen Heizkörper
    wird, geht hier noch nicht hervor" — genau diese Kette steht jetzt Schritt
    für Schritt da, mit den Zahlen des größten eigenen Heizkörpers (der ist am
    ehesten wiederzuerkennen). Fehlt eine Zutat, entfällt der Block still —
    die Tabelle darunter trägt die Zahlen ohnehin."""
    kandidaten = [z for z in zeilen
                  if z.get("bewertungsfaktor") and z.get("eur") is not None
                  and z.get("anteil_pct") and z.get("verbrauch")]
    if not kandidaten or not preis:
        return y
    z = max(kandidaten, key=lambda k: k["eur"])
    schritte = [
        (f"{_zahl(z['verbrauch'], )} Punkte abgelesen".replace(",00", ""),
         f"am Zähler {z['name']}"),
        (f"× {_zahl(z['bewertungsfaktor'])} = {_zahl(z['bewertet'])} bewertete Einheiten",
         "Bewertungsfaktor dieses Heizkörpers"),
        (f"= {geschrieben(z['anteil_pct'], 1)} % Ihrer Heizwärme "
         f"= {_zahl(z['eur'])} €", "Anteil an Ihren Heizkosten"),
        (f"÷ {geschrieben(preis, 2)} €/Liter = {geschrieben(z['liter'], 1)} Liter Öl",
         "zum Ø-Einkaufspreis dieses Zeitraums"),
    ]
    hoehe = 16 + len(schritte) * 22 + 8
    blatt.flaeche(links, y - hoehe + 8, breite, hoehe, _mische(WEISS, TEAL, 0.05), 10)
    y -= 6
    blatt.text(links + 12, y, "Beispiel: so entsteht ein Heizkörper-Wert",
               9.5, True, INK)
    y -= 18
    for satz, erklaerung in schritte:
        blatt.text(links + 12, y, satz, 9.5, False, INK)
        blatt.text_rechts(rechts - 12, y, erklaerung, 8, False, MATT)
        y -= 22
    return y - 6


def _heizkosten_nachweis(blatt: Blatt, links: float, rechts: float,
                         breite: float, y: float, zeitraum: str,
                         nachweis: dict) -> float:
    blatt.text(links, y, "Nachweis Heizung & Warmwasser", 15, True, INK)
    y -= 18
    blatt.text(links, y, f"Zeitraum {zeitraum} · nur Ihre eigenen Zähler und "
               "die Gesamtsumme aller Einheiten", 9.5, False, MATT)
    y -= 22

    # N423/N429 — der Rechenweg: erst allgemein in zwei Sätzen, dann an
    # EINEM echten Heizkörper vorgerechnet. Der Nutzer sah zwar die
    # bewerteten Einheiten, aber nicht, wie daraus Euro und Liter Öl werden.
    rechenweg = ("So wird gerechnet: Ein Wärmemengenzähler misst die "
                "verbrauchte Wärme direkt in kWh. Ein Heizkörper-Verteiler "
                "zeigt nur einen Rohwert — erst der Ablesewert mal seinem "
                "Bewertungsfaktor macht ihn mit anderen Heizkörpern "
                "vergleichbar. Ihr Anteil an der Summe aller Zähler im Haus "
                "bestimmt Ihren Anteil an den Heizölkosten; geteilt durch den "
                "Einkaufspreis ergibt das die Liter Öl.")
    for zeile in _umbruch(rechenweg, breite, 9):
        blatt.text(links, y, zeile, 9, False, MATT)
        y -= 12.5
    y -= 6

    zeilen = nachweis.get("zaehler") or []
    preis = nachweis.get("oel_preis_je_liter")
    y = _rechenbeispiel(blatt, links, rechts, breite, y, zeilen, preis)

    # ---- Zählertabelle
    if zeilen:
        # N429 — Anfangs-/Endstand haben ihre eigenen Spalten verloren: bei
        # Heizkörper-Verteilern sind sie prinzipbedingt leer (gezählt werden
        # Punkte, kein fortlaufender Stand), und bei zehn Heizkörpern klaffte
        # dadurch mitten in der Tabelle eine leere Fläche. Wo es echte Stände
        # gibt (Wärmemengen-/Warmwasserzähler), stehen sie als Unterzeile am
        # Namen — dort, wo auch die Punkte-mal-Faktor-Rechnung steht.
        breiten = [breite * a for a in (0.40, 0.15, 0.12, 0.15, 0.18)]
        kanten = [sum(breiten[:i + 1]) for i in range(len(breiten))]
        if preis:
            # Der Preis, mit dem die „Liter Öl"-Spalte gerechnet ist — direkt
            # über der Tabelle, damit die Spalte nicht aus dem Nichts kommt.
            y -= 4
            blatt.text_rechts(rechts, y + 15,
                              f"Ø-Einkaufspreis {geschrieben(preis, 2)} €/Liter",
                              8, False, MATT)
        _tabellenkopf(blatt, links, y, [
            ("Zähler", 0, "l"), ("Bewertet", kanten[1], "r"),
            ("Anteil", kanten[2], "r"), ("Liter Öl", kanten[3], "r"),
            ("Kosten", kanten[4], "r")])
        y -= 22

        for z in zeilen:
            ist_ww = z.get("kostenart") == "Warmwasser"
            ist_wmz = z.get("messeinheit") == "kWh"
            einheit = "m³" if ist_ww else ("kWh" if ist_wmz else "Punkte")
            nachkomma = 3 if ist_ww else (1 if ist_wmz else 0)
            name = z["name"]
            if z.get("nummer"):
                name = f"{name}  ·  Nr. {z['nummer']}"
            blatt.text(links + 6, y, _kuerzen(name, kanten[1] - 14, 9.5),
                      9.5, False, INK)
            # Die Herleitung des bewerteten Werts als ruhige Unterzeile: bei
            # einem Heizkörper „Punkte × Faktor", bei einem echten Zähler der
            # Sprung vom Anfangs- auf den Endstand.
            faktor = z.get("bewertungsfaktor")
            if not ist_ww and not ist_wmz and faktor and z.get("verbrauch") is not None:
                unter = (f"{geschrieben(z['verbrauch'], nachkomma)} {einheit}"
                        f" × {_zahl(faktor)} (Bewertungsfaktor)")
            elif z.get("start") is not None and z.get("ende") is not None:
                # Kein „→": WinAnsi/cp1252 kennt den Pfeil nicht, er käme als
                # „?" heraus (dieselbe Falle, die `test_gedankenstrich…`
                # bewacht). Ausgeschrieben ist es ohnehin verständlicher.
                unter = (f"Anfangsstand {geschrieben(z['start'], nachkomma)} · "
                        f"Endstand {geschrieben(z['ende'], nachkomma)} {einheit}")
            else:
                unter = ""
            if unter:
                blatt.text(links + 6, y - 11, unter, 8, False, MATT)

            bewertet = z.get("bewertet")
            blatt.text_rechts(links + kanten[1] - 6, y,
                              _fehlt(bewertet, nachkomma), 9, True, INK)
            blatt.text_rechts(links + kanten[2] - 6, y,
                              geschrieben(z["anteil_pct"], 1, einheit="%")
                              if z.get("anteil_pct") is not None else "–",
                              9, False, MATT)
            blatt.text_rechts(links + kanten[3] - 6, y,
                              geschrieben(z["liter"], 1)
                              if z.get("liter") is not None else "–",
                              9, False, MATT)
            blatt.text_rechts(rechts - 6, y,
                              f"{_zahl(z['eur'])} €" if z.get("eur") is not None
                              else "–", 9, True, INK)
            y -= 22 + (11 if unter else 0)
        y -= 8
        blatt.strich(links, rechts, y, 0.8, LINIE)
        y -= 24

    # ---- Verbrauchsvergleich (nur Summen, nie einzelne andere Nutzer)
    eigen_kwh = nachweis.get("eigener_verbrauch_kwh")
    gesamt_kwh = nachweis.get("gesamt_verbrauch_kwh")
    if eigen_kwh and gesamt_kwh:
        pct = round(100 * eigen_kwh / gesamt_kwh, 1)
        blatt.text(links, y, f"Wärmemenge: {_zahl(eigen_kwh)} kWh von "
                   f"insgesamt {_zahl(gesamt_kwh)} kWh im gesamten Haus",
                   10, False, INK)
        blatt.text_rechts(rechts, y, geschrieben(pct, 1, einheit="%"),
                          12, True, TEAL)
        y -= 18

    eigen_ww = nachweis.get("eigener_verbrauch_ww_m3")
    gesamt_ww = nachweis.get("gesamt_verbrauch_ww_m3")
    if eigen_ww and gesamt_ww:
        blatt.text(links, y, f"Warmwasser: {geschrieben(eigen_ww, 2)} m³ von "
                   f"insgesamt {geschrieben(gesamt_ww, 2)} m³ im gesamten Haus",
                   10, False, INK)
        y -= 22
    y -= 6

    # ---- Kostenanteil
    pct_kosten = nachweis.get("kostenanteil_pct")
    if pct_kosten is not None:
        blatt.strich(links, rechts, y + 8, 0.8, LINIE)
        blatt.text(links, y - 8, "Ihr Anteil an den Heiz-/Warmwasserkosten "
                   "des Hauses", 10.5, True, INK)
        blatt.text_rechts(rechts, y - 8, geschrieben(pct_kosten, 1, einheit="%"),
                          14, True, TEAL)
        y -= 24
        for kostenart, betrag in (nachweis.get("kosten_je_kostenart") or {}).items():
            blatt.text(links + 10, y, kostenart, 9.5, False, MATT)
            blatt.text_rechts(rechts, y, f"{_zahl(betrag)} €", 9.5, False, MATT)
            y -= 14

    # N423 — die Liter-Öl-Übersetzung: aus der echten FIFO-Bewertung des
    # Objekts (`heizkosten.nachweis_fuer_einheit`), kein angenommener Wert.
    oel_liter = nachweis.get("oel_liter_eigen")
    if oel_liter:
        y -= 6
        satz = f"Das entspricht rechnerisch rund {geschrieben(oel_liter, 1)} Litern Heizöl"
        preis = nachweis.get("oel_preis_je_liter")
        if preis:
            satz += f" (Ø-Einkaufspreis {geschrieben(preis, 2)} €/Liter in diesem Zeitraum)"
        satz += "."
        for zeile in _umbruch(satz, breite, 9.5):
            blatt.text(links, y, zeile, 9.5, False, INK)
            y -= 13

    y -= 14
    for zeile in _umbruch("Aus Datenschutzgründen werden nur die Zählerstände "
                          "Ihrer eigenen Einheit sowie die Gesamtsumme aller "
                          "Einheiten gemeinsam ausgewiesen — keine Einzelwerte "
                          "anderer Mietparteien.", breite, 8):
        blatt.text(links, y, zeile, 8, False, MATT)
        y -= 12
    return y


_HERKUNFT_TITEL = {"extern": "Netzbezug", "eigen": "Eigene PV-Anlage"}


def _strom_zusammensetzung(blatt: Blatt, links: float, rechts: float,
                           breite: float, y: float, zeitraum: str,
                           strom: list[dict]) -> float:
    """N423 — woher der Strom des ganzen Hauses kam, nicht der eigene Anteil:
    dieselben Zahlen für jede Partei, deshalb kein Datenschutz-Thema wie bei
    den Heizkosten-Zählern."""
    blatt.text(links, y, "Zusammensetzung des Stroms", 15, True, INK)
    y -= 18
    blatt.text(links, y, f"Zeitraum {zeitraum} · für das gesamte Haus, nicht "
               "nur Ihre Einheit", 9.5, False, MATT)
    y -= 26

    gesamt_kwh = sum(s.get("menge") or 0 for s in strom)
    gesamt_eur = sum(s.get("betrag") or 0 for s in strom)
    for s in strom:
        menge = s.get("menge") or 0
        titel = _HERKUNFT_TITEL.get(s.get("herkunft"), s.get("herkunft") or "Unbekannt")
        pct = round(100 * menge / gesamt_kwh, 1) if gesamt_kwh else None
        blatt.text(links, y, titel, 10.5, True, INK)
        if pct is not None:
            blatt.text_rechts(rechts, y, geschrieben(pct, 1, einheit="%"),
                              12, True, TEAL)
        y -= 15
        einheit = s.get("menge_einheit") or "kWh"
        zeile = f"{geschrieben(menge, 1, einheit=einheit)}"
        if s.get("arbeitspreis"):
            zeile += f" à {geschrieben(s['arbeitspreis'], 2)} ct/{einheit}"
        if s.get("betrag"):
            zeile += f" · {_zahl(s['betrag'])} €"
        blatt.text(links + 10, y, zeile, 9.5, False, MATT)
        y -= 20
    if gesamt_eur:
        y -= 4
        blatt.strich(links, rechts, y + 8, 0.8, LINIE)
        blatt.text(links, y - 8, "Gesamtkosten Strom", 10, True, INK)
        blatt.text_rechts(rechts, y - 8, f"{_zahl(gesamt_eur)} €", 10, True, INK)
        y -= 24
    return y


def abrechnung_pdf(objekt_name: str, zeitraum: str, partei: str,
                   werte: dict, positionen: list[dict] | None = None,
                   absender: str = "", *,
                   mieter: str = "", anschrift: str = "", einheit: str = "",
                   jahr: str = "", titel: str = "",
                   monate: int | None = None,
                   monatsbetrag: float | None = None,
                   anlage_hinweis: str = "", abschlag_hinweis: str = "",
                   erstellt_am: date | None = None,
                   heiznachweis: dict | None = None,
                   strom: list[dict] | None = None) -> bytes:
    """Die Abrechnung einer Partei: Seite 1 (Brief + Verteilerschlüssel-
    Tabelle), optional Seite 2 (Heizkosten-Nachweis N419 und/oder Strom-
    Zusammensetzung N423).

    Die ersten sechs Parameter sind die bestehende Aufrufform aus
    `routers/versand.py` und bleiben unverändert; alles Weitere ist optional
    und wird weggelassen, wenn es niemand mitgibt. `heiznachweis` kommt aus
    `heizkosten.nachweis_fuer_einheit`, `strom` aus `versand._strom_herkunft`
    — ohne Daten bleibt jeweils der Abschnitt weg; ohne beide bleibt es beim
    Onepager."""
    posten = _posten(positionen)
    jahr = (jahr or _jahr_aus(zeitraum)).strip()
    monate = monate or _monate_aus(zeitraum)
    empfaenger = (mieter or partei or "").strip()
    adresse = (anschrift or objekt_name or "").strip()
    kasten_titel = (einheit or "").strip()
    if not kasten_titel and mieter:
        kasten_titel = (partei or "").strip()
    stichtag = erstellt_am or date.today()

    seite2_kommt = bool(heiznachweis or strom)
    seite1 = _seite_eins(objekt_name, zeitraum, empfaenger, werte, posten,
                         absender, adresse, kasten_titel, jahr, monate,
                         monatsbetrag, anlage_hinweis, abschlag_hinweis,
                         stichtag, hinweis_seite_zwei=seite2_kommt)
    blaetter = [seite1]
    if seite2_kommt:
        blaetter.append(_seite_zwei(kasten_titel, zeitraum, jahr,
                                    heiznachweis, strom))
    # Erst jetzt ist die Gesamtzahl bekannt (N438).
    for nummer, blatt in enumerate(blaetter, start=1):
        _seitenzahl(blatt, nummer, len(blaetter))
    seiten = [b.strom() for b in blaetter]

    kopf_titel = titel or (f"Betriebskostenabrechnung {jahr}" if jahr
                           else "Betriebskostenabrechnung")
    return _pdf_seiten(seiten, f"{kopf_titel} · {empfaenger}")


def pdf_dateiname(objekt_name: str, zeitraum: str, partei: str) -> str:
    """Anhangsname ohne Sonderzeichen — Mailprogramme verstümmeln sie sonst."""
    jahr = zeitraum[-4:] if zeitraum[-4:].isdigit() else ""
    return f"Abrechnung_{sauber(objekt_name)}_{jahr}_{sauber(partei)}.pdf"
