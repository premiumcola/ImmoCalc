"""N405 — eine leere Position ohne Beleg schließen ("fällt nicht an").

Anders als `bestaetigt` (N364, Heizöl-Sammelposition) gilt `entfaellt` für
eine einzelne Position, die für DIESEN Zeitraum schlicht nicht anfällt (z. B.
Heizungswartung ohne Rechnung dieses Jahr). Die Position bleibt sichtbar,
zählt aber nicht mehr zu „ohne Betrag" und blockiert den Abschluss nicht.
"""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(),
                                     "test_position_entfaellt.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def _zeile(c, name):
    z = c.get("/api/zeitraeume/1").json()
    return next((k for k in z["checkliste"] if k["kostenart"] == name), None)


def test_entfaellt_ist_umkehrbar():
    with TestClient(app) as c:
        pid = c.post("/api/zeitraeume/1/positionen",
                     json={"kostenart": "Wartung-N405", "betrag": 0}
                     ).json()["id"]
        gesetzt = c.patch(f"/api/positionen/{pid}", json={"entfaellt": True})
        assert gesetzt.status_code == 200, gesetzt.text
        zeile = _zeile(c, "Wartung-N405")
        assert zeile["entfaellt"] is True
        assert zeile["zustand"] == "entfaellt"
        assert zeile["erledigt"] is False

        c.patch(f"/api/positionen/{pid}", json={"entfaellt": False})
        assert _zeile(c, "Wartung-N405")["entfaellt"] is False


def test_entfallene_position_blockiert_abschluss_nicht():
    with TestClient(app) as c:
        pid = c.post("/api/zeitraeume/1/positionen",
                     json={"kostenart": "Wartung-N405b", "betrag": 0}
                     ).json()["id"]
        c.patch(f"/api/positionen/{pid}", json={"entfaellt": True})
        abrechnung = c.get("/api/zeitraeume/1/abrechnung").json()
        assert "Wartung-N405b" not in abrechnung["ohne_betrag"]
        assert "Wartung-N405b" not in abrechnung["offen"]


def test_neue_position_ist_nicht_entfallen():
    with TestClient(app) as c:
        c.post("/api/zeitraeume/1/positionen",
               json={"kostenart": "Wartung-N405c", "betrag": 120.0})
        assert _zeile(c, "Wartung-N405c")["entfaellt"] is False
