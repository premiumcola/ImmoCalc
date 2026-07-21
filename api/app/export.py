"""Sicherung und Wiederherstellung einer Immobilie.

Eine Immobilie wird vollständig als JSON ausgegeben — Stammdaten, Einheiten,
Zeiträume samt Positionen, Mieten samt Bewohnern, Versicherungen, Kredite samt
Jahresständen, Zahlungen und die Verweise auf die Dokumente in der Nextcloud.

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

from .models import (Anteil, Bewohner, Dokument, Eigentuemer, Einheit,
                     Kostenart, Kostenposition, Kredit, Kreditstand, Miete,
                     Objekt, Partei, Versicherung, Vorauszahlung, Zahlung,
                     Zeitraum)

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

# Was nicht am Objekt hängt, sondern an einem seiner Sätze: die Jahresstände am
# Kredit, die Bewohner am Mietverhältnis. Ohne sie wäre die Sicherung
# unvollständig — und beim Löschen blieben sie als Waisen stehen. SQLite
# vergibt frei gewordene rowids neu: der nächste Kredit erbte sonst die
# Jahresstände des gelöschten, der nächste Mieter fremde Bewohner.
# Name in der Sicherung -> (Modell, Fremdschlüssel, Name des Elternteils)
KINDER: dict[str, tuple[Type[SQLModel], str, str]] = {
    "kreditstaende": (Kreditstand, "kredit_id", "kredite"),
    "bewohner": (Bewohner, "miete_id", "mieten"),
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


def _kinder(session: Session, modell: Type[SQLModel], schluessel: str,
            eltern_ids: list[int]) -> list[SQLModel]:
    """Alle Sätze eines Kindmodells zu einer Menge von Elternteilen — in einem
    Zug, nicht je Elternteil einzeln."""
    if not eltern_ids:
        return []
    return list(session.exec(
        select(modell).where(getattr(modell, schluessel).in_(eltern_ids))).all())


def exportiere(session: Session, objekt: Objekt) -> dict:
    """Vollständige Sicherung eines Objekts als reines JSON-Gerüst."""
    daten: dict = {
        "format": FORMAT,
        "erstellt": date.today().isoformat(),
        "objekt": {k: _rein(v) for k, v in objekt.model_dump().items()},
    }
    for name, modell in ANHAENGSEL.items():
        daten[name] = _zeilen(session, modell, objekt.id)

    # Jahresstände und Bewohner hängen einen Schritt tiefer. Ihr Fremdschlüssel
    # bleibt in der Sicherung stehen und wird beim Import auf die neu vergebene
    # id des Kredits bzw. des Mietverhältnisses umgehängt.
    for name, (modell, schluessel, eltern) in KINDER.items():
        ids = [z["id"] for z in daten[eltern] if z.get("id") is not None]
        daten[name] = [{k: _rein(v) for k, v in z.model_dump().items()}
                       for z in _kinder(session, modell, schluessel, ids)]

    # Der Anteil zeigt auf eine Eigentümer-id. SQLite vergibt frei gewordene
    # Nummern neu — nach Löschen und Neuanlegen zeigt dieselbe id auf eine
    # andere Person. Deshalb den Namen mitschreiben und beim Import danach
    # auflösen, sonst hält am Ende eine fremde Gesellschaft 100 %.
    for zeile in daten["anteile"]:
        eigner = session.get(Eigentuemer, zeile.get("eigentuemer_id"))
        zeile["eigentuemer_name"] = eigner.name if eigner else ""

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

    # Erst die Kinder der Sätze, dann die Sätze selbst — sonst kennt niemand
    # mehr die Kredite und Mietverhältnisse, an denen sie hängen.
    for name, (modell, schluessel, eltern) in KINDER.items():
        eltern_modell = ANHAENGSEL[eltern]
        saetze = session.exec(select(eltern_modell).where(
            eltern_modell.objekt_id == objekt.id)).all()
        ids = [s.id for s in saetze if s.id is not None]
        kinder = _kinder(session, modell, schluessel, ids)
        for kind in kinder:
            session.delete(kind)
        entfernt[name] = len(kinder)

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


def _passender_eigner(session: Session, anteil: dict) -> Eigentuemer | None:
    """Der Eigentümer zu einem gesicherten Anteil — über den Namen, nicht die id.

    Die id allein genügt nicht: sie kann inzwischen einer anderen Person
    gehören. Nur wenn Name *und* id zusammenpassen, ist es sicher dieselbe."""
    name = (anteil.get("eigentuemer_name") or "").strip()
    if name:
        treffer = session.exec(
            select(Eigentuemer).where(Eigentuemer.name == name)).first()
        if treffer:
            return treffer
        return None
    # Alte Sicherungen ohne Namen: nur die id, und die muss belegt sein.
    return session.get(Eigentuemer, anteil.get("eigentuemer_id"))


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

    # alte Satz-id -> neue, damit Jahresstände und Bewohner ihren Kredit bzw.
    # ihr Mietverhältnis wiederfinden
    eltern_ids: dict[str, dict[int, int]] = {
        eltern: {} for _, _, eltern in KINDER.values()}

    for name, modell in ANHAENGSEL.items():
        for zeile in daten.get(name) or []:
            eintrag = dict(zeile)
            alte_id = eintrag.pop("id", None)
            eintrag["objekt_id"] = objekt.id
            if name == "anteile":
                eigner = _passender_eigner(session, eintrag)
                # Eigentümer werden getrennt gepflegt und beim Löschen eines
                # Objekts nicht mitgelöscht. Passt keiner, bleibt der Anteil
                # weg — lieber keine Beteiligung als die falsche.
                if eigner is None:
                    log.info("Anteil ohne passenden Eigentümer übersprungen: %s",
                             eintrag.get("eigentuemer_name") or "ohne Namen")
                    continue
                eintrag["eigentuemer_id"] = eigner.id
                eintrag.pop("eigentuemer_name", None)
            neu = modell.model_validate(eintrag)
            session.add(neu)
            if name in eltern_ids:
                session.commit()
                session.refresh(neu)
                if alte_id is not None:
                    eltern_ids[name][alte_id] = neu.id

    # Alte Sicherungen kennen diese Schlüssel noch nicht — dann bleibt es
    # schlicht bei nichts, und die Wiederherstellung läuft wie zuvor durch.
    for name, (modell, schluessel, eltern) in KINDER.items():
        for zeile in daten.get(name) or []:
            kind = dict(zeile)
            kind.pop("id", None)
            neuer_elternteil = eltern_ids[eltern].get(kind.get(schluessel))
            if neuer_elternteil is None:
                log.info("%s ohne passenden Satz übersprungen: %s=%s",
                         name, schluessel, kind.get(schluessel))
                continue
            kind[schluessel] = neuer_elternteil
            session.add(modell.model_validate(kind))

    # alte Zeitraum-id -> neue, damit die Dokumente ihren Zeitraum wiederfinden
    zeitraeume: dict[int, int] = {}
    # dasselbe für die Kostenpositionen (CLXXXIII): ein Beleg zeigt über die id
    # auf seine Position. Bliebe die alte Nummer stehen, zeigte er nach dem
    # Wiederherstellen auf eine fremde Zeile — SQLite vergibt Nummern neu.
    positionen: dict[int, int] = {}
    for z in daten.get("zeitraeume") or []:
        roh_z = {k: v for k, v in z.items()
                 if k not in ("id", "positionen", "vorauszahlungen")}
        roh_z["objekt_id"] = objekt.id
        zeitraum = Zeitraum.model_validate(roh_z)
        session.add(zeitraum)
        session.commit()
        session.refresh(zeitraum)
        if z.get("id") is not None:
            zeitraeume[z["id"]] = zeitraum.id
        for p in z.get("positionen") or []:
            roh_p = dict(p)
            alte_id = roh_p.pop("id", None)
            roh_p["zeitraum_id"] = zeitraum.id
            position = Kostenposition.model_validate(roh_p)
            session.add(position)
            if alte_id is not None:
                session.commit()
                session.refresh(position)
                positionen[alte_id] = position.id
        for v in z.get("vorauszahlungen") or []:
            roh_v = dict(v)
            roh_v.pop("id", None)
            roh_v["zeitraum_id"] = zeitraum.id
            session.add(Vorauszahlung.model_validate(roh_v))

    # Die Dateien liegen weiterhin in der Nextcloud — nur die Zuordnung
    # Beleg↔Kostenart↔Zeitraum steckt in der Datenbank. Ohne sie fände ein
    # späterer Scan die Belege nicht wieder: der sieht nur lose Dateien im
    # Hauptordner, einsortierte liegen längst in den Unterordnern.
    for d in daten.get("dokumente") or []:
        roh_d = dict(d)
        roh_d.pop("id", None)
        roh_d["objekt_id"] = objekt.id
        roh_d["zeitraum_id"] = zeitraeume.get(roh_d.get("zeitraum_id"))
        roh_d["position_id"] = positionen.get(roh_d.get("position_id"))
        if session.exec(select(Dokument).where(
                Dokument.pfad == roh_d.get("pfad"))).first():
            continue                       # steht schon in der Datenbank
        session.add(Dokument.model_validate(roh_d))

    session.commit()
    log.info("Objekt aus Sicherung angelegt: %s", objekt.slug)
    return objekt
