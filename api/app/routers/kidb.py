"""N84 — Endpunkte der internen Belegdaten-Datenbank.

Vier dünne Endpunkte über `models.Belegdaten`; gerechnet und gemischt wird in
`app.kidb`:

* `POST /api/kidb/uebernehmen` — die gespeicherten KI-Auslesen der NK-Belege
  in die Wissens-Datenbank übernehmen (idempotent)
* `GET  /api/kidb`             — Liste und Volltextsuche
* `GET  /api/kidb/{id}`        — ein Eintrag inkl. `pfad` (Link zur Datei)
* `DELETE /api/kidb/{id}`      — den Eintrag entfernen; die Datei bleibt

**Es wird nie die Anthropic-API angefragt.** Die Übernahme arbeitet
ausschliesslich mit dem, was schon in der Datenbank steht (`ki_einordnung`,
`ki_felder`, `ki_immobilie`, `ki_einheit`) — kein KI-Aufruf, kein Laden einer
Datei aus der Cloud. Ausdrücklicher Nutzerwunsch: das kostet sonst Tokens.

Eigener Prefix `/api/kidb` — die Reihenfolge gegenüber dem Stammdaten-Fänger
`/objekte/{slug}/{bereich}` ist damit unkritisch; eingehängt wird trotzdem
davor (siehe `main.py`).
"""
import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from .. import kidb
from ..db import get_session
from ..deps import aktuelle_familie
from ..models import Belegdaten, Dokument, Familie, Objekt

log = logging.getLogger("immocalc")
router = APIRouter(prefix="/api/kidb", tags=["kidb"])

# Welche Belege die Übernahme anfasst. Die Nebenkosten sind der Bestand, der
# Jahr für Jahr wiederkehrt und in dem man später sucht.
STANDARD_KATEGORIE = "Nebenkosten"


# --------------------------------------------------------------------------
# Darstellung
# --------------------------------------------------------------------------

def _zeige(e: Belegdaten, objekte: dict[int, Objekt] | None = None) -> dict:
    """Ein Eintrag als JSON. `pfad` ist der Link auf die Datei in der Cloud —
    genau dafür gibt es diese Datenbank: kein lokales Duplikat, ein Verweis."""
    o = (objekte or {}).get(e.objekt_id) if e.objekt_id else None
    return {
        "id": e.id,
        "dokument_id": e.dokument_id,
        "objekt_id": e.objekt_id,
        "objekt": o.slug if o else None,
        "objekt_name": o.name if o else None,
        "jahr": e.jahr,
        "kategorie": e.kategorie,
        "kostenart": e.kostenart,
        "betrag": e.betrag,
        "belegdatum": e.belegdatum.isoformat() if e.belegdatum else None,
        "anbieter": e.anbieter,
        "zusammenfassung": e.zusammenfassung,
        "felder": e.felder or {},
        "pfad": e.pfad,
        "dateiname": e.dateiname,
        "quelle": e.quelle,
        "erfasst_am": e.erfasst_am.isoformat() if e.erfasst_am else None,
    }


def _eintrag(session: Session, eintrag_id: int) -> Belegdaten:
    e = session.get(Belegdaten, eintrag_id)
    if not e:
        raise HTTPException(404, "Belegdaten-Eintrag nicht gefunden")
    return e


def _objekt(session: Session, slug: str, familie: Familie) -> Objekt | None:
    """Das Objekt zum Slug — leerer Slug heisst „alle Objekte".

    N436 — die Suche bleibt auf die angemeldete Familie eingegrenzt; ein
    fremder Slug ist genauso ein 404 wie ein unbekannter."""
    if not slug:
        return None
    o = session.exec(select(Objekt).where(
        Objekt.slug == slug, Objekt.familie_id == familie.id)).first()
    if not o:
        raise HTTPException(404, "Objekt nicht gefunden")
    return o


def _beleg_jahr(d: Dokument) -> int | None:
    """Das Jahr eines Belegs — notfalls aus dem Belegdatum."""
    return d.jahr or (d.belegdatum.year if d.belegdatum else None)


# --------------------------------------------------------------------------
# Übernahme — aus den bereits gespeicherten KI-Daten, ohne jeden KI-Aufruf
# --------------------------------------------------------------------------

