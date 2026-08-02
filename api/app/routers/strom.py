"""N83 — Strom-/PV-Endpunkte: Eingaben je Objekt/Jahr lesen/speichern und das
Engine-Ergebnis (Kosten je Verbrauchsgruppe, PV-Ertrag je Eigentümer) abrufen.

Die Rechenlogik lebt in der Engine (`app.strom`); die Endpunkte bleiben dünn:
sie holen/legen den `Stromjahr`-Datensatz und reichen ihn an die Engine weiter.

Routen-Reihenfolge: `/objekte/{slug}/strom/…` steht vor dem Stammdaten-Fänger
`/objekte/{slug}/{bereich}` — der Router wird in `main.py` entsprechend früh
eingehängt (analog zu `zaehler`/`heizoel`/`waerme`).

N89 — welche Einheiten zu welcher Verbrauchsgruppe gehören, kommt entweder als
Abfrageparameter (`?wg=EG,1.OG&buero=Studio`) oder aus dem gespeicherten Feld
`Stromjahr.gruppen_einheiten` (JSON {Gruppe: "A,B"}), sobald es das gibt; der
Parameter hat Vorrang. Fehlt beides, bleibt die Rechnung bei den zwei Gruppen.
"""
import json
import logging

from fastapi import APIRouter, Depends, Query
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

# N89 — Spalte für die Zuordnung Gruppe → Einheiten. Sie ist im Datenmodell noch
# nicht angelegt; solange sie fehlt, arbeitet der Endpunkt rein parameterbasiert
# und der PUT nimmt die Angabe zwar an, kann sie aber nicht behalten.
_ZUORDNUNG_SPALTE = "gruppen_einheiten"
_HAT_SPALTE = hasattr(Stromjahr, _ZUORDNUNG_SPALTE)


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
    # N108 (Fund 2) — diese drei Felder schickt die Maske nicht mit. Als
    # Pflichtfeld mit Default "" loeschte jedes Speichern die gespeicherte
    # Zuordnung und die Notiz. `None` heisst jetzt „nicht mitgeschickt".
    notiz: str | None = None
    # N89 — Zuordnung der Immobilien-Einheiten zu den beiden Verbrauchsgruppen,
    # je eine komma-separierte Liste von Bezeichnungen ("EG, 1.OG").
    wg_einheiten: str | None = None
    buero_einheiten: str | None = None


def _hole_oder_neu(session: Session, objekt_id: int, jahr: int) -> Stromjahr:
    """Den Strom-Datensatz eines Objekt-Jahres holen — oder einen neuen,
    ungespeicherten mit Vorgabewerten (0) zurückgeben."""
    sj = session.exec(
        select(Stromjahr).where(Stromjahr.objekt_id == objekt_id,
                                Stromjahr.jahr == jahr)).first()
    return sj or Stromjahr(objekt_id=objekt_id, jahr=jahr)


def _gespeicherte_zuordnung(sj: Stromjahr) -> dict[str, str]:
    """Die gespeicherte Zuordnung Gruppe → Einheiten als {Gruppe: "A,B"}.

    Gibt es die Spalte noch nicht oder ist sie leer/unlesbar, ist die Zuordnung
    leer — die Rechnung bleibt dann bei den zwei Gruppen."""
    roh = getattr(sj, _ZUORDNUNG_SPALTE, "") if _HAT_SPALTE else ""
    if not roh:
        return {}
    try:
        d = json.loads(roh) if isinstance(roh, str) else dict(roh)
        return {str(k): ",".join(strom.einheiten_liste(v))
                for k, v in d.items()}
    except (ValueError, TypeError, AttributeError):
        log.warning("%s unlesbar — Zuordnung ignoriert", _ZUORDNUNG_SPALTE)
        return {}


def _merke_zuordnung(sj: Stromjahr, wg: str, buero: str) -> None:
    """Die Zuordnung als JSON in der dafür vorgesehenen Spalte ablegen — sofern
    es sie im Datenmodell schon gibt. Sonst nur ein Hinweis ins Log: die Angabe
    wird angenommen, wirkt aber nur für die Dauer der Anfrage."""
    if not _HAT_SPALTE:
        if wg or buero:
            log.info("Spalte %s fehlt — Einheiten-Zuordnung nicht gespeichert",
                     _ZUORDNUNG_SPALTE)
        return
    setattr(sj, _ZUORDNUNG_SPALTE, json.dumps(
        {strom.GRUPPE_WG: wg, strom.GRUPPE_BUERO: buero}, ensure_ascii=False)
        if (wg or buero) else "")


