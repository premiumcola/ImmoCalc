"""N436 (Häppchen 9) — die eigentliche Abnahme der Mandantentrennung.

Alle übrigen ~1700 Tests laufen über den `conftest.py`-Override, der jede
Anfrage als Bestandsfamilie „Heidenreich" durchgehen lässt. Hier nicht: der
Override wird entfernt, es melden sich ZWEI echte Familien mit eigenem Cookie
an, und geprüft wird, dass Familie B an die Daten von Familie A nicht
herankommt — weder lesend noch ändernd noch löschend.

**Warum jeder Fall ein PAAR ist (Eigentümer 2xx / Fremde 404):** ein Test, der
nur „B bekommt 404" prüft, geht auch dann durch, wenn der Pfad schlicht falsch
geschrieben ist — dann kommt der 404 vom Router und nicht von der
Besitzprüfung, und der Test bewacht nichts. Deshalb muss in jedem Fall zuerst
A auf demselben Pfad Erfolg haben. Erst dieses Paar beweist die Trennung.

404 statt 403 ist Absicht (siehe `deps.pruefe_familienbesitz`): ein fremder
Datensatz soll sich nicht von einem nicht existierenden unterscheiden lassen,
sonst verrät die Antwort, dass es die ID bei jemand anderem gibt.
"""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(),
                                     "test_mandantentrennung.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.deps import aktuelle_familie  # noqa: E402
from app.main import app  # noqa: E402


# Lesende und ändernde Zugriffe auf einen fremden Datensatz. `{...}` wird aus
# dem Bestand der Familie A gefüllt (siehe `welt`). Je Eintrag:
# (Name, Methode, Pfadmuster, Rumpf oder None).
FAELLE = [
    ("Objekt lesen", "GET", "/api/objekte/{slug}", None),
    ("Objekt ändern", "PATCH", "/api/objekte/{slug}", {"ort": "Woanders"}),
    ("Mietliste des Objekts", "GET", "/api/objekte/{slug}/mieten", None),
    ("Kostenarten des Objekts", "GET", "/api/objekte/{slug}/kostenarten", None),
    ("Kostenart anlegen", "POST", "/api/objekte/{slug}/kostenarten",
     {"name": "Fremdanlage"}),
    ("Einheiten des Objekts", "GET", "/api/objekte/{slug}/einheiten", None),
    ("Zähler des Objekts", "GET", "/api/objekte/{slug}/zaehler", None),
    ("Anteile des Objekts", "GET", "/api/objekte/{slug}/anteile", None),
    ("PV-Stammdaten", "GET", "/api/objekte/{slug}/pv/stammdaten", None),
    ("E-Tankstelle: Nutzer", "GET", "/api/tankstelle/{slug}/nutzer", None),
    ("Zeitraum lesen", "GET", "/api/zeitraeume/{zid}", None),
    ("Zeitraum ändern", "PATCH", "/api/zeitraeume/{zid}", {"notiz": "fremd"}),
    # Der Fänger mit dem höchsten Einzelrisiko: er holt die Zeile über einen
    # dynamisch gewählten Tabellennamen und hatte vor N436 gar keine Prüfung.
    ("Stammdaten-Fänger: Miete ändern", "PATCH",
     "/api/stammdaten/mieten/{miete}", {"kaltmiete": 999}),
    ("Einheit ändern", "PATCH", "/api/einheiten/{einheit}",
     {"bezeichnung": "Fremd"}),
]

# Löschende Zugriffe stehen getrennt: hier wird NUR die fremde Anfrage
# geschickt (404 erwartet) und danach geprüft, dass die Zeile noch da ist —
# den Eigentümer-Zweig mitlaufen zu lassen würde den Bestand zerstören, den
# die übrigen Fälle noch brauchen.
LOESCHFAELLE = [
    ("Objekt löschen", "/api/objekte/{slug}", "/api/objekte/{slug}"),
    ("Stammdaten-Fänger: Miete löschen", "/api/stammdaten/mieten/{miete}",
     "/api/objekte/{slug}/mieten"),
    ("Zeitraum löschen", "/api/zeitraeume/{zid}", "/api/zeitraeume/{zid}"),
    ("Einheit löschen", "/api/einheiten/{einheit}",
     "/api/objekte/{slug}/einheiten"),
]


@pytest.fixture(scope="module")
def welt():
    """Zwei angemeldete Familien; A legt einen vollständigen Bestand an.

    Der `conftest.py`-Override muss weg, sonst liefe jede Anfrage — auch die
    von B — als „Heidenreich" und der ganze Test wäre wertlos."""
    app.dependency_overrides.pop(aktuelle_familie, None)
    with TestClient(app) as a, TestClient(app) as b:
        assert a.post("/api/auth/registrieren", json={
            "name": "Familie A", "passwort": "sehrsicher123"}).status_code == 201
        assert b.post("/api/auth/registrieren", json={
            "name": "Familie B", "passwort": "auchsicher456"}).status_code == 201

        objekt = a.post("/api/objekte", json={
            "name": "Adlerweg 1",
            "einheiten": [{"bezeichnung": "EG", "flaeche": 60}]}).json()
        slug = objekt["slug"]
        zid = a.post(f"/api/objekte/{slug}/zeitraeume", json={
            "start": "2024-01-01", "ende": "2024-12-31"}).json()["id"]
        miete = a.post(f"/api/objekte/{slug}/mieten", json={
            "einheit": "EG", "partei": "Mieter A", "kaltmiete": 700,
            "ab_datum": "2024-01-01"}).json()
        einheit = a.get(f"/api/objekte/{slug}/einheiten").json()

        werte = {
            "slug": slug,
            "zid": zid,
            "miete": miete["id"],
            "einheit": (einheit[0]["id"] if isinstance(einheit, list)
                        else einheit["einheiten"][0]["id"]),
        }
        yield {"a": a, "b": b, "werte": werte}


