"""Objekt anlegen, Stammdaten pflegen, Auswertung rechnen."""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_stammdaten.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

# Je Bereich: was angelegt wird, welches Feld geändert wird und worauf.
# Deckt die vier echten Entitäten aus stammdaten.py ab.
BEREICHE = [
    ("versicherungen", {"art": "Gebäude", "jahresbeitrag": 100.0},
     "jahresbeitrag", 125.0),
    ("mieten", {"einheit": "EG", "partei": "Mieter A", "kaltmiete": 800.0,
                "ab_datum": "2025-01-01"}, "kaltmiete", 850.0),
    ("kredite", {"bezeichnung": "Kauf", "rate_monatlich": 500.0},
     "rate_monatlich", 540.0),
    ("zahlungen", {"jahr": 2025, "art": "Grundsteuer", "betrag": 240.0},
     "betrag", 260.0),
]


def test_objekt_anlegen_und_auswerten():
    with TestClient(app) as c:
        vorher = len(c.get("/api/objekte").json())

        neu = c.post("/api/objekte", json={
            "name": "Teststraße 7", "ort": "Musterstadt", "turnus": "kalender",
            "start_monat": 1, "kostenarten": ["Wasser", "Müll"],
            "einheiten": [{"bezeichnung": "EG", "flaeche": 70.0, "partei": "Mieter A"}],
        })
        assert neu.status_code == 201
        slug = neu.json()["slug"]
        assert slug == "teststrasse-7"          # Umlaute/ß werden übersetzt

        objekte = c.get("/api/objekte").json()
        assert len(objekte) == vorher + 1

        # Das neue Objekt hat sofort einen laufenden Zeitraum und eine Frist.
        det = c.get(f"/api/objekte/{slug}").json()
        assert len(det["zeitraeume"]) == 1
        assert det["zeitraeume"][0]["frist_tage"] is not None
        assert len(det["einheiten"]) == 1
        assert [k["name"] for k in c.get(f"/api/objekte/{slug}/kostenarten").json()] \
            == ["Wasser", "Müll"]

        # Stammdaten anlegen
        assert c.post(f"/api/objekte/{slug}/mieten", json={
            "einheit": "EG", "partei": "Mieter A", "kaltmiete": 800.0,
            "nebenkosten_vz": 150.0, "ab_datum": "2025-01-01"}).status_code == 201
        assert c.post(f"/api/objekte/{slug}/versicherungen", json={
            "art": "Gebäude", "anbieter": "Allianz", "jahresbeitrag": 480.0}).status_code == 201
        assert c.post(f"/api/objekte/{slug}/kredite", json={
            "bezeichnung": "Kauf", "bank": "Sparkasse",
            "rate_monatlich": 500.0}).status_code == 201
        assert c.post(f"/api/objekte/{slug}/zahlungen", json={
            "jahr": 2025, "art": "Grundsteuer", "kategorie": "Steuer",
            "betrag": 240.0}).status_code == 201

        assert len(c.get(f"/api/objekte/{slug}/mieten").json()) == 1

        # Auswertung: 12 x 800 Miete gegen 12 x 500 Kredit + 480 Vers. + 240 Steuer
        a = c.get("/api/auswertung", params={"jahr": 2025, "objekt": slug}).json()
        zeile = a["objekte"][0]
        assert zeile["einnahmen"] == 9600.0
        assert zeile["bloecke"]["Kredit"] == 6000.0
        assert zeile["bloecke"]["Versicherung"] == 480.0
        assert zeile["bloecke"]["Steuer"] == 240.0
        assert zeile["ausgaben"] == 6720.0
        assert zeile["saldo"] == 2880.0

        verlauf = c.get("/api/auswertung/mietverlauf", params={"objekt": slug}).json()
        assert verlauf["reihen"][0]["werte"][-1] == 9600.0


def test_stammdaten_aendern_und_loeschen():
    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={"name": "Löschweg 1"}).json()["slug"]
        eintrag = c.post(f"/api/objekte/{slug}/versicherungen",
                         json={"art": "Haftpflicht", "jahresbeitrag": 100.0}).json()["id"]

        assert c.patch(f"/api/versicherungen/{eintrag}",
                       json={"jahresbeitrag": 125.0}).status_code == 200
        assert c.get(f"/api/objekte/{slug}/versicherungen").json()[0]["jahresbeitrag"] == 125.0

        assert c.delete(f"/api/versicherungen/{eintrag}").status_code == 200
        assert c.get(f"/api/objekte/{slug}/versicherungen").json() == []


