"""N16b — byte-gleiches Duplikat entfernen (nur wenn eine identische Kopie
bleibt). Eine einzigartige Datei wird NIE gelöscht.
"""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(),
                                     "test_duplikat_entfernen.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

import app.routers.dokumente as dok  # noqa: E402
from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Dokument, Objekt  # noqa: E402
from app.nextcloud import NextcloudFehler  # noqa: E402


class _FakeCloud:
    def __init__(self, inhalt):
        self.inhalt = inhalt
        self.geloescht = []

    def hole(self, pfad):
        if pfad not in self.inhalt:
            raise NextcloudFehler(f"404: {pfad}")
        return self.inhalt[pfad], "application/pdf"

    def loesche(self, pfad):
        self.geloescht.append(pfad)


def _zuordnen(c, slug, pfad):
    return c.post("/api/dokumente/vorhandenen-zuordnen", json={
        "objekt": slug, "pfad": pfad, "kategorie": "Nebenkosten"}).json()["id"]


def test_byte_gleiches_duplikat_wird_entfernt(monkeypatch):
    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={"name": "Dupweg 9"}).json()["slug"]
        with Session(engine) as s:
            o = s.exec(select(Objekt).where(Objekt.slug == slug)).first()
            o.nc_ordner = "Obj"
            s.add(o)
            s.commit()
        a = _zuordnen(c, slug, "/Obj/60_NK/2025/weg.pdf")
        b = _zuordnen(c, slug, "/Obj/60_NK/2025/kanon.pdf")

        fake = _FakeCloud({"/Obj/60_NK/2025/weg.pdf": b"MUELL-PDF",
                           "/Obj/60_NK/2025/kanon.pdf": b"MUELL-PDF"})
        monkeypatch.setattr(dok, "verbindung", lambda session: fake)

        r = c.post(f"/api/dokumente/{a}/duplikat-entfernen",
                   json={"behalten_id": b})
        assert r.status_code == 200, r.text
        assert "/Obj/60_NK/2025/weg.pdf" in fake.geloescht
        assert "/Obj/60_NK/2025/weg.immocalc" in fake.geloescht   # Sidecar mit
        with Session(engine) as s:
            assert s.get(Dokument, a) is None        # Eintrag weg
            assert s.get(Dokument, b) is not None     # Kanon bleibt


def test_nicht_byte_gleich_wird_nicht_geloescht(monkeypatch):
    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={"name": "Dupweg 10"}).json()["slug"]
        with Session(engine) as s:
            o = s.exec(select(Objekt).where(Objekt.slug == slug)).first()
            o.nc_ordner = "Obj2"
            s.add(o)
            s.commit()
        a = _zuordnen(c, slug, "/Obj2/a.pdf")
        b = _zuordnen(c, slug, "/Obj2/b.pdf")
        fake = _FakeCloud({"/Obj2/a.pdf": b"EINS", "/Obj2/b.pdf": b"ZWEI"})
        monkeypatch.setattr(dok, "verbindung", lambda session: fake)

        r = c.post(f"/api/dokumente/{a}/duplikat-entfernen",
                   json={"behalten_id": b})
        assert r.status_code == 409, r.text
        assert fake.geloescht == []                   # nichts gelöscht
        with Session(engine) as s:
            assert s.get(Dokument, a) is not None      # Datei bleibt
