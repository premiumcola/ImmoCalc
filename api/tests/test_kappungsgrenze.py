"""CLXXVI — Kappungsgrenze nach § 558 Abs. 3 BGB.

Eckental ist seit 01.01.2026 Gebiet mit angespanntem Wohnungsmarkt
(Bayerische Mieterschutzverordnung vom 16.12.2025, GVBl. S. 718). Dort sind
binnen drei Jahren 15 % möglich statt der allgemeinen 20 %.
"""
import os
import sys
import tempfile
from datetime import date

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_kappung.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402

from app.kappungsgrenze import (ALLGEMEIN, ANGESPANNT, basismiete,  # noqa: E402
                                gemeinde_fuer, grenze_fuer, pruefe)
from app.main import app  # noqa: E402


class _Ort:
    """Ein Objekt, so viel davon wie die Prüfung braucht."""

    def __init__(self, plz="", ort="", ags=""):
        self.plz, self.ort, self.ags = plz, ort, ags


class _Stand:
    def __init__(self, ab, kaltmiete):
        self.ab_datum, self.kaltmiete = ab, kaltmiete


HEUTE = date(2026, 7, 21)


# --------------------------------------------------------------------------
# Welche Gemeinde ist gemeint
# --------------------------------------------------------------------------

def test_ortsteile_gehoeren_zu_ihrer_gemeinde():
    """Eschenau, Eckenhaid und Unterschöllenbach stehen nirgends in der
    Verordnung — sie sind Ortsteile von Eckental."""
    for ort in ("Eschenau", "Eckenhaid", "Unterschöllenbach"):
        g = gemeinde_fuer(_Ort(ort=ort))
        assert g is not None and g.ags == "09572121"


def test_die_verordnung_schreibt_eckenthal_mit_th():
    """Die Falle: ein Namensabgleich mit „Eckental" liefe ins Leere. Beide
    Schreibweisen treffen dieselbe Gemeinde — verbindlich ist der AGS."""
    assert gemeinde_fuer(_Ort(ort="Eckenthal")).ags == "09572121"
    assert gemeinde_fuer(_Ort(ort="Eckental")).ags == "09572121"
    assert gemeinde_fuer(_Ort(ags="09572121")).name == "Eckental"


def test_postleitzahl_reicht_auch_ohne_ortsnamen():
    assert gemeinde_fuer(_Ort(plz="90542")).ags == "09572121"
    assert gemeinde_fuer(_Ort(plz="90402")).ags == "09564000"   # Nürnberg
    assert gemeinde_fuer(_Ort(plz="91054", ort="Erlangen")) is None


def test_zusaetze_am_ortsnamen_stoeren_nicht():
    assert gemeinde_fuer(_Ort(ort="Eckental b.Nürnberg")).ags == "09572121"
    assert gemeinde_fuer(_Ort(ort="Eschenau, Eckental")).ags == "09572121"


def test_woanders_gilt_die_allgemeine_grenze():
    lage = grenze_fuer(_Ort(plz="91074", ort="Herzogenaurach"), HEUTE)
    assert lage["prozent"] == ALLGEMEIN
    assert lage["angespannt"] is False
    assert "§ 558" in lage["fundstelle"]


def test_die_verordnung_gilt_nur_in_ihrem_zeitraum():
    """Sie läuft vom 01.01.2026 bis 31.12.2029 — davor und danach zählen
    wieder 20 %, ohne dass jemand ein Datum pflegen muss."""
    ort = _Ort(ort="Eschenau")
    assert grenze_fuer(ort, date(2025, 12, 31))["prozent"] == ALLGEMEIN
    assert grenze_fuer(ort, date(2026, 1, 1))["prozent"] == ANGESPANNT
    assert grenze_fuer(ort, date(2029, 12, 31))["prozent"] == ANGESPANNT
    assert grenze_fuer(ort, date(2030, 1, 1))["prozent"] == ALLGEMEIN


def test_die_oberflaeche_erfaehrt_worauf_sich_die_grenze_stuetzt():
    lage = grenze_fuer(_Ort(ort="Eckenhaid"), HEUTE)
    assert lage["gemeinde"] == "Eckental"
    assert lage["ags"] == "09572121"
    assert lage["gueltig_bis"] == "2029-12-31"
    assert "Mieterschutzverordnung" in lage["fundstelle"]
    assert "5.3.5" in lage["fundstelle"]


# --------------------------------------------------------------------------
# Welche Miete ist die Basis
# --------------------------------------------------------------------------

def test_basis_ist_die_miete_von_vor_drei_jahren():
    staende = [_Stand(date(2019, 1, 1), 500.0),
               _Stand(date(2022, 7, 1), 600.0),      # vor dem Stichtag
               _Stand(date(2025, 1, 1), 700.0)]      # danach — zählt nicht
    basis = basismiete(staende, date(2026, 9, 1))
    assert basis["kaltmiete"] == 600.0
    assert basis["ab_datum"] == "2022-07-01"
    assert basis["stichtag"] == "2023-09-01"


def test_ein_junges_mietverhaeltnis_zaehlt_ab_der_ausgangsmiete():
    staende = [_Stand(date(2025, 3, 1), 800.0)]
    basis = basismiete(staende, date(2026, 9, 1))
    assert basis["kaltmiete"] == 800.0
    assert basis["vollstaendig"] is False


# --------------------------------------------------------------------------
# Die Prüfung selbst
# --------------------------------------------------------------------------

