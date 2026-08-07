"""N240/N247 — das Vorlagenarchiv (`Dokumentvorlage` + `/api/dokumentvorlagen`).

Die reinen DB-Endpunkte (Liste, Typen-Katalog, Löschen) plus die beiden
Riegel des Hochladens, die ohne Cloud prüfbar sind: die erlaubte Dateiart
(N247 — keine Fotos) und der Home-Ordner. Der eigentliche PUT braucht eine
echte Nextcloud-Verbindung und ist hier bewusst nicht Gegenstand, genau wie
bei den vergleichbaren Tests für `kidb`/`Belegdaten`.
"""
import os
import sys
import tempfile
from datetime import date

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_dokumentvorlagen.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session  # noqa: E402

from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Dokumentvorlage  # noqa: E402


def _vorlage(**abweichung) -> Dokumentvorlage:
    daten = dict(name="Übergabeprotokoll", verwendungszweck="Vermietung",
                typ="Übergabeprotokoll Einzug",
                pfad="/[010]_Immobilien/00_Vorlagen/Vermietung/"
                     "Uebergabeprotokoll.pdf",
                dateiname="Uebergabeprotokoll.pdf",
                quelle_url="https://example.org/uebergabeprotokoll.pdf",
                erstellt_am=date.today())
    daten.update(abweichung)
    return Dokumentvorlage(**daten)


def test_liste_ist_leer_ohne_bestand():
    with TestClient(app) as c:
        antwort = c.get("/api/dokumentvorlagen")
    assert antwort.status_code == 200
    daten = antwort.json()
    assert daten["anzahl"] == 0
    assert daten["vorlagen"] == []


def test_liste_nennt_den_typen_katalog_auch_ohne_bestand():
    """N247 — die Oberfläche zeigt je Vorlagenart eine Zeile, auch die noch
    leeren. Der Katalog dafür kommt aus dem Backend, damit er nicht doppelt
    gepflegt wird."""
    from app.routers.dokumentvorlagen import TYPEN_KATALOG

    with TestClient(app) as c:
        daten = c.get("/api/dokumentvorlagen").json()
    assert [t["typ"] for t in daten["typen"]] == [t["typ"] for t in TYPEN_KATALOG]
    # Der Mietvertrag ist bewusst NICHT dabei — zu individuell für eine Vorlage.
    assert not any("Mietvertrag" == t["typ"] for t in daten["typen"])
    assert all(t["verwendungszweck"] == "Vermietung" for t in daten["typen"])


def test_liste_filtert_nach_verwendungszweck_und_typ():
    with TestClient(app) as c, Session(engine) as session:
        session.add(_vorlage())
        session.add(_vorlage(name="Selbstauskunft", typ="Mieterselbstauskunft",
                             pfad="/Vorlagen/Vermietung/Selbstauskunft.pdf",
                             dateiname="Selbstauskunft.pdf"))
        session.commit()

        alle = c.get("/api/dokumentvorlagen").json()
        assert alle["anzahl"] == 2

        gefiltert = c.get("/api/dokumentvorlagen",
                          params={"typ": "Mieterselbstauskunft"}).json()
        assert gefiltert["anzahl"] == 1
        assert gefiltert["vorlagen"][0]["name"] == "Selbstauskunft"
        # Der Katalog folgt demselben Filter — sonst zeigte die Oberfläche
        # Zeilen für Arten, nach denen gar nicht gefragt wurde.
        assert [t["typ"] for t in gefiltert["typen"]] == ["Mieterselbstauskunft"]

        andernorts = c.get("/api/dokumentvorlagen",
                           params={"verwendungszweck": "Sonstiges"}).json()
        assert andernorts["anzahl"] == 0
        assert andernorts["typen"] == []


def test_loeschen_entfernt_nur_den_datenbankeintrag():
    with TestClient(app) as c, Session(engine) as session:
        v = _vorlage()
        session.add(v)
        session.commit()
        session.refresh(v)
        vid = v.id

    with TestClient(app) as c:
        antwort = c.delete(f"/api/dokumentvorlagen/{vid}")
        assert antwort.status_code == 200
        assert antwort.json() == {"ok": True}
        ids = [v["id"] for v in c.get("/api/dokumentvorlagen").json()["vorlagen"]]
        assert vid not in ids

        fehlt = c.delete(f"/api/dokumentvorlagen/{vid}")
        assert fehlt.status_code == 404


def test_es_gibt_keinen_startbestand_aus_dem_netz_mehr():
    """N247 — der Download fremder Muster ist ersatzlos entfallen: er lief in
    den Schreibriegel und war ohnehin nicht gewollt. Vorlagen kommen jetzt
    ausschliesslich vom Nutzer selbst."""
    with TestClient(app) as c:
        antwort = c.post("/api/dokumentvorlagen/startbestand")
    # 405 statt 404: der Pfad trifft nur noch `DELETE /{vorlage_id}` — ein POST
    # darauf gibt es nicht mehr.
    assert antwort.status_code == 405


def test_foto_wird_als_vorlage_abgelehnt():
    """N247 — ausdrücklicher Nutzerwunsch: hier gehören Roh-PDFs hin. Ein
    abfotografiertes Formular taugt nicht als Vordruck zum Ausdrucken.

    Der Riegel greift VOR jedem Cloud-Zugriff — die Absage kommt auch ohne
    eingerichtete Nextcloud, und zwar mit einer Begründung statt eines
    Verbindungsfehlers."""
    with TestClient(app) as c:
        antwort = c.post("/api/dokumentvorlagen",
                         params={"name": "Übergabeprotokoll",
                                 "typ": "Übergabeprotokoll Einzug"},
                         files={"datei": ("scan.jpg", b"\xff\xd8\xff", "image/jpeg")})
    assert antwort.status_code == 400
    assert "Vordruck" in antwort.json()["detail"]


def test_pdf_kommt_bis_zur_cloud_und_scheitert_erst_dort():
    """Die Gegenprobe: eine PDF passiert den Dateiart-Riegel und scheitert
    erst an der (hier nicht eingerichteten) Nextcloud — der Unterschied zur
    Absage oben zeigt, dass wirklich die Dateiart gefiltert wurde."""
    with TestClient(app) as c:
        antwort = c.post("/api/dokumentvorlagen",
                         params={"name": "Übergabeprotokoll",
                                 "typ": "Übergabeprotokoll Einzug"},
                         files={"datei": ("muster.pdf", b"%PDF-1.4",
                                          "application/pdf")})
    assert antwort.status_code == 400
    assert "eingerichtet" in antwort.json()["detail"]
