"""N83 — Strom-/PV-Endpunkte: Eingaben je Objekt/Jahr lesen/speichern und das
Engine-Ergebnis (Kosten je Verbrauchsgruppe, PV-Ertrag je Eigentümer) abrufen.

Die Rechenlogik lebt in der Engine (`app.strom`); die Endpunkte bleiben dünn:
sie holen/legen den `Stromjahr`-Datensatz und reichen ihn an die Engine weiter.

Routen-Reihenfolge: `/objekte/{slug}/strom/…` steht vor dem Stammdaten-Fänger
`/objekte/{slug}/{bereich}` — der Router wird in `main.py` entsprechend früh
eingehängt (analog zu `zaehler`/`heizoel`/`waerme`).

N139 — was zur Anlage gehört und nicht zum Jahr (Anschaffung, bereits
Abgetragenes, Leistung, Eigentümer-Anteile), steht in `PVAnlage` und wird über
`…/pv/stammdaten` gepflegt. Die gleichnamigen Felder am `Stromjahr` bleiben
stehen (nie umbenennen, nie entfernen), werden aber nur noch für die einmalige
Übernahme des Bestands gelesen.

N89 — welche Einheiten zu welcher Verbrauchsgruppe gehören, kommt entweder als
Abfrageparameter (`?wg=EG,1.OG&buero=Studio`) oder aus dem gespeicherten Feld
`Stromjahr.gruppen_einheiten` (JSON {Gruppe: "A,B"}), sobald es das gibt; der
Parameter hat Vorrang. Fehlt beides, bleibt die Rechnung bei den zwei Gruppen.
"""
import json
import logging

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from .. import strom
from ..db import get_session
from ..deps import objekt_holen
from ..models import (Anteil, Eigentuemer, Kostenart, Kostenposition, Objekt,
                      PVAnlage, Stromjahr, Tankladung, Zeitraum)
from .objekte import zeitraum_label_jahr

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


# --------------------------------------------------------------------------
# N139 — Stammdaten der PV-Anlage: was einmal gilt, nicht jedes Jahr neu.
#
# Anschaffung, bereits Abgetragenes, Leistung und die Eigentümer-Anteile hingen
# bisher am `Stromjahr` und wechselten damit mit der Jahresauswahl — die Anlage
# wurde aber einmal gekauft, nicht jedes Jahr neu. Sie stehen jetzt in
# `PVAnlage` (ein Satz je Objekt). Die alten Spalten am `Stromjahr` bleiben
# stehen und werden ignoriert; ihre Werte werden einmalig übernommen, damit
# kein Bestand verloren geht.
# --------------------------------------------------------------------------

# Stammdatenfeld → altes Feld am `Stromjahr`. Nur für die einmalige Übernahme.
_STAMM_AUS_JAHR = {
    "anschaffung_eur": "anschaffung_eur",
    "vorlauf_ertrag_eur": "vorlauf_ertrag_eur",
    "kwp": "pv_kwp",
    "anteile": "pv_anteile",
}

_VOLLE_PROMILLE = 1000.0
# Rundungsluft: 833,3 + 166,7 = 1000,0 soll als „geht auf" gelten.
_PROMILLE_TOLERANZ = 0.5


class StammdatenIn(BaseModel):
    """Die Stammdaten der PV-Anlage.

    Alle Felder optional: `None` heißt „nicht mitgeschickt" und lässt den
    gespeicherten Wert stehen. Das ist die Lehre aus N108 (Fund 2) — ein
    Pflichtfeld mit Default löscht bei jedem Teil-Speichern die übrigen
    Angaben."""
    anschaffung_eur: float | None = None
    vorlauf_ertrag_eur: float | None = None
    # N153 — der Vorlauf aufgeschlüsselt nach denselben Quellen wie die Jahre
    # danach. Ebenfalls `None`-Default: wer nur PV-Strom tippt, darf damit die
    # Einspeisung nicht auf 0 setzen (genau dieser Fehler kostete in N150 Daten).
    vorlauf_pv_strom_eur: float | None = None
    vorlauf_einspeisung_eur: float | None = None
    vorlauf_tanken_eur: float | None = None
    kwp: float | None = None
    inbetriebnahme: date | None = None
    anteile: str | None = None        # JSON {Name: ‰}
    notiz: str | None = None


# Quelle im Verlauf → Feld an der Anlage. Dieselben drei Namen wie in
# `_QUELLEN_LEER`, damit Vorlauf und Jahre dieselbe Sprache sprechen.
_VORLAUF_QUELLEN = {"pv_strom": "vorlauf_pv_strom_eur",
                    "einspeisung": "vorlauf_einspeisung_eur",
                    "tanken": "vorlauf_tanken_eur"}


def _vorlauf(a: PVAnlage) -> tuple[float, dict[str, float] | None]:
    """N153 — was die Anlage vor der ersten Abrechnung abgetragen hat: der
    Betrag und, wenn gepflegt, seine Herkunft.

    Die Vorrang-Regel: ist die Aufschlüsselung gepflegt (mindestens eines der
    drei Felder ≠ 0), gilt IHRE SUMME als Vorlauf. Sonst gilt weiterhin der
    Gesamtwert `vorlauf_ertrag_eur`. So bleibt der bestehende Wert des Nutzers
    gültig, bis er die Aufteilung einträgt — und es entstehen keine zwei
    Wahrheiten. `vorlauf_ertrag_eur` bleibt dabei unangetastet stehen."""
    teile = {quelle: round(float(getattr(a, feld, 0.0) or 0.0), 2)
             for quelle, feld in _VORLAUF_QUELLEN.items()}
    if any(teile.values()):
        return round(sum(teile.values()), 2), teile
    return round(a.vorlauf_ertrag_eur or 0.0, 2), None


