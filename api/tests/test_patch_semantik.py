"""N370 — PATCH ändert, was mitkommt. Alles andere bleibt stehen.

Drei Endpunkte verhielten sich wie PUT, weil ihr Eingabemodell für jedes Feld
einen Default hat und der Handler alle bedingungslos kopierte. Ein
`PATCH {"betrag": 120000}` löschte damit Rang, Grundbuchblatt, Gläubiger und
Notiz — stillschweigend. Die Oberfläche schickte zufällig immer alle Felder
mit; jeder andere Aufrufer verlor echte Grundbuchdaten.

Dazu die Gegenprobe für ein ausdrücklich mitgeschicktes `null`: das traf auf
NOT-NULL-Spalten und ergab HTTP 500 statt einer verständlichen Antwort.
"""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_patch_semantik.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def _objekt(c, name="Patchweg 1"):
    antwort = c.post("/api/objekte", json={
        "name": name, "ort": "Musterstadt", "strasse": name,
        "kaufpreis": 300000.0, "kostenarten": ["Wasser"],
        "einheiten": [{"bezeichnung": "EG", "flaeche": 70.0}],
    })
    assert antwort.status_code == 201, antwort.text
    return antwort.json()["slug"]


def test_grundschuld_patch_behaelt_ungenannte_felder():
    with TestClient(app) as c:
        slug = _objekt(c)
        angelegt = c.post(f"/api/objekte/{slug}/grundschulden", json={
            "betrag": 100000.0, "rang": "I", "grundbuch_blatt": "Blatt 4711",
            "glaeubiger": "Sparkasse Musterstadt", "brief": True,
            "notiz": "Erstrangig eingetragen"})
        assert angelegt.status_code == 201, angelegt.text
        gid = angelegt.json()["id"]

        geaendert = c.patch(f"/api/grundschulden/{gid}", json={"betrag": 120000.0})
        assert geaendert.status_code == 200, geaendert.text
        g = geaendert.json()
        assert g["betrag"] == 120000.0
        assert g["rang"] == "I", "Rang verloren"
        assert g["grundbuch_blatt"] == "Blatt 4711", "Grundbuchblatt verloren"
        assert g["glaeubiger"] == "Sparkasse Musterstadt", "Gläubiger verloren"
        assert g["brief"] is True, "Brief-Kennzeichen verloren"
        assert g["notiz"] == "Erstrangig eingetragen", "Notiz verloren"


def test_grundschuld_patch_kann_ein_feld_gezielt_leeren():
    """Der Gegentest: ausdrücklich mitgeschickt heißt weiterhin „ändern"."""
    with TestClient(app) as c:
        slug = _objekt(c, "Patchweg 2")
        gid = c.post(f"/api/objekte/{slug}/grundschulden", json={
            "betrag": 50000.0, "notiz": "vorläufig"}).json()["id"]
        g = c.patch(f"/api/grundschulden/{gid}", json={"notiz": ""}).json()
        assert g["notiz"] == ""
        assert g["betrag"] == 50000.0


def test_eigentuemer_patch_weist_unpassende_werte_zurueck():
    """Vorher war `hasattr` die einzige Prüfung — eine Zahl landete in einer
    Text-Spalte, ein `null` in einer Pflichtspalte brach mit 500 ab."""
    with TestClient(app) as c:
        eid = c.post("/api/eigentuemer", json={
            "name": "Anna Beispiel", "email": "a@example.org",
            "telefon": "0123"}).json()["id"]

        # Ein unbekanntes Feld wird benannt statt still geschluckt.
        fremd = c.patch(f"/api/eigentuemer/{eid}", json={"gibtsnicht": 1})
        assert fremd.status_code == 400, fremd.text

        # `null` auf einer Pflichtspalte darf nie 500 ergeben.
        leer = c.patch(f"/api/eigentuemer/{eid}", json={"name": None})
        assert leer.status_code < 500, leer.text

        # Und der gepflegte Bestand bleibt unangetastet.
        liste = c.get("/api/eigentuemer").json()
        ich = next(e for e in liste if e["id"] == eid)
        assert ich["name"] == "Anna Beispiel"
        assert ich["telefon"] == "0123"


def test_renovierung_patch_vertraegt_ausdrueckliches_null():
    with TestClient(app) as c:
        slug = _objekt(c, "Patchweg 3")
        rid = c.post(f"/api/objekte/{slug}/renovierungen", json={
            "name": "Bad neu", "budget": 5000.0}).json()["id"]
        for rumpf in ({"name": None}, {"abgeschlossen": None}):
            antwort = c.patch(f"/api/renovierungen/{rid}", json=rumpf)
            assert antwort.status_code < 500, (rumpf, antwort.text)
        # Der Name steht weiterhin da.
        assert c.get(f"/api/renovierungen/{rid}").json()["name"] == "Bad neu"
