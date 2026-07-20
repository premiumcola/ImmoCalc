"""Abrechnung abschließen: je Partei ein Ergebnis erzeugen und versenden."""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from ..db import get_session
from ..engine import Position, abrechnung
from ..mailversand import MailFehler
from ..models import (Kostenposition, Miete, Objekt, Vorauszahlung, Zeitraum)
from .mail import zugang

log = logging.getLogger("immocalc")
router = APIRouter(prefix="/api/zeitraeume", tags=["versand"])


def _ergebnis(session: Session, z: Zeitraum) -> dict:
    pos = session.exec(
        select(Kostenposition).where(Kostenposition.zeitraum_id == z.id)).all()
    vzs = session.exec(
        select(Vorauszahlung).where(Vorauszahlung.zeitraum_id == z.id)).all()
    positionen = [Position(p.kostenart, p.betrag, p.schluessel, p.anteile, p.s35)
                  for p in pos if p.status == "erledigt"]
    return abrechnung(positionen, {v.partei: v.betrag for v in vzs})


def _empfaenger(session: Session, objekt_id: int) -> dict[str, dict]:
    """Aktuelle Mietverhältnisse je Partei — dort hängen die Kontaktdaten."""
    mieten = session.exec(select(Miete).where(Miete.objekt_id == objekt_id)).all()
    laufend = [m for m in mieten if m.bis_datum is None]
    treffer = {}
    for m in laufend:
        if m.partei:
            treffer[m.partei] = {"email": m.email, "einheit": m.einheit,
                                 "telefon": m.telefon}
    return treffer


@router.get("/{zid}/versand")
def uebersicht(zid: int, session: Session = Depends(get_session)) -> dict:
    """Wer bekommt was — und wem fehlt die Mailadresse?"""
    z = session.get(Zeitraum, zid)
    if not z:
        raise HTTPException(404, "Zeitraum nicht gefunden")
    res = _ergebnis(session, z)
    kontakte = _empfaenger(session, z.objekt_id)

    zeilen = []
    for partei, werte in (res.get("parteien") or {}).items():
        kontakt = kontakte.get(partei, {})
        zeilen.append({
            "partei": partei,
            "einheit": kontakt.get("einheit", ""),
            "email": kontakt.get("email", ""),
            "kosten": werte.get("kosten"),
            "vz": werte.get("vz"),
            "saldo": werte.get("saldo"),
            "versandbereit": bool(kontakt.get("email")),
        })
    zeilen.sort(key=lambda r: r["partei"])
    return {
        "zeitraum": f"{z.start:%d.%m.%Y} – {z.ende:%d.%m.%Y}",
        "status": z.status,
        "offen": res.get("offen", []),
        "parteien": zeilen,
        "ohne_mail": [r["partei"] for r in zeilen if not r["versandbereit"]],
    }


class AbschlussIn(BaseModel):
    versenden: bool = False
    offene_uebergehen: bool = False


@router.post("/{zid}/abschliessen")
def abschliessen(zid: int, data: AbschlussIn,
                 session: Session = Depends(get_session)) -> dict:
    """Schließt den Zeitraum ab und verschickt die Abrechnungen.

    Offene Positionen blockieren, solange sie nicht ausdrücklich übergangen
    werden — sonst ginge eine unvollständige Abrechnung an die Mieter."""
    z = session.get(Zeitraum, zid)
    if not z:
        raise HTTPException(404, "Zeitraum nicht gefunden")
    o = session.get(Objekt, z.objekt_id)

    res = _ergebnis(session, z)
    offen = res.get("offen", [])
    if offen and not data.offene_uebergehen:
        raise HTTPException(400, "Noch offene Positionen: " + ", ".join(offen))

    kontakte = _empfaenger(session, z.objekt_id)
    zeitraum_text = f"{z.start:%d.%m.%Y} – {z.ende:%d.%m.%Y}"
    versendet, uebersprungen = [], []

    if data.versenden:
        z_mail = zugang(session)          # wirft, wenn kein Postfach verbunden
        for partei, werte in (res.get("parteien") or {}).items():
            adresse = kontakte.get(partei, {}).get("email")
            if not adresse:
                uebersprungen.append(partei)
                continue
            saldo = werte.get("saldo") or 0
            richtung = ("Guthaben zu Ihren Gunsten" if saldo >= 0
                        else "Nachzahlung")
            text = (
                f"Guten Tag {partei},\n\n"
                f"anbei die Betriebskostenabrechnung für {o.name}, "
                f"Zeitraum {zeitraum_text}.\n\n"
                f"Umlagefähige Kosten: {werte.get('kosten'):.2f} EUR\n"
                f"Geleistete Vorauszahlungen: {werte.get('vz'):.2f} EUR\n"
                f"{richtung}: {abs(saldo):.2f} EUR\n\n"
                f"Bei Rückfragen melden Sie sich gerne.\n\n"
                f"Freundliche Grüße\n"
            )
            try:
                z_mail.sende(adresse,
                             f"Betriebskostenabrechnung {o.name} · {zeitraum_text}",
                             text)
                versendet.append(partei)
            except MailFehler as e:
                raise HTTPException(400, f"Versand an {partei} fehlgeschlagen: {e}") from e

    z.status = "abgeschlossen"
    session.add(z)
    session.commit()
    log.info("Zeitraum %s abgeschlossen, %d Mail(s) versendet", zid, len(versendet))
    return {"ok": True, "status": z.status, "versendet": versendet,
            "ohne_mail": uebersprungen, "uebergangen": offen if data.offene_uebergehen else []}
