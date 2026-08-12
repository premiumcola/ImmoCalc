"""N364 — der Abschluss-Haken für Positionen ohne Beleg (Heizöl).

Öl hat keinen Beleg, der die Periode abschließt: der Verbrauch stimmt erst,
wenn alle Lieferungen UND der Zähler-Endstand drin sind. Das weiß nur der
Nutzer, deshalb hakt er es selbst ab.

`bestaetigt` ist bewusst NICHT `status`: die Öl-Sammelposition legt kein Geld
um (ihr Betrag erreicht die Einheiten über Heizung/Warmwasser), sie trägt
deshalb 0 €. Genau solche 0-€-Zeilen stuft `belegposten.anlegen` von
„erledigt" auf „offen" zurück (N238) — dieser Wächter bleibt, und der Haken
lebt daneben.
"""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(),
                                     "test_position_bestaetigt.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def _zeile(c, name):
    z = c.get("/api/zeitraeume/1").json()
    return next((k for k in z["checkliste"] if k["kostenart"] == name), None)


def test_bestaetigt_haelt_auch_bei_null_euro():
    """Der Haken überlebt, wo `status='erledigt'` zurückgestuft würde."""
    with TestClient(app) as c:
        neu = c.post("/api/zeitraeume/1/positionen",
                     json={"kostenart": "Heizkosten-N364", "betrag": 0})
        assert neu.status_code == 201, neu.text
        pid = neu.json()["id"]
        # Der Wächter (N238): 0 € ohne Beleg bleibt „offen".
        assert neu.json()["status"] == "offen"

        gesetzt = c.patch(f"/api/positionen/{pid}", json={"bestaetigt": True})
        assert gesetzt.status_code == 200, gesetzt.text

        zeile = _zeile(c, "Heizkosten-N364")
        assert zeile["bestaetigt"] is True
        # Der Betrag bleibt 0 — nichts wird doppelt umgelegt.
        assert not zeile["betrag"]
        assert zeile["erledigt"] is False


def test_bestaetigt_ist_umkehrbar():
    """Ein Haken, der sich nicht lösen lässt, wäre eine Sackgasse."""
    with TestClient(app) as c:
        pid = c.post("/api/zeitraeume/1/positionen",
                     json={"kostenart": "Heizkosten-N364b", "betrag": 0}
                     ).json()["id"]
        c.patch(f"/api/positionen/{pid}", json={"bestaetigt": True})
        c.patch(f"/api/positionen/{pid}", json={"bestaetigt": False})
        assert _zeile(c, "Heizkosten-N364b")["bestaetigt"] is False


def test_neue_position_ist_unbestaetigt():
    """Additiv: der Default ist False, nichts kippt von allein auf grün."""
    with TestClient(app) as c:
        c.post("/api/zeitraeume/1/positionen",
               json={"kostenart": "Heizkosten-N364c", "betrag": 120.0})
        assert _zeile(c, "Heizkosten-N364c")["bestaetigt"] is False
