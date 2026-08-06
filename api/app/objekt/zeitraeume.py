"""Zeiträume — anlegen, verschieben, teilen, Belege abgleichen.

Auch die Turnus-Grenzen-Regel (N34: das Jahr mit den meisten Tagen) und der
automatische Wegräumer für leere Zeiträume leben hier. Diese Helfer werden
von `dokumente.py`, `strom.py`, `stromkette.py` und dem alten `objekte.py`
weiter über `.objekte` bezogen — siehe die Re-Exports am Router-Kopf.
"""
import logging
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from ..belegposten import (BelegFehler, loese as beleg_loese,
                           verbuche as beleg_verbuche)
from ..db import get_session
from ..models import (Dokument, Kostenart, Kostenposition, Objekt,
                      Vorauszahlung, Zeitraum)
from ..verteilung import positionen_neu_ableiten

router = APIRouter(tags=["objekte"])


@router.get("/zeitraeume/{zid}/positionen")
def positionen(zid: int, session: Session = Depends(get_session)) -> list[Kostenposition]:
    return session.exec(
        select(Kostenposition).where(Kostenposition.zeitraum_id == zid)).all()


def zeitraum_label_jahr(start: date, ende: date) -> int:
    """N34 — das Kalenderjahr, das die MEISTEN Tage im Zeitraum hat.

    Ein Wirtschaftsjahr Okt–Sep gehört nach dieser Regel zum Endjahr: Okt2024–
    Sep2025 hat 92 Tage in 2024, aber 273 in 2025 → 2025. Ein Kalenderjahr
    trägt sein Jahr ohnehin. Gleichstand (selten) → das spätere Jahr."""
    tage: dict[int, int] = {}
    for jahr in range(start.year, ende.year + 1):
        von = max(start, date(jahr, 1, 1))
        bis = min(ende, date(jahr, 12, 31))
        tage[jahr] = (bis - von).days + 1
    return max(tage, key=lambda j: (tage[j], j))


def _grenzen_ab_startjahr(startjahr: int, start_monat: int) -> tuple[date, date]:
    """Zwölf Monate ab `startjahr`/`start_monat`."""
    start = date(startjahr, start_monat, 1)
    ende = date(start.year + 1, start.month, 1) - timedelta(days=1)
    return start, ende


def _zeitraum_grenzen(objekt: Objekt, jahr: int) -> tuple[date, date]:
    """Start und Ende des Abrechnungsjahres `jahr` aus dem Turnus des Objekts.

    N34 — `jahr` ist das Jahr mit den MEISTEN Tagen (`zeitraum_label_jahr`), nicht
    das Startjahr. Bei Start im Oktober gehört „2025" also zu 1.10.2024–30.9.2025.
    Kalenderjahr bleibt 1.1.–31.12. Diese eine Regel gilt fürs Anlegen wie fürs
    Erkennen, damit ein vorgeschlagener Zeitraum exakt dem entspricht, der beim
    Anlegen entsteht."""
    monat = objekt.start_monat or 1
    # Für ein gegebenes Label-Jahr kommt der Zeitraum entweder aus demselben oder
    # dem vorigen Startjahr — genau der, dessen „meiste-Tage-Jahr" `jahr` ergibt.
    for startjahr in (jahr, jahr - 1):
        start, ende = _grenzen_ab_startjahr(startjahr, monat)
        if zeitraum_label_jahr(start, ende) == jahr:
            return start, ende
    return _grenzen_ab_startjahr(jahr, monat)          # Rückfall (Kalenderjahr)


def _zeitraum_jahr(objekt: Objekt, datum: date) -> int:
    """In welches Abrechnungsjahr (Label nach `zeitraum_label_jahr`) ein Datum
    fällt — der Zeitraum, dessen zwölf Monate den Tag enthalten."""
    monat = objekt.start_monat or 1
    startjahr = datum.year if datum.month >= monat else datum.year - 1
    start, ende = _grenzen_ab_startjahr(startjahr, monat)
    return zeitraum_label_jahr(start, ende)


