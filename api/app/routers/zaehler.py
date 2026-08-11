"""Zähler und Ablesewerte (CCXCIII).

Zähler hängen am Objekt, Ablesungen am Zähler. Die Eingabemaske schrittet je
Abrechnungszeitraum durch die Zähler; der Verbrauch wird linear auf Tagesbasis
interpoliert (`ablesung.py` → `engine`). Die eigentliche Geld-Verteilung bleibt
in den Kostenpositionen — hier entsteht nur der Verbrauch je Zähler.

Routen-Reihenfolge: `/objekte/{slug}/zaehler` muss VOR dem Stammdaten-Fänger
`/objekte/{slug}/{bereich}` registriert werden (siehe main.py).
"""
import logging
from datetime import date
from types import SimpleNamespace

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from .. import ablesung, belegposten, kostenarten, verteilung, wasser
from ..db import get_session
from ..einheitenzuordnung import (karte as einheiten_karte, parse_einheiten,
                                  warnungen as zuordnungs_warnungen, zuordne,
                                  zuordne_zaehler)
from ..deps import objekt_holen
from ..models import (Ablesung, Einheit, Kostenposition, Miete, Objekt, Partei,
                      Zaehler, Zeitraum)
from .openwb import ladungen as openwb_ladungen
from .tankstelle import nutzer_lesen

log = logging.getLogger("immocalc")
router = APIRouter(prefix="/api", tags=["zaehler"])

# CD — Ableitung des Kostenblocks aus der Kostenart. Zuerst über
# `kostenarten.normalisieren` kanonisieren, dann umlaut-/schreibweisentolerant
# auf einen der vier Blöcke abbilden. Heizung VOR Wasser prüfen, damit
# „Warmwasser" (Heizung) nicht am „…wasser" hängenbleibt.
def _kostenblock(kostenart: str) -> str:
    """Einer von 'Wasser'|'Heizung'|'Strom'|'Sonstige'."""
    k = kostenarten._fold(kostenarten.normalisieren(kostenart))
    if any(t in k for t in ("heizung", "heizkost", "warmwasser", "heizoel",
                            "oel", "warmwaerme", "waermewasser")):
        return "Heizung"
    if any(t in k for t in ("wasser", "abwasser", "niederschlag", "frischwasser")):
        return "Wasser"
    if "strom" in k:
        return "Strom"
    return "Sonstige"


# CCCLXXX — der Anfangsstand („Erststand" vor der ersten Abrechnung) ist eine
# ganz normale Ablesung, nur mit dieser Notiz markiert und ohne Zeitraum-Tag.
# So bleibt das Modell unverändert (kein neues Feld), und die Interpolation
# behandelt ihn wie jeden anderen Stand.
ANFANGSSTAND = "Anfangsstand"
# Id der synthetischen Vorlauf-Periode (siehe `_mit_vorlauf`). 0 kollidiert nicht
# mit realen Zeitraum-Ids (SQLite-Autoincrement beginnt bei 1).
_VORLAUF_ID = 0


def _mit_vorlauf(zeitraeume: list, zma: list) -> tuple[list, object | None]:
    """Ergänzt die Periodenliste um eine synthetische Vorlauf-Periode, sobald ein
    Anfangsstand (Ablesung am/vor dem Beginn der ersten Abrechnung) vorliegt.

    Ohne sie behandelt `verbrauchsreihe` die erste reale Periode als Start-
    ablesung (Verbrauch 0) — der Anfangsstand bliebe wirkungslos. Die Vorlauf-
    Periode endet am Beginn der ersten realen Periode; dadurch wird der Anfangs-
    stand ihr Randwert und die erste Abrechnung bekommt ihre echte Differenz.
    Für Zähler ohne Anfangsstand bleibt alles unverändert: der bisherige
    Startablesungs-Randwert ist identisch (end-to-end verifiziert)."""
    if not zeitraeume:
        return list(zeitraeume), None
    erste_start = min(z.start for z in zeitraeume)
    hat_anfang = any(a.datum <= erste_start for _, abls in zma for a in abls)
    if not hat_anfang:
        return list(zeitraeume), None
    vorlauf = SimpleNamespace(id=_VORLAUF_ID, start=erste_start, ende=erste_start)
    return [vorlauf, *zeitraeume], vorlauf


# --------------------------------------------------------------------------
# N157 — die E-Tankstelle: ihr Jahreswert wird gezogen, nicht getippt
# --------------------------------------------------------------------------

#: Kennzeichen der Ladestation in der BESTEHENDEN Spalte `art` — additiv, keine
#: Schemaänderung. Ältere Zähler tragen dort nichts; für die greift der Name.
EAUTO_ART = "E-Tankstelle"

#: Wortmarken, an denen eine Ladestation zu erkennen ist (nach `_ohne_trenner`,
#: also ohne Bindestriche und Leerzeichen: „E-Tankstelle" → „etankstelle").
_EAUTO_WORTE = ("etankstelle", "eauto", "elektroauto", "ladestation",
                "ladesaeule", "wallbox")

#: Woher der gezogene Wert stammt — steht als Notiz an der Ablesung, damit an
#: der Zahl selbst hängt, dass sie nicht von Hand kam.
EAUTO_NOTIZ = "aus dem Ladeprotokoll der Wallbox gezogen"


def _ohne_trenner(text: str) -> str:
    """Vergleichsschlüssel ohne Umlaute, Bindestriche und Leerzeichen."""
    return "".join(c for c in kostenarten._fold(text) if c.isalnum())


def ist_eauto_zaehler(z: Zaehler) -> bool:
    """Ist das die Ladestation des Objekts?

    Nur Strom-Zähler (kWh) kommen in Frage. Erkannt wird zuerst am Merkmal in
    `art`, sonst am Namen — so überlebt die Erkennung ein Umbenennen, sobald
    das Merkmal einmal gesetzt ist."""
    if (z.messeinheit or "") != "kWh":
        return False
    return any(w in _ohne_trenner(z.art) or w in _ohne_trenner(z.name)
               for w in _EAUTO_WORTE)


