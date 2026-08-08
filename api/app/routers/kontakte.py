"""N309 — Endpunkte des Kontaktbuchs. Dünn; die Logik steht in `app.kontakte`.

Routen-Reihenfolge: `/kontakte/ernten` und `/kontakte/gewerke/{rid}` stehen VOR
`/kontakte/{kid}`, sonst verschluckt der Id-Pfad sie (CLAUDE.md).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from .. import kontakte as logik
from ..db import get_session
from ..models import Kontakt, Kundennummer, Objekt

log = logging.getLogger("immocalc")
router = APIRouter(prefix="/api/kontakte", tags=["kontakte"])


class KontaktIn(BaseModel):
    """Alles freiwillig — was mitkommt, wird gesetzt und ist ab dann vor der
    Ernte geschützt."""
    firma: str | None = None
    art: str | None = None
    gewerk: str | None = None
    telefon: str | None = None
    email: str | None = None
    web: str | None = None
    adresse: str | None = None
    notiz: str | None = None


class NummerIn(BaseModel):
    nummer: str = ""
    art: str = "Kundennummer"
    objekt: str = ""


@router.post("/ernten")
def ernten(session: Session = Depends(get_session)) -> dict:
    """Sammelt Firmen und Nummern aus dem Bestand ein — wiederholbar.

    „Sammle alle Infos aus allen Belegen ein!" Rein ergänzend: nichts wird
    gelöscht, und von Hand Gepflegtes bleibt unangetastet."""
    return logik.ernte(session)


@router.get("/gewerke/{renovierung_id}")
def gewerke(renovierung_id: int,
            session: Session = Depends(get_session)) -> dict:
    """Wer hat in welchem Gewerk gearbeitet — je Renovierung.

    Genau die Frage des Nutzers: „welche Handwerker in welchen Gewerken tätig
    waren"."""
    return {"renovierung_id": renovierung_id,
            "gewerke": logik.gewerke_der_renovierung(session, renovierung_id)}


@router.get("")
def liste(objekt: str = "", art: str = "", gewerk: str = "", suche: str = "",
          session: Session = Depends(get_session)) -> dict:
    """Das Kontaktbuch, gefiltert.

    `objekt` zeigt nur Firmen, zu denen es für diese Immobilie eine
    Kundennummer gibt — das ist die „immobilienzugehörige" Sicht, die der
    Nutzer verlangt hat."""
    objekte = {o.id: o for o in session.exec(select(Objekt)).all()}
    nach_slug = {o.slug: o for o in objekte.values()}
    alle = session.exec(select(Kontakt)).all()

    if objekt:
        o = nach_slug.get(objekt)
        if o is None:
            raise HTTPException(404, "Objekt nicht gefunden")
        erlaubt = {n.kontakt_id for n in session.exec(select(Kundennummer).where(
            Kundennummer.objekt_id == o.id)).all()}
        alle = [k for k in alle if k.id in erlaubt]
    if art:
        alle = [k for k in alle if (k.art or "") == art]
    if gewerk:
        alle = [k for k in alle if (k.gewerk or "") == gewerk]
    if suche:
        s = suche.strip().lower()
        alle = [k for k in alle
                if s in (k.firma or "").lower() or s in (k.notiz or "").lower()]

    eintraege = [logik.zeige(session, k, objekte) for k in alle]
    eintraege.sort(key=lambda e: (e["art"] or "zzz", e["firma"].lower()))
    return {
        "kontakte": eintraege,
        "anzahl": len(eintraege),
        "arten": sorted({e["art"] for e in eintraege if e["art"]}),
        "gewerke": sorted({e["gewerk"] for e in eintraege if e["gewerk"]}),
        # Wie viele noch ohne Telefon UND Mail dastehen — daran hängt der
        # Hinweis „Kontaktdaten ergänzen".
        "ohne_kontakt": sum(1 for e in eintraege if len(e["fehlt"]) == 2),
    }


@router.get("/{kontakt_id}")
def einzeln(kontakt_id: int, session: Session = Depends(get_session)) -> dict:
    k = session.get(Kontakt, kontakt_id)
    if k is None:
        raise HTTPException(404, "Kontakt nicht gefunden")
    objekte = {o.id: o for o in session.exec(select(Objekt)).all()}
    return logik.zeige(session, k, objekte)


@router.patch("/{kontakt_id}")
def aendern(kontakt_id: int, data: KontaktIn,
            session: Session = Depends(get_session)) -> dict:
    """Pflegt einen Kontakt von Hand.

    Jedes hier gesetzte Feld wird in `handgepflegt` vermerkt und von der Ernte
    danach **nie wieder überschrieben** — sonst ersetzte der nächste Lauf die
    korrigierte Telefonnummer wieder durch die schlechtere aus dem Beleg."""
    k = session.get(Kontakt, kontakt_id)
    if k is None:
        raise HTTPException(404, "Kontakt nicht gefunden")
    geschuetzt = set(k.handgepflegt or [])
    for feld, wert in data.model_dump(exclude_unset=True).items():
        if wert is None:
            continue
        setattr(k, feld, str(wert).strip())
        geschuetzt.add(feld)
    k.handgepflegt = sorted(geschuetzt)
    session.add(k)
    session.commit()
    session.refresh(k)
    objekte = {o.id: o for o in session.exec(select(Objekt)).all()}
    return logik.zeige(session, k, objekte)


@router.post("/{kontakt_id}/nummer", status_code=201)
def nummer_anlegen(kontakt_id: int, data: NummerIn,
                   session: Session = Depends(get_session)) -> dict:
    k = session.get(Kontakt, kontakt_id)
    if k is None:
        raise HTTPException(404, "Kontakt nicht gefunden")
    if not data.nummer.strip():
        raise HTTPException(400, "Bitte eine Nummer eintragen.")
    objekt_id = None
    if data.objekt:
        o = session.exec(select(Objekt).where(Objekt.slug == data.objekt)).first()
        if o is None:
            raise HTTPException(404, "Objekt nicht gefunden")
        objekt_id = o.id
    logik.nummer_merken(session, k, objekt_id, data.nummer, data.art, "hand")
    session.commit()
    objekte = {o.id: o for o in session.exec(select(Objekt)).all()}
    return logik.zeige(session, k, objekte)


@router.delete("/nummer/{nummer_id}")
def nummer_loeschen(nummer_id: int,
                    session: Session = Depends(get_session)) -> dict:
    """Eine falsch erkannte Nummer entfernen — bewusste Nutzeraktion."""
    n = session.get(Kundennummer, nummer_id)
    if n is None:
        raise HTTPException(404, "Nummer nicht gefunden")
    session.delete(n)
    session.commit()
    return {"ok": True}


@router.delete("/{kontakt_id}")
def kontakt_loeschen(kontakt_id: int,
                     session: Session = Depends(get_session)) -> dict:
    """Entfernt einen Kontakt samt seiner Nummern.

    Bewusste Nutzeraktion. Die Belege bleiben unangetastet — beim nächsten
    Ernten käme die Firma wieder herein, wenn sie dort noch steht; das ist
    gewollt und keine Überraschung."""
    k = session.get(Kontakt, kontakt_id)
    if k is None:
        raise HTTPException(404, "Kontakt nicht gefunden")
    for n in session.exec(select(Kundennummer).where(
            Kundennummer.kontakt_id == kontakt_id)).all():
        session.delete(n)
    session.delete(k)
    session.commit()
    log.info("N309: Kontakt %d gelöscht", kontakt_id)
    return {"ok": True}
