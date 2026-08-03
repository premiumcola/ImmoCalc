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

from .. import eauto
from ..cloudkern import _lies
from ..db import get_session
from ..deps import objekt_holen
from ..mailversand import MailFehler
from ..models import (Eigentuemer, Einstellung, Objekt, Stromjahr, Tankladung,
                      Tanknutzer, Zeitraum)
from ..tankabrechnung_pdf import tankabrechnung_pdf, tank_pdf_dateiname
from .ki import ki_key, ki_modell
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

# N165 Teil 2 — der Schalter „automatische Abrechnung" je Objekt. Standardmässig
# aus: verschickt wird nur, was der Nutzer bewusst freigegeben hat.
S_AUTOVERSAND = "tankstelle_autoversand"
# Die Mehrnutzer-Zuordnung je Objekt: Zeitraum-Regeln und ausgeschlossene
# Ladungen, als JSON in einer Einstellung.
S_ZUORDNUNG = "tankstelle_zuordnung"
# Der Versendet-Marker je Objekt+Quartal+Nutzer. Er ist die eine Zusicherung
# gegen doppelten Versand: der 15-Minuten-Wachdienst schickt ein bereits
# verschicktes Quartal nie ein zweites Mal.
S_VERSENDET = "tankstelle_versendet"
# N177 — Cache des von der KI ermittelten Benzinverbrauchs je E-Auto-Modell.
# Der Kostenvergleich im PDF braucht ihn; ein Cache spart wiederholte
# Netz-Aufrufe beim erneuten Ansehen desselben Quartals. Additiv, eigener
# Namensraum — kein bestehender Schlüssel wird angefasst.
S_BENZIN = "tankstelle_benzin"

# Wie viele Tage nach Quartalsende der automatische Versand noch nachholt. Der
# Auslöser ist „einen Tag nach dem Quartal" — dieses Fenster fängt ab, dass die
# App am Stichtag gerade aus war, ohne beim späteren Einschalten alte Quartale
# nachzublasen. Der Versendet-Marker verhindert Dopplungen innerhalb des
# Fensters.
GRACE_TAGE = 20

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


def quartale_monate(quartale: list[int]) -> list[int]:
    """Die Monatsnummern (1–12) einer Quartalsauswahl — aufsteigend, ohne
    Dopplung.

    Mehrere Quartale lassen sich zusammen abrechnen (N169): Q2 + Q3 ergeben die
    Monate April bis September. Ist ``0`` (ganzes Jahr) dabei, sind es alle
    zwölf."""
    monate: set[int] = set()
    for q in quartale:
        if q == 0:
            return list(range(1, 13))
        if q not in (1, 2, 3, 4):
            raise ValueError("Ein Quartal ist 1, 2, 3 oder 4 (0 = ganzes Jahr).")
        erster = 3 * (q - 1) + 1
        monate.update({erster, erster + 1, erster + 2})
    return sorted(monate)


def aktive_monate(quartale: list[int], aus) -> list[int]:
    """Die Monate der gewählten Quartale ohne die einzeln abgewählten (N169).

    Der Umstieg von der 4-Monats- auf die Quartalsabrechnung lässt einen Monat
    doppelt erscheinen (der April war schon in der alten Weise abgerechnet):
    darum lassen sich einzelne Monate eines Quartals ausschließen. `aus` ist die
    Menge der Monatsnummern, die draußen bleiben."""
    aus = set(aus or ())
    return [m for m in quartale_monate(quartale) if m not in aus]


def abrechnungs_label(jahr: int, quartale: list[int], aus) -> str:
    """Die Überschrift der Abrechnung — trägt die Quartalsauswahl und die
    abgewählten Monate (N169).

    „Q3 2025" wie bisher; „Q2/Q3 2025" für mehrere; „Jahr 2025" für das ganze
    Jahr. Abgewählte Monate stehen als „(ohne Apr)" dahinter, damit die
    Ausnahme sichtbar bleibt."""
    gewaehlt = sorted(set(quartale))
    aus = sorted(set(aus or ()))
    if gewaehlt == [0] or {1, 2, 3, 4}.issubset(set(gewaehlt)):
        basis = f"Jahr {jahr}"
    elif len(gewaehlt) == 1:
        basis = f"Q{gewaehlt[0]} {jahr}"
    else:
        basis = "/".join(f"Q{q}" for q in gewaehlt if q) + f" {jahr}"
    if aus:
        basis += " (ohne " + ", ".join(MONATSKURZ[m - 1] for m in aus) + ")"
    return basis


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