def _erster_abrechnungsstart(session: Session, objekt_id: int) -> date | None:
    """Der Beginn des ersten Abrechnungszeitraums — die Grenze, bis zu der der
    Vorlauf zählt. Kommt aus den Daten; kein Datum steht im Code."""
    return session.exec(select(Zeitraum.start)
                        .where(Zeitraum.objekt_id == objekt_id)
                        .order_by(Zeitraum.start)).first()


def _anteile_dict(roh: str | None) -> dict[str, float]:
    """Die Anteile als {Name: ‰}. Unlesbares oder Leeres ergibt {} — die
    Vorgabe 5/6 + 1/6 greift dann weiter unten."""
    if not roh:
        return {}
    try:
        d = json.loads(roh) if isinstance(roh, str) else dict(roh)
        return {str(k): float(v) for k, v in d.items() if float(v) > 0}
    except (ValueError, TypeError, AttributeError):
        log.warning("PV-Anteile unlesbar — Vorgabe 5/6+1/6")
        return {}


def _anteile_tupel(anlage: PVAnlage) -> tuple[tuple[str, float], ...]:
    """Die Anteile in der Form, die `strom.verteile_eigentuemer` erwartet."""
    anteile = _anteile_dict(anlage.anteile)
    return tuple(anteile.items()) if anteile else strom.EIGENTUEMER_ANTEILE


def _uebernahme_aus_jahren(session: Session, objekt_id: int) -> dict:
    """Die Bestandswerte aus den Strom-Jahren einsammeln — je Feld der zuletzt
    erfasste gefüllte Wert (die Angaben wanderten nicht jedes Jahr mit, oft
    steht die Anschaffung nur an einem einzigen Jahr)."""
    werte: dict[str, object] = {}
    for sj in session.exec(select(Stromjahr)
                           .where(Stromjahr.objekt_id == objekt_id)
                           .order_by(Stromjahr.jahr)).all():
        for stamm, alt in _STAMM_AUS_JAHR.items():
            wert = getattr(sj, alt, None)
            if wert:
                werte[stamm] = wert
    return werte


def _stammdaten(session: Session, objekt_id: int) -> PVAnlage:
    """Die Stammdaten eines Objekts — bei Bedarf angelegt.

    Gibt es noch keinen Satz, werden die Bestandswerte **einmalig** aus den
    Strom-Jahren übernommen und festgeschrieben. Danach gilt nur noch, was hier
    steht: ein Jahreswechsel ändert die Stammdaten nicht mehr. Ist nichts zu
    übernehmen, kommt ein leerer, ungespeicherter Satz zurück — erst der PUT
    legt ihn wirklich an."""
    anlage = session.exec(select(PVAnlage)
                          .where(PVAnlage.objekt_id == objekt_id)).first()
    if anlage:
        return anlage
    anlage = PVAnlage(objekt_id=objekt_id)
    uebernommen = _uebernahme_aus_jahren(session, objekt_id)
    for feld, wert in uebernommen.items():
        setattr(anlage, feld, wert)
    if uebernommen:
        session.add(anlage)
        session.commit()
        session.refresh(anlage)
        log.info("PV-Stammdaten aus den Strom-Jahren übernommen (Objekt %s): %s",
                 objekt_id, ", ".join(sorted(uebernommen)))
    return anlage


def _promille_text(wert: float) -> str:
    """Eine ‰-Zahl deutsch und ohne überflüssige Nullen."""
    return f"{wert:.1f}".rstrip("0").rstrip(".").replace(".", ",")


def _anteile_hinweise(anteile: dict[str, float], summe: float) -> list[str]:
    """Ein ruhiger Hinweis, wenn die vergebenen Anteile nicht 1000 ‰ ergeben.
    Ein Hinweis, keine Sperre — gespeichert wird trotzdem."""
    if not anteile or abs(summe - _VOLLE_PROMILLE) <= _PROMILLE_TOLERANZ:
        return []
    rest = round(_VOLLE_PROMILLE - summe, 1)
    fehlt = (f"{_promille_text(abs(rest))} ‰ "
             + ("fehlen noch" if rest > 0 else "zu viel"))
    return [f"Die vergebenen Anteile ergeben {_promille_text(summe)} ‰ "
            f"statt 1000 ‰ — {fehlt}."]


def _zeige_stammdaten(a: PVAnlage, vorlauf_bis: date | None = None) -> dict:
    """Die Stammdaten als JSON, inklusive der aufgelösten Anteile und der
    Hinweise zur Anteilssumme.

    N153 — dazu der Vorlauf in drei Formen: die drei Einzelfelder (die Maske),
    der geltende Betrag `vorlauf_summe` (die Vorrang-Regel, siehe `_vorlauf`)
    und `vorlauf_bis`, der Beginn des ersten Abrechnungszeitraums — daraus sagt
    die Maske, welcher Zeitraum überhaupt gemeint ist."""
    anteile = _anteile_dict(a.anteile)
    summe = round(sum(anteile.values()), 3)
    vorlauf_summe, vorlauf_teile = _vorlauf(a)
    return {
        "anschaffung_eur": a.anschaffung_eur,
        "vorlauf_ertrag_eur": a.vorlauf_ertrag_eur,
        **{feld: getattr(a, feld, 0.0) or 0.0
           for feld in _VORLAUF_QUELLEN.values()},
        "vorlauf_summe": vorlauf_summe,
        "vorlauf_teile": vorlauf_teile,
        "vorlauf_aufgeschluesselt": vorlauf_teile is not None,
        "vorlauf_bis": vorlauf_bis.isoformat() if vorlauf_bis else None,
        "kwp": a.kwp,
        "inbetriebnahme": a.inbetriebnahme.isoformat() if a.inbetriebnahme else None,
        "anteile": a.anteile or "",
        "anteile_promille": anteile,
        "anteile_summe": summe,
        "notiz": a.notiz,
        "hinweise": _anteile_hinweise(anteile, summe),
    }


