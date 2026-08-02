"""N83 — Strom/PV: zwei Verbrauchsgruppen, Quellen-Aufteilung, PV-Ertrag.

Drei Ebenen: die reinen Engine-Formeln (`app.strom`) mit einem Excel-nahen
Kernbeispiel, den Randfällen und den Cent-Summen; und die Endpunkte
(Lesen/Speichern der Eingaben, Engine-Ergebnis).

Das Kernbeispiel (dokumentiert in `test_rechne_kernbeispiel`) bildet die
Logik der Excel `NK-ALL-Strom-Verbrauch` nach: WG 60 % / Büro 40 % „ohne
Tanken", Quellen Netz/Solar/Akku, PV auf Eigentümer 5/6 + 1/6.
"""
import os
import sys
import tempfile
from types import SimpleNamespace

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_strom.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import strom  # noqa: E402
from app.main import app  # noqa: E402


# --------------------------------------------------------------------------
# 1) Verbrauchsgruppen: Büro/Studio = Rest, Gruppen-Anteil
# --------------------------------------------------------------------------

def test_buero_kwh_rest():
    # Rest = Gesamt − WG − Garage.
    assert strom.buero_kwh(12000, 7000, 500) == 4500.0
    # Nie negativ: Unterzähler > Gesamt → auf 0 geklemmt.
    assert strom.buero_kwh(1000, 800, 300) == 0.0


def test_gruppen_anteil_fester_split_und_abgeleitet():
    # Fester Split hat Vorrang: 60 % → 0,60.
    assert strom.gruppen_anteil(7000, 4500, tanken=1500, wg_anteil_prozent=60) == 0.6
    # Abgeleitet aus kWh, Tanken vorher aus der Büro-Seite raus:
    # WG 6000, Büro 5000 − 1000 Tanken = 4000 → 6000/10000 = 0,60.
    assert strom.gruppen_anteil(6000, 5000, tanken=1000) == 0.6
    # Ohne Tanken: 6000/(6000+4000) = 0,60.
    assert strom.gruppen_anteil(6000, 4000) == 0.6
    # Keine Grundlage → hälftig.
    assert strom.gruppen_anteil(0, 0) == 0.5


# --------------------------------------------------------------------------
# 2) Einspeisevergütung (EEG-Stufen 0–10 kWp 8,2 ct, 10–40 kWp 7,1 ct)
# --------------------------------------------------------------------------

def test_einspeise_satz_ct_stufen():
    # Bis 10 kWp voller kleiner Satz.
    assert strom.einspeise_satz_ct(0) == 8.2
    assert strom.einspeise_satz_ct(8) == 8.2
    assert strom.einspeise_satz_ct(10) == 8.2
    # 12 kWp: (10·8,2 + 2·7,1)/12 = 96,2/12 = 8,0167 ct.
    assert strom.einspeise_satz_ct(12) == 8.0167
    # 50 kWp (über 40, vereinfacht 7,1 fortgeschrieben):
    # (10·8,2 + 40·7,1)/50 = 366/50 = 7,32 ct.
    assert strom.einspeise_satz_ct(50) == 7.32


def test_einspeiseverguetung_gerechnet_und_vorgegeben():
    # Gerechnet: 3000 kWh × 8,0167 ct = 240,50 €.
    betrag, satz = strom.einspeiseverguetung(3000, kwp=12)
    assert betrag == 240.50
    assert satz == 8.0167
    # Vorgegebener Betrag hat Vorrang; Satz wird zurückgerechnet.
    betrag, satz = strom.einspeiseverguetung(3000, kwp=12, verguetung_eur=250)
    assert betrag == 250.0
    assert satz == round(250 / 3000 * 100, 4)


# --------------------------------------------------------------------------
# 3) Eigentümer-Verteilung 5/6 + 1/6 (cent-genau)
# --------------------------------------------------------------------------

def test_verteile_eigentuemer_cent_genau():
    v = strom.verteile_eigentuemer(2340.50)
    assert v == [{"anteil": "5/6", "betrag": 1950.42},
                 {"anteil": "1/6", "betrag": 390.08}]
    assert round(sum(e["betrag"] for e in v), 2) == 2340.50
    # Glatt teilbar: 35.700 → 29.750 + 5.950.
    v = strom.verteile_eigentuemer(35700.0)
    assert v == [{"anteil": "5/6", "betrag": 29750.0},
                 {"anteil": "1/6", "betrag": 5950.0}]


