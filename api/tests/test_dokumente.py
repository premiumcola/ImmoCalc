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
    """CXXII/CXXIII — bewusste Änderung der Benennung.

    Vorher hiess das Schema `JJJJ_Kategorie_Beschreibung`; im Ordner
    60_Nebenkosten stand damit „2026_Nebenkosten_Heizkosten.pdf" — der Ordner
    sagt es schon, der Name sagt es noch einmal. Jetzt: Datum vorn, Sache in
    der Mitte, Betrag hinten, die Kategorie gar nicht."""
    assert dateiname(2024, "Nebenkosten", "Grundsteuer", ".pdf") \
        == "2024_Grundsteuer.pdf"
    # Leerzeichen werden zu Bindestrichen, Umlaute bleiben lesbar
    assert dateiname(2025, "Steuer", "Bescheid Finanzamt Süd", ".pdf") \
        == "2025_Bescheid-Finanzamt-Süd.pdf"
    # ohne Beschreibung und ohne Jahr bleibt es trotzdem eindeutig — und
    # heisst nicht "Sonstiges", denn so heisst schon der Ordner
    assert dateiname(None, "Sonstiges", "", ".pdf") == "ohne-Jahr_Beleg.pdf"
    # Schrägstriche dürfen keinen Pfad erzeugen
    assert "/" not in dateiname(2024, "Nebenkosten", "a/b", ".pdf")


def test_dateiname_nennt_nicht_doppelt_was_der_ordner_sagt():
    """CXXII, wörtlich: „Wenn was im Ordner Nebenkosten ist, dann soll die
    Datei natürlich nicht 2026_Nebenkosten_Heizkosten heissen."" """
    assert dateiname(2026, "Nebenkosten", "Nebenkosten Heizkosten", ".pdf") \
        == "2026_Heizkosten.pdf"
    # auch im Kompositum: „Nebenkostenabrechnung" -> „Abrechnung"
    assert dateiname(2024, "Nebenkosten", "Nebenkostenabrechnung", ".pdf") \
        == "2024_Abrechnung.pdf"
    # aber nicht mitten im Wort: aus „Grundsteuerbescheid" darf nie
    # „Grundbescheid" werden
    assert dateiname(2024, "Steuer", "Grundsteuerbescheid", ".pdf") \
        == "2024_Grundsteuerbescheid.pdf"


def test_dateiname_haengt_den_betrag_hinten_an():
    """CXXIII, wörtlich: „Bitte im Dateinamen hinten noch mit dranhängen,
    dann sieht man's direkt, wenn man im Ordner ist."

    Geschrieben wird er, wie der Nutzer es selbst tut: deutsches Komma,
    Euro-Zeichen, kein Tausenderpunkt („2025_Muell_256,36€.pdf")."""
    assert dateiname(2026, "Nebenkosten", "Heizöl", ".pdf", 3, 1284.5) \
        == "2026-03_Heizöl_1284,50€.pdf"
    assert dateiname(2025, "Nebenkosten", "Müll", ".pdf", None, 256.36) \
        == "2025_Müll_256,36€.pdf"
    # ohne Betrag bleibt der Name kurz, statt eine 0,00 zu behaupten
    assert dateiname(2025, "Nebenkosten", "Müll", ".pdf") == "2025_Müll.pdf"
    assert dateiname(2025, "Nebenkosten", "Müll", ".pdf", None, 0) \
        == "2025_Müll.pdf"


def test_dateiname_setzt_datum_und_betrag_nicht_zweimal():
    """Beim Korrigieren wird der bestehende Name neu gebaut. Stünden Datum und
    Betrag dann ein zweites Mal drin, wüchse der Name bei jeder Änderung."""
    einmal = dateiname(2025, "Nebenkosten", "Heizöl", ".pdf", 10, 2729.91)
    assert einmal == "2025-10_Heizöl_2729,91€.pdf"
    # derselbe Name als Bezeichnung wieder hineingegeben
    assert dateiname(2025, "Nebenkosten", einmal.removesuffix(".pdf"), ".pdf",
                     10, 2729.91) == einmal


def test_datum_und_betrag_werden_aus_dem_alten_namen_gelesen():
    """Der Nutzer hat beides oft selbst drangeschrieben — beim Einsortieren
    darf es nicht verlorengehen, nur weil kein Beleg gelesen wurde."""
    from app.bezeichnung import betrag_aus_namen, datum_aus_namen

    assert datum_aus_namen("2025-10-oel-2729,91€.pdf") == (2025, 10)
    assert datum_aus_namen("2022.08_Öl_(3099,95€).pdf") == (2022, 8)
    assert datum_aus_namen("111_2025-Brennstoff-4158,98€.pdf") == (2025, None)
    # keine Monatslesung aus einer längeren Zahl
    assert datum_aus_namen("WWK-2025-1196,09€.pdf") == (2025, None)
    assert datum_aus_namen("Rechnung ohne Datum.pdf") == (None, None)

    assert betrag_aus_namen("2025_Muell_256,36€.pdf") == 256.36
    assert betrag_aus_namen("DeltaT-2023-(200,75€).pdf") == 200.75
    assert betrag_aus_namen("111_2025-Brennstoff-4158,98€.pdf") == 4158.98
    assert betrag_aus_namen("Bescheid 2024.pdf") is None


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


