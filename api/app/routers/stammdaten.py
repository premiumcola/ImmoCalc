"""CRUD für Immobilien-Informationen jenseits der Nebenkosten:
Versicherungen, Mieten, Kredite, Zahlungen.

Alle vier verhalten sich gleich, deshalb eine generische Fabrik statt
vierfach kopierter Endpunkte.

Zwei Dinge hängen nicht am Objekt, sondern an einem dieser Einträge und haben
deshalb eigene Pfade:
  * Jahresstände eines Kredits — /api/kredite/{id}/staende
  * Bewohner eines Mietverhältnisses — /api/mieten/{id}/bewohner
"""
from datetime import date
from typing import Type

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, SQLModel, select

from ..db import get_session
from ..felder import bereinige
from ..models import (Bewohner, Kredit, Kreditstand, Miete, Objekt,
                      Versicherung, Zahlung)
from ..turnus import VORGABE, auswahl_fuer
from ..vermoegen import kreditstand, verlauf

router = APIRouter(prefix="/api", tags=["stammdaten"])

ENTITAETEN: dict[str, Type[SQLModel]] = {
    "versicherungen": Versicherung,
    "mieten": Miete,
    "kredite": Kredit,
    "zahlungen": Zahlung,
}


def _objekt(session: Session, slug: str) -> Objekt:
    o = session.exec(select(Objekt).where(Objekt.slug == slug)).first()
    if not o:
        raise HTTPException(404, "Objekt nicht gefunden")
    return o


# Segmente, die unter /objekte/{slug}/… naheliegen, hier aber nichts zu suchen
# haben. Ohne diesen Wegweiser bekaeme der Aufrufer nur „Unbekannter Bereich"
# und suchte den Fehler bei sich.
WEGWEISER: dict[str, str] = {
    "zeitraeume": "Zeiträume stehen in GET /api/objekte/{slug} unter "
                  "'zeitraeume'; anlegen mit POST /api/objekte/{slug}/zeitraeume",
    "einheiten": "Einheiten haben eigene Endpunkte: GET/POST "
                 "/api/objekte/{slug}/einheiten, PATCH/DELETE /api/einheiten/{id}",
    "dokumente": "Dokumente eines Objekts: GET /api/dokumente/objekt/{slug}",
    "positionen": "Positionen haengen am Zeitraum: "
                  "GET /api/zeitraeume/{zid}/positionen",
}


def _modell(bereich: str) -> Type[SQLModel]:
    modell = ENTITAETEN.get(bereich)
    if modell is None:
        hinweis = WEGWEISER.get(bereich)
        raise HTTPException(404, f"Unbekannter Bereich '{bereich}' — hier gibt es "
                                 f"{', '.join(ENTITAETEN)}."
                                 + (f" {hinweis}" if hinweis else ""))
    return modell


@router.get("/turnus/{bereich}")
def turnus_auswahl(bereich: str) -> dict:
    """Zahlungsturnus-Optionen eines Bereichs — speist die Auswahlfelder."""
    _modell(bereich)                     # unbekannter Bereich -> 404
    return {"bereich": bereich, "vorgabe": VORGABE.get(bereich, "jaehrlich"),
            "optionen": auswahl_fuer(bereich)}


def _kredit_zeile(session: Session, k: Kredit) -> dict:
    """Ein Kredit mit der fortgeschriebenen Restschuld von heute.

    Das Feld `restschuld` bleibt so stehen, wie es eingetragen wurde — die
    Rechnung steht daneben. Sonst überschriebe die Fortschreibung beim
    nächsten Speichern die Eingabe des Nutzers."""
    staende = session.exec(select(Kreditstand)
                           .where(Kreditstand.kredit_id == k.id)).all()
    lage = kreditstand(k, list(staende))
    return {**k.model_dump(), "stand": lage, "staende": len(staende),
            "restschuld_aktuell": lage["restschuld"]}


