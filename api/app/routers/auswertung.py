"""Auswertung über alle Objekte: Einnahmen gegen Ausgaben, Kostenblöcke,
Mietverlauf. Speist den Statistik-Tab."""
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from ..db import get_session
from ..models import (Kostenposition, Kredit, Miete, Objekt, Versicherung,
                      Zahlung, Zeitraum)

router = APIRouter(prefix="/api/auswertung", tags=["auswertung"])


def _monate_im_jahr(m: Miete, jahr: int) -> int:
    """Wie viele Monate des Jahres war dieser Mietstand gültig?"""
    von = max(m.ab_datum, date(jahr, 1, 1))
    bis = min(m.bis_datum or date(jahr, 12, 31), date(jahr, 12, 31))
    if bis < von:
        return 0
    return (bis.year - von.year) * 12 + (bis.month - von.month) + 1


@router.get("")
def auswertung(jahr: int = Query(default=None),
               objekt: str = Query(default=None),
               session: Session = Depends(get_session)) -> dict:
    jahr = jahr or date.today().year
    objekte = session.exec(select(Objekt)).all()
    if objekt:
        objekte = [o for o in objekte if o.slug == objekt]

    zeilen, kostenbloecke = [], {}
    for o in objekte:
        mieten = session.exec(select(Miete).where(Miete.objekt_id == o.id)).all()
        einnahmen = sum(m.kaltmiete * _monate_im_jahr(m, jahr) for m in mieten)

        kredite = session.exec(select(Kredit).where(Kredit.objekt_id == o.id)).all()
        kreditkosten = sum(k.rate_monatlich * 12 for k in kredite)

        vers = session.exec(select(Versicherung).where(Versicherung.objekt_id == o.id)).all()
        versicherung = sum(v.jahresbeitrag for v in vers)

        zahlungen = session.exec(
            select(Zahlung).where(Zahlung.objekt_id == o.id, Zahlung.jahr == jahr)).all()
        steuer = sum(z.betrag for z in zahlungen if z.kategorie == "Steuer")
        sonstige = sum(z.betrag for z in zahlungen if z.kategorie != "Steuer")

        # Nebenkosten aus den Zeiträumen, die im Jahr enden
        zrs = session.exec(select(Zeitraum).where(Zeitraum.objekt_id == o.id)).all()
        nebenkosten = 0.0
        for z in zrs:
            if z.ende.year != jahr:
                continue
            pos = session.exec(
                select(Kostenposition).where(Kostenposition.zeitraum_id == z.id)).all()
            nebenkosten += sum(p.betrag for p in pos if p.status == "erledigt")

        ausgaben = kreditkosten + versicherung + steuer + sonstige + nebenkosten
        zeilen.append({
            "slug": o.slug, "name": o.name, "typ": o.typ,
            "einnahmen": round(einnahmen, 2),
            "ausgaben": round(ausgaben, 2),
            "saldo": round(einnahmen - ausgaben, 2),
            "bloecke": {
                "Kredit": round(kreditkosten, 2),
                "Versicherung": round(versicherung, 2),
                "Steuer": round(steuer, 2),
                "Nebenkosten": round(nebenkosten, 2),
                "Sonstiges": round(sonstige, 2),
            },
        })
        for k, v in zeilen[-1]["bloecke"].items():
            kostenbloecke[k] = round(kostenbloecke.get(k, 0.0) + v, 2)

    return {
        "jahr": jahr,
        "objekte": zeilen,
        "kostenbloecke": kostenbloecke,
        "gesamt": {
            "einnahmen": round(sum(z["einnahmen"] for z in zeilen), 2),
            "ausgaben": round(sum(z["ausgaben"] for z in zeilen), 2),
            "saldo": round(sum(z["saldo"] for z in zeilen), 2),
        },
    }


@router.get("/mietverlauf")
def mietverlauf(objekt: str = Query(default=None),
                session: Session = Depends(get_session)) -> dict:
    """Kaltmiete je Jahr — für die Verlaufskurve."""
    objekte = session.exec(select(Objekt)).all()
    if objekt:
        objekte = [o for o in objekte if o.slug == objekt]

    heute = date.today().year
    jahre = list(range(heute - 7, heute + 1))
    reihen = []
    for o in objekte:
        mieten = session.exec(select(Miete).where(Miete.objekt_id == o.id)).all()
        werte = [round(sum(m.kaltmiete * _monate_im_jahr(m, j) for m in mieten), 2)
                 for j in jahre]
        if any(werte):
            reihen.append({"slug": o.slug, "name": o.name, "werte": werte})
    return {"jahre": jahre, "reihen": reihen}
