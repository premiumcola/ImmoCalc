"""Einträge, deren Datei ausserhalb der App verschwunden ist (N242/N248).

Ein Beleg, dessen Datei der Nutzer direkt in der Nextcloud gelöscht hat, wird
**nicht** gelöscht: er behält KI-Auslese, Betrag und alle Verweise
(Kostenposition, Mietstand, Belegdaten) und legt nur seinen Pfad als Grabstein
(`entfernt:…`) beiseite. Damit gibt der Unique-Index den Namen wieder her, und
die Oberfläche führt ihn nicht länger als vorhandene Datei.

Hier wohnt die gesamte Mechanik dazu: den Pfad nachschlagen (`_eintraege_auf`),
einen Grabstein erkennen und aus Listen halten, ihn setzen und einen
nachweislich verwaisten Eintrag freigeben. Zwei Wege rufen das: das Ablegen
eines gleichnamigen Belegs (N242, `_verwaisten_eintrag_freigeben`) und der
Abgleich mit der Cloud (N248, `_abgleiche_objekt`).

Nur Datenbank, keine Cloud — der Aufrufer hat den Platz vorher live als frei
gemeldet bekommen.
"""
from __future__ import annotations

import logging

from sqlmodel import Session, select

from ..models import Dokument
from .darstellung import VERMISST

log = logging.getLogger("immocalc")


def _eintraege_auf(session: Session, pfad: str) -> list[Dokument]:
    """Welche Einträge zeigen auf diesen Pfad? (Mit und ohne führenden „/" —
    beide Schreibweisen kommen im Bestand vor.)

    Der Unique-Index verhindert ein Doppel später ohnehin — nur läge die Datei
    dann bereits am neuen Platz und die Datenbank am alten. Also vorher
    fragen."""
    ohne = pfad.strip("/")
    return list(session.exec(
        select(Dokument).where(Dokument.pfad.in_((f"/{ohne}", ohne)))).all())


# N242 — Vorsatz eines freigegebenen (extern gelöschten) Eintrags. Bewusst
# ohne führenden „/": alles, was „liegt in der Cloud" an diesem Zeichen
# erkennt, behandelt einen Grabstein dadurch von selbst richtig.
GRABSTEIN = "entfernt:"


def _ist_grabstein(pfad: str) -> bool:
    """Hat dieser Eintrag seinen Pfad nach N242 abgegeben?"""
    return (pfad or "").startswith(GRABSTEIN)


def _ohne_grabsteine(dokumente) -> list[Dokument]:
    """Nur Einträge, die noch eine Datei meinen — Grabsteine fliegen raus.

    N248/N253 — ein Grabstein (N242) ist kein Beleg mehr, sondern nur noch die
    Hülle eines gelöschten: er lebt allein deshalb weiter, damit Betrag,
    KI-Auslese und die Verweise aus Kostenposition/Mietstand nicht ins Leere
    zeigen. In einer Liste hat er nichts verloren — beim Nutzer sah es sonst
    aus wie ein Doppel, weil neben dem Grabstein der neue Beleg steht, der
    seinen freigewordenen Namen übernommen hat.

    Bewusst NICHT gefiltert wird der blosse Status `vermisst` mit echtem Pfad:
    der ist umkehrbar (die Datei kann zurückkommen) und wird im Eingang mit
    Abzeichen angezeigt, damit der Nutzer etwas tun kann."""
    return [d for d in dokumente if not _ist_grabstein(d.pfad)]


def _grabstein_setzen(session: Session, d: Dokument) -> None:
    """Legt den Pfad eines Eintrags als Grabstein beiseite (N242/N248).

    Der Eintrag wird **nicht** gelöscht — er behält KI-Auslese, Betrag und alle
    Verweise (Kostenposition, Mietstand, Belegdaten). Er gilt als `vermisst`,
    nur sein Pfad wandert nach `entfernt:…`, damit der Unique-Index den Namen
    wieder hergibt und die Oberfläche ihn nicht länger als vorhandene Datei
    führt. Der Vorsatz beginnt bewusst NICHT mit „/": jede Stelle, die „liegt
    in der Cloud" an genau diesem Zeichen erkennt (`darstellung._zeige`,
    Vorschau, Umbenennen), behandelt ihn dadurch von selbst richtig.

    Gemeinsame Mechanik zweier Wege: `_verwaisten_eintrag_freigeben` (N242,
    beim Ablegen eines gleichnamigen Belegs) und `_abgleiche_objekt` (N248,
    beim Abgleich mit der Cloud)."""
    grabstein = f"{GRABSTEIN}{d.pfad}"
    # Derselbe Pfad kann über die Jahre mehrfach verwaisen — jeder
    # Grabstein braucht seinen eigenen Platz im Unique-Index.
    n = 2
    while session.exec(select(Dokument)
                       .where(Dokument.pfad == grabstein)).first():
        grabstein = f"{GRABSTEIN}{d.pfad}#{n}"
        n += 1
    log.info("Eintrag freigegeben (Datei extern gelöscht): %s", d.pfad)
    d.pfad = grabstein
    d.status = VERMISST
    session.add(d)


def _verwaisten_eintrag_freigeben(session: Session, pfad: str) -> bool:
    """N242 — gibt den Namen einer ausserhalb der App gelöschten Datei frei.

    Wird nur gerufen, nachdem die Cloud diesen Pfad soeben live als **frei**
    gemeldet hat. Ein Eintrag, der trotzdem noch dorthin zeigt, ist damit
    nachweislich verwaist: der Nutzer hat die Datei direkt in der Nextcloud
    gelöscht. Bis N242 blockierte so ein Eintrag „seinen" Namen für immer und
    der nächste Beleg wich auf „…-2" aus, obwohl der Platz längst frei war.

    Gelöscht wird der Eintrag **nicht** — er behält KI-Auslese, Betrag und alle
    Verweise (Kostenposition, Mietstand, Belegdaten). Er gilt als `vermisst`
    und legt nur seinen Pfad als Grabstein (`entfernt:…`) beiseite, damit der
    Unique-Index den Namen wieder hergibt. Der Grabstein beginnt bewusst NICHT
    mit „/": jede Stelle, die „liegt in der Cloud" an genau diesem Zeichen
    erkennt (`darstellung._zeige`, Vorschau, Umbenennen), behandelt ihn dadurch
    von selbst richtig, ohne eigene Sonderregel.

    Der bewusst gewählte Preis (Nutzerentscheidung zu N242): kommt die Datei
    später unter genau diesem Pfad zurück, erkennt der Abgleich sie nicht mehr
    als „wiederda" (`_abgleiche_objekt` vergleicht auf `d.pfad`) — sie kommt
    als neuer Eintrag herein."""
    verwaist = _eintraege_auf(session, pfad)
    if not verwaist:
        return False
    for d in verwaist:
        _grabstein_setzen(session, d)
    # Der neue Eintrag bekommt gleich denselben Pfad — der Grabstein muss vor
    # ihm in der Datenbank stehen, sonst schlägt der Unique-Index zu.
    session.flush()
    return True
