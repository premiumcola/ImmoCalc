"""N501 — E-Mail am Familienzugang, letzter Login, Administratorkonto.

Stil wie `test_auth.py`: `_ohne_override()`, echter `TestClient`, deutsche
Satz-Testnamen.
"""
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import konten
from app.db import engine
from app.main import app
from app.models import Familie

PW = "ein-langes-passwort"


# ---- N501 — Rüstzeug ---------------------------------------------------

def _ohne_override():
    """Der Anmelde-Bypass aus conftest.py muss hier weg — geprüft wird ja
    genau die Anmeldung."""
    from app.deps import aktuelle_familie
    gemerkt = app.dependency_overrides.pop(aktuelle_familie, None)
    return gemerkt


@pytest.fixture
def klient():
    gemerkt = _ohne_override()
    with TestClient(app) as c:
        yield c
    if gemerkt:
        from app.deps import aktuelle_familie
        app.dependency_overrides[aktuelle_familie] = gemerkt


def _familie_anlegen(klient: TestClient, name: str) -> dict:
    antwort = klient.post("/api/auth/registrieren",
                          json={"name": name, "passwort": PW})
    assert antwort.status_code == 201, antwort.text
    return antwort.json()


def _email_setzen(klient: TestClient, email: str):
    return klient.post("/api/auth/email", json={"email": email, "passwort": PW})


# ---- N501 — die Adresse selbst ----------------------------------------

@pytest.mark.parametrize("roh,erwartet", [
    ("  R.Oman@GMX.de ", "r.oman@gmx.de"),
    ("a@b.de", "a@b.de"),
    ("", None),
    ("   ", None),
    (None, None),
])
def test_adressen_werden_einheitlich_geschrieben(roh, erwartet):
    assert konten.email_normalisieren(roh) == erwartet


@pytest.mark.parametrize("email", [
    "roman@gmx.de", "a.b+c@sub.example.co.uk", "x@y.io",
])
def test_brauchbare_adressen_gehen_durch(email):
    assert konten.email_gueltig(email)


@pytest.mark.parametrize("email", [
    None, "", "roman", "roman@", "@gmx.de", "roman@gmx", "zwei@@gmx.de",
    "mit leer@gmx.de", "a" * 250 + "@gmx.de",
])
def test_offensichtlich_kaputte_adressen_fallen_auf(email):
    assert not konten.email_gueltig(email)


# ---- N501 — Adresse am Zugang -----------------------------------------

def test_die_eigene_adresse_laesst_sich_setzen(klient):
    _familie_anlegen(klient, "Adresse-Setzen")
    antwort = _email_setzen(klient, "  Chef@Haus.DE ")
    assert antwort.status_code == 200, antwort.text
    assert antwort.json()["email"] == "chef@haus.de"


def test_ohne_passwort_keine_neue_adresse(klient):
    _familie_anlegen(klient, "Adresse-Ohne-Passwort")
    antwort = klient.post("/api/auth/email",
                          json={"email": "neu@haus.de", "passwort": "falsch"})
    assert antwort.status_code == 403


def test_kaputte_adresse_wird_abgelehnt(klient):
    _familie_anlegen(klient, "Adresse-Kaputt")
    assert _email_setzen(klient, "kein-at-zeichen").status_code == 400


def test_dieselbe_adresse_nicht_zweimal(klient):
    _familie_anlegen(klient, "Adresse-Erste")
    assert _email_setzen(klient, "geteilt@haus.de").status_code == 200
    klient.post("/api/auth/logout")
    _familie_anlegen(klient, "Adresse-Zweite")
    antwort = _email_setzen(klient, "GETEILT@haus.de")
    assert antwort.status_code == 409, antwort.text


def test_die_eigene_adresse_darf_man_erneut_setzen(klient):
    """Sonst liefe jedes Speichern ohne Änderung in den Eindeutigkeitsriegel."""
    _familie_anlegen(klient, "Adresse-Nochmal")
    assert _email_setzen(klient, "gleich@haus.de").status_code == 200
    assert _email_setzen(klient, "gleich@haus.de").status_code == 200


# ---- N501 — Anmeldung mit Adresse -------------------------------------

def test_ohne_hinterlegte_adresse_meldet_man_sich_weiter_ohne_an(klient):
    """Der Bestand darf durch die Erweiterung nicht ausgesperrt werden."""
    _familie_anlegen(klient, "Bestand-Ohne-Adresse")
    klient.post("/api/auth/logout")
    antwort = klient.post("/api/auth/login",
                          json={"name": "Bestand-Ohne-Adresse", "passwort": PW})
    assert antwort.status_code == 200, antwort.text


def test_mit_hinterlegter_adresse_gehoert_sie_zur_anmeldung(klient):
    _familie_anlegen(klient, "Mit-Adresse")
    _email_setzen(klient, "mit@haus.de")
    klient.post("/api/auth/logout")

    ohne = klient.post("/api/auth/login",
                       json={"name": "Mit-Adresse", "passwort": PW})
    assert ohne.status_code == 401

    falsch = klient.post("/api/auth/login", json={
        "name": "Mit-Adresse", "email": "andere@haus.de", "passwort": PW})
    assert falsch.status_code == 401

    richtig = klient.post("/api/auth/login", json={
        "name": "Mit-Adresse", "email": "MIT@haus.de", "passwort": PW})
    assert richtig.status_code == 200, richtig.text


