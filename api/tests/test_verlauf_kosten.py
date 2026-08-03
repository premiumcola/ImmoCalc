"""N188 — der Monatsverlauf trägt zusätzlich die Ladekosten (€) und die
Reichweite (km).

Beide Felder sind **additiv**: sie treten neben die bestehenden kWh-Blöcke, je
Monatszeile und in der Summe. `kosten` folgt dem abgeleiteten Satz (N148) und
bleibt leer, wo es keinen Satz gibt — **keine 0,00 € als Notnagel**. `km`
rechnet die geladenen kWh über den mittleren Verbrauch der Nutzer in
Kilometer um und bleibt leer, solange kein Verbrauch gepflegt ist.

Wie in `test_tankstelle.py`: kein Test geht ins Netz. Die Wallbox meldet sich
nicht, die erfassten Ladungen tragen den Verlauf.
"""
import os
import sys
import tempfile
from datetime import date

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_verlauf_kosten.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

from app import db as db_modul  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (Kostenposition, Objekt,  # noqa: E402
                        Stromjahr, Zeitraum)
from app.routers import tankstelle as t  # noqa: E402
from app import eauto  # noqa: E402


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _neues_objekt(c, name: str) -> str:
    antwort = c.post("/api/objekte", json={
        "name": name, "ort": "Teststadt", "turnus": "kalender",
        "start_monat": 1, "kostenarten": ["Strom"],
        "einheiten": [{"bezeichnung": "EG", "flaeche": 70.0,
                       "partei": "Müller"}],
    })
    assert antwort.status_code == 201, antwort.text
    return antwort.json()["slug"]


def _nutzer(c, slug: str, name: str, verbrauch: float = 0.0) -> dict:
    antwort = c.post(f"/api/tankstelle/{slug}/nutzer", json={"name": name})
    assert antwort.status_code == 201, antwort.text
    n = antwort.json()
    if verbrauch > 0:
        r = c.put(f"/api/tankstelle/{slug}/nutzer/{n['id']}",
                  json={"verbrauch_kwh_100km": verbrauch})
        assert r.status_code == 200, r.text
        n = r.json()
    return n


def _ladung(c, slug: str, jahr: int, **werte) -> dict:
    antwort = c.post(f"/api/objekte/{slug}/tankstelle/{jahr}", json=werte)
    assert antwort.status_code == 201, antwort.text
    return antwort.json()


def _jahresaufteilung(slug: str, jahr: int, extern: float, eigen: float) -> None:
    with Session(db_modul.engine) as session:
        o = session.exec(select(Objekt).where(Objekt.slug == slug)).one()
        sj = session.exec(select(Stromjahr).where(
            Stromjahr.objekt_id == o.id, Stromjahr.jahr == jahr)).first()
        if sj is None:
            sj = Stromjahr(objekt_id=o.id, jahr=jahr)
        sj.eauto_extern_kwh = extern
        sj.eauto_eigen_kwh = eigen
        session.add(sj)
        session.commit()


def _stromkosten(slug: str, jahr: int, betrag: float,
                 von: date, bis: date, netz_kwh: float = 5000.0) -> None:
    """Die Stromkosten einer Periode setzen — die Grundlage des Satzes (N148).

    Wie in `test_tankstelle.py`: direkt am Datensatz. 5.000 kWh Netzbezug zum
    genannten Betrag ergeben den Netzsatz Betrag ÷ 5.000."""
    with Session(db_modul.engine) as session:
        o = session.exec(select(Objekt).where(Objekt.slug == slug)).one()
        z = session.exec(select(Zeitraum).where(
            Zeitraum.objekt_id == o.id, Zeitraum.start == von)).first()
        if z is None:
            z = Zeitraum(objekt_id=o.id, start=von, ende=bis)
            session.add(z)
            session.commit()
            session.refresh(z)
        sj = session.exec(select(Stromjahr).where(
            Stromjahr.objekt_id == o.id, Stromjahr.jahr == jahr)).first()
        if sj is None:
            sj = Stromjahr(objekt_id=o.id, jahr=jahr)
        sj.gesamt_kwh = 10000.0
        sj.netz_kwh, sj.solar_kwh, sj.akku_kwh = netz_kwh, 3000.0, 2000.0
        session.add(sj)
        session.add(Kostenposition(zeitraum_id=z.id, kostenart="Strom",
                                   betrag=betrag, herkunft="extern",
                                   menge=netz_kwh, menge_einheit="kWh"))
        session.commit()


