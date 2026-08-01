"""N5 — abgeleitete Positions-Gewichte folgen einer Stammdaten-Änderung.

Der Fehler war: `Kostenposition.anteile` ist eine gespeicherte Momentaufnahme.
Wurde ein Mietverhältnis nachträglich korrigiert (Mietstart aus Versehen 2025,
richtig 2026), lebte der alte, falsche Anteil in der Position weiter — ein
Mieter, dessen Mietverhältnis gar nicht mehr in den Abrechnungszeitraum fällt,
wurde weiter belastet.

Fix: `abgeleitet=True`-Positionen offener Zeiträume werden nach jeder Miet-/
Einheit-Änderung neu aus den Stammdaten abgeleitet (`positionen_neu_ableiten`).
Von Hand gesetzte Gewichte (`abgeleitet=False`) und nicht ableitbare Schlüssel
(Verbrauch/Prozent) bleiben unangetastet.
"""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(),
                                     "test_anteile_neu_ableiten.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def _position(c, kostenart):
    z = c.get("/api/zeitraeume/1").json()
    return next((k for k in z["checkliste"] if k["kostenart"] == kostenart), None)


def test_abgeleitete_anteile_folgen_dem_geaenderten_mietstart():
    with TestClient(app) as c:
        # Seed: obj-a, Zeitraum 1 (2025). Einheit „1. OG" ist an „Partei OG"
        # vermietet (ab 2024, offen) — im Jahr 2025 also voll belegt.
        # Eine Fläche-Position anlegen; die Gewichte werden abgeleitet.
        r = c.post("/api/zeitraeume/1/positionen", json={
            "kostenart": "N5-Test", "betrag": 1200.0,
            "schluessel": "flaeche", "status": "erledigt"})
        assert r.status_code in (200, 201), r.text
        assert r.json()["abgeleitet"] is True
        anteile = r.json()["anteile"]
        assert "Partei OG" in anteile, anteile          # Mieter ist Partei

        # Den Mietstart aus Versehen weit in die Zukunft setzen (nach dem
        # Abrechnungszeitraum 2025). Das Mietverhältnis berührt 2025 nicht mehr.
        mieten = c.get("/api/objekte/obj-a/mieten").json()
        mieten = mieten if isinstance(mieten, list) else mieten.get("eintraege", [])
        mid = next(m["id"] for m in mieten if m["einheit"] == "1. OG")
        p = c.patch(f"/api/stammdaten/mieten/{mid}", json={"ab_datum": "2027-05-01"})
        assert p.status_code == 200, p.text

        # Die abgeleitete Position ist jetzt neu berechnet: „Partei OG" ist raus,
        # die volle Fläche der Einheit fällt als Leerstand an „1. OG".
        zeile = _position(c, "N5-Test")
        assert zeile is not None
        neu = zeile["anteile"]
        assert "Partei OG" not in neu, neu
        assert "1. OG" in neu, neu

        # In der Abrechnung trägt diese Position ihre Kosten nun am Leerstand
        # („1. OG"), nicht mehr am künftigen Mieter. (Der Gesamt-Parteienblock
        # kann „Partei OG" aus anderen Positionen mit HANDEINGABE — z. B. dem
        # Wasser-Zählerwert im Seed — weiter enthalten; das ist gewollt, manuelle
        # Zahlen werden nicht automatisch umgeschrieben.)
        ab = c.get("/api/zeitraeume/1/abrechnung").json()
        n5 = next((p for p in ab["positionen"] if p["kostenart"] == "N5-Test"), None)
        assert n5 is not None, ab["positionen"]
        assert "Partei OG" not in n5["verteilung"], n5["verteilung"]
        assert "1. OG" in n5["verteilung"], n5["verteilung"]


def test_handeingabe_bleibt_bei_mietaenderung_erhalten():
    """Gegenprobe: von Hand gesetzte Gewichte (abgeleitet=False) werden NICHT
    automatisch überschrieben, wenn sich ein Mietverhältnis ändert."""
    with TestClient(app) as c:
        r = c.post("/api/zeitraeume/1/positionen", json={
            "kostenart": "N5-Hand", "betrag": 900.0,
            "schluessel": "flaeche", "status": "erledigt"})
        pid = r.json()["id"]
        # Eine Handeingabe der Gewichte (abgeleitet=false).
        hand = {"Partei OG": 111.0, "WG": 222.0}
        c.patch(f"/api/positionen/{pid}",
                json={"anteile": hand, "abgeleitet": False})

        mieten = c.get("/api/objekte/obj-a/mieten").json()
        mieten = mieten if isinstance(mieten, list) else mieten.get("eintraege", [])
        mid = next(m["id"] for m in mieten if m["einheit"] == "2. OG")
        c.patch(f"/api/stammdaten/mieten/{mid}", json={"ab_datum": "2027-01-01"})

        zeile = _position(c, "N5-Hand")
        assert zeile["anteile"] == hand, zeile["anteile"]   # unverändert
