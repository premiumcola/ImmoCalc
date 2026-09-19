"""N474 — Backups: Archivformat, Familien-Rundreise, Instanz-Schnappschuss.

Wie `test_auth.py` über die ECHTE Anmeldung (Override entfernt), weil das
Backup je Familie gehört und die Mandantengrenze hier genauso gilt wie
überall sonst. `BACKUP_ORDNER`/`BACKUP_PASSWORT` zeigen auf ein Temp-
Verzeichnis dieses Moduls — nie auf den echten Ordner.
"""
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta

import pytest

_TMP = tempfile.mkdtemp()
os.environ["DB_PATH"] = os.path.join(_TMP, "test_backup.db")
os.environ["BACKUP_ORDNER"] = os.path.join(_TMP, "backups")
os.environ["BACKUP_PASSWORT"] = "betreiber-passwort-123"
os.makedirs(os.environ["BACKUP_ORDNER"])
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

from app import backup  # noqa: E402
from app.backup import BackupFehler  # noqa: E402
from app.db import engine  # noqa: E402
from app.deps import aktuelle_familie  # noqa: E402
from app.export import exportiere_familie  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Familie  # noqa: E402
from conftest import zweifaktor_einschalten, zweiter_faktor_einloesen

PASSWORT = "sehrsicher123"
BACKUP_PW = "backup-geheimnis-xyz"


def _ohne_override():
    app.dependency_overrides.pop(aktuelle_familie, None)


def _familie_mit_objekt(c, name, objekt="Sicherungsweg 1") -> int:
    fid = c.post("/api/auth/registrieren",
                 json={"name": name, "passwort": PASSWORT}).json()["id"]
    zweifaktor_einschalten(c, PASSWORT)        # N502
    antwort = c.post("/api/objekte", json={
        "name": objekt,
        "einheiten": [{"bezeichnung": "EG", "flaeche": 60.0, "partei": "Meier"}]})
    assert antwort.status_code in (200, 201), antwort.text
    return fid


def _backup_einrichten(c, **extra):
    antwort = c.put("/api/backup/einstellungen", json={
        "login_passwort": PASSWORT, "backup_passwort": BACKUP_PW, **extra})
    assert antwort.status_code == 200, antwort.text
    return antwort.json()


# --------------------------------------------------------------------------
# Archivformat
# --------------------------------------------------------------------------

def test_archiv_rundreise():
    salz = backup.neues_salz()
    schluessel = backup.schluessel_ableiten("geheim", salz)
    archiv = backup.verschluesseln(b"hallo welt" * 100, schluessel, salz)
    assert archiv.startswith(backup.MAGIC)
    assert backup.entschluesseln(archiv, "geheim") == b"hallo welt" * 100


def test_falsches_passwort_wird_erkannt():
    salz = backup.neues_salz()
    archiv = backup.verschluesseln(b"x", backup.schluessel_ableiten("richtig", salz), salz)
    with pytest.raises(BackupFehler):
        backup.entschluesseln(archiv, "falsch")


def test_manipulation_faellt_auf():
    """AES-GCM ist authentifiziert: ein gekipptes Byte liefert keinen
    Datenmüll, sondern einen Fehler."""
    salz = backup.neues_salz()
    archiv = bytearray(backup.verschluesseln(
        b"inhalt", backup.schluessel_ableiten("pw", salz), salz))
    archiv[-1] ^= 0x01
    with pytest.raises(BackupFehler):
        backup.entschluesseln(bytes(archiv), "pw")


def test_fremde_datei_ist_keine_sicherung():
    with pytest.raises(BackupFehler):
        backup.entschluesseln(b"%PDF-1.4 ganz sicher kein Backup", "pw")


def test_faellig_nur_nachts_einmal_und_nach_rhythmus():
    nacht = datetime(2026, 9, 15, 3, 0)            # Dienstag
    assert backup.faellig("taeglich", None, nacht) is True
    assert backup.faellig("taeglich", nacht - timedelta(days=1), nacht) is True
    assert backup.faellig("taeglich", nacht - timedelta(minutes=20), nacht) is False, \
        "in derselben Nacht schon geprüft"
    assert backup.faellig("taeglich", None, nacht.replace(hour=14)) is False
    assert backup.faellig("woechentlich", None, nacht) is False, "Dienstag"
    assert backup.faellig("woechentlich", None, datetime(2026, 9, 20, 3, 0)) is True
    assert backup.faellig("", None, nacht) is False


def test_instanz_aufraeumen_behaelt_monatsstaende(tmp_path):
    jetzt = datetime(2026, 9, 15, 3, 0)
    zeiten = {
        "frisch": jetzt - timedelta(days=5),
        "monatsstand": datetime(2026, 7, 2, 3, 0),      # erster des Monats Juli
        "spaeter_im_monat": datetime(2026, 7, 20, 3, 0),
        "uralt": jetzt - timedelta(days=500),
    }
    for zeit in zeiten.values():
        (tmp_path / backup.dateiname_instanz(zeit)).write_bytes(b"x")
    entfernt = backup.instanz_aufraeumen(str(tmp_path), jetzt)
    bleibt = {e["dateiname"] for e in backup.instanz_liste(str(tmp_path))}
    assert backup.dateiname_instanz(zeiten["frisch"]) in bleibt
    assert backup.dateiname_instanz(zeiten["monatsstand"]) in bleibt
    assert backup.dateiname_instanz(zeiten["spaeter_im_monat"]) in entfernt
    assert backup.dateiname_instanz(zeiten["uralt"]) in entfernt


