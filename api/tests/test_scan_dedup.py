"""CD — beim Scannen keine byte-gleiche Zweitkopie stehen lassen.

Legt der Nutzer denselben Beleg zweimal ab — erst generisch, dann unter einem
detaillierteren Namen —, entstehen zwei byte-identische PDFs. Der zweite Scan
räumt die schlechtere Kopie weg (Keeper-Regel: verbucht > hat Betrag >
detaillierterer Name > neuer). Byte-Gleichheit wird über den Inhalt bewiesen,
nie über den Namen. Der Dedup ist best-effort: schlägt der Cloud-Zugriff fehl,
bleibt der Scan trotzdem erfolgreich und es wird nichts gelöscht.
"""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_scan_dedup.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

import app.routers.dokumente as dok  # noqa: E402
from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Dokument, Objekt  # noqa: E402
from app.nextcloud import NextcloudFehler  # noqa: E402


class _FakeCloud:
    """Nextcloud-Ersatz mit echtem Inhalt, damit SHA1 wirklich gerechnet wird.

    `lege_ab` merkt sich Bytes je Pfad, `hole` gibt sie zurück — so ist die
    Byte-Gleichheit im Dedup inhaltsbasiert und nicht simuliert. `hole` kann
    einen Cloud-Fehler (NextcloudFehler) oder einen harten Absturz (RuntimeError)
    stellen, um die Best-effort-Kapselung zu prüfen."""

    def __init__(self):
        self.inhalt: dict[str, bytes] = {}
        self.geloescht: list[str] = []
        self.ordner: set[str] = set()
        self.hole_fehler = False       # NextcloudFehler in hole
        self.hole_absturz = False      # RuntimeError in hole

    @staticmethod
    def _n(pfad: str) -> str:
        return "/" + pfad.strip("/")

    def liste(self, pfad):
        return []

    def ordner_anlegen(self, pfad):
        self.ordner.add(pfad.strip("/"))
        return True

    def existiert(self, pfad):
        return self._n(pfad) in self.inhalt or pfad.strip("/") in self.ordner

    def lege_ab(self, pfad, inhalt):
        self.inhalt[self._n(pfad)] = inhalt

    def hole(self, pfad):
        if self.hole_absturz:
            raise RuntimeError("Cloud hart abgestürzt")
        if self.hole_fehler:
            raise NextcloudFehler("Cloud gerade nicht erreichbar")
        p = self._n(pfad)
        if p not in self.inhalt:
            raise NextcloudFehler(f"404: {pfad}")
        return self.inhalt[p], "application/pdf"

    def loesche(self, pfad):
        p = self._n(pfad)
        self.geloescht.append(p)
        self.inhalt.pop(p, None)

    def verschiebe(self, von, nach):
        v, n = self._n(von), self._n(nach)
        if v in self.inhalt:
            self.inhalt[n] = self.inhalt.pop(v)

    def finde_nach_checksum(self, wurzel, sha1, max_tiefe=3):
        return None


def _mit_cloud(c, name: str) -> str:
    slug = c.post("/api/objekte", json={"name": name}).json()["slug"]
    with Session(engine) as s:
        o = s.exec(select(Objekt).where(Objekt.slug == slug)).first()
        o.nc_ordner = f"Home/Immobilien/{name}"
        s.add(o)
        s.commit()
    return slug


def _scanne(c, slug, inhalt, beschreibung, **felder):
    daten = {"objekt": slug, "kategorie": "Nebenkosten", "jahr": 2025,
             "beschreibung": beschreibung}
    daten.update(felder)
    return c.post("/api/dokumente/scannen", data=daten,
                  files={"datei": (beschreibung + ".pdf", inhalt,
                                   "application/pdf")})


def _dokumente(slug):
    with Session(engine) as s:
        o = s.exec(select(Objekt).where(Objekt.slug == slug)).first()
        return list(s.exec(select(Dokument).where(Dokument.objekt_id == o.id)))


