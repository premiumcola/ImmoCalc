"""Zähler-Konfiguration (CCCLXXX): additives CRUD, Anfangsstand und die
Rest-/Hauptzähler-Verknüpfung.

Geprüft wird das, was die Konfig-Maske in `zeitraum.html` über die vorhandenen
Endpunkte tut — Zähler anlegen/patchen/löschen, einen Anfangsstand vor der
ersten Abrechnung setzen (der in derselben Interpolation landet) und einen
berechneten Rest-Zähler (Hauptzähler minus Unterzähler) einrichten.
"""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_zaehler_konfig.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _neues_objekt(c) -> tuple[str, int, dict]:
    """Ein frisches Objekt mit genau einem (ersten) Abrechnungszeitraum.
    Liefert (slug, zeitraum_id, maske) — die Maske trägt start/ende in ISO."""
    antwort = c.post("/api/objekte", json={
        "name": "Zählerhaus", "ort": "Teststadt", "turnus": "kalender",
        "start_monat": 1, "kostenarten": ["Wasser"],
        "einheiten": [{"bezeichnung": "EG", "flaeche": 70.0, "partei": "Büro"}],
    })
    assert antwort.status_code == 201
    slug = antwort.json()["slug"]
    zid = c.get(f"/api/objekte/{slug}").json()["zeitraeume"][0]["id"]
    maske = c.get(f"/api/zeitraeume/{zid}/ablesung").json()
    return slug, zid, maske


def _anlegen(c, slug, **felder) -> int:
    antwort = c.post(f"/api/objekte/{slug}/zaehler", json=felder)
    assert antwort.status_code == 201
    return antwort.json()["id"]


# --------------------------------------------------------------------------
# 1) Zähler anlegen / patchen / löschen — additiv
# --------------------------------------------------------------------------

def test_zaehler_crud_additiv(client):
    slug, _zid, _maske = _neues_objekt(client)

    # anlegen
    zid = _anlegen(client, slug, name="Kaltwasser", kostenart="Wasser",
                   messeinheit="m³", einheit_bezug="Büro")
    liste = client.get(f"/api/objekte/{slug}/zaehler").json()
    assert [z["name"] for z in liste] == ["Kaltwasser"]
    assert liste[0]["messeinheit"] == "m³"
    assert liste[0]["typ"] == "gemessen"
    assert liste[0]["anfangsstand"] is None      # additives Feld, noch leer

    # patchen — jedes konfigurierbare Feld übernimmt der PATCH
    r = client.patch(f"/api/zaehler/{zid}", json={
        "messeinheit": "kWh", "einheit_bezug": "WG", "kostenart": "Heizöl",
        "reihenfolge": 3, "notiz": "Keller"})
    assert r.status_code == 200
    z = client.get(f"/api/objekte/{slug}/zaehler").json()[0]
    assert (z["messeinheit"], z["einheit_bezug"], z["kostenart"],
            z["reihenfolge"], z["notiz"]) == ("kWh", "WG", "Heizöl", 3, "Keller")

    # löschen
    assert client.delete(f"/api/zaehler/{zid}").json() == {"ok": True}
    assert client.get(f"/api/objekte/{slug}/zaehler").json() == []


def test_reihenfolge_sortiert_die_liste(client):
    slug, _zid, _maske = _neues_objekt(client)
    a = _anlegen(client, slug, name="A", reihenfolge=2)
    b = _anlegen(client, slug, name="B", reihenfolge=1)
    # nach reihenfolge, dann id — B (1) vor A (2)
    namen = [z["name"] for z in client.get(f"/api/objekte/{slug}/zaehler").json()]
    assert namen == ["B", "A"]
    # verschieben: A nach vorn
    client.patch(f"/api/zaehler/{a}", json={"reihenfolge": 0})
    namen = [z["name"] for z in client.get(f"/api/objekte/{slug}/zaehler").json()]
    assert namen == ["A", "B"]
    assert b  # b bleibt unangetastet


