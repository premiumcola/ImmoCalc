"""N409 (Aufgabe 1) — die reine Investment-Kennzahlen-Engine.

Keine Datenbank, kein TestClient: `kennzahlen()` ist eine reine Funktion und
wird hier direkt mit `KpiEingabe`/`KreditEingabe` geprüft. Der rote Faden
jedes Tests: fehlt eine Eingabe, ist die davon abhängige Kennzahl `None` —
nie eine erfundene 0."""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.investment_kpi import KpiEingabe, KreditEingabe, kennzahlen  # noqa: E402

STICHTAG = date(2026, 1, 1)


def _voll() -> KpiEingabe:
    """Ein vollständig ausgefülltes Beispiel — Basis für Tests, die nur ein
    Feld gezielt verändern wollen."""
    return KpiEingabe(
        stichtag=STICHTAG,
        kaufpreis=400_000, kaufdatum=date(2020, 1, 1),
        nebenkosten_grunderwerbsteuer=14_000, nebenkosten_notar=6_000,
        nebenkosten_makler=12_000,
        verkehrswert=480_000,
        wohnflaeche_qm=200, anzahl_einheiten=3,
        grundstuecksflaeche_qm=500, bodenrichtwert_eur_qm=300,
        gebaeudeanteil_pct_manuell=70, afa_satz_pct=2.0,
        grenzsteuersatz_pct=42,
        baukosten_eur_qm=2_000,
        verwaltung_jahr=1_200, mietausfallwagnis_pct=2.0,
        nicht_umlagefaehige_kosten_jahr=800,
        kaltmiete_jahr_ist=24_000,
        vergleichsmiete_eur_qm=11,
        kredite=[KreditEingabe(restschuld=280_000, zinssatz_pct=3.2,
                               rate_monatlich=1_400,
                               zinsbindung_bis=date(2031, 1, 1))],
        opportunitaetszins_pct=4.0,
    )


# ---------------------------------------------------------------- Basisfall
def test_vollstaendige_eingabe_ergibt_plausible_kennzahlen():
    r = kennzahlen(_voll())
    assert r["betriebsergebnis"]["noi"] == 14_020.0
    assert r["rendite"]["brutto_rendite_pct"] == 6.0
    assert r["finanzierung"]["ltv_pct"] == 58.33
    assert r["finanzierung"]["dscr_anwendbar"] is True
    assert r["cashflow"]["echtes_defizit_jahr"] is not None


# ------------------------------------------------------------ Fehlende Angaben
def test_komplett_leere_eingabe_liefert_ueberall_none():
    r = kennzahlen(KpiEingabe())
    assert r["betriebsergebnis"]["noi"] is None
    assert r["rendite"]["brutto_rendite_pct"] is None
    assert r["rendite"]["netto_rendite_pct"] is None
    assert r["finanzierung"]["dscr"] is None
    assert r["finanzierung"]["ltv_pct"] is None
    assert r["cashflow"]["cashflow_nach_steuer"] is None
    assert r["potenzial"]["break_even_wertsteigerung_pct"] is None


def test_fehlende_miete_laesst_noi_und_rendite_none_nicht_null():
    e = _voll()
    e.kaltmiete_jahr_ist = None
    r = kennzahlen(e)
    assert r["betriebsergebnis"]["noi"] is None
    assert r["rendite"]["brutto_rendite_pct"] is None
    # Die Beleihung braucht die Miete nicht und bleibt berechenbar.
    assert r["finanzierung"]["ltv_pct"] is not None


def test_fehlender_kaufpreis_laesst_bruttorendite_und_kaufpreisfaktor_none():
    e = _voll()
    e.kaufpreis = None
    r = kennzahlen(e)
    assert r["rendite"]["brutto_rendite_pct"] is None
    assert r["rendite"]["kaufpreisfaktor"] is None
    # Der Verkehrswert steht weiter zur Verfügung — LTV bleibt berechenbar.
    assert r["finanzierung"]["ltv_pct"] is not None


