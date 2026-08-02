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
  Ladung Datum, Energie und die Anteile Netz/Speicher/PV. „extern" ist der
  Netzbezug, „eigen" sind Speicher + PV zusammen. Ist die Box weg oder das
  Modul (noch) nicht da, fällt die Auswertung auf die **erfassten**
  `Tankladung`-Datensätze zurück — mit ehrlichem Hinweis, welche Quelle gerade
  spricht. Nie eine stille Null.
* **Die Abrechnung je Nutzer** kommt immer aus den erfassten `Tankladung`-Sätzen:
  die Wallbox weiß, wie viel geladen wurde, aber nicht von wem. Der Satz je kWh
  steht in `Stromjahr.tanken_preis` und wird hier **nur gelesen**.
* **Versand** läuft über das bestehende Postfach des Nutzers
  (`app.mailversand` über `routers.mail.zugang`). Es gibt eine Vorschau, die
  nichts verschickt — erst der ausdrückliche POST sendet.

Eigener Prefix `/api/tankstelle`; der Stammdaten-Fänger `/objekte/{slug}/{bereich}`
wird davon nicht berührt.
"""
from __future__ import annotations

import json
import logging
from calendar import monthrange
from dataclasses import dataclass
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from ..cloudkern import _lies
from ..db import get_session
from ..deps import objekt_holen
from ..mailversand import MailFehler
from ..models import Eigentuemer, Einstellung, Objekt, Stromjahr, Tankladung
from .mail import zugang

# Die Wallbox-Anbindung entsteht parallel (N130). Fehlt sie, arbeitet dieser
# Bereich auf den erfassten Ladungen weiter — eine harte Abhängigkeit auf
# fremde, noch entstehende Arbeit wäre hier fehl am Platz.
try:                                        # pragma: no cover - Importzweig
    from .. import openwb
except ImportError:                         # pragma: no cover - Importzweig
    openwb = None                           # type: ignore[assignment]

try:                                        # pragma: no cover - Importzweig
    import httpx
except ImportError:                         # pragma: no cover - Importzweig
    httpx = None                            # type: ignore[assignment]

log = logging.getLogger("immocalc")
router = APIRouter(prefix="/api/tankstelle", tags=["tankstelle"])

# Schlüssel der Nutzerliste — je Objekt einer. Eigener Namensraum, es wird kein
# bestehender Schlüssel angefasst.
S_NUTZER = "tankstelle_nutzer"
# Adresse der Wallbox, gesetzt in `routers/openwb.py`. Hier nur gelesen.
S_OPENWB_URL = "openwb_url"

# Die Box steht im Heimnetz und ist mal aus. Kurz genug, dass die Seite nicht
# hängt.
TIMEOUT = 8.0

# Ein Verlauf über mehr als zehn Jahre ist eine Fehleingabe, kein Wunsch.
MAX_MONATE = 120

MONATSKURZ = ("Jan", "Feb", "Mär", "Apr", "Mai", "Jun",
              "Jul", "Aug", "Sep", "Okt", "Nov", "Dez")


# ==========================================================================
# Reine Logik — ohne Datenbank, ohne Netz. Hier wird gerechnet.
# ==========================================================================

@dataclass
class Posten:
    """Eine Ladung, auf das reduziert, was der Verlauf braucht.

    `extern_kwh`/`eigen_kwh` sind ``None``, solange niemand weiß, woher der
    Strom kam — dann zeigt die Oberfläche die Menge ohne Aufteilung statt
    einer erfundenen 0."""
    tag: date
    kwh: float
    extern_kwh: float | None = None
    eigen_kwh: float | None = None


@dataclass
class Buchung:
    """Eine Ladung, die einer Person zugeordnet ist — die Abrechnungszeile."""
    tag: date | None
    person: str
    email: str
    kwh: float
    preis: float


def quartal_zeitraum(jahr: int, quartal: int) -> tuple[date, date]:
    """Anfang und Ende eines Quartals — ``quartal=0`` meint das ganze Jahr.

    Beide Ränder zählen mit: Q3 läuft vom 01.07. bis zum 30.09."""
    if quartal == 0:
        return date(jahr, 1, 1), date(jahr, 12, 31)
    if quartal not in (1, 2, 3, 4):
        raise ValueError("Ein Quartal ist 1, 2, 3 oder 4 (0 = ganzes Jahr).")
    erster = 3 * (quartal - 1) + 1
    letzter = erster + 2
    return date(jahr, erster, 1), date(jahr, letzter,
                                       monthrange(jahr, letzter)[1])


def zeitraum_label(jahr: int, quartal: int) -> str:
    """„Q3 2025" bzw. „Jahr 2025" — die Überschrift der Abrechnung."""
    return f"Q{quartal} {jahr}" if quartal else f"Jahr {jahr}"


def monatsfolge(von: date, bis: date) -> list[tuple[int, int]]:
    """Alle Monate von `von` bis `bis` — auch die ohne eine einzige Ladung.

    Ein Verlauf mit Lücken ist kein Verlauf: ein Monat ohne Ladung ist eine
    Aussage und gehört als leerer Balken in die Grafik."""
    if bis < von:
        raise ValueError("Das Ende des Zeitraums liegt vor seinem Beginn.")
    folge: list[tuple[int, int]] = []
    jahr, monat = von.year, von.month
    while (jahr, monat) <= (bis.year, bis.month):
        folge.append((jahr, monat))
        if len(folge) > MAX_MONATE:
            raise ValueError(
                f"Der Zeitraum umfasst mehr als {MAX_MONATE} Monate — "
                "bitte einen kürzeren wählen.")
        monat += 1
        if monat > 12:
            jahr, monat = jahr + 1, 1
    return folge


def _prozent(teil: float, ganz: float) -> float | None:
    """Prozentanteil — ``None``, wenn es nichts zu teilen gibt."""
    return round(teil / ganz * 100.0, 1) if ganz > 0 else None


def verlauf(posten: list[Posten], von: date, bis: date) -> list[dict]:
    """Je Monat: wie viel geladen wurde und in welchen Anteilen.

    Gefiltert wird über den Tag der Ladung (beide Ränder zählen). Kennt auch
    nur eine Ladung des Monats ihre Herkunft nicht, gilt die Aufteilung des
    Monats als unvollständig (`aufteilung: false`) — dann steht die Menge da,
    aber keine Prozentzahl, die niemand belegen kann.

    Was weder Netz noch eigener Strom trägt, steht als `rest_kwh` **getrennt**
    da. Die Wallbox schreibt gelegentlich 0 % in alle vier Anteile (gesehen am
    12.07.2026, 49,88 kWh); diese Menge dem Netz zuzuschlagen wäre eine
    Behauptung, sie zu unterschlagen ein Loch in der Summe."""
    eimer: dict[tuple[int, int], dict] = {
        (j, m): {"jahr": j, "monat": m, "kurz": MONATSKURZ[m - 1],
                 "label": f"{MONATSKURZ[m - 1]} {j}", "anzahl": 0, "kwh": 0.0,
                 "extern_kwh": 0.0, "eigen_kwh": 0.0, "aufteilung": True}
        for j, m in monatsfolge(von, bis)}

    for p in posten:
        if p.tag is None or not (von <= p.tag <= bis):
            continue
        eimer_monat = eimer.get((p.tag.year, p.tag.month))
        if eimer_monat is None:
            continue
        eimer_monat["kwh"] += p.kwh
        if p.kwh > 0:
            eimer_monat["anzahl"] += 1
        if p.extern_kwh is None or p.eigen_kwh is None:
            eimer_monat["aufteilung"] = False
        else:
            eimer_monat["extern_kwh"] += p.extern_kwh
            eimer_monat["eigen_kwh"] += p.eigen_kwh

    zeilen: list[dict] = []
    for schluessel in monatsfolge(von, bis):
        m = eimer[schluessel]
        kwh = round(m["kwh"], 2)
        offen = not m["aufteilung"]
        extern = None if offen else round(m["extern_kwh"], 2)
        eigen = None if offen else round(m["eigen_kwh"], 2)
        rest = None if offen else round(kwh - extern - eigen, 2)
        zeilen.append({
            **m, "kwh": kwh, "extern_kwh": extern, "eigen_kwh": eigen,
            "rest_kwh": rest,
            "extern_prozent": None if offen else _prozent(extern or 0.0, kwh),
            "eigen_prozent": None if offen else _prozent(eigen or 0.0, kwh),
            "rest_prozent": None if offen else _prozent(rest or 0.0, kwh)})
    return zeilen


def verlauf_summe(zeilen: list[dict]) -> dict:
    """Die Summenzeile unter dem Verlauf — mit denselben Regeln wie oben.

    Summiert werden die **angezeigten** Monatswerte, nicht die Rohdaten: eine
    Summe, die nicht der Summe der Zeilen darüber entspricht, sieht wie ein
    Rechenfehler aus. Gegenüber der ungerundeten Summe kann das um einen
    Hundertstel-kWh abweichen."""
    kwh = round(sum(z["kwh"] for z in zeilen), 2)
    vollstaendig = all(z["aufteilung"] for z in zeilen)
    extern = (round(sum(z["extern_kwh"] or 0.0 for z in zeilen), 2)
              if vollstaendig else None)
    eigen = (round(sum(z["eigen_kwh"] or 0.0 for z in zeilen), 2)
             if vollstaendig else None)
    rest = None if extern is None else round(kwh - extern - eigen, 2)
    return {"anzahl": sum(z["anzahl"] for z in zeilen), "kwh": kwh,
            "extern_kwh": extern, "eigen_kwh": eigen, "rest_kwh": rest,
            "extern_prozent": None if extern is None else _prozent(extern, kwh),
            "eigen_prozent": None if eigen is None else _prozent(eigen, kwh),
            "rest_prozent": None if rest is None else _prozent(rest, kwh),
            "aufteilung": vollstaendig}


def schluessel(name: str) -> str:
    """Ein Name als Vergleichsschlüssel — die Brücke zwischen der Nutzerliste
    und den erfassten Ladungen.

    Beide führen den Namen als Text; „Marvin " und „marvin" sind dieselbe
    Person."""
    return " ".join((name or "").split()).casefold()


def abrechne(buchungen: list[Buchung], nutzer: list[dict],
             satz: float) -> list[dict]:
    """Je Nutzer: geladene Menge, Satz und Betrag.

    Jede Buchung ohne eigenen Preis wird mit dem gepflegten Satz bewertet
    (`Stromjahr.tanken_preis`). Angelegte Nutzer ohne Ladung erscheinen mit 0 —
    sonst verschwände jemand aus der Liste, nur weil er ein Quartal lang nicht
    geladen hat. Ladungen auf Namen, die (noch) nicht in der Liste stehen,
    stehen am Ende mit ``angelegt: false``: übergehen wäre stilles Verschlucken
    von Geld."""
    zeilen: dict[str, dict] = {}
    for n in nutzer:
        zeilen[schluessel(n["name"])] = {
            "nutzer_id": n["id"], "name": n["name"], "email": n.get("email", ""),
            "angelegt": True, "anzahl": 0, "kwh": 0.0, "betrag": 0.0,
            "ladungen": []}

    for b in buchungen:
        s = schluessel(b.person)
        zeile = zeilen.get(s)
        if zeile is None:
            zeile = zeilen[s] = {
                "nutzer_id": None, "name": b.person or "—", "email": b.email,
                "angelegt": False, "anzahl": 0, "kwh": 0.0, "betrag": 0.0,
                "ladungen": []}
        preis = b.preis if b.preis else satz
        betrag = b.kwh * preis
        zeile["anzahl"] += 1
        zeile["kwh"] += b.kwh
        zeile["betrag"] += betrag
        if not zeile["email"] and b.email:
            zeile["email"] = b.email
        zeile["ladungen"].append({
            "datum": b.tag.isoformat() if b.tag else None,
            "kwh": round(b.kwh, 3), "preis": round(preis, 4),
            "betrag": round(betrag, 2)})

    fertig = []
    for zeile in zeilen.values():
        kwh = round(zeile["kwh"], 3)
        betrag = round(zeile["betrag"], 2)
        fertig.append({**zeile, "kwh": kwh, "betrag": betrag,
                       "satz": round(betrag / kwh, 4) if kwh > 0 else round(satz, 4)})
    # Wer geladen hat, steht oben; danach alphabetisch — eine Reihenfolge, die
    # sich zwischen zwei Aufrufen nicht von selbst ändert.
    fertig.sort(key=lambda z: (-z["kwh"], schluessel(z["name"])))
    return fertig


def deutsch(wert: float, stellen: int = 2) -> str:
    """Eine Zahl in deutscher Schreibweise: „1.234,56".

    Python setzt Komma und Punkt genau andersherum; `translate` tauscht
    beide in einem Durchgang — nacheinander ersetzen würde die eigene
    Arbeit wieder einsammeln."""
    return f"{wert:,.{stellen}f}".translate(str.maketrans(",.", ".,"))


def abrechnungstext(objekt_name: str, zeile: dict, von: date, bis: date,
                    label: str, eigen_prozent: float | None) -> str:
    """Die Abrechnung als Text für die Mail — dieselbe Grundlage wie die
    Vorschau auf der Seite, damit niemand etwas anderes verschickt, als er
    gesehen hat."""
    def tag(d: date) -> str:
        return d.strftime("%d.%m.%Y")

    def geld(wert: float) -> str:
        return f"{deutsch(wert)} €"

    def menge(wert: float) -> str:
        return f"{deutsch(wert)} kWh"

    zeilen = [f"Hallo {zeile['name']},", "",
              f"hier die Abrechnung deiner Ladungen an der E-Tankstelle "
              f"{objekt_name} für {label} ({tag(von)} – {tag(bis)}).", "",
              f"Geladen    {menge(zeile['kwh'])}",
              f"Satz       {deutsch(zeile['satz'], 4)} € je kWh",
              f"Zu zahlen  {geld(zeile['betrag'])}", ""]

    if zeile["ladungen"]:
        zeilen.append("Einzelne Ladungen:")
        for l in zeile["ladungen"]:
            datum = (date.fromisoformat(l["datum"]).strftime("%d.%m.%Y")
                     if l["datum"] else "ohne Datum")
            zeilen.append(f"  {datum}   {menge(l['kwh'])}   {geld(l['betrag'])}")
        zeilen.append("")

    if eigen_prozent is not None:
        zeilen.append(f"{deutsch(eigen_prozent, 1)} % des Stroms kamen im "
                      "Zeitraum aus der eigenen Photovoltaik-Anlage.")
        zeilen.append("")

    zeilen.append("Viele Grüße")
    return "\n".join(zeilen) + "\n"


# ==========================================================================
# Nutzerliste — als JSON in der vorhandenen Schlüssel/Wert-Ablage
# ==========================================================================

def _nutzer_schluessel(slug: str) -> str:
    return f"{S_NUTZER}:{slug}"


def nutzer_lesen(session: Session, slug: str) -> list[dict]:
    """Die Nutzer eines Objekts. Unlesbares JSON ergibt eine leere Liste —
    und einen Eintrag im Log; es wird nichts überschrieben."""
    roh = _lies(session, _nutzer_schluessel(slug))
    if not roh:
        return []
    try:
        daten = json.loads(roh)
    except ValueError:
        log.warning("Nutzerliste der E-Tankstelle (%s) unlesbar — übergangen",
                    slug)
        return []
    if not isinstance(daten, list):
        return []
    liste = []
    for eintrag in daten:
        if not isinstance(eintrag, dict) or not str(eintrag.get("name", "")).strip():
            continue
        liste.append({"id": int(eintrag.get("id") or 0),
                      "name": str(eintrag["name"]).strip(),
                      "email": str(eintrag.get("email", "")).strip(),
                      "notiz": str(eintrag.get("notiz", "")).strip()})
    return liste


def _nutzer_schreiben(session: Session, slug: str, liste: list[dict]) -> None:
    """Die Nutzerliste ablegen — additiv, ohne einen anderen Schlüssel zu
    berühren."""
    wert = json.dumps(liste, ensure_ascii=False)
    eintrag = session.get(Einstellung, _nutzer_schluessel(slug))
    if eintrag:
        eintrag.wert = wert
    else:
        eintrag = Einstellung(schluessel=_nutzer_schluessel(slug), wert=wert)
    session.add(eintrag)
    session.commit()


def _pruefe_name(name: str, liste: list[dict], eigene_id: int = 0) -> str:
    """Ein Name muss da und eindeutig sein — sonst lässt sich eine Ladung
    keiner Person zuordnen."""
    sauber = " ".join((name or "").split())
    if not sauber:
        raise HTTPException(400, "Der Nutzer braucht einen Namen.")
    if any(schluessel(n["name"]) == schluessel(sauber) and n["id"] != eigene_id
           for n in liste):
        raise HTTPException(400, f"„{sauber}“ steht schon in der Liste.")
    return sauber


def _pruefe_email(email: str) -> str:
    """Locker geprüft: eine Adresse ohne @ ist mit Sicherheit keine. Leer ist
    erlaubt — verschickt wird dann eben nichts."""
    sauber = (email or "").strip()
    if sauber and ("@" not in sauber or " " in sauber):
        raise HTTPException(400, f"„{sauber}“ sieht nicht wie eine "
                                 "E-Mail-Adresse aus.")
    return sauber


class NutzerIn(BaseModel):
    name: str = ""
    email: str = ""
    notiz: str = ""


@router.get("/{slug}/nutzer")
def nutzer(slug: str, session: Session = Depends(get_session),
           o: Objekt = Depends(objekt_holen)) -> dict:
    """Wer an dieser Ladestation lädt. Nicht zwangsläufig Eigentümer — es kann
    jeder sein."""
    return {"objekt": o.name, "nutzer": nutzer_lesen(session, slug)}


@router.post("/{slug}/nutzer", status_code=201)
def nutzer_anlegen(slug: str, data: NutzerIn,
                   session: Session = Depends(get_session),
                   o: Objekt = Depends(objekt_holen)) -> dict:
    """Einen Nutzer ergänzen. Beliebig viele, jederzeit."""
    liste = nutzer_lesen(session, slug)
    eintrag = {"id": max((n["id"] for n in liste), default=0) + 1,
               "name": _pruefe_name(data.name, liste),
               "email": _pruefe_email(data.email),
               "notiz": (data.notiz or "").strip()}
    liste.append(eintrag)
    _nutzer_schreiben(session, slug, liste)
    log.info("E-Tankstelle %s: Nutzer „%s“ angelegt", o.slug, eintrag["name"])
    return eintrag


@router.put("/{slug}/nutzer/{nid}")
def nutzer_aendern(slug: str, nid: int, data: NutzerIn,
                   session: Session = Depends(get_session),
                   o: Objekt = Depends(objekt_holen)) -> dict:
    """Name oder Adresse berichtigen. Leere Felder lassen den Wert stehen —
    ein nicht mitgeschicktes Feld darf nichts löschen."""
    liste = nutzer_lesen(session, slug)
    eintrag = next((n for n in liste if n["id"] == nid), None)
    if eintrag is None:
        raise HTTPException(404, "Nutzer nicht gefunden")
    if (data.name or "").strip():
        eintrag["name"] = _pruefe_name(data.name, liste, eigene_id=nid)
    if (data.email or "").strip():
        eintrag["email"] = _pruefe_email(data.email)
    if (data.notiz or "").strip():
        eintrag["notiz"] = data.notiz.strip()
    _nutzer_schreiben(session, slug, liste)
    return eintrag


@router.delete("/{slug}/nutzer/{nid}")
def nutzer_entfernen(slug: str, nid: int,
                     session: Session = Depends(get_session),
                     o: Objekt = Depends(objekt_holen)) -> dict:
    """Einen Nutzer aus der Liste nehmen — eine bewusste Handlung des Nutzers.

    Erfasste Ladungen bleiben **unangetastet**; sie erscheinen in der
    Abrechnung dann als „nicht angelegt". Es geht nichts verloren."""
    liste = nutzer_lesen(session, slug)
    if not any(n["id"] == nid for n in liste):
        raise HTTPException(404, "Nutzer nicht gefunden")
    _nutzer_schreiben(session, slug, [n for n in liste if n["id"] != nid])
    log.info("E-Tankstelle %s: Nutzer %d entfernt", o.slug, nid)
    return {"ok": True}