def _miet_zeile(session: Session, m: Miete, heute: date) -> dict:
    """Ein Mietverhältnis mit seinen Bewohnern und seinem Zeitbezug.

    `geplant` heisst: der Mietstand gilt erst in der Zukunft — eine
    beschlossene Mieterhöhung etwa. Sie soll sichtbar sein, bevor sie
    wirksam wird, aber nicht wie der laufende Stand aussehen."""
    bewohner = session.exec(select(Bewohner)
                            .where(Bewohner.miete_id == m.id)).all()
    return {**m.model_dump(),
            "bewohner": [b.model_dump() for b in bewohner],
            "geplant": bool(m.ab_datum and m.ab_datum > heute),
            "beendet": bool(m.bis_datum and m.bis_datum < heute)}


# response_model=None: der Typ steht erst zur Laufzeit fest. Ohne das wuerde
# FastAPI gegen die Basisklasse SQLModel serialisieren und alle Felder schlucken.
@router.get("/objekte/{slug}/{bereich}", response_model=None)
def liste(slug: str, bereich: str,
          session: Session = Depends(get_session)) -> list:
    modell = _modell(bereich)
    o = _objekt(session, slug)
    zeilen = session.exec(select(modell).where(modell.objekt_id == o.id)).all()
    if bereich == "kredite":
        return [_kredit_zeile(session, k) for k in zeilen]
    if bereich == "mieten":
        heute = date.today()
        return [_miet_zeile(session, m, heute) for m in zeilen]
    return zeilen


@router.post("/objekte/{slug}/{bereich}", status_code=201)
def anlegen(slug: str, bereich: str, data: dict,
            session: Session = Depends(get_session)) -> dict:
    modell = _modell(bereich)
    o = _objekt(session, slug)
    # model_validate statt modell(**data): nur so werden Datumsstrings aus JSON
    # zu echten date-Objekten konvertiert, die SQLite akzeptiert.
    # bereinige davor: ein im Formular leer gelassenes Betragsfeld kommt als
    # null an und liesse sonst das ganze Anlegen scheitern — samt Mieter,
    # Kaltmiete und Anschrift, die daneben schon eingetragen waren.
    eintrag = modell.model_validate({**bereinige(modell, data), "objekt_id": o.id})
    if isinstance(eintrag, Miete):
        _pruefe_mietstand(session, o.id, eintrag)
    session.add(eintrag)
    session.commit()
    session.refresh(eintrag)
    return {"id": eintrag.id}


def _tag(d: date | None) -> str:
    """Ein Datum, wie es in einem Satz steht — ein offenes Ende bleibt offen."""
    return f"{d:%d.%m.%Y}" if d else "offen"


def _ueberschneidung(a: Miete, b: Miete) -> tuple[date, date | None] | None:
    """Die Zeitspanne, in der zwei Mietverhältnisse gleichzeitig laufen.

    Ein offenes Ende (`bis_datum is None`) reicht bis auf Weiteres. Endet das
    eine am 30.06. und beginnt das andere am 01.07., berühren sie sich nicht —
    ein lückenloser Mieterwechsel ist keine Doppelbelegung."""
    beginn = max(a.ab_datum, b.ab_datum)
    enden = [d for d in (a.bis_datum, b.bis_datum) if d is not None]
    ende = min(enden) if enden else None
    if ende is not None and ende < beginn:
        return None
    return beginn, ende


