"""N261 — einen bereits abgelegten Beleg nachträglich umbenennen.

Der Nutzer wollte den Namen eines abgelegten Belegs korrigieren; es gab dafür
keinen Weg, sein Versuch landete als „_348_" im Dateinamen statt im Betrag.
`PATCH /api/dokumente/{id}/name` schliesst die Lücke — mit derselben
Namensregel (`dateiname`), die auch `/scannen` und `/namensvorschlag` benutzen.

Der wichtigste Teil dieser Datei ist NICHT der Erfolgsfall, sondern der
Ausfall: fällt die Cloud aus, darf die Datenbank keinen Namen führen, den es
in der Cloud nicht gibt. Deshalb prüft jeder Fehlerfall beides — Datei UND
Eintrag.

Die Cloud wird hier nicht durch eine Attrappe ersetzt, sondern durch die echte
`Nextcloud`-Klasse mit ausgetauschter HTTP-Schicht. So gilt im Test derselbe
Schreibrecht-Riegel (`_pruefe_schreibrecht`) wie in der Anwendung — eine
Attrappe hätte ihn wegdefiniert und genau den Riegel ungeprüft gelassen, der
die echten Nutzerdaten schützt.
"""
import os
import sys
import tempfile
from datetime import date
from types import SimpleNamespace
from urllib.parse import unquote

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_beleg_umbenennen.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

import app.routers.dokumente as modul  # noqa: E402
from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Dokument, Objekt  # noqa: E402
from app.nextcloud import Nextcloud  # noqa: E402

HEIM = "/Home"
START = "2025_NK-Kaminkehrer.pdf"


class Wolke(Nextcloud):
    """Echte Nextcloud — nur die HTTP-Schicht antwortet aus dem Gedächtnis.

    `vorhanden` sind die Pfade, die die Cloud als belegt meldet (PROPFIND);
    `move_status` lässt einen MOVE scheitern (507 = die Cloud kann nicht).
    """

    def __init__(self, heimat: str = HEIM, vorhanden=(), move_status: int = 201):
        super().__init__("https://cloud.test", "nutzer", "geheim", heimat=heimat)
        self.vorhanden = {p.strip("/") for p in vorhanden}
        self.move_status = move_status
        self.verschoben: list[tuple[str, str]] = []

    def _anfrage(self, methode: str, pfad: str, **kw):
        if methode == "PROPFIND":
            da = pfad.strip("/") in self.vorhanden
            return SimpleNamespace(status_code=207 if da else 404, text="")
        if methode == "MOVE":
            # `verschiebe` hat den Schreibrecht-Riegel schon passiert — was hier
            # ankommt, liegt nachweislich unterhalb des Home-Ordners.
            if self.move_status < 400:
                ziel = unquote(kw["headers"]["Destination"])
                self.verschoben.append((pfad.strip("/"),
                                        ziel.split("/files/nutzer/", 1)[-1]))
            return SimpleNamespace(status_code=self.move_status, text="")
        return SimpleNamespace(status_code=200, text="")


@pytest.fixture
def wolke(monkeypatch):
    """Die Cloud dieses Tests — je Test frisch, an den Router gehängt."""
    def bauen(**kw) -> Wolke:
        w = Wolke(**kw)
        monkeypatch.setattr(modul, "verbindung", lambda session: w)
        return w
    return bauen


def _umgebung(c, ort: str, name: str = START, stamm: str = "",
              **felder) -> tuple[int, str]:
    """Immobilie mit einem abgelegten Beleg. Gibt `(dokument_id, ordner)`.

    `ort` macht Objekt und Ordner je Test eindeutig — der Pfad trägt in der
    Datenbank einen Unique-Index, zwei Tests dürfen sich nicht denselben
    Ablageort teilen."""
    slug = c.post("/api/objekte", json={"name": ort}).json()["slug"]
    ordner = f"{stamm or 'Home/Immobilien'}/{ort}/60_Nebenkosten/2025"
    with Session(engine) as s:
        o = s.exec(select(Objekt).where(Objekt.slug == slug)).first()
        o.nc_ordner = f"Home/Immobilien/{ort}"
        s.add(o)
        felder.setdefault("kategorie", "Nebenkosten")
        felder.setdefault("jahr", 2025)
        felder.setdefault("status", "zugeordnet")
        d = Dokument(pfad=f"/{ordner}/{name}", dateiname=name, groesse=1234,
                     objekt_id=o.id, erkannt_am=date.today(), **felder)
        s.add(d)
        s.commit()
        s.refresh(d)
        return d.id, ordner