def test_umbenennen_ohne_verschieben_gibt_es_nicht():
    """XCVI: `verschieben: false` benannte früher nur in der Datenbank um.

    Bewusste Fachlogik-Änderung: der Test hieß vorher
    `test_zuordnen_ohne_cloud_benennt_um` und schrieb genau den Schaden fest,
    den LXIX für den Normalfall behoben hatte — Datei und Eintrag liefen
    auseinander, der Beleg galt als abgelegt und war in der Cloud unter dem
    alten Namen. Ein Name in zwei Wahrheiten ist ein verlorener Beleg, deshalb
    gibt es den Schalter nicht mehr: umbenannt wird nur mit der Datei."""
    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={"name": "Ablageweg 9"}).json()["slug"]
        doc = _lege_dokument_an(_objekt_id(slug), "irgendwas.pdf")

        antwort = c.patch(f"/api/dokumente/{doc}", json={
            "objekt": slug, "kategorie": "Nebenkosten", "jahr": 2024,
            "beschreibung": "Wasser", "verschieben": False})
        assert antwort.status_code == 409
        assert "Ordner" in antwort.json()["detail"]

        # Der Eintrag bleibt, wie er war — Name und Eingang unverändert
        with Session(engine) as s:
            assert s.get(Dokument, doc).dateiname == "irgendwas.pdf"
        offen = [d["id"] for d in c.get("/api/dokumente", params={"status": "neu"}
                                        ).json()["dokumente"]]
        assert doc in offen


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


def _mit_cloud(c, name: str, ordner: str) -> str:
    """Immobilie mit verknüpftem Nextcloud-Ordner."""
    slug = c.post("/api/objekte", json={"name": name}).json()["slug"]
    with Session(engine) as s:
        o = s.exec(select(Objekt).where(Objekt.slug == slug)).first()
        o.nc_ordner = ordner
        s.add(o)
        s.commit()
    return slug


def test_umbenennen_ueber_die_bezeichnung(monkeypatch):
    """Umbenannt wird über die Bezeichnung — das Schema bleibt gewahrt,
    die Endung auch. Und die Datei in der Cloud heißt danach genauso."""
    import app.routers.dokumente as modul

    with TestClient(app) as c:
        slug = _mit_cloud(c, "Namensweg 2", "Home/Immobilien/Namensweg 2")
        doc = _lege_dokument_an(_objekt_id(slug), "alt.pdf",
                                kategorie="Nebenkosten", jahr=2025,
                                status="zugeordnet")
        wolke = _Wolke([])
        monkeypatch.setattr(modul, "verbindung", lambda session: wolke)

        antwort = c.patch(f"/api/dokumente/{doc}",
                          json={"beschreibung": "Heizung Ablesung"})
        assert antwort.status_code == 200
        # CXXII: „Nebenkosten" steht nicht mehr im Namen — der Ordner heisst so
        neu = "2025_Heizung-Ablesung.pdf"
        assert antwort.json()["dateiname"] == neu
        assert wolke.verschoben[-1][1] == \
            f"Home/Immobilien/Namensweg 2/60_Nebenkosten/{neu}"


def test_betrag_wandert_in_den_namen_und_bleibt_dort(monkeypatch):
    """CXXIII: der Betrag steht hinten im Namen — und überlebt eine
    spätere Korrektur, die ihn gar nicht erwähnt."""
    import app.routers.dokumente as modul

    with TestClient(app) as c:
        slug = _mit_cloud(c, "Betragsweg 3", "Home/Immobilien/Betragsweg 3")
        doc = _lege_dokument_an(_objekt_id(slug), "alt.pdf",
                                kategorie="Nebenkosten", jahr=2025,
                                status="zugeordnet")
        wolke = _Wolke([])
        monkeypatch.setattr(modul, "verbindung", lambda session: wolke)

        antwort = c.patch(f"/api/dokumente/{doc}", json={
            "beschreibung": "Heizöl", "monat": 10, "betrag": 2729.91})
        assert antwort.json()["dateiname"] == "2025-10_Heizöl_2729,91€.pdf"

        # Nur das Jahr korrigiert: Bezeichnung, Monat und Betrag bleiben
        antwort = c.patch(f"/api/dokumente/{doc}", json={"jahr": 2026})
        assert antwort.json()["dateiname"] == "2026-10_Heizöl_2729,91€.pdf"

        # und ausdrücklich gelöscht werden kann er auch
        antwort = c.patch(f"/api/dokumente/{doc}", json={"betrag": None})
        assert antwort.json()["dateiname"] == "2026-10_Heizöl.pdf"


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
    """Nextcloud-Ersatz für den Test: merkt sich, was verschoben wurde.

    `ordner` grenzt ein, wo die Dateien liegen — der Scanlauf geht über alle
    Immobilien, und ohne diese Grenze fände er dieselben Dateien in jedem
    Ordner wieder, den ein anderer Test angelegt hat."""

    def __init__(self, dateien, ordner=None):
        self.dateien = dateien
        self.ordner = ordner
        self.verschoben = []
        self.angelegt = []
        self.abgelegt = []

    def liste(self, pfad):
        if self.ordner and pfad.strip("/") != self.ordner.strip("/"):
            return []
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

    def lege_ab(self, pfad, inhalt):
        self.abgelegt.append(pfad)