def _pruefe_mietstand(session: Session, objekt_id: int, neu: Miete,
                      ausser: int | None = None) -> None:
    """Verhindert zwei gleichzeitige Mietstände in derselben Einheit.

    Zwei Fälle, ein Prüfweg — beide enden damit, dass die Abrechnung mit dem
    falschen Stand rechnet:

    * **Dieselbe Partei** bekommt keinen zweiten offenen Stand ab demselben
      Tag. Eine geplante Erhöhung liess sich sonst mehrfach anlegen; im Test
      entstanden vier Stände derselben Partei ab demselben Tag, alle mit dem
      Vermerk „geplant". Welcher gilt, entschied die Reihenfolge in der
      Datenbank. Eine echte Staffel mit späterem Wirkungstag bleibt erlaubt.
    * **Verschiedene Parteien** bewohnen dieselbe Einheit nicht gleichzeitig
      (CXLIII). Der Hinweis nennt die Überschneidung, damit klar ist, welches
      Enddatum fehlt. Der lückenlose Wechsel — der alte endet am 30.06., der
      neue beginnt am 01.07. — bleibt ausdrücklich erlaubt.

    `ausser` ist die eigene id beim Ändern: ein bearbeiteter Stand ist kein
    zweiter. Die Staffelregel greift dann nicht — sonst liesse sich ein
    laufender Stand nicht mehr anfassen, sobald für dieselbe Partei eine
    Erhöhung geplant ist.
    """
    if not neu.ab_datum:
        return
    vorhanden = session.exec(
        select(Miete).where(Miete.objekt_id == objekt_id,
                            Miete.einheit == neu.einheit)).all()
    for m in vorhanden:
        if ausser is not None and m.id == ausser:
            continue
        if neu.partei and m.partei == neu.partei:
            if ausser is not None:
                continue
            laeuft_noch = m.bis_datum is None or m.bis_datum >= neu.ab_datum
            if laeuft_noch and m.ab_datum and m.ab_datum >= neu.ab_datum:
                raise HTTPException(
                    409, f"Für {neu.partei} gibt es ab dem "
                         f"{m.ab_datum:%d.%m.%Y} bereits einen Mietstand. "
                         f"Ändere ihn, statt einen zweiten daneben zu stellen.")
            continue
        # Ohne benannte Einheit ist nicht zu erkennen, ob zwei Mietverhältnisse
        # dieselbe Wohnung meinen oder zwei verschiedene — dann lieber nichts
        # behaupten. Die Oberfläche lässt die Einheit antippen, sobald es
        # welche gibt; nur Bestandsdaten kommen noch ohne.
        if not neu.einheit.strip() or not neu.partei or not m.partei:
            continue
        spanne = _ueberschneidung(m, neu)
        if spanne:
            von, bis = spanne
            raise HTTPException(
                409, f"„{neu.einheit}“ ist schon an {m.partei} vermietet — "
                     f"Überschneidung {_tag(von)} bis {_tag(bis)}. Beende das "
                     f"bisherige Mietverhältnis am Tag davor.")


@router.patch("/stammdaten/{bereich}/{eintrag_id}")
def aendern(bereich: str, eintrag_id: int, data: dict,
            session: Session = Depends(get_session)) -> dict:
    modell = _modell(bereich)
    eintrag = session.get(modell, eintrag_id)
    if not eintrag:
        raise HTTPException(404, "Eintrag nicht gefunden")
    felder = bereinige(modell, {k: v for k, v in data.items()
                                if k not in ("id", "objekt_id")
                                and hasattr(eintrag, k)})
    geprueft = modell.model_validate({**eintrag.model_dump(), **felder})
    # Auch beim Ändern: eine Einheit umzuhängen oder ein Enddatum zu entfernen
    # kann dieselbe Doppelbelegung erzeugen wie ein neuer Eintrag.
    if isinstance(eintrag, Miete):
        _pruefe_mietstand(session, eintrag.objekt_id, geprueft, ausser=eintrag_id)
    for k in felder:
        setattr(eintrag, k, getattr(geprueft, k))
    session.add(eintrag)
    session.commit()
    return {"ok": True}


