"""CCCLXII — jede Immobilie braucht Gebäudeversicherung UND Gebäudehaftpflicht.

Der Backfill in `migrate.py` zieht beide Pflicht-Kostenarten je Objekt nach.
Er ist additiv und idempotent: er legt nur an, was fehlt, und ein zweiter Lauf
darf nichts verdoppeln. `migriere` läuft beim Start vor dem Seed — für die
frisch geseedeten Demo-Objekte wird die Routine hier direkt aufgerufen, so wie
sie im Betrieb den Bestand (der schon in der Datenbank steht) erfasst.
"""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(),
                                     "test_haftpflicht_backfill.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.migrate import _fold, pflicht_kostenarten_sichern  # noqa: E402
from app.models import Kostenart, Objekt  # noqa: E402

PFLICHT = ("Gebäudeversicherung", "Gebäudehaftpflicht")


def _namen(c, slug: str) -> list[str]:
    antwort = c.get(f"/api/objekte/{slug}/kostenarten")
    assert antwort.status_code == 200
    return [k["name"] for k in antwort.json()]


def _hat(namen: list[str], gesucht: str) -> bool:
    """Umlaut-/schreibweisentolerant — genau wie der Backfill vergleicht."""
    return any(_fold(n) == _fold(gesucht) for n in namen)


def _alle_slugs() -> list[str]:
    with Session(engine) as s:
        return [o.slug for o in s.exec(select(Objekt)).all()]


def test_jedes_objekt_hat_beide_pflicht_kostenarten():
    """Nach Start + Backfill trägt JEDES Objekt beide Pflicht-Kostenarten."""
    with TestClient(app) as c:
        # Start hat migriere (vor dem Seed, ohne Objekte) und den Seed gefahren.
        # Für die geseedeten Objekte den Backfill nachziehen — dieselbe Routine,
        # die im Betrieb den Bestand erfasst.
        pflicht_kostenarten_sichern(engine)

        slugs = _alle_slugs()
        assert "obj-a" in slugs                        # Seed muss gelaufen sein
        for slug in slugs:
            namen = _namen(c, slug)
            for pflicht in PFLICHT:
                assert _hat(namen, pflicht), f"{slug} fehlt {pflicht}: {namen}"


def test_backfill_ist_idempotent_keine_duplikate():
    """Ein zweiter (und dritter) Lauf legt nichts Doppeltes an."""
    with TestClient(app) as c:
        pflicht_kostenarten_sichern(engine)
        neu = pflicht_kostenarten_sichern(engine)      # zweiter Lauf
        assert neu == []                               # nichts mehr zu tun
        pflicht_kostenarten_sichern(engine)            # dritter Lauf, sicherheitshalber

        for slug in _alle_slugs():
            namen = _namen(c, slug)
            for pflicht in PFLICHT:
                treffer = sum(1 for n in namen if _fold(n) == _fold(pflicht))
                assert treffer == 1, f"{slug}: {pflicht} {treffer}x — {namen}"


def test_backfill_legt_fehlende_haftpflicht_an_ohne_bestand_zu_beruehren():
    """Ein Objekt mit nur „Gebäudeversicherung" bekommt „Gebäudehaftpflicht"
    dazu — die bestehende Versicherung bleibt unangetastet (dieselbe id)."""
    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={"name": "Backfillweg 1"}).json()["slug"]
        with Session(engine) as s:
            o = s.exec(select(Objekt).where(Objekt.slug == slug)).first()
            # Nur die Versicherung — Haftpflicht fehlt bewusst.
            for k in s.exec(select(Kostenart)
                            .where(Kostenart.objekt_id == o.id)).all():
                s.delete(k)
            s.commit()
            vers = Kostenart(objekt_id=o.id, name="Gebäudeversicherung",
                             umlagefaehig=True, aktiv=True)
            s.add(vers)
            s.commit()
            s.refresh(vers)
            vers_id = vers.id

        pflicht_kostenarten_sichern(engine)

        namen = _namen(c, slug)
        assert _hat(namen, "Gebäudeversicherung")
        assert _hat(namen, "Gebäudehaftpflicht")
        with Session(engine) as s:
            # Die vorhandene Versicherung wurde nicht ersetzt oder verändert.
            unveraendert = s.get(Kostenart, vers_id)
            assert unveraendert is not None
            assert unveraendert.name == "Gebäudeversicherung"
            assert unveraendert.aktiv is True
