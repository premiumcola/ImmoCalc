"""N47 — der Wasser-Detail-Endpunkt gegen die echten Excel-Zahlen
(KostenSPLIT_2024). Wächter: die verbrauchsscharfe Zuordnung über die
Unterzähler, der Personen·Mietdauer-Rest aufs Haupthaus und die
Kontrollsumme = Gesamtkosten laufen durch den Endpunkt genauso wie durch den
reinen Rechenkern.

Die Ablesungen sind so gesetzt (Anfangsstand 0 am 01.01., Endstand am 31.12.,
Ist-Tage == Soll-Tage), dass der interpolierte Verbrauch exakt der J-Differenz
der Excel entspricht.
"""
import os
import sys
import tempfile
from datetime import date

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_wasser_endpoint.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlmodel import Session, select  # noqa: E402

from app import db  # noqa: E402
from app.models import (Ablesung, Dokument, Einheit, Kostenposition,  # noqa: E402
                        Miete, Objekt, Zaehler, Zeitraum)
from app.routers.zaehler import (ANFANGSSTAND, rechnungsmenge_setzen,  # noqa: E402
                                 wasser_detail, wasser_leeren)

START = date(2024, 1, 1)
ENDE = date(2024, 12, 31)


def _zaehler(s, objekt_id, name, art, *, einheit="", haupt=None):
    z = Zaehler(objekt_id=objekt_id, name=name, art=art, typ="gemessen",
                einheit_bezug=einheit, hauptzaehler_id=haupt, kostenart="Wasser")
    s.add(z)
    s.commit()
    s.refresh(z)
    return z.id


def _ablesungen(s, zaehler_id, zeitraum_id, m3):
    """Anfangsstand 0 am 01.01. + Endstand m3 am 31.12. → Verbrauch == m3."""
    s.add(Ablesung(zaehler_id=zaehler_id, datum=START, stand=0.0,
                   zeitraum_id=None, notiz=ANFANGSSTAND))
    s.add(Ablesung(zaehler_id=zaehler_id, datum=ENDE, stand=m3,
                   zeitraum_id=zeitraum_id))
    s.commit()


def _aufbau(slug: str = "laufer-str-5"):
    with Session(db.engine) as s:
        o = Objekt(slug=slug, name="Laufer Str. 5", start_monat=1)
        s.add(o)
        s.commit()
        s.refresh(o)
        oid = o.id

        for bez in ("Büro", "Studio 1.OG", "EG", "1.OG"):
            s.add(Einheit(objekt_id=oid, bezeichnung=bez))
        # Haupthaus: EG mit 2 Personen, 1.OG mit 1 Person (Rest-Split 2:1).
        # Büro/Studio haben eigene Kaltzähler und fallen aus dem Rest heraus.
        for einheit, partei, pers in (("EG", "EG-Mieter", 2), ("1.OG", "OG-Mieter", 1),
                                      ("Büro", "Büro-Mieter", 1),
                                      ("Studio 1.OG", "Studio-Mieter", 1)):
            s.add(Miete(objekt_id=oid, einheit=einheit, partei=partei,
                        personen=pers, ab_datum=START))

        z = Zeitraum(objekt_id=oid, start=START, ende=ENDE, status="in Arbeit")
        s.add(z)
        s.commit()
        s.refresh(z)
        zid = z.id
        for art, betrag in (("Wasser", 298.05), ("Abwasser", 362.56),
                            ("Niederschlagswasser", 186.91)):
            s.add(Kostenposition(zeitraum_id=zid, kostenart=art, betrag=betrag))
        s.commit()

        haupt = _zaehler(s, oid, "Gesamt Wasser", "Kaltwasser")
        buero = _zaehler(s, oid, "Büro Kaltwasser", "Kaltwasser",
                         einheit="Büro", haupt=haupt)
        st_kw = _zaehler(s, oid, "Studio Kaltwasser", "Kaltwasser",
                         einheit="Studio 1.OG", haupt=haupt)
        st_wm = _zaehler(s, oid, "Studio Waschmaschine", "Waschmaschine",
                         einheit="Studio 1.OG", haupt=haupt)
        st_ww = _zaehler(s, oid, "Studio Warmwasser", "Warmwasser",
                         einheit="Studio 1.OG", haupt=haupt)
        garten = _zaehler(s, oid, "Gartenwasser", "Gartenwasser",
                          einheit="Studio 1.OG", haupt=haupt)

        _ablesungen(s, haupt, zid, 142.5775425531915)
        _ablesungen(s, buero, zid, 4.139773049645385)
        _ablesungen(s, st_kw, zid, 29.831631205673716)
        _ablesungen(s, st_wm, zid, 8.785627659574459)
        _ablesungen(s, st_ww, zid, 5.684421985815604)
        _ablesungen(s, garten, zid, 15.0)
        return zid


