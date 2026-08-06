"""N132 — die E-Tankstelle als eigener Bereich.

Bisher steckte die Ladestation als kleine Karte auf der PV-Seite. Sie hat aber
eine eigene Fachlichkeit: an der Anlage laden **Menschen**, die nicht
zwangsläufig Eigentümer der Immobilie sind, und die quartalsweise eine Rechnung
bekommen. Das ist ein eigener Bereich, keine Randnotiz.

Was hier passiert — und was ausdrücklich nicht:

* **Nutzer** (Name + E-Mail, beliebig viele) liegen als JSON in der vorhandenen
  Schlüssel/Wert-Ablage `Einstellung` unter ``tankstelle_nutzer:<slug>``. Damit
  bleibt das Datenmodell unangetastet: keine neue Tabelle, keine neue Spalte,
  kein Migrationsschritt. Gelöscht wird nur, was der Nutzer selbst löscht.
* **Der Monatsverlauf** kommt aus der openWB-Wallbox (`app.openwb`, N130): je
  Ladung Datum, Energie und die drei Blöcke **Netz · PV · Akku** (N143). Sie
  bleiben einzeln stehen, weil der Nutzer seine Stromkosten über genau diese
  drei rechnet; „eigen" (PV + Akku) ist nur die bequeme Summe. Ist die Box weg
  oder das Modul (noch) nicht da, fällt die Auswertung auf die **erfassten**
  `Tankladung`-Datensätze zurück — mit ehrlichem Hinweis, welche Quelle gerade
  spricht. Nie eine stille Null.
* **Der Verlauf läuft über alles** (N143): ohne Zeitraumangabe reicht er vom
  ersten bis zum letzten Monat, in dem überhaupt geladen wurde — nicht über
  ein Kalenderjahr. Aus denselben Daten kommt die Liste der Jahre **mit**
  Verbrauch; leere Jahre gehören in keine Auswahl.
* **Die Abrechnung je Nutzer** kommt immer aus den erfassten `Tankladung`-Sätzen:
  die Wallbox weiß, wie viel geladen wurde, aber nicht von wem.
* **Der Satz je kWh wird abgeleitet, nicht eingegeben** (N148). Netzstrom
  kostet, was er laut Rechnung gekostet hat — Gesamtbetrag der Strom-Positionen
  geteilt durch die bezogenen kWh, Grundpreis inbegriffen; eigener Strom kostet
  :data:`EIGEN_RABATT` weniger. Grundlage ist die Stromkette des passenden
  Abrechnungszeitraums (`GET /api/zeitraeume/{zid}/stromkette`). Weil eine
  Ladung aus beidem gespeist wird, zahlt der Nutzer den **Mischsatz** aus den
  Mengen des Zeitraums; woher er kommt, steht als Herkunft daneben.

  Die beiden Handeingaben sind damit stillgelegt: `Stromjahr.tanken_preis`
  **und** `Tankladung.preis`. Beide Spalten bleiben im Modell stehen (nie
  entfernen, CLAUDE.md) und werden zur Preisbildung **nicht mehr gelesen** —
  ein alter Wert darf die Rechnung nicht mehr bewegen. Fehlen die Kosten, gibt
  es **keinen** Satz und einen Grund dazu — nie eine stille 0,00-€-Rechnung.
* **Versand** läuft über das bestehende Postfach des Nutzers
  (`app.mailversand` über `routers.mail.zugang`). Es gibt eine Vorschau, die
  nichts verschickt — erst der ausdrückliche POST sendet.

Eigener Prefix `/api/tankstelle`; der Stammdaten-Fänger `/objekte/{slug}/{bereich}`
wird davon nicht berührt.

**Aufbau seit N215.** Die Rechen- und Datenzugriffslogik liegt jetzt im Paket
:mod:`app.tanken`; dieser Router bleibt schmal (Routen, Pydantic-Modelle,
Parameter-Prüfungen) und delegiert. Externe Aufrufer und Tests, die weiterhin
``from app.routers.tankstelle import <name>`` schreiben, funktionieren durch
die Re-Exports am Ende dieser Datei unverändert weiter.
"""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlmodel import Session

from .. import eauto
from ..db import get_session
from ..deps import objekt_holen
from ..mailversand import MailFehler
from ..models import Einstellung, Objekt, Tanknutzer
from ..tanken.abrechnung import _abrechnung, _zeile_holen, abrechne
from ..tanken.einstellungen import (S_AUTOVERSAND, S_ZUORDNUNG, _setze,
                                    autoversand_aktiv, zuordnung_lesen)
from ..tanken.marker import (S_VERSENDET, _expand_quartale, _monat_schluessel,
                             _versendet_merken, _versendet_schluessel,
                             abgerechnet_marker, ist_versendet)
from ..tanken.nutzer import (S_NUTZER, _migriere_json_nutzer, _nutzer_dict,
                             _pruefe_email, _pruefe_name, nutzer_lesen,
                             schluessel)
from ..tanken.perioden import (GRACE_TAGE, MAX_MONATE, MONATSKURZ,
                               RUECKBLICK_JAHRE, _monatsende, abrechnungs_label,
                               aktive_monate, belegte_spanne, faelliges_quartal,
                               jahre_mit_verbrauch, monatsfolge,
                               quartal_zeitraum, quartale_monate, suchfenster)
