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


def _a(datum, stand, zid=None, notiz=""):
    return SimpleNamespace(datum=datum, stand=stand, zeitraum_id=zid, notiz=notiz)


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


def test_folgeperioden_verlieren_keinen_tag(monkeypatch):
    """N368 — derselbe Off-by-one, eine Periode weiter.

    N315(j) hat den Anker der START-Periode auf das echte Ablesedatum gesetzt.
    Für jede FOLGE-Periode blieb er aber auf `z.ende` — dem letzten Tag der
    Vorperiode statt dem ersten der neuen. `engine.tage` misst exklusiv, also
    war die Ist-Spanne systematisch einen Tag länger als die Soll-Spanne:
    Faktor 364/365 in jeder Periode ab der zweiten.

    Drei lückenlose Jahre mit exakt 1000 Einheiten Verbrauch je Jahr. Jede
    Periode muss 1000 zeigen, und die Summe muss die echte Zählerdifferenz
    treffen — vorher waren es 997,26 ab der zweiten und 3997,26 gesamt.
    """
    p1 = _z(1, date(2023, 10, 1), date(2024, 9, 30))
    p2 = _z(2, date(2024, 10, 1), date(2025, 9, 30))
    p3 = _z(3, date(2025, 10, 1), date(2026, 9, 30))
    ablesungen = [_a(date(2023, 10, 1), 0.0),
                  _a(date(2024, 9, 30), 1000.0),
                  _a(date(2025, 9, 30), 2000.0),
                  _a(date(2026, 9, 30), 3000.0)]

    reihe = ablesung.verbrauchsreihe(ablesungen, [p1, p2, p3])
    for z in (p2, p3):
        assert abs(reihe[z.id]["verbrauch"] - 1000.0) < 1e-6, (
            f"Periode {z.id}: {reihe[z.id]['verbrauch']}")
    gesamt = sum(reihe[z.id]["verbrauch"] for z in (p1, p2, p3))
    assert abs(gesamt - 3000.0) < 1e-6, gesamt


def test_historische_delta_t_werte_werden_nie_als_zaehlerstand_gelesen():
    """N381 — der Fund an echten Daten (Laufer Str. 5, Wärmemengenzähler).

    Wird ein Zähler von `typ='direkt'` (fertiger Jahresverbrauch) auf
    `typ='gemessen'` (echte, kumulierte Stände) umgestellt, bleiben seine
    alten, aus einer fremden Abrechnung importierten Ablesungen als
    `HISTORISCH_PRAEFIX`-markierte Zeilen stehen — sie sind VERBRÄUCHE, keine
    Stände. Ohne die Absicherung griff `_ablesung_fuer` sie als vermeintliche
    Stände auf: 5.463 kWh (30.09.2022) → 3.533 kWh (30.09.2023) ergäbe
    rechnerisch −1.930 kWh Verbrauch für ein historisches Jahr — unmöglich,
    und noch gefährlicher: die anschließende, LAUFENDE Periode würde einen
    plausibel aussehenden, aber komplett falschen Wert erben (~+888 kWh statt
    des echten, noch unbekannten aktuellen Verbrauchs).

    Ohne die Markierung liest sich dieser exakte Datensatz (siehe unten) zu
    genau diesen Zahlen — mit ihr bleiben alle drei Perioden `None`, weil
    keine echte Ablesung vorliegt."""
    histor = "Delta-t-Historie (Saison endet 30.09.2022), nachgetragen"
    p1 = _z(18, date(2018, 10, 1), date(2019, 9, 30))
    p2 = _z(19, date(2022, 10, 1), date(2023, 9, 30))
    p3 = _z(15, date(2024, 10, 1), date(2025, 9, 30))
    ablesungen = [
        _a(date(2022, 9, 30), 5463.0, notiz=histor),
        _a(date(2023, 9, 30), 3533.0, notiz=histor),
        _a(date(2024, 9, 30), 4421.0, notiz=histor),
    ]

    reihe = ablesung.verbrauchsreihe(ablesungen, [p1, p2, p3])
    assert reihe[p1.id] is None
    assert reihe[p2.id] is None, (
        "eine historische Verbrauchszahl wurde als Zählerstand gelesen "
        f"(ergäbe {reihe[p2.id]})")
    assert reihe[p3.id] is None, (
        "die laufende Periode erbte einen aus Verbrauchszahlen "
        f"gerechneten Scheinwert ({reihe[p3.id]})")


def test_historische_werte_stoeren_eine_echte_folgeperiode_nicht():
    """Sobald ein echter Anfangsstand UND eine echte Folgeablesung existieren,
    rechnet die Periode korrekt — die historischen Zeilen bleiben außen vor,
    auch wenn sie näher an der Periodengrenze liegen als der echte Stand."""
    histor = "Delta-t-Historie (Saison endet 30.09.2024), nachgetragen"
    p = _z(15, date(2024, 10, 1), date(2025, 9, 30))
    ablesungen = [
        _a(date(2024, 9, 30), 4421.0, notiz=histor),   # historisch, ignoriert
        _a(date(2024, 10, 1), 500.0),                  # echter Anfangsstand
        _a(date(2025, 9, 30), 800.0),                  # echte Ablesung
    ]
    reihe = ablesung.verbrauchsreihe(ablesungen, [p])
    assert reihe[p.id] is not None
    assert abs(reihe[p.id]["verbrauch"] - 300.0) < 1e-6
