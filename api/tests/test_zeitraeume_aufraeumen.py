"""N314(e) — POST /api/zeitraeume/aufraeumen: Vorschau als Vorgabe, und drei
bislang unbeachtete Verknüpfungen (Ablesung, Versandprotokoll,
WegVorauszahlung) schützen einen Zeitraum vor dem Wegräumen.
"""
import os
import sys
import tempfile
from datetime import date

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(),
                                     "test_zeitraeume_aufraeumen.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (Ablesung, Dokument, Kostenposition, Objekt,
                        Versandprotokoll, Vorauszahlung, WegVorauszahlung,
                        Zaehler, Zeitraum)  # noqa: E402


def _objekt(c, name):
    return c.post("/api/objekte", json={"name": name}).json()["slug"]


def _leerer_zeitraum(slug, start, ende):
    """Ein zusätzlicher, komplett leerer Zeitraum — ohne das Standard-
    Anlegen-Objekt-Fenster mitzuzählen."""
    with Session(engine) as s:
        o = s.exec(select(Objekt).where(Objekt.slug == slug)).first()
        z = Zeitraum(objekt_id=o.id, start=date.fromisoformat(start),
                    ende=date.fromisoformat(ende))
        s.add(z)
        s.commit()
        s.refresh(z)
        return z.id


def test_vorschau_ist_die_vorgabe_und_loescht_nichts():
    with TestClient(app) as c:
        slug = _objekt(c, "Vorschauweg 1")
        zid = _leerer_zeitraum(slug, "2030-01-01", "2030-12-31")

        antwort = c.post("/api/zeitraeume/aufraeumen")
        assert antwort.status_code == 200
        daten = antwort.json()
        assert daten["vorschau"] is True
        assert daten["entfernt"] == 0
        assert zid in daten["wuerde_entfernen"]

        with Session(engine) as s:
            assert s.get(Zeitraum, zid) is not None      # nichts gelöscht


def test_vorschau_false_loescht_wirklich():
    with TestClient(app) as c:
        slug = _objekt(c, "Vorschauweg 2")
        zid = _leerer_zeitraum(slug, "2030-01-01", "2030-12-31")

        antwort = c.post("/api/zeitraeume/aufraeumen?vorschau=false")
        assert antwort.status_code == 200
        daten = antwort.json()
        assert daten["vorschau"] is False
        assert daten["entfernt"] >= 1

        with Session(engine) as s:
            assert s.get(Zeitraum, zid) is None


def test_ablesung_versandprotokoll_und_weg_vorauszahlung_schuetzen_den_zeitraum():
    """Vor N314(e) kannten `_verknuepfungen` nur Position/Beleg/Vorauszahlung
    — ein Zeitraum mit bereits abgelesenen Zählern oder einer verschickten
    Abrechnung galt fälschlich als leer."""
    with TestClient(app) as c:
        slug = _objekt(c, "Schutzweg 3")
        z_ablesung = _leerer_zeitraum(slug, "2031-01-01", "2031-12-31")
        z_versand = _leerer_zeitraum(slug, "2032-01-01", "2032-12-31")
        z_weg = _leerer_zeitraum(slug, "2033-01-01", "2033-12-31")

        with Session(engine) as s:
            o = s.exec(select(Objekt).where(Objekt.slug == slug)).first()
            zaehler = Zaehler(objekt_id=o.id, name="Wasser")
            s.add(zaehler)
            s.commit()
            s.refresh(zaehler)
            s.add(Ablesung(zaehler_id=zaehler.id, datum=date(2031, 12, 31),
                           stand=100.0, zeitraum_id=z_ablesung))
            s.add(Versandprotokoll(zeitraum_id=z_versand, partei="Mieter A",
                                   versendet_am=date(2032, 6, 1)))
            s.add(WegVorauszahlung(zeitraum_id=z_weg, einheit="EG",
                                   betrag_monat=80.0))
            s.commit()

        antwort = c.post("/api/zeitraeume/aufraeumen").json()
        assert z_ablesung not in antwort["wuerde_entfernen"]
        assert z_versand not in antwort["wuerde_entfernen"]
        assert z_weg not in antwort["wuerde_entfernen"]

        c.post("/api/zeitraeume/aufraeumen?vorschau=false")
        with Session(engine) as s:
            assert s.get(Zeitraum, z_ablesung) is not None
            assert s.get(Zeitraum, z_versand) is not None
            assert s.get(Zeitraum, z_weg) is not None


