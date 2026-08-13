"""PV-Anlage-Stammdaten (N139/N153/N216).

Was zur Anlage gehört und nicht zum Jahr — Anschaffung, bereits Abgetragenes
(mit Aufschlüsselung nach Quellen, N153), Leistung und Eigentümer-Anteile —
steht in :class:`app.models.PVAnlage` (ein Satz je Objekt). Die gleichnamigen
Felder am :class:`app.models.Stromjahr` bleiben stehen (nie umbenennen, nie
entfernen), werden aber nur noch für die **einmalige** Übernahme des Bestands
gelesen.
"""
from __future__ import annotations

import json
import logging
from datetime import date

from pydantic import BaseModel
from sqlmodel import Session, select

from .. import strom
from ..models import PVAnlage, Stromjahr, Zeitraum
from ..vermoegen import PROMILLE_TOLERANZ, VOLLE_PROMILLE

log = logging.getLogger("immocalc")


# Stammdatenfeld → altes Feld am `Stromjahr`. Nur für die einmalige Übernahme.
_STAMM_AUS_JAHR: dict[str, str] = {
    "anschaffung_eur": "anschaffung_eur",
    "vorlauf_ertrag_eur": "vorlauf_ertrag_eur",
    "kwp": "pv_kwp",
    "anteile": "pv_anteile",
}

# N370 — aus `vermoegen`, statt einer dritten eigenen Antwort. Die hier
# gepflegte Toleranz war auf 0,5 ‰ gewachsen, also das Fünffache der beiden
# anderen: dieselbe Anteilsliste galt je nach Ansicht als vollständig oder
# nicht. Rundungsluft bleibt, sie ist nur überall gleich groß (833,3 + 166,7
# = 1000,0 geht weiterhin auf).
_VOLLE_PROMILLE = VOLLE_PROMILLE
_PROMILLE_TOLERANZ = PROMILLE_TOLERANZ

# Quelle im Verlauf → Feld an der Anlage. Dieselben drei Namen wie in
# `_QUELLEN_LEER`, damit Vorlauf und Jahre dieselbe Sprache sprechen.
_VORLAUF_QUELLEN: dict[str, str] = {"pv_strom": "vorlauf_pv_strom_eur",
                                    "einspeisung": "vorlauf_einspeisung_eur",
                                    "tanken": "vorlauf_tanken_eur"}


class StammdatenIn(BaseModel):
    """Die Stammdaten der PV-Anlage.

    Alle Felder optional: `None` heißt „nicht mitgeschickt" und lässt den
    gespeicherten Wert stehen. Das ist die Lehre aus N108 (Fund 2) — ein
    Pflichtfeld mit Default löscht bei jedem Teil-Speichern die übrigen
    Angaben."""
    anschaffung_eur: float | None = None
    vorlauf_ertrag_eur: float | None = None
    # N153 — der Vorlauf aufgeschlüsselt nach denselben Quellen wie die Jahre
    # danach. Ebenfalls `None`-Default: wer nur PV-Strom tippt, darf damit die
    # Einspeisung nicht auf 0 setzen (genau dieser Fehler kostete in N150 Daten).
    vorlauf_pv_strom_eur: float | None = None
    vorlauf_einspeisung_eur: float | None = None
    vorlauf_tanken_eur: float | None = None
    kwp: float | None = None
    inbetriebnahme: date | None = None
    anteile: str | None = None        # JSON {Name: ‰}
    notiz: str | None = None


def _vorlauf(a: PVAnlage) -> tuple[float, dict[str, float] | None]:
    """N153 — was die Anlage vor der ersten Abrechnung abgetragen hat: der
    Betrag und, wenn gepflegt, seine Herkunft.

    Die Vorrang-Regel: ist die Aufschlüsselung gepflegt (mindestens eines der
    drei Felder ≠ 0), gilt IHRE SUMME als Vorlauf. Sonst gilt weiterhin der
    Gesamtwert `vorlauf_ertrag_eur`. So bleibt der bestehende Wert des Nutzers
    gültig, bis er die Aufteilung einträgt — und es entstehen keine zwei
    Wahrheiten. `vorlauf_ertrag_eur` bleibt dabei unangetastet stehen."""
    teile = {quelle: round(float(getattr(a, feld, 0.0) or 0.0), 2)
             for quelle, feld in _VORLAUF_QUELLEN.items()}
    if any(teile.values()):
        return round(sum(teile.values()), 2), teile
    return round(a.vorlauf_ertrag_eur or 0.0, 2), None


def _erster_abrechnungsstart(session: Session, objekt_id: int,
                             inbetriebnahme: date | None = None) -> date | None:
    """Der Beginn des ersten Abrechnungszeitraums — die Grenze, bis zu der der
    Vorlauf zählt. Kommt aus den Daten; kein Datum steht im Code.

    N335 — gemeint ist der erste Zeitraum, der die ANLAGE erfasst, nicht der
    erste des Hauses. Die Immobilie rechnet seit 2018 ab, die Anlage steht erst
    seit Mitte 2023: ohne diese Grenze sagte die Maske „von der Inbetriebnahme
    am 30.06.2023 bis zum 01.10.2018" — ein Zeitraum, der rückwärts läuft."""
    frage = select(Zeitraum.start).where(Zeitraum.objekt_id == objekt_id)
    if inbetriebnahme:
        frage = frage.where(Zeitraum.start >= inbetriebnahme)
    return session.exec(frage.order_by(Zeitraum.start)).first()


