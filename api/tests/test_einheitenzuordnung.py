"""N288-B4 — ein Zähler, der zu keiner Einheit gehört, wird in JEDER Kette
gemeldet und nirgends verschluckt.

Die Zuordnung „Label → Einheit" lag in drei Fassungen im Code und verhielt sich
unterschiedlich: die Wasser-Kette nannte ein unbekanntes Label, die Strom-Kette
schluckte es, und die Übernahme in die Kostenposition ließ einen Zähler ohne
`einheit_bezug` lautlos fallen. Ein verschluckter Zähler heißt: ein Verbrauch
fehlt in der Abrechnung, ohne dass es jemand sieht.

Wächter für die gemeinsame Fassung in `app/einheitenzuordnung.py`.
"""
import os
import sys
import tempfile
from datetime import date

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(),
                                     "test_einheitenzuordnung.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlmodel import Session  # noqa: E402

from app import db, einheitenzuordnung as ez  # noqa: E402
from app.models import (Ablesung, Einheit, Kostenposition, Miete,  # noqa: E402
                        Objekt, Stromjahr, Zaehler, Zeitraum)
from app.routers import stromkette as strommodul  # noqa: E402
from app.routers.zaehler import (ANFANGSSTAND, UebernahmeIn,  # noqa: E402
                                 uebernehmen, wasser_detail)

START = date(2025, 1, 1)
ENDE = date(2025, 12, 31)

#: Ein Label, das im Objekt weder Einheit noch Partei ist.
FREMD = "Dachboden"

WALLBOX = {"ok": True, "anzahl": 10, "kwh": 100.0, "extern_kwh": 50.0,
           "pv_kwh": 30.0, "speicher_kwh": 20.0, "warnungen": []}


def _objekt(s: Session, slug: str) -> tuple[int, int]:
    """Ein Objekt mit zwei Einheiten (EG, OG) und einem offenen Zeitraum."""
    o = Objekt(slug=slug, name=slug, start_monat=1)
    s.add(o)
    s.commit()
    s.refresh(o)
    for bez in ("EG", "OG"):
        s.add(Einheit(objekt_id=o.id, bezeichnung=bez))
        s.add(Miete(objekt_id=o.id, einheit=bez, partei=f"{bez}-Mieter",
                    personen=2, ab_datum=START))
    z = Zeitraum(objekt_id=o.id, start=START, ende=ENDE, status="in Arbeit")
    s.add(z)
    s.commit()
    s.refresh(z)
    return o.id, z.id


def _zaehler(s: Session, oid: int, name: str, **felder) -> int:
    z = Zaehler(objekt_id=oid, name=name, **felder)
    s.add(z)
    s.commit()
    s.refresh(z)
    return z.id


def _staende(s: Session, zaehler_id: int, zid: int, menge: float) -> None:
    """Anfangsstand 0 am Periodenbeginn, Endstand `menge` am Ende."""
    s.add(Ablesung(zaehler_id=zaehler_id, datum=START, stand=0.0,
                   zeitraum_id=None, notiz=ANFANGSSTAND))
    s.add(Ablesung(zaehler_id=zaehler_id, datum=ENDE, stand=menge,
                   zeitraum_id=zid))
    s.commit()


def _genannt(warnungen: list[str], label: str) -> bool:
    return any(label in w and "keiner Einheit" in w for w in warnungen)


# --------------------------------------------------------------------------
# 1) Die gemeinsame Fassung selbst
# --------------------------------------------------------------------------

def test_zuordne_meldet_das_unbekannte_label_mit():
    """Das Unzugeordnete ist Teil des Ergebnisses — es lässt sich nicht mehr
    durch Weglassen eines Parameters verschlucken."""
    karte = {"eg": "EG", "og": "OG"}
    treffer = ez.zuordne(["EG", FREMD], karte)
    assert treffer.ziele == ["EG"]
    assert treffer.unbekannt == [FREMD]
    # Ohne jedes Ziel ist die Zuordnung falsch, aber nicht stumm.
    leer = ez.zuordne([FREMD], karte)
    assert leer.ziele == [] and leer.unbekannt == [FREMD]
    assert not leer
    # Ohne Einheiten am Objekt gibt es nichts zu normalisieren.
    roh = ez.zuordne(["Partei A", "Partei A"], {})
    assert roh.ziele == ["Partei A"] and roh.unbekannt == []


