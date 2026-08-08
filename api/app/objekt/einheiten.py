"""Einheiten — die Wohnungen, Büros und Stellplätze eines Hauses.

`Miete.einheit` verweist über die Bezeichnung hierher, nicht über eine id.
Deshalb ist die Bezeichnung je Objekt eindeutig und wird beim Umbenennen in
den Mietverhältnissen mitgezogen: sonst zeigte die Miete ins Leere, und die
Partei fiele stumm aus der Kostenverteilung (Fund XCII).
"""
import json
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from .. import einheitname
from ..db import get_session
from ..deps import objekt_holen
from ..felder import bereinige
from ..models import Dokument, Einheit, Miete, Objekt, ist_grundstueck
from ..turnus import jahresbetrag
from ..verteilung import positionen_neu_ableiten
from .stammdaten import _laeuft, _zuordnung

router = APIRouter(tags=["objekte"])


class EinheitNeu(BaseModel):
    """Was eine Einheit ausmacht. Nur die Bezeichnung ist Pflicht — Flächen und
    Stellplätze trägt man oft erst nach, wenn der Grundriss vorliegt."""
    bezeichnung: str
    nutzungsart: str = "Wohnen"
    flaeche: Optional[float] = None
    terrasse: Optional[float] = None
    nebenflaeche: Optional[float] = None
    # Optional, obwohl das Modell eine Zahl erwartet: ein leer gelassenes Feld
    # kommt aus dem Formular als null und darf das Anlegen nicht scheitern lassen.
    stellplaetze: Optional[int] = 0
    # CLXXXVI: ein Verkehrswert je Einheit — nur gepflegt, wo er bekannt ist.
    verkehrswert: Optional[float] = None
    # CCCXXVII: Gemeinschaftsflächen [{bezeichnung, flaeche, personen}, …].
    gemeinflaechen: Optional[list] = None
    # CCCXXIX: zusätzliche Nutzflächen [{bezeichnung, flaeche}, …] — voll gezählt.
    nutzflaechen: Optional[list] = None
    # CCCXXXIII: €/m²-Ansätze je Flächenart — Grundlage der hergeleiteten
    # Kaltmiete (Vorschlag im Miet-Formular). Alle optional/None.
    miete_qm_wohn: Optional[float] = None
    miete_qm_neben: Optional[float] = None
    miete_qm_gemein: Optional[float] = None


def _einheit(session: Session, eid: int) -> Einheit:
    e = session.get(Einheit, eid)
    if not e:
        raise HTTPException(404, "Einheit nicht gefunden")
    return e


def _einheit_zeile(e: Einheit, mieten: list[Miete], einheiten: list[Einheit],
                   heute: date, lageplaene: Optional[dict] = None) -> dict:
    """Eine Einheit mit dem, was heute darin wohnt.

    `vermietet` ist die eine Auskunft, die man auf einen Blick braucht — sie
    entscheidet, ob die Blase in der Oberfläche als „frei" erscheint.

    `lageplaene` ist die vorab gebündelte Zuordnung Einheit-ID → Lagepläne
    (CCCXXVI); ohne sie bleibt die Liste leer, damit die Zeile auch ohne diese
    Vorarbeit funktioniert."""
    eigene = [m for m in mieten if _zuordnung(m, einheiten) == e.bezeichnung]
    laufend = [m for m in eigene if _laeuft(m, heute)]
    return {
        **e.model_dump(),
        # CCCXXVII — die Gemeinschaftsflächen als Liste (nicht als roher JSON-
        # Text) und der daraus errechnete anteilige Flächenbeitrag.
        "gemeinflaechen": _gemeinflaechen_liste(e),
        "gemein_flaeche": e.gemein_flaeche(),
        # CCCXXIX — die zusätzlichen Nutzflächen als Liste und ihr voller
        # Flächenbeitrag.
        "nutzflaechen": _nutzflaechen_liste(e),
        "nutz_flaeche": e.nutz_flaeche(),
        "vermietet": bool(laufend),
        "mieter": ", ".join(sorted({m.partei for m in laufend if m.partei})),
        # CCCLXXVIII b — auf den Monatsbetrag normalisieren (Turnus heraus-
        # rechnen); die Einheit zeigt „… €/M" und leitet daraus €/m² ab, sonst
        # verdreifachte eine vierteljährliche Miete den Quadratmeterpreis.
        "kaltmiete": round(sum(jahresbetrag(m.kaltmiete, m.turnus) / 12
                               for m in laufend), 2),
        "mietverhaeltnisse": len(eigene),
        # CCCXXVI — die hinterlegten Lagepläne dieser Einheit als
        # [{id, dateiname}]. Defensiv (leer, wenn keine); die Vorschau läuft
        # über die bestehenden Dokument-Endpunkte.
        "lageplaene": (lageplaene or {}).get(e.id, []),
    }