def _stand(doc_id: int) -> tuple[str, str]:
    with Session(engine) as s:
        d = s.get(Dokument, doc_id)
        return d.dateiname, d.pfad


def _pfad_setzen(doc_id: int, pfad: str) -> None:
    with Session(engine) as s:
        d = s.get(Dokument, doc_id)
        d.pfad = pfad
        s.add(d)
        s.commit()


# --------------------------------------------------------------------------
# Der Rundlauf
# --------------------------------------------------------------------------

def test_umbenennen_setzt_datum_und_betrag_selbst(wolke):
    """Der Nutzer schreibt nur die Sache — Datum vorn, Betrag hinten setzt
    `dateiname`. Genau das verhindert das „_348_" mitten im Namen."""
    with TestClient(app) as c:
        w = wolke()
        doc, ordner = _umgebung(c, "Rundlaufweg 1", betrag=348.0,
                                kostenart="Kaminkehrer")

        antwort = c.patch(f"/api/dokumente/{doc}/name",
                          json={"beschreibung": "Kaminkehrer Musterfirma"})
        assert antwort.status_code == 200
        neu = "2025_NK-Kaminkehrer-Musterfirma_348,00€.pdf"
        assert antwort.json() == {"dateiname": neu, "pfad": f"/{ordner}/{neu}",
                                  "geaendert": True}
        # Der Ordner bleibt, wo er war — umbenannt wird, nicht umgehängt.
        assert w.verschoben == [(f"{ordner}/{START}", f"{ordner}/{neu}")]
        # Und die Datenbank führt genau das, was in der Cloud liegt.
        assert _stand(doc) == (neu, f"/{ordner}/{neu}")


def test_endung_wird_nicht_verdoppelt(wolke):
    """Tippt der Nutzer die Endung mit, steht sie danach trotzdem einmal da.

    Abgeschnitten wird nur die ECHTE Endung dieser Datei, nicht am letzten
    Punkt getrennt: „Rechnung Fa. Müller.pdf" behält den Müller (aus dem Punkt
    in „Fa." macht die Namenssäuberung ohnehin einen Bindestrich)."""
    with TestClient(app) as c:
        wolke()
        doc, _ = _umgebung(c, "Endungsweg 2")
        antwort = c.patch(f"/api/dokumente/{doc}/name",
                          json={"beschreibung": "Rechnung Fa. Müller.pdf"})
        assert antwort.status_code == 200
        assert antwort.json()["dateiname"] == "2025_NK-Rechnung-Fa-Müller.pdf"


def test_gleicher_name_faesst_die_cloud_nicht_an(wolke):
    """Idempotent: wer nichts ändert, löst keinen MOVE aus."""
    with TestClient(app) as c:
        w = wolke()
        doc, _ = _umgebung(c, "Ruheweg 3")
        antwort = c.patch(f"/api/dokumente/{doc}/name",
                          json={"beschreibung": "Kaminkehrer"})
        assert antwort.status_code == 200
        assert antwort.json()["geaendert"] is False
        assert w.verschoben == []


def test_leerer_name_wird_abgelehnt(wolke):
    with TestClient(app) as c:
        w = wolke()
        doc, _ = _umgebung(c, "Leerweg 4")
        antwort = c.patch(f"/api/dokumente/{doc}/name",
                          json={"beschreibung": "  "})
        assert antwort.status_code == 400
        assert w.verschoben == []
        assert _stand(doc)[0] == START


# --------------------------------------------------------------------------
# Nie überschreiben, nie löschen
# --------------------------------------------------------------------------

