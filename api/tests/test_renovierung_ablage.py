"""N289 — Renovierungsrechnungen liegen im Projektordner des Bauvorhabens.

Vorher fiel die Kategorie „Renovierung" durch `ZIELORDNER.get(…, "99_Sonstiges")`
und alle Handwerkerrechnungen landeten zwischen allem anderen unter Sonstiges.
Jetzt: „50_Renovierung_Instandsetzung/2025.01_Generalsanierung" — der Ordner
heisst seit N332 so, vorher „50_Bauphase_Projekte".
"""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(),
                                     "test_renovierung_ablage.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.bezeichnung import STANDARD_UNTERORDNER  # noqa: E402
from app.cloudkern import ARTKUERZEL, STRUKTUR, ZIELORDNER  # noqa: E402
from app.renovierung import projektordner  # noqa: E402


# --------------------------------------------------------------------------
# Der Ordnername
# --------------------------------------------------------------------------

def test_projektordner_stellt_jahr_und_monat_voran():
    assert projektordner("Generalsanierung", "2025-01-15") == \
        "2025.01_Generalsanierung"
    assert projektordner("Bad EG", "2026-11-01") == "2026.11_Bad EG"


def test_projektordner_nimmt_auch_ein_date():
    """Aus der Datenbank kommt `von` als `date`, aus dem Formular als Text."""
    from datetime import date
    assert projektordner("Generalsanierung", date(2025, 1, 15)) == \
        "2025.01_Generalsanierung"


def test_projektordner_ohne_startdatum_ist_der_blosse_name():
    """Ein Ordner „ohne-Datum_…" hülfe beim Wiederfinden niemandem."""
    assert projektordner("Generalsanierung") == "Generalsanierung"
    assert projektordner("Generalsanierung", "") == "Generalsanierung"
    assert projektordner("Generalsanierung", None) == "Generalsanierung"
    # Ein abgeschnittenes Datum ergibt keinen halben Präfix
    assert projektordner("Generalsanierung", "2025") == "Generalsanierung"


def test_projektordner_bleibt_eine_ebene():
    """Ein Schrägstrich im Namen legte sonst ungefragt einen Baum an."""
    ordner = projektordner("Bad / Küche", "2025-03-02")
    assert "/" not in ordner
    assert ordner == "2025.03_Bad Küche"
    for zeichen in '\\:*?"<>|':
        assert zeichen not in projektordner(f"A{zeichen}B", "2025-03-02")


def test_projektordner_ohne_namen_ist_leer():
    """Leer heisst: kein Unterordner — die Rechnung bleibt im Sachordner,
    statt in einem Ordner ohne Namen zu verschwinden."""
    assert projektordner("") == ""
    assert projektordner("   ") == ""
    assert projektordner("...", "2025-01-01") == ""


# --------------------------------------------------------------------------
# Die Zuordnung
# --------------------------------------------------------------------------

def test_renovierung_zielt_auf_die_instandsetzung_nicht_auf_sonstiges():
    """N332 — der Zielordner heisst jetzt „50_Renovierung_Instandsetzung";
    „50_Bauphase_Projekte" ist nur noch Altbestand."""
    assert ZIELORDNER["Renovierung"] == "50_Renovierung_Instandsetzung"
    assert ZIELORDNER["Renovierung"] in STRUKTUR
    assert ARTKUERZEL["Renovierung"] == ""          # Name ist schon sprechend
    # Kein Jahresordner: der Projektordner tritt an seine Stelle (N285).
    assert STANDARD_UNTERORDNER["Renovierung"] == ""


def test_projektordner_schlaegt_die_vorlage():
    """`_ablageordner` nimmt den mitgegebenen Ordner, ohne ihn mit einem
    Jahresordner zu verwechseln — „2025.01_Generalsanierung" beginnt mit einer
    Jahreszahl und liefe sonst in `unterordner_finden`."""
    from app.routers.dokumente import _ablageordner

    class _Objekt:
        nc_ordner = "/Immobilien/Testweg 1"

    class _Client:
        def liste(self, ordner):                      # pragma: no cover
            raise AssertionError("Bei gesetztem Projektordner wird nicht "
                                 "in der Cloud nachgesehen")

    sach, ziel = _ablageordner(None, _Objekt(), "Renovierung", 2025, _Client(),
                               "2025.01_Generalsanierung")
    assert sach == "Immobilien/Testweg 1/50_Renovierung_Instandsetzung"
    assert ziel == sach + "/2025.01_Generalsanierung"


# --------------------------------------------------------------------------
# Bestandsrechnungen nachträglich einsortieren
# --------------------------------------------------------------------------

def test_einsortieren_meldet_saubere_fehler_statt_500():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        # Unbekannte Renovierung → 404, nicht 500
        assert c.post(
            "/api/dokumente/renovierungen/999999/einsortieren").status_code == 404

        slug = c.post("/api/objekte", json={"name": "Bauweg 1", "einheiten": [
            {"bezeichnung": "EG", "flaeche": 50}]}).json()["slug"]
        rid = c.post(f"/api/objekte/{slug}/renovierungen",
                     json={"name": "Generalsanierung",
                           "von": "2025-01-15"}).json()["id"]
        # Ohne Cloud-Ordner am Objekt: klare Auskunft, kein Absturz — und vor
        # allem kein halber Umzug in der Cloud.
        antwort = c.post(f"/api/dokumente/renovierungen/{rid}/einsortieren")
        assert antwort.status_code == 400
        assert "Cloud-Ordner" in antwort.json()["detail"]
