"""Adressen, die beim Kopieren aus dem Browser entstehen, müssen greifen."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.nextcloud import normalisiere_url  # noqa: E402


def test_login_pfad_wird_entfernt():
    """Der Praxisfall: aus der Adresszeile kopiert, endet auf /login -> 405."""
    assert normalisiere_url("https://192.168.178.10:444/login") \
        == "https://192.168.178.10:444"


def test_weitere_anhaengsel():
    for eingabe in [
        "https://host.de/index.php/apps/files",
        "https://host.de/apps/files/files/150885?dir=/x",
        "https://host.de/settings/user/security",
        "https://host.de/remote.php/dav/files/roman",
        "https://host.de/",
    ]:
        assert normalisiere_url(eingabe) == "https://host.de", eingabe


def test_unterverzeichnis_bleibt_erhalten():
    """Nextcloud darf in einem Unterordner liegen — den nicht wegwerfen."""
    assert normalisiere_url("https://host.de/nextcloud/login") \
        == "https://host.de/nextcloud"
    assert normalisiere_url("https://host.de/nextcloud") \
        == "https://host.de/nextcloud"


def test_fehlendes_schema_wird_ergaenzt():
    assert normalisiere_url("192.168.178.10:444") == "https://192.168.178.10:444"


def test_leere_eingabe():
    assert normalisiere_url("") == ""
    assert normalisiere_url(None) == ""