def test_falsche_adresse_klingt_wie_falsches_passwort(klient):
    """N469 #2 — von aussen darf nicht unterscheidbar sein, WELCHE der beiden
    Angaben nicht stimmt."""
    _familie_anlegen(klient, "Gleiche-Meldung")
    _email_setzen(klient, "gleich-meldung@haus.de")
    klient.post("/api/auth/logout")

    a = klient.post("/api/auth/login", json={
        "name": "Gleiche-Meldung", "email": "falsch@haus.de", "passwort": PW})
    b = klient.post("/api/auth/login", json={
        "name": "Gleiche-Meldung", "email": "gleich-meldung@haus.de",
        "passwort": "falsches-langes-passwort"})
    assert a.status_code == b.status_code == 401
    assert a.json()["detail"] == b.json()["detail"]


def test_falsche_adresse_zaehlt_als_fehlversuch(klient):
    """Sonst liesse sich die Adresse unbegrenzt durchprobieren, während das
    Passwort gesperrt wird."""
    from app.auth import MAX_FEHLVERSUCHE
    _familie_anlegen(klient, "Adresse-Fehlversuche")
    _email_setzen(klient, "zaehler@haus.de")
    klient.post("/api/auth/logout")

    for _ in range(MAX_FEHLVERSUCHE):
        klient.post("/api/auth/login", json={
            "name": "Adresse-Fehlversuche", "email": "falsch@haus.de",
            "passwort": PW})
    gesperrt = klient.post("/api/auth/login", json={
        "name": "Adresse-Fehlversuche", "email": "zaehler@haus.de",
        "passwort": PW})
    assert gesperrt.status_code == 429


# ---- N501 — letzter Login ---------------------------------------------

def test_erfolgreiche_anmeldung_merkt_sich_den_zeitpunkt(klient):
    _familie_anlegen(klient, "Letzter-Login")
    with Session(engine) as s:
        f = s.exec(select(Familie).where(Familie.name == "Letzter-Login")).one()
        assert f.letzter_login is not None
        vorher = f.letzter_login

    klient.post("/api/auth/logout")
    assert klient.post("/api/auth/login", json={
        "name": "Letzter-Login", "passwort": PW}).status_code == 200

    with Session(engine) as s:
        f = s.exec(select(Familie).where(Familie.name == "Letzter-Login")).one()
        assert f.letzter_login >= vorher


def test_gescheiterte_anmeldung_gilt_nicht_als_aktivitaet(klient):
    _familie_anlegen(klient, "Kein-Login")
    klient.post("/api/auth/logout")
    with Session(engine) as s:
        f = s.exec(select(Familie).where(Familie.name == "Kein-Login")).one()
        vorher = f.letzter_login

    klient.post("/api/auth/login",
                json={"name": "Kein-Login", "passwort": "falsches-passwort-xy"})

    with Session(engine) as s:
        f = s.exec(select(Familie).where(Familie.name == "Kein-Login")).one()
        assert f.letzter_login == vorher


# ---- N501 — Administratorkonto ----------------------------------------

def test_ohne_angabe_wird_die_zuerst_angelegte_familie_administrator(klient, monkeypatch):
    monkeypatch.delenv("ADMIN_FAMILIE", raising=False)
    with Session(engine) as s:
        for f in s.exec(select(Familie)).all():
            f.ist_admin = False
            s.add(f)
        s.commit()
        erste = s.exec(select(Familie).order_by(Familie.id)).first()
        assert erste is not None
        name = erste.name

        assert konten.admin_sicherstellen(s).name == name


def test_admin_familie_aus_der_umgebung_gewinnt(klient, monkeypatch):
    """Bewusst NICHT die zuerst angelegte Familie — sonst bewiese der Test
    nichts, weil die auch ohne Umgebungsvariable gewänne."""
    _familie_anlegen(klient, "Spaeter-Admin")
    with Session(engine) as s:
        for f in s.exec(select(Familie)).all():
            f.ist_admin = False
            s.add(f)
        s.commit()
        erste = s.exec(select(Familie).order_by(Familie.id)).first()
        assert erste.name != "Spaeter-Admin"          # sonst ist der Test blind

        monkeypatch.setenv("ADMIN_FAMILIE", "spaeter-admin")
        assert konten.admin_sicherstellen(s).name == "Spaeter-Admin"


def test_ein_vorhandener_administrator_wird_nicht_still_umgehaengt(klient, monkeypatch):
    """Sonst verlöre ein Betreiber seine Verwaltung, weil jemand eine
    Umgebungsvariable ändert."""
    _familie_anlegen(klient, "Bleibt-Admin")
    with Session(engine) as s:
        for f in s.exec(select(Familie)).all():
            f.ist_admin = f.name == "Bleibt-Admin"
            s.add(f)
        s.commit()
        monkeypatch.setenv("ADMIN_FAMILIE", "irgendwer-anders")
        assert konten.admin_sicherstellen(s).name == "Bleibt-Admin"


def test_ich_verraet_ob_der_zugang_verwalten_darf(klient):
    daten = _familie_anlegen(klient, "Darf-Verwalten")
    assert "ist_admin" in daten
    antwort = klient.get("/api/auth/ich")
    assert antwort.status_code == 200
    assert set(antwort.json()) >= {"email", "ist_admin", "hat_2fa"}


def test_das_geheimnis_steht_in_keiner_antwort(klient):
    """Wächter: `_familie_oeffentlich` ist um zwei Felder gewachsen — dabei
    darf nichts Geheimes mitgerutscht sein."""
    _familie_anlegen(klient, "Nichts-Geheimes")
    text = klient.get("/api/auth/ich").text
    for verboten in ("totp_geheimnis", "passwort_hash", "passwort_salz",
                     "backup_schluessel", "wiederherstellung"):
        assert verboten not in text
