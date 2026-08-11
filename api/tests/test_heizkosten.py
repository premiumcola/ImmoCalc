"""N340t/N340u — der Delta-t-Rechenweg aus echten Zählern statt aus der
Simulator-Konfiguration im Browser.

Zwei kleine, selbst gebaute Einheiten mit je einem Heizkörperverteiler
(unterschiedlicher Bewertungsfaktor) und ein gemeinsam genutzter Zähler ohne
Einheiten-Bezug — genug, um zu prüfen, dass `heizkosten.py`:

1. den Ablesewert eines Heizkörperverteilers mit seinem Bewertungsfaktor
   multipliziert, bevor er in die Rechnung geht (roher Wert allein wäre
   zwischen zwei Zählern nicht vergleichbar),
2. je Einheit eine eigene Nutzer-Zeile bildet, nicht eine Summe über alle,
3. einen Zähler ohne Einheiten-Bezug meldet statt seinen Verbrauch
   stillschweigend zu verlieren,
4. `typ='direkt'` (Jahreswert, kein Zählerstand) genauso verarbeitet wie die
   bereits bestehende E-Auto-Ladestation — dieselbe `ablesung.
   verbrauch_je_zaehler`-Funktion.
"""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_heizkosten.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def _objekt(c):
    neu = c.post("/api/objekte", json={
        "name": "Heizweg 1",
        "einheiten": [{"bezeichnung": "Whg A", "flaeche": 50.0, "partei": "A"},
                      {"bezeichnung": "Whg B", "flaeche": 30.0, "partei": "B"}]}
    ).json()
    slug = neu["slug"]
    det = c.get(f"/api/objekte/{slug}").json()
    laufend = next(z for z in det["zeitraeume"] if z["status"] == "in Arbeit")
    return slug, laufend["id"]


def _zaehler_direkt(c, slug, zid, *, name, einheit_bezug, wert,
                    messeinheit="Einheiten", kostenart="Heizung",
                    bewertungsfaktor=None):
    zaehler = c.post(f"/api/objekte/{slug}/zaehler", json={
        "name": name, "kostenart": kostenart, "einheit_bezug": einheit_bezug,
        "messeinheit": messeinheit, "typ": "direkt",
        **({"bewertungsfaktor": bewertungsfaktor} if bewertungsfaktor is not None else {}),
    }).json()
    zid_zaehler = zaehler["id"]
    r = c.post(f"/api/zaehler/{zid_zaehler}/ablesungen",
              json={"datum": "2026-09-30", "stand": wert, "zeitraum_id": zid})
    assert r.status_code in (200, 201), r.text
    return zid_zaehler


def test_bewertungsfaktor_geht_in_die_ehkv_summe_ein():
    """622 Einheiten × Faktor 1,108 UND 100 Einheiten × Faktor 2,0 dürfen NICHT
    einfach addiert werden (622+100) — der jeweilige Faktor entscheidet."""
    with TestClient(app) as c:
        slug, zid = _objekt(c)
        _zaehler_direkt(c, slug, zid, name="HKV A", einheit_bezug="Whg A",
                        wert=622, bewertungsfaktor=1.108)
        _zaehler_direkt(c, slug, zid, name="HKV B", einheit_bezug="Whg B",
                        wert=100, bewertungsfaktor=2.0)

        from app import db
        from app.heizkosten import nutzer_aus_zaehlern
        from sqlmodel import Session
        from app.models import Zeitraum
        with Session(db.engine) as s:
            z = s.get(Zeitraum, zid)
            nutzer, unzugeordnet = nutzer_aus_zaehlern(s, z)

        assert unzugeordnet == []
        nach_name = {n["name"]: n for n in nutzer}
        assert set(nach_name) == {"Whg A", "Whg B"}
        assert nach_name["Whg A"]["ehkv"] == 622 * 1.108
        assert nach_name["Whg B"]["ehkv"] == 100 * 2.0
        assert nach_name["Whg A"]["flaeche"] == 50.0
        assert nach_name["Whg B"]["flaeche"] == 30.0