def _anhaengsel_loeschen(session: Session, bereich: str, eintrag_id: int) -> None:
    """Was an einem Eintrag hängt, geht mit ihm.

    Ohne das bliebe nach dem Löschen eines Kredits sein Jahresstand als
    Waise stehen und tauchte beim nächsten Kredit mit derselben id wieder
    auf — mit fremden Zahlen."""
    kinder = {"kredite": (Kreditstand, Kreditstand.kredit_id),
              "mieten": (Bewohner, Bewohner.miete_id)}.get(bereich)
    if not kinder:
        return
    modell, verweis = kinder
    for kind in session.exec(select(modell).where(verweis == eintrag_id)).all():
        session.delete(kind)


@router.delete("/stammdaten/{bereich}/{eintrag_id}")
def loeschen(bereich: str, eintrag_id: int,
             session: Session = Depends(get_session)) -> dict:
    modell = _modell(bereich)
    eintrag = session.get(modell, eintrag_id)
    if not eintrag:
        raise HTTPException(404, "Eintrag nicht gefunden")
    _anhaengsel_loeschen(session, bereich, eintrag_id)
    session.delete(eintrag)
    session.commit()
    return {"ok": True}


# --------------------------------------------------------------------------
# Jahresstände eines Kredits — wie Zählerstände
# --------------------------------------------------------------------------

class StandIn(BaseModel):
    jahr: int
    restschuld: float
    notiz: str = ""


def _kredit(session: Session, kid: int) -> Kredit:
    k = session.get(Kredit, kid)
    if not k:
        raise HTTPException(404, "Kredit nicht gefunden")
    return k


def _staende(session: Session, kid: int) -> list[Kreditstand]:
    return list(session.exec(select(Kreditstand)
                             .where(Kreditstand.kredit_id == kid)
                             .order_by(Kreditstand.jahr)).all())


@router.get("/kredite/{kid}/staende", response_model=None)
def staende(kid: int, session: Session = Depends(get_session)) -> dict:
    """Eingetragene Jahresstände, die Restschuld von heute und der Verlauf.

    Der Verlauf zeigt für jedes Jahr, ob der Wert eingetragen oder aus Rate
    und Zinssatz fortgeschrieben ist."""
    k = _kredit(session, kid)
    reihe = _staende(session, kid)
    return {"kredit_id": kid, "bezeichnung": k.bezeichnung,
            "staende": [s.model_dump() for s in reihe],
            "aktuell": kreditstand(k, reihe),
            "verlauf": verlauf(k, reihe)}


@router.post("/kredite/{kid}/staende", status_code=201)
def stand_setzen(kid: int, data: StandIn,
                 session: Session = Depends(get_session)) -> dict:
    """Trägt den Stand zum 31.12. eines Jahres ein.

    Ein Stand je Jahr: ein zweiter Eintrag für dasselbe Jahr korrigiert den
    vorhandenen, statt sich danebenzustellen."""
    _kredit(session, kid)
    if not 1900 <= data.jahr <= date.today().year + 50:
        raise HTTPException(400, "Das Jahr liegt ausserhalb des Möglichen")
    if data.restschuld < 0:
        raise HTTPException(400, "Eine Restschuld ist nie negativ")

    eintrag = session.exec(
        select(Kreditstand).where(Kreditstand.kredit_id == kid,
                                  Kreditstand.jahr == data.jahr)).first()
    if eintrag is None:
        eintrag = Kreditstand(kredit_id=kid, jahr=data.jahr)
    eintrag.restschuld = float(data.restschuld)
    eintrag.notiz = data.notiz
    session.add(eintrag)
    session.commit()
    session.refresh(eintrag)
    return {"id": eintrag.id, "jahr": eintrag.jahr,
            "restschuld": eintrag.restschuld}


@router.delete("/kreditstaende/{sid}")
def stand_loeschen(sid: int, session: Session = Depends(get_session)) -> dict:
    eintrag = session.get(Kreditstand, sid)
    if not eintrag:
        raise HTTPException(404, "Jahresstand nicht gefunden")
    session.delete(eintrag)
    session.commit()
    return {"ok": True}


