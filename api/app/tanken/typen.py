"""Kleine Datentypen der E-Tankstelle.

Getrennt gehalten von den Fetcher-Funktionen, damit die Rechen-Module
(``perioden``, ``verlauf``, ``satz``) einen leichten Import haben — der
Wallbox-Anschluss (mit optionalem ``httpx``) wird nicht mitgezogen, nur weil
irgendwo eine Typ-Annotation ``list[Posten]`` steht.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


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
