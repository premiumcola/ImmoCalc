"""Eigentümer, Tausendstel-Anteile, die Vermögensübersicht — und was am
Vermögen hängt: die Jahresstände eines Kredits und die Bewohner eines
Mietverhältnisses."""
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


def test_vermoegen_ohne_angaben_faellt_nicht_um():
    with TestClient(app) as c:
        slug = _objekt(c, "Leerweg 6")
        zeile = next(z for z in c.get("/api/vermoegen").json()["objekte"]
                     if z["slug"] == slug)
        assert zeile["wert"] is None
        assert zeile["restschuld"] == 0
        assert zeile["eigenkapital"] is None


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
