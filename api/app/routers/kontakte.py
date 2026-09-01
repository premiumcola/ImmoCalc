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
from ..deps import aktuelle_familie, pruefe_familienbesitz
from ..models import Familie, Kontakt, Kundennummer, Objekt

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


def _kontakt_holen(session: Session, kontakt_id: int, familie: Familie) -> Kontakt:
    """N436 — `Kontakt` trägt seine eigene `familie_id` (keine Immobilie
    dazwischen, dieselbe Firma arbeitet für mehrere Objekte) — direkter
    Vergleich statt Umweg über `pruefe_familienbesitz`."""
    k = session.get(Kontakt, kontakt_id)
    if k is None or k.familie_id != familie.id:
        raise HTTPException(404, "Kontakt nicht gefunden")
    return k


def _pruefe_nummer_besitz(session: Session, n: Kundennummer, familie: Familie) -> None:
    """Eine Kundennummer hängt an einem Objekt ODER (nur) an einem Kontakt —
    beide Felder sind optional. Vorrang hat der Objekt-Bezug, sonst zählt die
    Familie des verlinkten Kontakts."""
    if n.objekt_id is not None:
        pruefe_familienbesitz(session, n, familie)
        return
    if n.kontakt_id is not None:
        k = session.get(Kontakt, n.kontakt_id)
        if k is not None and k.familie_id == familie.id:
            return
    raise HTTPException(404, "Nummer nicht gefunden")


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
def einzeln(kontakt_id: int, session: Session = Depends(get_session),
           familie: Familie = Depends(aktuelle_familie)) -> dict:
    k = _kontakt_holen(session, kontakt_id, familie)
    objekte = {o.id: o for o in session.exec(select(Objekt)).all()}
    return logik.zeige(session, k, objekte)


@router.patch("/{kontakt_id}")
def aendern(kontakt_id: int, data: KontaktIn,
            session: Session = Depends(get_session),
            familie: Familie = Depends(aktuelle_familie)) -> dict:
    """Pflegt einen Kontakt von Hand.

    Jedes hier gesetzte Feld wird in `handgepflegt` vermerkt und von der Ernte
    danach **nie wieder überschrieben** — sonst ersetzte der nächste Lauf die
    korrigierte Telefonnummer wieder durch die schlechtere aus dem Beleg."""
    k = _kontakt_holen(session, kontakt_id, familie)
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
                   session: Session = Depends(get_session),
                   familie: Familie = Depends(aktuelle_familie)) -> dict:
    k = _kontakt_holen(session, kontakt_id, familie)
    if not data.nummer.strip():
        raise HTTPException(400, "Bitte eine Nummer eintragen.")
    objekt_id = None
    if data.objekt:
        # N436 — der Slug kommt aus dem Body, nicht aus dem Pfad; dieselbe
        # Familien-Eingrenzung wie überall sonst (`objekt_holen`), nur ohne
        # dessen FastAPI-Dependency-Form, die einen Pfad-/Query-Parameter
        # namens `slug` erwarten würde.
        o = session.exec(select(Objekt).where(
            Objekt.slug == data.objekt, Objekt.familie_id == familie.id)).first()
        if o is None:
            raise HTTPException(404, "Objekt nicht gefunden")
        objekt_id = o.id
    logik.nummer_merken(session, k, objekt_id, data.nummer, data.art, "hand")
    session.commit()
    objekte = {o.id: o for o in session.exec(select(Objekt)).all()}
    return logik.zeige(session, k, objekte)


@router.delete("/nummer/{nummer_id}")
def nummer_loeschen(nummer_id: int,
                    session: Session = Depends(get_session),
                    familie: Familie = Depends(aktuelle_familie)) -> dict:
    """Eine falsch erkannte Nummer entfernen — bewusste Nutzeraktion."""
    n = session.get(Kundennummer, nummer_id)
    if n is None:
        raise HTTPException(404, "Nummer nicht gefunden")
    _pruefe_nummer_besitz(session, n, familie)
    session.delete(n)
    session.commit()
    return {"ok": True}


