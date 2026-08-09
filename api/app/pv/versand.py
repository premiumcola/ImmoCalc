"""Versand der jährlichen PV-Eigentümer-Abrechnung (N308).

Derselbe Ansatz wie der Versendet-Marker der E-Tankstelle
(:mod:`app.tanken.marker`): eigener Namensraum in der vorhandenen
Schlüssel/Wert-Ablage `Einstellung`, keine neue Tabelle. Bewusst hier neu
geschrieben statt aus `app.tanken` importiert — die beiden Pakete bleiben
unabhängig voneinander (siehe `app.pv._TOPICS.md`).

Ein Marker je (Objekt, Jahr, Eigentümer-Name) sperrt einen zweiten Versand.
Anders als bei der E-Tankstelle ist das hier keine Zahlungsaufforderung: die
Mieter haben der Anlage das Geld längst über die Nebenkostenabrechnung
gezahlt, die Mail sagt dem Mit-Eigentümer nur, welcher Anteil ihm für das
Jahr gehört."""
from __future__ import annotations

from datetime import date

from sqlmodel import Session, select

from ..cloudkern import _lies
from ..models import Einstellung

S_VERSENDET = "pv_versendet"


def _schluessel(slug: str, jahr: int, name: str) -> str:
    return f"{S_VERSENDET}:{slug}:{jahr}:{name}"


def ist_versendet(session: Session, slug: str, jahr: int, name: str) -> bool:
    """Hat dieser Eigentümer die Abrechnung dieses Jahres schon erhalten?"""
    return bool(_lies(session, _schluessel(slug, jahr, name)))


def _setze(session: Session, schluessel: str, wert: str) -> None:
    e = session.get(Einstellung, schluessel)
    if e is None:
        e = Einstellung(schluessel=schluessel, wert=wert)
    else:
        e.wert = wert
    session.add(e)


def versendet_merken(session: Session, slug: str, jahr: int, name: str) -> None:
    """Den Versand festhalten — ohne commit, der Aufrufer committet nach dem
    erfolgreichen Versand."""
    _setze(session, _schluessel(slug, jahr, name), date.today().isoformat())


def versendet_marker(session: Session, slug: str, jahr: int = 0) -> set[str]:
    """Welche Eigentümer-Namen für das genannte Jahr (0 = alle) bereits ihre
    Abrechnung erhalten haben — die Grundlage des ✓-Hakens in der Oberfläche."""
    prefix = f"{S_VERSENDET}:{slug}:"
    namen: set[str] = set()
    for e in session.exec(select(Einstellung).where(
            Einstellung.schluessel.like(prefix + "%"))).all():
        if not e.wert:
            continue
        jahr_roh, _, name = e.schluessel[len(prefix):].partition(":")
        try:
            j = int(jahr_roh)
        except ValueError:
            continue
        if jahr and j != jahr:
            continue
        namen.add(name)
    return namen


def _geld(wert: float) -> str:
    """Deutsche Schreibweise „1.234,56 €" — dieselbe Formel wie
    `tanken.satz.deutsch`, hier dupliziert, damit `app.pv` unabhängig vom
    Tankstellen-Paket bleibt."""
    return f"{wert:,.2f}".translate(str.maketrans(",.", ".,")) + " €"


def abrechnungstext(objekt_name: str, jahr: int, eintrag: dict,
                    jahresertrag: float) -> str:
    """Der Mailtext der jährlichen PV-Abrechnung — ein Informationsschreiben,
    keine Rechnung: die Anlage hat den Betrag schon eingenommen, hier steht
    nur, welcher Anteil davon diesem Eigentümer gehört."""
    anteil = (f"Dein Anteil ({eintrag['promille']:.1f} ‰): "
             f"{_geld(eintrag['betrag'])}" if eintrag.get("promille") is not None
             else f"Dein Anteil: {_geld(eintrag['betrag'])}")
    zeilen = [f"Hallo {eintrag['name']},", "",
              f"die PV-Anlage {objekt_name} hat im Jahr {jahr} insgesamt "
              f"{_geld(jahresertrag)} zur Amortisation beigetragen.", "",
              anteil, "", "Viele Grüße"]
    return "\n".join(zeilen) + "\n"
