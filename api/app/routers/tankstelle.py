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
"""
from __future__ import annotations

import json
import logging
from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlmodel import Session, select

from ..cloudkern import _lies
from ..db import get_session
from ..deps import objekt_holen
from ..mailversand import MailFehler
from ..models import (Eigentuemer, Einstellung, Objekt, Stromjahr, Tankladung,
                      Tanknutzer, Zeitraum)
from ..tankabrechnung_pdf import tankabrechnung_pdf, tank_pdf_dateiname
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

# Wie weit zurück nach Ladungen gesucht wird, wenn niemand einen Zeitraum
# nennt. Ein Jahr ohne Ladungen beantwortet die Box mit der blossen Kopfzeile —
# der Blick zurück kostet im Heimnetz Millisekunden.
RUECKBLICK_JAHRE = 9

# Eigener Strom (PV und Akku) kostet an der Ladestation 10 % weniger als
# zugekaufter. Feste Vorgabe des Betreibers — keine gerechnete Größe, deshalb
# hier einmal benannt statt als nackte 0,9 im Code verstreut.
EIGEN_RABATT = 0.10

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
    einer erfundenen 0.

    `pv_kwh` und `speicher_kwh` teilen den eigenen Strom in die beiden Blöcke
    auf, über die der Nutzer abrechnet (N143). Nur die Wallbox kennt sie; die
    aus Jahreswerten übertragene Schätzung kennt bloß „eigen" und lässt sie
    ``None``. `rest_kwh` sagt, wie viel davon über die Rest-Regel in den
    PV-Block kam — die Menge wird nicht verwischt, nur nicht mehr als eigener
    Topf gezeigt."""
    tag: date
    kwh: float
    extern_kwh: float | None = None
    eigen_kwh: float | None = None
    pv_kwh: float | None = None
    speicher_kwh: float | None = None
    rest_kwh: float = 0.0

    def __post_init__(self) -> None:
        """Wer die beiden Blöcke nennt, muss „eigen" nicht auch noch nennen."""
        if self.eigen_kwh is None and None not in (self.pv_kwh,
                                                   self.speicher_kwh):
            self.eigen_kwh = self.pv_kwh + self.speicher_kwh


@dataclass
class Buchung:
    """Eine Ladung, die einer Person zugeordnet ist — die Abrechnungszeile.

    Ohne Preis: der Satz wird abgeleitet und gilt für alle Ladungen des
    Zeitraums gleichermaßen (N148). `Tankladung.preis` bleibt als Spalte
    stehen, wird aber nicht mehr hereingereicht — ein alter Handwert soll die
    Rechnung nicht mehr bewegen."""
    tag: date | None
    person: str
    email: str
    kwh: float


@dataclass
class Satz:
    """Der abgeleitete Preis je kWh — mit seiner Herkunft (N148).

    `netz` ist der Durchschnittspreis des Netzbezugs, `eigen` liegt
    :data:`EIGEN_RABATT` darunter, `misch` ist der, den der Nutzer zahlt: eine
    Ladung speist sich aus beidem, gewichtet nach den Mengen des Zeitraums.

    Steht kein Satz fest, sind alle drei ``None`` und `grund` sagt, was dafür
    fehlt. **Keine 0,00 € als Notnagel** — eine Rechnung über null ohne
    erkennbaren Grund war hier schon einmal ein Problem."""
    netz: float | None = None
    eigen: float | None = None
    misch: float | None = None
    herkunft: str = ""
    grund: str = ""


def eigen_satz(netz_preis: float) -> float:
    """Was eigener Strom (PV und Akku) an der Ladestation kostet."""
    return round(netz_preis * (1.0 - EIGEN_RABATT), 5)


def mischsatz(netz_preis: float, eigen_preis: float, extern_kwh: float | None,
              eigen_kwh: float | None) -> float:
    """Der Satz einer Ladung: Netz und eigener Strom nach ihren Mengen.

    Ist die Aufteilung des Zeitraums nicht bekannt (`extern_kwh`/`eigen_kwh`
    sind dann ``None``), gilt der **Netzpreis**. Den günstigeren eigenen Satz
    zu unterstellen, ohne zu wissen, ob eigener Strom geflossen ist, wäre ein
    Rabatt auf Verdacht."""
    if extern_kwh is None or eigen_kwh is None:
        return netz_preis
    ganz = max(0.0, extern_kwh) + max(0.0, eigen_kwh)
    if ganz <= 0:
        return netz_preis
    return round((max(0.0, extern_kwh) * netz_preis
                  + max(0.0, eigen_kwh) * eigen_preis) / ganz, 5)


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
    """Prozentanteil — ``None``, wenn es nichts zu teilen gibt.

    ``or 0.0`` fängt die negative Null ab: sie käme als „−0,0 %" auf die
    Seite und sähe aus wie ein Vorzeichenfehler."""
    return (round(teil / ganz * 100.0, 1) or 0.0) if ganz > 0 else None


