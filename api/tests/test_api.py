import os, tempfile
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
import sys; sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from fastapi.testclient import TestClient
from app.main import app


def test_api_end_to_end():
    with TestClient(app) as c:
        assert c.get("/api/health").json()["status"] == "ok"
        objekte = c.get("/api/objekte").json()
        assert len(objekte) == 2

        gesamt_list = []
        for o in objekte:
            det = c.get("/api/objekte/" + o["slug"]).json()
            for z in det["zeitraeume"]:
                ab = c.get(f"/api/zeitraeume/{z['id']}/abrechnung").json()
                gesamt_list.append(ab)

        # Zahlen-Fixture (fiktive Demo, echte Werte anonymisiert): Auslagen 3121.33 -> Saldo -481.33
        assert any(abs(g["gesamt"]["auslagen"] - 3121.33) < 1e-6
                   and g["gesamt"]["saldo"] == -481.33 for g in gesamt_list)
        # ein anderes Objekt hat eine offene Position (Grundsteuer)
        assert any("Grundsteuer" in g.get("offen", []) for g in gesamt_list)
