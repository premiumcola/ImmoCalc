"""N187 — abgerechnet-Marker für **einzelne Monate**, additiv neben den
Quartalsmarkern.

Bisher hielt ein Marker ein ganzes Quartal fest. Jetzt kann die Oberfläche auch
einen einzelnen Monat als abgerechnet setzen (``M<monat>`` statt ``Q<quartal>``)
— im selben Namensraum, ohne die Quartalsmarker anzutasten. Jeder gelesene
Marker trägt beide Felder: `quartal` (bei einem Monatsmarker das Quartal, in
dem der Monat liegt) und `monat` (``None`` bei einem Quartalsmarker).
"""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_abg_monat.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _neues_objekt(c, name: str) -> str:
    antwort = c.post("/api/objekte", json={
        "name": name, "ort": "Teststadt", "turnus": "kalender",
        "start_monat": 1, "kostenarten": ["Strom"],
        "einheiten": [{"bezeichnung": "EG", "flaeche": 70.0,
                       "partei": "Müller"}],
    })
    assert antwort.status_code == 201, antwort.text
    return antwort.json()["slug"]


def _nutzer(c, slug: str, name: str) -> dict:
    antwort = c.post(f"/api/tankstelle/{slug}/nutzer", json={"name": name})
    assert antwort.status_code == 201, antwort.text
    return antwort.json()


def test_monat_marker_setzen_traegt_monat_und_quartal(client):
    """`monate:[4]` setzt einen Monatsmarker; er kommt mit `monat==4` und dem
    Quartal 2 zurück (April gehört zu Q2)."""
    slug = _neues_objekt(client, "Monatshaus")
    n = _nutzer(client, slug, "Marvin")

    r = client.put(f"/api/tankstelle/{slug}/abgerechnet",
                   json={"jahr": 2025, "monate": [4], "nutzer_id": n["id"],
                         "abgerechnet": True})
    assert r.status_code == 200, r.text

    d = client.get(f"/api/tankstelle/{slug}/abgerechnet").json()["abgerechnet"]
    assert len(d) == 1
    m = d[0]
    assert m["monat"] == 4
    assert m["quartal"] == 2
    assert m["jahr"] == 2025
    assert m["nutzer_id"] == n["id"]


def test_monat_marker_wieder_entfernen(client):
    """`abgerechnet:false` mit `monate:[4]` leert den Marker — er erscheint
    danach nicht mehr."""
    slug = _neues_objekt(client, "Leerhaus")
    n = _nutzer(client, slug, "Marvin")

    client.put(f"/api/tankstelle/{slug}/abgerechnet",
               json={"jahr": 2025, "monate": [4], "nutzer_id": n["id"],
                     "abgerechnet": True})
    assert len(client.get(f"/api/tankstelle/{slug}/abgerechnet"
                          ).json()["abgerechnet"]) == 1

    client.put(f"/api/tankstelle/{slug}/abgerechnet",
               json={"jahr": 2025, "monate": [4], "nutzer_id": n["id"],
                     "abgerechnet": False})
    rest = client.get(f"/api/tankstelle/{slug}/abgerechnet").json()["abgerechnet"]
    assert all(m["monat"] != 4 for m in rest)
    assert rest == []


def test_ausser_bereich_monate_werden_still_ignoriert(client):
    """Monate außerhalb 1–12 fallen weg; nur der gültige Monat bleibt."""
    slug = _neues_objekt(client, "Bereichshaus")
    n = _nutzer(client, slug, "Marvin")

    client.put(f"/api/tankstelle/{slug}/abgerechnet",
               json={"jahr": 2025, "monate": [0, 4, 13], "nutzer_id": n["id"],
                     "abgerechnet": True})
    d = client.get(f"/api/tankstelle/{slug}/abgerechnet").json()["abgerechnet"]
    assert [m["monat"] for m in d] == [4]


def test_quartals_und_monatsmarker_stehen_nebeneinander(client):
    """Ein bereits gesetzter Quartalsmarker bleibt (mit `monat is None`), wenn
    daneben ein Monatsmarker gesetzt wird."""
    slug = _neues_objekt(client, "Mischhaus")
    n = _nutzer(client, slug, "Marvin")

    # Erst quartalsweise (der bisherige Weg, unverändert).
    client.put(f"/api/tankstelle/{slug}/abgerechnet",
               json={"jahr": 2025, "quartal": 3, "nutzer_id": n["id"],
                     "abgerechnet": True})
    # Dann ein einzelner Monat aus einem anderen Quartal.
    client.put(f"/api/tankstelle/{slug}/abgerechnet",
               json={"jahr": 2025, "monate": [4], "nutzer_id": n["id"],
                     "abgerechnet": True})

    d = client.get(f"/api/tankstelle/{slug}/abgerechnet").json()["abgerechnet"]
    quartalsmarker = [m for m in d if m["monat"] is None]
    monatsmarker = [m for m in d if m["monat"] is not None]
    assert [m["quartal"] for m in quartalsmarker] == [3]
    assert quartalsmarker[0]["monat"] is None
    assert [(m["monat"], m["quartal"]) for m in monatsmarker] == [(4, 2)]


def test_quartals_put_ohne_monate_verhaelt_sich_unveraendert(client):
    """Ohne `monate` bleibt alles wie bisher: `quartal=0` markiert alle vier
    Quartale, jeder mit `monat is None`."""
    slug = _neues_objekt(client, "Unveraendert")
    n = _nutzer(client, slug, "Marvin")

    client.put(f"/api/tankstelle/{slug}/abgerechnet",
               json={"jahr": 2025, "quartal": 0, "nutzer_id": n["id"],
                     "abgerechnet": True})
    d = client.get(f"/api/tankstelle/{slug}/abgerechnet").json()["abgerechnet"]
    assert sorted(m["quartal"] for m in d) == [1, 2, 3, 4]
    assert all(m["monat"] is None for m in d)
