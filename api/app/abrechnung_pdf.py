"""Der Mieter-Onepager als PDF — ohne Fremdbibliothek.

Das PDF-Gerüst (Objekte, Querverweistabelle, WinAnsiEncoding) und die exakte
Helvetica-Breitenrechnung stehen in :mod:`pdfkern`, gemeinsam mit der
Tankabrechnung. Hier steht nur, wie diese eine Seite aussieht.

Gestalt: **genau eine Seite** ("Onepager"). Die Positionsliste bekommt einen
Heatmap-Hintergrund — je größer der Posten, desto kräftiger die Einfärbung
Richtung `--teal #0F6E5C`. Das ersetzt eine Zahlenkolonne durch ein Bild, das
man auf einen Blick liest, und ist damit derselbe Stil für jede Abrechnungsart.
Passt die Liste nicht, wird der Zeilenabstand gestaucht — nie umgebrochen,
denn eine zweite Seite gibt es hier strukturell nicht (`/Count 1`).

N407 — zwei Farbkorrekturen: die Heatmap färbte bisher Richtung `--neg` (Rot),
als wäre jede größere Kostenzeile eine Warnung — dieselbe Verwechslung, die
schon N399 bei der App selbst korrigiert hat (Rot/Grün sind Nachzahlung/
Guthaben, keine „hoher Betrag"-Warnung). Jetzt Richtung `--teal`, dem
neutralen Markenakzent. Und die Ergebnis-Fläche (Nachzahlung/Guthaben) war
zwar schon gerundet, aber reinweiß auf hellgrauem Kasten — im gedruckten PDF
kaum vom Rest zu unterscheiden. Sie trägt jetzt dieselbe blasse Pos/Neg-
Tönung wie die Chips in der App (`--pos-bg`/`--neg-bg`), damit das Ergebnis
als eigene Karte auffällt, nicht nur als eine Zeile mehr.
"""
from __future__ import annotations

import logging
import re
from datetime import date

from .pdfkern import SEITE_B, SEITE_H, UMLAUTE  # noqa: F401  (SEITE_B: Layout)
from .pdfkern import breite as _breite
from .pdfkern import escape as _escape
from .pdfkern import pdf as _pdf
from .pdfkern import sauber
from .zahlen import geschrieben

log = logging.getLogger("immocalc")

RAND = 48.0
UNTEN_MIN = 40.0                         # darunter darf nichts mehr stehen

# Farbsprache der App (CLAUDE.md) als 0..1-Tripel
INK = (0.086, 0.149, 0.173)              # #16262C
PAPER = (0.910, 0.925, 0.925)            # #E8ECEC
TEAL = (0.059, 0.431, 0.361)             # #0F6E5C
AMBER = (0.569, 0.384, 0.071)            # #916212
POS = (0.180, 0.490, 0.310)              # #2E7D4F
NEG = (0.698, 0.259, 0.161)              # #B24229
POS_BG = (0.906, 0.957, 0.925)           # #E7F4EC
NEG_BG = (0.969, 0.914, 0.890)           # #F7E9E3
MATT = (0.404, 0.463, 0.482)             # INK aufgehellt, für Nebentext

# Wie stark die größte Position eingefärbt wird. Darüber wird der Text auf dem
# Balken unleserlich — 0.55 ist der Punkt, an dem #16262C noch klar steht.
HEAT_MAX = 0.55
HEAT_MIN = 0.03                          # der kleinste Posten bleibt "fast weiß"


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
    """Fließtext (Anlagenhinweis) auf mehrere Zeilen verteilen."""
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
    """Sammelt Zeichenbefehle für den Inhaltsstrom der einen Seite.

    Text steht in PDF zwischen BT/ET, Flächen außerhalb. Jeder Textbaustein
    bekommt deshalb seinen eigenen BT/ET-Block — das kostet ein paar Bytes und
    erspart jede Reihenfolgeregel beim Aufbau der Seite.
    """

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
               farbe: tuple[float, float, float]) -> None:
        self.ops.append(b"%.3f %.3f %.3f RG %.2f w %.2f %.2f m %.2f %.2f l S"
                        % (farbe + (dicke, x1, y, x2, y)))

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