# --------------------------------------------------------------------------
# 4) rechne — Excel-nahes Kernbeispiel
# --------------------------------------------------------------------------

def _beispiel(**ueberschreibung):
    werte = dict(
        gesamt_kwh=12000, wg_kwh=7000, garage_kwh=500,
        wg_anteil_prozent=60, tanken_kwh=1500,
        netz_kwh=4000, netz_preis=0.35,
        solar_kwh=6000, solar_preis=0.08,
        akku_kwh=2000, akku_preis=0.12,
        pv_produktion_kwh=9000, einspeisung_kwh=3000, pv_kwp=12,
        verguetung_eur=0, anschaffung_eur=35700,
    )
    werte.update(ueberschreibung)
    return SimpleNamespace(**werte)


def test_rechne_kernbeispiel():
    e = strom.rechne(_beispiel())

    # Verbrauch: Büro/Studio = 12000 − 7000 − 500 = 4500.
    assert e["verbrauch"]["buero_kwh"] == 4500.0
    assert e["wg_anteil"] == 0.6 and e["buero_anteil"] == 0.4

    # Quellenkosten: 4000·0,35 + 6000·0,08 + 2000·0,12 = 1400 + 480 + 240.
    assert e["quellen"]["netz"]["kosten"] == 1400.0
    assert e["quellen"]["solar"]["kosten"] == 480.0
    assert e["quellen"]["akku"]["kosten"] == 240.0
    assert e["quellen_kosten_gesamt"] == 2120.0

    # Gruppen: 60/40 auf jede Quelle → WG 1272 €, Büro 848 €.
    assert e["gruppen"]["WG"]["kosten"] == 1272.0
    assert e["gruppen"]["Büro/Studio"]["kosten"] == 848.0
    # kWh je Gruppe: WG 60 % von 4000/6000/2000 = 2400/3600/1200 = 7200.
    assert e["gruppen"]["WG"]["kwh"] == 7200.0
    assert e["gruppen"]["Büro/Studio"]["kwh"] == 4800.0
    # Cent-Invariante: Gruppen summieren sich exakt auf die Quellenkosten.
    assert round(e["gruppen"]["WG"]["kosten"]
                 + e["gruppen"]["Büro/Studio"]["kosten"], 2) == 2120.0

    # PV: Eigenverbrauch 9000 − 3000 = 6000; Vergütung 240,50 €;
    # Ersparnis 6000 · 0,35 = 2100 €; Ertrag 2340,50 €.
    assert e["pv"]["eigenverbrauch_kwh"] == 6000.0
    assert e["pv"]["einspeiseverguetung"] == 240.50
    assert e["pv"]["eigenverbrauch_ersparnis"] == 2100.0
    assert e["pv"]["ertrag"] == 2340.50
    assert e["pv"]["anschaffung"] == 35700.0

    # Eigentümer 5/6 + 1/6, cent-genau.
    assert e["eigentuemer"] == [
        {"anteil": "5/6", "ertrag": 1950.42, "anschaffung": 29750.0},
        {"anteil": "1/6", "ertrag": 390.08, "anschaffung": 5950.0}]
    assert round(sum(x["ertrag"] for x in e["eigentuemer"]), 2) == 2340.50
    assert not e["warnungen"]


def test_rechne_rest_negativ_warnung():
    # Unterzähler weisen mehr aus als der Gesamtzähler → Büro 0, Warnung.
    e = strom.rechne(_beispiel(gesamt_kwh=1000, wg_kwh=800, garage_kwh=300))
    assert e["verbrauch"]["buero_kwh"] == 0.0
    assert any("Gesamtzähler" in w for w in e["warnungen"])


def test_rechne_einspeisung_ueber_produktion_warnung():
    e = strom.rechne(_beispiel(pv_produktion_kwh=2000, einspeisung_kwh=3000))
    assert e["pv"]["eigenverbrauch_kwh"] == 0.0
    assert any("Einspeisung" in w for w in e["warnungen"])


