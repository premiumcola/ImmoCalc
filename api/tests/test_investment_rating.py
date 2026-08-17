"""N409 (Aufgabe 2) — der Bewertungs-Layer über den KPIs: Ampel je Kennzahl,
Gesamtnote A–E mit Konfidenz, Potenzial getrennt von der Note."""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.investment_kpi import KpiEingabe, KreditEingabe, kennzahlen  # noqa: E402
from app.investment_rating import ampel, ampeln, bewertung  # noqa: E402


def _kennzahlen(**overrides) -> dict:
    basis = dict(
        kaufpreis=400_000, kaufdatum=date(2020, 1, 1), verkehrswert=480_000,
        wohnflaeche_qm=200, verwaltung_jahr=1_200, mietausfallwagnis_pct=2.0,
        nicht_umlagefaehige_kosten_jahr=800, baukosten_eur_qm=2_000,
        kaltmiete_jahr_ist=24_000, vergleichsmiete_eur_qm=11,
        kredite=[KreditEingabe(restschuld=280_000, zinssatz_pct=3.2,
                               rate_monatlich=1_400)],
        afa_satz_pct=2.0, gebaeudeanteil_pct_manuell=70, grenzsteuersatz_pct=42,
    )
    basis.update(overrides)
    return kennzahlen(KpiEingabe(**basis))


# ------------------------------------------------------------------- Ampel
def test_ampel_grenzwerte_leverage_spread():
    assert ampel("leverage_spread_pp", 1.5) == "gruen"
    assert ampel("leverage_spread_pp", 1.0) == "gruen"    # Grenze selbst zählt grün
    assert ampel("leverage_spread_pp", 0.5) == "gelb"
    assert ampel("leverage_spread_pp", 0.0) == "gelb"
    assert ampel("leverage_spread_pp", -0.1) == "rot"


def test_ampel_grenzwerte_ltv_ist_umgekehrt_gerichtet():
    """LTV: niedriger ist besser — Richtung „tief"."""
    assert ampel("ltv_pct", 40) == "gruen"
    assert ampel("ltv_pct", 60) == "gruen"
    assert ampel("ltv_pct", 70) == "gelb"
    assert ampel("ltv_pct", 85) == "rot"


def test_ampel_ohne_wert_ist_none():
    assert ampel("dscr", None) is None


def test_ampel_unbekannte_kennzahl_ist_none():
    assert ampel("nicht_definiert", 5.0) is None


def test_ampeln_deckt_alle_sechs_bewerteten_kennzahlen_ab():
    k = _kennzahlen()
    a = ampeln(k)
    assert set(a) == {"leverage_spread_pp", "dscr", "ltv_pct",
                      "netto_rendite_pct", "kaufpreisfaktor",
                      "echtes_defizit_monat"}


# ------------------------------------------------------------------- Note
def test_durchgehend_gute_kennzahlen_ergeben_note_a():
    k = _kennzahlen(kaufpreis=300_000, verkehrswert=350_000,
                    kaltmiete_jahr_ist=30_000,
                    kredite=[KreditEingabe(restschuld=100_000, zinssatz_pct=2.0,
                                           rate_monatlich=600)])
    b = bewertung(k)
    assert b["note"] == "A"
    assert b["note_anteil"] == 1.0


def test_durchgehend_schlechte_kennzahlen_ergeben_note_e():
    k = _kennzahlen(kaufpreis=500_000, verkehrswert=480_000,
                    kaltmiete_jahr_ist=12_000,
                    kredite=[KreditEingabe(restschuld=450_000, zinssatz_pct=5.5,
                                           rate_monatlich=2_000)])
    b = bewertung(k)
    assert b["note"] == "E"
    assert b["note_anteil"] == 0.0
    assert all(f == "rot" for f in b["ampeln"].values())


def test_ohne_jede_kennzahl_ist_die_note_none_nicht_e():
    """Fehlen ALLE Grundlagen, ist die Note unbekannt — nicht automatisch die
    schlechteste. `None` und „E" sind verschiedene Aussagen."""
    k = kennzahlen(KpiEingabe())
    b = bewertung(k)
    assert b["note"] is None
    assert b["konfidenz"] == 0.0
    assert len(b["fehlende_kennzahlen"]) == 6


# --------------------------------------------------------------- Konfidenz
def test_konfidenz_sinkt_mit_fehlenden_kennzahlen():
    voll = bewertung(_kennzahlen())
    # Ohne Steuerangaben fehlt „echtes Defizit" (Gewicht 2 von 13 gesamt).
    unvollstaendig = bewertung(_kennzahlen(afa_satz_pct=None,
                                           gebaeudeanteil_pct_manuell=None,
                                           grenzsteuersatz_pct=None))
    assert unvollstaendig["konfidenz"] < voll["konfidenz"]
    assert "echtes_defizit_monat" in unvollstaendig["fehlende_kennzahlen"]


def test_konfidenz_bei_vollstaendiger_eingabe_ist_eins():
    b = bewertung(_kennzahlen())
    assert b["konfidenz"] == 1.0
    assert b["fehlende_kennzahlen"] == []


# -------------------------------------------------------- Potenzial getrennt
def test_schlechte_note_kann_trotzdem_potenzial_haben():
    """Der Kernfall aus der Spezifikation: schlechte laufende Zahlen, aber
    eine Mietreserve — Note und Potenzial dürfen sich nicht gegenseitig
    verschlucken."""
    k = _kennzahlen(kaufpreis=500_000, verkehrswert=480_000,
                    kaltmiete_jahr_ist=12_000, vergleichsmiete_eur_qm=15,
                    kredite=[KreditEingabe(restschuld=450_000, zinssatz_pct=5.5,
                                           rate_monatlich=2_000)])
    b = bewertung(k)
    assert b["note"] == "E"
    assert b["potenzial_vorhanden"] is True
    assert b["potenzial"]["mietreserve_jahr"] > 0


def test_kein_potenzial_ohne_reserve_kappung_oder_gfz():
    k = _kennzahlen(vergleichsmiete_eur_qm=None)
    b = bewertung(k)
    assert b["potenzial_vorhanden"] is False