def test_scan_ordnet_zu_was_eindeutig_ist(monkeypatch):
    """LXXV: die Immobilie steht durch den Ordner fest, die Art steht im Namen —
    dann wird ohne Rückfrage einsortiert. Was unklar bleibt, wartet.

    XCVII: der ursprüngliche Name bleibt als Bezeichnung erhalten. Vorher
    erwartete dieser Test „2024_Steuer.pdf" — bewusste Fachlogik-Änderung: so
    hießen alle Steuerbelege eines Jahres gleich, der zweite wurde
    „2024_Steuer-2.pdf", und was der Nutzer selbst benannt hatte, war
    unwiderruflich weg."""
    import app.routers.dokumente as modul

    with TestClient(app) as c:
        ordner = "Home/Immobilien/Automatikweg 1"
        slug = _mit_cloud(c, "Automatikweg 1", ordner)

        wolke = _Wolke(["Grundsteuerbescheid 2024.pdf", "IMG_4711.pdf"], ordner)
        monkeypatch.setattr(modul, "verbindung", lambda session: wolke)

        ergebnis = c.post("/api/dokumente/scan").json()
        assert ergebnis["neu"] == 2
        assert ergebnis["automatisch"] == 1
        assert ergebnis["offen"] == 1

        # CXXII: die Art steckt im Zielordner, nicht noch einmal im Namen —
        # vorher hiess die Datei „2024_Steuer_Grundsteuerbescheid.pdf".
        ziel = "2024_Grundsteuerbescheid.pdf"
        assert wolke.verschoben[0][1] == \
            f"Home/Immobilien/Automatikweg 1/70_Steuer_Finanzamt/{ziel}"

        docs = c.get("/api/dokumente", params={"objekt": slug}).json()["dokumente"]
        nach_status = {d["status"]: d for d in docs}
        assert nach_status["zugeordnet"]["dateiname"] == ziel
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


# --------------------------------------------------------------------------
# XCIII: kein Wort in der Wortmitte
# --------------------------------------------------------------------------

HARMLOS = ["Kaufvertrag Berggasse 5.pdf", "Rechnung Mueller 2024.pdf",
           "Schreiben Wassermann.pdf", "Notar Elgassner.pdf"]


def test_worterkennung_trifft_nicht_die_wortmitte():
    """XCIII: „Berggasse" ist kein Gas, „Wassermann" kein Wasser.

    Vorher zählte `klein.count("gas")` auch mitten im Wort — alle vier Namen
    galten als Nebenkosten. Folgenlos, solange nur ein Vorschlag daran hing;
    seit die Automatik verschiebt, wandern damit echte Unterlagen."""
    from app.ocr import kategorie_aus_dateiname

    for name in HARMLOS:
        lesbar = name.lower().replace("_", " ").replace("-", " ")
        assert kategorie_aus_dateiname(lesbar) == ("", 0), name

    # Was wirklich dasteht, wird weiter erkannt
    for name, erwartet in [("Stromabrechnung-2025.pdf", "Nebenkosten"),
                           ("Grundsteuerbescheid_2024.pdf", "Steuer"),
                           ("Gasrechnung 2023.pdf", "Nebenkosten"),
                           ("Müllgebühren 2024.pdf", "Nebenkosten"),
                           ("Versicherungsschein.pdf", "Versicherung")]:
        lesbar = name.lower().replace("_", " ").replace("-", " ")
        assert kategorie_aus_dateiname(lesbar)[0] == erwartet, name


