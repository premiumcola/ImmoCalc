"""N124 — Stromkosten aus zwei Blöcken auf die Einheiten verteilen.

Strom kommt aus zwei Töpfen mit verschiedenen Preisen:

* **extern** — beim Versorger zugekauft, teurer. Menge und Betrag stehen auf
  der Rechnung; der Preis je kWh ist schlicht ``betrag / menge`` (die Umlage
  des Grundpreises auf ct/kWh braucht es dafür nicht).
* **eigen** — aus der eigenen PV-Anlage, günstiger. Ob der Strom direkt vom
  Dach oder aus dem Akku kam, spielt für die Abrechnung keine Rolle.

Verteilt wird in zwei Schritten:

1. **Das E-Auto zuerst.** Für die Ladungen ist taggenau bekannt, wie viel davon
   aus dem Netz und wie viel aus der Anlage kam. Diese Mengen werden vorab aus
   beiden Blöcken herausgenommen und exakt bepreist.
2. **Der Rest anteilig.** Was übrig bleibt, wird nach Verbrauch verteilt —
   jede Einheit trägt denselben Anteil an *beiden* Blöcken und zahlt damit
   denselben Mischpreis. Niemand bekommt „nur den teuren" Strom.

Cent-genau über :func:`engine.verteile_nach_wert`: die Summe der Anteile ist
exakt der Gesamtbetrag.
"""
from dataclasses import dataclass, field

from . import engine


@dataclass
class Block:
    """Ein Kostenblock: wie viel kWh zu wie viel Euro."""
    kwh: float = 0.0
    betrag: float = 0.0

    @property
    def preis(self) -> float:
        """€ je kWh — der Durchschnittspreis dieses Blocks."""
        return (self.betrag / self.kwh) if self.kwh else 0.0


@dataclass
class Ergebnis:
    kosten: dict[str, float] = field(default_factory=dict)
    extern_kwh: dict[str, float] = field(default_factory=dict)
    eigen_kwh: dict[str, float] = field(default_factory=dict)
    eauto: dict[str, float] = field(default_factory=dict)
    gesamt: float = 0.0
    eigenverbrauchsquote: float = 0.0
    warnungen: list[str] = field(default_factory=list)


def verteile(extern: Block, eigen: Block, verbrauch: dict[str, float],
             eauto_einheit: str = "", eauto_extern_kwh: float = 0.0,
             eauto_eigen_kwh: float = 0.0) -> Ergebnis:
    """Die Kosten beider Blöcke auf die Einheiten verteilen.

    `verbrauch` ist der kWh-Verbrauch je Einheit aus den Zählern — beim E-Auto
    ist das die Summe seiner Ladungen. Ist eine E-Auto-Einheit genannt, wird
    sie mit ihren exakten Mengen vorab bedient und nimmt an der anteiligen
    Verteilung nicht mehr teil.
    """
    e = Ergebnis()
    if extern.kwh < 0 or eigen.kwh < 0:
        e.warnungen.append("Negative Strommenge — bitte die Rechnung prüfen.")
        return e

    rest_extern, rest_eigen = extern.kwh, eigen.kwh
    offen = dict(verbrauch)

    # ---- Schritt 1: das E-Auto mit seiner bekannten Aufteilung -------------
    if eauto_einheit:
        if eauto_extern_kwh > extern.kwh + 1e-9 or eauto_eigen_kwh > eigen.kwh + 1e-9:
            e.warnungen.append(
                f"Die Ladungen von „{eauto_einheit}“ übersteigen die erfasste "
                "Strommenge — die Vorab-Verrechnung wurde ausgelassen.")
        else:
            betrag = round(eauto_extern_kwh * extern.preis
                           + eauto_eigen_kwh * eigen.preis, 2)
            e.kosten[eauto_einheit] = betrag
            e.extern_kwh[eauto_einheit] = round(eauto_extern_kwh, 3)
            e.eigen_kwh[eauto_einheit] = round(eauto_eigen_kwh, 3)
            e.eauto = {"einheit": eauto_einheit, "betrag": betrag,
                       "extern_kwh": round(eauto_extern_kwh, 3),
                       "eigen_kwh": round(eauto_eigen_kwh, 3)}
            rest_extern -= eauto_extern_kwh
            rest_eigen -= eauto_eigen_kwh
            offen.pop(eauto_einheit, None)

    # ---- Schritt 2: der Rest nach Verbrauch, beide Blöcke gleichermaßen ----
    summe = sum(v for v in offen.values() if v and v > 0)
    rest_betrag = round(rest_extern * extern.preis + rest_eigen * eigen.preis, 2)
    if summe > 0:
        anteile = engine.verteile_nach_wert(
            rest_betrag, {n: v for n, v in offen.items() if v and v > 0})
        for name, betrag in anteile.items():
            e.kosten[name] = round(e.kosten.get(name, 0.0) + betrag, 2)
            quote = offen[name] / summe
            e.extern_kwh[name] = round(rest_extern * quote, 3)
            e.eigen_kwh[name] = round(rest_eigen * quote, 3)
    elif rest_betrag > 0.005:
        e.warnungen.append(
            "Es bleibt Strom übrig, dem keine Einheit zugeordnet ist — die "
            "Zuordnung bitte an den Zählern nachtragen.")

    e.gesamt = round(sum(e.kosten.values()), 2)
    gesamt_kwh = extern.kwh + eigen.kwh
    e.eigenverbrauchsquote = round(eigen.kwh / gesamt_kwh, 4) if gesamt_kwh else 0.0
    return e
