"""N146 — die PV-Anlage als Investment unter ihrer Immobilie.

Die Anlage hat eigene Anteile: sie kann anderen gehören als das Haus. Geprüft
wird hier die Rechenlogik in `app.vermoegen` — dass die Summe aufgeht, dass ein
Anteil ohne Person nicht lautlos verschwindet und dass die Anlage bei Beleihung
und Wertsteigerung ausdrücklich draußen bleibt.
"""
import json
import os
import sys
import tempfile
from datetime import date
from types import SimpleNamespace

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_vermoegen.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.vermoegen import (PV_VORGABE_ANTEILE, PV_WERTQUELLE,  # noqa: E402
                           objekt_vermoegen, pv_anteile, pv_wert,
                           pv_zurechnung, wertzuwachs_kennzahlen)

# Die echte Anlage an der Laufer Str. 5: 36.000 € Anschaffung, 19,44 kWp,
# 5/6 zu 1/6 auf zwei Personen — eine davon hält am Gebäude selbst nichts.
LAUFER = SimpleNamespace(
    anschaffung_eur=36000.0, kwp=19.44,
    anteile=json.dumps({"Katja & Roland Heidenreich": 833.3333,
                        "Roman Heidenreich": 166.6666}))
PERSONEN = {3: "Katja & Roland Heidenreich", 2: "Roman Heidenreich"}


def _anlage(anteile=None, anschaffung=36000.0, kwp=19.44):
    return SimpleNamespace(anschaffung_eur=anschaffung, kwp=kwp,
                           anteile=json.dumps(anteile) if anteile else "")


# ---- Anteile lesen -------------------------------------------------------

def test_gepflegte_anteile_gelten():
    assert pv_anteile(LAUFER.anteile) == {"Katja & Roland Heidenreich": 833.3333,
                                          "Roman Heidenreich": 166.6666}


def test_ohne_anteile_gilt_die_vorgabe_fuenf_sechstel():
    """Ist nichts gepflegt, gilt die bisherige Vorgabe 5/6 zu 1/6 — als
    833,3 ‰ / 166,7 ‰, aber eben nur als Vorgabe."""
    assert pv_anteile("") == PV_VORGABE_ANTEILE
    assert pv_anteile(None) == {"5/6": 833.3, "1/6": 166.7}
    assert pv_anteile("{kaputt") == PV_VORGABE_ANTEILE


def test_wert_der_anlage_ist_die_anschaffung():
    assert pv_wert(LAUFER) == 36000.0
    assert pv_wert(_anlage(anschaffung=0)) is None


# ---- Zurechnung ----------------------------------------------------------

def test_anteile_summieren_sich_auf_den_anlagenwert():
    """Die wichtigste Zusicherung: über alle Personen kommt exakt der
    Anlagenwert heraus — kein Cent verschwindet, keiner entsteht."""
    z = pv_zurechnung(LAUFER, PERSONEN)
    assert z["wert"] == 36000.0
    assert z["wertquelle"] == PV_WERTQUELLE == "Anschaffungswert"
    assert round(sum(t["wert"] for t in z["je_person"].values()), 2) == 36000.0
    assert z["je_person"][3]["wert"] == 30000.0
    assert z["je_person"][2]["wert"] == 6000.0
    assert z["hinweise"] == []


def test_drittel_geht_ohne_rundungsverlust_auf():
    """333,3 dreimal ergibt 999,9 ‰ und 30.000 € — nicht 29.999,99 €."""
    z = pv_zurechnung(
        _anlage({"A": 333.3, "B": 333.3, "C": 333.3}, anschaffung=30000.0),
        {1: "A", 2: "B", 3: "C"})
    assert round(sum(t["wert"] for t in z["je_person"].values()), 2) == 30000.0
    assert z["hinweise"] == []                  # 999,9 ‰ liegt in der Toleranz


def test_anteile_ungleich_tausend_werden_proportional_gerechnet():
    """Der Nutzer pflegt von Hand — 900 ‰ sind möglich. Dann wird proportional
    gerechnet und darauf hingewiesen, statt zu sperren."""
    z = pv_zurechnung(_anlage({"A": 600, "B": 300}, anschaffung=9000.0),
                      {1: "A", 2: "B"})
    assert z["anteile_summe"] == 900.0
    assert z["je_person"][1]["wert"] == 6000.0
    assert z["je_person"][2]["wert"] == 3000.0
    assert round(sum(t["wert"] for t in z["je_person"].values()), 2) == 9000.0
    assert any("900 ‰ statt 1000 ‰" in h for h in z["hinweise"])


