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


def test_endpunkt_speichert_die_eauto_aufteilung(client):
    """N124 — welche Einheit die Ladungen trägt und wie viel davon Netz bzw.
    eigene Anlage war. Von Hand eingetragen (`strombloecke.verteile` rechnet
    damit), solange die Wallbox nichts liefert.

    Die Felder sind optional: ein Speichern der übrigen Strom-Maske darf sie
    nicht auf 0 zurücksetzen — genau der Fehler aus N108."""
    slug = _neues_objekt(client)
    client.put(f"/api/objekte/{slug}/strom/2025", json={
        "eauto_einheit": "Studio", "eauto_extern_kwh": 522.34,
        "eauto_eigen_kwh": 828.19})

    gelesen = client.get(f"/api/objekte/{slug}/strom/2025").json()
    assert gelesen["eauto_einheit"] == "Studio"
    assert gelesen["eauto_extern_kwh"] == 522.34
    assert gelesen["eauto_eigen_kwh"] == 828.19

    # Speichern ohne die drei Felder lässt sie stehen.
    client.put(f"/api/objekte/{slug}/strom/2025", json={"gesamt_kwh": 12000})
    danach = client.get(f"/api/objekte/{slug}/strom/2025").json()
    assert danach["gesamt_kwh"] == 12000
    assert (danach["eauto_einheit"], danach["eauto_extern_kwh"],
            danach["eauto_eigen_kwh"]) == ("Studio", 522.34, 828.19)


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


def test_verlauf_drei_quellen_ueber_mehrere_jahre(client, monkeypatch):
    """Der Kern von N127/N200: PV-Strom der Mieter, Einspeisevergütung und
    E-Tanken je Jahr, kumuliert gegen die Anschaffung.

    N200 — der E-Tanken-Beitrag kommt nicht mehr aus `Tankladung.preis` (seit
    N148 stillgelegt), sondern aus der eigenen Lademenge (PV + Akku) zum
    abgeleiteten Eigen-Satz. Die Aufteilung Netz/eigen der Ladung kommt hier aus
    dem Jahresverhältnis (`eauto_extern_kwh`/`eauto_eigen_kwh`), der Satz wird
    fest gesetzt — seine Ableitung prüft `test_tankstelle`/`test_stromkette`."""
    from app.routers import tankstelle
    # Fester Eigen-Satz 0,30 €/kWh — die Ableitung selbst ist anderswo geprüft.
    monkeypatch.setattr(tankstelle, "satz_ableiten",
                        lambda *a, **k: tankstelle.Satz(netz=0.3333, eigen=0.30,
                                                        misch=0.30))
    slug = _pv_objekt(client, "PV-Verlauf")
    # Aufteilung der Ladungen 2024: halb Netz, halb eigen — 3000 kWh Ladung
    # ergeben so 1500 kWh Eigenstrom (PV + Akku).
    client.put(f"/api/objekte/{slug}/strom/2024",
               json={"anschaffung_eur": 36000,
                     "eauto_extern_kwh": 1000, "eauto_eigen_kwh": 1000})

    z24 = _zeitraum_id(client, slug, 2024)
    # Netzbezug: umlagefähig und nicht „eigen" — zählt der Anlage NICHT zu.
    _position(client, z24, "Strom", 862.51, herkunft="extern")
    _position(client, z24, _EINSPEISUNG, 355.71)
    client.post(f"/api/objekte/{slug}/tankstelle/2024",
                json={"name": "Alicia", "kwh": 3000.0, "datum": "2024-06-15"})

    z25 = _zeitraum_id(client, slug, 2025)
    _position(client, z25, "PV-Strom", 620.00, herkunft="eigen")
    _position(client, z25, _EINSPEISUNG, 400.00)

    v = _verlauf(client, slug)
    assert v["anschaffung"] == 36000.0

    a = _jahr(v, 2024)
    assert a["pv_strom"] == 0.0            # „Strom" ist Netzbezug, kein Ertrag
    assert a["einspeisung"] == 355.71
    assert a["tanken"] == 450.0            # 1500 kWh eigen × 0,30 €
    assert a["summe"] == 805.71
    assert a["kumuliert"] == 805.71
    assert a["offen"] == 35194.29

    b = _jahr(v, 2025)
    assert (b["pv_strom"], b["einspeisung"], b["tanken"]) == (620.0, 400.0, 0.0)
    assert b["summe"] == 1020.0
    assert b["kumuliert"] == 1825.71

    # Kumuliert ist die Summe aller Jahressummen — keine verlorenen Cents.
    assert round(sum(z["summe"] for z in v["jahre"]), 2) == v["kumuliert"]
    assert v["rest"] == round(36000.0 - v["kumuliert"], 2)

    # N200 — die Kategorien-Aufteilung summiert sich exakt auf den kumulierten
    # Ertrag, und der €-Anteil steht neben der kWh-Menge.
    kat = {p["feld"]: p for p in v["kategorien"]["posten"]}
    assert kat["einspeisung"]["eur"] == 755.71     # 355,71 + 400,00
    assert kat["tanken"]["eur"] == 450.0
    assert kat["pv_strom"]["eur"] == 620.0
    assert v["kategorien"]["gesamt_eur"] == v["kumuliert"]
    assert kat["tanken"]["kwh"] == 1500.0          # eigene Lademenge
    # E-Tanken bringt viel € je kWh, die Einspeisung viele kWh zu wenig €.
    assert kat["tanken"]["eur_pro_kwh"] == 0.30


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
    assert v["break_even_methode"] is None
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
    assert v["break_even_methode"] == 'erreicht'
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
    assert v["break_even_methode"] == 'prognose'
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
    assert v["break_even_methode"] is None
    assert v["break_even_in_jahren"] is None
    assert any("zweiten Abrechnungsjahr" in w for w in v["warnungen"])


