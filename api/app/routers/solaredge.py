"""N126 — den SolarEdge-Screenshot hochladen statt die Zahlen abzutippen.

Ein Endpunkt, rein lesend: `POST /api/solaredge/lesen` nimmt das Bild entgegen,
lässt es vom Vision-Modell lesen und gibt die erkannten Zahlen samt Warnungen
zurück. **Gespeichert wird nichts** — weder in der Datenbank noch in der Cloud.
Der Nutzer sieht die Werte, bestätigt sie und trägt sie selbst ein.

Fällt die Erkennung aus (kein Schlüssel, kein Netz, unbrauchbare Antwort), ist
das kein Fehler: die Antwort kommt mit leeren Feldern und einem Hinweis, dass
die vier Werte von Hand einzutragen sind. Genau so hat der Nutzer es sich
gewünscht.
"""
import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlmodel import Session

from .. import kiauslese, solaredge
from ..db import get_session
from .ki import ki_key, ki_modell

log = logging.getLogger("immocalc")
router = APIRouter(prefix="/api/solaredge", tags=["solaredge"])

# Ein Screenshot ist ein paar hundert Kilobyte. Fünf Megabyte sind reichlich
# Luft und zugleich die Grenze, die die Bilderkennung selbst zieht.
MAX_BYTES = 5 * 1024 * 1024

VON_HAND = ("Bitte die vier Werte aus der SolarEdge-Oberfläche von Hand "
            "eintragen.")


@router.post("/lesen")
async def lesen(datei: UploadFile = File(...),
                session: Session = Depends(get_session)) -> dict:
    """Liest Produktion und Verbrauch aus einem SolarEdge-Screenshot.

    Gibt die erkannten Mengen in kWh, die drei Anteile je Balken, deren
    Umrechnung in kWh und etwaige Warnungen zurück. `erkannt` sagt, ob die
    Verbrauchszeile stand — nur sie wird für die Kostenblöcke gebraucht.

    Nichts wird gespeichert."""
    rohdaten = await datei.read()
    if not rohdaten:
        raise HTTPException(400, "Leere Datei")
    if len(rohdaten) > MAX_BYTES:
        raise HTTPException(400, "Das Bild ist zu groß (mehr als 5 MB) — bitte "
                                 "einen Screenshot statt eines Fotos hochladen.")
    typ = solaredge.medientyp(rohdaten, datei.content_type or "")
    if not typ:
        raise HTTPException(400, "Das ist kein Bild (PNG, JPEG, GIF oder WEBP).")

    schluessel = ki_key(session)
    if not kiauslese.verfuegbar(schluessel):
        ergebnis = solaredge.aufbereiten({}).als_dict()
        ergebnis["hinweis"] = ("Die Bilderkennung ist nicht eingerichtet. "
                               + VON_HAND)
        return ergebnis

    roh = kiauslese.lies_solaredge(rohdaten, typ, schluessel=schluessel,
                                   modell=ki_modell(session))
    ergebnis = solaredge.aufbereiten(roh).als_dict()
    ergebnis["hinweis"] = ("" if ergebnis["erkannt"] else
                           "Der Screenshot konnte nicht gelesen werden. " + VON_HAND)
    return ergebnis