# ==========================================================================
# Datenquellen — erst die Wallbox, dann die erfassten Ladungen
# ==========================================================================

def _wallbox_bereit() -> bool:
    """Ist die Wallbox-Anbindung da und hat sie die Form, die hier gebraucht
    wird? Fehlt sie, wird nicht geraten, sondern zurückgefallen."""
    return httpx is not None and openwb is not None and all(
        hasattr(openwb, name) for name in
        ("normalisiere_basis", "protokoll_url", "jahre", "lies",
         "zusammenfuehren", "OpenwbFehler"))


def _protokoll(basis: str, jahr: int) -> str:
    """Das Ladeprotokoll eines Jahres holen — nur GET, knapper Timeout."""
    adresse = openwb.protokoll_url(basis, jahr)
    try:
        antwort = httpx.get(adresse, timeout=TIMEOUT, follow_redirects=True)
    except Exception as fehler:            # noqa: BLE001 - httpx-Fehlerbaum
        raise openwb.OpenwbFehler(
            f"Die Wallbox ist unter {basis} nicht erreichbar ({fehler}).") \
            from fehler
    if antwort.status_code != 200:
        raise openwb.OpenwbFehler(
            f"Die Wallbox antwortete für {jahr} mit HTTP "
            f"{antwort.status_code}. Stimmt die Adresse?")
    return antwort.text


