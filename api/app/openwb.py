"""N130 — das Ladeprotokoll der openWB-Wallbox lesen: die reine Logik.

Die Wallbox stellt ihr Ladeprotokoll als CSV bereit
(``…/openWB/web/settings/downloadChargeLog.php?year=2025``). Das Format ist
deutsch: Trennzeichen **Semikolon**, Werte in Anführungszeichen, Dezimal**komma**.

Je Ladung stehen die Energiemenge (``Energie``, kWh), die Kosten und vier
Anteile in Prozent, die zusammen 100 ergeben:

* ``Energieanteil Netz`` — zugekaufter Strom,
* ``Energieanteil PV`` und ``Energieanteil Speicher`` — eigener Strom (ob
  direkt vom Dach oder aus dem Akku, ändert am Preis nichts),
* ``Energieanteil Ladepunkte`` — bisher immer 0. Er wird **getrennt geführt**
  und gemeldet, wenn er einmal nicht 0 ist: eine stille Fehlzuordnung wäre
  schlimmer als ein sichtbarer Hinweis.

Gerechnet wird nach **Datum**, nicht nach der Jahres-URL: die Nebenkosten­
periode läuft z. B. vom 01.10.2024 bis 30.09.2025. :func:`jahre` sagt, welche
Jahresdateien dafür zu holen sind, :func:`summiere` filtert die Zeilen selbst.

Dieses Modul geht **nie ins Netz** — es bekommt den CSV-Text gereicht. Der
Abruf und die Endpunkte leben in ``routers/openwb.py``. Alles, was schiefgehen
kann (leere Antwort, HTML statt CSV, umbenannte Spalte, kaputte Zahl), führt
hier zu einer verständlichen Meldung — nie zu einer stillen Null.
"""
from __future__ import annotations

import csv
import io
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime

log = logging.getLogger("immocalc")

# Ein Rechnername oder eine IP, wahlweise mit Port — mehr darf in der
# Basisadresse nicht stehen.
_HOST = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?(?::\d{1,5})?")

# Pfad des Ladeprotokolls auf der Box — Teil der openWB-Oberfläche.
PFAD = "/openWB/web/settings/downloadChargeLog.php"

# Spaltennamen, wie openWB sie schreibt. Ändert die Box sie, sagt die
# Fehlermeldung genau, welche fehlt und was stattdessen dastand.
S_BEGINN = "Beginn"
S_ENDE = "Ende"
S_STEMPEL_BEGINN = "Zeitstempel Beginn"
S_STEMPEL_ENDE = "Zeitstempel Ende"
S_KOSTEN = "Kosten"
S_ENERGIE = "Energie"
S_NETZ = "Energieanteil Netz"
S_LADEPUNKTE = "Energieanteil Ladepunkte"
S_SPEICHER = "Energieanteil Speicher"
S_PV = "Energieanteil PV"

# Ohne diese Spalten lässt sich nichts rechnen.
PFLICHT: tuple[str, ...] = (S_BEGINN, S_KOSTEN, S_ENERGIE, S_NETZ,
                            S_LADEPUNKTE, S_SPEICHER, S_PV)

# Die vier Anteile ergeben zusammen 100 %. openWB rundet auf zwei
# Nachkommastellen — eine halbe Prozentspanne ist reichlich Luft.
TOLERANZ = 0.5

# "03.09.2025, 18:14:02" — so schreibt openWB Beginn und Ende.
ZEITFORMAT = "%d.%m.%Y, %H:%M:%S"


class OpenwbFehler(RuntimeError):
    """Das Protokoll ist nicht lesbar. Die Meldung sagt dem Nutzer, warum —
    und dass er die Werte notfalls von Hand einträgt."""


# --------------------------------------------------------------------------
# Adresse der Box
# --------------------------------------------------------------------------

def normalisiere_basis(url: str) -> str:
    """Aus einer eingetippten Adresse die Basisadresse der Box.

    Nimmt „192.168.178.61", „192.168.178.61:80" oder eine aus dem Browser
    kopierte Adresse und macht daraus ``http://host[:port]``. Ohne Schema wird
    ``http`` angenommen — die Box spricht im Heimnetz kein TLS.

    Was kein Rechnername und keine IP sein kann, ergibt einen leeren String.
    Der Aufrufer lehnt dann ab, statt Unsinn an die HTTP-Bibliothek zu
    reichen (die dabei mit einer ganz anderen Ausnahme aussteigen würde)."""
    roh = (url or "").strip()
    if not roh:
        return ""
    if "://" not in roh:
        roh = "http://" + roh
    schema, _, rest = roh.partition("://")
    # Alles ab dem ersten Trenner ist Pfad der Oberfläche und gehört nicht in
    # die Basisadresse.
    host = rest.split("/")[0].strip()
    if schema.lower() not in ("http", "https") or not _HOST.fullmatch(host):
        return ""
    return f"{schema.lower()}://{host}"