from ..tanken.posten import (S_OPENWB_URL, TIMEOUT, Buchung, Posten, RohLadung,
                             _person, _posten_holen, _regel_treffer,
                             _stations_verbrauch, _wallbox_bereit,
                             buchungen, erfasste_ladungen, erfasste_posten,
                             posten_als_buchungen, wallbox_posten, zuordnen)
from ..tanken.satz import (EIGEN_RABATT, Satz, _stromkette_holen,
                           _ueberlappung, deutsch, eigen_satz, mischsatz,
                           passender_zeitraum, satz_ableiten)
from ..tanken.verlauf import (_monatszeile, _prozent, _verlauf_kosten_km,
                              verlauf, verlauf_summe)
from ..tanken.versand import (S_BENZIN, _benzin_verbrauch, _empfaenger,
                              _mailtext, _pdf_und_name, _quartal_verlauf,
                              abrechnungstext)
from .ki import ki_key, ki_modell
from .mail import zugang

log = logging.getLogger("immocalc")
router = APIRouter(prefix="/api/tankstelle", tags=["tankstelle"])


# ==========================================================================
# Nutzer — dünne Routen über der Tabelle `Tanknutzer` (siehe app.tanken.nutzer)
# ==========================================================================

class NutzerIn(BaseModel):
    """Die Stammdaten eines Tanknutzers. Alle Felder ``Optional`` und ``None``,
    damit ein PUT nur ändert, was wirklich mitgeschickt wird — ein leerer
    String (``""``) löscht bewusst, ``None`` lässt stehen."""
    name: Optional[str] = None
    email: Optional[str] = None
    person_id: Optional[int] = None
    strasse: Optional[str] = None
    plz: Optional[str] = None
    ort: Optional[str] = None
    iban: Optional[str] = None
    bic: Optional[str] = None
    kontoinhaber: Optional[str] = None
    notiz: Optional[str] = None
    # N170 — das E-Auto. `verbrauch_kwh_100km` wird meist über die KI ermittelt
    # (eigener Endpunkt), lässt sich hier aber auch von Hand setzen.
    e_auto_modell: Optional[str] = None
    verbrauch_kwh_100km: Optional[float] = None


@router.get("/{slug}/nutzer")
def nutzer(slug: str, session: Session = Depends(get_session),
           o: Objekt = Depends(objekt_holen)) -> dict:
    """Wer an dieser Ladestation lädt. Nicht zwangsläufig Eigentümer — es kann
    jeder sein."""
    return {"objekt": o.name, "nutzer": nutzer_lesen(session, o)}


@router.post("/{slug}/nutzer", status_code=201)
def nutzer_anlegen(slug: str, data: NutzerIn,
                   session: Session = Depends(get_session),
                   o: Objekt = Depends(objekt_holen)) -> dict:
    """Einen Nutzer ergänzen. Beliebig viele, jederzeit."""
    liste = nutzer_lesen(session, o)
    n = Tanknutzer(
        objekt_id=o.id, name=_pruefe_name(data.name or "", liste),
        email=_pruefe_email(data.email or ""), person_id=data.person_id,
        strasse=(data.strasse or "").strip(), plz=(data.plz or "").strip(),
        ort=(data.ort or "").strip(), iban=(data.iban or "").strip(),
        bic=(data.bic or "").strip(),
        kontoinhaber=(data.kontoinhaber or "").strip(),
        notiz=(data.notiz or "").strip(),
        e_auto_modell=(data.e_auto_modell or "").strip(),
        verbrauch_kwh_100km=(data.verbrauch_kwh_100km
                             if data.verbrauch_kwh_100km and
                             data.verbrauch_kwh_100km > 0 else 0.0))
    session.add(n)
    session.commit()
    session.refresh(n)
    log.info("E-Tankstelle %s: Nutzer „%s“ angelegt", o.slug, n.name)
    return _nutzer_dict(n)


@router.put("/{slug}/nutzer/{nid}")
def nutzer_aendern(slug: str, nid: int, data: NutzerIn,
                   session: Session = Depends(get_session),
                   o: Objekt = Depends(objekt_holen)) -> dict:
    """Stammdaten berichtigen. Ein nicht mitgeschicktes Feld (``None``) lässt
    den Wert stehen; ein leerer String löscht ihn bewusst."""
    n = session.get(Tanknutzer, nid)
    if n is None or n.objekt_id != o.id or not n.aktiv:
        raise HTTPException(404, "Nutzer nicht gefunden")
    if data.name is not None and data.name.strip():
        n.name = _pruefe_name(data.name, nutzer_lesen(session, o), eigene_id=nid)
    if data.email is not None:
        n.email = _pruefe_email(data.email)
    for feld in ("strasse", "plz", "ort", "iban", "bic", "kontoinhaber",
                 "notiz", "e_auto_modell"):
        wert = getattr(data, feld)
        if wert is not None:
            setattr(n, feld, wert.strip())
    # N170 — der Verbrauch von Hand: 0 oder None lässt den Wert stehen, ein
    # positiver überschreibt (der Handeintrag ist der Rückfallweg zur KI).
    if data.verbrauch_kwh_100km is not None and data.verbrauch_kwh_100km > 0:
        n.verbrauch_kwh_100km = round(data.verbrauch_kwh_100km, 1)
    if data.person_id is not None:
        n.person_id = data.person_id or None
    session.add(n)
    session.commit()
    session.refresh(n)
    return _nutzer_dict(n)