def test_wasser_endpoint_kostensplit_2024():
    zid = _aufbau()
    with Session(db.engine) as s:
        res = wasser_detail(zid, session=s)

    assert res["bereit"] is True, res
    # Gesamtkosten und Preis je m³ wie in der Excel.
    assert res["kosten"]["gesamt"] == 847.52
    assert res["kosten"]["preis_m3"] == 5.94
    assert res["gesamt_m3"] == 142.58

    summe = {e["name"]: e["summe"] for e in res["einheiten"]}
    assert summe["Büro"] == 24.61
    assert abs(summe["Studio 1.OG"] - 263.34) <= 0.01

    # Gartenwasser: Menge heraus, Kosten beim Eigentümer.
    assert res["garten"]["kosten"] == 31.36
    assert res["garten"]["einheit"] == "Studio 1.OG"

    # Rest (Haupthaus) und Kontrollsumme.
    assert abs(res["rest_m3"] - 79.14) <= 0.02
    assert res["rest_kosten"] == 528.21
    assert abs(res["kontrolle"] - 847.52) <= 0.02

    # Büro trägt genau seine gemessene Kaltwasser-Zeile.
    buero = next(e for e in res["einheiten"] if e["name"] == "Büro")
    assert buero["zeilen"] == [
        {"art": "Kaltwasser", "m3": 4.14, "kosten": 24.61, "quelle": "gemessen"}]

    # EG/1.OG bekommen ihren berechneten Haupthaus-Anteil (2:1).
    eg = next(e for e in res["einheiten"] if e["name"] == "EG")
    assert all(zeile["quelle"] == "berechnet" for zeile in eg["zeilen"])
    og = next(e for e in res["einheiten"] if e["name"] == "1.OG")
    assert abs(eg["summe"] / og["summe"] - 2.0) <= 0.02


def _aufbau_mehrfach():
    """CD — ein Warmwasser-Boiler versorgt EG UND 1.OG gemeinsam. Sein Verbrauch
    (30 m³) wird über die Mehrfachzuordnung nach Person·Mietdauer EG:1.OG = 2:1
    aufgeteilt; der verbleibende Rest (10 m³) geht denselben 2:1-Weg."""
    with Session(db.engine) as s:
        o = Objekt(slug="boiler-haus", name="Boiler-Haus", start_monat=1)
        s.add(o)
        s.commit()
        s.refresh(o)
        oid = o.id
        for bez in ("EG", "1.OG"):
            s.add(Einheit(objekt_id=oid, bezeichnung=bez))
        for einheit, partei, pers in (("EG", "EG-Mieter", 2),
                                      ("1.OG", "OG-Mieter", 1)):
            s.add(Miete(objekt_id=oid, einheit=einheit, partei=partei,
                        personen=pers, ab_datum=START))
        z = Zeitraum(objekt_id=oid, start=START, ende=ENDE, status="in Arbeit")
        s.add(z)
        s.commit()
        s.refresh(z)
        zid = z.id
        s.add(Kostenposition(zeitraum_id=zid, kostenart="Wasser", betrag=120.0))
        s.commit()

        haupt = _zaehler(s, oid, "Gesamt Wasser", "Kaltwasser")
        # Gemeinsamer Warmwasser-Boiler für EG + 1.OG (Mehrfachzuordnung).
        boiler = Zaehler(objekt_id=oid, name="Boiler-Zulauf", art="Warmwasser",
                         typ="gemessen", hauptzaehler_id=haupt, kostenart="Wasser",
                         einheiten="EG,1.OG")
        s.add(boiler)
        s.commit()
        s.refresh(boiler)
        _ablesungen(s, haupt, zid, 40.0)     # Gesamt 40 m³
        _ablesungen(s, boiler.id, zid, 30.0)  # Boiler 30 m³ → Rest 10 m³
        return zid


