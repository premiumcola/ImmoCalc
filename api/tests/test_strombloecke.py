"""N124 — Verteilung der Stromkosten aus zwei Blöcken.

Referenzzahlen aus NK-ALL-Strom-Verbrauch.xlsx, Blatt „Gesamtstrom", Zeilen
4–11 (Spalte D, Zeitraum 01.10.24 bis 30.04.26):

    Zukauf - €                   D4  = 862,51
    ct/kWh                       D5  = 27,38
    Grundpreis je Monat          D6  = 16,78
    Zukauf - kWh - Summe Jahr    D8  = 2416
    Durchschnittspreis           D11 = D4 / D8 = 0,357

Der Durchschnittspreis ist ausdrücklich Betrag durch Menge — die Umlage des
Grundpreises auf ct/kWh (D7) braucht die Verteilung nicht.
"""
from app.strombloecke import Block, verteile


def test_durchschnittspreis_ist_betrag_je_menge():
    """D11 der Excel: 862,51 € / 2416 kWh = 0,357 €/kWh."""
    extern = Block(kwh=2416.0, betrag=862.51)
    assert abs(extern.preis - 862.51 / 2416) < 1e-12
    assert round(extern.preis, 3) == 0.357


def test_jede_einheit_traegt_denselben_mischpreis():
    """„Jeder kriegt den gleichen Anteil von beiden Blöcken" — also zahlen alle
    denselben €/kWh, unabhängig von ihrer Größe."""
    extern = Block(kwh=2400.0, betrag=862.51)   # 0,3594 €/kWh
    eigen = Block(kwh=3600.0, betrag=1188.00)   # 0,3300 €/kWh
    e = verteile(extern, eigen, {"EG": 1000.0, "OG": 3000.0, "Büro": 2000.0})

    assert e.gesamt == round(862.51 + 1188.00, 2)
    # Gleicher Mischpreis fuer alle — bis auf die Cent-Rundung: die Verteilung
    # kann nur ganze Cent vergeben, der Rest landet nach Groesste-Reste bei
    # einer Einheit. Die Abweichung bleibt damit unter einem Cent je Einheit.
    verbrauch = {"EG": 1000.0, "OG": 3000.0, "Büro": 2000.0}
    preise = {n: e.kosten[n] / verbrauch[n] for n in verbrauch}
    schnitt = (862.51 + 1188.00) / 6000.0
    for name, preis in preise.items():
        assert abs(preis - schnitt) * verbrauch[name] < 0.01, (name, preis)
    # Und jede Einheit bekommt anteilig aus BEIDEN Töpfen.
    assert abs(e.extern_kwh["EG"] - 400.0) < 1e-6
    assert abs(e.eigen_kwh["EG"] - 600.0) < 1e-6


def test_summe_ist_cent_genau_der_gesamtbetrag():
    """Krumme Verbräuche dürfen keinen Cent verlieren."""
    extern = Block(kwh=2416.0, betrag=862.51)
    eigen = Block(kwh=4618.045, betrag=1523.95)
    e = verteile(extern, eigen,
                 {"EG": 1234.567, "OG": 2345.678, "Büro": 987.65, "Studio": 3.21})
    assert e.gesamt == round(862.51 + 1523.95, 2)
    assert round(sum(e.kosten.values()), 2) == e.gesamt


def test_eauto_wird_vorab_mit_seinen_exakten_mengen_verrechnet():
    """Für die Ladungen ist bekannt, wie viel aus dem Netz und wie viel aus der
    Anlage kam — das wird zuerst herausgerechnet, der Rest anteilig verteilt."""
    extern = Block(kwh=2000.0, betrag=700.00)   # 0,35 €/kWh
    eigen = Block(kwh=3000.0, betrag=900.00)    # 0,30 €/kWh
    e = verteile(extern, eigen,
                 {"EG": 1000.0, "OG": 1000.0, "E-Auto": 1000.0},
                 eauto_einheit="E-Auto",
                 eauto_extern_kwh=600.0, eauto_eigen_kwh=400.0)

    # Exakt bepreist: 600 × 0,35 + 400 × 0,30 = 210 + 120 = 330 €
    assert e.kosten["E-Auto"] == 330.00
    assert e.eauto["extern_kwh"] == 600.0
    # Der Rest (1400 extern, 2600 eigen) geht je zur Haelfte an EG und OG.
    assert abs(e.extern_kwh["EG"] - 700.0) < 1e-6
    assert abs(e.eigen_kwh["EG"] - 1300.0) < 1e-6
    assert e.kosten["EG"] == e.kosten["OG"]
    assert e.gesamt == 1600.00


def test_eauto_teurer_als_der_schnitt_belastet_die_anderen_nicht():
    """Laedt das E-Auto ueberwiegend aus dem Netz, traegt es diesen Aufschlag
    selbst — die uebrigen Einheiten zahlen den guenstigeren Rest-Mischpreis."""
    extern = Block(kwh=1000.0, betrag=400.00)   # 0,40 €/kWh
    eigen = Block(kwh=1000.0, betrag=200.00)    # 0,20 €/kWh
    ohne = verteile(extern, eigen, {"EG": 1000.0, "OG": 1000.0})
    mit = verteile(extern, eigen, {"EG": 500.0, "OG": 500.0, "E-Auto": 1000.0},
                   eauto_einheit="E-Auto",
                   eauto_extern_kwh=900.0, eauto_eigen_kwh=100.0)
    assert mit.kosten["E-Auto"] == 380.00          # 900×0,40 + 100×0,20
    assert mit.kosten["EG"] == mit.kosten["OG"] == 110.00   # (100×0,40 + 900×0,20)/2
    assert mit.gesamt == ohne.gesamt == 600.00


def test_unplausible_eauto_mengen_werden_gemeldet_nicht_gerechnet():
    extern = Block(kwh=100.0, betrag=40.00)
    eigen = Block(kwh=100.0, betrag=20.00)
    e = verteile(extern, eigen, {"EG": 100.0, "E-Auto": 500.0},
                 eauto_einheit="E-Auto",
                 eauto_extern_kwh=500.0, eauto_eigen_kwh=0.0)
    assert e.warnungen and "übersteigen" in e.warnungen[0]
    assert e.gesamt == 60.00          # trotzdem vollstaendig verteilt


def test_strom_ohne_zuordnung_warnt_statt_zu_verschwinden():
    e = verteile(Block(kwh=100.0, betrag=40.0), Block(), {})
    assert e.warnungen and "keine Einheit" in e.warnungen[0]


def test_eigenverbrauchsquote():
    e = verteile(Block(kwh=2416.0, betrag=862.51),
                 Block(kwh=4618.045, betrag=1523.95), {"EG": 100.0})
    assert e.eigenverbrauchsquote == round(4618.045 / (2416.0 + 4618.045), 4)