@router.get("/objekte/{slug}/pv/stammdaten")
def stammdaten_lesen(slug: str, session: Session = Depends(get_session),
                     o: Objekt = Depends(objekt_holen)) -> dict:
    """N139 — die Stammdaten der PV-Anlage lesen (jahresunabhängig)."""
    return _zeige_stammdaten(_stammdaten(session, o.id),
                             _erster_abrechnungsstart(session, o.id))


@router.put("/objekte/{slug}/pv/stammdaten")
def stammdaten_speichern(slug: str, data: StammdatenIn,
                         session: Session = Depends(get_session),
                         o: Objekt = Depends(objekt_holen)) -> dict:
    """N139 — die Stammdaten der PV-Anlage speichern (anlegen oder ändern).
    Nicht mitgeschickte Felder bleiben unverändert."""
    anlage = _stammdaten(session, o.id)
    for feld, wert in data.model_dump(exclude_none=True).items():
        setattr(anlage, feld, wert)
    session.add(anlage)
    session.commit()
    session.refresh(anlage)
    return _zeige_stammdaten(anlage, _erster_abrechnungsstart(session, o.id))


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


def _autarkie(ergebnis: dict) -> dict:
    """N154 — wie viel des VERBRAUCHTEN Stroms aus der eigenen Anlage kam.

    Bewusst die Verbraucherseite: (Solar + Akku) / (Netz + Solar + Akku). Das
    sind dieselben drei Mengen, aus denen die Engine auch die Kosten verteilt —
    eine einzige Quelle, keine zweite Rechnung daneben.

    N160 — die Erzeugerseite (Produktion − Einspeisung) wird hier bewusst NICHT
    gezeigt. Sie beantwortet keine Frage, die auf dieser Seite gestellt wird,
    und wurde genau deshalb für die Verbraucherseite gehalten: 8.375 gegen
    8.208 kWh, beides richtig, beides verwechselbar. Die Produktionsseite hat
    genau eine Aufgabe — sie sagt, wie viel wirklich ins Netz ging, und trägt
    damit die Einspeisevergütung. Eine Zahl weniger, die man verwechseln kann."""
    q = ergebnis["quellen"]
    eigen = round(q["solar"]["kwh"] + q["akku"]["kwh"], 3)
    verbrauch = round(eigen + q["netz"]["kwh"], 3)
    return {
        "eigen_kwh": eigen,
        "solar_kwh": q["solar"]["kwh"],
        "akku_kwh": q["akku"]["kwh"],
        "netz_kwh": q["netz"]["kwh"],
        "verbrauch_kwh": verbrauch,
        "prozent": round(eigen / verbrauch * 100, 1) if verbrauch > 0 else None,
    }


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
    Angabe bleibt der Block `einheiten` leer.

    N154 — dazu die Autarkiequote (`autarkie`), die Frage, um die es auf der
    PV-Seite geht: wie viel des verbrauchten Stroms aus der eigenen Anlage kam."""
    ergebnis = strom.rechne(_eingaben(_hole_oder_neu(session, o.id, jahr),
                                      wg, buero, _stammdaten(session, o.id)))
    ergebnis["autarkie"] = _autarkie(ergebnis)
    return ergebnis


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
    Anschaffung gestellt. Anschaffung und Anteile kommen aus den Stammdaten der
    Anlage (N139) — sie hängen nicht am Jahr. Zusätzlich die Verteilung des
    kumulierten Ertrags auf die PV-Eigentümer nach ihren eigenen Tausendsteln."""
    anlage = _stammdaten(session, o.id)
    reihe = [{"jahr": sj.jahr,
              "ertrag": strom.rechne(sj)["pv"]["investitions_ertrag"]}
             for sj in session.exec(
                 select(Stromjahr).where(Stromjahr.objekt_id == o.id)
                 .order_by(Stromjahr.jahr)).all()]
    anteile = _anteile_tupel(anlage)
    a = strom.amortisation(reihe, anlage.anschaffung_eur)
    a["eigentuemer"] = strom.verteile_eigentuemer(a["kumuliert"], anteile)
    return a


# --------------------------------------------------------------------------
# N127 — der Amortisationsverlauf über die Jahre.
#
# Anders als `/pv/amortisation` (rechnet aus den Strom-Eingaben) zieht der
# Verlauf sein Geld aus der NEBENKOSTENABRECHNUNG des Objekts. Drei Quellen,
# und ausdrücklich nur echte Zahlungsflüsse — eine kalkulatorische „Ersparnis
# Zukauf" ist kein Ertrag:
#
#   1. PV-Strom, den die Mieter bezahlt haben — Kostenpositionen mit
#      `herkunft == "eigen"`.
#   2. Einspeisevergütung — Positionen einer NICHT umlagefähigen Kostenart.
#      Sie steht im Zeitraum, damit sie zeitlich richtig sitzt, wird aber nicht
#      auf die Mieter verteilt (siehe `objekte.abrechnung_endpoint`, N125).
#   3. E-Tanken — die erfassten `Tankladung`-Datensätze des Jahres.
# --------------------------------------------------------------------------

