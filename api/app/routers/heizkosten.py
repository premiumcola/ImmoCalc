"""N340t/N340u — Heizkosten-Verteilung nach dem Delta-t-Rechenweg, aus echten
Zählern. Dünner Endpunkt: `heizkosten.py` rechnet, hier steht nur, wie das
Ergebnis geliefert oder in die Kostenposition eingetragen wird — dieselbe
Aufteilung wie bei `zaehler.uebernehmen` für die einfache Verbrauchs-
Gewichtung."""
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from sqlmodel import select

from .. import belegposten, heizkosten, models, verteilung
from ..db import get_session
from ..models import Einheit, Miete, Partei, Zeitraum
from ..deps import zeitraum_holen

router = APIRouter(prefix="/api/zeitraeume", tags=["heizkosten"])



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
    z = zeitraum_holen(zid, session)
    return heizkosten.rechne_fuer_zeitraum(session, z, eingabe or {})


@router.post("/{zid}/heizkosten/uebernehmen")
def uebernehmen(zid: int, eingabe: dict, session: Session = Depends(get_session)) -> dict:
    """Wie `rechnen`, trägt das Ergebnis aber als Verteilung in die
    bestehende Heizungs-Kostenposition ein. Nur eine BESTEHENDE Position wird
    konfiguriert (CCLVI: keine 0-€-Position ohne Beleg) — wie bei
    `zaehler.uebernehmen`."""
    z = zeitraum_holen(zid, session)
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
    # N401 — den BETRAG mitschreiben, nicht nur die Verteilung. Vorher setzte
    # dieser Endpunkt allein `anteile`; der errechnete Heizungsbetrag blieb in
    # der Oberfläche stehen und die Kostenposition auf 0,00 €. Die Abrechnung
    # zählt aber `Kostenposition.betrag` — die kompletten Heizkosten fehlten
    # dadurch in jeder Abrechnung (bei der Laufer Str. 5 3.013,19 € von
    # 9.372,97 €, also fast ein Drittel). Beides gehört in denselben Schreib-
    # vorgang, sonst können Betrag und Verteilung wieder auseinanderlaufen.
    pos.betrag = erg["heizung"]["gesamt"]
    pos.status = models.ERLEDIGT if pos.betrag > 0.005 else models.OFFEN
    session.add(pos)
    session.commit()
    session.refresh(pos)
    return {"ok": True, "angewandt": True, "anteile": pos.anteile,
            "betrag": pos.betrag, "position_id": pos.id,
            "unzugeordnet": unzugeordnet, "abgleich": erg.get("abgleich")}
