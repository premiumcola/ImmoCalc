"""ImmoCalc Rechen-Engine — reine Funktionen, testbar gegen die Excel-Zahlen.

Deckt ab: Zähler-Interpolation auf den Soll-Stichtag, berechnete (virtuelle)
Zähler als Rest, Verteilung nach Wert/Gewicht (Verbrauch, Fläche, Personen,
Bewohnermonate, Einheiten, Prozent, individuell), Zeitanteiligkeit sowie die
Abrechnung je Partei inkl. §35a-Summe und Gesamtübersicht.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date


def interpoliere_verbrauch(stand_vorjahr: float, stand_ist: float,
                           tage_ist: int, tage_soll: int) -> float:
    """Ist-Ablesung linear auf den Soll-Stichtag hochrechnen.
    Bsp. Musterstraße Gesamtwasser 2024: (781 - 634.1256) über 376 Tage,
    gebraucht über 365 -> 142.577."""
    ist_diff = stand_ist - stand_vorjahr
    if tage_ist == 0:
        return 0.0
    return ist_diff * (tage_soll / tage_ist)


def rest_verbrauch(gesamt: float, gemessene: list[float]) -> float:
    """Berechneter/virtueller Zähler = Gesamt minus alle gemessenen Unterzähler
    (z.B. WG-Wasser bei Musterstraße, das keinen eigenen Zähler hat)."""
    return gesamt - sum(gemessene)


def tage(von: date, bis: date) -> int:
    return (bis - von).days


def zeitanteil(nutzung_von: date, nutzung_bis: date,
               zeitraum_von: date, zeitraum_bis: date) -> float:
    """Faktor 0..1 für taggenaue Kürzung, wenn die Nutzung den Zeitraum nicht
    voll abdeckt (Mieterwechsel, Rumpfzeitraum)."""
    span = tage(zeitraum_von, zeitraum_bis)
    if span <= 0:
        return 0.0
    start = max(nutzung_von, zeitraum_von)
    ende = min(nutzung_bis, zeitraum_bis)
    genutzt = max(0, tage(start, ende))
    return min(1.0, genutzt / span)


class NegativesGewicht(ValueError):
    """Ein Verteilungsgewicht ist kleiner als null — so lässt sich nicht teilen."""


def verteile_nach_wert(kosten: float, anteile: dict[str, float]) -> dict[str, float]:
    """Kosten proportional zu Gewichten aufteilen. Trägt jede Schlüsselart:
    Verbrauch (Zählerwerte), Fläche (m²), Personen, Bewohnermonate,
    Einheiten (gleiche Gewichte), Prozent (Prozentwerte), individuell (1 Partei).

    Gerundet wird auf Cent, und zwar nach dem Größte-Reste-Verfahren: der
    Rundungsrest geht an die Partei mit dem größten abgeschnittenen Anteil.
    Ohne das ergäben 100 € auf drei Parteien dreimal 33,33 € = 99,99 € — der
    fehlende Cent taucht dann in der Abrechnung als Differenz zwischen der
    Positionsliste und der Endsumme auf, und genau da schaut ein Mieter hin.

    Damit gilt die Invariante auch nach dem Runden:
    `sum(verteile_nach_wert(k, a).values()) == round(k, 2)`.
    """
    negativ = [k for k, v in anteile.items() if v < 0]
    if negativ:
        # Kann bei Zählerständen entstehen (Unterzähler über Hauptzähler).
        # Stillschweigend weiterrechnen hiesse: eine Partei bekommt Geld
        # zurück, die anderen zahlen zusammen mehr als die Gesamtkosten.
        raise NegativesGewicht(
            "Negatives Verteilungsgewicht bei: " + ", ".join(sorted(negativ)))

    summe = sum(anteile.values())
    if summe == 0:
        return {k: 0.0 for k in anteile}

    ziel = round(kosten * 100)                 # in Cent, damit exakt gerechnet wird
    roh = {k: kosten * 100 * v / summe for k, v in anteile.items()}
    cent = {k: int(w) for k, w in roh.items()}          # abschneiden, nicht runden
    rest = ziel - sum(cent.values())
    # Die Cents, die durch das Abschneiden übrig sind, gehen der Reihe nach an
    # die grössten Nachkommareste. Bei Gleichstand entscheidet der Name, damit
    # dieselbe Eingabe immer dasselbe Ergebnis liefert.
    reihenfolge = sorted(roh, key=lambda k: (-(roh[k] - cent[k]), k))
    for i in range(abs(rest)):
        k = reihenfolge[i % len(reihenfolge)]
        cent[k] += 1 if rest > 0 else -1
    return {k: c / 100 for k, c in cent.items()}


@dataclass
class Position:
    kostenart: str
    kosten: float
    schluessel: str                       # 'verbrauch'|'flaeche'|'bewohnermonate'|...
    anteile: dict[str, float]             # Partei -> Gewicht
    s35: bool = False                     # haushaltsnahe Dienstleistung (§35a)


def abrechnung(positionen: list[Position],
               vorauszahlungen: dict[str, float]) -> dict:
    """Alle Positionen auf die Parteien verteilen, Vorauszahlungen gegenrechnen.
    Liefert je Partei kosten/vorauszahlungen/saldo/s35 und eine Gesamtübersicht."""
    kosten_je: dict[str, float] = {}
    s35_je: dict[str, float] = {}
    einzeln: list[dict] = []
    for p in positionen:
        verteilung = verteile_nach_wert(p.kosten, p.anteile)
        einzeln.append({
            "kostenart": p.kostenart, "kosten": round(p.kosten, 2),
            "schluessel": p.schluessel, "s35": p.s35,
            "verteilung": {k: round(v, 2) for k, v in verteilung.items()},
        })
        for partei, betrag in verteilung.items():
            kosten_je[partei] = kosten_je.get(partei, 0.0) + betrag
            if p.s35:
                s35_je[partei] = s35_je.get(partei, 0.0) + betrag

    parteien = {}
    for partei, kosten in kosten_je.items():
        vz = vorauszahlungen.get(partei, 0.0)
        parteien[partei] = {
            "kosten": round(kosten, 2),
            "vorauszahlungen": round(vz, 2),
            "saldo": round(vz - kosten, 2),          # + = Guthaben, - = Nachzahlung
            "s35": round(s35_je.get(partei, 0.0), 2),
        }
    auslagen = sum(kosten_je.values())
    abschlaege = sum(vorauszahlungen.values())
    gesamt = {
        "auslagen": round(auslagen, 2),
        "abschlaege": round(abschlaege, 2),
        "saldo": round(abschlaege - auslagen, 2),
    }
    # `positionen` ist der Nachweis je Kostenart — die Anlage zur Abrechnung.
    return {"parteien": parteien, "gesamt": gesamt, "positionen": einzeln}