@dataclass
class RohLadung:
    """Eine erfasste Ladung, auf das reduziert, was die Zuordnung braucht.

    `id` ist der stabile Griff für den Ausschluss einzelner Ladungen; `name`
    ist die bisherige Zuordnung über den Namen, die greift, wenn keine
    Zeitraum-Regel passt."""
    id: int | None
    tag: date | None
    name: str
    email: str
    kwh: float


def _regel_treffer(regeln: list[dict], tag: date | None) -> dict | None:
    """Die Zeitraum-Regel, die einen Ladetag enthält (beide Ränder zählen).

    Ohne Datum lässt sich keine Regel anwenden — dann ``None``. Treffen mehrere
    Regeln denselben Tag (überlappende Zeiträume), gewinnt die mit dem
    **späteren Beginn**: die jüngere, engere Zuordnung überschreibt die ältere,
    breite. Bei gleichem Beginn entscheidet das spätere Ende. So ist die
    Auswahl deterministisch und für den Nutzer nachvollziehbar."""
    if tag is None:
        return None
    passend = [r for r in regeln if r["von"] <= tag <= r["bis"]]
    if not passend:
        return None
    return max(passend, key=lambda r: (r["von"], r["bis"]))


def zuordnen(rohe: list[RohLadung], nutzer: list[dict], regeln: list[dict],
             ausschluss: set[int]) -> list[Buchung]:
    """Erfasste Ladungen einer Person zuschlagen — über einen Zeitraum, nicht
    Ladung für Ladung (N165 Teil 2).

    Für jede Ladung: liegt ihr Tag in einer Zeitraum-Regel, gehört sie dem
    Nutzer dieser Regel; sonst bleibt es bei der bisherigen Zuordnung über den
    Namen (`RohLadung.name`) — so geht keine Ladung verloren, nur weil (noch)
    keine Regel sie trägt. Ausgeschlossene Ladungen (`ausschluss`, Menge von
    Ladungs-Ids) fallen ganz heraus; das ist der Korrekturweg für eine falsch
    zugeordnete Ladung. `regeln` trägt bereits geprüfte Regeln mit
    ``date``-Rändern und einer `nutzer_id`, die in `nutzer` steht."""
    nach_id = {n["id"]: n for n in nutzer}
    gueltig = [r for r in regeln if r.get("nutzer_id") in nach_id]
    ergebnis: list[Buchung] = []
    for l in rohe:
        if l.id is not None and l.id in ausschluss:
            continue
        treffer = _regel_treffer(gueltig, l.tag) if gueltig else None
        if treffer is not None:
            n = nach_id[treffer["nutzer_id"]]
            ergebnis.append(Buchung(tag=l.tag, person=n["name"],
                                    email=n.get("email", ""), kwh=l.kwh))
        else:
            ergebnis.append(Buchung(tag=l.tag, person=l.name, email=l.email,
                                    kwh=l.kwh))
    return ergebnis


def faelliges_quartal(heute: date | None = None) -> tuple[int, int] | None:
    """Das Quartal, dessen Abrechnung jetzt automatisch fällig ist — oder
    ``None``.

    Ausgelöst wird **einen Tag nach Quartalsende**: am 01.07. steht Q2 an, am
    01.01. das Q4 des Vorjahres. Fällig bleibt es :data:`GRACE_TAGE` Tage lang,
    damit ein am Stichtag ausgeschalteter Rechner es nachholen kann; danach
    nicht mehr, damit ein spät eingeschalteter Autoversand nicht rückwirkend
    alte Quartale verschickt."""
    heute = heute or date.today()
    q = (heute.month - 1) // 3 + 1
    jahr, quartal = (heute.year - 1, 4) if q == 1 else (heute.year, q - 1)
    ende = quartal_zeitraum(jahr, quartal)[1]
    return (jahr, quartal) if 1 <= (heute - ende).days <= GRACE_TAGE else None


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
            "kontoinhaber": n.kontoinhaber or "", "notiz": n.notiz or "",
            # N170 — das E-Auto und sein Verbrauch (0 = noch nicht gesetzt).
            "e_auto_modell": getattr(n, "e_auto_modell", "") or "",
            "verbrauch_kwh_100km": getattr(n, "verbrauch_kwh_100km", 0.0) or 0.0}


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
# Einstellungen je Objekt — Autoversand, Zuordnung, Versendet-Marker (N165/2)
#
# Alles in der vorhandenen Schlüssel/Wert-Ablage `Einstellung`; kein neues
# Modellfeld, keine Migration. Eigener Namensraum, es wird kein bestehender
# Schlüssel angefasst.
# ==========================================================================

