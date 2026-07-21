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


def test_objektliste_nennt_die_einheiten():
    """CXLV — die Startseite zeigt Bubbles je Einheit, also muss die Liste
    die Einheiten mitliefern. `einheiten` bleibt daneben die Anzahl."""
    with TestClient(app) as c:
        objekte = {o["slug"]: o for o in c.get("/api/objekte").json()}

        haus = objekte["obj-a"]
        assert haus["einheiten"] == 4                      # weiterhin die Anzahl
        assert [e["bezeichnung"] for e in haus["einheiten_liste"]] == [
            "1. OG", "2. OG", "EG / Büro", "Garage"]
        assert [e["flaeche"] for e in haus["einheiten_liste"]] == [78, 85, 40, None]
        assert all(e["vermietet"] for e in haus["einheiten_liste"])

        # Bestehende Felder bleiben — die Ergänzung ist rein additiv.
        for feld in ("id", "slug", "name", "ort", "anzeigename", "strasse",
                     "plz", "typ", "turnus", "aktiv", "offene_positionen",
                     "frist_tage", "miete_monatlich"):
            assert feld in haus


def test_leerstand_ist_an_der_einheit_erkennbar():
    """Eine Einheit ohne laufendes Mietverhältnis gilt als nicht vermietet."""
    with TestClient(app) as c:
        neu = c.post("/api/objekte", json={
            "name": "Prüfweg 9", "einheiten": [
                {"bezeichnung": "EG links", "flaeche": 60, "partei": "Mieter A"},
                {"bezeichnung": "EG rechts", "flaeche": 62}]}).json()
        objekt = next(o for o in c.get("/api/objekte").json()
                      if o["slug"] == neu["slug"])
        assert objekt["einheiten"] == 2
        assert [e["vermietet"] for e in objekt["einheiten_liste"]] == [False, False]

        c.post(f"/api/objekte/{neu['slug']}/mieten", json={
            "einheit": "EG links", "partei": "Mieter A", "kaltmiete": 700,
            "ab_datum": "2024-01-01"})
        objekt = next(o for o in c.get("/api/objekte").json()
                      if o["slug"] == neu["slug"])
        assert [e["vermietet"] for e in objekt["einheiten_liste"]] == [True, False]
        assert objekt["miete_monatlich"] == 700.0