@pytest.mark.parametrize("bereich,anlage,feld,neuer_wert", BEREICHE)
def test_kanonischer_pfad_aendern_und_loeschen(bereich, anlage, feld, neuer_wert):
    """Der Weg, den die Oberfläche tatsächlich geht: /api/stammdaten/…

    Die Altroute ohne Präfix bleibt daneben bestehen; bricht das Präfix oder
    die Registrierungsreihenfolge, könnte die Oberfläche weder speichern noch
    löschen — dieser Test schlägt dann an."""
    with TestClient(app) as c:
        slug = c.post("/api/objekte",
                      json={"name": f"Kanonweg {bereich}"}).json()["slug"]
        eintrag = c.post(f"/api/objekte/{slug}/{bereich}", json=anlage).json()["id"]

        aendern = c.patch(f"/api/stammdaten/{bereich}/{eintrag}",
                          json={feld: neuer_wert})
        assert aendern.status_code == 200, aendern.text
        assert c.get(f"/api/objekte/{slug}/{bereich}").json()[0][feld] == neuer_wert

        assert c.delete(f"/api/stammdaten/{bereich}/{eintrag}").status_code == 200
        assert c.get(f"/api/objekte/{slug}/{bereich}").json() == []


@pytest.mark.parametrize("bereich", [b[0] for b in BEREICHE])
def test_kanonischer_pfad_unbekannte_id_ist_404(bereich):
    with TestClient(app) as c:
        assert c.patch(f"/api/stammdaten/{bereich}/999999",
                       json={"notiz": "x"}).status_code == 404
        assert c.delete(f"/api/stammdaten/{bereich}/999999").status_code == 404


def test_kanonischer_pfad_unbekannter_bereich_ist_404():
    with TestClient(app) as c:
        fehler = c.patch("/api/stammdaten/quatsch/1", json={"notiz": "x"})
        assert fehler.status_code == 404
        assert "Unbekannter Bereich" in fehler.json()["detail"]
        assert c.delete("/api/stammdaten/quatsch/1").status_code == 404


def test_unbekannter_bereich_ist_404():
    with TestClient(app) as c:
        assert c.get("/api/objekte/obj-a/quatsch").status_code == 404


def test_geplante_erhoehung_entsteht_nur_einmal():
    """CLIII: „Mieterhöhung planen" liess sich mehrfach auslösen.

    Dabei entstanden mehrere offene Stände derselben Partei ab demselben Tag,
    alle mit dem Vermerk „geplant" — welcher gilt, entschied dann die
    Reihenfolge in der Datenbank, und die Abrechnung rechnete mit dem falschen.
    Eine Staffel mit späterem Wirkungstag bleibt erlaubt."""
    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={"name": "Staffelweg 7"}).json()["slug"]
        anlegen = lambda **f: c.post(f"/api/objekte/{slug}/mieten", json=f)  # noqa: E731

        assert anlegen(partei="Lorenz", einheit="EG", kaltmiete=800,
                       ab_datum="2024-01-01").status_code == 201
        assert anlegen(partei="Lorenz", einheit="EG", kaltmiete=830,
                       ab_datum="2026-08-01").status_code == 201

        # derselbe Tag, dieselbe Partei — der zweite Anlauf wird abgewiesen
        zweimal = anlegen(partei="Lorenz", einheit="EG", kaltmiete=830,
                          ab_datum="2026-08-01")
        assert zweimal.status_code == 409
        assert "bereits einen Mietstand" in zweimal.json()["detail"]

        # eine echte Staffel ein Jahr später ist kein Doppel
        assert anlegen(partei="Lorenz", einheit="EG", kaltmiete=860,
                       ab_datum="2027-08-01").status_code == 201
        # und eine andere Partei darf am selben Tag beginnen
        assert anlegen(partei="Sommer", einheit="OG", kaltmiete=900,
                       ab_datum="2026-08-01").status_code == 201

        mieten = c.get(f"/api/objekte/{slug}/mieten").json()
        assert len(mieten) == 4


def test_doppelbelegung_einer_einheit_wird_abgewiesen():
    """CXLIII: eine Einheit ist nicht zweimal gleichzeitig vermietet.

    Der Hinweis muss die Überschneidung nennen — sonst rät der Nutzer, welches
    Enddatum fehlt."""
    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={
            "name": "Doppelweg 2",
            "einheiten": [{"bezeichnung": "EG"}, {"bezeichnung": "OG"}],
        }).json()["slug"]
        anlegen = lambda **f: c.post(f"/api/objekte/{slug}/mieten", json=f)  # noqa: E731

        assert anlegen(partei="Alt", einheit="EG", kaltmiete=800,
                       ab_datum="2024-01-01").status_code == 201

        # offenes Ende -> jeder spätere Beginn in derselben Einheit kollidiert
        doppelt = anlegen(partei="Neu", einheit="EG", kaltmiete=900,
                          ab_datum="2025-07-01")
        assert doppelt.status_code == 409
        text = doppelt.json()["detail"]
        assert "01.07.2025" in text and "Alt" in text

        # eine andere Einheit geht selbstverständlich
        assert anlegen(partei="Neu", einheit="OG", kaltmiete=900,
                       ab_datum="2025-07-01").status_code == 201


