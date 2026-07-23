"""CCXLIX — Erkennungsmuster: Nutzer-Wörter steuern die Richtung.

Kern ist die normalisierte Treffer-Logik: ein Muster muss auch den zerrupften
Scan treffen („N-ERGIE Netz" == „N - E R G I E  N e t z")."""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_regeln.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402

from app import ocr  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Erkennungsregel  # noqa: E402


def test_muster_trifft_auch_den_zerrupften_scan():
    regeln = [Erkennungsregel(muster="N-ERGIE Netz", kategorie="Sonstiges",
                              kostenart="Zählerablesung", ist_kosten=False)]
    zerrupft = "Rechnung  N - E R G I E   N e t z   GmbH  90338 Nürnberg"
    treffer = ocr.regel_richtung(zerrupft, regeln)
    assert treffer == ("Sonstiges", "Zählerablesung", False)


def test_hoeherer_rang_und_laenge_gewinnt():
    regeln = [
        Erkennungsregel(muster="Versicherung", kategorie="Nebenkosten",
                        kostenart="Gebäudeversicherung", rang=5),
        Erkennungsregel(muster="WWK", kategorie="Nebenkosten",
                        kostenart="Gebäudehaftpflicht", rang=1),
    ]
    # rang 1 vor rang 5 — die WWK-Regel greift zuerst
    assert ocr.regel_richtung("WWK Versicherung AG", regeln)[1] == "Gebäudehaftpflicht"


def test_kein_treffer_bleibt_none():
    regeln = [Erkennungsregel(muster="Schornsteinfeger", kategorie="Nebenkosten")]
    assert ocr.regel_richtung("Stadtwerke Wasserrechnung", regeln) is None


def test_crud_und_liste():
    with TestClient(app) as c:
        angelegt = c.post("/api/dokumente/erkennungsregeln", json={
            "muster": "Landratsamt", "kategorie": "Nebenkosten",
            "kostenart": "Abfall"}).json()
        rid = angelegt["id"]
        assert angelegt["kostenart"] == "Abfall"

        liste = c.get("/api/dokumente/erkennungsregeln").json()
        assert any(r["id"] == rid for r in liste)

        c.patch(f"/api/dokumente/erkennungsregeln/{rid}", json={"aktiv": False})
        assert c.delete(f"/api/dokumente/erkennungsregeln/{rid}").json()["ok"] is True


def test_leeres_muster_wird_abgelehnt():
    with TestClient(app) as c:
        assert c.post("/api/dokumente/erkennungsregeln",
                      json={"muster": "  "}).status_code == 400
