"""Löschen, Sichern, Wiederherstellen.

Der Kern: eine gelöschte Immobilie muss sich aus der Sicherung vollständig
wiederherstellen lassen — und das Löschen darf nichts anfassen, was einem
anderen Objekt gehört.
"""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_export.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def _anlegen(c, name="Löschstraße 3"):
    antwort = c.post("/api/objekte", json={
        "name": name, "ort": "Musterstadt", "strasse": "Löschstraße 3",
        "kaufpreis": 420000.0, "verkehrswert": 500000.0,
        "kostenarten": ["Wasser", "Müll"],
        "einheiten": [{"bezeichnung": "EG", "flaeche": 70.0, "partei": "Mieter A"}],
    })
    assert antwort.status_code == 201
    return antwort.json()["slug"]


def test_export_enthaelt_alles_und_import_stellt_wieder_her():
    with TestClient(app) as c:
        slug = _anlegen(c)
        c.post(f"/api/objekte/{slug}/mieten", json={
            "einheit": "EG", "partei": "Mieter A", "kaltmiete": 800.0,
            "email": "a@example.org", "ab_datum": "2024-01-01"})
        c.post(f"/api/objekte/{slug}/kredite", json={
            "bezeichnung": "Hauptdarlehen", "restschuld": 300000.0,
            "zinssatz": 3.5, "rate_monatlich": 1200.0})

        sicherung = c.get(f"/api/objekte/{slug}/export")
        assert sicherung.status_code == 200
        assert "attachment" in sicherung.headers["content-disposition"]
        daten = sicherung.json()
        assert daten["objekt"]["name"] == "Löschstraße 3"
        assert len(daten["mieten"]) == 1
        assert len(daten["kredite"]) == 1
        assert len(daten["kostenarten"]) == 2
        assert len(daten["zeitraeume"]) == 1

        weg = c.delete(f"/api/objekte/{slug}")
        assert weg.status_code == 200
        assert c.get(f"/api/objekte/{slug}").status_code == 404

        zurueck = c.post("/api/objekte/import", json=daten)
        assert zurueck.status_code == 201
        neu = zurueck.json()["slug"]
        det = c.get(f"/api/objekte/{neu}").json()
        assert det["objekt"]["kaufpreis"] == 420000.0
        assert len(det["zeitraeume"]) == 1
        assert len(c.get(f"/api/objekte/{neu}/mieten").json()) == 1
        assert len(c.get(f"/api/objekte/{neu}/kredite").json()) == 1


def test_import_ueberschreibt_kein_bestehendes_objekt():
    """Ein gleichnamiges Objekt bleibt unangetastet — es entsteht ein zweites."""
    with TestClient(app) as c:
        slug = _anlegen(c, "Doppelweg 1")
        daten = c.get(f"/api/objekte/{slug}/export").json()
        zweit = c.post("/api/objekte/import", json=daten).json()["slug"]
        assert zweit != slug
        assert c.get(f"/api/objekte/{slug}").status_code == 200


def test_loeschen_laesst_andere_objekte_unberuehrt():
    with TestClient(app) as c:
        a = _anlegen(c, "Bleibt 1")
        b = _anlegen(c, "Geht 2")
        c.post(f"/api/objekte/{a}/mieten", json={
            "partei": "Bleibt-Mieter", "kaltmiete": 500.0, "ab_datum": "2024-01-01"})

        c.delete(f"/api/objekte/{b}")
        assert c.get(f"/api/objekte/{a}").status_code == 200
        assert len(c.get(f"/api/objekte/{a}/mieten").json()) == 1


def test_import_ohne_objektblock_wird_abgelehnt():
    with TestClient(app) as c:
        assert c.post("/api/objekte/import", json={"irgendwas": 1}).status_code == 400