@router.delete("/{slug}/nutzer/{nid}")
def nutzer_entfernen(slug: str, nid: int,
                     session: Session = Depends(get_session),
                     o: Objekt = Depends(objekt_holen)) -> dict:
    """Einen Nutzer aus der Liste nehmen — eine bewusste Handlung des Nutzers.

    Erfasste Ladungen bleiben **unangetastet**; sie erscheinen in der
    Abrechnung dann als „nicht angelegt". Es geht nichts verloren."""
    n = session.get(Tanknutzer, nid)
    if n is None or n.objekt_id != o.id or not n.aktiv:
        raise HTTPException(404, "Nutzer nicht gefunden")
    session.delete(n)
    session.commit()
    log.info("E-Tankstelle %s: Nutzer %d entfernt", o.slug, nid)
    return {"ok": True}


# ==========================================================================
# N170 — das E-Auto je Nutzer und die einmalige Verbrauchsermittlung
# ==========================================================================

class EautoIn(BaseModel):
    """Das E-Auto eines Nutzers. `verbrauch_kwh_100km` optional: ist er gesetzt
    (Handeintrag), gilt er; sonst wird er über die KI zum Modell ermittelt."""
    modell: str = ""
    verbrauch_kwh_100km: Optional[float] = None


@router.post("/{slug}/nutzer/{nid}/eauto")
def eauto_setzen(slug: str, nid: int, data: EautoIn,
                 session: Session = Depends(get_session),
                 o: Objekt = Depends(objekt_holen)) -> dict:
    """Das E-Auto-Modell speichern und seinen Durchschnittsverbrauch bestimmen.

    Ein von Hand mitgeschickter `verbrauch_kwh_100km` hat Vorrang und wird direkt
    übernommen — der Rückfallweg, wenn die KI nichts liefert. Sonst zieht die KI
    einmalig den realistischen Verbrauch bei defensiver Fahrweise (netzfrei
    gerechnet wird in :mod:`app.eauto`, der KI-Aufruf ist die einzige
    Netz-Stelle). Schlägt das fehl, bleibt der Verbrauch unverändert und die
    Antwort trägt einen ehrlichen `hinweis` — nie ein Absturz, nie eine erfundene
    Zahl."""
    n = session.get(Tanknutzer, nid)
    if n is None or n.objekt_id != o.id or not n.aktiv:
        raise HTTPException(404, "Nutzer nicht gefunden")
    modell = " ".join((data.modell or "").split())
    if not modell:
        raise HTTPException(400, "Bitte ein E-Auto-Modell angeben.")
    n.e_auto_modell = modell

    hinweis, quelle = "", "ki"
    hand = data.verbrauch_kwh_100km
    if hand is not None and hand > 0:
        # Handeintrag: übernehmen, ohne die KI zu fragen.
        n.verbrauch_kwh_100km = round(hand, 1)
        quelle = "hand"
    else:
        verbrauch, hinweis = eauto.verbrauch_ermitteln(
            modell, schluessel=ki_key(session), ki_modell=ki_modell(session))
        if verbrauch is not None:
            n.verbrauch_kwh_100km = verbrauch
        else:
            quelle = "keine"
    session.add(n)
    session.commit()
    session.refresh(n)
    log.info("E-Tankstelle %s: E-Auto für Nutzer %d gesetzt (Quelle %s)",
             o.slug, nid, quelle)
    return {**_nutzer_dict(n), "hinweis": hinweis, "quelle": quelle}


# ==========================================================================
# Verlauf und Abrechnung — die Routen delegieren an app.tanken
# ==========================================================================

def _zeitraum(jahr: int, quartal: int, von: date | None,
              bis: date | None) -> tuple[date, date]:
    """Der auszuwertende Zeitraum: entweder frei gesetzt oder aus Jahr und
    Quartal."""
    if von and bis:
        if bis < von:
            raise HTTPException(400, "Das Ende des Zeitraums liegt vor "
                                     "seinem Beginn.")
        return von, bis
    try:
        return quartal_zeitraum(jahr, quartal)
    except ValueError as fehler:
        raise HTTPException(400, str(fehler)) from fehler


