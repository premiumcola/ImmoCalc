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

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from .. import ablesung as ablesung_modul
from .. import strombloecke, verteilung
from ..db import get_session
from ..einheitenzuordnung import (karte as einheiten_karte,
                                  warnungen as zuordnungs_warnungen, zuordne,
                                  zuordne_zaehler)
from ..models import (Ablesung, Dokument, Einheit, Kostenposition, Miete,
                      Objekt, Partei, Stromjahr, Zaehler, Zeitraum)
from .objekte import zeitraum_label_jahr
from .openwb import ladungen as openwb_ladungen
from .tankstelle import erfasste_ladungen
from .zaehler import _eauto_zaehler, _kostenblock, _mit_vorlauf
from ..deps import zeitraum_holen
# N378 — die reine Rechnung liegt in `app/stromkette.py`; hier wird nur
# eingesammelt und weitergereicht.
from ..stromkette import (EAUTO_TOLERANZ, EAUTO_VORGABE, H_EIGEN,
                          H_EXTERN, KWH, _anteile, _anteile_pruefen,
                          _beleg_karte, _block, _ct, _erfasste_anteile,
                          _geeichte_menge, _gesamtmenge, _gesamtzaehler,
                          _herkunft, _je_einheit, _verteile, _zahl)

log = logging.getLogger("immocalc")
router = APIRouter(prefix="/api", tags=["stromkette"])



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


def _gewichte(session: Session, z: Zeitraum) -> tuple[dict[str, str],
                                                      list[str],
                                                      dict[str, float],
                                                      list[str]]:
    """Einheiten-Karte, Haupthaus-Einheiten, die Person·Mietdauer-Gewichte —
    und die Labels, die sich keiner Einheit zuordnen ließen.

    Dieselbe Grundlage wie beim Wasser (CD): ein Zähler, der mehreren Einheiten
    gehört, teilt seine Menge nach diesen Gewichten.

    N288-B4 — eine Partei, deren Einheit sich nicht auflösen lässt, verlor hier
    ihr Gewicht lautlos: ihr Anteil fiel den übrigen zu, ohne dass es jemand
    sah. Das Unzugeordnete kommt jetzt mit heraus und wird gemeldet."""
    einheiten = list(session.exec(
        select(Einheit).where(Einheit.objekt_id == z.objekt_id)).all())
    mieten = list(session.exec(
        select(Miete).where(Miete.objekt_id == z.objekt_id)).all())
    parteien = list(session.exec(
        select(Partei).where(Partei.objekt_id == z.objekt_id)).all())
    bez = verteilung.bezuege(einheiten, mieten, parteien, z.start, z.ende)
    karte = einheiten_karte(einheiten, bez)
    haupthaus = [e.bezeichnung for e in einheiten if e.nk_abrechnung]

    partei_einheit = {b.partei: b.einheit for b in bez}
    gewichte: dict[str, float] = {}
    unbekannt: list[str] = []
    for partei, gew in verteilung.gewichte("personen", bez, z.start,
                                           z.ende).items():
        treffer = zuordne([partei_einheit.get(partei, "")], karte, haupthaus)
        for name in treffer.unbekannt:
            if name not in unbekannt:
                unbekannt.append(name)
        if treffer.ziele:
            ziel = treffer.ziele[0]
            gewichte[ziel] = round(gewichte.get(ziel, 0.0) + gew, 4)
    return karte, haupthaus, gewichte, unbekannt


# --------------------------------------------------------------------------
# Schritt 1 — aus kWh werden Euro
# --------------------------------------------------------------------------


def _strompositionen(session: Session, zid: int) -> list[Kostenposition]:
    """Die Kostenpositionen des Zeitraums, die zum Strom gehören."""
    return [p for p in session.exec(select(Kostenposition)
                                    .where(Kostenposition.zeitraum_id == zid)).all()
            if _kostenblock(p.kostenart) == "Strom"]


