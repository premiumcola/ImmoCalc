"""Verteilungsgewichte aus dem Schlüssel ableiten.

Die Rechen-Engine verteilt Kosten nach Gewichten (`Kostenposition.anteile`).
Woher diese Gewichte kommen, stand bisher nirgends: geschrieben hat sie nur der
Seed, und für jede selbst angelegte Immobilie blieb das Feld leer — die
Abrechnung lieferte dann keine Parteien und in der Summe 0,00 €.

Hier steht deshalb die Ableitung: aus den Stammdaten (Einheiten, laufende
Mietverhältnisse, Parteien) ergeben sich für die meisten Schlüssel die Gewichte
von selbst. Was sich nicht ableiten lässt — Zählerstände, Prozentsätze,
individuelle Zuordnung — bleibt Handarbeit und wird als solche gemeldet, statt
stillschweigend als Null durchzurutschen.

Die Partei-Namen stammen aus demselben Ort wie beim Versand
(`versand._empfaenger`): dem laufenden Mietverhältnis. Nur dann treffen
Verteilung, Vorauszahlung und Empfänger dieselbe Partei.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlmodel import Session, select

from .cashflow import monate_im_jahr
from .models import Einheit, Kostenposition, Miete, Partei, Zeitraum

# Was jeder Schlüssel bedeutet und ob er sich aus den Stammdaten ergibt.
# `einheit` ist die Maßeinheit des Gewichts — ohne sie steht in der Oberfläche
# nur eine nackte Zahl („Büro 4.1398"), die niemand einordnen kann.
SCHLUESSEL: dict[str, dict] = {
    "flaeche": {
        "titel": "Fläche", "einheit": "m²", "ableitbar": True,
        "hinweis": "Wohn-/Nutzfläche je Einheit; Terrasse und Nebenfläche "
                   "zählen zur Hälfte.",
    },
    "personen": {
        "titel": "Personen", "einheit": "Pers.", "ableitbar": True,
        "hinweis": "Personenzahl des laufenden Mietverhältnisses.",
    },
    "einheiten": {
        "titel": "Einheiten", "einheit": "Anteil", "ableitbar": True,
        "hinweis": "Alle Parteien zu gleichen Teilen.",
    },
    "bewohnermonate": {
        "titel": "Bewohnermonate", "einheit": "Pers.-Mon.", "ableitbar": True,
        "hinweis": "Personen × Monate im Zeitraum, taggenau — deckt den "
                   "Mieterwechsel mitten im Jahr ab.",
    },
    "verbrauch": {
        "titel": "Verbrauch", "einheit": "Zählerwert", "ableitbar": False,
        "hinweis": "Zählerstände lassen sich nicht ableiten — Werte je Partei "
                   "von Hand eintragen.",
    },
    "prozent": {
        "titel": "Prozent", "einheit": "%", "ableitbar": False,
        "hinweis": "Prozentsätze werden vereinbart, nicht berechnet.",
    },
    "individuell": {
        "titel": "Individuell", "einheit": "Anteil", "ableitbar": False,
        "hinweis": "Direkte Zuordnung — Gewichte von Hand setzen.",
    },
}

VORGABE = "flaeche"


class UnbekannterSchluessel(ValueError):
    """Ein Verteilungsschlüssel, den die Engine nicht kennt."""


@dataclass
class Bezug:
    """Eine Partei mit allem, woraus sich ihr Gewicht ergeben kann."""
    partei: str
    einheit: str = ""
    flaeche: float | None = None
    personen: int = 1
    ab: date | None = None
    bis: date | None = None


def _gesamtflaeche(e: Einheit) -> float | None:
    """Wie in `cashflow.EinheitZahlen.gesamtflaeche`: Terrasse und Nebenfläche
    zählen üblicherweise zur Hälfte. Ohne jede Angabe bleibt es None — eine 0
    wäre gelogen und würde die Partei aus der Verteilung werfen, ohne dass es
    auffällt."""
    teile = [e.flaeche, e.terrasse, e.nebenflaeche]
    if all(t is None for t in teile):
        return None
    return round((e.flaeche or 0) + (e.terrasse or 0) * 0.5
                 + (e.nebenflaeche or 0) * 0.5, 2)


def _laufend(mieten: list[Miete], start: date, ende: date) -> list[Miete]:
    """Mietverhältnisse, die den Zeitraum berühren — auch die schon beendeten.
    Wer bis Juli gewohnt hat, gehört in die Abrechnung dieses Jahres."""
    return [m for m in mieten
            if m.ab_datum <= ende and (m.bis_datum is None or m.bis_datum >= start)]


def bezuege(einheiten: list[Einheit], mieten: list[Miete],
            parteien: list[Partei], start: date, ende: date) -> list[Bezug]:
    """Wer im Zeitraum abzurechnen ist — in dieser Reihenfolge:

    1. laufende Mietverhältnisse (dort steht auch die Mailadresse),
    2. Einheiten ohne Mietverhältnis (Leerstand, Eigennutzung),
    3. ersatzweise die Partei-Liste des Objekts, falls es weder Einheiten
       noch Mietverhältnisse gibt.
    """
    flaechen = {e.bezeichnung: _gesamtflaeche(e) for e in einheiten}
    personen_je = {p.name: p.personen for p in parteien}
    treffer: list[Bezug] = []
    belegt: set[str] = set()

    for m in sorted(_laufend(mieten, start, ende),
                    key=lambda m: (m.einheit, m.ab_datum)):
        if not m.partei:
            continue
        # Ein Mietverhältnis ohne Einheit gehört bei einer Einzelwohnung
        # eindeutig zu dieser — sonst stünde die Wohnung ein zweites Mal als
        # eigene Partei in der Verteilung und bekäme Kosten aufgebrummt.
        name = m.einheit or (einheiten[0].bezeichnung if len(einheiten) == 1 else "")
        belegt.add(name)
        treffer.append(Bezug(
            partei=m.partei, einheit=name, flaeche=flaechen.get(name),
            personen=m.personen or personen_je.get(m.partei, 1),
            ab=max(m.ab_datum, start), bis=min(m.bis_datum or ende, ende)))

    for e in einheiten:
        if e.bezeichnung in belegt:
            continue
        treffer.append(Bezug(
            partei=e.bezeichnung, einheit=e.bezeichnung,
            flaeche=flaechen[e.bezeichnung],
            personen=personen_je.get(e.bezeichnung, 1), ab=start, bis=ende))

    if not treffer:
        for p in parteien:
            treffer.append(Bezug(
                partei=p.name, personen=p.personen,
                ab=max(p.einzug or start, start), bis=min(p.auszug or ende, ende)))
    return treffer


def _monate(b: Bezug, start: date, ende: date) -> float:
    """Monate im Zeitraum, taggenau. `monate_im_jahr` rechnet je Kalenderjahr —
    ein Wirtschaftsjahr Oktober–September berührt zwei davon."""
    von = max(b.ab or start, start)
    bis = min(b.bis or ende, ende)
    if bis < von:
        return 0.0
    return round(sum(monate_im_jahr(von, bis, j)
                     for j in range(von.year, bis.year + 1)), 4)


def _gewicht(schluessel: str, b: Bezug, start: date, ende: date) -> float | None:
    """Gewicht einer Partei — None heißt: nimmt an diesem Schlüssel nicht teil."""
    if schluessel == "flaeche":
        return b.flaeche if b.flaeche else None
    if schluessel == "personen":
        return float(b.personen or 0) or None
    if schluessel == "einheiten":
        return 1.0
    if schluessel == "bewohnermonate":
        monate = _monate(b, start, ende)
        return round((b.personen or 0) * monate, 4) or None
    return None


def gewichte(schluessel: str, bezuege_: list[Bezug],
             start: date, ende: date) -> dict[str, float]:
    """Gewichte je Partei für einen Schlüssel. Leeres dict heißt ehrlich:
    hier ist nichts abzuleiten — die Zahlen müssen von Hand kommen."""
    if schluessel not in SCHLUESSEL:
        raise UnbekannterSchluessel(
            f"Unbekannter Verteilungsschlüssel '{schluessel}'. Möglich: "
            + ", ".join(SCHLUESSEL))
    if not SCHLUESSEL[schluessel]["ableitbar"]:
        return {}
    out: dict[str, float] = {}
    for b in bezuege_:
        w = _gewicht(schluessel, b, start, ende)
        if w is None:
            continue
        # Zwei Mietverhältnisse derselben Partei (Wohnung und Garage) zählen
        # zusammen, statt sich gegenseitig zu überschreiben.
        out[b.partei] = round(out.get(b.partei, 0.0) + w, 4)
    return out if sum(out.values()) > 0 else {}


def stammdaten(session: Session, z: Zeitraum) -> list[Bezug]:
    """Bezüge eines Zeitraums aus der Datenbank."""
    einheiten = list(session.exec(
        select(Einheit).where(Einheit.objekt_id == z.objekt_id)).all())
    mieten = list(session.exec(
        select(Miete).where(Miete.objekt_id == z.objekt_id)).all())
    parteien = list(session.exec(
        select(Partei).where(Partei.objekt_id == z.objekt_id)).all())
    return bezuege(einheiten, mieten, parteien, z.start, z.ende)


def ableiten(session: Session, z: Zeitraum, schluessel: str) -> dict[str, float]:
    """Gewichte für eine neue oder umgestellte Position."""
    return gewichte(schluessel, stammdaten(session, z), z.start, z.ende)


def vorschau(bezuege_: list[Bezug], start: date, ende: date) -> list[dict]:
    """Alle Schlüssel mit den Gewichten, die dabei herauskämen — damit man
    sieht, worauf man sich einlässt, bevor man sich festlegt."""
    out = []
    for wert, meta in SCHLUESSEL.items():
        g = gewichte(wert, bezuege_, start, ende)
        summe = round(sum(g.values()), 4)
        out.append({
            "wert": wert, "titel": meta["titel"], "einheit": meta["einheit"],
            "ableitbar": meta["ableitbar"], "hinweis": meta["hinweis"],
            "gewichte": g, "summe": summe,
            "prozent": {k: round(v / summe * 100, 2) for k, v in g.items()}
            if summe > 0 else {},
            "moeglich": bool(g),
        })
    return out


def fehlende_angaben(positionen: list[Kostenposition]) -> dict:
    """Was einen sauberen Abschluss noch verhindert.

    Zwei Fälle, die beide zu einer zu kleinen Abrechnung führen:
    *ohne Betrag* — die Position ist noch offen; und *ohne Verteilung* — sie
    gilt als erledigt, hat aber keine Gewichte. Der zweite Fall ist der
    tückische: der Betrag verschwindet lautlos aus der Abrechnung, weil
    `verteile_nach_wert` ein leeres dict bekommt und nichts zurückgibt.
    """
    ohne_betrag = [p.kostenart for p in positionen if p.status != "erledigt"]
    ohne_verteilung = [p.kostenart for p in positionen
                       if p.status == "erledigt" and (p.betrag or 0) != 0
                       and sum((p.anteile or {}).values()) <= 0]
    return {"ohne_betrag": ohne_betrag, "ohne_verteilung": ohne_verteilung,
            "offen": ohne_betrag + ohne_verteilung}