def wallbox_posten(session: Session, von: date,
                   bis: date) -> tuple[list[Posten], str]:
    """Die Ladungen aus der Wallbox — ``([], Grund)``, wenn sie nichts sagt."""
    if not _wallbox_bereit():
        return [], ("Die Anbindung an die Wallbox ist auf diesem Stand noch "
                    "nicht verfügbar.")
    basis = openwb.normalisiere_basis(_lies(session, S_OPENWB_URL))
    if not basis:
        return [], ("Für die Wallbox ist noch keine Adresse hinterlegt "
                    "(Einstellungen → openWB).")
    try:
        alle: list = []
        for jahr in openwb.jahre(von, bis):
            alle = openwb.zusammenfuehren(alle,
                                          openwb.lies(_protokoll(basis, jahr)).ladungen)
    except openwb.OpenwbFehler as fehler:
        log.info("E-Tankstelle: Wallbox nicht auswertbar — %s", fehler)
        return [], str(fehler)
    return [Posten(tag=l.tag, kwh=l.kwh, extern_kwh=l.extern_kwh,
                   eigen_kwh=l.eigen_kwh)
            for l in alle if von <= l.tag <= bis], ""


def _jahresverhaeltnis(session: Session, objekt_id: int,
                       jahr: int) -> tuple[float, float] | None:
    """Die von Hand gepflegte Aufteilung Netz/eigen eines Jahres (N124).

    Ohne Wallbox ist das die einzige Aussage darüber, woher der Ladestrom kam.
    Sie gilt fürs ganze Jahr und wird auf die Monate übertragen — als Schätzung
    gekennzeichnet, nicht als Messung."""
    sj = session.exec(select(Stromjahr).where(
        Stromjahr.objekt_id == objekt_id, Stromjahr.jahr == jahr)).first()
    if not sj:
        return None
    extern = getattr(sj, "eauto_extern_kwh", 0.0) or 0.0
    eigen = getattr(sj, "eauto_eigen_kwh", 0.0) or 0.0
    return (extern, eigen) if extern + eigen > 0 else None


