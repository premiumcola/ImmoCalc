"""N270 — Renovierung je Objekt: Modell, API, Gewerk-/Budgetlogik.

Deckt die reine Logik (`app.renovierung`) und die Endpunkte ab. Der Wächter
`test_renovierungen_liste_landet_nicht_im_stammdaten_faenger` prüft genau die
Falle aus CLAUDE.md: `/objekte/{slug}/{bereich}` in stammdaten.py fängt
zweisegmentige Pfade ab, wenn die Renovierung-Route nicht VOR ihm registriert
ist.
"""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_renovierung.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.renovierung import (GEWERKE, budget_stand, einheiten_liste,
                             einheiten_text, gewerk_summen)  # noqa: E402


def _objekt(c: TestClient, name: str = "Testweg 1") -> str:
    return c.post("/api/objekte", json={
        "name": name, "einheiten": [
            {"bezeichnung": "EG, links", "flaeche": 60},
            {"bezeichnung": "OG", "flaeche": 60}]}).json()["slug"]


# --------------------------------------------------------------------------
# Reine Logik
# --------------------------------------------------------------------------

class _Posten:
    def __init__(self, betrag: float, gewerk: str = ""):
        self.betrag = betrag
        self.gewerk = gewerk


def test_gewerk_summen_ergibt_exakt_hundert_prozent():
    posten = [_Posten(100, "Elektro"), _Posten(50, "Sanitär"),
             _Posten(50, "Elektro"), _Posten(1, "Maler")]
    ergebnis = gewerk_summen(posten)
    assert round(sum(r["anteil_pct"] for r in ergebnis), 10) == 100.0
    # absteigend nach Summe
    assert [r["gewerk"] for r in ergebnis] == ["Elektro", "Sanitär", "Maler"]
    elektro = next(r for r in ergebnis if r["gewerk"] == "Elektro")
    assert elektro["summe"] == 150.0
    assert elektro["anzahl"] == 2


def test_gewerk_summen_posten_ohne_gewerk_landen_unter_sonstiges():
    ergebnis = gewerk_summen([_Posten(80, ""), _Posten(20, "Sonstiges")])
    assert len(ergebnis) == 1
    assert ergebnis[0]["gewerk"] == "Sonstiges"
    assert ergebnis[0]["summe"] == 100.0
    assert ergebnis[0]["anzahl"] == 2


def test_gewerk_summen_leer_ohne_posten():
    assert gewerk_summen([]) == []
    assert gewerk_summen([_Posten(0, "Elektro")]) == []


def test_budget_stand_ohne_ueberschreitung():
    stand = budget_stand(1000.0, 400.0)
    assert stand == {"budget": 1000.0, "ausgegeben": 400.0, "rest": 600.0,
                     "anteil_pct": 40.0, "ueberzogen": False}


def test_budget_stand_ueberschreitung_wird_negativ_nicht_auf_null_geklemmt():
    stand = budget_stand(1000.0, 1250.0)
    assert stand["rest"] == -250.0
    assert stand["ueberzogen"] is True
    assert stand["anteil_pct"] == 125.0


def test_budget_stand_ohne_budget_bleibt_none_und_faellt_nicht_um():
    stand = budget_stand(None, 300.0)
    assert stand == {"budget": None, "ausgegeben": 300.0, "rest": None,
                     "anteil_pct": None, "ueberzogen": False}


def test_einheiten_rundlauf_auch_mit_komma_im_namen():
    liste = ["EG, links", "OG"]
    text = einheiten_text(liste)
    assert "|" in text
    assert einheiten_liste(text) == liste
    assert einheiten_liste("") == []
    assert einheiten_text([]) == ""


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------

def test_gewerke_katalog_kommt_aus_der_api():
    with TestClient(app) as c:
        antwort = c.get("/api/renovierungen/gewerke")
    assert antwort.status_code == 200
    assert antwort.json() == {"gewerke": GEWERKE}