def test_verlauf_prognose_jenseits_des_horizonts_bleibt_leer(client):
    """Trägt die Anlage nur Kleinbeträge ab, wäre eine Jahreszahl in ferner
    Zukunft ohne Aussage — dann lieber keine."""
    slug = _pv_objekt(client, "PV-Schnecke")
    client.put(f"/api/objekte/{slug}/strom/2024", json={"anschaffung_eur": 100000})
    for jahr in (2024, 2025):
        _position(client, _zeitraum_id(client, slug, jahr), _EINSPEISUNG, 100.0)

    v = _verlauf(client, slug)
    assert v["prognose"] is None
    assert v["break_even_jahr"] is None
    assert any("noch nicht abbezahlt" in w for w in v["warnungen"])


def test_verlauf_faellt_auf_groben_schnitt_zurueck_wenn_echte_jahre_fast_leer_sind(client):
    """N428 — Nutzer-Fund: die laufenden Abrechnungsjahre trugen real nur ein
    paar hundert Euro (z. B. weil die eigentliche PV-Einspeisung dort noch
    nicht erfasst ist), `_prognose` mittelte über einen fast leeren Schnitt
    und landete jenseits von 60 Jahren — obwohl ÜBER DIE GESAMTE LAUFZEIT
    (Vorlauf eingeschlossen) schon reale ~2.800 € hereingekommen waren. Der
    grobe Fallback (`break_even_methode == 'grob'`) liefert dafür eine
    Jahreszahl statt der Fehlanzeige."""
    slug = _pv_objekt(client, "PV-Fast-Leer")
    client.put(f"/api/objekte/{slug}/pv/stammdaten", json={
        "anschaffung_eur": 35800, "inbetriebnahme": "2023-06-30",
        "vorlauf_ertrag_eur": 2355.36})
    # Die laufenden Jahre selbst tragen nur Kleinstbeträge — genau der Fall,
    # der `_prognose` (nur echte Ertragsjahre) über 60 Jahre treibt.
    for jahr, betrag in ((2025, 322.49), (2026, 151.22)):
        _position(client, _zeitraum_id(client, slug, jahr), _EINSPEISUNG, betrag)

    v = _verlauf(client, slug)
    assert v["prognose"] is None                  # der genaue Weg scheitert wie gemeldet
    assert v["break_even_methode"] == 'grob'
    assert v["break_even_jahr"] is not None
    assert 0 < v["break_even_in_jahren"] < 60
    assert not any("noch nicht abbezahlt" in w for w in v["warnungen"])


def test_verlauf_vorlauf_steht_vor_dem_ersten_abrechnungsjahr(client):
    """N153b — der Vorlauf ist, was die Anlage VOR der ersten Abrechnung schon
    abgetragen hat. Er bekommt deshalb eine eigene Zeile im Jahr davor und
    vermischt sich nicht mit den echten Erträgen des ersten Abrechnungsjahres.
    In Summe und Amortisation zählt er unverändert voll mit; den
    Prognose-Schnitt hebt er nicht an (er wiederholt sich nicht)."""
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
    assert v["vorlauf_jahr"] == 2023          # das Jahr vor der ersten Abrechnung
    vorlaufzeile = v["jahre"][0]
    assert vorlaufzeile["jahr"] == 2023
    assert vorlaufzeile["vorlauf"] == 1500.0
    assert vorlaufzeile["summe"] == 1500.0    # nur der Vorlauf, sonst nichts
    # Das erste Abrechnungsjahr zeigt allein seinen eigenen Ertrag.
    assert _jahr(v, 2024)["vorlauf"] == 0.0
    assert _jahr(v, 2024)["summe"] == 1000.0
    assert all(z["vorlauf"] == 0.0 for z in v["jahre"][1:])
    assert v["kumuliert"] == 3500.0
    # Der Schnitt rechnet ohne den einmaligen Vorlauf: 2 × 1000 € / 2 Jahre.
    assert v["prognose"]["schnitt"] == 1000.0


def test_verlauf_liest_die_anschaffung_aus_den_stammdaten(client):
    """N139 — der Verlauf zieht Anschaffung und Vorlauf aus den Stammdaten,
    nicht mehr aus dem Strom-Jahr."""
    slug = _pv_objekt(client, "PV-Stammverlauf")
    client.put(f"/api/objekte/{slug}/pv/stammdaten",
               json={"anschaffung_eur": 12000, "vorlauf_ertrag_eur": 2000})
    _position(client, _zeitraum_id(client, slug, 2024), _EINSPEISUNG, 1000.0)

    v = _verlauf(client, slug)
    assert v["anschaffung"] == 12000.0
    assert v["vorlauf"] == 2000.0
    # N153b — der Vorlauf steht im Jahr vor der ersten Abrechnung, das
    # Abrechnungsjahr zeigt nur seinen eigenen Ertrag.
    assert v["jahre"][0]["summe"] == 2000.0
    assert _jahr(v, 2024)["summe"] == 1000.0
    assert v["rest"] == 9000.0


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


# ---------------------------------------------------------------------------
# N139 — Stammdaten der PV-Anlage: was einmal gilt, nicht jedes Jahr neu.
#
# Anschaffung, bereits Abgetragenes, Leistung und die Eigentümer-Tausendstel
# hingen am `Stromjahr` und wechselten mit der Jahresauswahl. Sie stehen jetzt
# in `PVAnlage`; die alten Spalten bleiben stehen und werden einmalig
# übernommen, damit kein Bestand verloren geht.
# ---------------------------------------------------------------------------

