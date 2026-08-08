"""N288-B4 — die EINE Zuordnung „welches Ziel-Label gehört zu welcher Einheit".

Zähler tragen ihre Ziele als Freitext (`Zaehler.einheiten`, ersatzweise
`Zaehler.einheit_bezug`): mal die Bezeichnung einer Einheit, mal einen
Parteinamen, mal ein Altlabel wie „WG". Wer daraus Spalten einer Abrechnung
macht, muss diese Labels erst auf die echten Objekt-Einheiten abbilden.

Diese Abbildung lag in drei Fassungen im Code — und sie verhielten sich
unterschiedlich: die Wasser-Kette MELDETE ein Label, das zu keiner Einheit
passt; die Strom-Kette verschluckte es. Ein verschluckter Zähler heißt: ein
Verbrauch fehlt in der Abrechnung, ohne dass es jemand sieht. Deshalb gibt es
hier genau eine Fassung, und sie gibt das Unzugeordnete IMMER mit zurück
(:class:`Zuordnung`) — es lässt sich nicht mehr durch Weglassen eines
Parameters verschlucken. Ob der Aufrufer daraus einen Hinweis macht, bleibt
seine Sache; ihn nicht zu bekommen, kann er nicht mehr wählen.

Reine Abbildungslogik, keine DB — der Aufrufer sammelt Einheiten und Bezüge.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

from .models import Einheit, Zaehler
from .verteilung import Bezug

#: N101/6 — Altlabel der früheren Wohngemeinschaft. Es steht für keine Einheit
#: mehr, sondern für den gemeinsam genutzten Haupthaus-Teil.
ALT_WG = "wg"


def schluessel(name: str) -> str:
    """Vergleichsform eines Einheiten-/Partei-Labels: Leerraum vereinheitlicht,
    Groß-/Kleinschreibung egal. Nur zum Nachschlagen — ausgegeben wird immer die
    echte, unveränderte Bezeichnung der Einheit."""
    return " ".join((name or "").split()).casefold()


def parse_einheiten(z: Zaehler) -> list[str]:
    """Die Ziel-Labels eines Zählers als Liste.

    Aus dem komma-separierten Feld `einheiten` (getrimmt, Leere raus); ist es
    leer, fällt es auf den Einzelwert `einheit_bezug` zurück (leer → leere
    Liste)."""
    liste = [t.strip() for t in (z.einheiten or "").split(",") if t.strip()]
    if liste:
        return liste
    return [z.einheit_bezug] if z.einheit_bezug else []


def karte(einheiten: Sequence[Einheit],
          bezuege: Sequence[Bezug]) -> dict[str, str]:
    """Abbildung „Label → echte Einheiten-Bezeichnung".

    Zwei Quellen, in dieser Reihenfolge: die Bezeichnung einer Einheit zeigt auf
    sich selbst; ein Partei-Name zeigt auf die Einheit, in der diese Partei im
    Zeitraum wohnt (`verteilung.bezuege`). So landen Alt-Labels wie
    „Roman & Alicia" in der Spalte ihrer Einheit statt als eigene Spalte.
    """
    aus: dict[str, str] = {schluessel(e.bezeichnung): e.bezeichnung
                           for e in einheiten}
    aus.pop("", None)
    for b in bezuege:
        partei = schluessel(b.partei)
        ziel = aus.get(schluessel(b.einheit))
        if partei and ziel and partei not in aus:
            aus[partei] = ziel
    return aus


@dataclass(frozen=True)
class Zuordnung:
    """Was sich zuordnen ließ — und was nicht.

    `unbekannt` ist bewusst Teil des Ergebnisses und nicht ein optionaler
    Ausgabeparameter: ein Aufrufer kann es ignorieren, aber nicht mehr
    versehentlich gar nicht erst erzeugen."""
    ziele: list[str] = field(default_factory=list)
    unbekannt: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.ziele)


def zuordne(namen: Iterable[str], karte_: dict[str, str],
            haupthaus: Sequence[str] = ()) -> Zuordnung:
    """Normalisiert Ziel-Labels auf echte Objekt-Einheiten.

    Exakter Treffer → die Einheit selbst; Partei-Label → ihre Einheit; das
    überholte „WG" → die Haupthaus-Einheiten (die ohne eigenen Kaltwasser-
    Unterzähler). Alles andere erzeugt keine Spalte — eine Phantom-Spalte wäre
    schlimmer als eine fehlende Zuordnung — und steht in `unbekannt`.
    Reihenfolge bleibt erhalten, Dopplungen fallen weg.

    Hat das Objekt gar keine Einheiten hinterlegt, gibt es nichts zu
    normalisieren — dann bleiben die Namen unangetastet (sonst verlöre eine
    reine Partei-Abrechnung ihre Spalten und die Kontrollsumme).
    """
    namen = list(namen)
    if not karte_:
        return Zuordnung([n for i, n in enumerate(namen)
                          if n and n not in namen[:i]], [])
    # N111 — hat der Nutzer am Zähler eine ECHTE Einheit gewählt, gilt nur die.
    # Alte Sammel-Labels wie „WG" werden dann NICHT zusätzlich auf beide
    # Haupthaus-Wohnungen aufgelöst: der Zähler „Waschmaschine 1.OG" trug noch
    # `["WG", "Wohung EG"]` und landete dadurch zur Hälfte in der falschen
    # Wohnung (1,86 m³, obwohl der Zähler ihr gar nicht zugeordnet ist).
    hat_echte = any(karte_.get(schluessel(n)) for n in namen)
    ziele: list[str] = []
    unbekannt: list[str] = []
    for name in namen:
        s = schluessel(name)
        treffer = karte_.get(s)
        if treffer:
            kandidaten = [treffer]
        elif s == ALT_WG and haupthaus and not hat_echte:
            kandidaten = list(haupthaus)
        else:
            kandidaten = []
            if name and name not in unbekannt:
                unbekannt.append(name)
        for ziel in kandidaten:
            if ziel not in ziele:
                ziele.append(ziel)
    return Zuordnung(ziele, unbekannt)


def zuordne_zaehler(z: Zaehler, karte_: dict[str, str],
                    haupthaus: Sequence[str] = ()) -> Zuordnung:
    """Die Ziel-Einheiten eines Zählers — `parse_einheiten` + `zuordne`."""
    return zuordne(parse_einheiten(z), karte_, haupthaus)


def warnung(name: str) -> str:
    """Der EINE Hinweistext für ein Label, das zu keiner Einheit gehört.

    Er ist bedienbar formuliert (roter Faden 7): er sagt, wo es zu beheben
    ist."""
    return (f"„{name}“ gehört zu keiner Einheit dieses Objekts — die "
            "Zuordnung bitte am Zähler nachtragen.")


def warnungen(namen: Iterable[str]) -> list[str]:
    """Hinweise für mehrere unzugeordnete Labels, Reihenfolge erhalten,
    Dopplungen raus."""
    gesehen: list[str] = []
    for name in namen:
        if name and name not in gesehen:
            gesehen.append(name)
    return [warnung(n) for n in gesehen]