def _eauto_zaehler(session: Session, objekt_id: int) -> Zaehler | None:
    """Der Ladestations-Zähler eines Objekts — ``None``, wenn keiner erfasst ist."""
    zaehler = session.exec(
        select(Zaehler).where(Zaehler.objekt_id == objekt_id, Zaehler.aktiv)
        .order_by(Zaehler.reihenfolge, Zaehler.id)).all()
    return next((z for z in zaehler if ist_eauto_zaehler(z)), None)


class ZaehlerIn(BaseModel):
    name: str
    kostenart: str = ""
    einheit_bezug: str = ""
    art: str = ""
    messeinheit: str = "m³"
    typ: str = "gemessen"
    hauptzaehler_id: int | None = None
    reihenfolge: int = 0
    aktiv: bool = True
    notiz: str = ""
    bewertungsfaktor: float | None = None
    zaehlernummer: str = ""


class AblesungIn(BaseModel):
    datum: date
    stand: float
    zeitraum_id: int | None = None
    notiz: str = ""


class AnfangsstandIn(BaseModel):
    stand: float
    datum: date
    zeitraum_id: int | None = None


class UebernahmeIn(BaseModel):
    kostenart: str
    schluessel: str = "verbrauch"


def _zaehler(session: Session, zid: int) -> Zaehler:
    z = session.get(Zaehler, zid)
    if not z:
        raise HTTPException(404, "Zähler nicht gefunden")
    return z


def _stammbezug(session: Session,
                z: Zeitraum) -> tuple[list[Einheit], list[verteilung.Bezug]]:
    """Einheiten und Bezüge eines Zeitraums — die Grundlage jeder Zuordnung
    „Label → Einheit" (`einheitenzuordnung.karte`)."""
    einheiten = list(session.exec(
        select(Einheit).where(Einheit.objekt_id == z.objekt_id)).all())
    mieten = list(session.exec(
        select(Miete).where(Miete.objekt_id == z.objekt_id)).all())
    parteien = list(session.exec(
        select(Partei).where(Partei.objekt_id == z.objekt_id)).all())
    return einheiten, verteilung.bezuege(einheiten, mieten, parteien,
                                         z.start, z.ende)


# --------------------------------------------------------------------------
# Zähler-Stammdaten je Objekt
# --------------------------------------------------------------------------

@router.get("/objekte/{slug}/zaehler")
def liste(slug: str, session: Session = Depends(get_session),
          o: Objekt = Depends(objekt_holen)) -> list[dict]:
    zaehler = session.exec(
        select(Zaehler).where(Zaehler.objekt_id == o.id)
        .order_by(Zaehler.reihenfolge, Zaehler.id)).all()
    return [_zeige(session, z) for z in zaehler]


@router.post("/objekte/{slug}/zaehler", status_code=201)
def anlegen(slug: str, data: ZaehlerIn, session: Session = Depends(get_session),
            o: Objekt = Depends(objekt_holen)) -> dict:
    z = Zaehler(objekt_id=o.id, **data.model_dump())
    session.add(z)
    session.commit()
    session.refresh(z)
    return {"id": z.id}


@router.patch("/zaehler/{zid}")
def aendern(zid: int, data: dict, session: Session = Depends(get_session)) -> dict:
    z = _zaehler(session, zid)
    for feld in ("name", "kostenart", "einheit_bezug", "art", "messeinheit", "typ",
                 "hauptzaehler_id", "reihenfolge", "aktiv", "notiz", "bewertungsfaktor",
                 "zaehlernummer"):
        if feld in data:
            setattr(z, feld, data[feld])
    # CD — Mehrfachzuordnung: `einheiten` kommt als Liste und wird komma-gejoint
    # gespeichert (leere Liste → ""). Getrimmt, Leere raus.
    if "einheiten" in data:
        liste = data["einheiten"] or []
        z.einheiten = ",".join(str(x).strip() for x in liste if str(x).strip())
    session.add(z)
    session.commit()
    return {"ok": True}


@router.delete("/zaehler/{zid}")
def loeschen(zid: int, session: Session = Depends(get_session)) -> dict:
    z = _zaehler(session, zid)
    for a in session.exec(select(Ablesung).where(Ablesung.zaehler_id == zid)).all():
        session.delete(a)
    session.delete(z)
    session.commit()
    return {"ok": True}


# --------------------------------------------------------------------------
# Ablesungen je Zähler
# --------------------------------------------------------------------------

@router.get("/zaehler/{zid}/ablesungen")
def ablesungen(zid: int, session: Session = Depends(get_session)) -> list[dict]:
    _zaehler(session, zid)
    reihe = session.exec(select(Ablesung).where(Ablesung.zaehler_id == zid)
                         .order_by(Ablesung.datum)).all()
    return [{"id": a.id, "datum": a.datum.isoformat(), "stand": a.stand,
             "zeitraum_id": a.zeitraum_id, "notiz": a.notiz} for a in reihe]


@router.post("/zaehler/{zid}/ablesungen", status_code=201)
def ablesung_speichern(zid: int, data: AblesungIn,
                       session: Session = Depends(get_session)) -> dict:
    _zaehler(session, zid)
    # Idempotent je Zeitraum: eine bestehende Ablesung dieses Zeitraums wird
    # aktualisiert statt verdoppelt — so darf man im Wizard vor- und zurück.
    vorhanden = None
    if data.zeitraum_id is not None:
        vorhanden = session.exec(select(Ablesung).where(
            Ablesung.zaehler_id == zid,
            Ablesung.zeitraum_id == data.zeitraum_id)).first()
    elif (data.notiz or "") == ANFANGSSTAND:
        # CCCLXXX — der Anfangsstand ist ebenso idempotent, aber je Zähler (er
        # hängt an keinem Zeitraum): ein vorhandener wird aktualisiert statt
        # verdoppelt, damit die Konfig-Maske ihn ohne Dublette nachbessern kann.
        vorhanden = session.exec(select(Ablesung).where(
            Ablesung.zaehler_id == zid, Ablesung.zeitraum_id.is_(None),
            Ablesung.notiz == ANFANGSSTAND)).first()
    a = vorhanden or Ablesung(zaehler_id=zid, datum=data.datum, stand=data.stand)
    a.datum, a.stand = data.datum, data.stand
    a.zeitraum_id, a.notiz = data.zeitraum_id, data.notiz
    session.add(a)
    session.commit()
    session.refresh(a)
    return {"id": a.id}