# --------------------------------------------------------------------------
# Bewohner eines Mietverhältnisses
# --------------------------------------------------------------------------

class BewohnerIn(BaseModel):
    name: str = ""
    email: str = ""
    telefon: str = ""
    rolle: str = ""
    abrechnung: bool = True
    notiz: str = ""


def _miete(session: Session, mid: int) -> Miete:
    m = session.get(Miete, mid)
    if not m:
        raise HTTPException(404, "Mietverhältnis nicht gefunden")
    return m


@router.get("/mieten/{mid}/bewohner", response_model=None)
def bewohner_liste(mid: int, session: Session = Depends(get_session)) -> list:
    """Alle Bewohner eines Mietverhältnisses mit ihren eigenen Kontakten."""
    _miete(session, mid)
    return list(session.exec(select(Bewohner)
                             .where(Bewohner.miete_id == mid)).all())


@router.post("/mieten/{mid}/bewohner", status_code=201)
def bewohner_anlegen(mid: int, data: BewohnerIn,
                     session: Session = Depends(get_session)) -> dict:
    _miete(session, mid)
    if not (data.name or data.email or data.telefon).strip():
        raise HTTPException(400, "Ein Bewohner braucht Name, Mail oder Nummer")
    eintrag = Bewohner.model_validate({**data.model_dump(), "miete_id": mid})
    session.add(eintrag)
    session.commit()
    session.refresh(eintrag)
    return {"id": eintrag.id}


@router.patch("/bewohner/{bid}")
def bewohner_aendern(bid: int, data: dict,
                     session: Session = Depends(get_session)) -> dict:
    eintrag = session.get(Bewohner, bid)
    if not eintrag:
        raise HTTPException(404, "Bewohner nicht gefunden")
    felder = bereinige(Bewohner, {k: v for k, v in data.items()
                                  if k not in ("id", "miete_id")
                                  and hasattr(eintrag, k)})
    geprueft = Bewohner.model_validate({**eintrag.model_dump(), **felder})
    for k in felder:
        setattr(eintrag, k, getattr(geprueft, k))
    session.add(eintrag)
    session.commit()
    return {"ok": True}


@router.delete("/bewohner/{bid}")
def bewohner_loeschen(bid: int, session: Session = Depends(get_session)) -> dict:
    eintrag = session.get(Bewohner, bid)
    if not eintrag:
        raise HTTPException(404, "Bewohner nicht gefunden")
    session.delete(eintrag)
    session.commit()
    return {"ok": True}


def _altpfad(bereich: str) -> None:
    """Alter Pfad ohne Praefix — /api/mieten/7 statt /api/stammdaten/mieten/7.

    Frueher stand hier ein Fänger `/{bereich}/{eintrag_id}` direkt unter /api.
    Der verschluckte jeden zweisegmentigen Pfad (PATCH /api/dokumente/5 ->
    „Unbekannter Bereich"). Deshalb wird der alte Weg jetzt nur noch fuer die
    vier echten Bereiche einzeln registriert: eine Seite, die noch im Browser
    steht, funktioniert weiter, alles andere faellt nicht mehr hinein.

    Diese vier Routen koennen entfallen, sobald niemand mehr eine alte Seite
    offen hat — die Oberflaeche ruft nur noch /api/stammdaten/… auf.
    """
    @router.patch(f"/{bereich}/{{eintrag_id}}", include_in_schema=False)
    def alt_aendern(eintrag_id: int, data: dict,
                    session: Session = Depends(get_session)) -> dict:
        return aendern(bereich, eintrag_id, data, session)

    @router.delete(f"/{bereich}/{{eintrag_id}}", include_in_schema=False)
    def alt_loeschen(eintrag_id: int,
                     session: Session = Depends(get_session)) -> dict:
        return loeschen(bereich, eintrag_id, session)


for _bereich in ENTITAETEN:
    _altpfad(_bereich)