def _setze(session: Session, schluessel: str, wert: str) -> None:
    """Eine Einstellung setzen (anlegen oder überschreiben) — ohne commit."""
    e = session.get(Einstellung, schluessel)
    if e is None:
        e = Einstellung(schluessel=schluessel, wert=wert)
    else:
        e.wert = wert
    session.add(e)


def autoversand_aktiv(session: Session, slug: str) -> bool:
    """Ist der automatische Versand für dieses Objekt eingeschaltet? Default aus."""
    return _lies(session, f"{S_AUTOVERSAND}:{slug}") == "1"


def _regel_pruefen(regel: dict, nach_id: dict[int, dict]) -> dict | None:
    """Eine rohe Regel aus der Einstellung in ``{nutzer_id, von, bis}`` mit
    ``date``-Rändern übersetzen — unbrauchbare Regeln fallen still weg.

    Eine kaputte gespeicherte Regel darf die Abrechnung nicht zum Absturz
    bringen: fehlt ein Feld oder liegt das Ende vor dem Beginn, wird sie
    übergangen (und beim nächsten Speichern von der Oberfläche berichtigt)."""
    try:
        nid = int(regel.get("nutzer_id"))
        von = date.fromisoformat(regel["von"])
        bis = date.fromisoformat(regel["bis"])
    except (TypeError, ValueError, KeyError):
        return None
    if nid not in nach_id or bis < von:
        return None
    return {"nutzer_id": nid, "von": von, "bis": bis}


def zuordnung_lesen(session: Session, slug: str,
                    nutzer: list[dict]) -> tuple[list[dict], set[int]]:
    """Die Mehrnutzer-Zuordnung eines Objekts: geprüfte Zeitraum-Regeln und die
    Menge ausgeschlossener Ladungs-Ids.

    Unlesbares JSON ergibt eine leere Zuordnung und einen Log-Eintrag — nie
    einen Fehler, der die Abrechnung anhält. Regeln auf gelöschte Nutzer fallen
    weg (`nutzer` ist die aktuelle Liste)."""
    roh = _lies(session, f"{S_ZUORDNUNG}:{slug}")
    if not roh:
        return [], set()
    try:
        daten = json.loads(roh)
    except ValueError:
        log.warning("Zuordnung der E-Tankstelle (%s) unlesbar — übergangen", slug)
        return [], set()
    if not isinstance(daten, dict):
        return [], set()
    nach_id = {n["id"]: n for n in nutzer}
    regeln = [g for g in (_regel_pruefen(r, nach_id)
                          for r in daten.get("regeln", []) if isinstance(r, dict))
              if g is not None]
    ausschluss = {int(x) for x in daten.get("ausschluss", [])
                  if isinstance(x, (int, str)) and str(x).lstrip("-").isdigit()}
    return regeln, ausschluss


def _versendet_schluessel(slug: str, jahr: int, quartal: int,
                          nutzer_id: int) -> str:
    return f"{S_VERSENDET}:{slug}:{jahr}:Q{quartal}:{nutzer_id}"


def _monat_schluessel(slug: str, jahr: int, monat: int, nutzer_id: int) -> str:
    """Der Marker-Schlüssel für einen **einzelnen Monat** (N187).

    Gleicher Namensraum wie der Quartalsmarker, nur mit ``M<monat>`` statt
    ``Q<quartal>`` — additiv, kein Quartalsmarker wird davon berührt."""
    return f"{S_VERSENDET}:{slug}:{jahr}:M{monat}:{nutzer_id}"


def ist_versendet(session: Session, slug: str, jahr: int, quartal: int,
                  nutzer_id: int) -> bool:
    """Wurde dieses Quartal an diesen Nutzer schon automatisch verschickt?"""
    return bool(_lies(session, _versendet_schluessel(slug, jahr, quartal,
                                                     nutzer_id)))


def _versendet_merken(session: Session, slug: str, jahr: int, quartal: int,
                      nutzer_id: int) -> None:
    """Den Versand festhalten — die eine Zusicherung gegen Dopplung. Ohne commit;
    der Aufrufer committet nach jedem erfolgreichen Versand einzeln."""
    _setze(session, _versendet_schluessel(slug, jahr, quartal, nutzer_id),
           date.today().isoformat())


def _expand_quartale(roh) -> list[int]:
    """Eine Quartalsauswahl auf die einzelnen Quartale 1–4 auflösen.

    ``0`` (ganzes Jahr) wird zu allen vier Quartalen; eine leere Auswahl bleibt
    leer. Unbrauchbare Werte fallen still weg — die Marker sind grob (je
    Quartal), der Feinschliff über abgewählte Monate spielt hier keine Rolle."""
    qs: set[int] = set()
    for q in roh or ():
        if q == 0:
            qs.update({1, 2, 3, 4})
        elif q in (1, 2, 3, 4):
            qs.add(q)
    return sorted(qs)


