"""Bewertungs-Layer über den Kennzahlen aus `investment_kpi.py` (N409, Aufgabe
2): Ampel je Kennzahl, eine Gesamtnote A–E, Konfidenz bei fehlenden
Eingaben — und, bewusst getrennt davon, das Potenzial.

**Risiko und Potenzial sind zwei unabhängige Werte, kein einer.** Ein Objekt
kann bei der laufenden Kaltmiete auf D stehen und trotzdem eine große
Mietreserve oder ungenutztes Baurecht haben — genau der Fall bei
Grundstücks-lastigen, unterverwerteten Objekten. Eine einzige Zahl würde
diesen Unterschied verschlucken; deshalb liefert `bewertung()` `note` und
`potenzial` nebeneinander, nie verrechnet.

Die Schwellenwerte stehen in EINEM Konfig-Objekt (`SCHWELLEN`), wie
verlangt — wer sie kalibrieren will, ändert nur diese eine Stelle.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Schwellenwerte je Kennzahl: (grün-Schwelle, gelb-Schwelle, Richtung).
# `richtung="hoch"` heisst: je höher, desto besser (Wert >= grün-Schwelle ist
# grün). `richtung="tief"` heisst umgekehrt (Wert <= grün-Schwelle ist grün).
# Die Grenzen selbst sind gängige, aber justierbare Kennzahlen der
# Immobilien-Praxis — keine gesetzliche Vorgabe, deshalb an einer Stelle.
# ---------------------------------------------------------------------------
SCHWELLEN = {
    # Leverage-Spread — die Leitkennzahl: positiv heisst, die Fremdfinanzierung
    # verbessert die Eigenkapitalrendite („guter Hebel"); negativ heisst, sie
    # verschlechtert sie („der Kredit kostet mehr, als das Objekt erwirtschaftet").
    "leverage_spread_pp": {"gruen": 1.0, "gelb": 0.0, "richtung": "hoch", "gewicht": 3},
    # DSCR — deckt der Betriebsertrag den Kapitaldienst? Unter 1,0 reicht der
    # NOI allein nicht, der Rest muss aus anderen Mitteln kommen.
    "dscr": {"gruen": 1.2, "gelb": 0.8, "richtung": "hoch", "gewicht": 3},
    "ltv_pct": {"gruen": 60.0, "gelb": 80.0, "richtung": "tief", "gewicht": 2},
    "netto_rendite_pct": {"gruen": 4.0, "gelb": 3.0, "richtung": "hoch", "gewicht": 2},
    "kaufpreisfaktor": {"gruen": 22.0, "gelb": 28.0, "richtung": "tief", "gewicht": 1},
    # € im Monat — negative Zahlen sind rot, die Schwellen sind deshalb
    # absolute Beträge, keine Prozentwerte.
    "echtes_defizit_monat": {"gruen": 0.0, "gelb": -150.0, "richtung": "hoch", "gewicht": 2},
}

# Score-Punkte je Ampelfarbe (die Basis der gewichteten Gesamtnote).
PUNKTE = {"gruen": 2, "gelb": 1, "rot": 0}

# Notenbänder über den erreichten Anteil der Höchstpunktzahl (0..1). A–E, wie
# gefordert: A selbsttragend/positiver Hebel, E kritisch (Defizit + hohe
# Beleihung). Die drei Bänder dazwischen liegen gleichmäßig gestuft.
NOTENBAENDER = [
    (0.85, "A"), (0.65, "B"), (0.45, "C"), (0.25, "D"),
]
NOTE_MINIMUM = "E"


def ampel(kpi_schluessel: str, wert: float | None) -> str | None:
    """Grün/gelb/rot einer einzelnen Kennzahl — `None`, wenn der Wert fehlt
    (eine fehlende Kennzahl ist weder gut noch schlecht, sie ist unbekannt)."""
    if wert is None:
        return None
    schwelle = SCHWELLEN.get(kpi_schluessel)
    if not schwelle:
        return None
    gruen, gelb, richtung = schwelle["gruen"], schwelle["gelb"], schwelle["richtung"]
    if richtung == "hoch":
        if wert >= gruen:
            return "gruen"
        if wert >= gelb:
            return "gelb"
        return "rot"
    if wert <= gruen:
        return "gruen"
    if wert <= gelb:
        return "gelb"
    return "rot"


def _kpi_werte(k: dict) -> dict[str, float | None]:
    """Die sechs bewerteten Kennzahlen flach aus dem `kennzahlen()`-Ergebnis
    herausgezogen — an einer Stelle, damit Ampel-Berechnung und Score
    garantiert dieselben Werte lesen."""
    return {
        "leverage_spread_pp": k["finanzierung"]["leverage_spread_pp"],
        "dscr": k["finanzierung"]["dscr"],
        "ltv_pct": k["finanzierung"]["ltv_pct"],
        "netto_rendite_pct": k["rendite"]["netto_rendite_pct"],
        "kaufpreisfaktor": k["rendite"]["kaufpreisfaktor"],
        "echtes_defizit_monat": k["cashflow"]["echtes_defizit_monat"],
    }


def ampeln(k: dict) -> dict[str, str | None]:
    """Ampel je bewerteter Kennzahl — für die Detailansicht (Aufgabe 3)."""
    return {name: ampel(name, wert) for name, wert in _kpi_werte(k).items()}


def _note_aus_anteil(anteil: float) -> str:
    for schwelle, note in NOTENBAENDER:
        if anteil >= schwelle:
            return note
    return NOTE_MINIMUM


def bewertung(k: dict) -> dict:
    """Gesamtnote A–E mit Konfidenz, plus Potenzial getrennt davon.

    `konfidenz` ist der Anteil der GEWICHTETEN Kennzahlen, die tatsächlich
    vorliegen — eine Note aus drei von sechs Kennzahlen (v. a. wenn gerade
    die schwer wiegenden fehlen) verdient nicht dasselbe Vertrauen wie eine
    aus allen sechsen. `fehlende_kennzahlen` nennt genau, was noch fehlt,
    damit die Oberfläche direkt dorthin verlinken kann."""
    werte = _kpi_werte(k)
    ampel_je_kpi = {name: ampel(name, wert) for name, wert in werte.items()}

    gesamtgewicht = sum(s["gewicht"] for s in SCHWELLEN.values())
    vorhandenes_gewicht = sum(SCHWELLEN[name]["gewicht"]
                              for name, farbe in ampel_je_kpi.items()
                              if farbe is not None)
    punkte = sum(SCHWELLEN[name]["gewicht"] * PUNKTE[farbe]
                for name, farbe in ampel_je_kpi.items() if farbe is not None)
    hoechstpunktzahl_vorhandener = vorhandenes_gewicht * max(PUNKTE.values())

    note = None
    anteil = None
    if hoechstpunktzahl_vorhandener > 0:
        anteil = punkte / hoechstpunktzahl_vorhandener
        note = _note_aus_anteil(anteil)

    konfidenz = round(vorhandenes_gewicht / gesamtgewicht, 2) if gesamtgewicht else 0.0
    fehlende = [name for name, farbe in ampel_je_kpi.items() if farbe is None]

    # Potenzial — bewusst UNABHÄNGIG von der Note: eine positive Mietreserve
    # oder ungenutztes Baurecht bleibt sichtbar, auch wenn die laufende
    # Kaltmiete das Objekt auf eine schlechte Note drückt.
    pot = k["potenzial"]
    potenzial_vorhanden = bool(
        (pot["mietreserve_jahr"] or 0) > 0
        or (pot["kappungsgrenze_spielraum_jahr"] or 0) > 0
        or (pot["gfz_auslastung_pct"] is not None
            and pot["gfz_auslastung_pct"] < 100))

    return {
        "note": note,
        "note_anteil": round(anteil, 3) if anteil is not None else None,
        "konfidenz": konfidenz,
        "fehlende_kennzahlen": fehlende,
        "ampeln": ampel_je_kpi,
        "potenzial_vorhanden": potenzial_vorhanden,
        "potenzial": {
            "mietreserve_jahr": pot["mietreserve_jahr"],
            "kappungsgrenze_spielraum_jahr": pot["kappungsgrenze_spielraum_jahr"],
            "gfz_auslastung_pct": pot["gfz_auslastung_pct"],
        },
    }
