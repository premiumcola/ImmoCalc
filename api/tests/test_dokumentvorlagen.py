"""N240 — das Vorlagenarchiv (`Dokumentvorlage` + `/api/dokumentvorlagen`).

Nur die reinen DB-Endpunkte (Liste, Löschen) — Hochladen/Ansehen brauchen eine
echte Nextcloud-Verbindung und sind hier bewusst nicht Gegenstand, genau wie
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
                pfad="/Vorlagen/Vermietung/Uebergabeprotokoll.pdf",
                dateiname="Uebergabeprotokoll.pdf",
                quelle_url="https://example.org/uebergabeprotokoll.pdf",
                erstellt_am=date.today())
    daten.update(abweichung)
    return Dokumentvorlage(**daten)


def test_liste_ist_leer_ohne_bestand():
    with TestClient(app) as c:
        antwort = c.get("/api/dokumentvorlagen")
    assert antwort.status_code == 200
    assert antwort.json() == {"anzahl": 0, "vorlagen": []}


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

        andernorts = c.get("/api/dokumentvorlagen",
                           params={"verwendungszweck": "Sonstiges"}).json()
        assert andernorts["anzahl"] == 0


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


def test_startbestand_braucht_eingerichtete_nextcloud():
    """Ohne Nextcloud-Zugangsdaten wird kein Netzwerkzugriff versucht — der
    Aufruf scheitert sauber mit derselben Meldung wie jeder andere
    schreibende Cloud-Zugriff ohne Einrichtung."""
    with TestClient(app) as c:
        antwort = c.post("/api/dokumentvorlagen/startbestand")
    assert antwort.status_code == 400
    assert "eingerichtet" in antwort.json()["detail"]


def test_startbestand_ist_leerer_durchlauf_wenn_nichts_fehlt():
    """Ist jeder Typ des Startbestands schon vorhanden, wird nicht einmal
    nach der Nextcloud gefragt (kein Zugangsdaten-Fehler trotz fehlender
    Einrichtung) — reiner Abgleich."""
    from app.routers.dokumentvorlagen import STARTBESTAND

    with TestClient(app) as c, Session(engine) as session:
        for eintrag in STARTBESTAND:
            session.add(_vorlage(name=eintrag["name"], typ=eintrag["typ"],
                                 pfad=f"/Vorlagen/Vermietung/{eintrag['dateiname']}",
                                 dateiname=eintrag["dateiname"]))
        session.commit()

        antwort = c.post("/api/dokumentvorlagen/startbestand")
        assert antwort.status_code == 200
        assert antwort.json() == {"angelegt": 0, "fehler": []}
