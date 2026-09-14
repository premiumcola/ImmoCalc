"""N472 — Zweiter Faktor per Authenticator-App. Wie `test_auth.py`: die
ECHTE Prüfung über `deps.aktuelle_familie`, nicht über den conftest.py-
Override — jeder Testfall entfernt ihn zuerst.
"""
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_zwei_faktor.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

from app import totp  # noqa: E402
from app.auth import MAX_FEHLVERSUCHE, token_hashen  # noqa: E402
from app.db import engine  # noqa: E402
from app.deps import aktuelle_familie  # noqa: E402
from app.main import app  # noqa: E402
from app.models import ZweiFaktorTicket  # noqa: E402

PASSWORT = "sehrsicher123"


def _ohne_override():
    app.dependency_overrides.pop(aktuelle_familie, None)


def _familie(c, name, passwort=PASSWORT) -> int:
    return c.post("/api/auth/registrieren",
                  json={"name": name, "passwort": passwort}).json()["id"]


def _mit_2fa(c, name, passwort=PASSWORT) -> tuple[int, str, list[str]]:
    """Registriert, richtet 2FA ein und bestätigt es. Gibt
    (familie_id, geheimnis, wiederherstellungscodes) zurück."""
    fid = _familie(c, name, passwort)
    ein = c.post("/api/auth/2fa/einrichten", json={"passwort": passwort})
    assert ein.status_code == 200, ein.text
    geheimnis = ein.json()["geheimnis"]
    code = _code(geheimnis)
    bestaetigt = c.post("/api/auth/2fa/bestaetigen", json={"code": code})
    assert bestaetigt.status_code == 200, bestaetigt.text
    return fid, geheimnis, bestaetigt.json()["wiederherstellungscodes"]