# ------------------------------------------------------------- Divisionsschutz
def test_null_miete_ist_kein_absturz_und_kein_kaufpreisfaktor():
    e = _voll()
    e.kaltmiete_jahr_ist = 0.0
    r = kennzahlen(e)
    assert r["rendite"]["brutto_rendite_pct"] == 0.0
    assert r["rendite"]["kaufpreisfaktor"] is None    # Division durch 0 vermieden


def test_null_verkehrswert_laesst_ltv_none():
    e = _voll()
    e.verkehrswert = 0.0
    r = kennzahlen(e)
    assert r["finanzierung"]["ltv_pct"] is None


def test_kredit_ohne_rate_hat_keinen_kapitaldienst():
    e = _voll()
    e.kredite = [KreditEingabe(restschuld=100_000, zinssatz_pct=3.0,
                               rate_monatlich=None)]
    r = kennzahlen(e)
    assert r["finanzierung"]["kapitaldienst_jahr"] is None
    assert r["finanzierung"]["dscr"] is None


# ------------------------------------------------------------- Kein Darlehen
def test_schuldenfreies_objekt_hat_ltv_null_und_dscr_nicht_anwendbar():
    """Ein Objekt ganz ohne Darlehen ist nicht „unendlich gut" — DSCR ist
    dann schlicht nicht anwendbar, nicht unendlich."""
    e = _voll()
    e.kredite = []
    r = kennzahlen(e)
    assert r["finanzierung"]["ltv_pct"] == 0.0
    assert r["finanzierung"]["dscr"] is None
    assert r["finanzierung"]["dscr_anwendbar"] is False
    # Der Leverage-Spread bleibt berechenbar: 0 % Fremdkapitalzins.
    assert r["finanzierung"]["zins_gewichtet_pct"] == 0.0
    assert r["finanzierung"]["leverage_spread_pp"] == r["rendite"]["netto_rendite_pct"]


def test_bausparvertrag_zaehlt_nicht_als_darlehen():
    e = _voll()
    e.kredite = [KreditEingabe(restschuld=50_000, zinssatz_pct=1.0,
                               rate_monatlich=300, ist_bausparvertrag=True)]
    r = kennzahlen(e)
    assert r["finanzierung"]["restschuld_gesamt"] == 0.0
    assert r["finanzierung"]["dscr_anwendbar"] is False


# --------------------------------------------------------------------- Vacancy
def test_leerstand_flag_wird_durchgereicht():
    e = _voll()
    e.hat_leerstand = True
    e.kaltmiete_jahr_leerstand_potenziell = 30_000
    r = kennzahlen(e)
    assert r["hat_leerstand"] is True


# ---------------------------------------------------------- Bodenrichtwert
def test_bodenrichtwert_ueber_kaufpreis_wird_nicht_gekappt():
    """Ein realistischer Fall bei großen Grundstücken: Bodenwert übersteigt
    den Kaufpreis. Kein stiller Deckel — ein Warn-Flag, weil das ein
    Wertgutachten für den AfA-Split nötig macht."""
    e = _voll()
    e.kaufpreis = 100_000
    e.bodenrichtwert_eur_qm = 500
    e.grundstuecksflaeche_qm = 1_000
    r = kennzahlen(e)
    assert r["bodenrichtwert"]["bodenwert"] == 500_000.0
    assert r["bodenrichtwert"]["warnung_ueber_kaufpreis"] is True


def test_bodenrichtwert_unter_kaufpreis_ohne_warnung():
    e = _voll()
    r = kennzahlen(e)
    assert r["bodenrichtwert"]["warnung_ueber_kaufpreis"] is False


# -------------------------------------------------------------- Tilgungsplan
def test_tilgungsplan_zins_und_tilgung_ergeben_die_rate():
    e = _voll()
    r = kennzahlen(e)
    plan = r["finanzierung"]["tilgungsplaene_je_kredit"][0]
    assert len(plan) > 0
    jahr1 = plan[0]
    # Zins + Tilgung im ersten Jahr ergibt (auf Rundung) die Jahresrate.
    assert abs((jahr1["zins"] + jahr1["tilgung"]) - 1_400 * 12) < 1.0
    # Die Restschuld sinkt monoton, so lange noch etwas offen ist.
    for a, b in zip(plan, plan[1:]):
        assert b["restschuld_jahresende"] <= a["restschuld_jahresende"]


