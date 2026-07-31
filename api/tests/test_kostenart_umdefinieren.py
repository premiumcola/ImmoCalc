"""CCCLXII — eine Position auf eine andere Kostenart umhängen.

Fälle:
- eine noch unbekannte Zielart wird als Katalog-Eintrag angelegt (keine Waise);
- der Umzug auf eine Art, die im selben Zeitraum schon eine Position hat, wird
  als Konflikt (409) abgelehnt — eine Position je Kostenart bleibt die Regel;
- ein leerer Name wird abgelehnt;
- Wächter: hin und wieder zurück lässt die Abrechnung exakt unverändert.
"""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(),
                                     "test_kostenart_umdefinieren.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def _row(c, name):
    z = c.get("/api/zeitraeume/1").json()
    return next((k for k in z["checkliste"] if k["kostenart"] == name), None)


def _belegte_andere(c, ausser):
    z = c.get("/api/zeitraeume/1").json()
    return next(k for k in z["checkliste"]
                if k.get("position_id") and k["kostenart"] != ausser)


def _restore(c, pid):
    c.patch("/api/positionen/%d" % pid, json={"kostenart": "Wasser"})


def test_neue_kostenart_wird_als_katalog_angelegt():
    with TestClient(app) as c:
        pid = _row(c, "Wasser")["position_id"]
        neu = "Gebäudeversicherung Spezial"
        arten = [k["name"] for k in c.get("/api/objekte/obj-a/kostenarten").json()]
        assert neu not in arten
        r = c.patch("/api/positionen/%d" % pid, json={"kostenart": neu})
        assert r.status_code == 200
        assert r.json()["kostenart"] == neu
        # jetzt im Katalog des Objekts — konfigurierbar, keine namenlose Waise
        arten2 = [k["name"] for k in c.get("/api/objekte/obj-a/kostenarten").json()]
        assert neu in arten2
        umgezogen = _row(c, neu)
        assert umgezogen and umgezogen["position_id"] == pid
        _restore(c, pid)


def test_umzug_auf_belegte_art_ist_konflikt():
    with TestClient(app) as c:
        pid = _row(c, "Wasser")["position_id"]
        ziel = _belegte_andere(c, "Wasser")["kostenart"]
        r = c.patch("/api/positionen/%d" % pid, json={"kostenart": ziel})
        assert r.status_code == 409
        # Wasser bleibt unangetastet
        assert _row(c, "Wasser")["position_id"] == pid
        _restore(c, pid)


def test_leerer_name_wird_abgelehnt():
    with TestClient(app) as c:
        pid = _row(c, "Wasser")["position_id"]
        r = c.patch("/api/positionen/%d" % pid, json={"kostenart": "   "})
        assert r.status_code == 400
        _restore(c, pid)


def test_hin_und_zurueck_laesst_abrechnung_unveraendert():
    with TestClient(app) as c:
        pid = _row(c, "Wasser")["position_id"]
        vorher = c.get("/api/zeitraeume/1/abrechnung").json()["parteien"]
        c.patch("/api/positionen/%d" % pid,
                json={"kostenart": "Wasser Zwischenname"})
        _restore(c, pid)
        nachher = c.get("/api/zeitraeume/1/abrechnung").json()["parteien"]
        for partei, w in vorher.items():
            assert round(nachher[partei]["kosten"], 2) == round(w["kosten"], 2)
            assert round(nachher[partei]["s35"], 2) == round(w["s35"], 2)