def verlauf(posten: list[Posten], von: date, bis: date) -> list[dict]:
    """Je Monat: wie viel geladen wurde und in welchen Blöcken.

    Gefiltert wird über den Tag der Ladung (beide Ränder zählen). Kennt auch
    nur eine Ladung des Monats ihre Herkunft nicht, gilt die Aufteilung des
    Monats als unvollständig (`aufteilung: false`) — dann steht die Menge da,
    aber keine Prozentzahl, die niemand belegen kann. Kennt der Monat zwar
    Netz und eigen, aber nicht die Trennung PV/Akku, steht `dreiteilig` auf
    ``false``; das ist der Fall bei der aus Jahreswerten übertragenen
    Schätzung.

    kWh, die die Wallbox keinem Anteil zuordnet, zählen zum **PV-Block** und
    damit zum eigenen Strom (N143, Entscheidung des Nutzers). Sie stecken
    bereits in `pv_kwh`/`eigen_kwh`; `rest_kwh` sagt, wie viel auf diesem Weg
    dazukam. Ein eigener Topf „nicht zugeordnet" entsteht daraus nicht mehr —
    dafür gilt wieder ``Netz + eigen == geladen``."""
    eimer: dict[tuple[int, int], dict] = {
        (j, m): {"jahr": j, "monat": m, "kurz": MONATSKURZ[m - 1],
                 "label": f"{MONATSKURZ[m - 1]} {j}", "anzahl": 0, "kwh": 0.0,
                 "extern_kwh": 0.0, "eigen_kwh": 0.0, "pv_kwh": 0.0,
                 "speicher_kwh": 0.0, "rest_kwh": 0.0,
                 "aufteilung": True, "dreiteilig": True}
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
            eimer_monat["dreiteilig"] = False
            continue
        eimer_monat["extern_kwh"] += p.extern_kwh
        eimer_monat["eigen_kwh"] += p.eigen_kwh
        eimer_monat["rest_kwh"] += p.rest_kwh
        if p.pv_kwh is None or p.speicher_kwh is None:
            eimer_monat["dreiteilig"] = False
        else:
            eimer_monat["pv_kwh"] += p.pv_kwh
            eimer_monat["speicher_kwh"] += p.speicher_kwh

    return [_monatszeile(eimer[s]) for s in monatsfolge(von, bis)]


def _monatszeile(m: dict) -> dict:
    """Ein gefüllter Eimer als Ausgabezeile — gerundet, mit Prozenten."""
    kwh = round(m["kwh"], 2)
    offen = not m["aufteilung"]
    grob = not m["dreiteilig"]

    def menge(name: str, unbekannt: bool) -> float | None:
        # `or 0.0` macht aus der negativen Null eine glatte 0 — „−0,00 kWh"
        # wäre eine Irritation ohne Aussage.
        return None if unbekannt else (round(m[name], 2) or 0.0)

    werte = {"extern_kwh": menge("extern_kwh", offen),
             "eigen_kwh": menge("eigen_kwh", offen),
             "rest_kwh": menge("rest_kwh", offen),
             "pv_kwh": menge("pv_kwh", grob),
             "speicher_kwh": menge("speicher_kwh", grob)}
    prozente = {name.replace("_kwh", "_prozent"):
                None if wert is None else _prozent(wert, kwh)
                for name, wert in werte.items()}
    return {**m, "kwh": kwh, **werte, **prozente}


def verlauf_summe(zeilen: list[dict]) -> dict:
    """Die Summenzeile unter dem Verlauf — mit denselben Regeln wie oben.

    Summiert werden die **angezeigten** Monatswerte, nicht die Rohdaten: eine
    Summe, die nicht der Summe der Zeilen darüber entspricht, sieht wie ein
    Rechenfehler aus. Gegenüber der ungerundeten Summe kann das um einen
    Hundertstel-kWh abweichen."""
    kwh = round(sum(z["kwh"] for z in zeilen), 2)
    vollstaendig = all(z["aufteilung"] for z in zeilen)
    dreiteilig = all(z["dreiteilig"] for z in zeilen)

    def summe(name: str, unbekannt: bool) -> float | None:
        return (None if unbekannt
                else (round(sum(z[name] or 0.0 for z in zeilen), 2) or 0.0))

    werte = {"extern_kwh": summe("extern_kwh", not vollstaendig),
             "eigen_kwh": summe("eigen_kwh", not vollstaendig),
             "rest_kwh": summe("rest_kwh", not vollstaendig),
             "pv_kwh": summe("pv_kwh", not dreiteilig),
             "speicher_kwh": summe("speicher_kwh", not dreiteilig)}
    prozente = {name.replace("_kwh", "_prozent"):
                None if wert is None else _prozent(wert, kwh)
                for name, wert in werte.items()}
    return {"anzahl": sum(z["anzahl"] for z in zeilen), "kwh": kwh,
            **werte, **prozente,
            "aufteilung": vollstaendig, "dreiteilig": dreiteilig}


def schluessel(name: str) -> str:
    """Ein Name als Vergleichsschlüssel — die Brücke zwischen der Nutzerliste
    und den erfassten Ladungen.

    Beide führen den Namen als Text; „Marvin " und „marvin" sind dieselbe
    Person."""
    return " ".join((name or "").split()).casefold()


def abrechne(buchungen: list[Buchung], nutzer: list[dict],
             satz: float | None) -> list[dict]:
    """Je Nutzer: geladene Menge, Satz und Betrag.

    Der Satz ist abgeleitet (N148) und gilt für alle Ladungen des Zeitraums
    gleichermaßen — es gibt keinen Preis je Ladung mehr. Ist er ``None``,
    bleiben `betrag` und `satz` ebenfalls ``None``: die Mengen stehen da, aber
    kein Geldbetrag, den niemand belegen kann. **Eine 0,00 € wäre hier eine
    Behauptung**, keine Rechnung.

    Angelegte Nutzer ohne Ladung erscheinen mit 0 — sonst verschwände jemand
    aus der Liste, nur weil er ein Quartal lang nicht geladen hat. Ladungen auf
    Namen, die (noch) nicht in der Liste stehen, stehen am Ende mit
    ``angelegt: false``: übergehen wäre stilles Verschlucken von Geld."""
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
        zeile["anzahl"] += 1
        zeile["kwh"] += b.kwh
        if satz is not None:
            zeile["betrag"] += b.kwh * satz
        if not zeile["email"] and b.email:
            zeile["email"] = b.email
        zeile["ladungen"].append({
            "datum": b.tag.isoformat() if b.tag else None,
            "kwh": round(b.kwh, 3),
            "preis": None if satz is None else round(satz, 4),
            "betrag": None if satz is None else round(b.kwh * satz, 2)})

    fertig = []
    for zeile in zeilen.values():
        fertig.append({**zeile, "kwh": round(zeile["kwh"], 3),
                       "betrag": None if satz is None
                                 else round(zeile["betrag"], 2),
                       "satz": None if satz is None else round(satz, 4)})
    # Wer geladen hat, steht oben; danach alphabetisch — eine Reihenfolge, die
    # sich zwischen zwei Aufrufen nicht von selbst ändert.
    fertig.sort(key=lambda z: (-z["kwh"], schluessel(z["name"])))
    return fertig


def posten_als_buchungen(posten: list[Posten],
                         nutzer: list[dict]) -> tuple[list[Buchung], bool]:
    """N165 — die automatische Zuordnung bei **genau einem** Nutzer.

    Solange nur eine Person an der Station lädt, gibt es nichts zu entscheiden:
    ihr gehören alle Ladungen des Zeitraums, ohne dass jede von Hand zugebucht
    werden müsste. Grundlage sind die tatsächlich geladenen Mengen (`posten` —
    aus der Wallbox oder den erfassten Ladungen), nicht die per Namen erfassten
    `Tankladung`-Sätze: sonst bliebe die Abrechnung leer, obwohl kWh geflossen
    sind.

    Rückgabe ``(buchungen, automatisch)``. `automatisch` ist ``True``, wenn die
    Zuordnung so entstanden ist — damit die Oberfläche sie als das ausweisen
    kann, was sie ist, statt sie wie eine Handeingabe aussehen zu lassen. Bei
    mehreren (oder keinem) Nutzer bleibt es bei der Zuordnung über den Namen;
    die feinere Mehrnutzer-Regel kommt in einem zweiten Schritt."""
    if len(nutzer) != 1:
        return [], False
    n = nutzer[0]
    return ([Buchung(tag=p.tag, person=n["name"], email=n.get("email", ""),
                     kwh=p.kwh) for p in posten if p.kwh], True)


def deutsch(wert: float, stellen: int = 2) -> str:
    """Eine Zahl in deutscher Schreibweise: „1.234,56".

    Python setzt Komma und Punkt genau andersherum; `translate` tauscht
    beide in einem Durchgang — nacheinander ersetzen würde die eigene
    Arbeit wieder einsammeln."""
    return f"{wert:,.{stellen}f}".translate(str.maketrans(",.", ".,"))


def abrechnungstext(objekt_name: str, zeile: dict, von: date, bis: date,
                    label: str, eigen_prozent: float | None,
                    herkunft: str = "") -> str:
    """Die Abrechnung als Text für die Mail — dieselbe Grundlage wie die
    Vorschau auf der Seite, damit niemand etwas anderes verschickt, als er
    gesehen hat.

    `herkunft` sagt, woraus der Satz entstanden ist. Sie steht in der Mail,
    weil der Empfänger sonst eine Zahl bekäme, die er nicht nachprüfen kann.
    Ohne Satz nennt der Text die Menge und sagt offen, dass der Preis noch
    aussteht — statt eine 0,00-€-Forderung zu stellen."""
    def tag(d: date) -> str:
        return d.strftime("%d.%m.%Y")

    def geld(wert: float | None) -> str:
        return "—" if wert is None else f"{deutsch(wert)} €"

    def menge(wert: float) -> str:
        return f"{deutsch(wert)} kWh"

    zeilen = [f"Hallo {zeile['name']},", "",
              f"hier die Abrechnung deiner Ladungen an der E-Tankstelle "
              f"{objekt_name} für {label} ({tag(von)} – {tag(bis)}).", "",
              f"Geladen    {menge(zeile['kwh'])}"]
    if zeile["satz"] is None:
        zeilen += ["Satz       steht noch nicht fest",
                   "Zu zahlen  —", ""]
    else:
        zeilen += [f"Satz       {deutsch(zeile['satz'], 4)} € je kWh",
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

    if herkunft:
        zeilen.append(f"Der Satz ist nicht gesetzt, sondern gerechnet: "
                      f"{herkunft}. Eigener Strom aus PV und Akku kostet "
                      f"{deutsch(EIGEN_RABATT * 100, 0)} % weniger als "
                      "zugekaufter.")
        zeilen.append("")

    zeilen.append("Viele Grüße")
    return "\n".join(zeilen) + "\n"


# ==========================================================================
# Nutzerliste — in der Tabelle `Tanknutzer` (N164)
#
# Bis N164 lagen die Nutzer als JSON in einer `Einstellung` — das trug nur
# Name und E-Mail. Für die Quartalsabrechnung braucht es Anschrift und
# Bankverbindung; die gehören in eine eigene Tabelle. Der alte JSON-Schlüssel
# bleibt unangetastet stehen (CLAUDE.md: nie löschen); sein Inhalt wird einmalig
# in die Tabelle übernommen (`_migriere_json_nutzer`).
# ==========================================================================

def _nutzer_schluessel(slug: str) -> str:
    return f"{S_NUTZER}:{slug}"


def _migriert_schluessel(slug: str) -> str:
    return f"{S_NUTZER}_migriert:{slug}"


def _json_nutzer_lesen(session: Session, slug: str) -> list[dict]:
    """Der alte JSON-Bestand (nur Name + E-Mail + Notiz). Unlesbares JSON ergibt
    eine leere Liste und einen Log-Eintrag; es wird nichts überschrieben."""
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
        liste.append({"name": str(eintrag["name"]).strip(),
                      "email": str(eintrag.get("email", "")).strip(),
                      "notiz": str(eintrag.get("notiz", "")).strip()})
    return liste


def _migriere_json_nutzer(session: Session, o: Objekt) -> None:
    """Den alten JSON-Bestand einmalig in die Tabelle übernehmen.

    Läuft genau einmal je Objekt (ein Marker in der Einstellungs-Ablage sperrt
    weitere Läufe). So wird ein gelöschter Nutzer nicht bei der nächsten Lesung
    aus dem alten JSON wieder auferstehen. Der JSON-Schlüssel selbst bleibt
    unangetastet stehen — er wird nur gelesen, nie überschrieben."""
    if _lies(session, _migriert_schluessel(o.slug)):
        return
    schon_da = session.exec(select(Tanknutzer).where(
        Tanknutzer.objekt_id == o.id)).first()
    if schon_da is None:
        for e in _json_nutzer_lesen(session, o.slug):
            session.add(Tanknutzer(objekt_id=o.id, name=e["name"],
                                   email=e["email"], notiz=e["notiz"]))
        log.info("E-Tankstelle %s: alte Nutzerliste in die Tabelle übernommen",
                 o.slug)
    session.add(Einstellung(schluessel=_migriert_schluessel(o.slug), wert="1"))
    session.commit()


def _nutzer_dict(n: Tanknutzer) -> dict:
    """Ein Tanknutzer als das dict, mit dem die Rechen- und Anzeigelogik
    arbeitet — dieselben Schlüssel wie früher der JSON-Eintrag, plus die
    Stammdaten für den Versand."""
    return {"id": n.id, "name": n.name, "email": n.email or "",
            "person_id": n.person_id,
            "strasse": n.strasse or "", "plz": n.plz or "", "ort": n.ort or "",
            "iban": n.iban or "", "bic": n.bic or "",
            "kontoinhaber": n.kontoinhaber or "", "notiz": n.notiz or ""}


def nutzer_lesen(session: Session, objekt: Objekt | str) -> list[dict]:
    """Die Nutzer eines Objekts aus der Tabelle — vor dem ersten Lesen wird der
    alte JSON-Bestand einmalig übernommen.

    Nimmt ein :class:`Objekt` **oder** einen Slug: die eigenen Endpunkte reichen
    das aufgelöste Objekt herein, fremde Aufrufer (``routers/zaehler``) nur den
    Slug. Ein unbekannter Slug ergibt eine leere Liste statt eines Fehlers."""
    o = objekt
    if isinstance(o, str):
        o = session.exec(select(Objekt).where(Objekt.slug == o)).first()
        if o is None:
            return []
    _migriere_json_nutzer(session, o)
    liste = session.exec(select(Tanknutzer).where(
        Tanknutzer.objekt_id == o.id, Tanknutzer.aktiv == True)  # noqa: E712
        .order_by(Tanknutzer.id)).all()
    return [_nutzer_dict(n) for n in liste]


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
        notiz=(data.notiz or "").strip())
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
                 "notiz"):
        wert = getattr(data, feld)
        if wert is not None:
            setattr(n, feld, wert.strip())
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
        # Auch das Folgejahr holen: openWB legt eine Ladung nach ihrem **Ende**
        # ab. Die Ladung vom 31.12.2025 steht in der Datei 2026 — wer nur 2025
        # holt, verliert sie lautlos. Ein leeres Jahr kostet die Box nichts.
        alle: list = []
        for jahr in [*openwb.jahre(von, bis), bis.year + 1]:
            alle = openwb.zusammenfuehren(alle,
                                          openwb.lies(_protokoll(basis, jahr)).ladungen)
    except openwb.OpenwbFehler as fehler:
        log.info("E-Tankstelle: Wallbox nicht auswertbar — %s", fehler)
        return [], str(fehler)
    return [Posten(tag=l.tag, kwh=l.kwh, extern_kwh=l.extern_kwh,
                   pv_kwh=l.pv_kwh, speicher_kwh=l.speicher_kwh,
                   rest_kwh=l.rest_kwh)
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
    """Die erfassten Ladungen als Abrechnungszeilen.

    `Tankladung.preis` wird bewusst **nicht** übernommen (N148): der Satz ist
    abgeleitet und für alle Ladungen des Zeitraums derselbe."""
    namen = {e.id: e.name for e in session.exec(select(Eigentuemer)).all()}
    return [Buchung(tag=l.datum, person=_person(l, namen), email=l.email or "",
                    kwh=l.kwh or 0.0)
            for l in erfasste_ladungen(session, objekt_id, von, bis)]


# ==========================================================================
# Der Satz je kWh — abgeleitet aus der Stromkette (N148)
# ==========================================================================

def _stromkette_holen(session: Session, zid: int) -> dict:
    """Die Stromkette eines Zeitraums — erst beim Aufruf importiert.

    **Bewusst hier drin und nicht oben:** `routers/stromkette` importiert
    seinerseits `erfasste_ladungen` aus diesem Modul. Ein Import auf Modulebene
    liefe deshalb im Kreis und schlüge — je nach Ladereihenfolge — mit einem
    `ImportError` fehl, den ein `try/except` still zu „die Stromkette gibt es
    nicht" verharmlosen würde. Zur Aufrufzeit sind beide Module fertig
    geladen, und der Kreis löst sich auf."""
    from .stromkette import stromkette
    return stromkette(zid, session)


def _ueberlappung(a_von: date, a_bis: date, b_von: date, b_bis: date) -> int:
    """Wie viele Tage zwei Zeitspannen gemeinsam haben (beide Ränder zählen)."""
    return max(0, (min(a_bis, b_bis) - max(a_von, b_von)).days + 1)


def passender_zeitraum(zeitraeume: list[Zeitraum], von: date,
                       bis: date) -> Zeitraum | None:
    """Der Abrechnungszeitraum, der ein Quartal am weitesten trägt.

    Die Nebenkostenperiode läuft z. B. vom 01.10.2024 bis 30.09.2025, ein
    Quartal aber am Kalender entlang. Gewählt wird der Zeitraum mit der
    größten Überschneidung; bei Gleichstand der spätere — die jüngere Rechnung
    beschreibt den Preis besser. Ohne jede Überschneidung: ``None``."""
    treffer = [(_ueberlappung(z.start, z.ende, von, bis), z.start, z)
               for z in zeitraeume]
    treffer = [t for t in treffer if t[0] > 0]
    if not treffer:
        return None
    return max(treffer, key=lambda t: (t[0], t[1]))[2]


def satz_ableiten(session: Session, objekt_id: int, von: date, bis: date,
                  extern_kwh: float | None = None,
                  eigen_kwh: float | None = None) -> Satz:
    """Der Preis je kWh für einen Abrechnungszeitraum — aus der Stromkette.

    Netzstrom kostet den Durchschnittspreis des Netzbezugs: den Gesamtbetrag
    der Strom-Positionen geteilt durch die bezogenen kWh. Die Grundgebühr
    steckt im Betrag und wird **nicht** getrennt umgelegt — genau deshalb ist
    es ein Durchschnitt. Eigener Strom liegt :data:`EIGEN_RABATT` darunter.

    Eingegeben wird nichts: `Stromjahr.tanken_preis` und `Tankladung.preis`
    bleiben ungelesen. Fehlt die Rechnung, kommt ein leerer :class:`Satz` mit
    `grund` zurück — nicht 0,00 €."""
    zeitraeume = list(session.exec(
        select(Zeitraum).where(Zeitraum.objekt_id == objekt_id)).all())
    z = passender_zeitraum(zeitraeume, von, bis)
    if z is None:
        return Satz(grund="Für diesen Zeitraum gibt es noch keine "
                          "Abrechnungsperiode. Der Satz entsteht aus den "
                          "Stromkosten einer Periode — ohne sie lässt er sich "
                          "nicht ermitteln.")
    try:
        kette = _stromkette_holen(session, z.id)
    except Exception as fehler:            # noqa: BLE001 - fremde Kette
        log.info("E-Tankstelle: Stromkette %s nicht rechenbar — %s", z.id,
                 fehler)
        return Satz(grund=f"Die Stromkosten des Zeitraums "
                          f"{z.start:%d.%m.%Y} – {z.ende:%d.%m.%Y} lassen sich "
                          f"gerade nicht ermitteln ({fehler}).")

    schritt1 = kette.get("schritt1") or {}
    netz = schritt1.get("netz") or {}
    betrag, menge = netz.get("betrag") or 0.0, netz.get("kwh") or 0.0
    label = (kette.get("zeitraum") or {}).get("label", "")
    quelle = schritt1.get("quelle_betrag") or ""
    # Zwei Hälften, zwei verschiedene Lücken. Welche fehlt, gehört benannt —
    # „die Stromkosten fehlen" wäre falsch, wenn nur die Menge fehlt.
    if betrag <= 0:
        return Satz(grund=(
            f"Für den Zeitraum {label} ist noch kein Betrag für den Netzbezug "
            "erfasst. Der Satz entsteht aus diesem Betrag geteilt durch die "
            "bezogenen kWh — sobald die Stromkosten in den Nebenkosten "
            "stehen, rechnet er sich von selbst."))
    if menge <= 0:
        # Die Quellenangabe bringt selbst schon Klammern mit (Belegname) —
        # noch ein Klammerpaar drumherum liest sich wie ein Tippfehler.
        return Satz(grund=(
            f"Für den Zeitraum {label} steht der Betrag — "
            f"{quelle or f'{deutsch(betrag)} €'} —, aber nicht die bezogene "
            "Menge: ohne die kWh des Netzbezugs gibt es keinen "
            "Durchschnittspreis. Die Menge ergibt sich aus dem "
            "Gesamtverbrauch und den SolarEdge-Anteilen am Strom-Jahr."))

    netz_preis = round(betrag / menge, 5)
    eigen_preis = eigen_satz(netz_preis)
    return Satz(
        netz=netz_preis, eigen=eigen_preis,
        misch=mischsatz(netz_preis, eigen_preis, extern_kwh, eigen_kwh),
        herkunft=(f"{quelle or f'{deutsch(betrag)} € Netzbezug'} ÷ "
                  f"{deutsch(menge)} kWh Netzbezug "
                  f"aus der Stromkette des Zeitraums {label}"))


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


def suchfenster(heute: date | None = None) -> tuple[date, date]:
    """Das Fenster, in dem nach Ladungen gesucht wird, wenn niemand einen
    Zeitraum nennt.

    Bewusst grosszügig und trotzdem endlich: `RUECKBLICK_JAHRE` zurück bis zum
    Ende des laufenden Jahres. Die Wallbox beantwortet ein Jahr ohne Ladungen
    mit der blossen Kopfzeile — der Rückblick kostet fast nichts."""
    jetzt = heute or date.today()
    return date(jetzt.year - RUECKBLICK_JAHRE, 1, 1), date(jetzt.year, 12, 31)


def belegte_spanne(posten: list[Posten],
                   ersatz: tuple[date, date]) -> tuple[date, date]:
    """Vom ersten bis zum letzten Monat mit einer Ladung — volle Monate.

    Ohne eine einzige Ladung bleibt `ersatz` stehen: eine leere Grafik über
    zehn Jahre wäre keine Auskunft, das laufende Jahr schon."""
    tage = [p.tag for p in posten if p.tag and p.kwh > 0]
    if not tage:
        return ersatz
    erster, letzter = min(tage), max(tage)
    return (date(erster.year, erster.month, 1),
            date(letzter.year, letzter.month,
                 monthrange(letzter.year, letzter.month)[1]))


def jahre_mit_verbrauch(posten: list[Posten]) -> list[int]:
    """Die Jahre, in denen wirklich geladen wurde — aufsteigend.

    Grundlage der Jahresauswahl: ein Jahr ohne eine einzige Kilowattstunde
    gehört in keine Liste (N143)."""
    return sorted({p.tag.year for p in posten if p.tag and p.kwh > 0})


def _posten_holen(session: Session, o: Objekt, von: date,
                  bis: date) -> tuple[list[Posten], str, str]:
    """Die Ladungen eines Zeitraums — Wallbox zuerst, sonst die erfassten.

    Liefert ``(posten, quelle, hinweis)``. `quelle` ist „wallbox", „erfasst"
    oder „leer"; der Hinweis sagt, warum die Box nicht sprach. Nie eine stille
    Null."""
    posten, grund = wallbox_posten(session, von, bis)
    if posten:
        return posten, "wallbox", ""
    ersatz, geschaetzt = erfasste_posten(session, o.id, von, bis)
    hinweis = ""
    if grund:
        hinweis = (f"{grund} Gezeigt werden die erfassten Ladungen."
                   if ersatz else grund)
    if geschaetzt:
        hinweis = (hinweis + " Die Aufteilung Netz/eigen ist aus den "
                   "Jahreswerten übertragen; PV und Akku lassen sich daraus "
                   "nicht trennen.").strip()
    return ersatz, ("erfasst" if ersatz else "leer"), hinweis


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

    return {"objekt": o.name, "von": von.isoformat(), "bis": bis.isoformat(),
            "quelle": quelle, "hinweis": hinweis, "monate": zeilen,
            "summe": verlauf_summe(zeilen),
            "jahre": jahre_mit_verbrauch(posten)}


def _abrechnung(session: Session, o: Objekt, slug: str, jahr: int,
                quartal: int) -> dict:
    """Die Abrechnung eines Zeitraums — von Vorschau, Liste und Versand
    gemeinsam benutzt, damit alle drei dasselbe sagen.

    Abgerechnet wird ausschliesslich, was einer Person zugeordnet ist: die
    Wallbox weiss, wie viel geladen wurde, aber nicht von wem. Damit eine
    Abrechnung über 0 € nicht rätselhaft bleibt, steht daneben, wie viel im
    Zeitraum überhaupt geladen wurde (`geladen_kwh`) — die Lücke zwischen
    beiden Zahlen ist die Antwort auf „wieso passiert da nichts" (N143).

    Der Satz kommt aus der Stromkette (N148); die Mengen des Zeitraums sagen,
    wie stark Netz und eigener Strom darin gewichtet sind."""
    von, bis = _zeitraum(jahr, quartal, None, None)
    liste = nutzer_lesen(session, o)
    posten, quelle, _ = _posten_holen(session, o, von, bis)
    summe = verlauf_summe(verlauf(posten, von, bis)) if posten else {}
    satz = satz_ableiten(session, o.id, von, bis,
                         summe.get("extern_kwh"), summe.get("eigen_kwh"))
    # N165 — mit genau einem Nutzer gehören ihm automatisch alle Ladungen des
    # Zeitraums (aus den geladenen Mengen, nicht nur aus den namentlich
    # erfassten Sätzen). Bei mehreren bleibt es bei der Zuordnung über den Namen.
    auto_buch, automatisch = posten_als_buchungen(posten, liste)
    quelle_buch = auto_buch if automatisch else buchungen(session, o.id, von, bis)
    zeilen = abrechne(quelle_buch, liste, satz.misch)
    if automatisch:
        for z in zeilen:
            z["automatisch"] = z["kwh"] > 0
    zugeordnet = round(sum(z["kwh"] for z in zeilen), 3)
    return {"objekt": o.name, "jahr": jahr, "quartal": quartal,
            "label": zeitraum_label(jahr, quartal),
            "von": von.isoformat(), "bis": bis.isoformat(),
            "automatisch": automatisch,
            "satz": satz.misch, "satz_netz": satz.netz,
            "satz_eigen": satz.eigen, "satz_rabatt": EIGEN_RABATT,
            "satz_herkunft": satz.herkunft, "satz_grund": satz.grund,
            "nutzer": zeilen,
            "kwh_gesamt": zugeordnet,
            "betrag_gesamt": (None if satz.misch is None
                              else round(sum(z["betrag"] for z in zeilen), 2)),
            "geladen_kwh": summe.get("kwh"), "quelle": quelle,
            "offen_kwh": (None if not summe
                          else round(summe["kwh"] - zugeordnet, 2)),
            "eigen_prozent": summe.get("eigen_prozent")}


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
                                    daten["eigen_prozent"],
                                    daten["satz_herkunft"]),
            "betrag": zeile["betrag"], "kwh": zeile["kwh"],
            "satz": zeile["satz"], "satz_grund": daten["satz_grund"],
            "label": daten["label"]}


