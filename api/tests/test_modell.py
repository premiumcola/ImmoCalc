"""N213 — Objekt.modell: additiv, Default `standard`, Laufer-One-Off.

Wächter: das neue Feld darf den Bestand nicht brechen und darf keine anderen
Objekte automatisch umstellen — nur Laufer, nur einmal, nur wenn noch Default.
"""
import os
import sys
import tempfile
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlmodel import Session, SQLModel, select

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.migrate import (LAUFER_MODELL, LAUFER_SLUG, laufer_modell_setzen,
                         migriere)                             # noqa: E402
from app.models import Objekt                                  # noqa: E402
from fastapi.testclient import TestClient                       # noqa: E402
from app.main import app                                       # noqa: E402


def test_neues_objekt_hat_modell_standard():
    """Additiv, Default `standard` — auch für frisch angelegte Objekte."""
    with TestClient(app) as c:
        neu = c.post("/api/objekte", json={
            "name": "Modellprüfweg 1",
            "einheiten": [{"bezeichnung": "EG", "flaeche": 60}]}).json()
        zeile = next(o for o in c.get("/api/objekte").json()
                     if o["slug"] == neu["slug"])
        assert zeile["modell"] == "standard"


def test_patch_setzt_modell():
    """PATCH akzeptiert das neue Feld — sonst kann kein Nutzer korrigieren."""
    with TestClient(app) as c:
        neu = c.post("/api/objekte", json={
            "name": "Modellprüfweg 2",
            "einheiten": [{"bezeichnung": "EG", "flaeche": 60}]}).json()
        r = c.patch(f"/api/objekte/{neu['slug']}", json={
            "modell": "laufer_spezial"})
        assert r.status_code == 200, r.text
        zeile = next(o for o in c.get("/api/objekte").json()
                     if o["slug"] == neu["slug"])
        assert zeile["modell"] == "laufer_spezial"

        # Zurück auf standard geht auch — nichts ist eingebrannt.
        r = c.patch(f"/api/objekte/{neu['slug']}", json={"modell": "standard"})
        assert r.status_code == 200, r.text


def test_zeitraum_liefert_modell():
    """Die Zeitraum-Antwort trägt `modell`, damit das Frontend gaten kann."""
    with TestClient(app) as c:
        neu = c.post("/api/objekte", json={
            "name": "Modellprüfweg 3",
            "einheiten": [{"bezeichnung": "EG", "flaeche": 60}]}).json()
        det = c.get(f"/api/objekte/{neu['slug']}").json()
        assert det["zeitraeume"], "Neues Objekt bekommt automatisch einen Zeitraum"
        zid = det["zeitraeume"][0]["id"]
        antwort = c.get(f"/api/zeitraeume/{zid}").json()
        assert antwort["modell"] == "standard"


# --------------------------------------------------------------------------
# Der Laufer-One-Off-Setter — nur der bekannte Slug, nur wenn Default,
# idempotent, und keine anderen Objekte werden angefasst.
# --------------------------------------------------------------------------

def _frische_engine(tmp_path):
    pfad = tmp_path / "modell.db"
    engine = create_engine(f"sqlite:///{pfad}")
    SQLModel.metadata.create_all(engine)
    migriere(engine)
    return engine


def test_laufer_setzer_ohne_objekt_ist_kein_fehler(tmp_path):
    """Frische DB ohne Bestand: der Setter tut einfach nichts."""
    engine = _frische_engine(tmp_path)
    assert laufer_modell_setzen(engine) is False


def test_laufer_setzer_setzt_laufer_um(tmp_path):
    """Steht der bekannte Slug in der DB und ist noch Default, wird er auf
    `laufer_spezial` gehoben — ein zweiter Lauf tut nichts mehr."""
    engine = _frische_engine(tmp_path)
    with Session(engine) as s:
        s.add(Objekt(slug=LAUFER_SLUG, name="Laufer Str. 5", ort="Eschenau"))
        s.commit()

    assert laufer_modell_setzen(engine) is True
    with Session(engine) as s:
        laufer = s.exec(select(Objekt).where(Objekt.slug == LAUFER_SLUG)).one()
        assert laufer.modell == LAUFER_MODELL

    # Idempotent: zweiter Lauf → False, Wert bleibt.
    assert laufer_modell_setzen(engine) is False
    with Session(engine) as s:
        laufer = s.exec(select(Objekt).where(Objekt.slug == LAUFER_SLUG)).one()
        assert laufer.modell == LAUFER_MODELL


def test_laufer_setzer_ueberschreibt_keine_bewusste_wahl(tmp_path):
    """Hat der Nutzer Laufer bewusst auf `standard` (oder anderes) gestellt,
    wird nicht zurückgedreht — nur der Default wird ersetzt."""
    engine = _frische_engine(tmp_path)
    with Session(engine) as s:
        # Als hätte der Nutzer nach der Erst-Migration Laufer bewusst
        # zurückgestellt — der Setter macht das NICHT rückgängig.
        s.add(Objekt(slug=LAUFER_SLUG, name="Laufer Str. 5", ort="Eschenau",
                     modell="etwas-anderes"))
        s.commit()

    assert laufer_modell_setzen(engine) is False
    with Session(engine) as s:
        laufer = s.exec(select(Objekt).where(Objekt.slug == LAUFER_SLUG)).one()
        assert laufer.modell == "etwas-anderes"


def test_laufer_setzer_ruehrt_andere_slugs_nicht_an(tmp_path):
    """Ein anderes Objekt bekommt nie automatisch `laufer_spezial` — auch
    dann nicht, wenn zufällig sein Name „Laufer" enthält."""
    engine = _frische_engine(tmp_path)
    with Session(engine) as s:
        s.add(Objekt(slug="andere-strasse-1", name="Laufer-Weg 1",
                     ort="Nirgends"))
        s.commit()

    assert laufer_modell_setzen(engine) is False
    with Session(engine) as s:
        andere = s.exec(select(Objekt).where(
            Objekt.slug == "andere-strasse-1")).one()
        assert andere.modell == "standard"


def test_migration_gewachsene_db_ergaenzt_modell_als_standard(tmp_path):
    """Der Wächter (test_migration.py) prüft ausdrücklich, dass eine
    gewachsene DB weiterläuft. Hier zusätzlich: die neue Spalte `modell` ist
    hinterher da und trägt den Default `standard` — nichts, was schon dastand,
    verschwindet oder wechselt still auf `laufer_spezial`."""
    from sqlalchemy import inspect, text
    pfad = tmp_path / "alt.db"
    engine = create_engine(f"sqlite:///{pfad}")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE objekt (id INTEGER PRIMARY KEY, slug VARCHAR, "
            "name VARCHAR, ort VARCHAR, typ VARCHAR, nutzung VARCHAR, "
            "turnus VARCHAR, start_monat INTEGER)"))
        conn.execute(text(
            "INSERT INTO objekt (id, slug, name, ort, typ, nutzung, "
            "turnus, start_monat) VALUES "
            "(1, 'gewachsen', 'Bestand', 'Musterstadt', 'lg-mfhA', "
            "'Wohnen', 'kalender', 1)"))

    import app.models  # noqa: F401
    migriere(engine)

    spalten = {s["name"] for s in inspect(engine).get_columns("objekt")}
    assert "modell" in spalten
    with Session(engine) as s:
        objekt = s.exec(select(Objekt).where(Objekt.slug == "gewachsen")).one()
        assert objekt.modell == "standard"