@router.get("/objekte/{slug}/zeitraum-fuer")
def zeitraum_fuer(slug: str, datum: date,
                  session: Session = Depends(get_session)) -> dict:
    """Welcher Abrechnungszeitraum zu einem Beleg-Datum passt.

    Der Dokumenteneingang fragt hier für den erkannten Beleg-Tag: gibt es
    bereits einen Zeitraum, der ihn umfasst, wird der vorgeschlagen und
    vorausgewählt (`vorschlag: false`, mit `id`). Gibt es keinen, kommen die
    Grenzen des passenden Jahres zurück (`vorschlag: true`) — der Eingang bietet
    sie als „…anlegen" an und legt sie über `POST /zeitraeume` an, bevor der
    Beleg dort eingruppiert wird. Anlegen und Erkennen nutzen dieselbe
    Grenzen-Regel (`_zeitraum_grenzen`), damit beides deckungsgleich ist."""
    o = session.exec(select(Objekt).where(Objekt.slug == slug)).first()
    if not o:
        raise HTTPException(404, "Objekt nicht gefunden")

    bestehende = session.exec(
        select(Zeitraum).where(Zeitraum.objekt_id == o.id)).all()
    treffer = next((z for z in bestehende if z.start <= datum <= z.ende), None)
    if treffer:
        return {"vorschlag": False, "id": treffer.id,
                "label": f"{treffer.start:%d.%m.%Y} – {treffer.ende:%d.%m.%Y}",
                "start": treffer.start.isoformat(), "ende": treffer.ende.isoformat()}

    jahr = _zeitraum_jahr(o, datum)
    start, ende = _zeitraum_grenzen(o, jahr)
    return {"vorschlag": True, "id": None, "jahr": jahr,
            "label": f"{start:%d.%m.%Y} – {ende:%d.%m.%Y}",
            "start": start.isoformat(), "ende": ende.isoformat()}


class ZeitraumIn(BaseModel):
    """Ein Jahr genügt — Start und Ende ergeben sich aus dem Turnus des Objekts.
    Wer abweichende Grenzen braucht, gibt sie direkt an."""
    jahr: Optional[int] = None
    start: Optional[date] = None
    ende: Optional[date] = None
    typ: str = "regulär"


@router.post("/objekte/{slug}/zeitraeume", status_code=201)
def zeitraum_anlegen(slug: str, data: ZeitraumIn,
                     session: Session = Depends(get_session)) -> dict:
    """Legt einen weiteren Abrechnungszeitraum an — typisch ein Vorjahr.

    Die Kostenarten stehen am Objekt, nicht am Zeitraum; die Checkliste des
    neuen Zeitraums ist damit sofort vollständig. Übernommen werden zusätzlich
    die Vorauszahlungen des Vorgängers, denn die ändern sich selten."""
    o = session.exec(select(Objekt).where(Objekt.slug == slug)).first()
    if not o:
        raise HTTPException(404, "Objekt nicht gefunden")

    if data.start and data.ende:
        start, ende = data.start, data.ende
    else:
        jahr = data.jahr or (date.today().year - 1)
        start, ende = _zeitraum_grenzen(o, jahr)
    if ende <= start:
        raise HTTPException(400, "Das Ende muss nach dem Start liegen")

    bestehende = session.exec(
        select(Zeitraum).where(Zeitraum.objekt_id == o.id)).all()
    if any(z.start == start and z.ende == ende for z in bestehende):
        raise HTTPException(409, "Diesen Zeitraum gibt es bereits")

    z = Zeitraum(objekt_id=o.id, start=start, ende=ende, typ=data.typ,
                 status="in Arbeit")
    session.add(z)
    session.commit()
    session.refresh(z)

    # Vorauszahlungen vom zeitlich nächsten Vorgänger übernehmen
    vorgaenger = sorted((b for b in bestehende if b.ende <= start),
                        key=lambda b: b.ende)
    uebernommen = 0
    if vorgaenger:
        for v in session.exec(select(Vorauszahlung).where(
                Vorauszahlung.zeitraum_id == vorgaenger[-1].id)).all():
            session.add(Vorauszahlung(zeitraum_id=z.id, partei=v.partei,
                                      betrag=v.betrag))
            uebernommen += 1
        session.commit()

    arten = [k for k in session.exec(
        select(Kostenart).where(Kostenart.objekt_id == o.id)).all() if k.aktiv]
    return {"id": z.id, "label": f"{z.start:%d.%m.%Y} – {z.ende:%d.%m.%Y}",
            "kostenarten": len(arten), "vorauszahlungen": uebernommen}