# --------------------------------------------------------------------------
# Familie: Einstellungen, Herunterladen, Einspielen
# --------------------------------------------------------------------------

def test_einstellungen_verlangen_das_login_passwort():
    _ohne_override()
    with TestClient(app) as c:
        _familie_mit_objekt(c, "Backup-Sperre")
        antwort = c.put("/api/backup/einstellungen", json={
            "login_passwort": "falschfalschfalsch", "backup_passwort": BACKUP_PW})
        assert antwort.status_code == 403
        assert c.get("/api/backup/einstellungen").json()["hat_passwort"] is False


def test_rhythmus_ohne_backup_passwort_geht_nicht():
    _ohne_override()
    with TestClient(app) as c:
        _familie_mit_objekt(c, "Backup-Ohne-Pw")
        antwort = c.put("/api/backup/einstellungen", json={
            "login_passwort": PASSWORT, "rhythmus": "taeglich"})
        assert antwort.status_code == 400


def test_jetzt_sichern_ohne_ziel_ist_409():
    _ohne_override()
    with TestClient(app) as c:
        _familie_mit_objekt(c, "Backup-Kein-Ziel")
        _backup_einrichten(c)
        assert c.post("/api/backup/jetzt").status_code == 409


def test_herunterladen_und_einspielen_rundreise():
    """Der eigentliche Beweis: Familie A sichert, Familie B (frisch, leer)
    spielt ein und hat danach A's Immobilie — alles über die API."""
    _ohne_override()
    with TestClient(app) as a:
        _familie_mit_objekt(a, "Backup-A", objekt="Rundreiseweg 7")
        stand = _backup_einrichten(a)
        assert stand["hat_passwort"] is True
        datei = a.get("/api/backup/herunterladen")
        assert datei.status_code == 200, datei.text
        assert datei.headers["content-type"].startswith("application/octet-stream")
        archiv = datei.content
        assert archiv.startswith(backup.MAGIC)
        # Der Download steht in der Liste wie jede andere Sicherung.
        liste = a.get("/api/backup/einstellungen").json()["backups"]
        assert liste and liste[0]["ziel"] == "download"
        assert liste[0]["zusammenfassung"]["objekte"] == 1

    with TestClient(app) as b:
        b.post("/api/auth/registrieren", json={"name": "Backup-B", "passwort": PASSWORT})
        zweifaktor_einschalten(b, PASSWORT)     # N502
        falsch = b.post("/api/backup/einspielen", data={"passwort": "nicht-das"},
                        files={"datei": ("a.enc", archiv, "application/octet-stream")})
        assert falsch.status_code == 400
        assert b.get("/api/objekte").json() == []

        gut = b.post("/api/backup/einspielen", data={"passwort": BACKUP_PW},
                     files={"datei": ("a.enc", archiv, "application/octet-stream")})
        assert gut.status_code == 200, gut.text
        namen = [o["name"] for o in b.get("/api/objekte").json()]
        assert namen == ["Rundreiseweg 7"]

        # Nie in eine volle Familie — bestehende Daten werden nirgends ersetzt.
        nochmal = b.post("/api/backup/einspielen", data={"passwort": BACKUP_PW},
                         files={"datei": ("a.enc", archiv, "application/octet-stream")})
        assert nochmal.status_code == 409


def test_fremde_familie_sieht_keine_backups():
    _ohne_override()
    with TestClient(app) as a, TestClient(app) as b:
        _familie_mit_objekt(a, "Backup-Sicht-A")
        _backup_einrichten(a)
        a.get("/api/backup/herunterladen")
        b.post("/api/auth/registrieren", json={"name": "Backup-Sicht-B", "passwort": PASSWORT})
        zweifaktor_einschalten(b, PASSWORT)     # N502
        assert b.get("/api/backup/einstellungen").json()["backups"] == []


def test_fingerabdruck_ignoriert_das_datum_und_sieht_aenderungen():
    _ohne_override()
    with TestClient(app) as c:
        fid = _familie_mit_objekt(c, "Backup-Abdruck")
        with Session(engine) as s:
            familie = s.get(Familie, fid)
            erster = backup.fingerabdruck(exportiere_familie(s, familie))
            zweiter = backup.fingerabdruck(exportiere_familie(s, familie))
        assert erster == zweiter, "zwei Exporte ohne Änderung müssen gleich sein"
        c.post("/api/objekte", json={"name": "Zweites Haus 2"})
        with Session(engine) as s:
            dritter = backup.fingerabdruck(exportiere_familie(s, s.get(Familie, fid)))
        assert dritter != erster


# --------------------------------------------------------------------------
# Instanz-Schnappschuss
# --------------------------------------------------------------------------

