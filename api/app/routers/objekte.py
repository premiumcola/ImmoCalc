"""Objekte, Zeiträume, Positionen, Abrechnung."""
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from ..db import get_session
from ..engine import Position, abrechnung
from ..frist import frist_tage
from ..models import (Einheit, Kostenart, Kostenposition, Miete, Objekt,
                      Partei, Vorauszahlung, Zeitraum)

router = APIRouter(prefix="/api", tags=["objekte"])


def _slugify(name: str) -> str:
    umlaute = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}
    s = name.lower()
    for k, v in umlaute.items():
        s = s.replace(k, v)
    s = "".join(c if c.isalnum() else "-" for c in s)
    return "-".join(t for t in s.split("-") if t) or "objekt"


def _freier_slug(session: Session, name: str) -> str:
    basis = _slugify(name)
    slug, n = basis, 2
    while session.exec(select(Objekt).where(Objekt.slug == slug)).first():
        slug = f"{basis}-{n}"
        n += 1
    return slug


class EinheitIn(BaseModel):
    bezeichnung: str
    nutzungsart: str = "Wohnen"
    flaeche: Optional[float] = None
    partei: str = ""
    personen: int = 1


class ObjektIn(BaseModel):
    name: str
    ort: str = ""
    strasse: str = ""
    plz: str = ""
    typ: str = "lg-mfhA"
    nutzung: str = "Wohnen"
    turnus: str = "kalender"
    start_monat: int = 1
    flaeche: Optional[float] = None
    kaufpreis: Optional[float] = None
    verkehrswert: Optional[float] = None
    kostenarten: list[str] = []
    einheiten: list[EinheitIn] = []


@router.get("/objekte")
def objekte(session: Session = Depends(get_session)) -> list[dict]:
    out = []
    for o in session.exec(select(Objekt)).all():
        zs = session.exec(select(Zeitraum).where(Zeitraum.objekt_id == o.id)).all()
        aktiv = next((z for z in zs if z.status == "in Arbeit"), None)
        offen = 0
        if aktiv:
            pos = session.exec(
                select(Kostenposition).where(Kostenposition.zeitraum_id == aktiv.id)).all()
            offen = sum(1 for p in pos if p.status == "offen")
        einheiten = session.exec(select(Einheit).where(Einheit.objekt_id == o.id)).all()
        mieten = session.exec(select(Miete).where(Miete.objekt_id == o.id)).all()
        aktuell = [m for m in mieten if m.bis_datum is None]
        out.append({
            "id": o.id, "slug": o.slug, "name": o.name, "ort": o.ort,
            "typ": o.typ, "turnus": o.turnus, "aktiv": o.aktiv,
            "einheiten": len(einheiten),
            "offene_positionen": offen,
            "frist_tage": frist_tage(aktiv) if aktiv else None,
            "miete_monatlich": round(sum(m.kaltmiete for m in aktuell), 2),
        })
    return out


@router.post("/objekte", status_code=201)
def objekt_anlegen(data: ObjektIn, session: Session = Depends(get_session)) -> dict:
    o = Objekt(
        slug=_freier_slug(session, data.name), name=data.name, ort=data.ort,
        strasse=data.strasse, plz=data.plz, typ=data.typ, nutzung=data.nutzung,
        turnus=data.turnus, start_monat=data.start_monat, flaeche=data.flaeche,
        kaufpreis=data.kaufpreis, verkehrswert=data.verkehrswert,
    )
    session.add(o)
    session.commit()
    session.refresh(o)

    for e in data.einheiten:
        session.add(Einheit(objekt_id=o.id, bezeichnung=e.bezeichnung,
                            nutzungsart=e.nutzungsart, flaeche=e.flaeche))
        if e.partei:
            session.add(Partei(objekt_id=o.id, name=e.partei, personen=e.personen))
    for name in data.kostenarten:
        session.add(Kostenart(objekt_id=o.id, name=name, aktiv=True))

    # Erster Zeitraum ergibt sich aus dem Turnus — sonst hat das Objekt nichts zu tun.
    heute = date.today()
    start = date(heute.year if data.start_monat <= heute.month else heute.year - 1,
                 data.start_monat, 1)
    ende = date(start.year + 1, start.month, 1) - timedelta(days=1)
    session.add(Zeitraum(objekt_id=o.id, start=start, ende=ende,
                         typ="regulär", status="in Arbeit"))
    session.commit()
    return {"slug": o.slug, "id": o.id, "name": o.name}


@router.get("/objekte/{slug}")
def objekt(slug: str, session: Session = Depends(get_session)) -> dict:
    o = session.exec(select(Objekt).where(Objekt.slug == slug)).first()
    if not o:
        raise HTTPException(404, "Objekt nicht gefunden")
    einheiten = session.exec(select(Einheit).where(Einheit.objekt_id == o.id)).all()
    parteien = session.exec(select(Partei).where(Partei.objekt_id == o.id)).all()
    zeitraeume = session.exec(select(Zeitraum).where(Zeitraum.objekt_id == o.id)).all()
    return {
        "objekt": o, "einheiten": einheiten, "parteien": parteien,
        "zeitraeume": [{"id": z.id, "label": f"{z.start:%d.%m.%Y} – {z.ende:%d.%m.%Y}",
                        "typ": z.typ, "status": z.status,
                        "frist_tage": frist_tage(z) if z.status == "in Arbeit" else None}
                       for z in zeitraeume],
    }


@router.patch("/objekte/{slug}")
def objekt_aendern(slug: str, data: dict, session: Session = Depends(get_session)) -> dict:
    o = session.exec(select(Objekt).where(Objekt.slug == slug)).first()
    if not o:
        raise HTTPException(404, "Objekt nicht gefunden")
    erlaubt = {"name", "ort", "strasse", "plz", "typ", "nutzung", "turnus",
               "start_monat", "flaeche", "kaufpreis", "verkehrswert", "aktiv", "nc_ordner"}
    for k, v in data.items():
        if k in erlaubt:
            setattr(o, k, v)
    session.add(o)
    session.commit()
    return {"ok": True, "slug": o.slug}


@router.get("/objekte/{slug}/kostenarten")
def kostenarten(slug: str, session: Session = Depends(get_session)) -> list[Kostenart]:
    o = session.exec(select(Objekt).where(Objekt.slug == slug)).first()
    if not o:
        raise HTTPException(404, "Objekt nicht gefunden")
    return session.exec(select(Kostenart).where(Kostenart.objekt_id == o.id)).all()


@router.get("/zeitraeume/{zid}/positionen")
def positionen(zid: int, session: Session = Depends(get_session)) -> list[Kostenposition]:
    return session.exec(
        select(Kostenposition).where(Kostenposition.zeitraum_id == zid)).all()


@router.get("/zeitraeume/{zid}/abrechnung")
def abrechnung_endpoint(zid: int, session: Session = Depends(get_session)) -> dict:
    z = session.get(Zeitraum, zid)
    if not z:
        raise HTTPException(404, "Zeitraum nicht gefunden")
    pos = session.exec(select(Kostenposition).where(Kostenposition.zeitraum_id == zid)).all()
    vzs = session.exec(select(Vorauszahlung).where(Vorauszahlung.zeitraum_id == zid)).all()
    # offene Positionen (Betrag noch nicht da) fließen nicht in die Rechnung ein
    positionen = [Position(p.kostenart, p.betrag, p.schluessel, p.anteile, p.s35)
                  for p in pos if p.status == "erledigt"]
    res = abrechnung(positionen, {v.partei: v.betrag for v in vzs})
    res["offen"] = [p.kostenart for p in pos if p.status == "offen"]
    return res
