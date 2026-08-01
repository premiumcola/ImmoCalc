"""N24 — Batch-Migration bestehender Cloud-Dateien.

Zwei Endpunkte, beide idempotent und standardmäßig „trocken":
* `POST /praefix-entfernen` — streicht das führende „ohne-Jahr_" aus Namen.
* `POST /lageplaene-einsortieren` — zieht Lagepläne in ihren Sammelordner
  „10_Fotos_Lage/00_Lagepläne".

Nie überschreiben, nie löschen; die Datei wird per MOVE umgehängt und der
DB-Eintrag zieht mit.
"""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(),
                                     "test_praefix_lageplan.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

import app.routers.dokumente as dok  # noqa: E402
from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Dokument, Objekt  # noqa: E402


class _FakeCloud:
    """Merkt sich vorhandene Datei-/Ordnerpfade und führt MOVE/MKCOL nach."""

    def __init__(self, dateien=(), ordner=()):
        self.dateien = {p.strip("/") for p in dateien}
        self.ordner = {p.strip("/") for p in ordner}
        self.moves = []

    def existiert(self, pfad):
        p = pfad.strip("/")
        return p in self.dateien or p in self.ordner

    def verschiebe(self, alt, neu):
        a, n = alt.strip("/"), neu.strip("/")
        self.moves.append((a, n))
        if a in self.dateien:
            self.dateien.discard(a)
            self.dateien.add(n)

    def ordner_anlegen(self, pfad):
        self.ordner.add(pfad.strip("/"))
        return True

    def liste(self, pfad):
        return []


def _objekt(client, name):
    slug = client.post("/api/objekte", json={"name": name}).json()["slug"]
    with Session(engine) as s:
        o = s.exec(select(Objekt).where(Objekt.slug == slug)).first()
        o.nc_ordner = "Obj"
        s.add(o)
        s.commit()
        return o.id


def _dokument(objekt_id, dateiname, pfad, kategorie="Sonstiges"):
    with Session(engine) as s:
        d = Dokument(objekt_id=objekt_id, dateiname=dateiname, pfad=pfad,
                     kategorie=kategorie)
        s.add(d)
        s.commit()
        return d.id


def test_praefix_trocken_zeigt_nur_den_plan(monkeypatch):
    with TestClient(app) as c:
        oid = _objekt(c, "Präfix Trocken")
        did = _dokument(oid, "ohne-Jahr_Foto.jpg",
                        "/Obj/10_Fotos_Lage/ohne-Jahr_Foto.jpg")
        fake = _FakeCloud(dateien=["Obj/10_Fotos_Lage/ohne-Jahr_Foto.jpg"])
        monkeypatch.setattr(dok, "verbindung", lambda session: fake)

        r = c.post("/api/dokumente/praefix-entfernen").json()  # Vorgabe: trocken
        assert r["trocken"] is True
        assert r["anzahl"] == 1
        assert r["plan"][0] == {"id": did, "alt": "ohne-Jahr_Foto.jpg",
                                "neu": "Foto.jpg"}
        # Trocken ändert nichts.
        assert not fake.moves
        with Session(engine) as s:
            assert s.get(Dokument, did).dateiname == "ohne-Jahr_Foto.jpg"


def test_praefix_entfernen_benennt_um(monkeypatch):
    with TestClient(app) as c:
        oid = _objekt(c, "Präfix Scharf")
        did = _dokument(oid, "ohne-Jahr_Regenbogen.jpg",
                        "/Obj/10_Fotos_Lage/02_Aussen/ohne-Jahr_Regenbogen.jpg")
        # Eine Datei OHNE Präfix bleibt unangetastet.
        did2 = _dokument(oid, "2024_NK-Wasser.pdf",
                         "/Obj/60_Nebenkosten/2024_NK-Wasser.pdf",
                         kategorie="Nebenkosten")
        fake = _FakeCloud(dateien=[
            "Obj/10_Fotos_Lage/02_Aussen/ohne-Jahr_Regenbogen.jpg",
            "Obj/60_Nebenkosten/2024_NK-Wasser.pdf"])
        monkeypatch.setattr(dok, "verbindung", lambda session: fake)

        r = c.post("/api/dokumente/praefix-entfernen?trocken=false").json()
        assert r["trocken"] is False
        umbenannt = {x["id"]: x["neu"] for x in r["verschoben"]}
        assert umbenannt.get(did) == "Regenbogen.jpg"
        assert did2 not in umbenannt          # ohne Präfix → nicht angefasst
        assert r["fehler"] == []
        # Datei umgehängt (gleicher Ordner), DB zieht mit.
        assert ("Obj/10_Fotos_Lage/02_Aussen/ohne-Jahr_Regenbogen.jpg",
                "Obj/10_Fotos_Lage/02_Aussen/Regenbogen.jpg") in fake.moves
        with Session(engine) as s:
            d = s.get(Dokument, did)
            assert d.dateiname == "Regenbogen.jpg"
            assert d.pfad == "/Obj/10_Fotos_Lage/02_Aussen/Regenbogen.jpg"
            # Der Beleg ohne Präfix ist unberührt.
            assert s.get(Dokument, did2).dateiname == "2024_NK-Wasser.pdf"

        # Idempotent: zweiter Lauf findet nichts mehr.
        r2 = c.post("/api/dokumente/praefix-entfernen?trocken=false").json()
        assert r2["verschoben"] == []


def test_lageplaene_einsortieren_zieht_in_sammelordner(monkeypatch):
    with TestClient(app) as c:
        oid = _objekt(c, "Lageplan Umzug")
        did = _dokument(oid, "Lageplan-EG.pdf",
                        "/Obj/99_Sonstiges/Lageplan-EG.pdf",
                        kategorie="Lageplan")
        fake = _FakeCloud(dateien=["Obj/99_Sonstiges/Lageplan-EG.pdf"])
        monkeypatch.setattr(dok, "verbindung", lambda session: fake)

        r = c.post("/api/dokumente/lageplaene-einsortieren?trocken=false").json()
        assert r["trocken"] is False
        assert len(r["verschoben"]) == 1 and r["fehler"] == []
        with Session(engine) as s:
            d = s.get(Dokument, did)
            assert d.pfad == "/Obj/10_Fotos_Lage/00_Lagepläne/Lageplan-EG.pdf"
        # Der Sammelordner wurde angelegt (MKCOL, 405-sicher).
        assert "Obj/10_Fotos_Lage/00_Lagepläne" in fake.ordner

        # Idempotent: liegt er schon richtig, passiert nichts mehr.
        r2 = c.post("/api/dokumente/lageplaene-einsortieren?trocken=false").json()
        assert r2["verschoben"] == []