def test_wasser_endpoint_mehrfach_einheiten_split():
    zid = _aufbau_mehrfach()
    with Session(db.engine) as s:
        res = wasser_detail(zid, session=s)

    assert res["bereit"] is True, res
    assert res["kosten"]["gesamt"] == 120.0
    assert res["gesamt_m3"] == 40.0
    # preis = 120/40 = 3. Boiler 30 m³ → 90 € (2:1: EG 60, 1.OG 30); Rest 10 m³
    # → 30 € (2:1: EG 20, 1.OG 10). Summe EG 80, 1.OG 40 → Verhältnis 2:1.
    summe = {e["name"]: e["summe"] for e in res["einheiten"]}
    assert summe["EG"] == 80.0
    assert summe["1.OG"] == 40.0
    # Der Boiler erscheint als gemessene Zeile bei BEIDER Einheit, anteilig 2:1.
    eg = next(e for e in res["einheiten"] if e["name"] == "EG")
    og = next(e for e in res["einheiten"] if e["name"] == "1.OG")
    eg_gemessen = [z for z in eg["zeilen"] if z["quelle"] == "gemessen"]
    og_gemessen = [z for z in og["zeilen"] if z["quelle"] == "gemessen"]
    assert eg_gemessen == [
        {"art": "Warmwasser", "m3": 20.0, "kosten": 60.0, "quelle": "gemessen"}]
    assert og_gemessen == [
        {"art": "Warmwasser", "m3": 10.0, "kosten": 30.0, "quelle": "gemessen"}]
    # Kontrollsumme exakt = Gesamtkosten.
    assert abs(res["kontrolle"] - 120.0) <= 0.01


def _aufbau_altlabels():
    """N101/6 — die Spalten sind Einheiten, keine Parteien.

    Ein Zähler trägt nur das Alt-Label „Roman & Alicia" (der Partei-Name), ein
    zweiter ein Label, das zu gar nichts gehört. Erwartet: der erste landet in
    der Spalte „Studio 1.OG", der zweite erzeugt KEINE Spalte, sondern eine
    Warnung — sein Verbrauch fällt in den Haupthaus-Rest.
    """
    with Session(db.engine) as s:
        o = Objekt(slug="altlabel-haus", name="Altlabel", start_monat=1)
        s.add(o)
        s.commit()
        s.refresh(o)
        oid = o.id
        for bez in ("Studio 1.OG", "Wohung EG", "Wohnug 1.OG"):
            s.add(Einheit(objekt_id=oid, bezeichnung=bez))
        for einheit, partei, pers in (("Studio 1.OG", "Roman & Alicia", 1),
                                      ("Wohung EG", "EG-Mieter", 2),
                                      ("Wohnug 1.OG", "OG-Mieter", 1)):
            s.add(Miete(objekt_id=oid, einheit=einheit, partei=partei,
                        personen=pers, ab_datum=START))
        z = Zeitraum(objekt_id=oid, start=START, ende=ENDE, status="in Arbeit")
        s.add(z)
        s.commit()
        s.refresh(z)
        zid = z.id
        s.add(Kostenposition(zeitraum_id=zid, kostenart="Wasser", betrag=100.0))
        s.commit()

        haupt = _zaehler(s, oid, "Gesamt Wasser", "Kaltwasser")
        alt = Zaehler(objekt_id=oid, name="Bad Studio", art="Kaltwasser",
                      typ="gemessen", hauptzaehler_id=haupt, kostenart="Wasser",
                      einheiten="Roman & Alicia")
        fremd = Zaehler(objekt_id=oid, name="Kammer", art="Waschmaschine",
                        typ="gemessen", hauptzaehler_id=haupt, kostenart="Wasser",
                        einheiten="Hausmeister-Kammer")
        s.add(alt)
        s.add(fremd)
        s.commit()
        s.refresh(alt)
        s.refresh(fremd)
        _ablesungen(s, haupt, zid, 100.0)
        _ablesungen(s, alt.id, zid, 20.0)
        _ablesungen(s, fremd.id, zid, 5.0)
        return zid


def test_wasser_endpoint_altlabel_wird_zur_einheit():
    zid = _aufbau_altlabels()
    with Session(db.engine) as s:
        res = wasser_detail(zid, session=s)

    assert res["bereit"] is True, res
    namen = {e["name"] for e in res["einheiten"]}
    # Keine Partei-Spalte, keine Phantom-Spalte.
    assert namen == {"Studio 1.OG", "Wohung EG", "Wohnug 1.OG"}, namen
    # Das Alt-Label trägt seinen vollen Verbrauch in die Einheit.
    studio = next(e for e in res["einheiten"] if e["name"] == "Studio 1.OG")
    assert studio["zeilen"] == [
        {"art": "Kaltwasser", "m3": 20.0, "kosten": 20.0, "quelle": "gemessen"}]
    # Das unbekannte Label wird benannt, nicht verschluckt.
    assert any("Hausmeister-Kammer" in w for w in res["warnungen"]), res["warnungen"]
    # Sein Verbrauch fällt in den Rest: 100 − 20 = 80 m³ auf EG:1.OG = 2:1.
    summe = {e["name"]: e["summe"] for e in res["einheiten"]}
    assert abs(summe["Wohung EG"] - 53.33) <= 0.01
    assert abs(summe["Wohnug 1.OG"] - 26.67) <= 0.01
    # Harte Invariante: Σ Einheiten + Garten == Gesamtkosten.
    assert abs(res["kontrolle"] - 100.0) <= 0.01


