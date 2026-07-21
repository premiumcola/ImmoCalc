"""Löschen, Sichern, Wiederherstellen.

Der Kern: eine gelöschte Immobilie muss sich aus der Sicherung vollständig
wiederherstellen lassen — und das Löschen darf nichts anfassen, was einem
anderen Objekt gehört.
"""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_export.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def _anlegen(c, name="Löschstraße 3"):
    antwort = c.post("/api/objekte", json={
        "name": name, "ort": "Musterstadt", "strasse": "Löschstraße 3",
        "kaufpreis": 420000.0, "verkehrswert": 500000.0,
        "kostenarten": ["Wasser", "Müll"],
        "einheiten": [{"bezeichnung": "EG", "flaeche": 70.0, "partei": "Mieter A"}],
    })
    assert antwort.status_code == 201
    return antwort.json()["slug"]


def test_export_enthaelt_alles_und_import_stellt_wieder_her():
    with TestClient(app) as c:
        slug = _anlegen(c)
        c.post(f"/api/objekte/{slug}/mieten", json={
            "einheit": "EG", "partei": "Mieter A", "kaltmiete": 800.0,
            "email": "a@example.org", "ab_datum": "2024-01-01"})
        c.post(f"/api/objekte/{slug}/kredite", json={
            "bezeichnung": "Hauptdarlehen", "restschuld": 300000.0,
            "zinssatz": 3.5, "rate_monatlich": 1200.0})

        sicherung = c.get(f"/api/objekte/{slug}/export")
        assert sicherung.status_code == 200
        assert "attachment" in sicherung.headers["content-disposition"]
        daten = sicherung.json()
        assert daten["objekt"]["name"] == "Löschstraße 3"
        assert len(daten["mieten"]) == 1
        assert len(daten["kredite"]) == 1
        assert len(daten["kostenarten"]) == 2
        assert len(daten["zeitraeume"]) == 1

        weg = c.delete(f"/api/objekte/{slug}")
        assert weg.status_code == 200
        assert c.get(f"/api/objekte/{slug}").status_code == 404

        zurueck = c.post("/api/objekte/import", json=daten)
        assert zurueck.status_code == 201
        neu = zurueck.json()["slug"]
        det = c.get(f"/api/objekte/{neu}").json()
        assert det["objekt"]["kaufpreis"] == 420000.0
        assert len(det["zeitraeume"]) == 1
        assert len(c.get(f"/api/objekte/{neu}/mieten").json()) == 1
        assert len(c.get(f"/api/objekte/{neu}/kredite").json()) == 1


def test_import_ueberschreibt_kein_bestehendes_objekt():
    """Ein gleichnamiges Objekt bleibt unangetastet — es entsteht ein zweites."""
    with TestClient(app) as c:
        slug = _anlegen(c, "Doppelweg 1")
        daten = c.get(f"/api/objekte/{slug}/export").json()
        zweit = c.post("/api/objekte/import", json=daten).json()["slug"]
        assert zweit != slug
        assert c.get(f"/api/objekte/{slug}").status_code == 200


def test_loeschen_laesst_andere_objekte_unberuehrt():
    with TestClient(app) as c:
        a = _anlegen(c, "Bleibt 1")
        b = _anlegen(c, "Geht 2")
        c.post(f"/api/objekte/{a}/mieten", json={
            "partei": "Bleibt-Mieter", "kaltmiete": 500.0, "ab_datum": "2024-01-01"})

        c.delete(f"/api/objekte/{b}")
        assert c.get(f"/api/objekte/{a}").status_code == 200
        assert len(c.get(f"/api/objekte/{a}/mieten").json()) == 1


def test_import_ohne_objektblock_wird_abgelehnt():
    with TestClient(app) as c:
        assert c.post("/api/objekte/import", json={"irgendwas": 1}).status_code == 400


# --------------------------------------------------------------------------
# CLI — was nicht am Objekt hängt, sondern am Kredit bzw. am Mietverhältnis
# --------------------------------------------------------------------------

