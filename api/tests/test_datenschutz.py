"""Wächter gegen Datenverlust — Funde der Prüfung vom 20.07.2026.

Jeder Fall hier hat echte Nutzerdaten gefährdet. Schlägt einer fehl, ist die
Änderung falsch, nicht der Test.
"""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_datenschutz.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlmodel import Session, SQLModel, create_engine, select  # noqa: E402

from app.main import app  # noqa: E402
from app.migrate import migriere  # noqa: E402
from app.models import Einstellung, Kostenposition, Objekt  # noqa: E402
from app.seed import seed  # noqa: E402


def _frische_db(name: str):
    pfad = os.path.join(tempfile.mkdtemp(), name)
    engine = create_engine(f"sqlite:///{pfad}")
    SQLModel.metadata.create_all(engine)
    return engine


# --------------------------------------------------------------------------
# Der Seed darf genau einmal laufen — nie wieder
# --------------------------------------------------------------------------

def test_seed_kommt_nach_dem_loeschen_aller_objekte_nicht_zurueck():
    """Wer seine letzte Immobilie löscht und neu startet, bekam Demodaten."""
    engine = _frische_db("seed1.db")
    seed(engine)
    with Session(engine) as s:
        assert len(s.exec(select(Objekt)).all()) == 2
        for o in s.exec(select(Objekt)).all():
            s.delete(o)
        s.commit()

    seed(engine)                       # der Neustart nach dem Löschen
    with Session(engine) as s:
        assert s.exec(select(Objekt)).all() == []


def test_seed_laesst_eine_bereits_benutzte_datenbank_in_ruhe():
    """Eine Bestands-DB ohne Markierung, aber mit Einstellungen des Nutzers."""
    engine = _frische_db("seed2.db")
    with Session(engine) as s:
        s.add(Einstellung(schluessel="nc_url", wert="https://cloud.example"))
        s.commit()

    seed(engine)
    with Session(engine) as s:
        assert s.exec(select(Objekt)).all() == []
        assert s.get(Einstellung, "nc_url").wert == "https://cloud.example"


def test_seed_laeuft_in_einer_leeren_datenbank_genau_einmal():
    engine = _frische_db("seed3.db")
    seed(engine)
    seed(engine)
    with Session(engine) as s:
        assert len(s.exec(select(Objekt)).all()) == 2


# --------------------------------------------------------------------------
# Migration: eine gewachsene Datenbank darf keine NULL bekommen, wo eine
# frische NOT NULL hätte
# --------------------------------------------------------------------------

def test_migration_fuellt_json_spalten_statt_null_zu_lassen():
    """`anteile` hat eine erzeugte Vorgabe — die blieb früher NULL, und die
    Abrechnung stolperte danach über `None.values()`."""
    engine = _frische_db("mig.db")
    with Session(engine) as s:
        s.add(Kostenposition(zeitraum_id=1, kostenart="Wasser", betrag=100.0,
                             anteile={"A": 1}))
        s.commit()
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE kostenposition DROP COLUMN anteile"))

    migriere(engine)
    with Session(engine) as s:
        p = s.exec(select(Kostenposition)).first()
        assert p.anteile is not None
        assert p.anteile == {}


# --------------------------------------------------------------------------
# Export und Import: nichts darf verlorengehen oder falsch landen
# --------------------------------------------------------------------------

def _objekt_mit_allem(c, name="Sicherungsweg 1"):
    slug = c.post("/api/objekte", json={
        "name": name, "ort": "Prüfstadt", "strasse": name,
        "kostenarten": ["Wasser"], "kaufpreis": 300000.0}).json()["slug"]
    c.post(f"/api/objekte/{slug}/mieten", json={
        "partei": "Mieter A", "kaltmiete": 800.0, "ab_datum": "2024-01-01"})
    return slug