def _aufbau_wg():
    """N101/6 — das überholte Sammel-Label „WG" bekommt keine eigene Spalte,
    sondern verteilt sich auf die Haupthaus-Einheiten (Person·Mietdauer)."""
    with Session(db.engine) as s:
        o = Objekt(slug="wg-haus", name="WG-Haus", start_monat=1)
        s.add(o)
        s.commit()
        s.refresh(o)
        oid = o.id
        for bez in ("Wohung EG", "Wohnug 1.OG"):
            s.add(Einheit(objekt_id=oid, bezeichnung=bez))
        for einheit, partei, pers in (("Wohung EG", "EG-Mieter", 2),
                                      ("Wohnug 1.OG", "OG-Mieter", 1)):
            s.add(Miete(objekt_id=oid, einheit=einheit, partei=partei,
                        personen=pers, ab_datum=START))
        z = Zeitraum(objekt_id=oid, start=START, ende=ENDE, status="in Arbeit")
        s.add(z)
        s.commit()
        s.refresh(z)
        zid = z.id
        s.add(Kostenposition(zeitraum_id=zid, kostenart="Wasser", betrag=60.0))
        s.commit()

        haupt = _zaehler(s, oid, "Gesamt Wasser", "Kaltwasser")
        wm = Zaehler(objekt_id=oid, name="Waschmaschine WG", art="Waschmaschine",
                     typ="gemessen", hauptzaehler_id=haupt, kostenart="Wasser",
                     einheiten="WG")
        s.add(wm)
        s.commit()
        s.refresh(wm)
        _ablesungen(s, haupt, zid, 60.0)
        _ablesungen(s, wm.id, zid, 30.0)
        return zid


def test_wasser_endpoint_wg_geht_aufs_haupthaus():
    zid = _aufbau_wg()
    with Session(db.engine) as s:
        res = wasser_detail(zid, session=s)

    assert res["bereit"] is True, res
    namen = {e["name"] for e in res["einheiten"]}
    assert namen == {"Wohung EG", "Wohnug 1.OG"}, namen
    assert res["warnungen"] == []
    # 60 € / 60 m³ = 1 €/m³. Zähler 30 m³ und Rest 30 m³, beide 2:1 → 40 / 20.
    summe = {e["name"]: e["summe"] for e in res["einheiten"]}
    assert abs(summe["Wohung EG"] - 40.0) <= 0.01
    assert abs(summe["Wohnug 1.OG"] - 20.0) <= 0.01
    assert abs(res["kontrolle"] - 60.0) <= 0.01


def test_wasser_endpoint_nicht_bereit_ohne_betraege():
    """Ohne Wasserbeträge ist der Endpunkt nicht bereit und sagt, was fehlt."""
    with Session(db.engine) as s:
        o = Objekt(slug="leer-haus", name="Leer", start_monat=1)
        s.add(o)
        s.commit()
        s.refresh(o)
        z = Zeitraum(objekt_id=o.id, start=START, ende=ENDE, status="in Arbeit")
        s.add(z)
        s.commit()
        s.refresh(z)
        res = wasser_detail(z.id, session=s)
    assert res["bereit"] is False
    assert "fehlt" in res["hinweis"].lower()


