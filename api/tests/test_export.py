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


# --------------------------------------------------------------------------
# N314(c) — acht objektgebundene Tabellen fehlten in Sicherung und Löschung:
# Notarvertrag, Renovierung(-sposten), Zähler(-ablesung), Grundschuld(-kredit),
# Kundennummer.
# --------------------------------------------------------------------------

def _mit_allen_acht(c, name):
    """Ein Objekt mit je einem Satz aus jeder der acht fehlenden Tabellen,
    inklusive der beiden Selbstbezüge (Rest-Zähler, Ablesung mit Zeitraum)."""
    slug = _anlegen(c, name)
    zid_zr = c.get(f"/api/objekte/{slug}").json()["zeitraeume"][0]["id"]

    c.post(f"/api/objekte/{slug}/notarvertraege",
          json={"art": "Kaufvertrag", "notar": "Dr. Muster", "betrag": 5000.0})

    rid = c.post(f"/api/objekte/{slug}/renovierungen",
                json={"name": "Bad", "budget": 10000.0}).json()["id"]
    c.post(f"/api/renovierungen/{rid}/posten",
          json={"betrag": 500.0, "firma": "Handwerk GmbH", "gewerk": "Sanitär"})

    haupt = c.post(f"/api/objekte/{slug}/zaehler",
                   json={"name": "Hauptzähler"}).json()["id"]
    rest = c.post(f"/api/objekte/{slug}/zaehler",
                  json={"name": "Rest", "typ": "rest",
                        "hauptzaehler_id": haupt}).json()["id"]
    c.post(f"/api/zaehler/{haupt}/ablesungen",
          json={"datum": "2025-01-01", "stand": 100.0, "zeitraum_id": zid_zr})

    # Eigener Firmenname je Aufruf — sonst dedupliziert die Ernte gegen den
    # Kontakt eines anderen Tests in derselben Datenbank.
    bank = f"Testbank {name}"
    kid = c.post(f"/api/objekte/{slug}/kredite",
                json={"bezeichnung": "Darlehen", "bank": bank,
                      "darlehensnummer": "K-9000"}).json()["id"]
    gid = c.post(f"/api/objekte/{slug}/grundschulden",
                json={"betrag": 200000.0, "glaeubiger": bank,
                      "kredit_ids": [kid]}).json()["id"]

    assert c.post("/api/kontakte/ernten").status_code == 200
    kontakt = next(k for k in c.get("/api/kontakte").json()["kontakte"]
                  if k["firma"] == bank)

    return slug, {"rid": rid, "haupt": haupt, "rest": rest, "kid": kid,
                 "gid": gid, "kontakt_id": kontakt["id"]}


def test_export_enthaelt_die_acht_bisher_fehlenden_tabellen():
    with TestClient(app) as c:
        slug, ids = _mit_allen_acht(c, "Achtweg 11")
        daten = c.get(f"/api/objekte/{slug}/export").json()

        assert len(daten["notarvertraege"]) == 1
        assert len(daten["renovierungen"]) == 1
        assert len(daten["renovierungsposten"]) == 1
        assert len(daten["zaehler"]) == 2
        assert len(daten["ablesungen"]) == 1
        assert len(daten["grundschulden"]) == 1
        assert len(daten["grundschuldkredite"]) == 1
        assert len(daten["kundennummern"]) == 1
        assert daten["kundennummern"][0]["kontakt_schluessel"]


def test_loeschen_hinterlaesst_bei_den_acht_tabellen_keine_waisen():
    from sqlmodel import Session, select

    from app.db import engine
    from app.models import (Ablesung, Grundschuld, GrundschuldKredit, Kontakt,
                            Kundennummer, Renovierung, Renovierungsposten,
                            Zaehler)

    with TestClient(app) as c:
        slug, ids = _mit_allen_acht(c, "Waisenweg 12")
        assert c.delete(f"/api/objekte/{slug}").status_code == 200

        with Session(engine) as s:
            assert s.get(Renovierung, ids["rid"]) is None
            assert s.exec(select(Renovierungsposten)
                         .where(Renovierungsposten.renovierung_id == ids["rid"])
                         ).all() == []
            assert s.get(Zaehler, ids["haupt"]) is None
            assert s.get(Zaehler, ids["rest"]) is None
            assert s.exec(select(Ablesung)
                         .where(Ablesung.zaehler_id == ids["haupt"])).all() == []
            assert s.get(Grundschuld, ids["gid"]) is None
            assert s.exec(select(GrundschuldKredit)
                         .where(GrundschuldKredit.grundschuld_id == ids["gid"])
                         ).all() == []
            assert s.exec(select(Kundennummer)
                         .where(Kundennummer.kontakt_id == ids["kontakt_id"])
                         ).all() == []
            # Der Kontakt selbst gehört mehreren Objekten und bleibt bestehen.
            assert s.get(Kontakt, ids["kontakt_id"]) is not None


