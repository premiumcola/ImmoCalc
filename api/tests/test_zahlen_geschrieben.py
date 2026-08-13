"""N373 — die deutsche Zahlenschreibweise beim SCHREIBEN, einmal.

`zahlen.deutsch` liest (Text → Zahl), `zahlen.geschrieben` schreibt
(Zahl → Text). Letzteres gab es sechsmal im Backend, in zwei verschiedenen
Techniken: `tanken.satz.deutsch`, `pv.versand._geld`, `kappungsgrenze._geld`,
`abrechnung_pdf._zahl`, `tankabrechnung_pdf._eur`/`._zahl` und
`routers.stromkette._zahl`. Verhaltensgleich, aber sechsfach zu pflegen.

Dieser Test hält beides fest: dass die eine Fassung stimmt, und dass alle
sechs Aufrufer weiterhin genau das ausgeben, was sie vorher ausgaben — die
Beträge stehen in PDFs und in Mails an Mieter.
"""
import os
import sys
import tempfile

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(),
                                              "test_zahlen.db"))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest  # noqa: E402

from app.zahlen import deutsch, fehlt, geschrieben  # noqa: E402


@pytest.mark.parametrize("wert,erwartet", [
    (1234.56, "1.234,56"),
    (0.0, "0,00"),
    (-99.5, "-99,50"),
    (1_000_000, "1.000.000,00"),
    (0.005, "0,01"),          # kaufmännisch gerundet
    (None, "0,00"),           # `geschrieben` behandelt None als Null
])
def test_grundform(wert, erwartet):
    assert geschrieben(wert) == erwartet


def test_stellen_und_einheit():
    assert geschrieben(1234.5678, 3) == "1.234,568"
    assert geschrieben(1234.5, einheit="€") == "1.234,50 €"
    assert geschrieben(12.3, einheit="EUR") == "12,30 EUR"


def test_vorzeichen_wird_nur_auf_wunsch_ausgeschrieben():
    """Für Salden, wo „+ 120,00" und „− 120,00" nebeneinanderstehen."""
    assert geschrieben(120.0) == "120,00"
    assert geschrieben(120.0, vorzeichen=True) == "+120,00"
    # Das Minus steht immer da, auch ohne die Option.
    assert geschrieben(-120.0) == "-120,00"
    assert geschrieben(-120.0, vorzeichen=True) == "-120,00"


def test_fehlend_bleibt_sichtbar_leer():
    """Eine fehlende Angabe als „0,00" zu schreiben ist die Sorte stiller
    Fehler, die in einer Abrechnung nicht auffällt — und dann falsch ist."""
    assert fehlt(None) == "-"
    assert fehlt(None, platzhalter="—") == "—"
    assert fehlt(0.0) == "0,00"
    assert fehlt(12.5) == "12,50"


def test_hin_und_zurueck():
    """Was geschrieben wird, muss sich auch wieder lesen lassen."""
    for wert in (0.0, 1234.56, -99.5, 1_000_000.0, 0.07):
        assert deutsch(geschrieben(wert)) == pytest.approx(wert)


def test_alle_sechs_aufrufer_geben_unveraendert_aus():
    """Die Beträge stehen in PDFs und Mails — hier darf sich nichts verschieben."""
    from app.abrechnung_pdf import _zahl as abrechnung_zahl
    from app.kappungsgrenze import _geld as kappung_geld
    from app.pv.versand import _geld as pv_geld
    from app.routers.stromkette import _zahl as strom_zahl
    from app.tankabrechnung_pdf import _eur as tank_eur
    from app.tankabrechnung_pdf import _zahl as tank_zahl
    from app.tanken.satz import deutsch as satz_deutsch

    assert satz_deutsch(1234.56) == "1.234,56"
    assert satz_deutsch(0.1234, 4) == "0,1234"
    assert pv_geld(1000) == "1.000,00 €"
    assert kappung_geld(1234.5) == "1.234,50 €"
    assert abrechnung_zahl(-99.5) == "-99,50"
    assert abrechnung_zahl(99.5, vorzeichen=True) == "+99,50"
    assert abrechnung_zahl(None) == "0,00"
    assert tank_eur(12.3) == "12,30 EUR"
    assert tank_zahl(None) == "-", "eine fehlende Menge ist keine Null"
    assert tank_zahl(2416.0) == "2.416,00"
    assert strom_zahl(2416.0) == "2.416,00"
