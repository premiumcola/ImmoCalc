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
from datetime import date

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
    # N376 — die Antwort nennt zusätzlich, welche Unterzähler ihren Verweis
    # auf diesen Hauptzähler verloren haben; hier ist es keiner.
    weg = client.delete(f"/api/zaehler/{zid}").json()
    assert weg["ok"] is True and weg["geloest"] == []
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


def test_anfangsstand_entfernen(client):
    """N390 — DELETE /zaehler/{id}/anfangsstand löscht nur die als
    ANFANGSSTAND markierte Ablesung, eine echte Zeitraum-Ablesung bleibt
    unberührt; ohne gesetzten Anfangsstand gibt es 404."""
    slug, zid, maske = _neues_objekt(client)
    start, ende = maske["zeitraum"]["start"], maske["zeitraum"]["ende"]
    z = _anlegen(client, slug, name="Kaltwasser", kostenart="Wasser",
                 einheit_bezug="Büro")

    r = client.delete(f"/api/zaehler/{z}/anfangsstand")
    assert r.status_code == 404

    client.post(f"/api/zaehler/{z}/anfangsstand",
                json={"stand": 1000.0, "datum": start})
    client.post(f"/api/zaehler/{z}/ablesungen",
                json={"stand": 1210.0, "datum": ende, "zeitraum_id": zid})

    r2 = client.delete(f"/api/zaehler/{z}/anfangsstand")
    assert r2.status_code == 200
    assert r2.json()["anfangsstand"] is None

    abls = client.get(f"/api/zaehler/{z}/ablesungen").json()
    assert len(abls) == 1
    assert abls[0]["stand"] == 1210.0

    r3 = client.delete(f"/api/zaehler/{z}/anfangsstand")
    assert r3.status_code == 404


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


def _haus_mit_mietern(c) -> tuple[str, int, dict]:
    """Zwei Einheiten, zwei Mieter — Einheiten- und Mieternamen verschieden.

    Genau so sieht ein echtes Objekt aus (N367): „Wohnug 1.OG" heißt die
    Einheit, „Nicklas" der Mieter. Ein Testobjekt, in dem beide gleich heißen,
    kann den Unterschied zwischen Einheiten- und Partei-Schlüssel gar nicht
    zeigen — genau daran ist der Fehler jahrelang vorbeigelaufen."""
    antwort = c.post("/api/objekte", json={
        "name": "Mieterhaus", "ort": "Teststadt", "turnus": "kalender",
        "start_monat": 1, "kostenarten": ["Wasser"],
        "einheiten": [{"bezeichnung": "EG", "flaeche": 70.0},
                      {"bezeichnung": "OG", "flaeche": 70.0}],
    })
    assert antwort.status_code == 201
    slug = antwort.json()["slug"]
    zid = c.get(f"/api/objekte/{slug}").json()["zeitraeume"][0]["id"]
    maske = c.get(f"/api/zeitraeume/{zid}/ablesung").json()
    for einheit, partei in (("EG", "Frau Vogel"), ("OG", "Herr Nicklas")):
        assert c.post(f"/api/objekte/{slug}/mieten", json={
            "einheit": einheit, "partei": partei, "kaltmiete": 700.0,
            "ab_datum": maske["zeitraum"]["start"]}).status_code in (200, 201)
    return slug, zid, maske


