"""Lageplan je Einheit: anlegen, auflisten, umbenennen, entfernen (CCCLXXXI).

Der Schwerpunkt liegt auf der Datensicherheit: ein Lageplan wird über die
gewohnte Ablagelogik hochgeladen, aber Umbenennen und Löschen fassen die Datei
in der Nextcloud NIE an. Das Umbenennen ändert nur den Anzeigenamen am
Datensatz (kein MOVE), das Löschen entfernt nur den Datenbankeintrag (kein
DELETE in der Cloud) — beides wird hier belegt.
"""
import os
import sys
import tempfile
from datetime import date
from types import SimpleNamespace

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_lageplan.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Dokument, Einheit, Objekt  # noqa: E402


# --------------------------------------------------------------------------
# Hilfen
# --------------------------------------------------------------------------

class _Wolke:
    """Nextcloud-Ersatz, der jeden Zugriff mitschreibt — und keinen einzigen
    zerstörerischen kennt. Fehlt eine `loesche`/`entferne`-Methode, würde ein
    Löschversuch im Endpunkt sofort als AttributeError auffliegen."""

    def __init__(self):
        self.angelegt = []
        self.abgelegt = []
        self.verschoben = []

    def liste(self, pfad):
        return []

    def ordner_anlegen(self, pfad):
        self.angelegt.append(pfad)
        return True

    def existiert(self, pfad):
        return False

    def lege_ab(self, pfad, inhalt):
        self.abgelegt.append(pfad)

    def verschiebe(self, von, nach):
        self.verschoben.append((von, nach))


class _StummeWolke:
    """Eine Cloud, die bei jedem Zugriff aufschreit. Damit lässt sich beweisen,
    dass ein Aufruf die Nextcloud überhaupt nicht anfasst."""

    def __getattr__(self, name):
        raise AssertionError(f"Die Cloud wurde angefasst: {name}()")


def _objekt_mit_cloud(c, name, ordner):
    slug = c.post("/api/objekte", json={"name": name}).json()["slug"]
    with Session(engine) as s:
        o = s.exec(select(Objekt).where(Objekt.slug == slug)).first()
        o.nc_ordner = ordner
        s.add(o)
        s.commit()
        s.refresh(o)
        return slug, o.id


def _einheit(objekt_id, bezeichnung="EG links"):
    with Session(engine) as s:
        e = Einheit(objekt_id=objekt_id, bezeichnung=bezeichnung, flaeche=60.0)
        s.add(e)
        s.commit()
        s.refresh(e)
        return e.id


def _lege_lageplan_an(objekt_id, einheit_id, name="Lageplan EG links.pdf"):
    """Ein Lageplan direkt in der Datenbank — für die Wege, die die Cloud gar
    nicht brauchen (umbenennen, entfernen)."""
    with Session(engine) as s:
        pfad = f"/Home/Immobilien/{objekt_id}/{einheit_id}/99_Sonstiges/{name}"
        d = Dokument(pfad=pfad,
                     dateiname=name, groesse=4096, objekt_id=objekt_id,
                     kategorie="Lageplan", info_zu_typ="einheit",
                     info_zu_id=einheit_id, status="zugeordnet",
                     erkannt_am=date.today())
        s.add(d)
        s.commit()
        s.refresh(d)
        return d.id, d.pfad


def _stand(doc_id):
    with Session(engine) as s:
        return s.get(Dokument, doc_id)


# --------------------------------------------------------------------------
# Anlegen und auflisten
# --------------------------------------------------------------------------

def test_lageplan_anlegen_landet_in_der_liste(monkeypatch):
    """Ein hochgeladener Lageplan wird über die Ablagelogik in der Cloud
    abgelegt und erscheint danach in der Liste der Einheit."""
    import app.routers.dokumente as modul

    with TestClient(app) as c:
        slug, oid = _objekt_mit_cloud(c, "Planweg 1", "Home/Immobilien/Planweg 1")
        eid = _einheit(oid)
        wolke = _Wolke()
        monkeypatch.setattr(modul, "verbindung", lambda session: wolke)

        antwort = c.post(f"/api/einheiten/{eid}/lageplan",
                         files={"datei": ("plan.pdf", b"%PDF-1.4 test",
                                          "application/pdf")})
        assert antwort.status_code == 201
        neu = antwort.json()
        assert neu["einheit_id"] == eid
        # Die Datei wurde in der Cloud abgelegt — genau einmal, unter Sonstiges.
        assert len(wolke.abgelegt) == 1
        assert "99_Sonstiges" in wolke.abgelegt[0]

        liste = c.get(f"/api/einheiten/{eid}/lageplaene").json()
        assert [p["id"] for p in liste] == [neu["id"]]
        assert liste[0]["dateiname"].endswith(".pdf")


def test_liste_trennt_die_einheiten(monkeypatch):
    """Der Lageplan der einen Einheit taucht nicht bei der anderen auf."""
    with TestClient(app) as c:
        slug, oid = _objekt_mit_cloud(c, "Planweg 2", "Home/Immobilien/Planweg 2")
        eins = _einheit(oid, "EG")
        zwei = _einheit(oid, "OG")
        doc, _ = _lege_lageplan_an(oid, eins)

        assert [p["id"] for p in
                c.get(f"/api/einheiten/{eins}/lageplaene").json()] == [doc]
        assert c.get(f"/api/einheiten/{zwei}/lageplaene").json() == []


# --------------------------------------------------------------------------
# Löschen — der Datensatz geht, die Cloud-Datei bleibt
# --------------------------------------------------------------------------

