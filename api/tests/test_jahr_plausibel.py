"""CCCLXXIII — die Jahres-Erkennung aus Dateinamen bleibt auf plausible Jahre
begrenzt (1990 … heute+10). Eine Artikelnummer wie 204596 wird nicht mehr als
Jahr 2045 gelesen; ein plausibles Datum wird weiterhin erkannt und aus dem Namen
gestrichen. Wächter für die Datenlage aus den echten Belegen."""
import os
import sys
import tempfile
from datetime import date

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_jahr_plausibel.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.bezeichnung import datum_aus_namen, ohne_datum  # noqa: E402


def test_artikelnummer_ist_kein_jahr():
    # Genau der echte Fall: 2045 sind die ersten vier Stellen einer Artikelnr.
    assert datum_aus_namen("2045_204596-00-GPIE.jpg") == (None, None)
    # Und die Ziffer bleibt Teil des Namens, wird nicht gestrichen.
    assert "2045" in ohne_datum("2045_204596-00-GPIE.jpg")


def test_plausibles_datum_wird_erkannt():
    assert datum_aus_namen("2025-03_NK-Wasser.pdf") == (2025, 3)
    assert datum_aus_namen("2024-11-05_Rechnung.pdf") == (2024, 11)
    assert datum_aus_namen("2023_Grundsteuer.pdf") == (2023, None)
    # Das erkannte Datum wird aus dem Namen entfernt.
    assert "2025" not in ohne_datum("2025-03_NK-Wasser.pdf")


def test_naechste_jahre_bleiben_plausibel():
    naechstes = date.today().year + 1
    jahr, _ = datum_aus_namen(f"{naechstes}-01_Voraus.pdf")
    assert jahr == naechstes


def test_fernes_zukunftsjahr_wird_verworfen():
    fern = date.today().year + 20
    assert datum_aus_namen(f"{fern}-05_Unsinn.pdf") == (None, None)


def test_ohne_jahr_bleibt_leer():
    assert datum_aus_namen("Mietvertrag-Wohnung-1OG.pdf") == (None, None)
    assert datum_aus_namen("") == (None, None)