@pytest.mark.parametrize("fall", FAELLE, ids=[f[0] for f in FAELLE])
def test_fremder_zugriff_ist_nicht_moeglich(welt, fall):
    """Eigentümer kommt durch, Fremde bekommt 404 — nur das Paar beweist es."""
    _name, methode, muster, rumpf = fall
    pfad = muster.format(**welt["werte"])

    eigen = welt["a"].request(methode, pfad, json=rumpf)
    assert eigen.status_code < 400, (
        f"Der Eigentümer kommt an {methode} {pfad} selbst nicht durch "
        f"({eigen.status_code}) — dann prüft dieser Fall die Trennung nicht, "
        f"sondern nur einen kaputten Pfad: {eigen.text[:200]}")

    fremd = welt["b"].request(methode, pfad, json=rumpf)
    assert fremd.status_code == 404, (
        f"Familie B kam an {methode} {pfad} heran: {fremd.status_code} "
        f"{fremd.text[:200]}")


@pytest.mark.parametrize("fall", LOESCHFAELLE, ids=[f[0] for f in LOESCHFAELLE])
def test_fremdes_loeschen_ist_nicht_moeglich(welt, fall):
    """Löschen von aussen: 404 — und die Zeile steht danach noch."""
    _name, loeschpfad, pruefpfad = fall
    pfad = loeschpfad.format(**welt["werte"])

    fremd = welt["b"].delete(pfad)
    assert fremd.status_code == 404, (
        f"Familie B durfte {pfad} löschen: {fremd.status_code} "
        f"{fremd.text[:200]}")

    nachher = welt["a"].get(pruefpfad.format(**welt["werte"]))
    assert nachher.status_code == 200, (
        f"Nach dem Löschversuch von B ist {pruefpfad} für A nicht mehr "
        f"erreichbar ({nachher.status_code}) — es wurde also doch etwas "
        f"entfernt.")


def test_objektliste_zeigt_nur_die_eigenen(welt):
    """Der häufigste Leck-Typ: eine Sammelliste ohne Familienfilter."""
    eigene = welt["a"].get("/api/objekte").json()
    assert any(o["slug"] == welt["werte"]["slug"] for o in eigene)

    fremde = welt["b"].get("/api/objekte").json()
    assert not any(o["slug"] == welt["werte"]["slug"] for o in fremde), \
        "Familie B sieht das Objekt von Familie A in ihrer Objektliste"


@pytest.mark.parametrize("pfad", [
    "/api/objekte", "/api/dokumente", "/api/kontakte",
    "/api/dokumentvorlagen", "/api/kidb",
])
def test_sammellisten_sind_bei_der_fremden_familie_leer(welt, pfad):
    """B hat selbst nichts angelegt — jede Sammelliste muss für B leer sein.

    Sie darf weder Objekte noch Dokumente, Kontakte, Vorlagen oder
    Belegdaten der Familie A enthalten. Ein Zähler > 0 wäre hier bereits das
    Leck, unabhängig davon, welche Felder die Liste ausgibt."""
    antwort = welt["b"].get(pfad)
    assert antwort.status_code == 200, f"{pfad}: {antwort.text[:200]}"
    daten = antwort.json()
    eintraege = daten if isinstance(daten, list) else (
        daten.get("dokumente") or daten.get("kontakte")
        or daten.get("vorlagen") or daten.get("eintraege") or [])
    assert not eintraege, \
        f"{pfad} zeigt Familie B {len(eintraege)} fremde Einträge"


def test_ohne_anmeldung_kommt_man_ueberhaupt_nicht_hinein(welt):
    """Ohne Sitzung ist jeder Fachpfad zu — nur der Anmeldeweg selbst nicht."""
    with TestClient(app) as gast:
        for pfad in ("/api/objekte", "/api/dokumente", "/api/kontakte",
                     f"/api/objekte/{welt['werte']['slug']}"):
            assert gast.get(pfad).status_code == 401, f"{pfad} war offen"
        # Die Auswahlliste des Anmeldescreens bleibt bewusst offen — sie
        # nennt nur Namen, nie einen Hash (siehe routers/auth.py).
        assert gast.get("/api/auth/familien").status_code == 200


def test_die_familienliste_gibt_niemals_einen_hash_heraus(welt):
    """Sie ist der einzige unangemeldete Endpunkt und darf deshalb nichts
    ausser Name/Logo/„hat Passwort" enthalten."""
    with TestClient(app) as gast:
        for eintrag in gast.get("/api/auth/familien").json():
            assert set(eintrag) == {"id", "name", "logo_pfad", "hat_passwort"}
            assert "passwort" not in str(eintrag).lower().replace(
                "hat_passwort", "")