def test_brennstoff_zaehlt_zu_den_heizkosten():
    """Eine Ölrechnung nennt sich nie „Heizkosten".

    Sie spricht von Heizöl, Litern und dem Tank — deshalb blieb sie bisher
    unerkannt liegen, obwohl Brennstoff der grösste Posten der Heizkosten ist.
    """
    from app.ocr import kategorie_aus_dateiname

    for name in ["Heizoelrechnung 2024.pdf", "Rechnung Heizöl 3000 Liter.pdf",
                 "Pellets 2025.pdf", "Fluessiggas Abrechnung.pdf"]:
        lesbar = name.lower().replace("_", " ").replace("-", " ")
        assert kategorie_aus_dateiname(lesbar)[0] == "Nebenkosten", name

    # Die Gegenprobe bleibt gültig: kein Treffer mitten im Wort
    for name in HARMLOS:
        lesbar = name.lower().replace("_", " ").replace("-", " ")
        assert kategorie_aus_dateiname(lesbar) == ("", 0), name


def test_unsichere_namen_bleiben_liegen(monkeypatch):
    """XCIII: bei unsicherer Erkennung wird nichts verschoben."""
    import app.routers.dokumente as modul

    with TestClient(app) as c:
        ordner = "Home/Immobilien/Wortmitteweg 3"
        slug = _mit_cloud(c, "Wortmitteweg 3", ordner)
        wolke = _Wolke(list(HARMLOS), ordner)
        monkeypatch.setattr(modul, "verbindung", lambda session: wolke)

        ergebnis = c.post("/api/dokumente/scan").json()
        assert ergebnis["neu"] == len(HARMLOS)
        assert ergebnis["automatisch"] == 0
        assert wolke.verschoben == []

        docs = c.get("/api/dokumente", params={"objekt": slug}).json()["dokumente"]
        assert {d["dateiname"] for d in docs} == set(HARMLOS)
        assert all(d["status"] == "neu" for d in docs)
        assert all(d["vorschlag"]["sicher"] is False for d in docs)


# --------------------------------------------------------------------------
# XCIV: der Index entsteht beim Start, nicht erst beim ersten Scanlauf
# --------------------------------------------------------------------------

def _bestands_datenbank(zeilen: list[str]):
    """Eine gewachsene Datenbank: Tabelle `dokument` ohne Unique-Index."""
    from sqlalchemy import text
    from sqlmodel import create_engine

    pfad = os.path.join(tempfile.mkdtemp(), "bestand.db")
    motor = create_engine(f"sqlite:///{pfad}")
    with motor.begin() as conn:
        conn.execute(text('CREATE TABLE dokument ('
                          'id INTEGER PRIMARY KEY, pfad VARCHAR NOT NULL, '
                          'dateiname VARCHAR NOT NULL)'))
        for i, p in enumerate(zeilen, 1):
            conn.execute(text('INSERT INTO dokument (id, pfad, dateiname) '
                              f"VALUES ({i}, '{p}', 'x.pdf')"))
    return motor


def _indexnamen(motor) -> set[str]:
    from sqlalchemy import inspect
    return {i["name"] for i in inspect(motor).get_indexes("dokument")}


def test_bestandsdatenbank_bekommt_die_eindeutigkeit_beim_start():
    """XCIV: `unique=True` wirkt nur an einer neu angelegten Tabelle.

    Eine gewachsene Datenbank lief bis zum ersten Scanlauf ohne Index — und
    der kommt vom Wachdienst erst nach 15 Minuten."""
    from sqlalchemy import text
    from app.migrate import migriere

    motor = _bestands_datenbank(["/a/eins.pdf", "/a/zwei.pdf"])
    assert "ux_dokument_pfad" not in _indexnamen(motor)

    migriere(motor)
    assert "ux_dokument_pfad" in _indexnamen(motor)

    import pytest
    from sqlalchemy.exc import IntegrityError
    with pytest.raises(IntegrityError):
        with motor.begin() as conn:
            conn.execute(text("INSERT INTO dokument (pfad, dateiname) "
                              "VALUES ('/a/eins.pdf', 'x.pdf')"))


def test_doppelte_pfade_werden_gemeldet_statt_verschwiegen(caplog):
    """XCIV: gibt es die Doppel schon, wird der Index nicht gesetzt — aber
    protokolliert, welcher Pfad mehrfach dasteht. Gelöscht wird nichts."""
    import logging
    from app.migrate import migriere

    motor = _bestands_datenbank(["/a/doppelt.pdf", "/a/doppelt.pdf"])
    with caplog.at_level(logging.WARNING, logger="immocalc"):
        migriere(motor)

    assert "ux_dokument_pfad" not in _indexnamen(motor)
    assert "/a/doppelt.pdf" in caplog.text
    # und beide Zeilen liegen unangetastet weiter da
    from sqlalchemy import text
    with motor.begin() as conn:
        assert conn.execute(text("SELECT count(*) FROM dokument")).scalar() == 2