def _eingaben(sj: Stromjahr, wg: str | None = None,
              buero: str | None = None) -> dict:
    """Die Engine-Eingaben eines Strom-Jahres als dict — Spaltenwerte plus die
    Einheiten-Zuordnung. Ein gesetzter Abfrageparameter hat Vorrang vor der
    gespeicherten Zuordnung."""
    gespeichert = _gespeicherte_zuordnung(sj)
    daten = {f: getattr(sj, f) for f in _FELDER}
    daten["wg_einheiten"] = wg if wg is not None \
        else gespeichert.get(strom.GRUPPE_WG, "")
    daten["buero_einheiten"] = buero if buero is not None \
        else gespeichert.get(strom.GRUPPE_BUERO, "")
    return daten


def _zeige(sj: Stromjahr) -> dict:
    """Ein Strom-Jahr als JSON (Eingabewerte inkl. Einheiten-Zuordnung)."""
    gespeichert = _gespeicherte_zuordnung(sj)
    return {"jahr": sj.jahr, "notiz": sj.notiz,
            **{f: getattr(sj, f) for f in _FELDER},
            "wg_einheiten": gespeichert.get(strom.GRUPPE_WG, ""),
            "buero_einheiten": gespeichert.get(strom.GRUPPE_BUERO, "")}


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
    werte = data.model_dump(exclude_none=True)
    wg = werte.pop("wg_einheiten", None)
    buero = werte.pop("buero_einheiten", None)
    for feld, wert in werte.items():
        setattr(sj, feld, wert)
    # Nur anfassen, wenn wirklich etwas mitkam - sonst bleibt die gespeicherte
    # Zuordnung stehen.
    if wg is not None or buero is not None:
        _merke_zuordnung(sj, wg or "", buero or "")
    session.add(sj)
    session.commit()
    session.refresh(sj)
    return _zeige(sj)


_WG_PARAM = Query(None, description="Einheiten der Gruppe WG, komma-separiert")
_BUERO_PARAM = Query(None, description="Einheiten der Gruppe Büro/Studio")


@router.get("/objekte/{slug}/strom/{jahr}/rechnung")
def rechnung(slug: str, jahr: int, wg: str | None = _WG_PARAM,
             buero: str | None = _BUERO_PARAM,
             session: Session = Depends(get_session),
             o: Objekt = Depends(objekt_holen)) -> dict:
    """Das Engine-Ergebnis: Kosten je Verbrauchsgruppe (WG / Büro-Studio),
    die Aufteilung auf die zugeordneten Einheiten (N89), PV-Ertrag und dessen
    Verteilung auf die Eigentümer (`strom.rechne`).

    `?wg=EG,1.OG&buero=Studio` ordnet die Einheiten den Gruppen zu; ohne die
    Angabe bleibt der Block `einheiten` leer."""
    return strom.rechne(_eingaben(_hole_oder_neu(session, o.id, jahr), wg, buero))


@router.get("/objekte/{slug}/strom/{jahr}/nk-positionen")
def nk_positionen(slug: str, jahr: int, wg: str | None = _WG_PARAM,
                  buero: str | None = _BUERO_PARAM,
                  session: Session = Depends(get_session),
                  o: Objekt = Depends(objekt_holen)) -> dict:
    """N89 — die Strompositionen für die Nebenkostenabrechnung: je Einheit ein
    Betrag in €, dazu die kWh als Beleg und die Gesamtsumme.

    Das ist der Zweck der ganzen Rechnerei: `[{einheit, betrag, kwh}]` lässt
    sich unverändert als Kostenposition „Strom" übernehmen."""
    ergebnis = strom.rechne(_eingaben(_hole_oder_neu(session, o.id, jahr),
                                      wg, buero))
    return {"jahr": jahr, **strom.nk_positionen(ergebnis)}


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
