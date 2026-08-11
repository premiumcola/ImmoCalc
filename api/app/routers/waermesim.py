"""N340l — der Wärmesimulator als Endpunkt.

`app.waermesim.rechne` ist eine reine Funktion; hier steht nur die Hülle, die
sie über HTTP erreichbar macht. Kein Datenbankzugriff — das Frontend schickt
alles mit (Zähler, Zuordnung, Jahreswerte), der Endpunkt rechnet und gibt das
Ergebnis zurück. Bewusst so schlank: das ist ein Werkzeug auf Zeit (siehe
`waermesim.py`), keine dauerhafte Fachlogik."""
from fastapi import APIRouter

from .. import waermesim

router = APIRouter(prefix="/api/waermesim", tags=["waermesim"])


@router.post("/rechne")
def rechne(eingabe: dict) -> dict:
    """Ein Abrechnungsjahr durchrechnen — siehe `waermesim.rechne` für die
    Feldbeschreibung. Ungültige Eingaben ergeben eine leere/nullwertige
    Aufstellung statt eines Fehlers, dieselbe Grundhaltung wie das Modul
    selbst: ein unvollständiges Simulationsjahr soll nicht die ganze Seite
    zum Absturz bringen."""
    return waermesim.rechne(eingabe or {})
