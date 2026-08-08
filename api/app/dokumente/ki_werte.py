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

from .. import zahlen

import re
from datetime import date
from typing import Optional


def _ki_zahl(wert) -> Optional[float]:
    """Ein Rasterwert als Zahl — die gemeinsame Regel aus `zahlen` (N313).

    Eigen bleibt nur die Rundung: ein Rasterwert geht in ein Geldfeld, und dort
    sind zwei Nachkommastellen die Wahrheit."""
    zahl = zahlen.deutsch(wert)
    return None if zahl is None else round(zahl, 2)


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
