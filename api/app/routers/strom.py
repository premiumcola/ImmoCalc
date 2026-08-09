"""N83 — Strom-/PV-Endpunkte: Eingaben je Objekt/Jahr lesen/speichern und das
Engine-Ergebnis (Kosten je Verbrauchsgruppe, PV-Ertrag je Eigentümer) abrufen.

Die Rechenlogik lebt in der Engine (`app.strom`); die PV-Fachlogik seit N216
im Paket :mod:`app.pv`. Dieser Router bleibt schmal: Routen, Pydantic-Modelle
und dünne Orchestrierung. Externe Aufrufer und Tests, die weiterhin ``from
app.routers import strom as rs`` schreiben und ``rs.<name>`` benutzen (z. B.
``rs.tanken_beitrag_eur``, ``rs._kat_eur``, ``rs._kategorien``,
``rs._kategorie_kwh``, ``rs._HAT_SPALTE``), funktionieren durch die Re-Exports
am Router-Kopf unverändert weiter.

Routen-Reihenfolge: `/objekte/{slug}/strom/…` steht vor dem Stammdaten-Fänger
`/objekte/{slug}/{bereich}` — der Router wird in `main.py` entsprechend früh
eingehängt (analog zu `zaehler`/`heizoel`/`waerme`).

N139 — was zur Anlage gehört und nicht zum Jahr (Anschaffung, bereits
Abgetragenes, Leistung, Eigentümer-Anteile), steht in `PVAnlage` und wird über
`…/pv/stammdaten` gepflegt.

N89 — welche Einheiten zu welcher Verbrauchsgruppe gehören, kommt entweder als
Abfrageparameter (`?wg=EG,1.OG&buero=Studio`) oder aus dem gespeicherten Feld
`Stromjahr.gruppen_einheiten` (JSON {Gruppe: "A,B"}), sobald es das gibt; der
Parameter hat Vorrang. Fehlt beides, bleibt die Rechnung bei den zwei Gruppen.
"""
import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from .. import strom
from ..db import get_session
from ..deps import objekt_holen
from ..mailversand import MailFehler
from ..models import Eigentuemer, Objekt, Stromjahr, Tankladung
from .mail import zugang
# ------------------------------------------------------------------
# Re-Exports der bewegten PV-Fachlogik (N216) — halten Alt-Aufrufer und
# Test-Monkeypatches lauffähig, ohne dass sich Signaturen ändern.
# ------------------------------------------------------------------
from ..pv.amortisation import (_PROGNOSE_MAX_JAHRE, _anlage,  # noqa: F401
                               _prognose, verlauf_daten)
from ..pv import versand as pv_versand
from ..pv.eigentuemer import eigentuemer_daten, jahres_verteilung
from ..pv.ertrag import (_HERKUNFT_EIGEN, _KAT_LABEL,  # noqa: F401
                         _QUELLEN_LEER, _abrechnungsjahre, _ertraege_je_jahr,
                         _kat_beitrag, _kat_eur, _kategorie_kwh, _kategorien,
                         _nicht_umlagefaehig, _vorlauf_jahr)
from ..pv.jahre import (_FELDER, _HAT_SPALTE,  # noqa: F401
                        _ZUORDNUNG_SPALTE, StromIn, _eingaben,
                        _gespeicherte_zuordnung, _hole_oder_neu,
                        _merke_zuordnung, _zeige)
from ..pv.stammdaten import (_PROMILLE_TOLERANZ,  # noqa: F401
                             _STAMM_AUS_JAHR, _VOLLE_PROMILLE,
                             _VORLAUF_QUELLEN, StammdatenIn, _anteile_dict,
                             _anteile_hinweise, _anteile_tupel,
                             _erster_abrechnungsstart, _promille_text,
                             _stammdaten, _uebernahme_aus_jahren, _vorlauf,
                             _zeige_stammdaten)
from ..pv.tanken_bridge import _tanken_je_jahr, tanken_beitrag_eur  # noqa: F401

log = logging.getLogger("immocalc")
router = APIRouter(prefix="/api", tags=["strom"])


# ==========================================================================
# PV-Stammdaten — jahresunabhängig (N139)
# ==========================================================================

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


# ==========================================================================
# Strom-Jahr — Eingaben lesen/speichern
# ==========================================================================

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


# ==========================================================================
# Ergebnis der Engine — Kosten je Gruppe/Einheit, PV-Ertrag, Autarkie, NK
# ==========================================================================

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


# ==========================================================================
# PV-Amortisation — aus den Strom-Eingaben (N87)
# ==========================================================================

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


