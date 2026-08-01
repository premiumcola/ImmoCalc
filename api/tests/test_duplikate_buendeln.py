"""Byte-gleiche Duplikate in den Sammelordner „99_Duplikate" bündeln.

Inhaltsbasiert (SHA1 des geladenen Inhalts), unabhängig vom Dateinamen. Nie
löschen — nur MOVE; eine „behalten"-Kopie bleibt am Platz. Standardmäßig
„trocken" (nur Plan). Idempotent: ein zweiter scharfer Lauf verschiebt nichts
mehr.
"""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(),
                                     "test_duplikate_buendeln.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

import app.routers.dokumente as dok  # noqa: E402
from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Dokument, Objekt  # noqa: E402
from app.nextcloud import NextcloudFehler  # noqa: E402


class _FakeCloud:
    """Nextcloud-Ersatz: liefert Inhalte (für SHA1), führt MOVE/MKCOL nach.

    `inhalt`: {Pfad: bytes}. `hole` gibt (bytes, typ); `verschiebe` zieht den
    Inhalt mit, damit `hole` nach dem Move weiter funktioniert (Idempotenz)."""

    def __init__(self, inhalt):
        self.inhalt = {("/" + p.strip("/")): b for p, b in inhalt.items()}
        self.ordner: set[str] = set()
        self.moves: list[tuple[str, str]] = []

    def hole(self, pfad):
        p = "/" + pfad.strip("/")
        if p not in self.inhalt:
            raise NextcloudFehler(f"404: {pfad}")
        return self.inhalt[p], "application/pdf"

    def existiert(self, pfad):
        return ("/" + pfad.strip("/")) in self.inhalt \
            or pfad.strip("/") in self.ordner

    def verschiebe(self, alt, neu):
        a, n = "/" + alt.strip("/"), "/" + neu.strip("/")
        self.moves.append((alt.strip("/"), neu.strip("/")))
        if a in self.inhalt:
            self.inhalt[n] = self.inhalt.pop(a)

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
        return slug


def _dokument(slug, dateiname, pfad, *, kategorie="Nebenkosten",
              position_id=None, zeitraum_id=None):
    with Session(engine) as s:
        o = s.exec(select(Objekt).where(Objekt.slug == slug)).first()
        d = Dokument(objekt_id=o.id, dateiname=dateiname, pfad=pfad,
                     kategorie=kategorie, status="zugeordnet",
                     position_id=position_id, zeitraum_id=zeitraum_id)
        s.add(d)
        s.commit()
        return d.id


def test_byte_gleich_wird_gebuendelt_kleinere_id_bleibt(monkeypatch):
    with TestClient(app) as c:
        slug = _objekt(c, "Duplikat Bündel 1")
        # Gleicher Inhalt, verschiedene Namen und Ordner.
        a = _dokument(slug, "rechnung.pdf", "/Obj/60_NK/2025/rechnung.pdf")
        b = _dokument(slug, "kopie-scan.pdf", "/Obj/eingang/kopie-scan.pdf")
        fake = _FakeCloud({"/Obj/60_NK/2025/rechnung.pdf": b"GLEICHER-INHALT",
                           "/Obj/eingang/kopie-scan.pdf": b"GLEICHER-INHALT"})
        monkeypatch.setattr(dok, "verbindung", lambda session: fake)

        r = c.post(f"/api/dokumente/objekte/{slug}/duplikate-buendeln"
                   "?trocken=false")
        assert r.status_code == 200, r.text
        k = r.json()
        assert k["gebündelt"] == 1 and k["gruppen"] == 1 and k["fehler"] == []
        with Session(engine) as s:
            # Kleinere id bleibt am Platz, die andere landet in 99_Duplikate.
            assert s.get(Dokument, a).pfad == "/Obj/60_NK/2025/rechnung.pdf"
            assert s.get(Dokument, b).pfad == "/Obj/99_Duplikate/kopie-scan.pdf"
        assert "Obj/99_Duplikate" in fake.ordner


