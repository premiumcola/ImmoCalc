"""Nichts außerhalb des Home-Ordners anfassen — der Riegel muss halten."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.nextcloud import AussenhalbHome, Nextcloud  # noqa: E402


def client(heimat="/[010]_Immobilien"):
    return Nextcloud("https://example.org", "roman", "geheim", heimat=heimat)


@pytest.mark.parametrize("pfad", [
    "/Fotos/Urlaub",                       # ganz woanders
    "Dokumente",                           # Nachbarordner
    "/[010]_ImmobilienXY/Trick",           # Präfix, aber anderer Ordner
    "/[010]_Immobilien/../Privat",         # Ausbruch über ..
    "",                                    # Wurzel des Benutzers
])
def test_schreiben_ausserhalb_wird_abgelehnt(pfad):
    c = client()
    with pytest.raises(AussenhalbHome):
        c.ordner_anlegen(pfad)
    with pytest.raises(AussenhalbHome):
        c.lege_ab(pfad + "/datei.pdf" if pfad else "datei.pdf", b"x")


def test_verschieben_prueft_beide_seiten():
    c = client()
    # Ziel innerhalb, Quelle außerhalb
    with pytest.raises(AussenhalbHome):
        c.verschiebe("/Privat/geheim.pdf", "/[010]_Immobilien/A/geheim.pdf")
    # Quelle innerhalb, Ziel außerhalb
    with pytest.raises(AussenhalbHome):
        c.verschiebe("/[010]_Immobilien/A/x.pdf", "/Privat/x.pdf")


def test_ohne_home_wird_gar_nicht_geschrieben():
    """Solange kein Ordner gewählt ist, bleibt alles unangetastet."""
    c = client(heimat="")
    with pytest.raises(AussenhalbHome):
        c.ordner_anlegen("/[010]_Immobilien/Neu")


@pytest.mark.parametrize("pfad", [
    "/[010]_Immobilien",                              # der Ordner selbst
    "/[010]_Immobilien/Eschenau - Laufer Str. 5",     # Objektordner
    "[010]_Immobilien/A/60_Nebenkosten/beleg.pdf",    # ohne führenden Schrägstrich
])
def test_innerhalb_geht_durch(pfad):
    """Erlaubte Pfade dürfen nicht am Riegel scheitern (kein Netzzugriff)."""
    client()._pruefe_schreibrecht(pfad)     # wirft nicht
