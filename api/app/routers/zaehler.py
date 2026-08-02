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
from ..deps import objekt_holen
from ..models import (Ablesung, Einheit, Kostenposition, Miete, Objekt, Partei,
                      Zaehler, Zeitraum)

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


def _parse_einheiten(z: Zaehler) -> list[str]:
    """CD — die Einheiten dieses Zählers als Liste. Aus dem komma-separierten
    Feld `einheiten` (getrimmt, Leere raus); ist es leer, fällt es auf den
    Einzelwert `einheit_bezug` zurück (leer → leere Liste)."""
    liste = [t.strip() for t in (z.einheiten or "").split(",") if t.strip()]
    if liste:
        return liste
    return [z.einheit_bezug] if z.einheit_bezug else []

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
                 "hauptzaehler_id", "reihenfolge", "aktiv", "notiz"):
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
            "einheiten": _parse_einheiten(zae),
            "kostenblock": _kostenblock(zae.kostenart),
            "typ": zae.typ, "hauptzaehler_id": zae.hauptzaehler_id,
            "vorwert": None if not vorwert else {
                "stand": round(vorwert["randwert"], 3),
                "datum": vorwert["datum"].isoformat()},
            "ablesung": None if not erfasst else {
                "id": erfasst.id, "datum": erfasst.datum.isoformat(),
                "stand": erfasst.stand},
            "verbrauch": None if verb.get(zae.id) is None
            else round(verb[zae.id], 3),
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


@router.post("/zeitraeume/{zid}/ablesung/uebernehmen")
def uebernehmen(zid: int, data: UebernahmeIn,
                session: Session = Depends(get_session)) -> dict:
    """Trägt den interpolierten Verbrauch einer Kostenart als Verteilung in die
    NK-Kostenposition ein. Bei `schluessel='verbrauch'` werden die Gewichte je
    Partei aus den Zählern gebildet (Untermesser/Rest, gruppiert nach
    `einheit_bezug`); bei jedem anderen Schlüssel werden sie aus den Stammdaten
    abgeleitet. Der Betrag (aus dem Beleg) bleibt unberührt — nur die Verteilung
    wird gesetzt. Eine bestehende Position wird aktualisiert, sonst angelegt."""
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
    if data.schluessel == "verbrauch":
        zeitraeume = session.exec(
            select(Zeitraum).where(Zeitraum.objekt_id == z.objekt_id)).all()
        zma = [(zae, session.exec(select(Ablesung).where(
                Ablesung.zaehler_id == zae.id)).all()) for zae in zaehler]
        # Gleiche Vorlauf-Periode wie in der Maske: der Anfangsstand zählt so auch
        # bei der Übernahme in die erste Abrechnung mit (CCCLXXX).
        zeitraeume_i, _ = _mit_vorlauf(zeitraeume, zma)
        verb = ablesung.verbrauch_je_zaehler(zma, zeitraeume_i, zid)
        anteile = {}
        for zae in zaehler:
            # Der Gesamtzähler (ohne einheit_bezug) ist die Kontrollsumme, keine
            # Partei — nur die zugeordneten Unter-/Rest-Zähler tragen Gewicht.
            if zae.einheit_bezug and verb.get(zae.id):
                anteile[zae.einheit_bezug] = round(
                    anteile.get(zae.einheit_bezug, 0.0) + verb[zae.id], 4)

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
            "position_id": pos.id}


