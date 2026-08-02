"""N124/N142 — Verteilung der Stromkosten aus drei Blöcken (Netz · PV · Akku).

Referenzzahlen aus NK-ALL-Strom-Verbrauch.xlsx, Blatt „Gesamtstrom", Zeilen
4–11 (Spalte D, Zeitraum 01.10.24 bis 30.04.26):

    Zukauf - €                   D4  = 862,51
    ct/kWh                       D5  = 27,38
    Grundpreis je Monat          D6  = 16,78
    Zukauf - kWh - Summe Jahr    D8  = 2416
    Durchschnittspreis           D11 = D4 / D8 = 0,357

Der Durchschnittspreis ist ausdrücklich Betrag durch Menge — die Umlage des
Grundpreises auf ct/kWh (D7) braucht die Verteilung nicht.

N142 — PV und Speicher waren bis dahin **ein** Topf. Der Nutzer trennt sie
bewusst: beide haben einen eigenen Preis, und beide Datenquellen (SolarEdge,
openWB-Ladeprotokoll) führen sie ohnehin getrennt. Die tragenden Eigenschaften
bleiben und werden hier weiter festgehalten:

* die Summe der Anteile ist **exakt** der Gesamtbetrag (cent-genau),
* das E-Auto wird mit seinen **exakten** Mengen vorab herausgenommen,
* der Rest verteilt sich so, dass jede Einheit denselben Anteil an **allen**
  Blöcken trägt und damit denselben Mischpreis zahlt.
"""
from app.strombloecke import Block, Bloecke, verteile


def _drei(netz: Block, pv: Block, akku: Block = None) -> Bloecke:
    """Kurzform für die drei Blöcke; ohne Akku bleibt der Topf leer."""
    return Bloecke(netz=netz, pv=pv, akku=akku or Block())


def test_durchschnittspreis_ist_betrag_je_menge():
    """D11 der Excel: 862,51 € / 2416 kWh = 0,357 €/kWh."""
    netz = Block(kwh=2416.0, betrag=862.51)
    assert abs(netz.preis - 862.51 / 2416) < 1e-12
    assert round(netz.preis, 3) == 0.357


def test_jede_einheit_traegt_denselben_mischpreis():
    """„Jeder kriegt den gleichen Anteil von allen Blöcken" — also zahlen alle
    denselben €/kWh, unabhängig von ihrer Größe."""
    b = _drei(Block(kwh=2400.0, betrag=862.51),    # 0,3594 €/kWh
              Block(kwh=2400.0, betrag=600.00),    # 0,2500 €/kWh
              Block(kwh=1200.0, betrag=588.00))    # 0,4900 €/kWh
    verbrauch = {"EG": 1000.0, "OG": 3000.0, "Büro": 2000.0}
    e = verteile(b, dict(verbrauch))

    gesamt = 862.51 + 600.00 + 588.00
    assert e.gesamt == round(gesamt, 2)
    # Gleicher Mischpreis fuer alle — bis auf die Cent-Rundung: die Verteilung
    # kann nur ganze Cent vergeben, der Rest landet nach Groesste-Reste bei
    # einer Einheit. Die Abweichung bleibt damit unter einem Cent je Einheit.
    schnitt = gesamt / 6000.0
    for name, menge in verbrauch.items():
        preis = e.kosten[name] / menge
        assert abs(preis - schnitt) * menge < 0.01, (name, preis)
    # Und jede Einheit bekommt anteilig aus ALLEN drei Töpfen.
    assert abs(e.netz_kwh["EG"] - 400.0) < 1e-6
    assert abs(e.pv_kwh["EG"] - 400.0) < 1e-6
    assert abs(e.akku_kwh["EG"] - 200.0) < 1e-6
    # PV und Speicher zusammen bleiben als „eigener Strom" ablesbar.
    assert abs(e.eigen_kwh["EG"] - 600.0) < 1e-6
    assert abs(e.kwh("EG") - 1000.0) < 1e-6


def test_summe_ist_cent_genau_der_gesamtbetrag():
    """Krumme Verbräuche dürfen keinen Cent verlieren."""
    b = _drei(Block(kwh=2416.0, betrag=862.51),
              Block(kwh=3000.045, betrag=990.02),
              Block(kwh=1618.0, betrag=533.93))
    e = verteile(b, {"EG": 1234.567, "OG": 2345.678,
                     "Büro": 987.65, "Studio": 3.21})
    assert e.gesamt == round(862.51 + 990.02 + 533.93, 2)
    assert round(sum(e.kosten.values()), 2) == e.gesamt