def _stammdaten(c, slug: str) -> dict:
    antwort = c.get(f"/api/objekte/{slug}/pv/stammdaten")
    assert antwort.status_code == 200, antwort.text
    return antwort.json()


def test_stammdaten_anlegen_lesen_aendern(client):
    """Leer, dann gefüllt, dann geändert — ein Satz je Objekt."""
    slug = _neues_objekt(client)

    leer = _stammdaten(client, slug)
    assert leer["anschaffung_eur"] == 0.0
    assert leer["kwp"] == 0.0
    assert leer["inbetriebnahme"] is None
    assert leer["anteile_promille"] == {} and leer["hinweise"] == []

    gespeichert = client.put(f"/api/objekte/{slug}/pv/stammdaten", json={
        "anschaffung_eur": 36000, "vorlauf_ertrag_eur": 1500,
        "kwp": 19.44, "inbetriebnahme": "2021-06-01",
        "notiz": "Aufdach Süd"}).json()
    assert gespeichert["anschaffung_eur"] == 36000.0
    assert gespeichert["kwp"] == 19.44
    assert gespeichert["inbetriebnahme"] == "2021-06-01"

    # Erneut lesen: alles da.
    gelesen = _stammdaten(client, slug)
    assert gelesen["vorlauf_ertrag_eur"] == 1500.0
    assert gelesen["notiz"] == "Aufdach Süd"

    # Ändern, ohne die übrigen Felder mitzuschicken — sie bleiben stehen.
    client.put(f"/api/objekte/{slug}/pv/stammdaten", json={"kwp": 20.0})
    danach = _stammdaten(client, slug)
    assert danach["kwp"] == 20.0
    assert danach["anschaffung_eur"] == 36000.0
    assert danach["notiz"] == "Aufdach Süd"


def test_stammdaten_uebernehmen_bestand_aus_dem_strom_jahr_einmalig(client):
    """Der Bestand des Nutzers steht am Strom-Jahr (36.000 € und 19,44 kWp).
    Er wird EINMALIG übernommen — danach gilt nur noch, was in den Stammdaten
    steht, auch wenn ein Jahr etwas anderes trägt."""
    slug = _neues_objekt(client)
    client.put(f"/api/objekte/{slug}/strom/2023", json={
        "anschaffung_eur": 36000, "pv_kwp": 19.44, "vorlauf_ertrag_eur": 2500,
        "pv_anteile": '{"Roland": 833.3, "Marvin": 166.7}'})

    uebernommen = _stammdaten(client, slug)
    assert uebernommen["anschaffung_eur"] == 36000.0
    assert uebernommen["kwp"] == 19.44
    assert uebernommen["vorlauf_ertrag_eur"] == 2500.0
    assert uebernommen["anteile_promille"] == {"Roland": 833.3, "Marvin": 166.7}

    # Ab jetzt sind die Stammdaten die Wahrheit: eine Korrektur überlebt, und
    # ein Jahr mit abweichender Anschaffung überschreibt sie nicht mehr.
    client.put(f"/api/objekte/{slug}/pv/stammdaten", json={"anschaffung_eur": 34000})
    client.put(f"/api/objekte/{slug}/strom/2024", json={"anschaffung_eur": 99999,
                                                       "pv_kwp": 5.0})
    danach = _stammdaten(client, slug)
    assert danach["anschaffung_eur"] == 34000.0
    assert danach["kwp"] == 19.44

    # Das alte Feld am Jahr bleibt unangetastet stehen (nie löschen).
    assert client.get(f"/api/objekte/{slug}/strom/2023").json()[
        "anschaffung_eur"] == 36000.0


def test_jahreswechsel_aendert_die_stammdaten_nicht(client):
    """Der Fehler, den N139 behebt: oben ein anderes Jahr wählen ließ die
    Anschaffung verschwinden. Die Stammdaten kennen kein Jahr."""
    slug = _neues_objekt(client)
    client.put(f"/api/objekte/{slug}/pv/stammdaten",
               json={"anschaffung_eur": 36000, "kwp": 19.44})
    vorher = _stammdaten(client, slug)

    # Durch die Jahre blättern, wie es die Maske tut (GET legt leere Sätze an).
    for jahr in (2021, 2022, 2023, 2024, 2025):
        client.get(f"/api/objekte/{slug}/strom/{jahr}")
        client.put(f"/api/objekte/{slug}/strom/{jahr}",
                   json={"pv_produktion_kwh": 1000 * (jahr - 2020)})
        assert _stammdaten(client, slug) == vorher

    # Und die Rechnung eines beliebigen Jahres kennt die Anschaffung trotzdem.
    r = client.get(f"/api/objekte/{slug}/strom/2022/rechnung").json()
    assert r["pv"]["anschaffung"] == 36000.0


def test_stammdaten_anteile_als_promille_mit_hinweis(client):
    """Die Anteile werden in Tausendsteln vergeben. Ergeben sie nicht 1000 ‰,
    gibt es einen ruhigen Hinweis — gespeichert wird trotzdem."""
    slug = _neues_objekt(client)

    krumm = client.put(f"/api/objekte/{slug}/pv/stammdaten", json={
        "anteile": '{"Roland": 800, "Marvin": 100}'}).json()
    assert krumm["anteile_summe"] == 900.0
    assert krumm["anteile_promille"] == {"Roland": 800.0, "Marvin": 100.0}
    assert len(krumm["hinweise"]) == 1
    assert "1000" in krumm["hinweise"][0] and "100" in krumm["hinweise"][0]
    # Ein Hinweis, keine Sperre: der Wert steht wirklich in der Datenbank.
    assert _stammdaten(client, slug)["anteile_summe"] == 900.0

    # 833,3 + 166,7 = 1000,0 — geht auf, kein Hinweis.
    rund = client.put(f"/api/objekte/{slug}/pv/stammdaten", json={
        "anteile": '{"Roland": 833.3, "Marvin": 166.7}'}).json()
    assert rund["anteile_summe"] == 1000.0
    assert rund["hinweise"] == []

    # Und die Verteilung des Ertrags folgt genau diesen Tausendsteln.
    client.put(f"/api/objekte/{slug}/strom/2025",
               json={"solar_kwh": 1000, "solar_preis": 1.0})
    r = client.get(f"/api/objekte/{slug}/strom/2025/rechnung").json()
    assert {x["anteil"] for x in r["eigentuemer"]} == {"Roland", "Marvin"}