def test_name_ohne_person_verschwindet_nicht_lautlos():
    """Findet sich zu einem Namen kein Eigentümer, bleibt sein Anteil
    unzugeordnet — er wird nicht still auf die übrigen verteilt."""
    z = pv_zurechnung(_anlage({"Bekannt": 500, "Fremd": 500},
                              anschaffung=10000.0), {1: "Bekannt"})
    assert z["je_person"] == {1: {"promille": 500.0, "wert": 5000.0}}
    assert z["ohne_person"] == [{"name": "Fremd", "promille": 500.0}]
    assert any("Fremd" in h for h in z["hinweise"])
    # 5.000 € fallen niemandem zu — der andere bekommt nicht mehr als seine 500 ‰
    assert sum(t["wert"] for t in z["je_person"].values()) == 5000.0


def test_namen_werden_unabhaengig_von_schreibweise_zugeordnet():
    z = pv_zurechnung(_anlage({"  roman   heidenreich ": 1000.0},
                              anschaffung=5000.0), {2: "Roman Heidenreich"})
    assert z["je_person"][2]["wert"] == 5000.0
    assert z["ohne_person"] == []


def test_ohne_gepflegte_anteile_bleibt_die_vorgabe_unzugeordnet():
    """Die Vorgabe 5/6 zu 1/6 trägt keine Personennamen. Sie einer Person
    zuzuschlagen wäre geraten — stattdessen steht ein Hinweis da."""
    z = pv_zurechnung(_anlage(), PERSONEN)
    assert z["je_person"] == {}
    assert z["vorgabe"] is True
    assert len(z["ohne_person"]) == 2
    assert any("noch keine Anteile gepflegt" in h for h in z["hinweise"])


def test_ohne_anlage_gibt_es_nichts_zuzurechnen():
    assert pv_zurechnung(None, PERSONEN) is None


def test_leerer_stammsatz_ist_keine_anlage():
    """Ein angelegter, aber nie gefüllter Satz behauptet keine Beteiligung."""
    assert pv_zurechnung(_anlage(anschaffung=0, kwp=0), PERSONEN) is None


# ---- Was die Anlage ausdrücklich NICHT verändert -------------------------

def test_beleihung_und_wertsteigerung_kennen_die_anlage_nicht():
    """Die Anlage ist ein Investment, keine beleihbare Immobilie: sie bleibt
    aus der Beleihungsquote und aus der Wertentwicklung heraus. Beides hängt
    allein am Objekt — `objekt_vermoegen` sieht die Anlage gar nicht."""
    objekt = SimpleNamespace(
        slug="laufer", name="Laufer Str. 5", ort="Eschenau",
        strasse="Laufer Str. 5", typ="lg-bauernhof", flurstueck="", gemarkung="",
        kaufpreis=400000.0, verkehrswert=500000.0, kaufdatum=date(2015, 1, 1),
        erwerbsart="kauf", ruecklage_saldo=None, ruecklage_monatlich=None,
        weg=False, hausgeld_monatlich=None)
    kredit = SimpleNamespace(id=1, objekt_id=1, restschuld=200000.0,
                             rate_monatlich=1000.0, turnus="monatlich",
                             zinssatz=2.0, zinsbindung_bis=None, angespart=0.0,
                             bausparsumme=None, art="darlehen")
    zeile = objekt_vermoegen(objekt, [kredit], stichtag=date(2025, 1, 1))
    # 200.000 von 500.000 — die 36.000 € der Anlage tauchen hier nirgends auf.
    assert zeile["beleihung"] == 40.0
    assert zeile["wert"] == 500000.0
    assert "pv" not in zeile
    kennzahlen = wertzuwachs_kennzahlen(400000.0, 500000.0, date(2015, 1, 1),
                                        stichtag=date(2025, 1, 1))
    assert zeile["wertzuwachs"] == kennzahlen["wertzuwachs"] == 100000.0