def test_verlauf_rows_und_summe_tragen_kosten_und_km_als_schluessel(client):
    """Die Felder sind immer da — auch im nackten Leerzustand ohne Ladung."""
    slug = _neues_objekt(client, "Schluesselhaus")
    d = client.get(f"/api/tankstelle/{slug}/verlauf",
                   params={"jahr": 2025}).json()
    assert len(d["monate"]) == 12
    for m in d["monate"]:
        assert "kosten" in m and "km" in m
    assert "kosten" in d["summe"] and "km" in d["summe"]


def test_km_folgt_dem_mittleren_verbrauch_der_nutzer(client):
    """Mit einem gepflegten Verbrauch ist `km` eine positive Zahl und deckt sich
    mit `gefahrene_km(kwh, Durchschnitt)`."""
    slug = _neues_objekt(client, "Reichweitehaus")
    _nutzer(client, slug, "Marvin", verbrauch=20.0)
    _nutzer(client, slug, "Alicia", verbrauch=10.0)   # Durchschnitt = 15
    _ladung(client, slug, 2025, name="Marvin", kwh=150.0, datum="2025-03-05")

    d = client.get(f"/api/tankstelle/{slug}/verlauf",
                   params={"jahr": 2025}).json()
    maerz = next(m for m in d["monate"] if m["monat"] == 3)
    erwartet = round(eauto.gefahrene_km(150.0, 15.0))
    assert maerz["km"] == erwartet
    assert maerz["km"] > 0
    # Die Summe ist die Summe der belegten Monate.
    assert d["summe"]["km"] == erwartet


def test_ohne_verbrauch_bleibt_km_leer(client):
    """Kein Nutzer mit Verbrauch → jede Reichweite und die Summe bleiben leer,
    statt eine Zahl zu erfinden."""
    slug = _neues_objekt(client, "Verbrauchslos")
    _nutzer(client, slug, "Marvin")                   # ohne Verbrauch
    _ladung(client, slug, 2025, name="Marvin", kwh=80.0, datum="2025-04-09")

    d = client.get(f"/api/tankstelle/{slug}/verlauf",
                   params={"jahr": 2025}).json()
    assert all(m["km"] is None for m in d["monate"])
    assert d["summe"]["km"] is None


def test_kosten_leer_ohne_ableitbaren_satz(client):
    """Ohne Stromkosten gibt es keinen Satz — dann bleibt `kosten` leer (keine
    0,00 €), das Feld existiert aber."""
    slug = _neues_objekt(client, "Ohnesatz")
    _jahresaufteilung(slug, 2025, extern=60.0, eigen=40.0)
    _nutzer(client, slug, "Marvin")
    _ladung(client, slug, 2025, name="Marvin", kwh=100.0, datum="2025-03-05")

    d = client.get(f"/api/tankstelle/{slug}/verlauf",
                   params={"jahr": 2025}).json()
    maerz = next(m for m in d["monate"] if m["monat"] == 3)
    assert "kosten" in maerz
    assert maerz["kosten"] is None
    assert d["summe"]["kosten"] is None


def test_kosten_folgen_dem_abgeleiteten_satz(client):
    """Mit Stromkosten und bekannter Aufteilung ist `kosten` positiv und deckt
    sich mit Netz-kWh × Netzsatz + Eigen-kWh × Eigensatz (N148)."""
    slug = _neues_objekt(client, "Mitsatz")
    # Periode 01.10.2024–30.09.2025: 2.400 € / 5.000 kWh Netz = 0,48 €/kWh.
    _stromkosten(slug, 2025, betrag=2400.0,
                 von=date(2024, 10, 1), bis=date(2025, 9, 30))
    _jahresaufteilung(slug, 2025, extern=60.0, eigen=40.0)
    _nutzer(client, slug, "Marvin")
    _ladung(client, slug, 2025, name="Marvin", kwh=100.0, datum="2025-03-05")

    d = client.get(f"/api/tankstelle/{slug}/verlauf",
                   params={"jahr": 2025}).json()
    maerz = next(m for m in d["monate"] if m["monat"] == 3)
    erwartet = round(maerz["extern_kwh"] * 0.48
                     + maerz["eigen_kwh"] * t.eigen_satz(0.48), 2)
    assert maerz["kosten"] == erwartet
    assert maerz["kosten"] > 0
    assert d["summe"]["kosten"] == erwartet
