"""Eigentümer, Tausendstel-Anteile, die Vermögensübersicht — und was am
Vermögen hängt: die Jahresstände eines Kredits und die Bewohner eines
Mietverhältnisses."""
import json
import os
import sys
import tempfile
from datetime import date, timedelta

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


def test_eigenkapital_anteilig_nutzt_promille_nicht_das_gekappte_tausendstel():
    """N315h: `objekt_vermoegen` bildete die gehaltenen Tausendstel über
    `int(a.tausendstel)` statt über das massgebliche `promille` — 833,3 ‰ von
    300.000 € Eigenkapital wurden dadurch zu 249.900 € (mit `int(833.3) ==
    833`) statt korrekt 249.990 €. Über die echte Anteile-API gesetzt landet
    `promille=833.3` exakt, `tausendstel` nur gerundet auf 833."""
    with TestClient(app) as c:
        slug = _objekt(c, "Bruchweg 9", verkehrswert=300000.0)
        e = c.post("/api/eigentuemer", json={"name": "Katja"}).json()["id"]
        c.post(f"/api/objekte/{slug}/anteile",
               json={"eigentuemer_id": e, "promille": 833.3})

        zeile = next(z for z in c.get("/api/vermoegen").json()["objekte"]
                     if z["slug"] == slug)
        assert zeile["tausendstel"] == 833.3
        assert zeile["eigenkapital"] == 300000.0
        assert zeile["eigenkapital_anteilig"] == 249990.0


def test_vermoegen_ohne_angaben_faellt_nicht_um():
    with TestClient(app) as c:
        slug = _objekt(c, "Leerweg 6")
        zeile = next(z for z in c.get("/api/vermoegen").json()["objekte"]
                     if z["slug"] == slug)
        assert zeile["wert"] is None
        assert zeile["restschuld"] == 0
        assert zeile["eigenkapital"] is None


# --------------------------------------------------------------------------
# CCIX — Rücklagenkonto je Objekt
# --------------------------------------------------------------------------

def test_ruecklage_erscheint_als_eigene_zeile_im_vermoegen():
    """Der Saldo ist zurückgelegtes Eigentümergeld, die monatliche Rücklage ein
    laufender Betrag — beide als eigene Felder, nicht ins Eigenkapital gemischt."""
    with TestClient(app) as c:
        slug = _objekt(c, "Rücklagenweg 50", verkehrswert=500000.0)
        c.post(f"/api/objekte/{slug}/kredite", json={
            "bezeichnung": "Darlehen", "restschuld": 200000.0,
            "zinssatz": 2.0, "rate_monatlich": 1000.0, "turnus": "monatlich"})
        c.patch(f"/api/objekte/{slug}", json={
            "ruecklage_saldo": 15000.0, "ruecklage_monatlich": 250.0})

        zeile = next(z for z in c.get("/api/vermoegen").json()["objekte"]
                     if z["slug"] == slug)
        assert zeile["ruecklage_saldo"] == 15000.0
        assert zeile["ruecklage_monatlich"] == 250.0
        # Der Saldo bleibt aus Eigenkapital und Beleihung heraus.
        assert zeile["eigenkapital"] == 300000.0
        assert zeile["beleihung"] == 40.0


def test_ruecklage_summiert_sich_ueber_alle_objekte():
    with TestClient(app) as c:
        a = _objekt(c, "Summenweg 51")
        b = _objekt(c, "Summenweg 52")
        c.patch(f"/api/objekte/{a}", json={"ruecklage_saldo": 8000.0,
                                           "ruecklage_monatlich": 100.0})
        c.patch(f"/api/objekte/{b}", json={"ruecklage_saldo": 2000.0,
                                           "ruecklage_monatlich": 50.0})
        # Die Summe läuft über alle Objekte der (im Test geteilten) Datenbank —
        # diese beiden steuern zusammen 10.000 € / 150 € bei.
        gesamt = c.get("/api/vermoegen").json()["gesamt"]
        assert gesamt["ruecklage_saldo"] >= 10000.0
        assert gesamt["ruecklage_monatlich"] >= 150.0


def test_objekt_ohne_ruecklage_bleibt_unveraendert():
    """Additiv: ein Bestandsobjekt ohne Rücklage nennt None, nicht 0 — und sein
    Eigenkapital bleibt exakt wie zuvor."""
    with TestClient(app) as c:
        slug = _objekt(c, "Bestandsweg 53", verkehrswert=300000.0)
        zeile = next(z for z in c.get("/api/vermoegen").json()["objekte"]
                     if z["slug"] == slug)
        assert zeile["ruecklage_saldo"] is None
        assert zeile["ruecklage_monatlich"] is None
        assert zeile["eigenkapital"] == 300000.0


# --------------------------------------------------------------------------
# CCVIII — WEG-Ebene: Hausgeld als Eigentümerkosten
# --------------------------------------------------------------------------

def test_weg_hausgeld_erscheint_im_vermoegen():
    with TestClient(app) as c:
        slug = _objekt(c, "WEG-Weg 54", verkehrswert=300000.0)
        c.patch(f"/api/objekte/{slug}", json={
            "weg": True, "hausgeld_monatlich": 320.0,
            "weg_ruecklage_zufuehrung": 90.0, "weg_verwalter": "HV Müller"})
        zeile = next(z for z in c.get("/api/vermoegen").json()["objekte"]
                     if z["slug"] == slug)
        assert zeile["weg"] is True
        assert zeile["hausgeld_monatlich"] == 320.0
        assert zeile["hausgeld_jahr"] == 3840.0
        assert c.get("/api/vermoegen").json()["gesamt"]["hausgeld_jahr"] >= 3840.0


# --------------------------------------------------------------------------
# CLXI/CLXII/CLXXXVI — Eigentum je Einheit
# --------------------------------------------------------------------------

def _einheit(c, slug, bezeichnung, flaeche=None, verkehrswert=None):
    return c.post(f"/api/objekte/{slug}/einheiten", json={
        "bezeichnung": bezeichnung, "flaeche": flaeche,
        "verkehrswert": verkehrswert}).json()


def _miete(c, slug, einheit, partei, kaltmiete):
    return c.post(f"/api/objekte/{slug}/mieten", json={
        "einheit": einheit, "partei": partei, "kaltmiete": kaltmiete,
        "ab_datum": "2024-01-01"}).json()


def test_anteil_kann_an_einer_einheit_haengen():
    """CLXI: „mir gehört Wohnung 2" — ein Anteil trägt optional eine Einheit."""
    with TestClient(app) as c:
        slug = _objekt(c, "Einheitseigen 40")
        _einheit(c, slug, "Wohnung 1")
        _einheit(c, slug, "Wohnung 2")
        e = c.post("/api/eigentuemer", json={"name": "Eigner"}).json()["id"]

        antwort = c.post(f"/api/objekte/{slug}/anteile", json={
            "eigentuemer_id": e, "promille": 1000, "einheit": "Wohnung 2"})
        assert antwort.status_code == 201, antwort.text
        assert antwort.json()["einheit"] == "Wohnung 2"

        stand = c.get(f"/api/objekte/{slug}/anteile").json()
        zeile = stand["anteile"][0]
        assert zeile["einheit"] == "Wohnung 2"
        assert [e["bezeichnung"] for e in stand["einheiten"]] == \
            ["Wohnung 1", "Wohnung 2"]


