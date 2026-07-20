"""Zahlungsturnus — wie oft ein Betrag im Jahr anfällt.

Beträge werden immer *je Turnus* erfasst: 480 € jährlich, 120 € vierteljährlich
oder 40 € monatlich sind derselbe Jahreswert. Für Auswertung und Cashflow wird
über `jahresbetrag` hochgerechnet.
"""
from __future__ import annotations

# Bezeichnung -> Zahlungen pro Jahr
TURNUS = {
    "monatlich": 12,
    "vierteljaehrlich": 4,
    "halbjaehrlich": 2,
    "jaehrlich": 1,
    "einmalig": 1,
}

# Was in der Oberfläche steht
BESCHRIFTUNG = {
    "monatlich": "monatlich",
    "vierteljaehrlich": "vierteljährlich",
    "halbjaehrlich": "halbjährlich",
    "jaehrlich": "jährlich",
    "einmalig": "einmalig",
}

# Sinnvolle Auswahl je Bereich. Mieten laufen monatlich, eine einmalige Miete
# gibt es nicht; eine Steuerzahlung kann dagegen einmalig sein.
AUSWAHL = {
    "mieten": ["monatlich", "vierteljaehrlich"],
    "versicherungen": ["jaehrlich", "halbjaehrlich", "vierteljaehrlich", "monatlich"],
    "kredite": ["monatlich", "vierteljaehrlich", "halbjaehrlich", "jaehrlich"],
    "zahlungen": ["jaehrlich", "vierteljaehrlich", "halbjaehrlich", "monatlich",
                  "einmalig"],
}

VORGABE = {
    "mieten": "monatlich",
    "versicherungen": "jaehrlich",
    "kredite": "monatlich",
    "zahlungen": "jaehrlich",
}


def faktor(turnus: str | None) -> int:
    """Zahlungen pro Jahr; unbekannte Angaben gelten als jährlich."""
    return TURNUS.get((turnus or "").strip().lower(), 1)


def jahresbetrag(betrag: float | None, turnus: str | None) -> float:
    """Rechnet einen Betrag je Turnus auf das Jahr hoch."""
    return round((betrag or 0.0) * faktor(turnus), 2)


def auswahl_fuer(bereich: str) -> list[dict]:
    """Optionen für die Oberfläche — leer, wo ein Turnus keinen Sinn ergibt."""
    return [{"wert": t, "text": BESCHRIFTUNG[t], "pro_jahr": TURNUS[t]}
            for t in AUSWAHL.get(bereich, [])]
