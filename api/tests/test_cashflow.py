"""Cashflow je Einheit, Miete pro m² und der Fluss fürs Sankey-Diagramm."""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_cashflow.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402

from app.cashflow import EinheitZahlen, verteile  # noqa: E402
from app.main import app  # noqa: E402


def test_verteilung_nach_flaeche():
    einheiten = [
        EinheitZahlen("EG", "Wohnen", 60.0, None, None),
        EinheitZahlen("OG", "Wohnen", 40.0, None, None),
    ]
    assert verteile(1000.0, einheiten) == [600.0, 400.0]


def test_verteilung_ohne_flaeche_zu_gleichen_teilen():
    einheiten = [
        EinheitZahlen("A", "Wohnen", None, None, None),
        EinheitZahlen("B", "Wohnen", None, None, None),
    ]
    assert verteile(500.0, einheiten) == [250.0, 250.0]


def _objekt_mit_einheiten(c) -> str:
    slug = c.post("/api/objekte", json={
        "name": "Flusshaus 1", "turnus": "kalender",
        "einheiten": [
            {"bezeichnung": "EG", "flaeche": 60.0, "partei": "Mieter EG"},
            {"bezeichnung": "OG", "flaeche": 40.0, "partei": "Mieter OG"},
        ],
    }).json()["slug"]
    c.post(f"/api/objekte/{slug}/mieten", json={
        "einheit": "EG", "partei": "Mieter EG", "kaltmiete": 600.0,
        "stellplatz": 50.0, "sonstige": 10.0, "nebenkosten_vz": 150.0,
        "email": "eg@example.org", "telefon": "0170 1234567",
        "ab_datum": "2025-01-01"})
    c.post(f"/api/objekte/{slug}/mieten", json={
        "einheit": "OG", "partei": "Mieter OG", "kaltmiete": 400.0,
        "ab_datum": "2025-01-01"})
    c.post(f"/api/objekte/{slug}/kredite", json={
        "bezeichnung": "Kauf", "rate_monatlich": 500.0})
    c.post(f"/api/objekte/{slug}/versicherungen", json={
        "art": "Gebäude", "jahresbeitrag": 300.0})
    return slug


def test_cashflow_je_einheit():
    with TestClient(app) as c:
        slug = _objekt_mit_einheiten(c)
        daten = c.get("/api/auswertung/cashflow",
                      params={"objekt": slug, "jahr": 2025}).json()

        eg = next(e for e in daten["einheiten"] if e["bezeichnung"] == "EG")
        og = next(e for e in daten["einheiten"] if e["bezeichnung"] == "OG")

        # Einnahmen inkl. Stellplatz und Sonstigem
        assert eg["einnahmen_monat"] == 660.0
        assert eg["einnahmen_jahr"] == 7920.0
        assert og["einnahmen_jahr"] == 4800.0

        # Miete je m² zählt nur die Kaltmiete: 600 / 60
        assert eg["miete_pro_qm"] == 10.0
        assert og["miete_pro_qm"] == 10.0

        # Kosten 6000 Kredit + 300 Versicherung nach Fläche 60:40
        assert eg["bloecke"]["Kredit"] == 3600.0
        assert og["bloecke"]["Kredit"] == 2400.0
        assert eg["kosten_jahr"] == 3780.0
        assert og["kosten_jahr"] == 2520.0
        assert eg["saldo_jahr"] == 4140.0

        assert daten["gesamt"]["einnahmen"] == 12720.0
        assert daten["gesamt"]["kosten"] == 6300.0
        assert daten["gesamt"]["saldo"] == 6420.0

        # Kontaktdaten bleiben am Mietverhältnis
        miete = c.get(f"/api/objekte/{slug}/mieten").json()
        assert any(m["email"] == "eg@example.org" for m in miete)


def test_sankey_fluss_ist_ausgeglichen():
    with TestClient(app) as c:
        slug = _objekt_mit_einheiten(c)
        daten = c.get("/api/auswertung/cashflow",
                      params={"objekt": slug, "jahr": 2025}).json()
        s = daten["sankey"]

        namen = [k["name"] for k in s["knoten"]]
        assert "EG" in namen and "OG" in namen and "Einnahmen" in namen

        mitte = namen.index("Einnahmen")
        zufluss = sum(f["wert"] for f in s["fluss"] if f["nach"] == mitte)
        abfluss = sum(f["wert"] for f in s["fluss"] if f["von"] == mitte)
        # Was hereinkommt, geht auch wieder heraus — Überschuss inbegriffen
        assert abs(zufluss - abfluss) < 0.01
        assert abs(zufluss - 12720.0) < 0.01
        assert "Überschuss" in namen


def test_kategorienfilter_wirkt_auf_sankey():
    with TestClient(app) as c:
        slug = _objekt_mit_einheiten(c)
        nur_kredit = c.get("/api/auswertung/sankey", params={
            "objekt": slug, "jahr": 2025, "kategorien": "Kredit"}).json()
        namen = [k["name"] for k in nur_kredit["knoten"]]
        assert "Kredit" in namen
        assert "Versicherung" not in namen
        assert nur_kredit["kosten"] == 6000.0

        alles = c.get("/api/auswertung/sankey",
                      params={"objekt": slug, "jahr": 2025}).json()
        assert alles["kosten"] == 6300.0
