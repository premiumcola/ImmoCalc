"""N9 — Lagepläne sinnvoll ablegen und benennen.

Vorher: `dateiname(None, "Sonstiges", …)` erzeugte einen „ohne-Jahr_"-Präfix
und legte die Datei in `99_Sonstiges` ab. Ein Lageplan hat kein Belegjahr —
das Präfix ist unsinnig, und er gehört zu Fotos/Lage.
"""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(),
                                     "test_lageplan_ablage.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.cloudkern import ARTKUERZEL, STRUKTUR, ZIELORDNER  # noqa: E402
from app.routers.dokumente import _saubere_datei  # noqa: E402


def test_lageplan_landet_im_fotos_lage_ordner():
    """N332 — der Sammelordner heisst jetzt „10_Fotos_Lageplaene"."""
    assert ZIELORDNER["Lageplan"] == "10_Fotos_Lageplaene"
    assert ZIELORDNER["Lageplan"] in STRUKTUR       # Ordner existiert überall
    assert ARTKUERZEL["Lageplan"] == ""             # kein Kürzel im Namen


def test_lageplan_name_ohne_ohne_jahr_praefix():
    name = _saubere_datei("Lageplan Wohnug 1.OG") + ".pdf"
    assert name == "Lageplan-Wohnug-1.OG.pdf"
    assert "ohne-Jahr" not in name


def test_lageplan_name_nimmt_den_zusatztitel_auf():
    name = _saubere_datei("Lageplan Wohnug 1.OG - Bad") + ".pdf"
    assert name == "Lageplan-Wohnug-1.OG-Bad.pdf"
    assert name.startswith("Lageplan-") and name.endswith("-Bad.pdf")
