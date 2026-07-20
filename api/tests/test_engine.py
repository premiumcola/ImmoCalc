"""Tests der Rechen-Engine gegen die echten Excel-Zahlen (KostenSPLIT 2024 etc.)."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app.engine import (interpoliere_verbrauch, rest_verbrauch,
                        verteile_nach_wert, abrechnung, Position)


def test_interpolation_laufer_gesamtwasser():
    # Ist 781 am 11.10.2024, Vorjahr 634.1256; 376 Ist-Tage -> 365 Soll-Tage
    v = interpoliere_verbrauch(634.1256, 781.0, 376, 365)
    assert abs(v - 142.577) < 0.01


def test_rest_zaehler_wg_wasser():
    # WG hat keinen Zähler: Rest = Gesamt - gemessene Unterzähler
    rest = rest_verbrauch(142.5774, [4.1398, 29.8316, 8.7856, 5.6844, 15.0])
    assert abs(rest - 79.14) < 0.02


def test_wasser_verteilung_summiert_auf_gesamtkosten():
    # 847.52 EUR Wasser über die interpolierten Verbräuche verteilt
    anteile = {"Buero": 4.1398, "RundA": 59.3016, "WG": 79.136}
    v = verteile_nach_wert(847.52, anteile)
    assert abs(sum(v.values()) - 847.52) < 1e-6          # Invariante: Summe = Gesamt
    assert abs(v["Buero"] - 24.61) < 0.05                 # Büro-Anteil ~ Sheet


def test_bewohnermonate_wg_drittel():
    # WG = 12 von 36 Bewohnermonaten -> 1/3 der umgelegten Kosten
    v = verteile_nach_wert(900.0, {"WG": 12, "RundA": 12, "Buero": 12})
    assert abs(v["WG"] - 300.0) < 1e-6


def test_einhorn_abrechnung_nachzahlung():
    # Objekt Wohnung 2024: Kosten 3121.33, Vorauszahlung 12x220 = 2640
    pos = [Position("Gesamt", 3121.33, "individuell", {"Wohnung": 1.0})]
    res = abrechnung(pos, {"Wohnung": 2640.0})
    assert res["parteien"]["Wohnung"]["saldo"] == -481.33
    assert res["gesamt"]["saldo"] == -481.33


def test_s35_summe_wird_ausgewiesen():
    pos = [
        Position("Hausmeister", 722.43, "individuell", {"Wohnung": 1.0}, s35=True),
        Position("Müll", 152.14, "individuell", {"Wohnung": 1.0}, s35=False),
    ]
    res = abrechnung(pos, {"Wohnung": 0.0})
    assert res["parteien"]["Wohnung"]["s35"] == 722.43
