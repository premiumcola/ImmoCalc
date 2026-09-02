"""N439 — Kostenart-Normalisierung gegen echte Abrechnungen geprüft."""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_kostenarten.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.kostenarten import normalisieren  # noqa: E402


# N439 — Kostenarten aus einer echten WEG-Abrechnung (Immoware24), die der
# Nutzer als Foto geschickt hat. Sie stehen dort mit Kontonummer davor.
def test_kostenarten_einer_weg_abrechnung_werden_zusammengefasst():
    faelle = {
        "040100 Hausmeisterkosten": "Hausmeister",
        "040200 Hausmeistergehalt": "Hausmeister",
        "043201 Müllentsorgung": "Müll",
        "044300 Wartung Aufzug": "Aufzug",
        "051001 Matten-Service": "Mattenservice",
        "046001 Versicherung: Gebäude": "Gebäudeversicherung",
        "046203 Versicherung: Haus- und Grundbesitzer-Haftpflicht":
            "Gebäudehaftpflicht",
        "043005 Strom Allgemein": "Allgemeinstrom",
        "044501 Wartung Enthärtungsanlage": "Wartung Enthärtungsanlage",
    }
    for roh, erwartet in faelle.items():
        assert normalisieren(roh) == erwartet, roh


def test_eine_jahreszahl_ist_keine_kontonummer():
    """Die Kontonummer-Abtrennung darf nur echte Konten treffen (>= 5 Ziffern),
    sonst verschluckt sie das Jahr aus „2026 Nachzahlung"."""
    assert normalisieren("2026 Nachzahlung") == "2026 Nachzahlung"
    assert normalisieren("1 Rate") == "1 Rate"
    assert normalisieren("2025 Abrechnung") == "2025 Abrechnung"