def protokoll_url(basis: str, jahr: int, monat: int | None = None) -> str:
    """Die Adresse des Ladeprotokolls für ein Jahr (oder einen Monat darin)."""
    grund = normalisiere_basis(basis)
    if not grund:
        raise OpenwbFehler("Für die Wallbox ist noch keine Adresse hinterlegt.")
    adresse = f"{grund}{PFAD}?year={jahr}"
    return f"{adresse}&month={monat:02d}" if monat else adresse


def jahre(von: date, bis: date) -> list[int]:
    """Die Jahresdateien, die ein Abrechnungszeitraum berührt.

    Der Zeitraum 01.10.2024–30.09.2025 braucht beide Jahre — gefiltert wird
    danach über das Datum, nicht über die Datei."""
    if bis < von:
        raise OpenwbFehler("Das Ende des Zeitraums liegt vor seinem Beginn.")
    return list(range(von.year, bis.year + 1))


# --------------------------------------------------------------------------
# Zahlen und Zeiten aus dem CSV
# --------------------------------------------------------------------------

def zahl(roh: str) -> float | None:
    """Eine deutsche Dezimalzahl („4,21", „1.024,82") — ``None``, wenn der
    Wert unbrauchbar ist.

    Nie 0 als Notnagel: eine 0 sähe aus wie eine Messung. Der Aufrufer meldet
    die Zeile stattdessen als fehlerhaft."""
    text = (roh or "").strip().strip('"').replace(" ", "").replace(" ", "")
    if not text:
        return None
    if "," in text:                       # Punkt ist dann Tausendertrenner
        text = text.replace(".", "").replace(",", ".")
    try:
        wert = float(text)
    except ValueError:
        return None
    return None if wert != wert or wert in (float("inf"), float("-inf")) else wert


def zeitpunkt(text: str, stempel: str = "") -> datetime | None:
    """Beginn bzw. Ende einer Ladung — aus dem Klartext, sonst aus dem
    Unix-Zeitstempel.

    Zwei Quellen für dieselbe Angabe: schreibt openWB das Datum einmal anders,
    trägt der Zeitstempel die Auswertung weiter."""
    roh = (text or "").strip().strip('"')
    if roh:
        try:
            return datetime.strptime(roh, ZEITFORMAT)
        except ValueError:
            log.debug("openWB: unbekanntes Zeitformat %r", roh)
    sekunden = zahl(stempel)
    if sekunden is None or sekunden <= 0:
        return None
    try:
        return datetime.fromtimestamp(sekunden)
    except (OverflowError, OSError, ValueError):
        return None


# --------------------------------------------------------------------------
# Eine Ladung
# --------------------------------------------------------------------------

@dataclass
class Ladung:
    """Eine abgeschlossene Ladung — Mengen bereits in kWh aufgeteilt.

    Die Anteile sind aus den Prozentwerten des Protokolls gerechnet, damit die
    Abrechnung nur noch summieren muss."""
    beginn: datetime
    ende: datetime | None
    kwh: float
    kosten: float
    extern_kwh: float          # „Energieanteil Netz" — zugekauft
    speicher_kwh: float        # eigener Strom aus dem Akku
    pv_kwh: float              # eigener Strom direkt vom Dach
    ladepunkte_kwh: float      # getrennt geführt, siehe Modulkopf

    @property
    def tag(self) -> date:
        """Der Tag, an dem die Ladung begann — danach wird gefiltert."""
        return self.beginn.date()

    @property
    def eigen_kwh(self) -> float:
        """Eigener Strom: Speicher und PV zusammen."""
        return self.speicher_kwh + self.pv_kwh

    @property
    def nicht_zugeordnet_kwh(self) -> float:
        """Was keiner der vier Anteile trägt — bei gesunden Daten 0."""
        return (self.kwh - self.extern_kwh - self.speicher_kwh
                - self.pv_kwh - self.ladepunkte_kwh)


@dataclass
class Protokoll:
    """Das gelesene Ladeprotokoll: die brauchbaren Zeilen und was auffiel."""
    ladungen: list[Ladung] = field(default_factory=list)
    warnungen: list[str] = field(default_factory=list)


def _kopf_pruefen(spalten: list[str] | None) -> None:
    """Sind alle gebrauchten Spalten da? Sonst: sagen, welche fehlt."""
    vorhanden = [(s or "").strip() for s in (spalten or [])]
    fehlend = [s for s in PFLICHT if s not in vorhanden]
    if not fehlend:
        return
    raise OpenwbFehler(
        "Das Ladeprotokoll hat nicht die erwarteten Spalten — es fehlen: "
        + ", ".join(f"„{s}“" for s in fehlend)
        + ". Gefunden wurden: " + (", ".join(vorhanden) or "(keine)")
        + ". Vermutlich hat openWB die Spalten umbenannt.")