@router.get("/{slug}/verlauf")
def verlauf_zeigen(slug: str, jahr: int = Query(default=0),
                   quartal: int = Query(default=0),
                   von: date | None = None, bis: date | None = None,
                   alles: bool = Query(default=False),
                   session: Session = Depends(get_session),
                   o: Objekt = Depends(objekt_holen)) -> dict:
    """Der monatliche Verlauf: kWh je Monat in den drei Blöcken Netz, PV und
    Akku, jeweils mit Prozentangabe.

    Mit ``alles=1`` läuft er über **alle** Monate mit Verbrauch statt über ein
    Kalenderjahr (N143); `jahre` nennt dann die Jahre, in denen überhaupt
    geladen wurde — die Vorlage für die Jahresauswahl.

    Zuerst wird die Wallbox gefragt; meldet sie sich nicht, treten die
    erfassten Ladungen an ihre Stelle. Welche Quelle gesprochen hat, steht in
    `quelle` — die Zahlen sollen nie unerklärt springen."""
    if alles:
        fenster = suchfenster()
        posten, quelle, hinweis = _posten_holen(session, o, *fenster)
        heute = date.today()
        von, bis = belegte_spanne(posten,
                                  (date(heute.year, 1, 1),
                                   date(heute.year, 12, 31)))
    else:
        von, bis = _zeitraum(jahr or date.today().year, quartal, von, bis)
        posten, quelle, hinweis = _posten_holen(session, o, von, bis)

    try:
        zeilen = verlauf(posten, von, bis)
    except ValueError as fehler:
        raise HTTPException(400, str(fehler)) from fehler

    # N188 — Kosten (€) und Reichweite (km) additiv anreichern. `verlauf` und
    # `verlauf_summe` bleiben rein (ohne Session); die Anreicherung braucht die
    # Stromkette und die Nutzer und sitzt darum hier.
    summe = verlauf_summe(zeilen)
    zeilen, summe = _verlauf_kosten_km(session, o, zeilen, summe)

    return {"objekt": o.name, "von": von.isoformat(), "bis": bis.isoformat(),
            "quelle": quelle, "hinweis": hinweis, "monate": zeilen,
            "summe": summe,
            "jahre": jahre_mit_verbrauch(posten)}


def _quartale_aus(quartal: int, quartale: str, aus: str) -> tuple[list[int],
                                                                  set[int]]:
    """Die Zeitraumauswahl aus den Query-Parametern (N169).

    `quartale` ist eine kommagetrennte Liste („2,3"), `aus` die kommagetrennte
    Liste abgewählter Monatsnummern. Fehlt `quartale`, gilt das einzelne
    `quartal` — so bleibt der bisherige Aufruf unverändert gültig."""
    def zahlen(roh: str) -> list[int]:
        try:
            return [int(x) for x in roh.replace(" ", "").split(",") if x]
        except ValueError as fehler:
            raise HTTPException(400, "Ungültige Zeitraumauswahl.") from fehler

    ql = zahlen(quartale) or [quartal]
    return ql, set(zahlen(aus))


@router.get("/{slug}/abrechnung")
def abrechnung_zeigen(slug: str, jahr: int = Query(default=0),
                      quartal: int = Query(default=0),
                      quartale: str = Query(default=""),
                      aus: str = Query(default=""),
                      session: Session = Depends(get_session),
                      o: Objekt = Depends(objekt_holen)) -> dict:
    """Was jeder Nutzer geladen hat, zu welchem Satz, und was er zahlt.

    `quartal=0` rechnet das ganze Jahr ab. Mehrere Quartale zusammen (`quartale`)
    und einzeln abgewählte Monate (`aus`) sind der Feinschliff aus N169."""
    ql, aus_set = _quartale_aus(quartal, quartale, aus)
    return _abrechnung(session, o, slug, jahr or date.today().year, quartal,
                       quartale=ql, aus=aus_set)


@router.get("/{slug}/vorschau")
def vorschau(slug: str, jahr: int = Query(default=0),
             quartal: int = Query(default=0), nutzer_id: int = Query(default=0),
             name: str = Query(default=""),
             quartale: str = Query(default=""), aus: str = Query(default=""),
             session: Session = Depends(get_session),
             o: Objekt = Depends(objekt_holen)) -> dict:
    """Die Mail, wie sie beim Nutzer ankäme — verschickt wird hier nichts."""
    ql, aus_set = _quartale_aus(quartal, quartale, aus)
    daten = _abrechnung(session, o, slug, jahr or date.today().year, quartal,
                        quartale=ql, aus=aus_set)
    zeile = _zeile_holen(daten, nutzer_id, name)
    betreff, text = _mailtext(o, daten, zeile)
    return {"an": zeile["email"], "name": zeile["name"],
            "betreff": betreff, "text": text,
            "betrag": zeile["betrag"], "kwh": zeile["kwh"],
            "satz": zeile["satz"], "satz_grund": daten["satz_grund"],
            "label": daten["label"]}


def _sende_abrechnung(session: Session, o: Objekt, daten: dict, zeile: dict,
                      adresse: str) -> None:
    """Eine Abrechnung als Mail **mit dem Quartals-PDF im Anhang** verschicken.

    Der Mailtext bleibt kurz (N165 Teil 1); die Zahlen trägt das PDF. Der Anhang
    läuft über denselben Weg wie sonst in ImmoCalc (`Zugang.sende` mit
    ``anhang=(name, inhalt, subtyp)``).

    **Warum hier und nicht in ``app.tanken.versand``:** Die Tests
    monkeypatchen ``routers.tankstelle.zugang``. Läge diese Funktion im
    Paket, würde sie ``versand.zugang`` binden — der Patch bliebe wirkungslos.
    Der Rest der Zusammenstellung (Mailtext, PDF) sitzt im Paket."""
    betreff, text = _mailtext(o, daten, zeile)
    pdf, dateiname = _pdf_und_name(session, o, daten, zeile)
    zugang(session).sende(adresse, betreff, text,
                          anhang=(dateiname, pdf, "pdf"))