def test_person_kann_objekt_und_einheit_zugleich_halten():
    """Objekt-Anteil und Einheit-Anteil sind zwei verschiedene Zuordnungen —
    dieselbe Person darf beide tragen, ohne dass sie sich überschreiben."""
    with TestClient(app) as c:
        slug = _objekt(c, "Doppelt 41")
        _einheit(c, slug, "Wohnung 1")
        e = c.post("/api/eigentuemer", json={"name": "Eigner"}).json()["id"]
        c.post(f"/api/objekte/{slug}/anteile",
               json={"eigentuemer_id": e, "promille": 500})
        c.post(f"/api/objekte/{slug}/anteile",
               json={"eigentuemer_id": e, "promille": 1000, "einheit": "Wohnung 1"})

        stand = c.get(f"/api/objekte/{slug}/anteile").json()
        assert len(stand["anteile"]) == 2
        einheiten = {z["einheit"]: z["promille"] for z in stand["anteile"]}
        assert einheiten == {"": 500.0, "Wohnung 1": 1000.0}


def test_zweiter_anteil_derselben_einheit_aendert_statt_zu_doppeln():
    with TestClient(app) as c:
        slug = _objekt(c, "Einmal 42")
        _einheit(c, slug, "Wohnung 1")
        e = c.post("/api/eigentuemer", json={"name": "Eigner"}).json()["id"]
        c.post(f"/api/objekte/{slug}/anteile",
               json={"eigentuemer_id": e, "promille": 400, "einheit": "Wohnung 1"})
        c.post(f"/api/objekte/{slug}/anteile",
               json={"eigentuemer_id": e, "promille": 1000, "einheit": "Wohnung 1"})

        zeilen = [z for z in c.get(f"/api/objekte/{slug}/anteile").json()["anteile"]
                  if z["einheit"] == "Wohnung 1"]
        assert len(zeilen) == 1
        assert zeilen[0]["promille"] == 1000.0


def test_anteil_aendern_laesst_die_notiz_stehen():
    """Fund N118: das Zuweisen-Fenster sendet nur Eigner und Promille — der
    Upsert schrieb `notiz` trotzdem bedingungslos und löschte damit still eine
    gepflegte Notiz („Erbteil nach Onkel Karl, Vertrag 12/2019")."""
    with TestClient(app) as c:
        slug = _objekt(c, "Notizweg 45")
        e = c.post("/api/eigentuemer", json={"name": "Eigner"}).json()["id"]
        c.post(f"/api/objekte/{slug}/anteile", json={
            "eigentuemer_id": e, "promille": 400,
            "notiz": "Erbteil nach Onkel Karl, Vertrag 12/2019"})

        # Zweiter Aufruf wie aus dem Zuweisen-Fenster: ohne `notiz`.
        antwort = c.post(f"/api/objekte/{slug}/anteile",
                         json={"eigentuemer_id": e, "promille": 600,
                               "einheit": ""})
        assert antwort.status_code == 201, antwort.text

        zeilen = c.get(f"/api/objekte/{slug}/anteile").json()["anteile"]
        assert len(zeilen) == 1
        assert zeilen[0]["promille"] == 600.0
        assert zeilen[0]["notiz"] == "Erbteil nach Onkel Karl, Vertrag 12/2019"

        # Ausdrücklich geleert werden darf sie sehr wohl.
        c.post(f"/api/objekte/{slug}/anteile",
               json={"eigentuemer_id": e, "promille": 600, "notiz": ""})
        zeilen = c.get(f"/api/objekte/{slug}/anteile").json()["anteile"]
        assert zeilen[0]["notiz"] == ""


def test_einheit_anteil_wird_ohne_notiz_nicht_zum_objektanteil():
    """Fund N118: ein Einheiten-Anteil derselben Person darf beim Nachschärfen
    des Promille-Werts nicht als zweiter Objekt-Anteil danebengestellt werden —
    dann stünde am Objekt mehr als das Ganze."""
    with TestClient(app) as c:
        slug = _objekt(c, "Zuvielweg 46")
        _einheit(c, slug, "Wohnung 1")
        e = c.post("/api/eigentuemer", json={"name": "Eigner"}).json()["id"]
        c.post(f"/api/objekte/{slug}/anteile", json={
            "eigentuemer_id": e, "promille": 1000, "einheit": "Wohnung 1",
            "notiz": "gehört mir allein"})
        # Derselbe Anteil, nur der Wert korrigiert — Einheit mitgesendet.
        c.post(f"/api/objekte/{slug}/anteile", json={
            "eigentuemer_id": e, "promille": 900, "einheit": "Wohnung 1"})

        zeilen = c.get(f"/api/objekte/{slug}/anteile").json()["anteile"]
        assert len(zeilen) == 1
        assert zeilen[0]["einheit"] == "Wohnung 1"
        assert zeilen[0]["promille"] == 900.0
        assert zeilen[0]["notiz"] == "gehört mir allein"


def test_anteil_auf_unbekannte_einheit_wird_abgelehnt():
    with TestClient(app) as c:
        slug = _objekt(c, "Unbekannt 43")
        _einheit(c, slug, "Wohnung 1")
        e = c.post("/api/eigentuemer", json={"name": "Eigner"}).json()["id"]
        antwort = c.post(f"/api/objekte/{slug}/anteile", json={
            "eigentuemer_id": e, "promille": 1000, "einheit": "Wohnung 9"})
        assert antwort.status_code == 404


def test_einheit_anteile_pro_einheit_stimmig():
    """Je Einheit müssen 1000 ‰ verteilt sein; sind alle Einheiten zugeordnet,
    braucht es keinen Objekt-Anteil mehr."""
    with TestClient(app) as c:
        slug = _objekt(c, "Prostimmig 44")
        _einheit(c, slug, "Wohnung 1")
        _einheit(c, slug, "Wohnung 2")
        a = c.post("/api/eigentuemer", json={"name": "A"}).json()["id"]
        b = c.post("/api/eigentuemer", json={"name": "B"}).json()["id"]
        c.post(f"/api/objekte/{slug}/anteile",
               json={"eigentuemer_id": a, "promille": 1000, "einheit": "Wohnung 1"})
        c.post(f"/api/objekte/{slug}/anteile",
               json={"eigentuemer_id": b, "promille": 1000, "einheit": "Wohnung 2"})

        stand = c.get(f"/api/objekte/{slug}/anteile").json()
        assert stand["stimmig"] is True
        assert stand["objekt_noetig"] is False

        # CCCVIII: „Wohnung 2" ist mit 1000 ‰ voll — ein weiterer Anteil darf
        # dort nicht mehr angelegt werden (früher entstand still eine Summe von
        # 1500 ‰, die nur als „unstimmig" auffiel).
        antwort = c.post(f"/api/objekte/{slug}/anteile",
                         json={"eigentuemer_id": a, "promille": 500,
                               "einheit": "Wohnung 2"})
        assert antwort.status_code == 400
        assert "1000" in antwort.json()["detail"]

        # Unstimmig wird es weiterhin, wenn zu WENIG verteilt ist: B auf 500 ‰
        # verkleinern lässt 500 ‰ von „Wohnung 2" offen.
        c.post(f"/api/objekte/{slug}/anteile",
               json={"eigentuemer_id": b, "promille": 500, "einheit": "Wohnung 2"})
        stand = c.get(f"/api/objekte/{slug}/anteile").json()
        assert stand["stimmig"] is False


