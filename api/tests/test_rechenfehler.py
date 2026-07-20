"""Fehler aus der Prüfung vom 20.07.2026 — jeder mit seinem Wächter.

Alle Fälle hier waren einmal falsch. Schlägt einer fehl, ist der Fehler
zurück, nicht der Test kaputt.
"""
import os
import sys
import tempfile
from datetime import date

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_rechenfehler.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.cashflow import monate_im_jahr  # noqa: E402
from app.engine import (NegativesGewicht, Position, abrechnung,  # noqa: E402
                        verteile_nach_wert)
from app.frist import frist_datum  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Zeitraum  # noqa: E402


# --------------------------------------------------------------------------
# Rundung: die Summe der Anteile muss die Gesamtkosten treffen — auf den Cent
# --------------------------------------------------------------------------

@pytest.mark.parametrize("kosten,gewichte", [
    (100.0, {"A": 1, "B": 1, "C": 1}),          # 33,33 x 3 = 99,99
    (1000.0, dict.fromkeys("ABCDEFG", 1)),      # 142,86 x 7 = 1000,02
    (847.52, {"Büro": 4.14, "OG": 59.30, "WG": 79.14}),
    (0.01, {"A": 1, "B": 1}),                   # weniger Cent als Parteien
    (12345.67, {"A": 33.33, "B": 33.33, "C": 33.34}),
])
def test_summe_der_anteile_trifft_die_gesamtkosten(kosten, gewichte):
    anteile = verteile_nach_wert(kosten, gewichte)
    assert round(sum(anteile.values()), 2) == round(kosten, 2)
    assert all(round(w, 2) == w for w in anteile.values()), "nicht auf Cent gerundet"


def test_pdf_summe_stimmt_mit_den_einzelposten():
    """Zwei Positionen à 100 € auf drei Parteien: die Zeilen müssen sich zur
    ausgewiesenen Endsumme addieren — daran rechnet der Mieter nach."""
    gewichte = {"A": 1, "B": 1, "C": 1}
    res = abrechnung([Position("Wasser", 100.0, "flaeche", gewichte),
                      Position("Müll", 100.0, "flaeche", gewichte)], {})
    for partei, werte in res["parteien"].items():
        einzeln = sum(p["verteilung"][partei] for p in res["positionen"])
        assert round(einzeln, 2) == werte["kosten"], f"{partei}: {einzeln}"
    assert round(sum(w["kosten"] for w in res["parteien"].values()), 2) == 200.00


def test_gleiche_eingabe_ergibt_immer_dasselbe_ergebnis():
    """Der Restcent darf nicht von der Reihenfolge im dict abhängen."""
    a = verteile_nach_wert(100.0, {"A": 1, "B": 1, "C": 1})
    b = verteile_nach_wert(100.0, {"C": 1, "B": 1, "A": 1})
    assert a == b


# --------------------------------------------------------------------------
# Negative Gewichte: lieber laut abbrechen als still falsch verteilen
# --------------------------------------------------------------------------

def test_negatives_gewicht_wird_abgelehnt():
    """Unterzähler über Hauptzähler: eine Partei bekäme sonst eine Gutschrift,
    die anderen zahlten zusammen mehr als die Gesamtkosten."""
    with pytest.raises(NegativesGewicht):
        verteile_nach_wert(847.52, {"Büro": 5, "OG": 60, "WG": -5})


def test_gewichte_null_verteilen_nichts():
    assert verteile_nach_wert(500.0, {"A": 0, "B": 0}) == {"A": 0.0, "B": 0.0}


# --------------------------------------------------------------------------
# Frist: der 29. Februar darf die Objektliste nicht umwerfen
# --------------------------------------------------------------------------

def test_frist_ueberlebt_den_schalttag():
    z = Zeitraum(objekt_id=1, start=date(2023, 3, 1), ende=date(2024, 2, 29))
    assert frist_datum(z) == date(2025, 2, 28)


def test_frist_bleibt_sonst_taggenau():
    z = Zeitraum(objekt_id=1, start=date(2024, 1, 1), ende=date(2024, 12, 31))
    assert frist_datum(z) == date(2025, 12, 31)


# --------------------------------------------------------------------------
# Mieterwechsel: zwei Mietverhältnisse ergeben zusammen ein Jahr, nicht 13
# --------------------------------------------------------------------------

def test_mieterwechsel_ergibt_zwoelf_monate():
    vorher = monate_im_jahr(date(2025, 1, 1), date(2025, 7, 15), 2025)
    nachher = monate_im_jahr(date(2025, 7, 16), None, 2025)
    assert round(vorher + nachher, 6) == 12.0


def test_volles_jahr_bleibt_zwoelf_monate():
    assert monate_im_jahr(date(2020, 1, 1), None, 2025) == 12.0
    assert monate_im_jahr(date(2024, 1, 1), None, 2024) == 12.0     # Schaltjahr


def test_kurzer_aufenthalt_zaehlt_nicht_als_ganzer_monat():
    """Sechs Tage sind kein Monat — früher waren es genau das."""
    assert monate_im_jahr(date(2025, 1, 15), date(2025, 1, 20), 2025) < 0.3


def test_zeitraum_ausserhalb_des_jahres_zaehlt_nicht():
    assert monate_im_jahr(date(2023, 1, 1), date(2023, 12, 31), 2025) == 0.0


def test_einnahmen_bei_mieterwechsel_bleiben_bei_zwoelf_monatsmieten():
    """Der Fund über die API: 1000 €/Monat, Wechsel zur Jahresmitte."""
    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={
            "name": "Wechselhaus", "ort": "Prüfstadt"}).json()["slug"]
        c.post(f"/api/objekte/{slug}/mieten", json={
            "partei": "Vormieter", "kaltmiete": 1000.0, "turnus": "monatlich",
            "ab_datum": "2025-01-01", "bis_datum": "2025-07-15"})
        c.post(f"/api/objekte/{slug}/mieten", json={
            "partei": "Nachmieter", "kaltmiete": 1000.0, "turnus": "monatlich",
            "ab_datum": "2025-07-16"})

        zeile = next(o for o in c.get("/api/auswertung?jahr=2025").json()["objekte"]
                     if o["slug"] == slug)
        assert zeile["einnahmen"] == pytest.approx(12000.0, abs=1.0)
