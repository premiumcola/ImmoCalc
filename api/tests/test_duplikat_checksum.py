"""CCCLXXXVI — byte-exakte Duplikaterkennung von Belegen.

Nextcloud liefert je Datei eine SHA1-Prüfsumme (`oc:checksums`). Daran lässt
sich vor dem Hochladen fragen, ob genau diese Datei schon in der Cloud liegt.
Drei Dinge werden hier abgesichert:

  * die SHA1-Extraktion aus der PROPFIND-Antwort,
  * `finde_nach_checksum` (rein lesend, rekursiv),
  * `POST /api/dokumente/vorhandenen-zuordnen` ist idempotent und legt nie
    doppelt an — und fasst die Cloud dabei nie schreibend an.
"""
import os
import sys
import tempfile
from types import SimpleNamespace

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(),
                                     "test_duplikat_checksum.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Dokument, Objekt  # noqa: E402
from app.nextcloud import Eintrag, Nextcloud, _sha1_aus_checksums  # noqa: E402


# --------------------------------------------------------------------------
# SHA1-Extraktion aus dem oc:checksum-Feld
# --------------------------------------------------------------------------

def test_sha1_token_wird_case_insensitiv_gezogen():
    # Nextcloud legt mehrere Prüfsummen whitespace-getrennt ab.
    assert _sha1_aus_checksums("SHA1:AbC123 MD5:deadbeef ADLER32:1") == "abc123"
    # Reihenfolge egal, Kleinschreibung des Tokens egal.
    assert _sha1_aus_checksums("md5:x sha1:DEAD00") == "dead00"
    # Fehlt SHA1 (oder das Feld ganz), kommt leer heraus.
    assert _sha1_aus_checksums("MD5:deadbeef") == ""
    assert _sha1_aus_checksums(None) == ""
    assert _sha1_aus_checksums("") == ""


def _propfind_xml(dateien: list[tuple[str, str | None]]) -> str:
    """Baut eine PROPFIND-Antwort. `dateien`: (relativer Name, checksum-Text)."""
    zeilen = []
    for name, checksum in dateien:
        pruef = (f"<oc:checksums><oc:checksum>{checksum}</oc:checksum>"
                 "</oc:checksums>") if checksum is not None else ""
        zeilen.append(
            "<d:response>"
            f"<d:href>/remote.php/dav/files/user/Ordner/{name}</d:href>"
            "<d:propstat><d:prop>"
            "<d:resourcetype/>"
            "<d:getcontentlength>1234</d:getcontentlength>"
            f"{pruef}"
            "</d:prop></d:propstat></d:response>")
    return ('<?xml version="1.0"?>'
            '<d:multistatus xmlns:d="DAV:" xmlns:oc="http://owncloud.org/ns">'
            + "".join(zeilen) + "</d:multistatus>")


def _client() -> Nextcloud:
    return Nextcloud(url="https://host", benutzer="user", passwort="x")


def test_liste_fuellt_sha1_aus_propfind(monkeypatch):
    c = _client()
    xml = _propfind_xml([("mit.pdf", "SHA1:abc123 MD5:d"),
                         ("ohne.pdf", None)])
    monkeypatch.setattr(c, "_anfrage",
                        lambda *a, **k: SimpleNamespace(status_code=207, text=xml))

    nach_name = {e.name: e for e in c.liste("Ordner")}
    assert nach_name["mit.pdf"].sha1 == "abc123"
    # Ohne oc:checksums bleibt sha1 leer — nicht jede Datei hat eine.
    assert nach_name["ohne.pdf"].sha1 == ""


# --------------------------------------------------------------------------
# finde_nach_checksum — rekursiv, rein lesend
# --------------------------------------------------------------------------

def test_finde_nach_checksum_trifft_in_unterordner(monkeypatch):
    c = _client()
    baum = {
        "/Objekt": [Eintrag("60_NK", "/Objekt/60_NK", True),
                    Eintrag("lose.pdf", "/Objekt/lose.pdf", False, 10, "aaaa")],
        "/Objekt/60_NK": [Eintrag("rechnung.pdf", "/Objekt/60_NK/rechnung.pdf",
                                  False, 20, "beef99")],
    }
    monkeypatch.setattr(c, "liste", lambda pfad: baum.get(pfad, []))

    treffer = c.finde_nach_checksum("Objekt", "BEEF99")
    assert treffer is not None
    assert treffer.pfad == "/Objekt/60_NK/rechnung.pdf"


def test_finde_nach_checksum_ohne_treffer_und_leer(monkeypatch):
    c = _client()
    baum = {"/Objekt": [Eintrag("a.pdf", "/Objekt/a.pdf", False, 1, "1111")]}
    monkeypatch.setattr(c, "liste", lambda pfad: baum.get(pfad, []))

    assert c.finde_nach_checksum("Objekt", "9999") is None
    # Leere Prüfsumme: nichts zu suchen.
    assert c.finde_nach_checksum("Objekt", "") is None


def test_finde_nach_checksum_ueberspringt_kaputten_unterordner(monkeypatch):
    from app.nextcloud import NextcloudFehler

    c = _client()

    def _liste(pfad):
        if pfad == "/Objekt":
            return [Eintrag("kaputt", "/Objekt/kaputt", True),
                    Eintrag("gut", "/Objekt/gut", True)]
        if pfad == "/Objekt/kaputt":
            raise NextcloudFehler("nicht lesbar")
        if pfad == "/Objekt/gut":
            return [Eintrag("z.pdf", "/Objekt/gut/z.pdf", False, 5, "cafe")]
        return []

    monkeypatch.setattr(c, "liste", _liste)
    treffer = c.finde_nach_checksum("Objekt", "cafe")
    assert treffer is not None and treffer.name == "z.pdf"