@router.get("/{slug}/abrechnung.pdf")
def abrechnung_pdf_zeigen(slug: str, jahr: int = Query(default=0),
                          quartal: int = Query(default=0),
                          nutzer_id: int = Query(default=0),
                          name: str = Query(default=""),
                          quartale: str = Query(default=""),
                          aus: str = Query(default=""),
                          session: Session = Depends(get_session),
                          o: Objekt = Depends(objekt_holen)) -> Response:
    """Die Quartalsabrechnung eines Nutzers als PDF — zum Ansehen und Prüfen,
    **ohne** dass etwas verschickt wird (N165).

    Kein PDF über 0 €: eine Rechnung ohne Betrag ist keine Rechnung. Fehlt der
    Satz oder hat der Nutzer nichts geladen, sagt die Antwort, woran es liegt,
    statt ein leeres Blatt zu erzeugen."""
    ql, aus_set = _quartale_aus(quartal, quartale, aus)
    daten = _abrechnung(session, o, slug, jahr or date.today().year, quartal,
                        quartale=ql, aus=aus_set)
    zeile = _zeile_holen(daten, nutzer_id, name)
    if zeile["kwh"] <= 0:
        raise HTTPException(400, f"{zeile['name']} hat im Zeitraum "
                                 f"{daten['label']} nichts geladen — kein PDF.")
    if zeile["satz"] is None or not (zeile["betrag"] and zeile["betrag"] > 0):
        raise HTTPException(400, "Ohne Rechnungsbetrag gibt es kein PDF. "
                                 + (daten["satz_grund"] or ""))
    inhalt, dateiname = _pdf_und_name(session, o, daten, zeile)
    return Response(content=inhalt, media_type="application/pdf", headers={
        "Content-Disposition": f'inline; filename="{dateiname}"'})


class VersandIn(BaseModel):
    """Wer bekommt für welches Quartal seine Abrechnung.

    `quartale` (mehrere zusammen) und `aus` (abgewählte Monate) sind der
    Feinschliff aus N169; fehlen sie, gilt das einzelne `quartal`."""
    nutzer_id: int = 0
    name: str = ""
    jahr: int = 0
    quartal: int = 0
    quartale: list[int] = []
    aus: list[int] = []
    an: str = ""                  # abweichende Adresse, sonst die hinterlegte


def _versand_quartale(data: "VersandIn") -> list[int]:
    """Die Quartale, die ein Versand betrifft — als Marker-Granularität (N182).

    Die abgewählten Monate (`aus`) bleiben unberücksichtigt: der Marker merkt
    sich das Quartal, nicht den einzelnen Monat."""
    return _expand_quartale(data.quartale or [data.quartal])


@router.post("/{slug}/versand")
def versenden(slug: str, data: VersandIn,
              session: Session = Depends(get_session),
              o: Objekt = Depends(objekt_holen)) -> dict:
    """Die Abrechnung eines Nutzers per Mail schicken — über das Postfach des
    Vermieters (dieselbe Strecke wie die Nebenkostenabrechnung).

    Ohne Betrag wird nicht verschickt: eine Rechnung über 0 € ist kein Vorgang,
    sondern eine Irritation. Dasselbe gilt für einen Zeitraum ohne
    abgeleiteten Satz (N148) — dann fehlt der Preis, nicht die Menge."""
    jahr = data.jahr or date.today().year
    daten = _abrechnung(session, o, slug, jahr,
                        data.quartal, quartale=data.quartale or [data.quartal],
                        aus=set(data.aus))
    zeile = _zeile_holen(daten, data.nutzer_id, data.name)
    adresse = _pruefe_email(data.an) or zeile["email"]
    if not adresse:
        raise HTTPException(400, f"Für {zeile['name']} ist keine "
                                 "E-Mail-Adresse hinterlegt.")
    if zeile["kwh"] <= 0:
        raise HTTPException(400, f"{zeile['name']} hat im Zeitraum "
                                 f"{daten['label']} nichts geladen.")
    if zeile["satz"] is None:
        raise HTTPException(400, "Für diesen Zeitraum steht noch kein Preis je "
                                 "kWh fest. " + daten["satz_grund"])

    # N182 — ein bereits abgerechnetes (jahr, quartal, nutzer) wird nicht erneut
    # verschickt. Derselbe Riegel wie im Autoversand (N165): der Marker sperrt
    # den Versand, ganz gleich, ob er automatisch oder von Hand gesetzt wurde.
    quartale_sel = _versand_quartale(data)
    if data.nutzer_id and any(
            ist_versendet(session, o.slug, jahr, q, data.nutzer_id)
            for q in quartale_sel):
        raise HTTPException(400, f"{zeile['name']} ist für diese Periode "
                                 "bereits abgerechnet — kein erneuter Versand.")

    try:
        _sende_abrechnung(session, o, daten, zeile, adresse)
    except MailFehler as fehler:
        raise HTTPException(400, str(fehler)) from fehler
    # N182/N214 — den Versand festhalten, damit die Periode als abgerechnet
    # erscheint (Haken) und ein zweiter Versand gesperrt ist. GENAU die
    # versendeten Monate werden monatsgenau gemerkt (nicht das ganze Quartal —
    # sonst wären auch nicht versendete Monate stumm markiert). Der Marker fürs
    # ganze Quartal bleibt zusätzlich als Fallback für die alte Sperr-Logik.
    #
    # N220 — derselbe Zukunfts-Guard wie in `abgerechnet_setzen`: eine Auswahl
    # kann ein noch nicht abgeschlossenes Quartal enthalten (z. B. „ganzes
    # Jahr" mitten im laufenden Jahr) — dann darf nur der bereits
    # abgeschlossene Teil als abgerechnet gelten. Ohne diesen Filter erschienen
    # künftige, noch ungeladene Monate fälschlich als „✓ abgerechnet".
    if data.nutzer_id:
        heute = date.today()
        heute_iso = heute.isoformat()
        monate_sel = [m for m in aktive_monate(quartale_sel, set(data.aus))
                     if _monatsende(jahr, m) < heute]
        for m in monate_sel:
            _setze(session, _monat_schluessel(o.slug, jahr, m, data.nutzer_id),
                   heute_iso)
        for q in quartale_sel:
            if quartal_zeitraum(jahr, q)[1] < heute:
                _versendet_merken(session, o.slug, jahr, q, data.nutzer_id)
        session.commit()
    log.info("E-Tankstelle %s: Abrechnung %s an %s versendet (mit PDF)", o.slug,
             daten["label"], adresse)
    return {"ok": True, "an": adresse, "label": daten["label"],
            "betrag": zeile["betrag"]}


