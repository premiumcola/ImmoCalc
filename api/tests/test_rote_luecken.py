"""Die vier vom Nutzer freigegebenen „roten" Modell-Lücken (CCXXIX–CCXXXV):

* CCXXIX  Grundschuld als dingliche Sicherheit, objektübergreifend
* CCXXX   variabler Anschlusszins nach Ende der Zinsbindung
* CCXXXI  echte Sollzinsen je Jahr aus dem Kontoauszug
* CCXXXV  Erwerbsart (Kauf/Erbschaft/…) und Nießbrauch am Objekt

Alle Felder sind additiv — die Bestandsprüfung liegt in test_besitz/test_migration.
"""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_rote_luecken.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def _objekt(c, name, **felder):
    return c.post("/api/objekte", json={"name": name, "ort": "Musterstadt",
                                        **felder}).json()["slug"]


def _kredit(c, slug, **felder):
    daten = {"bezeichnung": "Darlehen", "restschuld": 200000.0,
             "zinssatz": 2.0, "rate_monatlich": 1000.0, "turnus": "monatlich"}
    daten.update(felder)
    c.post(f"/api/objekte/{slug}/kredite", json=daten)
    return c.get(f"/api/objekte/{slug}/kredite").json()[-1]["id"]


def _verlauf(c, kid):
    return {z["jahr"]: z for z in c.get(f"/api/kredite/{kid}/staende").json()["verlauf"]}


# ---------------------------------------------------------------- CCXXX -----

def test_variabler_zins_greift_erst_nach_der_zinsbindung():
    """Bis zum Bindungsende rechnen fester und variabler Kredit gleich; danach
    treibt der höhere Anschlusszins die Restschuld über die des festen."""
    with TestClient(app) as c:
        slug = _objekt(c, "Zinsweg 1", verkehrswert=500000.0)
        fest = _kredit(c, slug, bezeichnung="Fest")
        var = _kredit(c, slug, bezeichnung="Variabel",
                      zinsbindung_bis="2022-12-31", zinssatz_variabel=6.0)
        for kid in (fest, var):
            c.post(f"/api/kredite/{kid}/staende",
                   json={"jahr": 2020, "restschuld": 200000.0})

        vf, vv = _verlauf(c, fest), _verlauf(c, var)
        # Innerhalb der Bindung (2021): identisch
        assert vf[2021]["restschuld"] == vv[2021]["restschuld"]
        # Nach der Bindung (2026): der variable, höhere Zins lässt weniger tilgen
        assert vv[2026]["restschuld"] > vf[2026]["restschuld"]


def test_ohne_variablen_zins_bleibt_alles_beim_alten():
    """Kein `zinssatz_variabel` → exakt die bisherige Fortschreibung."""
    with TestClient(app) as c:
        slug = _objekt(c, "Zinsweg 2")
        kid = _kredit(c, slug)
        c.post(f"/api/kredite/{kid}/staende",
               json={"jahr": 2020, "restschuld": 200000.0})
        # Referenz: rein feste 2 % über 12 Monate ab 2020
        from app.vermoegen import stand_fortschreiben
        erwartet = stand_fortschreiben(200000.0, 1000.0, 2.0, 12)
        assert _verlauf(c, kid)[2021]["restschuld"] == erwartet


# --------------------------------------------------------------- CCXXXI -----

def test_echte_zinsen_stehen_neben_den_kalkulierten():
    with TestClient(app) as c:
        slug = _objekt(c, "Kontoweg 3")
        kid = _kredit(c, slug)
        c.post(f"/api/kredite/{kid}/staende",
               json={"jahr": 2020, "restschuld": 200000.0, "zinsen_ist": 3980.0})
        c.post(f"/api/kredite/{kid}/staende",
               json={"jahr": 2021, "restschuld": 190000.0, "zinsen_ist": 3780.0})

        verlauf = _verlauf(c, kid)
        assert verlauf[2020]["zinsen_ist"] == 3980.0
        assert verlauf[2021]["zinsen_ist"] == 3780.0
        # Für ein eingetragenes Folgejahr steht die Kalkulation daneben
        assert verlauf[2021]["zinsen_kalk"] is not None
        assert verlauf[2021]["zinsen_kalk"] > 0