# --------------------------------------------------------------------------
# vorhandenen-zuordnen — idempotent, ohne Upload
# --------------------------------------------------------------------------

def _mit_cloud(c: TestClient, name: str) -> str:
    slug = c.post("/api/objekte", json={"name": name}).json()["slug"]
    with Session(engine) as s:
        o = s.exec(select(Objekt).where(Objekt.slug == slug)).first()
        o.nc_ordner = f"Home/Immobilien/{name}"
        s.add(o)
        s.commit()
    return slug


def test_vorhandenen_zuordnen_ist_idempotent():
    with TestClient(app) as c:
        slug = _mit_cloud(c, "Duplikatweg 1")
        pfad = "/Home/Immobilien/Duplikatweg 1/60_Nebenkosten/2024/rg.pdf"
        body = {"objekt": slug, "pfad": pfad, "kategorie": "Nebenkosten"}

        erst = c.post("/api/dokumente/vorhandenen-zuordnen", json=body)
        assert erst.status_code == 200
        k1 = erst.json()
        assert k1["vorhanden"] is True and k1["abgelegt"] is True
        assert k1["dateiname"] == "rg.pdf"

        # Zweiter Aufruf: derselbe Datensatz, kein Duplikat.
        zweit = c.post("/api/dokumente/vorhandenen-zuordnen", json=body)
        assert zweit.status_code == 200
        assert zweit.json()["id"] == k1["id"]

        with Session(engine) as s:
            treffer = s.exec(select(Dokument).where(
                Dokument.pfad == pfad)).all()
            assert len(treffer) == 1
            assert treffer[0].status == "zugeordnet"
            assert treffer[0].kategorie == "Nebenkosten"


def test_vorhandenen_zuordnen_ergaenzt_zeitraum_additiv():
    from datetime import date
    from app.models import Zeitraum

    with TestClient(app) as c:
        slug = _mit_cloud(c, "Duplikatweg 2")
        with Session(engine) as s:
            o = s.exec(select(Objekt).where(Objekt.slug == slug)).first()
            z = Zeitraum(objekt_id=o.id, start=date(2024, 1, 1),
                         ende=date(2024, 12, 31))
            s.add(z)
            s.commit()
            s.refresh(z)
            zid = z.id
        pfad = "/Home/Immobilien/Duplikatweg 2/60_Nebenkosten/2024/wasser.pdf"

        # Erst ohne Zeitraum anlegen …
        c.post("/api/dokumente/vorhandenen-zuordnen",
               json={"objekt": slug, "pfad": pfad})
        # … dann mit Zeitraum nachziehen — additiv gesetzt, nichts verdoppelt.
        r = c.post("/api/dokumente/vorhandenen-zuordnen",
                   json={"objekt": slug, "pfad": pfad, "zeitraum_id": zid})
        assert r.status_code == 200

        with Session(engine) as s:
            treffer = s.exec(select(Dokument).where(
                Dokument.pfad == pfad)).all()
            assert len(treffer) == 1
            assert treffer[0].zeitraum_id == zid


def test_vorhandenen_zuordnen_unbekanntes_objekt_404():
    with TestClient(app) as c:
        r = c.post("/api/dokumente/vorhandenen-zuordnen",
                   json={"objekt": "gibt-es-nicht", "pfad": "/x/y.pdf"})
        assert r.status_code == 404


# --------------------------------------------------------------------------
# duplikat-pruefen — Fund, Zielordner-Lage, ohne Cloud
# --------------------------------------------------------------------------

class _FakeClient:
    """Nextcloud-Ersatz: kennt einen Fund und liefert leere Ordnerlisten."""

    def __init__(self, treffer: Eintrag | None):
        self._treffer = treffer

    def liste(self, pfad):
        return []

    def finde_nach_checksum(self, wurzel, sha1, max_tiefe=3):
        return self._treffer


def test_duplikat_pruefen_ohne_cloud_409():
    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={"name": "Ohne Cloud"}).json()["slug"]
        r = c.post("/api/dokumente/duplikat-pruefen",
                   json={"objekt": slug, "sha1": "abc"})
        assert r.status_code == 409


def test_duplikat_pruefen_meldet_fund_ausserhalb_ziel(monkeypatch):
    import app.routers.dokumente as modul

    with TestClient(app) as c:
        slug = _mit_cloud(c, "Prüfweg 3")
        fund = Eintrag("alt.pdf",
                       "/Home/Immobilien/Prüfweg 3/99_Sonstiges/alt.pdf",
                       False, 30, "feed01")
        monkeypatch.setattr(modul, "verbindung",
                            lambda session: _FakeClient(fund))

        r = c.post("/api/dokumente/duplikat-pruefen",
                   json={"objekt": slug, "sha1": "feed01", "jahr": 2024})
        assert r.status_code == 200
        k = r.json()
        assert k["gefunden"] is True
        assert k["dateiname"] == "alt.pdf"
        # liegt in 99_Sonstiges, nicht im NK-Jahr-Ordner
        assert k["im_ziel_ordner"] is False
        # noch kein Dokument-Eintrag darauf
        assert k["schon_erfasst"] is False and k["dokument_id"] is None


def test_duplikat_pruefen_ohne_fund(monkeypatch):
    import app.routers.dokumente as modul

    with TestClient(app) as c:
        slug = _mit_cloud(c, "Prüfweg 4")
        monkeypatch.setattr(modul, "verbindung",
                            lambda session: _FakeClient(None))

        r = c.post("/api/dokumente/duplikat-pruefen",
                   json={"objekt": slug, "sha1": "0000"})
        assert r.status_code == 200
        k = r.json()
        assert k == {"gefunden": False, "pfad": None, "dateiname": None,
                     "im_ziel_ordner": False, "schon_erfasst": False,
                     "dokument_id": None}
