"""N37 — ein Versicherungsbeleg landet über seinen Anbieter auf der
spezifischen Position, statt eine zweite generische daneben anzulegen.

Der gemeldete Fall (Laufer Str. 5 · 2026): der Anbieter „WWK" hing an der
(leeren) Kostenposition „Gebäudeversicherung", der Beleg trug aber die
generische Kostenart „Versicherung" und legte beim Übernehmen eine zweite
Position an. Erwartet: der Beleg wird über den Anbieter der vorhandenen
„Gebäudeversicherung"-Position zugeordnet — eine Zeile, nicht zwei.
"""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(),
                                     "test_beleg_anbieter_position.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session  # noqa: E402

from app.main import app  # noqa: E402


def _kostenart_id(c, objekt, name):
    for k in c.get(f"/api/objekte/{objekt}/kostenarten").json():
        if k["name"] == name:
            return k["id"]
    return None


def _setze_anbieter_am_beleg(doc_id, anbieter):
    """Das KI-Raster trägt den Anbieter — hier direkt gesetzt, ohne KI-Aufruf."""
    from app import db
    from app.models import Dokument
    with Session(db.engine) as s:
        d = s.get(Dokument, doc_id)
        d.ki_felder = {"anbieter": anbieter}
        s.add(d)
        s.commit()


def _zeile(c, kostenart):
    z = c.get("/api/zeitraeume/1").json()
    return next((k for k in z["checkliste"] if k["kostenart"] == kostenart), None)


def test_versicherungsbeleg_landet_auf_gebaeudeversicherung():
    with TestClient(app) as c:
        # Die vorhandene spezifische Position trägt den Anbieter WWK (über den
        # Kostenart-Katalog) — und ist noch leer (0 €), wie im gemeldeten Fall.
        kid = _kostenart_id(c, "obj-a", "Gebäudeversicherung")
        assert kid is not None
        assert c.patch(f"/api/kostenarten/{kid}",
                       json={"lieferant": "WWK"}).status_code in (200, 201)
        p = c.post("/api/zeitraeume/1/positionen",
                   json={"kostenart": "Gebäudeversicherung", "betrag": 0.0})
        assert p.status_code in (200, 201), p.text
        gv_pos_id = p.json()["id"]

        # Der Beleg kommt mit der GENERISCHEN Kostenart „Versicherung" und dem
        # Anbieter WWK herein.
        r = c.post("/api/dokumente/vorhandenen-zuordnen", json={
            "objekt": "obj-a", "pfad": "/test/WWK-Gebaeudeversicherung-2025.pdf",
            "kategorie": "Versicherung", "kostenart": "Versicherung",
            "betrag": 742.0, "jahr": 2025, "zeitraum_id": 1})
        assert r.status_code in (200, 201), r.text
        doc_id = r.json()["id"]
        _setze_anbieter_am_beleg(doc_id, "WWK")

        # Übernehmen — der Beleg soll auf der vorhandenen Gebäudeversicherung
        # landen, NICHT auf einer neuen „Versicherung"-Position.
        v = c.post(f"/api/dokumente/{doc_id}/position")
        assert v.status_code in (200, 201), v.text
        assert v.json()["position_id"] == gv_pos_id
        assert v.json()["neu"] is False        # keine neue Position

        # Die Gebäudeversicherung trägt jetzt den Betrag und den Beleg …
        gv = _zeile(c, "Gebäudeversicherung")
        assert gv["position_id"] == gv_pos_id
        assert round(gv["betrag"], 2) == 742.0
        namen = [b.get("dateiname", "") for b in (gv.get("belege") or [])]
        assert any("WWK-Gebaeudeversicherung" in n for n in namen), namen

        # … und es gibt keine zweite, generische „Versicherung"-Zeile.
        assert _zeile(c, "Versicherung") is None


def test_ohne_anbieter_keine_umhaengung():
    """Ohne passenden Anbieter bleibt es beim normalen Weg: der Beleg legt
    seine eigene (generische) Position an — es wird nichts geraten."""
    with TestClient(app) as c:
        kid = _kostenart_id(c, "obj-a", "Gebäudeversicherung")
        c.patch(f"/api/kostenarten/{kid}", json={"lieferant": "WWK"})
        c.post("/api/zeitraeume/1/positionen",
               json={"kostenart": "Gebäudeversicherung", "betrag": 0.0})

        r = c.post("/api/dokumente/vorhandenen-zuordnen", json={
            "objekt": "obj-a", "pfad": "/test/Andere-Versicherung-2025.pdf",
            "kategorie": "Versicherung", "kostenart": "Versicherung",
            "betrag": 99.0, "jahr": 2025, "zeitraum_id": 1})
        doc_id = r.json()["id"]
        # Anbieter passt zu KEINER Kostenart des Objekts.
        _setze_anbieter_am_beleg(doc_id, "Allianz")

        v = c.post(f"/api/dokumente/{doc_id}/position")
        assert v.status_code in (200, 201), v.text
        # Eigene, generische Position — nicht auf die Gebäudeversicherung
        # umgehängt (der Anbieter „Allianz" passt zu keiner Kostenart).
        assert v.json()["kostenart"] == "Versicherung"
        ver = _zeile(c, "Versicherung")
        assert ver is not None and ver["position_id"] == v.json()["position_id"]
        namen = [b.get("dateiname", "") for b in (ver.get("belege") or [])]
        assert any("Andere-Versicherung" in n for n in namen), namen
