"""Dokumentenablage: Benennung, Vermutung, Zuordnung, Korrektur, Filter."""
import os
import sys
import tempfile
from datetime import date
from types import SimpleNamespace

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_dokumente.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Dokument, Objekt  # noqa: E402
from app.routers.cloud import STRUKTUR  # noqa: E402
from app.routers.dokumente import ZIELORDNER, dateiname  # noqa: E402


def test_dateiname_folgt_dem_schema():
    assert dateiname(2024, "Nebenkosten", "Grundsteuer", ".pdf") \
        == "2024_Nebenkosten_Grundsteuer.pdf"
    # Leerzeichen werden zu Bindestrichen, Umlaute bleiben lesbar
    assert dateiname(2025, "Steuer", "Bescheid Finanzamt Süd", ".pdf") \
        == "2025_Steuer_Bescheid-Finanzamt-Süd.pdf"
    # ohne Beschreibung und ohne Jahr bleibt es trotzdem eindeutig
    assert dateiname(None, "Sonstiges", "", ".pdf") == "ohne-Jahr_Sonstiges.pdf"
    # Schrägstriche dürfen keinen Pfad erzeugen
    assert "/" not in dateiname(2024, "Nebenkosten", "a/b", ".pdf")


def test_jeder_zielordner_existiert_in_der_struktur():
    """Sonst würde eine Zuordnung ins Leere sortieren."""
    for ordner in ZIELORDNER.values():
        assert ordner in STRUKTUR, f"{ordner} fehlt in der Ordnerstruktur"


def _objekt_id(slug: str) -> int:
    with Session(engine) as s:
        return s.exec(select(Objekt).where(Objekt.slug == slug)).first().id


def _lege_dokument_an(objekt_id: int, name: str, **felder) -> int:
    with Session(engine) as s:
        felder.setdefault("status", "neu")
        d = Dokument(pfad=f"/[010]_Immobilien/{objekt_id}/{name}", dateiname=name,
                     groesse=12345, objekt_id=objekt_id,
                     erkannt_am=date.today(), **felder)
        s.add(d)
        s.commit()
        s.refresh(d)
        return d.id


def test_liste_zeigt_vermutung():
    """Die Art kommt aus derselben Worterkennung wie bei der Texterkennung."""
    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={"name": "Eingangsweg 4"}).json()["slug"]
        objekt_id = _objekt_id(slug)

        _lege_dokument_an(objekt_id, "Grundsteuerbescheid_2024.pdf")
        _lege_dokument_an(objekt_id, "Stromabrechnung-2025.pdf")
        _lege_dokument_an(objekt_id, "scan.pdf")

        daten = c.get("/api/dokumente", params={"objekt": slug}).json()
        assert daten["anzahl"] == 3
        nach_name = {d["dateiname"]: d for d in daten["dokumente"]}

        grund = nach_name["Grundsteuerbescheid_2024.pdf"]["vorschlag"]
        assert grund["kategorie"] == "Steuer"
        assert grund["jahr"] == 2024

        strom = nach_name["Stromabrechnung-2025.pdf"]["vorschlag"]
        assert strom["kategorie"] == "Nebenkosten"
        assert strom["jahr"] == 2025

        # Ein Kamerascan gibt im Namen nichts her — dann wird auch nichts geraten
        assert nach_name["scan.pdf"]["vorschlag"]["kategorie"] == ""


def test_filter_nach_objekt_kategorie_jahr_status_und_suche():
    with TestClient(app) as c:
        a = c.post("/api/objekte", json={"name": "Filterallee 1"}).json()["slug"]
        b = c.post("/api/objekte", json={"name": "Filterallee 2"}).json()["slug"]
        _lege_dokument_an(_objekt_id(a), "Wasser_2023.pdf",
                          kategorie="Nebenkosten", jahr=2023, status="zugeordnet")
        _lege_dokument_an(_objekt_id(a), "Police_2024.pdf",
                          kategorie="Versicherung", jahr=2024, status="zugeordnet")
        _lege_dokument_an(_objekt_id(b), "Offen_2024.pdf")

        assert c.get("/api/dokumente", params={"objekt": a}).json()["anzahl"] == 2
        assert c.get("/api/dokumente",
                     params={"kategorie": "Versicherung"}).json()["anzahl"] == 1
        assert c.get("/api/dokumente", params={"objekt": a, "jahr": 2023}
                     ).json()["anzahl"] == 1
        assert c.get("/api/dokumente", params={"objekt": b, "status": "neu"}
                     ).json()["anzahl"] == 1
        treffer = c.get("/api/dokumente", params={"suche": "police"}).json()
        assert [d["dateiname"] for d in treffer["dokumente"]] == ["Police_2024.pdf"]

        # Die Filterwerte kommen aus den Daten, nicht aus einer festen Liste
        gesamt = c.get("/api/dokumente").json()
        assert 2023 in gesamt["jahre"] and 2024 in gesamt["jahre"]
        assert "Versicherung" in gesamt["kategorien"]
        assert any(o["slug"] == a and o["anzahl"] == 2 for o in gesamt["objekte"])
        assert gesamt["offen"] >= 1

        # Offenes steht oben
        assert gesamt["dokumente"][0]["status"] == "neu"