def _versand_quartale(data: "VersandIn") -> list[int]:
    """Die Quartale, die ein Versand betrifft — als Marker-Granularität (N182).

    Die abgewählten Monate (`aus`) bleiben unberücksichtigt: der Marker merkt
    sich das Quartal, nicht den einzelnen Monat."""
    return _expand_quartale(data.quartale or [data.quartal])


def abgerechnet_marker(session: Session, slug: str,
                       jahr: int = 0) -> list[dict]:
    """Die abgerechnet-Marker eines Objekts: welche (jahr, quartal, nutzer) sind
    als abgerechnet/verschickt festgehalten (N182).

    Grundlage ist derselbe Schlüssel wie beim Autoversand
    (``tankstelle_versendet:<slug>:<jahr>:Q<quartal>:<nutzer_id>``) — automatisch
    und von Hand gesetzte Marker stehen damit im selben Namensraum. Mit `jahr`
    lässt sich auf ein Jahr einschränken.

    Seit N187 gibt es zusätzlich monatsgenaue Marker mit ``M<monat>`` statt
    ``Q<quartal>``. Jeder Eintrag trägt beide Felder: `quartal` (bei einem
    Monatsmarker das Quartal, in dem der Monat liegt) und `monat` (``None`` bei
    einem Quartalsmarker) — so kann die Oberfläche Monate weiterhin zu ihrem
    Quartal zusammenrollen."""
    prefix = f"{S_VERSENDET}:{slug}:"
    ergebnis: list[dict] = []
    for e in session.exec(select(Einstellung).where(
            Einstellung.schluessel.like(prefix + "%"))).all():
        if not e.wert:                       # geleerter Marker zählt nicht
            continue
        teile = e.schluessel[len(prefix):].split(":")
        if len(teile) != 3:
            continue
        jahr_roh, periode, nid_roh = teile
        try:
            j = int(jahr_roh)
            nid = int(nid_roh)
        except ValueError:
            continue
        if jahr and j != jahr:
            continue
        if periode.startswith("M"):          # Monatsmarker (N187)
            try:
                m = int(periode[1:])
            except ValueError:
                continue
            if not 1 <= m <= 12:
                continue
            q, monat = (m - 1) // 3 + 1, m
        else:                                # Quartalsmarker (wie bisher)
            try:
                q = int(periode.lstrip("Q"))
            except ValueError:
                continue
            monat = None
        ergebnis.append({"jahr": j, "quartal": q, "monat": monat,
                         "nutzer_id": nid, "am": e.wert})
    return sorted(ergebnis, key=lambda m: (m["jahr"], m["quartal"],
                                           m["monat"] or 0, m["nutzer_id"]))


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


