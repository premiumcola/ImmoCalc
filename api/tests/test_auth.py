"""N436 — Login/Sitzung/Sperre: die ECHTE Prüfung über `deps.aktuelle_familie`,
nicht über den conftest.py-Override, der für praktisch alle anderen ~1700
Tests bewusst abkürzt (siehe `_test_familie`/`eigene_datenbank` dort). Jeder
Testfall hier entfernt den Override zuerst — sonst würde jede Anfrage
unabhängig vom Cookie sofort als "Heidenreich" durchgehen.
"""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_auth.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402

from app.auth import MAX_FEHLVERSUCHE  # noqa: E402
from app.deps import aktuelle_familie  # noqa: E402
from app.main import app  # noqa: E402


def _ohne_override():
    app.dependency_overrides.pop(aktuelle_familie, None)


def test_ich_ohne_cookie_ist_401():
    _ohne_override()
    with TestClient(app) as c:
        assert c.get("/api/auth/ich").status_code == 401


def test_registrieren_setzt_cookie_und_ich_zeigt_die_neue_familie():
    _ohne_override()
    with TestClient(app) as c:
        antwort = c.post("/api/auth/registrieren",
                         json={"name": "Kumpelfamilie", "passwort": "sehrsicher123"})
        assert antwort.status_code == 201
        daten = antwort.json()
        assert daten["name"] == "Kumpelfamilie"
        assert daten["hat_passwort"] is True

        ich = c.get("/api/auth/ich")
        assert ich.status_code == 200
        assert ich.json()["name"] == "Kumpelfamilie"


def test_registrieren_mit_kurzem_passwort_schlaegt_fehl():
    _ohne_override()
    with TestClient(app) as c:
        antwort = c.post("/api/auth/registrieren",
                         json={"name": "Zukurz", "passwort": "123"})
        assert antwort.status_code == 400


def test_registrieren_doppelter_name_schlaegt_fehl():
    _ohne_override()
    with TestClient(app) as c:
        c.post("/api/auth/registrieren",
              json={"name": "Doppelt", "passwort": "sehrsicher123"})
        antwort = c.post("/api/auth/registrieren",
                         json={"name": "Doppelt", "passwort": "andereszeug99"})
        assert antwort.status_code == 409


def test_login_mit_falschem_passwort_schlaegt_fehl():
    _ohne_override()
    with TestClient(app) as c:
        reg = c.post("/api/auth/registrieren",
                     json={"name": "Login-Falsch", "passwort": "sehrsicher123"})
        fid = reg.json()["id"]

    with TestClient(app) as frisch:                    # neuer Client: kein Cookie
        antwort = frisch.post("/api/auth/login",
                              json={"familie_id": fid, "passwort": "falsch"})
        assert antwort.status_code == 401
        assert frisch.get("/api/auth/ich").status_code == 401


def test_login_mit_richtigem_passwort_meldet_an():
    _ohne_override()
    with TestClient(app) as c:
        reg = c.post("/api/auth/registrieren",
                     json={"name": "Login-Ok", "passwort": "sehrsicher123"})
        fid = reg.json()["id"]

    with TestClient(app) as frisch:
        antwort = frisch.post("/api/auth/login",
                              json={"familie_id": fid, "passwort": "sehrsicher123"})
        assert antwort.status_code == 200
        ich = frisch.get("/api/auth/ich")
        assert ich.status_code == 200
        assert ich.json()["id"] == fid


def test_logout_beendet_die_sitzung_serverseitig():
    _ohne_override()
    with TestClient(app) as c:
        c.post("/api/auth/registrieren",
              json={"name": "Logout-Test", "passwort": "sehrsicher123"})
        assert c.get("/api/auth/ich").status_code == 200

        aus = c.post("/api/auth/logout")
        assert aus.status_code == 204
        # Dasselbe (jetzt geloeschte) Cookie darf nicht weiter gelten.
        assert c.get("/api/auth/ich").status_code == 401


def test_sperre_nach_zu_vielen_fehlversuchen():
    _ohne_override()
    with TestClient(app) as c:
        reg = c.post("/api/auth/registrieren",
                     json={"name": "Sperr-Test", "passwort": "sehrsicher123"})
        fid = reg.json()["id"]

    with TestClient(app) as frisch:
        for _ in range(MAX_FEHLVERSUCHE):
            frisch.post("/api/auth/login", json={"familie_id": fid, "passwort": "falsch"})
        # jetzt gesperrt -- auch das RICHTIGE Passwort wird abgelehnt
        gesperrt = frisch.post("/api/auth/login",
                               json={"familie_id": fid, "passwort": "sehrsicher123"})
        assert gesperrt.status_code == 429