def test_verbuchte_kopie_bleibt_trotz_groesserer_id(monkeypatch):
    with TestClient(app) as c:
        slug = _objekt(c, "Duplikat Bündel 2")
        # A hat die kleinere id, ist aber NICHT verbucht.
        a = _dokument(slug, "a.pdf", "/Obj/eingang/a.pdf")
        # B hat die größere id, ist aber verbucht (position_id gesetzt).
        b = _dokument(slug, "b.pdf", "/Obj/60_NK/b.pdf", position_id=42)
        fake = _FakeCloud({"/Obj/eingang/a.pdf": b"XX",
                           "/Obj/60_NK/b.pdf": b"XX"})
        monkeypatch.setattr(dok, "verbindung", lambda session: fake)

        r = c.post(f"/api/dokumente/objekte/{slug}/duplikate-buendeln"
                   "?trocken=false").json()
        assert r["gebündelt"] == 1
        with Session(engine) as s:
            # Der verbuchte Beleg bleibt am Platz (behält position_id) …
            behalten = s.get(Dokument, b)
            assert behalten.pfad == "/Obj/60_NK/b.pdf"
            assert behalten.position_id == 42
            # … der unverbuchte wird verschoben.
            assert s.get(Dokument, a).pfad == "/Obj/99_Duplikate/a.pdf"


def test_verschiedener_inhalt_wird_nicht_bewegt(monkeypatch):
    with TestClient(app) as c:
        slug = _objekt(c, "Duplikat Bündel 3")
        a = _dokument(slug, "eins.pdf", "/Obj/eins.pdf")
        b = _dokument(slug, "zwei.pdf", "/Obj/zwei.pdf")
        fake = _FakeCloud({"/Obj/eins.pdf": b"INHALT-EINS",
                           "/Obj/zwei.pdf": b"INHALT-ZWEI"})
        monkeypatch.setattr(dok, "verbindung", lambda session: fake)

        r = c.post(f"/api/dokumente/objekte/{slug}/duplikate-buendeln"
                   "?trocken=false").json()
        assert r["gebündelt"] == 0 and r["gruppen"] == 0
        assert fake.moves == []
        with Session(engine) as s:
            assert s.get(Dokument, a).pfad == "/Obj/eins.pdf"
            assert s.get(Dokument, b).pfad == "/Obj/zwei.pdf"


def test_trocken_liefert_plan_ohne_aenderung(monkeypatch):
    with TestClient(app) as c:
        slug = _objekt(c, "Duplikat Bündel 4")
        a = _dokument(slug, "orig.pdf", "/Obj/60_NK/orig.pdf")
        b = _dokument(slug, "dubl.pdf", "/Obj/eingang/dubl.pdf")
        fake = _FakeCloud({"/Obj/60_NK/orig.pdf": b"SAME",
                           "/Obj/eingang/dubl.pdf": b"SAME"})
        monkeypatch.setattr(dok, "verbindung", lambda session: fake)

        # Vorgabe ist trocken=true.
        k = c.post(f"/api/dokumente/objekte/{slug}/duplikate-buendeln").json()
        assert k["trocken"] is True and len(k["gruppen"]) == 1
        gruppe = k["gruppen"][0]
        assert gruppe["behalten"]["id"] == a
        assert [v["id"] for v in gruppe["verschieben"]] == [b]
        assert len(gruppe["sha1"]) == 40      # SHA1-Hexdigest
        # Trocken ändert nichts — weder Cloud noch Datenbank.
        assert fake.moves == []
        with Session(engine) as s:
            assert s.get(Dokument, b).pfad == "/Obj/eingang/dubl.pdf"


