"""Kostenpositionen: Vorschau, Anlegen, Patch, Löschen.

Eine Position gehört zu einem Zeitraum und einer Kostenart; ihr Betrag geht
über einen Verteilungsschlüssel als Anteile an die Parteien. Ein Sonderposten
(`nur_einheit`) zählt zu 100 % auf eine Einheit — Schlüssel dann irrelevant.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from ..belegposten import anlegen as position_bauen
from ..db import get_session
from ..dokumente.zuordnung import loese_info_referenzen
from ..models import Dokument, Kostenart, Kostenposition, Vorauszahlung, Zeitraum
from ..verteilung import (SCHLUESSEL, VORGABE, UnbekannterSchluessel, ableiten,
                          ableiten_einheit, stammdaten,
                          unbekannte_vorauszahlungen, vorschau)
from .zeitraeume import _zeitraum, _zeitraum_leer_entfernen

router = APIRouter(tags=["objekte"])


def _gewichte(session: Session, z: Zeitraum, schluessel: str) -> dict[str, float]:
    try:
        return ableiten(session, z, schluessel)
    except UnbekannterSchluessel as fehler:
        raise HTTPException(400, str(fehler)) from fehler


@router.get("/zeitraeume/{zid}/schluessel")
def schluessel_vorschau(zid: int, session: Session = Depends(get_session)) -> dict:
    """Welche Verteilungsschlüssel für dieses Objekt taugen — und welche
    Gewichte dabei herauskämen.

    Vorschau vor der Festlegung: `moeglich` sagt, ob sich der Schlüssel aus den
    Stammdaten ergibt. `unbekannte_vorauszahlungen` deckt den stillen Fehler
    auf, bei dem eine Vorauszahlung auf einen Parteinamen lautet, den die
    Verteilung gar nicht kennt — die Engine rechnet dann an ihr vorbei."""
    z = _zeitraum(session, zid)
    bezuege = stammdaten(session, z)
    vzs = session.exec(
        select(Vorauszahlung).where(Vorauszahlung.zeitraum_id == zid)).all()
    return {
        "zeitraum": zid, "vorgabe": VORGABE,
        "parteien": [{"partei": b.partei, "einheit": b.einheit,
                      "flaeche": b.flaeche, "personen": b.personen}
                     for b in bezuege],
        "schluessel": vorschau(bezuege, z.start, z.ende),
        "unbekannte_vorauszahlungen": unbekannte_vorauszahlungen(session, z, vzs),
    }


class PositionNeu(BaseModel):
    """Ohne `anteile` werden die Gewichte aus dem Schlüssel abgeleitet.

    `nur_einheit` (CXCIV) macht daraus einen Sonderposten: ist eine Einheit
    genannt, geht die Position zu 100 % auf diese Einheit, der Schlüssel spielt
    keine Rolle mehr."""
    kostenart: str
    betrag: float = 0.0
    schluessel: str = VORGABE
    nur_einheit: str = ""
    wertquelle: str = "manuell"
    status: Optional[str] = None
    s35: Optional[bool] = None
    anteile: Optional[dict[str, float]] = None


@router.post("/zeitraeume/{zid}/positionen", status_code=201)
def position_anlegen(zid: int, data: PositionNeu,
                     session: Session = Depends(get_session)) -> dict:
    """Legt eine Kostenposition an — mit Gewichten, nicht ohne.

    Bisher entstanden Positionen nur beiläufig (Beleg-Scan) und blieben ohne
    `anteile`; ihr Betrag fiel damit aus der Abrechnung heraus.

    Eine zweite Position derselben Kostenart bleibt abgewiesen (CLXXXII): eine
    Kostenart, eine Zeile — sonst stünde „Wasser" zweimal in der Abrechnung und
    niemand wüsste, welche der beiden gilt. Dass trotzdem vier
    Abschlagsrechnungen auf dieselbe Zeile laufen, löst der Weg über den Beleg
    (`POST /api/dokumente/{id}/position`): dort addiert sich der Betrag in die
    vorhandene Position hinein, und es bleibt nachvollziehbar, aus welchen
    Belegen die Summe entstand."""
    z = _zeitraum(session, zid)
    if not data.kostenart.strip():
        raise HTTPException(400, "Die Kostenart darf nicht leer sein")
    vorhanden = session.exec(select(Kostenposition).where(
        Kostenposition.zeitraum_id == zid)).all()
    if any(p.kostenart == data.kostenart for p in vorhanden):
        raise HTTPException(409, f"'{data.kostenart}' ist in diesem Zeitraum "
                                 f"bereits erfasst. Ein weiterer Beleg wird "
                                 f"über „Als Kostenposition übernehmen“ "
                                 f"dazugerechnet.")

    # CXCIV: ein Sonderposten trägt seine Gewichte selbst — zu 100 % auf die
    # genannte Einheit. Der Schlüssel wird nicht abgeleitet.
    anteile = data.anteile
    if data.nur_einheit and anteile is None:
        anteile = ableiten_einheit(session, z, data.nur_einheit)
    try:
        p = position_bauen(session, z, data.kostenart, betrag=data.betrag,
                           schluessel=data.schluessel,
                           wertquelle=data.wertquelle, status=data.status,
                           s35=data.s35, anteile=anteile)
    except UnbekannterSchluessel as fehler:
        raise HTTPException(400, str(fehler)) from fehler
    if data.nur_einheit:
        p.nur_einheit = data.nur_einheit
    # N5 — ohne mitgelieferte anteile sind die Gewichte abgeleitet und dürfen
    # sich bei Stammdaten-Änderungen selbst neu berechnen; mit anteile sind sie
    # eine Handeingabe und bleiben.
    p.abgeleitet = data.anteile is None
    session.add(p)
    session.commit()
    session.refresh(p)
    return {"id": p.id, "kostenart": p.kostenart, "status": p.status,
            "anteile": p.anteile, "nur_einheit": p.nur_einheit,
            "abgeleitet": p.abgeleitet}


class PositionIn(BaseModel):
    betrag: Optional[float] = None
    status: Optional[str] = None
    # CCCLXII — die Position auf eine andere Kostenart umhängen (z. B. generische
    # „Versicherung" → spezifische „Gebäudeversicherung"). Freitext wie im Modell;
    # eine noch unbekannte Art wird als Katalog-Eintrag angelegt, damit sie nicht
    # als namenlose Waise dasteht.
    kostenart: Optional[str] = None
    schluessel: Optional[str] = None
    nur_einheit: Optional[str] = None
    wertquelle: Optional[str] = None
    # N122 — Menge hinter dem Betrag („2.400 kWh für 862,51 €") und woher der
    # Strom kam: 'extern' (Netzbezug) oder 'eigen' (eigene PV-Anlage).
    menge: Optional[float] = None
    menge_einheit: Optional[str] = None
    herkunft: Optional[str] = None
    # N124 — Arbeitspreis und Grundpreis laut Rechnung (nur Beleg/Gegenprobe).
    arbeitspreis: Optional[float] = None
    grundpreis_monat: Optional[float] = None
    anteile: Optional[dict[str, float]] = None
    # N5 — Herkunft der mitgesendeten Gewichte: true = aus den Stammdaten
    # abgeleitet („Aus Stammdaten ableiten"-Knopf), false = Handeingabe. Fehlt
    # das Flag bei gesetzten anteile, gilt es als Handeingabe.
    abgeleitet: Optional[bool] = None
    s35: Optional[bool] = None
    # CCCLIX — Vorab-Anteil direkt auf eine Einheit (mit eigenem §35a)
    vorab_betrag: Optional[float] = None
    vorab_einheit: Optional[str] = None
    vorab_s35: Optional[bool] = None
    vorab_netto: Optional[float] = None   # CCCLX — eingegebener Netto (Anzeige)


@router.patch("/positionen/{pid}")
def position_aendern(pid: int, data: PositionIn,
                     session: Session = Depends(get_session)) -> dict:
    """Betrag nachtragen oder Zustand ändern — das Nachbearbeiten aus der App.

    Wird nur der Schlüssel umgestellt, werden die Gewichte neu abgeleitet:
    Fläche-Gewichte unter dem Schlüssel „Personen" stehen zu lassen wäre die
    unauffälligste Art, falsch abzurechnen."""
    p = session.get(Kostenposition, pid)
    if not p:
        raise HTTPException(404, "Position nicht gefunden")
    # CCCLXII — die Position auf eine andere Kostenart setzen. Nur diese eine
    # Position wandert (kein globales Umbenennen — das macht kostenart_aendern).
    if data.kostenart is not None:
        neu = data.kostenart.strip()
        if not neu:
            raise HTTPException(400, "Die Kostenart braucht einen Namen")
        if neu != p.kostenart:
            z = _zeitraum(session, p.zeitraum_id)
            # In einem Zeitraum bleibt eine Position je Kostenart die Regel
            # (CLXXXII) — sonst kollidieren zwei Zeilen auf denselben Namen.
            kollision = session.exec(select(Kostenposition).where(
                Kostenposition.zeitraum_id == p.zeitraum_id,
                Kostenposition.kostenart == neu,
                Kostenposition.id != p.id)).first()
            if kollision:
                raise HTTPException(
                    409, f"Zu „{neu}“ gibt es in diesem Zeitraum schon eine "
                         f"Position — trag den Betrag dort ein.")
            # Ist die Zielart im Katalog des Objekts noch unbekannt, wird sie
            # angelegt (additiv): so bleibt sie konfigurierbar und für kommende
            # Zeiträume wählbar, statt als namenlose Waise dazustehen.
            bekannt = session.exec(select(Kostenart).where(
                Kostenart.objekt_id == z.objekt_id,
                Kostenart.name == neu)).first()
            if not bekannt:
                session.add(Kostenart(objekt_id=z.objekt_id, name=neu,
                                      umlagefaehig=True, s35=p.s35, aktiv=True))
            p.kostenart = neu
    if data.betrag is not None:
        p.betrag = data.betrag
        # N238 — der Zustand folgt dem Betrag in BEIDE Richtungen: ein
        # eingetragener Betrag heisst „erledigt", ein auf 0 korrigierter
        # (z. B. weil sich ein Beleg als reiner Info-Beleg herausstellte)
        # heisst wieder „offen" — sonst bliebe eine 0,00-€-Zeile fälschlich
        # grün stehen.
        if data.status is None:
            p.status = "erledigt" if data.betrag > 0 else "offen"
    if data.schluessel is not None and data.schluessel not in SCHLUESSEL:
        raise HTTPException(400, f"Unbekannter Verteilungsschlüssel "
                                 f"'{data.schluessel}'")
    umgestellt = data.schluessel is not None and data.schluessel != p.schluessel
    # CXCIV: die Einheit eines Sonderpostens wechseln — oder ihn wieder zum
    # normalen, über den Schlüssel verteilten Posten machen (leerer Wert).
    neue_einheit = (data.nur_einheit is not None
                    and data.nur_einheit != p.nur_einheit)
    for feld in ("status", "schluessel", "nur_einheit", "wertquelle", "s35",
                 "menge", "menge_einheit", "herkunft",
                 "arbeitspreis", "grundpreis_monat",
                 "vorab_betrag", "vorab_einheit", "vorab_s35", "vorab_netto"):
        wert = getattr(data, feld)
        if wert is not None:
            setattr(p, feld, wert)
    # N5 — Herkunfts-Flag mitführen: der „Aus Stammdaten ableiten"-Knopf sendet
    # anteile MIT abgeleitet=true (bleibt automatisch aktualisierbar), das Ändern
    # einzelner Gewichte sendet anteile MIT abgeleitet=false (Handeingabe).
    if data.abgeleitet is not None:
        p.abgeleitet = data.abgeleitet
    if data.anteile is not None:
        p.anteile = data.anteile
        # Ausdrücklich gesetzte anteile ohne Herkunfts-Flag = Handeingabe.
        if data.abgeleitet is None:
            p.abgeleitet = False
    elif neue_einheit or umgestellt:
        z = _zeitraum(session, p.zeitraum_id)
        # Solange eine Einheit genannt ist, trägt sie zu 100 %; sonst zählt
        # wieder der Schlüssel über alle Parteien. Serverseitig abgeleitet.
        p.anteile = (ableiten_einheit(session, z, p.nur_einheit)
                     if p.nur_einheit else _gewichte(session, z, p.schluessel))
        p.abgeleitet = True
    session.add(p)
    session.commit()
    return {"ok": True, "betrag": p.betrag, "status": p.status,
            "kostenart": p.kostenart,
            "schluessel": p.schluessel, "nur_einheit": p.nur_einheit,
            "anteile": p.anteile}


@router.delete("/positionen/{pid}")
def position_loeschen(pid: int, session: Session = Depends(get_session)) -> dict:
    """Entfernt eine Kostenposition — eine bewusste Nutzeraktion.

    Die Kostenart bleibt im Katalog des Objekts stehen; die Zeile taucht in der
    Checkliste danach wieder als „fehlt" auf, statt zu verschwinden.

    Belege, die auf die Position gezeigt haben, verlieren nur diese
    Verknüpfung: die Dateien bleiben in der Cloud, die Einträge bleiben am
    Zeitraum, und ein „Als Kostenposition übernehmen" legt die Zeile jederzeit
    wieder an. Ein Beleg, der auf eine gelöschte Position zeigt, wäre dagegen
    ein Verweis ins Leere."""
    p = session.get(Kostenposition, pid)
    if not p:
        raise HTTPException(404, "Position nicht gefunden")
    kostenart = p.kostenart
    zid = p.zeitraum_id
    geloest = 0
    for d in session.exec(select(Dokument)
                          .where(Dokument.position_id == pid)).all():
        d.position_id = None
        session.add(d)
        geloest += 1
    # N314(d) — ein Info-Beleg (nicht die Hauptrechnung) hängt über
    # `info_zu_typ`/`info_zu_id`, nicht über `position_id`.
    loese_info_referenzen(session, "kostenposition", pid)
    session.delete(p)
    session.commit()
    # War das die letzte Position und hängt sonst nichts mehr am Zeitraum,
    # verschwindet der leere Zeitraum von selbst — kein Löschknopf nötig.
    zeitraum_entfernt = _zeitraum_leer_entfernen(session, zid)
    return {"ok": True, "kostenart": kostenart, "belege_geloest": geloest,
            "zeitraum_entfernt": zeitraum_entfernt}