def _verknuepfungen(session: Session, zid: int) -> dict[str, int]:
    """Was an einem Zeitraum hängt: Kostenpositionen, Belege, Vorauszahlungen.
    Sind alle drei null, ist der Zeitraum leer und darf verschwinden."""
    return {
        "positionen": len(session.exec(select(Kostenposition)
                          .where(Kostenposition.zeitraum_id == zid)).all()),
        "belege": len(session.exec(select(Dokument)
                          .where(Dokument.zeitraum_id == zid)).all()),
        "vorauszahlungen": len(session.exec(select(Vorauszahlung)
                          .where(Vorauszahlung.zeitraum_id == zid)).all()),
    }


def _zeitraum_leer_entfernen(session: Session, zid: int,
                             commit: bool = True) -> bool:
    """Entfernt einen Zeitraum, wenn nichts mehr an ihm hängt — der
    automatische Ersatz für einen Löschknopf. War die entfernte Position der
    letzte Inhalt, verschwindet der leere Zeitraum von selbst. Ein Zeitraum
    mit auch nur einer Verknüpfung bleibt unangetastet.

    Gibt True zurück, wenn entfernt wurde. Löscht nur additiv-sicher: ein
    leerer Zeitraum hat weder Positionen noch Belege noch Vorauszahlungen, es
    kann also nichts verwaisen. `commit=False` staged nur — für Sammel-
    Aufräumen, das am Ende einmal committet."""
    if any(_verknuepfungen(session, zid).values()):
        return False
    z = session.get(Zeitraum, zid)
    if z:
        session.delete(z)
        if commit:
            session.commit()
    return True


@router.post("/zeitraeume/aufraeumen")
def zeitraeume_aufraeumen(session: Session = Depends(get_session)) -> dict:
    """Räumt alle leeren Abrechnungszeiträume weg — objektübergreifend.

    Nach einer Bestandsrücknahme (alle Belege wieder herausgenommen) bleiben
    Zeiträume ohne jeden Inhalt zurück. Statt sie einzeln zu löschen, wischt
    dieser Aufruf sie in einem Zug. Angefasst wird nur, was komplett leer ist —
    ein Zeitraum mit Position, Beleg oder Vorauszahlung bleibt."""
    entfernt = 0
    for z in session.exec(select(Zeitraum)).all():
        if not any(_verknuepfungen(session, z.id).values()):
            session.delete(z)
            entfernt += 1
    if entfernt:
        session.commit()
    logging.info("Leere Zeiträume aufgeräumt: %d entfernt", entfernt)
    return {"entfernt": entfernt}


def _zeitraum(session: Session, zid: int) -> Zeitraum:
    z = session.get(Zeitraum, zid)
    if not z:
        raise HTTPException(404, "Zeitraum nicht gefunden")
    return z


# --------------------------------------------------------------------------
# N35 — Zeiträume umstellen: Grenzen verschieben, teilen, Belege neu zuordnen.
# Werkzeug über der Zeitraumliste; z. B. Wirtschaftsjahr (Okt–Sep) auf volle
# Kalenderjahre. Additiv, abgeschlossene Zeiträume bleiben gesperrt.
# --------------------------------------------------------------------------

def _z_label(z: Zeitraum) -> str:
    return f"{z.start:%d.%m.%Y} – {z.ende:%d.%m.%Y}"


class ZeitraumPatch(BaseModel):
    """Grenzen oder Art eines bestehenden Zeitraums ändern (N35)."""
    start: Optional[date] = None
    ende: Optional[date] = None
    typ: Optional[str] = None