def _posten(positionen: list[dict] | None) -> list[tuple[str, float, bool]]:
    """Die übergebenen Positionen vereinheitlichen.

    Die Engine nennt den Betrag `kosten` (engine.py) und den §-35a-Status
    `s35`; `versand._einzelposten` reicht ihn als `betrag` weiter, die
    KI-Auslese als `s35a`. Hier werden alle drei Schreibweisen akzeptiert,
    statt an einer Stelle eine zweite Wahrheit zu erfinden."""
    fertig: list[tuple[str, float, bool]] = []
    for p in positionen or []:
        name = str(p.get("kostenart") or p.get("name") or "").strip()
        roh = p.get("betrag")
        if roh is None:
            roh = p.get("kosten")
        try:
            betrag = float(roh or 0)
        except (TypeError, ValueError):
            betrag = 0.0
        s35 = bool(p.get("s35") or p.get("s35a"))
        if name or betrag:
            fertig.append((name, betrag, s35))
    return fertig


def abrechnung_pdf(objekt_name: str, zeitraum: str, partei: str,
                   werte: dict, positionen: list[dict] | None = None,
                   absender: str = "", *,
                   mieter: str = "", anschrift: str = "", einheit: str = "",
                   jahr: str = "", titel: str = "",
                   monate: int | None = None,
                   monatsbetrag: float | None = None,
                   anlage_hinweis: str = "", abschlag_hinweis: str = "",
                   erstellt_am: date | None = None) -> bytes:
    """Der Onepager einer Partei: Kopf, Kasten, Heatmap-Positionen, Saldo.

    Die ersten sechs Parameter sind die bestehende Aufrufform aus
    `routers/versand.py` und bleiben unverändert; alles Weitere ist optional
    und wird weggelassen, wenn es niemand mitgibt.
    """
    posten = _posten(positionen)
    jahr = (jahr or _jahr_aus(zeitraum)).strip()
    monate = monate or _monate_aus(zeitraum)
    kosten = float(werte.get("kosten") or 0)
    vz = float(werte.get("vorauszahlungen") or 0)
    saldo = float(werte.get("saldo") or 0)
    s35_summe = float(werte.get("s35") or 0)
    empfaenger = (mieter or partei or "").strip()
    adresse = (anschrift or objekt_name or "").strip()
    kasten_titel = (einheit or "").strip()
    if not kasten_titel and mieter:
        # Ohne eigenen Mieternamen steht die Partei schon im Kopf — sie ein
        # zweites Mal in den Kasten zu setzen wäre eine Doublette.
        kasten_titel = (partei or "").strip()
    kopf_titel = titel or (f"Übersicht Nebenkosten – Abrechnung {jahr}"
                           if jahr else "Übersicht Nebenkosten")

    links, rechts = RAND, SEITE_B - RAND
    breite = rechts - links

    # ---- Was unterhalb des Kastens steht, bestimmt seine Höhe mit
    fuss: list[tuple[str, float, bool, tuple[float, float, float]]] = []
    if anlage_hinweis:
        for zeile in _umbruch(anlage_hinweis, breite, 9):
            fuss.append((zeile, 9, False, INK))
    if any(s for _, _, s in posten):
        fuss.append(("*  haushaltsnahe Dienstleistungen nach § 35a EStG",
                     8.5, False, MATT))
    if abschlag_hinweis:
        fuss.append((abschlag_hinweis, 9, False, AMBER))
    unterschrift = " ".join(x for x in [
        f"{erstellt_am or date.today():%d.%m.%Y}", (absender or "").strip()] if x)

    fuss_hoehe = 18 + sum(z[1] + 4.5 for z in fuss) + 20
    kasten_oben = SEITE_H - RAND - 14 - 36 - 26
    kasten_unten_min = UNTEN_MIN + fuss_hoehe

    # ---- Summenblock: erst zusammenstellen, dann Platz rechnen
    summen: list[tuple[str, str, bool, tuple[float, float, float]]] = []
    summen.append((f"Ihre angefallenen Nebenkosten {jahr}".strip(),
                   _zahl(kosten), True, INK))
    if monate:
        summen.append(("entspricht monatlich", _zahl(kosten / monate), False,
                       MATT))
    if s35_summe:
        summen.append(("davon haushaltsnah nach § 35a EStG",
                       _zahl(s35_summe), False, AMBER))
    if monate:
        pro_monat = monatsbetrag if monatsbetrag is not None else vz / monate
        summen.append((f"Vorauszahlungen {monate} Monate à "
                       f"{_zahl(pro_monat)} €/mtl", _zahl(vz), False, INK))
    else:
        summen.append(("Geleistete Vorauszahlungen", _zahl(vz), False, INK))

    anzahl = len(posten)
    ergebnis_farbe = POS if saldo >= 0 else NEG
    groesster = max((abs(b) for _, b, _ in posten), default=0.0)

    def zeichne(dehnung: float) -> tuple[Blatt, float, float, float]:
        """Die Seite einmal setzen — `dehnung` streckt nur die Abstände.

        Eine kurze Abrechnung (drei Posten) füllte den Bogen sonst nur zu einem
        Drittel und ließ den Rest als tote Fläche stehen. Deshalb wird die Seite
        zweimal gebaut: der erste Lauf misst, der zweite verteilt den
        Überschuss auf Innenabstände, Zeilen- und Ergebniszone. Die
        Schriftgrade bleiben dabei fest — sonst wirkt die Seite aufgeblasen."""
        blatt = Blatt()
        pad = 16.0 * dehnung
        # Kastenkopf und Ergebniszone sind inhaltlich bemessen und wachsen
        # nicht mit — gedehnt hinterließen sie nur ein Loch unter dem Text.
        # Ohne Einheit steht im Kopf nur eine Zeile statt zwei.
        kopf_zone = 46.0 if kasten_titel else 40.0
        summen_schritt = 17.0 * dehnung
        summen_zone = len(summen) * summen_schritt + 8.0
        saldo_zone = 36.0
        # Ohne Positionen gäbe es zwei Trennlinien mit nichts dazwischen.
        listen_rand = 16.0 if anzahl else 0.0
        fest = (pad * 2 + kopf_zone + listen_rand + summen_zone + 12
                + saldo_zone)
        frei = kasten_oben - kasten_unten_min - fest
        # Genau eine Seite: der Zeilenabstand wird gestaucht, bis die Liste
        # passt. Eine zweite Seite kann es nicht geben — /Count 1 steht fest.
        schritt = (max(4.0, min(24.0 * dehnung, 30.0, frei / anzahl))
                   if anzahl else 0.0)
        kasten_hoehe = fest + schritt * anzahl
        kasten_unten = kasten_oben - kasten_hoehe

        blatt.flaeche(links, kasten_unten, breite, kasten_hoehe, PAPER, 12)
        innen_l, innen_r = links + pad, rechts - pad
        innen_breite = innen_r - innen_l

        # ---- Kastenkopf: Einheit + Zeitraum links, Jahr + Währung rechts
        ky = kasten_oben - pad
        if jahr:
            blatt.text_rechts(innen_r, ky - 17, jahr, 21, True, TEAL)
            blatt.text_rechts(innen_r, ky - 30, "Euro", 8, False, MATT)
        if kasten_titel:
            blatt.text(innen_l, ky - 12, kasten_titel, 12.5, True, INK)
            blatt.text(innen_l, ky - 27, f"Zeitraum {zeitraum}", 9.5, False,
                       MATT)
        else:
            blatt.text(innen_l, ky - 12, f"Zeitraum {zeitraum}", 11, True, INK)
        ky -= kopf_zone
        blatt.strich(innen_l, innen_r, ky, 0.8, _mische(PAPER, INK, 0.25))

        # ---- Positionen mit Heatmap
        if anzahl:
            ky -= listen_rand / 2
            grad = max(6.0, min(10.5, schritt * 0.62))
            betrag_breite = max(_breite(_zahl(b), grad) for _, b, _ in posten)
            name_max = innen_breite - betrag_breite - 34
            for name, betrag, s35 in posten:
                anteil = (abs(betrag) / groesster) if groesster else 0.0
                farbe = _mische(PAPER, TEAL,
                                HEAT_MIN + (HEAT_MAX - HEAT_MIN) * anteil)
                blatt.flaeche(innen_l, ky - schritt + 1.5, innen_breite,
                              schritt - 2.5, farbe, 3)
                basis = ky - schritt + (schritt - grad) / 2 + 1.5
                blatt.text(innen_l + 8, basis,
                           _kuerzen(name + (" *" if s35 else ""), name_max,
                                    grad), grad, False, INK)
                blatt.text_rechts(innen_r - 10, basis, _zahl(betrag), grad,
                                  False, INK)
                ky -= schritt
            ky -= listen_rand / 2
            blatt.strich(innen_l, innen_r, ky, 0.8, _mische(PAPER, INK, 0.25))

        # ---- Summen
        for beschriftung, wert, fett, farbe in summen:
            ky -= summen_schritt
            blatt.text(innen_l + 8, ky, beschriftung, 10, fett, farbe)
            blatt.text_rechts(innen_r - 10, ky, wert, 10, fett, farbe)

        # ---- Ergebnis: Doppelstrich und eine eigene, farblich getönte Fläche
        # N407 — blasses Pos/Neg statt reinem Weiß: auf dem hellgrauen Kasten
        # war eine weiße Fläche kaum als eigene Karte zu erkennen.
        ky -= 12
        blatt.strich(innen_l, innen_r, ky + 3.0, 0.8, INK)
        blatt.strich(innen_l, innen_r, ky + 0.6, 0.8, INK)
        hoehe = saldo_zone - 10
        blatt.flaeche(innen_l, ky - hoehe, innen_breite, hoehe,
                      POS_BG if saldo >= 0 else NEG_BG, 10)
        basis = ky - hoehe + (hoehe - 13) / 2 + 3
        blatt.text(innen_l + 10, basis, "Nachzahlung (-) / Guthaben (+)", 11.5,
                   True, INK)
        blatt.text_rechts(innen_r - 10, basis, _zahl(saldo, vorzeichen=True),
                          13.5, True, ergebnis_farbe)

        # ---- Fußnoten und Unterschriftszeile
        fy = kasten_unten - 18
        for zeile, groesse, fett, farbe in fuss:
            fy -= groesse + 4.5
            blatt.text(links, fy, zeile, groesse, fett, farbe)
        fy -= 20
        blatt.text(links, fy, unterschrift, 9.5, False, MATT)
        return blatt, fy, kasten_hoehe, schritt

    blatt, unterkante, kasten_hoehe, schritt = zeichne(1.0)
    ueberschuss = unterkante - UNTEN_MIN
    if ueberschuss > 20:
        dehnung = min(1.4, 1.0 + ueberschuss / max(kasten_hoehe, 1.0))
        blatt, unterkante, _, schritt = zeichne(dehnung)
    if anzahl and schritt < 8.0:
        log.info("Onepager gestaucht: %d Positionen auf %.1f pt Zeilenabstand "
                 "(%s)", anzahl, schritt, empfaenger)

    # ---- Kopf: steht außerhalb von `zeichne`, weil er nie mitwächst
    y = SEITE_H - RAND - 14
    blatt.text(links, y, kopf_titel, 17, True, INK)
    blatt.text(links, y - 22, empfaenger, 11.5, True, INK)
    blatt.text(links, y - 36, adresse, 10, False, MATT)

    strom = blatt.strom()
    # Was jetzt noch übrig ist, wird zur Hälfte als Luft nach oben und unten
    # verteilt — ein kurzer Onepager sitzt so mittig statt am oberen Rand zu
    # kleben. Ein einziger Transformationsbefehl verschiebt die ganze Seite.
    rest = unterkante - UNTEN_MIN
    if rest > 20:
        strom = b"1 0 0 1 0 %.2f cm\n" % (-min(rest * 0.45, 96.0)) + strom
    return _pdf(strom, f"{kopf_titel} · {empfaenger}")


def pdf_dateiname(objekt_name: str, zeitraum: str, partei: str) -> str:
    """Anhangsname ohne Sonderzeichen — Mailprogramme verstümmeln sie sonst."""
    jahr = zeitraum[-4:] if zeitraum[-4:].isdigit() else ""
    return f"Abrechnung_{sauber(objekt_name)}_{jahr}_{sauber(partei)}.pdf"
