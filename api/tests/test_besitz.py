"""Eigentümer, Tausendstel-Anteile und die Vermögensübersicht."""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_besitz.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def _objekt(c, name, kaufpreis=None, verkehrswert=None):
    return c.post("/api/objekte", json={
        "name": name, "ort": "Musterstadt",
        "kaufpreis": kaufpreis, "verkehrswert": verkehrswert,
    }).json()["slug"]


def test_anteile_summieren_sich_auf_tausend():
    with TestClient(app) as c:
        slug = _objekt(c, "Anteilsweg 1")
        a = c.post("/api/eigentuemer", json={"name": "Roman"}).json()["id"]
        b = c.post("/api/eigentuemer", json={"name": "Partnerin"}).json()["id"]

        c.post(f"/api/objekte/{slug}/anteile",
               json={"eigentuemer_id": a, "tausendstel": 600})
        c.post(f"/api/objekte/{slug}/anteile",
               json={"eigentuemer_id": b, "tausendstel": 400})

        stand = c.get(f"/api/objekte/{slug}/anteile").json()
        assert stand["vergeben"] == 1000
        assert stand["frei"] == 0
        assert stand["stimmig"] is True
        assert sorted(z["prozent"] for z in stand["anteile"]) == [40.0, 60.0]


def test_zweiter_eintrag_derselben_person_aendert_statt_zu_doppeln():
    with TestClient(app) as c:
        slug = _objekt(c, "Einmalweg 2")
        e = c.post("/api/eigentuemer", json={"name": "Alleineigner"}).json()["id"]
        c.post(f"/api/objekte/{slug}/anteile",
               json={"eigentuemer_id": e, "tausendstel": 500})
        c.post(f"/api/objekte/{slug}/anteile",
               json={"eigentuemer_id": e, "tausendstel": 1000})

        stand = c.get(f"/api/objekte/{slug}/anteile").json()
        assert len(stand["anteile"]) == 1
        assert stand["vergeben"] == 1000


def test_eigentuemer_loeschen_laesst_das_objekt_stehen():
    with TestClient(app) as c:
        slug = _objekt(c, "Bleibtweg 3")
        e = c.post("/api/eigentuemer", json={"name": "Weg damit"}).json()["id"]
        c.post(f"/api/objekte/{slug}/anteile", json={"eigentuemer_id": e})
        assert c.delete(f"/api/eigentuemer/{e}").status_code == 200
        assert c.get(f"/api/objekte/{slug}").status_code == 200
        assert c.get(f"/api/objekte/{slug}/anteile").json()["vergeben"] == 0


def test_unsinnige_tausendstel_werden_abgelehnt():
    with TestClient(app) as c:
        slug = _objekt(c, "Grenzweg 4")
        e = c.post("/api/eigentuemer", json={"name": "Grenzfall"}).json()["id"]
        for wert in (0, -5, 1001):
            antwort = c.post(f"/api/objekte/{slug}/anteile",
                             json={"eigentuemer_id": e, "tausendstel": wert})
            assert antwort.status_code == 400


def test_drei_gleiche_anteile_gelten_als_vollstaendig():
    """333,3 dreimal ergibt 999,9 — auf eine Nachkommastelle ist das voll."""
    with TestClient(app) as c:
        slug = _objekt(c, "Drittelweg 7")
        for name in ("Erster", "Zweiter", "Dritter"):
            e = c.post("/api/eigentuemer", json={"name": name}).json()["id"]
            c.post(f"/api/objekte/{slug}/anteile",
                   json={"eigentuemer_id": e, "promille": 333.3})

        stand = c.get(f"/api/objekte/{slug}/anteile").json()
        assert stand["vergeben"] == 999.9
        assert stand["frei"] == 0.1
        assert stand["stimmig"] is True