def test_zaehler_ohne_bezug_wird_gemeldet_nicht_verschluckt():
    with TestClient(app) as c:
        slug, zid = _objekt(c)
        _zaehler_direkt(c, slug, zid, name="Waschküche", einheit_bezug="",
                        wert=50, bewertungsfaktor=1.5)

        from app import db
        from app.heizkosten import nutzer_aus_zaehlern
        from sqlmodel import Session
        from app.models import Zeitraum
        with Session(db.engine) as s:
            z = s.get(Zeitraum, zid)
            nutzer, unzugeordnet = nutzer_aus_zaehlern(s, z)

        assert nutzer == []
        assert unzugeordnet == ["Waschküche"]


def test_wmz_und_wwz_gehen_in_kwh_bzw_ww_m3_nicht_in_ehkv():
    with TestClient(app) as c:
        slug, zid = _objekt(c)
        _zaehler_direkt(c, slug, zid, name="Wärmemengenzähler", einheit_bezug="Whg A",
                        wert=1234.0, messeinheit="kWh")
        _zaehler_direkt(c, slug, zid, name="Warmwasserzähler", einheit_bezug="Whg A",
                        wert=12.5, messeinheit="m³", kostenart="Warmwasser")

        from app import db
        from app.heizkosten import nutzer_aus_zaehlern
        from sqlmodel import Session
        from app.models import Zeitraum
        with Session(db.engine) as s:
            z = s.get(Zeitraum, zid)
            nutzer, _ = nutzer_aus_zaehlern(s, z)

        whg_a = next(n for n in nutzer if n["name"] == "Whg A")
        assert whg_a["kwh"] == 1234.0
        assert whg_a["ww_m3"] == 12.5
        assert whg_a["ehkv"] == 0.0


def test_rechnen_endpunkt_liefert_heizkosten_je_einheit():
    """End-to-End über die API: `heizwert`/`liter`/`eur` wie am Beleg, die
    Verbrauchs-Gewichte kommen aus den echten Zählern."""
    with TestClient(app) as c:
        slug, zid = _objekt(c)
        _zaehler_direkt(c, slug, zid, name="HKV A", einheit_bezug="Whg A",
                        wert=600, bewertungsfaktor=1.0)
        _zaehler_direkt(c, slug, zid, name="HKV B", einheit_bezug="Whg B",
                        wert=400, bewertungsfaktor=1.0)

        r = c.post(f"/api/zeitraeume/{zid}/heizkosten/rechnen",
                  json={"heizwert": 10.0, "liter": 1000.0, "eur": 1000.0,
                        "fest_anteil": 0.0})
        assert r.status_code == 200, r.text
        erg = r.json()
        nach_name = {n["name"]: n for n in erg["nutzer"]}
        # Reiner Verbrauchsschlüssel (fest_anteil 0): 600:400 = 60/40 %.
        assert round(nach_name["Whg A"]["heizkosten"], 2) == 600.0
        assert round(nach_name["Whg B"]["heizkosten"], 2) == 400.0
        assert erg["unzugeordnet"] == []


def test_uebernehmen_traegt_ergebnis_in_bestehende_position_ein():
    with TestClient(app) as c:
        slug, zid = _objekt(c)
        _zaehler_direkt(c, slug, zid, name="HKV A", einheit_bezug="Whg A",
                        wert=1, bewertungsfaktor=1.0)
        _zaehler_direkt(c, slug, zid, name="HKV B", einheit_bezug="Whg B",
                        wert=1, bewertungsfaktor=1.0)

        # Ohne bestehende Heizungs-Position: nichts zu tun, kein 0-€-Posten.
        r0 = c.post(f"/api/zeitraeume/{zid}/heizkosten/uebernehmen",
                   json={"liter": 100.0, "eur": 100.0, "fest_anteil": 0.0})
        assert r0.json()["angewandt"] is False

        pos = c.post(f"/api/zeitraeume/{zid}/positionen",
                    json={"kostenart": "Heizung", "betrag": 250.0})
        assert pos.status_code in (200, 201), pos.text

        r = c.post(f"/api/zeitraeume/{zid}/heizkosten/uebernehmen",
                  json={"liter": 100.0, "eur": 100.0, "fest_anteil": 0.0})
        assert r.status_code == 200, r.text
        erg = r.json()
        assert erg["angewandt"] is True
        assert set(erg["anteile"]) == {"Whg A", "Whg B"}
        # Gleich hoher Ablesewert → gleich hoher Anteil.
        assert erg["anteile"]["Whg A"] == erg["anteile"]["Whg B"]