def test_zuordne_zaehler_liest_beide_felder():
    """`einheiten` hat Vorrang, `einheit_bezug` ist der Rückfall."""
    karte = {"eg": "EG"}
    mehrfach = Zaehler(objekt_id=1, name="A", einheiten=f"EG, {FREMD}")
    assert ez.zuordne_zaehler(mehrfach, karte).unbekannt == [FREMD]
    einzeln = Zaehler(objekt_id=1, name="B", einheit_bezug=FREMD)
    assert ez.zuordne_zaehler(einzeln, karte).unbekannt == [FREMD]


# --------------------------------------------------------------------------
# 2) Wasser-Kette — meldete schon immer, muss es weiter tun
# --------------------------------------------------------------------------

def test_wasser_meldet_den_unbekannten_zaehler():
    with Session(db.engine) as s:
        oid, zid = _objekt(s, "zuordnung-wasser")
        for art, betrag in (("Wasser", 300.0), ("Abwasser", 200.0),
                            ("Niederschlagswasser", 100.0)):
            s.add(Kostenposition(zeitraum_id=zid, kostenart=art, betrag=betrag))
        s.commit()
        haupt = _zaehler(s, oid, "Gesamt Wasser", art="Kaltwasser",
                         typ="gemessen", kostenart="Wasser")
        fremd = _zaehler(s, oid, "Waschmaschine Speicher", art="Waschmaschine",
                         typ="gemessen", kostenart="Wasser",
                         hauptzaehler_id=haupt, einheiten=FREMD)
        _staende(s, haupt, zid, 100.0)
        _staende(s, fremd, zid, 10.0)

        d = wasser_detail(zid, session=s)
        assert d["bereit"] is True
        assert _genannt(d["warnungen"], FREMD), d["warnungen"]


# --------------------------------------------------------------------------
# 3) Strom-Kette — hat geschluckt
# --------------------------------------------------------------------------

def _kette(s: Session, zid: int, monkeypatch) -> dict:
    monkeypatch.setattr(strommodul, "openwb_ladungen", lambda **kw: dict(WALLBOX))
    return strommodul.stromkette(zid, s)


def _stromobjekt(s: Session, slug: str) -> tuple[int, int]:
    oid, zid = _objekt(s, slug)
    s.add(Stromjahr(objekt_id=oid, jahr=2025, netz_kwh=2400.0, solar_kwh=5000.0,
                    akku_kwh=2600.0, solar_preis=0.10, akku_preis=0.20))
    s.add(Kostenposition(zeitraum_id=zid, kostenart="Strom", betrag=800.0,
                         menge=2400.0, menge_einheit="kWh", herkunft="extern"))
    s.commit()
    gesamt = _zaehler(s, oid, "Gesamt (SolarEdge)", kostenart="Strom",
                      messeinheit="kWh", typ="direkt", reihenfolge=1)
    _staende(s, gesamt, zid, 10000.0)
    return oid, zid


def test_strom_meldet_den_zaehler_ganz_ohne_einheit(monkeypatch):
    """Kein einziges auflösbares Ziel — der Zähler selbst ist der Fund."""
    with Session(db.engine) as s:
        oid, zid = _stromobjekt(s, "zuordnung-strom-ganz")
        fremd = _zaehler(s, oid, "Scheune", kostenart="Strom",
                         messeinheit="kWh", typ="direkt", einheiten=FREMD,
                         reihenfolge=2)
        _staende(s, fremd, zid, 900.0)

        d = _kette(s, zid, monkeypatch)
        assert _genannt(d["warnungen"], "Scheune"), d["warnungen"]
        assert [o["zaehler"] for o in d["schritt3"]["ohne_einheit"]] == ["Scheune"]