_HERKUNFT_EIGEN = "eigen"
_QUELLEN_LEER = {"pv_strom": 0.0, "einspeisung": 0.0, "tanken": 0.0}

# N200 — die Kategorien der Amortisation, unter denen Grafik, Prozent-Aufteilung
# und Ringdiagramm dasselbe benennen. Dieselben drei Quellen wie `_QUELLEN_LEER`.
_KAT_LABEL = {"pv_strom": "PV-Eigenverbrauch",
              "einspeisung": "Netz-Einspeisung",
              "tanken": "E-Tanken"}


# --------------------------------------------------------------------------
# N200 — die E-Tankstelle zahlt live auf die Amortisation ein.
#
# Bis N200 kam der E-Tanken-Ertrag aus `Tankladung.kwh × Tankladung.preis`. Der
# Handpreis ist aber seit N148 stillgelegt (die Preisbildung ist abgeleitet):
# in den echten Daten steht dort 0, und die Ladungen liegen ohnehin in der
# Wallbox, nicht als `Tankladung`-Sätze. Der Verlauf zeigte für 2025/2026
# deshalb 0, obwohl an der Station längst geladen wird.
#
# Was der PV-ANLAGE aus dem Laden zufließt, ist der **eigene** Strom (PV + Akku),
# den die Fahrer zum abgeleiteten Eigen-Satz zahlen: dieser Strom hat die Anlage
# nichts gekostet, jede Kilowattstunde davon trägt die Anschaffung ab. Der
# Netzanteil ist ein Durchlaufposten (er deckt den Zukauf) und zählt hier NICHT.
# Menge und Satz kommen aus derselben Quelle wie die Abrechnung der E-Tankstelle
# (`routers.tankstelle`): die Wallbox, ersatzweise die erfassten Ladungen.
# --------------------------------------------------------------------------

def tanken_beitrag_eur(eigen_kwh: float | None,
                       eigen_satz: float | None) -> float:
    """Was der geladene Eigenstrom (PV + Akku) zur Amortisation beiträgt: Menge
    mal abgeleitetem Eigen-Satz.

    Fehlt die Menge (die Aufteilung Netz/eigen ist unbekannt) oder der Satz
    (keine ableitbaren Stromkosten), ist der Beitrag 0 — nie eine erfundene
    Zahl. Genau dieselbe Zurückhaltung wie beim Satz selbst (N148)."""
    if not eigen_kwh or not eigen_satz:
        return 0.0
    return round(float(eigen_kwh) * float(eigen_satz), 2)


def _tanken_je_jahr(session: Session, o: Objekt) -> dict[int, dict]:
    """Der E-Tanken-Beitrag je Kalenderjahr — aus den tatsächlich geladenen
    Mengen, nicht aus einem Handpreis (N200).

    Je Jahr mit Ladung: die eigene Lademenge (PV + Akku) aus dem Verlauf der
    E-Tankstelle und der für dieses Jahr abgeleitete Eigen-Satz. Wallbox zuerst,
    ersatzweise die erfassten Ladungen — dieselbe Quelle wie die Abrechnung, mit
    denselben ehrlichen Lücken: ist die Aufteilung eines Jahres unbekannt oder
    fehlt der Satz, bleibt `eur` 0 und die Menge sagt, warum.

    Rückgabe: {Jahr: {eigen_kwh, extern_kwh, geladen_kwh, satz_eigen, satz_netz,
    eur, quelle, satz_grund}}. Leer, wenn nie geladen wurde."""
    from . import tankstelle as tk

    von, bis = tk.suchfenster()
    posten, quelle, _hinweis = tk._posten_holen(session, o, von, bis)
    out: dict[int, dict] = {}
    for jahr in tk.jahre_mit_verbrauch(posten):
        jvon, jbis = date(jahr, 1, 1), date(jahr, 12, 31)
        monate = tk.verlauf([p for p in posten
                             if p.tag and jvon <= p.tag <= jbis], jvon, jbis)
        summe = tk.verlauf_summe(monate)
        eigen_kwh = summe.get("eigen_kwh")
        extern_kwh = summe.get("extern_kwh")
        satz = tk.satz_ableiten(session, o.id, jvon, jbis, extern_kwh, eigen_kwh)
        out[jahr] = {
            "eigen_kwh": eigen_kwh,
            "extern_kwh": extern_kwh,
            "geladen_kwh": summe.get("kwh"),
            "satz_eigen": satz.eigen,
            "satz_netz": satz.netz,
            "eur": tanken_beitrag_eur(eigen_kwh, satz.eigen),
            "quelle": quelle,
            "satz_grund": satz.grund,
        }
    return out


def _kategorie_kwh(session: Session, objekt_id: int,
                   tanken: dict[int, dict]) -> dict[str, float | None]:
    """Die physische Energiemenge je Kategorie über alle Jahre — die Grundlage
    des Ringdiagramms (N200).

    PV-Eigenverbrauch ist der im Haus direkt genutzte Solar-/Akku-Strom
    (`solar_kwh + akku_kwh`), Netz-Einspeisung die ins Netz gegebene Menge
    (`einspeisung_kwh`), E-Tanken die eigene Lademenge (PV + Akku) aus der
    Station. So wird sichtbar, was der Nutzer sehen will: die Einspeisung bringt
    viele kWh, aber wenig € — Direktnutzung und E-Tanken weniger kWh, aber mehr €
    je kWh. Eine Kategorie ohne Menge ergibt `None`, keine erfundene 0."""
    solar = akku = einspeisung = 0.0
    for sj in session.exec(select(Stromjahr).where(
            Stromjahr.objekt_id == objekt_id)).all():
        solar += float(getattr(sj, "solar_kwh", 0.0) or 0.0)
        akku += float(getattr(sj, "akku_kwh", 0.0) or 0.0)
        einspeisung += float(getattr(sj, "einspeisung_kwh", 0.0) or 0.0)
    tank = round(sum(t["eigen_kwh"] for t in tanken.values()
                     if t.get("eigen_kwh")), 2)
    return {"pv_strom": round(solar + akku, 2) or None,
            "einspeisung": round(einspeisung, 2) or None,
            "tanken": tank or None}