def erfasste_ladungen(session: Session, objekt_id: int, von: date,
                      bis: date) -> list[Tankladung]:
    """Die erfassten Ladungen eines Zeitraums.

    Gefiltert wird über das Datum. Ladungen ohne Datum lassen sich keinem Monat
    zuordnen; sie zählen über ihr `jahr` mit, sobald dieses ganz im Zeitraum
    liegt — sonst bliebe eine bezahlte Ladung unsichtbar."""
    liste = session.exec(
        select(Tankladung).where(Tankladung.objekt_id == objekt_id)
        .order_by(Tankladung.datum, Tankladung.id)).all()
    passend = []
    for l in liste:
        if l.datum is not None:
            if von <= l.datum <= bis:
                passend.append(l)
        elif von <= date(l.jahr, 1, 1) and date(l.jahr, 12, 31) <= bis:
            passend.append(l)
    return passend


def erfasste_posten(session: Session, objekt_id: int, von: date,
                    bis: date) -> tuple[list[Posten], bool]:
    """Die erfassten Ladungen als Verlaufs-Posten — plus die Angabe, ob die
    Aufteilung Netz/eigen dabei geschätzt wurde."""
    verhaeltnisse: dict[int, tuple[float, float] | None] = {}
    posten, geschaetzt = [], False
    for l in erfasste_ladungen(session, objekt_id, von, bis):
        tag = l.datum or date(l.jahr, 1, 1)
        if l.jahr not in verhaeltnisse:
            verhaeltnisse[l.jahr] = _jahresverhaeltnis(session, objekt_id, l.jahr)
        anteil = verhaeltnisse[l.jahr]
        if anteil and l.kwh:
            extern, eigen = anteil
            quote = extern / (extern + eigen)
            posten.append(Posten(tag=tag, kwh=l.kwh,
                                 extern_kwh=l.kwh * quote,
                                 eigen_kwh=l.kwh * (1 - quote)))
            geschaetzt = True
        else:
            posten.append(Posten(tag=tag, kwh=l.kwh))
    return posten, geschaetzt