# ==========================================================================
# PV-Verlauf über alle Jahre — aus der Nebenkostenabrechnung (N127/N200/N204)
# ==========================================================================

@router.get("/objekte/{slug}/pv/verlauf")
def pv_verlauf(slug: str, session: Session = Depends(get_session),
               o: Objekt = Depends(objekt_holen)) -> dict:
    """N127 — der Verlauf über alle Jahre (siehe :func:`app.pv.amortisation.verlauf_daten`)."""
    return verlauf_daten(session, o)


# ==========================================================================
# E-Tankstelle — Ladungen je Objekt-Jahr (N112)
# --------------------------------------------------------------------------
# Die Ladungen haengen am Objekt-Jahr; die Person kommt aus der vorhandenen
# Eigentuemer-Liste (dieselben Personen wie ueberall) oder als freier Name.
# ==========================================================================

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
    """N112 — die Personen zur Auswahl für die PV-Anteile (siehe
    :func:`app.pv.eigentuemer.eigentuemer_daten`)."""
    return eigentuemer_daten(session, o)


# ==========================================================================
# N308 — die jährliche PV-Eigentümer-Abrechnung (statt eines nur kumulierten
# Standes) und ihr Versand, nach demselben Muster wie die E-Tankstelle
# (Rückfrage vor dem Senden, Versendet-Marker gegen Dopplung — hier ohne PDF,
# da es sich um ein Informationsschreiben unter Mit-Eigentümern handelt, nicht
# um eine Rechnung).
# ==========================================================================

@router.get("/objekte/{slug}/pv/jahresabrechnung")
def pv_jahresabrechnung(slug: str, jahr: int = Query(default=0),
                        session: Session = Depends(get_session),
                        o: Objekt = Depends(objekt_holen)) -> dict:
    """Was die Anlage in EINEM Jahr abgetragen hat, verteilt auf die
    Eigentümer nach ihren PV-‰ (siehe :func:`app.pv.eigentuemer.jahres_verteilung`),
    dazu je Eigentümer, ob er die Abrechnung für dieses Jahr schon erhalten hat."""
    d = jahres_verteilung(session, o, jahr or date.today().year)
    versendet = pv_versand.versendet_marker(session, slug, d["jahr"])
    for e in d["eigentuemer"]:
        e["versendet"] = e["name"] in versendet
    return d


class PvVersandIn(BaseModel):
    jahr: int
    name: str
    an: str = ""                  # abweichende Adresse, sonst die hinterlegte


@router.post("/objekte/{slug}/pv/jahresabrechnung/versand")
def pv_jahresabrechnung_versenden(slug: str, data: PvVersandIn,
                                  session: Session = Depends(get_session),
                                  o: Objekt = Depends(objekt_holen)) -> dict:
    """Die Jahresabrechnung EINES PV-Eigentümers per Mail schicken — über das
    Postfach des Nutzers, wie bei der E-Tankstelle. Kein Versand ohne Betrag,
    ohne Adresse oder für ein bereits verschicktes Jahr."""
    d = jahres_verteilung(session, o, data.jahr)
    eintrag = next((e for e in d["eigentuemer"] if e["name"] == data.name), None)
    if eintrag is None:
        raise HTTPException(400, d["hinweis"] or
                            f"„{data.name}“ hält für {data.jahr} keinen "
                            "PV-Anteil.")
    adresse = (data.an or eintrag["email"] or "").strip()
    if not adresse:
        raise HTTPException(400, f"Für {eintrag['name']} ist keine "
                                 "E-Mail-Adresse hinterlegt.")
    if not (eintrag["betrag"] and eintrag["betrag"] > 0):
        raise HTTPException(400, f"Für {data.jahr} ist kein Ertrag zu "
                                 "verteilen.")
    if pv_versand.ist_versendet(session, slug, data.jahr, data.name):
        raise HTTPException(400, f"{eintrag['name']} hat die Abrechnung "
                                 f"{data.jahr} bereits erhalten — kein "
                                 "erneuter Versand.")
    betreff = f"PV-Anlage {o.name} — Jahresabrechnung {data.jahr}"
    text = pv_versand.abrechnungstext(o.name, data.jahr, eintrag, d["ertrag"])
    try:
        zugang(session).sende(adresse, betreff, text)
    except MailFehler as fehler:
        raise HTTPException(400, str(fehler)) from fehler
    pv_versand.versendet_merken(session, slug, data.jahr, data.name)
    session.commit()
    log.info("PV-Eigentümer %s: Jahresabrechnung %d an %s versendet",
             slug, data.jahr, adresse)
    return {"ok": True, "an": adresse, "betrag": eintrag["betrag"],
            "jahr": data.jahr}
