"""N436 — Mandantentrennung: eine echte Bestandsdatenbank (vor N436, also ohne
`familie_id`, mit dem alten GLOBAL eindeutigen `ix_objekt_slug`/
`ix_kontakt_schluessel`) muss nach der Migration eine Bestandsfamilie
("Heidenreich") haben, jede Zeile zugeordnet bekommen, und zwei Familien
müssen danach denselben Slug/Schlüssel verwenden dürfen — nur DANN ist die
Migration nicht bloß additiv, sondern tatsächlich sicher für den echten
Bestand, der beim ersten Deploy genau diese alte Form hat.
"""
import os
import sys
import tempfile

DB_PATH = os.path.join(tempfile.mkdtemp(), "test_familie_backfill.db")
os.environ["DB_PATH"] = DB_PATH
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlalchemy import create_engine, text  # noqa: E402
from sqlmodel import Session, SQLModel, select  # noqa: E402

from app.migrate import BESTANDSFAMILIE_NAME, migriere  # noqa: E402
from app.models import Eigentuemer, Familie, Kontakt, Objekt  # noqa: E402


def _neue_engine():
    """Jeder Test bekommt eine eigene, frische Datei — die drei Tests bauen
    sich sonst gegenseitig ihr handgebautes Altschema kaputt (dieselbe
    `objekt`-Tabelle existierte schon aus einem vorherigen Test)."""
    pfad = os.path.join(tempfile.mkdtemp(), "bestand.db")
    return create_engine(f"sqlite:///{pfad}", connect_args={"check_same_thread": False})


def _altes_bestandsschema(engine):
    """Baut von Hand die Vor-N436-Form nach: `objekt.slug`/`kontakt.schluessel`
    global eindeutig, keine `familie_id`-Spalte irgendwo — genau der Stand,
    den die echte Produktionsdatenbank beim ersten Deploy dieser Änderung
    hat."""
    with engine.begin() as conn:
        conn.execute(text(
            'CREATE TABLE objekt (id INTEGER PRIMARY KEY, slug TEXT, name TEXT)'))
        conn.execute(text(
            'CREATE UNIQUE INDEX ix_objekt_slug ON objekt (slug)'))
        conn.execute(text(
            "INSERT INTO objekt (slug, name) VALUES ('obj-a', 'Haus A')"))
        conn.execute(text(
            "INSERT INTO objekt (slug, name) VALUES ('obj-b', 'Haus B')"))

        conn.execute(text(
            'CREATE TABLE kontakt (id INTEGER PRIMARY KEY, schluessel TEXT, firma TEXT)'))
        conn.execute(text(
            'CREATE UNIQUE INDEX ix_kontakt_schluessel ON kontakt (schluessel)'))
        conn.execute(text(
            "INSERT INTO kontakt (schluessel, firma) VALUES ('stadtwerke', 'Stadtwerke')"))

        conn.execute(text(
            'CREATE TABLE eigentuemer (id INTEGER PRIMARY KEY, name TEXT)'))
        conn.execute(text(
            "INSERT INTO eigentuemer (name) VALUES ('Max Mustermann')"))


