"""Zähler-Ablesungen → interpolierter Verbrauch je Abrechnungszeitraum (CCXCIII).

Verdrahtet die reinen, getesteten Engine-Funktionen (`interpoliere_verbrauch`,
`rest_verbrauch`, `tage`) mit den gespeicherten Ablesungen. `engine.py` bleibt
unberührt — die 142.577-Referenz läuft hier nur durch.

Modell wie in der Muster-Excel: je Abrechnungszeitraum eine Ablesung (nahe dem
Periodenende). Der interpolierte Stand zum Soll-Stichtag (`Zeitraum.ende`) wird
als Randwert in die nächste Periode fortgeschrieben; der Verbrauch einer Periode
ist die Differenz der beiden Randwerte — linear auf Tagesbasis hochgerechnet.
"""
from datetime import date
from typing import Optional

from . import engine


def _ablesung_fuer(ablesungen: list, z) -> Optional[object]:
    """Die Ablesung, die diesen Zeitraum abschließt: bevorzugt die ausdrücklich
    diesem Zeitraum zugeordnete (`zeitraum_id`), sonst die mit dem zum
    Periodenende nächstgelegenen Datum."""
    getaggt = [a for a in ablesungen if getattr(a, "zeitraum_id", None) == z.id]
    if getaggt:
        # N109 - bei mehreren Ablesungen desselben Zeitraums zaehlt die, die der
        # Periodengrenze am naechsten liegt, NICHT die spaeteste. Nach einem
        # Perioden-Split bleiben Altablesungen mit derselben `zeitraum_id`, aber
        # weit spaeterem Datum stehen; die spaeteste zu nehmen streckte die
        # Interpolation auf den alten, laengeren Zeitraum (28,1 m3 wurden so zu
        # 17,758 m3).
        return min(getaggt, key=lambda a: abs(engine.tage(z.ende, a.datum)))
    if not ablesungen:
        return None
    return min(ablesungen, key=lambda a: abs(engine.tage(z.ende, a.datum)))


def verbrauchsreihe(ablesungen: list, zeitraeume: list) -> dict:
    """{zeitraum_id: {"verbrauch", "randwert", "datum", "stand"}} über alle
    Zeiträume (nach Ende sortiert). Die erste Periode mit Ablesung ist die
    Startablesung — ihr Verbrauch ist 0, ihr Stand wird zum Randwert."""
    geordnet = sorted(zeitraeume, key=lambda z: z.ende)
    randwert: Optional[float] = None
    randdatum: Optional[date] = None
    out: dict = {}
    for z in geordnet:
        a = _ablesung_fuer(ablesungen, z)
        if a is None:
            out[z.id] = None
            continue
        if randwert is None:                       # Startablesung
            randwert, randdatum = a.stand, z.ende
            out[z.id] = {"verbrauch": 0.0, "randwert": randwert,
                         "datum": a.datum, "stand": a.stand, "start": True}
            continue
        tage_ist = engine.tage(randdatum, a.datum)
        tage_soll = engine.tage(z.start, z.ende)
        verb = engine.interpoliere_verbrauch(randwert, a.stand, tage_ist, tage_soll)
        randwert = randwert + verb
        randdatum = z.ende
        out[z.id] = {"verbrauch": verb, "randwert": randwert,
                     "datum": a.datum, "stand": a.stand, "start": False}
    return out


def verbrauch_je_zaehler(zaehler_mit_ablesungen: list, zeitraeume: list,
                         zid: int) -> dict:
    """Verbrauch aller Zähler für einen Zeitraum. `zaehler_mit_ablesungen` ist
    eine Liste von (zaehler, [ablesungen]). Rest-Zähler (`typ='rest'`) ergeben
    sich als Gesamt (ihr `hauptzaehler_id`) minus die gemessenen Geschwister."""
    verb: dict[int, Optional[float]] = {}
    reihen: dict[int, dict] = {}
    for zaehler, ablesungen in zaehler_mit_ablesungen:
        reihe = verbrauchsreihe(ablesungen, zeitraeume)
        reihen[zaehler.id] = reihe
        eintrag = reihe.get(zid)
        verb[zaehler.id] = eintrag["verbrauch"] if eintrag else None

    # Rest-Zähler: Gesamt minus die gemessenen Unterzähler desselben Hauptzählers
    for zaehler, _ in zaehler_mit_ablesungen:
        if zaehler.typ != "rest" or not zaehler.hauptzaehler_id:
            continue
        gesamt = verb.get(zaehler.hauptzaehler_id)
        if gesamt is None:
            continue
        gemessen = [verb[z.id] for z, _ in zaehler_mit_ablesungen
                    if z.hauptzaehler_id == zaehler.hauptzaehler_id
                    and z.typ == "gemessen" and verb.get(z.id) is not None]
        verb[zaehler.id] = engine.rest_verbrauch(gesamt, gemessen)
    return verb
