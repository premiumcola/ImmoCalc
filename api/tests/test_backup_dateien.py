"""N478 — die Belege wandern mit in die Sicherung, inkrementell.

Nutzer: „wie sieht es jetzt aus mit den ganzen Dateien, die da hochgeladen
sind … wenn man jedes Mal alle Dateien backupt, dann würde das sehr groß
werden … man könnte nur neue Dateien immer an das nächste Backup dranhängen."

Genau das prüfen die beiden wichtigsten Tests hier: beim zweiten Lauf ohne
Änderung wandert **nichts** mehr hinüber, und dieselbe Datei an zwei
Dokumenten liegt nur **einmal** im Speicher.

Die Cloud ist hier die echte `Nextcloud`-Klasse mit ausgetauschter
HTTP-Schicht (wie in `test_beleg_umbenennen.py`) — so gilt derselbe
Schreibrecht-Riegel wie in der Anwendung.
"""
import hashlib
import os
import sys
import tempfile
from types import SimpleNamespace

_TMP = tempfile.mkdtemp()
os.environ["DB_PATH"] = os.path.join(_TMP, "test_backup_dateien.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

from app import backup  # noqa: E402
from app.db import engine  # noqa: E402
from app.deps import aktuelle_familie  # noqa: E402
from app.main import app  # noqa: E402
from app.models import BackupDatei, Dokument, Familie, Objekt  # noqa: E402
from app.nextcloud import Nextcloud, NextcloudFehler  # noqa: E402

PASSWORT = "sehrsicher123"
BACKUP_PW = "backup-geheimnis-xyz"
HEIM = "/Home"
ORDNER = "Home/_Backups"


class Wolke(Nextcloud):
    """Echte Nextcloud, nur die HTTP-Schicht antwortet aus dem Gedächtnis."""

    def __init__(self, dateien: dict[str, bytes] | None = None):
        super().__init__("https://cloud.test", "nutzer", "geheim", heimat=HEIM)
        self.dateien: dict[str, bytes] = dict(dateien or {})
        self.schreibzugriffe: list[str] = []

    def _anfrage(self, methode, pfad, **kw):
        schluessel = pfad.strip("/")
        if methode == "PROPFIND":
            da = schluessel in self.dateien or any(
                p.startswith(schluessel + "/") for p in self.dateien)
            return SimpleNamespace(status_code=207 if da else 404, text="")
        if methode == "PUT":
            self.dateien[schluessel] = kw["content"]
            self.schreibzugriffe.append(schluessel)
            return SimpleNamespace(status_code=201, text="")
        if methode == "GET":
            if schluessel not in self.dateien:
                return SimpleNamespace(status_code=404, text="", content=b"",
                                       headers={})
            return SimpleNamespace(status_code=200, content=self.dateien[schluessel],
                                   headers={"Content-Type": "application/pdf"},
                                   text="")
        if methode == "MKCOL":
            return SimpleNamespace(status_code=201, text="")
        return SimpleNamespace(status_code=200, text="", content=b"", headers={})


def _ohne_override():
    app.dependency_overrides.pop(aktuelle_familie, None)


def _welt(c, name, belege: dict[str, bytes]):
    """Familie mit einem Objekt und Belegen in der Cloud."""
    c.post("/api/auth/registrieren", json={"name": name, "passwort": PASSWORT})
    fid = c.get("/api/auth/ich").json()["id"]
    slug = c.post("/api/objekte", json={"name": f"Weg {name}"}).json()["slug"]
    with Session(engine) as s:
        familie = s.get(Familie, fid)
        salz = backup.neues_salz()
        familie.backup_salz = salz.hex()
        familie.backup_schluessel = backup.schluessel_ableiten(BACKUP_PW, salz).hex()
        s.add(familie)
        objekt = s.exec(select(Objekt).where(Objekt.slug == slug)).one()
        for pfad, inhalt in belege.items():
            s.add(Dokument(pfad=pfad, dateiname=pfad.split("/")[-1],
                           groesse=len(inhalt), objekt_id=objekt.id,
                           sha1=hashlib.sha1(inhalt).hexdigest()))
        s.commit()
    return fid


def _sichern(fid, wolke, ziel=None, hoechstens=None):
    with Session(engine) as s:
        familie = s.get(Familie, fid)
        return backup.dateien_sichern(
            s, familie, wolke, ziel or wolke, ORDNER,
            bytes.fromhex(familie.backup_schluessel),
            bytes.fromhex(familie.backup_salz), hoechstens=hoechstens)


# --------------------------------------------------------------------------
# Der Kern: inkrementell und ohne Doppelung
# --------------------------------------------------------------------------

def test_zweiter_lauf_ohne_aenderung_uebertraegt_nichts():
    """Der Punkt des Nutzers: sonst würde jede Nacht alles neu hochgeladen."""
    _ohne_override()
    belege = {"Home/A/rechnung.pdf": b"%PDF-1.4 erste",
              "Home/A/zweite.pdf": b"%PDF-1.4 zweite"}
    with TestClient(app) as c:
        fid = _welt(c, "Inkrementell", belege)
    wolke = Wolke(belege)

    erster = _sichern(fid, wolke)
    assert erster["neu"] == 2, erster
    assert erster["bytes"] == sum(len(v) for v in belege.values())

    zweiter = _sichern(fid, wolke)
    assert zweiter["neu"] == 0, "beim zweiten Lauf darf nichts mehr wandern"
    assert zweiter["geprueft"] == 2, "geprüft wird trotzdem alles"


def test_neuer_beleg_wandert_allein():
    _ohne_override()
    belege = {"Home/B/alt.pdf": b"%PDF alt"}
    with TestClient(app) as c:
        fid = _welt(c, "Nachzuegler", belege)
    wolke = Wolke(belege)
    assert _sichern(fid, wolke)["neu"] == 1

    neu = b"%PDF ganz neu"
    wolke.dateien["Home/B/neu.pdf"] = neu
    with Session(engine) as s:
        objekt = s.exec(select(Objekt).where(Objekt.name == "Weg Nachzuegler")).one()
        s.add(Dokument(pfad="Home/B/neu.pdf", dateiname="neu.pdf",
                       groesse=len(neu), objekt_id=objekt.id,
                       sha1=hashlib.sha1(neu).hexdigest()))
        s.commit()

    stand = _sichern(fid, wolke)
    assert stand["neu"] == 1, "nur der neue Beleg"
    assert stand["geprueft"] == 2


def test_gleiche_datei_zweimal_liegt_nur_einmal_im_speicher():
    """Inhaltsadressiert: derselbe Beleg an zwei Stellen kostet einmal Platz."""
    _ohne_override()
    inhalt = b"%PDF derselbe Inhalt"
    belege = {"Home/C/eins.pdf": inhalt, "Home/C/zwei.pdf": inhalt}
    with TestClient(app) as c:
        fid = _welt(c, "Doppelt", belege)
    wolke = Wolke(belege)

    stand = _sichern(fid, wolke)
    assert stand["geprueft"] == 2
    assert stand["neu"] == 1, "zweimal derselbe Inhalt, einmal übertragen"
    with Session(engine) as s:
        zeilen = s.exec(select(BackupDatei).where(
            BackupDatei.familie_id == fid)).all()
        assert len(zeilen) == 1


def test_der_speicher_sieht_nur_verschluesselte_klumpen():
    _ohne_override()
    geheim = b"%PDF-1.4 Mietvertrag Familie Meier, 1200 EUR"
    with TestClient(app) as c:
        fid = _welt(c, "Verschluesselt", {"Home/D/vertrag.pdf": geheim})
    wolke = Wolke({"Home/D/vertrag.pdf": geheim})
    _sichern(fid, wolke)

    abgelegt = [p for p in wolke.schreibzugriffe if p.startswith(ORDNER)]
    assert abgelegt, "es wurde nichts abgelegt"
    for pfad in abgelegt:
        roh = wolke.dateien[pfad]
        assert roh.startswith(backup.MAGIC), "nicht als ImmoCalc-Archiv abgelegt"
        assert b"Mietvertrag" not in roh
        assert b"Meier" not in roh
        # Der Name verrät nur die Prüfsumme, nicht den Dateinamen.
        assert "vertrag" not in pfad


def test_fehlender_beleg_haelt_die_sicherung_nicht_auf():
    """Ein Beleg, den jemand in der Cloud gelöscht hat, darf den Rest nicht
    verhindern — gemeldet wird er trotzdem."""
    _ohne_override()
    da = b"%PDF vorhanden"
    with TestClient(app) as c:
        fid = _welt(c, "Luecke", {"Home/E/weg.pdf": b"x", "Home/E/da.pdf": da})
    wolke = Wolke({"Home/E/da.pdf": da})          # "weg.pdf" fehlt in der Cloud

    stand = _sichern(fid, wolke)
    assert stand["neu"] == 1
    assert len(stand["fehler"]) == 1
    assert "weg.pdf" in stand["fehler"][0]


def test_sehr_grosse_datei_wird_uebersprungen():
    _ohne_override()
    with TestClient(app) as c:
        fid = _welt(c, "Riesig", {"Home/F/film.mp4": b"x"})
    with Session(engine) as s:
        d = s.exec(select(Dokument).where(Dokument.pfad == "Home/F/film.mp4")).one()
        d.groesse = backup.DATEI_MAX_BYTES + 1
        s.add(d)
        s.commit()
    stand = _sichern(fid, Wolke({"Home/F/film.mp4": b"x"}))
    assert stand["neu"] == 0 and stand["uebersprungen"] == 1


# --------------------------------------------------------------------------
# Zurückholen
# --------------------------------------------------------------------------

def test_zurueckholen_legt_die_belege_wieder_unter_denselben_pfad():
    """Der eigentliche Ernstfall: neue Nextcloud, leer — die Belege müssen
    dorthin zurück, wo die Datenbank sie erwartet, sonst zeigen alle
    Verknüpfungen ins Leere."""
    _ohne_override()
    inhalt = b"%PDF-1.4 der wiederhergestellte Beleg"
    with TestClient(app) as c:
        fid = _welt(c, "Rueckholung", {"Home/G/beleg.pdf": inhalt})
    speicher = Wolke({"Home/G/beleg.pdf": inhalt})
    _sichern(fid, speicher)

    # Neue, leere Cloud — nur der Sicherungsordner ist noch da.
    neu = Wolke({p: i for p, i in speicher.dateien.items() if p.startswith(ORDNER)})
    with Session(engine) as s:
        stand = backup.dateien_zurueckholen(s, s.get(Familie, fid), neu, neu,
                                            ORDNER, BACKUP_PW)
    assert stand["zurueck"] == 1, stand
    assert neu.dateien["Home/G/beleg.pdf"] == inhalt, \
        "der Beleg kam nicht unverändert zurück"


def test_zurueckholen_ueberschreibt_vorhandene_belege_nicht():
    _ohne_override()
    inhalt = b"%PDF original"
    with TestClient(app) as c:
        fid = _welt(c, "Nichtsanfassen", {"Home/H/da.pdf": inhalt})
    wolke = Wolke({"Home/H/da.pdf": inhalt})
    _sichern(fid, wolke)
    wolke.schreibzugriffe.clear()
    wolke.dateien["Home/H/da.pdf"] = b"%PDF vom Nutzer geaendert"

    with Session(engine) as s:
        stand = backup.dateien_zurueckholen(s, s.get(Familie, fid), wolke, wolke,
                                            ORDNER, BACKUP_PW)
    assert stand["zurueck"] == 0
    assert wolke.dateien["Home/H/da.pdf"] == b"%PDF vom Nutzer geaendert"


def test_falsches_passwort_holt_nichts_zurueck():
    _ohne_override()
    inhalt = b"%PDF geheim"
    with TestClient(app) as c:
        fid = _welt(c, "Falschespw", {"Home/I/x.pdf": inhalt})
    speicher = Wolke({"Home/I/x.pdf": inhalt})
    _sichern(fid, speicher)
    leer = Wolke({p: i for p, i in speicher.dateien.items() if p.startswith(ORDNER)})

    with Session(engine) as s:
        stand = backup.dateien_zurueckholen(s, s.get(Familie, fid), leer, leer,
                                            ORDNER, "das-ist-nicht-das-passwort")
    assert stand["zurueck"] == 0
    assert stand["fehler"], "ein falsches Passwort muss gemeldet werden"
    assert "Home/I/x.pdf" not in leer.dateien