def _angehaengte_belege(session: Session,
                        positionen: list[Kostenposition]) -> str:
    """Die Dateinamen der Belege, die an diesen Positionen hängen."""
    ids = [p.id for p in positionen if p.id]
    if not ids:
        return ""
    belege = session.exec(select(Dokument)
                          .where(Dokument.position_id.in_(ids))).all()
    return " · ".join(sorted({d.dateiname for d in belege if d.dateiname}))


def _netz_belege(session: Session, zid: int,
                 positionen: list[Kostenposition]) -> list[dict]:
    """Die Belege, aus denen der Netzbetrag gebildet ist — als Karten (N192).

    Dieselbe Vorrangfolge wie :func:`_netz_betrag`: erst die Belege an einer
    bestätigten externen Strom-Position, sonst die Strom-Belege des Zeitraums
    mit erkanntem Betrag. So zeigt der Hinweis genau die Belege, die gerade in
    die Summe eingehen — und lässt einen doppelten (z. B. reine Abschläge)
    herausnehmen."""
    aus_position = [p for p in positionen
                    if (p.herkunft or "").strip().lower() == H_EXTERN
                    and p.betrag]
    if aus_position:
        ids = [p.id for p in aus_position if p.id]
        belege = list(session.exec(select(Dokument)
                                   .where(Dokument.position_id.in_(ids))).all())
    else:
        belege = [d for d in session.exec(select(Dokument)
                                          .where(Dokument.zeitraum_id == zid)).all()
                  if d.betrag and _kostenblock(d.kostenart) == "Strom"]
    return [_beleg_karte(d) for d in belege if d.id]


def _netz_betrag(session: Session, zid: int,
                 positionen: list[Kostenposition]) -> tuple[float | None, str,
                                                            list[str], dict]:
    """Was der zugekaufte Strom laut Rechnung gekostet hat.

    Erste Wahl ist die Kostenposition mit Herkunft „Netzbezug" — dort hat der
    Nutzer die Rechnung bestätigt. Gibt es sie noch nicht, greifen ersatzweise
    die Strom-Belege des Zeitraums mit einem erkannten Betrag; das steht dann
    sichtbar als Herkunft dabei, damit niemand es für gesetzt hält.

    Fehlt der Betrag ganz, kommt ``None`` zurück — **nicht** 0,00 €. Eine Null
    läse sich wie „der Netzstrom kostet nichts"; dass die Rechnung noch fehlt,
    ist etwas anderes und steht als Warnung dabei."""
    aus_position = [p for p in positionen
                    if (p.herkunft or "").strip().lower() == H_EXTERN
                    and p.betrag]
    if aus_position:
        betrag = round(sum(p.betrag for p in aus_position), 2)
        namen = " · ".join(sorted({p.kostenart for p in aus_position}))
        beleg = _angehaengte_belege(session, aus_position)
        text = f"Rechnung {_zahl(betrag)} € (Position „{namen}“)"
        return betrag, text, [], _herkunft(namen, beleg, text)

    belege = [d for d in session.exec(select(Dokument)
                                      .where(Dokument.zeitraum_id == zid)).all()
              if d.betrag and _kostenblock(d.kostenart) == "Strom"]
    if not belege:
        return None, "", [
            "Für den Netzbezug liegt noch keine Rechnung vor — bitte den Beleg "
            "an der Strom-Position anhängen und die Herkunft „Netzbezug“ "
            "setzen. Ohne sie lassen sich die kWh nicht in Euro umrechnen."
        ], _herkunft()
    betrag = round(sum(d.betrag for d in belege), 2)
    namen = " · ".join(d.dateiname for d in belege)
    arten = " · ".join(sorted({d.kostenart for d in belege if d.kostenart}))
    text = f"Beleg {_zahl(betrag)} € ({namen})"
    return betrag, text, [
        f"Der Netzbetrag stammt aus {len(belege)} angehängten Beleg(en), nicht "
        "aus einer bestätigten Position. Bitte an der Strom-Position die Menge "
        "und die Herkunft „Netzbezug“ setzen, damit die Zuordnung eindeutig ist."
    ], _herkunft(arten, namen, text)


