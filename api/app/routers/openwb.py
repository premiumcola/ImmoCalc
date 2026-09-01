"""N130 — die openWB-Wallbox anbinden: Adresse hinterlegen, Ladungen summieren.

Drei Endpunkte, alle **rein lesend** gegenüber der Wallbox (nur GET) und ohne
Schreibzugriff auf fremde Tabellen. Gespeichert wird genau eine Sache: die
Basisadresse der Box, als Einstellung unter ``openwb_url`` (Vorgabe leer — die
IP gehört in die Einstellungen, nicht in den Code).

Ob die ermittelten Werte in ein Stromjahr übernommen werden, entscheidet der
Nutzer später in der Oberfläche. Hier wird nichts übernommen.

Die Box steht im Heimnetz und ist mal weg. Deshalb führt **kein** Ausfall zu
einem Serverfehler: `/ladungen` antwortet dann mit ``ok: false``, einem
verständlichen Hinweis und **leeren** Feldern statt Nullen — eine 0 sähe aus
wie eine Messung. Die Handeingabe bleibt der Rückfallweg.
"""
import logging
from datetime import date

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session

from .. import openwb
from .. import familienraum
from ..cloudkern import _lies
from ..db import get_session
from ..models import Einstellung

log = logging.getLogger("immocalc")
router = APIRouter(prefix="/api/openwb", tags=["openwb"])

# Einstellungs-Schlüssel — eigener Name, kein bestehender wird angefasst.
S_URL = "openwb_url"

# Kurz genug, dass die Oberfläche nicht hängt, wenn die Box aus ist.
TIMEOUT = 8.0

VON_HAND = "Die Werte lassen sich solange von Hand eintragen."


class AdresseIn(BaseModel):
    url: str = ""


def _schreib(session: Session, schluessel: str, wert: str) -> None:
    """Eine Einstellung setzen — additiv, ohne andere Schlüssel zu berühren.
    N436 — derselbe Namensraum wie `cloudkern._lies`."""
    schluessel = familienraum.schluessel(schluessel)
    eintrag = session.get(Einstellung, schluessel)
    if eintrag:
        eintrag.wert = wert
    else:
        eintrag = Einstellung(schluessel=schluessel, wert=wert)
    session.add(eintrag)


def _basis(session: Session) -> str:
    """Die hinterlegte Basisadresse der Wallbox — leer, wenn keine da ist."""
    return openwb.normalisiere_basis(_lies(session, S_URL))


def _hole(basis: str, jahr: int) -> str:
    """Das Ladeprotokoll eines Jahres holen — nur GET, mit knappem Timeout.

    Jeder Netzfehler wird in einen :class:`openwb.OpenwbFehler` mit
    verständlichem Text übersetzt; der Aufrufer muss keine httpx-Ausnahmen
    kennen."""
    adresse = openwb.protokoll_url(basis, jahr)
    try:
        antwort = httpx.get(adresse, timeout=TIMEOUT,
                            follow_redirects=True)
    except httpx.TimeoutException as fehler:
        raise openwb.OpenwbFehler(
            f"Die Wallbox hat innerhalb von {TIMEOUT:.0f} Sekunden nicht "
            f"geantwortet ({basis}). Ist sie eingeschaltet und im Netz?"
        ) from fehler
    except (httpx.HTTPError, httpx.InvalidURL, ValueError) as fehler:
        # httpx.InvalidURL ist *kein* HTTPError — ohne diesen Zweig käme statt
        # einer Meldung ein Serverfehler heraus.
        raise openwb.OpenwbFehler(
            f"Die Wallbox ist unter {basis} nicht erreichbar ({fehler}).") \
            from fehler
    if antwort.status_code != 200:
        raise openwb.OpenwbFehler(
            f"Die Wallbox antwortete für {jahr} mit HTTP "
            f"{antwort.status_code}. Stimmt die Adresse?")
    return antwort.text


def _pruefe_zeitraum(von: date, bis: date) -> None:
    """Ein Zeitraum, der rückwärts läuft, ist eine Fehleingabe — kein Ausfall."""
    if bis < von:
        raise HTTPException(400, "Das Ende des Zeitraums liegt vor seinem "
                                 "Beginn.")