def test_passwort_festlegen_nur_solange_noch_keins_gesetzt_ist():
    """Der Erstanmeldungs-Flow der per Migration angelegten Bestandsfamilie
    "Heidenreich" (passwort_hash=None, siehe test_familie_backfill.py)."""
    _ohne_override()
    with TestClient(app) as c:
        familien = c.get("/api/auth/familien").json()
        heidenreich = next(f for f in familien if f["name"] == "Heidenreich")
        assert heidenreich["hat_passwort"] is False

        antwort = c.post("/api/auth/passwort-festlegen",
                         json={"familie_id": heidenreich["id"], "passwort": "sehrsicher123"})
        assert antwort.status_code == 200

    with TestClient(app) as frisch:
        nochmal = frisch.post("/api/auth/passwort-festlegen",
                              json={"familie_id": heidenreich["id"],
                                    "passwort": "andereszeug99"})
        assert nochmal.status_code == 409
        # Ab jetzt normaler Login mit dem gerade gesetzten Passwort.
        login = frisch.post("/api/auth/login",
                            json={"familie_id": heidenreich["id"],
                                  "passwort": "sehrsicher123"})
        assert login.status_code == 200


def test_familien_liste_liefert_nie_den_passwort_hash():
    _ohne_override()
    with TestClient(app) as c:
        c.post("/api/auth/registrieren",
              json={"name": "Kein-Hash-Leck", "passwort": "sehrsicher123"})
        for f in c.get("/api/auth/familien").json():
            assert "passwort_hash" not in f
            assert "passwort_salz" not in f



def test_cookie_secure_flag_folgt_der_umgebung(monkeypatch):
    """N436 — im VPN läuft die App über einfaches HTTP: mit `secure` käme das
    Cookie dort nie an, und niemand könnte sich anmelden. Der Schalter
    existiert für den Tag, an dem TLS davorsteht — er muss dann aber auch
    wirklich wirken, sonst ist er eine Zusicherung auf dem Papier."""
    _ohne_override()
    monkeypatch.delenv("COOKIE_SECURE", raising=False)
    with TestClient(app) as c:
        antwort = c.post("/api/auth/registrieren",
                         json={"name": "OhneTLS", "passwort": "sehrsicher123"})
        assert "Secure" not in antwort.headers["set-cookie"]

    monkeypatch.setenv("COOKIE_SECURE", "true")
    with TestClient(app) as c:
        antwort = c.post("/api/auth/registrieren",
                         json={"name": "MitTLS", "passwort": "sehrsicher123"})
        assert "Secure" in antwort.headers["set-cookie"]


# --------------------------------------------------------------------------
# N442 — Passwort ändern
# --------------------------------------------------------------------------

def _familie_mit_passwort(c, name, passwort="sehrsicher123"):
    c.post("/api/auth/registrieren", json={"name": name, "passwort": passwort})


def test_passwort_aendern_verlangt_das_bisherige():
    _ohne_override()
    with TestClient(app) as c:
        _familie_mit_passwort(c, "Wechsler")
        antwort = c.post("/api/auth/passwort-aendern", json={
            "alt": "falschfalsch", "neu": "ganzneuespw1",
            "neu_wiederholung": "ganzneuespw1"})
        assert antwort.status_code == 403
        # Das alte gilt weiter.
        assert c.get("/api/auth/ich").status_code == 200


def test_passwort_aendern_verlangt_zwei_gleiche_eingaben():
    _ohne_override()
    with TestClient(app) as c:
        _familie_mit_passwort(c, "Vertipper")
        antwort = c.post("/api/auth/passwort-aendern", json={
            "alt": "sehrsicher123", "neu": "ganzneuespw1",
            "neu_wiederholung": "ganzneuespw2"})
        assert antwort.status_code == 400
        assert "gleich" in antwort.json()["detail"].lower()


def test_passwort_aendern_verlangt_mindestlaenge():
    _ohne_override()
    with TestClient(app) as c:
        _familie_mit_passwort(c, "Zukurzneu")
        antwort = c.post("/api/auth/passwort-aendern", json={
            "alt": "sehrsicher123", "neu": "kurz", "neu_wiederholung": "kurz"})
        assert antwort.status_code == 400


