"""N456 — Zählerverbrauch einer zeitweise leerstehenden Einheit.

Gefunden bei der Prüfung in der Nacht auf den 03.09.2026. `auf_parteien`
übersetzt Mengen je EINHEIT in Gewichte je PARTEI. Für Zähler, die
historisch auf den Partei-Namen gepflegt sind, gibt es eine Abkürzung:
„steht dort schon ein Partei-Name, bleibt er stehen".

Ein Leerstands-Bezug trägt als Partei aber genau die BEZEICHNUNG DER EINHEIT
(`bezuege` setzt `partei = e.bezeichnung`). Die Abkürzung griff deshalb bei
jedem Zähler, der auf die Einheit gepflegt ist, sobald diese Einheit auch nur
einen Tag leer stand — und schrieb den GANZEN Jahresverbrauch dem Leerstand
zu. Der Mieter, der das Wasser tatsächlich verbraucht hat, zahlte nichts,
der Eigentümer alles. Gemeldet wurde nichts (`offen` blieb leer).
"""
import os
import sys
import tempfile
from datetime import date

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(),
                                     "test_zaehler_leerstand.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.models import Einheit, Miete  # noqa: E402
from app.verteilung import auf_parteien, bezuege  # noqa: E402

START, ENDE = date(2025, 1, 1), date(2025, 12, 31)


def _welt(bis_datum):
    """EG (Meier, ggf. mit Auszug) und OG (Schmidt, ganzjährig)."""
    einheiten = [Einheit(id=1, objekt_id=1, bezeichnung="EG", flaeche=60.0),
                 Einheit(id=2, objekt_id=1, bezeichnung="OG", flaeche=90.0)]
    mieten = [
        Miete(id=1, objekt_id=1, einheit="EG", partei="Meier",
              ab_datum=date(2025, 1, 1), bis_datum=bis_datum),
        Miete(id=2, objekt_id=1, einheit="OG", partei="Schmidt",
              ab_datum=date(2025, 1, 1), bis_datum=None),
    ]
    return bezuege(einheiten, mieten, [], START, ENDE)


def test_teilweiser_leerstand_teilt_den_zaehler_mit_dem_mieter():
    """Meier wohnt ein halbes Jahr — er trägt rund die Hälfte des Zählers."""
    bez = _welt(bis_datum=date(2025, 6, 30))
    gewichte, offen = auf_parteien({"EG": 100.0, "OG": 200.0}, bez, START, ENDE)

    assert offen == []
    assert gewichte.get("Schmidt") == 200.0
    assert "Meier" in gewichte, \
        "der Mieter bekommt vom Zähler seiner Wohnung nichts ab"
    # Rund halbe/halbe — die exakte Aufteilung ist taggenau (181/365).
    assert 45.0 < gewichte["Meier"] < 55.0, gewichte
    assert 45.0 < gewichte["EG"] < 55.0, gewichte
    # Nichts geht verloren und nichts kommt dazu.
    assert round(gewichte["Meier"] + gewichte["EG"], 2) == 100.0


def test_ohne_leerstand_bleibt_es_beim_ganzen_zaehler():
    """Gegenprobe: durchgehend vermietet — der Mieter trägt alles."""
    bez = _welt(bis_datum=None)
    gewichte, offen = auf_parteien({"EG": 100.0, "OG": 200.0}, bez, START, ENDE)

    assert offen == []
    assert gewichte == {"Meier": 100.0, "Schmidt": 200.0}


def test_zaehler_auf_den_parteinamen_gepflegt_wirkt_weiter():
    """Die Abkürzung, um die es geht, muss erhalten bleiben: ein Zähler, der
    auf den MIETER gepflegt ist, wird weiterhin direkt zugeordnet."""
    bez = _welt(bis_datum=None)
    gewichte, offen = auf_parteien({"Meier": 70.0}, bez, START, ENDE)

    assert offen == []
    assert gewichte == {"Meier": 70.0}


def test_unbekanntes_label_wird_weiterhin_gemeldet():
    """Ein Zähler, der weder Einheit noch Partei trifft, darf nicht lautlos
    verschwinden."""
    bez = _welt(bis_datum=None)
    gewichte, offen = auf_parteien({"Dachboden": 5.0}, bez, START, ENDE)

    assert offen == ["Dachboden"]
    assert gewichte == {}
