"""Ein geleertes Formularfeld darf nichts kaputt machen.

Die Oberfläche schickt für ein geleertes Feld `null`. Bei einem
`Optional`-Feld heisst das „nicht erfasst", bei einem Pflichtfeld mit
Vorgabewert heisst es „zurück auf null" — nie einen Serverfehler.
"""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_felder.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402

from app.felder import bereinige, darf_leer_sein, vorgabe_fuer  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Miete, Objekt  # noqa: E402


def test_optional_und_pflicht_werden_unterschieden():
    assert darf_leer_sein(Miete, "bis_datum") is True      # Optional[date]
    assert darf_leer_sein(Miete, "kaution") is True        # Optional[float]
    assert darf_leer_sein(Miete, "stellplatz") is False    # float = 0.0
    assert darf_leer_sein(Miete, "notiz") is False         # str = ""
    assert darf_leer_sein(Objekt, "flaeche") is True
    assert darf_leer_sein(Objekt, "iban") is False
    # Grundstück: Zahlen dürfen wirklich leer bleiben, Texte werden ""
    assert darf_leer_sein(Objekt, "grundstueck_flaeche") is True
    assert darf_leer_sein(Objekt, "grundsteuer_messbetrag") is True
    assert darf_leer_sein(Objekt, "grundstueck_nutzungsart") is False


def test_vorgabe_ist_die_leere_form_des_typs():
    assert vorgabe_fuer(Miete, "stellplatz") == 0.0
    assert vorgabe_fuer(Miete, "notiz") == ""
    assert vorgabe_fuer(Miete, "personen") == 1          # eigener Vorgabewert


def test_bereinige_laesst_optional_felder_leer():
    sauber = bereinige(Miete, {"bis_datum": None, "kaution": None,
                               "stellplatz": None, "notiz": None})
    assert sauber["bis_datum"] is None
    assert sauber["kaution"] is None
    assert sauber["stellplatz"] == 0.0
    assert sauber["notiz"] == ""


def _objekt(c):
    return c.post("/api/objekte", json={
        "name": "Leerweg 1", "ort": "Prüfstadt", "strasse": "Leerweg 1",
        "flaeche": 200.0, "kaufpreis": 300000.0}).json()["slug"]


def test_stellplatzmiete_laesst_sich_wieder_entfernen():
    """Der Fall aus der Oberfläche: Feld leeren und speichern."""
    with TestClient(app) as c:
        slug = _objekt(c)
        mid = c.post(f"/api/objekte/{slug}/mieten", json={
            "partei": "Mieter A", "kaltmiete": 800.0, "stellplatz": 40.0,
            "kaution": 2400.0, "ab_datum": "2024-01-01",
            "bis_datum": "2025-12-31"}).json()["id"]

        antwort = c.patch(f"/api/mieten/{mid}", json={
            "stellplatz": None, "kaution": None, "bis_datum": None,
            "notiz": ""})
        assert antwort.status_code == 200

        eintrag = c.get(f"/api/objekte/{slug}/mieten").json()[0]
        assert eintrag["stellplatz"] == 0.0      # Pflichtfeld -> Vorgabewert
        assert eintrag["kaution"] is None        # Optional -> wirklich leer
        assert eintrag["bis_datum"] is None      # laeuft wieder
        assert eintrag["kaltmiete"] == 800.0     # unberuehrt


def test_objekt_stammdaten_lassen_sich_leeren():
    with TestClient(app) as c:
        slug = _objekt(c)
        antwort = c.patch(f"/api/objekte/{slug}", json={
            "flaeche": None, "kaufpreis": None, "kaufdatum": None,
            "iban": None, "plz": ""})
        assert antwort.status_code == 200

        o = c.get(f"/api/objekte/{slug}").json()["objekt"]
        assert o["flaeche"] is None
        assert o["kaufpreis"] is None
        assert o["iban"] == ""                   # str-Pflichtfeld
        assert o["name"] == "Leerweg 1"          # unberuehrt


