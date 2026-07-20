"""Abrechnungsfrist nach § 556 BGB: Ende des Zeitraums + 12 Monate."""
from datetime import date

from .models import Zeitraum


def frist_datum(z: Zeitraum) -> date:
    return date(z.ende.year + 1, z.ende.month, z.ende.day)


def frist_tage(z: Zeitraum) -> int:
    return (frist_datum(z) - date.today()).days