@router.patch("/zeitraeume/{zid}")
def zeitraum_grenzen_aendern(zid: int, data: ZeitraumPatch,
                             session: Session = Depends(get_session)) -> dict:
    """Verschiebt/erweitert die Grenzen eines Abrechnungszeitraums (N35).

    Für die Turnus-Umstellung (Wirtschaftsjahr → Kalenderjahr): einen Zeitraum
    verlängern oder das Ende vorziehen, einen Rumpf kennzeichnen. Additiv — kein
    Beleg wird hier verschoben (das macht danach `belege-abgleichen`). Die
    abgeleiteten Gewichte offener Zeiträume werden neu berechnet, weil sich mit
    den Grenzen die Mietermonate ändern (N5). Ein abgeschlossener Zeitraum bleibt
    gesperrt — er ist ein fertiges Dokument."""
    z = _zeitraum(session, zid)
    if z.status == "abgeschlossen":
        raise HTTPException(409, "Ein abgeschlossener Zeitraum lässt sich nicht "
                                 "mehr verschieben.")
    start = data.start or z.start
    ende = data.ende or z.ende
    if ende <= start:
        raise HTTPException(400, "Das Ende muss nach dem Start liegen")
    andere = session.exec(select(Zeitraum).where(
        Zeitraum.objekt_id == z.objekt_id, Zeitraum.id != zid)).all()
    if any(a.start == start and a.ende == ende for a in andere):
        raise HTTPException(409, "Diesen Zeitraum gibt es bereits")
    z.start, z.ende = start, ende
    if data.typ:
        z.typ = data.typ
    session.add(z)
    session.commit()
    positionen_neu_ableiten(session, z.objekt_id)
    session.commit()
    return {"id": z.id, "typ": z.typ, "label": _z_label(z),
            "start": z.start.isoformat(), "ende": z.ende.isoformat()}


class TeilenIn(BaseModel):
    """Ein Zeitraum wird an diesem Datum in zwei geteilt (N35)."""
    datum: date


@router.post("/zeitraeume/{zid}/teilen", status_code=201)
def zeitraum_teilen(zid: int, data: TeilenIn,
                    session: Session = Depends(get_session)) -> dict:
    """Teilt einen Zeitraum am `datum` in [start, datum-1] und [datum, ende].

    Der alte Zeitraum wird verkürzt, ein zweiter für den Rest angelegt. Belege
    werden hier NICHT verschoben — danach `belege-abgleichen` ordnet sie nach
    Datum den beiden Hälften zu. Additiv, nichts geht verloren."""
    z = _zeitraum(session, zid)
    if z.status == "abgeschlossen":
        raise HTTPException(409, "Ein abgeschlossener Zeitraum lässt sich nicht "
                                 "teilen.")
    if not (z.start < data.datum <= z.ende):
        raise HTTPException(400, "Das Teilungsdatum muss innerhalb des Zeitraums "
                                 "liegen.")
    neu = Zeitraum(objekt_id=z.objekt_id, start=data.datum, ende=z.ende,
                   typ=z.typ, status="in Arbeit")
    z.ende = data.datum - timedelta(days=1)
    session.add(z)
    session.add(neu)
    session.commit()
    session.refresh(neu)
    positionen_neu_ableiten(session, z.objekt_id)
    session.commit()
    return {"alt": {"id": z.id, "label": _z_label(z)},
            "neu": {"id": neu.id, "label": _z_label(neu)}}


