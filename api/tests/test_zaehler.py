"""N157 — die E-Tankstelle am Zähler: gezogen statt getippt.

Drei Dinge werden hier festgehalten:

1. **Wer ist die Ladestation?** Genau eine Regel (`ist_eauto_zaehler`) — am
   Merkmal in `art`, ersatzweise am Namen. Nur kWh-Zähler kommen in Frage.
2. **Eine Menge, nicht zwei.** Der gezogene Wert wird als *Ablesung dieses
   Zählers* abgelegt. Damit rechnet alles Bestehende (Rest = Gesamt − Unter-
   zähler) unverändert weiter, und es gibt keine zweite Stelle, an der eine
   E-Auto-Menge steht.
3. **Keine Null, wenn die Box schweigt.** Antwortet die Wallbox nicht, bleibt
   der zuletzt gezogene Stand stehen — eine 0 wäre eine Falschaussage.

Die Kontrollzahlen (01.10.2024–30.09.2025: 81 Ladungen · 1373,84 kWh) stammen
vom echten Objekt und stehen in `test_kontrollzahlen_landen_am_zaehler`.
"""
import os
import sys
import tempfile
from datetime import date

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_zaehler.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

from app.main import app  # noqa: E402
from app.models import Zaehler, Zeitraum  # noqa: E402
from app.routers import zaehler as zaehler_router  # noqa: E402

VON, BIS = date(2024, 10, 1), date(2025, 9, 30)

# Was die Box am echten Objekt für den Abrechnungszeitraum liefert.
ECHT = {"ok": True, "hinweis": "", "quelle": "http://192.168.178.61",
        "von": VON.isoformat(), "bis": BIS.isoformat(),
        "anzahl": 81, "kwh": 1373.84, "extern_kwh": 522.34,
        "eigen_kwh": 851.5, "warnungen": []}

STUMM = {"ok": False, "kwh": None, "anzahl": None,
         "hinweis": "Die Wallbox hat nicht geantwortet.",
         "von": VON.isoformat(), "bis": BIS.isoformat()}


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def box(monkeypatch):
    """Die Wallbox als Attrappe — der echte Endpunkt ginge ins Heimnetz."""
    zustand = {"antwort": ECHT}

    def _ladungen(von, bis, session):
        zustand["gesehen"] = (von, bis)
        antwort = zustand["antwort"]
        if isinstance(antwort, Exception):
            raise antwort
        return antwort

    monkeypatch.setattr(zaehler_router, "openwb_ladungen", _ladungen)
    return zustand


def _zaehler_modell(name: str, art: str = "", messeinheit: str = "kWh") -> Zaehler:
    return Zaehler(objekt_id=1, name=name, art=art, messeinheit=messeinheit)


# --------------------------------------------------------------------------
# 1) Wer ist die Ladestation?
# --------------------------------------------------------------------------

def test_ladestation_am_namen_erkannt():
    # Beide Schreibweisen — die alte und die, auf die der Nutzer umbenannt hat.
    assert zaehler_router.ist_eauto_zaehler(_zaehler_modell("Stromverbrauch Elektroauto"))
    assert zaehler_router.ist_eauto_zaehler(_zaehler_modell("Stromverbrauch E-Tankstelle"))
    assert zaehler_router.ist_eauto_zaehler(_zaehler_modell("Ladesäule Hof"))
    assert zaehler_router.ist_eauto_zaehler(_zaehler_modell("Wallbox"))


def test_ladestation_ueberlebt_ein_umbenennen():
    # Steht das Merkmal in `art`, darf der Name beliebig heißen.
    assert zaehler_router.ist_eauto_zaehler(
        _zaehler_modell("Auto von Alicia", art="E-Tankstelle"))


def test_andere_zaehler_sind_keine_ladestation():
    assert not zaehler_router.ist_eauto_zaehler(
        _zaehler_modell("Verbrauch Strom Gesamt (SolarEdge)"))
    assert not zaehler_router.ist_eauto_zaehler(_zaehler_modell("Scheune Zähler"))
    # Ein Wasserzähler ist nie eine Ladestation, wie er auch heißt.
    assert not zaehler_router.ist_eauto_zaehler(
        _zaehler_modell("E-Tankstelle", messeinheit="m³"))


# --------------------------------------------------------------------------
# 2) Der Zug aus dem Ladeprotokoll
# --------------------------------------------------------------------------

def _objekt(c) -> str:
    return c.post("/api/objekte", json={
        "name": "Ladehaus", "ort": "Eschenau", "turnus": "kalender",
        "start_monat": 10, "kostenarten": ["Strom"],
        "einheiten": [{"bezeichnung": "EG", "flaeche": 70.0, "partei": "Müller"},
                      {"bezeichnung": "1.OG", "flaeche": 80.0, "partei": "Meier"}],
    }).json()["slug"]