def test_eauto_wird_vorab_mit_seinen_exakten_mengen_verrechnet():
    """Für die Ladungen ist bekannt, wie viel aus dem Netz, wie viel direkt aus
    der PV und wie viel aus dem Speicher kam — das wird zuerst herausgerechnet,
    der Rest anteilig verteilt."""
    b = _drei(Block(kwh=2000.0, betrag=700.00),    # 0,35 €/kWh
              Block(kwh=2000.0, betrag=500.00),    # 0,25 €/kWh
              Block(kwh=1000.0, betrag=400.00))    # 0,40 €/kWh
    e = verteile(b, {"EG": 1000.0, "OG": 1000.0, "E-Auto": 1000.0},
                 eauto_einheit="E-Auto", eauto_netz_kwh=600.0,
                 eauto_pv_kwh=300.0, eauto_akku_kwh=100.0)

    # Exakt bepreist: 600×0,35 + 300×0,25 + 100×0,40 = 210 + 75 + 40 = 325 €
    assert e.kosten["E-Auto"] == 325.00
    assert e.eauto["netz_kwh"] == 600.0
    assert e.eauto["pv_kwh"] == 300.0
    assert e.eauto["akku_kwh"] == 100.0
    assert e.eauto["kwh"] == 1000.0
    # Der Rest (1400 Netz, 1700 PV, 900 Akku) geht je zur Haelfte an EG und OG.
    assert abs(e.netz_kwh["EG"] - 700.0) < 1e-6
    assert abs(e.pv_kwh["EG"] - 850.0) < 1e-6
    assert abs(e.akku_kwh["EG"] - 450.0) < 1e-6
    assert e.kosten["EG"] == e.kosten["OG"]
    assert e.gesamt == 1600.00


def test_eauto_teurer_als_der_schnitt_belastet_die_anderen_nicht():
    """Laedt das E-Auto ueberwiegend aus dem Netz, traegt es diesen Aufschlag
    selbst — die uebrigen Einheiten zahlen den guenstigeren Rest-Mischpreis."""
    b = _drei(Block(kwh=1000.0, betrag=400.00),    # 0,40 €/kWh
              Block(kwh=1000.0, betrag=200.00))    # 0,20 €/kWh
    ohne = verteile(b, {"EG": 1000.0, "OG": 1000.0})
    mit = verteile(b, {"EG": 500.0, "OG": 500.0, "E-Auto": 1000.0},
                   eauto_einheit="E-Auto", eauto_netz_kwh=900.0,
                   eauto_pv_kwh=100.0)
    assert mit.kosten["E-Auto"] == 380.00          # 900×0,40 + 100×0,20
    assert mit.kosten["EG"] == mit.kosten["OG"] == 110.00   # (100×0,40 + 900×0,20)/2
    assert mit.gesamt == ohne.gesamt == 600.00


def test_eauto_kwh_landen_nicht_bei_den_bewohnern():
    """Der Zweck des Vorab-Abzugs: die geladene Menge darf in KEINEM Block bei
    den Einheiten auftauchen."""
    b = _drei(Block(kwh=1000.0, betrag=350.00), Block(kwh=1000.0, betrag=250.00),
              Block(kwh=1000.0, betrag=400.00))
    e = verteile(b, {"EG": 1000.0, "OG": 1000.0, "E-Auto": 600.0},
                 eauto_einheit="E-Auto", eauto_netz_kwh=300.0,
                 eauto_pv_kwh=200.0, eauto_akku_kwh=100.0)
    for block, geladen in (("netz", 300.0), ("pv", 200.0), ("akku", 100.0)):
        bewohner = e.mengen[block]["EG"] + e.mengen[block]["OG"]
        assert abs(bewohner - (1000.0 - geladen)) < 1e-6, block
    assert abs(e.kwh("E-Auto") - 600.0) < 1e-6


def test_unplausible_eauto_mengen_werden_gemeldet_nicht_gerechnet():
    b = _drei(Block(kwh=100.0, betrag=40.00), Block(kwh=100.0, betrag=20.00))
    e = verteile(b, {"EG": 100.0, "E-Auto": 500.0},
                 eauto_einheit="E-Auto", eauto_netz_kwh=500.0)
    assert e.warnungen and "übersteigen" in e.warnungen[0]
    assert e.gesamt == 60.00          # trotzdem vollstaendig verteilt