def test_gemischtes_eigentum_rechnet_je_eigentuemer_getrennt():
    """Der Fall des Nutzers: fünf Einheiten, dem einen gehören drei, dem
    anderen eine, eine ist extern. Jeder sieht nur seine Einheiten."""
    with TestClient(app) as c:
        slug = _objekt(c, "Fünferhaus 45")
        for n in range(1, 6):
            _einheit(c, slug, f"Wohnung {n}", flaeche=50, verkehrswert=100000.0)
        a = c.post("/api/eigentuemer", json={"name": "Eigner A"}).json()["id"]
        b = c.post("/api/eigentuemer", json={"name": "Eigner B"}).json()["id"]
        # A: Wohnungen 1-3, B: Wohnung 4, Wohnung 5 extern (kein Anteil)
        for n in (1, 2, 3):
            c.post(f"/api/objekte/{slug}/anteile", json={
                "eigentuemer_id": a, "promille": 1000, "einheit": f"Wohnung {n}"})
            _miete(c, slug, f"Wohnung {n}", f"Mieter {n}", 800.0)
        c.post(f"/api/objekte/{slug}/anteile", json={
            "eigentuemer_id": b, "promille": 1000, "einheit": "Wohnung 4"})
        _miete(c, slug, "Wohnung 4", "Mieter 4", 900.0)
        _miete(c, slug, "Wohnung 5", "Mieter 5", 1000.0)

        ueber = c.get("/api/eigentuemer/uebersicht").json()["eigentuemer"]
        za = next(z for z in ueber if z["id"] == a)
        zb = next(z for z in ueber if z["id"] == b)

        # A: drei Wohnungen à 800 € -> 28.800 €/Jahr, Wert 300.000
        assert za["gesamt"]["miete_jahr"] == round(3 * 800 * 12, 2)
        assert za["gesamt"]["wert"] == 300000.0
        # B: nur Wohnung 4 -> 900 €/Monat, Wert 100.000 — nicht das ganze Haus
        assert zb["gesamt"]["miete_jahr"] == round(900 * 12, 2)
        assert zb["gesamt"]["wert"] == 100000.0
        # Wohnung 5 (extern) taucht in keiner der beiden Sichten auf
        assert all("Wohnung 5" not in
                   {e["bezeichnung"] for e in o["einheiten"]}
                   for o in za["objekte"] + zb["objekte"])


def test_verkehrswert_je_einheit_gewichtet_die_zurechnung():
    """CLXXXVI: der teureren Wohnung fällt der grössere Anteil am Objektwert zu."""
    with TestClient(app) as c:
        slug = _objekt(c, "Wertgewicht 46", verkehrswert=400000.0)
        _einheit(c, slug, "Groß", verkehrswert=300000.0)
        _einheit(c, slug, "Klein", verkehrswert=100000.0)
        a = c.post("/api/eigentuemer", json={"name": "Groß-Eigner"}).json()["id"]
        b = c.post("/api/eigentuemer", json={"name": "Klein-Eigner"}).json()["id"]
        c.post(f"/api/objekte/{slug}/anteile",
               json={"eigentuemer_id": a, "promille": 1000, "einheit": "Groß"})
        c.post(f"/api/objekte/{slug}/anteile",
               json={"eigentuemer_id": b, "promille": 1000, "einheit": "Klein"})

        ueber = c.get("/api/eigentuemer/uebersicht").json()["eigentuemer"]
        za = next(z for z in ueber if z["id"] == a)
        zb = next(z for z in ueber if z["id"] == b)
        # 400.000 Objektwert nach Verkehrswert gewichtet: 300k zu 100k
        assert za["objekte"][0]["wert"] == 300000.0
        assert zb["objekte"][0]["wert"] == 100000.0
        assert za["objekte"][0]["fraktion"] == 0.75


def test_teilweise_gepflegter_verkehrswert_mischt_nicht_euro_mit_quadratmetern():
    """N315(b) — trägt nur EINE Einheit einen Verkehrswert, fiel die andere auf
    ihre Fläche zurück: ein sechsstelliger Eurobetrag gegen eine zweistellige
    Quadratmeterzahl ergab 399.800,10 € gegen 199,90 € statt je 200.000 €.
    Zwei gleich große Wohnungen ohne durchgängigen Verkehrswert müssen sich
    den Objektwert je zur Hälfte teilen."""
    with TestClient(app) as c:
        slug = _objekt(c, "Wertgewicht 46b", verkehrswert=400000.0)
        _einheit(c, slug, "Eins", flaeche=60.0, verkehrswert=300000.0)
        _einheit(c, slug, "Zwei", flaeche=60.0)  # kein Verkehrswert gepflegt
        a = c.post("/api/eigentuemer", json={"name": "Eins-Eigner"}).json()["id"]
        b = c.post("/api/eigentuemer", json={"name": "Zwei-Eigner"}).json()["id"]
        c.post(f"/api/objekte/{slug}/anteile",
               json={"eigentuemer_id": a, "promille": 1000, "einheit": "Eins"})
        c.post(f"/api/objekte/{slug}/anteile",
               json={"eigentuemer_id": b, "promille": 1000, "einheit": "Zwei"})

        ueber = c.get("/api/eigentuemer/uebersicht").json()["eigentuemer"]
        za = next(z for z in ueber if z["id"] == a)
        zb = next(z for z in ueber if z["id"] == b)
        # Gleich grosse Wohnungen -> gleicher Anteil, nicht 300k:60 zu 60:60.
        assert za["objekte"][0]["wert"] == 200000.0
        assert zb["objekte"][0]["wert"] == 200000.0
        assert za["objekte"][0]["fraktion"] == 0.5


def test_verkehrswert_je_einheit_ist_pflegbar():
    with TestClient(app) as c:
        slug = _objekt(c, "Pflege 47")
        eid = _einheit(c, slug, "Wohnung 1")["id"]
        c.patch(f"/api/einheiten/{eid}", json={"verkehrswert": 250000.0})
        e = next(x for x in c.get(f"/api/objekte/{slug}/einheiten").json()
                 if x["id"] == eid)
        assert e["verkehrswert"] == 250000.0


def test_objektanteil_deckt_die_einheiten_ohne_eigene_zuordnung():
    """Einheit-Anteile haben Vorrang; der Objekt-Anteil gilt für den Rest —
    hier bekommt der Objekt-Eigner die nicht einzeln zugeordnete Wohnung."""
    with TestClient(app) as c:
        slug = _objekt(c, "Rest 48", verkehrswert=200000.0)
        _einheit(c, slug, "Wohnung 1", verkehrswert=120000.0)
        _einheit(c, slug, "Wohnung 2", verkehrswert=80000.0)
        a = c.post("/api/eigentuemer", json={"name": "Einheitseigner"}).json()["id"]
        b = c.post("/api/eigentuemer", json={"name": "Resteigner"}).json()["id"]
        # A: Wohnung 1 einzeln; B: ganzes Objekt (deckt den Rest = Wohnung 2)
        c.post(f"/api/objekte/{slug}/anteile",
               json={"eigentuemer_id": a, "promille": 1000, "einheit": "Wohnung 1"})
        c.post(f"/api/objekte/{slug}/anteile",
               json={"eigentuemer_id": b, "promille": 1000})
        _miete(c, slug, "Wohnung 1", "Mieter 1", 700.0)
        _miete(c, slug, "Wohnung 2", "Mieter 2", 500.0)

        stand = c.get(f"/api/objekte/{slug}/anteile").json()
        assert stand["stimmig"] is True

        ueber = c.get("/api/eigentuemer/uebersicht").json()["eigentuemer"]
        za = next(z for z in ueber if z["id"] == a)
        zb = next(z for z in ueber if z["id"] == b)
        assert za["objekte"][0]["wert"] == 120000.0   # nur Wohnung 1
        assert zb["objekte"][0]["wert"] == 80000.0    # der Rest: Wohnung 2
        assert za["gesamt"]["miete_jahr"] == round(700 * 12, 2)
        assert zb["gesamt"]["miete_jahr"] == round(500 * 12, 2)