def test_lueckenloser_mieterwechsel_bleibt_erlaubt():
    """Der alte endet am 30.06., der neue beginnt am 01.07. — kein Doppel."""
    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={
            "name": "Wechselweg 4",
            "einheiten": [{"bezeichnung": "EG"}]}).json()["slug"]

        assert c.post(f"/api/objekte/{slug}/mieten", json={
            "partei": "Vormieter", "einheit": "EG", "kaltmiete": 800.0,
            "ab_datum": "2024-01-01", "bis_datum": "2025-06-30"}).status_code == 201
        nach = c.post(f"/api/objekte/{slug}/mieten", json={
            "partei": "Nachmieter", "einheit": "EG", "kaltmiete": 860.0,
            "ab_datum": "2025-07-01"})
        assert nach.status_code == 201, nach.text

        # ein Tag früher überschneidet sich und wird abgewiesen
        frueher = c.post(f"/api/objekte/{slug}/mieten", json={
            "partei": "Zufrüh", "einheit": "EG", "kaltmiete": 860.0,
            "ab_datum": "2025-06-30", "bis_datum": "2025-06-30"})
        assert frueher.status_code == 409
        assert "30.06.2025" in frueher.json()["detail"]


def test_enddatum_entfernen_darf_keine_doppelbelegung_erzeugen():
    """Die Lücke schliesst sich auch beim Ändern: nimmt man dem Vormieter sein
    Enddatum weg, wohnen plötzlich zwei gleichzeitig in derselben Wohnung."""
    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={
            "name": "Rückwärtsweg 1",
            "einheiten": [{"bezeichnung": "EG"}]}).json()["slug"]
        alt = c.post(f"/api/objekte/{slug}/mieten", json={
            "partei": "Vormieter", "einheit": "EG", "kaltmiete": 800.0,
            "ab_datum": "2024-01-01", "bis_datum": "2025-06-30"}).json()["id"]
        c.post(f"/api/objekte/{slug}/mieten", json={
            "partei": "Nachmieter", "einheit": "EG", "kaltmiete": 860.0,
            "ab_datum": "2025-07-01"})

        offen = c.patch(f"/api/stammdaten/mieten/{alt}", json={"bis_datum": None})
        assert offen.status_code == 409
        assert "Nachmieter" in offen.json()["detail"]

        # die Miete desselben Standes zu ändern bleibt jederzeit möglich
        assert c.patch(f"/api/stammdaten/mieten/{alt}",
                       json={"kaltmiete": 820.0}).status_code == 200


def test_einheiten_anlegen_aendern_und_loeschen():
    """CXLI: die Einheiten eines Hauses sind sichtbar und bearbeitbar."""
    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={"name": "Einheitenweg 5"}).json()["slug"]
        assert c.get(f"/api/objekte/{slug}/einheiten").json() == []

        neu = c.post(f"/api/objekte/{slug}/einheiten", json={
            "bezeichnung": "1. OG", "nutzungsart": "Wohnen", "flaeche": 78.0,
            "nebenflaeche": 6.0, "stellplaetze": 1})
        assert neu.status_code == 201, neu.text
        eid = neu.json()["id"]

        zeile = c.get(f"/api/objekte/{slug}/einheiten").json()[0]
        assert zeile["bezeichnung"] == "1. OG"
        assert zeile["flaeche"] == 78.0 and zeile["stellplaetze"] == 1
        assert zeile["vermietet"] is False

        # dieselbe Bezeichnung ein zweites Mal — auch in anderer Schreibweise
        assert c.post(f"/api/objekte/{slug}/einheiten",
                      json={"bezeichnung": "1. og"}).status_code == 409

        assert c.patch(f"/api/einheiten/{eid}",
                       json={"flaeche": 80.5, "nutzungsart": "Gewerbe"}).status_code == 200
        zeile = c.get(f"/api/objekte/{slug}/einheiten").json()[0]
        assert zeile["flaeche"] == 80.5 and zeile["nutzungsart"] == "Gewerbe"

        assert c.delete(f"/api/einheiten/{eid}").status_code == 200
        assert c.get(f"/api/objekte/{slug}/einheiten").json() == []
        assert c.delete(f"/api/einheiten/{eid}").status_code == 404


