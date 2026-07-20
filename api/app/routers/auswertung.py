"""Auswertung über alle Objekte: Einnahmen gegen Ausgaben, Kostenblöcke,
Mietverlauf. Speist den Statistik-Tab."""
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from fastapi import HTTPException
from sqlmodel import Session as DBSession

from ..cashflow import EinheitZahlen, cashflow, monate_im_jahr, sankey
from ..turnus import jahresbetrag
from ..db import get_session
from ..models import (Einheit, Kostenposition, Kredit, Miete, Objekt,
                      Versicherung, Zahlung, Zeitraum)

router = APIRouter(prefix="/api/auswertung", tags=["auswertung"])

BLOCK_NAMEN = ["Kredit", "Versicherung", "Steuer", "Nebenkosten", "Sonstiges"]


def _monate_im_jahr(m: Miete, jahr: int) -> int:
    """Wie viele Monate des Jahres war dieser Mietstand gültig?"""
    return monate_im_jahr(m.ab_datum, m.bis_datum, jahr)


def _miete_im_jahr(m: Miete, jahr: int) -> float:
    """Mieteinnahmen eines Eintrags im Jahr — Turnus und Laufzeit berücksichtigt."""
    voll = jahresbetrag(m.kaltmiete + m.stellplatz + m.sonstige, m.turnus)
    return voll * _monate_im_jahr(m, jahr) / 12


def _bloecke(session: DBSession, o: Objekt, jahr: int) -> dict[str, float]:
    """Jahreskosten eines Objekts, aufgeteilt in die Kostenblöcke."""
    kredite = session.exec(select(Kredit).where(Kredit.objekt_id == o.id)).all()
    vers = session.exec(select(Versicherung).where(Versicherung.objekt_id == o.id)).all()
    zahlungen = session.exec(
        select(Zahlung).where(Zahlung.objekt_id == o.id, Zahlung.jahr == jahr)).all()

    nebenkosten = 0.0
    for z in session.exec(select(Zeitraum).where(Zeitraum.objekt_id == o.id)).all():
        if z.ende.year != jahr:
            continue
        pos = session.exec(
            select(Kostenposition).where(Kostenposition.zeitraum_id == z.id)).all()
        nebenkosten += sum(p.betrag for p in pos if p.status == "erledigt")

    return {
        "Kredit": round(sum(jahresbetrag(k.rate_monatlich, k.turnus)
                            for k in kredite), 2),
        "Versicherung": round(sum(jahresbetrag(v.jahresbeitrag, v.turnus)
                                  for v in vers), 2),
        "Steuer": round(sum(jahresbetrag(z.betrag, z.turnus) for z in zahlungen
                            if z.kategorie == "Steuer"), 2),
        "Nebenkosten": round(nebenkosten, 2),
        "Sonstiges": round(sum(jahresbetrag(z.betrag, z.turnus) for z in zahlungen
                               if z.kategorie != "Steuer"), 2),
    }


def _einheiten_zahlen(session: DBSession, o: Objekt, jahr: int) -> list[EinheitZahlen]:
    """Einheiten mit ihren Mieteinnahmen im gewählten Jahr."""
    einheiten = session.exec(select(Einheit).where(Einheit.objekt_id == o.id)).all()
    mieten = session.exec(select(Miete).where(Miete.objekt_id == o.id)).all()

    zahlen = []
    for e in einheiten:
        passend = [m for m in mieten
                   if (m.einheit or "").strip().lower() == e.bezeichnung.strip().lower()
                   and _monate_im_jahr(m, jahr) > 0]
        # jüngster gültiger Mietstand zählt für die Kennzahlen
        aktuell = max(passend, key=lambda m: m.ab_datum, default=None)
        monatlich = sum(_miete_im_jahr(m, jahr) for m in passend) / 12 \
            if passend else 0.0
        zahlen.append(EinheitZahlen(
            bezeichnung=e.bezeichnung, nutzungsart=e.nutzungsart,
            flaeche=e.flaeche, terrasse=e.terrasse, nebenflaeche=e.nebenflaeche,
            einnahmen_monat=monatlich,
            kaltmiete=aktuell.kaltmiete if aktuell else 0.0,
            stellplatz=aktuell.stellplatz if aktuell else 0.0,
            sonstige=aktuell.sonstige if aktuell else 0.0,
            nebenkosten_vz=aktuell.nebenkosten_vz if aktuell else 0.0,
            partei=aktuell.partei if aktuell else "",
        ))

    # Mieten ohne passende Einheit (z.B. ganzes Objekt vermietet) nicht verlieren
    zugeordnet = {e.bezeichnung.strip().lower() for e in einheiten}
    lose = [m for m in mieten
            if (m.einheit or "").strip().lower() not in zugeordnet
            and _monate_im_jahr(m, jahr) > 0]
    for m in lose:
        zahlen.append(EinheitZahlen(
            bezeichnung=m.einheit or m.partei or "Gesamtobjekt",
            nutzungsart=o.nutzung, flaeche=None, terrasse=None, nebenflaeche=None,
            einnahmen_monat=_miete_im_jahr(m, jahr) / 12,
            kaltmiete=m.kaltmiete, stellplatz=m.stellplatz, sonstige=m.sonstige,
            nebenkosten_vz=m.nebenkosten_vz, partei=m.partei,
        ))
    return zahlen


