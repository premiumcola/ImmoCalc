"""Kostenart-Katalog: lesen, anlegen, umbenennen, umlagefähig/aktiv/optional
setzen.

Ein Namenswechsel zieht die Positionen und Belege mit, damit die Historie nicht
ins Leere zeigt (CXC). Gelöscht wird nichts — der Katalog kennt dafür
`aktiv=False`.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from ..db import get_session
from ..felder import bereinige
from ..models import Dokument, Kostenart, Kostenposition, Objekt, Zeitraum

router = APIRouter(tags=["objekte"])


@router.get("/objekte/{slug}/kostenarten")
def kostenarten(slug: str, session: Session = Depends(get_session)) -> list[Kostenart]:
    o = session.exec(select(Objekt).where(Objekt.slug == slug)).first()
    if not o:
        raise HTTPException(404, "Objekt nicht gefunden")
    return session.exec(select(Kostenart).where(Kostenart.objekt_id == o.id)).all()


class KostenartNeu(BaseModel):
    name: str
    umlagefaehig: bool = True
    s35: bool = False
    optional: bool = False


@router.post("/objekte/{slug}/kostenarten", status_code=201)
def kostenart_anlegen(slug: str, data: KostenartNeu,
                      session: Session = Depends(get_session)) -> dict:
    """N408 — bisher entstand eine neue Kostenart nur beiläufig: beim Anlegen
    des Objekts, oder als Nebeneffekt, wenn eine bestehende Position auf
    einen noch unbekannten Namen umgehängt wird (`kostenart_aendern`). Eine
    Kostenart, die noch KEINE Position trägt, ließ sich am Bestandsobjekt gar
    nicht anlegen — genau der Fall bei einer neuen, noch nie erfassten
    Kostenart wie „Zählermiete"."""
    o = session.exec(select(Objekt).where(Objekt.slug == slug)).first()
    if not o:
        raise HTTPException(404, "Objekt nicht gefunden")
    name = data.name.strip()
    if not name:
        raise HTTPException(400, "Die Kostenart braucht einen Namen")
    doppelt = session.exec(select(Kostenart).where(
        Kostenart.objekt_id == o.id, Kostenart.name == name)).first()
    if doppelt:
        raise HTTPException(409, f"„{name}“ gibt es an dieser Immobilie schon")
    k = Kostenart(objekt_id=o.id, name=name, umlagefaehig=data.umlagefaehig,
                 s35=data.s35, optional=data.optional)
    session.add(k)
    session.commit()
    session.refresh(k)
    return {"id": k.id, "name": k.name, "umlagefaehig": k.umlagefaehig,
            "s35": k.s35, "optional": k.optional}


def _positionen_mit_art(session: Session, objekt_id: int,
                        name: str) -> list[Kostenposition]:
    """Alle Kostenpositionen dieser Immobilie, die auf diesen Namen lauten —
    über alle Abrechnungszeiträume. `Kostenposition.kostenart` ist Freitext und
    kein Fremdschlüssel: eine Position kann diesen Namen tragen, ohne dass es im
    Katalog eine gleichnamige Kostenart gibt (aus einem Beleg entstanden)."""
    zids = [z.id for z in session.exec(
        select(Zeitraum).where(Zeitraum.objekt_id == objekt_id)).all()]
    if not zids:
        return []
    return list(session.exec(select(Kostenposition).where(
        Kostenposition.zeitraum_id.in_(zids),
        Kostenposition.kostenart == name)).all())


