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

from dataclasses import dataclass, field
from datetime import date, timedelta

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
                   "zählen zur Hälfte. Bei einem Mieterwechsel teilen sich "
                   "Vor- und Nachmieter die Fläche nach Wohndauer; "
                   "Leerstandszeiten bleiben beim Eigentümer.",
    },
    "personen": {
        "titel": "Personen", "einheit": "Pers.", "ableitbar": True,
        "hinweis": "Personenzahl des Mietverhältnisses, gewichtet nach "
                   "Wohndauer im Zeitraum.",
    },
    "einheiten": {
        "titel": "Einheiten", "einheit": "Anteil", "ableitbar": True,
        "hinweis": "Alle Einheiten zu gleichen Teilen; bei einem Wechsel "
                   "teilen sich Vor- und Nachmieter den Anteil ihrer Einheit.",
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
    """Eine Partei mit allem, woraus sich ihr Gewicht ergeben kann.

    `zugeordnet` sagt, ob sich die genannte Einheit im Objekt wiederfindet.
    `Miete.einheit` ist Freitext: steht dort nichts (bei mehreren Einheiten)
    oder eine abweichende Schreibweise, dann gibt es keine Fläche, die Partei
    fällt aus der Flächenverteilung — und bekäme ihre Vorauszahlung voll
    erstattet, ohne dass es jemandem auffällt.

    `zeiten` trägt die Spannen, in denen der Bezug im Zeitraum gilt. Für ein
    Mietverhältnis ist das genau `ab`–`bis`; ein Leerstand kann dagegen aus
    mehreren Stücken bestehen (Januar leer, dann vermietet, im Dezember wieder
    leer), die sich nicht als ein einzelnes ab/bis schreiben lassen."""
    partei: str
    einheit: str = ""
    flaeche: float | None = None
    personen: int = 1
    ab: date | None = None
    bis: date | None = None
    zugeordnet: bool = True
    leerstand: bool = False
    zeiten: list[tuple[date, date]] = field(default_factory=list)


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


def _luecken(belegt: list[tuple[date, date]],
             start: date, ende: date) -> list[tuple[date, date]]:
    """Die Zeitspannen, in denen eine Einheit im Zeitraum leer stand.

    Die belegten Spannen sind einschliesslich zu verstehen: endet ein
    Mietverhältnis am 30.06., beginnt der Leerstand am 01.07."""
    frei: list[tuple[date, date]] = []
    lauf = start
    for von, bis in sorted(belegt):
        if von > lauf:
            frei.append((lauf, von - timedelta(days=1)))
        lauf = max(lauf, bis + timedelta(days=1))
        if lauf > ende:
            return frei
    if lauf <= ende:
        frei.append((lauf, ende))
    return frei


def bezuege(einheiten: list[Einheit], mieten: list[Miete],
            parteien: list[Partei], start: date, ende: date) -> list[Bezug]:
    """Wer im Zeitraum abzurechnen ist — in dieser Reihenfolge:

    1. laufende Mietverhältnisse (dort steht auch die Mailadresse),
    2. die unbelegte Zeit jeder Einheit (Leerstand, Eigennutzung),
    3. ersatzweise die Partei-Liste des Objekts, falls es weder Einheiten
       noch Mietverhältnisse gibt.

    Punkt 2 gilt ausdrücklich auch für eine Einheit, die nur einen Teil des
    Zeitraums vermietet war. Vorher bekam nur die ganz leerstehende Einheit
    einen Bezug; endete ein Mietverhältnis mitten im Jahr ohne Nachmieter,
    galt die Einheit als belegt und trug — seit die Gewichte zeitanteilig sind
    — nur noch ihren halben Anteil. Der Rest verteilte sich auf die übrigen
    Mieter: bei 60 m² (halbes Jahr) und 90 m² zahlte das OG 75,2 % statt 60 %.
    Mit dem Leerstands-Bezug summiert sich jede Einheit wieder exakt auf ihre
    Fläche, und die unbelegte Zeit bleibt beim Eigentümer.
    """
    flaechen = {e.bezeichnung: _gesamtflaeche(e) for e in einheiten}
    personen_je = {p.name: p.personen for p in parteien}
    treffer: list[Bezug] = []
    belegt: dict[str, list[tuple[date, date]]] = {}

    for m in sorted(_laufend(mieten, start, ende),
                    key=lambda m: (m.einheit, m.ab_datum)):
        if not m.partei:
            continue
        # Ein Mietverhältnis ohne Einheit gehört bei einer Einzelwohnung
        # eindeutig zu dieser — sonst stünde die Wohnung ein zweites Mal als
        # eigene Partei in der Verteilung und bekäme Kosten aufgebrummt.
        name = m.einheit or (einheiten[0].bezeichnung if len(einheiten) == 1 else "")
        von, bis = max(m.ab_datum, start), min(m.bis_datum or ende, ende)
        belegt.setdefault(name, []).append((von, bis))
        treffer.append(Bezug(
            partei=m.partei, einheit=name, flaeche=flaechen.get(name),
            personen=m.personen or personen_je.get(m.partei, 1),
            ab=von, bis=bis, zeiten=[(von, bis)],
            zugeordnet=not einheiten or name in flaechen))

    for e in einheiten:
        frei = _luecken(belegt.get(e.bezeichnung, []), start, ende)
        if not frei:
            continue
        treffer.append(Bezug(
            partei=e.bezeichnung, einheit=e.bezeichnung,
            flaeche=flaechen[e.bezeichnung],
            personen=personen_je.get(e.bezeichnung, 1),
            ab=frei[0][0], bis=frei[-1][1], zeiten=frei, leerstand=True))

    if not treffer:
        for p in parteien:
            treffer.append(Bezug(
                partei=p.name, personen=p.personen,
                ab=max(p.einzug or start, start), bis=min(p.auszug or ende, ende)))
    return treffer


def _monate(b: Bezug, start: date, ende: date) -> float:
    """Monate im Zeitraum, taggenau. `monate_im_jahr` rechnet je Kalenderjahr —
    ein Wirtschaftsjahr Oktober–September berührt zwei davon.

    Ein Leerstand besteht unter Umständen aus mehreren Stücken; sie werden
    zusammengezählt."""
    summe = 0.0
    for a, z in b.zeiten or [(b.ab or start, b.bis or ende)]:
        von, bis = max(a, start), min(z, ende)
        if bis < von:
            continue
        summe += sum(monate_im_jahr(von, bis, j)
                     for j in range(von.year, bis.year + 1))
    return round(summe, 4)


def _zeitraum_monate(start: date, ende: date) -> float:
    """Länge des Abrechnungszeitraums in Monaten, taggenau — die Bezugsgröße,
    an der die Wohndauer gemessen wird."""
    if ende < start:
        return 0.0
    return round(sum(monate_im_jahr(start, ende, j)
                     for j in range(start.year, ende.year + 1)), 4)


def _zeitanteil(b: Bezug, start: date, ende: date) -> float:
    """Welchen Teil des Zeitraums diese Partei bewohnt hat: 1.0 durchgehend,
    0.5 ein halbes Jahr."""
    gesamt = _zeitraum_monate(start, ende)
    if gesamt <= 0:
        return 0.0
    return _monate(b, start, ende) / gesamt


def _gewicht(schluessel: str, b: Bezug, start: date, ende: date) -> float | None:
    """Gewicht einer Partei — None heißt: nimmt an diesem Schlüssel nicht teil.

    Alle Gewichte sind zeitanteilig. Ohne das bekam bei einem Mieterwechsel
    jede der beiden Parteien die volle Fläche ihrer Einheit angerechnet: eine
    Wohnung mit Wechsel zählte doppelt, und die Nachbarwohnung ohne Wechsel
    zahlte entsprechend zu wenig — beim Wechsel am 21.12. genauso viel wie bei
    einem Wechsel zur Jahresmitte. Mit dem Zeitanteil teilen sich Vor- und
    Nachmieter die 60 m² ihrer Einheit nach Wohndauer, und die Summe je
    Einheit stimmt wieder."""
    if schluessel == "bewohnermonate":
        # Schon in Personen-Monaten gemessen — dort steckt die Dauer im Wert.
        return round((b.personen or 0) * _monate(b, start, ende), 4) or None
    if schluessel == "flaeche":
        basis = b.flaeche or 0.0
    elif schluessel == "personen":
        basis = float(b.personen or 0)
    elif schluessel == "einheiten":
        basis = 1.0
    else:
        return None
    return round(basis * _zeitanteil(b, start, ende), 4) or None


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


def ohne_einheit(bezuege_: list[Bezug]) -> list[str]:
    """Parteien, deren Mietverhältnis auf keine Einheit des Objekts zeigt."""
    return sorted({b.partei for b in bezuege_ if not b.zugeordnet})


def leerstaende(bezuege_: list[Bezug]) -> list[str]:
    """Bezüge, hinter denen keine Partei steht, sondern unbelegte Zeit.

    Sie tragen ihren Anteil an den Kosten — der bleibt beim Eigentümer — und
    bekommen weder Vorauszahlung noch Post."""
    return sorted({b.partei for b in bezuege_ if b.leerstand})


def vorschau(bezuege_: list[Bezug], start: date, ende: date) -> list[dict]:
    """Alle Schlüssel mit den Gewichten, die dabei herauskämen — damit man
    sieht, worauf man sich einlässt, bevor man sich festlegt.

    `parteien_ohne_einheit` nennt die Parteien, die bei diesem Schlüssel leer
    ausgingen, weil ihre Einheit nicht zu finden ist. Solange dort jemand
    steht, gilt der Schlüssel nicht als sauber ableitbar: er würde rechnen, als
    gäbe es die Partei nicht — sie bekäme keine Kosten und ihre Vorauszahlung
    voll erstattet."""
    fehlzuordnung = ohne_einheit(bezuege_)
    leer = leerstaende(bezuege_)
    out = []
    for wert, meta in SCHLUESSEL.items():
        g = gewichte(wert, bezuege_, start, ende)
        betroffen = [name for name in fehlzuordnung if name not in g]
        summe = round(sum(g.values()), 4)
        out.append({
            "wert": wert, "titel": meta["titel"], "einheit": meta["einheit"],
            "ableitbar": meta["ableitbar"] and not betroffen,
            "hinweis": meta["hinweis"],
            "gewichte": g, "summe": summe,
            "prozent": {k: round(v / summe * 100, 2) for k, v in g.items()}
            if summe > 0 else {},
            "moeglich": bool(g) and not betroffen,
            "parteien_ohne_einheit": betroffen,
            # Damit sich in der Vorschau erklärt, warum eine Einheit mit
            # halbjährigem Leerstand zweimal auftaucht.
            "leerstand": [name for name in leer if name in g],
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
