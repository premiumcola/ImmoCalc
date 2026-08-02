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
    # N87 — das Ergebnis trägt zusätzlich `investitions_ertrag` je Eigentümer
    # (additiv). Deshalb Feld für Feld prüfen statt das ganze dict zu vergleichen.
    assert [(x["anteil"], x["ertrag"], x["anschaffung"]) for x in e["eigentuemer"]] == [
        ("5/6", 1950.42, 29750.0), ("1/6", 390.08, 5950.0)]
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
# 5) N89 — von der Gruppe zur Einheit
# --------------------------------------------------------------------------

def test_einheiten_liste_bereinigt():
    # Komma-Liste mit Leerraum, leeren Einträgen und einer Dublette.
    assert strom.einheiten_liste(" EG , 1.OG ,, EG ") == ["EG", "1.OG"]
    # Auch eine fertige Liste wird angenommen; nichts drin = nichts raus.
    assert strom.einheiten_liste(["Studio", "Büro"]) == ["Studio", "Büro"]
    assert strom.einheiten_liste("") == []
    assert strom.einheiten_liste(None) == []


def test_rechne_einheiten_zwei_plus_zwei():
    """Der Kern von N89: WG 1272 € auf zwei Wohnungen, Büro/Studio 848 € auf
    zwei Einheiten — je gleichmäßig, und die Summe ist exakt die Gesamtsumme."""
    e = strom.rechne(_beispiel(wg_einheiten="EG, 1.OG",
                               buero_einheiten="Büro EG,Studio 1.OG"))
    assert [(x["name"], x["gruppe"], x["kosten"]) for x in e["einheiten"]] == [
        ("EG", "WG", 636.0), ("1.OG", "WG", 636.0),
        ("Büro EG", "Büro/Studio", 424.0), ("Studio 1.OG", "Büro/Studio", 424.0)]
    # kWh mitgeführt: WG 7200 → 2×3600, Büro 4800 → 2×2400.
    assert [x["kwh"] for x in e["einheiten"]] == [3600.0, 3600.0, 2400.0, 2400.0]
    # Invariante: Σ Einheiten == Σ Gruppen == Quellenkosten.
    assert round(sum(x["kosten"] for x in e["einheiten"]), 2) \
        == e["quellen_kosten_gesamt"] == 2120.0
    assert not e["warnungen"]


def test_rechne_ohne_zuordnung_unveraendert():
    """Regression: ohne `wg_einheiten`/`buero_einheiten` rechnet alles wie
    bisher — der Einheiten-Block ist dann leer, sonst ändert sich kein Wert."""
    ohne = strom.rechne(_beispiel())
    assert ohne["einheiten"] == []
    mit = strom.rechne(_beispiel(wg_einheiten="EG,1.OG",
                                 buero_einheiten="Büro,Studio"))
    assert {k: v for k, v in mit.items() if k != "einheiten"} \
        == {k: v for k, v in ohne.items() if k != "einheiten"}


def test_rechne_einheiten_krumme_betraege_summieren_exakt():
    """Krumme Beträge auf ungerade Einheitenzahlen: keine verlorenen Cents.
    3 Wohnungen + 2 Büroeinheiten, damit sich nichts glatt teilt."""
    for netz, np_, solar, sp, akku, ap, proz in [
            (4000, 0.35, 6000, 0.08, 2000, 0.12, 60),
            (3333, 0.2871, 1234, 0.0731, 777, 0.191, 0),
            (1, 0.99, 1, 0.33, 1, 0.11, 33),
            (100, 0.3333, 0, 0.0, 0, 0.0, 50),
            (0, 0.30, 0, 0.10, 0, 0.10, 0)]:
        e = strom.rechne(_beispiel(
            netz_kwh=netz, netz_preis=np_, solar_kwh=solar, solar_preis=sp,
            akku_kwh=akku, akku_preis=ap, wg_anteil_prozent=proz,
            wg_einheiten="EG,1.OG,2.OG", buero_einheiten="Büro,Studio"))
        assert len(e["einheiten"]) == 5
        summe = round(sum(x["kosten"] for x in e["einheiten"]), 2)
        assert summe == e["quellen_kosten_gesamt"], (netz, np_, proz)
        # Auch je Gruppe exakt: die Einheiten einer Gruppe ergeben deren Kosten.
        for gruppe in ("WG", "Büro/Studio"):
            teil = round(sum(x["kosten"] for x in e["einheiten"]
                             if x["gruppe"] == gruppe), 2)
            assert teil == e["gruppen"][gruppe]["kosten"], (gruppe, netz, proz)
        # Und die kWh gehen ebenso auf.
        assert round(sum(x["kwh"] for x in e["einheiten"]), 3) \
            == round(e["gruppen"]["WG"]["kwh"]
                     + e["gruppen"]["Büro/Studio"]["kwh"], 3)


