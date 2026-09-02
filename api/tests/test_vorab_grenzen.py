"""N457 — Grenzfälle des Vorab-Anteils (CCCLIX).

Gefunden bei der Prüfung in der Nacht auf den 03.09.2026. Ein Vorab-Anteil
schneidet einen Betrag direkt auf eine Einheit heraus, der Rest wird nach
Schlüssel verteilt. Zwei Fälle rechneten still falsch:

1. Ein Vorab GRÖSSER als die Position selbst wurde voll abgerechnet — die
   Abrechnung wies mehr aus, als die Kostenposition hergibt.
2. Zeigte der Vorab auf eine Einheit ohne Bezug (Tippfehler, Einheit von der
   NK-Abrechnung ausgenommen, unbelegt), lieferte `ableiten_einheit` ein
   leeres Gewicht — und `verteile_nach_wert(500, {})` gibt `{}` zurück. Das
   Geld verschwand spurlos und wurde nirgends gemeldet.
"""
import os
import sys
import tempfile
from datetime import date

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(),
                                     "test_vorab_grenzen.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

from app import db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Kostenposition, Zeitraum  # noqa: E402
from app.verteilung import _engine_positionen  # noqa: E402


def _objekt(c, name):
    neu = c.post("/api/objekte", json={
        "name": name,
        "einheiten": [{"bezeichnung": "EG", "flaeche": 60.0, "partei": "Meier"},
                      {"bezeichnung": "OG", "flaeche": 40.0,
                       "partei": "Schmidt"}]}).json()
    slug = neu["slug"]
    for einheit, partei in (("EG", "Meier"), ("OG", "Schmidt")):
        c.post(f"/api/objekte/{slug}/mieten", json={
            "einheit": einheit, "partei": partei, "kaltmiete": 500,
            "ab_datum": "2025-01-01"})
    det = c.get(f"/api/objekte/{slug}").json()
    zid = next(z for z in det["zeitraeume"] if z["status"] == "in Arbeit")["id"]
    return slug, zid


def _position(c, zid, *, betrag, **vorab):
    """Anlegen und danach den Vorab-Anteil setzen — die Vorab-Felder kennt
    nur der PATCH (`PositionIn`), nicht das Anlegen."""
    antwort = c.post(f"/api/zeitraeume/{zid}/positionen", json={
        "kostenart": "Wasser", "betrag": betrag, "schluessel": "flaeche"})
    assert antwort.status_code in (200, 201), antwort.text
    pos = antwort.json()
    if vorab:
        geaendert = c.patch(f"/api/positionen/{pos['id']}", json=vorab)
        assert geaendert.status_code == 200, geaendert.text
    return pos


def _aufgeteilt(zid, pid):
    with Session(db.engine) as s:
        z = s.get(Zeitraum, zid)
        p = s.exec(select(Kostenposition)
                   .where(Kostenposition.id == pid)).one()
        return _engine_positionen(s, z, p)


def test_vorab_groesser_als_die_position_wird_gedeckelt():
    """Mehr als die Position hergibt darf nirgends herauskommen."""
    with TestClient(app) as c:
        slug, zid = _objekt(c, "Vorabweg 1")
        pos = _position(c, zid, betrag=300.0, vorab_betrag=500.0,
                        vorab_einheit="EG")

        teile = _aufgeteilt(zid, pos["id"])
        summe = round(sum(t.kosten for t in teile), 2)
        assert summe == 300.0, (
            f"aufgeteilt wurden {summe} € aus einer 300-€-Position: "
            f"{[(t.kostenart, t.kosten) for t in teile]}")


def test_vorab_auf_eine_unbekannte_einheit_verliert_kein_geld():
    """Zeigt der Vorab ins Leere, muss der Betrag trotzdem ankommen.

    Vorher: `ableiten_einheit` liefert `{}`, `verteile_nach_wert(500, {})`
    ergibt `{}` — 500 € fielen aus der Abrechnung, ohne Hinweis."""
    with TestClient(app) as c:
        slug, zid = _objekt(c, "Vorabweg 2")
        pos = _position(c, zid, betrag=1200.0, vorab_betrag=500.0,
                        vorab_einheit="1. OG")     # heisst in Wahrheit "OG"

        teile = _aufgeteilt(zid, pos["id"])
        verteilt = 0.0
        for t in teile:
            gewichte = t.anteile or {}
            if sum(gewichte.values()) > 0:
                verteilt += t.kosten
        assert round(verteilt, 2) == 1200.0, (
            f"nur {verteilt} € von 1.200 € haben einen Empfänger: "
            f"{[(t.kosten, t.anteile) for t in teile]}")


def test_vorab_auf_eine_echte_einheit_bleibt_unveraendert():
    """Gegenprobe: der gute Fall rechnet weiter wie bisher."""
    with TestClient(app) as c:
        slug, zid = _objekt(c, "Vorabweg 3")
        pos = _position(c, zid, betrag=1200.0, vorab_betrag=500.0,
                        vorab_einheit="EG")

        teile = _aufgeteilt(zid, pos["id"])
        assert round(sum(t.kosten for t in teile), 2) == 1200.0
        vorab = next(t for t in teile if t.kosten == 500.0)
        assert sum((vorab.anteile or {}).values()) > 0
        assert any(round(t.kosten, 2) == 700.0 for t in teile)