def test_index_wird_nach_fehlschlag_erneut_versucht():
    """XCIV: der Merker fiel früher *vor* dem Versuch — ein Fehlschlag wurde
    nie wiederholt, und die Datenbank lief bis zum Neustart ohne
    Eindeutigkeit. Jetzt zählt nur der Erfolg."""
    from sqlalchemy import text
    import app.routers.dokumente as modul
    from app.routers.dokumente import _eindeutigkeit_sichern

    motor = _bestands_datenbank(["/x/gleich.pdf", "/x/gleich.pdf"])
    try:
        modul._index_geprueft = False
        with Session(motor) as s:
            _eindeutigkeit_sichern(s)
        assert modul._index_geprueft is False     # Doppel: noch nicht erledigt

        # Der Nutzer räumt das Doppel auf — nächster Lauf, jetzt klappt es
        with motor.begin() as conn:
            conn.execute(text("UPDATE dokument SET pfad = '/x/anders.pdf' "
                              "WHERE id = 2"))
        with Session(motor) as s:
            _eindeutigkeit_sichern(s)
        assert modul._index_geprueft is True
        assert "ux_dokument_pfad" in _indexnamen(motor)
    finally:
        modul._index_geprueft = False


# --------------------------------------------------------------------------
# XCV: ein vergebener Pfad bricht nichts ab
# --------------------------------------------------------------------------

def test_freier_name_fragt_auch_die_datenbank(monkeypatch):
    """XCV: die Datei ist in der Cloud gelöscht, der Eintrag zeigt weiter
    dorthin. Ohne die zweite Frage verschiebt die Automatik und scheitert
    danach am Eintrag — 500, Datei am Ziel, Datenbank am Eingang."""
    import app.routers.dokumente as modul

    with TestClient(app) as c:
        ordner = "Home/Immobilien/Belegtweg 4"
        slug = _mit_cloud(c, "Belegtweg 4", ordner)
        objekt_id = _objekt_id(slug)
        # Eintrag auf dem Zielpfad — in der Cloud gibt es die Datei nicht mehr
        ziel = ("/Home/Immobilien/Belegtweg 4/70_Steuer_Finanzamt/"
                "2024_Grundsteuerbescheid.pdf")
        with Session(engine) as s:
            s.add(Dokument(pfad=ziel, dateiname="2024_Grundsteuerbescheid.pdf",
                           objekt_id=objekt_id, status="zugeordnet"))
            s.commit()

        wolke = _Wolke(["Grundsteuerbescheid 2024.pdf"], ordner)
        monkeypatch.setattr(modul, "verbindung", lambda session: wolke)

        ergebnis = c.post("/api/dokumente/scan").json()
        assert ergebnis["automatisch"] == 1
        # ausgewichen statt kollidiert
        assert wolke.verschoben[-1][1].endswith("2024_Grundsteuerbescheid-2.pdf")


def test_scanlauf_geht_nach_einem_fehler_weiter(monkeypatch):
    """XCV: eine Datei, die sich nicht ablegen lässt, hält den Lauf nicht an."""
    import app.routers.dokumente as modul

    class _Stolpert(_Wolke):
        def verschiebe(self, von, nach):
            if "Erste" in von:
                raise RuntimeError("Zielordner gesperrt")
            super().verschiebe(von, nach)

    with TestClient(app) as c:
        ordner = "Home/Immobilien/Stolperweg 6"
        slug = _mit_cloud(c, "Stolperweg 6", ordner)
        wolke = _Stolpert(["Erste Stromabrechnung 2024.pdf",
                           "Zweite Wasserrechnung 2024.pdf"], ordner)
        monkeypatch.setattr(modul, "verbindung", lambda session: wolke)

        ergebnis = c.post("/api/dokumente/scan").json()
        assert ergebnis["neu"] == 2
        assert ergebnis["automatisch"] == 1        # die zweite kam durch
        docs = c.get("/api/dokumente", params={"objekt": slug}).json()["dokumente"]
        nach_status = {d["status"] for d in docs}
        assert nach_status == {"neu", "zugeordnet"}


# --------------------------------------------------------------------------
# XC: der Beleg gehört an seinen Zeitraum
# --------------------------------------------------------------------------

def _zeitraum(c, slug: str) -> int:
    return c.post(f"/api/objekte/{slug}/zeitraeume",
                  json={"start": "2024-01-01", "ende": "2024-12-31"}).json()["id"]


