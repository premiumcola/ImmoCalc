"""Der abgerechnet-/versendet-Marker der E-Tankstelle (N182/N187).

Ein Marker ist derselbe Schlüssel für Autoversand und Handmarkierung: einer je
(Objekt, Jahr, Quartal, Nutzer) — oder monatsgenau (N187). Er sperrt einen
zweiten Versand und trägt den „abgerechnet"-Haken der Oberfläche."""
from __future__ import annotations

from datetime import date

from sqlmodel import Session, select

from .. import familienraum
from ..cloudkern import _lies
from ..models import Einstellung
from .einstellungen import _setze

# Der Versendet-Marker je Objekt+Quartal+Nutzer. Er ist die eine Zusicherung
# gegen doppelten Versand: der 15-Minuten-Wachdienst schickt ein bereits
# verschicktes Quartal nie ein zweites Mal.
S_VERSENDET = "tankstelle_versendet"


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
    # N436 — Rohabfrage statt _lies: der Namensraum muss hier von Hand rein.
    prefix = f"{familienraum.schluessel(S_VERSENDET)}:{slug}:"
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
