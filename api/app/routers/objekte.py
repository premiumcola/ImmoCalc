"""Objekte, Zeiträume, Positionen, Abrechnung."""
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from ..db import get_session
from ..engine import Position, abrechnung
from ..erinnerungen import beleg_erinnerung, frist_erinnerung
from ..frist import frist_tage
from ..models import (Dokument, Einheit, Kostenart, Kostenposition, Miete,
                      Objekt, Partei, Vorauszahlung, Zeitraum)

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
               "start_monat", "flaeche", "kaufpreis", "verkehrswert", "aktiv",
               "nc_ordner", "bank", "iban", "kontoinhaber"}
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


@router.get("/erinnerungen")
def erinnerungen(session: Session = Depends(get_session)) -> dict:
    """Was ansteht: Abrechnungsfristen und erwartete Jahresabrechnungen.
    Grundlage für Benachrichtigungen."""
    heute = date.today()
    offen = []
    for o in session.exec(select(Objekt)).all():
        if not o.aktiv:
            continue
        for z in session.exec(select(Zeitraum).where(Zeitraum.objekt_id == o.id)).all():
            if z.status != "in Arbeit":
                continue
            label = f"{z.start:%d.%m.%Y} – {z.ende:%d.%m.%Y}"
            hinweis = frist_erinnerung(label, frist_tage(z))
            if hinweis:
                offen.append({"objekt": o.slug, "name": o.name, **hinweis})

            vorhanden = {p.kostenart for p in session.exec(
                select(Kostenposition).where(
                    Kostenposition.zeitraum_id == z.id)).all()
                if p.status == "erledigt"}
            for k in session.exec(
                    select(Kostenart).where(Kostenart.objekt_id == o.id)).all():
                if not k.aktiv:
                    continue
                hinweis = beleg_erinnerung(k.name, k.beleg_monat, k.erinnerung_tage,
                                           k.name in vorhanden, heute)
                if hinweis:
                    offen.append({"objekt": o.slug, "name": o.name, **hinweis})

    offen.sort(key=lambda e: (not e["faellig"], e["tage"]))
    return {"heute": heute.isoformat(),
            "faellig": sum(1 for e in offen if e["faellig"]),
            "erinnerungen": offen}


@router.get("/zeitraeume/{zid}/positionen")
def positionen(zid: int, session: Session = Depends(get_session)) -> list[Kostenposition]:
    return session.exec(
        select(Kostenposition).where(Kostenposition.zeitraum_id == zid)).all()