def test_rolle_haengt_am_objekt_nicht_an_der_person():
    with TestClient(app) as c:
        allein = _objekt(c, "Alleinweg 8")
        geteilt = _objekt(c, "Geteiltweg 9")
        e = c.post("/api/eigentuemer", json={"name": "Doppelrolle"}).json()["id"]
        c.post(f"/api/objekte/{allein}/anteile",
               json={"eigentuemer_id": e, "promille": 1000})
        c.post(f"/api/objekte/{geteilt}/anteile",
               json={"eigentuemer_id": e, "promille": 250})

        rollen = {a["slug"]: a["rolle"] for a in
                  next(x for x in c.get("/api/eigentuemer").json()
                       if x["id"] == e)["objekte"]}
        assert rollen[allein] == "Alleineigentümer"
        assert rollen[geteilt] == "Miteigentümer"

        zeile = c.get(f"/api/objekte/{geteilt}/anteile").json()["anteile"][0]
        assert zeile["rolle"] == "Miteigentümer"
        assert zeile["promille"] == 250.0


def test_bestehende_ganzzahlige_anteile_ueberleben_die_erweiterung():
    """Zeilen ohne `promille` — wie sie in der gewachsenen Datenbank stehen —
    werden weiter ueber `tausendstel` gelesen."""
    from sqlmodel import Session, select

    from app.db import engine
    from app.models import Anteil

    with TestClient(app) as c:
        slug = _objekt(c, "Bestandsweg 10")
        e = c.post("/api/eigentuemer", json={"name": "Bestand"}).json()["id"]
        c.post(f"/api/objekte/{slug}/anteile",
               json={"eigentuemer_id": e, "tausendstel": 700})

        with Session(engine) as s:                      # Altzustand nachstellen
            a = s.exec(select(Anteil).where(Anteil.eigentuemer_id == e)).one()
            a.promille = None
            s.add(a)
            s.commit()

        stand = c.get(f"/api/objekte/{slug}/anteile").json()
        assert stand["vergeben"] == 700.0
        assert stand["anteile"][0]["promille"] == 700.0
        assert stand["frei"] == 300.0
        assert stand["stimmig"] is False


def test_anteilsstand_zeigt_auch_objekte_ohne_beteiligung():
    with TestClient(app) as c:
        slug = _objekt(c, "Ohneweg 11")
        zeile = next(z for z in c.get("/api/anteile/stand").json()
                     if z["slug"] == slug)
        assert zeile["beteiligte"] == 0
        assert zeile["frei"] == 1000.0
        assert zeile["stimmig"] is False


def test_vermoegen_rechnet_wert_minus_restschuld():
    with TestClient(app) as c:
        slug = _objekt(c, "Vermögensweg 5", kaufpreis=400000.0,
                       verkehrswert=500000.0)
        c.post(f"/api/objekte/{slug}/kredite", json={
            "bezeichnung": "Darlehen", "restschuld": 200000.0,
            "zinssatz": 2.0, "rate_monatlich": 1000.0, "turnus": "monatlich"})

        uebersicht = c.get("/api/vermoegen").json()
        zeile = next(z for z in uebersicht["objekte"] if z["slug"] == slug)
        assert zeile["wert"] == 500000.0          # Verkehrswert schlaegt Kaufpreis
        assert zeile["wertquelle"] == "Verkehrswert"
        assert zeile["restschuld"] == 200000.0
        assert zeile["eigenkapital"] == 300000.0
        assert zeile["beleihung"] == 40.0
        assert zeile["annuitaet_jahr"] == 12000.0
        assert zeile["zinslast_jahr"] == 4000.0
        assert zeile["tilgung_jahr"] == 8000.0


def test_vermoegen_ohne_angaben_faellt_nicht_um():
    with TestClient(app) as c:
        slug = _objekt(c, "Leerweg 6")
        zeile = next(z for z in c.get("/api/vermoegen").json()["objekte"]
                     if z["slug"] == slug)
        assert zeile["wert"] is None
        assert zeile["restschuld"] == 0
        assert zeile["eigenkapital"] is None