def _vorpruefung(text: str) -> str:
    """Ist das überhaupt ein CSV? Leere und HTML-Antworten früh abfangen."""
    roh = (text or "").lstrip("﻿").strip()
    if not roh:
        raise OpenwbFehler("Die Wallbox hat ein leeres Ladeprotokoll geliefert.")
    if roh[0] == "<" or roh[:200].lower().lstrip().startswith("<!doctype"):
        raise OpenwbFehler(
            "Die Wallbox hat eine HTML-Seite statt des Ladeprotokolls geliefert "
            "— meist ist dann die Adresse falsch oder die Anmeldung fehlt.")
    return roh


def lies(text: str) -> Protokoll:
    """CSV-Text → geprüfte Ladungen.

    Zeilen, die sich nicht rechnen lassen (kaputte Zahl, unlesbares Datum),
    werden **übersprungen und gemeldet** — nicht mit Nullen gefüllt. Fehlt eine
    ganze Spalte, ist das ein :class:`OpenwbFehler`: dann stimmt das Format
    nicht mehr und alles Weitere wäre geraten."""
    roh = _vorpruefung(text)
    leser = csv.DictReader(io.StringIO(roh), delimiter=";")
    _kopf_pruefen(leser.fieldnames)

    ergebnis = Protokoll()
    for nummer, zeile in enumerate(leser, start=2):   # Zeile 1 ist der Kopf
        eintrag = _zeile_lesen(nummer, zeile, ergebnis.warnungen)
        if eintrag:
            ergebnis.ladungen.append(eintrag)
    ergebnis.ladungen.sort(key=lambda l: l.beginn)
    return ergebnis


def _zeile_lesen(nummer: int, zeile: dict, warnungen: list[str]) -> Ladung | None:
    """Eine Protokollzeile — ``None``, wenn sie nicht zu gebrauchen ist."""
    beginn = zeitpunkt(zeile.get(S_BEGINN, ""), zeile.get(S_STEMPEL_BEGINN, ""))
    if beginn is None:
        warnungen.append(f"Zeile {nummer}: kein lesbarer Beginn "
                         f"(„{(zeile.get(S_BEGINN) or '').strip()}“) — "
                         "die Ladung wurde übergangen.")
        return None

    werte: dict[str, float] = {}
    for spalte in (S_ENERGIE, S_KOSTEN, S_NETZ, S_LADEPUNKTE, S_SPEICHER, S_PV):
        wert = zahl(zeile.get(spalte, ""))
        if wert is None:
            warnungen.append(
                f"Zeile {nummer} ({beginn:%d.%m.%Y}): „{spalte}“ ist keine Zahl "
                f"(„{(zeile.get(spalte) or '').strip()}“) — die Ladung wurde "
                "übergangen.")
            return None
        werte[spalte] = wert

    kwh = werte[S_ENERGIE]
    if kwh < 0:
        warnungen.append(f"Zeile {nummer} ({beginn:%d.%m.%Y}): negative "
                         "Energiemenge — die Ladung wurde übergangen.")
        return None

    summe = werte[S_NETZ] + werte[S_LADEPUNKTE] + werte[S_SPEICHER] + werte[S_PV]
    if kwh > 0 and abs(summe - 100.0) > TOLERANZ:
        warnungen.append(
            f"Ladung am {beginn:%d.%m.%Y}: die Energieanteile ergeben "
            f"{summe:.1f} % statt 100 % — bitte in der openWB nachsehen.")

    return Ladung(
        beginn=beginn,
        ende=zeitpunkt(zeile.get(S_ENDE, ""), zeile.get(S_STEMPEL_ENDE, "")),
        kwh=kwh, kosten=werte[S_KOSTEN],
        extern_kwh=kwh * werte[S_NETZ] / 100.0,
        speicher_kwh=kwh * werte[S_SPEICHER] / 100.0,
        pv_kwh=kwh * werte[S_PV] / 100.0,
        ladepunkte_kwh=kwh * werte[S_LADEPUNKTE] / 100.0)


def zusammenfuehren(*teile: list[Ladung]) -> list[Ladung]:
    """Mehrere Jahresdateien zu einer Liste — doppelte Ladungen fliegen raus.

    Überschneiden sich zwei Dateien (eine Ladung über den Jahreswechsel steht
    in beiden), zählt sie sonst doppelt. Erkannt wird sie am Beginn samt
    Energiemenge."""
    gesehen: set[tuple[datetime, float]] = set()
    zusammen: list[Ladung] = []
    for teil in teile:
        for ladung in teil:
            schluessel = (ladung.beginn, round(ladung.kwh, 3))
            if schluessel in gesehen:
                continue
            gesehen.add(schluessel)
            zusammen.append(ladung)
    zusammen.sort(key=lambda l: l.beginn)
    return zusammen


