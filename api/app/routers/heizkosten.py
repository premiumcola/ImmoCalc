"""N340t/N340u — Heizkosten-Verteilung nach dem Delta-t-Rechenweg, aus echten
Zählern. Dünner Endpunkt: `heizkosten.py` rechnet, hier steht nur, wie das
Ergebnis geliefert oder in die Kostenposition eingetragen wird — dieselbe
Aufteilung wie bei `zaehler.uebernehmen` für die einfache Verbrauchs-
Gewichtung."""
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from .. import belegposten, heizkosten
from ..db import get_session
from ..models import Zeitraum

router = APIRouter(prefix="/api/zeitraeume", tags=["heizkosten"])


def _zeitraum(session: Session, zid: int) -> Zeitraum:
    z = session.get(Zeitraum, zid)
    if not z:
        raise HTTPException(404, "Zeitraum nicht gefunden")
    return z


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
    pos.schluessel = "heizkosten"
    pos.wertquelle = "Zähler"
    pos.anteile = {n["name"]: n["heizkosten"] for n in erg["nutzer"]}
    session.add(pos)
    session.commit()
    session.refresh(pos)
    return {"ok": True, "angewandt": True, "anteile": pos.anteile,
            "position_id": pos.id, "unzugeordnet": erg.get("unzugeordnet", []),
            "abgleich": erg.get("abgleich")}