def test_bestand_bekommt_eine_familie_und_wird_ihr_zugeordnet():
    """Kernfall: eine Datenbank aus der Zeit vor N436 bekommt beim ersten
    Start nach diesem Update automatisch die Familie "Heidenreich", und jede
    vorher unzugeordnete Zeile wird ihr zugeordnet — ohne dass irgendetwas
    an den ursprünglichen Werten (slug, name, firma) sich ändert."""
    engine = _neue_engine()
    _altes_bestandsschema(engine)

    # create_all legt nur NEUE Tabellen an (familie, sitzung, ...) — die
    # handgebauten objekt/kontakt/eigentuemer bleiben unangetastet, genau wie
    # bei einem echten Programmstart gegen eine bestehende Datenbank.
    SQLModel.metadata.create_all(engine)
    migriere(engine)

    with Session(engine) as s:
        familie = s.exec(select(Familie)
                         .where(Familie.name == BESTANDSFAMILIE_NAME)).first()
        assert familie is not None
        assert familie.passwort_hash is None      # Migration erfindet kein Passwort

        objekte = s.exec(select(Objekt)).all()
        assert len(objekte) == 2
        assert {o.slug for o in objekte} == {"obj-a", "obj-b"}   # unverändert
        assert all(o.familie_id == familie.id for o in objekte)

        kontakt = s.exec(select(Kontakt)).first()
        assert kontakt.schluessel == "stadtwerke"                # unverändert
        assert kontakt.familie_id == familie.id

        eigentuemer = s.exec(select(Eigentuemer)).first()
        assert eigentuemer.name == "Max Mustermann"              # unverändert
        assert eigentuemer.familie_id == familie.id


def test_migration_ist_idempotent_ueberschreibt_keine_zuordnung():
    """Ein zweiter Lauf legt keine zweite Familie an und rührt eine bereits
    gesetzte (ggf. bewusst abweichende) `familie_id` nicht an."""
    engine = _neue_engine()
    _altes_bestandsschema(engine)
    SQLModel.metadata.create_all(engine)
    migriere(engine)

    with Session(engine) as s:
        andere_familie = Familie(name="Kumpelfamilie", passwort_hash="x")
        s.add(andere_familie)
        s.commit()
        s.refresh(andere_familie)
        obj_b = s.exec(select(Objekt).where(Objekt.slug == "obj-b")).first()
        obj_b.familie_id = andere_familie.id      # bewusst umgehängt
        s.add(obj_b)
        s.commit()

    migriere(engine)      # zweiter Lauf

    with Session(engine) as s:
        familien = s.exec(select(Familie)).all()
        namen = sorted(f.name for f in familien)
        assert namen.count(BESTANDSFAMILIE_NAME) == 1     # keine zweite Bestandsfamilie
        assert "Kumpelfamilie" in namen

        obj_b = s.exec(select(Objekt).where(Objekt.slug == "obj-b")).first()
        andere = s.exec(select(Familie).where(Familie.name == "Kumpelfamilie")).first()
        assert obj_b.familie_id == andere.id              # bewusste Zuordnung blieb


def test_slug_und_schluessel_sind_nur_noch_je_familie_eindeutig():
    """Der eigentliche Zweck der Migration: zwei Familien dürfen danach
    denselben Slug bzw. denselben Kontakt-Schlüssel verwenden — vorher hätte
    der alte globale Unique-Index das zweite INSERT abgelehnt."""
    engine = _neue_engine()
    _altes_bestandsschema(engine)
    SQLModel.metadata.create_all(engine)
    migriere(engine)

    with Session(engine) as s:
        heidenreich = s.exec(select(Familie)
                             .where(Familie.name == BESTANDSFAMILIE_NAME)).first()
        kumpel = Familie(name="Kumpelfamilie", passwort_hash="x")
        s.add(kumpel)
        s.commit()
        s.refresh(kumpel)

        # Derselbe Slug wie obj-a bei Heidenreich — vorher hätte das den
        # globalen Unique-Index verletzt.
        s.add(Objekt(slug="obj-a", name="Haus A (Kumpel)", familie_id=kumpel.id))
        s.commit()

        objekte_a = s.exec(select(Objekt).where(Objekt.slug == "obj-a")).all()
        assert len(objekte_a) == 2
        assert {o.familie_id for o in objekte_a} == {heidenreich.id, kumpel.id}

        # Derselbe Kontakt-Schlüssel bei beiden Familien.
        s.add(Kontakt(schluessel="stadtwerke", firma="Stadtwerke (Kumpel)",
                     familie_id=kumpel.id))
        s.commit()
        kontakte = s.exec(select(Kontakt).where(Kontakt.schluessel == "stadtwerke")).all()
        assert len(kontakte) == 2
