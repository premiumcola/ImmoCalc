"""N80/N81 — Wärme aus Heizöl aufteilen und die Heizungswärme verteilen.

Zwei reine, testbare Rechenschritte der Heizkostenabrechnung:

**N80 — Warmwasser- gegen Heizungs-Wärme (§9 HeizkostenV).**
Bei einer gemeinsamen Anlage (ein Öltank heizt Wohnung *und* Warmwasser) muss
der Öl-Kostenanteil, der aufs Warmwasser entfällt, herausgerechnet werden. Der
Standardweg des § 9 HeizkostenV: die für das Warmwasser aufgewendete Wärmemenge
aus dem gemessenen Warmwasser-Volumen bestimmen und die Öl-Kosten proportional
zur Energie splitten.

**N81 — Heizungswärme über Heizkostenverteiler (HKV).**
Der Heizungs-Anteil wird je Einheit über die abgelesenen HKV-Einheiten verteilt:
pro Heizkörper Faktor × abgelesene Einheiten = gewichtete Einheiten, Summe je
Einheit → Kostenanteil (cent-genau wie der Abrechnungsdienst).

Der Modul ist rein: er kennt keine Datenbank, sondern rechnet auf Zahlen bzw.
auf einer Liste von HKV-Datensätzen. Ein HKV-Datensatz ist alles, was `einheit`,
`faktor` und `einheiten_stand` als Attribut ODER als dict-Schlüssel trägt — so
funktionieren Modell-Instanzen (`models.Heizverteiler`) und Testobjekte gleich.
"""
from __future__ import annotations

import logging
from typing import Any

from .engine import verteile_nach_wert

log = logging.getLogger("immocalc")

# §9 HeizkostenV: Q = 2,5 · V · (t_ww − 10) [kWh], mit V in m³ und t in °C.
# Der Faktor 2,5 kWh/(m³·K) fasst die spezifische Wärmekapazität des Wassers
# zusammen; 10 °C ist die angenommene Kaltwasser-Zulauftemperatur.
_WW_FAKTOR = 2.5
_KALTWASSER_C = 10.0
# Heizwert Heizöl EL: rund 10 kWh je Liter. N373 — dieselbe physikalische
# Größe stand dreimal im Baum (hier, `waermesim` als Vorgabewert,
# `routers/waerme` als Query-Default). Öffentlich, damit die beiden anderen
# sie holen statt sie zu wiederholen: ein korrigierter Heizwert muss überall
# gleichzeitig gelten, sonst rechnen Simulator und echte Abrechnung
# auseinander.
HEIZWERT_OEL = 10.0
_HEIZWERT_OEL = HEIZWERT_OEL


def warmwasser_kwh(volumen_m3: float, temp_c: float = 60.0) -> float:
    """Wärmemenge zur Erwärmung des Warmwassers in kWh (§9 HeizkostenV).

    Q = 2,5 · V · (t − 10), mit V in m³ und der Warmwassertemperatur t in °C
    (Standard 60 °C). Negatives oder unsinniges Volumen ergibt 0."""
    v = max(0.0, float(volumen_m3 or 0))
    t = float(temp_c if temp_c is not None else 60.0)
    q = _WW_FAKTOR * v * (t - _KALTWASSER_C)
    return round(max(0.0, q), 3)


def oel_kwh(liter: float, heizwert_kwh_pro_l: float = _HEIZWERT_OEL) -> float:
    """Energiegehalt einer Ölmenge in kWh = Liter × Heizwert (Standard 10 kWh/L)."""
    l = max(0.0, float(liter or 0))
    hw = float(heizwert_kwh_pro_l if heizwert_kwh_pro_l is not None else _HEIZWERT_OEL)
    return round(l * hw, 3)