def test_rechne_null_werte_sauber():
    # Ein völlig leeres Jahr rechnet ohne Fehler (alles 0), hälftiger Split.
    e = strom.rechne(SimpleNamespace())
    assert e["quellen_kosten_gesamt"] == 0.0
    assert e["gruppen"]["WG"]["kosten"] == 0.0
    assert e["pv"]["ertrag"] == 0.0
    assert e["wg_anteil"] == 0.5


def test_rechne_cent_summe_bei_krummen_werten():
    for netz, np_, solar, sp, akku, ap, proz in [
            (4000, 0.35, 6000, 0.08, 2000, 0.12, 60),
            (3333, 0.2871, 1234, 0.0731, 777, 0.191, 0),
            (1, 0.99, 1, 0.33, 1, 0.11, 33),
            (0, 0.30, 0, 0.10, 0, 0.10, 0)]:
        e = strom.rechne(_beispiel(
            netz_kwh=netz, netz_preis=np_, solar_kwh=solar, solar_preis=sp,
            akku_kwh=akku, akku_preis=ap, wg_anteil_prozent=proz))
        summe = round(e["gruppen"]["WG"]["kosten"]
                      + e["gruppen"]["Büro/Studio"]["kosten"], 2)
        assert summe == e["quellen_kosten_gesamt"], (netz, np_, proz)
        # Ertrag exakt auf die Eigentümer verteilt.
        assert round(sum(x["ertrag"] for x in e["eigentuemer"]), 2) \
            == e["pv"]["ertrag"]


# --------------------------------------------------------------------------
# 5) Endpunkte
# --------------------------------------------------------------------------

@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _neues_objekt(c) -> str:
    antwort = c.post("/api/objekte", json={
        "name": "Stromhaus", "ort": "Teststadt", "turnus": "kalender",
        "start_monat": 1, "kostenarten": ["Strom"],
        "einheiten": [{"bezeichnung": "EG", "flaeche": 70.0, "partei": "Müller"},
                      {"bezeichnung": "1.OG", "flaeche": 80.0, "partei": "Meier"}],
    })
    assert antwort.status_code == 201
    return antwort.json()["slug"]


def test_endpunkt_leer_dann_speichern_und_rechnen(client):
    slug = _neues_objekt(client)

    # Vor dem Speichern: leerer Satz (alles 0).
    leer = client.get(f"/api/objekte/{slug}/strom/2025").json()
    assert leer["jahr"] == 2025
    assert leer["gesamt_kwh"] == 0.0

    # Speichern (PUT) — legt den Datensatz an.
    werte = {
        "gesamt_kwh": 12000, "wg_kwh": 7000, "garage_kwh": 500,
        "wg_anteil_prozent": 60, "tanken_kwh": 1500,
        "netz_kwh": 4000, "netz_preis": 0.35,
        "solar_kwh": 6000, "solar_preis": 0.08,
        "akku_kwh": 2000, "akku_preis": 0.12,
        "pv_produktion_kwh": 9000, "einspeisung_kwh": 3000, "pv_kwp": 12,
        "anschaffung_eur": 35700,
    }
    gespeichert = client.put(f"/api/objekte/{slug}/strom/2025", json=werte).json()
    assert gespeichert["gesamt_kwh"] == 12000

    # Erneut lesen: die Werte sind da (ein Datensatz je Objekt/Jahr).
    gelesen = client.get(f"/api/objekte/{slug}/strom/2025").json()
    assert gelesen["wg_anteil_prozent"] == 60

    # Rechnung: dieselben Zahlen wie im Engine-Kernbeispiel.
    r = client.get(f"/api/objekte/{slug}/strom/2025/rechnung").json()
    assert r["gruppen"]["WG"]["kosten"] == 1272.0
    assert r["gruppen"]["Büro/Studio"]["kosten"] == 848.0
    assert r["pv"]["ertrag"] == 2340.50
    assert r["eigentuemer"][0] == {
        "anteil": "5/6", "ertrag": 1950.42, "anschaffung": 29750.0}


def test_endpunkt_put_aktualisiert_bestehenden(client):
    slug = _neues_objekt(client)
    client.put(f"/api/objekte/{slug}/strom/2025", json={"gesamt_kwh": 5000})
    client.put(f"/api/objekte/{slug}/strom/2025", json={"gesamt_kwh": 8000})
    gelesen = client.get(f"/api/objekte/{slug}/strom/2025").json()
    assert gelesen["gesamt_kwh"] == 8000
