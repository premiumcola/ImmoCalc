"""N79 — Heizöl-Lieferungen und FIFO-Bewertung.

Zwei Ebenen: die reine Engine (`app.heizoel.verbrauch_bewerten`) mit dem
FIFO-Kernfall aus der Nutzer-Beschreibung, den Randfällen und der Cent-Summe;
und die Endpunkte (anlegen/lesen/ändern/löschen/bewerten).
"""
import os
import sys
import tempfile
from datetime import date
from types import SimpleNamespace

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_heizoel.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import heizoel  # noqa: E402
from app.main import app  # noqa: E402


def _lief(datum, liter, wert, lid=None, anfang=False):
    """Eine Test-Lieferung als leichtes Objekt (die Engine liest per getattr)."""
    return SimpleNamespace(id=lid, datum=datum, liter=liter, wert=wert,
                           ist_anfangsbestand=anfang)


# --------------------------------------------------------------------------
# 1) FIFO-Kernfall aus der Nutzer-Beschreibung
#    Anfangsbestand 1000 L @ 700 € · +3000 L @ 2400 € · +2000 L @ 1900 €
#    Gesamt: 6000 L / 5000 €. Verbrauch 3500 L.
# --------------------------------------------------------------------------

def _drei_lieferungen():
    return [
        _lief(date(2024, 1, 1), 1000.0, 700.0, lid=1, anfang=True),   # 0,70 €/L
        _lief(date(2024, 3, 1), 3000.0, 2400.0, lid=2),               # 0,80 €/L
        _lief(date(2024, 9, 1), 2000.0, 1900.0, lid=3),               # 0,95 €/L
    ]


def test_fifo_kernfall_aeltestes_zuerst():
    e = heizoel.verbrauch_bewerten(_drei_lieferungen(), 3500.0)
    # 1000 L @ 0,70 = 700 · 2500 L @ 0,80 = 2000 → 2700 € verbraucht
    assert e["verbrauch_liter"] == 3500.0
    assert e["verbrauch_kosten"] == 2700.0
    # Rest 2500 L: 500 L @ 0,80 = 400 · 2000 L @ 0,95 = 1900 → 2300 €
    assert e["rest_liter"] == 2500.0
    assert e["rest_wert"] == 2300.0
    # Schnittpreis des Verbrauchs: 2700 / 3500
    assert e["preis_schnitt"] == round(2700.0 / 3500.0, 4)   # 0,7714
    assert "warnung" not in e
    # Cent-sauber: Verbrauch + Rest == Gesamtwert
    assert e["verbrauch_kosten"] + e["rest_wert"] == 5000.0


def test_fifo_verbrauch_genau_eine_lieferung():
    # Verbrauch 1000 L trifft genau den Anfangsbestand (0,70 €/L).
    e = heizoel.verbrauch_bewerten(_drei_lieferungen(), 1000.0)
    assert e["verbrauch_kosten"] == 700.0
    assert e["rest_liter"] == 5000.0
    assert e["rest_wert"] == 4300.0
    assert e["preis_schnitt"] == 0.7


def test_reihenfolge_egal_sortierung_nach_datum():
    # Auch wenn die Liste verdreht kommt, gilt FIFO nach Datum/id.
    l = _drei_lieferungen()
    e = heizoel.verbrauch_bewerten([l[2], l[0], l[1]], 3500.0)
    assert e["verbrauch_kosten"] == 2700.0
    assert e["rest_wert"] == 2300.0


# --------------------------------------------------------------------------
# 2) Randfälle
# --------------------------------------------------------------------------

def test_verbrauch_uebersteigt_bestand_warnung():
    e = heizoel.verbrauch_bewerten(_drei_lieferungen(), 7000.0)
    assert e["verbrauch_liter"] == 6000.0          # gedeckelt auf den Bestand
    assert e["verbrauch_kosten"] == 5000.0         # alles verbraucht
    assert e["rest_liter"] == 0.0
    assert e["rest_wert"] == 0.0
    assert "warnung" in e
    assert "1000" in e["warnung"]                  # Fehlmenge 1000 L


def test_verbrauch_null_rest_ist_gesamt():
    e = heizoel.verbrauch_bewerten(_drei_lieferungen(), 0.0)
    assert e["verbrauch_kosten"] == 0.0
    assert e["preis_schnitt"] == 0.0
    assert e["rest_liter"] == 6000.0
    assert e["rest_wert"] == 5000.0
    assert "warnung" not in e


def test_kein_bestand_kosten_null():
    e = heizoel.verbrauch_bewerten([], 500.0)
    assert e["verbrauch_liter"] == 0.0
    assert e["verbrauch_kosten"] == 0.0
    assert e["rest_liter"] == 0.0
    assert e["rest_wert"] == 0.0
    assert e["preis_schnitt"] == 0.0


def test_negativer_verbrauch_wie_null():
    e = heizoel.verbrauch_bewerten(_drei_lieferungen(), -100.0)
    assert e["verbrauch_kosten"] == 0.0
    assert e["rest_liter"] == 6000.0


