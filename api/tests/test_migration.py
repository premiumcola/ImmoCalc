"""Eine gewachsene Datenbank ohne die neuen Spalten muss weiterlaufen.

Genau das ist in der Produktion gebrochen: create_all legt nur fehlende
Tabellen an, die vorhandene `objekt`-Tabelle blieb ohne die neuen Spalten
zurück und der Start scheiterte.
"""
import os
import sys
import tempfile
from datetime import date

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


# Schema, wie es vor der Erweiterung um Kontaktdaten/Zusatzflächen aussah —
# `objekt`/`einheit`/`miete` existierten schon, aber ohne die seither
# ergänzten Spalten (aktiv/strasse/kaufpreis/nc_ordner, terrasse/stellplaetze/
# nutzungsart, email/kaution*/vorgaenger_id/personen/...). Genau der reale
# Fall: eine gewachsene Datenbank mit echten Nutzerdaten, kein frisches Schema.
ALTES_SCHEMA_VOLL = """
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
CREATE TABLE einheit (
    id INTEGER NOT NULL PRIMARY KEY,
    objekt_id INTEGER NOT NULL,
    bezeichnung VARCHAR NOT NULL,
    flaeche FLOAT
);
CREATE TABLE miete (
    id INTEGER NOT NULL PRIMARY KEY,
    objekt_id INTEGER NOT NULL,
    einheit VARCHAR NOT NULL,
    partei VARCHAR NOT NULL,
    kaltmiete FLOAT NOT NULL,
    turnus VARCHAR NOT NULL,
    ab_datum DATE NOT NULL,
    bis_datum DATE
);
INSERT INTO objekt (id, slug, name, ort, typ, nutzung, turnus, start_monat)
VALUES (1, 'meine-immo', 'Musterstr. 5', 'Musterstadt', 'lg-mfhA', 'Wohnen', 'kalender', 1);
INSERT INTO einheit (id, objekt_id, bezeichnung, flaeche)
VALUES (1, 1, '1. OG', 78.0);
INSERT INTO miete (id, objekt_id, einheit, partei, kaltmiete, turnus, ab_datum, bis_datum)
VALUES (1, 1, '1. OG', 'Familie Muster', 845.0, 'monatlich', '2025-04-01', NULL);
"""


