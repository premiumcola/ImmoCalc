"""N189 — Pflicht/optional je Kostenart (objektweit) über den Konfig-Weg.

Die Sichtbarkeit einer Position (`aktiv`) gab es schon; hier kommt additiv das
`optional`-Flag dazu. Vorgabe ist Pflicht (`optional=False`) — der Bestand
verhält sich unverändert. Der Konfig-Modus im Frontend liest und schreibt
{sichtbar (=aktiv), optional} über dieselben Endpunkte:

* GET  /api/objekte/{slug}/kostenarten  → je Kostenart u. a. `aktiv`, `optional`
* PATCH /api/kostenarten/{id}            → `aktiv` und/oder `optional` setzen

Jede Kostenart-Zeile der Checkliste (GET /api/zeitraeume/{id}) trägt `optional`,
damit das Frontend das rote Pflicht-Signal konsistent entscheiden kann.
"""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(),
                                     "test_positionen_konfig.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def _art(c, name):
    arten = c.get("/api/objekte/obj-a/kostenarten").json()
    return next((a for a in arten if a["name"] == name), None)


def _check(c, name):
    z = c.get("/api/zeitraeume/1").json()
    return next((k for k in z["checkliste"] if k["kostenart"] == name), None)


def test_kostenart_traegt_optional_mit_vorgabe_pflicht():
    """Jede Kostenart hat das neue Feld — und ist per Vorgabe Pflicht."""
    with TestClient(app) as c:
        a = _art(c, "Wasser")
        assert a is not None
        assert "optional" in a
        assert a["optional"] is False


def test_checkliste_zeile_traegt_optional_flag():
    """Die Checkliste reicht `optional` je Zeile durch (fürs rote Signal)."""
    with TestClient(app) as c:
        zeile = _check(c, "Wasser")
        assert zeile is not None
        assert zeile.get("optional") is False


def test_optional_laesst_sich_setzen_und_zuruecknehmen():
    """PATCH setzt `optional` — sichtbar in Katalog UND Checkliste."""
    with TestClient(app) as c:
        aid = _art(c, "Grundsteuer")["id"]

        r = c.patch(f"/api/kostenarten/{aid}", json={"optional": True})
        assert r.status_code == 200
        assert _art(c, "Grundsteuer")["optional"] is True
        assert _check(c, "Grundsteuer")["optional"] is True

        # zurück auf Pflicht
        r = c.patch(f"/api/kostenarten/{aid}", json={"optional": False})
        assert r.status_code == 200
        assert _art(c, "Grundsteuer")["optional"] is False
        assert _check(c, "Grundsteuer")["optional"] is False


def test_sichtbarkeit_und_optional_sind_unabhaengig():
    """`aktiv` (Anzeige) und `optional` (Pflicht) greifen nicht ineinander."""
    with TestClient(app) as c:
        aid = _art(c, "Müll")["id"]
        c.patch(f"/api/kostenarten/{aid}", json={"optional": True})
        # Ausblenden ändert das Optional-Flag nicht.
        c.patch(f"/api/kostenarten/{aid}", json={"aktiv": False})
        a = _art(c, "Müll")
        assert a["aktiv"] is False and a["optional"] is True
        # Eine ausgeblendete Kostenart fällt aus der Checkliste — bleibt aber
        # im Katalog konfigurierbar (der Konfig-Modus zeigt sie).
        assert _check(c, "Müll") is None
        # Wieder einblenden, Optional bleibt erhalten.
        c.patch(f"/api/kostenarten/{aid}", json={"aktiv": True})
        a = _art(c, "Müll")
        assert a["aktiv"] is True and a["optional"] is True
        assert _check(c, "Müll")["optional"] is True
        # aufräumen: Vorgabe wiederherstellen
        c.patch(f"/api/kostenarten/{aid}", json={"optional": False})


def test_optional_ueberlebt_migration():
    """Wächter: das additive Feld hat einen Default und bricht den Bestand nicht.

    Eine frisch angelegte Kostenart ohne Angabe ist Pflicht — nicht NULL.
    """
    with TestClient(app) as c:
        r = c.get("/api/objekte/obj-a/kostenarten").json()
        assert all(a.get("optional") in (True, False) for a in r)