@router.post("/zaehler/{zid}/anfangsstand")
def anfangsstand_setzen(zid: int, data: AnfangsstandIn,
                        session: Session = Depends(get_session)) -> dict:
    """CD — den Anfangsstand (den `vorwert` der ersten Abrechnung) direkt in der
    Maske editierbar machen. Idempotent: existiert schon eine Anfangs-Ablesung
    (per Notiz markiert, sonst die früheste untaggte), wird deren Stand/Datum
    aktualisiert; sonst wird sie neu angelegt. Der Anfangsstand ist eine ganz
    normale Ablesung mit der Markierung `ANFANGSSTAND` und ohne Zeitraum-Tag —
    so behandelt die Interpolation ihn wie jeden anderen Stand (CCCLXXX).

    Gibt den aktualisierten Zähler-Stand zurück (wie `_zeige`)."""
    z = _zaehler(session, zid)
    abls = session.exec(select(Ablesung).where(Ablesung.zaehler_id == zid)
                        .order_by(Ablesung.datum)).all()
    vorhanden = next((a for a in abls if (a.notiz or "") == ANFANGSSTAND), None) \
        or next((a for a in abls if a.zeitraum_id is None), None)
    a = vorhanden or Ablesung(zaehler_id=zid, datum=data.datum, stand=data.stand)
    a.datum, a.stand = data.datum, data.stand
    # N96 — der Anfangsstand hängt an KEINEM Zeitraum. Wurde hier die mitge-
    # schickte `zeitraum_id` gesetzt, trug er dieselbe Markierung wie der
    # Endstand dieser Periode — und wurde als dieser gelesen: die Eingabe des
    # Anfangs überschrieb sichtbar das Ende. Deshalb immer None.
    a.zeitraum_id = None
    a.notiz = ANFANGSSTAND
    session.add(a)
    session.commit()
    return _zeige(session, z)


# --------------------------------------------------------------------------
# Eingabemaske je Abrechnungszeitraum — die Zähler in Reihenfolge mit Vorwert
# und (falls erfasst) interpoliertem Verbrauch.
# --------------------------------------------------------------------------

@router.get("/zeitraeume/{zid}/ablesung")
def maske(zid: int, session: Session = Depends(get_session)) -> dict:
    z = session.get(Zeitraum, zid)
    if not z:
        raise HTTPException(404, "Zeitraum nicht gefunden")
    zeitraeume = session.exec(
        select(Zeitraum).where(Zeitraum.objekt_id == z.objekt_id)).all()
    vorher = max((p for p in zeitraeume if p.ende < z.ende),
                 key=lambda p: p.ende, default=None)
    zaehler = session.exec(
        select(Zaehler).where(Zaehler.objekt_id == z.objekt_id, Zaehler.aktiv)
        .order_by(Zaehler.reihenfolge, Zaehler.id)).all()
    zma = [(zae, session.exec(select(Ablesung).where(Ablesung.zaehler_id == zae.id)
            .order_by(Ablesung.datum)).all()) for zae in zaehler]
    # CCCLXXX — ein Anfangsstand vor der ersten Abrechnung wird über eine
    # synthetische Vorlauf-Periode Teil derselben Interpolation (`verbrauchsreihe`).
    zeitraeume_i, vorlauf = _mit_vorlauf(zeitraeume, zma)
    erste_start = min((p.start for p in zeitraeume), default=None)
    verb = ablesung.verbrauch_je_zaehler(zma, zeitraeume_i, zid)

    zeilen = []
    for zae, abls in zma:
        reihe = ablesung.verbrauchsreihe(abls, zeitraeume_i)
        # Der Vorstand kommt aus der vorigen realen Periode; für die erste Periode
        # ist es — falls vorhanden — der Anfangsstand (Randwert der Vorlauf-Periode).
        if vorher:
            vorwert = reihe.get(vorher.id)
        elif (vorlauf and erste_start is not None
              and any(a.datum <= erste_start for a in abls)):
            vorwert = reihe.get(_VORLAUF_ID)
        else:
            vorwert = None
        erfasst = next((a for a in abls if a.zeitraum_id == zid), None)
        zeilen.append({
            "id": zae.id, "name": zae.name, "messeinheit": zae.messeinheit,
            "kostenart": zae.kostenart, "einheit_bezug": zae.einheit_bezug,
            # CD — Mehrfachzuordnung + Kostenblock (bestehende Felder unverändert).
            "einheiten": parse_einheiten(zae),
            "kostenblock": _kostenblock(zae.kostenart),
            "typ": zae.typ, "hauptzaehler_id": zae.hauptzaehler_id,
            # N120 — `art` unterscheidet die Zeilen der Strom-Maske (Gesamt,
            # Anbau, E-Auto, Scheune, Haus) genauso wie beim Wasser; `notiz`
            # traegt die Erlaeuterung, die der Nutzer selbst hinterlegt.
            "art": zae.art, "notiz": zae.notiz,
            # N157 — die Ladestation ist die einzige Zeile, deren Jahreswert
            # gezogen und nicht getippt wird. Welche das ist, entscheidet EINE
            # Regel hier im Backend; die Oberfläche liest nur das Merkmal.
            "eauto": ist_eauto_zaehler(zae),
            "vorwert": None if not vorwert else {
                "stand": round(vorwert["randwert"], 3),
                "datum": vorwert["datum"].isoformat()},
            "ablesung": None if not erfasst else {
                "id": erfasst.id, "datum": erfasst.datum.isoformat(),
                "stand": erfasst.stand},
            "verbrauch": None if verb.get(zae.id) is None
            else round(verb[zae.id], 3),
            "zaehlernummer": zae.zaehlernummer, "verlauf": _verlauf(abls),
        })
    return {
        "zeitraum": {"id": z.id, "start": z.start.isoformat(),
                     "ende": z.ende.isoformat(),
                     "label": f"{z.start:%d.%m.%Y} – {z.ende:%d.%m.%Y}"},
        "vorheriges_ende": vorher.ende.isoformat() if vorher else None,
        "zaehler": zeilen,
        "schluessel_optionen": [
            {"wert": k, "titel": v["titel"], "ableitbar": v["ableitbar"]}
            for k, v in verteilung.SCHLUESSEL.items()],
    }


