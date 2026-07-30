"""CCCLXVII — ein Scan darf gleich am gemeinten Eintrag landen.

Der Mietvertrag wird am Mietverhältnis abfotografiert, nicht irgendwo und
danach im Baum gesucht. `POST /api/dokumente/scannen` nimmt dafür zwei
freiwillige Felder entgegen (`an_typ`, `an_id`). Freiwillig heisst: ohne sie
verhält sich der Endpunkt exakt wie vorher — diese Datei wacht darüber.
"""
import os
import sys
import tempfile
from datetime import date
from types import SimpleNamespace

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_scan_ziel.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Dokument, Miete, Objekt  # noqa: E402

PDF = ("scan.pdf", b"%PDF-1.4 mietvertrag", "application/pdf")


class _Wolke:
    """Nextcloud-Ersatz: merkt sich, was abgelegt wurde, und löscht nie."""

    def __init__(self):
        self.abgelegt = []
        self.angelegt = []
        self.verschoben = []

    def liste(self, pfad):
        return []

    def ordner_anlegen(self, pfad):
        self.angelegt.append(pfad)
        return True

    def existiert(self, pfad):
        return False

    def verschiebe(self, von, nach):
        self.verschoben.append((von, nach))

    def lege_ab(self, pfad, inhalt):
        self.abgelegt.append(pfad)


def _mit_cloud(c, name: str) -> str:
    """Immobilie mit verknüpftem Nextcloud-Ordner."""
    slug = c.post("/api/objekte", json={"name": name}).json()["slug"]
    with Session(engine) as s:
        o = s.exec(select(Objekt).where(Objekt.slug == slug)).first()
        o.nc_ordner = f"Home/Immobilien/{name}"
        s.add(o)
        s.commit()
    return slug


def _miete(c, slug: str, partei: str = "Mieter A") -> int:
    return c.post(f"/api/objekte/{slug}/mieten",
                  json={"einheit": "EG", "partei": partei, "kaltmiete": 800.0,
                        "nebenkosten_vz": 150.0,
                        "ab_datum": "2024-01-01"}).json()["id"]


def _scanne(c, slug: str, **felder):
    daten = {"objekt": slug, "kategorie": "Mietvertrag", "jahr": 2024}
    daten.update(felder)
    return c.post("/api/dokumente/scannen", data=daten,
                  files={"datei": PDF})


def _dokumente(objekt_id: int) -> list[Dokument]:
    with Session(engine) as s:
        return list(s.exec(select(Dokument)
                           .where(Dokument.objekt_id == objekt_id)))


def _objekt_id(slug: str) -> int:
    with Session(engine) as s:
        return s.exec(select(Objekt).where(Objekt.slug == slug)).first().id


def test_scan_ohne_an_typ_bleibt_wie_bisher(monkeypatch):
    """Der bestehende Weg (Eingang, Zeitraum, Abrechnung) schickt kein
    `an_typ` — er muss unverändert durchlaufen und darf an keinem Eintrag
    hängen bleiben."""
    import app.routers.dokumente as modul

    with TestClient(app) as c:
        slug = _mit_cloud(c, "Altweg 1")
        mid = _miete(c, slug)
        monkeypatch.setattr(modul, "verbindung", lambda session: _Wolke())

        antwort = _scanne(c, slug, beschreibung="Vertrag")
        assert antwort.status_code == 201
        koerper = antwort.json()
        assert koerper["abgelegt"] is True
        assert koerper["an_typ"] == "" and koerper["an_id"] is None

        with Session(engine) as s:
            d = s.get(Dokument, koerper["id"])
            assert not d.info_zu_typ and d.info_zu_id is None
            assert s.get(Miete, mid).quelle_dokument_id is None


def test_scan_mit_an_typ_haengt_am_mietverhaeltnis(monkeypatch):
    """Der Kernwunsch: am Mietverhältnis abfotografieren — danach kennt der
    Eintrag seinen Beleg und der Beleg seinen Eintrag."""
    import app.routers.dokumente as modul

    with TestClient(app) as c:
        slug = _mit_cloud(c, "Vertragsweg 2")
        mid = _miete(c, slug)
        monkeypatch.setattr(modul, "verbindung", lambda session: _Wolke())

        antwort = _scanne(c, slug, beschreibung="Mieter A",
                          an_typ="miete", an_id=mid)
        assert antwort.status_code == 201
        koerper = antwort.json()
        assert koerper["an_typ"] == "miete" and koerper["an_id"] == mid

        with Session(engine) as s:
            d = s.get(Dokument, koerper["id"])
            assert (d.info_zu_typ, d.info_zu_id) == ("miete", mid)
            assert s.get(Miete, mid).quelle_dokument_id == d.id

        # und der Beleg steht am Eintrag, wo die Detailansicht ihn holt
        belege = c.get(f"/api/dokumente/objekt/{slug}/eintrag/miete/{mid}/belege")
        assert belege.status_code == 200
        assert belege.json()["haupt"]["id"] == koerper["id"]