def test_strom_ohne_zuordnung_warnt_statt_zu_verschwinden():
    e = verteile(_drei(Block(kwh=100.0, betrag=40.0), Block()), {})
    assert e.warnungen and "keine Einheit" in e.warnungen[0]


def test_eigenverbrauchsquote_zaehlt_pv_und_akku():
    b = _drei(Block(kwh=2416.0, betrag=862.51), Block(kwh=3000.045, betrag=990.0),
              Block(kwh=1618.0, betrag=533.9))
    e = verteile(b, {"EG": 100.0})
    eigen = 3000.045 + 1618.0
    assert e.eigenverbrauchsquote == round(eigen / (2416.0 + eigen), 4)


# --------------------------------------------------------------------------
# N125 — Einspeisevergütung (Blatt „Gesamtstrom", Zeilen 13–20)
# --------------------------------------------------------------------------

def test_einspeiseverguetung_aus_den_eeg_stufen():
    """D18 = D19 × 0,082 + D20 × 0,071 = 2595 × 0,082 + 2013 × 0,071."""
    from app.strombloecke import einspeiseverguetung
    assert einspeiseverguetung(2595, 2013) == 355.71


def test_einspeiseverguetung_nur_eine_stufe():
    from app.strombloecke import einspeiseverguetung
    assert einspeiseverguetung(1000, 0) == 82.00
    assert einspeiseverguetung(0, 1000) == 71.00


# --------------------------------------------------------------------------
# N126/N142 — SolarEdge-Verbrauchsaufteilung
# --------------------------------------------------------------------------

def test_solaredge_anteile_werden_zu_drei_bloecken():
    """Screenshot des Nutzers: 10,8 MWh · 24 % Netz · 50 % PV · 26 % Speicher.
    N142 — PV und Speicher sind jetzt zwei getrennte Töpfe."""
    from app.strombloecke import bloecke_aus_solaredge
    b, warnungen = bloecke_aus_solaredge(10800.0, 24.0, 50.0, 26.0)
    assert not warnungen
    assert b.netz.kwh == 2592.0
    assert b.pv.kwh == 5400.0
    assert b.akku.kwh == 2808.0
    assert b.kwh == 10800.0
    assert b.eigen_kwh == 8208.0


def test_solaredge_zwei_topf_sicht_bleibt():
    """Die zusammengefasste Sicht (zugekauft / eigen) rechnet unverändert."""
    from app.strombloecke import aus_solaredge
    extern, eigen, warnungen = aus_solaredge(10800.0, 24.0, 50.0, 26.0)
    assert not warnungen
    assert extern.kwh == 2592.0
    assert eigen.kwh == 8208.0


def test_solaredge_anteile_die_nicht_aufgehen_werden_gemeldet():
    from app.strombloecke import bloecke_aus_solaredge
    _, warnungen = bloecke_aus_solaredge(10800.0, 24.0, 50.0, 20.0)
    assert warnungen and "94 %" in warnungen[0]


def test_solaredge_bloecke_lassen_sich_direkt_verteilen():
    """Aus dem Screenshot heraus bis zur Verteilung, mit dem E-Auto vorab."""
    from app.strombloecke import bloecke_aus_solaredge
    b, _ = bloecke_aus_solaredge(10800.0, 24.0, 50.0, 26.0,
                                 netz_betrag=862.51, pv_betrag=1620.00,
                                 akku_betrag=1088.64)
    e = verteile(b, {"Wohnug 1.OG": 3000.0, "Wohung EG": 2000.0,
                     "Büro EG": 1500.0, "Studio 1.OG": 2926.14,
                     "E-Auto": 1373.86},
                 eauto_einheit="E-Auto", eauto_netz_kwh=300.0,
                 eauto_pv_kwh=800.0, eauto_akku_kwh=273.86)
    assert e.gesamt == round(862.51 + 1620.00 + 1088.64, 2)
    assert round(sum(e.kosten.values()), 2) == e.gesamt
    # Das E-Auto laedt ueberwiegend solar und faehrt damit guenstiger als der
    # Schnitt — genau der Vorteil, den der Nutzer beschreibt.
    schnitt = e.gesamt / 10800.0
    assert e.kosten["E-Auto"] / 1373.86 < schnitt