def test_grundstuecksangaben_lassen_sich_wieder_leeren():
    """Auch eine falsch eingetragene Fläche muss man wieder loswerden."""
    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={
            "name": "Leeracker", "typ": "lg-grundstueck"}).json()["slug"]
        c.patch(f"/api/objekte/{slug}", json={
            "grundstueck_flaeche": 4630.0, "grundstueck_nutzungsart": "Wald",
            "grundsteuer_hebesatz": 330.0})
        antwort = c.patch(f"/api/objekte/{slug}", json={
            "grundstueck_flaeche": None, "grundstueck_nutzungsart": None,
            "grundsteuer_hebesatz": None})
        assert antwort.status_code == 200

        o = c.get(f"/api/objekte/{slug}").json()["objekt"]
        assert o["grundstueck_flaeche"] is None          # Optional -> leer
        assert o["grundstueck_nutzungsart"] == ""        # str-Pflichtfeld
        assert o["grundsteuer_hebesatz"] is None


def test_auswertung_rechnet_nach_dem_leeren_weiter():
    """Ein geleertes Feld darf keine Folgefehler in der Auswertung erzeugen."""
    with TestClient(app) as c:
        slug = _objekt(c)
        mid = c.post(f"/api/objekte/{slug}/mieten", json={
            "partei": "Mieter B", "kaltmiete": 600.0, "stellplatz": 50.0,
            "ab_datum": "2024-01-01"}).json()["id"]
        c.patch(f"/api/mieten/{mid}", json={"stellplatz": None})

        assert c.get("/api/auswertung?jahr=2025").status_code == 200
        assert c.get("/api/vermoegen").status_code == 200


def test_kostenart_umlagefaehig_und_umbenennen():
    """CLX/CXC: die Kostenart war nirgends änderbar.

    `umlagefaehig` entscheidet, ob eine Position in der Mieterabrechnung
    landet oder beim Eigentümer bleibt — ohne Schreibweg galt faktisch alles
    als umlagefähig. Und der Name verbindet die Position mit dem Katalog:
    wird er nur im Katalog geändert, zeigt die Position ins Leere."""
    with TestClient(app) as c:
        slug = c.post("/api/objekte",
                      json={"name": "Katalogweg 2",
                            "kostenarten": ["Wasser", "Kamin"]}).json()["slug"]
        arten = c.get(f"/api/objekte/{slug}/kostenarten").json()
        wasser = next(a for a in arten if a["name"] == "Wasser")
        assert wasser["umlagefaehig"] is True

        zid = c.get(f"/api/objekte/{slug}").json()["zeitraeume"][0]["id"]
        c.post(f"/api/zeitraeume/{zid}/positionen", json={"kostenart": "Wasser"})

        aus = c.patch(f"/api/kostenarten/{wasser['id']}",
                      json={"umlagefaehig": False})
        assert aus.status_code == 200
        assert aus.json()["umlagefaehig"] is False

        um = c.patch(f"/api/kostenarten/{wasser['id']}",
                     json={"name": "Kaltwasser"})
        assert um.status_code == 200
        # die Position wandert mit, sonst zeigte sie auf einen toten Namen
        assert um.json()["positionen_nachgezogen"] == 1
        zeitraum = c.get(f"/api/zeitraeume/{zid}").json()
        namen = [p["kostenart"] for p in zeitraum["checkliste"]]
        assert "Kaltwasser" in namen and "Wasser" not in namen

        kamin = next(a for a in c.get(f"/api/objekte/{slug}/kostenarten").json()
                     if a["name"] == "Kamin")
        assert c.patch(f"/api/kostenarten/{kamin['id']}",
                       json={"name": "Kaltwasser"}).status_code == 409
        assert c.patch(f"/api/kostenarten/{kamin['id']}",
                       json={"name": "  "}).status_code == 400
