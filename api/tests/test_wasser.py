"""N47 — Wasser-Verrechnung gegen die echten Excel-Zahlen (KostenSPLIT_2024)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.wasser import Zaehlerposten, verrechne  # noqa: E402


def test_kostensplit_2024_kontrollsumme():
    # Die drei Bestandteile der Wasserrechnung 2024.
    komponenten = {"wasser": 298.05, "schmutz": 362.56, "niederschlag": 186.91}
    gesamt_m3 = 142.5775425531915           # Hauptzähler-Differenz (J4)
    # Unterzähler mit Ziel-Einheit (Werte = Ablesung Ende − Anfang aus J-Spalte).
    zaehler = [
        Zaehlerposten("Büro Kaltwasser", "Büro", 4.139773049645385),
        Zaehlerposten("Studio Kaltwasser", "Studio 1.OG", 29.831631205673716),
        Zaehlerposten("Studio Waschmaschine", "Studio 1.OG", 8.785627659574459),
        Zaehlerposten("Studio Warmwasser", "Studio 1.OG", 5.684421985815604),
    ]
    garten_m3 = 15
    # Rest (Haupthaus EG + 1.OG) per Personen·Mietdauer — Beispiel 2:1.
    rest_gewichte = {"EG": 24, "1.OG": 12}

    e = verrechne(komponenten, gesamt_m3, zaehler, garten_m3, rest_gewichte)

    # Preis/m³ und Einzelposten wie in der Excel.
    assert round(e.preis_m3, 2) == 5.94
    kosten = {z["name"]: z["kosten"] for z in e.zaehler}
    assert kosten["Büro Kaltwasser"] == 24.61
    assert kosten["Studio Kaltwasser"] == 177.33
    assert kosten["Studio Waschmaschine"] == 52.22
    assert kosten["Studio Warmwasser"] == 33.79
    # Rest = Gesamt − Zähler − Garten (J14) → ~79,14 m³ → ~470,41 €
    assert round(e.rest_m3, 1) == 79.1
    assert e.rest_kosten == 470.41
    assert e.garten_kosten == 89.16
    # Kontrollsumme aller verteilten € (inkl. Garten/Eigentümer) = Gesamtkosten
    # (± 1 Cent Rundung beim Summieren gerundeter Einzelposten).
    assert abs(e.kontrolle - 847.52) <= 0.01
    # Studio bündelt seine drei Zähler.
    assert e.einheiten["Studio 1.OG"]["kosten"] == round(177.33 + 52.22 + 33.79, 2)


def test_rest_split_2_zu_1():
    komponenten = {"wasser": 100.0, "schmutz": 0.0, "niederschlag": 0.0}
    e = verrechne(komponenten, 100.0, [], 0, {"EG": 2, "1.OG": 1})
    # Kein Zähler, kein Garten → alles ist Rest, 2:1 verteilt.
    assert e.rest_kosten == 100.0
    assert e.einheiten["EG"]["kosten"] == round(100 * 2 / 3, 2)
    assert e.einheiten["1.OG"]["kosten"] == round(100 * 1 / 3, 2)


def test_mehrfach_einheiten_split_nach_person_mietdauer():
    """CD — ein Zähler (Boiler-Zulauf) für EG+1.OG teilt m³ UND Kosten über
    seine beiden Einheiten nach Person·Mietdauer (rest_gewichte 2:1)."""
    komponenten = {"wasser": 100.0, "schmutz": 0.0, "niederschlag": 0.0}
    boiler = Zaehlerposten("Boiler-Zulauf", "", 30.0, art="Warmwasser",
                           einheiten=["EG", "1.OG"])
    # Gesamt so gewählt, dass es keinen Rest gibt: Gesamt == Zähler-m³.
    e = verrechne(komponenten, 30.0, [boiler], 0, {"EG": 2, "1.OG": 1})

    preis = 100.0 / 30.0
    # Der Posten erscheint bei BEIDER Einheit, anteilig 2:1.
    eg = e.einheiten["EG"]
    og = e.einheiten["1.OG"]
    assert eg["kosten"] == round(preis * 30.0 * 2 / 3, 2)
    assert og["kosten"] == round(preis * 30.0 * 1 / 3, 2)
    # m³ ebenfalls anteilig aufgeteilt.
    assert eg["posten"][0]["m3"] == round(30.0 * 2 / 3, 3)
    assert og["posten"][0]["m3"] == round(30.0 * 1 / 3, 3)
    # beide Zeilen tragen denselben Zähler als Quelle.
    assert eg["posten"][0]["quelle"] == "Zähler Boiler-Zulauf"
    assert og["posten"][0]["quelle"] == "Zähler Boiler-Zulauf"
    # Kontrollsumme bleibt exakt = Gesamtkosten.
    assert e.kontrolle == 100.0


def test_mehrfach_einheiten_ohne_gewichte_gleiche_teile():
    """CD — haben die Einheiten eines Mehrfach-Zählers keine Gewichte, wird zu
    gleichen Teilen aufgeteilt."""
    komponenten = {"wasser": 60.0, "schmutz": 0.0, "niederschlag": 0.0}
    boiler = Zaehlerposten("Boiler", "", 30.0, art="Warmwasser",
                           einheiten=["EG", "1.OG"])
    e = verrechne(komponenten, 30.0, [boiler], 0, {})
    assert e.einheiten["EG"]["kosten"] == 30.0
    assert e.einheiten["1.OG"]["kosten"] == 30.0
    assert e.kontrolle == 60.0


def test_einzel_einheit_fall_unveraendert():
    """CD — ein Zähler mit genau einer Einheit (egal ob über `einheit` oder
    `einheiten`) verhält sich wie bisher: alles auf diese eine Einheit."""
    komponenten = {"wasser": 50.0, "schmutz": 0.0, "niederschlag": 0.0}
    ueber_liste = Zaehlerposten("A", "", 10.0, einheiten=["Büro"])
    ueber_einzel = Zaehlerposten("B", "Büro", 15.0)
    e = verrechne(komponenten, 100.0, [ueber_liste, ueber_einzel], 0,
                  {"EG": 1})
    preis = 50.0 / 100.0
    # beide Posten landen komplett bei "Büro".
    quellen = {p["quelle"] for p in e.einheiten["Büro"]["posten"]}
    assert quellen == {"Zähler A", "Zähler B"}
    assert e.einheiten["Büro"]["kosten"] == round(preis * (10.0 + 15.0), 2)
    assert e.kontrolle == 50.0


def test_eigene_waschmaschine_je_einheit_on_top():
    # Korrektur: statt geteilter WG-Maschine je Einheit eine eigene, on top.
    komponenten = {"wasser": 594.43, "schmutz": 0.0, "niederschlag": 0.0}
    zaehler = [Zaehlerposten("WM EG", "EG", 5), Zaehlerposten("WM 1.OG", "1.OG", 3)]
    e = verrechne(komponenten, 100.0, zaehler, 0, {"EG": 1, "1.OG": 1})
    # EG zahlt seinen Rest-Anteil + eigene Waschmaschine.
    eg = e.einheiten["EG"]
    quellen = {p["quelle"] for p in eg["posten"]}
    assert any("WM EG" in q for q in quellen) and any("Haupthaus" in q for q in quellen)
    assert e.kontrolle == 594.43
