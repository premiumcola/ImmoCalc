"""Objekt anlegen, Stammdaten pflegen, Auswertung rechnen."""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_stammdaten.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def test_objekt_anlegen_und_auswerten():
    with TestClient(app) as c:
        vorher = len(c.get("/api/objekte").json())

        neu = c.post("/api/objekte", json={
            "name": "Teststraße 7", "ort": "Musterstadt", "turnus": "kalender",
            "start_monat": 1, "kostenarten": ["Wasser", "Müll"],
            "einheiten": [{"bezeichnung": "EG", "flaeche": 70.0, "partei": "Mieter A"}],
        })
        assert neu.status_code == 201
        slug = neu.json()["slug"]
        assert slug == "teststrasse-7"          # Umlaute/ß werden übersetzt

        objekte = c.get("/api/objekte").json()
        assert len(objekte) == vorher + 1

        # Das neue Objekt hat sofort einen laufenden Zeitraum und eine Frist.
        det = c.get(f"/api/objekte/{slug}").json()
        assert len(det["zeitraeume"]) == 1
        assert det["zeitraeume"][0]["frist_tage"] is not None
        assert len(det["einheiten"]) == 1
        assert [k["name"] for k in c.get(f"/api/objekte/{slug}/kostenarten").json()] \
            == ["Wasser", "Müll"]

        # Stammdaten anlegen
        assert c.post(f"/api/objekte/{slug}/mieten", json={
            "einheit": "EG", "partei": "Mieter A", "kaltmiete": 800.0,
            "nebenkosten_vz": 150.0, "ab_datum": "2025-01-01"}).status_code == 201
        assert c.post(f"/api/objekte/{slug}/versicherungen", json={
            "art": "Gebäude", "anbieter": "Allianz", "jahresbeitrag": 480.0}).status_code == 201
        assert c.post(f"/api/objekte/{slug}/kredite", json={
            "bezeichnung": "Kauf", "bank": "Sparkasse",
            "rate_monatlich": 500.0}).status_code == 201
        assert c.post(f"/api/objekte/{slug}/zahlungen", json={
            "jahr": 2025, "art": "Grundsteuer", "kategorie": "Steuer",
            "betrag": 240.0}).status_code == 201

        assert len(c.get(f"/api/objekte/{slug}/mieten").json()) == 1

        # Auswertung: 12 x 800 Miete gegen 12 x 500 Kredit + 480 Vers. + 240 Steuer
        a = c.get("/api/auswertung", params={"jahr": 2025, "objekt": slug}).json()
        zeile = a["objekte"][0]
        assert zeile["einnahmen"] == 9600.0
        assert zeile["bloecke"]["Kredit"] == 6000.0
        assert zeile["bloecke"]["Versicherung"] == 480.0
        assert zeile["bloecke"]["Steuer"] == 240.0
        assert zeile["ausgaben"] == 6720.0
        assert zeile["saldo"] == 2880.0

        verlauf = c.get("/api/auswertung/mietverlauf", params={"objekt": slug}).json()
        assert verlauf["reihen"][0]["werte"][-1] == 9600.0


def test_stammdaten_aendern_und_loeschen():
    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={"name": "Löschweg 1"}).json()["slug"]
        eintrag = c.post(f"/api/objekte/{slug}/versicherungen",
                         json={"art": "Haftpflicht", "jahresbeitrag": 100.0}).json()["id"]

        assert c.patch(f"/api/versicherungen/{eintrag}",
                       json={"jahresbeitrag": 125.0}).status_code == 200
        assert c.get(f"/api/objekte/{slug}/versicherungen").json()[0]["jahresbeitrag"] == 125.0

        assert c.delete(f"/api/versicherungen/{eintrag}").status_code == 200
        assert c.get(f"/api/objekte/{slug}/versicherungen").json() == []


def test_unbekannter_bereich_ist_404():
    with TestClient(app) as c:
        assert c.get("/api/objekte/obj-a/quatsch").status_code == 404
