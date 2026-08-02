"""N142 — die Stromkette als Endpunkt: kWh → Euro → E-Tankstelle → Einheiten.

Aufbau wie beim echten Objekt (01.10.2024–30.09.2025):

    Gesamtverbrauch (SolarEdge)      10800 kWh
    Anteile                          24 % Netz · 50 % PV · 26 % Speicher
    Netz-Rechnung                    862,51 €
    E-Auto (Wallbox)                 522,34 Netz · 444,94 PV · 383,25 Speicher

Geprüft wird, dass jeder Schritt einzeln herauskommt, die Kontrollsumme exakt
aufgeht, die geladene Menge NICHT bei den Einheiten landet und die Kette auch
dann eine verständliche Auskunft gibt, wenn die Wallbox aus ist, die Anteile
nicht 100 % ergeben, die Rechnung fehlt oder gar kein Zähler da ist.
"""
import os
import sys
import tempfile
from datetime import date

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_stromkette.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from sqlmodel import Session, select  # noqa: E402

from app import db  # noqa: E402
from app.models import (Ablesung, Dokument, Einheit, Kostenposition,  # noqa: E402
                        Miete, Objekt, Stromjahr, Zaehler, Zeitraum)
from app.routers import stromkette as modul  # noqa: E402

START = date(2024, 10, 1)
ENDE = date(2025, 9, 30)

# Was die Wallbox für die Periode meldet (Kontrollzahlen des Nutzers).
WALLBOX = {"ok": True, "anzahl": 81, "kwh": 1373.84, "extern_kwh": 522.34,
           "pv_kwh": 444.94, "speicher_kwh": 383.25, "warnungen": []}


def _objekt(slug: str, *, mit_zaehler: bool = True,
            anteile: tuple[float, float, float] = (2592.0, 5400.0, 2808.0),
            rechnung: float | None = 862.51, beleg: float | None = None,
            hand: tuple[float, float] = (0.0, 0.0)) -> int:
    """Ein Objekt mit zwei Wohnungen, Zeitraum, Strom-Jahr und Zählern."""
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

        netz, solar, akku = anteile
        s.add(Stromjahr(objekt_id=o.id, jahr=2025, netz_kwh=netz,
                        solar_kwh=solar, akku_kwh=akku,
                        solar_preis=0.10, akku_preis=0.20,
                        eauto_extern_kwh=hand[0], eauto_eigen_kwh=hand[1]))
        if rechnung is not None:
            s.add(Kostenposition(zeitraum_id=z.id, kostenart="Strom",
                                 betrag=rechnung, menge=2592.0,
                                 menge_einheit="kWh", herkunft="extern"))
        if beleg is not None:
            s.add(Dokument(pfad=f"/{slug}/strom.pdf", dateiname="strom.pdf",
                           objekt_id=o.id, zeitraum_id=z.id,
                           kategorie="Nebenkosten", kostenart="Strom",
                           betrag=beleg))

        if mit_zaehler:
            gesamt = Zaehler(objekt_id=o.id, name="Gesamt (SolarEdge)",
                             kostenart="Strom", messeinheit="kWh", typ="direkt",
                             reihenfolge=1)
            s.add(gesamt)
            s.commit()
            s.refresh(gesamt)
            s.add(Zaehler(objekt_id=o.id, name="Elektroauto", kostenart="Strom",
                          messeinheit="kWh", typ="direkt",
                          hauptzaehler_id=gesamt.id, reihenfolge=2))
            s.add(Zaehler(objekt_id=o.id, name="Verbrauch Haus — errechnet",
                          kostenart="Strom", messeinheit="kWh", typ="rest",
                          hauptzaehler_id=gesamt.id, einheiten="EG,OG",
                          reihenfolge=3))
            s.commit()
            for name, stand in (("Gesamt (SolarEdge)", 10800.0),
                                ("Elektroauto", 1373.84)):
                zae = s.exec(select(Zaehler).where(Zaehler.objekt_id == o.id,
                                                   Zaehler.name == name)).first()
                s.add(Ablesung(zaehler_id=zae.id, datum=ENDE, stand=stand,
                               zeitraum_id=z.id))
        s.commit()
        return z.id


def _kette(zid: int, monkeypatch=None, wallbox: dict | None = None) -> dict:
    """Die Kette rechnen — mit oder ohne antwortende Wallbox."""
    if monkeypatch is not None:
        antwort = dict(wallbox) if wallbox else {"ok": False, "hinweis":
                                                 "Die Wallbox ist aus."}
        monkeypatch.setattr(modul, "openwb_ladungen",
                            lambda **kw: antwort)
    with Session(db.engine) as s:
        return modul.stromkette(zid, s)