def buchungen(session: Session, objekt_id: int, von: date, bis: date,
              nutzer: list[dict] | None = None,
              regeln: list[dict] | None = None,
              ausschluss: set[int] | None = None,
              aktive_monate: set[int] | None = None) -> list[Buchung]:
    """Die erfassten Ladungen als Abrechnungszeilen.

    `Tankladung.preis` wird bewusst **nicht** übernommen (N148): der Satz ist
    abgeleitet und für alle Ladungen des Zeitraums derselbe.

    Ohne Zeitraum-Regeln bleibt es bei der Zuordnung über den Namen (der alte
    Weg). Mit Regeln greift die Mehrnutzer-Zuordnung über den Zeitraum
    (N165/2): jede Ladung geht an den Nutzer, dessen Zeitraum ihren Tag enthält;
    ausgeschlossene Ladungen fallen heraus.

    `aktive_monate` grenzt zusätzlich auf einzelne Monate der Spanne ein (N169):
    ein aus dem Quartal abgewählter Monat fällt aus Menge und Betrag heraus.
    Ladungen ohne Datum bleiben, weil sie keinem Monat zugeordnet werden
    können."""
    namen = {e.id: e.name for e in session.exec(select(Eigentuemer)).all()}
    rohe = [RohLadung(id=l.id, tag=l.datum, name=_person(l, namen),
                      email=l.email or "", kwh=l.kwh or 0.0)
            for l in erfasste_ladungen(session, objekt_id, von, bis)
            if aktive_monate is None or l.datum is None
            or l.datum.month in aktive_monate]
    return zuordnen(rohe, nutzer or [], regeln or [], ausschluss or set())


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
    # N173 — der Fahrer zahlt den GEEICHTEN Netzsatz (Betrag ÷ geeichte
    # Rechnungsmenge), nicht den Verteilungssatz der Mieter (Betrag ÷
    # SolarEdge-Menge). Fehlt die geeichte Menge, hat die Kette bereits auf den
    # Verteilungssatz zurückgestellt — dann ist `netz_preis_geeicht` == diesem.
    netz_preis = schritt1.get("netz_preis_geeicht")
    geeichte_menge = schritt1.get("geeichte_menge") or 0.0
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
    if netz_preis is None:
        # Weder die geeichte Rechnungsmenge noch die SolarEdge-Menge ist da —
        # ohne Nenner kein Durchschnittspreis.
        # Die Quellenangabe bringt selbst schon Klammern mit (Belegname) —
        # noch ein Klammerpaar drumherum liest sich wie ein Tippfehler.
        return Satz(grund=(
            f"Für den Zeitraum {label} steht der Betrag — "
            f"{quelle or f'{deutsch(betrag)} €'} —, aber nicht die bezogene "
            "Menge: ohne die kWh des Netzbezugs gibt es keinen "
            "Durchschnittspreis. Die Menge ergibt sich aus dem "
            "Gesamtverbrauch und den SolarEdge-Anteilen am Strom-Jahr."))

    # Die Menge, die den Satz trägt: die geeichte Rechnungsmenge, sonst
    # (Rückfall) die SolarEdge-Netzmenge — dieselbe, auf die die Kette dann auch
    # zurückgestellt hat.
    satz_menge = geeichte_menge if geeichte_menge > 0 else menge
    geeicht_hinweis = ("geeichte Rechnungsmenge" if geeichte_menge > 0
                       else "SolarEdge-Menge, geeichte Menge fehlt")
    eigen_preis = eigen_satz(netz_preis)
    return Satz(
        netz=netz_preis, eigen=eigen_preis,
        misch=mischsatz(netz_preis, eigen_preis, extern_kwh, eigen_kwh),
        herkunft=(f"{quelle or f'{deutsch(betrag)} € Netzbezug'} ÷ "
                  f"{deutsch(satz_menge)} kWh Netzbezug "
                  f"({geeicht_hinweis}, {label})"))


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


def _stations_verbrauch(nutzer: list[dict]) -> float | None:
    """Der mittlere Verbrauch (kWh/100km) über alle Nutzer der Station, die
    einen Wert gepflegt haben (N188).

    Für die Reichweite eines Monats braucht es einen typischen Verbrauch der
    Station — der Durchschnitt der Nutzer mit einem Wert > 0. Hat niemand einen
    Verbrauch hinterlegt, kommt ``None`` zurück: dann bleibt die Reichweite
    leer, statt sie aus dem Nichts zu erfinden."""
    werte = [n.get("verbrauch_kwh_100km") or 0.0 for n in nutzer]
    werte = [w for w in werte if w > 0]
    return sum(werte) / len(werte) if werte else None


def _verlauf_kosten_km(session: Session, o: Objekt, zeilen: list[dict],
                       summe: dict) -> tuple[list[dict], dict]:
    """Je Monatszeile (und in der Summe) die Ladekosten (€) und die Reichweite
    (km) ergänzen — beide additiv (N188).

    `kosten` = Netz-kWh × Netzsatz + Eigen-kWh × Eigensatz. Der Satz stammt aus
    der Abrechnungsperiode, in der der Monat liegt (`satz_ableiten`, N148), und
    wird je Monatsspanne gemerkt — Monate derselben Periode rechnen ihn nicht
    doppelt. Fehlt der Netzsatz (kein ableitbarer Satz) oder ist die Aufteilung
    des Monats unbekannt, bleibt `kosten` leer: **keine 0,00 € als Notnagel.**

    `km` sagt, wie weit die geladenen kWh ein typisches Fahrzeug der Station
    tragen. Ohne einen einzigen gepflegten Verbrauch bleibt sie leer. Der
    Stationsverbrauch wird einmal je Abfrage bestimmt.

    Die Summe addiert nur die belegten Monate; sie ist nur dann leer, wenn
    **jeder** Monat leer ist."""
    verbrauch = _stations_verbrauch(nutzer_lesen(session, o))
    cache: dict[tuple[date, date], Satz] = {}

    def _satz(von: date, bis: date) -> Satz:
        if (von, bis) not in cache:
            cache[(von, bis)] = satz_ableiten(session, o.id, von, bis)
        return cache[(von, bis)]

    def _monatskosten(z: dict) -> float | None:
        extern, eigen = z.get("extern_kwh"), z.get("eigen_kwh")
        if extern is None or eigen is None:
            return None
        von = date(z["jahr"], z["monat"], 1)
        bis = date(z["jahr"], z["monat"], monthrange(z["jahr"], z["monat"])[1])
        satz = _satz(von, bis)
        if satz.netz is None or satz.grund:
            return None
        return round(extern * satz.netz + eigen * satz.eigen, 2)

    def _monatskm(z: dict) -> int | None:
        if verbrauch is None:
            return None
        km = eauto.gefahrene_km(z["kwh"], verbrauch)
        return None if km is None else round(km)

    for z in zeilen:
        z["kosten"] = _monatskosten(z)
        z["km"] = _monatskm(z)

    kosten = [z["kosten"] for z in zeilen if z["kosten"] is not None]
    km = [z["km"] for z in zeilen if z["km"] is not None]
    summe["kosten"] = round(sum(kosten), 2) if kosten else None
    summe["km"] = round(sum(km)) if km else None
    return zeilen, summe


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