def test_pv_eigentuemer_bietet_die_vorhandenen_personen_an(client):
    """Zugeordnet wird aus derselben Personenliste wie überall; der
    Objekt-Anteil steht als Vorschlag daneben, die gesetzten PV-Anteile kommen
    aus den Stammdaten."""
    slug = _neues_objekt(client)
    eid = client.post("/api/eigentuemer",
                      json={"name": "Roland", "email": "r@example.org"}).json()["id"]
    client.post(f"/api/objekte/{slug}/anteile",
                json={"eigentuemer_id": eid, "promille": 1000})
    client.put(f"/api/objekte/{slug}/pv/stammdaten",
               json={"anteile": '{"Roland": 1000}'})

    d = client.get(f"/api/objekte/{slug}/pv/eigentuemer").json()
    roland = next(p for p in d["personen"] if p["name"] == "Roland")
    assert roland["am_objekt"] == 1000.0
    assert d["pv_anteile"] == {"Roland": 1000.0}
    assert d["anteile_summe"] == 1000.0 and d["hinweise"] == []


# --------------------------------------------------------------------------
# N308 — die jährliche PV-Eigentümer-Abrechnung (statt eines kumulierten
# Standes) und ihr Versand.
# --------------------------------------------------------------------------

def _jahresabrechnung_objekt(c, roland_mail: str = "roland@example.invalid",
                             marvin_mail: str = "marvin@example.invalid") -> str:
    """Ein PV-Objekt mit zwei Eigentümern (700 ‰ / 300 ‰) und zwei Jahren mit
    unterschiedlicher Einspeisevergütung — verschieden genug, um kumuliert von
    „nur dieses Jahr" zu unterscheiden."""
    slug = _pv_objekt(c, "PV-Jahresabrechnung")
    c.post("/api/eigentuemer", json={"name": "Roland", "email": roland_mail})
    c.post("/api/eigentuemer", json={"name": "Marvin", "email": marvin_mail})
    c.put(f"/api/objekte/{slug}/pv/stammdaten",
         json={"anteile": '{"Roland": 700, "Marvin": 300}'})
    z24 = _zeitraum_id(c, slug, 2024)
    _position(c, z24, _EINSPEISUNG, 500.0)
    z25 = _zeitraum_id(c, slug, 2025)
    _position(c, z25, _EINSPEISUNG, 300.0)
    return slug


def test_jahresabrechnung_verteilt_nur_das_eine_jahr(client):
    """Der Kern von N308: die Abrechnung eines Jahres verteilt den Ertrag
    GENAU dieses Jahres — nicht den kumulierten Stand über alle Jahre."""
    slug = _jahresabrechnung_objekt(client)

    a = client.get(f"/api/objekte/{slug}/pv/jahresabrechnung",
                   params={"jahr": 2024}).json()
    assert a["ertrag"] == 500.0
    assert a["kumuliert_bis_jahr"] == 500.0
    eigentuemer = {e["name"]: e for e in a["eigentuemer"]}
    assert eigentuemer["Roland"]["betrag"] == 350.0      # 500 × 700 ‰
    assert eigentuemer["Marvin"]["betrag"] == 150.0      # 500 × 300 ‰
    assert round(sum(e["betrag"] for e in a["eigentuemer"]), 2) == 500.0
    # 2024 ist zugleich das erste Jahr — Jahresbetrag und kumulierter Anteil
    # fallen hier zusammen.
    assert eigentuemer["Roland"]["kumuliert_anteil"] == 350.0
    assert eigentuemer["Marvin"]["kumuliert_anteil"] == 150.0

    b = client.get(f"/api/objekte/{slug}/pv/jahresabrechnung",
                   params={"jahr": 2025}).json()
    assert b["ertrag"] == 300.0                # NICHT 800 (kumuliert)
    assert b["kumuliert_bis_jahr"] == 800.0
    eigentuemer_b = {e["name"]: e for e in b["eigentuemer"]}
    assert eigentuemer_b["Roland"]["betrag"] == 210.0    # 300 × 700 ‰
    assert eigentuemer_b["Marvin"]["betrag"] == 90.0     # 300 × 300 ‰
    # Der kumulierte Anteil zieht die Vorjahre mit — 800 × 700 ‰ = 560.
    assert eigentuemer_b["Roland"]["kumuliert_anteil"] == 560.0
    assert eigentuemer_b["Marvin"]["kumuliert_anteil"] == 240.0


def test_jahresabrechnung_ohne_zeitraum_zeigt_hinweis_statt_erfundener_zahl(client):
    """Ein Jahr ohne Abrechnungszeitraum bekommt keinen Betrag, sondern eine
    Erklärung — nie eine stille 0,00-€-Abrechnung."""
    slug = _jahresabrechnung_objekt(client)
    d = client.get(f"/api/objekte/{slug}/pv/jahresabrechnung",
                   params={"jahr": 1999}).json()
    assert d["ertrag"] is None
    assert d["eigentuemer"] == []
    assert "1999" in d["hinweis"]


