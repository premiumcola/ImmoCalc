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

from sqlmodel import Session  # noqa: E402

from app import db  # noqa: E402
from app.models import (Ablesung, Einheit, Kostenposition, Miete, Objekt,  # noqa: E402
                        Zaehler, Zeitraum)
from app.routers.zaehler import ANFANGSSTAND, wasser_detail  # noqa: E402

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


def _aufbau():
    with Session(db.engine) as s:
        o = Objekt(slug="laufer-str-5", name="Laufer Str. 5", start_monat=1)
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
    assert res["garten"]["kosten"] == 89.16
    assert res["garten"]["einheit"] == "Studio 1.OG"

    # Rest (Haupthaus) und Kontrollsumme.
    assert abs(res["rest_m3"] - 79.14) <= 0.02
    assert res["rest_kosten"] == 470.41
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
