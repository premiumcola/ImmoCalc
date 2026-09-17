"""N483 — der Korrekturlauf `POST /api/dokumente/namen-richten`.

Die Namensregel ist mit N483 berichtigt (`namen.py`), aber die bereits
abgelegten Dateien hiessen weiter falsch — ein Mietvertrag trug die Kostenart
„Gebäudehaftpflicht" mitten im Namen. Dieser Lauf zieht den Bestand nach.

Die Cloud wird hier nicht durch eine Attrappe ersetzt, sondern durch die echte
`Nextcloud`-Klasse mit ausgetauschter HTTP-Schicht — dasselbe Vorgehen wie in
`test_beleg_umbenennen.py` und aus demselben Grund: so gilt im Test derselbe
Schreibrecht-Riegel wie in der Anwendung.

Der wichtigste Test dieser Datei ist NICHT der Erfolgsfall, sondern
`test_der_lauf_fasst_die_dateien_einer_fremden_familie_nicht_an`: ein Lauf
über den Bestand hat den Schutz von `deps.dokument_holen` nicht von selbst.
"""
import os
import sys
import tempfile
from datetime import date
from types import SimpleNamespace
from urllib.parse import unquote

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_namen_richten.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

import app.routers.dokumente as modul  # noqa: E402
from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Dokument, Familie, Objekt  # noqa: E402
from app.nextcloud import Nextcloud  # noqa: E402

# Die Datenbank enthaelt ausserdem die Seed-Immobilien der Demo, deren Belege
# ausserhalb des Home-Ordners liegen. Der Lauf nimmt sie mit und meldet sie als
# Fehler — richtig so. Die Tests machen ihre Aussagen deshalb am EIGENEN Beleg
# fest und nicht an Gesamtzahlen.
def _eintrag(liste, doc_id):
    return next((e for e in liste if e["id"] == doc_id), None)


HEIM = "/Home"
FALSCH = "2014-09_Miete-Gebäudehaftpflicht-Jana.Meinecke.signed-bis.08.pdf"
RICHTIG = "2014-09_Miete-Jana.Meinecke.signed-bis.08.pdf"


class Wolke(Nextcloud):
    """Echte Nextcloud — nur die HTTP-Schicht antwortet aus dem Gedächtnis."""

    def __init__(self, move_status: int = 201):
        super().__init__("https://cloud.test", "nutzer", "geheim", heimat=HEIM)
        self.move_status = move_status
        self.verschoben: list[tuple[str, str]] = []

    def _anfrage(self, methode: str, pfad: str, **kw):
        if methode == "PROPFIND":
            return SimpleNamespace(status_code=404, text="")   # nichts belegt
        if methode == "MOVE":
            if self.move_status < 400:
                ziel = unquote(kw["headers"]["Destination"])
                self.verschoben.append((pfad.strip("/"),
                                        ziel.split("/files/nutzer/", 1)[-1]))
            return SimpleNamespace(status_code=self.move_status, text="")
        return SimpleNamespace(status_code=200, text="")


@pytest.fixture
def wolke(monkeypatch):
    def bauen(**kw) -> Wolke:
        w = Wolke(**kw)
        monkeypatch.setattr(modul, "verbindung", lambda session: w)
        return w
    return bauen


def _beleg(c, ort: str, name: str = FALSCH, **felder) -> int:
    """Immobilie mit einem abgelegten Beleg; gibt die Dokument-id."""
    slug = c.post("/api/objekte", json={"name": ort}).json()["slug"]
    ordner = f"Home/Immobilien/{ort}/30_Vermietung_Verpachtung"
    with Session(engine) as s:
        o = s.exec(select(Objekt).where(Objekt.slug == slug)).first()
        o.nc_ordner = f"Home/Immobilien/{ort}"
        s.add(o)
        felder.setdefault("kategorie", "Mietvertrag")
        felder.setdefault("kostenart", "Gebäudehaftpflicht")
        felder.setdefault("jahr", 2014)
        felder.setdefault("belegdatum", date(2014, 9, 1))
        felder.setdefault("status", "zugeordnet")
        d = Dokument(pfad=f"/{ordner}/{name}", dateiname=name, groesse=1234,
                     objekt_id=o.id, erkannt_am=date.today(), **felder)
        s.add(d)
        s.commit()
        s.refresh(d)
        return d.id


def _name(doc_id: int) -> str:
    with Session(engine) as s:
        return s.get(Dokument, doc_id).dateiname


# ---- N483 — der Plan --------------------------------------------------