class _Postfach:
    def __init__(self):
        self.gesendet = []

    def sende(self, an, betreff, text, anhang=None):
        self.gesendet.append((an, betreff, text, anhang))


def test_jahresabrechnung_versand_geht_an_die_hinterlegte_adresse(client,
                                                                   monkeypatch):
    from app.routers import strom as rs
    slug = _jahresabrechnung_objekt(client)
    postfach = _Postfach()
    monkeypatch.setattr(rs, "zugang", lambda session: postfach)

    antwort = client.post(f"/api/objekte/{slug}/pv/jahresabrechnung/versand",
                          json={"jahr": 2024, "name": "Roland"})
    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["an"] == "roland@example.invalid"
    assert antwort.json()["betrag"] == 350.0
    assert len(postfach.gesendet) == 1
    an, betreff, text, anhang = postfach.gesendet[0]
    assert an == "roland@example.invalid"
    assert "2024" in betreff
    assert "350,00 €" in text
    assert anhang is None                      # Informationsschreiben, kein PDF

    # Der ✓-Haken erscheint jetzt im Abruf …
    d = client.get(f"/api/objekte/{slug}/pv/jahresabrechnung",
                   params={"jahr": 2024}).json()
    roland = next(e for e in d["eigentuemer"] if e["name"] == "Roland")
    assert roland["versendet"] is True
    marvin = next(e for e in d["eigentuemer"] if e["name"] == "Marvin")
    assert marvin["versendet"] is False

    # … und ein zweiter Versand für dasselbe Jahr wird abgelehnt.
    zweiter = client.post(f"/api/objekte/{slug}/pv/jahresabrechnung/versand",
                          json={"jahr": 2024, "name": "Roland"})
    assert zweiter.status_code == 400
    assert "bereits erhalten" in zweiter.json()["detail"]
    assert len(postfach.gesendet) == 1          # kein zweiter Versand ausgelöst

    # Ein anderes Jahr ist davon unberührt.
    dritter = client.post(f"/api/objekte/{slug}/pv/jahresabrechnung/versand",
                          json={"jahr": 2025, "name": "Roland"})
    assert dritter.status_code == 200
    assert len(postfach.gesendet) == 2


def test_jahresabrechnung_versand_ohne_adresse_wird_abgelehnt(client,
                                                               monkeypatch):
    from app.routers import strom as rs
    slug = _jahresabrechnung_objekt(client, roland_mail="", marvin_mail="")
    postfach = _Postfach()
    monkeypatch.setattr(rs, "zugang", lambda session: postfach)

    antwort = client.post(f"/api/objekte/{slug}/pv/jahresabrechnung/versand",
                          json={"jahr": 2024, "name": "Roland"})
    assert antwort.status_code == 400
    assert "E-Mail" in antwort.json()["detail"]
    assert postfach.gesendet == []


def test_jahresabrechnung_versand_fuer_unbekanntes_jahr_wird_abgelehnt(client,
                                                                       monkeypatch):
    from app.routers import strom as rs
    slug = _jahresabrechnung_objekt(client)
    postfach = _Postfach()
    monkeypatch.setattr(rs, "zugang", lambda session: postfach)

    antwort = client.post(f"/api/objekte/{slug}/pv/jahresabrechnung/versand",
                          json={"jahr": 1999, "name": "Roland"})
    assert antwort.status_code == 400
    assert postfach.gesendet == []


def test_teil_put_setzt_die_uebrigen_felder_nicht_auf_null(client):
    """N150 — der PUT nahm frueher immer den ganzen Satz: wer nur einen Teil der
    Maske schickte, setzte alle uebrigen Felder still auf 0. Das hat real Daten
    gekostet (`pv_kwp` 12,0 und `anschaffung_eur` 35.700 fielen so auf 0)."""
    slug = _neues_objekt(client)
    client.put(f"/api/objekte/{slug}/strom/2025",
               json={"pv_kwp": 19.44, "anschaffung_eur": 35700.0,
                     "gesamt_kwh": 10800.0})
    # Ein zweiter Aufruf mit NUR den Mengen darf die Anlagenwerte stehen lassen.
    client.put(f"/api/objekte/{slug}/strom/2025",
               json={"netz_kwh": 2592.0, "solar_kwh": 5400.0, "akku_kwh": 2808.0})

    antwort = client.get(f"/api/objekte/{slug}/strom/2025").json()
    e = antwort.get("eingaben", antwort)
    assert e["pv_kwp"] == 19.44
    assert e["anschaffung_eur"] == 35700.0
    assert e["gesamt_kwh"] == 10800.0
    assert e["netz_kwh"] == 2592.0


# ---------------------------------------------------------------------------
# N153 — den Startbetrag der Amortisation aufschlüsseln.
#
# Die Jahre NACH der ersten Abrechnung zeigen im Verlauf schon, woher der Ertrag
# kam (Direktnutzung / Einspeisevergütung / E-Tanken). Beim Vorlauf stand bisher
# nur eine Gesamtzahl — der Anfang des Verlaufs war damit die einzige Stelle
# ohne Herkunft.
#
# Die Vorrang-Regel: ist die Aufschlüsselung gepflegt (mindestens eines der drei
# Felder ≠ 0), gilt IHRE SUMME als Vorlauf; sonst weiterhin
# `vorlauf_ertrag_eur`. So bleibt der bestehende Wert gültig, bis die Aufteilung
# eingetragen wird — und es gibt keine zwei Wahrheiten.
# ---------------------------------------------------------------------------

