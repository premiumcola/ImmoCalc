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


def test_status_vertrag_der_plexdice_migration():
    """Status-Vertrag: /healthz prüft die DB wirklich (200), /status liefert
    app/version/last_run/last_result/next_run fürs Monitoring-Label."""
    with TestClient(app) as c:
        antwort = c.get("/healthz")
        assert antwort.status_code == 200
        assert antwort.json()["status"] == "ok"

        status = c.get("/status").json()
        assert status["app"] == "immocalc-api"
        assert status["version"]
        for feld in ("last_run", "last_result", "next_run"):
            assert feld in status


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


def test_kuerzel_ist_leer_bis_es_gepflegt_wird():
    """N322 — ohne Pflege bleibt das Kürzel leer (Frontend kürzt dann selbst
    aus dem Namen); gesetzt wird es über dieselbe PATCH-Route wie jedes
    andere Stammdatenfeld und erscheint in der Objektliste."""
    with TestClient(app) as c:
        objekte = {o["slug"]: o for o in c.get("/api/objekte").json()}
        assert objekte["obj-a"]["kuerzel"] == ""

        antwort = c.patch("/api/objekte/obj-a", json={"kuerzel": "TAU5"})
        assert antwort.status_code == 200

        objekte = {o["slug"]: o for o in c.get("/api/objekte").json()}
        assert objekte["obj-a"]["kuerzel"] == "TAU5"
        assert c.get("/api/objekte/obj-a").json()["objekt"]["kuerzel"] == "TAU5"


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


def test_einheiten_liste_nennt_die_monatsmiete():
    """CCCLXVII — die Blase auf der Startseite zeigt Miete und €/m². Beträge
    stehen je Turnus: eine vierteljährliche Miete darf nicht als Monatsmiete
    durchgereicht werden."""
    with TestClient(app) as c:
        neu = c.post("/api/objekte", json={
            "name": "Mietweg 3", "einheiten": [
                {"bezeichnung": "EG", "flaeche": 50},
                {"bezeichnung": "OG", "flaeche": 80},
                {"bezeichnung": "Laden", "flaeche": 25}]}).json()
        c.post(f"/api/objekte/{neu['slug']}/mieten", json={
            "einheit": "EG", "partei": "Mieter A", "kaltmiete": 600,
            "stellplatz": 50, "ab_datum": "2024-01-01"})
        # vierteljährlich gezahlt: 1800 im Quartal sind 600 im Monat
        c.post(f"/api/objekte/{neu['slug']}/mieten", json={
            "einheit": "OG", "partei": "Mieter B", "kaltmiete": 1800,
            "turnus": "vierteljaehrlich", "ab_datum": "2024-01-01"})

        einheiten = {e["bezeichnung"]: e for e in next(
            o for o in c.get("/api/objekte").json()
            if o["slug"] == neu["slug"])["einheiten_liste"]}

        assert einheiten["EG"]["miete_monat"] == 650.0
        assert einheiten["EG"]["miete_qm"] == 13.0
        assert einheiten["OG"]["miete_monat"] == 600.0
        assert einheiten["OG"]["miete_qm"] == 7.5
        # Ohne Mietverhältnis wird nichts erfunden.
        assert einheiten["Laden"]["miete_monat"] == 0.0
        assert einheiten["Laden"]["miete_qm"] is None