@router.post("/zeitraeume/{zid}/eauto")
def eauto_ziehen(zid: int, session: Session = Depends(get_session)) -> dict:
    """N157 — den Jahreswert der E-Tankstelle aus dem Ladeprotokoll ziehen.

    Der Wert wird **als Ablesung dieses Zählers** abgelegt. Damit gibt es genau
    eine Menge: alles, was schon rechnet (Verbrauch Haus als Rest, der Abgleich
    in der Stromkette), liest weiter den Zähler — nur getippt wird sie nicht
    mehr. Gezogen wird nach den Monaten des Abrechnungszeitraums, nicht nach
    Kalenderjahr.

    Antwortet die Wallbox nicht, bleibt der zuletzt gezogene Stand **stehen**
    und der Grund steht in `hinweis`. Eine 0 wäre hier eine Falschaussage.
    Ein abgeschlossener Zeitraum wird nie mehr überschrieben."""
    z = session.get(Zeitraum, zid)
    if not z:
        raise HTTPException(404, "Zeitraum nicht gefunden")
    objekt = session.get(Objekt, z.objekt_id)
    antwort: dict = {
        "zeitraum_id": z.id, "von": z.start.isoformat(), "bis": z.ende.isoformat(),
        "zaehler_id": None, "name": "", "ok": False, "hinweis": "",
        "kwh": None, "anzahl": None, "stand": None, "gespeichert": False,
        "nutzer": [n["name"] for n in nutzer_lesen(session, objekt.slug)]
        if objekt else [],
    }
    zae = _eauto_zaehler(session, z.objekt_id)
    if not zae:
        antwort["hinweis"] = ("Für dieses Objekt ist keine Ladestation als "
                              "Zähler erfasst.")
        return antwort
    # Das Merkmal einmal festschreiben (leeres Feld → additiv gefüllt), damit
    # ein späteres Umbenennen die Erkennung nicht verliert.
    if not (zae.art or "").strip():
        zae.art = EAUTO_ART
        session.add(zae)
        session.commit()
    erfasst = session.exec(select(Ablesung).where(
        Ablesung.zaehler_id == zae.id, Ablesung.zeitraum_id == zid)).first()
    antwort.update({"zaehler_id": zae.id, "name": zae.name,
                    "stand": erfasst.stand if erfasst else None})

    try:
        daten = openwb_ladungen(von=z.start, bis=z.ende, session=session)
    except Exception as fehler:            # noqa: BLE001 — Box im Heimnetz
        log.info("E-Tankstelle: Wallbox nicht abrufbar — %s", fehler)
        antwort["hinweis"] = ("Die Wallbox antwortet gerade nicht — der zuletzt "
                              "gezogene Wert bleibt stehen.")
        return antwort
    if not daten.get("ok") or daten.get("kwh") is None:
        antwort["hinweis"] = daten.get("hinweis") or (
            "Die Wallbox liefert für diesen Zeitraum nichts Auswertbares — der "
            "zuletzt gezogene Wert bleibt stehen.")
        return antwort

    kwh = round(daten["kwh"], 3)
    antwort.update({"ok": True, "kwh": kwh, "anzahl": daten.get("anzahl") or 0,
                    "quelle": daten.get("quelle", "")})
    if z.status != "in Arbeit":
        antwort["hinweis"] = ("Der Zeitraum ist abgeschlossen — der gezogene "
                              "Wert wird nicht mehr eingetragen.")
        return antwort
    if erfasst is None or abs((erfasst.stand or 0.0) - kwh) > 0.0005 \
            or erfasst.datum != z.ende:
        ablesung_speichern(zae.id, AblesungIn(
            datum=z.ende, stand=kwh, zeitraum_id=zid, notiz=EAUTO_NOTIZ), session)
        antwort["gespeichert"] = True
        log.info("E-Tankstelle: %s kWh am Zähler %s eingetragen", kwh, zae.id)
    antwort["stand"] = kwh
    return antwort


