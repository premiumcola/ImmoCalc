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
UNTEN_MIN = 42.0                         # darunter darf nichts mehr stehen

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

    # ---- Briefkopf: Logo + Datum
    y = SEITE_H - RAND
    blatt.logo(links, y - 15, 15)
    blatt.text(links + 21, y - 10, "ImmoCalc", 9.5, True, INK)
    blatt.text_rechts(rechts, y - 10, f"{erstellt_am:%d.%m.%Y}", 9, False, MATT)
    y -= 24
    blatt.strich(links, rechts, y, 0.8, LINIE)
    y -= 18

    # ---- Absenderzeile (klein, DIN-Brief-Konvention)
    if absender or objekt_name:
        blatt.text(links, y, _kuerzen(
            " · ".join(x for x in [absender, objekt_name] if x), breite, 7.5),
            7.5, False, MATT)
    y -= 26

    # ---- Empfänger
    if empfaenger:
        blatt.text(links, y, empfaenger, 11.5, True, INK)
        y -= 15
    if kasten_titel and kasten_titel != empfaenger:
        blatt.text(links, y, kasten_titel, 10, False, MATT)
        y -= 13
    for zeile in _umbruch(adresse, breite * 0.6, 10)[:2]:
        blatt.text(links, y, zeile, 10, False, MATT)
        y -= 13
    y -= 20

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

    # ---- Verteilerschlüssel-Tabelle
    kosten = float(werte.get("kosten") or 0)
    vz = float(werte.get("vorauszahlungen") or 0)
    s35_summe = float(werte.get("s35") or 0)

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
        fest_danach = (18 + len(_summenzeilen(kosten, monate, s35_summe, vz,
                                              monatsbetrag)) * 15.5
                      + 34 + _fussnoten_hoehe(posten, anlage_hinweis,
                                              abschlag_hinweis) + 58)
        frei = y - (RAND + UNTEN_MIN) - fest_danach
        zeile_h = min(15.0, max(8.0, frei / len(posten)))
        groesse = min(9.5, max(6.5, zeile_h * 0.62))

        groesster = max((abs(p["betrag"]) for p in posten), default=0.0)
        for p in posten:
            anteil = (abs(p["betrag"]) / groesster) if groesster else 0.0
            akzent = _mische(WEISS, TEAL, AKZENT_MIN + (AKZENT_MAX - AKZENT_MIN) * anteil)
            blatt.flaeche(links, y - zeile_h + 2, breite, zeile_h - 2, akzent, 2)
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
                nachweis: dict) -> Blatt:
    blatt = Blatt()
    links, rechts = RAND, SEITE_B - RAND
    breite = rechts - links
    y = SEITE_H - RAND

    blatt.text(links, y, kasten_titel or "Nachweis Heizkosten", 9, False, MATT)
    blatt.text_rechts(rechts, y, f"{jahr} · Seite 2", 9, False, MATT)
    y -= 20
    blatt.strich(links, rechts, y, 0.8, LINIE)
    y -= 30

    blatt.text(links, y, "Nachweis Heizung & Warmwasser", 15, True, INK)
    y -= 18
    blatt.text(links, y, f"Zeitraum {zeitraum} · nur Ihre eigenen Zähler und "
               "die Gesamtsumme aller Einheiten", 9.5, False, MATT)
    y -= 26

    # ---- Zählertabelle
    zeilen = nachweis.get("zaehler") or []
    if zeilen:
        breiten = [breite * a for a in (0.34, 0.14, 0.17, 0.17, 0.18)]
        kanten = [sum(breiten[:i + 1]) for i in range(len(breiten))]
        _tabellenkopf(blatt, links, y, [
            ("Zähler", 0, "l"), ("Nummer", kanten[0], "l"),
            ("Anfangsstand", kanten[2], "r"), ("Endstand", kanten[3], "r"),
            ("Verbrauch", kanten[4], "r")])
        y -= 22

        for z in zeilen:
            ist_ww = z.get("kostenart") == "Warmwasser"
            ist_wmz = z.get("messeinheit") == "kWh"
            einheit = "m³" if ist_ww else ("kWh" if ist_wmz else "Punkte")
            nachkomma = 3 if ist_ww else (1 if ist_wmz else 0)
            blatt.text(links + 6, y, z["name"], 9.5, False, INK)
            blatt.text(links + kanten[0] + 6, y, z.get("nummer") or "–", 9,
                      False, MATT)
            blatt.text_rechts(links + kanten[2] - 6, y,
                              _fehlt(z.get("start"), nachkomma), 9, False, MATT)
            blatt.text_rechts(links + kanten[3] - 6, y,
                              _fehlt(z.get("ende"), nachkomma), 9, False, MATT)
            verbrauch_text = _fehlt(z.get("verbrauch"), nachkomma, einheit=einheit)
            if not ist_ww and not ist_wmz and z.get("bewertungsfaktor") and z.get("verbrauch") is not None:
                bewertet = z["verbrauch"] * z["bewertungsfaktor"]
                verbrauch_text = (f"{verbrauch_text} × {_zahl(z['bewertungsfaktor'])} "
                                  f"= {_zahl(bewertet)}")
            blatt.text_rechts(rechts - 6, y, verbrauch_text, 9, True, INK)
            y -= 22
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

    y -= 20
    for zeile in _umbruch("Aus Datenschutzgründen werden nur die Zählerstände "
                          "Ihrer eigenen Einheit sowie die Gesamtsumme aller "
                          "Einheiten gemeinsam ausgewiesen — keine Einzelwerte "
                          "anderer Mietparteien.", breite, 8):
        blatt.text(links, y, zeile, 8, False, MATT)
        y -= 12

    return blatt


