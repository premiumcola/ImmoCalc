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
    Liste).

    Der Rückfall wird ebenso getrimmt wie die Liste. Ungetrimmt ergab ein
    `einheit_bezug` aus lauter Leerzeichen das Label `"   "` — und daraus die
    Warnung „„   " gehört zu keiner Einheit dieses Objekts", die niemand
    nachtragen kann, weil es nichts nachzutragen gibt."""
    liste = [t.strip() for t in (z.einheiten or "").split(",") if t.strip()]
    if liste:
        return liste
    einzeln = (z.einheit_bezug or "").strip()
    return [einzeln] if einzeln else []


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
    Reihenfolge bleibt erhalten, Dopplungen fallen weg (verglichen wird über
    `schluessel()`, also so, wie auch nachgeschlagen wird).

    Nicht in `unbekannt` steht, was hier BEWUSST übergangen wird: das Altlabel
    „WG" neben einer echten Einheit (siehe unten). Es zu melden hiesse, eine
    getroffene Entscheidung als offenen Fund auszugeben.

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
    gemeldet: set[str] = set()
    for name in namen:
        s = schluessel(name)
        treffer = karte_.get(s)
        if treffer:
            kandidaten = [treffer]
        elif s == ALT_WG and hat_echte:
            # Genau der Fall aus N111 oben: „WG" tritt hinter die echte Einheit
            # zurück und wird BEWUSST fallen gelassen. Ein bewusst Übergangenes
            # ist kein Fund — landete es in `unbekannt`, machte die Strom-Kette
            # daraus die Warnung „„WG" gehört zu keiner Einheit dieses Objekts
            # — die Zuordnung bitte am Zähler nachtragen." Sie ist sachlich
            # falsch (die Zuordnung IST nachgetragen) und nicht abstellbar:
            # ein Dauer-Warnbanner, das keinen Weg zum Beheben kennt.
            kandidaten = []
        elif s == ALT_WG and haupthaus:
            kandidaten = list(haupthaus)
        else:
            kandidaten = []
            # Verglichen wird über `schluessel()` — genau wie das Nachschlagen.
            # Exakt zu vergleichen ergäbe für „Keller" und „keller" zwei
            # Warnungen zu demselben Label, und ein Label aus lauter Leerraum
            # (leerer Schlüssel) ist gar keins.
            if s and s not in gemeldet:
                gemeldet.add(s)
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
    Dopplungen raus.

    Dopplung heißt hier dasselbe wie beim Nachschlagen: verglichen wird über
    `schluessel()`. „Keller" und „keller" sind ein Label und bekommen einen
    Hinweis, nicht zwei."""
    gesehen: set[str] = set()
    eindeutig: list[str] = []
    for name in namen:
        s = schluessel(name)
        if s and s not in gesehen:
            gesehen.add(s)
            eindeutig.append(name)
    return [warnung(n) for n in eindeutig]