def _zeitraum(c, slug: str) -> int:
    for z in c.get(f"/api/objekte/{slug}").json()["zeitraeume"]:
        if z["start"] == VON.isoformat() and z["ende"] == BIS.isoformat():
            return z["id"]
    return c.post(f"/api/objekte/{slug}/zeitraeume",
                  json={"start": VON.isoformat(), "bis": BIS.isoformat(),
                        "ende": BIS.isoformat()}).json()["id"]


def _lade_objekt(c, name: str = "Stromverbrauch E-Tankstelle") -> tuple[str, int, int]:
    """Objekt mit Gesamtzähler + Ladestation und dem Zeitraum 10/24–09/25."""
    slug = _objekt(c)
    zid = _zeitraum(c, slug)
    gesamt = c.post(f"/api/objekte/{slug}/zaehler", json={
        "name": "Verbrauch Strom Gesamt (SolarEdge)", "kostenart": "Strom",
        "messeinheit": "kWh", "typ": "direkt"}).json()["id"]
    c.post(f"/api/zaehler/{gesamt}/ablesungen",
           json={"stand": 10800.0, "datum": BIS.isoformat(), "zeitraum_id": zid})
    lade = c.post(f"/api/objekte/{slug}/zaehler", json={
        "name": name, "kostenart": "Strom", "messeinheit": "kWh",
        "typ": "direkt", "hauptzaehler_id": gesamt}).json()["id"]
    return slug, zid, lade


def _zeile(c, zid: int, zaehler_id: int) -> dict:
    maske = c.get(f"/api/zeitraeume/{zid}/ablesung").json()
    return next(z for z in maske["zaehler"] if z["id"] == zaehler_id)


def test_kontrollzahlen_landen_am_zaehler(client, box):
    slug, zid, lade = _lade_objekt(client)
    d = client.post(f"/api/zeitraeume/{zid}/eauto").json()

    assert d["ok"] is True
    assert d["anzahl"] == 81
    assert d["kwh"] == 1373.84
    assert d["gespeichert"] is True
    assert d["zaehler_id"] == lade
    # Gezogen wird nach den MONATEN der Periode, nicht nach Kalenderjahr.
    assert box["gesehen"] == (VON, BIS)

    # Die Menge steht jetzt am Zähler — dort, wo alles Bestehende sie liest.
    zeile = _zeile(client, zid, lade)
    assert zeile["verbrauch"] == 1373.84
    assert zeile["ablesung"]["stand"] == 1373.84
    assert zeile["ablesung"]["datum"] == BIS.isoformat()


def test_kein_zweiter_ort_fuer_die_menge(client, box):
    """Der gezogene Wert ist die Ablesung selbst — keine Kopie daneben."""
    slug, zid, lade = _lade_objekt(client)
    client.post(f"/api/zeitraeume/{zid}/eauto")
    abls = client.get(f"/api/zaehler/{lade}/ablesungen").json()
    assert len(abls) == 1
    assert abls[0]["stand"] == 1373.84

    # Ein zweiter Zug legt nichts daneben, sondern erkennt: steht schon so.
    d = client.post(f"/api/zeitraeume/{zid}/eauto").json()
    assert d["gespeichert"] is False
    assert d["stand"] == 1373.84
    assert len(client.get(f"/api/zaehler/{lade}/ablesungen").json()) == 1


def test_neuer_wert_ersetzt_den_alten(client, box):
    slug, zid, lade = _lade_objekt(client)
    client.post(f"/api/zeitraeume/{zid}/eauto")
    box["antwort"] = {**ECHT, "kwh": 1400.5, "anzahl": 83}
    d = client.post(f"/api/zeitraeume/{zid}/eauto").json()
    assert d["gespeichert"] is True
    assert _zeile(client, zid, lade)["verbrauch"] == 1400.5
    assert len(client.get(f"/api/zaehler/{lade}/ablesungen").json()) == 1


def test_der_rest_rechnet_mit_dem_gezogenen_wert(client, box):
    """Verbrauch Haus = Gesamt − Ladestation: unverändert dieselbe Rechnung."""
    slug, zid, lade = _lade_objekt(client)
    gesamt = _zeile(client, zid, lade)["hauptzaehler_id"]
    rest = client.post(f"/api/objekte/{slug}/zaehler", json={
        "name": "Verbrauch Haus — errechnet", "kostenart": "Strom",
        "messeinheit": "kWh", "typ": "rest", "hauptzaehler_id": gesamt}).json()["id"]
    client.post(f"/api/zeitraeume/{zid}/eauto")
    assert _zeile(client, zid, rest)["verbrauch"] == round(10800.0 - 1373.84, 3)


# --------------------------------------------------------------------------
# 3) Wenn die Box schweigt: keine Null
# --------------------------------------------------------------------------