def test_vorlauf_aufschluesselung_speichern_und_lesen(client):
    """Die drei Felder überdauern das Speichern und kommen mit Summe und
    Herkunft zurück."""
    slug = _neues_objekt(client)
    gespeichert = client.put(f"/api/objekte/{slug}/pv/stammdaten", json={
        "anschaffung_eur": 35800, "vorlauf_pv_strom_eur": 1400.0,
        "vorlauf_einspeisung_eur": 955.0, "vorlauf_tanken_eur": 0.0}).json()
    assert gespeichert["vorlauf_pv_strom_eur"] == 1400.0
    assert gespeichert["vorlauf_einspeisung_eur"] == 955.0
    assert gespeichert["vorlauf_tanken_eur"] == 0.0

    gelesen = _stammdaten(client, slug)
    assert gelesen["vorlauf_summe"] == 2355.0
    assert gelesen["vorlauf_aufgeschluesselt"] is True
    assert gelesen["vorlauf_teile"] == {"pv_strom": 1400.0,
                                        "einspeisung": 955.0, "tanken": 0.0}


def test_vorlauf_summe_schlaegt_den_gesamtwert(client):
    """Ist die Aufschlüsselung gepflegt, gilt IHRE Summe — der alte Gesamtwert
    bleibt stehen (nie überschreiben), zählt aber nicht mehr."""
    slug = _neues_objekt(client)
    client.put(f"/api/objekte/{slug}/pv/stammdaten",
               json={"vorlauf_ertrag_eur": 9999.0})
    assert _stammdaten(client, slug)["vorlauf_summe"] == 9999.0

    client.put(f"/api/objekte/{slug}/pv/stammdaten",
               json={"vorlauf_pv_strom_eur": 1400.0,
                     "vorlauf_einspeisung_eur": 955.0})
    danach = _stammdaten(client, slug)
    assert danach["vorlauf_summe"] == 2355.0
    assert danach["vorlauf_ertrag_eur"] == 9999.0      # steht unangetastet da


def test_vorlauf_ohne_aufschluesselung_gilt_der_gesamtwert(client):
    """Solange keines der drei Felder gepflegt ist, bleibt es beim bisherigen
    Gesamtwert — der Bestand des Nutzers bleibt gültig."""
    slug = _neues_objekt(client)
    client.put(f"/api/objekte/{slug}/pv/stammdaten",
               json={"vorlauf_ertrag_eur": 2355.0, "vorlauf_pv_strom_eur": 0.0,
                     "vorlauf_einspeisung_eur": 0.0, "vorlauf_tanken_eur": 0.0})
    d = _stammdaten(client, slug)
    assert d["vorlauf_summe"] == 2355.0
    assert d["vorlauf_aufgeschluesselt"] is False
    assert d["vorlauf_teile"] is None


def test_vorlauf_teil_speichern_setzt_die_uebrigen_nicht_auf_null(client):
    """N150 — jedes Feld hat `None`-Default: wer nur den PV-Strom nachträgt,
    darf die Einspeisung nicht auf 0 setzen."""
    slug = _neues_objekt(client)
    client.put(f"/api/objekte/{slug}/pv/stammdaten", json={
        "vorlauf_pv_strom_eur": 1400.0, "vorlauf_einspeisung_eur": 955.0,
        "vorlauf_tanken_eur": 120.0})
    client.put(f"/api/objekte/{slug}/pv/stammdaten",
               json={"vorlauf_pv_strom_eur": 1500.0})

    d = _stammdaten(client, slug)
    assert d["vorlauf_pv_strom_eur"] == 1500.0
    assert d["vorlauf_einspeisung_eur"] == 955.0
    assert d["vorlauf_tanken_eur"] == 120.0
    assert d["vorlauf_summe"] == 2575.0


def test_vorlauf_bis_kommt_aus_dem_ersten_zeitraum(client):
    """Welcher Zeitraum gemeint ist, leitet sich aus den Daten ab: alles vor dem
    Beginn des ersten Abrechnungszeitraums. Kein Datum steht im Code."""
    slug = _pv_objekt(client, "PV-Vorlaufgrenze")
    _zeitraum_id(client, slug, 2025)
    start = _stammdaten(client, slug)["vorlauf_bis"]
    assert start is not None
    erster = min(z["start"] for z in
                 client.get(f"/api/objekte/{slug}").json()["zeitraeume"])
    assert start == erster


def test_verlauf_rechnet_mit_der_summe_der_aufschluesselung(client):
    """Der Verlauf nimmt die Summe der Aufschlüsselung als Vorlauf und hängt
    ihre Herkunft an die erste Zeile — die Jahre danach bleiben unberührt."""
    slug = _pv_objekt(client, "PV-Vorlaufteile")
    client.put(f"/api/objekte/{slug}/pv/stammdaten", json={
        "anschaffung_eur": 35800.0, "vorlauf_ertrag_eur": 9999.0,
        "vorlauf_pv_strom_eur": 1400.0, "vorlauf_einspeisung_eur": 955.0})
    for jahr in (2024, 2025):
        _position(client, _zeitraum_id(client, slug, jahr), _EINSPEISUNG, 1000.0)

    v = _verlauf(client, slug)
    assert v["vorlauf"] == 2355.0                 # die Summe, nicht die 9999
    assert v["vorlauf_aufgeschluesselt"] is True
    assert v["vorlauf_teile"] == {"pv_strom": 1400.0, "einspeisung": 955.0,
                                  "tanken": 0.0}
    # Eigene Zeile vor dem ersten Abrechnungsjahr (N153b).
    erstes = v["jahre"][0]
    assert erstes["jahr"] == v["vorlauf_jahr"] == 2023
    assert erstes["vorlauf"] == 2355.0
    assert erstes["vorlauf_teile"] == v["vorlauf_teile"]
    # Die Herkunft ist ein Zusatz, keine zweite Buchung.
    assert erstes["summe"] == 2355.0
    assert v["kumuliert"] == 4355.0
    assert all(z["vorlauf_teile"] is None for z in v["jahre"][1:])
    # Ohne Aufschlüsselung bleibt es beim Gesamtwert — ein Block, keine Herkunft.
    client.put(f"/api/objekte/{slug}/pv/stammdaten",
               json={"vorlauf_pv_strom_eur": 0.0, "vorlauf_einspeisung_eur": 0.0})
    ohne = _verlauf(client, slug)
    assert ohne["vorlauf"] == 9999.0
    assert ohne["vorlauf_aufgeschluesselt"] is False
    assert ohne["jahre"][0]["vorlauf_teile"] is None