# N158 — der eigene Strom wird 10 % unter dem Netzpreis verkauft. Feste Vorgabe
# des Betreibers, gilt je Abrechnungszeitraum und fuer PV wie Akku gleichermassen.
# Bezugsgroesse ist der Durchschnittspreis des Netzbezugs INKLUSIVE Grundgebuehr
# (Betrag je Menge) — nicht der reine Arbeitspreis.
# N313 — der Rabatt stand hier ein zweites Mal, samt Formel. Wird er
# einmal geändert, rechnen Mieterabrechnung und Fahrerrechnung
# verschieden — und beides sind versendete Dokumente. Jetzt gilt die
# eine Fassung aus `tanken.satz`, die `routers/tankstelle.py` schon
# benutzt.
from ..tanken.satz import EIGEN_RABATT, eigen_satz  # noqa: E402


def _eigen_betraege(session: Session, sj: Stromjahr, pv_kwh: float,
                    akku_kwh: float, netz_preis: float | None,
                    positionen: list[Kostenposition]) -> tuple[float | None,
                                                               float | None, str,
                                                               list[str], dict,
                                                               dict]:
    """Was PV-Direktverbrauch und Akku-Entnahme kosten.

    Beide haben einen eigenen Satz (`solar_preis`, `akku_preis` am Strom-Jahr) —
    der Akku ist teurer, er will bezahlt und ersetzt werden. Fehlen die Sätze,
    greift ersatzweise eine Kostenposition mit Herkunft „eigene Anlage"; ihr
    Betrag wird dann mengenanteilig auf beide Töpfe gelegt.

    Ist weder ein Satz noch eine Position da, kommt ``None`` zurück — nicht
    0,00 €. Der eigene Strom ist nicht umsonst, sein Preis ist nur noch nicht
    gepflegt; das ist eine Lücke und keine Zahl.

    PV und Akku bekommen **je eigene** Herkunft: an der PV-Zeile steht der
    PV-Satz, an der Akku-Zeile der Akku-Satz. Beide Sätze an beiden Zeilen
    stünden zweimal da und ließen offen, welcher für welche gilt."""
    solar, akku = sj.solar_preis or 0.0, sj.akku_preis or 0.0
    if solar > 0 or akku > 0:
        # Ist nur ein Satz gepflegt, gilt er für beide — besser als ein Topf
        # zum Nulltarif.
        solar = solar or akku
        akku = akku or solar
        return (round(pv_kwh * solar, 2), round(akku_kwh * akku, 2),
                f"Sätze am Strom-Jahr: PV {_ct(solar)} ct/kWh · "
                f"Akku {_ct(akku)} ct/kWh", [],
                _herkunft("Strom-Jahr", "",
                          f"Satz am Strom-Jahr: {_ct(solar)} ct/kWh"),
                _herkunft("Strom-Jahr", "",
                          f"Satz am Strom-Jahr: {_ct(akku)} ct/kWh"))

    aus_position = [p for p in positionen
                    if (p.herkunft or "").strip().lower() == H_EIGEN and p.betrag]
    if aus_position:
        betrag = round(sum(p.betrag for p in aus_position), 2)
        summe = pv_kwh + akku_kwh
        pv_teil = round(betrag * pv_kwh / summe, 2) if summe > 0 else 0.0
        akku_teil = round(betrag - pv_teil, 2)
        namen = " · ".join(sorted({p.kostenart for p in aus_position}))
        beleg = _angehaengte_belege(session, aus_position)
        # Je Zeile ihr eigener Anteil an derselben Position — so trägt jede
        # Zahl ihre Herkunft, ohne dass dieselbe Summe zweimal dasteht.
        def teil_text(teil: float) -> str:
            return (f"Position „{namen}“ · {_zahl(teil)} € von "
                    f"{_zahl(betrag)} € (mengenanteilig)")
        return (pv_teil, akku_teil, f"Position „{namen}“ {_zahl(betrag)} €", [
                    "Der eigene Strom hat nur einen Gesamtbetrag — PV und Akku "
                    "wurden mengenanteilig getrennt. Für getrennte Preise die "
                    "Sätze am Strom-Jahr pflegen."],
                _herkunft(namen, beleg, teil_text(pv_teil)),
                _herkunft(namen, beleg, teil_text(akku_teil)))
    # N158 — ohne gepflegten Satz gilt die feste Regel: 10 % unter dem
    # Durchschnittspreis des Netzbezugs. Damit steht hier ein Betrag statt einer
    # Luecke, und zwar derselbe, den auch die E-Tankstelle abrechnet.
    if netz_preis and netz_preis > 0:
        satz = eigen_satz(netz_preis)
        text = (f"{_ct(satz)} ct/kWh — 10 % unter dem Netzpreis "
                f"({_ct(netz_preis)} ct/kWh, inkl. Grundgebühr)")
        return (round(pv_kwh * satz, 2), round(akku_kwh * satz, 2),
                text, [], _herkunft("Regel", "", text), _herkunft("Regel", "", text))
    return None, None, "", [
        "Für den eigenen Strom lässt sich noch kein Preis bilden: er folgt mit "
        "10 % Abschlag dem Netzpreis, und der steht noch nicht fest."
    ], _herkunft(), _herkunft()


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