def test_stumme_box_laesst_den_alten_wert_stehen(client, box):
    slug, zid, lade = _lade_objekt(client)
    client.post(f"/api/zeitraeume/{zid}/eauto")

    box["antwort"] = STUMM
    d = client.post(f"/api/zeitraeume/{zid}/eauto").json()
    assert d["ok"] is False
    assert d["kwh"] is None          # keine 0 — das wäre eine Messung
    assert d["gespeichert"] is False
    assert d["hinweis"]
    assert d["stand"] == 1373.84     # der zuletzt gezogene Wert bleibt
    assert _zeile(client, zid, lade)["verbrauch"] == 1373.84


def test_ausfall_der_box_ist_kein_serverfehler(client, box):
    slug, zid, lade = _lade_objekt(client)
    client.post(f"/api/zeitraeume/{zid}/eauto")
    box["antwort"] = RuntimeError("Netz weg")
    antwort = client.post(f"/api/zeitraeume/{zid}/eauto")
    assert antwort.status_code == 200
    assert antwort.json()["ok"] is False
    assert antwort.json()["stand"] == 1373.84


def test_abgeschlossener_zeitraum_wird_nicht_ueberschrieben(client, box):
    slug, zid, lade = _lade_objekt(client)
    client.post(f"/api/zeitraeume/{zid}/eauto")

    from app import db as db_modul
    with Session(db_modul.engine) as s:
        z = s.get(Zeitraum, zid)
        z.status = "abgeschlossen"
        s.add(z)
        s.commit()

    box["antwort"] = {**ECHT, "kwh": 9999.0}
    d = client.post(f"/api/zeitraeume/{zid}/eauto").json()
    assert d["gespeichert"] is False
    assert _zeile(client, zid, lade)["verbrauch"] == 1373.84


def test_ohne_ladestation_bleibt_es_ruhig(client, box):
    slug = _objekt(client)
    zid = _zeitraum(client, slug)
    d = client.post(f"/api/zeitraeume/{zid}/eauto").json()
    assert d["zaehler_id"] is None
    assert d["ok"] is False
    assert d["hinweis"]


# --------------------------------------------------------------------------
# 4) Was die Oberfläche daraus liest
# --------------------------------------------------------------------------

def test_maske_kennzeichnet_die_ladestation(client, box):
    slug, zid, lade = _lade_objekt(client)
    maske = client.get(f"/api/zeitraeume/{zid}/ablesung").json()
    markiert = [z["id"] for z in maske["zaehler"] if z["eauto"]]
    assert markiert == [lade]


def test_merkmal_wird_festgeschrieben(client, box):
    """Nach dem ersten Zug steht das Merkmal in `art` — ein Umbenennen später
    verliert die Erkennung dann nicht mehr."""
    slug, zid, lade = _lade_objekt(client)
    client.post(f"/api/zeitraeume/{zid}/eauto")
    client.patch(f"/api/zaehler/{lade}", json={"name": "Auto von Alicia"})

    from app import db as db_modul
    with Session(db_modul.engine) as s:
        assert s.get(Zaehler, lade).art == zaehler_router.EAUTO_ART
    assert _zeile(client, zid, lade)["eauto"] is True


def test_wer_laedt_kommt_mit(client, box):
    slug, zid, lade = _lade_objekt(client)
    assert client.post(f"/api/zeitraeume/{zid}/eauto").json()["nutzer"] == []
    client.post(f"/api/tankstelle/{slug}/nutzer",
                json={"name": "Alicia", "email": "a@example.org"})
    assert client.post(f"/api/zeitraeume/{zid}/eauto").json()["nutzer"] == ["Alicia"]


def test_ein_vorhandenes_merkmal_bleibt_stehen(client, box):
    """Ein vom Nutzer gepflegtes `art` wird nicht überschrieben."""
    slug, zid, lade = _lade_objekt(client)
    client.patch(f"/api/zaehler/{lade}", json={"art": "Wallbox Hof"})
    client.post(f"/api/zeitraeume/{zid}/eauto")
    from app import db as db_modul
    with Session(db_modul.engine) as s:
        assert s.get(Zaehler, lade).art == "Wallbox Hof"


def test_unbekannter_zeitraum(client, box):
    assert client.post("/api/zeitraeume/999999/eauto").status_code == 404


def test_bestehende_ablesungen_bleiben_unberuehrt(client, box):
    """Der Zug rührt NUR den Ladestations-Zähler an."""
    slug, zid, lade = _lade_objekt(client)
    from app import db as db_modul
    with Session(db_modul.engine) as s:
        vorher = {(a.zaehler_id, a.stand) for a in s.exec(
            select(zaehler_router.Ablesung)).all() if a.zaehler_id != lade}
    client.post(f"/api/zeitraeume/{zid}/eauto")
    with Session(db_modul.engine) as s:
        nachher = {(a.zaehler_id, a.stand) for a in s.exec(
            select(zaehler_router.Ablesung)).all() if a.zaehler_id != lade}
    assert vorher == nachher
