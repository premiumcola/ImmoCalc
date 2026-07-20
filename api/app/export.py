"""Sicherung und Wiederherstellung einer Immobilie.

Eine Immobilie wird vollständig als JSON ausgegeben — Stammdaten, Einheiten,
Zeiträume samt Positionen, Mieten, Versicherungen, Kredite, Zahlungen und die
Verweise auf die Dokumente in der Nextcloud.

Beim Löschen wird diese Sicherung zuerst geschrieben, dann erst gelöscht. Die
Dateien in der Nextcloud bleiben dabei unangetastet — gelöscht wird nur, was in
der Datenbank steht. Der Import legt daraus wieder ein Objekt an; ein
bestehendes wird nie überschrieben, sondern ein neuer Datensatz angelegt.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Type

from sqlmodel import Session, SQLModel, select

from .models import (Anteil, Dokument, Eigentuemer, Einheit, Kostenart,
                     Kostenposition, Kredit, Miete, Objekt, Partei,
                     Versicherung, Vorauszahlung, Zahlung, Zeitraum)

log = logging.getLogger("immocalc")

FORMAT = "immocalc-objekt/1"

# Alles, was am Objekt hängt. Reihenfolge = Reihenfolge beim Wiederanlegen.
ANHAENGSEL: dict[str, Type[SQLModel]] = {
    "einheiten": Einheit,
    "parteien": Partei,
    "kostenarten": Kostenart,
    "versicherungen": Versicherung,
    "mieten": Miete,
    "kredite": Kredit,
    "zahlungen": Zahlung,
    "anteile": Anteil,
}


def _rein(wert):
    """date/datetime nach ISO — json.dumps kann sie sonst nicht schreiben."""
    if isinstance(wert, (date, datetime)):
        return wert.isoformat()
    return wert


def _zeilen(session: Session, modell: Type[SQLModel], objekt_id: int) -> list[dict]:
    treffer = session.exec(
        select(modell).where(modell.objekt_id == objekt_id)).all()
    return [{k: _rein(v) for k, v in z.model_dump().items()} for z in treffer]


def exportiere(session: Session, objekt: Objekt) -> dict:
    """Vollständige Sicherung eines Objekts als reines JSON-Gerüst."""
    daten: dict = {
        "format": FORMAT,
        "erstellt": date.today().isoformat(),
        "objekt": {k: _rein(v) for k, v in objekt.model_dump().items()},
    }
    for name, modell in ANHAENGSEL.items():
        daten[name] = _zeilen(session, modell, objekt.id)

    zeitraeume = session.exec(
        select(Zeitraum).where(Zeitraum.objekt_id == objekt.id)).all()
    daten["zeitraeume"] = []
    for z in zeitraeume:
        positionen = session.exec(
            select(Kostenposition).where(Kostenposition.zeitraum_id == z.id)).all()
        vzs = session.exec(
            select(Vorauszahlung).where(Vorauszahlung.zeitraum_id == z.id)).all()
        daten["zeitraeume"].append({
            **{k: _rein(v) for k, v in z.model_dump().items()},
            "positionen": [{k: _rein(v) for k, v in p.model_dump().items()}
                           for p in positionen],
            "vorauszahlungen": [{k: _rein(v) for k, v in v_.model_dump().items()}
                                for v_ in vzs],
        })

    daten["dokumente"] = [{k: _rein(v) for k, v in d.model_dump().items()}
                          for d in session.exec(
                              select(Dokument).where(
                                  Dokument.objekt_id == objekt.id)).all()]
    return daten


def als_datei(daten: dict) -> bytes:
    return json.dumps(daten, ensure_ascii=False, indent=2).encode("utf-8")


def dateiname(objekt: Objekt) -> str:
    return f"ImmoCalc-Sicherung_{objekt.slug}_{date.today():%Y-%m-%d}.json"


def loesche(session: Session, objekt: Objekt) -> dict:
    """Entfernt das Objekt und alles, was daran hängt — aus der Datenbank.

    Die Dateien in der Nextcloud bleiben bestehen; sie gehören dem Nutzer.
    Auch die Dokument-Einträge werden nur aus der Datenbank genommen, damit
    ein späterer Scan sie wiederfindet."""
    entfernt: dict[str, int] = {}

    zeitraeume = session.exec(
        select(Zeitraum).where(Zeitraum.objekt_id == objekt.id)).all()
    for z in zeitraeume:
        for modell in (Kostenposition, Vorauszahlung):
            for eintrag in session.exec(
                    select(modell).where(modell.zeitraum_id == z.id)).all():
                session.delete(eintrag)
                entfernt[modell.__name__] = entfernt.get(modell.__name__, 0) + 1
        session.delete(z)
    entfernt["Zeitraum"] = len(zeitraeume)

    for name, modell in ANHAENGSEL.items():
        treffer = session.exec(
            select(modell).where(modell.objekt_id == objekt.id)).all()
        for eintrag in treffer:
            session.delete(eintrag)
        entfernt[name] = len(treffer)

    dokumente = session.exec(
        select(Dokument).where(Dokument.objekt_id == objekt.id)).all()
    for d in dokumente:
        session.delete(d)
    entfernt["dokumente"] = len(dokumente)

    session.delete(objekt)
    session.commit()
    log.info("Objekt %s gelöscht (%s)", objekt.slug, entfernt)
    return entfernt


def importiere(session: Session, daten: dict, freier_slug) -> Objekt:
    """Legt aus einer Sicherung wieder ein Objekt an — immer als neuer Datensatz.

    `freier_slug(session, name)` liefert einen noch unbenutzten Slug; so bleibt
    ein gleichnamiges Objekt, das noch existiert, unangetastet."""
    roh = dict(daten.get("objekt") or {})
    roh.pop("id", None)
    roh["name"] = roh.get("name") or "Wiederhergestellt"
    roh["slug"] = freier_slug(session, roh["name"])
    objekt = Objekt.model_validate(roh)
    session.add(objekt)
    session.commit()
    session.refresh(objekt)

    for name, modell in ANHAENGSEL.items():
        for zeile in daten.get(name) or []:
            eintrag = dict(zeile)
            eintrag.pop("id", None)
            eintrag["objekt_id"] = objekt.id
            # Eigentümer werden getrennt gepflegt und beim Löschen eines
            # Objekts nicht mitgelöscht. Fehlt der Eintrag inzwischen, waere
            # der Anteil ein Verweis ins Leere.
            if name == "anteile" and not session.get(
                    Eigentuemer, eintrag.get("eigentuemer_id")):
                continue
            session.add(modell.model_validate(eintrag))

    for z in daten.get("zeitraeume") or []:
        roh_z = {k: v for k, v in z.items()
                 if k not in ("id", "positionen", "vorauszahlungen")}
        roh_z["objekt_id"] = objekt.id
        zeitraum = Zeitraum.model_validate(roh_z)
        session.add(zeitraum)
        session.commit()
        session.refresh(zeitraum)
        for p in z.get("positionen") or []:
            roh_p = dict(p)
            roh_p.pop("id", None)
            roh_p["zeitraum_id"] = zeitraum.id
            session.add(Kostenposition.model_validate(roh_p))
        for v in z.get("vorauszahlungen") or []:
            roh_v = dict(v)
            roh_v.pop("id", None)
            roh_v["zeitraum_id"] = zeitraum.id
            session.add(Vorauszahlung.model_validate(roh_v))

    session.commit()
    log.info("Objekt aus Sicherung angelegt: %s", objekt.slug)
    return objekt