# ==========================================================================
# N165 Teil 2 — Autoversand-Schalter und Mehrnutzer-Zuordnung (Endpunkte)
# ==========================================================================

class AutoversandIn(BaseModel):
    aktiv: bool = False


class RegelIn(BaseModel):
    """Eine Zeitraum-Regel: „vom … bis … lädt dieser Nutzer"."""
    nutzer_id: int
    von: date
    bis: date


class ZuordnungIn(BaseModel):
    """Die Mehrnutzer-Zuordnung eines Objekts: Zeitraum-Regeln je Nutzer und
    einzeln ausgeschlossene Ladungen (der Korrekturweg)."""
    regeln: list[RegelIn] = []
    ausschluss: list[int] = []


@router.get("/{slug}/einstellungen")
def einstellungen(slug: str, session: Session = Depends(get_session),
                  o: Objekt = Depends(objekt_holen)) -> dict:
    """Autoversand-Schalter und Mehrnutzer-Zuordnung eines Objekts."""
    liste = nutzer_lesen(session, o)
    regeln, ausschluss = zuordnung_lesen(session, o.slug, liste)
    return {"autoversand": autoversand_aktiv(session, o.slug),
            "regeln": [{"nutzer_id": r["nutzer_id"], "von": r["von"].isoformat(),
                        "bis": r["bis"].isoformat()} for r in regeln],
            "ausschluss": sorted(ausschluss)}


@router.put("/{slug}/autoversand")
def autoversand_setzen(slug: str, data: AutoversandIn,
                       session: Session = Depends(get_session),
                       o: Objekt = Depends(objekt_holen)) -> dict:
    """Den automatischen Versand ein- oder ausschalten. Default aus — verschickt
    wird nur, was der Nutzer bewusst freigibt."""
    _setze(session, f"{S_AUTOVERSAND}:{o.slug}", "1" if data.aktiv else "0")
    session.commit()
    log.info("E-Tankstelle %s: Autoversand %s", o.slug,
             "eingeschaltet" if data.aktiv else "ausgeschaltet")
    return {"autoversand": data.aktiv}


@router.put("/{slug}/zuordnung")
def zuordnung_setzen(slug: str, data: ZuordnungIn,
                     session: Session = Depends(get_session),
                     o: Objekt = Depends(objekt_holen)) -> dict:
    """Die Mehrnutzer-Zuordnung setzen: je Nutzer ein Zeitraum, dazu die
    einzeln ausgeschlossenen Ladungen. Ganz ersetzend — die Oberfläche schickt
    stets den vollständigen Stand."""
    bekannt = {n["id"] for n in nutzer_lesen(session, o)}
    for r in data.regeln:
        if r.bis < r.von:
            raise HTTPException(400, "Das Ende eines Zeitraums liegt vor "
                                     "seinem Beginn.")
        if r.nutzer_id not in bekannt:
            raise HTTPException(400, "Eine Regel verweist auf einen Nutzer, "
                                     "der nicht (mehr) in der Liste steht.")
    daten = {"regeln": [{"nutzer_id": r.nutzer_id, "von": r.von.isoformat(),
                         "bis": r.bis.isoformat()} for r in data.regeln],
             "ausschluss": sorted(set(data.ausschluss))}
    _setze(session, f"{S_ZUORDNUNG}:{o.slug}", json.dumps(daten))
    session.commit()
    log.info("E-Tankstelle %s: Zuordnung gesetzt — %d Regel(n), %d "
             "ausgeschlossen", o.slug, len(daten["regeln"]),
             len(daten["ausschluss"]))
    return {"ok": True, "regeln": daten["regeln"],
            "ausschluss": daten["ausschluss"]}