def test_eingegebene_daten_ueberleben_ein_update(tmp_path):
    """Der Fall aus der Praxis: Immobilie ist auf einem ALTEN Schema erfasst
    (objekt/einheit/miete existieren bereits, aber ohne die seither
    ergänzten Spalten), dann wird die App aktualisiert — genau die Reihen-
    folge aus `main.py` (`create_all` dann `migriere`). Nichts darf
    verlorengehen oder überschrieben werden, und die neuen Spalten müssen
    mit dem richtigen Vorgabewert nachgezogen sein."""
    import app.models  # noqa: F401
    from sqlmodel import Session, SQLModel, select

    from app.models import Einheit, Miete, Objekt
    from app.seed import seed

    pfad = tmp_path / "bestand.db"
    engine = create_engine(f"sqlite:///{pfad}")

    # --- Bestand auf altem Schema: Nutzer hat seine Immobilie eingetragen ---
    with engine.begin() as conn:
        for anweisung in filter(str.strip, ALTES_SCHEMA_VOLL.split(";")):
            conn.execute(text(anweisung))

    vorher = inspect(engine)
    assert "aktiv" not in {s["name"] for s in vorher.get_columns("objekt")}
    assert "terrasse" not in {s["name"] for s in vorher.get_columns("einheit")}
    assert "email" not in {s["name"] for s in vorher.get_columns("miete")}

    # --- Update: genau die main.py-Reihenfolge — create_all, dann migriere ---
    SQLModel.metadata.create_all(engine)
    geaendert = migriere(engine)
    seed(engine)

    # Die drei bereits vorhandenen Tabellen wurden per ALTER erweitert, nicht
    # stillschweigend übersprungen — sonst wäre dieser Test ein No-op.
    for erwartet in ("objekt.aktiv", "einheit.terrasse", "miete.email"):
        assert erwartet in geaendert, f"{erwartet} wurde nicht ergänzt"

    with Session(engine) as s:
        objekte = s.exec(select(Objekt)).all()
        # Der Seed darf keine Demo-Objekte danebenlegen
        assert [o.slug for o in objekte] == ["meine-immo"]
        o = objekte[0]
        # --- Bestandsdaten unverändert ---
        assert o.name == "Musterstr. 5"
        assert o.ort == "Musterstadt"
        assert o.turnus == "kalender"
        # --- neue Spalten mit dem korrekten Vorgabewert nachgezogen ---
        assert o.aktiv is True
        assert o.strasse == ""
        assert o.plz == ""
        assert o.flaeche is None            # optional, bleibt leer
        assert o.kaufpreis is None          # optional, bleibt leer
        assert o.nc_ordner == ""
        assert o.modell == "standard"       # kein Laufer-Sonderfall

        miete = s.exec(select(Miete)).one()
        # --- Bestandsdaten unverändert ---
        assert miete.kaltmiete == 845.0
        assert miete.partei == "Familie Muster"
        assert miete.ab_datum == date(2025, 4, 1)
        # --- neue Spalten mit dem korrekten Vorgabewert nachgezogen ---
        assert miete.email == ""
        assert miete.personen == 1
        assert miete.kaution_objektkonto is False
        assert miete.kaution_eingang is None      # optional, bleibt leer
        assert miete.vorgaenger_id is None        # optional, bleibt leer

        einheit = s.exec(select(Einheit)).one()
        # --- Bestandsdaten unverändert ---
        assert einheit.flaeche == 78.0
        assert einheit.bezeichnung == "1. OG"
        # --- neue Spalten mit dem korrekten Vorgabewert nachgezogen ---
        assert einheit.nutzungsart == "Wohnen"
        assert einheit.terrasse is None           # optional, bleibt leer
        assert einheit.stellplaetze == 0
        assert einheit.nk_abrechnung is True
        assert einheit.gemeinflaechen == "[]"


def test_seed_verdoppelt_objekte_nicht_nach_migration(tmp_path):
    """Ergänzend zum Fall oben: auch wenn die Datenbank schon im vollen
    Schema vorliegt (z. B. weil sie erst kürzlich angelegt wurde), darf
    `migriere` + `seed` keine Demo-Objekte neben den echten Bestand legen."""
    import app.models  # noqa: F401
    from sqlmodel import Session, SQLModel, select

    from app.models import Einheit, Miete, Objekt
    from app.seed import seed

    pfad = tmp_path / "bestand_aktuell.db"
    engine = create_engine(f"sqlite:///{pfad}")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as s:
        o = Objekt(slug="meine-immo", name="Laufer Str. 5", ort="Eschenau",
                   kaufpreis=310000.0)
        s.add(o)
        s.commit()
        s.refresh(o)
        s.add(Einheit(objekt_id=o.id, bezeichnung="1. OG", flaeche=78.0))
        s.add(Miete(objekt_id=o.id, einheit="1. OG", partei="Familie Muster",
                    kaltmiete=845.0, email="mieter@example.org",
                    ab_datum=date(2025, 4, 1)))
        s.commit()

    migriere(engine)
    seed(engine)

    with Session(engine) as s:
        objekte = s.exec(select(Objekt)).all()
        assert [o.slug for o in objekte] == ["meine-immo"]
        o = objekte[0]
        assert o.name == "Laufer Str. 5"
        assert o.kaufpreis == 310000.0

        miete = s.exec(select(Miete)).one()
        assert miete.kaltmiete == 845.0
        assert miete.partei == "Familie Muster"
        assert miete.email == "mieter@example.org"

        einheit = s.exec(select(Einheit)).one()
        assert einheit.flaeche == 78.0
        assert einheit.terrasse is None
        assert einheit.stellplaetze == 0


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