def _gefiltert(bloecke: dict[str, float], kategorien: str | None) -> dict[str, float]:
    """Auf die gewählten Kostenarten eindampfen; ohne Angabe bleibt alles."""
    if not kategorien:
        return bloecke
    gewaehlt = {k.strip().lower() for k in kategorien.split(",") if k.strip()}
    return {n: b for n, b in bloecke.items() if n.lower() in gewaehlt}


@router.get("")
def auswertung(jahr: int = Query(default=None),
               objekt: str = Query(default=None),
               kategorien: str = Query(default=None),
               session: Session = Depends(get_session)) -> dict:
    jahr = jahr or date.today().year
    objekte = session.exec(select(Objekt)).all()
    if objekt:
        objekte = [o for o in objekte if o.slug == objekt]

    zeilen, kostenbloecke = [], {}
    for o in objekte:
        mieten = session.exec(select(Miete).where(Miete.objekt_id == o.id)).all()
        einnahmen = sum(_miete_im_jahr(m, jahr) for m in mieten)
        bloecke = _gefiltert(_bloecke(session, o, jahr), kategorien)
        ausgaben = sum(bloecke.values())

        zeilen.append({
            "slug": o.slug, "name": o.name, "typ": o.typ,
            "einnahmen": round(einnahmen, 2),
            "ausgaben": round(ausgaben, 2),
            "saldo": round(einnahmen - ausgaben, 2),
            "bloecke": bloecke,
        })
        for k, v in bloecke.items():
            kostenbloecke[k] = round(kostenbloecke.get(k, 0.0) + v, 2)

    return {
        "jahr": jahr,
        "objekte": zeilen,
        "kostenbloecke": kostenbloecke,
        "kategorien": BLOCK_NAMEN,
        "gesamt": {
            "einnahmen": round(sum(z["einnahmen"] for z in zeilen), 2),
            "ausgaben": round(sum(z["ausgaben"] for z in zeilen), 2),
            "saldo": round(sum(z["saldo"] for z in zeilen), 2),
        },
    }


@router.get("/cashflow")
def cashflow_endpoint(objekt: str = Query(...), jahr: int = Query(default=None),
                      kategorien: str = Query(default=None),
                      session: Session = Depends(get_session)) -> dict:
    """Einnahmen, Kosten und €/m² je Einheit — plus Fluss fürs Sankey."""
    jahr = jahr or date.today().year
    o = session.exec(select(Objekt).where(Objekt.slug == objekt)).first()
    if not o:
        raise HTTPException(404, "Objekt nicht gefunden")

    einheiten = _einheiten_zahlen(session, o, jahr)
    bloecke = _gefiltert(_bloecke(session, o, jahr), kategorien)
    ergebnis = cashflow(einheiten, bloecke)
    return {
        "jahr": jahr, "objekt": o.slug, "name": o.name,
        "kategorien": BLOCK_NAMEN,
        **ergebnis,
        "sankey": sankey(ergebnis["einheiten"], bloecke),
    }


@router.get("/sankey")
def sankey_endpoint(jahr: int = Query(default=None), objekt: str = Query(default=None),
                    kategorien: str = Query(default=None),
                    session: Session = Depends(get_session)) -> dict:
    """Kostenfluss über alle Objekte — folgt denselben Filtern wie die Auswertung."""
    jahr = jahr or date.today().year
    objekte = session.exec(select(Objekt)).all()
    if objekt:
        objekte = [o for o in objekte if o.slug == objekt]

    quellen, bloecke_gesamt = [], {}
    for o in objekte:
        bloecke = _gefiltert(_bloecke(session, o, jahr), kategorien)
        for k, v in bloecke.items():
            bloecke_gesamt[k] = round(bloecke_gesamt.get(k, 0.0) + v, 2)

        if objekt:      # ein Objekt -> je Einheit aufschlüsseln
            for e in cashflow(_einheiten_zahlen(session, o, jahr), {})["einheiten"]:
                quellen.append(e)
        else:           # alle Objekte -> je Objekt
            mieten = session.exec(select(Miete).where(Miete.objekt_id == o.id)).all()
            quellen.append({
                "bezeichnung": o.name,
                "einnahmen_jahr": round(sum(_miete_im_jahr(m, jahr)
                                            for m in mieten), 2),
            })

    return {"jahr": jahr, "kategorien": BLOCK_NAMEN,
            **sankey(quellen, bloecke_gesamt)}


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
        werte = [round(sum(jahresbetrag(m.kaltmiete, m.turnus)
                           * _monate_im_jahr(m, j) / 12 for m in mieten), 2)
                 for j in jahre]
        if any(werte):
            reihen.append({"slug": o.slug, "name": o.name, "werte": werte})
    return {"jahre": jahre, "reihen": reihen}
