"""CCCLIX — ein Teilbetrag einer Position geht vorab direkt auf eine Einheit
(mit eigenem §35a), der Rest läuft nach Schlüssel. Wächter: ohne Vorab bleibt
alles wie bisher, mit Vorab stimmt Summe und §35a-Zuordnung."""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_vorab_split.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def _wasser(c):
    z = c.get("/api/zeitraeume/1").json()
    return next(k for k in z["checkliste"]
                if k["kostenart"] == "Wasser" and k.get("position_id"))


def _parteien(c):
    return c.get("/api/zeitraeume/1/abrechnung").json()["parteien"]


def _ohne_vorab(c, pid):
    """Sauberer Ausgangszustand — die Modul-DB wird von mehreren Tests geteilt."""
    c.patch("/api/positionen/%d" % pid, json={"vorab_betrag": 0, "vorab_einheit": ""})


def test_vorab_teilbetrag_auf_einheit_mit_s35():
    with TestClient(app) as c:
        pid = _wasser(c)["position_id"]
        _ohne_vorab(c, pid)
        base = _parteien(c)
        summe_base = round(sum(v["kosten"] for v in base.values()), 2)
        s35_og_base = round(base["Partei OG"]["s35"], 2)

        # 100 € vorab direkt auf „1. OG" (= Partei OG), als §35a; Rest nach Verbrauch.
        r = c.patch("/api/positionen/%d" % pid,
                    json={"vorab_betrag": 100, "vorab_einheit": "1. OG",
                          "vorab_s35": True})
        assert r.status_code == 200
        neu = _parteien(c)

        # Kein Geld verschwindet — die Gesamtsumme bleibt exakt gleich.
        assert round(sum(v["kosten"] for v in neu.values()), 2) == summe_base
        # Der Vorab-Betrag trägt seinen eigenen §35a: Partei OG bekommt genau
        # 100 € mehr § 35a als ohne Vorab (Wasser war sonst nicht absetzbar).
        assert round(neu["Partei OG"]["s35"] - s35_og_base, 2) == 100.0
        # Partei OG trägt mehr Kosten als vorher (der 100-€-Anteil kommt oben drauf).
        assert neu["Partei OG"]["kosten"] > base["Partei OG"]["kosten"]
        _ohne_vorab(c, pid)   # für nachfolgende Tests wieder aufräumen


def test_ohne_vorab_bleibt_die_abrechnung_unveraendert():
    with TestClient(app) as c:
        pid = _wasser(c)["position_id"]
        _ohne_vorab(c, pid)
        base = _parteien(c)
        # setzen und wieder zurücknehmen — danach muss alles exakt wie zuvor sein.
        c.patch("/api/positionen/%d" % pid,
                json={"vorab_betrag": 50, "vorab_einheit": "2. OG", "vorab_s35": False})
        _ohne_vorab(c, pid)
        zurueck = _parteien(c)
        for partei, w in base.items():
            assert round(zurueck[partei]["kosten"], 2) == round(w["kosten"], 2)
            assert round(zurueck[partei]["s35"], 2) == round(w["s35"], 2)