def test_tankstelle_zukunftsmarker_werden_bereinigt(tmp_path):
    """N220 — vor dem Zukunfts-Guard gesetzte Marker für noch nicht
    abgeschlossene Monate/Quartale werden beim Start geleert; ein bereits
    abgeschlossener Marker bleibt unangetastet."""
    from sqlmodel import Session, SQLModel, select

    from app.migrate import tankstelle_zukunftsmarker_bereinigen
    from app.models import Einstellung
    from app.tanken.marker import S_VERSENDET

    engine = create_engine(f"sqlite:///{tmp_path / 'zm.db'}")
    SQLModel.metadata.create_all(engine)
    heute = date.today()
    kuenftiges_jahr = heute.year + 1
    with Session(engine) as s:
        s.add(Einstellung(schluessel=f"{S_VERSENDET}:haus:2020:Q1:5",
                          wert="2020-04-01"))          # laengst abgeschlossen
        s.add(Einstellung(
            schluessel=f"{S_VERSENDET}:haus:{kuenftiges_jahr}:Q1:5",
            wert="2024-01-01"))                        # Quartal noch offen
        s.add(Einstellung(
            schluessel=f"{S_VERSENDET}:haus:{kuenftiges_jahr}:M6:5",
            wert="2024-01-01"))                        # Monat noch offen
        s.commit()

    n = tankstelle_zukunftsmarker_bereinigen(engine)
    assert n == 2

    with Session(engine) as s:
        werte = {e.schluessel: e.wert for e in s.exec(select(Einstellung)).all()}
    assert werte[f"{S_VERSENDET}:haus:2020:Q1:5"] == "2020-04-01"
    assert werte[f"{S_VERSENDET}:haus:{kuenftiges_jahr}:Q1:5"] == ""
    assert werte[f"{S_VERSENDET}:haus:{kuenftiges_jahr}:M6:5"] == ""

    # Idempotent: ein zweiter Lauf findet nichts mehr zu bereinigen.
    assert tankstelle_zukunftsmarker_bereinigen(engine) == 0


