"""N142 — die Stromkette eines Abrechnungszeitraums: von kWh über Euro zur
Verteilung auf die Einheiten. Drei Schritte, jeder einzeln ausgewiesen.

    Schritt 1 — Umwandlung in Geld.
        Aus der SolarEdge-Auswertung kommen die drei Anteile (Netz · PV direkt ·
        Akku). Der Netzanteil wird über die **angehängte Rechnung** bepreist, PV
        und Akku über die am Strom-Jahr gepflegten Sätze. Aus den 10.800 kWh
        werden so drei Kostenblöcke mit je eigenem Preis.

    Schritt 2 — Abzug der E-Tankstelle.
        Die Ladungen des Zeitraums werden **taggenau nach den Monaten der
        Periode** gezogen (nicht nach Kalenderjahr) und mit ihrer exakten
        Aufteilung auf die drei Töpfe vorab herausgerechnet. Wer geladen hat,
        spielt hier keine Rolle — das gehört auf die Tankstellenseite. Für die
        Nebenkostenabrechnung zählt allein, dass diese Menge **nicht** auf die
        Bewohner der Einheiten weiterverrechnet wird.

    Schritt 3 — der Rest auf die Einheiten.
        Was übrig bleibt, verteilt sich nach den Zählerwerten; jede Einheit
        trägt denselben Anteil an allen drei Blöcken und damit denselben
        Mischpreis (`strombloecke.verteile`).

Der Endpunkt bleibt **dünn**: er sammelt ein, reicht an `strombloecke` weiter
und gibt jeden Schritt einzeln zurück. Gerechnet wird nicht hier.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from .. import ablesung as ablesung_modul
from .. import strombloecke, verteilung
from ..db import get_session
from ..models import (Ablesung, Dokument, Einheit, Kostenposition, Miete,
                      Objekt, Partei, Stromjahr, Zaehler, Zeitraum)
from .objekte import zeitraum_label_jahr
from .openwb import ladungen as openwb_ladungen
from .tankstelle import erfasste_ladungen
from .zaehler import (_echte_einheiten, _einheiten_karte, _kostenblock,
                      _mit_vorlauf, _parse_einheiten)

log = logging.getLogger("immocalc")
router = APIRouter(prefix="/api", tags=["stromkette"])

# Zähler in dieser Messeinheit tragen die Stromverteilung.
KWH = "kWh"
# Trägt das Strom-Jahr keine Einheit für die Ladungen, bekommt der Abzug diesen
# Namen. Er ist keine Wohnung — er hält die geladene Menge sichtbar aus der
# Verteilung heraus.
EAUTO_VORGABE = "E-Tankstelle"
# Ein zuordnungsloser Zähler, dessen Menge ungefähr der E-Auto-Menge entspricht,
# IST die Ladestation — dafür braucht es keine Warnung.
EAUTO_TOLERANZ = 0.05
# Herkunft an einer Kostenposition (N122).
H_EXTERN, H_EIGEN = "extern", "eigen"


def _zahl(wert: float) -> str:
    """Eine Zahl deutsch geschrieben — die Quellenangaben in den Antworten
    werden gelesen, nicht weitergerechnet."""
    return f"{wert:,.2f}".replace(",", "#").replace(".", ",").replace("#", ".")


def _ct(preis: float) -> str:
    """Ein Preis je kWh in Cent, deutsch geschrieben."""
    return f"{preis * 100:.2f}".replace(".", ",")


# --------------------------------------------------------------------------
# Zähler: Gesamtmenge und Verbrauch je Einheit
# --------------------------------------------------------------------------

def _verbrauch(session: Session, z: Zeitraum) -> tuple[list[Zaehler],
                                                       dict[int, float | None]]:
    """Alle aktiven Zähler des Objekts und ihr interpolierter Verbrauch — genau
    wie in der Ablesungs-Maske, inklusive der Vorlauf-Periode (CCCLXXX)."""
    zaehler = list(session.exec(
        select(Zaehler).where(Zaehler.objekt_id == z.objekt_id, Zaehler.aktiv)
        .order_by(Zaehler.reihenfolge, Zaehler.id)).all())
    zma = [(zae, session.exec(select(Ablesung)
                              .where(Ablesung.zaehler_id == zae.id)
                              .order_by(Ablesung.datum)).all())
           for zae in zaehler]
    zeitraeume = session.exec(
        select(Zeitraum).where(Zeitraum.objekt_id == z.objekt_id)).all()
    zeitraeume_i, _ = _mit_vorlauf(zeitraeume, zma)
    return zaehler, ablesung_modul.verbrauch_je_zaehler(zma, zeitraeume_i, z.id)


def _gesamtzaehler(kwh_zaehler: list[Zaehler]) -> Zaehler | None:
    """Der Zähler, der den Gesamtverbrauch trägt: der, auf den die anderen
    zeigen, sonst der erste ohne eigenen Hauptzähler (wie in der Maske)."""
    haupt_ids = {zae.hauptzaehler_id for zae in kwh_zaehler if zae.hauptzaehler_id}
    return (next((zae for zae in kwh_zaehler
                  if zae.typ != "rest" and zae.id in haupt_ids), None)
            or next((zae for zae in kwh_zaehler
                     if zae.typ != "rest" and not zae.hauptzaehler_id), None))


def _gewichte(session: Session, z: Zeitraum) -> tuple[dict[str, str],
                                                      list[str],
                                                      dict[str, float]]:
    """Einheiten-Karte, Haupthaus-Einheiten und die Person·Mietdauer-Gewichte.

    Dieselbe Grundlage wie beim Wasser (CD): ein Zähler, der mehreren Einheiten
    gehört, teilt seine Menge nach diesen Gewichten."""
    einheiten = list(session.exec(
        select(Einheit).where(Einheit.objekt_id == z.objekt_id)).all())
    mieten = list(session.exec(
        select(Miete).where(Miete.objekt_id == z.objekt_id)).all())
    parteien = list(session.exec(
        select(Partei).where(Partei.objekt_id == z.objekt_id)).all())
    bez = verteilung.bezuege(einheiten, mieten, parteien, z.start, z.ende)
    karte = _einheiten_karte(einheiten, bez)
    haupthaus = [e.bezeichnung for e in einheiten if e.nk_abrechnung]

    partei_einheit = {b.partei: b.einheit for b in bez}
    gewichte: dict[str, float] = {}
    for partei, gew in verteilung.gewichte("personen", bez, z.start,
                                           z.ende).items():
        ziel = _echte_einheiten([partei_einheit.get(partei, "")], karte,
                                haupthaus)
        if ziel:
            gewichte[ziel[0]] = round(gewichte.get(ziel[0], 0.0) + gew, 4)
    return karte, haupthaus, gewichte


def _je_einheit(kwh_zaehler: list[Zaehler], verb: dict[int, float | None],
                gesamt_id: int | None, karte: dict[str, str],
                haupthaus: list[str],
                gewichte: dict[str, float]) -> tuple[dict[str, float],
                                                     list[dict]]:
    """Der kWh-Verbrauch je Einheit — plus die Zähler ohne Zuordnung.

    Der Gesamtzähler zählt nicht mit (er ist die Summe der übrigen). Ein Zähler
    mit mehreren Einheiten teilt seine Menge nach Person·Mietdauer, ersatzweise
    zu gleichen Teilen — dieselbe Regel wie beim Wasser."""
    verbrauch: dict[str, float] = {}
    ohne: list[dict] = []
    for zae in kwh_zaehler:
        menge = verb.get(zae.id)
        if zae.id == gesamt_id or menge is None or menge <= 0:
            continue
        ziele = _echte_einheiten(_parse_einheiten(zae), karte, haupthaus)
        if not ziele:
            ohne.append({"zaehler": zae.name, "kwh": round(menge, 3)})
            continue
        teil = {name: max(0.0, gewichte.get(name, 0.0)) for name in ziele}
        if sum(teil.values()) <= 0:
            teil = {name: 1.0 for name in ziele}
        summe = sum(teil.values())
        for name, gew in teil.items():
            verbrauch[name] = round(verbrauch.get(name, 0.0)
                                    + menge * gew / summe, 3)
    return verbrauch, ohne


# --------------------------------------------------------------------------
# Schritt 1 — aus kWh werden Euro
# --------------------------------------------------------------------------

def _mengen(sj: Stromjahr) -> tuple[float, float, float]:
    """Die drei erfassten SolarEdge-Mengen (Netz · PV · Speicher)."""
    return (sj.netz_kwh or 0.0, sj.solar_kwh or 0.0, sj.akku_kwh or 0.0)


def _anteile(sj: Stromjahr) -> tuple[float, float, float, str]:
    """Die drei SolarEdge-Anteile in Prozent — die, mit denen gerechnet wird.

    Ein eigenes Prozentfeld gibt es im Datenmodell nicht — wohl aber die drei
    Mengen `netz_kwh`, `solar_kwh` und `akku_kwh`. Genau sie sind die Anteile;
    die Prozente ergeben sich daraus.

    Bezugsgröße ist ihre Summe, nicht der Gesamtverbrauch: nur so decken die
    drei Blöcke die ganze Menge ab und es bleibt kein Strom ohne Preis. Decken
    sich beide nicht, sagt das :func:`_anteile_pruefen`."""
    mengen = _mengen(sj)
    summe = sum(mengen)
    if summe <= 0:
        return 0.0, 0.0, 0.0, ""
    netz, pv, akku = (round(m / summe * 100.0, 2) for m in mengen)
    return netz, pv, akku, (f"aus den erfassten Mengen "
                            f"({mengen[0]:.0f} · {mengen[1]:.0f} · "
                            f"{mengen[2]:.0f} kWh)")


def _erfasste_anteile(sj: Stromjahr,
                      gesamt_kwh: float) -> tuple[float, float, float]:
    """Die Anteile, wie der Nutzer sie eingetragen hat — Menge am Gesamt-
    verbrauch. Sie stehen in den Eingabefeldern und gehen deshalb unverändert
    wieder hinein; die gerechneten Anteile (`_anteile`) können davon abweichen,
    wenn die drei zusammen nicht 100 % ergeben."""
    if gesamt_kwh <= 0:
        return 0.0, 0.0, 0.0
    netz, pv, akku = (round(m / gesamt_kwh * 100.0, 2) for m in _mengen(sj))
    return netz, pv, akku


def _anteile_pruefen(sj: Stromjahr, gesamt_kwh: float) -> list[str]:
    """Decken die drei erfassten Mengen den Gesamtverbrauch?

    Ein eigenes Prozentfeld gibt es nicht — ob die SolarEdge-Anteile 100 %
    ergeben, zeigt sich daran, ob ihre Mengen zusammen den Gesamtverbrauch
    treffen. Verteilt wird trotzdem auf 100 %, sonst fehlte Geld."""
    erfasst = ((sj.netz_kwh or 0.0) + (sj.solar_kwh or 0.0)
               + (sj.akku_kwh or 0.0))
    if erfasst <= 0 or gesamt_kwh <= 0:
        return []
    prozent = erfasst / gesamt_kwh * 100.0
    if abs(prozent - 100.0) <= 0.5:
        return []
    return [f"Die erfassten Anteile ergeben zusammen {prozent:.0f} % des "
            f"Gesamtverbrauchs ({_zahl(erfasst)} von {_zahl(gesamt_kwh)} kWh) — "
            "bitte die SolarEdge-Werte prüfen. Verteilt wird trotzdem auf "
            "den vollen Verbrauch."]


def _strompositionen(session: Session, zid: int) -> list[Kostenposition]:
    """Die Kostenpositionen des Zeitraums, die zum Strom gehören."""
    return [p for p in session.exec(select(Kostenposition)
                                    .where(Kostenposition.zeitraum_id == zid)).all()
            if _kostenblock(p.kostenart) == "Strom"]


def _netz_betrag(session: Session, zid: int,
                 positionen: list[Kostenposition]) -> tuple[float, str, list[str]]:
    """Was der zugekaufte Strom laut Rechnung gekostet hat.

    Erste Wahl ist die Kostenposition mit Herkunft „Netzbezug" — dort hat der
    Nutzer die Rechnung bestätigt. Gibt es sie noch nicht, greifen ersatzweise
    die Strom-Belege des Zeitraums mit einem erkannten Betrag; das steht dann
    sichtbar als Herkunft dabei, damit niemand es für gesetzt hält."""
    aus_position = [p for p in positionen
                    if (p.herkunft or "").strip().lower() == H_EXTERN
                    and p.betrag]
    if aus_position:
        betrag = round(sum(p.betrag for p in aus_position), 2)
        namen = " · ".join(sorted({p.kostenart for p in aus_position}))
        return betrag, f"Rechnung {_zahl(betrag)} € (Position „{namen}“)", []

    belege = [d for d in session.exec(select(Dokument)
                                      .where(Dokument.zeitraum_id == zid)).all()
              if d.betrag and _kostenblock(d.kostenart) == "Strom"]
    if not belege:
        return 0.0, "", [
            "Für den Netzbezug liegt noch keine Rechnung vor — bitte den Beleg "
            "an der Strom-Position anhängen und die Herkunft „Netzbezug“ "
            "setzen. Ohne sie lassen sich die kWh nicht in Euro umrechnen."]
    betrag = round(sum(d.betrag for d in belege), 2)
    namen = " · ".join(d.dateiname for d in belege)
    return betrag, f"Beleg {_zahl(betrag)} € ({namen})", [
        f"Der Netzbetrag stammt aus {len(belege)} angehängten Beleg(en), nicht "
        "aus einer bestätigten Position. Bitte an der Strom-Position die Menge "
        "und die Herkunft „Netzbezug“ setzen, damit die Zuordnung eindeutig ist."]


def _eigen_betraege(sj: Stromjahr, pv_kwh: float, akku_kwh: float,
                    positionen: list[Kostenposition]) -> tuple[float, float,
                                                               str, list[str]]:
    """Was PV-Direktverbrauch und Akku-Entnahme kosten.

    Beide haben einen eigenen Satz (`solar_preis`, `akku_preis` am Strom-Jahr) —
    der Akku ist teurer, er will bezahlt und ersetzt werden. Fehlen die Sätze,
    greift ersatzweise eine Kostenposition mit Herkunft „eigene Anlage"; ihr
    Betrag wird dann mengenanteilig auf beide Töpfe gelegt."""
    solar, akku = sj.solar_preis or 0.0, sj.akku_preis or 0.0
    if solar > 0 or akku > 0:
        # Ist nur ein Satz gepflegt, gilt er für beide — besser als ein Topf
        # zum Nulltarif.
        solar = solar or akku
        akku = akku or solar
        return (round(pv_kwh * solar, 2), round(akku_kwh * akku, 2),
                f"Sätze am Strom-Jahr: PV {_ct(solar)} ct/kWh · "
                f"Akku {_ct(akku)} ct/kWh", [])

    aus_position = [p for p in positionen
                    if (p.herkunft or "").strip().lower() == H_EIGEN and p.betrag]
    if aus_position:
        betrag = round(sum(p.betrag for p in aus_position), 2)
        summe = pv_kwh + akku_kwh
        pv_teil = round(betrag * pv_kwh / summe, 2) if summe > 0 else 0.0
        return (pv_teil, round(betrag - pv_teil, 2),
                f"Position „eigene Anlage“ {_zahl(betrag)} €", [
                    "Der eigene Strom hat nur einen Gesamtbetrag — PV und Akku "
                    "wurden mengenanteilig getrennt. Für getrennte Preise die "
                    "Sätze am Strom-Jahr pflegen."])
    return 0.0, 0.0, "", [
        "Für den eigenen Strom ist noch kein Preis hinterlegt (Solar- und "
        "Akku-Satz am Strom-Jahr) — PV und Akku gehen mit 0 € in die "
        "Verteilung ein."]


# --------------------------------------------------------------------------
# Schritt 2 — die E-Tankstelle, ohne Personenbezug
# --------------------------------------------------------------------------

def _aus_wallbox(session: Session, z: Zeitraum) -> dict | None:
    """Die Ladungen des Zeitraums aus dem openWB-Protokoll — taggenau nach den
    Monaten der Periode, nicht nach Kalenderjahr. ``None``, wenn die Box nichts
    Verwertbares liefert."""
    try:
        d = openwb_ladungen(von=z.start, bis=z.ende, session=session)
    except Exception as fehler:            # noqa: BLE001 — Box im Heimnetz
        log.info("Stromkette: Wallbox nicht abrufbar — %s", fehler)
        return None
    if not d.get("ok"):
        return {"hinweis": d.get("hinweis", "")}
    return {
        "netz_kwh": round(d.get("extern_kwh") or 0.0, 3),
        "pv_kwh": round(d.get("pv_kwh") or 0.0, 3),
        "akku_kwh": round(d.get("speicher_kwh") or 0.0, 3),
        "gemessen_kwh": round(d.get("kwh") or 0.0, 3),
        "anzahl": d.get("anzahl") or 0,
        "warnungen": list(d.get("warnungen") or []),
    }


def _aus_ladungen(session: Session, z: Zeitraum) -> float:
    """Die im Tankstellen-Bereich erfassten Ladungen des Zeitraums (kWh).

    Gefiltert wird über das Datum, also nach den Monaten der Abrechnungsperiode
    — nicht nach Kalenderjahr. Auch hier zählt allein die Menge: die Personen
    hinter den Ladungen gehören auf die Tankstellenseite, nicht in die
    Nebenkostenabrechnung."""
    return round(sum(l.kwh or 0.0 for l in erfasste_ladungen(
        session, z.objekt_id, z.start, z.ende)), 3)


def _eauto(session: Session, z: Zeitraum, sj: Stromjahr, netz_p: float,
           pv_p: float, akku_p: float) -> dict:
    """Wie viel im Zeitraum geladen wurde und woraus — in dieser Reihenfolge:
    Wallbox-Protokoll, erfasste Ladungen, Handeingabe am Strom-Jahr."""
    box = _aus_wallbox(session, z)
    if box and "netz_kwh" in box:
        return {**box, "quelle": "wallbox",
                "quelle_text": f"openWB · {box['anzahl']} Ladungen im Zeitraum"}
    hinweis = (box or {}).get("hinweis", "")

    # Ersatzweise die im Tankstellen-Bereich erfassten Ladungen: sie tragen nur
    # die Menge, aufgeteilt wird sie nach den Anteilen aus Schritt 1.
    menge = _aus_ladungen(session, z)
    quelle, text = "ladungen", "erfasste Ladungen der E-Tankstelle im Zeitraum"
    if menge <= 0:
        menge = round((sj.eauto_extern_kwh or 0.0) + (sj.eauto_eigen_kwh or 0.0), 3)
        quelle, text = "hand", "von Hand am Strom-Jahr eingetragen"
    if menge <= 0:
        return {"netz_kwh": 0.0, "pv_kwh": 0.0, "akku_kwh": 0.0,
                "gemessen_kwh": 0.0, "anzahl": 0, "quelle": "keine",
                "quelle_text": hinweis or "keine Ladungen im Zeitraum",
                "warnungen": []}

    warnungen = [
        "Die Aufteilung der Ladungen auf Netz, PV und Akku ist geschätzt "
        "(Anteile aus Schritt 1) — die Wallbox liefert sie sonst taggenau."]
    if hinweis:
        warnungen.append(hinweis)
    if quelle == "hand" and (sj.eauto_extern_kwh or 0.0) > 0:
        # Die Handeingabe kennt nur Netz und „eigen"; der eigene Teil wird auf
        # PV und Akku nach ihren Anteilen aufgeteilt.
        eigen = sj.eauto_eigen_kwh or 0.0
        eigen_summe = pv_p + akku_p
        return {"netz_kwh": round(sj.eauto_extern_kwh or 0.0, 3),
                "pv_kwh": round(eigen * pv_p / eigen_summe, 3) if eigen_summe else 0.0,
                "akku_kwh": round(eigen * akku_p / eigen_summe, 3) if eigen_summe else 0.0,
                "gemessen_kwh": menge, "anzahl": 0, "quelle": quelle,
                "quelle_text": text, "warnungen": warnungen}
    return {"netz_kwh": round(menge * netz_p / 100.0, 3),
            "pv_kwh": round(menge * pv_p / 100.0, 3),
            "akku_kwh": round(menge * akku_p / 100.0, 3),
            "gemessen_kwh": menge, "anzahl": 0, "quelle": quelle,
            "quelle_text": text, "warnungen": warnungen}


# --------------------------------------------------------------------------
# Der Endpunkt
# --------------------------------------------------------------------------

def _block(b: strombloecke.Block) -> dict:
    return {"kwh": round(b.kwh, 3), "betrag": round(b.betrag, 2),
            "preis": round(b.preis, 5)}


def _stromjahr(session: Session, objekt_id: int, jahr: int) -> Stromjahr:
    """Der Strom-Datensatz des Objekt-Jahres — oder ein leerer, ungespeicherter."""
    sj = session.exec(select(Stromjahr).where(Stromjahr.objekt_id == objekt_id,
                                              Stromjahr.jahr == jahr)).first()
    return sj or Stromjahr(objekt_id=objekt_id, jahr=jahr)


def _gesamtmenge(gesamt: Zaehler | None, verb: dict[int, float | None],
                 sj: Stromjahr) -> tuple[float, str]:
    """Der Gesamtverbrauch der Periode — aus dem Zähler, sonst aus dem Jahr."""
    if gesamt is not None and verb.get(gesamt.id):
        return round(verb[gesamt.id], 3), f"Zähler „{gesamt.name}“"
    if sj.gesamt_kwh:
        return round(sj.gesamt_kwh, 3), "Jahreswert am Strom-Jahr"
    return 0.0, ""


@router.get("/zeitraeume/{zid}/stromkette")
def stromkette(zid: int, session: Session = Depends(get_session)) -> dict:
    """Die drei Schritte der Stromverrechnung für einen Abrechnungszeitraum.

    Jeder Schritt wird einzeln ausgewiesen, damit die Oberfläche die Kette
    zeigen kann: was hineingeht und was herauskommt."""
    z = session.get(Zeitraum, zid)
    if not z:
        raise HTTPException(404, "Zeitraum nicht gefunden")
    objekt = session.get(Objekt, z.objekt_id)
    jahr = zeitraum_label_jahr(z.start, z.ende)
    sj = _stromjahr(session, z.objekt_id, jahr)
    warnungen: list[str] = []

    # ---- Zähler ----------------------------------------------------------
    zaehler, verb = _verbrauch(session, z)
    kwh_zaehler = [zae for zae in zaehler if (zae.messeinheit or "") == KWH]
    gesamt_z = _gesamtzaehler(kwh_zaehler)
    gesamt_kwh, quelle_menge = _gesamtmenge(gesamt_z, verb, sj)
    if not gesamt_kwh:
        warnungen.append(
            "Der Gesamtverbrauch der Periode fehlt — bitte den Stromzähler "
            "„Gesamtverbrauch“ ablesen oder den Jahreswert eintragen.")

    # ---- Schritt 1: kWh → Euro -------------------------------------------
    netz_p, pv_p, akku_p, quelle_anteile = _anteile(sj)
    if not quelle_anteile:
        warnungen.append(
            "Die SolarEdge-Anteile sind noch nicht erfasst — bitte Netz, PV "
            "und Speicher am Strom-Jahr eintragen. Ohne sie lassen sich die "
            "kWh keinem Preis zuordnen.")
    erfasst = _erfasste_anteile(sj, gesamt_kwh)
    warnungen += _anteile_pruefen(sj, gesamt_kwh)
    # Erst die Mengen (die Anteile am Gesamtverbrauch), dann das Geld: der Preis
    # des eigenen Stroms hängt an eben diesen Mengen.
    bloecke, hinweise = strombloecke.bloecke_aus_solaredge(
        gesamt_kwh, netz_p, pv_p, akku_p)
    warnungen += hinweise
    positionen = _strompositionen(session, zid)
    bloecke.netz.betrag, quelle_betrag, hinweise = _netz_betrag(
        session, zid, positionen)
    warnungen += hinweise
    (bloecke.pv.betrag, bloecke.akku.betrag,
     quelle_eigen, hinweise) = _eigen_betraege(
        sj, bloecke.pv.kwh, bloecke.akku.kwh, positionen)
    warnungen += hinweise

    # ---- Schritt 2: die E-Tankstelle vorab -------------------------------
    eauto = _eauto(session, z, sj, netz_p, pv_p, akku_p)
    warnungen += eauto.pop("warnungen", [])
    eauto_einheit = (sj.eauto_einheit or "").strip() or EAUTO_VORGABE
    eauto_kwh = round(eauto["netz_kwh"] + eauto["pv_kwh"] + eauto["akku_kwh"], 3)

    # ---- Schritt 3: der Rest nach Zählerwerten ---------------------------
    karte, haupthaus, gewichte = _gewichte(session, z)
    verbrauch, ohne = _je_einheit(kwh_zaehler, verb, gesamt_z.id if gesamt_z
                                  else None, karte, haupthaus, gewichte)
    # Ein zuordnungsloser Zähler in der Größenordnung der Ladungen IST die
    # Ladestation — sie steht in Schritt 2 und braucht keine Einheit. Er zählt
    # deshalb weder als offener Fund noch als fehlende Zuordnung.
    grenze = max(1.0, eauto_kwh * EAUTO_TOLERANZ)
    ladezaehler = next((o for o in ohne
                        if abs(o["kwh"] - eauto_kwh) <= grenze), None) \
        if eauto_kwh > 0 else None
    offen = [o for o in ohne if o is not ladezaehler]
    warnungen += [f"„{o['zaehler']}“ gehört zu keiner Einheit dieses Objekts — "
                  "die Zuordnung bitte am Zähler nachtragen." for o in offen]

    e = strombloecke.verteile(
        bloecke, verbrauch, eauto_einheit=eauto_einheit if eauto_kwh > 0 else "",
        eauto_netz_kwh=eauto["netz_kwh"], eauto_pv_kwh=eauto["pv_kwh"],
        eauto_akku_kwh=eauto["akku_kwh"])
    warnungen += e.warnungen

    je_einheit = {name: {"kwh": e.kwh(name), "netz_kwh": e.netz_kwh.get(name, 0.0),
                         "pv_kwh": e.pv_kwh.get(name, 0.0),
                         "akku_kwh": e.akku_kwh.get(name, 0.0),
                         "betrag": betrag}
                  for name, betrag in e.kosten.items() if name != eauto_einheit}
    summe = round(sum(zeile["betrag"] for zeile in je_einheit.values()), 2)
    eauto_betrag = round(e.kosten.get(eauto_einheit, 0.0), 2)

    return {
        "zeitraum": {"id": z.id, "start": z.start.isoformat(),
                     "ende": z.ende.isoformat(), "jahr": jahr,
                     "label": f"{z.start:%d.%m.%Y} – {z.ende:%d.%m.%Y}"},
        "objekt": objekt.slug if objekt else "",
        "schritt1": {
            "gesamt_kwh": gesamt_kwh, "quelle_menge": quelle_menge,
            "netz_prozent": netz_p, "pv_prozent": pv_p,
            "speicher_prozent": akku_p,
            # Was eingetragen wurde (Menge am Gesamtverbrauch) — die Zahlen der
            # Eingabefelder. Ergeben sie 100 %, sind sie mit den gerechneten
            # Anteilen identisch.
            "netz_erfasst": erfasst[0], "pv_erfasst": erfasst[1],
            "speicher_erfasst": erfasst[2],
            "erfasst_summe": round(sum(erfasst), 2),
            "quelle_anteile": quelle_anteile,
            "netz": _block(bloecke.netz), "pv": _block(bloecke.pv),
            "akku": _block(bloecke.akku),
            "betrag": bloecke.betrag,
            "quelle_betrag": quelle_betrag, "quelle_eigen": quelle_eigen,
        },
        "schritt2": {
            "eauto_kwh": eauto_kwh, "gemessen_kwh": eauto["gemessen_kwh"],
            "netz_kwh": eauto["netz_kwh"], "pv_kwh": eauto["pv_kwh"],
            "akku_kwh": eauto["akku_kwh"], "betrag": eauto_betrag,
            "quelle": eauto["quelle"], "quelle_text": eauto["quelle_text"],
            "einheit": eauto_einheit, "anzahl": eauto["anzahl"],
            # Der Zähler, der dieselbe Menge ausweist — der Gegenbeleg zur
            # Ladeprotokoll-Zahl, ohne eigene Einheit.
            "zaehler": (ladezaehler or {}).get("zaehler", ""),
            "zaehler_kwh": (ladezaehler or {}).get("kwh"),
            "beruecksichtigt": bool(eauto_kwh > 0 and e.eauto),
        },
        "schritt3": {
            "je_einheit": je_einheit, "summe": summe,
            "rest_kwh": round(bloecke.kwh - eauto_kwh, 3),
            "ohne_einheit": offen,
        },
        "kontrolle": {
            "gesamt": e.gesamt, "schritt1_betrag": bloecke.betrag,
            "verteilt": round(summe + eauto_betrag, 2),
            "differenz": round(e.gesamt - bloecke.betrag, 2),
            "stimmt": abs(e.gesamt - bloecke.betrag) < 0.005,
        },
        "eigenverbrauchsquote": e.eigenverbrauchsquote,
        "warnungen": warnungen,
    }
