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

from .engine import verteile_nach_wert


@dataclass
class Zaehlerposten:
    """Ein Unterzähler, der einer oder mehreren Einheiten zugeordnet ist."""
    name: str
    einheit: str          # Ziel-Einheit (Bezeichnung/Slug), z. B. "Büro" — Fallback
    m3: float             # verbrauchte Menge (Ablesung Ende − Anfang)
    art: str = "Kaltwasser"   # Zeile im Popup: Kaltwasser|Warmwasser|Waschmaschine
    # CD — Mehrfachzuordnung: teilt dieser Zähler seinen Verbrauch/seine Kosten
    # unter mehreren Einheiten (Person·Mietdauer), stehen sie hier. Leer =
    # Einzelzuordnung über `einheit` (Fallback), Verhalten wie bisher.
    einheiten: list[str] = field(default_factory=list)

    def ziele(self) -> list[str]:
        """Die Einheiten, auf die dieser Posten aufgeteilt wird. Fällt auf den
        Einzelwert `einheit` zurück, wenn `einheiten` leer ist."""
        if self.einheiten:
            return list(self.einheiten)
        return [self.einheit] if self.einheit else []


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
    kontrolle: float = 0.0        # Summe aller verteilten € (== gesamt_kosten)
    # N118 — was der Nutzer wissen muss, bevor er die Zahlen verschickt:
    # unplausible Zählerstände (Unterzähler über dem Hauptzähler, Garten größer
    # als der Rest) oder ein Rest, den keine Einheit trägt. Leer = alles glatt.
    warnungen: list[str] = field(default_factory=list)


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
    # N107 - Gartenwasser wird NUR mit dem Frischwasser-Anteil belastet: es
    # versickert im Beet und laeuft weder in die Kanalisation (Schmutzwasser)
    # noch ueber die versiegelte Flaeche (Niederschlagswasser). Der volle
    # Mischpreis waere hier zu teuer. Ohne Frischwasser-Angabe (Altbestand)
    # bleibt es beim Mischpreis, damit die Kontrollsumme aufgeht.
    frisch = float(komponenten.get("wasser") or 0.0)
    preis_frisch = (frisch / gesamt_m3) if frisch > 0 else preis
    garten_kosten = _r2(preis_frisch * max(0.0, garten_m3))

    warnungen: list[str] = []
    einheiten: dict[str, dict] = {}

    def zu_einheit(name: str, betrag: float, quelle: str, m3: float) -> None:
        """Einen bereits auf Cent gerundeten Betrag einer Einheit gutschreiben.
        Nur gerundete Beträge summieren — dann stimmt die Summe der angezeigten
        Zeilen mit der angezeigten Einheitensumme überein."""
        e = einheiten.setdefault(name, {"kosten": 0.0, "posten": []})
        e["kosten"] = _r2(e["kosten"] + betrag)
        e["posten"].append({"quelle": quelle, "m3": round(m3, 3),
                            "kosten": betrag})

    zaehler_zeige = []
    verteilt = 0.0            # Summe aller schon vergebenen Zähler-Cent
    for z in zaehler:
        betrag = _r2(preis * max(0.0, z.m3))
        verteilt = _r2(verteilt + betrag)
        zaehler_zeige.append({"name": z.name, "einheit": z.einheit,
                              "m3": round(z.m3, 3), "kosten": betrag})
        ziele = z.ziele()
        if len(ziele) <= 1:
            # Einzelzuordnung (oder gar keine Einheit) — alles auf eine Einheit.
            name = ziele[0] if ziele else z.einheit
            zu_einheit(name, betrag, f"Zähler {z.name}", z.m3)
            continue
        # CD — Mehrfachzuordnung: m³ UND Kosten über die Einheiten dieses Zählers
        # nach Person·Mietdauer (dieselben `rest_gewichte`, beschränkt auf genau
        # diese Einheiten). Haben sie keine Gewichte, zu gleichen Teilen.
        gew = {name: max(0.0, rest_gewichte.get(name, 0.0)) for name in ziele}
        if sum(gew.values()) <= 0:
            gew = {name: 1.0 for name in ziele}
        summe_gew = sum(gew.values())
        # Cent-genau (Größte-Reste) statt je Einheit einzeln gerundet: sonst
        # fehlt oder entsteht bei jedem Zähler bis zu ein Cent.
        for name, teil in verteile_nach_wert(betrag, gew).items():
            zu_einheit(name, teil, f"Zähler {z.name}",
                       z.m3 * gew[name] / summe_gew)

    # Der Rest ist die Ausgleichsgröße: was nach Zählern und Garten von der
    # Rechnung übrig ist. Als Differenz gerechnet — nicht aus preis × m³ —,
    # damit Σ Einheiten + Garten auf den Cent genau die Gesamtkosten ergibt.
    # Darin steckt auch der Aufschlag, den das Gartenwasser weniger trägt
    # (N107: Garten zahlt nur Frischwasser, die Rechnung ist trotzdem fällig).
    rest_kosten = _r2(gesamt_kosten - garten_kosten - verteilt)

    if rest_m3 < 0 or rest_kosten < 0:
        # Unterzähler über dem Hauptzähler oder Garten größer als der Rest: die
        # Ablesungen passen nicht zusammen. Früher bekam eine Einheit dafür
        # stillschweigend einen Minusbetrag — das ist keine Abrechnung, sondern
        # ein Datenfehler, und er wird benannt statt verteilt.
        warnungen.append(
            f"Die Unterzähler und das Gartenwasser übersteigen den Hauptzähler "
            f"um {abs(round(rest_m3, 2)):g} m³ ({abs(rest_kosten):.2f} €). "
            "Bitte die Ablesungen prüfen — es wird kein negativer Anteil "
            "verteilt, deshalb geht die Kontrollsumme hier nicht auf.")
        rest_kosten = 0.0
        rest_m3 = 0.0

    # Rest per Gewicht auf die Haupthaus-Einheiten — ebenfalls cent-genau.
    gewichte = {name: max(0.0, g) for name, g in rest_gewichte.items()}
    gew_summe = sum(gewichte.values())
    if gew_summe > 0 and rest_kosten:
        for name, teil in verteile_nach_wert(rest_kosten, gewichte).items():
            zu_einheit(name, teil, "Anteil Haupthaus (Personen·Mietdauer)",
                       rest_m3 * gewichte[name] / gew_summe)
    elif rest_kosten:
        warnungen.append(
            f"{rest_kosten:.2f} € Restverbrauch lassen sich keiner Einheit "
            "zuordnen — es ist keine Einheit für den Rest hinterlegt.")

    kontrolle = _r2(sum(e["kosten"] for e in einheiten.values()) + garten_kosten)

    return WasserErgebnis(
        gesamt_kosten=gesamt_kosten, gesamt_m3=round(gesamt_m3, 3),
        preis_m3=round(preis, 4), garten_m3=round(max(0.0, garten_m3), 3),
        garten_kosten=garten_kosten, rest_m3=round(rest_m3, 3),
        rest_kosten=rest_kosten, zaehler=zaehler_zeige,
        einheiten=einheiten, kontrolle=kontrolle, warnungen=warnungen)
