"""N340t/N340u — Heizkosten-Verteilung nach dem Delta-t-Rechenweg, aus echten
Zählern. Dünner Endpunkt: `heizkosten.py` rechnet, hier steht nur, wie das
Ergebnis geliefert oder in die Kostenposition eingetragen wird — dieselbe
Aufteilung wie bei `zaehler.uebernehmen` für die einfache Verbrauchs-
Gewichtung."""
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from sqlmodel import select

from .. import belegposten, heizkosten, verteilung
from ..db import get_session
from ..models import Einheit, Miete, Partei, Zeitraum

router = APIRouter(prefix="/api/zeitraeume", tags=["heizkosten"])


def _zeitraum(session: Session, zid: int) -> Zeitraum:
    z = session.get(Zeitraum, zid)
    if not z:
        raise HTTPException(404, "Zeitraum nicht gefunden")
    return z


def _bezuege(session: Session, z: Zeitraum) -> list[verteilung.Bezug]:
    """Wer in diesem Zeitraum abzurechnen ist — für die Übersetzung von
    Einheiten- auf Partei-Namen (N367)."""
    return verteilung.bezuege(
        list(session.exec(select(Einheit).where(
            Einheit.objekt_id == z.objekt_id)).all()),
        list(session.exec(select(Miete).where(
            Miete.objekt_id == z.objekt_id)).all()),
        list(session.exec(select(Partei).where(
            Partei.objekt_id == z.objekt_id)).all()),
        z.start, z.ende)


@router.post("/{zid}/heizkosten/rechnen")
def rechnen(zid: int, eingabe: dict, session: Session = Depends(get_session)) -> dict:
    """Rechnet die Heizkosten-Verteilung dieses Zeitraums nach dem Delta-t-
    Rechenweg — aus echten Zähler-Ablesungen und Bewertungsfaktoren. `eingabe`
    liefert nur, was am Zähler nicht steht (Brennstoff, Kostenblöcke,
    Warmwasservolumen, wie in `waermesim.rechne`). Schreibt nichts."""
    z = _zeitraum(session, zid)
    return heizkosten.rechne_fuer_zeitraum(session, z, eingabe or {})


@router.post("/{zid}/heizkosten/uebernehmen")
def uebernehmen(zid: int, eingabe: dict, session: Session = Depends(get_session)) -> dict:
    """Wie `rechnen`, trägt das Ergebnis aber als Verteilung in die
    bestehende Heizungs-Kostenposition ein. Nur eine BESTEHENDE Position wird
    konfiguriert (CCLVI: keine 0-€-Position ohne Beleg) — wie bei
    `zaehler.uebernehmen`."""
    z = _zeitraum(session, zid)
    erg = heizkosten.rechne_fuer_zeitraum(session, z, eingabe or {})
    pos = belegposten.finde(session, zid, "Heizung")
    if not pos:
        return {"ok": True, "angewandt": False,
                "grund": "Noch keine Heizungs-Position — erst den Beleg/Betrag erfassen."}
    # N367 — `heizkosten.nutzer_aus_zaehlern` schlüsselt nach EINHEIT, die
    # Abrechnung nach PARTEI. Ohne die Übersetzung bekamen Phantom-Parteien
    # die Heizkosten und die echten Mieter nichts.
    je_einheit = {n["name"]: n["heizkosten"] for n in erg["nutzer"]}
    anteile, ohne_partei = verteilung.auf_parteien(
        je_einheit, _bezuege(session, z), z.start, z.ende)
    unzugeordnet = list(erg.get("unzugeordnet", [])) + ohne_partei
    if not anteile:
        return {"ok": True, "angewandt": False,
                "grund": "Kein Wärmezähler ist einer Partei zugeordnet — die "
                         "Zuordnung steht in „Zähler konfigurieren“.",
                "unzugeordnet": unzugeordnet}
    pos.schluessel = "heizkosten"
    pos.wertquelle = "Zähler"
    pos.anteile = anteile
    session.add(pos)
    session.commit()
    session.refresh(pos)
    return {"ok": True, "angewandt": True, "anteile": pos.anteile,
            "position_id": pos.id, "unzugeordnet": unzugeordnet,
            "abgleich": erg.get("abgleich")}
