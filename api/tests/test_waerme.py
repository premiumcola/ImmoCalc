"""N80/N81 — Wärme aus Öl splitten und Heizungswärme über HKV verteilen.

Drei Ebenen: die reine Engine (`app.waerme`) mit dem Kernbeispiel, den
Randfällen und der Cent-Summe; und die Endpunkte (Split, Verteilung, HKV-CRUD).
"""
import os
import sys
import tempfile
from types import SimpleNamespace

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_waerme.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import waerme  # noqa: E402
from app.main import app  # noqa: E402


# --------------------------------------------------------------------------
# 1) N80 — Wärmemengen-Formeln (§9 HeizkostenV)
# --------------------------------------------------------------------------

def test_warmwasser_kwh_formel():
    # Q = 2,5 · V · (t − 10); 11 m³ bei 60 °C → 2,5·11·50 = 1375 kWh.
    assert waerme.warmwasser_kwh(11.0, 60.0) == 1375.0
    # Standardtemperatur 60 °C.
    assert waerme.warmwasser_kwh(11.0) == 1375.0
    # 20 m³ bei 55 °C → 2,5·20·45 = 2250 kWh.
    assert waerme.warmwasser_kwh(20.0, 55.0) == 2250.0
    # Negatives/leeres Volumen → 0.
    assert waerme.warmwasser_kwh(0.0) == 0.0
    assert waerme.warmwasser_kwh(-5.0, 60.0) == 0.0


def test_oel_kwh_formel():
    # Liter × Heizwert (Standard 10 kWh/L).
    assert waerme.oel_kwh(3500.0) == 35000.0
    assert waerme.oel_kwh(3500.0, 10.0) == 35000.0
    # Anderer Heizwert.
    assert waerme.oel_kwh(1000.0, 9.8) == 9800.0
    assert waerme.oel_kwh(0.0) == 0.0


# --------------------------------------------------------------------------
# 2) N80 — split_oel: Kernbeispiel + Randfälle + Cent-Summe
# --------------------------------------------------------------------------

def test_split_oel_kernbeispiel():
    # oel_kosten=2700, oel_liter=3500 (→35000 kWh), ww=11 m³ @60 °C (→1375 kWh)
    e = waerme.split_oel(2700.0, 3500.0, 11.0, temp_c=60.0)
    assert e["ww_kwh"] == 1375.0
    assert e["gesamt_kwh"] == 35000.0
    assert e["ww_anteil"] == round(1375.0 / 35000.0, 6)   # ≈ 0,039286
    assert e["ww_kosten"] == 106.07
    assert e["heizung_kosten"] == 2593.93
    # Cent-sauber: exakt die Öl-Kosten.
    assert e["ww_kosten"] + e["heizung_kosten"] == 2700.0
    assert "warnung" not in e


def test_split_oel_kein_oel_alles_heizung():
    # gesamt_kwh 0 → alles Heizung, ww_anteil 0.
    e = waerme.split_oel(2700.0, 0.0, 11.0)
    assert e["gesamt_kwh"] == 0.0
    assert e["ww_anteil"] == 0.0
    assert e["ww_kosten"] == 0.0
    assert e["heizung_kosten"] == 2700.0


def test_split_oel_ww_uebersteigt_gesamt_deckel_und_warnung():
    # Sehr viel Warmwasser, wenig Öl: Anteil auf 1 gedeckelt, Warnung gesetzt.
    e = waerme.split_oel(1000.0, 10.0, 50.0, temp_c=60.0)  # ww=6250, gesamt=100 kWh
    assert e["ww_anteil"] == 1.0
    assert e["ww_kosten"] == 1000.0
    assert e["heizung_kosten"] == 0.0
    assert "warnung" in e
    # Cent-sauber auch im Deckel-Fall.
    assert e["ww_kosten"] + e["heizung_kosten"] == 1000.0


def test_split_oel_cent_summe_bei_krummen_werten():
    for kosten, liter, vol, t in [
            (2700.0, 3500.0, 11.0, 60.0),
            (1234.56, 2871.0, 7.3, 55.0),
            (999.99, 1000.0, 3.0, 60.0),
            (500.0, 4000.0, 0.0, 60.0),      # kein Warmwasser
            (0.0, 3500.0, 11.0, 60.0)]:      # keine Kosten
        e = waerme.split_oel(kosten, liter, vol, temp_c=t)
        assert e["ww_kosten"] + e["heizung_kosten"] == round(kosten, 2), (
            kosten, liter, vol, t)


# --------------------------------------------------------------------------
# 3) N81 — verteile_heizung über HKV-Faktoren
# --------------------------------------------------------------------------