def test_passwort_aendern_wirkt_und_das_alte_gilt_nicht_mehr():
    _ohne_override()
    with TestClient(app) as c:
        _familie_mit_passwort(c, "Erfolgreich")
        fid = c.get("/api/auth/ich").json()["id"]
        assert c.post("/api/auth/passwort-aendern", json={
            "alt": "sehrsicher123", "neu": "ganzneuespw1",
            "neu_wiederholung": "ganzneuespw1"}).status_code == 200
        # Angemeldet bleibt man — die eigene Sitzung wird erneuert.
        assert c.get("/api/auth/ich").status_code == 200

    with TestClient(app) as frisch:
        assert frisch.post("/api/auth/login", json={
            "familie_id": fid, "passwort": "sehrsicher123"}).status_code == 401
        assert frisch.post("/api/auth/login", json={
            "familie_id": fid, "passwort": "ganzneuespw1"}).status_code == 200


def test_passwort_aendern_wirft_fremde_sitzungen_raus():
    """Ein anderswo mitgenommenes Cookie darf danach nicht weitergelten."""
    _ohne_override()
    with TestClient(app) as c, TestClient(app) as zweitgeraet:
        _familie_mit_passwort(c, "Zweigeraete")
        fid = c.get("/api/auth/ich").json()["id"]
        zweitgeraet.post("/api/auth/login",
                         json={"familie_id": fid, "passwort": "sehrsicher123"})
        assert zweitgeraet.get("/api/auth/ich").status_code == 200

        c.post("/api/auth/passwort-aendern", json={
            "alt": "sehrsicher123", "neu": "ganzneuespw1",
            "neu_wiederholung": "ganzneuespw1"})
        assert zweitgeraet.get("/api/auth/ich").status_code == 401


# --------------------------------------------------------------------------
# N444 — Familienlogo
# --------------------------------------------------------------------------

def _bild(breite=900, hoehe=400) -> str:
    """Ein Querformat-Bild als Data-URL — muss quadratisch werden."""
    import base64
    import io

    from PIL import Image

    puffer = io.BytesIO()
    Image.new("RGBA", (breite, hoehe), (10, 120, 90, 255)).save(
        puffer, format="PNG")
    return ("data:image/png;base64,"
            + base64.b64encode(puffer.getvalue()).decode("ascii"))


def test_logo_wird_quadratisch_gespeichert_und_ausgeliefert():
    _ohne_override()
    with TestClient(app) as c:
        c.post("/api/auth/registrieren",
              json={"name": "Luther", "passwort": "sehrsicher123"})
        assert c.get("/api/auth/ich").json()["logo_pfad"] is None

        antwort = c.put("/api/auth/logo", json={"logo": _bild()})
        assert antwort.status_code == 200, antwort.text
        pfad = c.get("/api/auth/ich").json()["logo_pfad"]
        assert pfad.startswith("data:image/png;base64,")

        import base64
        import io

        from PIL import Image
        bild = Image.open(io.BytesIO(base64.b64decode(pfad.split(",", 1)[1])))
        assert bild.width == bild.height, "die Kachel ist quadratisch"
        assert bild.width <= 256

        # Der Anmeldescreen zeigt es — er liest dieselbe Liste.
        eintrag = next(f for f in c.get("/api/auth/familien").json()
                       if f["name"] == "Luther")
        assert eintrag["logo_pfad"] == pfad


def test_logo_entfernen_geht_zurueck_auf_kein_logo():
    _ohne_override()
    with TestClient(app) as c:
        c.post("/api/auth/registrieren",
              json={"name": "Ohnelogo", "passwort": "sehrsicher123"})
        c.put("/api/auth/logo", json={"logo": _bild(300, 300)})
        assert c.delete("/api/auth/logo").status_code == 204
        assert c.get("/api/auth/ich").json()["logo_pfad"] is None


def test_kaputtes_logo_wird_abgelehnt():
    _ohne_override()
    import base64
    with TestClient(app) as c:
        c.post("/api/auth/registrieren",
              json={"name": "Kaputt", "passwort": "sehrsicher123"})
        murks = base64.b64encode(b"kein bild").decode("ascii")
        antwort = c.put("/api/auth/logo",
                        json={"logo": f"data:image/png;base64,{murks}"})
        assert antwort.status_code == 400
        assert c.get("/api/auth/ich").json()["logo_pfad"] is None


def test_ein_logo_gehoert_nur_der_eigenen_familie():
    """Gegenprobe zur Mandantentrennung: B darf A kein Logo verpassen."""
    _ohne_override()
    with TestClient(app) as a, TestClient(app) as b:
        a.post("/api/auth/registrieren",
              json={"name": "LogoA", "passwort": "sehrsicher123"})
        b.post("/api/auth/registrieren",
              json={"name": "LogoB", "passwort": "auchsicher456"})
        b.put("/api/auth/logo", json={"logo": _bild(300, 300)})
        assert a.get("/api/auth/ich").json()["logo_pfad"] is None
