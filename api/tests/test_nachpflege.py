"""Nachpflege-Hinweise und das Anlegen weiterer Zeiträume."""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_nachpflege.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def _objekt(c, name, **felder):
    return c.post("/api/objekte", json={"name": name, **felder}).json()["slug"]


def test_fehlende_angaben_werden_gemeldet_und_verschwinden_wieder():
    with TestClient(app) as c:
        slug = _objekt(c, "Lückenweg 1")
        offen = c.get(f"/api/objekte/{slug}").json()["nachpflege"]
        assert offen["anzahl"] > 0
        assert "Straße" in offen["felder"]

        c.patch(f"/api/objekte/{slug}", json={
            "strasse": "Lückenweg 1", "plz": "90562", "flaeche": 210.0,
            "kaufpreis": 400000.0, "verkehrswert": 480000.0, "iban": "DE02..."})
        danach = c.get(f"/api/objekte/{slug}").json()["nachpflege"]
        assert danach["anzahl"] == 0
        assert danach["text"] == ""


def test_beendete_mietverhaeltnisse_werden_nicht_angemahnt():
    """Ein ausgezogener Mieter braucht keine Mailadresse mehr."""
    with TestClient(app) as c:
        slug = _objekt(c, "Auszugweg 2")
        c.post(f"/api/objekte/{slug}/mieten", json={
            "partei": "Ehemalig", "ab_datum": "2020-01-01",
            "bis_datum": "2023-12-31"})
        offen = c.get(f"/api/objekte/{slug}").json()["nachpflege"]["offen"]
        assert not [h for h in offen if h["bereich"] == "miete"]


def test_stammdaten_patch_nimmt_ein_datum_entgegen():
    with TestClient(app) as c:
        slug = _objekt(c, "Datumsweg 3")
        assert c.patch(f"/api/objekte/{slug}",
                       json={"kaufdatum": "2019-08-15"}).status_code == 200
        assert c.get(f"/api/objekte/{slug}").json()["objekt"]["kaufdatum"] \
            == "2019-08-15"


def test_leerer_name_wird_abgelehnt():
    with TestClient(app) as c:
        slug = _objekt(c, "Namensweg 4")
        assert c.patch(f"/api/objekte/{slug}", json={"name": ""}).status_code == 400


def test_vorjahr_anlegen_uebernimmt_vorauszahlungen():
    with TestClient(app) as c:
        slug = _objekt(c, "Vorjahrweg 5", kostenarten=["Wasser", "Müll"])
        neu = c.post(f"/api/objekte/{slug}/zeitraeume", json={"jahr": 2023})
        assert neu.status_code == 201
        assert neu.json()["kostenarten"] == 2

        # Die Checkliste des neuen Zeitraums ist sofort vollstaendig
        zid = neu.json()["id"]
        checkliste = c.get(f"/api/zeitraeume/{zid}").json()["checkliste"]
        assert {k["kostenart"] for k in checkliste} == {"Wasser", "Müll"}
        assert all(k["zustand"] == "fehlt" for k in checkliste)


def test_derselbe_zeitraum_wird_nicht_zweimal_angelegt():
    with TestClient(app) as c:
        slug = _objekt(c, "Doppelweg 6")
        c.post(f"/api/objekte/{slug}/zeitraeume", json={"jahr": 2022})
        zweiter = c.post(f"/api/objekte/{slug}/zeitraeume", json={"jahr": 2022})
        assert zweiter.status_code == 409


def test_grundstueck_wird_nicht_nach_wohnflaeche_gefragt():
    """Ein Acker hat keine Wohnfläche und kein Hauskonto — dort danach zu
    fragen wäre eine falsche Fährte. Gefragt wird nach dem Katasterauszug."""
    with TestClient(app) as c:
        slug = _objekt(c, "Steigäcker", typ="lg-grundstueck",
                       nutzung="Landwirtschaft")
        offen = c.get(f"/api/objekte/{slug}").json()["nachpflege"]
        felder = offen["felder"]
        assert "Nutzungsart" in felder
        assert "Grundstücksfläche" in felder
        assert "Grundsteuerwert" in felder
        # nichts aus der Welt der Gebäude
        assert "Gesamtfläche" not in felder
        assert "IBAN des Hauskontos" not in felder
        assert "Straße" not in felder