def _eauto_aus_zaehler(session: Session, z: Zeitraum) -> float:
    """N166 — die geladene Menge aus dem Stand des E-Tankstellen-Zählers (kWh).

    Seit N157 zieht die Zählermaske die Wallbox-Menge und legt sie als Ablesung
    dieses Zählers ab. Der Stand ist damit die eine, sichtbare Wahrheit — und er
    bleibt stehen, wenn die Box gerade stumm ist. Deshalb liest die Stromkette
    hier den Zähler, statt die Box ein zweites Mal zu fragen; sonst könnten die
    Zählermaske und die Kette bei stummer Box zwei verschiedene Mengen zeigen.
    0.0, wenn kein Zähler oder kein Stand für den Zeitraum da ist."""
    zae = _eauto_zaehler(session, z.objekt_id)
    if not zae:
        return 0.0
    abls = session.exec(select(Ablesung).where(Ablesung.zaehler_id == zae.id)
                        .order_by(Ablesung.datum)).all()
    zeitraeume = session.exec(
        select(Zeitraum).where(Zeitraum.objekt_id == z.objekt_id)).all()
    zeitraeume_i, _ = _mit_vorlauf(zeitraeume, [(zae, abls)])
    verb = ablesung_modul.verbrauch_je_zaehler([(zae, abls)], zeitraeume_i, z.id)
    return round(verb.get(zae.id) or 0.0, 3)


def _eauto(session: Session, z: Zeitraum, sj: Stromjahr, netz_p: float,
           pv_p: float, akku_p: float) -> dict:
    """Wie viel im Zeitraum geladen wurde und woraus — in dieser Reihenfolge:
    Wallbox-Protokoll, erfasste Ladungen, Handeingabe am Strom-Jahr."""
    box = _aus_wallbox(session, z)
    if box and "netz_kwh" in box:
        return {**box, "quelle": "wallbox",
                "quelle_text": f"openWB · {box['anzahl']} Ladungen im Zeitraum"}
    hinweis = (box or {}).get("hinweis", "")

    # N166 — zuerst der Zählerstand (dieselbe Zahl wie in der Zählermaske,
    # zuletzt aus der Box gezogen); erst danach die erfassten Ladungen und die
    # Handeingabe. So zeigen Maske und Kette bei stummer Box nicht zwei Mengen.
    menge = _eauto_aus_zaehler(session, z)
    quelle, text = "zaehler", "Stand des E-Tankstellen-Zählers (Wallbox-Menge)"
    if menge <= 0:
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