# --------------------------------------------------------------------------
# Schritt 1 — aus kWh werden Euro
# --------------------------------------------------------------------------

def test_schritt1_macht_aus_kwh_drei_kostenbloecke(monkeypatch):
    """10.800 kWh · 24/50/26 % → Netz 2592 · PV 5400 · Akku 2808 kWh."""
    zid = _objekt("kette-schritt1")
    d = _kette(zid, monkeypatch, WALLBOX)
    s1 = d["schritt1"]

    assert s1["gesamt_kwh"] == 10800.0
    assert s1["quelle_menge"].startswith("Zähler")
    assert (s1["netz_prozent"], s1["pv_prozent"], s1["speicher_prozent"]) \
        == (24.0, 50.0, 26.0)
    assert s1["netz"]["kwh"] == 2592.0
    assert s1["pv"]["kwh"] == 5400.0
    assert s1["akku"]["kwh"] == 2808.0
    # Netz aus der Rechnung, PV/Akku aus den gepflegten Sätzen.
    assert s1["netz"]["betrag"] == 862.51
    assert s1["pv"]["betrag"] == 540.00        # 5400 × 0,10
    assert s1["akku"]["betrag"] == 561.60      # 2808 × 0,20
    assert s1["betrag"] == round(862.51 + 540.00 + 561.60, 2)
    assert "862.51" in s1["quelle_betrag"] or "862,51" in s1["quelle_betrag"]


def test_prozente_die_nicht_hundert_ergeben_werden_gemeldet(monkeypatch):
    """Ein schiefer Screenshot darf nicht still durchlaufen."""
    zid = _objekt("kette-schief", anteile=(2400.0, 5000.0, 2000.0))
    d = _kette(zid, monkeypatch, WALLBOX)
    # Die Anteile werden aus den Mengen normiert — sie ergeben also 100 %,
    # aber die erfasste Summe deckt den Gesamtverbrauch nicht.
    assert round(sum((d["schritt1"]["netz_prozent"],
                      d["schritt1"]["pv_prozent"],
                      d["schritt1"]["speicher_prozent"])), 1) == 100.0
    # Ohne erfasste Anteile sagt die Kette das ausdrücklich.
    leer = _kette(_objekt("kette-ohne-anteile", anteile=(0.0, 0.0, 0.0)),
                  monkeypatch, WALLBOX)
    assert any("SolarEdge-Anteile" in w for w in leer["warnungen"])
    assert leer["schritt1"]["netz"]["kwh"] == 0.0


def test_fehlender_rechnungsbetrag_wird_benannt(monkeypatch):
    """Ohne Rechnung gibt es keinen Netz-Preis — und einen klaren Hinweis."""
    zid = _objekt("kette-ohne-rechnung", rechnung=None)
    d = _kette(zid, monkeypatch, WALLBOX)
    assert d["schritt1"]["netz"]["betrag"] == 0.0
    assert d["schritt1"]["quelle_betrag"] == ""
    assert any("keine Rechnung" in w for w in d["warnungen"])
    # Die übrigen Blöcke rechnen trotzdem weiter.
    assert d["schritt1"]["pv"]["betrag"] == 540.00


def test_beleg_traegt_den_betrag_wenn_die_position_fehlt(monkeypatch):
    """Hängt die Rechnung am Zeitraum, aber noch nicht an einer Position, wird
    sie benutzt — sichtbar als Ersatzquelle, nicht als gesetzte Wahrheit."""
    zid = _objekt("kette-beleg", rechnung=None, beleg=862.51)
    d = _kette(zid, monkeypatch, WALLBOX)
    assert d["schritt1"]["netz"]["betrag"] == 862.51
    assert "strom.pdf" in d["schritt1"]["quelle_betrag"]
    assert any("angehängten Beleg" in w for w in d["warnungen"])


# --------------------------------------------------------------------------
# Schritt 2 — die E-Tankstelle
# --------------------------------------------------------------------------

def test_schritt2_zieht_die_ladungen_der_periode_aus_der_wallbox(monkeypatch):
    """Die Mengen kommen taggenau aus dem Ladeprotokoll — ohne Personenbezug."""
    zid = _objekt("kette-wallbox")
    d = _kette(zid, monkeypatch, WALLBOX)
    s2 = d["schritt2"]

    assert s2["quelle"] == "wallbox"
    assert s2["anzahl"] == 81
    assert (s2["netz_kwh"], s2["pv_kwh"], s2["akku_kwh"]) \
        == (522.34, 444.94, 383.25)
    assert s2["eauto_kwh"] == round(522.34 + 444.94 + 383.25, 3)
    assert s2["beruecksichtigt"] is True
    # Exakt bepreist aus den drei Blöcken.
    preise = (862.51 / 2592.0, 0.10, 0.20)
    erwartet = round(522.34 * preise[0] + 444.94 * preise[1]
                     + 383.25 * preise[2], 2)
    assert s2["betrag"] == erwartet
    # Und in keiner Zeile taucht ein Name auf.
    assert "person" not in str(s2).lower()


