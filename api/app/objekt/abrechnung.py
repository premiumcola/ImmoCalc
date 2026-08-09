"""Abrechnungs-Endpunkt: die Engine über die Zeitraum-Positionen laufen lassen.

Nicht umlagefähige Kostenarten (N125, z. B. Einspeisevergütung) gehören dem
Eigentümer und werden dem Mieter nicht berechnet. Ein Vorab-Anteil (CCCLIX)
splittet die Position in zwei Engine-Positionen: der Vorab-Betrag geht direkt
auf eine Einheit (eigener §35a), der Rest über den gewählten Schlüssel.
"""
from fastapi import APIRouter, Depends
from sqlmodel import Session

from ..db import get_session
from ..engine import abrechnung
from ..verteilung import (fehlende_angaben, positionen_fuer_abrechnung,
                          unbekannte_vorauszahlungen)
from .zeitraeume import _zeitraum

router = APIRouter(tags=["objekte"])


@router.get("/zeitraeume/{zid}/abrechnung")
def abrechnung_endpoint(zid: int, session: Session = Depends(get_session)) -> dict:
    z = _zeitraum(session, zid)
    # N274 — die Positions-/Vorauszahlungs-Aufbereitung (N125-Filter,
    # CCCLIX-Vorab-Split, CCCLXIV-Vorauszahlung-aus-Miete) steht seither in
    # `verteilung.positionen_fuer_abrechnung` — dieselbe Stelle, die auch
    # `routers/versand.py` für den echten Versand nutzt, damit Vorschau und
    # Versand nie wieder auseinanderlaufen.
    positionen, vorausz, umlegbar, vzs = positionen_fuer_abrechnung(session, z)
    res = abrechnung(positionen, vorausz)
    # Erledigte Positionen ohne Gewichte gehören zu den offenen: ihr Betrag
    # verschwindet sonst lautlos, und der Abschluss übergeht sie.
    res.update(fehlende_angaben(list(umlegbar)))
    # N314(g) — dieselbe Lücke bei Vorauszahlungen: eine Zahlung ohne
    # passende Partei fliesst in `gesamt.abschlaege` ein, ohne in einer
    # Partei-Zeile aufzutauchen. Bislang nur in der Schlüssel-Vorschau
    # sichtbar (`GET .../schluessel`) — hier ebenso, direkt an der Abrechnung.
    res["vorauszahlungen_ohne_partei"] = unbekannte_vorauszahlungen(session, z, vzs)
    return res