def _abrechnung(session: Session, o: Objekt, slug: str, jahr: int,
                quartal: int, quartale: list[int] | None = None,
                aus: set[int] | None = None) -> dict:
    """Die Abrechnung eines Zeitraums — von Vorschau, Liste und Versand
    gemeinsam benutzt, damit alle drei dasselbe sagen.

    Abgerechnet wird ausschliesslich, was einer Person zugeordnet ist: die
    Wallbox weiss, wie viel geladen wurde, aber nicht von wem. Damit eine
    Abrechnung über 0 € nicht rätselhaft bleibt, steht daneben, wie viel im
    Zeitraum überhaupt geladen wurde (`geladen_kwh`) — die Lücke zwischen
    beiden Zahlen ist die Antwort auf „wieso passiert da nichts" (N143).

    Der Satz kommt aus der Stromkette (N148); die Mengen des Zeitraums sagen,
    wie stark Netz und eigener Strom darin gewichtet sind.

    `quartale` (mehrere zusammen) und `aus` (einzeln abgewählte Monate) sind der
    Quartals-Feinschliff aus N169. Ohne sie bleibt es beim einzelnen `quartal`
    — der bisherige Weg (auch der Autoversand ruft so)."""
    quartale = list(quartale) if quartale is not None else [quartal]
    aus = set(aus or ())
    try:
        monate = aktive_monate(quartale, aus)
    except ValueError as fehler:
        raise HTTPException(400, str(fehler)) from fehler
    if not monate:
        raise HTTPException(400, "Für die Abrechnung ist kein Monat ausgewählt "
                                 "— mindestens ein Monat muss bleiben.")
    aktiv = set(monate)
    von = date(jahr, monate[0], 1)
    bis = date(jahr, monate[-1], monthrange(jahr, monate[-1])[1])
    label = abrechnungs_label(jahr, quartale, aus)
    liste = nutzer_lesen(session, o)
    posten_roh, quelle, _ = _posten_holen(session, o, von, bis)
    # Ein aus dem Quartal abgewählter Monat fällt aus Menge und Betrag heraus
    # (N169) — nicht nur aus der Anzeige. Darum hier an der Quelle filtern.
    posten = [p for p in posten_roh
              if p.tag is None or p.tag.month in aktiv]
    zeilen_verlauf = [z for z in verlauf(posten, von, bis) if z["monat"] in aktiv]
    summe = verlauf_summe(zeilen_verlauf) if posten else {}
    satz = satz_ableiten(session, o.id, von, bis,
                         summe.get("extern_kwh"), summe.get("eigen_kwh"))
    # N165 — mit genau einem Nutzer gehören ihm automatisch alle Ladungen des
    # Zeitraums (aus den geladenen Mengen, nicht nur aus den namentlich
    # erfassten Sätzen). Bei mehreren bleibt es bei der Zuordnung über den Namen.
    auto_buch, automatisch = posten_als_buchungen(posten, liste)
    if automatisch:
        quelle_buch = auto_buch
    else:
        # Mehrere Nutzer: Zuordnung über den Zeitraum, wenn Regeln hinterlegt
        # sind; sonst wie bisher über den Namen. Ausgeschlossene Ladungen fallen
        # in beiden Fällen heraus (N165/2), abgewählte Monate ebenso (N169).
        regeln, ausschluss = zuordnung_lesen(session, o.slug, liste)
        quelle_buch = buchungen(session, o.id, von, bis, liste, regeln,
                                ausschluss, aktiv)
    zeilen = abrechne(quelle_buch, liste, satz.misch)
    if automatisch:
        for z in zeilen:
            z["automatisch"] = z["kwh"] > 0
    # N170 — je Nutzer aus geladenen kWh und seinem Verbrauch die gefahrenen km,
    # den Preis je 100 km und das energetische Benzin-Äquivalent. Ohne
    # hinterlegten Verbrauch bleiben die Größen None (keine erfundene Zahl).
    nach_id = {n["id"]: n for n in liste}
    for z in zeilen:
        n = nach_id.get(z.get("nutzer_id")) or {}
        modell = n.get("e_auto_modell", "")
        verbrauch = n.get("verbrauch_kwh_100km", 0.0)
        kz = eauto.kennzahlen(z["kwh"], z["betrag"], verbrauch or None)
        z["e_auto_modell"] = modell
        z["verbrauch_kwh_100km"] = verbrauch or 0.0
        z["km"], z["preis_100km"], z["liter_100km"] = (
            kz["km"], kz["preis_100km"], kz["liter_100km"])
        # N184b — die Empfänger-Anschrift, damit die Inline-Vorschau sie unter
        # dem Namen zeigen kann (wie das PDF). Eine noch nicht angelegte Person
        # (nutzer_id None) hat keine.
        z["strasse"] = n.get("strasse", "")
        z["plz"] = n.get("plz", "")
        z["ort"] = n.get("ort", "")
        # N184b — der Benzin-Kostenvergleich je Nutzer, exakt wie ihn das PDF
        # baut (`_pdf_und_name`): realer Verbrauch eines vergleichbaren Benziners
        # aus der KI (gecacht über `_benzin_verbrauch`) gegen den echten
        # E-Auto-Preis je 100 km. Ohne Verbrauch oder ohne belastbaren
        # Benzinwert bleibt er None — kein Vergleich, keine erfundene Zahl.
        z["benzin"] = (eauto.benzin_vergleich(
            _benzin_verbrauch(session, modell), kz["preis_100km"], kz["km"])
            if verbrauch and verbrauch > 0 else None)
    # N184b — die Objekt-Bankverbindung (der Betreiber, an den überwiesen wird);
    # None, wenn ungepflegt. Dieselbe Quelle wie das PDF (`_pdf_und_name`).
    konto = {"kontoinhaber": o.kontoinhaber or "", "iban": o.iban or "",
             "bank": o.bank or ""}
    zugeordnet = round(sum(z["kwh"] for z in zeilen), 3)
    return {"objekt": o.name, "jahr": jahr, "quartal": quartal,
            "quartale": sorted(set(quartale)), "aus_monate": sorted(aus),
            "monate_aktiv": monate,
            "label": label,
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
            "eigen_prozent": summe.get("eigen_prozent"),
            # N170 — die Annahme des Benzin-Äquivalents, sichtbar mitgeführt.
            "benzin_kwh_pro_liter": eauto.BENZIN_KWH_PRO_LITER,
            # N184b — die Objekt-Bankverbindung für den Konto-Block der
            # Inline-Vorschau; None, wenn keine der drei Angaben gepflegt ist.
            "konto": (konto if any(konto.values()) else None)}


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