def test_miete_vorgaenger_wird_fuer_altfaelle_verknuepft(tmp_path):
    """N235 — vor N228 angelegte Mieterhöhungen (zwei getrennte Mietstände
    ohne `vorgaenger_id`) werden nachträglich verkettet, wenn Einheit und
    Partei übereinstimmen und der neue Stand nahtlos (Tag danach) beginnt.
    Mehrdeutige/unpassende Fälle bleiben unverknüpft."""
    from sqlmodel import Session, SQLModel, select

    from app.migrate import miete_vorgaenger_backfuellen
    from app.models import Miete, Objekt

    engine = create_engine(f"sqlite:///{tmp_path / 'mv.db'}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        o = Objekt(slug="test-obj", name="Testobjekt")
        s.add(o)
        s.commit()
        s.refresh(o)
        # Altfall: nahtlose Mieterhöhung derselben Partei, kein vorgaenger_id.
        alt = Miete(objekt_id=o.id, einheit="1.OG", partei="Julia Buckenleib",
                    ab_datum=date(2026, 7, 1), bis_datum=date(2028, 2, 29))
        neu = Miete(objekt_id=o.id, einheit="1.OG", partei="Julia Buckenleib",
                    ab_datum=date(2028, 3, 1), bis_datum=date(2030, 5, 31))
        # Andere Einheit, andere Partei — darf nicht mit hineingezogen werden.
        fremd = Miete(objekt_id=o.id, einheit="EG", partei="Anderer Mieter",
                       ab_datum=date(2028, 4, 1), bis_datum=None)
        s.add_all([alt, neu, fremd])
        s.commit()
        alt_id = alt.id

    n = miete_vorgaenger_backfuellen(engine)
    assert n == 1

    with Session(engine) as s:
        nach_datum = {m.ab_datum: m for m in s.exec(select(Miete)).all()}
    assert nach_datum[date(2026, 7, 1)].vorgaenger_id is None  # der ALTE bleibt unverknüpft
    assert nach_datum[date(2028, 3, 1)].vorgaenger_id == alt_id
    assert nach_datum[date(2028, 3, 1)].partei == "Julia Buckenleib"

    # Idempotent: ein zweiter Lauf findet nichts mehr zu verknüpfen.
    assert miete_vorgaenger_backfuellen(engine) == 0


def test_kaution_objektkonto_wird_ueber_vorgaenger_kette_uebernommen(tmp_path):
    """N239 — Kaution auf Objektkonto / Eingangsdatum gelten für die ganze
    Mietbeziehung, nicht nur für den Mietstand, an dem sie eingetragen
    wurden. Bei einer (auch mehrstufigen) Mieterhöhung erbt ein Mietstand
    ohne eigenen Wert den seines nächsten Vorfahren, der einen trägt. Ein
    Mietstand mit einem EIGENEN Wert wird nie überschrieben."""
    from sqlmodel import Session, SQLModel, select

    from app.migrate import miete_kaution_vorgaenger_uebernehmen
    from app.models import Miete, Objekt

    engine = create_engine(f"sqlite:///{tmp_path / 'mk.db'}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        o = Objekt(slug="test-obj", name="Testobjekt")
        s.add(o)
        s.commit()
        s.refresh(o)
        urspruenglich = Miete(objekt_id=o.id, einheit="1.OG", partei="Julia Buckenleib",
                              ab_datum=date(2026, 7, 1), bis_datum=date(2028, 2, 29),
                              kaution_objektkonto=True,
                              kaution_eingang=date(2026, 6, 15))
        s.add(urspruenglich)
        s.commit()
        s.refresh(urspruenglich)
        # Erste Erhöhung: eigener Wert fehlt, muss vom Ursprung erben.
        erhoehung_1 = Miete(objekt_id=o.id, einheit="1.OG", partei="Julia Buckenleib",
                            ab_datum=date(2028, 3, 1), bis_datum=date(2030, 5, 31),
                            vorgaenger_id=urspruenglich.id)
        s.add(erhoehung_1)
        s.commit()
        s.refresh(erhoehung_1)
        # Zweite Erhöhung: mehrstufige Kette — erbt über erhoehung_1 hinweg
        # vom ursprünglichen Mietstand.
        erhoehung_2 = Miete(objekt_id=o.id, einheit="1.OG", partei="Julia Buckenleib",
                            ab_datum=date(2030, 6, 1), bis_datum=None,
                            vorgaenger_id=erhoehung_1.id)
        # Anderer Mietstand: hat selbst schon einen (abweichenden) Wert und
        # darf nicht überschrieben werden.
        eigener_wert = Miete(objekt_id=o.id, einheit="EG", partei="Anderer Mieter",
                             ab_datum=date(2027, 1, 1), bis_datum=None,
                             kaution_objektkonto=False,
                             kaution_eingang=date(2027, 1, 10))
        s.add_all([erhoehung_2, eigener_wert])
        s.commit()

    n = miete_kaution_vorgaenger_uebernehmen(engine)
    assert n == 2  # erhoehung_1 und erhoehung_2, nicht eigener_wert

    with Session(engine) as s:
        nach_datum = {m.ab_datum: m for m in s.exec(select(Miete)).all()}
    assert nach_datum[date(2028, 3, 1)].kaution_objektkonto is True
    assert nach_datum[date(2028, 3, 1)].kaution_eingang == date(2026, 6, 15)
    assert nach_datum[date(2030, 6, 1)].kaution_objektkonto is True
    assert nach_datum[date(2030, 6, 1)].kaution_eingang == date(2026, 6, 15)
    # Eigener, expliziter Wert bleibt unangetastet (kaution_eingang gesetzt).
    assert nach_datum[date(2027, 1, 1)].kaution_objektkonto is False
    assert nach_datum[date(2027, 1, 1)].kaution_eingang == date(2027, 1, 10)

    # Idempotent: ein zweiter Lauf findet nichts mehr zu übernehmen.
    assert miete_kaution_vorgaenger_uebernehmen(engine) == 0