def test_instanz_schnappschuss_und_wiederherstellung_in_datei(tmp_path):
    _ohne_override()
    with TestClient(app) as c:
        _familie_mit_objekt(c, "Instanz-Probe")
    # `engine` ist die je Modul ausgetauschte Engine (conftest) — ihr Pfad ist
    # die Wahrheit, nicht die beim Import gelesene Konstante `db.DB_PATH`.
    stand = backup.instanz_sichern(engine.url.database, ordner=str(tmp_path),
                                   passwort="op-pw")
    assert os.path.getsize(stand["pfad"]) == stand["groesse"]
    assert backup.instanz_liste(str(tmp_path))[0]["dateiname"] == stand["dateiname"]

    with open(stand["pfad"], "rb") as f:
        archiv = f.read()
    ziel = str(tmp_path / "kopie.db")
    backup.instanz_wiederherstellen(archiv, "op-pw", ziel)
    namen = [z[0] for z in sqlite3.connect(ziel).execute(
        "SELECT name FROM familie").fetchall()]
    assert "Instanz-Probe" in namen

    with pytest.raises(BackupFehler):
        backup.instanz_wiederherstellen(archiv, "falsch", ziel)


def test_familienarchiv_gilt_nicht_als_instanz_und_umgekehrt(tmp_path):
    _ohne_override()
    with TestClient(app) as c:
        _familie_mit_objekt(c, "Verwechslung")
        _backup_einrichten(c)
        familien_archiv = c.get("/api/backup/herunterladen").content
    with pytest.raises(BackupFehler, match="Familien-Sicherung"):
        backup.instanz_wiederherstellen(familien_archiv, BACKUP_PW, str(tmp_path / "x.db"))
    stand = backup.instanz_sichern(engine.url.database, ordner=str(tmp_path),
                                   passwort="op-pw")
    with open(stand["pfad"], "rb") as f:
        with pytest.raises(BackupFehler, match="Instanz-Sicherung"):
            backup.familie_aus_archiv(f.read(), "op-pw")


def test_instanz_endpunkt_nur_auf_unbeanspruchter_instanz():
    _ohne_override()
    with TestClient(app) as c:
        _familie_mit_objekt(c, "Instanz-Beansprucht")
    with TestClient(app) as gast:
        zustand = gast.get("/api/backup/instanz/zustand").json()
        assert zustand == {"moeglich": False, "dateien": []}
        antwort = gast.post("/api/backup/instanz/wiederherstellen",
                            data={"passwort": "x", "dateiname": "egal"})
        assert antwort.status_code == 409


def test_instanz_wiederherstellung_auf_frischer_instanz():
    """Bewusst der letzte Test des Moduls: er ersetzt die Datenbankdatei.
    Ablauf wie im Ernstfall — Schnappschuss ziehen, dann so tun, als sei die
    Installation frisch (kein Passwort gesetzt), dann über den offenen Weg
    zurückholen und mit dem alten Passwort anmelden."""
    _ohne_override()
    with TestClient(app) as c:
        _familie_mit_objekt(c, "Instanz-Zurueck", objekt="Rueckholweg 3")
    stand = backup.instanz_sichern(engine.url.database)      # in BACKUP_ORDNER

    with Session(engine) as s:
        for familie in s.exec(select(Familie)).all():
            familie.passwort_hash = None
            s.add(familie)
        s.commit()

    with TestClient(app) as gast:
        zustand = gast.get("/api/backup/instanz/zustand").json()
        assert zustand["moeglich"] is True
        assert stand["dateiname"] in [d["dateiname"] for d in zustand["dateien"]]

        falsch = gast.post("/api/backup/instanz/wiederherstellen",
                           data={"passwort": "falsch", "dateiname": stand["dateiname"]})
        assert falsch.status_code == 400

        antwort = gast.post("/api/backup/instanz/wiederherstellen",
                            data={"passwort": os.environ["BACKUP_PASSWORT"],
                                  "dateiname": stand["dateiname"]})
        assert antwort.status_code == 200, antwort.text
        assert antwort.json()["familien"] >= 1

    with TestClient(app) as frisch:
        # Die Passwörter sind zurück — und damit ist die Instanz wieder
        # beansprucht: der offene Weg ist zu.
        #
        # N502 — die Familie hat seit dem Zwei-Faktor-Zwang auch einen zweiten
        # Faktor, und der ist mitgesichert worden: `/login` antwortet deshalb
        # mit 202 und einem Ticket statt mit 200 und einer Sitzung. Genau das
        # ist hier der stärkere Nachweis — das Passwort hat gestimmt UND der
        # zweite Faktor hat die Wiederherstellung überlebt.
        login = frisch.post("/api/auth/login",
                            json={"name": "Instanz-Zurueck", "passwort": PASSWORT})
        assert login.status_code == 202, login.text
        assert login.json()["zwei_faktor_noetig"] is True
        zweiter_faktor_einloesen(frisch, login.json()["ticket"],
                                 "Instanz-Zurueck")
        assert [o["name"] for o in frisch.get("/api/objekte").json()] == ["Rueckholweg 3"]
        assert frisch.get("/api/backup/instanz/zustand").json()["moeglich"] is False
