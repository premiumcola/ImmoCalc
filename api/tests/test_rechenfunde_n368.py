"""N368 — drei Rechenfehler, die Geld lautlos verschoben haben.

Alle drei teilen dasselbe Muster: sie halten eine Invariante scheinbar ein
(die Summe stimmt, kein Fehler fliegt), verteilen dahinter aber falsch. Genau
deshalb sind sie nie aufgefallen — und deshalb prüft jeder Test hier nicht nur
das Ergebnis, sondern dass die Summe auch wirklich dort ankommt, wo sie hin
soll.
"""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_n368.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import cashflow, heizoel, waermesim  # noqa: E402


# --------------------------------------------------------------------------
# 1) Heizöl: eine Lieferung ohne Litermenge belastete die Periode voll
# --------------------------------------------------------------------------

def test_lieferung_ohne_liter_belastet_den_verbrauch_nicht():
    """Der FIFO-Lauf übersprang sie, `gesamt_wert` nicht — ihr voller Betrag
    landete über `verbrauch = gesamt − rest` in den Verbrauchskosten.

    Typischer Auslöser: die Rechnung ist erfasst, die Litermenge noch nicht
    nachgetragen. Das Modell erlaubt das ausdrücklich (`liter: float = 0.0`).
    """
    lieferungen = [{"datum": "2024-01-10", "liter": 3000.0, "wert": 2100.0},
                   {"datum": "2024-02-10", "liter": 0.0, "wert": 900.0}]

    # Ohne Verbrauch darf gar nichts anfallen — vorher waren es 900 €.
    leer = heizoel.verbrauch_bewerten(lieferungen, 0.0)
    assert leer["verbrauch_kosten"] == 0.0, leer

    # Mit Verbrauch zählt nur das Öl, dessen Menge bekannt ist: 0,70 €/L.
    ergebnis = heizoel.verbrauch_bewerten(lieferungen, 1000.0)
    assert ergebnis["verbrauch_kosten"] == 700.0, ergebnis

    # Und der Nutzer erfährt, welcher Betrag noch nicht mitzählt.
    assert "900.00" in ergebnis["warnung"] or "900,00" in ergebnis["warnung"], \
        ergebnis["warnung"]


def test_vollstaendige_lieferungen_rechnen_unveraendert():
    """Der Wächter zum Fix: ohne unvollständige Lieferung ändert sich nichts."""
    lieferungen = [{"datum": "2024-01-10", "liter": 2000.0, "wert": 1400.0},
                   {"datum": "2024-06-10", "liter": 1000.0, "wert": 800.0}]
    ergebnis = heizoel.verbrauch_bewerten(lieferungen, 2500.0)
    # FIFO: 2000 L à 0,70 € + 500 L à 0,80 € = 1400 + 400
    assert ergebnis["verbrauch_kosten"] == 1800.0
    assert ergebnis["rest_wert"] == 400.0
    assert not ergebnis.get("warnung")


# --------------------------------------------------------------------------
# 2) Cashflow: gemischter Pflegestand der Wohnflächen
# --------------------------------------------------------------------------

class _Einheit:
    """Nur so viel, wie `cashflow.verteile` anfasst."""

    def __init__(self, flaeche):
        self.gesamtflaeche = flaeche


def test_fehlende_flaeche_zieht_nicht_alle_kosten_auf_die_gepflegte_einheit():
    """`gesamtflaeche` gibt bewusst `None` zurück, solange die Angabe fehlt.

    Ein `or 0.0` machte daraus ein Gewicht von null: bei EG 60 m² und OG noch
    ohne Angabe trug das EG sämtliche Objektkosten und das OG gar keine — der
    Jahressaldo beider Einheiten war falsch, ohne dass irgendwo etwas fehlte.
    """
    gemischt = cashflow.verteile(1200.0, [_Einheit(60.0), _Einheit(None)])
    assert gemischt == [600.0, 600.0], gemischt

    # Sind alle Flächen bekannt, wird weiter nach Fläche verteilt.
    bekannt = cashflow.verteile(1200.0, [_Einheit(60.0), _Einheit(180.0)])
    assert bekannt == [300.0, 900.0], bekannt

    # Und ohne jede Fläche bleibt es bei gleichen Teilen (unverändert).
    ohne = cashflow.verteile(1200.0, [_Einheit(None), _Einheit(None)])
    assert ohne == [600.0, 600.0], ohne


# --------------------------------------------------------------------------
# 3) Wärmesimulator: gleichnamige Nutzerzeilen
# --------------------------------------------------------------------------

def test_gleichnamige_nutzer_bekommen_nicht_beide_den_ganzen_topf():
    """Die Töpfe bündelten nach Name, die Zeilen lasen positionsweise aus.

    Zwei Zeilen gleichen Namens bekamen darum jeweils den zusammengelegten
    Betrag — die Zeilensumme überschritt die eingesetzten Liter und Euro, und
    die im Docstring von `rechne` zugesicherte Invariante war gebrochen.
    """
    eingabe = {
        "heizwert": 10.0,
        "bestaende": [{"datum": "2024-10-01", "liter": 1000.0, "eur": 1000.0}],
        "rest": {"datum": "2025-09-30", "liter": 0.0, "eur": 0.0},
        "ww_m3": 0.0,
        "fest_anteil": 0.30,
        "h2_anteil": 0.0,
        "nutzer": [
            {"name": "Meier", "ehkv": 100.0, "flaeche": 50.0},
            {"name": "Meier", "ehkv": 100.0, "flaeche": 50.0},
            {"name": "Schulz", "ehkv": 200.0, "flaeche": 100.0},
        ],
    }
    ergebnis = waermesim.rechne(eingabe)
    zeilen = ergebnis["nutzer"]
    assert len(zeilen) == 3

    summe_kosten = round(sum(z["summe"] for z in zeilen), 2)
    summe_liter = round(sum(z["liter"] + z["liter_warmwasser"] for z in zeilen), 1)
    assert abs(summe_kosten - 1000.0) < 0.05, [z["summe"] for z in zeilen]
    assert abs(summe_liter - 1000.0) < 0.5, [z["liter"] for z in zeilen]

    # Die beiden gleichnamigen tragen zusammen so viel wie der eine Schulz.
    meier = round(sum(z["summe"] for z in zeilen if z["name"] == "Meier"), 2)
    schulz = round(sum(z["summe"] for z in zeilen if z["name"] == "Schulz"), 2)
    assert abs(meier - schulz) < 0.05, (meier, schulz)
