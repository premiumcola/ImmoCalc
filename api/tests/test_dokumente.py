"""Eingangsordner: Benennung, Vermutung und Zuordnung."""
import os
import sys
import tempfile
from datetime import date

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_dokumente.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session  # noqa: E402

from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Dokument, Objekt  # noqa: E402
from app.routers.dokumente import ZIELORDNER, dateiname  # noqa: E402
from app.routers.cloud import STRUKTUR  # noqa: E402


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


def _lege_dokument_an(objekt_id: int, name: str) -> int:
    with Session(engine) as s:
        d = Dokument(pfad=f"/[010]_Immobilien/Test/{name}", dateiname=name,
                     groesse=12345, objekt_id=objekt_id, status="neu",
                     erkannt_am=date.today())
        s.add(d)
        s.commit()
        s.refresh(d)
        return d.id


def test_inbox_zeigt_vermutung():
    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={"name": "Eingangsweg 4"}).json()["slug"]
        with Session(engine) as s:
            objekt_id = s.exec(
                __import__("sqlmodel").select(Objekt).where(Objekt.slug == slug)).first().id

        _lege_dokument_an(objekt_id, "Grundsteuerbescheid_2024.pdf")
        _lege_dokument_an(objekt_id, "Stromabrechnung-2025.pdf")

        inbox = c.get("/api/dokumente/inbox").json()
        assert inbox["anzahl"] >= 2
        nach_name = {d["dateiname"]: d for d in inbox["dokumente"]}

        grund = nach_name["Grundsteuerbescheid_2024.pdf"]["vorschlag"]
        assert grund["kategorie"] == "Steuer"
        assert grund["jahr"] == 2024

        strom = nach_name["Stromabrechnung-2025.pdf"]["vorschlag"]
        assert strom["kategorie"] == "Nebenkosten"
        assert strom["jahr"] == 2025


def test_zuordnen_ohne_cloud_benennt_um():
    """Ohne verknüpften Nextcloud-Ordner wird nur umbenannt, nicht verschoben."""
    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={"name": "Ablageweg 9"}).json()["slug"]
        with Session(engine) as s:
            import sqlmodel
            objekt_id = s.exec(
                sqlmodel.select(Objekt).where(Objekt.slug == slug)).first().id
        doc = _lege_dokument_an(objekt_id, "irgendwas.pdf")

        antwort = c.post(f"/api/dokumente/{doc}/zuordnen", json={
            "objekt": slug, "kategorie": "Nebenkosten", "jahr": 2024,
            "beschreibung": "Wasser", "verschieben": False})
        assert antwort.status_code == 200
        assert antwort.json()["dateiname"] == "2024_Nebenkosten_Wasser.pdf"

        # verschwindet aus dem Eingang und taucht beim Objekt auf
        offen = [d["id"] for d in c.get("/api/dokumente/inbox").json()["dokumente"]]
        assert doc not in offen
        beim_objekt = c.get(f"/api/dokumente/objekt/{slug}").json()
        assert any(d["id"] == doc for d in beim_objekt)


def test_unbekanntes_dokument_ist_404():
    with TestClient(app) as c:
        antwort = c.post("/api/dokumente/999999/zuordnen", json={
            "objekt": "egal", "kategorie": "Sonstiges"})
        assert antwort.status_code == 404
