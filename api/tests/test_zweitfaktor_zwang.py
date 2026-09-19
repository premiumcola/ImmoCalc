"""N502 — ohne bestätigten zweiten Faktor entsteht nichts Neues.

Nutzer: „bitte lass die User am besten gar nichts anlegen, bevor nicht
Zwei-Faktor-Anmeldung eben aktiviert ist."

Geprüft wird der Riegel an `deps.aktuelle_familie` — also der eine Punkt, den
jeder geschützte Endpunkt durchläuft. Stil wie `test_zwei_faktor.py`.
"""
import pytest
from fastapi.testclient import TestClient

from app import totp
from app.main import app

PW = "ein-langes-passwort"


def _ohne_override():
    from app.deps import aktuelle_familie
    return app.dependency_overrides.pop(aktuelle_familie, None)


@pytest.fixture
def klient():
    gemerkt = _ohne_override()
    with TestClient(app) as c:
        yield c
    if gemerkt:
        from app.deps import aktuelle_familie
        app.dependency_overrides[aktuelle_familie] = gemerkt


def _anmelden(klient: TestClient, name: str) -> None:
    antwort = klient.post("/api/auth/registrieren",
                          json={"name": name, "passwort": PW})
    assert antwort.status_code == 201, antwort.text


def _zweifaktor_einschalten(klient: TestClient) -> None:
    daten = klient.post("/api/auth/2fa/einrichten",
                        json={"passwort": PW}).json()
    code = totp.code_erzeugen(daten["geheimnis"]) \
        if hasattr(totp, "code_erzeugen") else _code_aus(daten["geheimnis"])
    antwort = klient.post("/api/auth/2fa/bestaetigen", json={"code": code})
    assert antwort.status_code == 200, antwort.text


def _code_aus(geheimnis: str) -> str:
    """Der gültige Code zum aktuellen Zeitfenster — ohne eine Hilfsfunktion
    im Produktivcode zu erfinden, die dort niemand braucht."""
    import base64
    import hashlib
    import hmac
    import struct
    import time
    schluessel = base64.b32decode(geheimnis, casefold=True)
    zaehler = struct.pack(">Q", int(time.time()) // 30)
    roh = hmac.new(schluessel, zaehler, hashlib.sha1).digest()
    versatz = roh[-1] & 0x0F
    zahl = struct.unpack(">I", roh[versatz:versatz + 4])[0] & 0x7FFFFFFF
    return f"{zahl % 1_000_000:06d}"


# ---- N502 — der Riegel ------------------------------------------------

def test_ohne_zweiten_faktor_laesst_sich_nichts_anlegen(klient):
    _anmelden(klient, "Zwang-Anlegen")
    antwort = klient.post("/api/objekte",
                          json={"name": "Teststrasse 1", "adresse": "Teststrasse 1"})
    assert antwort.status_code == 403, antwort.text
    assert antwort.headers.get("X-ImmoCalc-Grund") == "zwei-faktor"


def _eine_route_je_methode() -> dict[str, str]:
    """Sucht zu jeder schreibenden Methode einen ECHTEN registrierten Pfad.

    Ein fest getippter Pfad wäre hier wertlos: `/api/objekte/irgendwas` nimmt
    kein PUT, und ein 405 käme, BEVOR irgendeine Dependency läuft — der Test
    wäre grün, ohne den Riegel je berührt zu haben.

    Gelesen wird aus dem OpenAPI-Schema und nicht aus `app.routes`: die Router
    hängen dort geschachtelt (`_IncludedRouter`) und ein flacher Durchlauf
    findet keinen einzigen Endpunkt — er hätte den Test still übersprungen.
    Platzhalter werden mit `1` gefüllt, damit keine Typprüfung (422) vor die
    Dependency gerät."""
    import re
    gefunden: dict[str, str] = {}
    for pfad, eintrag in app.openapi()["paths"].items():
        if not pfad.startswith("/api/") or pfad.startswith("/api/auth/"):
            continue
        # N474 — `/api/backup/instanz/…` hängt bewusst NICHT an einer Sitzung
        # (eine frische Instanz hat noch keine) und damit auch nicht an
        # diesem Riegel. Hier ausgenommen, sonst prüfte der Test eine Route,
        # die der Riegel gar nicht sehen kann.
        if pfad.startswith("/api/backup/instanz/"):
            continue
        for methode in eintrag:
            gross = methode.upper()
            if gross in {"GET", "HEAD", "OPTIONS"} or gross in gefunden:
                continue
            gefunden[gross] = re.sub(r"\{[^}]+\}", "1", pfad)
    return gefunden


def test_der_routenfinder_findet_ueberhaupt_etwas():
    """Wächter für den Test darüber: findet er nichts, überspringt er sich
    selbst und bewiese nichts. Genau das ist beim ersten Anlauf passiert."""
    routen = _eine_route_je_methode()
    assert set(routen) >= {"POST", "PUT", "DELETE"}, routen


@pytest.mark.parametrize("methode", ["POST", "PUT", "PATCH", "DELETE"])
def test_der_riegel_gilt_fuer_jede_schreibende_methode(klient, methode):
    routen = _eine_route_je_methode()
    pfad = routen.get(methode)
    if not pfad:
        pytest.skip(f"keine {methode}-Route ausserhalb von /api/auth")
    _anmelden(klient, f"Zwang-{methode}")
    antwort = klient.request(methode, pfad, json={})
    assert antwort.status_code == 403, f"{methode} {pfad}: {antwort.text}"
    assert antwort.headers.get("X-ImmoCalc-Grund") == "zwei-faktor"


def test_lesen_bleibt_erlaubt(klient):
    """Wer schon Daten hat, soll sie sehen können, während er einrichtet."""
    _anmelden(klient, "Zwang-Lesen")
    assert klient.get("/api/objekte").status_code == 200


def test_der_weg_zum_einrichten_bleibt_offen(klient):
    """Sonst führte der Riegel aus sich selbst nicht heraus."""
    _anmelden(klient, "Zwang-Ausweg")
    assert klient.post("/api/auth/2fa/einrichten",
                       json={"passwort": PW}).status_code == 200


def test_passwort_und_adresse_bleiben_aenderbar(klient):
    """Beides hängt am Zugang, nicht an den Daten — und beides kann nötig
    sein, BEVOR der zweite Faktor steht."""
    _anmelden(klient, "Zwang-Zugang")
    assert klient.post("/api/auth/email", json={
        "email": "zwang@haus.de", "passwort": PW}).status_code == 200
    assert klient.post("/api/auth/passwort-aendern", json={
        "alt": PW, "neu": "noch-ein-langes-passwort",
        "neu_wiederholung": "noch-ein-langes-passwort"}).status_code == 200


def test_abmelden_bleibt_moeglich(klient):
    _anmelden(klient, "Zwang-Abmelden")
    assert klient.post("/api/auth/logout").status_code == 204


def test_mit_aktivem_zweiten_faktor_faellt_der_riegel(klient):
    _anmelden(klient, "Zwang-Frei")
    _zweifaktor_einschalten(klient)
    antwort = klient.post("/api/objekte",
                          json={"name": "Freistrasse 2", "adresse": "Freistrasse 2"})
    assert antwort.status_code in (200, 201), antwort.text


def test_die_meldung_sagt_was_zu_tun_ist(klient):
    """Kein blosses „verboten" — der Nutzer muss wissen, wie er weiterkommt
    (roter Faden #7: Hinweise bedienbar machen)."""
    _anmelden(klient, "Zwang-Meldung")
    text = klient.post("/api/objekte", json={}).json()["detail"]
    assert "Zwei-Faktor" in text and "einrichten" in text
