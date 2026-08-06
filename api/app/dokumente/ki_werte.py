"""Rohwerte aus dem KI-Raster in Python-Typen wandeln — Betrag, Datum, Text.

Die KI liefert Rasterfelder mal als Zahl, mal als String mit deutschem Komma
und Tausenderpunkt, ein Datum mal ISO und mal in deutscher Schreibweise. Damit
Auslesestellen (`_entwurf_*`, `/immocalc`, `_ki_am_beleg_festhalten`) nicht
jedes Mal wieder dieselbe Bereinigung schreiben, hängen die drei Wandler hier.

Alle drei sind bewusst nachsichtig: unlesbares Material ergibt `None` bzw. ""
statt einer Ausnahme. Ein einzelner Rasterfehler darf einen Beleg nicht als
ganzen abweisen.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Optional


def _ki_zahl(wert) -> Optional[float]:
    """Ein Rasterwert als Zahl — deutsches Komma und Tausenderpunkt inklusive.

    Das Modell soll Punkt-Dezimalzahlen liefern, aber ein „1.234,56 €" aus dem
    Beleg darf nicht scheitern. `None`, wenn nichts Brauchbares dasteht."""
    if isinstance(wert, bool):        # bool ist in Python eine Zahl — hier nicht
        return None
    if isinstance(wert, (int, float)):
        return round(float(wert), 2)
    if not isinstance(wert, str):
        return None
    roh = re.sub(r"[^\d,.-]", "", wert)
    if not roh or roh in ("-", ".", ","):
        return None
    if "," in roh:
        # Deutsches Format: Punkt ist Tausendertrenner, Komma das Dezimalzeichen.
        roh = roh.replace(".", "").replace(",", ".")
    elif roh.count(".") > 1:
        # Nur Punkte, mehrere davon → alle sind Tausendertrenner (1.234.567).
        roh = roh.replace(".", "")
    else:
        # Genau ein Punkt: eine dreistellige Endgruppe ist ein Tausendertrenner
        # (1.234 → 1234), zwei Stellen sind Nachkommastellen (12.50 → 12,50).
        ganz, _, rest = roh.rpartition(".")
        if ganz and len(rest) == 3:
            roh = ganz + rest
    try:
        return round(float(roh), 2)
    except ValueError:
        return None


def _ki_datum(wert) -> date | None:
    """Ein Rasterwert als Datum — ISO (YYYY-MM-DD) oder deutsch (TT.MM.JJJJ).

    Ein blosses Jahr („2024") ergibt kein Datum: den Tag zu erfinden hiesse,
    einen Zeitraum zu behaupten, den der Beleg nicht nennt."""
    if isinstance(wert, date):
        return wert
    if not isinstance(wert, str):
        return None
    roh = wert.strip()
    treffer = re.match(r"(\d{4})-(\d{2})-(\d{2})", roh)
    if treffer:
        try:
            return date(int(treffer[1]), int(treffer[2]), int(treffer[3]))
        except ValueError:
            return None
    treffer = re.match(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", roh)
    if treffer:
        try:
            return date(int(treffer[3]), int(treffer[2]), int(treffer[1]))
        except ValueError:
            return None
    return None


def _ki_text(wert) -> str:
    """Ein Rasterwert als knapper Klartext, ohne Umbrüche."""
    if wert is None or isinstance(wert, (dict, list)):
        return ""
    return str(wert).strip().replace("\n", " ")[:120]
