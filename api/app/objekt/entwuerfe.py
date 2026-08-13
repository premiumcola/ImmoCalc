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
from ..dokumente.zuordnung import loese_info_referenzen
from ..models import (Bewohner, Kostenposition, Kredit, Miete, Notarvertrag,
                      Versicherung, Zahlung)
# Der reguläre Löschweg steht in `routers/stammdaten.py`; Verwerfen ist
# dasselbe Löschen, nur über einen anderen Knopf. Deshalb dieselben Helfer
# statt einer zweiten, auseinanderlaufenden Kopie.
from ..routers.stammdaten import (ENTITAETEN, _AN_TYP_VON_MODELL,
                                  _anhaengsel_loeschen)
from ..verteilung import positionen_neu_ableiten

log = logging.getLogger("immocalc")
router = APIRouter(tags=["objekte"])

# Modell -> Bereichsname, unter dem `stammdaten.py` denselben Datensatz führt
# (`mieten`, `kredite`, …). Aus der dortigen Registry abgeleitet, nicht ein
# zweites Mal von Hand aufgeschrieben.
_BEREICH_VON_MODELL = {modell: bereich for bereich, modell in ENTITAETEN.items()}

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
    # N5 — ein bestätigter Miet-Entwurf ist ein reguläres Mietverhältnis: die
    # Verteilung filtert `vorlaeufig` nicht. Die gespeicherten Gewichte offener
    # Zeiträume kennen den neuen Mieter aber noch nicht — er trüge 0 % und die
    # übrigen Parteien absorbierten seinen Anteil. Also dieselbe Neuableitung
    # wie beim regulären Anlegen (`stammdaten.anlegen`).
    if isinstance(eintrag, Miete) and eintrag.objekt_id is not None:
        positionen_neu_ableiten(session, eintrag.objekt_id)
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
    # Verwerfen ist Löschen — und muss deshalb genauso vollständig aufräumen wie
    # `stammdaten.loeschen`. Ohne diese drei Schritte blieben Kinder (Bewohner
    # einer Miete, Jahresstände eines Kredits) und Info-Belege als Waisen
    # stehen: N314(d), denn SQLite vergibt die id neu und der Waise taucht beim
    # nächsten Datensatz mit fremden Zahlen wieder auf.
    bereich = _BEREICH_VON_MODELL.get(type(eintrag))
    if bereich:
        _anhaengsel_loeschen(session, bereich, eintrag_id)
    an_typ = _AN_TYP_VON_MODELL.get(type(eintrag))
    if an_typ:
        loese_info_referenzen(session, an_typ, eintrag_id)
    # N5 — vor dem Löschen merken; ein entferntes Mietverhältnis gibt Leerstand
    # zurück, die abgeleiteten Gewichte offener Zeiträume gehören neu gerechnet.
    ist_miete = isinstance(eintrag, Miete)
    objekt_id = getattr(eintrag, "objekt_id", None)
    session.delete(eintrag)
    session.commit()
    if ist_miete and objekt_id is not None:
        positionen_neu_ableiten(session, objekt_id)
    log.info("Entwurf verworfen: %s#%s (Beleg %s zurück im Prüfmodus)",
             typ, eintrag_id, quelle)
    return {"ok": True, "typ": typ.lower(), "id": eintrag_id, "verworfen": True,
            "quelle_dokument_id": quelle}
