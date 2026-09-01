"""N192 — die zwei Stromketten-Hinweise werden bearbeitbar/auflösbar:

- der Netzbetrag aus angehängten Belegen liefert die Belege jetzt als Karten
  (id, Dateiname, Betrag, Pfad) mit, damit der Nutzer sie ansehen und einen
  doppelten herausnehmen kann.
- die geeichte Rechnungsmenge lässt sich am Zeitraum eintragen (dort, wo es
  keine externe Strom-Position gibt); dann fällt der E-Auto-Satz nicht mehr
  ersatzweise auf den Verteilungssatz und der Dauerhinweis verschwindet.

Nutzt denselben Aufbau wie ``test_stromkette`` — dieselbe eine, isolierte
Test-Datenbank, damit nichts an echten Daten hängt.
"""
import os
import sys
import tempfile
from datetime import date

os.environ.setdefault("DB_PATH",
                      os.path.join(tempfile.mkdtemp(), "test_sk_hinweise.db"))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlmodel import Session, select  # noqa: E402

from app import db  # noqa: E402
from app.models import (Ablesung, Dokument, Einheit, Kostenposition,  # noqa: E402
                        Miete, Objekt, Stromjahr, Zaehler, Zeitraum)
from app.routers import stromkette as modul  # noqa: E402

START = date(2024, 10, 1)
ENDE = date(2025, 9, 30)
WALLBOX = {"ok": True, "anzahl": 81, "kwh": 1373.84, "extern_kwh": 522.34,
           "pv_kwh": 444.94, "speicher_kwh": 383.25, "warnungen": []}


def _objekt_mit_zwei_belegen(slug: str) -> int:
    """Wie das echte Objekt: der Netzbetrag stammt aus ZWEI Zeitraum-Belegen
    (die Rechnung + eine reine Abschlags-PDF), es gibt KEINE bestätigte externe
    Strom-Position — genau der Fall, der den ersten Hinweis auslöst."""
    with Session(db.engine) as s:
        o = Objekt(slug=slug, name=slug, start_monat=10)
        s.add(o)
        s.commit()
        s.refresh(o)
        for bez, personen in (("EG", 2), ("OG", 2)):
            s.add(Einheit(objekt_id=o.id, bezeichnung=bez))
            s.add(Miete(objekt_id=o.id, einheit=bez, partei=f"{bez}-Mieter",
                        personen=personen, ab_datum=START))
        z = Zeitraum(objekt_id=o.id, start=START, ende=ENDE, status="in Arbeit")
        s.add(z)
        s.commit()
        s.refresh(z)
        s.add(Stromjahr(objekt_id=o.id, jahr=2025, netz_kwh=2592.0,
                        solar_kwh=5400.0, akku_kwh=2808.0))
        s.add(Dokument(pfad=f"/{slug}/rechnung.pdf", dateiname="rechnung.pdf",
                       objekt_id=o.id, zeitraum_id=z.id, kategorie="Nebenkosten",
                       kostenart="Strom", betrag=862.51,
                       belegdatum=date(2025, 6, 1)))
        s.add(Dokument(pfad=f"/{slug}/abschlaege.pdf", dateiname="abschlaege.pdf",
                       objekt_id=o.id, zeitraum_id=z.id, kategorie="Nebenkosten",
                       kostenart="Strom", betrag=32.86))
        gesamt = Zaehler(objekt_id=o.id, name="Gesamt (SolarEdge)",
                         kostenart="Strom", messeinheit="kWh", typ="direkt",
                         reihenfolge=1)
        s.add(gesamt)
        s.commit()
        s.refresh(gesamt)
        s.add(Zaehler(objekt_id=o.id, name="Verbrauch Haus — errechnet",
                      kostenart="Strom", messeinheit="kWh", typ="rest",
                      hauptzaehler_id=gesamt.id, einheiten="EG,OG",
                      reihenfolge=2))
        s.commit()
        s.add(Ablesung(zaehler_id=gesamt.id, datum=ENDE, stand=10800.0,
                       zeitraum_id=z.id))
        s.commit()
        return z.id


def _kette(zid: int, monkeypatch) -> dict:
    monkeypatch.setattr(modul, "openwb_ladungen", lambda **kw: WALLBOX)
    with Session(db.engine) as s:
        return modul.stromkette(session=s, z=s.get(Zeitraum, zid))


