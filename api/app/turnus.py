"""Zahlungsturnus — wie oft ein Betrag im Jahr anfällt.

Beträge werden immer *je Turnus* erfasst: 480 € jährlich, 120 € vierteljährlich
oder 40 € monatlich sind derselbe Jahreswert. Für Auswertung und Cashflow wird
über `jahresbetrag` hochgerechnet.
"""
from __future__ import annotations

import logging

log = logging.getLogger("immocalc")

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
    # Eine Miete läuft monatlich, eine Landpacht dagegen fast immer jährlich —
    # deshalb stehen hier alle laufenden Turnusse zur Wahl (CCCV).
    "mieten": ["monatlich", "vierteljaehrlich", "halbjaehrlich", "jaehrlich"],
    "versicherungen": ["jaehrlich", "halbjaehrlich", "vierteljaehrlich", "monatlich"],
    "kredite": ["monatlich", "vierteljaehrlich", "halbjaehrlich", "jaehrlich"],
    "zahlungen": ["jaehrlich", "vierteljaehrlich", "halbjaehrlich", "monatlich",
                  "einmalig"],
}

# N461 — Wortformen, die kein Anfang des kanonischen Namens sind und sich
# deshalb nicht über den Wortanfang auflösen lassen.
_WORTFORMEN = {
    "mtl": "monatlich", "promonat": "monatlich", "jemonat": "monatlich",
    "quartal": "vierteljaehrlich", "quartalsweise": "vierteljaehrlich",
    "proquartal": "vierteljaehrlich", "14jaehrlich": "vierteljaehrlich",
    "halbjahr": "halbjaehrlich", "halbjaehrig": "halbjaehrlich",
    "pa": "jaehrlich", "projahr": "jaehrlich", "jaehrig": "jaehrlich",
    "einmal": "einmalig", "einmalzahlung": "einmalig",
}

VORGABE = {
    "mieten": "monatlich",
    "versicherungen": "jaehrlich",
    "kredite": "monatlich",
    "zahlungen": "jaehrlich",
}


def _schluessel(turnus: str | None) -> str:
    """N314 — die Schreibweise vereinheitlichen, bevor nachgeschlagen wird.

    `TURNUS` kennt nur die ae-Form (`vierteljaehrlich`). Die Oberfläche zeigt
    aber die Umlautform (`BESCHRIFTUNG`), und die KI-Auslese schreibt genau
    diese in den Datensatz — „vierteljährlich" fiel damit still auf den
    Vorgabewert 1 zurück: `jahresbetrag(125, "vierteljährlich")` ergab
    **125,00 € statt 500,00 €**, ein Faktor 4 mitten in der Auswertung.

    Gefaltet wird wie überall im Projekt (ä→ae), zusätzlich fallen Punkte und
    Bindestriche heraus — „viertelj." und „viertel-jährlich" meinen dasselbe.

    N461 — genau das stimmte vorher NICHT: nach dem Falten wurde exakt
    nachgeschlagen, „monatl" stand aber nirgends und fiel auf den Vorgabewert
    1 zurück. `jahresbetrag(125, "monatl.")` ergab 125 € statt 1.500 € —
    Faktor 12. Erreichbar über die KI-Auslese, die den Turnus als Freitext
    aus dem Beleg übernimmt. Jetzt werden zusätzlich gängige Wortformen
    aufgelöst und Abkürzungen über den Wortanfang erkannt."""
    from .kostenarten import _fold                   # noqa: PLC0415 — Zirkel

    roh = _fold(turnus or "").replace(".", "").replace("-", "").replace(" ", "")
    if not roh or roh in TURNUS:
        return roh
    if roh in _WORTFORMEN:
        return _WORTFORMEN[roh]
    # Abkürzung: „monatl", „viertelj", „halbjaehrl" sind eindeutige Anfänge
    # ihres kanonischen Namens. Mindestens vier Zeichen, damit „j" nicht
    # alles trifft, und nur bei genau EINEM Treffer.
    if len(roh) >= 4:
        treffer = [k for k in TURNUS if k.startswith(roh)]
        if len(treffer) == 1:
            return treffer[0]
    return roh


def faktor(turnus: str | None) -> int:
    """Zahlungen pro Jahr; unbekannte Angaben gelten als jährlich."""
    schluessel = _schluessel(turnus)
    if schluessel in TURNUS:
        return TURNUS[schluessel]
    # Ein unbekannter Turnus ist meist ein Tippfehler oder eine ungewohnte
    # Schreibweise — er soll auffallen, statt lautlos zu jährlich zu werden.
    if (turnus or "").strip():
        log.info('Unbekannter Turnus „%s“ — gilt als jährlich', turnus)
    return 1


def jahresbetrag(betrag: float | None, turnus: str | None) -> float:
    """Rechnet einen Betrag je Turnus auf das Jahr hoch."""
    return round((betrag or 0.0) * faktor(turnus), 2)


def auswahl_fuer(bereich: str) -> list[dict]:
    """Optionen für die Oberfläche — leer, wo ein Turnus keinen Sinn ergibt."""
    return [{"wert": t, "text": BESCHRIFTUNG[t], "pro_jahr": TURNUS[t]}
            for t in AUSWAHL.get(bereich, [])]