# --------------------------------------------------------------------------
# N146 — die PV-Anlage als untergeordnete Zeile unter ihrer Immobilie
#
# Die Anlage ist ein eigenes Investment mit eigenen Anteilen. Ihr Wert zählt auf
# den Immobilienwert der Person, aber NICHT in Beleihung und Spielraum.
# --------------------------------------------------------------------------

def _pv(c, slug, anteile=None, anschaffung=36000.0, kwp=19.44):
    """Die PV-Stammdaten setzen — über den Endpunkt, wie die Oberfläche."""
    daten = {"anschaffung_eur": anschaffung, "kwp": kwp}
    if anteile is not None:
        daten["anteile"] = json.dumps(anteile)
    return c.put(f"/api/objekte/{slug}/pv/stammdaten", json=daten)


def _zeile(ueber, eid, slug):
    person = next(z for z in ueber if z["id"] == eid)
    return next(o for o in person["objekte"] if o["slug"] == slug)


def test_pv_anlage_haengt_unter_ihrer_immobilie():
    """Der Fall des Nutzers: die Anlage an der Laufer Str. 5 gehört 5/6 zu 1/6,
    und dem Sechstel-Eigner gehört am Gebäude selbst nichts."""
    with TestClient(app) as c:
        slug = _objekt(c, "PV-Hof 60", verkehrswert=500000.0)
        haus = c.post("/api/eigentuemer",
                      json={"name": "Katja & Roland 60"}).json()["id"]
        pv = c.post("/api/eigentuemer", json={"name": "Roman 60"}).json()["id"]
        c.post(f"/api/objekte/{slug}/anteile",
               json={"eigentuemer_id": haus, "promille": 1000})
        _pv(c, slug, {"Katja & Roland 60": 833.3333, "Roman 60": 166.6666})

        ueber = c.get("/api/eigentuemer/uebersicht").json()["eigentuemer"]
        zh, zp = _zeile(ueber, haus, slug), _zeile(ueber, pv, slug)

        # Die Anlage steht unter der Immobilie, nicht als eigenes Objekt.
        assert zh["pv"]["titel"] == "Investment PV"
        assert zh["pv"]["promille"] == 833.3
        assert zh["pv"]["wert"] == 30000.0
        assert zh["pv"]["wertquelle"] == "Anschaffungswert"
        assert zh["pv"]["kwp"] == 19.44
        # Der Sechstel-Eigner hält am Gebäude nichts — nur an der Anlage.
        assert zp["fraktion"] == 0.0
        assert zp["wert"] == 0.0
        assert zp["pv"]["promille"] == 166.7
        assert zp["pv"]["wert"] == 6000.0


def test_pv_anteil_zaehlt_auf_den_objektwert_der_person():
    """„Auf den Gesamtwert der jeweiligen Immobilie für die Person" — der
    Immobilienwert selbst bleibt daneben unverändert stehen."""
    with TestClient(app) as c:
        slug = _objekt(c, "PV-Hof 61", verkehrswert=300000.0)
        e = c.post("/api/eigentuemer", json={"name": "Alleineigner PV"}).json()["id"]
        c.post(f"/api/objekte/{slug}/anteile",
               json={"eigentuemer_id": e, "promille": 1000})
        _pv(c, slug, {"Alleineigner PV": 1000.0}, anschaffung=36000.0)

        person = next(z for z in c.get("/api/eigentuemer/uebersicht").json()
                      ["eigentuemer"] if z["id"] == e)
        zeile = person["objekte"][0]
        assert zeile["wert"] == 300000.0              # die Immobilie allein
        assert zeile["pv_wert"] == 36000.0
        assert zeile["wert_gesamt"] == 336000.0       # mit der Anlage
        assert person["gesamt"]["wert"] == 300000.0
        assert person["gesamt"]["wert_gesamt"] == 336000.0
        assert person["gesamt"]["eigenkapital_gesamt"] == 336000.0


def test_pv_summe_ueber_alle_personen_trifft_den_anlagenwert():
    """Wird der Anteil auf die Personen addiert, muss die Summe weiterhin dem
    Gesamtwert der Anlage entsprechen — kein Cent mehr, keiner weniger."""
    with TestClient(app) as c:
        slug = _objekt(c, "PV-Hof 62", verkehrswert=200000.0)
        ids = [c.post("/api/eigentuemer", json={"name": f"Drittel {n}"})
               .json()["id"] for n in range(3)]
        c.post(f"/api/objekte/{slug}/anteile",
               json={"eigentuemer_id": ids[0], "promille": 1000})
        _pv(c, slug, {f"Drittel {n}": 333.3 for n in range(3)},
            anschaffung=10000.0)

        # Nur die Zeilen dieses Objekts — die Testdatenbank trägt auch die
        # Objekte der übrigen Tests.
        zeilen = [o for z in c.get("/api/eigentuemer/uebersicht").json()
                  ["eigentuemer"] for o in z["objekte"] if o["slug"] == slug]
        assert round(sum(o["pv_wert"] for o in zeilen), 2) == 10000.0
        # Und die Objektwerte gehen weiterhin auf: Immobilie + Anlage
        assert round(sum(o["wert_gesamt"] for o in zeilen), 2) == 210000.0


def test_objekt_ohne_pv_anlage_bleibt_zahlengleich():
    """Die wichtigste Zusicherung: ein Objekt ohne Anlage ändert sich in
    keiner Zahl. `wert_gesamt` ist dort exakt `wert`."""
    with TestClient(app) as c:
        slug = _objekt(c, "Ohne PV 63", verkehrswert=250000.0)
        e = c.post("/api/eigentuemer", json={"name": "Ohne Anlage"}).json()["id"]
        c.post(f"/api/objekte/{slug}/anteile",
               json={"eigentuemer_id": e, "promille": 1000})

        person = next(z for z in c.get("/api/eigentuemer/uebersicht").json()
                      ["eigentuemer"] if z["id"] == e)
        zeile = next(o for o in person["objekte"] if o["slug"] == slug)
        assert zeile["pv"] is None
        assert zeile["pv_wert"] == 0.0
        assert zeile["wert"] == zeile["wert_gesamt"] == 250000.0
        assert zeile["eigenkapital"] == zeile["eigenkapital_gesamt"] == 250000.0
        assert person["gesamt"]["pv_wert"] == 0.0
        assert person["gesamt"]["wert"] == person["gesamt"]["wert_gesamt"]


