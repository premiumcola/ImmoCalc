"""N492 — die Fundstellen: wo auf dem Blatt eine erkannte Angabe steht.

Der Teil, der Tesseract braucht (`_worte`), ist hier ausgetauscht — geprüft
wird die Zuordnung: aus gemessenen Wortkästen und den Werten der Auslese
werden die Markierungen. Genau dort sitzt die Fachlogik, und genau dort
entstehen die Fehler, die der Nutzer sähe: ein Kasten um das falsche Wort ist
schlimmer als gar keiner, weil er eine Genauigkeit behauptet, die er nicht hat.
"""
from __future__ import annotations

import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_fundstellen.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest  # noqa: E402

from app import fundstellen  # noqa: E402

BREITE, HOEHE = 1000, 1400


def _wort(text, x, y, b=80, h=24, zeile=1):
    return {"text": text, "x": x, "y": y, "b": b, "h": h,
            "zeile": (1, 1, zeile)}


# Ein Blatt, wie es die Kamera liefert: drei Zeilen, ein Betrag, ein Datum.
BLATT = [
    _wort("Kommunale", 100, 100, zeile=1),
    _wort("Abfallwirtschaft", 200, 100, b=210, zeile=1),
    _wort("Tauchersreuther", 100, 300, b=200, zeile=2),
    _wort("Str.", 310, 300, b=45, zeile=2),
    _wort("7,", 360, 300, b=25, zeile=2),
    _wort("90542", 390, 300, b=90, zeile=2),
    _wort("Eckental-Eschenau", 485, 300, b=230, zeile=2),
    _wort("Rechnungsbetrag", 100, 600, b=210, zeile=3),
    _wort("348,00", 320, 600, b=95, zeile=3),
    _wort("EUR", 420, 600, b=55, zeile=3),
    _wort("12.03.2026", 700, 600, b=140, zeile=3),
]


@pytest.fixture
def blatt(monkeypatch):
    """Tesseract durch ein festes Messergebnis ersetzen."""
    def messen(_rohdaten):
        return BLATT, BREITE, HOEHE
    monkeypatch.setattr(fundstellen, "_worte", messen)


def _nach_art(funde):
    return {f["art"]: f for f in funde}


# ---- N492 — die Zuordnung ---------------------------------------------

def test_ein_betrag_wird_auf_dem_blatt_gefunden(blatt):
    funde = fundstellen.finde(b"x", [{"art": "betrag", "wert": "348,00 €"}])
    assert len(funde) == 1
    f = funde[0]
    # Der Kasten sitzt auf „348,00" — relativ zur Bildgrösse.
    assert f["x"] == pytest.approx(320 / BREITE, abs=1e-4)
    assert f["y"] == pytest.approx(600 / HOEHE, abs=1e-4)
    assert 0 < f["b"] < 1 and 0 < f["h"] < 1


def test_das_eurozeichen_stoert_die_zuordnung_nicht(blatt):
    """Auf dem Blatt steht „EUR", in der Auslese „€" — und Tesseract
    verschluckt Sonderzeichen gern ganz. Verglichen wird deshalb nur, was
    Buchstabe oder Ziffer ist."""
    assert fundstellen.finde(b"x", [{"art": "betrag", "wert": "348,00 €"}])
    assert fundstellen.finde(b"x", [{"art": "betrag", "wert": "348.00 EUR"}])


def test_ein_datum_wird_gefunden(blatt):
    funde = fundstellen.finde(b"x", [{"art": "datum", "wert": "12.03.2026"}])
    assert len(funde) == 1
    assert funde[0]["x"] == pytest.approx(700 / BREITE, abs=1e-4)


def test_eine_mehrwortige_adresse_ergibt_EINEN_kasten(blatt):
    """Die Immobilie steht über fünf Wörter verteilt. Der Kasten muss sie
    umschliessen, nicht nur das erste Wort treffen."""
    funde = fundstellen.finde(b"x", [
        {"art": "immobilie",
         "wert": "Tauchersreuther Str. 7, 90542 Eckental-Eschenau"}])
    assert len(funde) == 1
    f = funde[0]
    assert f["x"] == pytest.approx(100 / BREITE, abs=1e-4)
    # von x=100 bis x=715 (Ende des letzten Wortes)
    assert f["b"] == pytest.approx((715 - 100) / BREITE, abs=1e-3)


def test_ein_bindestrich_wort_trifft_ueber_seinen_bestandteil(blatt):
    """„Abfallwirtschaft-Anmeldung" steht so nicht auf dem Blatt —
    „Abfallwirtschaft" schon. Ohne die Zerlegung am Bindestrich bliebe die
    Sache unmarkiert (derselbe Fall wie im Erklärtext, N491)."""
    funde = fundstellen.finde(b"x", [
        {"art": "sache", "wert": "Abfallwirtschaft-Anmeldung"}])
    assert len(funde) == 1
    assert funde[0]["x"] == pytest.approx(200 / BREITE, abs=1e-4)


