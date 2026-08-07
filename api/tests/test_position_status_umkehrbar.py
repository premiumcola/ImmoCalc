"""N238 — eine Position wird „offen", wenn ihr Betrag auf 0 korrigiert wird.

Bisher setzte `PATCH /positionen/{pid}` und `belegposten._schreibe`/
`nachrechnen` den Zustand nur NACH „erledigt" (ein Betrag > 0 heisst fertig),
nie zurück nach „offen": ein Info-Beleg (SEPA-Mandat, Abbuchungsvorankündigung)
ohne echten Rechnungsbetrag liess die Zeile grün mit „0,00 €" stehen — ein
klarer Verstoss gegen den roten Faden #11 (erledigt nur, wenn wirklich fertig).
"""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(),
                                     "test_position_status_umkehrbar.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def _check(c, name):
    z = c.get("/api/zeitraeume/1").json()
    return next((k for k in z["checkliste"] if k["kostenart"] == name), None)


def test_betrag_auf_null_setzt_position_zurueck_auf_offen():
    with TestClient(app) as c:
        neu = c.post("/api/zeitraeume/1/positionen",
                     json={"kostenart": "Grundsteuer-N238-Test", "betrag": 0})
        assert neu.status_code == 201
        pid = neu.json()["id"]
        assert neu.json()["status"] == "offen"          # 0 € heisst nie erledigt

        hoch = c.patch(f"/api/positionen/{pid}", json={"betrag": 256.36})
        assert hoch.status_code == 200
        assert hoch.json()["status"] == "erledigt"

        runter = c.patch(f"/api/positionen/{pid}", json={"betrag": 0})
        assert runter.status_code == 200
        assert runter.json()["status"] == "offen"        # N238: zurück auf offen

        zeile = _check(c, "Grundsteuer-N238-Test")
        assert zeile is not None
        assert zeile["zustand"] == "offen"


def test_explizit_gesetzter_status_bleibt_massgeblich():
    """Ein ausdrücklich mitgeschickter `status` gewinnt weiterhin — die
    Ableitung greift nur, wenn der Aufrufer nichts vorgibt."""
    with TestClient(app) as c:
        neu = c.post("/api/zeitraeume/1/positionen",
                     json={"kostenart": "Wasser-N238-Test", "betrag": 50})
        pid = neu.json()["id"]

        r = c.patch(f"/api/positionen/{pid}",
                    json={"betrag": 0, "status": "erledigt"})
        assert r.status_code == 200
        assert r.json()["status"] == "erledigt"