def test_import_stellt_die_belegzuordnung_wieder_her():
    """Die Dateien bleiben in der Cloud — die Zuordnung steckt in der DB."""
    with TestClient(app) as c:
        slug = _objekt_mit_allem(c, "Belegweg 1")
        daten = c.get(f"/api/objekte/{slug}/export").json()
        # Ein Beleg, wie ihn der Scan anlegt
        daten["dokumente"] = [{
            "id": 999, "pfad": "/Immobilien/Belegweg 1/60_Nebenkosten/2024_Wasser.pdf",
            "dateiname": "2024_Wasser.pdf", "groesse": 1234, "objekt_id": 1,
            "zeitraum_id": daten["zeitraeume"][0]["id"], "kategorie": "Nebenkosten",
            "jahr": 2024, "status": "zugeordnet", "erkannt_am": "2024-06-01"}]

        c.delete(f"/api/objekte/{slug}")
        neu = c.post("/api/objekte/import", json=daten).json()["slug"]

        belege = c.get(f"/api/dokumente/objekt/{neu}").json()
        assert len(belege) == 1
        assert belege[0]["dateiname"] == "2024_Wasser.pdf"
        # und der Beleg hängt wieder am richtigen Zeitraum
        zid = c.get(f"/api/objekte/{neu}").json()["zeitraeume"][0]["id"]
        assert c.get(f"/api/zeitraeume/{zid}").json()["dokumente"]


def test_anteil_landet_nie_bei_einem_fremden_eigentuemer():
    """Ids werden neu vergeben — der Anteil muss am Namen hängen."""
    with TestClient(app) as c:
        slug = _objekt_mit_allem(c, "Anteilsweg 1")
        eid = c.post("/api/eigentuemer", json={"name": "Roman Einmalig"}).json()["id"]
        c.post(f"/api/objekte/{slug}/anteile",
               json={"eigentuemer_id": eid, "tausendstel": 1000})
        daten = c.get(f"/api/objekte/{slug}/export").json()
        assert daten["anteile"][0]["eigentuemer_name"] == "Roman Einmalig"

        c.delete(f"/api/objekte/{slug}")
        c.delete(f"/api/eigentuemer/{eid}")
        fremd = c.post("/api/eigentuemer",
                       json={"name": "Fremde GmbH"}).json()["id"]

        neu = c.post("/api/objekte/import", json=daten).json()["slug"]
        stand = c.get(f"/api/objekte/{neu}/anteile").json()
        namen = [a["name"] for a in stand["anteile"]]
        assert "Fremde GmbH" not in namen, f"fremde Beteiligung: {namen} (id {fremd})"
        assert stand["vergeben"] == 0        # lieber keine als die falsche


def test_anteil_findet_seinen_eigentuemer_ueber_den_namen_wieder():
    with TestClient(app) as c:
        slug = _objekt_mit_allem(c, "Wiederweg 1")
        eid = c.post("/api/eigentuemer", json={"name": "Bleibt Bestehen"}).json()["id"]
        c.post(f"/api/objekte/{slug}/anteile",
               json={"eigentuemer_id": eid, "tausendstel": 700})
        daten = c.get(f"/api/objekte/{slug}/export").json()

        c.delete(f"/api/objekte/{slug}")
        neu = c.post("/api/objekte/import", json=daten).json()["slug"]
        stand = c.get(f"/api/objekte/{neu}/anteile").json()
        assert stand["vergeben"] == 700
        assert stand["anteile"][0]["name"] == "Bleibt Bestehen"


# --------------------------------------------------------------------------
# Anlegen: ein leeres Zahlenfeld darf nicht den ganzen Eintrag verwerfen
# --------------------------------------------------------------------------

def test_mietverhaeltnis_mit_leeren_zahlenfeldern_wird_angelegt():
    """Stellplatz und Sonstiges leer lassen ist der Normalfall."""
    with TestClient(app) as c:
        slug = _objekt_mit_allem(c, "Leerfeldweg 1")
        antwort = c.post(f"/api/objekte/{slug}/mieten", json={
            "einheit": "EG", "partei": "Mieter B", "kaltmiete": 700.0,
            "nebenkosten_vz": None, "stellplatz": None, "sonstige": None,
            "ab_datum": "2024-01-01", "email": "b@example.org"})
        assert antwort.status_code == 201, antwort.text

        eintrag = [m for m in c.get(f"/api/objekte/{slug}/mieten").json()
                   if m["partei"] == "Mieter B"][0]
        assert eintrag["kaltmiete"] == 700.0
        assert eintrag["email"] == "b@example.org"     # nichts verworfen
        assert eintrag["stellplatz"] == 0.0


def test_versicherung_und_kredit_ohne_betrag_werden_angelegt():
    with TestClient(app) as c:
        slug = _objekt_mit_allem(c, "Ohnebetragweg 1")
        assert c.post(f"/api/objekte/{slug}/versicherungen", json={
            "art": "Gebäude", "anbieter": "X", "jahresbeitrag": None,
        }).status_code == 201
        assert c.post(f"/api/objekte/{slug}/kredite", json={
            "bezeichnung": "Darlehen", "rate_monatlich": None,
        }).status_code == 201
