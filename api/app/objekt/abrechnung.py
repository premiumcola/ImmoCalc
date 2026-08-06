"""Abrechnungs-Endpunkt: die Engine über die Zeitraum-Positionen laufen lassen.

Nicht umlagefähige Kostenarten (N125, z. B. Einspeisevergütung) gehören dem
Eigentümer und werden dem Mieter nicht berechnet. Ein Vorab-Anteil (CCCLIX)
splittet die Position in zwei Engine-Positionen: der Vorab-Betrag geht direkt
auf eine Einheit (eigener §35a), der Rest über den gewählten Schlüssel.
"""
from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from ..db import get_session
from ..engine import Position, abrechnung
from ..models import Kostenart, Kostenposition, Vorauszahlung, Zeitraum
from ..verteilung import (ableiten_einheit, fehlende_angaben,
                          vorauszahlung_je_partei)
from .zeitraeume import _zeitraum

router = APIRouter(tags=["objekte"])


def _engine_positionen(session: Session, z: Zeitraum,
                       p: Kostenposition) -> list[Position]:
    """CCCLIX — eine Kostenposition in die zu rechnenden Engine-Positionen
    übersetzen. Trägt sie einen Vorab-Anteil direkt auf eine Einheit, entstehen
    zwei: der Vorab-Betrag zu 100 % auf diese Einheit (mit eigenem §35a) und der
    Rest (Betrag − Vorab) nach dem gewählten Schlüssel. Ohne Vorab bleibt es die
    eine Position wie bisher."""
    vorab = round(p.vorab_betrag or 0, 2)
    if vorab > 0 and (p.vorab_einheit or "").strip():
        aus = [Position(p.kostenart, vorab, "individuell",
                        ableiten_einheit(session, z, p.vorab_einheit), p.vorab_s35)]
        rest = round((p.betrag or 0) - vorab, 2)
        if rest > 0.005:
            aus.append(Position(p.kostenart, rest, p.schluessel, p.anteile or {}, p.s35))
        return aus
    return [Position(p.kostenart, p.betrag, p.schluessel, p.anteile or {}, p.s35)]


@router.get("/zeitraeume/{zid}/abrechnung")
def abrechnung_endpoint(zid: int, session: Session = Depends(get_session)) -> dict:
    z = _zeitraum(session, zid)
    pos = session.exec(select(Kostenposition).where(Kostenposition.zeitraum_id == zid)).all()
    vzs = session.exec(select(Vorauszahlung).where(Vorauszahlung.zeitraum_id == zid)).all()
    # N125 — nicht umlagefähige Kostenarten gehören dem Eigentümer und werden
    # dem Mieter nicht berechnet. Bisher fiel das nicht auf, weil es keine gab;
    # mit der Einspeisevergütung gibt es die erste: sie steht im Zeitraum, damit
    # sie zeitlich richtig zugeordnet ist und in die Amortisation der Anlage
    # fließt — in der Mieterrechnung hat sie nichts verloren.
    nicht_umlegen = {k.name.strip().lower() for k in session.exec(
        select(Kostenart).where(Kostenart.objekt_id == z.objekt_id)).all()
        if not k.umlagefaehig}
    umlegbar = [p for p in pos
                if p.kostenart.strip().lower() not in nicht_umlegen]
    # offene Positionen (Betrag noch nicht da) fließen nicht in die Rechnung ein
    positionen = [ep for p in umlegbar if p.status == "erledigt"
                  for ep in _engine_positionen(session, z, p)]
    # CCCLXIV — Vorauszahlungen aus der Miete ableiten (monatliche NK × belegte
    # Monate); separat erfasste Vorauszahlungs-Datensätze haben Vorrang.
    vorausz = {**vorauszahlung_je_partei(session, z),
               **{v.partei: v.betrag for v in vzs}}
    res = abrechnung(positionen, vorausz)
    # Erledigte Positionen ohne Gewichte gehören zu den offenen: ihr Betrag
    # verschwindet sonst lautlos, und der Abschluss übergeht sie.
    res.update(fehlende_angaben(list(umlegbar)))
    return res
