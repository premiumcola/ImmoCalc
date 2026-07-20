"""Eine gewachsene Datenbank ohne die neuen Spalten muss weiterlaufen.

Genau das ist in der Produktion gebrochen: create_all legt nur fehlende
Tabellen an, die vorhandene `objekt`-Tabelle blieb ohne die neuen Spalten
zurück und der Start scheiterte.
"""
import os
import sys
import tempfile

import pytest
from sqlalchemy import create_engine, inspect, text

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.migrate import migriere  # noqa: E402

# Schema, wie es vor der Erweiterung aussah — ohne aktiv/strasse/kaufpreis/...
ALTES_SCHEMA = """
CREATE TABLE objekt (
    id INTEGER NOT NULL PRIMARY KEY,
    slug VARCHAR NOT NULL,
    name VARCHAR NOT NULL,
    ort VARCHAR NOT NULL,
    typ VARCHAR NOT NULL,
    nutzung VARCHAR NOT NULL,
    turnus VARCHAR NOT NULL,
    start_monat INTEGER NOT NULL
);
INSERT INTO objekt (id, slug, name, ort, typ, nutzung, turnus, start_monat)
VALUES (1, 'obj-alt', 'Altbestand 3', 'Musterstadt', 'lg-mfhA', 'Wohnen', 'kalender', 1);
"""


@pytest.fixture()
def alte_db(tmp_path):
    pfad = tmp_path / "alt.db"
    engine = create_engine(f"sqlite:///{pfad}")
    with engine.begin() as conn:
        for anweisung in filter(str.strip, ALTES_SCHEMA.split(";")):
            conn.execute(text(anweisung))
    return pfad


def test_fehlende_spalten_werden_ergaenzt(alte_db):
    engine = create_engine(f"sqlite:///{alte_db}")
    import app.models  # noqa: F401  — registriert die Tabellen im Metadata

    vorher = {s["name"] for s in inspect(engine).get_columns("objekt")}
    assert "aktiv" not in vorher

    geaendert = migriere(engine)

    nachher = {s["name"] for s in inspect(engine).get_columns("objekt")}
    for neu in ("aktiv", "strasse", "plz", "flaeche", "kaufpreis", "nc_ordner"):
        assert neu in nachher, f"{neu} fehlt weiterhin"
    assert any("objekt.aktiv" == g for g in geaendert)

    # Bestandsdaten bleiben erhalten und bekommen den Vorgabewert
    with engine.begin() as conn:
        zeile = conn.execute(text("SELECT name, aktiv FROM objekt WHERE id = 1")).one()
    assert zeile[0] == "Altbestand 3"
    assert zeile[1] == 1          # default True nachgezogen


def test_migration_ist_wiederholbar(alte_db):
    engine = create_engine(f"sqlite:///{alte_db}")
    import app.models  # noqa: F401

    assert migriere(engine)        # erster Lauf ergänzt
    assert migriere(engine) == []  # zweiter Lauf findet nichts mehr


def test_orm_zugriff_auf_alter_datenbank(alte_db):
    """Der eigentliche Produktionsfehler: das ORM fragt Spalten ab, die die
    gewachsene Tabelle nicht hat -> OperationalError beim Start."""
    from sqlmodel import Session, select

    from app.models import Objekt

    engine = create_engine(f"sqlite:///{alte_db}")

    with pytest.raises(Exception) as fehler:
        with Session(engine) as s:
            s.exec(select(Objekt)).all()
    assert "aktiv" in str(fehler.value)      # genau die fehlende Spalte

    migriere(engine)

    with Session(engine) as s:
        objekte = s.exec(select(Objekt)).all()
    assert [o.name for o in objekte] == ["Altbestand 3"]
    assert objekte[0].aktiv is True
