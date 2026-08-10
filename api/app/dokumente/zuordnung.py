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
from sqlmodel import Session, select

from ..models import (Bewohner, Dokument, Einheit, Grundschuld, Kostenposition,
                      Kredit, Miete, Notarvertrag, Objekt, Versicherung,
                      Zahlung, Zeitraum)


# Modelle, die per `quelle_dokument_id` auf einen Beleg zeigen, samt der
# Rubrik, unter der sie in der Objektansicht stehen.
_ZUORDNUNG_MODELLE = (
    (Kostenposition, "Nebenkosten"), (Miete, "mieten"),
    (Versicherung, "versicherungen"), (Kredit, "kredite"),
    (Notarvertrag, "notarvertraege"), (Bewohner, "mieten"),
    (Zahlung, "zahlungen"), (Grundschuld, "grundschulden"),
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
    # N331c — der Scan-Weg für Grundschulden (Eintragungsbekanntmachung des
    # Grundbuchamts): Rang, Grundbuchblatt, Gläubiger, Betrag.
    "grundschuld": (Grundschuld, "grundschulden"),
}

# Rubrik eines Info-Belegs im Dokumentenbaum. „objekt" ist der Beleg, der zur
# Immobilie als Ganzes gehört und an keinem einzelnen Eintrag hängt.
_INFO_RUBRIK = {typ: rubrik for typ, (_m, rubrik) in _AN_TYP_MODELLE.items()}
_INFO_RUBRIK["objekt"] = "objekt"

# N314(d) — dieselben Kurznamen wie `_AN_TYP_MODELLE`, dazu „einheit": der
# Lageplan hängt genauso über `info_zu_typ`/`info_zu_id` an einer Einheit
# (CCCXX), ohne über den allgemeinen „Beleg an Eintrag hängen"-Weg zu laufen.
_INFO_ZU_MODELLE = {typ: modell for typ, (modell, _r) in _AN_TYP_MODELLE.items()}
_INFO_ZU_MODELLE["einheit"] = Einheit


def loese_info_referenzen(session: Session, typ: str, eintrag_id: int) -> int:
    """Löst jeden Info-Beleg von einem gelöschten Eintrag (`info_zu_typ`/
    `info_zu_id`).

    Der Verweis ist weich — keine Fremdschlüssel-Spalte, also auch keine
    Löschprüfung durch die Datenbank. SQLite vergibt eine frei gewordene id
    neu: ohne diese Lösung zeigte der Lageplan der gelöschten Einheit
    unbemerkt auf die nächste, die dieselbe id erbt — ebenso ein Info-Beleg an
    einem gelöschten Kredit/einer Miete/einer Versicherung/einem Notarvertrag/
    einer Zahlung/einer Kostenposition."""
    geloest = 0
    for d in session.exec(select(Dokument).where(
            Dokument.info_zu_typ == typ, Dokument.info_zu_id == eintrag_id)).all():
        d.info_zu_typ, d.info_zu_id = "", None
        session.add(d)
        geloest += 1
    return geloest


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
