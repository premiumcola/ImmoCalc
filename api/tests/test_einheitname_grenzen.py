"""N454 — Umbenennen einer Einheit darf nur das eigene Objekt treffen.

Gefunden bei der Prüfung in der Nacht auf den 03.09.2026. `benenne_um` zog den
Namen mit einem `UPDATE … WHERE spalte = :alt` nach — **ohne** Einschränkung
auf das Objekt. „Wohnung 2" heisst aber in jedem Haus so. Damit schrieb das
Umbenennen in Haus A die Mieten, Anteile und Kostenpositionen von Haus B um —
und seit N436 auch die einer ANDEREN FAMILIE.

Zweiter Fund derselben Datei: das Register wird aus dem Datenmodell erzeugt
(„Textspalte, deren Name auf ‚einheit' endet"). Dabei fielen zwei Spalten
hinein, die gar keinen Einheitennamen tragen, sondern eine MASSEINHEIT:
`zaehler.messeinheit` ('m³' | 'kWh' | 'Liter' | 'Einheiten') und
`kostenposition.menge_einheit` ('kWh' | 'm³' | 'Liter'). Eine Einheit, die
„Liter" oder „Einheiten" heisst, hätte quer durch den Bestand Zählertypen
umgeschrieben.
"""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(),
                                     "test_einheitname_grenzen.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402

from app.einheitname import register  # noqa: E402
from app.main import app  # noqa: E402


def _haus(c, name, einheiten):
    neu = c.post("/api/objekte", json={
        "name": name,
        "einheiten": [{"bezeichnung": b, "flaeche": f} for b, f in einheiten],
    }).json()
    return neu["slug"]


def _miete(c, slug, einheit, partei, betrag):
    return c.post(f"/api/objekte/{slug}/mieten", json={
        "einheit": einheit, "partei": partei, "kaltmiete": betrag,
        "ab_datum": "2025-01-01"}).json()


def _einheit_id(c, slug, bezeichnung):
    for e in c.get(f"/api/objekte/{slug}/einheiten").json():
        if e["bezeichnung"] == bezeichnung:
            return e["id"]
    raise AssertionError(f"{bezeichnung} nicht gefunden")


def test_umbenennen_laesst_das_gleichnamige_haus_daneben_in_ruhe():
    """Der Kern: „Wohnung 2" gibt es in jedem Haus genau einmal."""
    with TestClient(app) as c:
        a = _haus(c, "Haus A N454", [("Wohnung 1", 70.0), ("Wohnung 2", 30.0)])
        b = _haus(c, "Haus B N454", [("Wohnung 1", 70.0), ("Wohnung 2", 30.0)])
        _miete(c, a, "Wohnung 2", "Mieter A", 500.0)
        _miete(c, b, "Wohnung 2", "Mieter B", 600.0)

        antwort = c.patch(f"/api/einheiten/{_einheit_id(c, a, 'Wohnung 2')}",
                          json={"bezeichnung": "Wohnung 2 OG"})
        assert antwort.status_code == 200, antwort.text

        # Haus A ist umbenannt …
        namen_a = {e["bezeichnung"] for e in
                   c.get(f"/api/objekte/{a}/einheiten").json()}
        assert "Wohnung 2 OG" in namen_a
        mieten_a = {m["partei"]: m["einheit"] for m in
                    c.get(f"/api/objekte/{a}/mieten").json()}
        assert mieten_a["Mieter A"] == "Wohnung 2 OG"

        # … und Haus B ist unangetastet.
        namen_b = {e["bezeichnung"] for e in
                   c.get(f"/api/objekte/{b}/einheiten").json()}
        assert namen_b == {"Wohnung 1", "Wohnung 2"}
        mieten_b = {m["partei"]: m["einheit"] for m in
                    c.get(f"/api/objekte/{b}/mieten").json()}
        assert mieten_b["Mieter B"] == "Wohnung 2", \
            "die Miete des Nachbarhauses wurde mit umbenannt"


def test_umbenennen_meldet_nur_die_eigenen_treffer():
    """Die Rückmeldung „nachgezogen" darf keine fremden Zeilen mitzählen."""
    with TestClient(app) as c:
        a = _haus(c, "Zaehlweg A", [("Studio", 40.0)])
        b = _haus(c, "Zaehlweg B", [("Studio", 40.0)])
        _miete(c, a, "Studio", "A", 400.0)
        _miete(c, b, "Studio", "B", 400.0)

        antwort = c.patch(f"/api/einheiten/{_einheit_id(c, a, 'Studio')}",
                          json={"bezeichnung": "Studio Nord"}).json()
        nachgezogen = antwort.get("nachgezogen") or {}
        assert nachgezogen.get("miete.einheit", 0) <= 1, \
            f"fremde Zeilen mitgezählt: {nachgezogen}"


def test_masseinheiten_gehoeren_nicht_ins_register():
    """`messeinheit` und `menge_einheit` tragen 'm³'/'kWh', keinen Namen.

    Eine Einheit namens „Liter" hätte sonst quer durch den Bestand
    Zählertypen umgeschrieben."""
    felder = {str(f) for f in register()}
    assert "zaehler.messeinheit" not in felder
    assert "kostenposition.menge_einheit" not in felder
    # Die echten Namensfelder müssen weiterhin dabei sein.
    assert "miete.einheit" in felder
    assert "anteil.einheit" in felder
    assert "kostenposition.nur_einheit" in felder


def test_eine_einheit_namens_liter_zerstoert_keine_zaehler():
    """Gegenprobe zum Register-Fund, über die echte API."""
    with TestClient(app) as c:
        slug = _haus(c, "Literweg 1", [("Liter", 30.0), ("Whg", 60.0)])
        zae = c.post(f"/api/objekte/{slug}/zaehler", json={
            "name": "Ölzähler", "kostenart": "Heizung",
            "einheit_bezug": "Whg", "messeinheit": "Liter",
            "typ": "direkt"}).json()

        c.patch(f"/api/einheiten/{_einheit_id(c, slug, 'Liter')}",
                json={"bezeichnung": "Kellerraum"})

        danach = next(z for z in c.get(f"/api/objekte/{slug}/zaehler").json()
                      if z["id"] == zae["id"])
        assert danach["messeinheit"] == "Liter", \
            "die Masseinheit des Zählers wurde mit umbenannt"
