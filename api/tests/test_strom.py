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


# ---------------------------------------------------------------------------
# N127 — der Amortisationsverlauf über die Jahre.
#
# Die Erträge kommen aus der Nebenkostenabrechnung: PV-Strom, den die Mieter
# bezahlt haben (`herkunft == "eigen"`), die Einspeisevergütung (eine NICHT
# umlagefähige Kostenart) und die Ladungen der E-Tankstelle. Eine
# kalkulatorische „Ersparnis Zukauf" ist bewusst kein Ertrag.
# ---------------------------------------------------------------------------

_EINSPEISUNG = "Einspeisevergütung"


def _pv_objekt(c, name: str = "PV-Haus") -> str:
    """Ein Objekt mit einer NICHT umlagefähigen Kostenart — daran erkennt der
    Verlauf die Einspeisevergütung. Kalenderjahr, damit Label-Jahr = Jahr."""
    slug = c.post("/api/objekte", json={
        "name": name, "ort": "Teststadt", "turnus": "kalender",
        "start_monat": 1, "kostenarten": ["Strom", _EINSPEISUNG],
        "einheiten": [{"bezeichnung": "EG", "flaeche": 70.0,
                       "partei": "Müller"}],
    }).json()["slug"]
    for k in c.get(f"/api/objekte/{slug}/kostenarten").json():
        if k["name"] == _EINSPEISUNG:
            c.patch(f"/api/kostenarten/{k['id']}", json={"umlagefaehig": False})
    return slug


def _zeitraum_id(c, slug: str, jahr: int) -> int:
    """Den Zeitraum eines Jahres holen — oder anlegen. Beim Anlegen entsteht
    automatisch schon einer fürs laufende Jahr; den nimmt der Test mit."""
    for z in c.get(f"/api/objekte/{slug}").json()["zeitraeume"]:
        if z["jahr"] == jahr:
            return z["id"]
    return c.post(f"/api/objekte/{slug}/zeitraeume",
                  json={"jahr": jahr}).json()["id"]


def _position(c, zid: int, kostenart: str, betrag: float,
              herkunft: str = "") -> int:
    pid = c.post(f"/api/zeitraeume/{zid}/positionen",
                 json={"kostenart": kostenart, "betrag": betrag,
                       "status": "erledigt"}).json()["id"]
    if herkunft:
        c.patch(f"/api/positionen/{pid}", json={"herkunft": herkunft})
    return pid


def _verlauf(c, slug: str) -> dict:
    antwort = c.get(f"/api/objekte/{slug}/pv/verlauf")
    assert antwort.status_code == 200, antwort.text
    return antwort.json()


def _jahr(v: dict, jahr: int) -> dict:
    return next(z for z in v["jahre"] if z["jahr"] == jahr)


def test_verlauf_drei_quellen_ueber_mehrere_jahre(client):
    """Der Kern von N127: PV-Strom der Mieter, Einspeisevergütung und E-Tanken
    je Jahr, kumuliert gegen die Anschaffung."""
    slug = _pv_objekt(client, "PV-Verlauf")
    client.put(f"/api/objekte/{slug}/strom/2024",
               json={"anschaffung_eur": 36000, "tanken_preis": 0.30})

    z24 = _zeitraum_id(client, slug, 2024)
    # Netzbezug: umlagefähig und nicht „eigen" — zählt der Anlage NICHT zu.
    _position(client, z24, "Strom", 862.51, herkunft="extern")
    _position(client, z24, _EINSPEISUNG, 355.71)
    client.post(f"/api/objekte/{slug}/tankstelle/2024",
                json={"name": "Alicia", "kwh": 3048.1, "preis": 0.30})

    z25 = _zeitraum_id(client, slug, 2025)
    _position(client, z25, "PV-Strom", 620.00, herkunft="eigen")
    _position(client, z25, _EINSPEISUNG, 400.00)

    v = _verlauf(client, slug)
    assert v["anschaffung"] == 36000.0

    a = _jahr(v, 2024)
    assert a["pv_strom"] == 0.0            # „Strom" ist Netzbezug, kein Ertrag
    assert a["einspeisung"] == 355.71
    assert a["tanken"] == 914.43           # 3048,1 kWh × 0,30 €
    assert a["summe"] == 1270.14
    assert a["kumuliert"] == 1270.14
    assert a["offen"] == 34729.86

    b = _jahr(v, 2025)
    assert (b["pv_strom"], b["einspeisung"], b["tanken"]) == (620.0, 400.0, 0.0)
    assert b["summe"] == 1020.0
    assert b["kumuliert"] == 2290.14

    # Kumuliert ist die Summe aller Jahressummen — keine verlorenen Cents.
    assert round(sum(z["summe"] for z in v["jahre"]), 2) == v["kumuliert"]
    assert v["rest"] == round(36000.0 - v["kumuliert"], 2)