def _stromjahr(session: Session, objekt_id: int, jahr: int) -> Stromjahr:
    """Der Strom-Datensatz des Objekt-Jahres — oder ein leerer, ungespeicherter."""
    sj = session.exec(select(Stromjahr).where(Stromjahr.objekt_id == objekt_id,
                                              Stromjahr.jahr == jahr)).first()
    return sj or Stromjahr(objekt_id=objekt_id, jahr=jahr)


# --------------------------------------------------------------------------
# N173 — zwei Netzsätze: Verteilung (Mieter) und geeicht (E-Auto)
# --------------------------------------------------------------------------


@router.get("/zeitraeume/{zid}/stromkette")
def stromkette(session: Session = Depends(get_session),
              z: Zeitraum = Depends(zeitraum_holen)) -> dict:
    """Die drei Schritte der Stromverrechnung für einen Abrechnungszeitraum.

    Jeder Schritt wird einzeln ausgewiesen, damit die Oberfläche die Kette
    zeigen kann: was hineingeht und was herauskommt."""
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
    positionen = _strompositionen(session, z.id)
    netz_betrag, quelle_betrag, hinweise, h_netz = _netz_betrag(
        session, z.id, positionen)
    warnungen += hinweise
    (pv_betrag, akku_betrag, quelle_eigen,
     hinweise, h_pv, h_akku) = _eigen_betraege(
        session, sj, bloecke.pv.kwh, bloecke.akku.kwh,
        (netz_betrag / bloecke.netz.kwh) if (netz_betrag and bloecke.netz.kwh) else None,
        positionen)
    warnungen += hinweise
    # Gerechnet wird mit 0 €, wo noch kein Betrag da ist — die Kette soll nicht
    # abreißen. Nach außen bleibt der fehlende Betrag `null` (siehe `_block`).
    bloecke.netz.betrag = netz_betrag or 0.0
    bloecke.pv.betrag = pv_betrag or 0.0
    bloecke.akku.betrag = akku_betrag or 0.0

    # N173 — zwei Netzsätze. Der Verteilungssatz (Mieter) bezieht den vollen
    # Netzbetrag auf die SolarEdge-gemessene Netzmenge; der geeichte Satz
    # (E-Auto) auf die geeichte Rechnungsmenge am externen Posten. Weichen sie
    # ab, wird der Gap mit dem Versorger geklärt.
    netz_preis = (round(netz_betrag / bloecke.netz.kwh, 5)
                  if netz_betrag and bloecke.netz.kwh else None)
    # N192 — die geeichte Menge zuerst aus einer externen Strom-Position (N173);
    # wo es keine gibt, aus dem am Zeitraum festgehaltenen Wert (direkt aus dem
    # Stromketten-Hinweis eingetragen). So löst sich der Dauerhinweis auf.
    geeichte_menge = _geeichte_menge(positionen) or round(z.strom_rechnung_kwh
                                                          or 0.0, 3)
    if netz_betrag and geeichte_menge > 0:
        netz_preis_geeicht = round(netz_betrag / geeichte_menge, 5)
    else:
        # Ohne geeichte Menge fällt der E-Auto-Satz auf den Verteilungssatz
        # zurück — nie eine Null, nie ein Absturz.
        netz_preis_geeicht = netz_preis
        if netz_preis is not None:
            warnungen.append(
                "Für den Netzbezug ist keine geeichte Rechnungsmenge hinterlegt "
                "— der E-Auto-Satz nutzt ersatzweise den Verteilungssatz auf "
                "SolarEdge-Menge. Für den geeichten Satz die abgerechnete Menge "
                "an der Strom-Position („Verbrauch & Herkunft“) eintragen.")

    # ---- Schritt 2: die E-Tankstelle vorab -------------------------------
    eauto = _eauto(session, z, sj, netz_p, pv_p, akku_p)
    warnungen += eauto.pop("warnungen", [])
    eauto_einheit = (sj.eauto_einheit or "").strip() or EAUTO_VORGABE
    eauto_kwh = round(eauto["netz_kwh"] + eauto["pv_kwh"] + eauto["akku_kwh"], 3)

    # ---- Schritt 3: der Rest nach Zählerwerten ---------------------------
    karte, haupthaus, gewichte, unbekannt = _gewichte(session, z)
    verbrauch, ohne, unbekannt_z = _je_einheit(
        kwh_zaehler, verb, gesamt_z.id if gesamt_z else None, karte, haupthaus,
        gewichte)
    # Ein zuordnungsloser Zähler in der Größenordnung der Ladungen IST die
    # Ladestation — sie steht in Schritt 2 und braucht keine Einheit. Er zählt
    # deshalb weder als offener Fund noch als fehlende Zuordnung.
    grenze = max(1.0, eauto_kwh * EAUTO_TOLERANZ)
    ladezaehler = next((o for o in ohne
                        if abs(o["kwh"] - eauto_kwh) <= grenze), None) \
        if eauto_kwh > 0 else None
    offen = [o for o in ohne if o is not ladezaehler]
    # N288-B4 — derselbe Hinweis wie in der Wasser-Kette, aus derselben Quelle:
    # der Zähler ohne jedes Ziel, das einzelne unbekannte Label an einem sonst
    # zugeordneten Zähler, und die Partei, deren Einheit sich nicht auflöst.
    warnungen += zuordnungs_warnungen([o["zaehler"] for o in offen]
                                      + unbekannt_z + unbekannt)

    e = _verteile(
        bloecke, verbrauch, eauto_einheit=eauto_einheit if eauto_kwh > 0 else "",
        eauto_netz_kwh=eauto["netz_kwh"], eauto_pv_kwh=eauto["pv_kwh"],
        eauto_akku_kwh=eauto["akku_kwh"], netz_preis_geeicht=netz_preis_geeicht)
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
            "netz": _block(bloecke.netz, netz_betrag, h_netz),
            "pv": _block(bloecke.pv, pv_betrag, h_pv),
            "akku": _block(bloecke.akku, akku_betrag, h_akku),
            "betrag": bloecke.betrag,
            # N173 — die zwei Netzsätze getrennt: Verteilung (Mieter, auf
            # SolarEdge-Menge) und geeicht (E-Auto, auf die Rechnungsmenge).
            "netz_preis": netz_preis,
            "netz_preis_geeicht": netz_preis_geeicht,
            "geeichte_menge": geeichte_menge,
            # Trägt jeder der drei Blöcke einen Betrag? Sonst ist die Summe nur
            # das, was bisher bekannt ist — und nicht der ganze Stromaufwand.
            "vollstaendig": None not in (netz_betrag, pv_betrag, akku_betrag),
            "quelle_betrag": quelle_betrag, "quelle_eigen": quelle_eigen,
            # N192 — die Belege hinter dem Netzbetrag, damit der Hinweis sie
            # ansehen und einen doppelten herausnehmen lassen kann.
            "netz_belege": _netz_belege(session, z.id, positionen),
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


@router.put("/zeitraeume/{zid}/strom/rechnungsmenge")
def strom_rechnungsmenge_setzen(data: dict, session: Session = Depends(get_session),
                                z: Zeitraum = Depends(zeitraum_holen)) -> dict:
    """N192 — die geeichte Rechnungsmenge des Netzbezugs festhalten (kWh).

    Der Nutzer trägt sie direkt aus dem Stromketten-Hinweis ein; danach rechnet
    der E-Auto-Satz auf die geeichte Menge statt ersatzweise auf die
    SolarEdge-Menge, und der Dauerhinweis verschwindet. Der SolarEdge-Wert bleibt
    unberührt — die beiden Sätze weichen bewusst voneinander ab (N173).

    Additiv und zurücknehmbar: 0 (oder leer) setzt sie wieder zurück, dann gilt
    wieder der Verteilungssatz."""
    wert = data.get("rechnung_kwh")
    z.strom_rechnung_kwh = float(wert) if wert not in (None, "") else 0.0
    session.add(z)
    session.commit()
    return {"ok": True, "rechnung_kwh": z.strom_rechnung_kwh}
