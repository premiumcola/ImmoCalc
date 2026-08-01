"""N… — der Objekt-Endpunkt liefert je Zeitraum die Anzahl der
Kostenpositionen und der zugeordneten Belege.

Das Frontend blendet damit leere Zeiträume (0 Positionen) aus und bietet die
belegbehafteten dezent zum Öffnen an. Rein additive Felder — der Bestand bleibt
unberührt.
"""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(),
                                     "test_zeitraum_zaehler.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session  # noqa: E402

from app.main import app  # noqa: E402


def _beleg(zeitraum_id, objekt_id, name):
    """Legt einen zugeordneten Beleg direkt in der DB an (ohne Cloud/Scan)."""
    from app import db
    from app.models import Dokument
    with Session(db.engine) as s:
        s.add(Dokument(pfad=f"/test/{name}", dateiname=name,
                       objekt_id=objekt_id, zeitraum_id=zeitraum_id))
        s.commit()


def test_objekt_endpunkt_zaehlt_positionen_und_belege():
    with TestClient(app) as c:
        neu = c.post("/api/objekte", json={
            "name": "Zählerweg 3",
            "einheiten": [{"bezeichnung": "EG", "flaeche": 60, "partei": "M"}]}
        ).json()
        slug = neu["slug"]
        objekt_id = neu["id"]

        det = c.get(f"/api/objekte/{slug}").json()
        assert det["zeitraeume"], "Ein neues Objekt bekommt einen Zeitraum"
        laufend = next(z for z in det["zeitraeume"] if z["status"] == "in Arbeit")

        # Felder sind additiv vorhanden und anfangs 0.
        for z in det["zeitraeume"]:
            assert z["positionen"] == 0
            assert z["belege"] == 0

        # Zwei Positionen an den laufenden Zeitraum (je eigene Kostenart —
        # dieselbe Kostenart ein zweites Mal wäre ein 409).
        for kostenart, betrag in (("Wasser", 100.0), ("Müll", 50.0)):
            r = c.post(f"/api/zeitraeume/{laufend['id']}/positionen",
                       json={"kostenart": kostenart, "betrag": betrag})
            assert r.status_code in (200, 201), r.text

        # Ein Vorjahres-Zeitraum ohne Positionen, aber mit drei Belegen.
        vj = c.post(f"/api/objekte/{slug}/zeitraeume", json={"jahr": 2018})
        assert vj.status_code in (200, 201), vj.text
        alt_id = vj.json()["id"]
        for i in range(3):
            _beleg(alt_id, objekt_id, f"beleg-{i}.pdf")
        # Ein Beleg auch am laufenden Zeitraum.
        _beleg(laufend["id"], objekt_id, "aktuell.pdf")

        det2 = c.get(f"/api/objekte/{slug}").json()
        zmap = {z["id"]: z for z in det2["zeitraeume"]}

        assert zmap[laufend["id"]]["positionen"] == 2
        assert zmap[laufend["id"]]["belege"] == 1
        assert zmap[alt_id]["positionen"] == 0
        assert zmap[alt_id]["belege"] == 3