def test_belegter_zielname_bekommt_ein_suffix(wolke):
    """Liegt dort schon eine Datei, wird sie NICHT überschrieben — der Beleg
    weicht auf „…-2" aus (`_freier_name`, live gegen die Cloud gefragt)."""
    with TestClient(app) as c:
        ort = "Kollisionsweg 5"
        belegt = f"Home/Immobilien/{ort}/60_Nebenkosten/2025/2025_NK-Wasser.pdf"
        w = wolke(vorhanden=[belegt])
        doc, ordner = _umgebung(c, ort)

        antwort = c.patch(f"/api/dokumente/{doc}/name",
                          json={"beschreibung": "Wasser"})
        assert antwort.status_code == 200
        assert antwort.json()["dateiname"] == "2025_NK-Wasser-2.pdf"
        assert w.verschoben == [(f"{ordner}/{START}",
                                 f"{ordner}/2025_NK-Wasser-2.pdf")]


# --------------------------------------------------------------------------
# Der wichtigste Teil: kein halber Zustand
# --------------------------------------------------------------------------

def test_cloud_ausfall_laesst_datei_und_eintrag_unveraendert(wolke):
    """MOVE scheitert → 502 im Klartext, und weder Datei noch Eintrag haben
    sich bewegt. Ein Eintrag mit einem Namen, den es in der Cloud nicht gibt,
    wäre ein verlorener Beleg."""
    with TestClient(app) as c:
        w = wolke(move_status=507)
        doc, _ = _umgebung(c, "Ausfallweg 6")
        vorher = _stand(doc)

        antwort = c.patch(f"/api/dokumente/{doc}/name",
                          json={"beschreibung": "Schornsteinfeger"})
        assert antwort.status_code == 502
        detail = antwort.json()["detail"]
        assert "nicht umbenannt" in detail
        assert START in detail                  # der Name, der bleibt
        assert w.verschoben == []
        assert _stand(doc) == vorher


def test_schreibrecht_riegel_greift_weiterhin(wolke):
    """Ein Beleg ausserhalb des Home-Ordners wird nicht angefasst.

    `nextcloud.py::_pruefe_schreibrecht` bricht vor dem MOVE ab; hier zählt,
    dass daraus eine Meldung wird und kein halber Zustand — und dass niemand
    den Riegel umgeht, um „nur kurz" umzubenennen."""
    with TestClient(app) as c:
        w = wolke(heimat="/Home")
        doc, _ = _umgebung(c, "Fremdweg 7", stamm="Fremd")
        vorher = _stand(doc)

        antwort = c.patch(f"/api/dokumente/{doc}/name",
                          json={"beschreibung": "Versuch"})
        assert antwort.status_code == 502
        assert "ausserhalb" in antwort.json()["detail"]
        assert w.verschoben == []
        assert _stand(doc) == vorher


def test_grabstein_wird_abgelehnt(wolke):
    """N242 — die Datei wurde in der Nextcloud gelöscht. Umbenennen griffe ins
    Leere: sprechender 409 statt 500."""
    with TestClient(app) as c:
        w = wolke()
        doc, ordner = _umgebung(c, "Grabsteinweg 8")
        _pfad_setzen(doc, f"entfernt:/{ordner}/{START}")

        antwort = c.patch(f"/api/dokumente/{doc}/name",
                          json={"beschreibung": "Neuer Name"})
        assert antwort.status_code == 409
        assert "gelöscht" in antwort.json()["detail"]
        assert w.verschoben == []


def test_eintrag_ohne_datei_wird_abgelehnt(wolke):
    """Ein Eintrag, der noch gar nicht in der Cloud liegt, hat nichts zum
    Umbenennen — Ehrlichkeit statt Erfolgsmeldung."""
    with TestClient(app) as c:
        w = wolke()
        doc, _ = _umgebung(c, "Ohnedatei 9")
        _pfad_setzen(doc, f"(nicht abgelegt)/{START}")

        antwort = c.patch(f"/api/dokumente/{doc}/name",
                          json={"beschreibung": "Neuer Name"})
        assert antwort.status_code == 409
        assert w.verschoben == []


def test_unbekannte_id_ist_404(wolke):
    with TestClient(app) as c:
        wolke()
        antwort = c.patch("/api/dokumente/987654/name",
                          json={"beschreibung": "Egal"})
        assert antwort.status_code == 404