def _quartal_verlauf(session: Session, o: Objekt, von: date, bis: date,
                     aktiv: set[int] | None = None) -> tuple[list[dict], dict]:
    """Die Monatszeilen des Quartals plus ihre Summe — die Grundlage von
    Diagramm und Tabelle im PDF.

    `aktiv` grenzt auf die nicht abgewählten Monate ein (N169), damit ein
    ausgeschlossener Monat auch aus Diagramm, Tabelle und Summe des PDF
    verschwindet — nicht nur aus dem Rechnungsbetrag."""
    posten, _, _ = _posten_holen(session, o, von, bis)
    if aktiv is not None:
        posten = [p for p in posten if p.tag is None or p.tag.month in aktiv]
    monate = [z for z in verlauf(posten, von, bis)
              if aktiv is None or z["monat"] in aktiv]
    return monate, verlauf_summe(monate)


def _mailtext(o: Objekt, daten: dict, zeile: dict) -> tuple[str, str]:
    """Betreff und Text der Abrechnungsmail — von Vorschau, Versand und
    Autoversand gemeinsam benutzt, damit alle drei dasselbe sagen."""
    von = date.fromisoformat(daten["von"])
    bis = date.fromisoformat(daten["bis"])
    betreff = f"E-Tankstelle {o.name} — Abrechnung {daten['label']}"
    text = abrechnungstext(o.name, zeile, von, bis, daten["label"],
                           daten["eigen_prozent"], daten["satz_herkunft"])
    return betreff, text


