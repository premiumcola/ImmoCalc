"""CRUD für Immobilien-Informationen jenseits der Nebenkosten:
Versicherungen, Mieten, Kredite, Zahlungen.

Alle vier verhalten sich gleich, deshalb eine generische Fabrik statt
vierfach kopierter Endpunkte."""
from typing import Type

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, SQLModel, select

from ..db import get_session
from ..felder import bereinige
from ..models import Kredit, Miete, Objekt, Versicherung, Zahlung
from ..turnus import VORGABE, auswahl_fuer

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
    "einheiten": "Einheiten stehen in GET /api/objekte/{slug} unter 'einheiten'",
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


# response_model=None: der Typ steht erst zur Laufzeit fest. Ohne das wuerde
# FastAPI gegen die Basisklasse SQLModel serialisieren und alle Felder schlucken.
@router.get("/objekte/{slug}/{bereich}", response_model=None)
def liste(slug: str, bereich: str,
          session: Session = Depends(get_session)) -> list:
    modell = _modell(bereich)
    o = _objekt(session, slug)
    return session.exec(select(modell).where(modell.objekt_id == o.id)).all()


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
    session.add(eintrag)
    session.commit()
    session.refresh(eintrag)
    return {"id": eintrag.id}


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
    for k in felder:
        setattr(eintrag, k, getattr(geprueft, k))
    session.add(eintrag)
    session.commit()
    return {"ok": True}


@router.delete("/stammdaten/{bereich}/{eintrag_id}")
def loeschen(bereich: str, eintrag_id: int,
             session: Session = Depends(get_session)) -> dict:
    modell = _modell(bereich)
    eintrag = session.get(modell, eintrag_id)
    if not eintrag:
        raise HTTPException(404, "Eintrag nicht gefunden")
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
