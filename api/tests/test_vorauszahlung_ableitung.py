"""CCCLXIV — NK-Vorauszahlungen werden aus der Miete abgeleitet (monatliche
Vorauszahlung × belegte Monate, zeitanteilig ab Einzug). Wächter: sie erscheinen
ohne separate Erfassung, und ein Mitten-im-Jahr-Einzug halbiert sie."""
import os
import sys
import tempfile
from datetime import date

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_vorausz_ableitung.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def _objekt_mit_zeitraum(c):
    # start_monat=1 → das automatisch angelegte Fenster ist ein Kalenderjahr.
    slug = c.post("/api/objekte", json={
        "name": "VZ-Ableitung", "start_monat": 1,
        "einheiten": [{"bezeichnung": "Voll"}, {"bezeichnung": "Halb"}]}).json()["slug"]
    z = c.get(f"/api/objekte/{slug}").json()["zeitraeume"][0]
    det = c.get(f"/api/zeitraeume/{z['id']}").json()
    return slug, z["id"], date.fromisoformat(det["start"]), date.fromisoformat(det["ende"])


def test_vorauszahlung_zeitanteilig_und_ohne_erfassung():
    with TestClient(app) as c:
        slug, zid, start, ende = _objekt_mit_zeitraum(c)
        # Voll: das ganze Fenster belegt. Halb: erst zur Jahresmitte eingezogen.
        c.post(f"/api/objekte/{slug}/mieten", json={
            "einheit": "Voll", "partei": "Voll-Mieter", "kaltmiete": 500.0,
            "nebenkosten_vz": 100.0, "ab_datum": start.isoformat()})
        mitte = date(ende.year, 7, 1)
        c.post(f"/api/objekte/{slug}/mieten", json={
            "einheit": "Halb", "partei": "Halb-Mieter", "kaltmiete": 500.0,
            "nebenkosten_vz": 100.0, "ab_datum": mitte.isoformat()})
        # eine erledigte Position, damit die Abrechnung rechnet
        c.post(f"/api/zeitraeume/{zid}/positionen", json={
            "kostenart": "Müll", "betrag": 240.0, "schluessel": "einheiten"})

        parteien = c.get(f"/api/zeitraeume/{zid}/abrechnung").json()["parteien"]
        voll = parteien["Voll-Mieter"]["vorauszahlungen"]
        halb = parteien["Halb-Mieter"]["vorauszahlungen"]

        # Ohne jeden separat erfassten Vorauszahlungs-Datensatz stehen sie da.
        assert voll > 0 and halb > 0
        # Volles Jahr: 100 €/Monat × ~12 Monate.
        assert 1150.0 <= voll <= 1250.0
        # Halbes Jahr (ab 01.07.) trägt rund die Hälfte.
        assert 0.45 <= halb / voll <= 0.55