def _person(l: Tankladung, namen: dict[int, str]) -> str:
    """Wer geladen hat: die verknüpfte Person, sonst der freie Name."""
    return namen.get(l.person_id or 0, "") or l.name or "—"


def buchungen(session: Session, objekt_id: int, von: date,
              bis: date) -> list[Buchung]:
    """Die erfassten Ladungen als Abrechnungszeilen."""
    namen = {e.id: e.name for e in session.exec(select(Eigentuemer)).all()}
    return [Buchung(tag=l.datum, person=_person(l, namen), email=l.email or "",
                    kwh=l.kwh or 0.0, preis=l.preis or 0.0)
            for l in erfasste_ladungen(session, objekt_id, von, bis)]


def satz_fuer(session: Session, objekt_id: int, jahr: int) -> float:
    """Der gepflegte Satz je kWh (`Stromjahr.tanken_preis`) — nur gelesen."""
    sj = session.exec(select(Stromjahr).where(
        Stromjahr.objekt_id == objekt_id, Stromjahr.jahr == jahr)).first()
    return (sj.tanken_preis if sj else 0.0) or 0.0


# ==========================================================================
# Verlauf und Abrechnung
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
                   session: Session = Depends(get_session),
                   o: Objekt = Depends(objekt_holen)) -> dict:
    """Der monatliche Verlauf: kWh je Monat, aufgeteilt in Netzbezug und
    eigenen Strom (Speicher + PV), jeweils mit Prozentangabe.

    Zuerst wird die Wallbox gefragt; meldet sie sich nicht, treten die
    erfassten Ladungen an ihre Stelle. Welche Quelle gesprochen hat, steht in
    `quelle` — die Zahlen sollen nie unerklärt springen."""
    von, bis = _zeitraum(jahr or date.today().year, quartal, von, bis)
    posten, grund = wallbox_posten(session, von, bis)
    quelle, hinweis = "wallbox", ""
    if not posten:
        ersatz, geschaetzt = erfasste_posten(session, o.id, von, bis)
        if grund:
            hinweis = (f"{grund} Gezeigt werden die erfassten Ladungen."
                       if ersatz else grund)
        quelle = "erfasst" if ersatz else "leer"
        posten = ersatz
        if geschaetzt:
            hinweis = (hinweis + " Die Aufteilung Netz/eigen ist aus den "
                       "Jahreswerten übertragen.").strip()

    try:
        zeilen = verlauf(posten, von, bis)
    except ValueError as fehler:
        raise HTTPException(400, str(fehler)) from fehler
    summe = verlauf_summe(zeilen)

    # Die Wallbox schreibt gelegentlich 0 % in alle vier Anteile (gesehen am
    # 12.07.2026). Diese Menge gehört weder in den einen noch in den anderen
    # Topf — sie wird benannt, nicht verteilt.
    if (summe["rest_kwh"] or 0) > 0.05:
        hinweis = (f"{hinweis} {deutsch(summe['rest_kwh'])} kWh "
                   f"({deutsch(summe['rest_prozent'] or 0.0, 1)} %) ordnet die "
                   "Wallbox weder dem Netz noch der eigenen Anlage zu — die "
                   "Energieanteile im Ladeprotokoll ergeben dort keine "
                   "100 %.").strip()

    return {"objekt": o.name, "von": von.isoformat(), "bis": bis.isoformat(),
            "quelle": quelle, "hinweis": hinweis, "monate": zeilen,
            "summe": summe}