def _benzin_verbrauch(session: Session, modell: str) -> float | None:
    """N177 — der Verbrauch eines vergleichbaren Benziners (l/100km) zum
    E-Auto-Modell, für den Kostenvergleich im PDF.

    Erst im Cache nachsehen (je Modell einer), sonst die KI fragen und einen
    plausiblen Wert merken. Scheitert die Ermittlung, gibt es **keinen**
    Vergleich (``None``) statt einer erfundenen Zahl — der einzige Netz-Aufruf
    liegt in :func:`eauto.verbrauch_benzin_ermitteln` und wirft nie."""
    name = " ".join((modell or "").split())
    if not name:
        return None
    key = f"{S_BENZIN}:{name.casefold()}"
    roh = _lies(session, key)
    if roh:
        try:
            return float(roh)
        except ValueError:
            pass
    verbrauch, _hinweis = eauto.verbrauch_benzin_ermitteln(
        name, schluessel=ki_key(session), ki_modell=ki_modell(session))
    if verbrauch is not None:
        _setze(session, key, str(verbrauch))
        session.commit()
    return verbrauch


def _pdf_und_name(session: Session, o: Objekt, daten: dict,
                  zeile: dict) -> tuple[bytes, str]:
    """Das Quartals-PDF eines Nutzers und sein Dateiname — die eine Stelle, die
    das PDF baut. Ansehen (`abrechnung.pdf`) und Versand-Anhang teilen sie sich.

    Setzt einen ermittelten Satz und einen Betrag voraus; die Aufrufer prüfen
    das vorher (kein PDF über 0 €)."""
    von = date.fromisoformat(daten["von"])
    bis = date.fromisoformat(daten["bis"])
    monate, summe = _quartal_verlauf(session, o, von, bis,
                                     set(daten.get("monate_aktiv") or []) or None)
    satz = {"netz": daten["satz_netz"], "eigen": daten["satz_eigen"],
            "misch": daten["satz"], "herkunft": daten["satz_herkunft"],
            "grund": daten["satz_grund"], "rabatt": daten["satz_rabatt"]}
    # N170 — hat der Nutzer ein E-Auto mit Verbrauch, trägt das PDF km und
    # Preis/100 km statt der Netz/PV/Akku-Spalten; ohne bleibt es beim Alten.
    verbrauch = zeile.get("verbrauch_kwh_100km") or 0.0
    ea = None
    if verbrauch > 0:
        modell = zeile.get("e_auto_modell", "")
        ea = {"modell": modell, "verbrauch": verbrauch, "satz": daten["satz"]}
        # N177 — der Kosten-Benzinvergleich: realer Verbrauch eines
        # vergleichbaren Benziners (KI) gegen den echten E-Auto-Preis je 100 km.
        # Ohne belastbaren Benzinwert entfällt der Vergleich (None).
        ea["benzin"] = eauto.benzin_vergleich(
            _benzin_verbrauch(session, modell),
            zeile.get("preis_100km"), zeile.get("km"))
    konto = {"bank": o.bank, "iban": o.iban, "kontoinhaber": o.kontoinhaber}
    inhalt = tankabrechnung_pdf(o.name, _empfaenger(session, zeile),
                                daten["label"], von, bis, monate, summe, satz,
                                zeile["kwh"], zeile["betrag"], eauto=ea,
                                konto=konto)
    return inhalt, tank_pdf_dateiname(o.name, daten["label"], zeile["name"])


def _sende_abrechnung(session: Session, o: Objekt, daten: dict, zeile: dict,
                      adresse: str) -> None:
    """Eine Abrechnung als Mail **mit dem Quartals-PDF im Anhang** verschicken.

    Der Mailtext bleibt kurz (N165 Teil 1); die Zahlen trägt das PDF. Der Anhang
    läuft über denselben Weg wie sonst in ImmoCalc (`Zugang.sende` mit
    ``anhang=(name, inhalt, subtyp)``)."""
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
    # N182 — den Versand festhalten, damit die Periode als abgerechnet erscheint
    # (Haken) und ein zweiter Versand gesperrt ist.
    if data.nutzer_id:
        for q in quartale_sel:
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
    heute = heute or date.today()
    fq = faelliges_quartal(heute)
    if fq is None:
        return {"faellig": False, "geprueft": 0, "versendet": 0}
    jahr, quartal = fq
    geprueft = versendet = 0
    for o in session.exec(select(Objekt)).all():
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