# ==========================================================================
# N182 — abgerechnete Perioden merken, kennzeichnen, Versand sperren
#
# Ein abgerechnet-Marker ist derselbe Versendet-Marker wie beim Autoversand
# (N165). Wer eine Periode von Hand als abgerechnet setzt (etwa den alten
# 4-Monats-Initialstand), sperrt damit den erneuten Versand genauso, wie es der
# automatische Versand nach dem Verschicken tut.
# ==========================================================================

class AbgerechnetIn(BaseModel):
    """Eine Periode als abgerechnet setzen oder die Markierung entfernen.

    `quartale` (oder das einzelne `quartal`, ``0`` = ganzes Jahr) nennt die
    betroffenen Quartale; `nutzer_id` ``0`` meint alle aktuell gelisteten
    Nutzer (der Initialstand wird für die ganze Station gesetzt).

    `monate` (1–12) markiert stattdessen **einzelne Monate** (N187). Ist die
    Liste nicht leer, gilt sie und die Quartale bleiben unberührt; ist sie leer,
    verhält sich alles wie bisher (quartalsweise)."""
    jahr: int
    quartale: list[int] = []
    quartal: int = 0
    monate: list[int] = []
    nutzer_id: int = 0
    abgerechnet: bool = True


@router.get("/{slug}/abgerechnet")
def abgerechnet_zeigen(slug: str, jahr: int = Query(default=0),
                       session: Session = Depends(get_session),
                       o: Objekt = Depends(objekt_holen)) -> dict:
    """Welche Perioden (jahr, quartal, nutzer) sind als abgerechnet festgehalten
    (N182). Mit `jahr` auf ein Jahr eingeschränkt."""
    return {"abgerechnet": abgerechnet_marker(session, o.slug, jahr)}


@router.put("/{slug}/abgerechnet")
def abgerechnet_setzen(slug: str, data: AbgerechnetIn,
                       session: Session = Depends(get_session),
                       o: Objekt = Depends(objekt_holen)) -> dict:
    """Eine Periode von Hand als abgerechnet markieren oder die Markierung
    entfernen (N182).

    Setzen schreibt denselben Marker wie der Versand — damit sperrt ein manuell
    gesetzter Marker den Versand genauso. Entfernen nimmt den Marker der
    genannten Perioden/Nutzer wieder heraus (der Korrekturweg)."""
    if not data.jahr:
        raise HTTPException(400, "Zu welchem Jahr soll die Periode als "
                                 "abgerechnet gelten?")
    liste = nutzer_lesen(session, o)
    if data.nutzer_id:
        if not any(n["id"] == data.nutzer_id for n in liste):
            raise HTTPException(404, "Nutzer nicht gefunden")
        nutzer_ids = [data.nutzer_id]
    else:
        nutzer_ids = [n["id"] for n in liste]

    # N187 — sind Monate genannt, greift die feine Granularität: je Monat ein
    # M-Marker, gesetzt oder geleert. Der leere Wert ("") zählt in
    # `abgerechnet_marker` nicht mehr — das ist der Weg zum Entfernen. Ohne
    # Monate bleibt es beim bisherigen Quartalsweg.
    monate = [m for m in data.monate if 1 <= m <= 12]
    if monate:
        # N214 — noch nicht abgeschlossene Monate (Ende in der Zukunft) DÜRFEN
        # nicht als abgerechnet markiert werden: eine offene Abrechnung ist
        # keine Abrechnung. Beim Entfernen greift der Guard nicht — Korrekturen
        # müssen möglich bleiben.
        if data.abgerechnet:
            heute = date.today()
            offen = [m for m in monate if _monatsende(data.jahr, m) >= heute]
            if offen:
                raise HTTPException(400,
                    "Diese Monate sind noch nicht abgeschlossen und können "
                    "nicht als abgerechnet gesetzt werden: "
                    + ", ".join(f"{MONATSKURZ[m - 1]} {data.jahr}" for m in offen))
        wert = date.today().isoformat() if data.abgerechnet else ""
        for m in monate:
            for nid in nutzer_ids:
                _setze(session, _monat_schluessel(o.slug, data.jahr, m, nid),
                       wert)
        anzahl, was = len(monate), "Monat(e)"
    else:
        quartale = _expand_quartale(data.quartale or [data.quartal])
        if not quartale:
            raise HTTPException(400, "Kein Quartal ausgewählt.")
        for q in quartale:
            for nid in nutzer_ids:
                key = _versendet_schluessel(o.slug, data.jahr, q, nid)
                if data.abgerechnet:
                    _setze(session, key, date.today().isoformat())
                else:
                    vorhanden = session.get(Einstellung, key)
                    if vorhanden is not None:
                        session.delete(vorhanden)
        anzahl, was = len(quartale), "Periode(n)"
    session.commit()
    log.info("E-Tankstelle %s: %d %s je %d Nutzer %s", o.slug, anzahl, was,
             len(nutzer_ids),
             "als abgerechnet markiert" if data.abgerechnet
             else "aus der Abrechnung genommen")
    return {"ok": True,
            "abgerechnet": abgerechnet_marker(session, o.slug, data.jahr)}