def test_verlauf_jahr_ohne_ertraege_ist_eine_zeile_mit_null(client):
    """Ein Jahr ohne Daten ist eine Zeile mit 0, keine Lücke — sonst sähe der
    Verlauf aus, als hätte es das Jahr nie gegeben."""
    slug = _pv_objekt(client, "PV-Luecke")
    client.put(f"/api/objekte/{slug}/strom/2022", json={"anschaffung_eur": 20000})
    z22 = _zeitraum_id(client, slug, 2022)
    _position(client, z22, _EINSPEISUNG, 500.0)
    _zeitraum_id(client, slug, 2023)          # angelegt, aber ohne Positionen
    z24 = _zeitraum_id(client, slug, 2024)
    _position(client, z24, _EINSPEISUNG, 700.0)

    v = _verlauf(client, slug)
    jahre = [z["jahr"] for z in v["jahre"]]
    assert jahre == sorted(jahre) and 2023 in jahre
    # lückenlos von der ersten bis zur letzten Zeile
    assert jahre == list(range(jahre[0], jahre[-1] + 1))
    leer = _jahr(v, 2023)
    assert (leer["pv_strom"], leer["einspeisung"], leer["tanken"],
            leer["summe"]) == (0.0, 0.0, 0.0, 0.0)
    # Der kumulierte Stand bleibt im leeren Jahr stehen und fällt nicht zurück.
    assert leer["kumuliert"] == _jahr(v, 2022)["kumuliert"] == 500.0
    assert _jahr(v, 2024)["kumuliert"] == 1200.0


def test_verlauf_objekt_ohne_pv_bleibt_ruhig(client):
    """Kein PV-Ertrag, keine Anschaffung: keine erfundene Jahreszahl, sondern
    None — und ein Hinweis, was fehlt."""
    slug = _neues_objekt(client)
    v = _verlauf(client, slug)
    assert v["anschaffung"] == 0.0
    assert v["kumuliert"] == 0.0
    assert v["break_even_jahr"] is None
    assert v["break_even_geschaetzt"] is False
    assert v["amortisiert_prozent"] is None
    assert any("Anschaffung" in w for w in v["warnungen"])
    assert any("Noch keine Erträge" in w for w in v["warnungen"])
    # Die Zeilen selbst sind sauber (das Anlegen erzeugt einen Zeitraum).
    assert all(z["summe"] == 0.0 for z in v["jahre"])


def test_verlauf_break_even_erreicht(client):
    """Deckt der kumulierte Ertrag die Anschaffung, ist das Jahr echt erreicht
    — nicht geschätzt."""
    slug = _pv_objekt(client, "PV-Fertig")
    client.put(f"/api/objekte/{slug}/strom/2023", json={"anschaffung_eur": 1000})
    for jahr, betrag in ((2023, 400.0), (2024, 400.0), (2025, 400.0)):
        _position(client, _zeitraum_id(client, slug, jahr), _EINSPEISUNG, betrag)

    v = _verlauf(client, slug)
    assert v["break_even_jahr"] == 2025
    assert v["break_even_geschaetzt"] is False
    assert v["prognose"] is None            # erreicht — nichts mehr zu raten
    assert v["rest"] == 0.0
    assert v["amortisiert_prozent"] == 100.0
    assert _jahr(v, 2025)["offen"] == 0.0
    # Ab dem Break-even läuft die Anlage ins Plus.
    assert _jahr(v, 2025)["ueberschuss"] == 200.0