def _anteile_dict(roh: str | None) -> dict[str, float]:
    """Die Anteile als {Name: ‰}. Unlesbares oder Leeres ergibt {} — die
    Vorgabe 5/6 + 1/6 greift dann weiter unten."""
    if not roh:
        return {}
    try:
        d = json.loads(roh) if isinstance(roh, str) else dict(roh)
        return {str(k): float(v) for k, v in d.items() if float(v) > 0}
    except (ValueError, TypeError, AttributeError):
        log.warning("PV-Anteile unlesbar — Vorgabe 5/6+1/6")
        return {}


def _anteile_tupel(anlage: PVAnlage) -> tuple[tuple[str, float], ...]:
    """Die Anteile in der Form, die `strom.verteile_eigentuemer` erwartet."""
    anteile = _anteile_dict(anlage.anteile)
    return tuple(anteile.items()) if anteile else strom.EIGENTUEMER_ANTEILE


def _uebernahme_aus_jahren(session: Session, objekt_id: int) -> dict:
    """Die Bestandswerte aus den Strom-Jahren einsammeln — je Feld der zuletzt
    erfasste gefüllte Wert (die Angaben wanderten nicht jedes Jahr mit, oft
    steht die Anschaffung nur an einem einzigen Jahr)."""
    werte: dict[str, object] = {}
    for sj in session.exec(select(Stromjahr)
                           .where(Stromjahr.objekt_id == objekt_id)
                           .order_by(Stromjahr.jahr)).all():
        for stamm, alt in _STAMM_AUS_JAHR.items():
            wert = getattr(sj, alt, None)
            if wert:
                werte[stamm] = wert
    return werte


def _stammdaten(session: Session, objekt_id: int) -> PVAnlage:
    """Die Stammdaten eines Objekts — bei Bedarf angelegt.

    Gibt es noch keinen Satz, werden die Bestandswerte **einmalig** aus den
    Strom-Jahren übernommen und festgeschrieben. Danach gilt nur noch, was hier
    steht: ein Jahreswechsel ändert die Stammdaten nicht mehr. Ist nichts zu
    übernehmen, kommt ein leerer, ungespeicherter Satz zurück — erst der PUT
    legt ihn wirklich an."""
    anlage = session.exec(select(PVAnlage)
                          .where(PVAnlage.objekt_id == objekt_id)).first()
    if anlage:
        return anlage
    anlage = PVAnlage(objekt_id=objekt_id)
    uebernommen = _uebernahme_aus_jahren(session, objekt_id)
    for feld, wert in uebernommen.items():
        setattr(anlage, feld, wert)
    if uebernommen:
        session.add(anlage)
        session.commit()
        session.refresh(anlage)
        log.info("PV-Stammdaten aus den Strom-Jahren übernommen (Objekt %s): %s",
                 objekt_id, ", ".join(sorted(uebernommen)))
    return anlage


def _promille_text(wert: float) -> str:
    """Eine ‰-Zahl deutsch und ohne überflüssige Nullen."""
    return f"{wert:.1f}".rstrip("0").rstrip(".").replace(".", ",")


def _anteile_hinweise(anteile: dict[str, float], summe: float) -> list[str]:
    """Ein ruhiger Hinweis, wenn die vergebenen Anteile nicht 1000 ‰ ergeben.
    Ein Hinweis, keine Sperre — gespeichert wird trotzdem."""
    if not anteile or abs(summe - _VOLLE_PROMILLE) <= _PROMILLE_TOLERANZ:
        return []
    rest = round(_VOLLE_PROMILLE - summe, 1)
    fehlt = (f"{_promille_text(abs(rest))} ‰ "
             + ("fehlen noch" if rest > 0 else "zu viel"))
    return [f"Die vergebenen Anteile ergeben {_promille_text(summe)} ‰ "
            f"statt 1000 ‰ — {fehlt}."]


def _zeige_stammdaten(a: PVAnlage, vorlauf_bis: date | None = None) -> dict:
    """Die Stammdaten als JSON, inklusive der aufgelösten Anteile und der
    Hinweise zur Anteilssumme.

    N153 — dazu der Vorlauf in drei Formen: die drei Einzelfelder (die Maske),
    der geltende Betrag `vorlauf_summe` (die Vorrang-Regel, siehe `_vorlauf`)
    und `vorlauf_bis`, der Beginn des ersten Abrechnungszeitraums — daraus sagt
    die Maske, welcher Zeitraum überhaupt gemeint ist."""
    anteile = _anteile_dict(a.anteile)
    summe = round(sum(anteile.values()), 3)
    vorlauf_summe, vorlauf_teile = _vorlauf(a)
    return {
        "anschaffung_eur": a.anschaffung_eur,
        "vorlauf_ertrag_eur": a.vorlauf_ertrag_eur,
        **{feld: getattr(a, feld, 0.0) or 0.0
           for feld in _VORLAUF_QUELLEN.values()},
        "vorlauf_summe": vorlauf_summe,
        "vorlauf_teile": vorlauf_teile,
        "vorlauf_aufgeschluesselt": vorlauf_teile is not None,
        "vorlauf_bis": vorlauf_bis.isoformat() if vorlauf_bis else None,
        "kwp": a.kwp,
        "inbetriebnahme": a.inbetriebnahme.isoformat() if a.inbetriebnahme else None,
        "anteile": a.anteile or "",
        "anteile_promille": anteile,
        "anteile_summe": summe,
        "notiz": a.notiz,
        "hinweise": _anteile_hinweise(anteile, summe),
    }