def _lageplaene_je_einheit(session: Session, einheit_ids: list[int]) -> dict:
    """CCCXXVI — die Lagepläne aller genannten Einheiten in einer Abfrage,
    nach Einheit-ID gebündelt. Ein Lageplan ist ein `Dokument` mit
    `kategorie="Lageplan"`, das über `info_zu_*` an der Einheit hängt — dieselbe
    Definition wie im Listen-Endpunkt in `dokumente.py`."""
    if not einheit_ids:
        return {}
    treffer = session.exec(select(Dokument).where(
        Dokument.kategorie == "Lageplan",
        Dokument.info_zu_typ == "einheit",
        Dokument.info_zu_id.in_(einheit_ids))).all()
    eimer: dict[int, list] = {}
    for d in treffer:
        eimer.setdefault(d.info_zu_id, []).append(
            {"id": d.id, "dateiname": d.dateiname, "pfad": d.pfad})
    return eimer


def _gemeinflaechen_liste(e: Einheit) -> list:
    """Die Gemeinschaftsflächen einer Einheit als Liste — leer bei kaputtem
    oder fehlendem JSON, damit die Oberfläche nie über einen String stolpert."""
    try:
        wert = json.loads(e.gemeinflaechen or "[]")
        return wert if isinstance(wert, list) else []
    except (ValueError, TypeError):
        return []


def _gemein_bereinigt(posten: list) -> list:
    """Nur die drei Felder je Gemeinschaftsfläche, sauber getypt. Zeilen ohne
    Fläche werden verworfen — eine leere Zeile aus dem Formular ist kein Posten."""
    sauber = []
    for p in posten:
        if not isinstance(p, dict):
            continue
        try:
            flaeche = float(p.get("flaeche") or 0)
            personen = int(float(p.get("personen") or 0))
        except (ValueError, TypeError):
            continue
        if flaeche <= 0:
            continue
        sauber.append({"bezeichnung": str(p.get("bezeichnung") or "").strip(),
                       "flaeche": flaeche, "personen": max(personen, 0)})
    return sauber


def _nutzflaechen_liste(e: Einheit) -> list:
    """CCCXXIX — die zusätzlichen Nutzflächen einer Einheit als Liste — leer
    bei kaputtem oder fehlendem JSON, damit die Oberfläche nie über einen
    String stolpert."""
    try:
        wert = json.loads(e.nutzflaechen or "[]")
        return wert if isinstance(wert, list) else []
    except (ValueError, TypeError):
        return []


def _nutz_bereinigt(posten: list) -> list:
    """CCCXXIX — nur {bezeichnung, flaeche} je Nutzfläche, sauber getypt. Zeilen
    ohne Fläche werden verworfen — eine leere Zeile aus dem Formular ist kein
    Posten. Personen gibt es hier nicht: die Nutzfläche zählt voll."""
    sauber = []
    for p in posten:
        if not isinstance(p, dict):
            continue
        try:
            flaeche = float(p.get("flaeche") or 0)
        except (ValueError, TypeError):
            continue
        if flaeche <= 0:
            continue
        sauber.append({"bezeichnung": str(p.get("bezeichnung") or "").strip(),
                       "flaeche": flaeche})
    return sauber


