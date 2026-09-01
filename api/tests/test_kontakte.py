"""N309 — das Kontaktbuch: Firmen, Gewerke, Kundennummern.

Der Nutzer will „die Firmennamen aller Handwerker, Versicherer, unsere
Kundennummern und Kontaktdaten immobilienzugehörig" an einer Stelle, gespeist
aus dem, was ohnehin schon in den Belegen steht.

Die zwei Aussagen, die dieser Test schützt:

1. **Wiedererkennung.** „Elektro Müller GmbH", „Elektro Müller gmbh" und
   „Elektro-Müller" sind dieselbe Firma. Ohne das wäre das Kontaktbuch nach
   zehn Belegen unbrauchbar.
2. **Nie überschreiben.** Die Ernte läuft wiederholt. Ein Lauf, der eine von
   Hand korrigierte Telefonnummer wieder durch die schlechtere aus dem Beleg
   ersetzt, macht die Pflege sinnlos.
"""
import os
import sys
import tempfile
from datetime import date

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_kontakte.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

from app import kontakte as logik  # noqa: E402
from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.migrate import BESTANDSFAMILIE_NAME  # noqa: E402
from app.models import (Dokument, Familie, Kontakt, Kundennummer,  # noqa: E402
                        Objekt, Renovierung, Renovierungsposten, Versicherung)


def _familie_id(s: Session) -> int | None:
    """N436 — Kontakte hängen an einer Familie statt an einem Objekt; ohne
    diese id wären direkt in der DB angelegte Test-Kontakte für die
    HTTP-Endpunkte unsichtbar (Besitzprüfung, `conftest._test_familie`
    nutzt dieselbe Bestandsfamilie)."""
    f = s.exec(select(Familie).where(Familie.name == BESTANDSFAMILIE_NAME)).first()
    return f.id if f else None


# --------------------------------------------------------------------------
# Wiedererkennung
# --------------------------------------------------------------------------

def test_schreibweisen_derselben_firma_fallen_zusammen():
    gleich = ["Elektro Müller GmbH", "Elektro Müller gmbh", "Elektro-Müller",
              "  Elektro   Müller  GmbH  ", "Elektro Müller GmbH & Co. KG"]
    schluessel = {logik.schluessel(f) for f in gleich}
    assert len(schluessel) == 1, schluessel


def test_verschiedene_firmen_bleiben_verschieden():
    assert logik.schluessel("Elektro Müller") != logik.schluessel("Elektro Meier")
    assert logik.schluessel("") == ""
    assert logik.schluessel("   ") == ""


def test_art_wird_aus_dem_namen_geraten():
    assert logik.art_raten("WWK Versicherung AG") == "Versicherung"
    assert logik.art_raten("Sparkasse Erlangen") == "Bank"
    assert logik.art_raten("Stadtwerke Eckental") == "Versorger"
    assert logik.art_raten("Finanzamt Erlangen") == "Behörde"
    # Ohne Hinweis im Namen entscheidet das Gewerk.
    assert logik.art_raten("Hofmann", gewerk="Dach") == "Handwerker"
    assert logik.art_raten("Hofmann") == "Sonstiges"
    # Eine Vorgabe gewinnt immer — wer aus der Versicherungsliste kommt, IST eine.
    assert logik.art_raten("Hofmann", "Dach", "Versicherung") == "Versicherung"


# --------------------------------------------------------------------------
# Nie überschreiben
# --------------------------------------------------------------------------

def test_ernte_fuellt_nur_leere_felder():
    k = Kontakt(schluessel="x", firma="X", telefon="0911 111", handgepflegt=[])
    assert logik.zusammenfuehren(k, {"telefon": "0911 999", "email": "a@b.de"})
    assert k.telefon == "0911 111"           # war belegt → bleibt
    assert k.email == "a@b.de"               # war leer → gefüllt


def test_handgepflegtes_wird_nie_ueberschrieben():
    """Der Kern: sonst ersetzte der nächste Lauf die korrigierte Nummer wieder
    durch die schlechtere aus dem Beleg."""
    k = Kontakt(schluessel="x", firma="X", telefon="", handgepflegt=["telefon"])
    logik.zusammenfuehren(k, {"telefon": "0911 999"})
    assert k.telefon == ""                   # geschützt, obwohl leer