def test_scan_merkt_sich_den_zeitraum(monkeypatch):
    """XC: ein Beleg, der von der Abrechnung aus fotografiert wird, landete
    zwar in der Cloud, war am Zeitraum aber nie wiederzufinden."""
    import app.routers.dokumente as modul

    with TestClient(app) as c:
        slug = _mit_cloud(c, "Zeitraumweg 8", "Home/Immobilien/Zeitraumweg 8")
        zid = _zeitraum(c, slug)
        wolke = _Wolke([])
        monkeypatch.setattr(modul, "verbindung", lambda session: wolke)

        antwort = c.post("/api/dokumente/scannen",
                         data={"objekt": slug, "kategorie": "Nebenkosten",
                               "jahr": 2024, "zeitraum_id": zid},
                         files={"datei": ("scan.pdf", b"%PDF-1.4 x",
                                          "application/pdf")})
        assert antwort.status_code == 201
        assert antwort.json()["zeitraum_id"] == zid

        gefiltert = c.get("/api/dokumente", params={"zeitraum": zid}).json()
        assert gefiltert["anzahl"] == 1
        assert gefiltert["dokumente"][0]["zeitraum_id"] == zid


def test_patch_haengt_einen_beleg_an_den_zeitraum(monkeypatch):
    """XC: nachträglich zuordnen — und wieder lösen."""
    import app.routers.dokumente as modul

    with TestClient(app) as c:
        slug = _mit_cloud(c, "Nachtragweg 2", "Home/Immobilien/Nachtragweg 2")
        zid = _zeitraum(c, slug)
        doc = _lege_dokument_an(_objekt_id(slug), "beleg.pdf",
                                kategorie="Nebenkosten", jahr=2024)
        wolke = _Wolke([])
        monkeypatch.setattr(modul, "verbindung", lambda session: wolke)

        antwort = c.patch(f"/api/dokumente/{doc}", json={"zeitraum_id": zid})
        assert antwort.status_code == 200
        assert antwort.json()["zeitraum_id"] == zid

        # unbekannter Zeitraum wird abgelehnt, statt ins Leere zu zeigen
        assert c.patch(f"/api/dokumente/{doc}",
                       json={"zeitraum_id": 999999}).status_code == 404

        gelöst = c.patch(f"/api/dokumente/{doc}", json={"zeitraum_id": None})
        assert gelöst.json()["zeitraum_id"] is None


# --------------------------------------------------------------------------
# CXXVII: den Ordner vollständig neu einlesen
# --------------------------------------------------------------------------

class _Baum:
    """Nextcloud-Ersatz mit Unterordnern — für den Abgleich.

    `inhalt` bildet den Baum ab: Ordnerpfad -> [(Dateiname, Grösse)]. Ein
    Ordner, der nicht als Schlüssel dasteht, gibt es nicht; `liste` meldet
    dann denselben Fehler wie die echte Nextcloud."""

    def __init__(self, inhalt: dict):
        self.inhalt = {"/" + p.strip("/"): list(v) for p, v in inhalt.items()}
        self.verschoben = []
        self.angelegt = []
        self.abgelegt = []

    def liste(self, pfad):
        from app.nextcloud import NextcloudFehler
        p = "/" + pfad.strip("/")
        if p not in self.inhalt:
            raise NextcloudFehler(f"Ordner nicht gefunden: {p}")
        eintraege = [SimpleNamespace(pfad=f"{p}/{n}", name=n, groesse=g,
                                     ordner=False)
                     for n, g in self.inhalt[p]]
        eintraege += [SimpleNamespace(pfad=k, name=k.rsplit("/", 1)[-1],
                                      groesse=0, ordner=True)
                      for k in self.inhalt
                      if k != p and k.rsplit("/", 1)[0] == p]
        return eintraege

    def ordner_anlegen(self, pfad):
        self.angelegt.append(pfad)
        return True

    def existiert(self, pfad):
        return False

    def verschiebe(self, von, nach):
        self.verschoben.append((von, nach))

    def lege_ab(self, pfad, inhalt):
        self.abgelegt.append(pfad)


def _beleg(objekt_id: int, pfad: str, groesse: int = 4096, **felder) -> int:
    """Ein Eintrag, der auf einen bestimmten Cloud-Pfad zeigt."""
    with Session(engine) as s:
        felder.setdefault("status", "zugeordnet")
        felder.setdefault("kategorie", "Nebenkosten")
        d = Dokument(pfad=pfad, dateiname=pfad.rsplit("/", 1)[-1],
                     groesse=groesse, objekt_id=objekt_id,
                     erkannt_am=date.today(), **felder)
        s.add(d)
        s.commit()
        s.refresh(d)
        return d.id


def _stand(doc_id: int) -> Dokument:
    with Session(engine) as s:
        return s.get(Dokument, doc_id)


