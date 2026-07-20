"""Erinnerungen aus Kostenart-Turnus und gesetzlicher Frist."""
import os
import sys
import tempfile
from datetime import date

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_erinnerungen.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402

from app.erinnerungen import (beleg_erinnerung, frist_erinnerung,  # noqa: E402
                              termin_im_jahr)
from app.main import app  # noqa: E402


def test_termin_ist_monatsanfang_plus_karenz():
    assert termin_im_jahr(6, 7, 2026) == date(2026, 6, 8)
    assert termin_im_jahr(1, 14, 2026) == date(2026, 1, 15)


def test_verstrichener_termin_ohne_beleg_ist_ueberfaellig():
    """Der Kern: ein fehlender Beleg darf nicht ins nächste Jahr wegrutschen."""
    heute = date(2026, 7, 20)
    offen = beleg_erinnerung("Strom", 6, 7, False, heute)   # Juni ist vorbei
    assert offen["faellig"] is True
    assert offen["tage"] < 0


def test_beleg_erinnerung_nur_ohne_beleg():
    heute = date(2026, 7, 20)
    # Beleg liegt schon vor -> keine Erinnerung
    assert beleg_erinnerung("Strom", 6, 7, True, heute) is None
    # Juni + 7 Tage ist vorbei und der Beleg fehlt -> fällig
    offen = beleg_erinnerung("Strom", 6, 7, False, heute)
    assert offen["faellig"] is True
    assert "Strom" in offen["text"]
    # ohne Belegmonat gibt es nichts zu erinnern
    assert beleg_erinnerung("Müll", None, 7, False, heute) is None


def test_frist_erinnerung_erst_im_vorlauf():
    assert frist_erinnerung("2024", 200) is None          # noch weit weg
    nah = frist_erinnerung("2024", 30)
    assert nah["faellig"] is False
    ueber = frist_erinnerung("2024", -5)
    assert ueber["faellig"] is True
    assert "überschritten" in ueber["text"]


def test_endpunkt_liefert_erinnerungen():
    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={
            "name": "Erinnerweg 2", "turnus": "kalender",
            "kostenarten": ["Strom"],
        }).json()["slug"]

        # Kostenart mit Belegmonat versehen
        arten = c.get(f"/api/objekte/{slug}/kostenarten").json()
        strom = next(k for k in arten if k["name"] == "Strom")
        assert strom["turnus_start_monat"] == 1        # Vorgabe
        assert strom["erinnerung_tage"] == 7

        daten = c.get("/api/erinnerungen").json()
        assert "erinnerungen" in daten and "faellig" in daten
        # Fristerinnerungen tragen ihren Zeitraum, Belegerinnerungen ihre Kostenart
        for e in daten["erinnerungen"]:
            assert e["art"] in ("frist", "beleg")
            assert e["objekt"] and e["text"]