def test_rechne_einheiten_nur_eine_gruppe_zugeordnet():
    # Ist nur die WG zugeordnet, deckt der Block auch nur deren Kosten ab.
    e = strom.rechne(_beispiel(wg_einheiten="EG,1.OG"))
    assert len(e["einheiten"]) == 2
    assert round(sum(x["kosten"] for x in e["einheiten"]), 2) == 1272.0


def test_rechne_einheit_in_beiden_gruppen_warnt():
    e = strom.rechne(_beispiel(wg_einheiten="EG,Studio",
                               buero_einheiten="Studio,Büro"))
    assert any("beiden Gruppen" in w for w in e["warnungen"])


def test_nk_positionen_schlanke_liste():
    """Was die Nebenkosten-Seite übernimmt: je Einheit Bezeichnung, € und kWh."""
    p = strom.nk_positionen(strom.rechne(_beispiel(
        wg_einheiten="EG,1.OG", buero_einheiten="Büro,Studio")))
    assert p["positionen"][0] == {"einheit": "EG", "betrag": 636.0,
                                 "kwh": 3600.0}
    assert p["gesamt"] == 2120.0
    assert p["kwh_gesamt"] == 12000.0
    assert p["warnungen"] == []
    # Ohne Zuordnung: leere Liste statt einer falschen Zahl.
    leer = strom.nk_positionen(strom.rechne(_beispiel()))
    assert leer["positionen"] == [] and leer["gesamt"] == 0.0


# --------------------------------------------------------------------------
# 6) Endpunkte
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
    e0 = r["eigentuemer"][0]
    assert (e0["anteil"], e0["ertrag"], e0["anschaffung"]) \
        == ("5/6", 1950.42, 29750.0)


def test_endpunkt_rechnung_mit_einheiten_parametern(client):
    """N89 — die Zuordnung kommt als Abfrageparameter an den Endpunkt; ohne sie
    bleibt der Einheiten-Block leer (Verhalten wie bisher)."""
    slug = _neues_objekt(client)
    client.put(f"/api/objekte/{slug}/strom/2025", json={
        "gesamt_kwh": 12000, "wg_kwh": 7000, "garage_kwh": 500,
        "wg_anteil_prozent": 60, "tanken_kwh": 1500,
        "netz_kwh": 4000, "netz_preis": 0.35,
        "solar_kwh": 6000, "solar_preis": 0.08,
        "akku_kwh": 2000, "akku_preis": 0.12,
    })

    ohne = client.get(f"/api/objekte/{slug}/strom/2025/rechnung").json()
    assert ohne["einheiten"] == []

    mit = client.get(f"/api/objekte/{slug}/strom/2025/rechnung",
                     params={"wg": "EG,1.OG", "buero": "Büro,Studio"}).json()
    assert [(x["name"], x["kosten"]) for x in mit["einheiten"]] == [
        ("EG", 636.0), ("1.OG", 636.0), ("Büro", 424.0), ("Studio", 424.0)]


def test_endpunkt_nk_positionen(client):
    """Die schlanke Liste für die Nebenkostenabrechnung."""
    slug = _neues_objekt(client)
    client.put(f"/api/objekte/{slug}/strom/2025", json={
        "gesamt_kwh": 12000, "wg_kwh": 7000, "garage_kwh": 500,
        "wg_anteil_prozent": 60, "tanken_kwh": 1500,
        "netz_kwh": 4000, "netz_preis": 0.35,
        "solar_kwh": 6000, "solar_preis": 0.08,
        "akku_kwh": 2000, "akku_preis": 0.12,
    })
    p = client.get(f"/api/objekte/{slug}/strom/2025/nk-positionen",
                   params={"wg": "EG,1.OG", "buero": "Büro,Studio"}).json()
    assert p["jahr"] == 2025
    assert p["positionen"] == [
        {"einheit": "EG", "betrag": 636.0, "kwh": 3600.0},
        {"einheit": "1.OG", "betrag": 636.0, "kwh": 3600.0},
        {"einheit": "Büro", "betrag": 424.0, "kwh": 2400.0},
        {"einheit": "Studio", "betrag": 424.0, "kwh": 2400.0}]
    assert p["gesamt"] == 2120.0
    # Ohne Zuordnung liefert der Endpunkt eine leere Liste, keinen Fehler.
    leer = client.get(f"/api/objekte/{slug}/strom/2025/nk-positionen").json()
    assert leer["positionen"] == [] and leer["gesamt"] == 0.0


