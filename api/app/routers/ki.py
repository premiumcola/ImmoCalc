"""KI-Beleg-Auslese: Anthropic-Schlüssel eintragen und Erreichbarkeit prüfen.

Der Schlüssel wird — wie die Nextcloud-Zugangsdaten — in der `Einstellung`-
Tabelle abgelegt (Schlüssel/Wert). Er hat Vorrang vor `ANTHROPIC_API_KEY` aus
der Umgebung; ohne beides bleibt die Auslese stumm (siehe `kiauslese.py`).

Sicherheit — der Schlüssel selbst verlässt die API nie: `GET /ki/status` gibt
nur zurück, ob etwas hinterlegt ist, und `POST` speichert, gibt aber nur das
Testergebnis zurück. Nichts loggt den Schlüssel.
"""
import logging
import os

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session

from .. import kiauslese
from .. import familienraum, geheimnis
from ..cloudkern import _lies
from ..db import get_session
from ..models import Einstellung

log = logging.getLogger("immocalc")
router = APIRouter(prefix="/api/ki", tags=["ki"])

# Schlüssel in der Einstellung-Tabelle. Der API-Key ist ein Geheimnis wie das
# Nextcloud-Passwort; das Modell ist frei wählbar (Vorgabe in kiauslese.py).
S_KI_KEY = "ki_api_key"
S_KI_MODELL = "ki_modell"


def _schreib(session: Session, schluessel: str, wert: str) -> None:
    """Einen Einstellung-Eintrag anlegen oder überschreiben (wie in cloud.py).
    N436 — derselbe Namensraum wie `cloudkern._lies`.
    N475 — der KI-Schlüssel wird vor dem Speichern verschlüsselt."""
    if schluessel in geheimnis.GEHEIME_SCHLUESSEL:
        wert = geheimnis.schuetzen(wert)
    schluessel = familienraum.schluessel(schluessel)
    eintrag = session.get(Einstellung, schluessel)
    if eintrag:
        eintrag.wert = wert
    else:
        eintrag = Einstellung(schluessel=schluessel, wert=wert)
    session.add(eintrag)


def ki_key(session: Session) -> str:
    """Der hinterlegte Schlüssel — leer, wenn keiner gespeichert ist."""
    return _lies(session, S_KI_KEY)


def ki_modell(session: Session) -> str:
    """Das hinterlegte Modell — leer heißt: Vorgabe aus kiauslese.py."""
    return _lies(session, S_KI_MODELL)


class SchluesselIn(BaseModel):
    key: str
    modell: str = ""


@router.get("/status")
def status(session: Session = Depends(get_session)) -> dict:
    """Ist die KI eingerichtet und erreichbar?

    `eingerichtet` = Schlüssel in der DB ODER `ANTHROPIC_API_KEY` gesetzt. Ist
    sie eingerichtet, wird ein winziger echter Ping gemacht (`kiauslese.pruefe`)
    → `erreichbar` true/false. Ohne Einrichtung bleibt `erreichbar` null.

    N482 — der SELBST hinterlegte Schlüssel geht an die angemeldete Familie
    zurück, damit das Feld ihn als Punkte zeigt und das Auge daneben ihn
    aufdecken kann (Begründung ausführlich in `routers/cloud.py::status`).

    Der Schlüssel aus der UMGEBUNG geht ausdrücklich NICHT mit: der gehört
    dem Betreiber der Installation, nicht der Familie. `ki_key()` liest
    ohnehin nur die Datenbank — die Trennung ist damit schon im Aufruf
    angelegt und wird hier nur nicht wieder aufgeweicht."""
    key = ki_key(session)
    modell = ki_modell(session)
    eingerichtet = kiauslese.verfuegbar(key)
    aus_umgebung = bool((os.environ.get("ANTHROPIC_API_KEY") or "").strip())
    antwort = {
        "eingerichtet": eingerichtet,
        "gespeichert": bool(key),
        # Nur der eigene, gespeicherte Schlüssel — nie der aus der Umgebung.
        "schluessel": key or "",
        "aus_umgebung": aus_umgebung and not key,
        "modell": modell or kiauslese.STANDARD_MODELL,
        "erreichbar": None,
        "fehler": "",
    }
    if eingerichtet:
        ergebnis = kiauslese.pruefe(key, modell)
        antwort["erreichbar"] = ergebnis["erreichbar"]
        antwort["fehler"] = ergebnis["fehler"]
    return antwort


@router.post("/schluessel")
def schluessel_speichern(data: SchluesselIn,
                         session: Session = Depends(get_session)) -> dict:
    """Speichert Schlüssel (und Modell, falls gesetzt) und prüft gleich.

    Ein leerer Schlüssel löscht den gespeicherten Eintrag. Zurück kommt nur das
    Testergebnis — nie der Schlüssel."""
    key = (data.key or "").strip()
    modell = (data.modell or "").strip()

    if not key:
        _schreib(session, S_KI_KEY, "")
        if modell:
            _schreib(session, S_KI_MODELL, modell)
        session.commit()
        log.info("KI-Schlüssel entfernt")
        return {"gespeichert": False, "erreichbar": None, "fehler": ""}

    _schreib(session, S_KI_KEY, key)
    _schreib(session, S_KI_MODELL, modell)
    session.commit()
    # NIE den Schlüssel loggen — nur, dass einer hinterlegt wurde.
    log.info("KI-Schlüssel gespeichert (Modell %s)",
             modell or kiauslese.STANDARD_MODELL)
    ergebnis = kiauslese.pruefe(key, modell)
    return {"gespeichert": True, **ergebnis}


@router.delete("/schluessel")
def schluessel_loeschen(session: Session = Depends(get_session)) -> dict:
    """Entfernt den gespeicherten Schlüssel. Die Umgebung bleibt unberührt."""
    _schreib(session, S_KI_KEY, "")
    session.commit()
    log.info("KI-Schlüssel entfernt")
    return {"gespeichert": False}
