"""N120 — Strom aus Zählerständen, Referenzzahlen aus NK-ALL-Strom-Verbrauch.xlsx.

Blatt „Strom-Ablesezahlen", Abrechnungszeitraum 01.10.2024–30.09.2025:

    Gesamt nach SolarEdge      L6  = 10800      (Absolutwert, „kein einzelwert")
    Zwischenzähler Anbau       L8  =  4762,069  (= K8 − I8, beide interpoliert)
    Stromverbrauch E-Auto      L9  =  1373,86   (Jahreswert aus Einzelposten)
    Scheune                    L10 =    46,026
    Verbrauch Haus errechnet   L12 =  4618,045  (= L6 − L8 − L9 − L10)

Die Rollen bilden sich auf das bestehende Zähler-Modell ab: ein Hauptzähler
(Gesamt), die gemessenen bzw. direkt erfassten Unterzähler und das Haus als
`typ='rest'`. Der feste 60/40-Split der Vorgängerlösung entfällt damit.
"""
from datetime import date
from types import SimpleNamespace

from app import ablesung, engine


def _z(id, start, ende):
    return SimpleNamespace(id=id, start=start, ende=ende)


def _zaehler(id, typ="gemessen", haupt=None):
    return SimpleNamespace(id=id, typ=typ, hauptzaehler_id=haupt)


def _a(datum, stand, zid=None):
    return SimpleNamespace(datum=datum, stand=stand, zeitraum_id=zid)


def test_interpolation_wie_in_der_excel():
    """E8 der Excel: zwischen 01.06.2023 (0) und 07.11.2023 (1482) ergibt der
    01.10.2023 den Stand 1137,132075471698 — 1482 × 122/159."""
    tage_ist = engine.tage(date(2023, 6, 1), date(2023, 11, 7))
    assert tage_ist == 159
    tage_soll = engine.tage(date(2023, 6, 1), date(2023, 10, 1))
    assert tage_soll == 122
    stand = engine.interpoliere_verbrauch(0.0, 1482.0, tage_ist, tage_soll)
    assert abs(stand - 1137.132075471698) < 1e-9


def test_haus_ist_gesamt_minus_anbau_eauto_scheune():
    """Die Kernformel L12 = L6 − L8 − L9 − L10 fällt aus dem Rest-Zähler."""
    z = _z(1, date(2024, 10, 1), date(2025, 9, 30))
    gesamt = _zaehler(10, "direkt")
    anbau = _zaehler(11, "gemessen", haupt=10)
    eauto = _zaehler(12, "direkt", haupt=10)
    scheune = _zaehler(13, "gemessen", haupt=10)
    haus = _zaehler(14, "rest", haupt=10)

    zma = [
        # Gesamt und E-Auto sind Jahreswerte ohne Zählerstände.
        (gesamt, [_a(date(2025, 9, 30), 10800.0, zid=1)]),
        (eauto, [_a(date(2025, 9, 30), 1373.86, zid=1)]),
        # Anbau und Scheune tragen die beiden Randstände der Periode.
        (anbau, [_a(date(2024, 10, 1), 4706.0), _a(date(2025, 9, 30), 9468.068965517241)]),
        (scheune, [_a(date(2024, 10, 1), 2923.684210526316),
                   _a(date(2025, 9, 30), 2969.7105263157896)]),
        (haus, []),
    ]
    vorlauf = _z(0, date(2023, 10, 1), date(2024, 9, 30))
    verb = ablesung.verbrauch_je_zaehler(zma, [vorlauf, z], 1)

    assert verb[10] == 10800.0                       # Gesamt, direkt
    assert verb[12] == 1373.86                       # E-Auto, direkt

    # Die gemessenen Zaehler weichen um den Faktor 364/365 von der Excel ab:
    # die Vorperiode endet am 30.09., die neue beginnt am 01.10.; die Engine
    # schreibt den Randwert auf das Periodenende fort und rechnet die Stand-
    # differenz damit ueber 365 Tage, verteilt sie aber auf eine Periode von
    # 364 Tagen (`engine.tage` ist eine reine Differenz). Die Excel nimmt
    # stattdessen K8 - I8 ohne Streckung. Bewusst NICHT hier geradegezogen:
    # dieselbe Interpolation traegt Wasser und Heizoel samt der Musterstrasse-
    # Referenz. Die Konvention gehoert in die Rechenkonzept-Durchsicht (N90).
    assert abs(verb[11] - 4762.068965517241 * 364 / 365) < 1e-6   # Anbau
    assert abs(verb[13] - 46.026315789473756 * 364 / 365) < 1e-6  # Scheune

    # Die Kernformel der Excel gilt unabhaengig davon exakt:
    # Haus = Gesamt - Anbau - E-Auto - Scheune.
    assert abs(verb[14] - (verb[10] - verb[11] - verb[12] - verb[13])) < 1e-9
    # ... und liegt damit im Promillebereich an der Excel-Zahl 4618,045.
    assert abs(verb[14] - 4618.044718693285) < 15.0


def test_direkt_zaehler_wird_vom_rest_abgezogen():
    """Ohne den Abzug der direkt erfassten Geschwister bliebe der E-Auto-Strom
    im Haus hängen — das war der Fehler der 60/40-Aufteilung."""
    z = _z(1, date(2024, 10, 1), date(2025, 9, 30))
    zma = [
        (_zaehler(10, "direkt"), [_a(date(2025, 9, 30), 1000.0, zid=1)]),
        (_zaehler(12, "direkt", haupt=10), [_a(date(2025, 9, 30), 300.0, zid=1)]),
        (_zaehler(14, "rest", haupt=10), []),
    ]
    verb = ablesung.verbrauch_je_zaehler(zma, [z], 1)
    assert verb[14] == 700.0


def test_direkt_ohne_wert_bleibt_leer():
    """Ein Jahreswert, der für diesen Zeitraum nicht erfasst ist, gilt nicht als
    Null — sonst sähe eine fehlende Angabe wie ein Verbrauch von 0 aus."""
    z = _z(1, date(2024, 10, 1), date(2025, 9, 30))
    zma = [(_zaehler(10, "direkt"), [_a(date(2023, 9, 30), 500.0, zid=99)])]
    verb = ablesung.verbrauch_je_zaehler(zma, [z], 1)
    assert verb[10] is None