@router.patch("/kostenarten/{kid}")
def kostenart_aendern(kid: int, data: dict,
                      session: Session = Depends(get_session)) -> dict:
    """Ändert eine Kostenart — und zieht einen neuen Namen in den Positionen
    nach.

    Zwei Dinge hängen daran, die ohne diesen Weg nicht zu erreichen waren:

    * **umlagefähig** (CLX) entscheidet, ob eine Kostenart in der
      Mieterabrechnung landet oder beim Eigentümer bleibt. Das Feld stand im
      Modell, war aber nirgends änderbar — damit galt faktisch alles als
      umlagefähig und die ganze Trennung war eine Behauptung.
    * **Der Name** (CXC) verbindet `Kostenposition.kostenart` mit dem Katalog.
      Er ist Freitext, kein Fremdschlüssel; wird er nur hier geändert, zeigen
      die Positionen auf einen Namen, den es nicht mehr gibt. Deshalb wandern
      sie mit — so wie `Miete.einheit` beim Umbenennen einer Einheit.

    Gelöscht wird eine Kostenart nicht: der Katalog kennt dafür `aktiv=False`.
    Eine gelöschte Art nähme die Geschichte ihrer Positionen mit.
    """
    k = session.get(Kostenart, kid)
    if not k:
        raise HTTPException(404, "Kostenart nicht gefunden")
    erlaubt = {"name", "aktiv", "optional", "umlagefaehig", "s35", "beleg_monat",
               "erinnerung_tage", "lieferant", "kundennummer", "turnus",
               "schluessel", "notiz"}
    felder = bereinige(Kostenart, {a: b for a, b in data.items() if a in erlaubt})

    alt = k.name
    if "name" in felder:
        neu = (felder["name"] or "").strip()
        if not neu:
            raise HTTPException(400, "Die Kostenart braucht einen Namen")
        doppelt = session.exec(select(Kostenart).where(
            Kostenart.objekt_id == k.objekt_id, Kostenart.name == neu)).all()
        if any(a.id != k.id for a in doppelt):
            raise HTTPException(
                409, f"„{neu}“ gibt es an dieser Immobilie schon")
        # Nicht nur der Katalog zählt: eine Position entsteht auch aus einem
        # Beleg, ohne dass es dafür einen Katalog-Eintrag gibt. Zöge der neue
        # Name in die Positionen nach, stünden zwei Zeilen gleichen Namens im
        # selben Zeitraum — die Checkliste (ein Eintrag je Art) zeigte eine
        # davon, die Abrechnung summierte beide, und der Betrag stünde doppelt
        # in der Endsumme. Die verdeckte Zeile wäre über die Oberfläche nicht
        # mehr erreichbar. Deshalb: derselbe Konflikt, dieselbe Antwort wie beim
        # Umhängen einer Position (Fund N118).
        if neu != alt:
            belegt = _positionen_mit_art(session, k.objekt_id, neu)
            if belegt:
                raise HTTPException(409, (
                    f"„{neu}“ steht in {len(belegt)} "
                    + ("Abrechnung" if len(belegt) == 1 else "Abrechnungen")
                    + " dieser Immobilie schon als eigene Position. Der Name "
                    "würde doppelt vorkommen und der Betrag doppelt zählen — "
                    "hänge diese Position zuerst um oder wähle einen anderen "
                    "Namen."))
        felder["name"] = neu

    geprueft = Kostenart.model_validate({**k.model_dump(), **felder})
    for feld in felder:
        setattr(k, feld, getattr(geprueft, feld))
    session.add(k)

    nachgezogen = 0
    if k.name != alt:
        for p in _positionen_mit_art(session, k.objekt_id, alt):
            p.kostenart = k.name
            session.add(p)
            nachgezogen += 1
        for d in session.exec(select(Dokument).where(
                Dokument.objekt_id == k.objekt_id,
                Dokument.kostenart == alt)).all():
            d.kostenart = k.name
            session.add(d)
    # N351 — § 35a zieht in die BESTEHENDEN Positionen nach, wie der Name:
    # der Vermerk soll in der laufenden Abrechnung sofort gelten, nicht erst
    # bei der nächsten neu angelegten Position (die erbt ihn ohnehin,
    # `belegposten.anlegen`).
    if "s35" in felder:
        for p in _positionen_mit_art(session, k.objekt_id, k.name):
            if p.s35 != k.s35:
                p.s35 = k.s35
                session.add(p)
                nachgezogen += 1
    session.commit()
    return {"ok": True, "name": k.name, "umlagefaehig": k.umlagefaehig,
            "s35": k.s35, "positionen_nachgezogen": nachgezogen}