def test_pflege_merkt_sich_das_feld():
    with TestClient(app) as c:
        with Session(engine) as s:
            k = Kontakt(schluessel="pflege", firma="Pflege GmbH",
                        erfasst_am=date.today(), handgepflegt=[],
                        familie_id=_familie_id(s))
            s.add(k); s.commit(); s.refresh(k)
            kid = k.id
        antwort = c.patch(f"/api/kontakte/{kid}",
                          json={"telefon": "0911 4711"})
        assert antwort.status_code == 200
        assert antwort.json()["telefon"] == "0911 4711"
        assert "telefon" in antwort.json()["handgepflegt"]
        # Und ein Erntelauf lässt es in Ruhe.
        c.post("/api/kontakte/ernten")
        assert c.get(f"/api/kontakte/{kid}").json()["telefon"] == "0911 4711"


# --------------------------------------------------------------------------
# Die Ernte
# --------------------------------------------------------------------------

_ZAEHLER = [0]


def _welt(c: TestClient):
    """Eine eigene kleine Welt je Test — mit EIGENEM Objekt und eigenem
    Belegpfad. `Dokument.pfad` ist eindeutig indiziert; ein fester Pfad liesse
    den zweiten Test an der Datenbank scheitern statt an seiner Aussage."""
    _ZAEHLER[0] += 1
    n = _ZAEHLER[0]
    slug = c.post("/api/objekte", json={"name": f"Kontaktweg {n}", "einheiten": [
        {"bezeichnung": "EG", "flaeche": 50}]}).json()["slug"]
    with Session(engine) as s:
        o = s.exec(select(Objekt).where(Objekt.slug == slug)).first()
        r = Renovierung(objekt_id=o.id, name="Sanierung", von=date(2025, 1, 1))
        s.add(r); s.commit(); s.refresh(r)
        s.add(Renovierungsposten(renovierung_id=r.id, betrag=8200.0,
                                 firma="Bedachung Hofmann GmbH", gewerk="Dach"))
        s.add(Renovierungsposten(renovierung_id=r.id, betrag=4100.0,
                                 firma="Bedachung Hofmann", gewerk="Dach"))
        s.add(Renovierungsposten(renovierung_id=r.id, betrag=2050.0,
                                 firma="Malerbetrieb Ludwig", gewerk="Maler"))
        s.add(Versicherung(objekt_id=o.id, art="Gebäude", beitrag=480.0,
                           anbieter="WWK Versicherung AG", police_nr="P-4711"))
        s.add(Dokument(pfad=f"/K{n}/beleg.pdf", dateiname="beleg.pdf",
                       objekt_id=o.id, ki_felder={
                           "anbieter": "Stadtwerke Eckental",
                           "kundennummer": "KD-90210"}))
        s.commit()
        return slug, o.id, r.id


def test_ernte_sammelt_aus_allen_quellen():
    with TestClient(app) as c:
        slug, _oid, _rid = _welt(c)
        c.post("/api/kontakte/ernten")
        namen = {k["firma"]: k for k in c.get("/api/kontakte").json()["kontakte"]}
        assert "Bedachung Hofmann GmbH" in namen or "Bedachung Hofmann" in namen
        assert "WWK Versicherung AG" in namen
        assert "Stadtwerke Eckental" in namen
        # Die zwei Schreibweisen des Dachdeckers sind EIN Eintrag.
        dach = [k for k in namen.values() if "Hofmann" in k["firma"]]
        assert len(dach) == 1
        assert dach[0]["gewerk"] == "Dach"
        assert dach[0]["art"] == "Handwerker"
        assert namen["WWK Versicherung AG"]["art"] == "Versicherung"
        assert namen["Stadtwerke Eckental"]["art"] == "Versorger"


def test_kundennummern_kommen_mit_und_haengen_am_objekt():
    with TestClient(app) as c:
        slug, _oid, _rid = _welt(c)
        c.post("/api/kontakte/ernten")
        alle = c.get("/api/kontakte").json()["kontakte"]
        sw = next(k for k in alle if k["firma"] == "Stadtwerke Eckental")
        assert any(n["nummer"] == "KD-90210" and n["art"] == "Kundennummer"
                   for n in sw["nummern"])
        wwk = next(k for k in alle if k["firma"] == "WWK Versicherung AG")
        assert any(n["nummer"] == "P-4711" and n["art"] == "Police"
                   for n in wwk["nummern"])
        # Und die Nummer weiss, zu welcher Immobilie sie gehört.
        assert any(n["objekt"] == slug for n in sw["nummern"])