def test_grundstuecksangaben_verschwinden_wenn_sie_gepflegt_sind():
    with TestClient(app) as c:
        slug = _objekt(c, "Flurweg 619", typ="lg-grundstueck")
        antwort = c.patch(f"/api/objekte/{slug}", json={
            "grundstueck_flaeche": 4630.0,
            "grundstueck_nutzungsart": "Gemischt",
            "gemarkung": "Eckenhaid", "flurstueck": "619",
            "verkehrswert": 55000.0, "grundsteuerwert": 2600.0,
            "grundsteuer_messbetrag": 1.43, "grundsteuer_hebesatz": 330.0})
        assert antwort.status_code == 200

        det = c.get(f"/api/objekte/{slug}").json()
        assert det["nachpflege"]["anzahl"] == 0
        o = det["objekt"]
        assert o["grundstueck_flaeche"] == 4630.0
        assert o["grundsteuer_messbetrag"] == 1.43
        # Der Grundstückswert ist der Verkehrswert — so rechnet ihn die
        # Vermögensübersicht ohne Zutun mit.
        assert o["verkehrswert"] == 55000.0
        # Die Wohnfläche bleibt unberührt: sie speist den Verteilungsschlüssel
        assert o["flaeche"] is None


def test_pacht_ist_ein_mietverhaeltnis():
    """Pächter, Pachtzins und Turnus passen auf das bestehende Miet-Modell —
    ohne zweite Tabelle, die Auswertung und Sicherung übersehen könnten."""
    with TestClient(app) as c:
        slug = _objekt(c, "Pachtacker", typ="lg-grundstueck")
        neu = c.post(f"/api/objekte/{slug}/mieten", json={
            "partei": "Landwirt Huber", "kaltmiete": 320.0,
            "turnus": "jaehrlich", "ab_datum": "2024-01-01"})
        assert neu.status_code == 201

        pacht = c.get(f"/api/objekte/{slug}/mieten").json()[0]
        assert pacht["partei"] == "Landwirt Huber"
        assert pacht["kaltmiete"] == 320.0
        # Ohne Kontakt ist eine Pacht kein Mangel: es gibt nichts zu versenden
        assert not [h for h in c.get(f"/api/objekte/{slug}").json()
                    ["nachpflege"]["offen"] if h["bereich"] == "miete"]


def test_grundstueck_uebersteht_export_und_wiederherstellung():
    """Die neuen Felder hängen am Objekt und wandern deshalb ohne Zutun in
    die Sicherung — eine eigene Tabelle hätte hier gefehlt."""
    with TestClient(app) as c:
        slug = _objekt(c, "Sicherungsacker", typ="lg-grundstueck")
        c.patch(f"/api/objekte/{slug}", json={
            "grundstueck_flaeche": 4630.0, "grundstueck_nutzungsart": "Wald",
            "grundsteuerwert": 2600.0})
        sicherung = c.get(f"/api/objekte/{slug}/export").json()
        assert sicherung["objekt"]["grundstueck_nutzungsart"] == "Wald"

        zurueck = c.post("/api/objekte/import", json=sicherung)
        assert zurueck.status_code == 201
        wieder = c.get(f"/api/objekte/{zurueck.json()['slug']}").json()["objekt"]
        assert wieder["grundstueck_flaeche"] == 4630.0
        assert wieder["grundsteuerwert"] == 2600.0
        assert wieder["typ"] == "lg-grundstueck"


def test_turnus_auswahl_kommt_aus_der_api():
    with TestClient(app) as c:
        mieten = c.get("/api/turnus/mieten").json()
        assert mieten["vorgabe"] == "monatlich"
        assert [o["wert"] for o in mieten["optionen"]][0] == "monatlich"
        assert c.get("/api/turnus/quatsch").status_code == 404