def test_vorlauf_jahr_kommt_aus_dem_ersten_abrechnungsjahr(client):
    """Beim Nutzer beginnt die erste Abrechnung am 01.10.2024 und läuft als
    Jahr 2025 — der Vorlauf gehört auf 2024. Abgeleitet, nicht gesetzt."""
    slug = client.post("/api/objekte", json={
        "name": "PV-Oktober", "ort": "Teststadt", "turnus": "abweichend",
        "start_monat": 10, "kostenarten": ["Strom"],
        "einheiten": [{"bezeichnung": "EG", "flaeche": 70.0,
                       "partei": "Müller"}]}).json()["slug"]
    client.post(f"/api/objekte/{slug}/zeitraeume",
                json={"start": "2024-10-01", "ende": "2025-09-30"})
    client.put(f"/api/objekte/{slug}/pv/stammdaten",
               json={"anschaffung_eur": 35800.0,
                     "vorlauf_pv_strom_eur": 1798.50,
                     "vorlauf_einspeisung_eur": 556.86})

    v = _verlauf(client, slug)
    assert v["vorlauf"] == 2355.36
    assert v["vorlauf_jahr"] == 2024
    zeile = _jahr(v, 2024)
    assert zeile["vorlauf"] == 2355.36 and zeile["summe"] == 2355.36
    # Das erste Abrechnungsjahr trägt den Vorlauf nicht mehr mit.
    assert _jahr(v, 2025)["vorlauf"] == 0.0
    assert v["kumuliert"] == 2355.36


def test_autarkie_nimmt_die_verbraucherseite(client):
    """N154/N160 — die Quote beantwortet „wie viel meines Verbrauchs decke ich
    selbst": (Solar + Akku) / (Netz + Solar + Akku) = 8.208 / 10.800 = 76 %.
    Die Erzeugerseite (Produktion − Einspeisung = 8.375 kWh) geht ausdrücklich
    NICHT ein — mit ihr käme 77,5 % heraus, eine geschönte Antwort auf eine
    andere Frage."""
    slug = _neues_objekt(client)
    client.put(f"/api/objekte/{slug}/strom/2025", json={
        "netz_kwh": 2592.0, "solar_kwh": 5400.0, "akku_kwh": 2808.0,
        "pv_produktion_kwh": 12500.0, "einspeisung_kwh": 4125.0})

    a = client.get(f"/api/objekte/{slug}/strom/2025/rechnung").json()["autarkie"]
    assert a["eigen_kwh"] == 8208.0
    assert (a["solar_kwh"], a["akku_kwh"], a["netz_kwh"]) \
        == (5400.0, 2808.0, 2592.0)
    assert a["verbrauch_kwh"] == 10800.0
    assert a["prozent"] == 76.0
    # Die Erzeugerseite steht nicht in der Kennzahl — nur in der Vergütung.
    assert "erzeugung_selbst_genutzt_kwh" not in a


def test_autarkie_ohne_mengen_bleibt_leer(client):
    """Ohne erfasste Mengen gibt es keine Quote — lieber nichts als eine Zahl
    ohne Grundlage."""
    slug = _neues_objekt(client)
    a = client.get(f"/api/objekte/{slug}/strom/2025/rechnung").json()["autarkie"]
    assert a["prozent"] is None
    assert a["verbrauch_kwh"] == 0.0


# ---------------------------------------------------------------------------
# N174 — der Vorlauf des ersten Jahres wird in dieselben Quellenspalten
# aufgeschlüsselt wie die Jahre danach; es gibt keine eigene Vorlauf-Spalte
# mehr. Die Tabelle (Frontend) faltet dazu `vorlauf_teile` in die
# Quellenspalten. Diese Tests sichern den Backend-Kontrakt, auf dem das beruht:
# die drei aufgeschlüsselten Beträge summieren sich exakt auf die Jahressumme,
# und über alle Jahre gehen die gefalteten Spalten auf `kumuliert` auf.
# ---------------------------------------------------------------------------

_QUELLEN = ("pv_strom", "einspeisung", "tanken")


def _gefaltete_spalte(z: dict, feld: str, vorlauf_jahr) -> float:
    """So faltet die Tabelle (N174) eine Quellenspalte einer Zeile: der eigene
    Jahreswert plus — im Vorlaufjahr — der aufgeschlüsselte Vorlauf-Anteil. Ist
    der Vorlauf nicht aufgeschlüsselt, steht sein Gesamtbetrag in PV-Strom."""
    wert = z.get(feld) or 0.0
    if z["jahr"] == vorlauf_jahr:
        if z.get("vorlauf_teile"):
            wert += z["vorlauf_teile"].get(feld) or 0.0
        elif feld == "pv_strom":
            wert += z.get("vorlauf") or 0.0
    return round(wert, 2)


