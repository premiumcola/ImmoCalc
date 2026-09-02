"""N314 — der Name einer Einheit steht als TEXT an sieben Stellen.

Beim Umbenennen wurde bis dahin nur `Miete.einheit` nachgezogen (Fund XCII).
Der Rest blieb auf dem alten Namen — und `verteilung.nur_einheit_gewichte` gibt
bei fehlender Übereinstimmung **stumm `{}`** zurück. Eine Kostenposition „nur
für Wohnung 2" über 300 € wurde danach auf NIEMANDEN verteilt; die
Engine-Invariante „Summe der Anteile == Gesamtkosten" war für sie gebrochen,
ohne einen einzigen Hinweis.
"""
import os
import sys
import tempfile
from datetime import date

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_einheitname.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session, SQLModel, select  # noqa: E402

from app import einheitname  # noqa: E402
from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Einheit, Kostenposition, Objekt, Zeitraum  # noqa: E402


def test_das_register_findet_jede_namensspalte():
    """Wächter: eine Textspalte, die auf „einheit" endet, trägt einen Namen —
    und muss beim Umbenennen mitwandern. Aus dem Datenmodell gelesen, damit
    ein neues Modell von selbst dabei ist."""
    aus_metadaten = set()
    for name, tabelle in SQLModel.metadata.tables.items():
        if name == "einheit":
            continue
        for spalte in tabelle.columns:
            # N454 — `messeinheit`/`menge_einheit` enden zwar auf „einheit",
            # tragen aber eine MASSeinheit ('m³' | 'kWh' | 'Liter') und keinen
            # Namen. Sie gehören nicht ins Register; siehe
            # `test_einheitname_grenzen.py`.
            if spalte.foreign_keys or spalte.name in (
                    "einheit_id", "einheiten", "messeinheit", "menge_einheit"):
                continue
            if not spalte.name.endswith("einheit"):
                continue
            if "CHAR" not in str(spalte.type).upper() and \
                    "TEXT" not in str(spalte.type).upper():
                continue
            aus_metadaten.add(f"{name}.{spalte.name}")
    assert {str(f) for f in einheitname.register()} == aus_metadaten
    # Untergrenze: fällt das Register auf eine Handvoll, prüft der Test nichts
    # mehr. Bei der Einführung waren es sieben.
    assert len(aus_metadaten) >= 6


def test_die_bekannten_stellen_sind_dabei():
    """Genau sie blieben beim Umbenennen stehen."""
    im_register = {str(f) for f in einheitname.register()}
    for erwartet in ("miete.einheit", "kostenposition.nur_einheit",
                     "kostenposition.vorab_einheit", "anteil.einheit",
                     "heizverteiler.einheit", "stromjahr.eauto_einheit"):
        assert erwartet in im_register, erwartet


def test_umbenennen_zieht_die_sonderposition_mit():
    """Der reproduzierte Fall: 300 € „nur für Wohnung 2"."""
    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={"name": "Umbenennweg 1", "einheiten": [
            {"bezeichnung": "Wohnung 1", "flaeche": 60},
            {"bezeichnung": "Wohnung 2", "flaeche": 60}]}).json()["slug"]
        with Session(engine) as s:
            o = s.exec(select(Objekt).where(Objekt.slug == slug)).first()
            z = Zeitraum(objekt_id=o.id, start=date(2025, 1, 1),
                         ende=date(2025, 12, 31))
            s.add(z); s.commit(); s.refresh(z)
            s.add(Kostenposition(zeitraum_id=z.id, kostenart="Reparatur",
                                 betrag=300.0, nur_einheit="Wohnung 2"))
            s.commit()
            eid = s.exec(select(Einheit).where(
                Einheit.objekt_id == o.id,
                Einheit.bezeichnung == "Wohnung 2")).first().id

        antwort = c.patch(f"/api/einheiten/{eid}", json={"bezeichnung": "WE 02"})
        assert antwort.status_code == 200, antwort.text
        assert antwort.json()["nachgezogen"].get("kostenposition.nur_einheit") == 1

        with Session(engine) as s:
            p = s.exec(select(Kostenposition).where(
                Kostenposition.kostenart == "Reparatur")).first()
            assert p.nur_einheit == "WE 02"       # nicht mehr „Wohnung 2"


def test_kein_name_bleibt_auf_dem_alten_stand():
    """Die Aussage unabhängig von einzelnen Tabellen."""
    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={"name": "Umbenennweg 2", "einheiten": [
            {"bezeichnung": "Alt-OG", "flaeche": 60}]}).json()["slug"]
        with Session(engine) as s:
            o = s.exec(select(Objekt).where(Objekt.slug == slug)).first()
            z = Zeitraum(objekt_id=o.id, start=date(2025, 1, 1),
                         ende=date(2025, 12, 31))
            s.add(z); s.commit(); s.refresh(z)
            s.add(Kostenposition(zeitraum_id=z.id, kostenart="Sonder",
                                 betrag=100.0, nur_einheit="Alt-OG",
                                 vorab_einheit="Alt-OG"))
            s.commit()
            eid = s.exec(select(Einheit).where(
                Einheit.objekt_id == o.id)).first().id

        c.patch(f"/api/einheiten/{eid}", json={"bezeichnung": "Neu-OG"})
        with Session(engine) as s:
            assert einheitname.haengt_daran(s, "Alt-OG") == {}


def test_umbenennen_auf_denselben_namen_tut_nichts():
    """N454 — `objekt_id` ist Pflicht geworden: ohne sie schrieb das UPDATE
    quer durch alle Objekte und Familien."""
    with Session(engine) as s:
        assert einheitname.benenne_um(s, "X", "X", 1) == {}
        assert einheitname.benenne_um(s, "", "Y", 1) == {}
        assert einheitname.benenne_um(s, "X", "", 1) == {}