def test_netz_belege_kommen_als_karten_mit(monkeypatch):
    """Der Netzbetrag stammt aus zwei Belegen — beide kommen als Karten mit
    id, Dateiname und Betrag, damit der Hinweis sie ansehen/herausnehmen kann."""
    zid = _objekt_mit_zwei_belegen("sk-belege")
    d = _kette(zid, monkeypatch)
    belege = d["schritt1"]["netz_belege"]

    assert len(belege) == 2
    namen = {b["dateiname"] for b in belege}
    assert namen == {"rechnung.pdf", "abschlaege.pdf"}
    for b in belege:
        assert isinstance(b["id"], int) and b["id"] > 0
        assert b["pfad"].endswith(".pdf")
        assert b["aus_position"] is False
    # Der Warnhinweis steht weiter für den Fall, dass die UI ihn nicht auflöst.
    assert any("angehängten Beleg" in w for w in d["warnungen"])


def test_beleg_geloest_verschwindet_aus_dem_netzbetrag(monkeypatch):
    """Wird der (doppelte) Abschlags-Beleg aus dem Zeitraum genommen, sinkt der
    Netzbetrag auf den der echten Rechnung und die Liste zeigt nur noch ihn."""
    zid = _objekt_mit_zwei_belegen("sk-belege-loesen")
    d = _kette(zid, monkeypatch)
    assert d["schritt1"]["netz"]["betrag"] == 895.37   # 862,51 + 32,86

    # So löst die App den Beleg: die Zuordnung zum Zeitraum wird entfernt (die
    # Datei bleibt in der Cloud). Hier direkt in der DB nachgestellt.
    with Session(db.engine) as s:
        weg = s.exec(select(Dokument).where(
            Dokument.zeitraum_id == zid,
            Dokument.dateiname == "abschlaege.pdf")).first()
        weg.zeitraum_id = None
        s.add(weg)
        s.commit()

    d = _kette(zid, monkeypatch)
    belege = d["schritt1"]["netz_belege"]
    assert [b["dateiname"] for b in belege] == ["rechnung.pdf"]
    assert d["schritt1"]["netz"]["betrag"] == 862.51


def test_geeichte_menge_am_zeitraum_loest_den_hinweis(monkeypatch):
    """Ohne geeichte Menge warnt die Kette und der E-Auto-Satz gleicht dem
    Verteilungssatz. Wird die geeichte Menge am Zeitraum gesetzt, verschwindet
    der Hinweis und der geeichte Satz weicht (kleiner, weil größere Menge) ab."""
    zid = _objekt_mit_zwei_belegen("sk-geeicht")

    d = _kette(zid, monkeypatch)
    s1 = d["schritt1"]
    assert s1["geeichte_menge"] == 0
    assert s1["netz_preis_geeicht"] == s1["netz_preis"]
    assert any("geeichte Rechnungsmenge" in w for w in d["warnungen"])

    with Session(db.engine) as s:
        modul.strom_rechnungsmenge_setzen({"rechnung_kwh": 4021.0}, session=s, z=s.get(Zeitraum, zid))

    d = _kette(zid, monkeypatch)
    s1 = d["schritt1"]
    assert s1["geeichte_menge"] == 4021.0
    assert s1["netz_preis_geeicht"] < s1["netz_preis"]
    assert not any("geeichte Rechnungsmenge" in w for w in d["warnungen"])
    # Cent-genau bleibt die Kontrollsumme stehen.
    assert d["kontrolle"]["stimmt"] is True


def test_geeichte_menge_zuruecksetzbar(monkeypatch):
    """0 (oder leer) nimmt die geeichte Menge wieder zurück — der Hinweis kommt
    zurück, nichts stürzt ab."""
    zid = _objekt_mit_zwei_belegen("sk-geeicht-zurueck")
    with Session(db.engine) as s:
        modul.strom_rechnungsmenge_setzen({"rechnung_kwh": 4021.0}, session=s, z=s.get(Zeitraum, zid))
        r = modul.strom_rechnungsmenge_setzen({"rechnung_kwh": ""}, session=s, z=s.get(Zeitraum, zid))
    assert r == {"ok": True, "rechnung_kwh": 0.0}

    d = _kette(zid, monkeypatch)
    assert d["schritt1"]["geeichte_menge"] == 0
    assert any("geeichte Rechnungsmenge" in w for w in d["warnungen"])