@router.post("/zeitraeume/{zid}/ablesung/uebernehmen")
def uebernehmen(zid: int, data: UebernahmeIn,
                session: Session = Depends(get_session)) -> dict:
    """Trägt den interpolierten Verbrauch einer Kostenart als Verteilung in die
    NK-Kostenposition ein. Bei `schluessel='verbrauch'` werden die Gewichte je
    Partei aus den Zählern gebildet (Untermesser/Rest, gruppiert nach
    `einheit_bezug`); bei jedem anderen Schlüssel werden sie aus den Stammdaten
    abgeleitet. Der Betrag (aus dem Beleg) bleibt unberührt — nur die Verteilung
    wird gesetzt. Eine bestehende Position wird aktualisiert, sonst angelegt.

    N288-B4 — die Schlüssel dieser Gewichte sind PARTEI-Namen (`engine.Position.
    anteile`), nicht Einheiten-Bezeichnungen; deshalb wird hier nicht auf die
    Einheit normalisiert. Gemeldet wird trotzdem, genau wie in der Wasser- und
    der Strom-Kette: `unzugeordnet`/`warnungen` nennen jeden Zähler, dessen
    Verbrauch in dieser Verteilung nicht ankommt."""
    z = session.get(Zeitraum, zid)
    if not z:
        raise HTTPException(404, "Zeitraum nicht gefunden")
    if data.schluessel not in verteilung.SCHLUESSEL:
        raise HTTPException(400, f"Unbekannter Schlüssel „{data.schluessel}“")

    zaehler = session.exec(select(Zaehler).where(
        Zaehler.objekt_id == z.objekt_id, Zaehler.kostenart == data.kostenart,
        Zaehler.aktiv)).all()
    if not zaehler:
        raise HTTPException(404, f"Keine Zähler für „{data.kostenart}“")

    # Gewichte je Partei aus dem Verbrauch — nur bei Verbrauchsschlüssel.
    anteile = None
    unzugeordnet: list[str] = []
    if data.schluessel == "verbrauch":
        zeitraeume = session.exec(
            select(Zeitraum).where(Zeitraum.objekt_id == z.objekt_id)).all()
        zma = [(zae, session.exec(select(Ablesung).where(
                Ablesung.zaehler_id == zae.id)).all()) for zae in zaehler]
        # Gleiche Vorlauf-Periode wie in der Maske: der Anfangsstand zählt so auch
        # bei der Übernahme in die erste Abrechnung mit (CCCLXXX).
        zeitraeume_i, _ = _mit_vorlauf(zeitraeume, zma)
        verb = ablesung.verbrauch_je_zaehler(zma, zeitraeume_i, zid)
        karte = einheiten_karte(*_stammbezug(session, z))
        anteile = {}
        for zae in zaehler:
            menge = verb.get(zae.id)
            if not menge:
                continue
            # Der Gesamtzähler (weder `einheiten` noch `einheit_bezug`) ist die
            # Kontrollsumme, keine Partei — er trägt hier nie Gewicht.
            ziele = parse_einheiten(zae)
            if not ziele:
                continue
            # N288-B4 — zwei Wege, auf denen ein Verbrauch bisher lautlos
            # verschwand: ein Zähler, der sein Ziel NUR über die Mehrfach-
            # zuordnung `einheiten` trägt (leeres `einheit_bezug`), und ein
            # Ziel-Label, das im Objekt weder Einheit noch Partei ist. Beides
            # wird jetzt genannt statt geschluckt.
            if not zae.einheit_bezug or not zuordne(ziele, karte).ziele:
                unzugeordnet.append(zae.name)
                if not zae.einheit_bezug:
                    continue
            anteile[zae.einheit_bezug] = round(
                anteile.get(zae.einheit_bezug, 0.0) + menge, 4)

    # Nur eine BESTEHENDE Position wird konfiguriert. Keine leere Hülle anlegen
    # (CCLVI: keine 0-€-Position ohne Beleg) — der Betrag kommt aus dem Beleg,
    # die Position entsteht dort; hier wird nur die Verteilung gesetzt.
    pos = belegposten.finde(session, zid, data.kostenart)
    if not pos:
        return {"ok": True, "kostenart": data.kostenart, "angewandt": False,
                "grund": "Noch keine Position — erst den Beleg/Betrag erfassen."}
    pos.schluessel = data.schluessel
    pos.wertquelle = "Zähler"
    pos.anteile = (anteile if anteile is not None
                   else verteilung.ableiten(session, z, data.schluessel))
    session.add(pos)
    session.commit()
    session.refresh(pos)
    return {"ok": True, "kostenart": data.kostenart, "angewandt": True,
            "schluessel": pos.schluessel, "anteile": pos.anteile,
            "position_id": pos.id,
            # N288-B4 — die Zähler, deren Verbrauch hier nicht ankommt. Leer =
            # alles verteilt; sonst steht in `warnungen`, was zu tun ist.
            "unzugeordnet": unzugeordnet,
            "warnungen": zuordnungs_warnungen(unzugeordnet)}


def _verlauf(abls: list[Ablesung]) -> dict[int, float]:
    """N340y — der Verlauf am Kärtchen (wie im Wärme-Simulator): letzter Stand
    je Kalenderjahr des Ablesedatums, unabhängig davon, ob die Ablesung einem
    echten Zeitraum zugeordnet ist. So zeigt sich sowohl historisch
    nachgetragener Verlauf als auch der laufende Jahreswert eines
    `typ='direkt'`-Zählers, ohne eigene Abfrage in der Oberfläche."""
    verlauf: dict[int, float] = {}
    for a in abls:
        if (a.notiz or "") == ANFANGSSTAND:
            continue
        verlauf[a.datum.year] = a.stand
    return verlauf


def _zeige(session: Session, z: Zaehler) -> dict:
    abls = session.exec(select(Ablesung).where(Ablesung.zaehler_id == z.id)
                        .order_by(Ablesung.datum)).all()
    # CCCLXXX — der Anfangsstand (Notiz-Markierung, sonst der früheste untaggte
    # Stand) kommt mit, damit die Konfig-Maske ihn ohne Extra-Abfrage zeigt.
    anfang = next((a for a in abls if (a.notiz or "") == ANFANGSSTAND), None) \
        or next((a for a in abls if a.zeitraum_id is None), None)
    return {"id": z.id, "name": z.name, "kostenart": z.kostenart,
            "einheit_bezug": z.einheit_bezug, "einheiten": parse_einheiten(z),
            "kostenblock": _kostenblock(z.kostenart),
            "art": z.art, "messeinheit": z.messeinheit,
            "typ": z.typ, "hauptzaehler_id": z.hauptzaehler_id,
            "reihenfolge": z.reihenfolge, "aktiv": z.aktiv, "notiz": z.notiz,
            "bewertungsfaktor": z.bewertungsfaktor, "zaehlernummer": z.zaehlernummer,
            "ablesungen": len(abls), "verlauf": _verlauf(abls),
            "anfangsstand": None if not anfang else {
                "stand": anfang.stand, "datum": anfang.datum.isoformat()}}


# --------------------------------------------------------------------------
# N47 — Wasser-Detailübersicht je Abrechnungszeitraum
#
# Bindet den getesteten Rechenkern (`wasser.verrechne`) an die gespeicherten
# Zähler, Ablesungen und Kostenpositionen: drei Kostenbestandteile (Frisch-,
# Schmutz-, Niederschlagswasser) werden über die Unterzähler verbrauchsscharf
# den Einheiten zugeordnet, der Rest (Haupthaus ohne eigenen Kaltzähler) per
# Personen·Mietdauer verteilt, das Gartenwasser als Menge herausgenommen.
# Der Endpunkt selbst bleibt dünn — er sammelt nur und mappt aufs Ergebnis.
# --------------------------------------------------------------------------

# Zeilenarten eines Unterzählers im Wasser-Popup.
_UNTER_ARTEN = frozenset({"Kaltwasser", "Warmwasser", "Waschmaschine"})