def _empfaenger(session: Session, zeile: dict) -> dict:
    """Anschrift und Name des Empfängers für das PDF — aus dem Tanknutzer,
    soweit vorhanden. Eine noch nicht angelegte Person hat keine Anschrift; dann
    steht nur ihr Name."""
    empf = {"name": zeile["name"], "email": zeile.get("email", ""),
            "strasse": "", "plz": "", "ort": ""}
    n = session.get(Tanknutzer, zeile["nutzer_id"]) if zeile.get("nutzer_id") else None
    if n is not None:
        empf.update(strasse=n.strasse or "", plz=n.plz or "", ort=n.ort or "",
                    kontoinhaber=n.kontoinhaber or "", iban=n.iban or "")
    return empf


def _quartal_verlauf(session: Session, o: Objekt, von: date,
                     bis: date) -> tuple[list[dict], dict]:
    """Die Monatszeilen des Quartals plus ihre Summe — die Grundlage von
    Diagramm und Tabelle im PDF."""
    posten, _, _ = _posten_holen(session, o, von, bis)
    monate = verlauf(posten, von, bis)
    return monate, verlauf_summe(monate)


@router.get("/{slug}/abrechnung.pdf")
def abrechnung_pdf_zeigen(slug: str, jahr: int = Query(default=0),
                          quartal: int = Query(default=0),
                          nutzer_id: int = Query(default=0),
                          name: str = Query(default=""),
                          session: Session = Depends(get_session),
                          o: Objekt = Depends(objekt_holen)) -> Response:
    """Die Quartalsabrechnung eines Nutzers als PDF — zum Ansehen und Prüfen,
    **ohne** dass etwas verschickt wird (N165).

    Kein PDF über 0 €: eine Rechnung ohne Betrag ist keine Rechnung. Fehlt der
    Satz oder hat der Nutzer nichts geladen, sagt die Antwort, woran es liegt,
    statt ein leeres Blatt zu erzeugen."""
    daten = _abrechnung(session, o, slug, jahr or date.today().year, quartal)
    zeile = _zeile_holen(daten, nutzer_id, name)
    if zeile["kwh"] <= 0:
        raise HTTPException(400, f"{zeile['name']} hat im Zeitraum "
                                 f"{daten['label']} nichts geladen — kein PDF.")
    if zeile["satz"] is None or not (zeile["betrag"] and zeile["betrag"] > 0):
        raise HTTPException(400, "Ohne Rechnungsbetrag gibt es kein PDF. "
                                 + (daten["satz_grund"] or ""))
    von = date.fromisoformat(daten["von"])
    bis = date.fromisoformat(daten["bis"])
    monate, summe = _quartal_verlauf(session, o, von, bis)
    satz = {"netz": daten["satz_netz"], "eigen": daten["satz_eigen"],
            "misch": daten["satz"], "herkunft": daten["satz_herkunft"],
            "grund": daten["satz_grund"], "rabatt": daten["satz_rabatt"]}
    inhalt = tankabrechnung_pdf(o.name, _empfaenger(session, zeile),
                                daten["label"], von, bis, monate, summe, satz,
                                zeile["kwh"], zeile["betrag"])
    dateiname = tank_pdf_dateiname(o.name, daten["label"], zeile["name"])
    return Response(content=inhalt, media_type="application/pdf", headers={
        "Content-Disposition": f'inline; filename="{dateiname}"'})


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
    sondern eine Irritation. Dasselbe gilt für einen Zeitraum ohne
    abgeleiteten Satz (N148) — dann fehlt der Preis, nicht die Menge."""
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
    if zeile["satz"] is None:
        raise HTTPException(400, "Für diesen Zeitraum steht noch kein Preis je "
                                 "kWh fest. " + daten["satz_grund"])

    von = date.fromisoformat(daten["von"])
    bis = date.fromisoformat(daten["bis"])
    betreff = f"E-Tankstelle {o.name} — Abrechnung {daten['label']}"
    text = abrechnungstext(o.name, zeile, von, bis, daten["label"],
                           daten["eigen_prozent"], daten["satz_herkunft"])
    try:
        zugang(session).sende(adresse, betreff, text)
    except MailFehler as fehler:
        raise HTTPException(400, str(fehler)) from fehler
    log.info("E-Tankstelle %s: Abrechnung %s an %s versendet", o.slug,
             daten["label"], adresse)
    return {"ok": True, "an": adresse, "label": daten["label"],
            "betrag": zeile["betrag"]}
