"""N409 (Aufgabe 3, Brücke) — GET /api/objekte/{slug}/kpi: die reine Engine
an echte Stammdaten angeschlossen."""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(),
                                     "test_investment_kpi_endpoint.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def test_route_registriert_vor_dem_stammdaten_faenger():
    """N408 wiederholte sich fast: ein neuer `/objekte/{slug}/<wort>`-Pfad
    muss vor `stammdaten` eingehängt sein, sonst antwortet der generische
    Fänger mit „Unbekannter Bereich" statt der echten Route."""
    with TestClient(app) as c:
        antwort = c.get("/api/objekte/kein-objekt-xyz/kpi")
        assert antwort.status_code == 404
        assert antwort.json()["detail"] == "Objekt nicht gefunden"


def test_leeres_objekt_liefert_ueberall_none_aber_200():
    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={
            "name": "KPI-Leerobjekt", "einheiten": [{"bezeichnung": "EG"}],
        }).json()["slug"]
        r = c.get(f"/api/objekte/{slug}/kpi")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["kennzahlen"]["betriebsergebnis"]["noi"] is None
        assert d["bewertung"]["note"] is None


def test_vollstaendiges_objekt_ergibt_echte_kennzahlen():
    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={
            "name": "KPI-Vollobjekt",
            "einheiten": [{"bezeichnung": "EG", "flaeche": 80.0}],
        }).json()["slug"]
        assert c.patch(f"/api/objekte/{slug}", json={
            "kaufpreis": 300_000, "kaufdatum": "2021-01-01",
            "verkehrswert": 340_000, "kpi_baukosten_eur_qm": 2_000,
        }).status_code == 200
        assert c.post(f"/api/objekte/{slug}/mieten", json={
            "einheit": "EG", "partei": "Mieter A", "kaltmiete": 900.0,
            "ab_datum": "2021-01-01"}).status_code == 201
        assert c.post(f"/api/objekte/{slug}/kredite", json={
            "bezeichnung": "Darlehen", "bank": "Sparkasse",
            "restschuld": 200_000, "zinssatz": 3.0,
            "rate_monatlich": 1_000}).status_code == 201

        r = c.get(f"/api/objekte/{slug}/kpi").json()
        k = r["kennzahlen"]
        assert k["betriebsergebnis"]["noi"] is not None
        # Jahreskaltmiete = 900 * 12 = 10800
        assert k["rendite"]["brutto_rendite_pct"] == round(10_800 / 300_000 * 100, 2)
        assert k["finanzierung"]["ltv_pct"] == round(200_000 / 340_000 * 100, 2)
        assert r["bewertung"]["note"] in {"A", "B", "C", "D", "E"}


def test_schuldenfreies_objekt_ist_dscr_nicht_anwendbar():
    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={
            "name": "KPI-Schuldenfrei",
            "einheiten": [{"bezeichnung": "EG", "flaeche": 60.0}],
        }).json()["slug"]
        c.patch(f"/api/objekte/{slug}", json={
            "kaufpreis": 200_000, "verkehrswert": 220_000})
        r = c.get(f"/api/objekte/{slug}/kpi").json()
        assert r["kennzahlen"]["finanzierung"]["ltv_pct"] == 0.0
        assert r["kennzahlen"]["finanzierung"]["dscr_anwendbar"] is False


def test_leerstehende_einheit_setzt_hat_leerstand():
    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={
            "name": "KPI-Leerstand",
            "einheiten": [{"bezeichnung": "EG", "flaeche": 50.0},
                          {"bezeichnung": "OG", "flaeche": 50.0}],
        }).json()["slug"]
        c.post(f"/api/objekte/{slug}/mieten", json={
            "einheit": "EG", "partei": "Mieter A", "kaltmiete": 500.0,
            "ab_datum": "2021-01-01"})
        r = c.get(f"/api/objekte/{slug}/kpi").json()
        assert r["kennzahlen"]["hat_leerstand"] is True


def test_grenzsteuersatz_kommt_vom_groessten_anteilseigner():
    """Ohne Grenzsteuersatz bleibt „steuerpflichtiges Ergebnis" zwar
    berechenbar, aber die Steuererstattung braucht den Satz — sie muss von
    `None` auf einen echten Wert kippen, sobald der Eigentümer ihn trägt."""
    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={
            "name": "KPI-Steuersatz",
            "einheiten": [{"bezeichnung": "EG", "flaeche": 70.0}],
        }).json()["slug"]
        c.patch(f"/api/objekte/{slug}", json={
            "kaufpreis": 250_000, "verkehrswert": 260_000,
            "gebaeudeanteil_pct": 70, "afa_satz_pct": 2.0,
            "kpi_nicht_umlagefaehige_kosten_jahr": 500})
        c.post(f"/api/objekte/{slug}/mieten", json={
            "einheit": "EG", "partei": "Mieter A", "kaltmiete": 800.0,
            "ab_datum": "2021-01-01"})
        c.post(f"/api/objekte/{slug}/kredite", json={
            "bezeichnung": "Darlehen", "bank": "Sparkasse",
            "restschuld": 150_000, "zinssatz": 3.0, "rate_monatlich": 700})

        ohne_satz = c.get(f"/api/objekte/{slug}/kpi").json()
        assert ohne_satz["kennzahlen"]["cashflow"]["steuererstattung"] is None

        eid = c.post("/api/eigentuemer", json={
            "name": "Eigner KPI", "grenzsteuersatz_pct": 35.0}).json()["id"]
        assert c.post(f"/api/objekte/{slug}/anteile", json={
            "eigentuemer_id": eid, "promille": 1000}).status_code == 201

        mit_satz = c.get(f"/api/objekte/{slug}/kpi").json()
        assert mit_satz["kennzahlen"]["cashflow"]["steuererstattung"] is not None
