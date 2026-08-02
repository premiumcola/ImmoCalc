"""N73 — Verteilungsschlüssel „prozentual": ein Prozentsatz je Einheit.

Der einfachste Schlüssel: pro Einheit ein Prozentsatz, verteilt wird
proportional zu den Gewichten (cent-genau, ohne Rundungsverlust). Ohne eigene
Angabe fällt er gleichmäßig auf alle Einheiten (100/n), damit nie durch 0
geteilt wird und die Summe stimmt.
"""
import os
import sys
import tempfile
from datetime import date

os.environ.setdefault(
    "DB_PATH", os.path.join(tempfile.mkdtemp(), "test_prozentual.db"))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import verteilung  # noqa: E402
from app.engine import verteile_nach_wert  # noqa: E402
from app.models import Einheit  # noqa: E402

JAHR = date.today().year
START, ENDE = date(JAHR, 1, 1), date(JAHR, 12, 31)


def _einheit(bezeichnung: str) -> Einheit:
    return Einheit(objekt_id=1, bezeichnung=bezeichnung, nk_abrechnung=True)


# ------------------------------------------------ explizite Prozentsätze

def test_explizite_prozente_gehen_exakt_auf():
    """{A:60, B:40} auf 1000 € → 600/400, Summe exakt 1000."""
    v = verteile_nach_wert(1000.0, {"A": 60, "B": 40})
    assert v == {"A": 600.0, "B": 400.0}
    assert sum(v.values()) == 1000.0


def test_ungleiche_nicht_100_summe_geht_auf():
    """Prozente müssen nicht exakt 100 sein — 30/30/40 verteilt proportional,
    cent-genau ohne Rundungsverlust."""
    v = verteile_nach_wert(1000.0, {"A": 30, "B": 30, "C": 40})
    assert v == {"A": 300.0, "B": 300.0, "C": 400.0}
    assert sum(v.values()) == 1000.0


def test_krummer_betrag_bleibt_cent_genau():
    """Auch bei einem Betrag, der nicht glatt aufgeht, ist die Summe der
    zugeteilten Beträge exakt gleich den Gesamtkosten (Größte-Reste)."""
    v = verteile_nach_wert(999.99, {"A": 50, "B": 50})
    assert sum(v.values()) == 999.99


# ---------------------------------------- Vorgabe: gleichmäßig auf alle

def test_ohne_anteile_gleichmaessig_auf_alle_einheiten():
    """3 Einheiten, keine gesetzten Anteile → je 100/3 %, und 999 € teilen
    sich exakt in 333/333/333."""
    b = verteilung.bezuege(
        [_einheit("A"), _einheit("B"), _einheit("C")], [], [], START, ENDE)
    g = verteilung.gewichte("prozentual", b, START, ENDE)
    assert set(g) == {"A", "B", "C"}
    # Je Einheit ein echter Prozentsatz (100/n), Summe rund 100.
    for wert in g.values():
        assert abs(wert - 100 / 3) < 1e-4
    assert abs(sum(g.values()) - 100.0) < 1e-3
    v = verteile_nach_wert(999.0, g)
    assert v == {"A": 333.0, "B": 333.0, "C": 333.0}
    assert sum(v.values()) == 999.0


def test_ableiten_ist_nie_leer_und_teilt_nie_durch_null():
    """Der Default darf nie {} liefern (sonst 0,00 €) — zwei Einheiten → 50/50."""
    b = verteilung.bezuege([_einheit("EG"), _einheit("OG")], [], [], START, ENDE)
    g = verteilung.gewichte("prozentual", b, START, ENDE)
    assert g == {"EG": 50.0, "OG": 50.0}


# ----------------------------------------------------- Metadaten / Bestand

def test_prozentual_ist_als_schluessel_verankert():
    meta = verteilung.SCHLUESSEL["prozentual"]
    assert meta["titel"] == "Prozentual"
    assert meta["einheit"] == "%"
    assert meta["ableitbar"] is True


def test_bestehende_schluessel_bleiben_unveraendert():
    """Keine Regression: die anderen Schlüssel verhalten sich wie zuvor."""
    b = verteilung.bezuege([_einheit("EG"), _einheit("OG")], [], [], START, ENDE)
    # „einheiten" liefert weiterhin rohe Gewichte 1.0, nicht Prozente.
    assert verteilung.gewichte("einheiten", b, START, ENDE) == {"EG": 1.0, "OG": 1.0}
    # „prozent"/„verbrauch"/„individuell" bleiben nicht ableitbar.
    for schluessel in ("verbrauch", "prozent", "individuell"):
        assert verteilung.gewichte(schluessel, b, START, ENDE) == {}