def _ohne_ergebnis(von: date, bis: date, hinweis: str) -> dict:
    """Die Antwortform, wenn nichts zu holen war — leere Felder, nie Nullen."""
    return {"ok": False, "hinweis": hinweis,
            "von": von.isoformat(), "bis": bis.isoformat(),
            "anzahl": None, "ohne_energie": None, "kwh": None, "kosten": None,
            "extern_kwh": None, "speicher_kwh": None, "pv_kwh": None,
            "eigen_kwh": None, "ladepunkte_kwh": None,
            "nicht_zugeordnet_kwh": None, "extern_prozent": None,
            "eigen_prozent": None, "speicher_prozent": None,
            "pv_prozent": None, "warnungen": []}


@router.get("/status")
def status(session: Session = Depends(get_session)) -> dict:
    """Ist eine Adresse hinterlegt — und meldet sich die Box?

    Antwortet immer mit 200: „nicht erreichbar" ist ein Zustand, den die
    Oberfläche anzeigt, kein Fehler."""
    basis = _basis(session)
    if not basis:
        return {"eingerichtet": False, "url": "", "erreichbar": False,
                "hinweis": "Für die Wallbox ist noch keine Adresse hinterlegt."}
    try:
        _hole(basis, date.today().year)
    except openwb.OpenwbFehler as fehler:
        log.info("openWB nicht erreichbar: %s", fehler)
        return {"eingerichtet": True, "url": basis, "erreichbar": False,
                "hinweis": f"{fehler} {VON_HAND}"}
    return {"eingerichtet": True, "url": basis, "erreichbar": True,
            "hinweis": ""}


@router.post("/adresse")
def adresse_speichern(data: AdresseIn,
                      session: Session = Depends(get_session)) -> dict:
    """Die Basisadresse der Wallbox hinterlegen (z. B. ``192.168.178.61``).

    Gespeichert wird auch dann, wenn die Box gerade nicht antwortet — sie ist
    im Heimnetz nicht immer an, und der Nutzer soll sie trotzdem einrichten
    können. Ob sie sich meldet, steht in `erreichbar`. Ein leerer Wert löscht
    die Angabe wieder."""
    basis = openwb.normalisiere_basis(data.url)
    if data.url.strip() and not basis:
        raise HTTPException(400, "Das ist keine brauchbare Adresse — erwartet "
                                 "wird z. B. „192.168.178.61“.")
    _schreib(session, S_URL, basis)
    session.commit()
    log.info("openWB-Adresse gesetzt: %s", basis or "(geleert)")
    return status(session)


@router.get("/ladungen")
def ladungen(von: date = Query(...), bis: date = Query(...),
             session: Session = Depends(get_session)) -> dict:
    """Die Ladungen eines **Abrechnungszeitraums** summieren.

    Gefiltert wird nach dem Datum des Ladebeginns, nicht nach Kalenderjahr:
    für 01.10.2024–30.09.2025 werden beide Jahresdateien geholt und die Zeilen
    selbst ausgesiebt. Rein lesend — es wird nichts gespeichert."""
    _pruefe_zeitraum(von, bis)
    basis = _basis(session)
    if not basis:
        return _ohne_ergebnis(von, bis, "Für die Wallbox ist noch keine "
                                        f"Adresse hinterlegt. {VON_HAND}")

    alle: list[openwb.Ladung] = []
    warnungen: list[str] = []
    try:
        for jahr in openwb.jahre(von, bis):
            protokoll = openwb.lies(_hole(basis, jahr))
            alle = openwb.zusammenfuehren(alle, protokoll.ladungen)
            warnungen += protokoll.warnungen
        summe = openwb.summiere(alle, von, bis, warnungen)
    except openwb.OpenwbFehler as fehler:
        # Kein Serverfehler: die Box ist weg oder liefert etwas Unerwartetes.
        # Der Nutzer bekommt den Grund und trägt notfalls von Hand ein.
        log.warning("openWB-Ladeprotokoll nicht auswertbar: %s", fehler)
        return _ohne_ergebnis(von, bis, f"{fehler} {VON_HAND}")

    return {"ok": True, "hinweis": "", "quelle": basis, **summe.als_dict()}
