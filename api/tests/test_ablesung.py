"""N315(j) — Regressionstest für den Off-by-one bei der Tagezählung in
`ablesung.verbrauchsreihe`.

Bug: die Startablesung einer Reihe (roher Zählerstand, nicht interpoliert)
wurde mit `z.ende` (dem Soll-Stichtag der Periode) statt mit dem tatsächlichen
Ablesedatum als Anker für die Folgeperiode fortgeschrieben. Fiel die Ablesung
nicht exakt auf die Periodengrenze (z.B. Periodenende 30.09., Ablesung am
01.10.), fehlte der Folgeperiode ein Ist-Tag — ein systematischer Streckfaktor
von 364/365 statt 1,0, rund -0,27 % Fehler im interpolierten Verbrauch.
"""
from datetime import date
from types import SimpleNamespace

from app import ablesung, engine


def _z(id, start, ende):
    return SimpleNamespace(id=id, start=start, ende=ende)


def _a(datum, stand, zid=None):
    return SimpleNamespace(datum=datum, stand=stand, zeitraum_id=zid)


def test_ist_tage_zaehlen_kein_tag_zu_wenig_bei_lueckenlosen_perioden():
    """Zwei Perioden, die sich exakt am Kalendertag abloesen (Periode 0 endet
    30.09., Periode 1 beginnt 01.10.) und deren Ablesungen genau auf die
    Periodengrenzen fallen (01.10. und 30.09. des Folgejahres): Ist-Tage und
    Soll-Tage der zweiten Periode muessen exakt uebereinstimmen (beide
    `engine.tage(01.10., 30.09.)` = 364) — vorher lieferte die Startablesung
    ihren Anker auf `z.ende` (30.09. der VORperiode) statt auf ihr eigenes
    Datum (01.10.), was einen Tag verschluckte und eine Streckung um 364/365
    erzwang, obwohl gar keine noetig war. Bei Ist-Tage == Soll-Tage darf keine
    Streckung stattfinden, der Verbrauch ist dann die reine Standdifferenz."""
    vorlauf = _z(0, date(2023, 10, 1), date(2024, 9, 30))
    z = _z(1, date(2024, 10, 1), date(2025, 9, 30))
    ablesungen = [_a(date(2024, 10, 1), 4706.0),
                  _a(date(2025, 9, 30), 9468.068965517241)]

    tage_ist = engine.tage(date(2024, 10, 1), date(2025, 9, 30))
    tage_soll = engine.tage(z.start, z.ende)
    assert tage_ist == tage_soll == 364

    reihe = ablesung.verbrauchsreihe(ablesungen, [vorlauf, z])
    # Ist-Tage == Soll-Tage -> keine Streckung, reine Differenz.
    assert abs(reihe[z.id]["verbrauch"] - (9468.068965517241 - 4706.0)) < 1e-9


def test_musterstrasse_referenz_unveraendert():
    """Faellt die Startablesung exakt auf die Periodengrenze (wie im echten
    Musterstraße-Fall), aendert der Fix nichts: 142.577 bleibt exakt."""
    z0 = _z(0, date(2023, 1, 1), date(2023, 10, 1))
    z1 = _z(1, date(2024, 1, 1), date(2024, 12, 31))
    ablesungen = [_a(date(2023, 10, 1), 634.1256), _a(date(2024, 10, 11), 781.0)]

    reihe = ablesung.verbrauchsreihe(ablesungen, [z0, z1])
    assert abs(reihe[z1.id]["verbrauch"] - 142.577) < 0.01


# --------------------------------------------------------------------------
# N352 — Altperioden ohne eigene Ablesung dürfen keinen fremden Stand greifen
# --------------------------------------------------------------------------
def test_altperiode_greift_nicht_den_anfangsstand_einer_spaeteren():
    """Der echte Fund an der Laufer Str. 5 (Zähler „Liter Öl Heizung"):

    Das Objekt hat Altzeiträume 2018/19 und 2022/23, für die dieser Zähler nie
    abgelesen wurde — er wird erst seit 1.10.2024 geführt. Vorher griff sich
    2018/19 den Anfangsstand vom 1.10.2024 als „seine" Ablesung und 2022/23
    schob den Randwert-Anker auf den 30.9.2023; die eigentliche Periode
    2024/25 rechnete ihre 3.431 Liter danach über 731 statt 364 Ist-Tage —
    angezeigt wurden 1.708,46 statt 3.431 Liter, also fast genau die Hälfte.
    """
    alt1 = _z(18, date(2018, 10, 1), date(2019, 9, 30))
    alt2 = _z(19, date(2022, 10, 1), date(2023, 9, 30))
    lauf = _z(15, date(2024, 10, 1), date(2025, 9, 30))
    ablesungen = [_a(date(2024, 10, 1), 19696.0),            # Anfangsstand
                  _a(date(2025, 9, 30), 23127.0, zid=15)]    # abgelesen

    reihe = ablesung.verbrauchsreihe(ablesungen, [alt1, alt2, lauf])

    # Die Altperioden kennen diesen Zähler nicht — kein erfundener Verbrauch.
    assert reihe[alt1.id] is None
    assert reihe[alt2.id] is None
    # Und die laufende Periode rechnet die volle Differenz, nicht die halbe.
    assert abs(reihe[lauf.id]["verbrauch"] - 3431.0) < 1e-9


def test_anfangsstand_bleibt_anker_auch_ohne_vorlaufperiode():
    """Derselbe Mechanismus ohne Altperioden: liegt ein ungetaggter Stand VOR
    dem Beginn der ersten Periode, ist er deren Randwert — die Periode ist
    dann keine blosse Startablesung mit Verbrauch 0."""
    z = _z(1, date(2024, 10, 1), date(2025, 9, 30))
    ablesungen = [_a(date(2024, 10, 1), 100.0),
                  _a(date(2025, 9, 30), 400.0, zid=1)]

    reihe = ablesung.verbrauchsreihe(ablesungen, [z])
    assert abs(reihe[z.id]["verbrauch"] - 300.0) < 1e-9