def _abrechnung(session: Session, o: Objekt, slug: str, jahr: int,
                quartal: int) -> dict:
    """Die Abrechnung eines Zeitraums — von Vorschau, Liste und Versand
    gemeinsam benutzt, damit alle drei dasselbe sagen."""
    von, bis = _zeitraum(jahr, quartal, None, None)
    liste = nutzer_lesen(session, slug)
    satz = satz_fuer(session, o.id, jahr)
    zeilen = abrechne(buchungen(session, o.id, von, bis), liste, satz)
    return {"objekt": o.name, "jahr": jahr, "quartal": quartal,
            "label": zeitraum_label(jahr, quartal),
            "von": von.isoformat(), "bis": bis.isoformat(), "satz": satz,
            "nutzer": zeilen,
            "kwh_gesamt": round(sum(z["kwh"] for z in zeilen), 3),
            "betrag_gesamt": round(sum(z["betrag"] for z in zeilen), 2)}


@router.get("/{slug}/abrechnung")
def abrechnung_zeigen(slug: str, jahr: int = Query(default=0),
                      quartal: int = Query(default=0),
                      session: Session = Depends(get_session),
                      o: Objekt = Depends(objekt_holen)) -> dict:
    """Was jeder Nutzer geladen hat, zu welchem Satz, und was er zahlt.

    `quartal=0` rechnet das ganze Jahr ab."""
    return _abrechnung(session, o, slug, jahr or date.today().year, quartal)