def test_strom_meldet_auch_ein_einzelnes_unbekanntes_ziel(monkeypatch):
    """Der eigentliche Fund: trug ein Zähler „EG" UND ein unbekanntes Label,
    ging die ganze Menge stillschweigend an EG — ohne jeden Hinweis. Die
    Wasser-Kette nennt so etwas seit N101/6."""
    with Session(db.engine) as s:
        oid, zid = _stromobjekt(s, "zuordnung-strom-teil")
        halb = _zaehler(s, oid, "Wohnungen", kostenart="Strom",
                        messeinheit="kWh", typ="direkt",
                        einheiten=f"EG,{FREMD}", reihenfolge=2)
        _staende(s, halb, zid, 900.0)

        d = _kette(s, zid, monkeypatch)
        # Gerechnet wird weiter mit dem, was zuzuordnen ist …
        assert "EG" in d["schritt3"]["je_einheit"]
        # … aber das fehlende Ziel steht als Hinweis da.
        assert _genannt(d["warnungen"], FREMD), d["warnungen"]


def test_strom_meldet_die_partei_ohne_auflösbare_einheit(monkeypatch):
    """Auch die Gewichte schluckten: eine Partei, deren Einheit sich nicht
    auflösen lässt, verlor ihr Gewicht an die übrigen — lautlos."""
    with Session(db.engine) as s:
        oid, zid = _stromobjekt(s, "zuordnung-strom-partei")
        s.add(Miete(objekt_id=oid, einheit=FREMD, partei="Fremd-Mieter",
                    personen=2, ab_datum=START))
        s.commit()
        haus = _zaehler(s, oid, "Verbrauch Haus", kostenart="Strom",
                        messeinheit="kWh", typ="direkt", einheiten="EG,OG",
                        reihenfolge=2)
        _staende(s, haus, zid, 900.0)

        d = _kette(s, zid, monkeypatch)
        assert _genannt(d["warnungen"], FREMD), d["warnungen"]


# --------------------------------------------------------------------------
# 4) Übernahme in die Kostenposition — hat geschluckt
# --------------------------------------------------------------------------

def test_uebernehmen_traegt_die_mehrfachzuordnung_mit():
    """Ein Zähler, der sein Ziel NUR über `einheiten` trägt, zählt jetzt mit.

    Vorher fiel er ganz heraus: verbucht wurde allein auf `einheit_bezug`, und
    das ist bei einem neu angelegten Zähler leer — sein Verbrauch fehlte in der
    Verteilung, gemeldet wurde er nur als „unzugeordnet" (N367). Gemeldet
    bleibt, was sich wirklich nicht auflösen lässt.

    Die Schlüssel sind PARTEI-Namen: „OG" ist die Einheit, „OG-Mieter" die
    Partei, und nur unter der findet die Abrechnung das Geld wieder."""
    with Session(db.engine) as s:
        oid, zid = _objekt(s, "zuordnung-uebernahme")
        s.add(Kostenposition(zeitraum_id=zid, kostenart="Wasser", betrag=300.0))
        s.commit()
        eg = _zaehler(s, oid, "EG Kaltwasser", kostenart="Wasser",
                      typ="gemessen", einheit_bezug="EG-Mieter")
        nur_liste = _zaehler(s, oid, "OG Kaltwasser", kostenart="Wasser",
                             typ="gemessen", einheiten="OG")
        fremd = _zaehler(s, oid, "Speicher", kostenart="Wasser",
                         typ="gemessen", einheit_bezug=FREMD)
        _staende(s, eg, zid, 40.0)
        _staende(s, nur_liste, zid, 60.0)
        _staende(s, fremd, zid, 5.0)

        r = uebernehmen(zid, UebernahmeIn(kostenart="Wasser",
                                          schluessel="verbrauch"), s)
        assert r["angewandt"] is True
        # Der Zähler mit reiner Listen-Zuordnung trägt jetzt sein Gewicht …
        assert r["anteile"]["OG-Mieter"] == 60.0
        assert "OG Kaltwasser" not in r["unzugeordnet"]
        # … und die Schlüssel sind Partei-, nicht Einheiten-Namen.
        assert "OG" not in r["anteile"] and "EG" not in r["anteile"]
        # Ein Label, das im Objekt nichts trifft, wird weiter genannt.
        assert r["unzugeordnet"] == ["Speicher"]
        assert _genannt(r["warnungen"], "Speicher"), r["warnungen"]
        # Der sauber zugeordnete Zähler bleibt unauffällig.
        assert "EG Kaltwasser" not in r["unzugeordnet"]
        assert r["anteile"]["EG-Mieter"] == 40.0