# --------------------------------------------------------------------------
# 2) Anfangsstand — als Ablesung angelegt und von der Interpolation beachtet
# --------------------------------------------------------------------------

def test_anfangsstand_wird_interpoliert(client):
    slug, zid, maske = _neues_objekt(client)
    start, ende = maske["zeitraum"]["start"], maske["zeitraum"]["ende"]

    z = _anlegen(client, slug, name="Kaltwasser", kostenart="Wasser",
                 messeinheit="m³", einheit_bezug="Büro")
    # Anfangsstand vor der ersten Abrechnung (am Periodenbeginn), untaggt.
    r = client.post(f"/api/zaehler/{z}/ablesungen",
                    json={"stand": 1000.0, "datum": start, "notiz": "Anfangsstand"})
    assert r.status_code == 201
    # laufender Stand am Periodenende, diesem Zeitraum zugeordnet.
    client.post(f"/api/zaehler/{z}/ablesungen",
                json={"stand": 1200.0, "datum": ende, "zeitraum_id": zid})

    # Beide Stände liegen als Ablesungen vor.
    abls = client.get(f"/api/zaehler/{z}/ablesungen").json()
    assert len(abls) == 2
    assert any(a["notiz"] == "Anfangsstand" and a["zeitraum_id"] is None
               for a in abls)

    # Ohne Anfangsstand wäre die erste Periode die Startablesung (Verbrauch 0).
    # Mit ihm rechnet dieselbe Interpolation die echte Differenz 200.
    zeile = client.get(f"/api/zeitraeume/{zid}/ablesung").json()["zaehler"][0]
    assert zeile["verbrauch"] == 200.0
    assert zeile["vorwert"] == {"stand": 1000.0, "datum": start}


def test_ohne_anfangsstand_erste_periode_ist_startablesung(client):
    """Wächter: die Vorlauf-Periode darf Zähler ohne Anfangsstand nicht
    verändern — die erste Periode bleibt Startablesung mit Verbrauch 0."""
    slug, zid, maske = _neues_objekt(client)
    ende = maske["zeitraum"]["ende"]
    z = _anlegen(client, slug, name="Strom", kostenart="Wasser", messeinheit="kWh")
    client.post(f"/api/zaehler/{z}/ablesungen",
                json={"stand": 500.0, "datum": ende, "zeitraum_id": zid})
    zeile = client.get(f"/api/zeitraeume/{zid}/ablesung").json()["zaehler"][0]
    assert zeile["verbrauch"] == 0.0
    assert zeile["vorwert"] is None


def test_anfangsstand_ist_idempotent(client):
    slug, _zid, maske = _neues_objekt(client)
    start = maske["zeitraum"]["start"]
    z = _anlegen(client, slug, name="Wasser", kostenart="Wasser")
    client.post(f"/api/zaehler/{z}/ablesungen",
                json={"stand": 1000.0, "datum": start, "notiz": "Anfangsstand"})
    # zweites Setzen aktualisiert denselben Stand, verdoppelt ihn nicht.
    client.post(f"/api/zaehler/{z}/ablesungen",
                json={"stand": 1010.0, "datum": start, "notiz": "Anfangsstand"})
    abls = client.get(f"/api/zaehler/{z}/ablesungen").json()
    assert len(abls) == 1
    assert abls[0]["stand"] == 1010.0
    # und die Konfig-Liste zeigt den aktuellen Anfangsstand.
    z_zeige = client.get(f"/api/objekte/{slug}/zaehler").json()[0]
    assert z_zeige["anfangsstand"] == {"stand": 1010.0, "datum": start}


