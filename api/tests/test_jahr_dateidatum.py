"""CCCLXXXIV — das Datei-Datum als Jahres-Rückfall.

Wenn aus dem Dateinamen kein plausibles Jahr ableitbar ist, soll das Datei-
Erstellungs-/Änderungsdatum als Jahr herangezogen werden — dann entsteht ein
Unsinnsjahr wie 2045 (die ersten vier Stellen einer Artikelnummer) gar nicht
erst. Der Name behält seinen Vorrang, solange er ein plausibles Jahr hergibt;
das Datei-Datum ist ausschließlich Rückfall.

Zwei Ebenen werden geprüft:
  * `_jahr_mit_fallback` — die reine Vorrang-Regel.
  * `POST /api/dokumente/scannen` — der Upload-Weg reicht das vom Browser
    mitgeschickte `datei_jahr` genau so durch (und bestehende Aufrufe bleiben
    unverändert).
"""
import os
import sys
import tempfile
from datetime import date

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_jahr_dateidatum.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Dokument, Objekt  # noqa: E402
from app.routers.dokumente import _jahr_mit_fallback  # noqa: E402


# --------------------------------------------------------------------------
# Die reine Vorrang-Regel
# --------------------------------------------------------------------------

def test_namensjahr_gewinnt_gegen_dateidatum():
    # Name mit plausiblem Jahr -> das Namensjahr gilt, das Datei-Datum tritt
    # gar nicht erst an.
    assert _jahr_mit_fallback(None, "2023-05_Rechnung.pdf", 2019) == 2023


def test_ohne_jahr_im_namen_zieht_das_dateidatum():
    # Kein Jahr im Namen + Datei-Datum 2023 -> Jahr 2023.
    assert _jahr_mit_fallback(None, "Rechnung.pdf", 2023) == 2023


def test_unplausibles_namensjahr_weicht_dem_dateidatum():
    # „2045_204596-…" ist eine Artikelnummer, kein Datum. Unplausibles
    # Namensjahr + Datei-Datum 2024 -> 2024.
    assert _jahr_mit_fallback(None, "2045_204596-00-GPIE.jpg", 2024) == 2024


def test_ausgewaehltes_jahr_bleibt_vorrangig():
    # Ein bereits feststehendes (ausgewähltes oder erkanntes) Jahr behält den
    # Vorrang vor dem Datei-Datum.
    assert _jahr_mit_fallback(2022, "2023-05_Rechnung.pdf", 2019) == 2022


def test_unplausibles_dateidatum_wird_nicht_genommen():
    # Ein unsinniges Datei-Datum ist kein besserer Rückfall als gar keins.
    fern = date.today().year + 20
    assert _jahr_mit_fallback(None, "Rechnung.pdf", fern) is None
    # Ohne jeden Anhaltspunkt bleibt es schlicht bei None (Ordner „ohne-Jahr").
    assert _jahr_mit_fallback(None, "Rechnung.pdf", None) is None


# --------------------------------------------------------------------------
# Der Upload-Weg: /api/dokumente/scannen reicht datei_jahr durch
# --------------------------------------------------------------------------

class _Wolke:
    """Nextcloud-Ersatz: nimmt alles an, löscht nie."""

    def liste(self, pfad):
        return []

    def ordner_anlegen(self, pfad):
        return True

    def existiert(self, pfad):
        return False

    def verschiebe(self, von, nach):
        pass

    def lege_ab(self, pfad, inhalt):
        pass


def _mit_cloud(c, name: str) -> str:
    slug = c.post("/api/objekte", json={"name": name}).json()["slug"]
    with Session(engine) as s:
        o = s.exec(select(Objekt).where(Objekt.slug == slug)).first()
        o.nc_ordner = f"Home/Immobilien/{name}"
        s.add(o)
        s.commit()
    return slug


def _dokument_jahr(dokument_id: int) -> int | None:
    with Session(engine) as s:
        return s.get(Dokument, dokument_id).jahr


def test_scannen_nimmt_dateidatum_bei_unsinns_namen(monkeypatch):
    """Ein Foto mit Artikelnummer-Namen und ohne Jahr: das mitgeschickte
    Datei-Datum 2024 wird zum Jahr — kein Unsinnsjahr 2045."""
    import app.routers.dokumente as modul

    with TestClient(app) as c:
        slug = _mit_cloud(c, "Fotoweg 1")
        monkeypatch.setattr(modul, "verbindung", lambda session: _Wolke())

        antwort = c.post(
            "/api/dokumente/scannen",
            data={"objekt": slug, "kategorie": "Sonstiges", "datei_jahr": 2024},
            files={"datei": ("2045_204596-00-GPIE.jpg", b"\xff\xd8\xff data",
                             "image/jpeg")})
        assert antwort.status_code == 201
        assert _dokument_jahr(antwort.json()["id"]) == 2024


def test_scannen_namensjahr_schlaegt_dateidatum(monkeypatch):
    """Steht ein plausibles Jahr im Namen, gewinnt es — das Datei-Datum wird
    ignoriert."""
    import app.routers.dokumente as modul

    with TestClient(app) as c:
        slug = _mit_cloud(c, "Fotoweg 2")
        monkeypatch.setattr(modul, "verbindung", lambda session: _Wolke())

        antwort = c.post(
            "/api/dokumente/scannen",
            data={"objekt": slug, "kategorie": "Sonstiges", "datei_jahr": 2019},
            files={"datei": ("2023-05_Rechnung.pdf", b"%PDF-1.4 x",
                             "application/pdf")})
        assert antwort.status_code == 201
        assert _dokument_jahr(antwort.json()["id"]) == 2023


def test_scannen_ausgewaehltes_jahr_bleibt_vorrangig(monkeypatch):
    """Ein ausdrücklich mitgegebenes Jahr behält den Vorrang vor beidem —
    Datei-Datum wie Namensjahr."""
    import app.routers.dokumente as modul

    with TestClient(app) as c:
        slug = _mit_cloud(c, "Fotoweg 3")
        monkeypatch.setattr(modul, "verbindung", lambda session: _Wolke())

        antwort = c.post(
            "/api/dokumente/scannen",
            data={"objekt": slug, "kategorie": "Sonstiges", "jahr": 2022,
                  "datei_jahr": 2019},
            files={"datei": ("2023-05_Rechnung.pdf", b"%PDF-1.4 x",
                             "application/pdf")})
        assert antwort.status_code == 201
        assert _dokument_jahr(antwort.json()["id"]) == 2022


def test_scannen_ohne_dateidatum_bleibt_wie_bisher(monkeypatch):
    """Wächter: das neue Feld ist rein additiv. Ein Aufruf ohne `datei_jahr`
    und ohne Jahr im Namen läuft unverändert — der Beleg landet ohne Jahr."""
    import app.routers.dokumente as modul

    with TestClient(app) as c:
        slug = _mit_cloud(c, "Fotoweg 4")
        monkeypatch.setattr(modul, "verbindung", lambda session: _Wolke())

        antwort = c.post(
            "/api/dokumente/scannen",
            data={"objekt": slug, "kategorie": "Sonstiges"},
            files={"datei": ("scan.pdf", b"%PDF-1.4 x", "application/pdf")})
        assert antwort.status_code == 201
        assert _dokument_jahr(antwort.json()["id"]) is None