def test_zweiter_erntelauf_verdoppelt_nichts():
    """Wiederholbar heisst wiederholbar."""
    with TestClient(app) as c:
        _welt(c)
        c.post("/api/kontakte/ernten")
        vorher = c.get("/api/kontakte").json()
        c.post("/api/kontakte/ernten")
        nachher = c.get("/api/kontakte").json()
        assert nachher["anzahl"] == vorher["anzahl"]
        for a, b in zip(vorher["kontakte"], nachher["kontakte"]):
            assert len(a["nummern"]) == len(b["nummern"])


def test_nach_objekt_gefiltert_zeigt_nur_dessen_firmen():
    with TestClient(app) as c:
        slug, _oid, _rid = _welt(c)
        c.post("/api/kontakte/ernten")
        eigene = c.get(f"/api/kontakte?objekt={slug}").json()["kontakte"]
        # Nur wer für diese Immobilie eine Nummer trägt.
        assert eigene
        assert all(any(n["objekt"] == slug for n in k["nummern"])
                   for k in eigene)


# --------------------------------------------------------------------------
# Wer hat in welchem Gewerk gearbeitet
# --------------------------------------------------------------------------

def test_gewerke_je_renovierung():
    """Die Frage des Nutzers: „welche Handwerker in welchen Gewerken tätig
    waren"."""
    with TestClient(app) as c:
        _slug, _oid, rid = _welt(c)
        c.post("/api/kontakte/ernten")
        gewerke = c.get(f"/api/kontakte/gewerke/{rid}").json()["gewerke"]
        nach_name = {g["gewerk"]: g for g in gewerke}
        assert set(nach_name) == {"Dach", "Maler"}
        # Das teuerste Gewerk steht vorn.
        assert gewerke[0]["gewerk"] == "Dach"
        assert nach_name["Dach"]["summe"] == 12300.0
        # Die zwei Schreibweisen desselben Dachdeckers sind EINE Firma.
        assert len(nach_name["Dach"]["firmen"]) == 1
        assert nach_name["Dach"]["firmen"][0]["anzahl"] == 2
        # Und sie verlinkt auf ihren Kontakt.
        assert nach_name["Dach"]["firmen"][0]["kontakt_id"] is not None


def test_unbekannte_renovierung_ergibt_404_statt_500():
    """N436 — vormals eine leere Liste (nicht unterscheidbar von „gibt's,
    aber ohne Gewerke"); eine geratene ID gehört keiner Familie, also 404
    wie überall sonst, statt kein Crash zu sein UND unklar zu bleiben."""
    with TestClient(app) as c:
        assert c.get("/api/kontakte/gewerke/999999").status_code == 404


# --------------------------------------------------------------------------
# Pflegen und Entfernen
# --------------------------------------------------------------------------

def test_nummer_anlegen_und_entfernen():
    with TestClient(app) as c:
        slug, _oid, _rid = _welt(c)
        c.post("/api/kontakte/ernten")
        k = c.get("/api/kontakte").json()["kontakte"][0]
        antwort = c.post(f"/api/kontakte/{k['id']}/nummer",
                         json={"nummer": "V-123", "art": "Vertragsnummer",
                               "objekt": slug})
        assert antwort.status_code == 201
        neu = next(n for n in antwort.json()["nummern"] if n["nummer"] == "V-123")
        assert c.delete(f"/api/kontakte/nummer/{neu['id']}").status_code == 200
        assert not [n for n in c.get(f"/api/kontakte/{k['id']}").json()["nummern"]
                    if n["nummer"] == "V-123"]


def test_leere_nummer_wird_abgewiesen():
    with TestClient(app) as c:
        _welt(c)
        c.post("/api/kontakte/ernten")
        k = c.get("/api/kontakte").json()["kontakte"][0]
        assert c.post(f"/api/kontakte/{k['id']}/nummer",
                      json={"nummer": "   "}).status_code == 400


def test_unbekanntes_meldet_404_statt_500():
    with TestClient(app) as c:
        assert c.get("/api/kontakte/999999").status_code == 404
        assert c.patch("/api/kontakte/999999", json={"firma": "X"}).status_code == 404
        assert c.delete("/api/kontakte/999999").status_code == 404
        assert c.delete("/api/kontakte/nummer/999999").status_code == 404
        assert c.get("/api/kontakte?objekt=gibtsnicht").status_code == 404