def _zeile_holen(daten: dict, nutzer_id: int, name: str) -> dict:
    """Die Abrechnungszeile eines Nutzers — über die Kennung oder den Namen."""
    for z in daten["nutzer"]:
        if (nutzer_id and z["nutzer_id"] == nutzer_id) or \
           (name and schluessel(z["name"]) == schluessel(name)):
            return z
    raise HTTPException(404, "Für diesen Nutzer gibt es keine Abrechnung.")


def _eigen_prozent(session: Session, o: Objekt, von: date,
                   bis: date) -> float | None:
    """Wie viel des Ladestroms im Zeitraum aus der eigenen Anlage kam — für den
    Satz in der Mail. Ist es unbekannt, steht der Satz einfach nicht da."""
    posten, _ = wallbox_posten(session, von, bis)
    if not posten:
        posten, _ = erfasste_posten(session, o.id, von, bis)
    if not posten:
        return None
    try:
        return verlauf_summe(verlauf(posten, von, bis))["eigen_prozent"]
    except ValueError:
        return None


@router.get("/{slug}/vorschau")
def vorschau(slug: str, jahr: int = Query(default=0),
             quartal: int = Query(default=0), nutzer_id: int = Query(default=0),
             name: str = Query(default=""),
             session: Session = Depends(get_session),
             o: Objekt = Depends(objekt_holen)) -> dict:
    """Die Mail, wie sie beim Nutzer ankäme — verschickt wird hier nichts."""
    daten = _abrechnung(session, o, slug, jahr or date.today().year, quartal)
    zeile = _zeile_holen(daten, nutzer_id, name)
    von = date.fromisoformat(daten["von"])
    bis = date.fromisoformat(daten["bis"])
    return {"an": zeile["email"], "name": zeile["name"],
            "betreff": f"E-Tankstelle {o.name} — Abrechnung {daten['label']}",
            "text": abrechnungstext(o.name, zeile, von, bis, daten["label"],
                                    _eigen_prozent(session, o, von, bis)),
            "betrag": zeile["betrag"], "kwh": zeile["kwh"],
            "label": daten["label"]}


