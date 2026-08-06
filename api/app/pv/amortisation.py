"""Verlauf der PV-Amortisation über alle Jahre (N127/N200/N204/N216).

Zieht die Erträge aus der Nebenkostenabrechnung (siehe :mod:`.ertrag`) und dem
Live-Beitrag der E-Tankstelle (siehe :mod:`.tanken_bridge`) zusammen, legt sie
auf die Amortisationskurve der Engine (`app.strom.amortisation`), ergänzt eine
sanfte Prognose und die Aufteilung auf die drei Kategorien.
"""
from __future__ import annotations

from sqlmodel import Session

from .. import strom
from ..models import Objekt, PVAnlage
from .ertrag import (_ertraege_je_jahr, _kategorie_kwh, _kategorien,
                     _QUELLEN_LEER, _vorlauf_jahr)
from .stammdaten import _anteile_tupel, _stammdaten, _vorlauf
from .tanken_bridge import _tanken_je_jahr

# Wie weit die Prognose höchstens rechnet. Trägt eine Anlage nur ein paar Euro
# im Jahr ab, liefe die Schleife sonst über Jahrhunderte.
_PROGNOSE_MAX_JAHRE = 60


def _anlage(session: Session,
            objekt_id: int) -> tuple[float, float, dict | None, tuple]:
    """Anschaffung, Vorlauf-Ertrag, dessen Herkunft und die PV-Anteile.

    N139 — alle kommen aus den Stammdaten (`PVAnlage`), nicht mehr aus dem
    Strom-Jahr: die Anlage wurde einmal gekauft, nicht jedes Jahr neu. Der
    Vorlauf ist, was die Anlage VOR der ersten Nebenkostenabrechnung schon
    abgetragen hat (N127): ein einmaliger Betrag, kein jährlicher. Woher er kam,
    steht in `teile` — oder in `None`, wenn nur der Gesamtwert gepflegt ist
    (N153, Vorrang-Regel in `_vorlauf`)."""
    a: PVAnlage = _stammdaten(session, objekt_id)
    vorlauf, teile = _vorlauf(a)
    return a.anschaffung_eur or 0.0, vorlauf, teile, _anteile_tupel(a)


def _prognose(jahre: list[dict], anschaffung: float) -> dict | None:
    """Wie es voraussichtlich weitergeht — linear aus dem bisherigen Schnitt.

    Erst ab **zwei** Jahren mit laufendem Ertrag: eine Prognose aus einem
    einzigen Wert wäre geraten, nicht gerechnet. Der einmalige Vorlauf zählt
    dabei nicht in den Schnitt (er wiederholt sich nicht), wohl aber im schon
    erreichten Stand.

    Rückgabe: `schnitt` (Ertrag je Jahr), `jahre` (die fortgeschriebenen Zeilen
    {jahr, summe, kumuliert, offen, ueberschuss}), `break_even_jahr` und
    `in_jahren`. `None`, wenn es (noch) nichts fortzuschreiben gibt."""
    if anschaffung <= 0 or not jahre:
        return None
    letztes = jahre[-1]
    if letztes["offen"] <= 0:
        return None                       # schon amortisiert, nichts zu raten
    laufend = [z for z in jahre if round(z["summe"] - z["vorlauf"], 2) > 0]
    if len(laufend) < 2:
        return None
    spanne = max(1, laufend[-1]["jahr"] - laufend[0]["jahr"] + 1)
    schnitt = round(sum(z["summe"] - z["vorlauf"] for z in laufend) / spanne, 2)
    if schnitt <= 0:
        return None

    reihe, kum = [], letztes["kumuliert"]
    for i in range(1, _PROGNOSE_MAX_JAHRE + 1):
        kum = round(kum + schnitt, 2)
        reihe.append({"jahr": letztes["jahr"] + i, "summe": schnitt,
                      "kumuliert": kum,
                      "offen": round(max(0.0, anschaffung - kum), 2),
                      "ueberschuss": round(max(0.0, kum - anschaffung), 2)})
        if kum >= anschaffung:
            break
    if reihe[-1]["offen"] > 0:
        return None                       # jenseits des Horizonts — lieber nichts
    return {"schnitt": schnitt, "jahre": reihe,
            "break_even_jahr": reihe[-1]["jahr"], "in_jahren": len(reihe)}


