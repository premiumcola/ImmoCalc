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