def test_ueber_fuenfzehn_prozent_wird_in_eckental_gewarnt():
    staende = [_Stand(date(2022, 1, 1), 600.0)]
    ergebnis = pruefe(_Ort(plz="90542", ort="Eschenau"), staende,
                      700.0, date(2026, 10, 1))
    assert ergebnis["grenze_prozent"] == 15.0
    assert ergebnis["hoechstmiete"] == 690.0
    assert ergebnis["erhoehung_prozent"] == 16.7
    assert ergebnis["ueberschritten"] is True
    assert "690,00 €" in ergebnis["text"]
    # Überschrift und Erklärung getrennt — und die Grenze steht nur einmal
    # im Text, nicht in beiden.
    assert ergebnis["titel"] == "Über der Kappungsgrenze von 15 %"
    assert "Kappungsgrenze" not in ergebnis["text"]


def test_dieselbe_erhoehung_ist_anderswo_zulaessig():
    """20 % statt 15 % — dieselben Zahlen, andere Gemeinde."""
    staende = [_Stand(date(2022, 1, 1), 600.0)]
    ergebnis = pruefe(_Ort(plz="91074", ort="Herzogenaurach"), staende,
                      700.0, date(2026, 10, 1))
    assert ergebnis["grenze_prozent"] == 20.0
    assert ergebnis["hoechstmiete"] == 720.0
    assert ergebnis["ueberschritten"] is False


def test_genau_auf_der_grenze_ist_noch_erlaubt():
    staende = [_Stand(date(2022, 1, 1), 600.0)]
    ergebnis = pruefe(_Ort(ort="Eckenhaid"), staende, 690.0, date(2026, 10, 1))
    assert ergebnis["ueberschritten"] is False
    assert ergebnis["erhoehung_prozent"] == 15.0


def test_ohne_neue_miete_wird_nur_der_rahmen_genannt():
    staende = [_Stand(date(2022, 1, 1), 600.0)]
    ergebnis = pruefe(_Ort(ort="Eschenau"), staende, None, date(2026, 10, 1))
    assert ergebnis["hoechstmiete"] == 690.0
    assert ergebnis["ueberschritten"] is False
    assert ergebnis["neue_kaltmiete"] is None


def test_ohne_frueheren_stand_wird_nichts_behauptet():
    ergebnis = pruefe(_Ort(ort="Eschenau"), [], 900.0, date(2026, 10, 1))
    assert ergebnis["hoechstmiete"] is None
    assert ergebnis["ueberschritten"] is False
    assert ergebnis["basis"] is None
    assert "Ohne eine frühere Kaltmiete" in ergebnis["text"]


# --------------------------------------------------------------------------
# Über die API — so, wie die Oberfläche fragt
# --------------------------------------------------------------------------

def _objekt_mit_miete(c, name, ort, plz, alt_miete, ab):
    slug = c.post("/api/objekte", json={"name": name, "ort": ort,
                                        "plz": plz}).json()["slug"]
    mid = c.post(f"/api/objekte/{slug}/mieten", json={
        "einheit": "Wohnung 1", "partei": "Familie Muster",
        "kaltmiete": alt_miete, "ab_datum": ab.isoformat()}).json()["id"]
    return slug, mid


def test_endpunkt_warnt_bei_mehr_als_fuenfzehn_prozent():
    with TestClient(app) as c:
        slug, mid = _objekt_mit_miete(c, "Eschenauer Weg 1", "Eschenau",
                                      "90542", 600.0, date(2021, 1, 1))
        assert slug
        antwort = c.get(f"/api/mieten/{mid}/kappungsgrenze",
                        params={"neu": 700.0, "ab": "2026-10-01"}).json()
        assert antwort["gemeinde"] == "Eckental"
        assert antwort["grenze_prozent"] == 15.0
        assert antwort["ueberschritten"] is True
        assert antwort["hoechstmiete"] == 690.0
        assert "Mieterschutzverordnung" in antwort["fundstelle"]


def test_endpunkt_schweigt_bei_einer_massvollen_erhoehung():
    with TestClient(app) as c:
        _, mid = _objekt_mit_miete(c, "Eckenhaider Weg 2", "Eckenhaid",
                                   "90542", 600.0, date(2021, 1, 1))
        antwort = c.get(f"/api/mieten/{mid}/kappungsgrenze",
                        params={"neu": 660.0, "ab": "2026-10-01"}).json()
        assert antwort["ueberschritten"] is False
        assert antwort["erhoehung_prozent"] == 10.0


def test_endpunkt_zaehlt_nur_die_eigene_partei():
    """Eine Erhöhung bemisst sich am eigenen Mietverhältnis, nicht an dem des
    Vormieters — sonst wäre jeder Mieterwechsel eine Erhöhung."""
    with TestClient(app) as c:
        slug, _ = _objekt_mit_miete(c, "Wechselweg 3", "Eschenau", "90542",
                                    400.0, date(2018, 1, 1))
        neu = c.post(f"/api/objekte/{slug}/mieten", json={
            "einheit": "Wohnung 2", "partei": "Nachmieter",
            "kaltmiete": 700.0, "ab_datum": "2025-01-01"}).json()["id"]
        antwort = c.get(f"/api/mieten/{neu}/kappungsgrenze",
                        params={"neu": 760.0, "ab": "2026-10-01"}).json()
        assert antwort["basis"]["kaltmiete"] == 700.0
        assert antwort["basis"]["vollstaendig"] is False
