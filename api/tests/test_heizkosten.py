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


def test_partei_name_und_einheiten_name_landen_in_derselben_zeile():
    """Ein Zähler kann seinen Bezug als Einheiten-Bezeichnung tragen
    („Whg A", neue Konvention) oder als Partei-Name („A", ältere Zähler wie
    die bestehenden Warmwasserzähler dieses Objekts) — beide meinen dieselbe
    Wohnung und müssen in EINER Nutzer-Zeile landen, nicht in zweien."""
    with TestClient(app) as c:
        slug, zid = _objekt(c)
        _zaehler_direkt(c, slug, zid, name="HKV (Einheiten-Name)",
                        einheit_bezug="Whg A", wert=100, bewertungsfaktor=1.0)
        _zaehler_direkt(c, slug, zid, name="Warmwasser (Partei-Name)",
                        einheit_bezug="A", wert=5.0, messeinheit="m³",
                        kostenart="Warmwasser")

        from app import db
        from app.heizkosten import nutzer_aus_zaehlern
        from sqlmodel import Session
        from app.models import Miete, Zeitraum
        with Session(db.engine) as s:
            z = s.get(Zeitraum, zid)
            # N340w-Fund: `bezuege()` findet einen Partei-Namen nur über ein
            # echtes Mietverhältnis — ohne das gilt die Einheit als leerstehend
            # und "A" bliebe unresolved. Genau das übersah der erste Test.
            s.add(Miete(objekt_id=z.objekt_id, einheit="Whg A", partei="A",
                        personen=1, ab_datum=z.start))
            s.commit()
            nutzer, unzugeordnet = nutzer_aus_zaehlern(s, z)

        assert unzugeordnet == []
        assert len(nutzer) == 1
        assert nutzer[0]["name"] == "Whg A"
        assert nutzer[0]["ehkv"] == 100.0
        assert nutzer[0]["ww_m3"] == 5.0


def test_altes_partei_label_mit_gesetztem_einheiten_feld_zaehlt_richtig():
    """N341 — Bestandszähler tragen im `einheit_bezug` oft ein Alt-Label, das
    zu keiner Einheit und keiner Partei mehr passt („Roman & Alicia"), haben
    aber die echte Einheit im Mehrfachfeld `einheiten` stehen. Dann gilt
    `einheiten` — genau wie bei Wasser und Strom (`parse_einheiten`).

    Der Test hält fest, dass dieser Zähler NICHT in einer eigenen
    Phantom-Zeile landet und NICHT als unzugeordnet gemeldet wird. (Vorher
    las `heizkosten.py` allein `einheit_bezug` — das war der Grund, warum an
    echten Daten herumkorrigiert wurde, statt den Code zu reparieren.)"""
    with TestClient(app) as c:
        slug, zid = _objekt(c)
        zaehler_id = _zaehler_direkt(c, slug, zid, name="HKV mit Alt-Label",
                                     einheit_bezug="Irgendein Altlabel",
                                     wert=100, bewertungsfaktor=1.0)
        # Die echte Einheit steht im Mehrfachfeld — wie im Bestand.
        assert c.patch(f"/api/zaehler/{zaehler_id}",
                       json={"einheiten": ["Whg A"]}).status_code == 200

        from app import db
        from app.heizkosten import nutzer_aus_zaehlern
        from sqlmodel import Session
        from app.models import Zeitraum
        with Session(db.engine) as s:
            z = s.get(Zeitraum, zid)
            nutzer, unzugeordnet = nutzer_aus_zaehlern(s, z)

        assert unzugeordnet == []
        assert [n["name"] for n in nutzer] == ["Whg A"]
        assert nutzer[0]["ehkv"] == 100.0
        assert nutzer[0]["flaeche"] == 50.0


def test_gemeinschaftlicher_zaehler_teilt_sich_auf_die_gewaehlten_einheiten():
    """N343 — ein Heizkörper, der auf MEHRERE Einheiten zählt (Waschküche):
    sein Wert verteilt sich zu gleichen Teilen auf genau diese Einheiten —
    nicht auf eine davon, nicht auf alle des Hauses."""
    with TestClient(app) as c:
        slug, zid = _objekt(c)
        zaehler_id = _zaehler_direkt(c, slug, zid, name="Waschküche",
                                     einheit_bezug="", wert=100,
                                     bewertungsfaktor=2.0)
        assert c.patch(f"/api/zaehler/{zaehler_id}",
                       json={"einheiten": ["Whg A", "Whg B"]}).status_code == 200

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
        # 100 Einheiten × Faktor 2,0 = 200, je zur Hälfte: 100 pro Wohnung.
        assert nach_name["Whg A"]["ehkv"] == 100.0
        assert nach_name["Whg B"]["ehkv"] == 100.0


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