def _mit_kredit_und_miete(c, name):
    """Ein Objekt mit zwei Jahresständen und einem Bewohner."""
    slug = _anlegen(c, name)
    kid = c.post(f"/api/objekte/{slug}/kredite", json={
        "bezeichnung": "Hauptdarlehen", "restschuld": 200000.0,
        "zinssatz": 3.0, "rate_monatlich": 1000.0}).json()["id"]
    for jahr, rest in ((2023, 200000.0), (2024, 190000.0)):
        antwort = c.post(f"/api/kredite/{kid}/staende",
                         json={"jahr": jahr, "restschuld": rest})
        assert antwort.status_code == 201, antwort.text
    mid = c.post(f"/api/objekte/{slug}/mieten", json={
        "einheit": "EG", "partei": "WG Süd", "kaltmiete": 900.0,
        "ab_datum": "2024-01-01"}).json()["id"]
    antwort = c.post(f"/api/mieten/{mid}/bewohner",
                     json={"name": "Anna", "email": "anna@example.org"})
    assert antwort.status_code == 201, antwort.text
    return slug, kid, mid


def test_kreditstaende_und_bewohner_gehen_mit_dem_objekt():
    """Jahresstände hängen am Kredit, Bewohner am Mietverhältnis — beim Löschen
    des Objekts blieben sie als Waisen stehen. SQLite vergibt frei gewordene
    rowids neu: der nächste Kredit erbte die Zahlen des gelöschten."""
    from sqlmodel import Session, select

    from app.db import engine
    from app.models import Bewohner, Kredit, Kreditstand, Miete

    with TestClient(app) as c:
        slug, _, _ = _mit_kredit_und_miete(c, "Erbstraße 7")
        assert c.delete(f"/api/objekte/{slug}").status_code == 200

        with Session(engine) as s:
            kredite = {k.id for k in s.exec(select(Kredit)).all()}
            mieten = {m.id for m in s.exec(select(Miete)).all()}
            waisen = [x for x in s.exec(select(Kreditstand)).all()
                      if x.kredit_id not in kredite]
            verlassen = [b for b in s.exec(select(Bewohner)).all()
                         if b.miete_id not in mieten]
        assert waisen == []
        assert verlassen == []

        # Und das nächste Objekt erbt nichts.
        neu = _anlegen(c, "Neubau 8")
        kid = c.post(f"/api/objekte/{neu}/kredite",
                     json={"bezeichnung": "Frisch"}).json()["id"]
        assert c.get(f"/api/kredite/{kid}/staende").json()["staende"] == []
        mid = c.post(f"/api/objekte/{neu}/mieten",
                     json={"partei": "Frisch", "ab_datum": "2025-01-01"}).json()["id"]
        assert c.get(f"/api/mieten/{mid}/bewohner").json() == []


def test_sicherung_bringt_staende_und_bewohner_zurueck():
    """Gelöscht wird erst nach der Sicherung — dann muss sie auch alles
    enthalten, sonst verliert die Wiederherstellung genau diese Zahlen."""
    with TestClient(app) as c:
        slug, _, _ = _mit_kredit_und_miete(c, "Rückweg 9")

        daten = c.get(f"/api/objekte/{slug}/export").json()
        assert sorted(z["jahr"] for z in daten["kreditstaende"]) == [2023, 2024]
        assert [b["email"] for b in daten["bewohner"]] == ["anna@example.org"]

        assert c.delete(f"/api/objekte/{slug}").status_code == 200
        zurueck = c.post("/api/objekte/import", json=daten)
        assert zurueck.status_code == 201
        neu = zurueck.json()["slug"]

        kredit = c.get(f"/api/objekte/{neu}/kredite").json()[0]
        assert kredit["staende"] == 2
        assert kredit["stand"]["stand_jahr"] == 2024
        assert kredit["stand"]["stand_wert"] == 190000.0
        miete = c.get(f"/api/objekte/{neu}/mieten").json()[0]
        assert [b["email"] for b in miete["bewohner"]] == ["anna@example.org"]


def test_alte_sicherung_ohne_die_neuen_schluessel_laesst_sich_einlesen():
    """Rückwärtsverträglich: eine Datei von früher kennt weder `kreditstaende`
    noch `bewohner` — sie muss sich trotzdem einlesen lassen."""
    with TestClient(app) as c:
        slug, _, _ = _mit_kredit_und_miete(c, "Altweg 10")
        daten = c.get(f"/api/objekte/{slug}/export").json()
        daten.pop("kreditstaende")
        daten.pop("bewohner")

        zurueck = c.post("/api/objekte/import", json=daten)
        assert zurueck.status_code == 201
        neu = zurueck.json()["slug"]
        assert c.get(f"/api/objekte/{neu}/kredite").json()[0]["staende"] == 0
        assert c.get(f"/api/objekte/{neu}/mieten").json()[0]["bewohner"] == []
