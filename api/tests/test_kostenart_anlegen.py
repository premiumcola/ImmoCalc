"""N408 — eine Kostenart ohne Position ließ sich am Bestandsobjekt bisher gar
nicht anlegen: sie entstand nur beiläufig beim Objekt anlegen oder als
Nebeneffekt, wenn eine Position auf einen neuen Namen umgehängt wird
(`kostenart_aendern`). Neu: POST /api/objekte/{slug}/kostenarten.
"""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(),
                                     "test_kostenart_anlegen.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def _art(c, name):
    arten = c.get("/api/objekte/obj-a/kostenarten").json()
    return next((a for a in arten if a["name"] == name), None)


def test_kostenart_ohne_position_laesst_sich_anlegen():
    with TestClient(app) as c:
        neu = c.post("/api/objekte/obj-a/kostenarten",
                     json={"name": "Zählermiete-N408"})
        assert neu.status_code == 201, neu.text
        assert neu.json()["name"] == "Zählermiete-N408"
        assert neu.json()["umlagefaehig"] is True

        art = _art(c, "Zählermiete-N408")
        assert art is not None
        assert art["aktiv"] is True


def test_doppelter_name_wird_abgewiesen():
    with TestClient(app) as c:
        c.post("/api/objekte/obj-a/kostenarten", json={"name": "Doppelt-N408"})
        zweiter = c.post("/api/objekte/obj-a/kostenarten",
                         json={"name": "Doppelt-N408"})
        assert zweiter.status_code == 409


def test_leerer_name_wird_abgewiesen():
    with TestClient(app) as c:
        antwort = c.post("/api/objekte/obj-a/kostenarten", json={"name": "  "})
        assert antwort.status_code == 400


def test_unbekanntes_objekt_ist_404():
    with TestClient(app) as c:
        antwort = c.post("/api/objekte/kein-objekt/kostenarten",
                         json={"name": "Irgendwas"})
        assert antwort.status_code == 404


def test_nicht_umlagefaehig_und_optional_lassen_sich_gleich_mitgeben():
    with TestClient(app) as c:
        neu = c.post("/api/objekte/obj-a/kostenarten", json={
            "name": "Abrechnungskosten-N408", "umlagefaehig": True,
            "optional": True})
        assert neu.status_code == 201, neu.text
        art = _art(c, "Abrechnungskosten-N408")
        assert art["optional"] is True


# N443 — versehentlich Angelegtes wieder loswerden (Anlass: eine
# `__deploy-probe__`-Kostenart aus einem Deploy-Test blieb in echten Daten).
def test_unbenutzte_kostenart_laesst_sich_loeschen():
    with TestClient(app) as c:
        neu = c.post("/api/objekte/obj-a/kostenarten",
                     json={"name": "__probe-N443__"}).json()
        assert c.delete(f"/api/kostenarten/{neu['id']}").status_code == 204
        assert _art(c, "__probe-N443__") is None


def test_benutzte_kostenart_bleibt_stehen():
    """Sie mitzunehmen hiesse, die Geschichte ihrer Positionen mitzunehmen."""
    with TestClient(app) as c:
        art = c.post("/api/objekte/obj-a/kostenarten",
                     json={"name": "__belegt-N443__"}).json()
        zid = c.get("/api/objekte/obj-a").json()["zeitraeume"][0]["id"]
        angelegt = c.post(f"/api/zeitraeume/{zid}/positionen",
                          json={"kostenart": "__belegt-N443__",
                                "kosten": 120.0, "schluessel": "flaeche"})
        assert angelegt.status_code in (200, 201), angelegt.text

        antwort = c.delete(f"/api/kostenarten/{art['id']}")
        assert antwort.status_code == 409, antwort.text
        assert "benutzt" in antwort.json()["detail"]
        # Und sie steht danach noch im Katalog.
        assert _art(c, "__belegt-N443__") is not None