def _zeige(session: Session, z: Zaehler) -> dict:
    abls = session.exec(select(Ablesung).where(Ablesung.zaehler_id == z.id)
                        .order_by(Ablesung.datum)).all()
    # CCCLXXX — der Anfangsstand (Notiz-Markierung, sonst der früheste untaggte
    # Stand) kommt mit, damit die Konfig-Maske ihn ohne Extra-Abfrage zeigt.
    anfang = next((a for a in abls if (a.notiz or "") == ANFANGSSTAND), None) \
        or next((a for a in abls if a.zeitraum_id is None), None)
    return {"id": z.id, "name": z.name, "kostenart": z.kostenart,
            "einheit_bezug": z.einheit_bezug, "einheiten": _parse_einheiten(z),
            "kostenblock": _kostenblock(z.kostenart),
            "art": z.art, "messeinheit": z.messeinheit,
            "typ": z.typ, "hauptzaehler_id": z.hauptzaehler_id,
            "reihenfolge": z.reihenfolge, "aktiv": z.aktiv, "notiz": z.notiz,
            "ablesungen": len(abls),
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

# N101/6 — Alt-Label der früheren Wohngemeinschaft. Es steht für keine Einheit
# mehr, sondern für den gemeinsam genutzten Haupthaus-Teil.
_ALT_WG = "wg"


def _label_schluessel(name: str) -> str:
    """Vergleichsform eines Einheiten-/Partei-Labels: Leerraum vereinheitlicht,
    Groß-/Kleinschreibung egal. Nur zum Nachschlagen — ausgegeben wird immer die
    echte, unveränderte Bezeichnung der Einheit."""
    return " ".join((name or "").split()).casefold()


def _einheiten_karte(einheiten: list[Einheit],
                     bezuege: list[verteilung.Bezug]) -> dict[str, str]:
    """Abbildung „Label → echte Einheiten-Bezeichnung".

    Zwei Quellen, in dieser Reihenfolge: die Bezeichnung einer Einheit zeigt auf
    sich selbst; ein Partei-Name zeigt auf die Einheit, in der diese Partei im
    Zeitraum wohnt (`verteilung.bezuege`). So landen Alt-Labels wie
    „Roman & Alicia" in der Spalte ihrer Einheit statt als eigene Spalte.
    """
    karte = {_label_schluessel(e.bezeichnung): e.bezeichnung for e in einheiten}
    karte.pop("", None)
    for b in bezuege:
        partei = _label_schluessel(b.partei)
        ziel = karte.get(_label_schluessel(b.einheit))
        if partei and ziel and partei not in karte:
            karte[partei] = ziel
    return karte


def _echte_einheiten(namen: list[str], karte: dict[str, str],
                     haupthaus: list[str],
                     unbekannt: dict[str, None] | None = None) -> list[str]:
    """Normalisiert eine Liste von Ziel-Labels auf echte Objekt-Einheiten.

    Exakter Treffer → die Einheit selbst; Partei-Label → ihre Einheit; das
    überholte „WG" → die Haupthaus-Einheiten (die ohne eigenen Kaltwasser-
    Unterzähler). Alles andere wird weggelassen — eine Phantom-Spalte wäre
    schlimmer als eine fehlende Zuordnung — und in `unbekannt` vermerkt.
    Reihenfolge bleibt erhalten, Dopplungen fallen weg.

    Hat das Objekt gar keine Einheiten hinterlegt, gibt es nichts zu
    normalisieren — dann bleiben die Namen unangetastet (sonst verlöre eine
    reine Partei-Abrechnung ihre Spalten und die Kontrollsumme).
    """
    if not karte:
        return [n for i, n in enumerate(namen) if n and n not in namen[:i]]
    out: list[str] = []
    for name in namen:
        s = _label_schluessel(name)
        treffer = karte.get(s)
        if treffer:
            ziele = [treffer]
        elif s == _ALT_WG and haupthaus:
            ziele = list(haupthaus)
        else:
            ziele = []
            if unbekannt is not None and name:
                unbekannt.setdefault(name, None)
        for ziel in ziele:
            if ziel not in out:
                out.append(ziel)
    return out


@router.get("/zeitraeume/{zid}/wasser")
def wasser_detail(zid: int, session: Session = Depends(get_session)) -> dict:
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

    # N101/6 — die Spalten sind Einheiten, keine Parteien. Alte Zähler tragen
    # noch Partei-/Altlabels („Roman & Alicia", „WG", „Büro"); sie werden hier
    # einmal zentral auf die echten Objekt-Einheiten abgebildet, bevor irgend
    # etwas gerechnet wird. Dafür müssen Einheiten und Bezüge früh stehen.
    einheiten = list(session.exec(
        select(Einheit).where(Einheit.objekt_id == z.objekt_id)).all())
    mieten = list(session.exec(
        select(Miete).where(Miete.objekt_id == z.objekt_id)).all())
    parteien = list(session.exec(
        select(Partei).where(Partei.objekt_id == z.objekt_id)).all())
    bez = verteilung.bezuege(einheiten, mieten, parteien, z.start, z.ende)
    karte = _einheiten_karte(einheiten, bez)
    unbekannt: dict[str, None] = {}

    # CD — Einheiten mit eigenem Kaltwasser-Vollzähler; sie fallen aus dem
    # Haupthaus-Rest heraus. Ohne „WG"-Auflösung, denn die braucht das Ergebnis.
    kalt_einheiten: set[str] = set()
    for zae in zaehler:
        if (_wasser_art(zae) == "Kaltwasser" and zae.typ == "gemessen"
                and zae.hauptzaehler_id):
            kalt_einheiten.update(_echte_einheiten(_parse_einheiten(zae), karte, []))
    haupthaus = [e.bezeichnung for e in einheiten
                 if e.nk_abrechnung and e.bezeichnung not in kalt_einheiten]

    def _ziele(zae: Zaehler | None) -> list[str]:
        """Ziel-Einheiten eines Zählers, auf echte Einheiten normalisiert."""
        if zae is None:
            return []
        return _echte_einheiten(_parse_einheiten(zae), karte, haupthaus, unbekannt)

    # Unterzähler → Zaehlerposten. Verbrauchsscharf einer Einheit zugeordnet,
    # oder (CD) über mehrere Einheiten aufgeteilt (Person·Mietdauer).
    posten = []
    for zae in zaehler:
        art = _wasser_art(zae)
        if not (zae.typ == "gemessen" and zae.hauptzaehler_id
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
    for partei, gew in verteilung.gewichte("personen", bez, z.start, z.ende).items():
        # Auch hier zählt die echte Einheit — ein Bezug auf ein Altlabel darf
        # keine eigene Rest-Spalte aufmachen.
        ziel = _echte_einheiten([partei_einheit.get(partei, "")], karte,
                                haupthaus, unbekannt)
        einheit = ziel[0] if ziel else ""
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
    warnungen = [f"„{name}“ gehört zu keiner Einheit dieses Objekts — die"
                 " Zuordnung bitte am Zähler nachtragen." for name in unbekannt]

    return {
        "bereit": True,
        "hinweis": "",
        "warnungen": warnungen,
        "kosten": {**komponenten, "gesamt": e.gesamt_kosten,
                   "preis_m3": round(e.preis_m3, 2)},
        "gesamt_m3": round(e.gesamt_m3, 2),
        "garten": garten,
        "einheiten": einheiten_out,
        "rest_m3": round(e.rest_m3, 2),
        "rest_kosten": e.rest_kosten,
        "kontrolle": e.kontrolle,
    }