# ==========================================================================
# N165 Teil 2 — der automatische Versand, einen Tag nach Quartalsende
#
# Kein zweiter Zeitgeber: der Wachdienst (`wachdienst.py`, alle 15 Minuten) ruft
# `versand_faellig_pruefen(session)` auf. Die Funktion ist idempotent — der
# Versendet-Marker sorgt dafür, dass ein Quartal nie zweimal hinausgeht.
# ==========================================================================

def _autoversand_objekt(session: Session, o: Objekt, jahr: int,
                        quartal: int) -> int:
    """Ein Objekt automatisch abrechnen: an jeden angelegten Nutzer mit Adresse,
    Ladung und ermitteltem Satz die Abrechnung schicken — sofern das Quartal ihm
    noch nicht geschickt wurde.

    Kein Versand bei 0 € oder ohne Satz (lieber nichts als eine Rechnung über
    nichts). Nach jedem erfolgreichen Versand wird der Marker gesetzt und einzeln
    committet — so verliert ein Abbruch mitten im Lauf höchstens die noch nicht
    verschickten Nutzer, nie den schon erledigten Marker."""
    daten = _abrechnung(session, o, o.slug, jahr, quartal)
    if daten["satz"] is None:
        return 0
    gesendet = 0
    for zeile in daten["nutzer"]:
        nid = zeile.get("nutzer_id")
        betrag = zeile.get("betrag")
        if not nid or not zeile.get("email"):
            continue
        if not (zeile["kwh"] > 0) or not (betrag and betrag > 0):
            continue
        if ist_versendet(session, o.slug, jahr, quartal, nid):
            continue
        try:
            _sende_abrechnung(session, o, daten, zeile, zeile["email"])
        except (MailFehler, HTTPException) as fehler:
            log.warning("E-Tankstelle %s: Autoversand an %s fehlgeschlagen — %s",
                        o.slug, zeile["email"], fehler)
            continue
        _versendet_merken(session, o.slug, jahr, quartal, nid)
        session.commit()
        gesendet += 1
        log.info("E-Tankstelle %s: Autoversand %s an %s (mit PDF)", o.slug,
                 daten["label"], zeile["email"])
    return gesendet


def versand_faellig_pruefen(session: Session,
                            heute: date | None = None) -> dict:
    """Vom Wachdienst gerufen: verschickt fällige Quartalsabrechnungen für alle
    Objekte mit eingeschaltetem Autoversand.

    Idempotent: ausgelöst wird einen Tag nach Quartalsende (Fenster
    :data:`GRACE_TAGE`), und jeder Versand wird per Marker festgehalten — ein
    zweiter Lauf im selben Fenster schickt nichts erneut. Ist gerade kein
    Quartal fällig, tut die Funktion nichts."""
    from sqlmodel import select as _select

    heute = heute or date.today()
    fq = faelliges_quartal(heute)
    if fq is None:
        return {"faellig": False, "geprueft": 0, "versendet": 0}
    jahr, quartal = fq
    geprueft = versendet = 0
    for o in session.exec(_select(Objekt)).all():
        if not autoversand_aktiv(session, o.slug):
            continue
        geprueft += 1
        try:
            versendet += _autoversand_objekt(session, o, jahr, quartal)
        except Exception as fehler:            # noqa: BLE001 - nie den Lauf killen
            log.warning("E-Tankstelle %s: Autoversand-Lauf fehlgeschlagen — %s",
                        o.slug, fehler)
    if versendet:
        log.info("E-Tankstelle: Autoversand Q%d %d — %d Abrechnung(en) an %d "
                 "Objekt(en) geprüft", quartal, jahr, versendet, geprueft)
    return {"faellig": True, "jahr": jahr, "quartal": quartal,
            "geprueft": geprueft, "versendet": versendet}


def autoversand_lauf() -> dict:
    """Der Einhängepunkt für den Wachdienst: öffnet eine eigene Session und
    prüft den fälligen Autoversand — parameterlos, wie die übrigen Läufe des
    Wachdienstes (`einmal_scannen`, `_ocr_lauf`).

    Damit ist die eine Zeile in `wachdienst.schleife` (im ``try``-Block, neben
    den anderen ``to_thread``-Aufrufen)::

        await asyncio.to_thread(autoversand_lauf)

    mit dem Import ``from .routers.tankstelle import autoversand_lauf``. Wirft
    nie — der Wächter darf daran nicht sterben."""
    from ..db import engine
    try:
        with Session(engine) as session:
            return versand_faellig_pruefen(session)
    except Exception as fehler:                # noqa: BLE001 - Wächter darf nie sterben
        log.warning("E-Tankstelle: Autoversand-Lauf fehlgeschlagen — %s", fehler)
        return {"faellig": False, "geprueft": 0, "versendet": 0,
                "fehler": str(fehler)}