@router.post("/uebernehmen")
def uebernehmen(objekt: str = "", jahre: int = 3,
                kategorie: str = STANDARD_KATEGORIE,
                session: Session = Depends(get_session),
                familie: Familie = Depends(aktuelle_familie)) -> dict:
    """Die Belege eines Objekts in die Wissens-Datenbank übernehmen.

    Geht die Dokumente der gewählten Kategorie aus den letzten `jahre` Jahren
    durch und legt je Beleg einen `Belegdaten`-Eintrag an — **aus dem, was
    bereits gespeichert ist**. Es wird keine Datei geladen und keine KI
    gefragt.

    Wiederholbar: ein zweiter Lauf findet den Eintrag über `dokument_id`
    wieder und mischt additiv nach (`kidb.zusammenfuehren`), statt einen
    zweiten daneben zu legen. Belege ohne KI-Auslese bekommen trotzdem ihren
    Eintrag (Jahr, Kostenart, Betrag, Pfad — `quelle` „regel") und werden
    zusätzlich in `ohne_ki` gemeldet, damit man sieht, wo noch nichts steht.
    """
    o = _objekt(session, objekt, familie)
    grenze = date.today().year - max(jahre, 1) + 1

    frage = select(Dokument)
    if o:
        frage = frage.where(Dokument.objekt_id == o.id)
    if kategorie:
        frage = frage.where(Dokument.kategorie == kategorie)
    belege = [d for d in session.exec(frage).all()
              if (_beleg_jahr(d) or 0) >= grenze]

    vorhandene = {e.dokument_id: e for e in session.exec(
        select(Belegdaten).order_by(Belegdaten.id)).all() if e.dokument_id}

    angelegt = aktualisiert = 0
    ohne_ki: list[dict] = []
    for d in belege:
        if not kidb.hat_ki(d):
            ohne_ki.append({"dokument_id": d.id, "dateiname": d.dateiname,
                            "jahr": _beleg_jahr(d), "pfad": d.pfad})
        neu = kidb.aus_dokument(d)
        # Steht am Beleg kein Jahr, zählt das Belegdatum — sonst stünde der
        # Eintrag ohne Jahr in einer Datenbank, die man nach Jahren durchsieht.
        neu["jahr"] = neu["jahr"] or _beleg_jahr(d)

        e = vorhandene.get(d.id)
        if e is None:
            e = Belegdaten()
            angelegt += 1
        else:
            aktualisiert += 1
        gemischt = kidb.zusammenfuehren(
            {f: getattr(e, f) for f in kidb.FELDER}, neu)
        for feld, wert in gemischt.items():
            setattr(e, feld, wert)
        session.add(e)
        vorhandene[d.id] = e

    session.commit()
    log.info("Belegdaten übernommen: %d angelegt, %d aktualisiert, "
             "%d ohne KI-Auslese (Objekt %s, ab %d)",
             angelegt, aktualisiert, len(ohne_ki), objekt or "alle", grenze)
    return {"angelegt": angelegt, "aktualisiert": aktualisiert,
            "ohne_ki": ohne_ki, "geprueft": len(belege), "ab_jahr": grenze}


# --------------------------------------------------------------------------
# Lesen und Suchen
# --------------------------------------------------------------------------

@router.get("")
def liste(objekt: str = "", jahr: int | None = None, q: str = "",
          session: Session = Depends(get_session),
          familie: Familie = Depends(aktuelle_familie)) -> dict:
    """Die Wissens-Datenbank, gefiltert und durchsucht.

    `q` läuft über Zusammenfassung, Anbieter, Kostenart, Dateiname und alle
    Werte des KI-Rasters — gross-/kleinschreib- und umlauttolerant."""
    o = _objekt(session, objekt, familie)
    eigene = session.exec(
        select(Objekt).where(Objekt.familie_id == familie.id)).all()
    objekte = {x.id: x for x in eigene}

    frage = select(Belegdaten)
    if o:
        frage = frage.where(Belegdaten.objekt_id == o.id)
    else:
        # N436 — ohne Objektfilter zeigte diese Sicht bislang die
        # Belegdaten ALLER Familien; eingegrenzt auf die eigenen Objekte.
        frage = frage.where(Belegdaten.objekt_id.in_(list(objekte.keys())))
    if jahr is not None:
        frage = frage.where(Belegdaten.jahr == jahr)
    alle = session.exec(frage).all()
    # Neuestes zuerst, dann alphabetisch — so steht oben, was gerade zählt.
    alle = sorted(alle, key=lambda e: (-(e.jahr or 0), e.dateiname.lower()))

    treffer = kidb.suche(alle, q)
    return {
        "anzahl": len(treffer),
        "gesamt": len(alle),
        "jahre": sorted({e.jahr for e in alle if e.jahr}, reverse=True),
        "eintraege": [_zeige(e, objekte) for e in treffer],
    }


@router.get("/{eintrag_id}")
def einer(eintrag_id: int, session: Session = Depends(get_session)) -> dict:
    """Ein Eintrag inkl. `pfad` — dem Link auf die Datei in der Cloud."""
    objekte = {x.id: x for x in session.exec(select(Objekt)).all()}
    return _zeige(_eintrag(session, eintrag_id), objekte)


@router.delete("/{eintrag_id}")
def loeschen(eintrag_id: int, session: Session = Depends(get_session)) -> dict:
    """Einen Eintrag entfernen — nur den Datenbankeintrag.

    Die Datei in der Cloud gehört dem Nutzer und bleibt unangetastet; der
    Eintrag ist abgeleitet und lässt sich jederzeit neu übernehmen."""
    e = _eintrag(session, eintrag_id)
    session.delete(e)
    session.commit()
    log.info("Belegdaten-Eintrag %d entfernt (Datei bleibt)", eintrag_id)
    return {"ok": True}