class VersandIn(BaseModel):
    """Wer bekommt für welches Quartal seine Abrechnung."""
    nutzer_id: int = 0
    name: str = ""
    jahr: int = 0
    quartal: int = 0
    an: str = ""                  # abweichende Adresse, sonst die hinterlegte


@router.post("/{slug}/versand")
def versenden(slug: str, data: VersandIn,
              session: Session = Depends(get_session),
              o: Objekt = Depends(objekt_holen)) -> dict:
    """Die Abrechnung eines Nutzers per Mail schicken — über das Postfach des
    Vermieters (dieselbe Strecke wie die Nebenkostenabrechnung).

    Ohne Betrag wird nicht verschickt: eine Rechnung über 0 € ist kein Vorgang,
    sondern eine Irritation."""
    daten = _abrechnung(session, o, slug, data.jahr or date.today().year,
                        data.quartal)
    zeile = _zeile_holen(daten, data.nutzer_id, data.name)
    adresse = _pruefe_email(data.an) or zeile["email"]
    if not adresse:
        raise HTTPException(400, f"Für {zeile['name']} ist keine "
                                 "E-Mail-Adresse hinterlegt.")
    if zeile["kwh"] <= 0:
        raise HTTPException(400, f"{zeile['name']} hat im Zeitraum "
                                 f"{daten['label']} nichts geladen.")

    von = date.fromisoformat(daten["von"])
    bis = date.fromisoformat(daten["bis"])
    betreff = f"E-Tankstelle {o.name} — Abrechnung {daten['label']}"
    text = abrechnungstext(o.name, zeile, von, bis, daten["label"],
                           _eigen_prozent(session, o, von, bis))
    try:
        zugang(session).sende(adresse, betreff, text)
    except MailFehler as fehler:
        raise HTTPException(400, str(fehler)) from fehler
    log.info("E-Tankstelle %s: Abrechnung %s an %s versendet", o.slug,
             daten["label"], adresse)
    return {"ok": True, "an": adresse, "label": daten["label"],
            "betrag": zeile["betrag"]}