def test_delete_entfernt_nur_den_eintrag_und_laesst_die_cloud_datei_stehen(
        monkeypatch):
    """Der DELETE nimmt den Datenbankeintrag heraus — und fasst die Nextcloud
    dabei überhaupt nicht an. Kein DELETE, kein MOVE, kein Client."""
    import app.routers.dokumente as modul

    with TestClient(app) as c:
        slug, oid = _objekt_mit_cloud(c, "Planweg 3", "Home/Immobilien/Planweg 3")
        eid = _einheit(oid)
        doc, pfad = _lege_lageplan_an(oid, eid)

        # Jeder Cloud-Zugriff aus dem DELETE heraus würde hier auffliegen.
        monkeypatch.setattr(modul, "verbindung",
                            lambda session: _StummeWolke())

        antwort = c.delete(f"/api/einheiten/{eid}/lageplan/{doc}")
        assert antwort.status_code == 200
        assert antwort.json()["datei_bleibt"] is True
        # Der Datensatz ist weg …
        assert _stand(doc) is None
        assert c.get(f"/api/einheiten/{eid}/lageplaene").json() == []
        # … ein zweiter Versuch ist ehrlich 404.
        assert c.delete(f"/api/einheiten/{eid}/lageplan/{doc}").status_code == 404
        assert pfad.startswith("/")


def test_delete_greift_nicht_ueber_die_falsche_einheit(monkeypatch):
    """Ein Lageplan lässt sich nicht über eine fremde Einheit löschen."""
    with TestClient(app) as c:
        slug, oid = _objekt_mit_cloud(c, "Planweg 4", "Home/Immobilien/Planweg 4")
        eins = _einheit(oid, "EG")
        zwei = _einheit(oid, "OG")
        doc, _ = _lege_lageplan_an(oid, eins)

        assert c.delete(
            f"/api/einheiten/{zwei}/lageplan/{doc}").status_code == 404
        # Der Datensatz ist unberührt.
        assert _stand(doc) is not None


def test_delete_trifft_nur_lageplaene(monkeypatch):
    """Ein gewöhnlicher Beleg an der Einheit ist kein Lageplan — der
    Lageplan-DELETE fasst ihn nicht an."""
    with TestClient(app) as c:
        slug, oid = _objekt_mit_cloud(c, "Planweg 5", "Home/Immobilien/Planweg 5")
        eid = _einheit(oid)
        with Session(engine) as s:
            d = Dokument(pfad=f"/Home/Immobilien/{oid}/60_Nebenkosten/beleg.pdf",
                         dateiname="beleg.pdf", groesse=1, objekt_id=oid,
                         kategorie="Nebenkosten", info_zu_typ="einheit",
                         info_zu_id=eid, status="zugeordnet")
            s.add(d)
            s.commit()
            s.refresh(d)
            fremd = d.id

        assert c.delete(
            f"/api/einheiten/{eid}/lageplan/{fremd}").status_code == 404
        assert _stand(fremd) is not None


# --------------------------------------------------------------------------
# Umbenennen — nur der Anzeigename, die Datei bleibt liegen
# --------------------------------------------------------------------------

def test_umbenennen_setzt_den_anzeigenamen_ohne_die_datei_zu_bewegen(
        monkeypatch):
    """Umbenennen ändert den Namen am Datensatz — der Pfad in der Cloud bleibt,
    die Cloud wird nicht angefasst, und die Endung bleibt erhalten."""
    import app.routers.dokumente as modul

    with TestClient(app) as c:
        slug, oid = _objekt_mit_cloud(c, "Planweg 6", "Home/Immobilien/Planweg 6")
        eid = _einheit(oid)
        doc, pfad = _lege_lageplan_an(oid, eid)

        monkeypatch.setattr(modul, "verbindung",
                            lambda session: _StummeWolke())

        antwort = c.patch(f"/api/einheiten/{eid}/lageplan/{doc}",
                          json={"name": "Grundriss Erdgeschoss"})
        assert antwort.status_code == 200
        # Endung bleibt dran, damit Vorschau/Download den Typ erkennen.
        assert antwort.json()["dateiname"] == "Grundriss Erdgeschoss.pdf"

        nach = _stand(doc)
        assert nach.dateiname == "Grundriss Erdgeschoss.pdf"
        # Der Pfad in der Cloud ist unverändert — die Datei wurde nicht bewegt.
        assert nach.pfad == pfad
        # Die Liste zeigt den neuen Anzeigenamen.
        assert c.get(f"/api/einheiten/{eid}/lageplaene").json()[0][
            "dateiname"] == "Grundriss Erdgeschoss.pdf"


def test_umbenennen_verdoppelt_die_endung_nicht(monkeypatch):
    """Gibt der Nutzer die Endung selbst mit, wird sie nicht ein zweites Mal
    angehängt."""
    import app.routers.dokumente as modul

    with TestClient(app) as c:
        slug, oid = _objekt_mit_cloud(c, "Planweg 7", "Home/Immobilien/Planweg 7")
        eid = _einheit(oid)
        doc, _ = _lege_lageplan_an(oid, eid, name="alter Plan.jpg")

        monkeypatch.setattr(modul, "verbindung",
                            lambda session: _StummeWolke())

        antwort = c.patch(f"/api/einheiten/{eid}/lageplan/{doc}",
                          json={"name": "Lageplan.jpg"})
        assert antwort.json()["dateiname"] == "Lageplan.jpg"


def test_umbenennen_braucht_einen_namen(monkeypatch):
    """Ein leerer Name ist kein Name — 400 statt eines namenlosen Eintrags."""
    with TestClient(app) as c:
        slug, oid = _objekt_mit_cloud(c, "Planweg 8", "Home/Immobilien/Planweg 8")
        eid = _einheit(oid)
        doc, _ = _lege_lageplan_an(oid, eid)

        assert c.patch(f"/api/einheiten/{eid}/lageplan/{doc}",
                       json={"name": "   "}).status_code == 400
