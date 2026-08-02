"""N83 — Strom-/PV-Endpunkte: Eingaben je Objekt/Jahr lesen/speichern und das
Engine-Ergebnis (Kosten je Verbrauchsgruppe, PV-Ertrag je Eigentümer) abrufen.

Die Rechenlogik lebt in der Engine (`app.strom`); die Endpunkte bleiben dünn:
sie holen/legen den `Stromjahr`-Datensatz und reichen ihn an die Engine weiter.

Routen-Reihenfolge: `/objekte/{slug}/strom/…` steht vor dem Stammdaten-Fänger
`/objekte/{slug}/{bereich}` — der Router wird in `main.py` entsprechend früh
eingehängt (analog zu `zaehler`/`heizoel`/`waerme`).
"""
import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, select

from .. import strom
from ..db import get_session
from ..deps import objekt_holen
from ..models import Objekt, Stromjahr

log = logging.getLogger("immocalc")
router = APIRouter(prefix="/api", tags=["strom"])

# Die editierbaren Eingabefelder — einmal aufgelistet, damit Anzeige, PUT und
# Anlegen sich nicht auseinanderentwickeln.
_FELDER = (
    "gesamt_kwh", "wg_kwh", "garage_kwh", "wg_anteil_prozent", "tanken_kwh",
    "netz_kwh", "netz_preis", "solar_kwh", "solar_preis", "akku_kwh",
    "akku_preis", "pv_produktion_kwh", "einspeisung_kwh", "pv_kwp",
    "verguetung_eur", "anschaffung_eur",
    # N87/N89 — PV als Add-on-Investment: eigene Eigentümer-‰ und die
    # E-Tankstelle (Satz + wem sie berechnet wird).
    "pv_anteile", "tanken_preis", "tanken_person",
)


class StromIn(BaseModel):
    """Eingaben eines Strom-Jahres. Alle optional (Default 0/„") — der Nutzer
    füllt die Maske Schritt für Schritt, ein leeres Feld bleibt 0."""
    gesamt_kwh: float = 0.0
    wg_kwh: float = 0.0
    garage_kwh: float = 0.0
    wg_anteil_prozent: float = 0.0
    tanken_kwh: float = 0.0
    netz_kwh: float = 0.0
    netz_preis: float = 0.0
    solar_kwh: float = 0.0
    solar_preis: float = 0.0
    akku_kwh: float = 0.0
    akku_preis: float = 0.0
    pv_produktion_kwh: float = 0.0
    einspeisung_kwh: float = 0.0
    pv_kwp: float = 0.0
    verguetung_eur: float = 0.0
    anschaffung_eur: float = 0.0
    pv_anteile: str = ""              # JSON {Name: ‰}; leer = Vorgabe 5/6+1/6
    tanken_preis: float = 0.0
    tanken_person: str = ""
    notiz: str = ""


def _hole_oder_neu(session: Session, objekt_id: int, jahr: int) -> Stromjahr:
    """Den Strom-Datensatz eines Objekt-Jahres holen — oder einen neuen,
    ungespeicherten mit Vorgabewerten (0) zurückgeben."""
    sj = session.exec(
        select(Stromjahr).where(Stromjahr.objekt_id == objekt_id,
                                Stromjahr.jahr == jahr)).first()
    return sj or Stromjahr(objekt_id=objekt_id, jahr=jahr)


def _zeige(sj: Stromjahr) -> dict:
    """Ein Strom-Jahr als JSON (Eingabewerte)."""
    return {"jahr": sj.jahr, "notiz": sj.notiz,
            **{f: getattr(sj, f) for f in _FELDER}}


@router.get("/objekte/{slug}/strom/{jahr}")
def lesen(slug: str, jahr: int, session: Session = Depends(get_session),
          o: Objekt = Depends(objekt_holen)) -> dict:
    """Die Strom-Eingaben eines Objekt-Jahres lesen (leerer Satz, wenn noch
    nichts erfasst wurde)."""
    return _zeige(_hole_oder_neu(session, o.id, jahr))


@router.put("/objekte/{slug}/strom/{jahr}")
def speichern(slug: str, jahr: int, data: StromIn,
              session: Session = Depends(get_session),
              o: Objekt = Depends(objekt_holen)) -> dict:
    """Die Strom-Eingaben eines Objekt-Jahres speichern (anlegen oder
    aktualisieren) — ein Datensatz je Objekt und Jahr."""
    sj = _hole_oder_neu(session, o.id, jahr)
    for feld, wert in data.model_dump().items():
        setattr(sj, feld, wert)
    session.add(sj)
    session.commit()
    session.refresh(sj)
    return _zeige(sj)


@router.get("/objekte/{slug}/strom/{jahr}/rechnung")
def rechnung(slug: str, jahr: int, session: Session = Depends(get_session),
             o: Objekt = Depends(objekt_holen)) -> dict:
    """Das Engine-Ergebnis: Kosten je Verbrauchsgruppe (WG / Büro-Studio),
    PV-Ertrag und dessen Verteilung auf die Eigentümer (`strom.rechne`)."""
    return strom.rechne(_hole_oder_neu(session, o.id, jahr))


@router.get("/objekte/{slug}/pv/amortisation")
def pv_amortisation(slug: str, session: Session = Depends(get_session),
                    o: Objekt = Depends(objekt_holen)) -> dict:
    """N87 — Amortisierung der PV-Anlage über ALLE erfassten Jahre.

    Je Jahr wird der Investitions-Ertrag gerechnet (was Mieter für PV-Strom
    zahlen + Einspeisevergütung + Tank-Erlös) und kumuliert gegen die
    Anschaffung gestellt. Die Anschaffung ist die zuletzt erfasste (sie ändert
    sich nicht jährlich). Zusätzlich die Verteilung des kumulierten Ertrags auf
    die PV-Eigentümer nach ihren eigenen Tausendsteln."""
    jahre = session.exec(
        select(Stromjahr).where(Stromjahr.objekt_id == o.id)
        .order_by(Stromjahr.jahr)).all()
    reihe, anschaffung, anteile = [], 0.0, strom.EIGENTUEMER_ANTEILE
    for sj in jahre:
        r = strom.rechne(sj)
        reihe.append({"jahr": sj.jahr, "ertrag": r["pv"]["investitions_ertrag"]})
        if sj.anschaffung_eur:
            anschaffung = sj.anschaffung_eur
        anteile = strom._pv_anteile(sj)
    a = strom.amortisation(reihe, anschaffung)
    a["eigentuemer"] = strom.verteile_eigentuemer(a["kumuliert"], anteile)
    return a