def test_trocken_ist_die_vorgabe_und_aendert_nichts(wolke):
    """Ein Lauf, der Dateien anfasst, darf nie versehentlich losgehen."""
    w = wolke()
    with TestClient(app) as c:
        doc = _beleg(c, "Trockenlauf")
        antwort = c.post("/api/dokumente/namen-richten").json()
    assert antwort["trocken"] is True
    meiner = _eintrag(antwort["plan"], doc)
    assert meiner and meiner["alt"] == FALSCH and meiner["neu"] == RICHTIG
    assert w.verschoben == []
    assert _name(doc) == FALSCH


# ---- N483 — die Ausführung --------------------------------------------

def test_der_lauf_nimmt_die_kostenart_aus_dem_namen(wolke):
    w = wolke()
    with TestClient(app) as c:
        doc = _beleg(c, "Ausfuehrung")
        antwort = c.post("/api/dokumente/namen-richten?trocken=false").json()
    assert antwort["trocken"] is False
    meiner = _eintrag(antwort["umbenannt"], doc)
    assert meiner and meiner["neu"] == RICHTIG
    assert _name(doc) == RICHTIG
    assert (f"Home/Immobilien/Ausfuehrung/30_Vermietung_Verpachtung/{FALSCH}",
            f"Home/Immobilien/Ausfuehrung/30_Vermietung_Verpachtung/{RICHTIG}"
            ) in w.verschoben


def test_ein_zweiter_lauf_findet_nichts_mehr(wolke):
    """Idempotenz — sonst wächst der Name bei jedem Lauf weiter."""
    wolke()
    with TestClient(app) as c:
        doc = _beleg(c, "Zweimal")
        c.post("/api/dokumente/namen-richten?trocken=false")
        zweiter = c.post("/api/dokumente/namen-richten").json()
    assert _eintrag(zweiter["plan"], doc) is None


def test_ein_nebenkostenbeleg_behaelt_seine_kostenart(wolke):
    """Die Gegenprobe: unter Nebenkosten trägt die Kostenart die
    Unterscheidung und muss im Namen bleiben."""
    wolke()
    name = "2025-03_NK-Schornsteinfeger.pdf"
    with TestClient(app) as c:
        doc = _beleg(c, "Nebenkosten-Fall", name=name, kategorie="Nebenkosten",
                     kostenart="Schornsteinfeger", jahr=2025,
                     belegdatum=date(2025, 3, 1))
        c.post("/api/dokumente/namen-richten?trocken=false")
    assert _name(doc) == name


def test_ein_gescheiterter_move_laesst_datei_und_eintrag_unberuehrt(wolke):
    """Fällt die Cloud aus, darf die Datenbank keinen Namen führen, den es in
    der Cloud nicht gibt — und der Lauf muss trotzdem weiterlaufen."""
    wolke(move_status=507)
    with TestClient(app) as c:
        doc = _beleg(c, "Cloud-Ausfall")
        antwort = c.post("/api/dokumente/namen-richten?trocken=false").json()
    assert _eintrag(antwort["umbenannt"], doc) is None
    assert _eintrag(antwort["fehler"], doc) is not None
    assert _name(doc) == FALSCH


# ---- N483 — die Grenze zur fremden Familie ----------------------------

def test_der_lauf_fasst_die_dateien_einer_fremden_familie_nicht_an(wolke):
    """N436 — `deps.dokument_holen` schützt Einzelzugriffe. Ein Lauf über
    `select(Dokument)` hat diesen Schutz NICHT von selbst; genau das war beim
    Vorbild `praefix-entfernen` der Fall und ist mit N483 geschlossen."""
    w = wolke()
    with TestClient(app) as c:
        eigen = _beleg(c, "Eigenes Haus")
        fremd = _beleg(c, "Fremdes Haus")
        # Das zweite Objekt einer anderen Familie zuschlagen.
        with Session(engine) as s:
            andere = Familie(name="Andere Familie")
            s.add(andere)
            s.commit()
            s.refresh(andere)
            d = s.get(Dokument, fremd)
            o = s.get(Objekt, d.objekt_id)
            o.familie_id = andere.id
            s.add(o)
            s.commit()
        antwort = c.post("/api/dokumente/namen-richten?trocken=false").json()

    assert _eintrag(antwort["umbenannt"], eigen) is not None
    assert _eintrag(antwort["umbenannt"], fremd) is None
    assert _eintrag(antwort["fehler"], fremd) is None, "fremde Datei angefasst"
    assert _name(eigen) == RICHTIG
    assert _name(fremd) == FALSCH, "die fremde Datei wurde umbenannt"
    assert not any("Fremdes Haus" in alt for alt, _neu in w.verschoben)