def test_vorhandener_quellbeleg_wird_nie_ueberschrieben(monkeypatch):
    """Ein zweiter Scan hängt daneben, nicht darüber: der erste Beleg bleibt
    der Quellbeleg des Eintrags."""
    import app.routers.dokumente as modul

    with TestClient(app) as c:
        slug = _mit_cloud(c, "Zweitweg 3")
        mid = _miete(c, slug)
        monkeypatch.setattr(modul, "verbindung", lambda session: _Wolke())

        erst = _scanne(c, slug, beschreibung="Vertrag",
                       an_typ="miete", an_id=mid).json()["id"]
        zweit = _scanne(c, slug, beschreibung="Nachtrag",
                        an_typ="miete", an_id=mid).json()["id"]
        assert erst != zweit

        with Session(engine) as s:
            assert s.get(Miete, mid).quelle_dokument_id == erst
            # der zweite hängt trotzdem am Eintrag — nur eben als Info-Beleg
            d = s.get(Dokument, zweit)
            assert (d.info_zu_typ, d.info_zu_id) == ("miete", mid)

        belege = c.get(
            f"/api/dokumente/objekt/{slug}/eintrag/miete/{mid}/belege").json()
        assert belege["haupt"]["id"] == erst
        assert [u["id"] for u in belege["unter"]] == [zweit]


def test_fremdes_oder_unbekanntes_ziel_legt_nichts_halb_an(monkeypatch):
    """Ein Eintrag der Nachbarimmobilie, eine Id, die es nicht gibt, ein Typ,
    den niemand kennt: sauber gemeldet — und ohne Datei in der Cloud und ohne
    halben Eintrag in der Datenbank."""
    import app.routers.dokumente as modul

    with TestClient(app) as c:
        slug = _mit_cloud(c, "Eigenweg 4")
        fremd = _mit_cloud(c, "Fremdweg 5")
        fremde_miete = _miete(c, fremd, "Mieter F")
        wolke = _Wolke()
        monkeypatch.setattr(modul, "verbindung", lambda session: wolke)

        fremd_antwort = _scanne(c, slug, an_typ="miete", an_id=fremde_miete)
        assert fremd_antwort.status_code == 400
        assert "andere" in fremd_antwort.json()["detail"]

        unbekannt = _scanne(c, slug, an_typ="miete", an_id=99999)
        assert unbekannt.status_code == 404

        falscher_typ = _scanne(c, slug, an_typ="knollenblaetterpilz", an_id=1)
        assert falscher_typ.status_code == 400

        ohne_id = _scanne(c, slug, an_typ="miete")
        assert ohne_id.status_code == 400

        # nichts abgelegt, nichts angelegt: kein halber Zustand
        assert wolke.abgelegt == []
        assert _dokumente(_objekt_id(slug)) == []
        with Session(engine) as s:
            assert s.get(Miete, fremde_miete).quelle_dokument_id is None


def test_durchsuchbar_ohne_werkzeug_ist_kein_fehler(monkeypatch):
    """Ohne die OCR-Bibliotheken bleibt der Beleg stumm — ehrlich gemeldet,
    nicht als Fehler. Die Oberfläche ruft das nebenher auf; ein 500 dürfte
    dabei nie entstehen."""
    import app.routers.dokumente as modul

    with TestClient(app) as c:
        slug = _mit_cloud(c, "Stummweg 6")
        wolke = _Wolke()
        monkeypatch.setattr(modul, "verbindung", lambda session: wolke)
        doc = _scanne(c, slug, beschreibung="Vertrag").json()["id"]
        monkeypatch.setattr(modul.ocr, "durchsuchbar_verfuegbar", lambda: False)

        antwort = c.post(f"/api/dokumente/{doc}/durchsuchbar")
        assert antwort.status_code == 200
        assert antwort.json() == {"ok": True, "ergaenzt": False,
                                  "grund": "Werkzeug nicht verfügbar"}
        # nichts angefasst
        assert wolke.verschoben == []