def test_zinsen_ist_ist_optional():
    """Ein Stand ohne Kontoauszug bleibt gültig, zinsen_ist bleibt leer."""
    with TestClient(app) as c:
        slug = _objekt(c, "Kontoweg 4")
        kid = _kredit(c, slug)
        c.post(f"/api/kredite/{kid}/staende",
               json={"jahr": 2021, "restschuld": 200000.0})
        assert _verlauf(c, kid)[2021]["zinsen_ist"] is None


# --------------------------------------------------------------- CCXXIX -----

def test_grundschuld_sichert_kredit_am_anderen_objekt():
    """Cross-Collateral: eine Grundschuld auf Objekt A sichert das Darlehen für
    Objekt B."""
    with TestClient(app) as c:
        haus_a = _objekt(c, "Sicherungsweg A")
        haus_b = _objekt(c, "Finanzierungsweg B")
        kredit_b = _kredit(c, haus_b, bezeichnung="Darlehen B")

        # Auswahl bietet Kredite über alle Objekte an
        auswahl = c.get("/api/grundschulden/kredit-auswahl").json()
        assert any(k["id"] == kredit_b for k in auswahl)

        g = c.post(f"/api/objekte/{haus_a}/grundschulden", json={
            "betrag": 150000.0, "rang": "I", "grundbuch_blatt": "1234",
            "glaeubiger": "Sparkasse", "kredit_ids": [kredit_b]}).json()
        assert g["kredit_ids"] == [kredit_b]

        liste = c.get(f"/api/objekte/{haus_a}/grundschulden").json()
        assert len(liste) == 1
        assert liste[0]["betrag"] == 150000.0
        assert liste[0]["kredit_ids"] == [kredit_b]


def test_grundschuld_aendern_und_loeschen():
    with TestClient(app) as c:
        slug = _objekt(c, "Grundschuldweg 5")
        kid = _kredit(c, slug)
        gid = c.post(f"/api/objekte/{slug}/grundschulden",
                     json={"betrag": 100000.0, "kredit_ids": [kid]}).json()["id"]

        geaendert = c.patch(f"/api/grundschulden/{gid}",
                            json={"betrag": 120000.0, "kredit_ids": []}).json()
        assert geaendert["betrag"] == 120000.0
        assert geaendert["kredit_ids"] == []          # Verknüpfung gelöst

        assert c.delete(f"/api/grundschulden/{gid}").json()["ok"] is True
        assert c.get(f"/api/objekte/{slug}/grundschulden").json() == []


def test_grundschuld_betrag_nie_negativ():
    with TestClient(app) as c:
        slug = _objekt(c, "Grundschuldweg 6")
        antwort = c.post(f"/api/objekte/{slug}/grundschulden",
                         json={"betrag": -5.0})
        assert antwort.status_code == 400


# --------------------------------------------------------------- CCXXXV -----

def test_erwerbsart_und_niessbrauch_am_objekt():
    with TestClient(app) as c:
        slug = _objekt(c, "Erbweg 7")
        c.patch(f"/api/objekte/{slug}", json={
            "erwerbsart": "Erbschaft", "afa_basis_uebernommen": 180000.0,
            "niessbrauch_berechtigt": "Mutter", "niessbrauch_bis": "2035-12-31"})

        o = c.get(f"/api/objekte/{slug}").json()["objekt"]
        assert o["erwerbsart"] == "Erbschaft"
        assert o["afa_basis_uebernommen"] == 180000.0
        assert o["niessbrauch_berechtigt"] == "Mutter"
        assert str(o["niessbrauch_bis"]).startswith("2035-12-31")


def test_erwerbsart_vorgabe_ist_kauf():
    with TestClient(app) as c:
        slug = _objekt(c, "Kaufweg 8")
        assert c.get(f"/api/objekte/{slug}").json()["objekt"]["erwerbsart"] == "Kauf"