def test_zeitraum_entfernen_loest_belege_loescht_positionen():
    """N393 — DELETE /zeitraeume/{id}: Belege bleiben erhalten (nur die
    Zuordnung wird gelöst), Kostenpositionen/Vorauszahlungen/Ablesungen
    gehören untrennbar zum Zeitraum und verschwinden mit ihm."""
    with TestClient(app) as c:
        slug = _objekt(c, "Entfernen-Weg 1")
        zid = _leerer_zeitraum(slug, "2019-01-01", "2019-12-31")

        with Session(engine) as s:
            o = s.exec(select(Objekt).where(Objekt.slug == slug)).first()
            doc = Dokument(pfad=f"/[010]_Immobilien/{o.id}/altes-jahr.pdf",
                           dateiname="altes-jahr.pdf", zeitraum_id=zid)
            s.add(doc)
            s.add(Kostenposition(zeitraum_id=zid, kostenart="Wasser", betrag=42.0))
            s.add(Vorauszahlung(zeitraum_id=zid, partei="Mieter A", betrag=100.0))
            zaehler = Zaehler(objekt_id=o.id, name="Wasser")
            s.add(zaehler)
            s.commit()
            s.refresh(zaehler)
            s.add(Ablesung(zaehler_id=zaehler.id, datum=date(2019, 12, 31),
                           stand=50.0, zeitraum_id=zid))
            s.commit()
            s.refresh(doc)
            doc_id = doc.id

        antwort = c.delete(f"/api/zeitraeume/{zid}")
        assert antwort.status_code == 200
        daten = antwort.json()
        assert daten["entfernt"] is True
        assert daten["belege_geloest"] == 1
        assert daten["positionen_entfernt"] == 1

        with Session(engine) as s:
            assert s.get(Zeitraum, zid) is None
            beleg = s.get(Dokument, doc_id)
            assert beleg is not None                # nicht gelöscht
            assert beleg.zeitraum_id is None         # nur gelöst
            assert not s.exec(select(Kostenposition)
                              .where(Kostenposition.zeitraum_id == zid)).all()
            assert not s.exec(select(Vorauszahlung)
                              .where(Vorauszahlung.zeitraum_id == zid)).all()
            assert not s.exec(select(Ablesung)
                              .where(Ablesung.zeitraum_id == zid)).all()


def test_zeitraum_mit_versandprotokoll_laesst_sich_nicht_entfernen():
    """Eine bereits verschickte Abrechnung ist ein reales, den Mietern
    kommuniziertes Ereignis — kein Aufräumfall, deshalb 409 statt Löschen."""
    with TestClient(app) as c:
        slug = _objekt(c, "Entfernen-Weg 2")
        zid = _leerer_zeitraum(slug, "2019-01-01", "2019-12-31")
        with Session(engine) as s:
            s.add(Versandprotokoll(zeitraum_id=zid, partei="Mieter A",
                                   versendet_am=date(2020, 1, 15)))
            s.commit()

        antwort = c.delete(f"/api/zeitraeume/{zid}")
        assert antwort.status_code == 409
        with Session(engine) as s:
            assert s.get(Zeitraum, zid) is not None


def test_zeitraum_entfernen_unbekannte_id_404():
    with TestClient(app) as c:
        assert c.delete("/api/zeitraeume/999999").status_code == 404