# --------------------------------------------------------------------------
# 3) Cent-Sauberkeit bei krummen Preisen
# --------------------------------------------------------------------------

def test_cent_summe_bei_krummem_preis():
    # 3 L @ 1,00 € → 0,3333… €/L. Verbrauch 1 L.
    lief = [_lief(date(2024, 1, 1), 3.0, 1.0, lid=1)]
    e = heizoel.verbrauch_bewerten(lief, 1.0)
    # Cent-sauber: die beiden Teile addieren sich exakt zum Gesamtwert.
    assert e["verbrauch_kosten"] + e["rest_wert"] == 1.0
    assert e["verbrauch_kosten"] == 0.33
    assert e["rest_wert"] == 0.67


def test_cent_summe_mehrere_lieferungen():
    lief = [
        _lief(date(2024, 1, 1), 700.0, 511.0, lid=1),    # 0,73 €/L
        _lief(date(2024, 6, 1), 1234.0, 999.54, lid=2),  # krumm
        _lief(date(2024, 9, 1), 333.0, 289.71, lid=3),
    ]
    gesamt = round(511.0 + 999.54 + 289.71, 2)
    for verbrauch in (0.0, 350.5, 700.0, 1500.0, 2267.0, 5000.0):
        e = heizoel.verbrauch_bewerten(lief, verbrauch)
        assert e["verbrauch_kosten"] + e["rest_wert"] == gesamt, verbrauch


# --------------------------------------------------------------------------
# 4) Endpunkte
# --------------------------------------------------------------------------

@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _neues_objekt(c) -> str:
    antwort = c.post("/api/objekte", json={
        "name": "Ölhaus", "ort": "Teststadt", "turnus": "kalender",
        "start_monat": 1, "kostenarten": ["Heizung"],
        "einheiten": [{"bezeichnung": "EG", "flaeche": 70.0, "partei": "Müller"}],
    })
    assert antwort.status_code == 201
    return antwort.json()["slug"]


def test_endpunkt_anlegen_lesen_bestand(client):
    slug = _neues_objekt(client)
    # Anfangsbestand + zwei Lieferungen anlegen.
    for datum, liter, wert, anfang in [
            ("2024-01-01", 1000.0, 700.0, True),
            ("2024-03-01", 3000.0, 2400.0, False),
            ("2024-09-01", 2000.0, 1900.0, False)]:
        r = client.post(f"/api/objekte/{slug}/heizoel", json={
            "datum": datum, "liter": liter, "wert": wert,
            "ist_anfangsbestand": anfang})
        assert r.status_code == 201
        assert r.json()["preis_liter"] == round(wert / liter, 4)

    daten = client.get(f"/api/objekte/{slug}/heizoel").json()
    assert len(daten["lieferungen"]) == 3
    # FIFO-sortiert: Anfangsbestand zuerst.
    assert daten["lieferungen"][0]["ist_anfangsbestand"] is True
    assert daten["bestand_liter"] == 6000.0
    assert daten["bestand_wert"] == 5000.0


def test_endpunkt_bewertung(client):
    slug = _neues_objekt(client)
    for datum, liter, wert in [
            ("2024-01-01", 1000.0, 700.0),
            ("2024-03-01", 3000.0, 2400.0),
            ("2024-09-01", 2000.0, 1900.0)]:
        client.post(f"/api/objekte/{slug}/heizoel", json={
            "datum": datum, "liter": liter, "wert": wert})
    e = client.get(f"/api/objekte/{slug}/heizoel/bewertung",
                   params={"verbrauch_liter": 3500}).json()
    assert e["verbrauch_kosten"] == 2700.0
    assert e["rest_wert"] == 2300.0
    assert e["rest_liter"] == 2500.0


def test_endpunkt_patch_und_delete(client):
    slug = _neues_objekt(client)
    lid = client.post(f"/api/objekte/{slug}/heizoel", json={
        "datum": "2024-01-01", "liter": 1000.0, "wert": 700.0}).json()["id"]

    # Fehleingabe korrigieren.
    r = client.patch(f"/api/heizoel/{lid}", json={"liter": 1200.0, "wert": 900.0})
    assert r.status_code == 200
    assert r.json()["liter"] == 1200.0
    assert r.json()["preis_liter"] == round(900.0 / 1200.0, 4)

    # Löschen (bewusste Nutzeraktion an genau diesem Zusatz-Datensatz).
    assert client.delete(f"/api/heizoel/{lid}").json() == {"ok": True}
    assert client.get(f"/api/objekte/{slug}/heizoel").json()["lieferungen"] == []


def test_endpunkt_bewertung_ohne_bestand(client):
    slug = _neues_objekt(client)
    e = client.get(f"/api/objekte/{slug}/heizoel/bewertung",
                   params={"verbrauch_liter": 500}).json()
    assert e["verbrauch_kosten"] == 0.0
    assert e["rest_liter"] == 0.0