# --------------------------------------------------------------------------
# Summen über einen Abrechnungszeitraum
# --------------------------------------------------------------------------

def _anteil(teil: float, ganz: float) -> float | None:
    """Prozentanteil — ``None``, wenn es nichts zu teilen gibt."""
    return round(teil / ganz * 100.0, 1) if ganz > 0 else None


@dataclass
class Summe:
    """Was im Zeitraum geladen wurde — die Zahlen für die Abrechnung.

    `anzahl` zählt die Ladungen, bei denen wirklich Strom geflossen ist.
    Angesteckt-und-nichts-passiert steht getrennt in `ohne_energie`, damit die
    Zahl der Ladungen nicht von Fehlversuchen aufgebläht wird."""
    von: date
    bis: date
    anzahl: int
    ohne_energie: int
    kwh: float
    kosten: float
    extern_kwh: float
    speicher_kwh: float
    pv_kwh: float
    eigen_kwh: float
    ladepunkte_kwh: float
    nicht_zugeordnet_kwh: float
    warnungen: list[str] = field(default_factory=list)

    def als_dict(self) -> dict:
        """Die flache Form für die API."""
        return {
            "von": self.von.isoformat(), "bis": self.bis.isoformat(),
            "anzahl": self.anzahl, "ohne_energie": self.ohne_energie,
            "kwh": self.kwh, "kosten": self.kosten,
            "extern_kwh": self.extern_kwh,
            "speicher_kwh": self.speicher_kwh, "pv_kwh": self.pv_kwh,
            "eigen_kwh": self.eigen_kwh,
            "ladepunkte_kwh": self.ladepunkte_kwh,
            "nicht_zugeordnet_kwh": self.nicht_zugeordnet_kwh,
            "extern_prozent": _anteil(self.extern_kwh, self.kwh),
            "eigen_prozent": _anteil(self.eigen_kwh, self.kwh),
            "speicher_prozent": _anteil(self.speicher_kwh, self.kwh),
            "pv_prozent": _anteil(self.pv_kwh, self.kwh),
            "warnungen": list(self.warnungen),
        }


def im_zeitraum(ladungen: list[Ladung], von: date, bis: date) -> list[Ladung]:
    """Die Ladungen, die im Zeitraum begonnen haben (beide Ränder zählen)."""
    if bis < von:
        raise OpenwbFehler("Das Ende des Zeitraums liegt vor seinem Beginn.")
    return [l for l in ladungen if von <= l.tag <= bis]


def summiere(ladungen: list[Ladung], von: date, bis: date,
             warnungen: list[str] | None = None) -> Summe:
    """Die Summen eines Abrechnungszeitraums.

    Gefiltert wird über das Datum des Ladebeginns — nicht über das Kalender­
    jahr der Datei, aus der die Zeile stammt. Ist ``Energieanteil Ladepunkte``
    einmal nicht 0, steht das als Warnung dabei: der Anteil wird **keinem** der
    beiden Töpfe zugeschlagen."""
    gewaehlt = im_zeitraum(ladungen, von, bis)
    hinweise = list(warnungen or [])

    extern = sum(l.extern_kwh for l in gewaehlt)
    speicher = sum(l.speicher_kwh for l in gewaehlt)
    pv = sum(l.pv_kwh for l in gewaehlt)
    ladepunkte = sum(l.ladepunkte_kwh for l in gewaehlt)
    offen = sum(l.nicht_zugeordnet_kwh for l in gewaehlt)

    if round(ladepunkte, 2) != 0.0:
        hinweise.append(
            f"„{S_LADEPUNKTE}“ ist mit {ladepunkte:.2f} kWh belegt. Dieser "
            "Anteil zählt weder als zugekaufter noch als eigener Strom — "
            "bitte entscheiden, wohin er gehört.")
    if abs(offen) > 0.5:
        hinweise.append(
            f"{offen:.2f} kWh lassen sich keinem Anteil zuordnen — die "
            "Prozentwerte im Ladeprotokoll ergeben nicht 100 %.")

    return Summe(
        von=von, bis=bis,
        anzahl=sum(1 for l in gewaehlt if l.kwh > 0),
        ohne_energie=sum(1 for l in gewaehlt if l.kwh <= 0),
        kwh=round(sum(l.kwh for l in gewaehlt), 2),
        kosten=round(sum(l.kosten for l in gewaehlt), 2),
        extern_kwh=round(extern, 2), speicher_kwh=round(speicher, 2),
        pv_kwh=round(pv, 2), eigen_kwh=round(speicher + pv, 2),
        ladepunkte_kwh=round(ladepunkte, 2),
        nicht_zugeordnet_kwh=round(offen, 2), warnungen=hinweise)