def _wasser_art(zae: Zaehler) -> str:
    """Wasser-Art eines Zählers — bevorzugt aus `art`, sonst aus dem NAMEN.
    Die realen Zähler tragen oft kein `art`; dann muss der Name entscheiden
    (Spiegel der Frontend-Logik `wasserArt`). Spezifisches vor Generischem."""
    for feld in ((zae.art or "").lower(), (zae.name or "").lower()):
        if not feld:
            continue
        if "waschmaschine" in feld:
            return "Waschmaschine"
        if "garten" in feld:
            return "Gartenwasser"
        if "warmwasser" in feld:
            return "Warmwasser"
        if "kaltwasser" in feld:
            return "Kaltwasser"
    return ""
# Kostenart je Wasser-Bestandteil.
_KOMPONENTEN_ART = {"wasser": "Wasser", "schmutz": "Abwasser",
                    "niederschlag": "Niederschlagswasser"}

# N288-B4 — die Abbildung „Label → echte Einheit" steht jetzt in
# `app/einheitenzuordnung.py`: EINE Fassung für Wasser, Strom und Übernahme,
# und sie gibt das Unzugeordnete immer mit zurück, statt es zu verschlucken.


@router.get("/zeitraeume/{zid}/wasser")
def wasser_detail(zid: int, schluessel: str = "personen",
                  rechnung_m3: float | None = None,
                  session: Session = Depends(get_session)) -> dict:
    """Wasser-Verrechnung dieses Zeitraums, aufgeschlüsselt je Einheit.

    Nicht bereit (`bereit=False`), solange der Hauptzähler-Verbrauch oder die
    Wasserbeträge fehlen — dann nennt `hinweis`, was noch gebraucht wird.
    """
    z = session.get(Zeitraum, zid)
    if not z:
        raise HTTPException(404, "Zeitraum nicht gefunden")

    # Verbrauch je Zähler-Id für diesen Zeitraum — wie in der Ablesungs-Maske,
    # inkl. synthetischer Vorlauf-Periode für einen Anfangsstand (CCCLXXX).
    zaehler = session.exec(
        select(Zaehler).where(Zaehler.objekt_id == z.objekt_id, Zaehler.aktiv)
        .order_by(Zaehler.reihenfolge, Zaehler.id)).all()
    zma = [(zae, session.exec(select(Ablesung).where(Ablesung.zaehler_id == zae.id)
            .order_by(Ablesung.datum)).all()) for zae in zaehler]
    zeitraeume = session.exec(
        select(Zeitraum).where(Zeitraum.objekt_id == z.objekt_id)).all()
    zeitraeume_i, _ = _mit_vorlauf(zeitraeume, zma)
    verb = ablesung.verbrauch_je_zaehler(zma, zeitraeume_i, zid)

    # Gesamtverbrauch = Wasser-Hauptzähler: gemessen, ohne eigenen Haupt und
    # Wasser-bezogen. Robuster als nur `art=='Kaltwasser'` — der reale „Gesamt
    # Kaltwasser" trägt oft kein `art`-Feld, nur Name + Kostenart „Wasser"
    # (sonst hieß es fälschlich „Gesamtverbrauch nicht verfügbar").
    def _ist_wasser_haupt(zae: Zaehler) -> bool:
        if zae.typ != "gemessen" or zae.hauptzaehler_id is not None:
            return False
        if zae.art == "Kaltwasser":
            return True
        if zae.art:                       # ein anderes spezifisches art ≠ Haupt
            return False
        name = (zae.name or "").lower()
        return ("kaltwasser" in name or "gesamt" in name
                or _kostenblock(zae.kostenart) == "Wasser")

    haupt = next((zae for zae in zaehler if _ist_wasser_haupt(zae)), None)
    gesamt_m3 = verb.get(haupt.id) if haupt else None
    # N116 — massgeblich ist die ABGERECHNETE Menge des Versorgers, wenn sie
    # bekannt ist (`rechnung_m3`, aus dem Bescheid: „Wasserbezug"). Der eigene
    # Zaehler weist oft mehr aus (Zaehlerwechsel, Stichtagsversatz, Leitungs-
    # verlust). Die Differenz gehoert NICHT dem Haupthaus angelastet: sie faellt
    # aus dem Rest heraus, die Kosten verteilen sich dafuer auf die kleinere,
    # tatsaechlich berechnete Menge.
    abgelesen_m3 = gesamt_m3
    # N116b — ohne mitgeschickten Wert gilt der am Zeitraum gespeicherte.
    if rechnung_m3 is None:
        rechnung_m3 = z.wasser_rechnung_m3 or None
    if rechnung_m3 and rechnung_m3 > 0:
        gesamt_m3 = float(rechnung_m3)

    # N101/6 — die Spalten sind Einheiten, keine Parteien. Alte Zähler tragen
    # noch Partei-/Altlabels („Roman & Alicia", „WG", „Büro"); sie werden hier
    # einmal zentral auf die echten Objekt-Einheiten abgebildet, bevor irgend
    # etwas gerechnet wird. Dafür müssen Einheiten und Bezüge früh stehen.
    einheiten, bez = _stammbezug(session, z)
    karte = einheiten_karte(einheiten, bez)
    unbekannt: list[str] = []

    def _merken(namen: list[str]) -> None:
        """Unzugeordnetes sammeln — je Label einmal, Reihenfolge erhalten."""
        for name in namen:
            if name not in unbekannt:
                unbekannt.append(name)

    # CD — Einheiten mit eigenem Kaltwasser-Vollzähler; sie fallen aus dem
    # Haupthaus-Rest heraus. Ohne „WG"-Auflösung, denn die braucht das Ergebnis.
    # Nur eine Vorauswahl: dieselben Zähler laufen unten durch `_ziele`, dort
    # wird Unzugeordnetes gemeldet — hier bliebe es sonst doppelt stehen.
    kalt_einheiten: set[str] = set()
    for zae in zaehler:
        if (_wasser_art(zae) == "Kaltwasser" and zae.typ == "gemessen"
                and zae.hauptzaehler_id):
            kalt_einheiten.update(zuordne_zaehler(zae, karte).ziele)
    haupthaus = [e.bezeichnung for e in einheiten
                 if e.nk_abrechnung and e.bezeichnung not in kalt_einheiten]

    def _ziele(zae: Zaehler | None) -> list[str]:
        """Ziel-Einheiten eines Zählers, auf echte Einheiten normalisiert."""
        if zae is None:
            return []
        treffer = zuordne_zaehler(zae, karte, haupthaus)
        _merken(treffer.unbekannt)
        return treffer.ziele

    # Unterzähler → Zaehlerposten. Verbrauchsscharf einer Einheit zugeordnet,
    # oder (CD) über mehrere Einheiten aufgeteilt (Person·Mietdauer).
    posten = []
    for zae in zaehler:
        art = _wasser_art(zae)
        # N113 - auch der WARMWASSER-REST zaehlt hier mit: Warmwasser ist
        # Kaltwasser, das erhitzt wurde. Die Heizung berechnet nur die Waerme
        # zum Erhitzen - die MENGE gehoert in die Wasserabrechnung. Ohne diese
        # Zeile fehlte den beiden Wohnungen ihr Warmwasseranteil.
        ww_rest = (zae.typ == "rest" and art == "Warmwasser"
                   and verb.get(zae.id) is not None and (verb.get(zae.id) or 0) > 0)
        if not ww_rest and not (zae.typ == "gemessen" and zae.hauptzaehler_id
                and art in _UNTER_ARTEN and verb.get(zae.id) is not None):
            continue
        ziele = _ziele(zae)
        if not ziele:
            continue
        posten.append(wasser.Zaehlerposten(
            name=zae.name, einheit=ziele[0], m3=verb[zae.id],
            art=art, einheiten=ziele))

    # Gartenwasser — Menge aus dem Rest heraus, Kosten trägt der Eigentümer.
    garten_z = next((zae for zae in zaehler if _wasser_art(zae) == "Gartenwasser"), None)
    garten_m3 = (verb.get(garten_z.id) or 0.0) if garten_z else 0.0
    garten_ziele = _ziele(garten_z)
    garten_einheit = garten_ziele[0] if garten_ziele else ""

    # Kostenbestandteile aus den Kostenpositionen des Zeitraums (fehlende = 0).
    betrag_je_art = {p.kostenart: (p.betrag or 0.0) for p in session.exec(
        select(Kostenposition).where(Kostenposition.zeitraum_id == zid)).all()}
    komponenten = {schluessel: round(betrag_je_art.get(kostenart, 0.0), 2)
                   for schluessel, kostenart in _KOMPONENTEN_ART.items()}

    # Bereitschaft: ohne Gesamtverbrauch oder ohne Beträge lässt sich nichts
    # rechnen — dann konkret sagen, was fehlt.
    fehlt = []
    if not gesamt_m3 or gesamt_m3 <= 0:
        fehlt.append("die Hauptzähler-Ablesung (Gesamtverbrauch)")
    if sum(komponenten.values()) <= 0:
        fehlt.append("die Wasserbeträge (Wasser/Abwasser/Niederschlagswasser)")
    if fehlt:
        return {"bereit": False,
                "hinweis": "Es fehlt noch " + " und ".join(fehlt) + "."}

    # Rest-Gewichte (Haupthaus EG+1.OG): Personen·Mietdauer je Einheit, die
    # KEINEN eigenen Kaltwasser-Unterzähler hat. `gewichte("personen", …)`
    # liefert {Partei: Gewicht}; über die Bezüge wird Partei→Einheit abgebildet
    # und je Haupthaus-Einheit summiert.
    #
    # N69 — der Rest ist zuteilbar: hat der Rest-Zähler (typ='rest' im Wasser-
    # Block) explizit Einheiten gesetzt, tragen NUR diese den Rest (weiterhin
    # nach Person·Mietdauer gewichtet); ohne Auswahl gilt der Default (alle
    # Haupthaus-Einheiten ohne eigenen Kaltwasser-Zähler).
    rest_z = next((zae for zae in zaehler if zae.typ == "rest"
                   and _kostenblock(zae.kostenart) == "Wasser"), None)
    rest_wahl = set(_ziele(rest_z))
    partei_einheit = {b.partei: b.einheit for b in bez}
    rest_gewichte: dict[str, float] = {}
    # N113 - der Rest kann nach Personen ODER nach Flaeche verteilt werden;
    # der Nutzer waehlt es oben in der Detailansicht (`?schluessel=`).
    schl = schluessel if schluessel in ("personen", "flaeche") else "personen"
    for partei, gew in verteilung.gewichte(schl, bez, z.start, z.ende).items():
        # Auch hier zählt die echte Einheit — ein Bezug auf ein Altlabel darf
        # keine eigene Rest-Spalte aufmachen.
        treffer = zuordne([partei_einheit.get(partei, "")], karte, haupthaus)
        _merken(treffer.unbekannt)
        einheit = treffer.ziele[0] if treffer.ziele else ""
        erlaubt = einheit not in kalt_einheiten and (not rest_wahl
                                                     or einheit in rest_wahl)
        if einheit and erlaubt:
            rest_gewichte[einheit] = round(rest_gewichte.get(einheit, 0.0) + gew, 4)

    e = wasser.verrechne(komponenten, gesamt_m3, posten, garten_m3, rest_gewichte)

    # Ergebnis auf den Vertrag mappen: je Einheit ihre Zeilen (Art, m³, €,
    # Quelle). Die Art steckt am Zählerposten; der Rest-Anteil ist berechnet.
    name_art = {p.name: p.art for p in posten}
    einheiten_out = []
    for name, daten in e.einheiten.items():
        zeilen = []
        for p in daten["posten"]:
            quelle_txt = p["quelle"]
            if quelle_txt.startswith("Zähler "):
                art = name_art.get(quelle_txt[len("Zähler "):], "Kaltwasser")
                quelle = "gemessen"
            else:
                art, quelle = "Anteil Haupthaus", "berechnet"
            zeilen.append({"art": art, "m3": round(p["m3"], 2),
                           "kosten": p["kosten"], "quelle": quelle})
        einheiten_out.append({"name": name, "zeilen": zeilen,
                              "summe": daten["kosten"]})

    garten = None
    if e.garten_m3 > 0:
        garten = {"einheit": garten_einheit or None, "m3": round(e.garten_m3, 2),
                  "kosten": e.garten_kosten}

    # N101/6 — was sich keiner Einheit zuordnen ließ, wird nicht stillschweigend
    # verschluckt: es erzeugt keine Spalte, aber einen sichtbaren Hinweis.
    warnungen = zuordnungs_warnungen(unbekannt)
    # Was die Verrechnung selbst bemängelt (Unterzähler über dem Hauptzähler,
    # Gartenwasser größer als der Rest, Rest ohne Ziel-Einheit), gehört ebenso
    # in die Ansicht — sonst bleibt es in der Engine stehen.
    warnungen += list(getattr(e, "warnungen", []) or [])

    return {
        "bereit": True,
        "hinweis": "",
        "warnungen": warnungen,
        "schluessel": schl,
        "abgelesen_m3": round(abgelesen_m3, 3) if abgelesen_m3 else None,
        "rechnung_m3": round(float(rechnung_m3), 3) if rechnung_m3 else None,
        # Beide Werte bleiben stehen; die Abweichung wird benannt, damit sie in
        # den Folgejahren geklaert werden kann, statt zu verschwinden.
        "abweichung_m3": (round(abgelesen_m3 - float(rechnung_m3), 3)
                          if rechnung_m3 and abgelesen_m3 else None),
        "kosten": {**komponenten, "gesamt": e.gesamt_kosten,
                   "preis_m3": round(e.preis_m3, 2)},
        "gesamt_m3": round(e.gesamt_m3, 2),
        "garten": garten,
        "einheiten": einheiten_out,
        "rest_m3": round(e.rest_m3, 2),
        "rest_kosten": e.rest_kosten,
        "kontrolle": e.kontrolle,
    }