def test_ohne_zinsbindung_kein_restschuld_zum_bindungsende():
    e = _voll()
    e.kredite[0].zinsbindung_bis = None
    r = kennzahlen(e)
    assert r["finanzierung"]["restschuld_bei_zinsbindungsende_je_kredit"] == {}


def test_naechste_zinsbindung_ist_die_fruehste_kuenftige():
    e = _voll()
    e.kredite = [
        KreditEingabe(restschuld=100_000, zinssatz_pct=3.0, rate_monatlich=500,
                     zinsbindung_bis=date(2033, 1, 1)),
        KreditEingabe(restschuld=50_000, zinssatz_pct=3.0, rate_monatlich=300,
                     zinsbindung_bis=date(2028, 6, 1)),
    ]
    r = kennzahlen(e)
    assert r["finanzierung"]["naechste_zinsbindung_bis"] == date(2028, 6, 1)


def test_ohne_zinsbindung_ist_naechste_zinsbindung_none():
    e = _voll()
    e.kredite[0].zinsbindung_bis = None
    r = kennzahlen(e)
    assert r["finanzierung"]["naechste_zinsbindung_bis"] is None


def test_restschuld_zum_bindungsende_liegt_unter_der_heutigen():
    e = _voll()
    r = kennzahlen(e)
    rs = r["finanzierung"]["restschuld_bei_zinsbindungsende_je_kredit"][0]
    assert 0 < rs < e.kredite[0].restschuld


# ------------------------------------------------------------------- Potenzial
def test_mietreserve_positiv_wenn_vergleichsmiete_hoeher():
    e = _voll()
    r = kennzahlen(e)
    # Vergleichsmiete 11 €/m², Ist 24000/12/200 = 10 €/m² -> Reserve > 0
    assert r["potenzial"]["mietreserve_jahr"] == 2_400.0


def test_kappungsgrenze_spielraum_ohne_daten_ist_none():
    e = _voll()
    r = kennzahlen(e)
    assert r["potenzial"]["kappungsgrenze_spielraum_jahr"] is None


def test_kappungsgrenze_spielraum_mit_daten():
    e = _voll()
    e.kappungsgrenze_prozent = 20.0
    e.basismiete_vor_3_jahren = 1_500.0
    e.aktuelle_kaltmiete_gesamt = 24_000.0
    r = kennzahlen(e)
    # Höchstmiete: 1500 * 1.20 * 12 = 21600 -> Spielraum negativ (Ist ist höher)
    assert r["potenzial"]["kappungsgrenze_hoechstmiete_jahr"] == 21_600.0
    assert r["potenzial"]["kappungsgrenze_spielraum_jahr"] == -2_400.0


def test_gfz_auslastung_ohne_angaben_ist_none():
    e = _voll()
    r = kennzahlen(e)
    assert r["potenzial"]["gfz_auslastung_pct"] is None


def test_gfz_auslastung_mit_angaben():
    e = _voll()
    e.bestehende_geschossflaeche_qm = 300
    e.zulaessige_geschossflaeche_qm = 500
    r = kennzahlen(e)
    assert r["potenzial"]["gfz_auslastung_pct"] == 60.0


# --------------------------------------------------------------- Leverage-Spread
def test_leverage_spread_ist_differenz_aus_rendite_und_zins():
    e = _voll()
    r = kennzahlen(e)
    netto = r["rendite"]["netto_rendite_pct"]
    zins = r["finanzierung"]["zins_gewichtet_pct"]
    assert r["finanzierung"]["leverage_spread_pp"] == round(netto - zins, 2)


def test_mehrere_kredite_gewichten_den_zinssatz_nach_restschuld():
    e = _voll()
    e.kredite = [
        KreditEingabe(restschuld=200_000, zinssatz_pct=2.0, rate_monatlich=900),
        KreditEingabe(restschuld=100_000, zinssatz_pct=5.0, rate_monatlich=700),
    ]
    r = kennzahlen(e)
    # (200000*2 + 100000*5) / 300000 = 3.0
    assert r["finanzierung"]["zins_gewichtet_pct"] == 3.0