def test_unbekanntes_objekt_im_filter_ist_404():
    with TestClient(app) as c:
        assert c.get("/api/dokumente",
                     params={"objekt": "gibtsnicht"}).status_code == 404


def test_zuordnen_ohne_cloud_benennt_um():
    """Ohne verknüpften Nextcloud-Ordner wird nur umbenannt, nicht verschoben."""
    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={"name": "Ablageweg 9"}).json()["slug"]
        doc = _lege_dokument_an(_objekt_id(slug), "irgendwas.pdf")

        antwort = c.patch(f"/api/dokumente/{doc}", json={
            "objekt": slug, "kategorie": "Nebenkosten", "jahr": 2024,
            "beschreibung": "Wasser", "verschieben": False})
        assert antwort.status_code == 200
        assert antwort.json()["dateiname"] == "2024_Nebenkosten_Wasser.pdf"
        assert antwort.json()["verschoben"] is False

        # verschwindet aus dem Eingang und taucht in der Ablage auf
        offen = [d["id"] for d in c.get("/api/dokumente", params={"status": "neu"}
                                        ).json()["dokumente"]]
        assert doc not in offen
        beim_objekt = c.get("/api/dokumente", params={"objekt": slug}).json()
        assert any(d["id"] == doc and d["status"] == "zugeordnet"
                   for d in beim_objekt["dokumente"])


def test_zuordnen_ohne_cloud_ordner_meldet_keinen_erfolg():
    """LXIX: Verschieben ohne verknüpften Ordner darf nicht 'zugeordnet' melden.

    Sonst verschwindet die Datei aus dem Eingang, liegt aber weiter im
    Hauptordner — und der nächste Scan findet sie nie wieder."""
    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={"name": "Ohnewolke 3"}).json()["slug"]
        doc = _lege_dokument_an(_objekt_id(slug), "beleg.pdf")

        antwort = c.patch(f"/api/dokumente/{doc}", json={
            "objekt": slug, "kategorie": "Steuer", "jahr": 2025})
        assert antwort.status_code == 409
        assert "Ordner" in antwort.json()["detail"]

        # und bleibt im Eingang, statt still zu verschwinden
        offen = [d["id"] for d in c.get("/api/dokumente", params={"status": "neu"}
                                        ).json()["dokumente"]]
        assert doc in offen


def test_scan_ohne_cloud_ordner_wird_abgelehnt():
    """Ein Kamerascan ohne Ablageort erzeugte früher einen Eintrag unter
    '(nicht abgelegt)/…' — eine Datei, die es nirgends gab."""
    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={"name": "Kameraweg 7"}).json()["slug"]
        antwort = c.post("/api/dokumente/scannen",
                         data={"objekt": slug, "kategorie": "Sonstiges"},
                         files={"datei": ("scan.pdf", b"%PDF-1.4 test",
                                          "application/pdf")})
        assert antwort.status_code == 409
        assert "Nextcloud" in antwort.json()["detail"]


def test_umbenennen_ueber_die_bezeichnung():
    """Umbenannt wird über die Bezeichnung — das Schema bleibt gewahrt,
    die Endung auch."""
    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={"name": "Namensweg 2"}).json()["slug"]
        doc = _lege_dokument_an(_objekt_id(slug), "alt.pdf",
                                kategorie="Nebenkosten", jahr=2025,
                                status="zugeordnet")
        antwort = c.patch(f"/api/dokumente/{doc}", json={
            "beschreibung": "Heizung Ablesung", "verschieben": False})
        assert antwort.status_code == 200
        assert antwort.json()["dateiname"] == "2025_Nebenkosten_Heizung-Ablesung.pdf"


def test_entfernen_loescht_nur_den_eintrag():
    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={"name": "Papierkorbweg 5"}).json()["slug"]
        doc = _lege_dokument_an(_objekt_id(slug), "doppelt.pdf")
        antwort = c.delete(f"/api/dokumente/{doc}")
        assert antwort.status_code == 200
        assert antwort.json()["datei_bleibt"] is True
        assert c.delete(f"/api/dokumente/{doc}").status_code == 404
        with Session(engine) as s:
            assert s.get(Dokument, doc) is None


