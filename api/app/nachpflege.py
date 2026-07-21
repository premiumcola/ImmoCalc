"""Nachpflege-Hinweise.

Das Datenmodell wächst weiter, während echte Objekte längst eingepflegt sind.
Neue Felder kommen deshalb immer mit Vorgabewert — bestehende Daten bleiben
gültig, nur eben unvollständig.

Hier steht, was ein Objekt noch gebrauchen könnte. Nichts davon ist ein Fehler
und nichts wird automatisch gefüllt: die Oberfläche zeigt einen ruhigen
orangen Hinweis, entschieden wird vom Nutzer.
"""
from __future__ import annotations

from .models import ist_grundstueck

# feld -> (Beschriftung, warum es nützlich ist)
OBJEKTFELDER: dict[str, tuple[str, str]] = {
    "flaeche": ("Gesamtfläche", "Grundlage für die Verteilung nach Fläche"),
    "strasse": ("Straße", "wird für den Ordnernamen in der Nextcloud gebraucht"),
    "plz": ("PLZ", "vervollständigt die Anschrift"),
    "kaufpreis": ("Kaufpreis", "Grundlage der Vermögensübersicht"),
    "verkehrswert": ("Verkehrswert", "aktueller Wert für die Vermögensübersicht"),
    "iban": ("IBAN des Hauskontos", "gehört zur Abrechnung"),
}

# Ein Grundstück hat weder Wohnfläche noch Hauskonto — dort danach zu fragen
# wäre kein Hinweis, sondern eine falsche Fährte. Gefragt wird nach dem, was
# im Bescheid des Finanzamts und im Katasterauszug steht.
GRUNDSTUECKSFELDER: dict[str, tuple[str, str]] = {
    "grundstueck_nutzungsart": (
        "Nutzungsart", "Ackerland, Grünland oder Wald — sagt, wie das "
                       "Grundstück bewertet und besteuert wird"),
    "grundstueck_flaeche": (
        "Grundstücksfläche", "ohne sie kein Preis je m²"),
    "gemarkung": ("Gemarkung", "gehört zur Bezeichnung des Flurstücks"),
    "flurstueck": ("Flurstück", "benennt das Grundstück eindeutig"),
    "verkehrswert": ("Grundstückswert", "Grundlage der Vermögensübersicht"),
    "grundsteuerwert": (
        "Grundsteuerwert", "steht im Bescheid des Finanzamts und ergibt "
                           "zusammen mit dem Hebesatz die Grundsteuer"),
}

EINHEITFELDER: dict[str, tuple[str, str]] = {
    "flaeche": ("Wohnfläche", "ohne sie kein €/m² und keine Flächenverteilung"),
}

MIETFELDER: dict[str, tuple[str, str]] = {
    "email": ("E-Mail", "ohne sie lässt sich die Abrechnung nicht versenden"),
}


def _leer(wert) -> bool:
    return wert is None or (isinstance(wert, str) and not wert.strip())


def _pruefe(eintrag, felder: dict[str, tuple[str, str]], bereich: str,
            bezug: str) -> list[dict]:
    return [{"bereich": bereich, "bezug": bezug, "feld": feld,
             "label": label, "warum": warum}
            for feld, (label, warum) in felder.items()
            if _leer(getattr(eintrag, feld, None))]


def hinweise(objekt, einheiten: list, mieten: list) -> list[dict]:
    """Was an diesem Objekt noch fehlt — von grob nach fein."""
    if ist_grundstueck(objekt):
        # Keine Einheiten, keine Nebenkostenabrechnung, also auch keine
        # Mailadresse, an die etwas zu versenden wäre. Ein Pachtverhältnis
        # ohne Kontakt ist hier kein Mangel.
        return _pruefe(objekt, GRUNDSTUECKSFELDER, "objekt", objekt.name)

    offen = _pruefe(objekt, OBJEKTFELDER, "objekt", objekt.name)
    for e in einheiten:
        offen += _pruefe(e, EINHEITFELDER, "einheit", e.bezeichnung)
    for m in mieten:
        if m.bis_datum:                      # beendete Mietverhältnisse: egal
            continue
        offen += _pruefe(m, MIETFELDER, "miete",
                         m.partei or m.einheit or "Mietverhältnis")
    return offen


def zusammenfassung(offen: list[dict]) -> dict:
    """Kurzfassung für den Hinweisstreifen in der Oberfläche."""
    if not offen:
        return {"anzahl": 0, "text": "", "felder": []}
    labels: list[str] = []
    for h in offen:
        if h["label"] not in labels:
            labels.append(h["label"])
    gezeigt = labels[:3]
    rest = len(labels) - len(gezeigt)
    text = ", ".join(gezeigt) + (f" und {rest} weitere" if rest > 0 else "")
    return {"anzahl": len(offen), "text": text, "felder": labels}
