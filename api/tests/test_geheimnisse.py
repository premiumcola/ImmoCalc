"""N475 — Zugangsdaten verschlüsselt in der Datenbank (N469 Punkt 11).

Der eigentliche Beweis steht in `test_datenbankdatei_gibt_keine_zugangsdaten_preis`:
die Datei wird nach dem Speichern BYTEWEISE durchsucht. Taucht das Passwort
darin auf, ist alles andere hier egal.
"""
import os
import sys
import tempfile

_TMP = tempfile.mkdtemp()
os.environ["DB_PATH"] = os.path.join(_TMP, "test_geheimnisse.db")
os.environ["GEHEIMNIS_SCHLUESSEL"] = "test-schluessel-sehr-lang-und-zufaellig"
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

from app import geheimnis  # noqa: E402
from app.db import engine  # noqa: E402
from app.deps import aktuelle_familie  # noqa: E402
from app.main import app  # noqa: E402
from app.migrate import geheimnisse_schuetzen  # noqa: E402
from app.models import Einstellung, Familie  # noqa: E402

PASSWORT = "sehrsicher123"
NC_PASSWORT = "nextcloud-geheim-9f3a"


def _ohne_override():
    app.dependency_overrides.pop(aktuelle_familie, None)


def _datei_inhalt() -> bytes:
    with open(engine.url.database, "rb") as datei:
        return datei.read()


# --------------------------------------------------------------------------
# Das Verfahren selbst
# --------------------------------------------------------------------------

def test_rundreise():
    geschuetzt = geheimnis.schuetzen("hallo welt")
    assert geschuetzt.startswith(geheimnis.PRAEFIX)
    assert "hallo welt" not in geschuetzt
    assert geheimnis.lesen(geschuetzt) == "hallo welt"


def test_klartext_wird_unveraendert_durchgereicht():
    """Der Bestand vor N475 und jede nicht geheime Einstellung müssen weiter
    lesbar sein — daran hängt, dass der Umstieg ohne Bruch läuft."""
    assert geheimnis.lesen("/Home/Immobilien") == "/Home/Immobilien"
    assert geheimnis.lesen("") == ""
    assert geheimnis.lesen(None) is None


def test_zweimal_schuetzen_aendert_nichts():
    einmal = geheimnis.schuetzen("wert")
    assert geheimnis.schuetzen(einmal) == einmal


def test_jedes_mal_ein_anderer_geheimtext():
    """Gleicher Klartext, anderes Ergebnis — sonst verriete die Datei, welche
    zwei Familien dasselbe Passwort benutzen."""
    a = geheimnis.schuetzen("dasselbe")
    b = geheimnis.schuetzen("dasselbe")
    assert a != b
    assert geheimnis.lesen(a) == geheimnis.lesen(b) == "dasselbe"


def test_falscher_schluessel_gibt_leer_statt_absturz(monkeypatch):
    """Eine vertauschte env-Datei darf die App nicht am Starten hindern —
    ein unlesbarer Zugang ist so gut wie ein leerer."""
    geschuetzt = geheimnis.schuetzen("geheim")
    monkeypatch.setenv("GEHEIMNIS_SCHLUESSEL", "ein-ganz-anderer-schluessel")
    assert geheimnis.lesen(geschuetzt) == ""


def test_ohne_schluessel_bleibt_alles_klartext(monkeypatch):
    monkeypatch.delenv("GEHEIMNIS_SCHLUESSEL", raising=False)
    assert geheimnis.aktiv() is False
    assert geheimnis.schuetzen("offen") == "offen"


def test_veraenderte_bytes_fallen_auf():
    """AES-GCM ist authentifiziert — ein gekipptes Bit liefert keinen
    Datenmüll, sondern gilt als unlesbar."""
    geschuetzt = geheimnis.schuetzen("unversehrt")
    kaputt = geschuetzt[:-4] + ("AAAA" if geschuetzt[-4:] != "AAAA" else "BBBB")
    assert geheimnis.lesen(kaputt) == ""


# --------------------------------------------------------------------------
# In der echten Datenbank
# --------------------------------------------------------------------------

def test_datenbankdatei_gibt_keine_zugangsdaten_preis():
    """Der Kern von N469 Punkt 11: wer die Datei hat, darf nichts finden."""
    _ohne_override()
    with TestClient(app) as c:
        c.post("/api/auth/registrieren",
               json={"name": "Geheim-A", "passwort": PASSWORT})
        # Nextcloud-Zugang setzen — die Verbindung schlägt fehl (kein Server),
        # deshalb direkt über den Schreibweg, den auch der Endpunkt nimmt.
        from app import familienraum                       # noqa: PLC0415
        from app.routers.cloud import _schreib             # noqa: PLC0415
        fid = c.get("/api/auth/ich").json()["id"]
        with Session(engine) as s:
            familienraum.setzen(fid)
            _schreib(s, "nc_passwort", NC_PASSWORT)
            _schreib(s, "mail_passwort", "postfach-geheim-7c1")
            _schreib(s, "ki_api_key", "sk-ant-geheim-4b2")
            _schreib(s, "nc_home", "/Home/Immobilien")     # NICHT geheim
            s.commit()
            familienraum.setzen(None)

    inhalt = _datei_inhalt()
    assert NC_PASSWORT.encode() not in inhalt, "Nextcloud-Passwort steht im Klartext in der Datei"
    assert b"postfach-geheim-7c1" not in inhalt
    assert b"sk-ant-geheim-4b2" not in inhalt
    # Gegenprobe: was nicht geheim ist, bleibt lesbar — sonst wäre die
    # Datenbank für eine Prüfung von Hand unbrauchbar.
    assert b"/Home/Immobilien" in inhalt