@router.post("/objekte/{slug}/zeitraeume/belege-abgleichen")
def belege_abgleichen(slug: str, vorschau: bool = True,
                      session: Session = Depends(get_session)) -> dict:
    """Ordnet die Belege eines Objekts ihren Zeiträumen übers ABRECHNUNGSJAHR
    neu zu (N35/N50).

    Nach einer Umstellung (Grenzen verschoben, Zeitraum geteilt) kann ein Beleg
    im falschen Zeitraum sitzen. Diese Funktion schiebt jeden Beleg in die
    offene Periode, deren Label-Jahr sein Abrechnungsjahr (`d.jahr`, N14) trifft
    — nicht nach rohem Belegdatum, denn NK wird oft nachträglich in Rechnung
    gestellt (Datum ≠ Jahr). So bewegt die Umstellung nur, was wirklich sein
    Jahr wechselt, und lässt Belege unangetasteter Jahre in Ruhe. Verbuchte
    Belege werden am Zielort neu eingerechnet (`loese`+`verbuche`).

    `?vorschau=true` (Vorgabe) ändert nichts, sondern meldet, was passieren
    würde: welche Belege wohin wandern und welche **Grenzfälle** Handarbeit
    brauchen — `kein_datum` (weder Jahr noch Datum am Beleg) oder `kein_zeitraum`
    (kein passendes Jahr/Fenster). Abgeschlossene Zeiträume bleiben unberührt."""
    o = session.exec(select(Objekt).where(Objekt.slug == slug)).first()
    if not o:
        raise HTTPException(404, "Objekt nicht gefunden")
    perioden = sorted(session.exec(select(Zeitraum).where(
        Zeitraum.objekt_id == o.id)).all(), key=lambda z: z.start)
    gesperrt = {z.id for z in perioden if z.status == "abgeschlossen"}
    p_nach_id = {z.id: z for z in perioden}
    offene = [z for z in perioden if z.id not in gesperrt]
    def ziel_periode(d: Dokument):
        """N50 — Zuordnung übers ABRECHNUNGSJAHR (N14, `d.jahr`): der Beleg
        gehört in die offene Periode, deren Label-Jahr sein Jahr trifft. NK wird
        oft nachträglich abgerechnet (Belegdatum ≠ Abrechnungsjahr) — nach
        Belegdatum verschöbe die Umstellung sonst Belege aus Jahren, die gar
        nicht angefasst wurden. Nur wenn am Beleg kein Jahr steht, entscheidet
        das Belegdatum."""
        if d.jahr:
            treffer = [z for z in offene
                       if zeitraum_label_jahr(z.start, z.ende) == d.jahr]
            if treffer:
                if d.belegdatum:
                    enth = [z for z in treffer
                            if z.start <= d.belegdatum <= z.ende]
                    if enth:
                        return enth[0]
                return treffer[0]
        if d.belegdatum:
            return next((z for z in offene
                         if z.start <= d.belegdatum <= z.ende), None)
        return None

    belege = session.exec(select(Dokument).where(
        Dokument.objekt_id == o.id, Dokument.zeitraum_id.is_not(None))).all()
    moves, grenzfaelle = [], []
    for d in belege:
        if d.zeitraum_id in gesperrt:
            continue
        ziel = ziel_periode(d)
        if ziel is None:
            grenzfaelle.append({
                "id": d.id, "name": d.dateiname,
                "typ": "kein_datum" if not (d.jahr or d.belegdatum)
                else "kein_zeitraum"})
            continue
        if d.zeitraum_id != ziel.id:
            moves.append({
                "id": d.id, "name": d.dateiname,
                "von": _z_label(p_nach_id[d.zeitraum_id])
                if d.zeitraum_id in p_nach_id else "—",
                "nach": _z_label(ziel), "ziel_id": ziel.id,
                "verbucht": d.position_id is not None})

    if vorschau:
        return {"vorschau": True, "wandern": len(moves), "moves": moves,
                "grenzfaelle": grenzfaelle}

    verschoben, fehler = 0, []
    for m in moves:
        d = session.get(Dokument, m["id"])
        if d is None:
            continue
        try:
            if d.position_id:
                beleg_loese(session, d)
            d.zeitraum_id = m["ziel_id"]
            session.add(d)
            if m["verbucht"] and (d.kostenart or "").strip():
                beleg_verbuche(session, d)
            verschoben += 1
        except BelegFehler as e:
            session.rollback()
            fehler.append({"id": d.id, "name": d.dateiname, "grund": str(e)})
    session.commit()
    positionen_neu_ableiten(session, o.id)
    session.commit()
    logging.info("Belege abgeglichen für %s: %d verschoben, %d Grenzfälle, "
                 "%d Fehler", slug, verschoben, len(grenzfaelle), len(fehler))
    return {"vorschau": False, "verschoben": verschoben,
            "grenzfaelle": grenzfaelle, "fehler": fehler}