def test_durchsuchbar_ersetzt_nur_per_move(monkeypatch):
    """Ergänzt die Erkennung etwas, wandert das Original zuerst unangetastet
    in den Sicherungsordner — überschrieben wird nie."""
    import app.routers.dokumente as modul

    class _MitInhalt(_Wolke):
        def hole(self, pfad):
            return b"%PDF-1.4 roh", "application/pdf"

    with TestClient(app) as c:
        slug = _mit_cloud(c, "Textweg 7")
        wolke = _MitInhalt()
        monkeypatch.setattr(modul, "verbindung", lambda session: wolke)
        doc = _scanne(c, slug, beschreibung="Vertrag").json()["id"]
        wolke.abgelegt.clear()
        monkeypatch.setattr(modul.ocr, "durchsuchbar_verfuegbar", lambda: True)
        monkeypatch.setattr(modul.ocr, "durchsuchbar_machen",
                            lambda roh: b"%PDF-1.4 mit-text-schicht")

        antwort = c.post(f"/api/dokumente/{doc}/durchsuchbar")
        assert antwort.status_code == 200
        assert antwort.json()["ergaenzt"] is True

        with Session(engine) as s:
            d = s.get(Dokument, doc)
            assert d.groesse == len(b"%PDF-1.4 mit-text-schicht")
            # das Original liegt gesichert daneben, am selben Ort
            assert wolke.verschoben == [
                (d.pfad, f"{d.pfad.strip('/').rpartition('/')[0]}/"
                         f"{modul.OCR_SICHERUNGSORDNER}/{d.dateiname}")]
            assert wolke.abgelegt == [d.pfad]


def test_unbekanntes_dokument_meldet_sich_ehrlich():
    """Kein 500, sondern ein 404 — die Oberfläche zeigt es an."""
    with TestClient(app) as c:
        assert c.post("/api/dokumente/424242/durchsuchbar").status_code == 404


def test_scan_an_kostenposition_bleibt_moeglich(monkeypatch):
    """Nicht nur Mieten: derselbe Weg trägt jede Rubrik, die das Backend
    kennt — hier eine Kostenposition am Zeitraum."""
    import app.routers.dokumente as modul
    from app.models import Kostenposition, Zeitraum

    with TestClient(app) as c:
        slug = _mit_cloud(c, "Kostenweg 8")
        oid = _objekt_id(slug)
        with Session(engine) as s:
            z = Zeitraum(objekt_id=oid, start=date(2024, 1, 1),
                         ende=date(2024, 12, 31))
            s.add(z)
            s.commit()
            s.refresh(z)
            k = Kostenposition(zeitraum_id=z.id, kostenart="Müll",
                               betrag=256.36, schluessel="wohnflaeche")
            s.add(k)
            s.commit()
            s.refresh(k)
            kid, zid = k.id, z.id
        monkeypatch.setattr(modul, "verbindung", lambda session: _Wolke())

        antwort = _scanne(c, slug, kategorie="Nebenkosten", zeitraum_id=zid,
                          beschreibung="Müll", an_typ="kostenposition",
                          an_id=kid)
        assert antwort.status_code == 201
        with Session(engine) as s:
            assert s.get(Kostenposition, kid).quelle_dokument_id \
                == antwort.json()["id"]


def test_an_typ_objekt_haengt_an_keinem_eintrag(monkeypatch):
    """„objekt" meint die Immobilie selbst, nicht einen einzelnen Eintrag —
    dieselbe Lesart wie in `/zuordnen`, damit die Oberfläche nicht zwei
    Sprachen sprechen muss."""
    import app.routers.dokumente as modul

    with TestClient(app) as c:
        slug = _mit_cloud(c, "Hausweg 9")
        monkeypatch.setattr(modul, "verbindung", lambda session: _Wolke())

        antwort = _scanne(c, slug, an_typ="objekt", an_id=1)
        assert antwort.status_code == 201
        assert antwort.json()["an_typ"] == ""
        with Session(engine) as s:
            d = s.get(Dokument, antwort.json()["id"])
            assert not d.info_zu_typ and d.info_zu_id is None


def test_kein_altes_feld_ist_pflicht_geworden(monkeypatch):
    """Wächter: die neuen Felder sind rein additiv. Ein Aufruf mit dem
    Mindestsatz von früher muss weiter 201 liefern."""
    import app.routers.dokumente as modul

    with TestClient(app) as c:
        slug = _mit_cloud(c, "Minimalweg 10")
        monkeypatch.setattr(modul, "verbindung", lambda session: _Wolke())

        antwort = c.post("/api/dokumente/scannen",
                         data={"objekt": slug, "kategorie": "Sonstiges"},
                         files={"datei": PDF})
        assert antwort.status_code == 201
        assert SimpleNamespace(**antwort.json()).an_id is None