def test_zweiter_scan_raeumt_die_schlechtere_kopie_weg(monkeypatch):
    """Erst generisch, dann detailliert + verbucht: am Ende bleibt EINE Datei,
    die bessere. Die Rückgabe zeigt den Keeper und meldet die entfernte Dublette."""
    with TestClient(app) as c:
        slug = _mit_cloud(c, "Dedup Heiz 1")
        fake = _FakeCloud()
        monkeypatch.setattr(dok, "verbindung", lambda session: fake)

        r1 = _scanne(c, slug, b"HEIZKOSTEN-PDF", "Heizkosten")
        assert r1.status_code == 201, r1.text
        r2 = _scanne(c, slug, b"HEIZKOSTEN-PDF", "Heizkosten Heizöl",
                     betrag=2895.27, kostenart="Heizöl")
        assert r2.status_code == 201, r2.text

        antwort = r2.json()
        assert antwort["dublette_entfernt"] is True
        # Der detailliertere/verbuchte (längere Name, hat Betrag) bleibt.
        assert "Heiz" in antwort["dateiname"] and "2895" in antwort["dateiname"]

        # Genau eine Datei ist in der Cloud übrig, die generische ist gelöscht.
        assert len(fake.inhalt) == 1
        assert any("Heizkosten.pdf" not in p or "2895" in p for p in fake.inhalt)
        assert fake.geloescht                       # die alte Datei wurde entfernt

        docs = _dokumente(slug)
        assert len(docs) == 1                        # nur der Keeper bleibt
        assert docs[0].id == antwort["id"]


def test_verschiedener_inhalt_bleibt_erhalten(monkeypatch):
    """Zwei verschiedene Inhalte sind keine Dublette — beide bleiben."""
    with TestClient(app) as c:
        slug = _mit_cloud(c, "Dedup Heiz 2")
        fake = _FakeCloud()
        monkeypatch.setattr(dok, "verbindung", lambda session: fake)

        assert _scanne(c, slug, b"INHALT-EINS", "Wasser").status_code == 201
        r2 = _scanne(c, slug, b"INHALT-ZWEI", "Strom")
        assert r2.status_code == 201
        assert r2.json()["dublette_entfernt"] is False

        assert len(fake.inhalt) == 2
        assert fake.geloescht == []
        assert len(_dokumente(slug)) == 2


def test_byte_gleich_trotz_verschiedener_namen(monkeypatch):
    """Byte-Gleichheit zählt der Inhalt, nicht der Name: völlig verschiedene
    Namen, gleicher Inhalt → als Dublette erkannt, eine weicht."""
    with TestClient(app) as c:
        slug = _mit_cloud(c, "Dedup Heiz 3")
        fake = _FakeCloud()
        monkeypatch.setattr(dok, "verbindung", lambda session: fake)

        assert _scanne(c, slug, b"GLEICH", "Kaminkehrer").status_code == 201
        r2 = _scanne(c, slug, b"GLEICH", "Voellig-Anderer-Name-Muell")
        assert r2.status_code == 201
        assert r2.json()["dublette_entfernt"] is True

        assert len(fake.inhalt) == 1
        assert len(_dokumente(slug)) == 1


def test_cloud_fehler_beim_dedup_laesst_scan_erfolgreich(monkeypatch):
    """NextcloudFehler beim Laden im Dedup: der Scan bleibt erfolgreich, es wird
    nichts gelöscht — beide Belege bleiben stehen."""
    with TestClient(app) as c:
        slug = _mit_cloud(c, "Dedup Heiz 4")
        fake = _FakeCloud()
        monkeypatch.setattr(dok, "verbindung", lambda session: fake)

        assert _scanne(c, slug, b"SAME-4", "Erster").status_code == 201
        fake.hole_fehler = True                      # Cloud fällt beim Dedup aus
        r2 = _scanne(c, slug, b"SAME-4", "Zweiter")
        assert r2.status_code == 201, r2.text
        assert r2.json()["dublette_entfernt"] is False

        assert fake.geloescht == []                  # nichts gelöscht
        assert len(fake.inhalt) == 2                 # beide Dateien bleiben
        assert len(_dokumente(slug)) == 2


def test_harter_absturz_im_dedup_bricht_scan_nicht(monkeypatch):
    """Selbst ein unerwarteter Absturz (RuntimeError) im Dedup darf den Upload
    nie scheitern lassen — alles bleibt bestehen, der Scan meldet 201."""
    with TestClient(app) as c:
        slug = _mit_cloud(c, "Dedup Heiz 5")
        fake = _FakeCloud()
        monkeypatch.setattr(dok, "verbindung", lambda session: fake)

        assert _scanne(c, slug, b"SAME-5", "Erster").status_code == 201
        fake.hole_absturz = True
        r2 = _scanne(c, slug, b"SAME-5", "Zweiter")
        assert r2.status_code == 201, r2.text
        assert r2.json()["dublette_entfernt"] is False

        assert fake.geloescht == []
        assert len(fake.inhalt) == 2
        assert len(_dokumente(slug)) == 2