def test_anfangsstand_endpoint_anlegen_und_aktualisieren(client):
    """CD — POST /zaehler/{id}/anfangsstand legt den Anfangsstand an und
    aktualisiert ihn idempotent (eine Ablesung, kein Duplikat)."""
    slug, zid, maske = _neues_objekt(client)
    start, ende = maske["zeitraum"]["start"], maske["zeitraum"]["ende"]
    z = _anlegen(client, slug, name="Kaltwasser", kostenart="Wasser",
                 einheit_bezug="Büro")

    # anlegen — Antwort ist die _zeige-Form mit dem gesetzten Anfangsstand.
    r = client.post(f"/api/zaehler/{z}/anfangsstand",
                    json={"stand": 1000.0, "datum": start})
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == z
    assert body["anfangsstand"] == {"stand": 1000.0, "datum": start}
    assert body["ablesungen"] == 1

    # aktualisieren — dieselbe Ablesung, kein Duplikat.
    r2 = client.post(f"/api/zaehler/{z}/anfangsstand",
                     json={"stand": 1010.0, "datum": start})
    assert r2.status_code == 200
    assert r2.json()["anfangsstand"] == {"stand": 1010.0, "datum": start}
    abls = client.get(f"/api/zaehler/{z}/ablesungen").json()
    assert len(abls) == 1
    assert abls[0]["notiz"] == "Anfangsstand"
    assert abls[0]["zeitraum_id"] is None

    # der Anfangsstand wirkt in der Interpolation als Vorwert der ersten Periode.
    client.post(f"/api/zaehler/{z}/ablesungen",
                json={"stand": 1210.0, "datum": ende, "zeitraum_id": zid})
    zeile = next(zz for zz in
                 client.get(f"/api/zeitraeume/{zid}/ablesung").json()["zaehler"]
                 if zz["id"] == z)
    assert zeile["verbrauch"] == 200.0
    assert zeile["vorwert"] == {"stand": 1010.0, "datum": start}


def test_ablesung_output_einheiten_und_kostenblock(client):
    """CD — die Ablesungs-Maske führt je Zähler `einheiten` (Mehrfachzuordnung,
    geparst) und `kostenblock` (aus der Kostenart abgeleitet)."""
    slug, zid, _maske = _neues_objekt(client)
    # Mehrfachzuordnung EG+1.OG über PATCH; Kostenart Warmwasser → Block Heizung.
    a = _anlegen(client, slug, name="Boiler", kostenart="Warmwasser",
                 einheit_bezug="EG")
    assert client.patch(f"/api/zaehler/{a}",
                        json={"einheiten": ["EG", " 1.OG "]}).status_code == 200
    # weitere Zähler zur Block-Prüfung.
    b = _anlegen(client, slug, name="Frisch", kostenart="Abwasser")
    c = _anlegen(client, slug, name="Zähler-Strom", kostenart="Allgemeinstrom")
    d = _anlegen(client, slug, name="Sonst", kostenart="Kabelanschluss")
    e = _anlegen(client, slug, name="Fallback", kostenart="Wasser",
                 einheit_bezug="Büro")   # ohne einheiten → Fallback einheit_bezug

    zeilen = {zz["name"]: zz for zz in
              client.get(f"/api/zeitraeume/{zid}/ablesung").json()["zaehler"]}
    # Mehrfachzuordnung getrimmt geparst.
    assert zeilen["Boiler"]["einheiten"] == ["EG", "1.OG"]
    assert zeilen["Boiler"]["kostenblock"] == "Heizung"
    # Kostenblöcke.
    assert zeilen["Frisch"]["kostenblock"] == "Wasser"
    assert zeilen["Zähler-Strom"]["kostenblock"] == "Strom"
    assert zeilen["Sonst"]["kostenblock"] == "Sonstige"
    # Fallback: leeres einheiten-Feld → [einheit_bezug].
    assert zeilen["Fallback"]["einheiten"] == ["Büro"]
    assert zeilen["Fallback"]["kostenblock"] == "Wasser"
    # PATCH auf leere Liste räumt die Mehrfachzuordnung wieder ab.
    assert client.patch(f"/api/zaehler/{a}",
                        json={"einheiten": []}).status_code == 200
    zeilen = {zz["name"]: zz for zz in
              client.get(f"/api/zeitraeume/{zid}/ablesung").json()["zaehler"]}
    assert zeilen["Boiler"]["einheiten"] == ["EG"]   # Fallback einheit_bezug
    assert b and c and d and e