def _kat_eur(jahre: list[dict], feld: str, vorlauf_jahr: int | None) -> float:
    """Der Amortisations-Beitrag EINER Kategorie über alle Jahre — inklusive des
    einmaligen Vorlaufs, nach genau derselben Regel wie die Tabelle (N174): ist
    der Vorlauf aufgeschlüsselt, zählt sein Anteil zur jeweiligen Kategorie;
    sonst fällt der ganze Vorlauf der PV-Strom-Spalte zu.

    So ist die Summe der drei Kategorien exakt der kumulierte Ertrag — kein
    Cent liegt neben der Kurve."""
    total = 0.0
    for z in jahre:
        w = float(z.get(feld) or 0.0)
        if z["jahr"] == vorlauf_jahr:
            teile = z.get("vorlauf_teile")
            if teile:
                w += float(teile.get(feld) or 0.0)
            elif feld == "pv_strom":
                w += float(z.get("vorlauf") or 0.0)
        total += w
    return round(total, 2)


def _kategorien(jahre: list[dict], vorlauf_jahr: int | None,
                kwh: dict[str, float | None]) -> dict:
    """N200 — die Aufteilung der Amortisation auf ihre drei Kategorien: je
    Kategorie der Beitrag in €, sein Anteil in % (woraus die Amortisation
    besteht) und die physische Energiemenge in kWh dahinter.

    `eur_pro_kwh` macht den Kern sichtbar: die Einspeisung bringt viele kWh zu
    wenigen Cent, Direktnutzung und E-Tanken weniger kWh zu einem Vielfachen je
    kWh. Der Prozentsatz ist der €-Anteil an der Amortisation, das Ringdiagramm
    zeigt die kWh — zwei Blicke auf dieselben drei Kategorien."""
    eur = {f: _kat_eur(jahre, f, vorlauf_jahr)
           for f in ("pv_strom", "einspeisung", "tanken")}
    gesamt_eur = round(sum(eur.values()), 2)
    posten = []
    for feld in ("pv_strom", "einspeisung", "tanken"):
        e, k = eur[feld], kwh.get(feld)
        posten.append({
            "feld": feld, "label": _KAT_LABEL[feld],
            "eur": e, "kwh": k,
            "prozent": round(e / gesamt_eur * 100, 1) if gesamt_eur > 0 else None,
            "eur_pro_kwh": round(e / k, 4) if k else None,
        })
    gesamt_kwh = round(sum(p["kwh"] for p in posten if p["kwh"]), 2) or None
    return {"gesamt_eur": gesamt_eur, "gesamt_kwh": gesamt_kwh, "posten": posten}


def _nicht_umlagefaehig(session: Session, objekt_id: int) -> set[str]:
    """Die Namen der nicht umlagefähigen Kostenarten eines Objekts, klein
    geschrieben — der Vergleichsschlüssel für die Positionen."""
    return {k.name.strip().lower() for k in session.exec(
        select(Kostenart).where(Kostenart.objekt_id == objekt_id)).all()
        if not k.umlagefaehig}


def _ertraege_je_jahr(session: Session, objekt_id: int,
                      tanken: dict[int, dict]) -> dict[int, dict]:
    """Die drei Ertragsquellen je Kalenderjahr einsammeln.

    Das Jahr eines Zeitraums ist sein Label-Jahr (`zeitraum_label_jahr`) —
    dasselbe Jahr, unter dem die Abrechnung überall sonst geführt wird. Offene
    Positionen (Betrag noch nicht da) bleiben außen vor, genau wie in der
    Abrechnung selbst. Eine Position zählt nur einmal: ist sie „eigen", ist sie
    PV-Strom, sonst gegebenenfalls Einspeisevergütung.

    N200 — der E-Tanken-Beitrag kommt nicht mehr aus `Tankladung.preis` (seit
    N148 stillgelegt), sondern live aus der eigenen Lademenge zum abgeleiteten
    Satz (`tanken`, vorberechnet in `_tanken_je_jahr`). Ein Jahr, in dem nur
    geladen wurde, bekommt trotzdem seine Zeile."""
    nicht_umlegen = _nicht_umlagefaehig(session, objekt_id)
    jahr_von_zeitraum = {
        z.id: zeitraum_label_jahr(z.start, z.ende) for z in session.exec(
            select(Zeitraum).where(Zeitraum.objekt_id == objekt_id)).all()}
    werte: dict[int, dict] = {j: dict(_QUELLEN_LEER)
                              for j in jahr_von_zeitraum.values()}
    if jahr_von_zeitraum:
        positionen = session.exec(select(Kostenposition).where(
            Kostenposition.zeitraum_id.in_(list(jahr_von_zeitraum)))).all()
        for p in positionen:
            if p.status != "erledigt":
                continue
            eintrag = werte[jahr_von_zeitraum[p.zeitraum_id]]
            betrag = round(float(p.betrag or 0), 2)
            if (p.herkunft or "").strip().lower() == _HERKUNFT_EIGEN:
                eintrag["pv_strom"] = round(eintrag["pv_strom"] + betrag, 2)
            elif (p.kostenart or "").strip().lower() in nicht_umlegen:
                eintrag["einspeisung"] = round(eintrag["einspeisung"] + betrag, 2)
    # N200 — der live abgeleitete E-Tanken-Beitrag. Ladungen hängen am Jahr,
    # nicht am Zeitraum — ein Jahr, in dem nur geladen wurde, bekommt trotzdem
    # eine Zeile, sonst ginge der Erlös verloren.
    for jahr, t in tanken.items():
        eintrag = werte.setdefault(jahr, dict(_QUELLEN_LEER))
        eintrag["tanken"] = round(eintrag["tanken"] + float(t.get("eur") or 0.0), 2)
    return werte