def verlauf_daten(session: Session, o: Objekt) -> dict:
    """N127 — wie die Erträge die Anschaffung Jahr für Jahr auffressen.

    Die Jahre kommen aus den vorhandenen Zeiträumen des Objekts (plus Jahren
    mit Ladungen), lückenlos von der ersten bis zur letzten Zeile: ein Jahr
    ohne Erträge ist eine Zeile mit 0, keine Lücke. Die Beträge werden bei
    jedem Aufruf frisch aus den Kostenpositionen gezogen — ändert sich die
    Nebenkostenabrechnung, ändert sich der Verlauf mit.

    Rückgabe: `anschaffung`, `vorlauf`, `vorlauf_teile` (dessen Herkunft oder
    `None`, N153), `vorlauf_jahr`, `jahre` ([{jahr, vorlauf, vorlauf_teile,
    pv_strom, einspeisung, tanken, summe, kumuliert, offen, ueberschuss}]),
    `kumuliert`, `rest`, `amortisiert_prozent`, `break_even_jahr` (erreicht oder
    prognostiziert), `break_even_geschaetzt`, `break_even_in_jahren`,
    `prognose`, `eigentuemer` und `warnungen`."""
    tanken = _tanken_je_jahr(session, o)
    quellen = _ertraege_je_jahr(session, o.id, tanken)
    anschaffung, vorlauf, vorlauf_teile, anteile = _anlage(session, o.id)
    # N153b — der Vorlauf steht VOR der ersten Abrechnung, nicht darin: eine
    # eigene Zeile im Jahr davor. Vorher zählte er auf das erste erfasste Jahr
    # und vermischte sich dort mit dessen echten Erträgen — beim Nutzer stand
    # der Vorsprung aus 2023/24 im ersten Abrechnungsjahr 2025. In Summe und
    # Amortisation zählt er unverändert voll mit, er sitzt nur richtig.
    vorlauf_jahr = _vorlauf_jahr(session, o.id, quellen) if vorlauf else None
    if vorlauf_jahr is not None:
        quellen.setdefault(vorlauf_jahr, dict(_QUELLEN_LEER))
    spanne = range(min(quellen), max(quellen) + 1) if quellen else range(0)
    roh = [{"jahr": j, **quellen.get(j, _QUELLEN_LEER)} for j in spanne]
    for z in roh:
        eigenes = z["jahr"] == vorlauf_jahr
        z["vorlauf"] = round(vorlauf, 2) if eigenes else 0.0
        z["vorlauf_teile"] = vorlauf_teile if eigenes else None

    a = strom.amortisation(
        [{"jahr": z["jahr"],
          "ertrag": round(z["vorlauf"] + z["pv_strom"] + z["einspeisung"]
                          + z["tanken"], 2)}
         for z in roh], anschaffung)
    jahre = [{**z, "summe": k["ertrag"], "kumuliert": k["kumuliert"],
              "offen": round(max(0.0, a["anschaffung"] - k["kumuliert"]), 2),
              "ueberschuss": round(max(0.0, k["kumuliert"] - a["anschaffung"]), 2)}
             for z, k in zip(roh, a["reihe"])]

    erreicht = a["break_even_jahr"]
    prognose = None if erreicht else _prognose(jahre, a["anschaffung"])
    warnungen: list[str] = []
    if not a["anschaffung"]:
        warnungen.append("Anschaffungskosten der Anlage sind noch nicht "
                         "erfasst — ohne sie gibt es keinen Break-even.")
    if not jahre:
        warnungen.append("Für dieses Objekt ist noch kein Abrechnungszeitraum "
                         "angelegt.")
    elif not a["kumuliert"]:
        warnungen.append("Noch keine Erträge erfasst: PV-Strom kommt aus den "
                         "Kostenpositionen mit Herkunft „eigen“, die "
                         "Einspeisevergütung aus einer nicht umlagefähigen "
                         "Kostenart, das E-Tanken aus den Ladungen.")
    elif not erreicht and not prognose and a["anschaffung"]:
        ertragsjahre = sum(1 for z in jahre
                           if round(z["summe"] - z["vorlauf"], 2) > 0)
        warnungen.append(
            f"Bei diesem Ertrag ist die Anlage in {_PROGNOSE_MAX_JAHRE} Jahren "
            f"noch nicht abbezahlt — eine Jahreszahl wäre hier ohne Aussage."
            if ertragsjahre >= 2 else
            "Eine Prognose gibt es ab dem zweiten Abrechnungsjahr mit Ertrag — "
            "aus einem einzigen Jahr wäre sie geraten.")
    # N200 — die Aufteilung der Amortisation auf ihre drei Kategorien: € (Anteil
    # an der Amortisation) und kWh (physische Menge) je Kategorie, für die
    # Prozentzeile und das Ringdiagramm unter der Kurve.
    kategorien = _kategorien(jahre, vorlauf_jahr,
                             _kategorie_kwh(session, o.id, jahre, vorlauf_jahr,
                                            tanken))
    return {"anschaffung": a["anschaffung"], "vorlauf": round(vorlauf, 2),
            "vorlauf_teile": vorlauf_teile,
            "vorlauf_aufgeschluesselt": vorlauf_teile is not None,
            "vorlauf_jahr": vorlauf_jahr,
            "jahre": jahre,
            "kategorien": kategorien,
            "kumuliert": a["kumuliert"], "rest": a["rest"],
            "amortisiert_prozent": a["amortisiert_prozent"],
            "break_even_jahr": erreicht or (prognose or {}).get("break_even_jahr"),
            "break_even_geschaetzt": prognose is not None,
            "break_even_in_jahren": (prognose or {}).get("in_jahren"),
            "prognose": prognose,
            "eigentuemer": strom.verteile_eigentuemer(a["kumuliert"], anteile),
            "warnungen": warnungen}
