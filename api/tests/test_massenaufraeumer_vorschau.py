"""N314(h) — warte-archiv und nk-vor-jahr-entfernen: Vorschau als Vorgabe,
wie bei jedem Nachbarn (`belege-abgleichen`, `zeitraeume/aufraeumen`).
"""
import os
import sys
import tempfile
from datetime import date

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(),
                                     "test_massenaufraeumer_vorschau.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Dokument, Kostenposition, Objekt, Zeitraum  # noqa: E402


def _objekt(c, name):
    return c.post("/api/objekte", json={"name": name}).json()["slug"]


def test_warte_archiv_vorschau_ist_die_vorgabe_und_aendert_nichts():
    with TestClient(app) as c:
        slug = _objekt(c, "Archivweg 1")
        with Session(engine) as s:
            o = s.exec(select(Objekt).where(Objekt.slug == slug)).first()
            d = Dokument(objekt_id=o.id, pfad=f"/{slug}/beleg.pdf",
                        dateiname="beleg.pdf", status="zugeordnet")
            s.add(d)
            s.commit()
            s.refresh(d)
            did = d.id

        antwort = c.post("/api/dokumente/warte-archiv")
        assert antwort.status_code == 200
        daten = antwort.json()
        assert daten["vorschau"] is True
        assert daten["belege"] >= 1

        with Session(engine) as s:
            assert s.get(Dokument, did).status == "zugeordnet"  # unverändert


def test_warte_archiv_vorschau_false_stellt_wirklich_zurueck():
    with TestClient(app) as c:
        slug = _objekt(c, "Archivweg 2")
        with Session(engine) as s:
            o = s.exec(select(Objekt).where(Objekt.slug == slug)).first()
            d = Dokument(objekt_id=o.id, pfad=f"/{slug}/beleg2.pdf",
                        dateiname="beleg2.pdf", status="zugeordnet")
            s.add(d)
            s.commit()
            s.refresh(d)
            did = d.id

        antwort = c.post(f"/api/dokumente/warte-archiv?objekt={slug}&vorschau=false")
        assert antwort.status_code == 200
        assert antwort.json()["ok"] is True

        with Session(engine) as s:
            assert s.get(Dokument, did).status == "neu"


def test_nk_vor_jahr_entfernen_vorschau_ist_die_vorgabe():
    with TestClient(app) as c:
        slug = _objekt(c, "Jahresweg 3")
        with Session(engine) as s:
            o = s.exec(select(Objekt).where(Objekt.slug == slug)).first()
            z = Zeitraum(objekt_id=o.id, start=date(2020, 1, 1),
                        ende=date(2020, 12, 31))
            s.add(z)
            s.commit()
            s.refresh(z)
            d = Dokument(objekt_id=o.id, pfad=f"/{slug}/alt.pdf",
                        dateiname="alt.pdf", status="zugeordnet",
                        zeitraum_id=z.id)
            s.add(d)
            s.commit()
            s.refresh(d)
            p = Kostenposition(zeitraum_id=z.id, kostenart="Müll", betrag=50.0,
                              vorlaeufig=True, quelle_dokument_id=d.id)
            s.add(p)
            s.commit()
            s.refresh(p)
            pid, did = p.id, d.id

        antwort = c.post("/api/dokumente/nk-vor-jahr-entfernen?grenze_jahr=2025")
        assert antwort.status_code == 200
        daten = antwort.json()
        assert daten["vorschau"] is True
        assert daten["orange_positionen"] == 1

        with Session(engine) as s:
            assert s.get(Kostenposition, pid) is not None      # unverändert
            assert s.get(Dokument, did).status == "zugeordnet"


def test_nk_vor_jahr_entfernen_vorschau_false_raeumt_wirklich_auf():
    with TestClient(app) as c:
        slug = _objekt(c, "Jahresweg 4")
        with Session(engine) as s:
            o = s.exec(select(Objekt).where(Objekt.slug == slug)).first()
            z = Zeitraum(objekt_id=o.id, start=date(2020, 1, 1),
                        ende=date(2020, 12, 31))
            s.add(z)
            s.commit()
            s.refresh(z)
            d = Dokument(objekt_id=o.id, pfad=f"/{slug}/alt2.pdf",
                        dateiname="alt2.pdf", status="zugeordnet",
                        zeitraum_id=z.id)
            s.add(d)
            s.commit()
            s.refresh(d)
            p = Kostenposition(zeitraum_id=z.id, kostenart="Müll", betrag=50.0,
                              vorlaeufig=True, quelle_dokument_id=d.id)
            s.add(p)
            s.commit()
            s.refresh(p)
            pid, did = p.id, d.id

        antwort = c.post(
            "/api/dokumente/nk-vor-jahr-entfernen?grenze_jahr=2025&vorschau=false")
        assert antwort.status_code == 200
        assert antwort.json()["ok"] is True

        with Session(engine) as s:
            assert s.get(Kostenposition, pid) is None          # entfernt
            assert s.get(Dokument, did).status == "neu"