@router.get("/objekte/{slug}/einheiten")
def einheiten_liste(slug: str,
                    session: Session = Depends(get_session),
                    o: Objekt = Depends(objekt_holen)) -> list[dict]:
    """Die Einheiten eines Objekts, jede mit ihrem heutigen Mieter."""
    einheiten = list(session.exec(
        select(Einheit).where(Einheit.objekt_id == o.id)).all())
    mieten = list(session.exec(select(Miete).where(Miete.objekt_id == o.id)).all())
    heute = date.today()
    lageplaene = _lageplaene_je_einheit(
        session, [e.id for e in einheiten if e.id is not None])
    return [_einheit_zeile(e, mieten, einheiten, heute, lageplaene)
            for e in einheiten]


def _bezeichnung_frei(session: Session, objekt_id: int, bezeichnung: str,
                      ausser: Optional[int] = None) -> None:
    """Zwei gleichnamige Einheiten wären nicht auseinanderzuhalten — weder für
    den Nutzer noch für `Miete.einheit`."""
    for e in session.exec(select(Einheit).where(Einheit.objekt_id == objekt_id)).all():
        if e.id != ausser and e.bezeichnung.strip().casefold() == bezeichnung.casefold():
            raise HTTPException(409, f"„{bezeichnung}“ gibt es in diesem Objekt "
                                     f"schon. Wähle eine andere Bezeichnung.")


@router.post("/objekte/{slug}/einheiten", status_code=201)
def einheit_anlegen(slug: str, data: EinheitNeu,
                    session: Session = Depends(get_session),
                    o: Objekt = Depends(objekt_holen)) -> dict:
    if ist_grundstueck(o):
        raise HTTPException(400, "Ein Grundstück hat keine Einheiten — "
                                 "Fläche und Nutzungsart stehen am Objekt.")
    bezeichnung = data.bezeichnung.strip()
    if not bezeichnung:
        raise HTTPException(400, "Die Einheit braucht eine Bezeichnung")
    _bezeichnung_frei(session, o.id, bezeichnung)
    e = Einheit(objekt_id=o.id, bezeichnung=bezeichnung,
                nutzungsart=data.nutzungsart.strip() or "Wohnen",
                flaeche=data.flaeche, terrasse=data.terrasse,
                nebenflaeche=data.nebenflaeche,
                stellplaetze=data.stellplaetze or 0,
                verkehrswert=data.verkehrswert,
                gemeinflaechen=json.dumps(_gemein_bereinigt(data.gemeinflaechen or []),
                                          ensure_ascii=False),
                nutzflaechen=json.dumps(_nutz_bereinigt(data.nutzflaechen or []),
                                        ensure_ascii=False),
                # CCCXXXIII — €/m²-Ansätze je Flächenart (optional).
                miete_qm_wohn=data.miete_qm_wohn,
                miete_qm_neben=data.miete_qm_neben,
                miete_qm_gemein=data.miete_qm_gemein)
    session.add(e)
    session.commit()
    session.refresh(e)
    return {"id": e.id, "bezeichnung": e.bezeichnung}


