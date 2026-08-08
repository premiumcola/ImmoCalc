"""CCCVII — einen verlorenen Dateipfad wiederfinden, ohne etwas zu bewegen.

Der Nutzer räumt in der Nextcloud selbst auf: er zieht ein PDF einen Ordner
tiefer, und der gespeicherte Pfad zeigt ins Leere. Die Vorschau meldete dann
„Datei nicht gefunden", obwohl die Datei einen Klick entfernt lag.

Deshalb sucht `_pfad_heilen` sie unter ihrem Namen im Objektordner
(`_dateien_im_objekt`, eine Ebene tief — tiefer legt die App nichts ab) und
berichtigt den Eintrag. `_datei_holen` macht daraus den selbstheilenden Weg zur
Datei: erst der gespeicherte Pfad, bei „nicht gefunden" einmal suchen, sonst
der bisherige Fehler.

Zwei Grenzen sind wichtig: **verschoben oder gelöscht wird nie etwas** — es
wird nur gelesen und der Pfad in der Datenbank nachgezogen. Und ein Pfad
gehört genau einem Eintrag (`_pfad_belegt_von`, `migrate.eindeutigkeit_
sichern`): hält ihn schon ein anderer, bleibt die Datenbank unberührt und der
Aufrufer bekommt den gefundenen Pfad trotzdem zu lesen.

Der Nextcloud-Client kommt von aussen — wer ihn selbst besorgt (`verbindung`),
bleibt im Router.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from .. import kidb
from ..models import Dokument, Objekt
from ..nextcloud import NextcloudFehler
from .darstellung import VERMISST

log = logging.getLogger("immocalc")


def _dateien_im_objekt(client, o: Objekt) -> dict[str, str]:
    """Wo welche Datei der Immobilie wirklich liegt: Dateiname → Cloud-Pfad.

    Angesehen werden der Hauptordner und eine Ebene darunter — tiefer legt die
    App nichts ab. Der erste Fund gewinnt. Rein lesend."""
    wo: dict[str, str] = {}
    wurzel = (o.nc_ordner or "").strip("/")
    if not wurzel:
        return wo
    ebenen = [wurzel] + [f"{wurzel}/{e.name}" for e in client.liste(wurzel)
                         if e.ordner]
    for ordner in ebenen:
        try:
            for e in client.liste(ordner):
                if not e.ordner:
                    wo.setdefault(e.name, f"/{ordner}/{e.name}")
        except NextcloudFehler:
            continue
    return wo


def _pfad_belegt_von(session: Session, pfad: str,
                     ausser_id: Optional[int]) -> Optional[int]:
    """Die Id eines ANDEREN Dokuments, das diesen Pfad schon hält — sonst None.

    `dokument.pfad` ist eindeutig (`migrate.eindeutigkeit_sichern`): ein Pfad,
    ein Eintrag. Zeigen nach einer Berichtigung zwei Einträge auf dieselbe
    Datei — etwa ein Alteintrag unter dem alten Dateinamen und der neue —,
    scheitert der Commit. Deshalb wird vorher gefragt, nicht hinterher."""
    treffer = session.exec(select(Dokument).where(
        Dokument.pfad == pfad, Dokument.id != ausser_id)).first()
    return treffer.id if treffer else None


def _pfad_heilen(session: Session, client, d: Dokument) -> str:
    """Sucht eine vermisste Datei unter ihrem Namen im Objektordner (CCCVII).

    Dieselbe Suche wie in `pfade_reparieren`, nur für einen einzelnen Beleg —
    damit die Vorschau sich selbst heilt, statt „Datei nicht gefunden" zu
    melden, obwohl die Datei nur einen Ordner tiefer liegt. Zurück kommt der
    gefundene Pfad (leer, wenn sie nirgends liegt).

    Der gespeicherte Pfad wird nur dann berichtigt, wenn ihn kein anderes
    Dokument hält; sonst bleibt die Datenbank unberührt und der Aufrufer liest
    trotzdem aus dem gefundenen Pfad. Verschoben oder gelöscht wird nichts."""
    o = session.get(Objekt, d.objekt_id) if d.objekt_id else None
    if not o or not o.nc_ordner:
        return ""
    try:
        wo = _dateien_im_objekt(client, o)
    except NextcloudFehler as fehler:
        log.info("Pfad nicht heilbar (%s): %s", d.dateiname, fehler)
        return ""
    richtig = wo.get(d.dateiname) or ""
    if not richtig or richtig == d.pfad:
        return richtig
    belegt = _pfad_belegt_von(session, richtig, d.id)
    if belegt:
        # Ein anderer Eintrag hält diesen Pfad schon. Die Vorschau bekommt den
        # gefundenen Pfad trotzdem — nur gespeichert wird nichts.
        log.info("Pfad %s schon von Dokument #%s belegt — nur gelesen",
                 richtig, belegt)
        return richtig
    alt = d.pfad
    d.pfad = richtig
    kidb.pfad_nachziehen(session, d)   # N299
    if d.status == VERMISST:
        d.status = "zugeordnet"
    session.add(d)
    try:
        session.commit()
    except IntegrityError:
        # Nebenläufig dazwischengekommen: lieber alles lassen, wie es war.
        session.rollback()
        log.info("Pfad nicht gespeichert (Konflikt): %s → %s", alt, richtig)
        return richtig
    log.info("Pfad geheilt: %s → %s", alt, richtig)
    return richtig


def _datei_holen(session: Session, client, d: Dokument) -> tuple[bytes, str]:
    """Die Datei zu einem Beleg — selbstheilend (CCCVII).

    Zeigt der gespeicherte Pfad ins Leere (die Datei wurde in der Nextcloud in
    einen Unterordner gezogen), wird sie einmalig im Objektordner gesucht, der
    Pfad — wo möglich — berichtigt und die Datei dann normal geliefert. Erst
    wenn sie wirklich nirgends liegt, kommt der bisherige Fehler."""
    try:
        return client.hole(d.pfad)
    except NextcloudFehler as fehler:
        if "nicht gefunden" not in str(fehler).lower():
            raise HTTPException(400, str(fehler)) from fehler
        richtig = _pfad_heilen(session, client, d)
        if not richtig:
            raise HTTPException(400, str(fehler)) from fehler
    try:
        return client.hole(richtig)
    except NextcloudFehler as fehler:
        raise HTTPException(400, str(fehler)) from fehler