def test_abgleich_meldet_eine_geloeschte_datei_als_vermisst(monkeypatch):
    """CXXVII: der Nutzer löscht in der Nextcloud selbst. Der Eintrag bleibt
    stehen — mit Zeitraum und Zuordnung —, tut aber nicht mehr so, als läge
    die Datei noch da."""
    import app.routers.dokumente as modul

    with TestClient(app) as c:
        ordner = "Home/Immobilien/Abgleichweg 1"
        slug = _mit_cloud(c, "Abgleichweg 1", ordner)
        doc = _beleg(_objekt_id(slug), f"/{ordner}/60_Nebenkosten/2025_Müll.pdf")
        baum = _Baum({ordner: [], f"{ordner}/60_Nebenkosten": []})
        monkeypatch.setattr(modul, "verbindung", lambda session: baum)

        ergebnis = c.post("/api/dokumente/abgleich").json()
        assert [v["id"] for v in ergebnis["vermisst"]] == [doc]
        assert ergebnis["geprueft"] == 1

        # Der Eintrag lebt weiter, nur gekennzeichnet — gelöscht wird nichts
        assert _stand(doc) is not None
        assert _stand(doc).status == "vermisst"
        assert _stand(doc).kategorie == "Nebenkosten"

        # und die Oberfläche kann es lesen
        daten = c.get("/api/dokumente", params={"objekt": slug}).json()
        assert daten["vermisst"] == 1
        gezeigt = daten["dokumente"][0]
        assert gezeigt["vermisst"] is True
        assert gezeigt["abgelegt"] is False

        # Korrigieren ginge ins Leere und wird ehrlich abgelehnt
        antwort = c.patch(f"/api/dokumente/{doc}", json={"jahr": 2026})
        assert antwort.status_code == 409
        assert "nicht mehr" in antwort.json()["detail"]


def test_abgleich_zieht_eine_verschobene_datei_nach(monkeypatch):
    """Der Nutzer räumt den Beleg selbst in einen anderen Unterordner."""
    import app.routers.dokumente as modul

    with TestClient(app) as c:
        ordner = "Home/Immobilien/Abgleichweg 2"
        slug = _mit_cloud(c, "Abgleichweg 2", ordner)
        doc = _beleg(_objekt_id(slug), f"/{ordner}/60_Nebenkosten/2025_Öl.pdf")
        baum = _Baum({ordner: [], f"{ordner}/60_Nebenkosten": [],
                      f"{ordner}/60_Nebenkosten/2025": [("2025_Öl.pdf", 4096)]})
        monkeypatch.setattr(modul, "verbindung", lambda session: baum)

        ergebnis = c.post("/api/dokumente/abgleich").json()
        assert ergebnis["vermisst"] == []
        assert [v["id"] for v in ergebnis["verschoben"]] == [doc]
        assert _stand(doc).pfad == f"/{ordner}/60_Nebenkosten/2025/2025_Öl.pdf"
        assert _stand(doc).status == "zugeordnet"
        # In der Cloud wurde dabei nichts angefasst
        assert baum.verschoben == []


def test_abgleich_erkennt_eine_umbenannte_datei(monkeypatch):
    """Gleicher Ordner, gleiche Grösse, anderer Name — dieselbe Datei."""
    import app.routers.dokumente as modul

    with TestClient(app) as c:
        ordner = "Home/Immobilien/Abgleichweg 3"
        slug = _mit_cloud(c, "Abgleichweg 3", ordner)
        doc = _beleg(_objekt_id(slug), f"/{ordner}/60_Nebenkosten/alt.pdf",
                     groesse=7777)
        baum = _Baum({ordner: [], f"{ordner}/60_Nebenkosten":
                      [("2025-10_Heizöl_2729,91€.pdf", 7777)]})
        monkeypatch.setattr(modul, "verbindung", lambda session: baum)

        ergebnis = c.post("/api/dokumente/abgleich").json()
        assert [v["id"] for v in ergebnis["umbenannt"]] == [doc]
        assert _stand(doc).dateiname == "2025-10_Heizöl_2729,91€.pdf"
        assert baum.verschoben == []


def test_abgleich_trockenlauf_aendert_nichts(monkeypatch):
    """Erst sehen, dann tun — wie beim Ordnerumzug."""
    import app.routers.dokumente as modul

    with TestClient(app) as c:
        ordner = "Home/Immobilien/Abgleichweg 4"
        slug = _mit_cloud(c, "Abgleichweg 4", ordner)
        doc = _beleg(_objekt_id(slug), f"/{ordner}/60_Nebenkosten/weg.pdf")
        baum = _Baum({ordner: [("Neue Wasserrechnung 2025.pdf", 900)],
                      f"{ordner}/60_Nebenkosten": []})
        monkeypatch.setattr(modul, "verbindung", lambda session: baum)

        plan = c.get("/api/dokumente/abgleich").json()
        assert plan["trockenlauf"] is True
        assert [v["id"] for v in plan["vermisst"]] == [doc]
        # eine Datei in der Cloud ohne Eintrag — gemeldet, nicht angefasst
        assert plan["ohne_eintrag"] == 1
        assert plan["neu"] == 0

        assert _stand(doc).status == "zugeordnet"
        assert baum.verschoben == []