def test_pv_anteile_ungleich_tausend_werden_proportional_gerechnet():
    """Von Hand gepflegt, deshalb möglich: 900 ‰. Proportional rechnen und
    hinweisen — nichts sperren."""
    with TestClient(app) as c:
        slug = _objekt(c, "PV-Hof 64", verkehrswert=100000.0)
        a = c.post("/api/eigentuemer", json={"name": "Krumm A"}).json()["id"]
        b = c.post("/api/eigentuemer", json={"name": "Krumm B"}).json()["id"]
        c.post(f"/api/objekte/{slug}/anteile",
               json={"eigentuemer_id": a, "promille": 1000})
        _pv(c, slug, {"Krumm A": 600, "Krumm B": 300}, anschaffung=9000.0)

        ueber = c.get("/api/eigentuemer/uebersicht").json()["eigentuemer"]
        za, zb = _zeile(ueber, a, slug), _zeile(ueber, b, slug)
        assert za["pv"]["wert"] == 6000.0
        assert zb["pv"]["wert"] == 3000.0
        assert za["pv"]["anteile_summe"] == 900.0
        assert any("900 ‰ statt 1000 ‰" in h for h in za["pv"]["hinweise"])


def test_pv_name_ohne_person_wird_benannt_statt_verschwiegen():
    with TestClient(app) as c:
        slug = _objekt(c, "PV-Hof 65", verkehrswert=100000.0)
        e = c.post("/api/eigentuemer", json={"name": "Bekannt 65"}).json()["id"]
        c.post(f"/api/objekte/{slug}/anteile",
               json={"eigentuemer_id": e, "promille": 1000})
        _pv(c, slug, {"Bekannt 65": 500, "Wer ist das": 500},
            anschaffung=10000.0)

        zeile = _zeile(c.get("/api/eigentuemer/uebersicht").json()["eigentuemer"],
                       e, slug)
        assert zeile["pv"]["wert"] == 5000.0          # nur die eigenen 500 ‰
        assert any("Wer ist das" in h for h in zeile["pv"]["hinweise"])


def test_pv_bleibt_aus_beleihung_und_wertsteigerung_heraus():
    """Ausdrücklich gewollt: die Anlage ist kein beleihbares Grundpfandobjekt.
    Beleihungsquote und freier Spielraum rechnen ohne sie."""
    with TestClient(app) as c:
        slug = _objekt(c, "PV-Hof 66", kaufpreis=400000.0, verkehrswert=500000.0)
        e = c.post("/api/eigentuemer", json={"name": "Beleiht 66"}).json()["id"]
        c.post(f"/api/objekte/{slug}/anteile",
               json={"eigentuemer_id": e, "promille": 1000})
        c.post(f"/api/objekte/{slug}/kredite", json={
            "bezeichnung": "Hauskredit", "restschuld": 250000.0,
            "rate_monatlich": 1000.0, "zinssatz": 2.0})
        _pv(c, slug, {"Beleiht 66": 1000.0}, anschaffung=36000.0)

        # /vermoegen (Basis für Quote und Wertentwicklung) kennt die Anlage nicht
        v = next(z for z in c.get("/api/vermoegen").json()["objekte"]
                 if z["slug"] == slug)
        assert v["wert"] == 500000.0
        assert v["beleihung"] == 50.0
        assert v["wertzuwachs"] == 100000.0           # 500.000 − 400.000, ohne PV

        # Und in der Eigentümersicht trägt `wert` weiter die Quote:
        # 250.000 / 500.000, nicht 250.000 / 536.000.
        person = next(z for z in c.get("/api/eigentuemer/uebersicht").json()
                      ["eigentuemer"] if z["id"] == e)
        g = person["gesamt"]
        assert g["wert"] == 500000.0
        assert round(g["restschuld"] / g["wert"] * 100, 1) == 50.0
        assert g["wert_gesamt"] == 536000.0


# --------------------------------------------------------------------------
# CXV — Restschuld fortschreiben statt raten
# --------------------------------------------------------------------------

def _von_hand(rest, rate, zinssatz, monate):
    """Dieselbe Rechnung von Hand — damit der Test nicht die Funktion prüft,
    die er prüfen soll."""
    z = zinssatz / 100 / 12
    for _ in range(monate):
        rest = rest - (rate - rest * z)
    return round(rest, 2)


def test_restschuld_sinkt_monatlich_um_die_tilgung():
    from app.vermoegen import stand_fortschreiben

    # 100.000 € zu 3 %, Rate 500 €: erster Monat 250 € Zins, 250 € Tilgung.
    assert stand_fortschreiben(100000.0, 500.0, 3.0, 1) == 99750.0
    # Danach ist der Zinsanteil kleiner, die Tilgung wächst.
    assert stand_fortschreiben(100000.0, 500.0, 3.0, 12) == \
        _von_hand(100000.0, 500.0, 3.0, 12)
    assert stand_fortschreiben(100000.0, 500.0, 3.0, 12) < 97000.0


def test_ohne_rate_wird_nicht_geraten():
    """Deckt die Rate den Zins nicht, bleibt der letzte bekannte Wert stehen."""
    from app.vermoegen import stand_fortschreiben

    assert stand_fortschreiben(100000.0, 0.0, 3.0, 24) == 100000.0
    assert stand_fortschreiben(100000.0, 100.0, 3.0, 24) == 100000.0
    assert stand_fortschreiben(200.0, 500.0, 3.0, 12) == 0.0   # nie negativ


def test_rueckwaerts_ist_die_umkehrung_der_fortschreibung():
    from app.vermoegen import stand_fortschreiben

    ende = stand_fortschreiben(250000.0, 1200.0, 2.5, 18)
    zurueck = stand_fortschreiben(ende, 1200.0, 2.5, -18)
    assert abs(zurueck - 250000.0) < 0.5


def test_zinskalkulation_und_restschuld_bleiben_synchron_bei_negativer_tilgung():
    """N316f: `stand_fortschreiben` (Restschuld für `verlauf`) und
    `_jahreszins_kalk` (Sollzinsen für dieselbe Zeile) simulierten dieselbe
    Monatsrechnung an zwei unabhängigen Stellen — sobald die Rate den Zins
    nicht mehr deckt (negative Tilgung), durfte keine der beiden Stellen eine
    andere Restschuld unterstellen als die andere. Beide laufen jetzt über
    denselben `_monatsschritt`.

    Mit fest 12 % p. a. und einer Rate von 500 €/Monat auf 100.000 € deckt die
    Rate die 1.000 €/Monat Zins nicht — die Restschuld bleibt das ganze Jahr
    stehen, und die kalkulierten Jahreszinsen müssen exakt zu dieser
    eingefrorenen Restschuld passen (12 × 1.000 € = 12.000 €), nicht zu einer
    Kurve, die weiterrechnet."""
    from types import SimpleNamespace

    from app.vermoegen import _jahreszins_kalk, stand_fortschreiben

    rest, rate, zinssatz = 100000.0, 500.0, 12.0
    kredit = SimpleNamespace(zinssatz=zinssatz, zinssatz_variabel=None,
                             zinsbindung_bis=None)

    restschuld = stand_fortschreiben(rest, rate, zinssatz, 12)
    zinsen_kalk = _jahreszins_kalk(kredit, 2020, rest, rate)

    assert restschuld == 100000.0             # Rate deckt nicht mal den Zins
    assert zinsen_kalk == 12000.0             # 12 × 1.000 € auf denselben Stand

    # Auch mit einem Zinswechsel mitten in der eingefrorenen Phase (fest 12 %,
    # ab Monat 5 variabel 3 % — deckt die Rate wieder) müssen beide Stellen
    # exakt denselben Verlauf unterstellen.
    kredit_wechsel = SimpleNamespace(zinssatz=12.0, zinssatz_variabel=3.0,
                                     zinsbindung_bis=date(2020, 5, 31))
    from app.vermoegen import _fortschreiben_darlehen
    restschuld_wechsel = _fortschreiben_darlehen(kredit_wechsel, 2019, rest, rate, 12)
    zinsen_wechsel = _jahreszins_kalk(kredit_wechsel, 2019, rest, rate)
    # Handgerechnet nachvollzogen statt gegen sich selbst geprüft: 5 Monate
    # fest eingefroren bei 100.000 € (500 € Rate < 1.000 € Zins), danach 7
    # Monate zu 3 % mit Tilgung.
    erwartet_rest = stand_fortschreiben(
        stand_fortschreiben(rest, rate, 12.0, 5), rate, 3.0, 7)
    assert restschuld_wechsel == erwartet_rest == 98236.82
    # Von Hand nachgerechnet: 5 Monate eingefroren (5.000 € Zins auf
    # 100.000 €), danach 7 Monate zu 3 % mit sinkender Restschuld — macht
    # 6.736,82 € Jahreszins. Stimmt das nicht mit `restschuld_wechsel`
    # überein, sind die beiden Stellen wieder auseinandergelaufen.
    assert zinsen_wechsel == 6736.82