def test_endpunkt_put_nimmt_einheiten_zuordnung_an(client):
    """Der PUT nimmt die Zuordnung entgegen, ohne die übrigen Werte zu
    beschädigen. Ob sie überdauert, hängt an der Spalte `gruppen_einheiten` —
    solange es sie nicht gibt, kommt sie leer zurück (siehe Router)."""
    from app.routers import strom as strom_router

    slug = _neues_objekt(client)
    antwort = client.put(f"/api/objekte/{slug}/strom/2025", json={
        "gesamt_kwh": 12000, "wg_einheiten": "EG,1.OG",
        "buero_einheiten": "Büro,Studio"})
    assert antwort.status_code == 200
    assert antwort.json()["gesamt_kwh"] == 12000
    erwartet = "EG,1.OG" if strom_router._HAT_SPALTE else ""
    assert client.get(f"/api/objekte/{slug}/strom/2025").json()["wg_einheiten"] \
        == erwartet


def test_endpunkt_put_aktualisiert_bestehenden(client):
    slug = _neues_objekt(client)
    client.put(f"/api/objekte/{slug}/strom/2025", json={"gesamt_kwh": 5000})
    client.put(f"/api/objekte/{slug}/strom/2025", json={"gesamt_kwh": 8000})
    gelesen = client.get(f"/api/objekte/{slug}/strom/2025").json()
    assert gelesen["gesamt_kwh"] == 8000


# ---------------------------------------------------------------------------
# N87 — PV als Add-on-Investment: eigene Tausendstel, Tank-Erlös, Amortisation.
# ---------------------------------------------------------------------------

def test_pv_investitions_ertrag_ohne_kalkulatorische_ersparnis():
    """Der Investitions-Ertrag ist ein ZAHLUNGSFLUSS: was Mieter für PV-Strom
    (Solar+Akku) zahlen, plus Einspeisevergütung und Tank-Erlös. Die
    Eigenverbrauchs-Ersparnis (kalkulatorisch) gehört NICHT dazu."""
    e = strom.rechne(dict(
        gesamt_kwh=10000, wg_kwh=6000, garage_kwh=0,
        netz_kwh=4000, netz_preis=0.30,
        solar_kwh=4000, solar_preis=0.20, akku_kwh=2000, akku_preis=0.20,
        pv_produktion_kwh=9000, einspeisung_kwh=3000, pv_kwp=10,
        tanken_kwh=1000, tanken_preis=0.30, tanken_person="Alicia"))
    # Solar 800 € + Akku 400 € + Einspeisung 3000×8,2ct = 246 € + Tanken 300 €.
    assert e["quellen"]["solar"]["kosten"] == 800.0
    assert e["quellen"]["akku"]["kosten"] == 400.0
    assert e["pv"]["einspeiseverguetung"] == 246.0
    assert e["tankstelle"] == {"kwh": 1000.0, "preis": 0.3, "betrag": 300.0,
                               "person": "Alicia"}
    assert e["pv"]["investitions_ertrag"] == 1746.0
    # Der kalkulatorische pv.ertrag ist eine ANDERE Zahl (mit Ersparnis).
    assert e["pv"]["ertrag"] != e["pv"]["investitions_ertrag"]


def test_eigene_pv_anteile_gehen_cent_genau_auf():
    """Die PV-Anlage hat eigene Tausendstel, unabhängig vom Objekt."""
    e = strom.rechne(dict(
        solar_kwh=1000, solar_preis=1.0, netz_preis=0.3,
        pv_anteile='{"Roland": 833.3, "Marvin": 166.7}'))
    namen = [x["anteil"] for x in e["eigentuemer"]]
    assert set(namen) == {"Roland", "Marvin"}
    summe = round(sum(x["investitions_ertrag"] for x in e["eigentuemer"]), 2)
    assert summe == e["pv"]["investitions_ertrag"] == 1000.0


def test_amortisation_kumuliert_und_break_even():
    a = strom.amortisation(
        [{"jahr": 2024, "ertrag": 4000.0}, {"jahr": 2025, "ertrag": 4000.0},
         {"jahr": 2026, "ertrag": 4000.0}], 10000.0)
    assert a["kumuliert"] == 12000.0
    assert a["rest"] == 0.0
    assert a["break_even_jahr"] == 2026        # im dritten Jahr erreicht
    assert a["amortisiert_prozent"] == 100.0
    assert [z["kumuliert"] for z in a["reihe"]] == [4000.0, 8000.0, 12000.0]


def test_amortisation_ohne_anschaffung_bleibt_stumm():
    a = strom.amortisation([{"jahr": 2024, "ertrag": 500.0}], 0.0)
    assert a["amortisiert_prozent"] is None and a["break_even_jahr"] is None
    assert a["kumuliert"] == 500.0


def test_warnung_wenn_quellen_nicht_zum_gesamtzaehler_passen():
    e = strom.rechne(dict(gesamt_kwh=10000, wg_kwh=5000,
                          netz_kwh=9000, solar_kwh=9000))
    assert any("Gesamtzähler" in w for w in e["warnungen"])
