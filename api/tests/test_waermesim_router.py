"""N340l — der Wärmesimulator-Endpunkt: reine Weiterleitung an `waermesim.rechne`."""
import os
import sys
import tempfile

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test_wsim_r.db"))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def test_leere_eingabe_ergibt_nullwertige_aufstellung():
    with TestClient(app) as c:
        antwort = c.post("/api/waermesim/rechne", json={})
    assert antwort.status_code == 200
    erg = antwort.json()
    assert erg["nutzer"] == []
    assert erg["heizung"]["gesamt"] == 0.0


def test_brennstoff_und_energie_stimmen_mit_der_abrechnung_ueberein():
    """Reine Durchleitung geprüft — die volle Domänenprobe mit allen neun
    Nutzern steht in `test_waermesim.py`, direkt gegen `waermesim.rechne`."""
    eingabe = {
        "heizwert": 10.0,
        "bestaende": [
            {"liter": 1990.0, "eur": 1430.21},
            {"liter": 1000.0, "eur": 765.17},
            {"liter": 1000.0, "eur": 777.07},
            {"liter": 2000.0, "eur": 1560.09},
        ],
        "rest": {"liter": 1544.0, "eur": 1204.39},
        "ww_m3": 30.110,
    }
    with TestClient(app) as c:
        erg = c.post("/api/waermesim/rechne", json=eingabe).json()
    assert erg["brennstoff"]["liter"] == 4446.0
    assert erg["brennstoff"]["eur"] == 3328.15
    assert erg["energie"]["gesamt_kwh"] == 44460.0
    assert round(erg["anteile"]["warmwasser"] * 100, 2) == 8.47