def test_zinssatz_und_monatszins_rechnen_ineinander():
    """CXLVIII: wer den Satz nicht kennt, gibt den Zinsanteil je Monat an."""
    from app.vermoegen import monatszins, zinssatz_aus_monatszins

    # 140.000 € zu 1,28 % sind 149,33 € Zinsen im Monat.
    assert monatszins(140000.0, 1.28) == 149.33
    assert zinssatz_aus_monatszins(140000.0, 149.33) == 1.28

    # Und zurueck: der Weg ist in beide Richtungen derselbe.
    assert monatszins(250000.0, 3.45) == 718.75
    assert zinssatz_aus_monatszins(250000.0, 718.75) == 3.45


def test_ohne_restschuld_gibt_es_nichts_umzurechnen():
    """Kein Wert ist keine Null — 0,00 € waere eine Behauptung."""
    from app.vermoegen import monatszins, zinssatz_aus_monatszins

    assert monatszins(None, 1.28) is None
    assert monatszins(0.0, 1.28) is None
    assert monatszins(140000.0, None) is None
    assert zinssatz_aus_monatszins(0.0, 149.33) is None
    assert zinssatz_aus_monatszins(140000.0, None) is None

    # Zinsfrei ist eine Angabe, kein Fehlen.
    assert monatszins(140000.0, 0.0) == 0.0


def test_kleine_betraege_verschwinden_nicht():
    from app.vermoegen import monatszins, zinssatz_aus_monatszins

    assert monatszins(500.0, 1.28) == 0.53      # 0,5333… -> 0,53
    assert monatszins(1.0, 1.28) == 0.0         # unter einem Cent
    assert zinssatz_aus_monatszins(500.0, 0.53) == 1.27


def _kredit_mit_stand(c, slug, jahr, restschuld, zinssatz=3.0, rate=1000.0):
    kid = c.post(f"/api/objekte/{slug}/kredite", json={
        "bezeichnung": "Hauptdarlehen", "restschuld": restschuld,
        "zinssatz": zinssatz, "rate_monatlich": rate,
        "turnus": "monatlich"}).json()["id"]
    antwort = c.post(f"/api/kredite/{kid}/staende",
                     json={"jahr": jahr, "restschuld": restschuld})
    assert antwort.status_code == 201, antwort.text
    return kid


def test_jahresstand_wird_bis_heute_fortgeschrieben():
    heute = date.today()
    with TestClient(app) as c:
        slug = _objekt(c, "Kreditweg 12", kaufpreis=400000.0)
        kid = _kredit_mit_stand(c, slug, heute.year - 1, 200000.0)

        stand = c.get(f"/api/kredite/{kid}/staende").json()
        assert stand["aktuell"]["stand_jahr"] == heute.year - 1
        # Seit dem 31.12. des Vorjahres ist je Monat eine Rate geflossen.
        assert stand["aktuell"]["monate"] == heute.month
        assert stand["aktuell"]["quelle"] == "fortgeschrieben"
        assert stand["aktuell"]["restschuld"] == \
            _von_hand(200000.0, 1000.0, 3.0, heute.month)
        assert stand["aktuell"]["restschuld"] < 200000.0


def test_naechster_stand_korrigiert_die_rechnung():
    """Der eingetragene Jahreswert ist die Wahrheit, nicht die Fortschreibung."""
    heute = date.today()
    with TestClient(app) as c:
        slug = _objekt(c, "Korrekturweg 13", kaufpreis=400000.0)
        kid = _kredit_mit_stand(c, slug, heute.year - 3, 200000.0)
        c.post(f"/api/kredite/{kid}/staende",
               json={"jahr": heute.year - 1, "restschuld": 150000.0})

        stand = c.get(f"/api/kredite/{kid}/staende").json()
        assert stand["aktuell"]["stand_jahr"] == heute.year - 1
        assert stand["aktuell"]["stand_wert"] == 150000.0
        assert stand["aktuell"]["restschuld"] == \
            _von_hand(150000.0, 1000.0, 3.0, heute.month)

        # Der Verlauf weist aus, welches Jahr gemessen und welches gerechnet ist.
        jahre = {z["jahr"]: z for z in stand["verlauf"]}
        assert jahre[heute.year - 3]["eingetragen"] is True
        assert jahre[heute.year - 2]["eingetragen"] is False
        assert jahre[heute.year - 1]["eingetragen"] is True
        assert jahre[heute.year - 1]["restschuld"] == 150000.0


def test_zweiter_stand_im_selben_jahr_aendert_statt_zu_doppeln():
    heute = date.today()
    with TestClient(app) as c:
        slug = _objekt(c, "Zaehlerweg 14")
        kid = _kredit_mit_stand(c, slug, heute.year - 1, 180000.0)
        c.post(f"/api/kredite/{kid}/staende",
               json={"jahr": heute.year - 1, "restschuld": 178500.0})

        stand = c.get(f"/api/kredite/{kid}/staende").json()
        assert len(stand["staende"]) == 1
        assert stand["staende"][0]["restschuld"] == 178500.0


def test_unsinnige_jahresstaende_werden_abgelehnt():
    with TestClient(app) as c:
        slug = _objekt(c, "Grenzweg 15")
        kid = _kredit_mit_stand(c, slug, date.today().year - 1, 100000.0)
        assert c.post(f"/api/kredite/{kid}/staende",
                      json={"jahr": 1234, "restschuld": 1.0}).status_code == 400
        assert c.post(f"/api/kredite/{kid}/staende",
                      json={"jahr": date.today().year,
                            "restschuld": -5.0}).status_code == 400
        assert c.post("/api/kredite/999999/staende",
                      json={"jahr": 2024, "restschuld": 1.0}).status_code == 404


