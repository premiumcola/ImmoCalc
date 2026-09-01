"""DELETE /objekte/{slug} — Löschen mit vorheriger JSON-Sicherung.

Löschen ist die einzige Stelle im ganzen Backend, die Nutzerdaten wirklich
entfernt. Vorher wird eine JSON-Sicherung in die Nextcloud geschrieben; die
Dateien in der Cloud gehören dem Nutzer und bleiben unangetastet.
"""
import logging

from fastapi import APIRouter, Depends
from sqlmodel import Session

from ..db import get_session
from ..deps import objekt_holen
from ..export import als_datei, dateiname, exportiere, loesche
from ..models import Objekt

log = logging.getLogger("immocalc")
router = APIRouter(tags=["objekte"])

# Sicherungen liegen im Home-Ordner, nicht bei den Unterlagen einer Immobilie —
# die bleibt beim Löschen ja gerade bestehen.
SICHERUNGSORDNER = "00_ImmoCalc_Sicherungen"


def _sicherung_in_die_cloud(session: Session, objekt: Objekt,
                            daten: dict) -> dict:
    """Legt die Sicherung neben den Unterlagen ab — best effort.

    Scheitert das (keine Verbindung, kein Home-Ordner), wird trotzdem
    gelöscht: die Sicherung geht ohnehin auch an den Browser."""
    from ..routers.cloud import S_HOME, _lies, verbindung  # zirkelfrei zur Laufzeit
    home = _lies(session, S_HOME)
    if not home:
        return {"gesichert": False, "grund": "Kein Home-Ordner gewählt"}
    ordner = f"{home.strip('/')}/{SICHERUNGSORDNER}"
    ziel = f"{ordner}/{dateiname(objekt)}"
    try:
        client = verbindung(session)
        client.ordner_anlegen(ordner)
        name, n = ziel, 2
        while client.existiert(name):        # nie überschreiben
            name = ziel[:-5] + f"_{n}.json"
            n += 1
        client.lege_ab(name, als_datei(daten), typ="application/json")
        return {"gesichert": True, "pfad": "/" + name}
    except Exception as fehler:              # noqa: BLE001 — Löschen soll laufen
        log.warning("Sicherung in die Cloud fehlgeschlagen: %s", fehler)
        return {"gesichert": False, "grund": str(fehler)}


@router.delete("/objekte/{slug}")
def objekt_loeschen(session: Session = Depends(get_session),
                    o: Objekt = Depends(objekt_holen)) -> dict:
    """Löscht eine Immobilie samt allem, was in der Datenbank daran hängt.

    Vorher wird eine JSON-Sicherung in die Nextcloud geschrieben. Die dort
    liegenden Unterlagen bleiben unberührt — sie gehören dem Nutzer."""
    daten = exportiere(session, o)
    sicherung = _sicherung_in_die_cloud(session, o, daten)
    name, ordner = o.name, o.nc_ordner
    entfernt = loesche(session, o)
    return {"ok": True, "name": name, "entfernt": entfernt,
            "sicherung": sicherung,
            "cloud_ordner_bleibt": ordner or None}