def _abrechnungsjahre(session: Session, objekt_id: int) -> list[int]:
    """Die Label-Jahre der Abrechnungszeiträume — dieselben Jahre, unter denen
    die Abrechnung überall sonst geführt wird."""
    return [zeitraum_label_jahr(z.start, z.ende) for z in session.exec(
        select(Zeitraum).where(Zeitraum.objekt_id == objekt_id)).all()]


def _vorlauf_jahr(session: Session, objekt_id: int,
                  quellen: dict[int, dict]) -> int | None:
    """N153b — das Jahr, unter dem der Vorlauf steht: das Jahr VOR dem ersten
    Abrechnungsjahr.

    Beim Nutzer beginnt die erste Abrechnung am 01.10.2024 und läuft als Jahr
    2025 — der Vorlauf gehört damit auf 2024. Abgeleitet aus den Daten, nie
    gesetzt. Gibt es noch keinen Zeitraum, tut es das erste Jahr mit Erträgen;
    gibt es gar nichts, gibt es auch keine Zeile."""
    jahre = _abrechnungsjahre(session, objekt_id) or list(quellen)
    return min(jahre) - 1 if jahre else None


def _anlage(session: Session,
            objekt_id: int) -> tuple[float, float, dict | None, tuple]:
    """Anschaffung, Vorlauf-Ertrag, dessen Herkunft und die PV-Anteile.

    N139 — alle kommen aus den Stammdaten (`PVAnlage`), nicht mehr aus dem
    Strom-Jahr: die Anlage wurde einmal gekauft, nicht jedes Jahr neu. Der
    Vorlauf ist, was die Anlage VOR der ersten Nebenkostenabrechnung schon
    abgetragen hat (N127): ein einmaliger Betrag, kein jährlicher. Woher er kam,
    steht in `teile` — oder in `None`, wenn nur der Gesamtwert gepflegt ist
    (N153, Vorrang-Regel in `_vorlauf`)."""
    a = _stammdaten(session, objekt_id)
    vorlauf, teile = _vorlauf(a)
    return a.anschaffung_eur or 0.0, vorlauf, teile, _anteile_tupel(a)


# Wie weit die Prognose höchstens rechnet. Trägt eine Anlage nur ein paar Euro
# im Jahr ab, liefe die Schleife sonst über Jahrhunderte.
_PROGNOSE_MAX_JAHRE = 60


def _prognose(jahre: list[dict], anschaffung: float) -> dict | None:
    """Wie es voraussichtlich weitergeht — linear aus dem bisherigen Schnitt.

    Erst ab **zwei** Jahren mit laufendem Ertrag: eine Prognose aus einem
    einzigen Wert wäre geraten, nicht gerechnet. Der einmalige Vorlauf zählt
    dabei nicht in den Schnitt (er wiederholt sich nicht), wohl aber im schon
    erreichten Stand.

    Rückgabe: `schnitt` (Ertrag je Jahr), `jahre` (die fortgeschriebenen Zeilen
    {jahr, summe, kumuliert, offen, ueberschuss}), `break_even_jahr` und
    `in_jahren`. `None`, wenn es (noch) nichts fortzuschreiben gibt."""
    if anschaffung <= 0 or not jahre:
        return None
    letztes = jahre[-1]
    if letztes["offen"] <= 0:
        return None                       # schon amortisiert, nichts zu raten
    laufend = [z for z in jahre if round(z["summe"] - z["vorlauf"], 2) > 0]
    if len(laufend) < 2:
        return None
    spanne = max(1, laufend[-1]["jahr"] - laufend[0]["jahr"] + 1)
    schnitt = round(sum(z["summe"] - z["vorlauf"] for z in laufend) / spanne, 2)
    if schnitt <= 0:
        return None

    reihe, kum = [], letztes["kumuliert"]
    for i in range(1, _PROGNOSE_MAX_JAHRE + 1):
        kum = round(kum + schnitt, 2)
        reihe.append({"jahr": letztes["jahr"] + i, "summe": schnitt,
                      "kumuliert": kum,
                      "offen": round(max(0.0, anschaffung - kum), 2),
                      "ueberschuss": round(max(0.0, kum - anschaffung), 2)})
        if kum >= anschaffung:
            break
    if reihe[-1]["offen"] > 0:
        return None                       # jenseits des Horizonts — lieber nichts
    return {"schnitt": schnitt, "jahre": reihe,
            "break_even_jahr": reihe[-1]["jahr"], "in_jahren": len(reihe)}