def split_oel(oel_kosten: float, oel_liter: float, ww_volumen_m3: float,
              temp_c: float = 60.0, heizwert: float = _HEIZWERT_OEL) -> dict:
    """Öl-Kosten in Warmwasser- und Heizungs-Anteil splitten (§9 HeizkostenV).

    Die Warmwasser-Wärmemenge (`warmwasser_kwh`) wird ins Verhältnis zur
    gesamten Öl-Energie (`oel_kwh`) gesetzt; die Öl-Kosten teilen sich
    proportional zu dieser Energie.

    Rückgabe (dict):
      * `ww_kwh`         — Warmwasser-Wärmemenge in kWh.
      * `gesamt_kwh`     — Gesamt-Öl-Energie in kWh (= oel_kwh).
      * `ww_anteil`      — Anteil der Warmwasser-Energie (0…1, gedeckelt ≤ 1).
      * `ww_kosten`      — Öl-Kostenanteil Warmwasser in € (2 Stellen).
      * `heizung_kosten` — Rest = oel_kosten − ww_kosten in € (2 Stellen).
      * `warnung`        — nur gesetzt, wenn die Warmwasser-Energie die
                           Gesamtenergie übersteigt (Anteil auf 1 gedeckelt).

    Cent-sauber: `ww_kosten + heizung_kosten == round(oel_kosten, 2)`; der
    Heizungs-Anteil bekommt den Rundungsrest.

    Randfälle: gesamt_kwh 0 (kein Öl) → alles Heizung, `ww_anteil` 0.
    Übersteigt die Warmwasser-Energie die Gesamtenergie, wird der Anteil auf 1
    gedeckelt (alles Warmwasser) und eine `warnung` gesetzt."""
    kosten = round(float(oel_kosten or 0), 2)
    ww = warmwasser_kwh(ww_volumen_m3, temp_c)
    gesamt = oel_kwh(oel_liter, heizwert)

    ergebnis: dict = {"ww_kwh": ww, "gesamt_kwh": gesamt}

    if gesamt <= 0:
        # Kein Öl (keine Energie) → nichts zum Aufteilen: alles Heizung.
        ergebnis.update({"ww_anteil": 0.0, "ww_kosten": 0.0,
                         "heizung_kosten": kosten})
        return ergebnis

    anteil_roh = ww / gesamt
    if anteil_roh > 1.0:
        # Mehr Warmwasser-Energie als überhaupt Öl-Energie da ist: gedeckelt,
        # damit der Heizungs-Anteil nie negativ wird. Ein Hinweis, dass die
        # Eingaben (Volumen/Temperatur/Liter) zu prüfen sind.
        ueberschuss = round((ww - gesamt), 1)
        ergebnis["warnung"] = (
            f"Warmwasser-Wärme übersteigt Öl-Energie um {ueberschuss:g} kWh — "
            "Anteil auf 100 % gedeckelt")
        anteil = 1.0
    else:
        anteil = anteil_roh

    ww_kosten = round(kosten * anteil, 2)
    heizung_kosten = round(kosten - ww_kosten, 2)   # Rest → Cent-Summe stimmt
    ergebnis.update({
        "ww_anteil": round(anteil, 6),
        "ww_kosten": ww_kosten,
        "heizung_kosten": heizung_kosten,
    })
    return ergebnis


def _feld(hkv: Any, name: str, vorgabe: Any = None) -> Any:
    """Liest ein Feld aus Attribut oder dict-Schlüssel — je nachdem, was da ist."""
    if isinstance(hkv, dict):
        return hkv.get(name, vorgabe)
    return getattr(hkv, name, vorgabe)


def verteile_heizung(hkv: list, kosten: float) -> dict[str, float]:
    """Heizungs-Kosten je Einheit über die HKV-Faktoren verteilen (N81).

    Je Heizkörper ist das Gewicht `faktor × einheiten_stand` (gewichtete
    Einheiten); die Gewichte werden je `einheit` summiert und die `kosten`
    proportional verteilt (cent-genau, `verteile_nach_wert`).

    Rückgabe: {Einheit: Kostenanteil}. Invariante:
    `sum(...) == round(kosten, 2)`. Ohne positive Gewichte (keine Ablesung /
    Faktor 0) ist keine sinnvolle Verteilung möglich → leeres dict."""
    gewichte: dict[str, float] = {}
    for h in hkv:
        einheit = str(_feld(h, "einheit", "") or "").strip()
        if not einheit:
            continue
        try:
            faktor = float(_feld(h, "faktor", 1.0) or 0)
            stand = float(_feld(h, "einheiten_stand", 0.0) or 0)
        except (ValueError, TypeError):
            continue
        gewicht = faktor * stand
        if gewicht <= 0:
            continue
        gewichte[einheit] = gewichte.get(einheit, 0.0) + gewicht

    if not gewichte:
        return {}
    return verteile_nach_wert(kosten, gewichte)