def test_abgleich_nimmt_neue_dateien_gleich_mit(monkeypatch):
    """„Neu einlesen" heisst beides: aufräumen und aufnehmen."""
    import app.routers.dokumente as modul

    with TestClient(app) as c:
        ordner = "Home/Immobilien/Abgleichweg 5"
        slug = _mit_cloud(c, "Abgleichweg 5", ordner)
        baum = _Baum({ordner: [("Wasserrechnung 2025.pdf", 900)],
                      f"{ordner}/60_Nebenkosten": []})
        monkeypatch.setattr(modul, "verbindung", lambda session: baum)

        ergebnis = c.post("/api/dokumente/abgleich").json()
        assert ergebnis["neu"] == 1
        assert ergebnis["automatisch"] == 1
        assert baum.verschoben[-1][1] == \
            f"{ordner}/60_Nebenkosten/2025_Wasserrechnung.pdf"


def test_abgleich_ueberspringt_unlesbare_ordner(monkeypatch):
    """Eine Cloud, die gerade nicht antwortet, darf nicht den ganzen Bestand
    als vermisst melden — das wäre die schlimmste aller Fehlmeldungen."""
    import app.routers.dokumente as modul

    with TestClient(app) as c:
        ordner = "Home/Immobilien/Abgleichweg 6"
        slug = _mit_cloud(c, "Abgleichweg 6", ordner)
        doc = _beleg(_objekt_id(slug), f"/{ordner}/60_Nebenkosten/da.pdf")
        # Der Objektordner fehlt im Baum — er ist nicht lesbar
        baum = _Baum({"Home/Immobilien": []})
        monkeypatch.setattr(modul, "verbindung", lambda session: baum)

        ergebnis = c.post("/api/dokumente/abgleich").json()
        assert ergebnis["vermisst"] == []
        assert any("Abgleichweg 6" in h for h in ergebnis["hinweise"])
        assert _stand(doc).status == "zugeordnet"


def test_vermisster_eintrag_kommt_zurueck(monkeypatch):
    """Der Nutzer legt die Datei wieder hin — dann ist der Eintrag wieder gut."""
    import app.routers.dokumente as modul

    with TestClient(app) as c:
        ordner = "Home/Immobilien/Abgleichweg 7"
        slug = _mit_cloud(c, "Abgleichweg 7", ordner)
        pfad = f"/{ordner}/60_Nebenkosten/2025_Strom.pdf"
        doc = _beleg(_objekt_id(slug), pfad)

        leer = _Baum({ordner: [], f"{ordner}/60_Nebenkosten": []})
        monkeypatch.setattr(modul, "verbindung", lambda session: leer)
        c.post("/api/dokumente/abgleich")
        assert _stand(doc).status == "vermisst"

        voll = _Baum({ordner: [],
                      f"{ordner}/60_Nebenkosten": [("2025_Strom.pdf", 4096)]})
        monkeypatch.setattr(modul, "verbindung", lambda session: voll)
        ergebnis = c.post("/api/dokumente/abgleich").json()
        assert [v["id"] for v in ergebnis["wiederda"]] == [doc]
        assert _stand(doc).status == "zugeordnet"


def test_abgleich_raet_nicht_bei_zwei_gleichen_dateien(monkeypatch):
    """Zwei gleich grosse Dateien im selben Ordner lassen sich nicht
    auseinanderhalten. Dann lieber melden als falsch umhängen."""
    import app.routers.dokumente as modul

    with TestClient(app) as c:
        ordner = "Home/Immobilien/Abgleichweg 8"
        slug = _mit_cloud(c, "Abgleichweg 8", ordner)
        doc = _beleg(_objekt_id(slug), f"/{ordner}/60_Nebenkosten/alt.pdf",
                     groesse=555)
        baum = _Baum({ordner: [], f"{ordner}/60_Nebenkosten":
                      [("eins.pdf", 555), ("zwei.pdf", 555)]})
        monkeypatch.setattr(modul, "verbindung", lambda session: baum)

        ergebnis = c.post("/api/dokumente/abgleich").json()
        assert [v["id"] for v in ergebnis["vermisst"]] == [doc]
        assert _stand(doc).pfad == f"/{ordner}/60_Nebenkosten/alt.pdf"


def test_abgleich_und_scan_laufen_nie_gleichzeitig():
    """Beide lesen dieselben Ordner — sie teilen sich die Sperre."""
    from app.wachdienst import sperre

    with TestClient(app) as c:
        with sperre:
            assert c.post("/api/dokumente/abgleich").status_code == 409
            assert c.get("/api/dokumente/abgleich").status_code == 409