def test_eine_einordnung_ohne_entsprechung_bleibt_ohne_kasten(blatt):
    """„Sonstiges" ist eine Einordnung, kein Wort auf dem Blatt. Nichts zu
    finden ist hier der RICHTIGE Ausgang — ein Kasten irgendwo wäre eine
    Behauptung."""
    assert fundstellen.finde(b"x", [
        {"art": "kategorie", "wert": "Sonstiges"}]) == []


def test_zwei_angaben_bekommen_nie_denselben_kasten(blatt):
    """Sonst lägen zwei Farben übereinander und der Nutzer sähe nur die obere."""
    funde = fundstellen.finde(b"x", [
        {"art": "betrag", "wert": "348,00 €"},
        {"art": "feld", "wert": "348,00"},
    ])
    kaesten = {(f["x"], f["y"], f["b"], f["h"]) for f in funde}
    assert len(kaesten) == len(funde)


def test_ein_kasten_umspannt_nie_zwei_zeilen(blatt):
    """„Abfallwirtschaft Tauchersreuther" stünde quer über zwei Zeilen. Als
    GANZES darf das nie einen Kasten ergeben — der wäre ein halbes Blatt.

    Dass trotzdem etwas gefunden wird, ist richtig und kein Nebeneffekt: die
    Suche fällt auf die Bestandteile zurück, und „Abfallwirtschaft" steht
    wirklich dort. Genau dieser Rückfall lässt auch „Abfallwirtschaft-
    Anmeldung" treffen. Geprüft wird deshalb die HÖHE des Kastens: eine
    Zeile, nicht zwei."""
    funde = fundstellen.finde(b"x", [
        {"art": "feld", "wert": "Abfallwirtschaft Tauchersreuther"}])
    assert len(funde) == 1
    f = funde[0]
    zeilenhoehe = 24 / HOEHE
    assert f["h"] == pytest.approx(zeilenhoehe, abs=1e-4), (
        "der Kasten reicht über die Zeile hinaus")
    assert f["y"] == pytest.approx(100 / HOEHE, abs=1e-4)


def test_alle_kaesten_liegen_im_bild(blatt):
    funde = fundstellen.finde(b"x", [
        {"art": "betrag", "wert": "348,00 €"},
        {"art": "datum", "wert": "12.03.2026"},
        {"art": "immobilie", "wert": "Tauchersreuther Str. 7, 90542 Eckental-Eschenau"},
    ])
    assert len(funde) == 3
    for f in funde:
        assert 0 <= f["x"] and f["x"] + f["b"] <= 1.0001
        assert 0 <= f["y"] and f["y"] + f["h"] <= 1.0001


# ---- N492 — die Markierung darf nie etwas aufhalten -------------------

def test_ohne_tesseract_kommt_einfach_nichts(monkeypatch):
    monkeypatch.setattr(fundstellen, "verfuegbar", lambda: False)
    assert fundstellen.finde(b"x", [{"art": "betrag", "wert": "348,00 €"}]) == []


def test_ein_leeres_messergebnis_ergibt_keine_funde(monkeypatch):
    monkeypatch.setattr(fundstellen, "_worte", lambda _r: ([], 0, 0))
    assert fundstellen.finde(b"x", [{"art": "betrag", "wert": "1,00"}]) == []


def test_ohne_werte_wird_gar_nicht_erst_gemessen(monkeypatch):
    def nie(_r):
        raise AssertionError("es sollte gar nicht gemessen werden")
    monkeypatch.setattr(fundstellen, "_worte", nie)
    assert fundstellen.finde(b"x", []) == []


def test_zu_kurze_werte_werden_nicht_gesucht(blatt):
    """Eine Nadel aus zwei Zeichen träfe irgendwo — „7" steht auf jedem Blatt."""
    assert fundstellen.finde(b"x", [{"art": "feld", "wert": "7"}]) == []


# ---- N492 — die Vergleichsform ----------------------------------------

def test_der_kern_wirft_alle_trennzeichen_weg():
    assert fundstellen._kern("348,00 €") == "34800"
    assert fundstellen._kern("348.00 EUR") == "34800eur"
    assert fundstellen._kern("Eckental-Eschenau") == "eckentaleschenau"


def test_die_nadeln_stehen_von_lang_nach_kurz():
    nadeln = fundstellen._nadeln("Tauchersreuther Str. 7, 90542 Eckental-Eschenau")
    assert nadeln[0] == "Tauchersreuther Str. 7, 90542 Eckental-Eschenau"
    laengen = [len(n) for n in nadeln[1:]]
    assert laengen == sorted(laengen, reverse=True)