@router.put("/zeitraeume/{zid}/wasser/rechnungsmenge")
def rechnungsmenge_setzen(zid: int, data: dict,
                          session: Session = Depends(get_session)) -> dict:
    """N116b — die abgerechnete Wassermenge des Bescheids festhalten.

    Sie ersetzt den Zaehlerwert NICHT: der Stand bleibt am Zaehler stehen. Hier
    steht nur, was der Versorger tatsaechlich berechnet hat; die Differenz wird
    als Abweichung ausgewiesen."""
    z = session.get(Zeitraum, zid)
    if not z:
        raise HTTPException(404, "Zeitraum nicht gefunden")
    wert = data.get("rechnung_m3")
    z.wasser_rechnung_m3 = float(wert) if wert not in (None, "") else 0.0
    session.add(z)
    session.commit()
    return {"ok": True, "rechnung_m3": z.wasser_rechnung_m3}


# N185 — die drei Wasser-Bestandteile eines Bescheids (Frisch-/Schmutz-/
# Niederschlagswasser) stehen als eigene Kostenpositionen; der Beleg haengt
# aber nur an der Frischwasser-Position. Wird er geloescht, laeuft
# `belegposten.nachrechnen` nur dort — die zwei Geschwister blieben als
# Handanteil stehen, die Sammelposition zeigt weiter ihre Summe und klappte
# nicht ein. Dieser Endpunkt leert die ganze Sammelposition in einem Zug.
_WASSER_GESCHWISTER = ("Wasser", "Abwasser", "Niederschlagswasser")