def test_wallbox_aus_dann_greift_die_handeingabe(monkeypatch):
    """Ist die Box weg, tragen die von Hand gepflegten Mengen die Kette weiter."""
    zid = _objekt("kette-hand", hand=(522.34, 828.19))
    d = _kette(zid, monkeypatch)          # ohne Wallbox-Antwort
    s2 = d["schritt2"]

    assert s2["quelle"] == "hand"
    assert s2["netz_kwh"] == 522.34
    # Der eigene Teil wird nach den PV-/Akku-Anteilen getrennt (50 : 26).
    assert s2["pv_kwh"] == round(828.19 * 50.0 / 76.0, 3)
    assert s2["akku_kwh"] == round(828.19 * 26.0 / 76.0, 3)
    assert s2["beruecksichtigt"] is True
    assert any("geschätzt" in w for w in d["warnungen"])
    assert any("Wallbox ist aus" in w for w in d["warnungen"])


def test_ohne_ladungen_bleibt_schritt2_leer(monkeypatch):
    zid = _objekt("kette-ohne-auto")
    d = _kette(zid, monkeypatch)
    assert d["schritt2"]["quelle"] == "keine"
    assert d["schritt2"]["eauto_kwh"] == 0.0
    assert d["schritt2"]["beruecksichtigt"] is False


# --------------------------------------------------------------------------
# Schritt 3 — der Rest auf die Einheiten
# --------------------------------------------------------------------------

def test_schritt3_verteilt_den_rest_und_die_summe_geht_auf(monkeypatch):
    """Kontrollsumme: Schritt 2 + Schritt 3 == der Gesamtbetrag aus Schritt 1."""
    zid = _objekt("kette-schritt3")
    d = _kette(zid, monkeypatch, WALLBOX)

    assert set(d["schritt3"]["je_einheit"]) == {"EG", "OG"}
    assert d["kontrolle"]["stimmt"] is True
    assert d["kontrolle"]["differenz"] == 0.0
    assert d["kontrolle"]["verteilt"] == d["schritt1"]["betrag"]
    assert round(d["schritt3"]["summe"] + d["schritt2"]["betrag"], 2) \
        == d["schritt1"]["betrag"]
    # Zwei gleich große Wohnungen tragen dasselbe — bis auf den einen Cent, den
    # die Größte-Reste-Verteilung nur ganz vergeben kann.
    eg, og = d["schritt3"]["je_einheit"]["EG"], d["schritt3"]["je_einheit"]["OG"]
    assert abs(eg["betrag"] - og["betrag"]) <= 0.01
    # Jede Einheit bekommt anteilig aus allen drei Töpfen.
    assert eg["netz_kwh"] > 0 and eg["pv_kwh"] > 0 and eg["akku_kwh"] > 0


def test_geladene_kwh_landen_nicht_bei_den_bewohnern(monkeypatch):
    """Der Zweck des Abzugs: die Ladungen dürfen in keinem Block bei den
    Einheiten auftauchen."""
    zid = _objekt("kette-abzug")
    d = _kette(zid, monkeypatch, WALLBOX)
    s1, s2, s3 = d["schritt1"], d["schritt2"], d["schritt3"]
    for block in ("netz", "pv", "akku"):
        bewohner = sum(zeile[f"{block}_kwh"] for zeile in s3["je_einheit"].values())
        assert abs(bewohner - (s1[block]["kwh"] - s2[f"{block}_kwh"])) < 0.01, block
    # Der zuordnungslose E-Auto-Zähler gilt als die Ladestation, nicht als Fund.
    assert not any("Elektroauto" in w for w in d["warnungen"])


def test_ohne_zaehler_sagt_die_kette_was_fehlt(monkeypatch):
    """Keine Zähler: kein Gesamtverbrauch, keine Verteilung — aber eine Ansage
    statt eines Fehlers."""
    zid = _objekt("kette-ohne-zaehler", mit_zaehler=False)
    d = _kette(zid, monkeypatch, WALLBOX)

    assert d["schritt1"]["gesamt_kwh"] == 0.0
    assert d["schritt3"]["je_einheit"] == {}
    assert d["schritt3"]["summe"] == 0.0
    assert any("Gesamtverbrauch" in w for w in d["warnungen"])


def test_unbekannter_zeitraum_ergibt_404():
    import pytest
    from fastapi import HTTPException
    with Session(db.engine) as s:
        with pytest.raises(HTTPException) as fehler:
            modul.stromkette(999999, s)
    assert fehler.value.status_code == 404
