"""N70 — kanonischer Immobilientitel; N71 — leere Zeiträume tragen keine Frist.

N70: Objekte sollen überall unter ihrem offiziellen Titel „(Ort) Straße"
erscheinen, auch wenn im `name` versehentlich nur ein Einheitenname
(„Wohnung 1.OG") steht. Der Titel wird abgeleitet, `name` bleibt unangetastet.

N71: Ein frisch angelegtes Objekt bekommt einen leeren „in Arbeit"-Zeitraum.
Der darf auf der Startseiten-Kachel keine „X T über Frist" melden — erst eine
Kostenposition macht daraus eine echte laufende Abrechnung.
"""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_titel_und_frist.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from app.bezeichnung import objekt_titel  # noqa: E402
from app.main import app  # noqa: E402


def _kachel(c, slug: str) -> dict:
    return next(o for o in c.get("/api/objekte").json() if o["slug"] == slug)


# --------------------------------------------------------------------------
# N70 — der Helfer selbst
# --------------------------------------------------------------------------

def _obj(**kw):
    basis = dict(name="", ort="", strasse="", plz="", typ="lg-mfhA",
                 gemarkung="", flurstueck="", grundstueck_nutzungsart="")
    basis.update(kw)
    return SimpleNamespace(**basis)


def test_objekt_titel_gebaeude_zeigt_ort_und_strasse():
    # Einheitenname im `name` — der Titel folgt trotzdem der Adresse.
    o = _obj(name="Wohnung 1.OG", ort="Unterschöllenbach",
             strasse="Hauptstr. 6a", plz="90542")
    assert objekt_titel(o) == "(Unterschöllenbach) Hauptstr. 6a"


def test_objekt_titel_uebernimmt_korrekten_namen():
    o = _obj(name="(Eschenau) Laufer Str. 5", ort="Eschenau",
             strasse="Laufer Str. 5", plz="90542")
    assert objekt_titel(o) == "(Eschenau) Laufer Str. 5"


def test_objekt_titel_grundstueck_ohne_strasse():
    o = _obj(name="Eckenhaid", ort="Eckenhaid", typ="lg-grundstueck",
             flurstueck="619")
    assert objekt_titel(o) == "Eckenhaid · Grundstück · Flurstück 619"


def test_objekt_titel_faellt_auf_namen_zurueck():
    assert objekt_titel(_obj(name="Nur ein Name")) == "Nur ein Name"


# --------------------------------------------------------------------------
# N70 — der Titel kommt aus den Serialisierungen (Liste + Detail)
# --------------------------------------------------------------------------

def test_liste_und_detail_liefern_den_titel():
    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={
            "name": "Wohnung 1.OG", "ort": "Unterschöllenbach",
            "strasse": "Hauptstr. 6a", "plz": "90542"}).json()["slug"]

        kachel = _kachel(c, slug)
        assert kachel["titel"] == "(Unterschöllenbach) Hauptstr. 6a"
        assert kachel["name"] == "Wohnung 1.OG"      # `name` bleibt unangetastet

        objekt = c.get(f"/api/objekte/{slug}").json()["objekt"]
        assert objekt["titel"] == "(Unterschöllenbach) Hauptstr. 6a"
        assert objekt["name"] == "Wohnung 1.OG"


# --------------------------------------------------------------------------
# N71 — leerer Zeitraum -> keine Kachel-Frist; mit Position -> Frist
# --------------------------------------------------------------------------

def test_leerer_zeitraum_traegt_keine_kachelfrist():
    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={
            "name": "(Prüfstadt) Fristweg 1", "ort": "Prüfstadt",
            "strasse": "Fristweg 1", "kostenarten": ["Heizkosten"]}
        ).json()["slug"]

        # Frisch angelegt: genau ein leerer „in Arbeit"-Zeitraum, 0 Positionen.
        assert _kachel(c, slug)["frist_tage"] is None

        # Sobald eine Kostenposition daranhängt, ist es eine echte Abrechnung.
        zid = c.get(f"/api/objekte/{slug}").json()["zeitraeume"][0]["id"]
        c.post(f"/api/zeitraeume/{zid}/positionen",
               json={"kostenart": "Heizkosten", "betrag": 100.0,
                     "status": "erledigt"})
        assert _kachel(c, slug)["frist_tage"] is not None
