"""Orange Entwürfe (vorläufige Datensätze aus dem Belegscan) bestätigen/verwerfen.

Ein aus einem Beleg vorläufig angelegter Datensatz (`vorlaeufig=True`) ist
orange — der Nutzer entscheidet, ob er stimmt. „Bestätigen" macht ihn zum
regulären Datensatz; „Verwerfen" löscht ihn wieder, aber nur solange er
vorläufig ist — ein bestätigter Datensatz wird hier nie gelöscht. Das
Quell-Dokument bleibt in beiden Fällen unangetastet: nach dem Verwerfen steht
der Beleg wieder im Prüfmodus und kann neu zugeordnet werden.

Die Registry `_ENTWURF_MODELLE` wird von `dokumente.py` mitgenutzt (zirkelfrei
per Laufzeit-Import) — eine Wahrheit, welche Modelle Entwürfe sind.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from ..db import get_session
from ..models import (Bewohner, Kostenposition, Kredit, Miete, Notarvertrag,
                      Versicherung, Zahlung)

log = logging.getLogger("immocalc")
router = APIRouter(tags=["objekte"])

_ENTWURF_MODELLE = {
    "kostenposition": Kostenposition,
    "miete": Miete,
    "bewohner": Bewohner,
    "versicherung": Versicherung,
    "kredit": Kredit,
    "notarvertrag": Notarvertrag,
    "zahlung": Zahlung,
}


def _entwurf(session: Session, typ: str, eintrag_id: int):
    """Der vorläufige Datensatz — mit sauberem 404 statt eines Fehlerkaskade."""
    modell = _ENTWURF_MODELLE.get((typ or "").strip().lower())
    if modell is None:
        raise HTTPException(404, f"Unbekannter Entwurfstyp „{typ}“")
    eintrag = session.get(modell, eintrag_id)
    if not eintrag:
        raise HTTPException(404, "Entwurf nicht gefunden")
    return eintrag


@router.post("/entwuerfe/{typ}/{eintrag_id}/bestaetigen")
def entwurf_bestaetigen(typ: str, eintrag_id: int,
                        session: Session = Depends(get_session)) -> dict:
    """Macht aus einem vorläufigen (orange) Datensatz einen regulären.

    Setzt nur `vorlaeufig=False` — alle übrigen Werte bleiben, wie der Beleg sie
    ergab. Ein bereits bestätigter Datensatz bleibt einfach bestätigt."""
    eintrag = _entwurf(session, typ, eintrag_id)
    eintrag.vorlaeufig = False
    session.add(eintrag)
    session.commit()
    log.info("Entwurf bestätigt: %s#%s", typ, eintrag_id)
    return {"ok": True, "typ": typ.lower(), "id": eintrag_id, "vorlaeufig": False}


@router.post("/entwuerfe/{typ}/{eintrag_id}/verwerfen")
def entwurf_verwerfen(typ: str, eintrag_id: int,
                      session: Session = Depends(get_session)) -> dict:
    """Löscht einen vorläufigen (orange) Datensatz — nur, wenn er vorläufig ist.

    Ein bestätigter Datensatz wird nie gelöscht (409). Das Quell-Dokument bleibt
    bestehen und geht damit „zurück in den Prüfmodus"."""
    eintrag = _entwurf(session, typ, eintrag_id)
    if not eintrag.vorlaeufig:
        raise HTTPException(409, "Dieser Datensatz ist bereits bestätigt und "
                                 "wird nicht gelöscht.")
    quelle = eintrag.quelle_dokument_id
    session.delete(eintrag)
    session.commit()
    log.info("Entwurf verworfen: %s#%s (Beleg %s zurück im Prüfmodus)",
             typ, eintrag_id, quelle)
    return {"ok": True, "typ": typ.lower(), "id": eintrag_id, "verworfen": True,
            "quelle_dokument_id": quelle}
