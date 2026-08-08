"""CCLXXXI/CCLXXXII — einen Beleg wieder zum offenen Fall machen.

„Zurück ins Warten" nimmt zurück, was die App aus einem Beleg gemacht hat: die
aus ihm vorläufig (orange) angelegten Datensätze werden gelöscht, seine
NK-Bindung (Kostenposition-Anteil, Zeitraum) gelöst, der Status steht wieder
auf „neu".

Zwei Grenzen sind der ganze Punkt: **die Cloud wird nicht angefasst** — das
Dokument und seine Datei bleiben, wo sie sind, zurückgenommen wird nur die
App-seitige Zuordnung. Und gelöscht werden ausschliesslich VORLÄUFIGE
Entwürfe; ein bestätigter Datensatz bleibt unangetastet.

Welche Modelle Entwürfe sind, steht nicht hier, sondern in derselben Registry,
aus der auch `entwurf_verwerfen` liest (`_ENTWURF_MODELLE` in `objekte.py`) —
eine Wahrheit, nicht zwei.
"""
from __future__ import annotations

from sqlmodel import Session, select

from .. import belegposten
from ..models import Dokument, Kostenposition


def _entwuerfe_des_belegs(session: Session, dokument_id: int) -> list:
    """Alle noch vorläufigen (orange) Datensätze, die aus diesem Beleg entstanden.

    Nutzt dieselbe Entwurfs-Registry wie `entwurf_verwerfen` (`_ENTWURF_MODELLE`
    in `objekte.py`) — eine Wahrheit, welche Modelle Entwürfe sind."""
    from ..routers.objekte import _ENTWURF_MODELLE           # zirkelfrei zur Laufzeit
    treffer: list = []
    for modell in _ENTWURF_MODELLE.values():
        treffer += session.exec(select(modell).where(
            modell.quelle_dokument_id == dokument_id,
            modell.vorlaeufig == True)).all()          # noqa: E712
    return treffer


def _zurueck_ins_warten(session: Session, d: Dokument) -> set[int]:
    """Nimmt einen Beleg aus allen NK-Bindungen und stellt ihn auf „neu".

    Gibt die berührten Zeitraum-IDs zurück, damit der Aufrufer danach leer
    gewordene Zeiträume aufräumen kann. Löscht ausschließlich vorläufige
    Entwürfe — ein bestätigter Datensatz bleibt unangetastet."""
    beruehrt: set[int] = set()
    if d.zeitraum_id:
        beruehrt.add(d.zeitraum_id)
    if d.position_id:
        p = belegposten.loese(session, d)
        if p:
            beruehrt.add(p.zeitraum_id)
    for e in _entwuerfe_des_belegs(session, d.id):
        if isinstance(e, Kostenposition):
            beruehrt.add(e.zeitraum_id)
        session.delete(e)
    d.zeitraum_id = None
    d.status = "neu"
    session.add(d)
    return beruehrt


def _leere_zeitraeume_raeumen(session: Session, zeitraum_ids: set[int]) -> int:
    """Räumt die berührten, jetzt leeren Zeiträume weg — in einem einzigen
    Commit statt einem pro Zeitraum."""
    from ..routers.objekte import _zeitraum_leer_entfernen    # zirkelfrei zur Laufzeit
    entfernt = sum(1 for z in zeitraum_ids
                   if _zeitraum_leer_entfernen(session, z, commit=False))
    if entfernt:
        session.commit()
    return entfernt