def test_lageplaene_werden_ausgenommen(monkeypatch):
    with TestClient(app) as c:
        slug = _objekt(c, "Duplikat Bündel 5")
        # Zwei byte-gleiche Fotos DESSELBEN Lageplans sind gewollt — kein Duplikat.
        _dokument(slug, "lage1.jpg", "/Obj/10_Fotos_Lage/lage1.jpg",
                  kategorie="Lageplan")
        _dokument(slug, "lage2.jpg", "/Obj/10_Fotos_Lage/lage2.jpg",
                  kategorie="Lageplan")
        fake = _FakeCloud({"/Obj/10_Fotos_Lage/lage1.jpg": b"PLAN",
                           "/Obj/10_Fotos_Lage/lage2.jpg": b"PLAN"})
        monkeypatch.setattr(dok, "verbindung", lambda session: fake)

        r = c.post(f"/api/dokumente/objekte/{slug}/duplikate-buendeln"
                   "?trocken=false").json()
        assert r["gebündelt"] == 0 and fake.moves == []


def test_idempotent_zweiter_lauf_verschiebt_nichts(monkeypatch):
    with TestClient(app) as c:
        slug = _objekt(c, "Duplikat Bündel 6")
        _dokument(slug, "haupt.pdf", "/Obj/60_NK/haupt.pdf")
        b = _dokument(slug, "neben.pdf", "/Obj/eingang/neben.pdf")
        fake = _FakeCloud({"/Obj/60_NK/haupt.pdf": b"IDEM",
                           "/Obj/eingang/neben.pdf": b"IDEM"})
        monkeypatch.setattr(dok, "verbindung", lambda session: fake)

        erst = c.post(f"/api/dokumente/objekte/{slug}/duplikate-buendeln"
                      "?trocken=false").json()
        assert erst["gebündelt"] == 1
        with Session(engine) as s:
            assert s.get(Dokument, b).pfad == "/Obj/99_Duplikate/neben.pdf"

        # Zweiter scharfer Lauf: die verschobene Kopie liegt in 99_Duplikate und
        # wird nicht erneut betrachtet — nichts mehr zu bündeln.
        zweit = c.post(f"/api/dokumente/objekte/{slug}/duplikate-buendeln"
                       "?trocken=false").json()
        assert zweit["gebündelt"] == 0 and zweit["gruppen"] == 0


def test_ohne_cloud_409(monkeypatch):
    with TestClient(app) as c:
        slug = c.post("/api/objekte",
                      json={"name": "Duplikat Ohne Cloud"}).json()["slug"]
        r = c.post(f"/api/dokumente/objekte/{slug}/duplikate-buendeln")
        assert r.status_code == 409


def test_unbekanntes_objekt_404():
    with TestClient(app) as c:
        r = c.post("/api/dokumente/objekte/gibt-es-nicht/duplikate-buendeln")
        assert r.status_code == 404


def test_nicht_ladbarer_beleg_wird_uebersprungen(monkeypatch):
    with TestClient(app) as c:
        slug = _objekt(c, "Duplikat Bündel 7")
        a = _dokument(slug, "da.pdf", "/Obj/da.pdf")
        b = _dokument(slug, "weg.pdf", "/Obj/weg.pdf")
        _dokument(slug, "kopie.pdf", "/Obj/kopie.pdf")
        # „weg.pdf" fehlt im Inhalt → hole scheitert, der Beleg wird übersprungen.
        fake = _FakeCloud({"/Obj/da.pdf": b"A", "/Obj/kopie.pdf": b"A"})
        monkeypatch.setattr(dok, "verbindung", lambda session: fake)

        r = c.post(f"/api/dokumente/objekte/{slug}/duplikate-buendeln"
                   "?trocken=false").json()
        # da.pdf und kopie.pdf sind byte-gleich → eine wandert; weg.pdf steckt
        # als Ladefehler in der Fehlerliste, hält den Lauf aber nicht an.
        assert r["gebündelt"] == 1
        assert any(f["id"] == b for f in r["fehler"])