def test_pfade_bleiben_eindeutig():
    """LXVIII: derselbe Pfad darf nur einmal in der Ablage stehen."""
    from app.routers.dokumente import _eindeutigkeit_sichern
    import app.routers.dokumente as modul

    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={"name": "Doppelweg 8"}).json()["slug"]
        objekt_id = _objekt_id(slug)
        modul._index_geprueft = False
        with Session(engine) as s:
            _eindeutigkeit_sichern(s)

        pfad = "/[010]_Immobilien/Doppelweg/zweimal.pdf"
        with Session(engine) as s:
            s.add(Dokument(pfad=pfad, dateiname="zweimal.pdf",
                           objekt_id=objekt_id, status="neu"))
            s.commit()

        from sqlalchemy.exc import IntegrityError
        import pytest
        with Session(engine) as s:
            s.add(Dokument(pfad=pfad, dateiname="zweimal.pdf",
                           objekt_id=objekt_id, status="neu"))
            with pytest.raises(IntegrityError):
                s.commit()


def test_scan_und_wachdienst_laufen_nie_gleichzeitig():
    """LXVIII: die Sperre verhindert, dass beide dieselbe Datei aufnehmen."""
    from app.wachdienst import einmal_scannen, sperre

    with TestClient(app) as c:
        assert c.get("/api/dokumente/wachdienst").status_code == 200
        with sperre:
            # Der Handlauf tritt zurück, statt ein zweites Mal einzulesen
            assert c.post("/api/dokumente/scan").status_code == 409
            # und der Wachdienst meldet das nicht als Fehler
            assert einmal_scannen() == 0


class _Wolke:
    """Nextcloud-Ersatz für den Test: merkt sich, was verschoben wurde."""

    def __init__(self, dateien):
        self.dateien = dateien
        self.verschoben = []
        self.angelegt = []

    def liste(self, pfad):
        return [SimpleNamespace(pfad=f"/{pfad.strip('/')}/{n}", name=n,
                                groesse=1000, ordner=False)
                for n in self.dateien]

    def ordner_anlegen(self, pfad):
        self.angelegt.append(pfad)
        return True

    def existiert(self, pfad):
        return False

    def verschiebe(self, von, nach):
        self.verschoben.append((von, nach))


def test_scan_ordnet_zu_was_eindeutig_ist(monkeypatch):
    """LXXV: die Immobilie steht durch den Ordner fest, die Art steht im Namen —
    dann wird ohne Rückfrage einsortiert. Was unklar bleibt, wartet."""
    import app.routers.dokumente as modul

    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={"name": "Automatikweg 1"}).json()["slug"]
        with Session(engine) as s:
            o = s.exec(select(Objekt).where(Objekt.slug == slug)).first()
            o.nc_ordner = "Home/Immobilien/Automatikweg 1"
            s.add(o)
            s.commit()

        wolke = _Wolke(["Grundsteuerbescheid 2024.pdf", "IMG_4711.pdf"])
        monkeypatch.setattr(modul, "verbindung", lambda session: wolke)

        ergebnis = c.post("/api/dokumente/scan").json()
        assert ergebnis["neu"] == 2
        assert ergebnis["automatisch"] == 1
        assert ergebnis["offen"] == 1

        assert wolke.verschoben[0][1] == \
            "Home/Immobilien/Automatikweg 1/70_Steuer_Finanzamt/2024_Steuer.pdf"

        docs = c.get("/api/dokumente", params={"objekt": slug}).json()["dokumente"]
        nach_status = {d["status"]: d for d in docs}
        assert nach_status["zugeordnet"]["dateiname"] == "2024_Steuer.pdf"
        assert nach_status["zugeordnet"]["kategorie"] == "Steuer"
        assert nach_status["neu"]["dateiname"] == "IMG_4711.pdf"

        # Ein zweiter Lauf über dieselben Ordner legt nichts doppelt an
        wolke.dateien = ["IMG_4711.pdf"]
        assert c.post("/api/dokumente/scan").json()["neu"] == 0


def test_erkennung_meldet_ihren_zustand():
    """Der Hinweis in der App hängt daran — die Antwort muss immer kommen."""
    with TestClient(app) as c:
        antwort = c.get("/api/dokumente/erkennung")
        assert antwort.status_code == 200
        assert isinstance(antwort.json()["verfuegbar"], bool)


def test_unbekanntes_dokument_ist_404():
    with TestClient(app) as c:
        assert c.patch("/api/dokumente/999999",
                       json={"objekt": "egal"}).status_code == 404
        assert c.delete("/api/dokumente/999999").status_code == 404
