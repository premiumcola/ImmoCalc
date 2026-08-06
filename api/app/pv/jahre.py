"""Ein `Stromjahr` lesen/speichern und die Engine-Eingaben zusammenstellen
(N83/N89/N139/N216).

Die editierbaren Eingabefelder sind einmal in :data:`_FELDER` gelistet — Anzeige,
PUT und Anlegen sollen sich nicht auseinanderentwickeln. Was zur Anlage gehört
(Anschaffung, Leistung, Anteile, Vorlauf), kommt aus den Stammdaten (N139) und
überschreibt für die Rechnung die alten Jahresfelder.
"""
from __future__ import annotations

import json
import logging

from pydantic import BaseModel
from sqlmodel import Session, select

from .. import strom
from ..models import PVAnlage, Stromjahr
from .stammdaten import _STAMM_AUS_JAHR

log = logging.getLogger("immocalc")

# Die editierbaren Eingabefelder — einmal aufgelistet, damit Anzeige, PUT und
# Anlegen sich nicht auseinanderentwickeln.
_FELDER: tuple[str, ...] = (
    "gesamt_kwh", "wg_kwh", "garage_kwh", "wg_anteil_prozent", "tanken_kwh",
    "netz_kwh", "netz_preis", "solar_kwh", "solar_preis", "akku_kwh",
    "akku_preis", "pv_produktion_kwh", "einspeisung_kwh", "pv_kwp",
    "verguetung_eur", "anschaffung_eur",
    # N87/N89 — PV als Add-on-Investment: eigene Eigentümer-‰ und die
    # E-Tankstelle (Satz + wem sie berechnet wird).
    "pv_anteile", "tanken_preis", "tanken_person",
    # N127 — was die Anlage VOR der ersten Nebenkostenabrechnung schon
    # abgetragen hat: ein einmaliger Betrag, der auf das erste erfasste Jahr
    # zählt und nicht über die Jahre verteilt wird.
    "vorlauf_ertrag_eur",
    # N124 — die E-Auto-Ladungen aus dem Gesamtverbrauch herausrechnen: welche
    # Einheit sie trägt und wie viel davon Netz bzw. eigene Anlage war
    # (`strombloecke.verteile`). Von Hand eingetragen, solange die Wallbox
    # nichts liefert.
    "eauto_einheit", "eauto_extern_kwh", "eauto_eigen_kwh",
)
# N139 — `anschaffung_eur`, `pv_kwp`, `pv_anteile` und `vorlauf_ertrag_eur`
# gehören zur Anlage, nicht zum Jahr. Sie stehen weiter in der Liste (die
# Spalten bleiben, der PUT nimmt sie noch an), gepflegt werden sie aber über
# `…/pv/stammdaten` — von dort kommen auch die Werte für die Rechnung
# (siehe `_STAMM_AUS_JAHR` und `_eingaben`).

# N89 — Spalte für die Zuordnung Gruppe → Einheiten. Sie ist im Datenmodell noch
# nicht angelegt; solange sie fehlt, arbeitet der Endpunkt rein parameterbasiert
# und der PUT nimmt die Angabe zwar an, kann sie aber nicht behalten.
_ZUORDNUNG_SPALTE = "gruppen_einheiten"
_HAT_SPALTE = hasattr(Stromjahr, _ZUORDNUNG_SPALTE)


class StromIn(BaseModel):
    """Eingaben eines Strom-Jahres.

    N150 — ALLE Felder sind `None`-Default, nicht 0.0/"". Vorher nahm der PUT
    immer den ganzen Satz: wer nur einen Teil der Maske schickte, setzte alle
    uebrigen Felder still auf 0. Das hat real Daten gekostet (`pv_kwp` 12,0
    und `anschaffung_eur` 35.700 fielen so auf 0). `None` heisst jetzt
    „nicht mitgeschickt" und laesst den gespeicherten Wert stehen. Alle optional (Default 0/„") — der Nutzer
    füllt die Maske Schritt für Schritt, ein leeres Feld bleibt 0."""
    gesamt_kwh: float | None = None
    wg_kwh: float | None = None
    garage_kwh: float | None = None
    wg_anteil_prozent: float | None = None
    tanken_kwh: float | None = None
    netz_kwh: float | None = None
    netz_preis: float | None = None
    solar_kwh: float | None = None
    solar_preis: float | None = None
    akku_kwh: float | None = None
    akku_preis: float | None = None
    pv_produktion_kwh: float | None = None
    einspeisung_kwh: float | None = None
    pv_kwp: float | None = None
    verguetung_eur: float | None = None
    anschaffung_eur: float | None = None
    pv_anteile: str | None = None              # JSON {Name: ‰}; leer = Vorgabe 5/6+1/6
    tanken_preis: float | None = None
    tanken_person: str | None = None
    # N127 — Vorlauf vor der ersten Abrechnung (einmalig, s. `_FELDER`).
    vorlauf_ertrag_eur: float | None = None
    # N108 (Fund 2) — diese drei Felder schickt die Maske nicht mit. Als
    # Pflichtfeld mit Default "" loeschte jedes Speichern die gespeicherte
    # Zuordnung und die Notiz. `None` heisst jetzt „nicht mitgeschickt".
    notiz: str | None = None
    # N124 — die von Hand eingetragene E-Auto-Aufteilung. Ebenfalls optional:
    # ein Speichern der Strom-Maske darf sie nicht auf 0 zurücksetzen.
    eauto_einheit: str | None = None
    eauto_extern_kwh: float | None = None
    eauto_eigen_kwh: float | None = None
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
              buero: str | None = None,
              anlage: PVAnlage | None = None) -> dict:
    """Die Engine-Eingaben eines Strom-Jahres als dict — Spaltenwerte plus die
    Einheiten-Zuordnung. Ein gesetzter Abfrageparameter hat Vorrang vor der
    gespeicherten Zuordnung.

    N139 — was zur Anlage gehört (Anschaffung, Leistung, Anteile), kommt aus den
    Stammdaten und überschreibt die alten Jahresfelder; ist dort nichts
    hinterlegt, gilt weiterhin der Jahreswert."""
    gespeichert = _gespeicherte_zuordnung(sj)
    daten = {f: getattr(sj, f) for f in _FELDER}
    daten["wg_einheiten"] = wg if wg is not None \
        else gespeichert.get(strom.GRUPPE_WG, "")
    daten["buero_einheiten"] = buero if buero is not None \
        else gespeichert.get(strom.GRUPPE_BUERO, "")
    if anlage is not None:
        for stamm, jahresfeld in _STAMM_AUS_JAHR.items():
            wert = getattr(anlage, stamm)
            if wert:
                daten[jahresfeld] = wert
    return daten


def _zeige(sj: Stromjahr) -> dict:
    """Ein Strom-Jahr als JSON (Eingabewerte inkl. Einheiten-Zuordnung)."""
    gespeichert = _gespeicherte_zuordnung(sj)
    return {"jahr": sj.jahr, "notiz": sj.notiz,
            **{f: getattr(sj, f) for f in _FELDER},
            "wg_einheiten": gespeichert.get(strom.GRUPPE_WG, ""),
            "buero_einheiten": gespeichert.get(strom.GRUPPE_BUERO, "")}