@router.get("/objekte/{slug}/pv/verlauf")
def pv_verlauf(slug: str, session: Session = Depends(get_session),
               o: Objekt = Depends(objekt_holen)) -> dict:
    """N127 — wie die Erträge die Anschaffung Jahr für Jahr auffressen.

    Die Jahre kommen aus den vorhandenen Zeiträumen des Objekts (plus Jahren
    mit Ladungen), lückenlos von der ersten bis zur letzten Zeile: ein Jahr
    ohne Erträge ist eine Zeile mit 0, keine Lücke. Die Beträge werden bei
    jedem Aufruf frisch aus den Kostenpositionen gezogen — ändert sich die
    Nebenkostenabrechnung, ändert sich der Verlauf mit.

    Rückgabe: `anschaffung`, `vorlauf`, `vorlauf_teile` (dessen Herkunft oder
    `None`, N153), `vorlauf_jahr`, `jahre` ([{jahr, vorlauf, vorlauf_teile,
    pv_strom, einspeisung, tanken, summe, kumuliert, offen, ueberschuss}]),
    `kumuliert`, `rest`, `amortisiert_prozent`, `break_even_jahr` (erreicht oder
    prognostiziert), `break_even_geschaetzt`, `break_even_in_jahren`,
    `prognose`, `eigentuemer` und `warnungen`."""
    tanken = _tanken_je_jahr(session, o)
    quellen = _ertraege_je_jahr(session, o.id, tanken)
    anschaffung, vorlauf, vorlauf_teile, anteile = _anlage(session, o.id)
    # N153b — der Vorlauf steht VOR der ersten Abrechnung, nicht darin: eine
    # eigene Zeile im Jahr davor. Vorher zählte er auf das erste erfasste Jahr
    # und vermischte sich dort mit dessen echten Erträgen — beim Nutzer stand
    # der Vorsprung aus 2023/24 im ersten Abrechnungsjahr 2025. In Summe und
    # Amortisation zählt er unverändert voll mit, er sitzt nur richtig.
    vorlauf_jahr = _vorlauf_jahr(session, o.id, quellen) if vorlauf else None
    if vorlauf_jahr is not None:
        quellen.setdefault(vorlauf_jahr, dict(_QUELLEN_LEER))
    spanne = range(min(quellen), max(quellen) + 1) if quellen else range(0)
    roh = [{"jahr": j, **quellen.get(j, _QUELLEN_LEER)} for j in spanne]
    for z in roh:
        eigenes = z["jahr"] == vorlauf_jahr
        z["vorlauf"] = round(vorlauf, 2) if eigenes else 0.0
        z["vorlauf_teile"] = vorlauf_teile if eigenes else None

    a = strom.amortisation(
        [{"jahr": z["jahr"],
          "ertrag": round(z["vorlauf"] + z["pv_strom"] + z["einspeisung"]
                          + z["tanken"], 2)}
         for z in roh], anschaffung)
    jahre = [{**z, "summe": k["ertrag"], "kumuliert": k["kumuliert"],
              "offen": round(max(0.0, a["anschaffung"] - k["kumuliert"]), 2),
              "ueberschuss": round(max(0.0, k["kumuliert"] - a["anschaffung"]), 2)}
             for z, k in zip(roh, a["reihe"])]

    erreicht = a["break_even_jahr"]
    prognose = None if erreicht else _prognose(jahre, a["anschaffung"])
    warnungen: list[str] = []
    if not a["anschaffung"]:
        warnungen.append("Anschaffungskosten der Anlage sind noch nicht "
                         "erfasst — ohne sie gibt es keinen Break-even.")
    if not jahre:
        warnungen.append("Für dieses Objekt ist noch kein Abrechnungszeitraum "
                         "angelegt.")
    elif not a["kumuliert"]:
        warnungen.append("Noch keine Erträge erfasst: PV-Strom kommt aus den "
                         "Kostenpositionen mit Herkunft „eigen“, die "
                         "Einspeisevergütung aus einer nicht umlagefähigen "
                         "Kostenart, das E-Tanken aus den Ladungen.")
    elif not erreicht and not prognose and a["anschaffung"]:
        ertragsjahre = sum(1 for z in jahre
                           if round(z["summe"] - z["vorlauf"], 2) > 0)
        warnungen.append(
            f"Bei diesem Ertrag ist die Anlage in {_PROGNOSE_MAX_JAHRE} Jahren "
            f"noch nicht abbezahlt — eine Jahreszahl wäre hier ohne Aussage."
            if ertragsjahre >= 2 else
            "Eine Prognose gibt es ab dem zweiten Abrechnungsjahr mit Ertrag — "
            "aus einem einzigen Jahr wäre sie geraten.")
    # N200 — die Aufteilung der Amortisation auf ihre drei Kategorien: € (Anteil
    # an der Amortisation) und kWh (physische Menge) je Kategorie, für die
    # Prozentzeile und das Ringdiagramm unter der Kurve.
    kategorien = _kategorien(jahre, vorlauf_jahr,
                             _kategorie_kwh(session, o.id, tanken))
    return {"anschaffung": a["anschaffung"], "vorlauf": round(vorlauf, 2),
            "vorlauf_teile": vorlauf_teile,
            "vorlauf_aufgeschluesselt": vorlauf_teile is not None,
            "vorlauf_jahr": vorlauf_jahr,
            "jahre": jahre,
            "kategorien": kategorien,
            "kumuliert": a["kumuliert"], "rest": a["rest"],
            "amortisiert_prozent": a["amortisiert_prozent"],
            "break_even_jahr": erreicht or (prognose or {}).get("break_even_jahr"),
            "break_even_geschaetzt": prognose is not None,
            "break_even_in_jahren": (prognose or {}).get("in_jahren"),
            "prognose": prognose,
            "eigentuemer": strom.verteile_eigentuemer(a["kumuliert"], anteile),
            "warnungen": warnungen}