def test_einheit_zeigt_ihren_heutigen_mieter():
    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={
            "name": "Belegtweg 8",
            "einheiten": [{"bezeichnung": "EG"}, {"bezeichnung": "OG"}]}).json()["slug"]
        c.post(f"/api/objekte/{slug}/mieten", json={
            "partei": "Frau Sommer", "einheit": "EG", "kaltmiete": 700.0,
            "ab_datum": "2020-01-01"})

        zeilen = {e["bezeichnung"]: e for e in
                  c.get(f"/api/objekte/{slug}/einheiten").json()}
        assert zeilen["EG"]["vermietet"] is True
        assert zeilen["EG"]["mieter"] == "Frau Sommer"
        assert zeilen["EG"]["kaltmiete"] == 700.0
        assert zeilen["OG"]["vermietet"] is False and zeilen["OG"]["mieter"] == ""


def test_umbenennen_zieht_die_mietverhaeltnisse_mit():
    """Fund XCII in Zeitlupe: hiesse die Einheit nach dem Umbenennen anders als
    in der Miete, fiele die Partei stumm aus der Kostenverteilung."""
    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={
            "name": "Namensweg 9",
            "einheiten": [{"bezeichnung": "EG", "flaeche": 60}]}).json()["slug"]
        eid = c.get(f"/api/objekte/{slug}/einheiten").json()[0]["id"]
        c.post(f"/api/objekte/{slug}/mieten", json={
            "partei": "Herr Berg", "einheit": "EG", "kaltmiete": 700.0,
            "ab_datum": "2020-01-01"})

        antwort = c.patch(f"/api/einheiten/{eid}", json={"bezeichnung": "EG links"})
        assert antwort.status_code == 200
        assert antwort.json()["mieten_umbenannt"] == 1
        assert c.get(f"/api/objekte/{slug}/mieten").json()[0]["einheit"] == "EG links"
        assert c.get(f"/api/objekte/{slug}/einheiten").json()[0]["vermietet"] is True


def test_einheit_mit_mietverhaeltnis_wird_nicht_geloescht():
    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={
            "name": "Haltweg 3",
            "einheiten": [{"bezeichnung": "EG"}, {"bezeichnung": "OG"}]}).json()["slug"]
        eid = next(e["id"] for e in c.get(f"/api/objekte/{slug}/einheiten").json()
                   if e["bezeichnung"] == "EG")
        c.post(f"/api/objekte/{slug}/mieten", json={
            "partei": "Herr Klein", "einheit": "EG", "kaltmiete": 700.0,
            "ab_datum": "2020-01-01"})

        weg = c.delete(f"/api/einheiten/{eid}")
        assert weg.status_code == 409
        assert "Herr Klein" in weg.json()["detail"]
        assert len(c.get(f"/api/objekte/{slug}/einheiten").json()) == 2


def test_grundstueck_bekommt_keine_einheiten():
    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={"name": "Steigäcker",
                                            "typ": "lg-grundstueck"}).json()["slug"]
        antwort = c.post(f"/api/objekte/{slug}/einheiten",
                         json={"bezeichnung": "Acker"})
        assert antwort.status_code == 400
        assert "Grundstück" in antwort.json()["detail"]


def test_faenger_verschluckt_keine_zweisegmentigen_pfade():
    """Fund LXXI: früher stand unter /api ein Fänger `/{bereich}/{eintrag_id}`.

    Der beantwortete jeden zweisegmentigen Pfad mit „Unbekannter Bereich" —
    PATCH /api/dokumente/5 kam nie beim Dokument-Router an. Ebenso darf der
    Fänger `/objekte/{slug}/{bereich}` die Anteile nicht abfangen."""
    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={"name": "Fängerweg 3"}).json()["slug"]

        anteile = c.get(f"/api/objekte/{slug}/anteile")
        assert anteile.status_code == 200, anteile.text
        assert "anteile" in anteile.json()

        for antwort in (c.patch("/api/dokumente/999999", json={}),
                        c.delete("/api/dokumente/999999"),
                        c.patch("/api/positionen/999999", json={}),
                        c.delete("/api/positionen/999999"),
                        c.delete("/api/anteile/999999")):
            assert "Unbekannter Bereich" not in antwort.text, antwort.text


def test_fehlendes_pflichtfeld_ist_400_kein_500():
    """Ein Kredit ohne Bezeichnung ist ein Eingabefehler, kein Serverfehler.

    Vorher warf `model_validate` eine ValidationError durch bis zum 500 — die
    Oberfläche bekam eine leere Fehlermeldung. Jetzt: 400 mit dem Feldnamen."""
    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={"name": "Pflichtweg 1"}).json()["slug"]
        antwort = c.post(f"/api/objekte/{slug}/kredite",
                         json={"bank": "Sparkasse", "restschuld": 100000})
        assert antwort.status_code == 400
        assert "bezeichnung" in antwort.json()["detail"].lower()