def _code(geheimnis: str) -> str:
    # `time.time()` — NICHT `datetime.utcnow().timestamp()`: Letzteres
    # deutet die naiven UTC-Feldwerte als LOKALE Zeit und verschiebt das
    # Ergebnis um die Zeitzonen-Differenz (am Testrechner z. B. 2 Stunden =
    # 240 Zeitfenster daneben) — derselbe Fallstrick, den `totp.code_pruefen`
    # durch die Wahl von `time.time()` als Vorgabe von Haus aus vermeidet.
    return totp._code_fuer(geheimnis, int(time.time() // 30))


# --------------------------------------------------------------------------
# Einrichten / Bestätigen
# --------------------------------------------------------------------------

def test_einrichten_verlangt_das_passwort():
    _ohne_override()
    with TestClient(app) as c:
        _familie(c, "Ohne-Passwort-Kein-2fa")
        antwort = c.post("/api/auth/2fa/einrichten", json={"passwort": "falsch"})
        assert antwort.status_code == 403
        assert c.get("/api/auth/ich").json()["hat_2fa"] is False


def test_bestaetigen_mit_falschem_code_aktiviert_nichts():
    _ohne_override()
    with TestClient(app) as c:
        _familie(c, "Falscher-Erster-Code")
        c.post("/api/auth/2fa/einrichten", json={"passwort": PASSWORT})
        antwort = c.post("/api/auth/2fa/bestaetigen", json={"code": "000000"})
        assert antwort.status_code == 400
        assert c.get("/api/auth/ich").json()["hat_2fa"] is False


def test_bestaetigen_ohne_vorheriges_einrichten_schlaegt_fehl():
    _ohne_override()
    with TestClient(app) as c:
        _familie(c, "Kein-Setup")
        antwort = c.post("/api/auth/2fa/bestaetigen", json={"code": "123456"})
        assert antwort.status_code == 409


def test_geheimnis_erscheint_nirgends_in_familien_liste_oder_ich():
    _ohne_override()
    with TestClient(app) as c:
        fid, geheimnis, _codes = _mit_2fa(c, "Kein-Leck")
        ich = c.get("/api/auth/ich").json()
        assert "totp_geheimnis" not in ich
        assert "totp_wiederherstellung" not in ich
        assert ich["hat_2fa"] is True
        # Der einzige unangemeldete Lesezugriff verrät nicht einmal, WER
        # überhaupt einen zweiten Faktor hat.
        assert "hat_2fa" not in str(c.get("/api/auth/zustand").json())


def test_neues_einrichten_laesst_ein_aktives_geheimnis_unangetastet():
    """Der Fund beim Bauen: ein Gerätewechsel während 2FA schon aktiv ist
    darf das noch funktionierende Geheimnis nicht sofort ersetzen — sonst
    sperrt ein Scan-Fehler beim Einrichten sofort aus, obwohl das alte Gerät
    weiter Codes hätte liefern können."""
    _ohne_override()
    with TestClient(app) as c:
        fid, altes_geheimnis, _codes = _mit_2fa(c, "Geraetewechsel")

        # Neue Einrichtung angestossen, aber NICHT bestätigt.
        c.post("/api/auth/2fa/einrichten", json={"passwort": PASSWORT})

        # Das alte Geheimnis meldet weiterhin an — es wurde nicht ersetzt.
        c.post("/api/auth/logout")
        login = c.post("/api/auth/login", json={"familie_id": fid, "passwort": PASSWORT})
        assert login.status_code == 202
        zweiter = c.post("/api/auth/login/2fa",
                         json={"ticket": login.json()["ticket"],
                               "code": _code(altes_geheimnis)})
        assert zweiter.status_code == 200, zweiter.text


# --------------------------------------------------------------------------
# Login mit zweitem Faktor
# --------------------------------------------------------------------------

def test_login_ohne_2fa_bleibt_einstufig():
    """Gegenprobe: eine Familie ohne 2FA merkt vom neuen Code nichts."""
    _ohne_override()
    with TestClient(app) as c:
        fid = _familie(c, "Kein-2fa")
    with TestClient(app) as frisch:
        antwort = frisch.post("/api/auth/login",
                              json={"familie_id": fid, "passwort": PASSWORT})
        assert antwort.status_code == 200
        assert frisch.get("/api/auth/ich").status_code == 200


def test_login_mit_2fa_verlangt_den_zweiten_schritt():
    _ohne_override()
    with TestClient(app) as c:
        fid, geheimnis, _codes = _mit_2fa(c, "Zweistufig")

    with TestClient(app) as frisch:
        erster = frisch.post("/api/auth/login",
                             json={"familie_id": fid, "passwort": PASSWORT})
        assert erster.status_code == 202
        daten = erster.json()
        assert daten["zwei_faktor_noetig"] is True
        # Nach dem ersten Schritt allein ist man NICHT angemeldet.
        assert frisch.get("/api/auth/ich").status_code == 401

        zweiter = frisch.post("/api/auth/login/2fa",
                              json={"ticket": daten["ticket"], "code": _code(geheimnis)})
        assert zweiter.status_code == 200, zweiter.text
        assert frisch.get("/api/auth/ich").json()["id"] == fid


def test_login_mit_2fa_und_falschem_code_schlaegt_fehl():
    _ohne_override()
    with TestClient(app) as c:
        fid, _geheimnis, _codes = _mit_2fa(c, "Falscher-Zweiter-Code")

    with TestClient(app) as frisch:
        erster = frisch.post("/api/auth/login",
                             json={"familie_id": fid, "passwort": PASSWORT})
        antwort = frisch.post("/api/auth/login/2fa",
                              json={"ticket": erster.json()["ticket"], "code": "000000"})
        assert antwort.status_code == 401
        assert frisch.get("/api/auth/ich").status_code == 401


def test_falscher_zweiter_faktor_zaehlt_als_fehlversuch_und_sperrt():
    """Derselbe Riegel wie beim Passwort — kein zweiter Zähler nötig."""
    _ohne_override()
    with TestClient(app) as c:
        fid, geheimnis, _codes = _mit_2fa(c, "Sperrt-Auch")

    with TestClient(app) as frisch:
        erster = frisch.post("/api/auth/login",
                             json={"familie_id": fid, "passwort": PASSWORT})
        ticket = erster.json()["ticket"]
        for _ in range(MAX_FEHLVERSUCHE):
            frisch.post("/api/auth/login/2fa", json={"ticket": ticket, "code": "000000"})
        # Jetzt gesperrt -- auch der RICHTIGE Code wird abgelehnt.
        gesperrt = frisch.post("/api/auth/login",
                               json={"familie_id": fid, "passwort": PASSWORT})
        assert gesperrt.status_code == 429


def test_abgelaufenes_ticket_verlangt_neuen_login():
    _ohne_override()
    with TestClient(app) as c:
        fid, geheimnis, _codes = _mit_2fa(c, "Ticket-Abgelaufen")

    with TestClient(app) as frisch:
        erster = frisch.post("/api/auth/login",
                             json={"familie_id": fid, "passwort": PASSWORT})
        ticket = erster.json()["ticket"]

        with Session(engine) as s:
            zeile = s.exec(select(ZweiFaktorTicket).where(
                ZweiFaktorTicket.ticket_hash == token_hashen(ticket))).one()
            zeile.laeuft_ab = datetime.utcnow() - timedelta(seconds=1)
            s.add(zeile)
            s.commit()

        antwort = frisch.post("/api/auth/login/2fa",
                              json={"ticket": ticket, "code": _code(geheimnis)})
        assert antwort.status_code == 401


def test_unbekanntes_ticket_wird_abgelehnt():
    _ohne_override()
    with TestClient(app) as c:
        antwort = c.post("/api/auth/login/2fa",
                         json={"ticket": "nieausgestellt", "code": "123456"})
        assert antwort.status_code == 401


# --------------------------------------------------------------------------
# Wiederherstellungscodes
# --------------------------------------------------------------------------

def test_wiederherstellungscode_funktioniert_genau_einmal():
    _ohne_override()
    with TestClient(app) as c:
        fid, _geheimnis, codes = _mit_2fa(c, "Wiederherstellung")

    with TestClient(app) as frisch:
        erster = frisch.post("/api/auth/login",
                             json={"familie_id": fid, "passwort": PASSWORT})
        zweiter = frisch.post("/api/auth/login/2fa",
                              json={"ticket": erster.json()["ticket"], "code": codes[0]})
        assert zweiter.status_code == 200, zweiter.text

    with TestClient(app) as nochmal:
        erster = nochmal.post("/api/auth/login",
                              json={"familie_id": fid, "passwort": PASSWORT})
        zweiter = nochmal.post("/api/auth/login/2fa",
                               json={"ticket": erster.json()["ticket"], "code": codes[0]})
        assert zweiter.status_code == 401, "derselbe Code darf kein zweites Mal gelten"


def test_wiederherstellungscodes_neu_erzeugen_macht_die_alten_ungueltig():
    _ohne_override()
    with TestClient(app) as c:
        fid, _geheimnis, alte_codes = _mit_2fa(c, "Codes-Erneuert")
        neu = c.post("/api/auth/2fa/wiederherstellungscodes-neu",
                    json={"passwort": PASSWORT})
        assert neu.status_code == 200
        neue_codes = neu.json()["wiederherstellungscodes"]
        assert neue_codes != alte_codes

    with TestClient(app) as frisch:
        erster = frisch.post("/api/auth/login",
                             json={"familie_id": fid, "passwort": PASSWORT})
        alt = frisch.post("/api/auth/login/2fa",
                          json={"ticket": erster.json()["ticket"], "code": alte_codes[0]})
        assert alt.status_code == 401


# --------------------------------------------------------------------------
# Deaktivieren
# --------------------------------------------------------------------------

def test_deaktivieren_verlangt_das_passwort():
    _ohne_override()
    with TestClient(app) as c:
        fid, _geheimnis, _codes = _mit_2fa(c, "Deaktivieren-Falsch")
        antwort = c.post("/api/auth/2fa/deaktivieren", json={"passwort": "falsch"})
        assert antwort.status_code == 403
        assert c.get("/api/auth/ich").json()["hat_2fa"] is True


def test_deaktivieren_macht_den_login_wieder_einstufig():
    _ohne_override()
    with TestClient(app) as c:
        fid, _geheimnis, _codes = _mit_2fa(c, "Deaktivieren-Ok")
        assert c.post("/api/auth/2fa/deaktivieren",
                      json={"passwort": PASSWORT}).status_code == 204
        assert c.get("/api/auth/ich").json()["hat_2fa"] is False

    with TestClient(app) as frisch:
        antwort = frisch.post("/api/auth/login",
                              json={"familie_id": fid, "passwort": PASSWORT})
        assert antwort.status_code == 200


# --------------------------------------------------------------------------
# Mandantentrennung
# --------------------------------------------------------------------------

def test_2fa_der_einen_familie_beeinflusst_die_andere_nicht():
    _ohne_override()
    with TestClient(app) as a, TestClient(app) as b:
        a.post("/api/auth/registrieren", json={"name": "2fa-A", "passwort": PASSWORT})
        fid_b, _geheimnis, _codes = _mit_2fa(b, "2fa-B")

        # A meldet sich weiterhin einstufig an.
        assert a.get("/api/auth/ich").json()["hat_2fa"] is False

    with TestClient(app) as a_frisch:
        antwort = a_frisch.post("/api/auth/login",
                                json={"familie_id": fid_b, "passwort": PASSWORT})
        # B braucht den zweiten Schritt -- auch wenn A es versucht.
        assert antwort.status_code == 202