# --------------------------------------------------------------------------
# N112 — E-Tankstelle: wer geladen hat, wie viel, und was ihm berechnet wird.
# Die Ladungen haengen am Objekt-Jahr; die Person kommt aus der vorhandenen
# Eigentuemer-Liste (dieselben Personen wie ueberall) oder als freier Name.
# --------------------------------------------------------------------------

class LadungIn(BaseModel):
    """Eine Ladung an der E-Tankstelle."""
    person_id: int | None = None
    name: str = ""
    email: str = ""
    kwh: float = 0.0
    preis: float = 0.0
    datum: date | None = None
    notiz: str = ""


def _zeige_ladung(l: Tankladung, namen: dict[int, str]) -> dict:
    """Eine Ladung als JSON — mit aufgeloestem Personennamen und Betrag."""
    return {"id": l.id, "jahr": l.jahr, "person_id": l.person_id,
            "person": namen.get(l.person_id or 0, l.name or ""),
            "email": l.email, "kwh": l.kwh, "preis": l.preis,
            "betrag": round(l.kwh * l.preis, 2),
            "datum": l.datum.isoformat() if l.datum else None, "notiz": l.notiz}


def _namen(session: Session) -> dict[int, str]:
    return {e.id: e.name for e in session.exec(select(Eigentuemer)).all()}


@router.get("/objekte/{slug}/tankstelle/{jahr}")
def ladungen(slug: str, jahr: int, session: Session = Depends(get_session),
             o: Objekt = Depends(objekt_holen)) -> dict:
    """Die Ladungen eines Objekt-Jahres samt Summen je Person."""
    liste = session.exec(
        select(Tankladung).where(Tankladung.objekt_id == o.id,
                                 Tankladung.jahr == jahr)
        .order_by(Tankladung.datum, Tankladung.id)).all()
    namen = _namen(session)
    zeilen = [_zeige_ladung(l, namen) for l in liste]
    je_person: dict[str, dict] = {}
    for z in zeilen:
        p = je_person.setdefault(z["person"] or "—",
                                 {"person": z["person"] or "—",
                                  "email": z["email"], "kwh": 0.0, "betrag": 0.0})
        p["kwh"] = round(p["kwh"] + z["kwh"], 3)
        p["betrag"] = round(p["betrag"] + z["betrag"], 2)
        if not p["email"] and z["email"]:
            p["email"] = z["email"]
    return {"ladungen": zeilen, "je_person": list(je_person.values()),
            "kwh_gesamt": round(sum(z["kwh"] for z in zeilen), 3),
            "betrag_gesamt": round(sum(z["betrag"] for z in zeilen), 2)}


@router.post("/objekte/{slug}/tankstelle/{jahr}", status_code=201)
def ladung_anlegen(slug: str, jahr: int, data: LadungIn,
                   session: Session = Depends(get_session),
                   o: Objekt = Depends(objekt_holen)) -> dict:
    """Eine Ladung erfassen. Ohne eigenen Preis gilt der Satz des Strom-Jahres."""
    werte = data.model_dump()
    if not werte.get("preis"):
        sj = _hole_oder_neu(session, o.id, jahr)
        werte["preis"] = sj.tanken_preis or 0.0
    l = Tankladung(objekt_id=o.id, jahr=jahr, **werte)
    session.add(l)
    session.commit()
    session.refresh(l)
    return _zeige_ladung(l, _namen(session))


@router.delete("/tankladungen/{lid}")
def ladung_loeschen(lid: int, session: Session = Depends(get_session)) -> dict:
    """Eine Ladung entfernen — bewusste Korrektur einer Fehleingabe."""
    l = session.get(Tankladung, lid)
    if not l:
        raise HTTPException(404, "Ladung nicht gefunden")
    session.delete(l)
    session.commit()
    return {"ok": True}


@router.get("/objekte/{slug}/pv/eigentuemer")
def pv_eigentuemer(slug: str, session: Session = Depends(get_session),
                   o: Objekt = Depends(objekt_holen)) -> dict:
    """N112 — die Personen zur Auswahl für die PV-Anteile.

    Die PV-Anlage ist ein eigenes Investment mit eigenen Tausendsteln; gewählt
    wird aber aus derselben Personenliste wie überall (`Eigentuemer`). Geliefert
    werden alle Personen, die am Objekt beteiligten zuerst und mit ihrem
    Objekt-Anteil als Vorschlag.

    N139 — die gesetzten Anteile kommen aus den Stammdaten der Anlage, nicht
    mehr aus einem Jahr; dazu ihre Summe und der Hinweis, wenn sie nicht
    1000 ‰ ergibt."""
    alle = session.exec(select(Eigentuemer).order_by(Eigentuemer.name)).all()
    am_objekt = {a.eigentuemer_id: a.promille for a in session.exec(
        select(Anteil).where(Anteil.objekt_id == o.id)).all()}
    personen = sorted(
        ({"id": e.id, "name": e.name, "email": e.email,
          "am_objekt": am_objekt.get(e.id)} for e in alle),
        key=lambda p: (p["am_objekt"] is None, p["name"]))
    gesetzt = _anteile_dict(_stammdaten(session, o.id).anteile)
    summe = round(sum(gesetzt.values()), 3)
    return {"personen": personen, "pv_anteile": gesetzt,
            "anteile_summe": summe,
            "hinweise": _anteile_hinweise(gesetzt, summe)}