def _okt_objekt(c, name: str):
    """Ein Objekt mit abweichendem Wirtschaftsjahr ab Oktober — wie beim echten
    Objekt (erste Abrechnung 01.10.2024–30.09.2025, Label-Jahr 2025)."""
    return c.post("/api/objekte", json={
        "name": name, "ort": "Teststadt", "turnus": "abweichend",
        "start_monat": 10, "kostenarten": ["Strom"],
        "einheiten": [{"bezeichnung": "EG", "flaeche": 70.0,
                       "partei": "Müller"}]}).json()["slug"]


def test_verlauf_vorlauf_faellt_in_die_quellenspalten(client):
    """Das echte Objekt: erste Abrechnung 01.10.2024–30.09.2025 (Label 2025),
    Vorlauf PV-Strom 1.798,50 € + Einspeisung 556,86 € = 2.355,36 €. Der Vorlauf
    landet in den Quellenspalten des Jahres 2024, nicht in einer eigenen
    Spalte."""
    slug = _okt_objekt(client, "PV-N174")
    client.post(f"/api/objekte/{slug}/zeitraeume",
                json={"start": "2024-10-01", "ende": "2025-09-30"})
    client.put(f"/api/objekte/{slug}/pv/stammdaten",
               json={"anschaffung_eur": 35800.0,
                     "vorlauf_pv_strom_eur": 1798.50,
                     "vorlauf_einspeisung_eur": 556.86})

    v = _verlauf(client, slug)
    assert v["vorlauf_jahr"] == 2024

    zeile = _jahr(v, 2024)
    # Die Vorlaufzeile trägt die drei aufgeschlüsselten Quellen, nicht eine Summe.
    assert zeile["vorlauf_teile"] == {"pv_strom": 1798.50,
                                      "einspeisung": 556.86, "tanken": 0.0}
    # Gefaltet ergeben die drei Spalten der Zeile genau ihre Summe.
    gefaltet = {q: _gefaltete_spalte(zeile, q, v["vorlauf_jahr"])
                for q in _QUELLEN}
    assert gefaltet == {"pv_strom": 1798.50, "einspeisung": 556.86,
                        "tanken": 0.0}
    assert round(sum(gefaltet.values()), 2) == zeile["summe"] == 2355.36

    # Über alle Jahre gehen die gefalteten Quellenspalten auf `kumuliert` auf —
    # ganz ohne eigene Vorlauf-Spalte.
    spalten = {q: round(sum(_gefaltete_spalte(z, q, v["vorlauf_jahr"])
                            for z in v["jahre"]), 2) for q in _QUELLEN}
    assert spalten == {"pv_strom": 1798.50, "einspeisung": 556.86,
                       "tanken": 0.0}
    assert round(sum(spalten.values()), 2) == v["kumuliert"] == 2355.36


def test_verlauf_folgejahr_ohne_ertraege_bleibt_ehrlich_null(client):
    """Ein Abrechnungsjahr nach dem Vorlauf ohne PV-Ertrag zeigt in allen
    Quellenspalten ehrlich 0 — der kumulierte Stand bleibt stehen. So sieht der
    Verlauf des echten Objekts aus: 2024 Vorlauf, 2025/2026 (noch) ohne
    Erträge, weil dort keine „eigen"-Position, keine nicht umlagefähige
    Kostenart und keine Ladung erfasst ist (N174)."""
    slug = _okt_objekt(client, "PV-N174-Null")
    client.post(f"/api/objekte/{slug}/zeitraeume",
                json={"start": "2024-10-01", "ende": "2025-09-30"})
    client.post(f"/api/objekte/{slug}/zeitraeume",
                json={"start": "2025-10-01", "ende": "2026-09-30"})
    client.put(f"/api/objekte/{slug}/pv/stammdaten",
               json={"anschaffung_eur": 35800.0,
                     "vorlauf_pv_strom_eur": 1798.50,
                     "vorlauf_einspeisung_eur": 556.86})

    v = _verlauf(client, slug)
    assert v["vorlauf_jahr"] == 2024
    for jahr in (2025, 2026):
        z = _jahr(v, jahr)
        assert (z["pv_strom"], z["einspeisung"], z["tanken"], z["summe"]) \
            == (0.0, 0.0, 0.0, 0.0)
        assert z["kumuliert"] == 2355.36      # der Vorlauf bleibt stehen


def test_verlauf_unaufgeschluesselter_vorlauf_geht_in_pv_strom(client):
    """Ist nur der Gesamt-Vorlauf gepflegt (keine Aufschlüsselung), zeigt die
    Tabelle ihn in der PV-Strom-Spalte mit dem Hinweis „nicht aufgeschlüsselt" —
    statt eine Spalte wieder einzuführen. Der Backend-Kontrakt dafür:
    `vorlauf_teile` ist None, `vorlauf` trägt den Gesamtbetrag (N174)."""
    slug = _okt_objekt(client, "PV-N174-Roh")
    client.post(f"/api/objekte/{slug}/zeitraeume",
                json={"start": "2024-10-01", "ende": "2025-09-30"})
    client.put(f"/api/objekte/{slug}/pv/stammdaten",
               json={"anschaffung_eur": 35800.0, "vorlauf_ertrag_eur": 2355.36})

    v = _verlauf(client, slug)
    assert v["vorlauf_aufgeschluesselt"] is False
    zeile = _jahr(v, v["vorlauf_jahr"])
    assert zeile["vorlauf_teile"] is None
    # Der Gesamtbetrag fällt in die PV-Strom-Spalte, die übrigen bleiben 0.
    assert _gefaltete_spalte(zeile, "pv_strom", v["vorlauf_jahr"]) == 2355.36
    assert _gefaltete_spalte(zeile, "einspeisung", v["vorlauf_jahr"]) == 0.0
    assert _gefaltete_spalte(zeile, "tanken", v["vorlauf_jahr"]) == 0.0
    assert zeile["summe"] == 2355.36
