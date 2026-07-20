"""Vermögensübersicht: was gehört mir, was schulde ich, was ist es wert.

Rechnet je Objekt und in Summe:
  Wert        — Verkehrswert, ersatzweise Kaufpreis
  Restschuld  — Summe der offenen Darlehen
  Eigenkapital = Wert − Restschuld
  Volumen     — investiertes Volumen (Kaufpreis)
  Beleihung   — Restschuld / Wert in Prozent

Fehlen Angaben, wird die Zeile trotzdem gezeigt — mit dem, was da ist. Ein
Objekt ohne Kredit hat schlicht keine Restschuld, das ist kein Fehler.
"""
from __future__ import annotations

from .turnus import jahresbetrag


def _wert(objekt) -> float | None:
    """Verkehrswert schlägt Kaufpreis — er ist die aktuellere Angabe."""
    if objekt.verkehrswert:
        return float(objekt.verkehrswert)
    if objekt.kaufpreis:
        return float(objekt.kaufpreis)
    return None


def objekt_vermoegen(objekt, kredite: list, anteile: list | None = None) -> dict:
    """Vermögenslage eines Objekts. `anteile` sind Tausendstel je Eigentümer."""
    wert = _wert(objekt)
    restschuld = round(sum(float(k.restschuld or 0) for k in kredite), 2)
    annuitaet = round(sum(jahresbetrag(k.rate_monatlich, k.turnus) for k in kredite), 2)
    zinsen = round(sum(float(k.restschuld or 0) * float(k.zinssatz or 0) / 100
                       for k in kredite), 2)
    eigen = round(wert - restschuld, 2) if wert is not None else None
    quote = round(restschuld / wert * 100, 1) if wert else None
    gehalten = sum(int(a.tausendstel or 0) for a in (anteile or [])) or None

    return {
        "slug": objekt.slug,
        "name": objekt.name,
        "wert": wert,
        "wertquelle": "Verkehrswert" if objekt.verkehrswert else (
            "Kaufpreis" if objekt.kaufpreis else None),
        "kaufpreis": float(objekt.kaufpreis) if objekt.kaufpreis else None,
        "restschuld": restschuld,
        "eigenkapital": eigen,
        "beleihung": quote,
        "annuitaet_jahr": annuitaet,
        "zinslast_jahr": zinsen,
        "tilgung_jahr": round(max(annuitaet - zinsen, 0.0), 2),
        "kredite": len(kredite),
        "tausendstel": gehalten,
        # Anteilig bewertet — bei Alleineigentum identisch mit eigenkapital
        "eigenkapital_anteilig": round(eigen * gehalten / 1000, 2)
        if eigen is not None and gehalten else eigen,
    }


def gesamt(zeilen: list[dict]) -> dict:
    """Summenzeile. `None` zählt als nicht vorhanden, nicht als Null."""
    def summe(feld: str) -> float:
        return round(sum(z[feld] or 0 for z in zeilen), 2)

    wert = summe("wert")
    restschuld = summe("restschuld")
    return {
        "objekte": len(zeilen),
        "wert": wert,
        "kaufpreis": summe("kaufpreis"),
        "restschuld": restschuld,
        "eigenkapital": round(wert - restschuld, 2),
        "eigenkapital_anteilig": summe("eigenkapital_anteilig"),
        "beleihung": round(restschuld / wert * 100, 1) if wert else None,
        "annuitaet_jahr": summe("annuitaet_jahr"),
        "zinslast_jahr": summe("zinslast_jahr"),
        "tilgung_jahr": summe("tilgung_jahr"),
        "ohne_wert": sum(1 for z in zeilen if z["wert"] is None),
    }