@router.patch("/einheiten/{eid}")
def einheit_aendern(eid: int, data: dict,
                    session: Session = Depends(get_session)) -> dict:
    """Ändert eine Einheit — und zieht eine neue Bezeichnung in den
    Mietverhältnissen nach.

    Ohne das Nachziehen zeigte `Miete.einheit` nach dem Umbenennen auf eine
    Einheit, die es nicht mehr gibt: die Partei bekäme keine Kosten mehr und
    ihre Vorauszahlung voll erstattet, ohne dass es irgendwo auffiele."""
    e = _einheit(session, eid)
    erlaubt = {"bezeichnung", "nutzungsart", "flaeche", "terrasse",
               "nebenflaeche", "stellplaetze", "nk_abrechnung", "verkehrswert",
               "gemeinflaechen", "nutzflaechen",
               # CCCXXXIII — €/m²-Ansätze je Flächenart
               "miete_qm_wohn", "miete_qm_neben", "miete_qm_gemein"}
    daten = dict(data)
    # CCCXXVII — die Gemeinschaftsflächen kommen als Liste und werden als JSON
    # gespeichert (das Modell hält eine Zeichenkette).
    if isinstance(daten.get("gemeinflaechen"), list):
        daten["gemeinflaechen"] = json.dumps(_gemein_bereinigt(daten["gemeinflaechen"]),
                                             ensure_ascii=False)
    # CCCXXIX — dasselbe für die zusätzlichen Nutzflächen.
    if isinstance(daten.get("nutzflaechen"), list):
        daten["nutzflaechen"] = json.dumps(_nutz_bereinigt(daten["nutzflaechen"]),
                                           ensure_ascii=False)
    felder = bereinige(Einheit, {k: v for k, v in daten.items() if k in erlaubt})
    if "bezeichnung" in felder:
        neu = (felder["bezeichnung"] or "").strip()
        if not neu:
            raise HTTPException(400, "Die Einheit braucht eine Bezeichnung")
        _bezeichnung_frei(session, e.objekt_id, neu, ausser=e.id)
        felder["bezeichnung"] = neu
    alt = e.bezeichnung
    geprueft = Einheit.model_validate({**e.model_dump(), **felder})
    for k in felder:
        setattr(e, k, getattr(geprueft, k))
    session.add(e)

    umbenannt = 0
    nachgezogen: dict[str, int] = {}
    if e.bezeichnung != alt:
        for m in session.exec(select(Miete).where(Miete.objekt_id == e.objekt_id,
                                                  Miete.einheit == alt)).all():
            m.einheit = e.bezeichnung
            session.add(m)
            umbenannt += 1
        # N314 — und überall sonst, wo der Name als TEXT steht: an den Anteilen,
        # an Kostenpositionen (`nur_einheit`, `vorab_einheit`), am
        # Heizverteiler, am Strom-Jahr, an der WEG-Vorauszahlung.
        #
        # Bis hierher wurde nur `Miete` nachgezogen (Fund XCII). Der Rest blieb
        # auf dem alten Namen — und `verteilung.nur_einheit_gewichte` gibt bei
        # fehlender Übereinstimmung **stumm `{}`** zurück. Eine Position „nur
        # für Wohnung 2" über 300 € wurde danach auf NIEMANDEN verteilt; die
        # Engine-Invariante „Summe der Anteile == Gesamtkosten" war für sie
        # gebrochen, ohne einen einzigen Hinweis. Und der Schaden entstand
        # sofort, weil `positionen_neu_ableiten` gleich darunter läuft.
        nachgezogen = einheitname.benenne_um(session, alt, e.bezeichnung)
    session.commit()
    # N5 — geänderte Fläche/Bezeichnung/nk_abrechnung verschiebt die abgeleiteten
    # Gewichte offener Zeiträume; neu berechnen (Handeingaben bleiben).
    positionen_neu_ableiten(session, e.objekt_id)
    return {"ok": True, "bezeichnung": e.bezeichnung,
            "mieten_umbenannt": umbenannt,
            # N314 — was sonst noch mitwanderte; die Oberfläche kann es
            # zeigen, statt den Nutzer raten zu lassen.
            "nachgezogen": nachgezogen}


@router.delete("/einheiten/{eid}")
def einheit_loeschen(eid: int, session: Session = Depends(get_session)) -> dict:
    """Entfernt eine Einheit — aber nur, solange nichts daran hängt.

    Ein Mietverhältnis ohne Einheit ist genau der stille Fehler aus XCII.
    Deshalb wird hier lieber abgewiesen und gesagt, wer im Weg steht."""
    e = _einheit(session, eid)
    einheiten = list(session.exec(
        select(Einheit).where(Einheit.objekt_id == e.objekt_id)).all())
    mieten = [m for m in session.exec(
        select(Miete).where(Miete.objekt_id == e.objekt_id)).all()
        if _zuordnung(m, einheiten) == e.bezeichnung]
    if mieten:
        namen = sorted({m.partei for m in mieten if m.partei})
        eins = len(mieten) == 1
        raise HTTPException(
            409, f"An „{e.bezeichnung}“ "
                 + ("hängt noch ein Mietverhältnis" if eins
                    else f"hängen noch {len(mieten)} Mietverhältnisse")
                 + (f" ({', '.join(namen)})" if namen else "")
                 + ". Entferne " + ("es" if eins else "sie")
                 + " zuerst — sonst gehört die Miete zu keiner Einheit mehr.")
    bezeichnung = e.bezeichnung
    session.delete(e)
    session.commit()
    return {"ok": True, "bezeichnung": bezeichnung}
