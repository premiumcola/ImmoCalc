"""Modellübergreifende Eintrags-Bausteine — Umklassifizieren und Benennen.

Ein Eintrag (Zahlung, Notarvertrag, Kredit, Versicherung, Miete,
Kostenposition) taucht an zwei Stellen auf, wo modellübergreifend dieselbe
Frage beantwortet wird: wie er in einer Antwort knapp heißt (`_eintrag_wo`,
für „an einen bestehenden Eintrag hängen" und die Detailansicht) und wie sich
seine Felder in einen anderen Eintragstyp überführen lassen
(`_UMKLASS_ZIEL`/`_eintrag_kern`/`_bewahrt`, CCCXXIV).

Reine Modell-Introspektion — keine Datenbank, keine Cloud.
"""
from __future__ import annotations

# CCCXXIV — einen Eintrag in eine andere Rubrik überführen. Wohin: Kurzname →
# Zieltyp und (bei Zahlungen) die feste Kategorie/Turnus. Bewusst auf den
# „Erwerb/Steuer"-Cluster beschränkt, wo eine Umklassifizierung fachlich vorkommt.
_UMKLASS_ZIEL = {
    "erwerbskosten": {"typ": "zahlung", "kategorie": "Erwerbsnebenkosten",
                      "turnus": "einmalig", "absetzbar": False},
    "zahlungen": {"typ": "zahlung", "kategorie": "Steuer",
                  "turnus": "jaehrlich", "absetzbar": True},
    "notarvertraege": {"typ": "notarvertrag"},
}


def _eintrag_kern(eintrag) -> dict:
    """Die übertragbaren Felder eines Eintrags — modellübergreifend. Das Jahr
    kommt aus `jahr` (Zahlung) oder dem Beurkundungsdatum (Notarvertrag).

    Alles, was der Quelltyp mitbringt, wandert mit: der alte Eintrag wird nach
    der Überführung gelöscht, also ist jedes hier vergessene Feld endgültig weg.
    `datum`, `notar` und `urnr` gibt es nur am Notarvertrag — sie werden
    durchgereicht, damit ein Hin und Her (Notarvertrag → Zahlung → Notarvertrag)
    aus einem tagesgenauen Beurkundungsdatum nicht den 1. Januar macht und die
    Urkundenrollennummer nicht verliert."""
    jahr = getattr(eintrag, "jahr", None)
    datum = getattr(eintrag, "datum", None)
    if not jahr:
        jahr = datum.year if datum else None
    return {
        "art": (getattr(eintrag, "art", None)
                or getattr(eintrag, "bezeichnung", None) or "Sonstiges"),
        "betrag": getattr(eintrag, "betrag", 0.0) or 0.0,
        "jahr": jahr,
        "datum": datum,
        "notar": getattr(eintrag, "notar", "") or "",
        "urnr": getattr(eintrag, "urnr", "") or "",
        "notiz": getattr(eintrag, "notiz", "") or "",
        "beteiligte": getattr(eintrag, "beteiligte", "") or "",
        "quelle_dokument_id": getattr(eintrag, "quelle_dokument_id", None),
    }


def _bewahrt(kern: dict) -> str:
    """Die Notiz für ein Ziel, das Notar, Urkundenrolle, Beurkundungsdatum und
    Parteien gar nicht kennt (eine `Zahlung` hat diese Felder nicht).

    Ohne diese Zeile wären sie nach dem Löschen des alten Eintrags weg — die
    Urkundenrollennummer steht dann nur noch auf dem Papier. Angehängt wird
    additiv, die vorhandene Notiz bleibt vorn stehen."""
    teile = [t for t in (
        f"Notar: {kern['notar']}" if kern["notar"] else "",
        f"URNr: {kern['urnr']}" if kern["urnr"] else "",
        (f"beurkundet {kern['datum'].strftime('%d.%m.%Y')}"
         if kern["datum"] else ""),
        f"Parteien: {kern['beteiligte']}" if kern["beteiligte"] else "",
    ) if t]
    if not teile:
        return kern["notiz"]
    zusatz = "Aus dem Notarvertrag übernommen — " + " · ".join(teile)
    return f"{kern['notiz']}\n{zusatz}".strip() if kern["notiz"] else zusatz


def _eintrag_wo(eintrag) -> str:
    """Wie ein bestehender Eintrag in der Antwort heisst — dieselbe knappe
    Benennung wie in den `_entwurf_*`-Bauplänen.

    Modellübergreifend über `type(eintrag).__name__` unterschieden statt über
    `isinstance`-Importe — so bleibt dieses Modul frei von einer Abhängigkeit
    auf `app.models`."""
    name = type(eintrag).__name__
    if name == "Notarvertrag":
        return eintrag.art or "Notarvertrag"
    if name == "Zahlung":
        return f"{eintrag.art} {eintrag.jahr}".strip()
    if name == "Kredit":
        return eintrag.bezeichnung or "Kredit"
    if name == "Versicherung":
        return eintrag.art or "Versicherung"
    if name == "Miete":
        return eintrag.partei or eintrag.einheit or "Mietverhältnis"
    if name == "Kostenposition":
        return eintrag.kostenart or "Kostenposition"
    return name