def abrechnung_pdf(objekt_name: str, zeitraum: str, partei: str,
                   werte: dict, positionen: list[dict] | None = None,
                   absender: str = "", *,
                   mieter: str = "", anschrift: str = "", einheit: str = "",
                   jahr: str = "", titel: str = "",
                   monate: int | None = None,
                   monatsbetrag: float | None = None,
                   anlage_hinweis: str = "", abschlag_hinweis: str = "",
                   erstellt_am: date | None = None,
                   heiznachweis: dict | None = None) -> bytes:
    """Die Abrechnung einer Partei: Seite 1 (Brief + Verteilerschlüssel-
    Tabelle), optional Seite 2 (Heizkosten-Nachweis, N419).

    Die ersten sechs Parameter sind die bestehende Aufrufform aus
    `routers/versand.py` und bleiben unverändert; alles Weitere ist optional
    und wird weggelassen, wenn es niemand mitgibt. `heiznachweis` kommt aus
    `heizkosten.nachweis_fuer_einheit` — ohne Zählerdaten bleibt es leer und
    das PDF hat wie gehabt nur eine Seite."""
    posten = _posten(positionen)
    jahr = (jahr or _jahr_aus(zeitraum)).strip()
    monate = monate or _monate_aus(zeitraum)
    empfaenger = (mieter or partei or "").strip()
    adresse = (anschrift or objekt_name or "").strip()
    kasten_titel = (einheit or "").strip()
    if not kasten_titel and mieter:
        kasten_titel = (partei or "").strip()
    stichtag = erstellt_am or date.today()

    seite1 = _seite_eins(objekt_name, zeitraum, empfaenger, werte, posten,
                         absender, adresse, kasten_titel, jahr, monate,
                         monatsbetrag, anlage_hinweis, abschlag_hinweis,
                         stichtag, hinweis_seite_zwei=bool(heiznachweis))
    seiten = [seite1.strom()]
    if heiznachweis:
        seiten.append(_seite_zwei(kasten_titel, zeitraum, jahr, heiznachweis).strom())

    kopf_titel = titel or (f"Betriebskostenabrechnung {jahr}" if jahr
                           else "Betriebskostenabrechnung")
    return _pdf_seiten(seiten, f"{kopf_titel} · {empfaenger}")


def pdf_dateiname(objekt_name: str, zeitraum: str, partei: str) -> str:
    """Anhangsname ohne Sonderzeichen — Mailprogramme verstümmeln sie sonst."""
    jahr = zeitraum[-4:] if zeitraum[-4:].isdigit() else ""
    return f"Abrechnung_{sauber(objekt_name)}_{jahr}_{sauber(partei)}.pdf"
