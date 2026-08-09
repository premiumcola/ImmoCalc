"""N326 — die aus dem Dateinamen abgeleitete "Sache" in der gespeicherten
KI-Auslese (`_ki_aus_db`).
"""
import os
import sys
import tempfile
from datetime import date

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_ki_beleg.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.dokumente.ki_beleg import _ki_aus_db  # noqa: E402
from app.models import Dokument  # noqa: E402


def _dokument(dateiname: str) -> Dokument:
    return Dokument(pfad=f"/Obj/{dateiname}", dateiname=dateiname,
                    ki_einordnung="Testauslese", betrag=309.29,
                    belegdatum=date(2026, 4, 1), kategorie="Renovierung")


def test_sache_traegt_nicht_die_dateiendung():
    """Der gemeldete Fall: ein Dateiname mit Datum, Betrag und Endung zeigte
    als Sache einen rohen Namensrest samt Unterstrich und „.pdf" — Datum/
    Betrag wurden entfernt, aber die Endung blieb stehen, weil sie vor dem
    Entfernen nie abgeschnitten wurde."""
    d = _dokument("Heizungs-und-Wasserleitungen_2026.04.01_309,29€.pdf")
    ergebnis = _ki_aus_db(d)
    assert ergebnis["sache"] == "Heizungs-und-Wasserleitungen"
    assert ".pdf" not in ergebnis["sache"]
    assert "_" not in ergebnis["sache"]


def test_sache_ohne_datum_und_betrag_im_namen_bleibt_der_ganze_stamm():
    d = _dokument("Gartenpflege Sommer.pdf")
    assert _ki_aus_db(d)["sache"] == "Gartenpflege Sommer"