def _hkv(einheit, faktor, stand):
    """Ein Test-HKV als leichtes Objekt (die Engine liest per getattr)."""
    return SimpleNamespace(einheit=einheit, faktor=faktor, einheiten_stand=stand)


def test_verteile_heizung_drei_hkv_zwei_einheiten():
    # EG: Faktor 1,0 × 100 = 100 · Faktor 1,0 × 50 = 50 → 150
    # OG: Faktor 1,2 × 125 = 150 → 150
    # Summe 300 → 3000 € je 1500 €.
    hkv = [_hkv("EG", 1.0, 100.0), _hkv("EG", 1.0, 50.0), _hkv("OG", 1.2, 125.0)]
    v = waerme.verteile_heizung(hkv, 3000.0)
    assert v == {"EG": 1500.0, "OG": 1500.0}
    assert round(sum(v.values()), 2) == 3000.0


def test_verteile_heizung_cent_genau():
    # Krumme Gewichte auf drei Einheiten → Summe bleibt exakt.
    hkv = [_hkv("A", 1.0, 33.0), _hkv("B", 1.0, 33.0), _hkv("C", 1.0, 34.0)]
    v = waerme.verteile_heizung(hkv, 100.0)
    assert round(sum(v.values()), 2) == 100.0


def test_verteile_heizung_ohne_gewichte_leer():
    # Keine Ablesung (Stand 0) oder Faktor 0 → keine Verteilung möglich.
    assert waerme.verteile_heizung([_hkv("EG", 1.0, 0.0)], 3000.0) == {}
    assert waerme.verteile_heizung([_hkv("EG", 0.0, 100.0)], 3000.0) == {}
    assert waerme.verteile_heizung([], 3000.0) == {}


# --------------------------------------------------------------------------
# 4) Endpunkte
# --------------------------------------------------------------------------

@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _neues_objekt(c) -> str:
    antwort = c.post("/api/objekte", json={
        "name": "Wärmehaus", "ort": "Teststadt", "turnus": "kalender",
        "start_monat": 1, "kostenarten": ["Heizung"],
        "einheiten": [{"bezeichnung": "EG", "flaeche": 70.0, "partei": "Müller"},
                      {"bezeichnung": "OG", "flaeche": 80.0, "partei": "Meier"}],
    })
    assert antwort.status_code == 201
    return antwort.json()["slug"]


def test_endpunkt_hkv_crud(client):
    slug = _neues_objekt(client)
    r = client.post(f"/api/objekte/{slug}/heizverteiler", json={
        "einheit": "EG", "nummer": "HKV-1", "raum": "Wohnzimmer",
        "faktor": 1.2, "einheiten_stand": 100.0})
    assert r.status_code == 201
    hid = r.json()["id"]
    assert r.json()["gewicht"] == round(1.2 * 100.0, 4)

    liste = client.get(f"/api/objekte/{slug}/heizverteiler").json()
    assert len(liste["heizverteiler"]) == 1

    # Jährliche Ablesung nachtragen.
    p = client.patch(f"/api/heizverteiler/{hid}", json={"einheiten_stand": 150.0})
    assert p.status_code == 200
    assert p.json()["einheiten_stand"] == 150.0

    assert client.delete(f"/api/heizverteiler/{hid}").json() == {"ok": True}
    assert client.get(f"/api/objekte/{slug}/heizverteiler").json()[
        "heizverteiler"] == []


def test_endpunkt_split(client):
    slug = _neues_objekt(client)
    e = client.get(f"/api/objekte/{slug}/waerme/split", params={
        "oel_kosten": 2700, "oel_liter": 3500, "ww_volumen_m3": 11,
        "temp_c": 60}).json()
    assert e["ww_kwh"] == 1375.0
    assert e["gesamt_kwh"] == 35000.0
    assert e["ww_kosten"] == 106.07
    assert e["heizung_kosten"] == 2593.93
    assert e["ww_kosten"] + e["heizung_kosten"] == 2700.0


def test_endpunkt_verteilung(client):
    slug = _neues_objekt(client)
    for einheit, faktor, stand in [("EG", 1.0, 100.0), ("EG", 1.0, 50.0),
                                   ("OG", 1.2, 125.0)]:
        client.post(f"/api/objekte/{slug}/heizverteiler", json={
            "einheit": einheit, "faktor": faktor, "einheiten_stand": stand})
    v = client.get(f"/api/objekte/{slug}/heizung/verteilung",
                   params={"kosten": 3000}).json()
    assert v == {"EG": 1500.0, "OG": 1500.0}


def test_endpunkt_verteilung_ohne_hkv_leer(client):
    slug = _neues_objekt(client)
    v = client.get(f"/api/objekte/{slug}/heizung/verteilung",
                   params={"kosten": 3000}).json()
    assert v == {}
