"""Abrechnungsfrist nach § 556 BGB: Ende des Zeitraums + 12 Monate."""
from calendar import monthrange
from datetime import date

from .models import Zeitraum


def frist_datum(z: Zeitraum) -> date:
    """Derselbe Tag ein Jahr später.

    Den 29. Februar gibt es im Folgejahr meist nicht — ein Rumpfzeitraum, der
    am 29.02. endet, beantwortet die Frist sonst mit einem ValueError und
    reisst die ganze Objektliste mit (500 statt Kacheln). Dann zählt der
    letzte Tag des Monats.
    """
    jahr = z.ende.year + 1
    letzter = monthrange(jahr, z.ende.month)[1]
    return date(jahr, z.ende.month, min(z.ende.day, letzter))


def frist_tage(z: Zeitraum) -> int:
    return (frist_datum(z) - date.today()).days
