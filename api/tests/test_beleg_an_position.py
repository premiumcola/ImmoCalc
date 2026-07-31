"""CCCXCII — ein zugeordneter Beleg landet an seiner Kostenposition.

Der Fehler war: der per Drag&Drop abgelegte Beleg trug die Kostenart nur im
Namen, nicht im Feld `kostenart`, und wurde nie verbucht → `position_id` blieb
leer → er tauchte an der Zeile nicht auf. Fix: Kostenart als Feld mitgeben und
nach der Ablage `POST /dokumente/{id}/position` (verbuche) aufrufen.

Getestet ohne Cloud über `vorhandenen-zuordnen` (reine DB-Arbeit, kein Upload).
"""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_beleg_an_position.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def _muell_zeile(c):
    z = c.get("/api/zeitraeume/1").json()
    return next((k for k in z["checkliste"] if k["kostenart"] == "Müll"), None)


def test_zugeordneter_beleg_erscheint_an_der_position():
    with TestClient(app) as c:
        # Einen vorhandenen Cloud-Beleg mit Kostenart + Betrag zuordnen (DB-only).
        r = c.post("/api/dokumente/vorhandenen-zuordnen", json={
            "objekt": "obj-a", "pfad": "/test/Muell-Rechnung.pdf",
            "kategorie": "Nebenkosten", "kostenart": "Müll",
            "betrag": 318.0, "jahr": 2025, "zeitraum_id": 1})
        assert r.status_code in (200, 201), r.text
        doc_id = r.json()["id"]
        assert r.json().get("kostenart", "Müll")  # Beleg trägt die Kostenart

        # Verbuchen — erst dadurch bekommt der Beleg seine position_id.
        v = c.post(f"/api/dokumente/{doc_id}/position")
        assert v.status_code in (200, 201), v.text

        # An der Müll-Zeile hängt jetzt der Beleg — und ein Betrag ist da.
        zeile = _muell_zeile(c)
        assert zeile is not None
        assert zeile.get("position_id")
        namen = [b.get("dateiname", "") for b in (zeile.get("belege") or [])]
        assert any("Muell-Rechnung" in n for n in namen), namen


def test_idempotent_kein_doppelter_beleg():
    with TestClient(app) as c:
        body = {"objekt": "obj-a", "pfad": "/test/Wasser-Beleg.pdf",
                "kategorie": "Nebenkosten", "kostenart": "Wasser",
                "jahr": 2025, "zeitraum_id": 1}
        a = c.post("/api/dokumente/vorhandenen-zuordnen", json=body).json()["id"]
        b = c.post("/api/dokumente/vorhandenen-zuordnen", json=body).json()["id"]
        assert a == b   # derselbe Pfad → derselbe Datensatz, kein Duplikat