def test_uebernehmen_bildet_gewichte_je_partei(client):
    """Die Gewichte laufen auf PARTEI-Namen, nicht auf Einheiten-Bezeichnungen.

    `engine.Position.anteile` ist nach Partei geschlüsselt (`verteilung.
    gewichte` schreibt `out[b.partei]`). Stand dort eine Einheiten-
    Bezeichnung, verteilte die Abrechnung an eine Partei, die es nicht gibt:
    der Mieter bekam nichts und sein Saldo war um den vollen Betrag falsch."""
    slug, zid, maske = _haus_mit_mietern(client)
    start, ende = maske["zeitraum"]["start"], maske["zeitraum"]["ende"]
    u1 = _anlegen(client, slug, name="Wasser EG", kostenart="Wasser",
                  einheit_bezug="EG")
    u2 = _anlegen(client, slug, name="Wasser OG", kostenart="Wasser",
                  einheit_bezug="OG")
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
    assert r["anteile"] == {"Frau Vogel": 40.0, "Herr Nicklas": 60.0}

    # Und das Geld kommt auch wirklich bei den beiden an — das ist der Punkt:
    # ein Einheiten-Schlüssel erzeugte hier eine Partei, die es nicht gibt.
    abrechnung = client.get(f"/api/zeitraeume/{zid}/abrechnung").json()
    assert set(abrechnung["parteien"]) == {"Frau Vogel", "Herr Nicklas"}
    # 300 € nach Verbrauch 40:60 — beide tragen echtes Geld, keiner 0 €.
    lasten = {name: eintrag["kosten"]
              for name, eintrag in abrechnung["parteien"].items()}
    assert all(betrag > 0 for betrag in lasten.values()), lasten
    assert round(sum(lasten.values()), 2) == 300.0, lasten


def test_uebernehmen_teilt_mehrfachzuordnung_und_schreibt_nichts_ins_leere(client):
    """Zwei Fälle, die vorher lautlos Geld verloren (N367).

    (a) Ein Zähler, der über `einheiten` auf zwei Wohnungen zeigt, ging
        komplett auf `einheit_bezug` — die zweite Einheit trug nichts.
    (b) Lässt sich gar nichts zuordnen, wurde ein LEERES `anteile` geschrieben.
        `verteile_nach_wert` liefert bei Gewichtssumme 0 ein leeres dict: die
        ganze Position fiel aus der Abrechnung — quittiert mit „angewandt"."""
    slug, zid, maske = _haus_mit_mietern(client)
    start, ende = maske["zeitraum"]["start"], maske["zeitraum"]["ende"]
    geteilt = _anlegen(client, slug, name="Waschküche", kostenart="Wasser",
                       einheiten=["EG", "OG"])
    client.post(f"/api/zaehler/{geteilt}/ablesungen",
                json={"stand": 0.0, "datum": start, "notiz": "Anfangsstand"})
    client.post(f"/api/zaehler/{geteilt}/ablesungen",
                json={"stand": 50.0, "datum": ende, "zeitraum_id": zid})
    client.post(f"/api/zeitraeume/{zid}/positionen",
                json={"kostenart": "Wasser", "betrag": 300.0})
    r = client.post(f"/api/zeitraeume/{zid}/ablesung/uebernehmen",
                    json={"kostenart": "Wasser", "schluessel": "verbrauch"}).json()
    assert r["angewandt"] is True
    assert r["anteile"] == {"Frau Vogel": 25.0, "Herr Nicklas": 25.0}

    # (b) Ein Zähler, dessen Ziel es im Objekt nicht gibt.
    slug2, zid2, maske2 = _haus_mit_mietern(client)
    s2, e2 = maske2["zeitraum"]["start"], maske2["zeitraum"]["ende"]
    fremd = _anlegen(client, slug2, name="Phantom", kostenart="Wasser",
                     einheit_bezug="Gibtsnicht")
    client.post(f"/api/zaehler/{fremd}/ablesungen",
                json={"stand": 0.0, "datum": s2, "notiz": "Anfangsstand"})
    client.post(f"/api/zaehler/{fremd}/ablesungen",
                json={"stand": 10.0, "datum": e2, "zeitraum_id": zid2})
    client.post(f"/api/zeitraeume/{zid2}/positionen",
                json={"kostenart": "Wasser", "betrag": 300.0})
    r2 = client.post(f"/api/zeitraeume/{zid2}/ablesung/uebernehmen",
                     json={"kostenart": "Wasser", "schluessel": "verbrauch"}).json()
    assert r2["angewandt"] is False, "Eine leere Verteilung darf nicht greifen"
    assert r2["unzugeordnet"] == ["Phantom"]
    # Die Position behält ihre bisherige (abgeleitete) Verteilung.
    zeile = next(k for k in client.get(f"/api/zeitraeume/{zid2}").json()["checkliste"]
                 if k["kostenart"] == "Wasser")
    assert zeile["anteile"], "Die bestehende Verteilung wurde überschrieben"


