"""Fällige Erinnerungen: Abrechnungsfristen und erwartete Belege.

Zwei Quellen:
  * § 556 BGB — Abrechnung je Zeitraum bis Ende + 12 Monate
  * Kostenarten — die Jahresabrechnung des Versorgers trifft im `beleg_monat`
    ein; `erinnerung_tage` später wird nachgehakt, falls sie fehlt.
"""
from __future__ import annotations

from datetime import date, timedelta

# Weiter als ein Jahr voraus erinnert die App nicht. Was danach kommt, ist
# heute nicht zu erledigen und verstellt nur den Blick auf das, was ansteht.
HORIZONT_TAGE = 365


def in_sicht(hinweis: dict | None) -> bool:
    """Ist dieser Hinweis nah genug, um ihn zu zeigen?

    Überfälliges (negative Tage) bleibt immer sichtbar — es verschwindet erst,
    wenn der Beleg da ist.
    """
    return bool(hinweis) and hinweis["tage"] <= HORIZONT_TAGE


def termin_im_jahr(monat: int, tage_danach: int, jahr: int) -> date:
    """Erinnerungstermin: Monatsanfang plus Karenzzeit."""
    return date(jahr, monat, 1) + timedelta(days=tage_danach)


def beleg_erinnerung(kostenart_name: str, beleg_monat: int | None,
                     erinnerung_tage: int, hat_beleg: bool,
                     heute: date) -> dict | None:
    """Erinnerung für eine Kostenart — None, wenn nichts ansteht.

    Der Termin bleibt im laufenden Jahr: Ist er verstrichen und der Beleg
    fehlt weiterhin, ist er überfällig (negative Tage). Erst wenn der Beleg
    da ist, wird auf den Termin des Folgejahres gesehen.
    """
    if not beleg_monat:
        return None
    if hat_beleg:
        return None
    termin = termin_im_jahr(beleg_monat, erinnerung_tage, heute.year)
    tage = (termin - heute).days
    faellig = tage <= 0
    return {
        "art": "beleg",
        "kostenart": kostenart_name,
        "termin": termin.isoformat(),
        "tage": tage,
        "faellig": faellig,
        "text": f"Jahresabrechnung {kostenart_name} sollte vorliegen"
                if faellig else f"{kostenart_name} wird erwartet",
    }


def frist_erinnerung(label: str, frist_tage: int, vorlauf: int = 60,
                     zeitraum_beendet: bool = True) -> dict | None:
    """Erinnerung an die gesetzliche Abrechnungsfrist.

    Ein Zeitraum, der noch läuft, kann gar nicht abgerechnet werden — dafür
    zu erinnern wäre sinnlos. Erst wenn er abgelaufen ist, beginnt die Uhr.
    """
    if not zeitraum_beendet:
        return None
    if frist_tage > vorlauf:
        return None
    return {
        "art": "frist",
        "zeitraum": label,
        "tage": frist_tage,
        "faellig": frist_tage <= 0,
        "text": f"Frist § 556 BGB überschritten ({label})" if frist_tage < 0
                else f"Abrechnung {label} fällig in {frist_tage} Tagen",
    }
