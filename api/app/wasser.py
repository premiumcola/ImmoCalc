"""N47 — Wasser-Verrechnung: drei Kostenbestandteile über Zähler auf die
Einheiten, Rest per Personen/Mietdauer aufs Haupthaus.

Genau nach der Excel `KostenSPLIT` (Laufer Str. 5):

* Eine Wasserrechnung hat DREI Bestandteile: Frischwasser, Schmutzwasser
  (Abwasser) und Niederschlagswasser. Ihre Summe sind die Gesamtkosten.
* Der **Preis je m³** ergibt sich aus Gesamtkosten ÷ Gesamtverbrauch
  (Hauptzähler-Differenz). Alles wird mit diesem einen Preis gerechnet.
* Jeder **Unterzähler** (Büro, Studio Kalt/Waschmaschine/Warm, je Einheit eine
  eigene Waschmaschine) wird m³ × Preis der zugehörigen Einheit direkt
  zugeordnet — verbrauchsscharf abgegrenzt.
* **Gartenwasser** (manuell in m³) wird als Menge aus dem Rest herausgenommen;
  seine Kosten trägt der Eigentümer, nicht die Mieter.
* Der **Rest** (Gesamt − alle Zähler − Garten) ist der gemeinsame Verbrauch des
  Haupthauses (EG + 1. OG, Kalt + Warm ohne eigenen Zähler). Er wird per
  Gewicht (Personen × Mietdauer im Zeitraum) auf die Haupthaus-Einheiten
  verteilt. Jede Einheit zahlt zusätzlich ihre eigene Waschmaschine.

Reine Rechenfunktion, keine DB — der Aufrufer sammelt Zählerstände und
Kostenbestandteile und reicht sie herein.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Zaehlerposten:
    """Ein Unterzähler, der einer Einheit direkt zugeordnet ist."""
    name: str
    einheit: str          # Ziel-Einheit (Bezeichnung/Slug), z. B. "Büro"
    m3: float             # verbrauchte Menge (Ablesung Ende − Anfang)


@dataclass
class WasserErgebnis:
    gesamt_kosten: float
    gesamt_m3: float
    preis_m3: float
    garten_m3: float
    garten_kosten: float          # trägt der Eigentümer
    rest_m3: float
    rest_kosten: float            # gemeinsamer Haupthaus-Verbrauch
    zaehler: list[dict] = field(default_factory=list)   # je Unterzähler
    einheiten: dict[str, dict] = field(default_factory=dict)  # je Einheit die Summe
    kontrolle: float = 0.0        # Summe aller verteilten € (muss ≈ gesamt_kosten)


def _r2(x: float) -> float:
    return round(x + 1e-9, 2)


def verrechne(komponenten: dict[str, float], gesamt_m3: float,
              zaehler: list[Zaehlerposten], garten_m3: float,
              rest_gewichte: dict[str, float]) -> WasserErgebnis:
    """Rechnet die Wasserverrechnung.

    `komponenten`  z. B. {"wasser": 298.05, "schmutz": 362.56, "niederschlag": 186.91}
    `gesamt_m3`    Hauptzähler-Differenz (Gesamtverbrauch).
    `zaehler`      Unterzähler mit Ziel-Einheit.
    `garten_m3`    Gartenwasser (manuell), Menge aus dem Rest heraus.
    `rest_gewichte`  {Einheit: Gewicht} für die Rest-Verteilung (Personen ×
                     Mietdauer) — nur die Haupthaus-Einheiten ohne eigenen
                     Vollzähler (EG, 1. OG).
    """
    gesamt_kosten = _r2(sum(komponenten.values()))
    if gesamt_m3 <= 0:
        raise ValueError("Gesamtverbrauch (Hauptzähler) muss > 0 sein")
    preis = gesamt_kosten / gesamt_m3

    zaehler_m3 = sum(max(0.0, z.m3) for z in zaehler)
    rest_m3 = gesamt_m3 - zaehler_m3 - max(0.0, garten_m3)
    rest_kosten = preis * rest_m3
    garten_kosten = preis * max(0.0, garten_m3)

    einheiten: dict[str, dict] = {}

    def zu_einheit(name: str, betrag: float, quelle: str, m3: float) -> None:
        e = einheiten.setdefault(name, {"kosten": 0.0, "posten": []})
        e["kosten"] += betrag
        e["posten"].append({"quelle": quelle, "m3": round(m3, 3),
                             "kosten": _r2(betrag)})

    zaehler_zeige = []
    for z in zaehler:
        betrag = preis * max(0.0, z.m3)
        zaehler_zeige.append({"name": z.name, "einheit": z.einheit,
                              "m3": round(z.m3, 3), "kosten": _r2(betrag)})
        zu_einheit(z.einheit, betrag, f"Zähler {z.name}", z.m3)

    # Rest per Gewicht auf die Haupthaus-Einheiten.
    gew_summe = sum(max(0.0, g) for g in rest_gewichte.values())
    if gew_summe > 0:
        for name, gew in rest_gewichte.items():
            anteil = max(0.0, gew) / gew_summe
            betrag = rest_kosten * anteil
            zu_einheit(name, betrag, "Anteil Haupthaus (Personen·Mietdauer)",
                       rest_m3 * anteil)

    for e in einheiten.values():
        e["kosten"] = _r2(e["kosten"])
    kontrolle = _r2(sum(e["kosten"] for e in einheiten.values()) + garten_kosten)

    return WasserErgebnis(
        gesamt_kosten=gesamt_kosten, gesamt_m3=round(gesamt_m3, 3),
        preis_m3=round(preis, 4), garten_m3=round(max(0.0, garten_m3), 3),
        garten_kosten=_r2(garten_kosten), rest_m3=round(rest_m3, 3),
        rest_kosten=_r2(rest_kosten), zaehler=zaehler_zeige,
        einheiten=einheiten, kontrolle=kontrolle)