def test_hauptzaehler_loeschen_laesst_keine_sackgasse(client):
    """N376 — ein gelöschter Hauptzähler darf keine toten Verweise hinterlassen.

    `_ist_wasser_haupt` und `stromkette._gesamtzaehler` verzweigen über
    `hauptzaehler_id`. Blieb dort die Nummer eines gelöschten Zählers stehen,
    meldete die Kette „Gesamtverbrauch nicht verfügbar", obwohl alle Stände
    erfasst waren — und der Unterzähler war über die Oberfläche nicht mehr
    aus seiner Zuordnung zu lösen.
    """
    slug, zid, _maske = _neues_objekt(client)
    haupt = _anlegen(client, slug, name="Hauptwasser", kostenart="Wasser",
                     typ="gemessen")
    unter = _anlegen(client, slug, name="Unterzähler EG", kostenart="Wasser",
                     typ="gemessen", hauptzaehler_id=haupt)

    weg = client.delete(f"/api/zaehler/{haupt}")
    assert weg.status_code == 200, weg.text
    assert weg.json()["geloest"] == ["Unterzähler EG"]

    # Der Unterzähler lebt weiter — nur ohne Verweis ins Leere.
    liste = client.get(f"/api/objekte/{slug}/zaehler").json()
    ueberlebt = next(z for z in liste if z["id"] == unter)
    assert ueberlebt["hauptzaehler_id"] is None


# --------------------------------------------------------------------------
# N384 — die reine "Anfang"-Anzeige darf historische Delta-t-Werte nicht als
# echten Zählerstand ausgeben, selbst wenn die eigentliche Rechnung (N381)
# sie schon zurecht ignoriert.
# --------------------------------------------------------------------------

def test_maske_vorwert_ignoriert_historische_werte(client):
    """`routers/zaehler.maske()` hat einen eigenen, zweiten `frueher`-Fallback
    fürs „Anfang"-Feld (N353), unabhängig von `verbrauchsreihe`. Ohne den
    Ausschluss zeigte er einem Zähler ohne echten Anfangsstand trotzdem einen
    „Anfang" an — den alten Delta-t-Verbrauchswert, fälschlich als Stand
    gelesen. Die Rechnung selbst bleibt korrekt leer (`verbrauch` ist None);
    hier geht es um den irreführenden Anzeigetext."""
    slug, zid, maske0 = _neues_objekt(client)
    z = _anlegen(client, slug, name="WMZ", kostenart="Heizung",
                 messeinheit="kWh", typ="gemessen")
    from sqlmodel import Session
    from app.db import engine
    from app.models import Ablesung
    with Session(engine) as s:
        s.add(Ablesung(zaehler_id=z, datum=date(2022, 9, 30), stand=5463.0,
                       notiz="Delta-t-Historie (Saison endet 30.09.2022), "
                             "nachgetragen aus der geprueften Gesamtabrechnung "
                             "— nicht an einen Abrechnungszeitraum gebunden, "
                             "dient nur dem Verlauf."))
        s.commit()

    zeile = next(r for r in client.get(f"/api/zeitraeume/{zid}/ablesung")
                .json()["zaehler"] if r["id"] == z)
    assert zeile["vorwert"] is None, (
        f"zeigt einen historischen Verbrauchswert als Anfangsstand: {zeile['vorwert']}")
    assert zeile["verbrauch"] is None