def test_verlauf_break_even_nicht_erreicht_wird_fortgeschrieben(client):
    """Noch nicht gedeckt: aus dem Schnitt der Ertragsjahre fortgeschrieben —
    als Schätzung gekennzeichnet, mit den einzelnen Prognosejahren."""
    slug = _pv_objekt(client, "PV-Laeuft")
    client.put(f"/api/objekte/{slug}/strom/2023", json={"anschaffung_eur": 10000})
    for jahr in (2023, 2024):
        _position(client, _zeitraum_id(client, slug, jahr), _EINSPEISUNG, 1000.0)

    v = _verlauf(client, slug)
    letztes = v["jahre"][-1]["jahr"]
    p = v["prognose"]
    # 2000 € in zwei Ertragsjahren = 1000 €/Jahr; 8000 € offen → acht Jahre.
    assert p["schnitt"] == 1000.0
    assert p["in_jahren"] == 8
    assert [z["jahr"] for z in p["jahre"]] == list(range(letztes + 1,
                                                         letztes + 9))
    assert p["jahre"][-1]["offen"] == 0.0
    assert v["break_even_geschaetzt"] is True
    assert v["break_even_jahr"] == p["break_even_jahr"] == letztes + 8
    assert v["break_even_in_jahren"] == 8
    assert 0 < v["amortisiert_prozent"] < 100


def test_verlauf_prognose_erst_ab_zwei_ertragsjahren(client):
    """Aus einem einzigen Jahr wird nicht hochgerechnet — lieber ein Satz als
    eine Zahl, die auf einem Wert beruht."""
    slug = _pv_objekt(client, "PV-Erstjahr")
    client.put(f"/api/objekte/{slug}/strom/2024", json={"anschaffung_eur": 10000})
    _position(client, _zeitraum_id(client, slug, 2024), _EINSPEISUNG, 1000.0)

    v = _verlauf(client, slug)
    assert v["prognose"] is None
    assert v["break_even_jahr"] is None
    assert v["break_even_geschaetzt"] is False
    assert v["break_even_in_jahren"] is None
    assert any("zweiten Abrechnungsjahr" in w for w in v["warnungen"])


def test_verlauf_vorlauf_zaehlt_einmalig_aufs_erste_jahr(client):
    """Der Vorlauf ist, was die Anlage vor der ersten Abrechnung schon
    abgetragen hat: einmalig auf die erste Zeile, nie wiederholt — und er hebt
    den Prognose-Schnitt nicht an."""
    slug = _pv_objekt(client, "PV-Vorlauf")
    client.put(f"/api/objekte/{slug}/strom/2024",
               json={"anschaffung_eur": 10000, "vorlauf_ertrag_eur": 1500})
    # Das Feld überdauert das Speichern (additive Spalte).
    assert client.get(f"/api/objekte/{slug}/strom/2024").json()[
        "vorlauf_ertrag_eur"] == 1500.0

    for jahr in (2024, 2025):
        _position(client, _zeitraum_id(client, slug, jahr), _EINSPEISUNG, 1000.0)

    v = _verlauf(client, slug)
    assert v["vorlauf"] == 1500.0
    erstes = v["jahre"][0]
    assert erstes["jahr"] == 2024
    assert erstes["vorlauf"] == 1500.0
    assert erstes["summe"] == 2500.0         # 1500 Vorlauf + 1000 Einspeisung
    assert all(z["vorlauf"] == 0.0 for z in v["jahre"][1:])
    assert v["kumuliert"] == 3500.0
    # Der Schnitt rechnet ohne den einmaligen Vorlauf: 2 × 1000 € / 2 Jahre.
    assert v["prognose"]["schnitt"] == 1000.0


def test_verlauf_offene_position_zaehlt_noch_nicht(client):
    """Eine Position ohne Betrag (Status „offen") ist noch kein Geldfluss —
    genau wie in der Abrechnung selbst."""
    slug = _pv_objekt(client, "PV-Offen")
    zid = _zeitraum_id(client, slug, 2024)
    pid = client.post(f"/api/zeitraeume/{zid}/positionen",
                      json={"kostenart": _EINSPEISUNG, "betrag": 300.0,
                            "status": "offen"}).json()["id"]
    assert _jahr(_verlauf(client, slug), 2024)["einspeisung"] == 0.0
    client.patch(f"/api/positionen/{pid}", json={"status": "erledigt"})
    assert _jahr(_verlauf(client, slug), 2024)["einspeisung"] == 300.0
