"""Datumsbausteine für Belege — Jahr/Monat ziehen, Tagesdatum parsen,
Belegjahr mit Rückfall bestimmen.

Alle drei Helfer sind rein: sie kennen weder Datenbank noch Cloud, sondern
formen nur die Angaben, die andernorts (Auslese, Formularfeld, Datei-Datum)
bereits vorliegen. So bleibt das Belegjahr eine einzige Wahrheit — und lässt
sich einzeln prüfen (`tests/test_jahr_dateidatum.py`).
"""
from __future__ import annotations

from datetime import date

from ..bezeichnung import _jahr_plausibel, datum_aus_namen


def _aus_datum(datum: str) -> tuple[int | None, int | None]:
    """Jahr und Monat aus einem ISO-Datum, wie `/erkennen` es liefert.

    Unvollständiges oder Unsinniges wird still verworfen — der Beleg ist
    wichtiger als sein Datum."""
    teile = (datum or "").split("-")
    try:
        jahr = int(teile[0]) if teile[0] else None
        monat = int(teile[1]) if len(teile) > 1 and teile[1] else None
    except ValueError:
        return None, None
    return jahr, (monat if monat and 1 <= monat <= 12 else None)


def _zum_datum(datum: str) -> date | None:
    """Ein vollständiges ISO-Datum, sonst nichts (CLXXII).

    Ein halbes Datum („2025-11") ist kein Belegdatum: den Tag zu erfinden
    hiesse, den Beleg in einen Zeitraum zu schieben, in den er vielleicht gar
    nicht gehört."""
    try:
        return date.fromisoformat((datum or "").strip())
    except ValueError:
        return None


def _jahr_mit_fallback(jahr: int | None, name: str,
                       datei_jahr: int | None) -> int | None:
    """Das Belegjahr — das Datei-Datum zählt nur als Rückfall (CCCLXXXIV).

    Vorrang hat, was Name oder erkanntes Datum sagen, solange es plausibel ist
    (1990 … heute+10). Erst wenn von dort kein Jahr kommt, tritt das
    mitgeschickte Erstellungs-/Änderungsdatum der Datei ein. So wird aus einer
    Artikelnummer wie „2045_204596-…" kein Unsinnsjahr 2045 — und ein Beleg
    ohne Jahr im Namen bekommt wenigstens das Jahr seiner Datei statt gar keins.

    `jahr` ist das, was vorher feststand (ausgewähltes Jahr oder das aus dem
    erkannten Datum); `name` der Dateiname, aus dem ein Jahr gelesen werden darf
    (`datum_aus_namen` liefert von sich aus nur plausible Jahre); `datei_jahr`
    das Jahr des Datei-Datums."""
    if jahr and _jahr_plausibel(jahr):
        return jahr
    aus_name, _ = datum_aus_namen(name or "")
    if aus_name:
        return aus_name
    if datei_jahr and _jahr_plausibel(datei_jahr):
        return datei_jahr
    return jahr