@router.delete("/{kontakt_id}")
def kontakt_loeschen(kontakt_id: int,
                     session: Session = Depends(get_session),
                     familie: Familie = Depends(aktuelle_familie)) -> dict:
    """Entfernt einen Kontakt samt seiner Nummern.

    Bewusste Nutzeraktion. Die Belege bleiben unangetastet — beim nächsten
    Ernten käme die Firma wieder herein, wenn sie dort noch steht; das ist
    gewollt und keine Überraschung."""
    k = _kontakt_holen(session, kontakt_id, familie)
    for n in session.exec(select(Kundennummer).where(
            Kundennummer.kontakt_id == kontakt_id)).all():
        session.delete(n)
    session.delete(k)
    session.commit()
    log.info("N309: Kontakt %d gelöscht", kontakt_id)
    return {"ok": True}


class ZusammenIn(BaseModel):
    weg_ids: list[int] = []


@router.post("/{behalten_id}/zusammenfuehren")
def zusammenfuehren(behalten_id: int, data: ZusammenIn,
                    session: Session = Depends(get_session),
                    familie: Familie = Depends(aktuelle_familie)) -> dict:
    """Führt Firmen zusammen, die dieselbe sind — ohne etwas zu verlieren.

    Die Ernte liest Firmennamen so, wie die Texterkennung sie hergibt. Ein
    Lesefehler wird damit zu einer eigenen Firma: aus „WWK" wurde „WVWK", aus
    „H. Liebel" ein zweites „N. Liebel" — beide mit derselben Police bzw.
    demselben Gewerk. Der Schlüsselvergleich fängt Schreibweisen ab
    (Rechtsform, Bindestriche), aber keine verlesenen Buchstaben.

    Reihenfolge wie beim Zusammenführen von Belegen ([N300]): erst wandert
    alles auf den Bleibenden, dann fällt der andere.

    * **Kundennummern** wandern mit; Doppel werden übersprungen, nicht
      verdoppelt.
    * **Leere Felder** des Bleibenden werden aus dem Weichenden gefüllt — was
      dort schon steht, bleibt. Von Hand Gepflegtes gewinnt immer.
    * Gelöscht wird nur der zusammengeführte Eintrag, nie ein Beleg."""
    behalten = session.get(Kontakt, behalten_id)
    if behalten is None or behalten.familie_id != familie.id:
        raise HTTPException(404, "Der Kontakt, der bleiben soll, existiert nicht.")
    weg_ids = [i for i in dict.fromkeys(data.weg_ids) if i != behalten_id]
    if not weg_ids:
        raise HTTPException(400, "Es ist kein zweiter Kontakt angegeben.")

    uebernommen = 0
    geschuetzt = set(behalten.handgepflegt or [])
    for i in weg_ids:
        weg = session.get(Kontakt, i)
        # N436 — ein Kontakt einer anderen Familie ist genauso „existiert
        # nicht" wie eine unbekannte ID: nicht unterscheidbar machen.
        if weg is None or weg.familie_id != familie.id:
            raise HTTPException(404, f"Kontakt {i} existiert nicht.")
        # Erst die Angaben: nur in leere Felder, nie über Gepflegtes.
        logik.zusammenfuehren(behalten, {
            f: getattr(weg, f) for f in
            ("art", "gewerk", "telefon", "email", "web", "adresse", "notiz")})
        # Dann die Nummern.
        for n in session.exec(select(Kundennummer).where(
                Kundennummer.kontakt_id == i)).all():
            doppelt = any(
                (v.nummer or "").strip().lower() == (n.nummer or "").strip().lower()
                and v.objekt_id == n.objekt_id
                for v in session.exec(select(Kundennummer).where(
                    Kundennummer.kontakt_id == behalten_id)).all())
            if doppelt:
                session.delete(n)
                continue
            n.kontakt_id = behalten_id
            session.add(n)
            uebernommen += 1
        session.delete(weg)
    # Was aus dem Weichenden kam, gilt als geerntet und bleibt für die nächste
    # Ernte offen — nur wirklich von Hand Gepflegtes ist geschützt.
    behalten.handgepflegt = sorted(geschuetzt)
    session.add(behalten)
    session.commit()
    log.info("N309: Kontakte %s auf %d zusammengeführt, %d Nummern übernommen",
             weg_ids, behalten_id, uebernommen)
    objekte = {o.id: o for o in session.exec(select(Objekt)).all()}
    return {**logik.zeige(session, behalten, objekte),
            "zusammengefuehrt": len(weg_ids), "nummern_uebernommen": uebernommen}