def test_anlegen_lesen_aendern_loeschen_mit_posten():
    with TestClient(app) as c:
        slug = _objekt(c)

        neu = c.post(f"/api/objekte/{slug}/renovierungen", json={
            "name": "Bad EG", "von": "2026-01-01", "bis": "2026-03-01",
            "budget": 10000, "einheiten": ["EG, links"], "notiz": "Testfall",
        })
        assert neu.status_code == 201
        rid = neu.json()["id"]
        assert neu.json()["einheiten"] == ["EG, links"]
        assert neu.json()["summe"] == 0.0
        assert neu.json()["rest"] == 10000.0

        # Liste zeigt den Eintrag mit den Übersichtszahlen
        liste = c.get(f"/api/objekte/{slug}/renovierungen").json()
        assert len(liste) == 1
        assert liste[0]["id"] == rid
        assert liste[0]["anzahl_posten"] == 0

        # Zwei Posten anlegen
        p1 = c.post(f"/api/renovierungen/{rid}/posten", json={
            "datum": "2026-01-15", "betrag": 3000, "firma": "Sanitär Meier",
            "gewerk": "Sanitär"}).json()
        p2 = c.post(f"/api/renovierungen/{rid}/posten", json={
            "betrag": 500, "firma": "Diverses"}).json()  # ohne Datum, ohne Gewerk

        detail = c.get(f"/api/renovierungen/{rid}").json()
        assert detail["summe"] == 3500.0
        assert detail["budget_stand"]["rest"] == 6500.0
        assert detail["budget_stand"]["ueberzogen"] is False
        # ohne Datum ans Ende
        assert [p["id"] for p in detail["posten"]] == [p1["id"], p2["id"]]
        gewerke_summen = {g["gewerk"]: g["summe"] for g in detail["gewerke"]}
        assert gewerke_summen["Sanitär"] == 3000.0
        assert gewerke_summen["Sonstiges"] == 500.0

        # Posten ändern
        geaendert = c.patch(f"/api/renovierungen/posten/{p2['id']}",
                            json={"betrag": 1000, "gewerk": "Elektro"})
        assert geaendert.status_code == 200
        assert geaendert.json()["betrag"] == 1000.0

        # Renovierung ändern (u. a. Budget überschreiten)
        aenderung = c.patch(f"/api/renovierungen/{rid}",
                            json={"budget": 3500}).json()
        assert aenderung["budget_stand"]["ueberzogen"] is True
        assert aenderung["budget_stand"]["rest"] == -500.0

        # Einzelnen Posten löschen
        c.delete(f"/api/renovierungen/posten/{p1['id']}")
        nach_loeschen = c.get(f"/api/renovierungen/{rid}").json()
        assert len(nach_loeschen["posten"]) == 1

        # Renovierung löschen — Posten verschwinden mit
        geloescht = c.delete(f"/api/renovierungen/{rid}")
        assert geloescht.status_code == 200
        assert c.get(f"/api/renovierungen/{rid}").status_code == 404
        assert c.get(f"/api/objekte/{slug}/renovierungen").json() == []


def test_posten_traegt_dateiname_und_pfad_seines_belegs():
    """N326 — das Frontend holte Name/Pfad des Belegs über eine Route, die es
    nie gab (`GET /api/dokumente/{id}`); der stille Fehlschlag liess nur den
    Platzhalter „Beleg" übrig. Jetzt stehen sie direkt am Posten."""
    from sqlmodel import Session, select

    from app.db import engine
    from app.models import Dokument, Objekt

    with TestClient(app) as c:
        slug = _objekt(c)
        rid = c.post(f"/api/objekte/{slug}/renovierungen",
                     json={"name": "Bad EG"}).json()["id"]
        with Session(engine) as s:
            o = s.exec(select(Objekt).where(Objekt.slug == slug)).first()
            d = Dokument(pfad=f"/{slug}/60_Nebenkosten/Rechnung.pdf",
                        dateiname="Rechnung.pdf", objekt_id=o.id)
            s.add(d)
            s.commit()
            s.refresh(d)
            did = d.id

        posten = c.post(f"/api/renovierungen/{rid}/posten",
                        json={"betrag": 100.0, "firma": "Sanitär Meier",
                              "quelle_dokument_id": did}).json()
        assert posten["beleg_dateiname"] == "Rechnung.pdf"
        assert posten["beleg_pfad"] == f"/{slug}/60_Nebenkosten/Rechnung.pdf"

        detail = c.get(f"/api/renovierungen/{rid}").json()
        assert detail["posten"][0]["beleg_dateiname"] == "Rechnung.pdf"

        # Ohne Beleg bleibt es leer statt eines Fehlers.
        ohne_beleg = c.post(f"/api/renovierungen/{rid}/posten",
                            json={"betrag": 50.0, "firma": "X"}).json()
        assert ohne_beleg["beleg_dateiname"] == ""
        assert ohne_beleg["beleg_pfad"] == ""


def test_renovierungen_liste_landet_nicht_im_stammdaten_faenger():
    """Genau die Falle aus CLAUDE.md: ohne die Reihenfolge in main.py würde
    stammdaten.py mit 'Unbekannter Bereich' antworten statt mit der Liste."""
    with TestClient(app) as c:
        slug = _objekt(c)
        antwort = c.get(f"/api/objekte/{slug}/renovierungen")
    assert antwort.status_code == 200
    assert isinstance(antwort.json(), list)
    assert "Unbekannter Bereich" not in antwort.text


def test_unbekannter_slug_und_unbekannte_id_ergeben_404_kein_500():
    with TestClient(app) as c:
        assert c.get("/api/objekte/nicht-vorhanden/renovierungen").status_code == 404
        assert c.post("/api/objekte/nicht-vorhanden/renovierungen",
                      json={"name": "X"}).status_code == 404
        assert c.get("/api/renovierungen/999999").status_code == 404
        assert c.patch("/api/renovierungen/999999", json={"name": "X"}).status_code == 404
        assert c.delete("/api/renovierungen/999999").status_code == 404
        assert c.post("/api/renovierungen/999999/posten",
                      json={"betrag": 1}).status_code == 404
        assert c.patch("/api/renovierungen/posten/999999",
                      json={"betrag": 1}).status_code == 404
        assert c.delete("/api/renovierungen/posten/999999").status_code == 404
