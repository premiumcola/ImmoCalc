"""Welche Einträge an einem Beleg hängen können — und wie man sie erreicht.

Ein Beleg zeigt nie auf sich selbst zurück: die Verbindung läuft immer über
`quelle_dokument_id` am Eintrag (Kostenposition, Miete, Versicherung, Kredit,
Notarvertrag, Bewohner, Zahlung). Damit diese Liste nicht an drei Stellen
auseinanderläuft, steht sie hier genau einmal:

* `_ZUORDNUNG_MODELLE` — wer per `quelle_dokument_id` auf einen Beleg zeigt,
  samt der Rubrik der Objektansicht (CCXCIX, Dokumentenbaum).
* `_AN_TYP_MODELLE`/`_INFO_RUBRIK` — an welchen bestehenden Eintrag sich ein
  Beleg hängen lässt, adressiert über einen Kurznamen (CCCX/CCCXI).
* `_eintrag_holen` — genau diesen Eintrag holen, mit sauberer Meldung statt
  stiller Fehlverknüpfung, und `_gehoert_zum_objekt` als Riegel davor: ein
  Eintrag einer anderen Immobilie wird nie verknüpft.

Reine Modell-Introspektion und Datenbank, keine Cloud.
"""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException
from sqlmodel import Session

from ..models import (Bewohner, Kostenposition, Kredit, Miete, Notarvertrag,
                      Objekt, Versicherung, Zahlung, Zeitraum)


# Modelle, die per `quelle_dokument_id` auf einen Beleg zeigen, samt der
# Rubrik, unter der sie in der Objektansicht stehen.
_ZUORDNUNG_MODELLE = (
    (Kostenposition, "Nebenkosten"), (Miete, "mieten"),
    (Versicherung, "versicherungen"), (Kredit, "kredite"),
    (Notarvertrag, "notarvertraege"), (Bewohner, "mieten"),
    (Zahlung, "zahlungen"),
)

# CCCX/CCCXI — an welchen bestehenden Eintrag sich ein Beleg hängen lässt:
# Kurzname (`an_typ`) → Modell und Rubrik der Objektansicht.
_AN_TYP_MODELLE = {
    "notarvertrag": (Notarvertrag, "notarvertraege"),
    "zahlung": (Zahlung, "zahlungen"),
    "kredit": (Kredit, "kredite"),
    "versicherung": (Versicherung, "versicherungen"),
    "miete": (Miete, "mieten"),
    "kostenposition": (Kostenposition, "Nebenkosten"),
}

# Rubrik eines Info-Belegs im Dokumentenbaum. „objekt" ist der Beleg, der zur
# Immobilie als Ganzes gehört und an keinem einzelnen Eintrag hängt.
_INFO_RUBRIK = {typ: rubrik for typ, (_m, rubrik) in _AN_TYP_MODELLE.items()}
_INFO_RUBRIK["objekt"] = "objekt"


def _gehoert_zum_objekt(session: Session, eintrag, o: Objekt) -> bool:
    """Hängt dieser Eintrag an derselben Immobilie? Eine Kostenposition hängt
    nur mittelbar daran — über ihren Zeitraum."""
    if isinstance(eintrag, Kostenposition):
        z = session.get(Zeitraum, eintrag.zeitraum_id)
        return bool(z and z.objekt_id == o.id)
    return getattr(eintrag, "objekt_id", None) == o.id


def _eintrag_holen(session: Session, an_typ: str, an_id: Optional[int],
                   o: Objekt):
    """Der bestehende Eintrag, an den der Beleg gehängt werden soll (CCCXI).

    Gibt Eintrag und Rubrik zurück. Ein unbekannter Typ, eine fehlende Id oder
    ein Eintrag einer anderen Immobilie werden sauber gemeldet, statt still
    etwas Falsches zu verknüpfen."""
    paar = _AN_TYP_MODELLE.get(an_typ)
    if not paar:
        raise HTTPException(400, f"Unbekannter Eintragstyp „{an_typ}“")
    if not an_id:
        raise HTTPException(400, "Zu diesem Eintragstyp fehlt die Id.")
    modell, rubrik = paar
    eintrag = session.get(modell, an_id)
    if not eintrag:
        raise HTTPException(404, "Der gewählte Eintrag wurde nicht gefunden.")
    if not _gehoert_zum_objekt(session, eintrag, o):
        raise HTTPException(400, "Der Eintrag gehört zu einer anderen Immobilie.")
    return eintrag, rubrik