def test_kontakt_loeschen_nimmt_seine_nummern_mit():
    with TestClient(app) as c:
        _welt(c)
        c.post("/api/kontakte/ernten")
        k = next(x for x in c.get("/api/kontakte").json()["kontakte"]
                 if x["nummern"])
        assert c.delete(f"/api/kontakte/{k['id']}").status_code == 200
        with Session(engine) as s:
            assert s.get(Kontakt, k["id"]) is None
            assert not s.exec(select(Kundennummer).where(
                Kundennummer.kontakt_id == k["id"])).all()


# --------------------------------------------------------------------------
# Zusammenführen — OCR-Lesefehler werden zu eigenen Firmen
# --------------------------------------------------------------------------

def test_zusammenfuehren_nimmt_nummern_und_leere_felder_mit():
    """Der echte Fall: aus „WWK" las die Texterkennung „WVWK" — zwei Einträge
    mit derselben Police."""
    with TestClient(app) as c:
        with Session(engine) as s:
            fid = _familie_id(s)
            a = Kontakt(schluessel="wwk", firma="WWK Versicherung AG",
                        art="Versicherung", telefon="089 5114-0",
                        handgepflegt=["telefon"], familie_id=fid)
            b = Kontakt(schluessel="wvwk", firma="WVWK Versicherung AG",
                        art="Versicherung", email="info@wwk.de",
                        adresse="München", handgepflegt=[], familie_id=fid)
            s.add(a); s.add(b); s.commit(); s.refresh(a); s.refresh(b)
            s.add(Kundennummer(kontakt_id=b.id, nummer="53139472", art="Police"))
            s.commit()
            aid, bid = a.id, b.id

        antwort = c.post(f"/api/kontakte/{aid}/zusammenfuehren",
                         json={"weg_ids": [bid]})
        assert antwort.status_code == 200, antwort.text
        d = antwort.json()
        assert d["zusammengefuehrt"] == 1
        assert d["nummern_uebernommen"] == 1
        # Leeres wurde gefüllt …
        assert d["email"] == "info@wwk.de"
        assert d["adresse"] == "München"
        # … Gepflegtes blieb.
        assert d["telefon"] == "089 5114-0"
        assert any(n["nummer"] == "53139472" for n in d["nummern"])
        with Session(engine) as s:
            assert s.get(Kontakt, bid) is None


def test_doppelte_nummern_werden_nicht_verdoppelt():
    with TestClient(app) as c:
        with Session(engine) as s:
            fid = _familie_id(s)
            a = Kontakt(schluessel="d-a", firma="A", handgepflegt=[], familie_id=fid)
            b = Kontakt(schluessel="d-b", firma="B", handgepflegt=[], familie_id=fid)
            s.add(a); s.add(b); s.commit(); s.refresh(a); s.refresh(b)
            s.add(Kundennummer(kontakt_id=a.id, nummer="4711", art="Kundennummer"))
            s.add(Kundennummer(kontakt_id=b.id, nummer="4711", art="Kundennummer"))
            s.commit()
            aid, bid = a.id, b.id
        d = c.post(f"/api/kontakte/{aid}/zusammenfuehren",
                   json={"weg_ids": [bid]}).json()
        assert d["nummern_uebernommen"] == 0
        assert len([n for n in d["nummern"] if n["nummer"] == "4711"]) == 1


def test_zusammenfuehren_meldet_saubere_fehler():
    with TestClient(app) as c:
        with Session(engine) as s:
            a = Kontakt(schluessel="f-a", firma="A", handgepflegt=[],
                       familie_id=_familie_id(s))
            s.add(a); s.commit(); s.refresh(a)
            aid = a.id
        assert c.post("/api/kontakte/999999/zusammenfuehren",
                      json={"weg_ids": [aid]}).status_code == 404
        assert c.post(f"/api/kontakte/{aid}/zusammenfuehren",
                      json={"weg_ids": [999999]}).status_code == 404
        # Kein zweiter Kontakt angegeben
        assert c.post(f"/api/kontakte/{aid}/zusammenfuehren",
                      json={"weg_ids": []}).status_code == 400
        assert c.post(f"/api/kontakte/{aid}/zusammenfuehren",
                      json={"weg_ids": [aid]}).status_code == 400
        # Und nach all dem steht A noch da.
        with Session(engine) as s:
            assert s.get(Kontakt, aid) is not None