@router.get("/zeitraeume/{zid}")
def zeitraum(zid: int, session: Session = Depends(get_session)) -> dict:
    """Checkliste eines Abrechnungszeitraums: was liegt vor, was fehlt.

    Jede aktive Kostenart des Objekts ist eine Zeile. Ohne Position gilt sie
    als offen — so sieht man auch, was noch gar nicht erfasst wurde."""
    z = session.get(Zeitraum, zid)
    if not z:
        raise HTTPException(404, "Zeitraum nicht gefunden")
    o = session.get(Objekt, z.objekt_id)

    positionen = session.exec(
        select(Kostenposition).where(Kostenposition.zeitraum_id == zid)).all()
    arten = session.exec(select(Kostenart).where(Kostenart.objekt_id == o.id)).all()
    dokumente = session.exec(
        select(Dokument).where(Dokument.zeitraum_id == zid)).all()
    vzs = session.exec(select(Vorauszahlung).where(Vorauszahlung.zeitraum_id == zid)).all()

    nach_art = {p.kostenart: p for p in positionen}
    belege = {}
    for d in dokumente:
        belege.setdefault(d.kategorie or "", []).append(
            {"id": d.id, "dateiname": d.dateiname, "pfad": d.pfad})

    checkliste = []
    for k in arten:
        if not k.aktiv:
            continue
        p = nach_art.get(k.name)
        erledigt = bool(p and p.status == "erledigt")
        checkliste.append({
            "kostenart": k.name, "s35": k.s35 or (p.s35 if p else False),
            "erledigt": erledigt,
            "betrag": p.betrag if p else None,
            "schluessel": p.schluessel if p else None,
            "wertquelle": p.wertquelle if p else None,
            "anteile": p.anteile if p else {},
            "position_id": p.id if p else None,
            "beleg_monat": k.beleg_monat,
            "zustand": "erledigt" if erledigt else ("offen" if p else "fehlt"),
        })
    # Positionen zu Kostenarten, die nicht im Katalog stehen, gehen sonst verloren
    for p in positionen:
        if p.kostenart in {k["kostenart"] for k in checkliste}:
            continue
        checkliste.append({
            "kostenart": p.kostenart, "s35": p.s35,
            "erledigt": p.status == "erledigt", "betrag": p.betrag,
            "schluessel": p.schluessel, "wertquelle": p.wertquelle,
            "anteile": p.anteile, "position_id": p.id, "beleg_monat": None,
            "zustand": "erledigt" if p.status == "erledigt" else "offen",
        })

    fertig = sum(1 for k in checkliste if k["erledigt"])
    # Fluss fuer das Diagramm: erledigte Kostenarten -> Abrechnung -> Parteien
    summe_erledigt = sum(k["betrag"] or 0 for k in checkliste if k["erledigt"])
    knoten = [{"name": "Abrechnung", "spalte": 1}]
    fluss = []
    for k in sorted((k for k in checkliste if k["erledigt"] and (k["betrag"] or 0) > 0),
                    key=lambda k: -(k["betrag"] or 0)):
        knoten.append({"name": k["kostenart"], "spalte": 0})
        fluss.append({"von": len(knoten) - 1, "nach": 0, "wert": round(k["betrag"], 2)})
    if summe_erledigt > 0:
        gewichte = {}
        for k in checkliste:
            if not k["erledigt"]:
                continue
            gesamt_anteil = sum(k["anteile"].values()) or 1
            for partei, anteil in (k["anteile"] or {}).items():
                gewichte[partei] = gewichte.get(partei, 0.0) + \
                    (k["betrag"] or 0) * anteil / gesamt_anteil
        for partei, betrag in sorted(gewichte.items(), key=lambda p: -p[1]):
            knoten.append({"name": partei, "spalte": 2})
            fluss.append({"von": 0, "nach": len(knoten) - 1, "wert": round(betrag, 2)})

    return {
        "id": z.id, "objekt": o.slug, "objekt_name": o.name,
        "label": f"{z.start:%d.%m.%Y} – {z.ende:%d.%m.%Y}",
        "start": z.start.isoformat(), "ende": z.ende.isoformat(),
        "typ": z.typ, "status": z.status,
        "frist_tage": frist_tage(z) if z.status == "in Arbeit" else None,
        "fortschritt": {"fertig": fertig, "gesamt": len(checkliste),
                        "summe": round(summe_erledigt, 2)},
        "checkliste": checkliste,
        "sankey": {"knoten": knoten, "fluss": fluss},
        "dokumente": [{"id": d.id, "dateiname": d.dateiname, "pfad": d.pfad,
                       "kategorie": d.kategorie} for d in dokumente],
        "belege_je_art": belege,
        "vorauszahlungen": [{"partei": v.partei, "betrag": v.betrag} for v in vzs],
    }


class PositionIn(BaseModel):
    betrag: float | None = None
    status: str | None = None
    schluessel: str | None = None
    wertquelle: str | None = None


@router.patch("/positionen/{pid}")
def position_aendern(pid: int, data: PositionIn,
                     session: Session = Depends(get_session)) -> dict:
    """Betrag nachtragen oder Zustand ändern — das Nachbearbeiten aus der App."""
    p = session.get(Kostenposition, pid)
    if not p:
        raise HTTPException(404, "Position nicht gefunden")
    if data.betrag is not None:
        p.betrag = data.betrag
        # Ein eingetragener Betrag heisst: der Beleg liegt vor.
        if data.status is None and data.betrag > 0:
            p.status = "erledigt"
    for feld in ("status", "schluessel", "wertquelle"):
        wert = getattr(data, feld)
        if wert is not None:
            setattr(p, feld, wert)
    session.add(p)
    session.commit()
    return {"ok": True, "betrag": p.betrag, "status": p.status}


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