def test_kreditliste_zeigt_die_fortgeschriebene_restschuld():
    """Die Eingabe bleibt stehen, die Rechnung steht daneben."""
    heute = date.today()
    with TestClient(app) as c:
        slug = _objekt(c, "Listenweg 16")
        _kredit_mit_stand(c, slug, heute.year - 1, 200000.0)

        zeile = c.get(f"/api/objekte/{slug}/kredite").json()[0]
        assert zeile["restschuld"] == 200000.0          # unveraendert
        assert zeile["restschuld_aktuell"] < 200000.0   # fortgeschrieben
        assert zeile["staende"] == 1
        assert zeile["stand"]["stand_jahr"] == heute.year - 1


def test_kredit_ohne_jahresstand_bleibt_wie_eingetragen():
    """Der gewachsene Bestand rechnet unveraendert weiter."""
    with TestClient(app) as c:
        slug = _objekt(c, "Bestandsweg 17", verkehrswert=500000.0)
        c.post(f"/api/objekte/{slug}/kredite", json={
            "bezeichnung": "Alt", "restschuld": 300000.0, "zinssatz": 2.0,
            "rate_monatlich": 1000.0, "turnus": "monatlich"})

        zeile = c.get(f"/api/objekte/{slug}/kredite").json()[0]
        assert zeile["restschuld_aktuell"] == 300000.0
        assert zeile["stand"]["quelle"] == "eingetragen"
        # 300.000 € zu 2 % — 500 € der Rate sind Zinsen.
        assert zeile["stand"]["zins_monat"] == 500.0
        vermoegen = next(z for z in c.get("/api/vermoegen").json()["objekte"]
                         if z["slug"] == slug)
        assert vermoegen["restschuld"] == 300000.0


def test_objektseite_und_vermoegen_nennen_dieselbe_restschuld():
    """CLII: die Vermoegensuebersicht liess die Jahresstaende liegen und nannte
    den roh eingetragenen Wert — die Objektseite den fortgeschriebenen. Zwei
    Zahlen fuer dieselbe Restschuld."""
    heute = date.today()
    with TestClient(app) as c:
        slug = _objekt(c, "Gleichweg 24", verkehrswert=400000.0)
        kid = _kredit_mit_stand(c, slug, heute.year - 2, 220000.0)
        c.post(f"/api/kredite/{kid}/staende",
               json={"jahr": heute.year - 1, "restschuld": 212400.0})

        zeile = c.get(f"/api/objekte/{slug}/kredite").json()[0]
        uebersicht = next(z for z in c.get("/api/vermoegen").json()["objekte"]
                          if z["slug"] == slug)
        assert zeile["restschuld"] == 220000.0            # Eingabe bleibt stehen
        assert zeile["restschuld_aktuell"] < 212400.0     # fortgeschrieben
        assert uebersicht["restschuld"] == zeile["restschuld_aktuell"]
        # und daraus folgt alles Weitere
        assert uebersicht["eigenkapital"] == \
            round(400000.0 - zeile["restschuld_aktuell"], 2)


def test_jahresstand_verschwindet_mit_dem_kredit():
    heute = date.today()
    with TestClient(app) as c:
        slug = _objekt(c, "Waisenweg 18")
        kid = _kredit_mit_stand(c, slug, heute.year - 1, 90000.0)
        assert c.delete(f"/api/stammdaten/kredite/{kid}").status_code == 200
        assert c.get(f"/api/kredite/{kid}/staende").status_code == 404

        from sqlmodel import Session, select

        from app.db import engine
        from app.models import Kreditstand
        with Session(engine) as s:
            uebrig = s.exec(select(Kreditstand)
                            .where(Kreditstand.kredit_id == kid)).all()
        assert uebrig == []


# --------------------------------------------------------------------------
# CXLIX — ein Bausparvertrag ist kein Darlehen
# --------------------------------------------------------------------------

def test_bausparguthaben_erhoeht_das_eigenkapital():
    """Der Fund: „LBS Bausparer" lief als Kredit und drueckte das Eigenkapital
    um sein Guthaben — es muesste es erhoehen."""
    with TestClient(app) as c:
        slug = _objekt(c, "Sparweg 30", verkehrswert=500000.0)
        c.post(f"/api/objekte/{slug}/kredite", json={
            "bezeichnung": "Ankaufsdarlehen", "restschuld": 200000.0,
            "zinssatz": 2.0, "rate_monatlich": 1000.0, "turnus": "monatlich"})
        c.post(f"/api/objekte/{slug}/kredite", json={
            "bezeichnung": "LBS Bausparer", "art": "Bausparvertrag",
            "bausparsumme": 140000.0, "angespart": 45000.0,
            "zinssatz": 0.1, "rate_monatlich": 300.0, "turnus": "monatlich"})

        zeile = next(z for z in c.get("/api/vermoegen").json()["objekte"]
                     if z["slug"] == slug)
        assert zeile["restschuld"] == 200000.0        # nur das Darlehen
        assert zeile["bauspar_guthaben"] == 45000.0
        # 500.000 − 200.000 + 45.000 — das Guthaben kommt hinzu, statt zu fehlen
        assert zeile["eigenkapital"] == 345000.0
        # Die Beleihung misst die Belastung des Objekts: 200.000 / 500.000.
        assert zeile["beleihung"] == 40.0
        # Kapitaldienst ist Zins und Tilgung — die Sparrate steht daneben.
        assert zeile["annuitaet_jahr"] == 12000.0
        assert zeile["sparrate_jahr"] == 3600.0
        assert zeile["zinslast_jahr"] == 4000.0
        assert zeile["tilgung_jahr"] == 8000.0


def test_bausparvertrag_nennt_was_noch_zu_sparen_ist():
    with TestClient(app) as c:
        slug = _objekt(c, "Zielweg 31")
        c.post(f"/api/objekte/{slug}/kredite", json={
            "bezeichnung": "LBS", "art": "Bausparvertrag",
            "bausparsumme": 140000.0, "angespart": 45000.0,
            "rate_monatlich": 250.0, "turnus": "monatlich"})

        zeile = c.get(f"/api/objekte/{slug}/kredite").json()[0]
        assert zeile["guthaben_aktuell"] == 45000.0
        assert zeile["restschuld_aktuell"] == 0.0      # keine Schuld
        assert zeile["noch_zu_sparen"] == 95000.0
        # In der Ansparphase gibt es keine Zinslast im Sinne eines Darlehens.
        assert zeile["stand"]["zins_monat"] is None
        assert zeile["stand"]["zuteilungsreif"] is False


def test_sparstand_waechst_statt_zu_sinken():
    """Dieselbe Mechanik wie beim Darlehen, umgekehrtes Vorzeichen."""
    from app.vermoegen import spar_fortschreiben

    # Ohne Verzinsung ist es reines Ansparen: 12 x 300 auf 45.000.
    assert spar_fortschreiben(45000.0, 300.0, 0.0, 12) == 48600.0
    # Rückwärts ist die Umkehrung.
    assert spar_fortschreiben(48600.0, 300.0, 0.0, -12) == 45000.0
    # Über die Bausparsumme hinaus waechst nichts.
    assert spar_fortschreiben(139000.0, 300.0, 0.0, 24, 140000.0) == 140000.0
    # Mit Habenzins wird es etwas mehr als die reine Summe der Beitraege.
    assert spar_fortschreiben(45000.0, 300.0, 1.0, 12) > 48600.0