def test_rechnungsmenge_bleibt_stehen_und_weist_die_abweichung_aus():
    """N116b — die abgerechnete Menge ueberlebt das Neuladen, der Zaehlerwert
    bleibt daneben stehen und die Differenz wird benannt."""
    zid = _aufbau("laufer-str-5-rechnungsmenge")
    with Session(db.engine) as s:
        vorher = wasser_detail(zid, session=s)
    abgelesen = vorher["abgelesen_m3"]
    assert abgelesen and abgelesen > 0

    gesetzt = round(abgelesen - 10.0, 3)
    with Session(db.engine) as s:
        rechnungsmenge_setzen(zid, {"rechnung_m3": gesetzt}, session=s)
        d = wasser_detail(zid, session=s)

    assert d["rechnung_m3"] == gesetzt
    assert d["abgelesen_m3"] == abgelesen        # der Zaehler bleibt unangetastet
    assert abs(d["abweichung_m3"] - 10.0) < 1e-6
    assert abs(d["gesamt_m3"] - gesetzt) < 0.01  # verteilt wird auf die Rechnung

    # Leeren loest die Angabe wieder auf.
    with Session(db.engine) as s:
        rechnungsmenge_setzen(zid, {"rechnung_m3": None}, session=s)
        zurueck = wasser_detail(zid, session=s)
    assert zurueck["rechnung_m3"] is None
    assert abs(zurueck["gesamt_m3"] - abgelesen) < 0.01


def _wasser_positionen_der(session, zid):
    return [p for p in session.exec(
        select(Kostenposition).where(Kostenposition.zeitraum_id == zid)).all()
        if p.kostenart in ("Wasser", "Abwasser", "Niederschlagswasser")]


def test_wasser_leeren_force_nullt_betraege_und_menge_zaehler_bleiben():
    """N185 — `force=true` (manueller „Position leeren"-Knopf) setzt alle drei
    Bestandteile auf 0 + `status='offen'` und loest die geeichte Menge, laesst
    aber die ZAEHLER und ihre Ablesungen unangetastet."""
    zid = _aufbau("leeren-force")
    with Session(db.engine) as s:
        rechnungsmenge_setzen(zid, {"rechnung_m3": 130.0}, session=s)
        assert wasser_detail(zid, session=s)["bereit"] is True
        zaehler_vorher = len(s.exec(select(Zaehler)).all())
        ablesungen_vorher = len(s.exec(select(Ablesung)).all())

    with Session(db.engine) as s:
        res = wasser_leeren(zid, force=True, session=s)
    assert res["geleert"] is True
    assert res["positionen"] == 3

    with Session(db.engine) as s:
        pos = _wasser_positionen_der(s, zid)
        assert pos and all(p.betrag == 0.0 for p in pos)
        assert all((p.beleg_summe or 0.0) == 0.0 for p in pos)
        assert all(p.status == "offen" for p in pos)
        z = s.get(Zeitraum, zid)
        assert (z.wasser_rechnung_m3 or 0.0) == 0.0
        # Zähler + Ablesungen unangetastet — sie messen Verbrauch, nicht den Bescheid.
        assert len(s.exec(select(Zaehler)).all()) == zaehler_vorher
        assert len(s.exec(select(Ablesung)).all()) == ablesungen_vorher
        # Ohne Beträge ist die Detailübersicht nicht mehr „bereit" → klappt leer ein.
        assert wasser_detail(zid, session=s)["bereit"] is False


def test_wasser_leeren_ohne_force_raeumt_ab_wenn_kein_beleg_mehr_haengt():
    """N185 — der letzte Beleg ist schon geloest (position_id=None): dann leert
    `force=false` die ganze Sammelposition (das ist der Auto-Fall nach dem
    Beleg-Entfernen)."""
    zid = _aufbau("leeren-auto")
    with Session(db.engine) as s:
        res = wasser_leeren(zid, force=False, session=s)
    assert res["geleert"] is True
    with Session(db.engine) as s:
        assert all(p.betrag == 0.0 for p in _wasser_positionen_der(s, zid))


def test_wasser_leeren_ohne_force_haelt_position_wenn_noch_ein_beleg_haengt():
    """N185 — hängt noch ein Beleg an einer der drei Positionen, bleibt ohne
    `force` alles stehen (ein bloss entfernter Zwischenbeleg räumt nicht ab)."""
    zid = _aufbau("leeren-behalt")
    with Session(db.engine) as s:
        wasserpos = next(p for p in _wasser_positionen_der(s, zid)
                         if p.kostenart == "Wasser")
        s.add(Dokument(pfad="/Belege/wasser-2024.pdf", dateiname="wasser-2024.pdf",
                       zeitraum_id=zid, kostenart="Wasser", betrag=298.05,
                       position_id=wasserpos.id))
        s.commit()
        res = wasser_leeren(zid, force=False, session=s)
    assert res["geleert"] is False
    with Session(db.engine) as s:
        betraege = {p.kostenart: p.betrag for p in _wasser_positionen_der(s, zid)}
        # Die von Hand/Beleg getragenen Beträge stehen unverändert.
        assert betraege["Abwasser"] == 362.56
        assert betraege["Niederschlagswasser"] == 186.91