def test_wiederherstellung_verknuepft_die_acht_tabellen_neu():
    with TestClient(app) as c:
        slug, ids = _mit_allen_acht(c, "Wiederweg 13")
        daten = c.get(f"/api/objekte/{slug}/export").json()
        assert c.delete(f"/api/objekte/{slug}").status_code == 200

        zurueck = c.post("/api/objekte/import", json=daten)
        assert zurueck.status_code == 201
        neu = zurueck.json()["slug"]

        notarvertraege = c.get(f"/api/objekte/{neu}/notarvertraege").json()
        assert notarvertraege[0]["betrag"] == 5000.0

        renovierungen = c.get(f"/api/objekte/{neu}/renovierungen").json()
        assert len(renovierungen) == 1
        detail = c.get(f"/api/renovierungen/{renovierungen[0]['id']}").json()
        assert len(detail["posten"]) == 1
        assert detail["posten"][0]["firma"] == "Handwerk GmbH"

        zaehler = c.get(f"/api/objekte/{neu}/zaehler").json()
        haupt_neu = next(z for z in zaehler if z["name"] == "Hauptzähler")
        rest_neu = next(z for z in zaehler if z["name"] == "Rest")
        # Der Rest-Zähler zeigt wieder auf den (neu vergebenen) Hauptzähler.
        assert rest_neu["hauptzaehler_id"] == haupt_neu["id"]
        ablesungen = c.get(f"/api/zaehler/{haupt_neu['id']}/ablesungen").json()
        assert ablesungen[0]["stand"] == 100.0
        assert ablesungen[0]["zeitraum_id"] is not None

        grundschulden = c.get(f"/api/objekte/{neu}/grundschulden").json()
        kredite = c.get(f"/api/objekte/{neu}/kredite").json()
        assert grundschulden[0]["kredit_ids"] == [kredite[0]["id"]]


def test_grundschuld_kredit_ueberlebt_wenn_nur_die_grundschuld_geloescht_wird():
    """Die Grundschuld auf Haus A kann einen Kredit an Haus B sichern (siehe
    `models.Grundschuld`). Wird nur Haus A gelöscht und wiederhergestellt,
    bleibt Haus B samt Kredit die ganze Zeit unangetastet — die Verknüpfung
    muss trotzdem zurückkommen, nicht nur, wenn beide Seiten mitgelöscht
    wurden."""
    with TestClient(app) as c:
        haus_a = _anlegen(c, "Haus A 14")
        haus_b = _anlegen(c, "Haus B 15")
        kid_b = c.post(f"/api/objekte/{haus_b}/kredite",
                      json={"bezeichnung": "Darlehen B"}).json()["id"]
        gid_a = c.post(f"/api/objekte/{haus_a}/grundschulden",
                      json={"betrag": 100000.0,
                            "kredit_ids": [kid_b]}).json()["id"]

        daten = c.get(f"/api/objekte/{haus_a}/export").json()
        assert daten["grundschuldkredite"] == [
            {"grundschuld_id": gid_a, "kredit_id": kid_b}]

        assert c.delete(f"/api/objekte/{haus_a}").status_code == 200
        # Haus B und sein Kredit bleiben unberührt.
        assert c.get(f"/api/objekte/{haus_b}/kredite").json()[0]["id"] == kid_b

        zurueck = c.post("/api/objekte/import", json=daten)
        assert zurueck.status_code == 201
        neu_a = zurueck.json()["slug"]
        grundschulden = c.get(f"/api/objekte/{neu_a}/grundschulden").json()
        assert grundschulden[0]["kredit_ids"] == [kid_b]


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