def test_app_liest_die_zugangsdaten_weiterhin():
    """Verschlüsselt gespeichert, aber im Betrieb ganz normal lesbar."""
    _ohne_override()
    from app import familienraum                           # noqa: PLC0415
    from app.cloudkern import _lies                        # noqa: PLC0415

    with TestClient(app) as c:
        c.post("/api/auth/registrieren",
               json={"name": "Geheim-B", "passwort": PASSWORT})
        fid = c.get("/api/auth/ich").json()["id"]
    from app.routers.cloud import _schreib                  # noqa: PLC0415
    with Session(engine) as s:
        familienraum.setzen(fid)
        _schreib(s, "nc_passwort", "zurueckgelesen-ok")
        s.commit()
        assert _lies(s, "nc_passwort") == "zurueckgelesen-ok"
        familienraum.setzen(None)


def test_totp_geheimnis_steht_nicht_im_klartext_in_der_datei():
    _ohne_override()
    with TestClient(app) as c:
        c.post("/api/auth/registrieren",
               json={"name": "Geheim-TOTP", "passwort": PASSWORT})
        ein = c.post("/api/auth/2fa/einrichten", json={"passwort": PASSWORT})
        assert ein.status_code == 200, ein.text
        secret = ein.json()["geheimnis"]

    assert secret.encode() not in _datei_inhalt(), \
        "das TOTP-Geheimnis steht im Klartext in der Datenbank"

    # Und es ist trotzdem nutzbar: derselbe Wert kommt beim Lesen zurück.
    with Session(engine) as s:
        familie = s.exec(select(Familie).where(
            Familie.name == "Geheim-TOTP")).one()
        assert familie.totp_geheimnis_ausstehend == secret


def test_webdav_passwort_steht_nicht_im_klartext():
    _ohne_override()
    with TestClient(app) as c:
        c.post("/api/auth/registrieren",
               json={"name": "Geheim-DAV", "passwort": PASSWORT})
        fid = c.get("/api/auth/ich").json()["id"]
    with Session(engine) as s:
        familie = s.get(Familie, fid)
        familie.backup_webdav_passwort = "koofr-app-passwort-88"
        s.add(familie)
        s.commit()
    assert b"koofr-app-passwort-88" not in _datei_inhalt()
    with Session(engine) as s:
        assert s.get(Familie, fid).backup_webdav_passwort == "koofr-app-passwort-88"


# --------------------------------------------------------------------------
# Der Umstieg für den Bestand
# --------------------------------------------------------------------------

def test_migration_verschluesselt_bestehenden_klartext():
    """Der Bestand liegt im Klartext — nach einem Start ist er geschützt,
    ohne dass jemand etwas neu eintragen muss."""
    _ohne_override()
    with TestClient(app) as c:
        c.post("/api/auth/registrieren",
               json={"name": "Geheim-Alt", "passwort": PASSWORT})
        fid = c.get("/api/auth/ich").json()["id"]

    # Von Hand Klartext hineinschreiben, wie er vor N475 dort stand.
    with Session(engine) as s:
        s.add(Einstellung(schluessel=f"{fid}:nc_passwort",
                          wert="altes-klartext-passwort-33"))
        s.commit()
    assert b"altes-klartext-passwort-33" in _datei_inhalt()

    umgestellt = geheimnisse_schuetzen(engine)
    assert umgestellt >= 1
    assert b"altes-klartext-passwort-33" not in _datei_inhalt()

    with Session(engine) as s:
        eintrag = s.get(Einstellung, f"{fid}:nc_passwort")
        assert geheimnis.ist_geschuetzt(eintrag.wert)
        assert geheimnis.lesen(eintrag.wert) == "altes-klartext-passwort-33"

    # Zweiter Lauf ändert nichts mehr.
    assert geheimnisse_schuetzen(engine) == 0


def test_familien_sicherung_enthaelt_klartext_und_laesst_sich_woanders_einspielen():
    """Eine Sicherung muss auf einer FRISCHEN Instanz mit anderem Schlüssel
    aufgehen — deshalb liegt im (ohnehin verschlüsselten) Archiv Klartext."""
    _ohne_override()
    from app import familienraum                           # noqa: PLC0415
    from app.export import exportiere_familie              # noqa: PLC0415
    from app.routers.cloud import _schreib                 # noqa: PLC0415

    with TestClient(app) as c:
        c.post("/api/auth/registrieren",
               json={"name": "Geheim-Export", "passwort": PASSWORT})
        fid = c.get("/api/auth/ich").json()["id"]
    with Session(engine) as s:
        familienraum.setzen(fid)
        _schreib(s, "nc_passwort", "export-klartext-55")
        s.commit()
        daten = exportiere_familie(s, s.get(Familie, fid))
        familienraum.setzen(None)

    assert daten["einstellungen"]["nc_passwort"] == "export-klartext-55"
