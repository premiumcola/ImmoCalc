"""N461 — Turnus-Schreibweisen, die bisher still auf „jährlich" fielen.

Gefunden bei der Prüfung in der Nacht auf den 03.09.2026. `_schluessel`
entfernt Punkte und Bindestriche, schlägt danach aber exakt nach — eine
Abkürzung wie „monatl." wird zu „monatl" und steht in `TURNUS` nicht. Der
Docstring behauptete ausdrücklich, „viertelj." und „viertel-jährlich" meinten
dasselbe; das stimmte nicht.

Folge: `jahresbetrag(125, "monatl.")` ergab 125 € statt 1.500 € — Faktor 12
mitten in der Auswertung. Erreichbar über die KI-Auslese, die den Turnus als
Freitext aus dem Beleg übernimmt (`dokumente/entwuerfe.py` reicht ihn ohne
Normalisierung durch).
"""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(),
                                     "test_turnus_schreibweisen.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest  # noqa: E402

from app.turnus import faktor, jahresbetrag  # noqa: E402


@pytest.mark.parametrize("schreibweise, erwartet", [
    ("monatlich", 12), ("monatl.", 12), ("mtl.", 12), ("mtl", 12),
    ("vierteljährlich", 4), ("viertelj.", 4), ("viertel-jährlich", 4),
    ("quartalsweise", 4), ("quartal", 4),
    ("halbjährlich", 2), ("halbjährl.", 2), ("halbjahr", 2),
    ("jährlich", 1), ("jährl.", 1), ("p.a.", 1),
    ("einmalig", 1),
])
def test_gaengige_schreibweisen_treffen_den_richtigen_faktor(schreibweise,
                                                             erwartet):
    assert faktor(schreibweise) == erwartet, schreibweise


def test_jahresbetrag_rechnet_die_abkuerzung_hoch():
    """Der Fall aus der Praxis: eine monatliche Position als „monatl.“."""
    assert jahresbetrag(125.0, "monatl.") == 1500.0
    assert jahresbetrag(125.0, "viertelj.") == 500.0


def test_unbekanntes_bleibt_jaehrlich_und_faellt_auf():
    """Ein echter Tippfehler soll weiterhin als jährlich gelten — und nicht
    versehentlich über die Abkürzungslogik irgendwo landen."""
    assert faktor("wöchentlich") == 1
    assert faktor("zweimonatlich") == 1
    assert faktor("") == 1
    assert faktor(None) == 1