# --------------------------------------------------------------------------
# 3) Rest-/Hauptzähler-Verknüpfung per PATCH (Verrechnungsart)
# --------------------------------------------------------------------------

def test_rest_zaehler_ist_gesamt_minus_unterzaehler(client):
    slug, zid, maske = _neues_objekt(client)
    start, ende = maske["zeitraum"]["start"], maske["zeitraum"]["ende"]

    gesamt = _anlegen(client, slug, name="Gesamt Wasser", kostenart="Wasser")
    u1 = _anlegen(client, slug, name="Büro", kostenart="Wasser",
                  einheit_bezug="Büro", hauptzaehler_id=gesamt)
    u2 = _anlegen(client, slug, name="WG", kostenart="Wasser",
                  einheit_bezug="WG", hauptzaehler_id=gesamt)
    # Rest-Zähler nachträglich als „Rest von Gesamt" markieren (GUI-Weg: PATCH).
    rest = _anlegen(client, slug, name="Wohnung OG", kostenart="Wasser",
                    einheit_bezug="OG")
    assert client.patch(f"/api/zaehler/{rest}",
                        json={"typ": "rest", "hauptzaehler_id": gesamt}
                        ).status_code == 200
    z_rest = next(z for z in client.get(f"/api/objekte/{slug}/zaehler").json()
                  if z["id"] == rest)
    assert z_rest["typ"] == "rest" and z_rest["hauptzaehler_id"] == gesamt

    # Stände: je Zähler Anfangsstand 0 am Beginn, Endstand am Periodenende.
    for zae, endstand in [(gesamt, 100.0), (u1, 30.0), (u2, 20.0)]:
        client.post(f"/api/zaehler/{zae}/ablesungen",
                    json={"stand": 0.0, "datum": start, "notiz": "Anfangsstand"})
        client.post(f"/api/zaehler/{zae}/ablesungen",
                    json={"stand": endstand, "datum": ende, "zeitraum_id": zid})

    verb = {z["id"]: z["verbrauch"]
            for z in client.get(f"/api/zeitraeume/{zid}/ablesung").json()["zaehler"]}
    assert verb[gesamt] == 100.0
    assert verb[u1] == 30.0 and verb[u2] == 20.0
    # berechneter Rest: 100 − 30 − 20 = 50 (ohne eigene Ablesung)
    assert verb[rest] == 50.0


def test_uebernehmen_bildet_gewichte_je_partei(client):
    """Die Übernahme in die Abrechnung nutzt dieselbe (Vorlauf-)Interpolation:
    die Zähler-Verbräuche werden zu Partei-Gewichten der bestehenden Position."""
    slug, zid, maske = _neues_objekt(client)
    start, ende = maske["zeitraum"]["start"], maske["zeitraum"]["ende"]
    u1 = _anlegen(client, slug, name="Büro", kostenart="Wasser", einheit_bezug="Büro")
    u2 = _anlegen(client, slug, name="WG", kostenart="Wasser", einheit_bezug="WG")
    for zae, endstand in [(u1, 40.0), (u2, 60.0)]:
        client.post(f"/api/zaehler/{zae}/ablesungen",
                    json={"stand": 0.0, "datum": start, "notiz": "Anfangsstand"})
        client.post(f"/api/zaehler/{zae}/ablesungen",
                    json={"stand": endstand, "datum": ende, "zeitraum_id": zid})
    # Eine bestehende Position ist Voraussetzung (keine leere Hülle, CCLVI).
    client.post(f"/api/zeitraeume/{zid}/positionen",
                json={"kostenart": "Wasser", "betrag": 300.0})
    r = client.post(f"/api/zeitraeume/{zid}/ablesung/uebernehmen",
                    json={"kostenart": "Wasser", "schluessel": "verbrauch"}).json()
    assert r["angewandt"] is True
    assert r["anteile"] == {"Büro": 40.0, "WG": 60.0}