def test_sparstand_zum_jahresende_wird_fortgeschrieben():
    heute = date.today()
    with TestClient(app) as c:
        slug = _objekt(c, "Standweg 32", verkehrswert=300000.0)
        kid = c.post(f"/api/objekte/{slug}/kredite", json={
            "bezeichnung": "LBS", "art": "Bausparvertrag",
            "bausparsumme": 140000.0, "angespart": 40000.0,
            "rate_monatlich": 300.0, "turnus": "monatlich"}).json()["id"]
        antwort = c.post(f"/api/kredite/{kid}/staende",
                         json={"jahr": heute.year - 1, "sparstand": 45000.0})
        assert antwort.status_code == 201

        zeile = c.get(f"/api/objekte/{slug}/kredite").json()[0]
        assert zeile["angespart"] == 40000.0            # Eingabe bleibt stehen
        assert zeile["guthaben_aktuell"] >= 45000.0     # fortgeschrieben
        assert zeile["stand"]["stand_jahr"] == heute.year - 1
        uebersicht = next(z for z in c.get("/api/vermoegen").json()["objekte"]
                          if z["slug"] == slug)
        assert uebersicht["bauspar_guthaben"] == zeile["guthaben_aktuell"]
        assert uebersicht["eigenkapital"] == \
            round(300000.0 + zeile["guthaben_aktuell"], 2)


def test_bestehende_kredite_bleiben_darlehen():
    """Additiv: wer nichts waehlt, hat weiter ein Darlehen."""
    with TestClient(app) as c:
        slug = _objekt(c, "Bestandsweg 33", verkehrswert=400000.0)
        c.post(f"/api/objekte/{slug}/kredite", json={
            "bezeichnung": "Alt ohne Art", "restschuld": 100000.0,
            "zinssatz": 2.0, "rate_monatlich": 600.0, "turnus": "monatlich"})

        zeile = c.get(f"/api/objekte/{slug}/kredite").json()[0]
        assert zeile["art"] == "Darlehen"
        assert zeile["restschuld_aktuell"] == 100000.0
        assert zeile["guthaben_aktuell"] == 0.0
        uebersicht = next(z for z in c.get("/api/vermoegen").json()["objekte"]
                          if z["slug"] == slug)
        assert uebersicht["eigenkapital"] == 300000.0
        assert uebersicht["bauspar_guthaben"] == 0.0


# --------------------------------------------------------------------------
# CXVI — geplante Mieterhöhungen
# --------------------------------------------------------------------------

def test_kuenftiger_mietstand_gilt_als_geplant():
    heute = date.today()
    with TestClient(app) as c:
        slug = _objekt(c, "Erhoehungsweg 19")
        kuenftig = date(heute.year + 1, 1, 1)
        c.post(f"/api/objekte/{slug}/mieten", json={
            "einheit": "EG", "partei": "Mieter A", "kaltmiete": 800.0,
            "ab_datum": (heute - timedelta(days=400)).isoformat(),
            "bis_datum": (kuenftig - timedelta(days=1)).isoformat()})
        c.post(f"/api/objekte/{slug}/mieten", json={
            "einheit": "EG", "partei": "Mieter A", "kaltmiete": 880.0,
            "ab_datum": kuenftig.isoformat()})

        zeilen = c.get(f"/api/objekte/{slug}/mieten").json()
        laufend = next(z for z in zeilen if z["kaltmiete"] == 800.0)
        geplant = next(z for z in zeilen if z["kaltmiete"] == 880.0)
        assert geplant["geplant"] is True
        assert geplant["beendet"] is False
        assert laufend["geplant"] is False
        # Der laufende Stand endet erst mit der Erhoehung — heute laeuft er noch.
        assert laufend["beendet"] is False

        # Die kuenftige Miete zaehlt erst im kommenden Jahr.
        heuer = c.get("/api/auswertung",
                      params={"jahr": heute.year, "objekt": slug}).json()
        naechstes = c.get("/api/auswertung",
                          params={"jahr": heute.year + 1, "objekt": slug}).json()
        assert naechstes["objekte"][0]["einnahmen"] > \
            heuer["objekte"][0]["einnahmen"]


# --------------------------------------------------------------------------
# CXVII — Kontakt je Bewohner
# --------------------------------------------------------------------------

def _mietverhaeltnis(c, slug):
    return c.post(f"/api/objekte/{slug}/mieten", json={
        "einheit": "EG", "partei": "WG Nord", "kaltmiete": 900.0,
        "email": "haupt@example.org", "ab_datum": "2024-01-01"}).json()["id"]


def test_jeder_bewohner_hat_eigene_mail_und_nummer():
    with TestClient(app) as c:
        slug = _objekt(c, "Bewohnerweg 20")
        mid = _mietverhaeltnis(c, slug)
        for name, mail, nummer in (("Anna", "anna@example.org", "0170 1"),
                                   ("Ben", "ben@example.org", "0170 2")):
            antwort = c.post(f"/api/mieten/{mid}/bewohner", json={
                "name": name, "email": mail, "telefon": nummer})
            assert antwort.status_code == 201, antwort.text

        leute = c.get(f"/api/mieten/{mid}/bewohner").json()
        assert [b["email"] for b in leute] == ["anna@example.org",
                                               "ben@example.org"]
        assert [b["telefon"] for b in leute] == ["0170 1", "0170 2"]
        assert all(b["abrechnung"] is True for b in leute)

        # Der Hauptkontakt am Mietverhaeltnis bleibt unangetastet.
        zeile = c.get(f"/api/objekte/{slug}/mieten").json()[0]
        assert zeile["email"] == "haupt@example.org"
        assert len(zeile["bewohner"]) == 2


def test_bewohner_aendern_und_entfernen():
    with TestClient(app) as c:
        slug = _objekt(c, "Wechselweg 21")
        mid = _mietverhaeltnis(c, slug)
        bid = c.post(f"/api/mieten/{mid}/bewohner",
                     json={"name": "Cem", "email": "alt@example.org"}).json()["id"]

        assert c.patch(f"/api/bewohner/{bid}",
                       json={"email": "neu@example.org",
                             "abrechnung": False}).status_code == 200
        b = c.get(f"/api/mieten/{mid}/bewohner").json()[0]
        assert b["email"] == "neu@example.org"
        assert b["abrechnung"] is False
        assert b["telefon"] == ""            # geleertes Feld bleibt leer

        assert c.delete(f"/api/bewohner/{bid}").status_code == 200
        assert c.get(f"/api/mieten/{mid}/bewohner").json() == []


def test_bewohner_ohne_jede_angabe_wird_abgelehnt():
    with TestClient(app) as c:
        slug = _objekt(c, "Leerbewohnerweg 22")
        mid = _mietverhaeltnis(c, slug)
        assert c.post(f"/api/mieten/{mid}/bewohner",
                      json={"name": "", "email": ""}).status_code == 400
        assert c.post("/api/mieten/999999/bewohner",
                      json={"name": "Niemand"}).status_code == 404


def test_bewohner_verschwinden_mit_dem_mietverhaeltnis():
    with TestClient(app) as c:
        slug = _objekt(c, "Auszugsweg 23")
        mid = _mietverhaeltnis(c, slug)
        c.post(f"/api/mieten/{mid}/bewohner", json={"name": "Dana"})
        assert c.delete(f"/api/stammdaten/mieten/{mid}").status_code == 200
        assert c.get(f"/api/mieten/{mid}/bewohner").status_code == 404