def _wasser_positionen(session: Session, zid: int) -> list[Kostenposition]:
    """Die drei Wasser-Bestandteile eines Zeitraums — kanonisch gematcht wie in
    `dokumente._rechnungssumme`, damit dieselben Positionen getroffen werden,
    auf die ein Wasser-Beleg gebucht wird."""
    return [p for p in session.exec(
        select(Kostenposition).where(Kostenposition.zeitraum_id == zid)).all()
        if kostenarten.normalisieren(p.kostenart) in _WASSER_GESCHWISTER]


@router.post("/zeitraeume/{zid}/wasser/leeren")
def wasser_leeren(zid: int, force: bool = False,
                  session: Session = Depends(get_session)) -> dict:
    """N185 — leert die Wasser-Sammelposition, damit ein neuer Bescheid sauber
    einliest: die drei Bestandteile (Frisch-/Schmutz-/Niederschlagswasser)
    werden auf 0 gesetzt und auf `status='offen'` gestellt, noch haengende
    Belege werden geloest (die Datei bleibt in der Cloud), und die geeichte
    Rechnungsmenge wird zurueckgesetzt.

    Die ZAEHLER darunter bleiben unangetastet — sie messen den Verbrauch, nicht
    den Bescheid. Das Nullsetzen ist hier erlaubt, weil es eine bewusste
    Nutzeraktion ist (letzten Beleg entfernt oder „Position leeren").

    Ohne `force` wird nur geleert, wenn KEIN Beleg mehr an einer der drei
    Positionen haengt — so raeumt das Entfernen des letzten Belegs die ganze
    Position ab, ein bloss entfernter Zwischenbeleg (weitere bleiben) aber
    nicht. Mit `force=true` (manueller „Position leeren"-Knopf) wird immer
    geleert."""
    positionen = _wasser_positionen(session, zid)
    if not positionen:
        return {"geleert": False, "grund": "keine Wasser-Positionen"}

    if not force:
        noch_belege = any(belegposten.belege_der_position(session, p.id)
                          for p in positionen if p.id is not None)
        if noch_belege:
            # Es haengen noch Belege — nichts leeren, aber die Summen ehrlich
            # halten (der eben geloeste Beleg ist schon abgezogen).
            for p in positionen:
                belegposten.nachrechnen(session, p)
            session.commit()
            return {"geleert": False, "grund": "es haengen noch Belege"}

    for p in positionen:
        for d in belegposten.belege_der_position(session, p.id):
            d.position_id = None
            session.add(d)
        p.betrag = 0.0
        p.beleg_summe = 0.0
        p.status = "offen"
        session.add(p)

    z = session.get(Zeitraum, zid)
    if z is not None:
        z.wasser_rechnung_m3 = 0.0
        session.add(z)

    session.commit()
    return {"geleert": True, "positionen": len(positionen)}
