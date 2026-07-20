"""Ordnernamen von grob nach fein — inklusive Vorlagen."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.bezeichnung import (STANDARD_VORLAGE, anzeigename,  # noqa: E402
                             nach_vorlage, ordnername, vorlage_pruefen)


def test_anzeigename_von_grob_nach_fein():
    assert anzeigename("Wohnung 1. OG", ort="Unterschöllenbach",
                       strasse="Hauptstr. 6a") \
        == "Unterschöllenbach · Hauptstr. 6a · Wohnung 1. OG"


def test_keine_doppelungen():
    """Steht der Ort schon in der Bezeichnung, nicht zweimal nennen."""
    assert anzeigename("Eschenau - Laufer Str. 5", ort="Eschenau") \
        == "Eschenau - Laufer Str. 5"


def test_ordnername_folgt_dem_bestand():
    assert ordnername("Wohnung 1. OG", ort="Eschenau", strasse="Laufer Str. 5") \
        == "Eschenau - Laufer Str. 5 - Wohnung 1. OG"


def test_vorlage_mit_klammern():
    ergebnis = nach_vorlage("({ort}) {strasse} · {name}",
                            ort="Unterschöllenbach", strasse="Hauptstr. 6a",
                            name="Wohnung 1. OG")
    assert ergebnis == "(Unterschöllenbach) Hauptstr. 6a · Wohnung 1. OG"


def test_prozent_schreibweise():
    """Die Kurzform %ort funktioniert genauso wie {ort}."""
    assert nach_vorlage("(%ORT) %strasse", ort="Nürnberg",
                        strasse="Klausner Winkel 12") \
        == "(Nürnberg) Klausner Winkel 12"


def test_schraegstrich_wird_entfernt():
    """// wäre ein Pfadtrenner und darf nie im Ordnernamen landen."""
    ergebnis = nach_vorlage("({ort}) {strasse} // {name}", ort="Eschenau",
                            strasse="Laufer Str. 5", name="Wohnung 1. OG")
    assert "/" not in ergebnis
    assert ergebnis.startswith("(Eschenau) Laufer Str. 5")
    assert ergebnis.endswith("Wohnung 1. OG")


def test_leere_felder_lassen_keine_reste():
    """Ohne Ort darf kein leeres Klammerpaar stehenbleiben."""
    assert nach_vorlage(STANDARD_VORLAGE, ort="", strasse="Hauptstr. 6a",
                        name="Wohnung 1. OG") == "Hauptstr. 6a · Wohnung 1. OG"
    assert nach_vorlage(STANDARD_VORLAGE, ort="", strasse="", name="Garage") \
        == "Garage"


def test_vorlage_pruefen_meldet_probleme():
    assert vorlage_pruefen("") == ["Die Vorlage ist leer."]
    assert any("Platzhalter" in h for h in vorlage_pruefen("Immobilie"))
    assert any("nicht erlaubt" in h for h in vorlage_pruefen("{ort}/{name}"))
    assert any("Unbekannte" in h for h in vorlage_pruefen("{quatsch} {ort}"))
    assert vorlage_pruefen(STANDARD_VORLAGE) == []
