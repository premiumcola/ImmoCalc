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
            kp = Kostenposition(zeitraum_id=z.id, kostenart="Strom",
                                betrag=rechnung, menge=2592.0,
                                menge_einheit="kWh", herkunft="extern")
            s.add(kp)
            s.commit()
            s.refresh(kp)
            # Der Beleg hängt an der Position — die Herkunft des Netzbetrags
            # soll ihn mit ausweisen.
            s.add(Dokument(pfad=f"/{slug}/netzrechnung.pdf",
                           dateiname="netzrechnung.pdf", objekt_id=o.id,
                           zeitraum_id=z.id, position_id=kp.id,
                           kategorie="Nebenkosten", kostenart="Strom"))
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
    # Gehen die Anteile auf, sind Eingabe und Rechnung dieselben Zahlen.
    assert (s1["netz_erfasst"], s1["pv_erfasst"], s1["speicher_erfasst"]) \
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
    """Ein schiefer Screenshot darf nicht still durchlaufen. 2400+5000+2000 sind
    nur 9400 der 10.800 kWh — das sind 87 %, nicht 100 %."""
    zid = _objekt("kette-schief", anteile=(2400.0, 5000.0, 2000.0))
    d = _kette(zid, monkeypatch, WALLBOX)
    assert any("87 %" in w for w in d["warnungen"]), d["warnungen"]
    # Die Eingabefelder zeigen unverändert, was eingetragen wurde …
    assert d["schritt1"]["netz_erfasst"] == round(2400 / 10800 * 100, 2)
    assert d["schritt1"]["erfasst_summe"] == round(9400 / 10800 * 100, 2)
    # … verteilt wird trotzdem auf den vollen Verbrauch, sonst fehlte Geld.
    assert round(sum((d["schritt1"]["netz_prozent"],
                      d["schritt1"]["pv_prozent"],
                      d["schritt1"]["speicher_prozent"])), 1) == 100.0
    assert d["schritt1"]["netz"]["kwh"] + d["schritt1"]["pv"]["kwh"] \
        + d["schritt1"]["akku"]["kwh"] == 10800.0
    assert d["kontrolle"]["stimmt"] is True


def test_ohne_erfasste_anteile_sagt_die_kette_was_fehlt(monkeypatch):
    leer = _kette(_objekt("kette-ohne-anteile", anteile=(0.0, 0.0, 0.0)),
                  monkeypatch, WALLBOX)
    assert any("SolarEdge-Anteile" in w for w in leer["warnungen"])
    assert leer["schritt1"]["netz"]["kwh"] == 0.0


def test_fehlender_rechnungsbetrag_ist_null_nicht_null_euro(monkeypatch):
    """Ohne Rechnung gibt es keinen Netz-Preis — und einen klaren Hinweis.

    Der Betrag ist ausdrücklich ``None``, nicht 0.0: eine Null läse sich wie
    „der Netzstrom kostet nichts". Dass die Rechnung fehlt, ist etwas anderes."""
    zid = _objekt("kette-ohne-rechnung", rechnung=None)
    d = _kette(zid, monkeypatch, WALLBOX)
    assert d["schritt1"]["netz"]["betrag"] is None
    assert d["schritt1"]["netz"]["preis"] is None
    assert d["schritt1"]["netz"]["herkunft"]["kostenart"] == ""
    assert d["schritt1"]["quelle_betrag"] == ""
    assert d["schritt1"]["vollstaendig"] is False
    assert any("keine Rechnung" in w for w in d["warnungen"])
    # Die übrigen Blöcke rechnen trotzdem weiter — die Kette reißt nicht ab.
    assert d["schritt1"]["pv"]["betrag"] == 540.00
    assert d["kontrolle"]["stimmt"] is True


def test_ohne_gepflegten_satz_gilt_zehn_prozent_unter_dem_netzpreis(monkeypatch):
    """N158 — feste Vorgabe des Betreibers: der eigene Strom wird 10 % unter dem
    Durchschnittspreis des Netzbezugs (inkl. Grundgebühr) verkauft.

    Das loest die frühere Regel ab, nach der PV und Akku ohne gepflegten Satz
    ganz ohne Betrag blieben. Bewusste Fachlogik-Aenderung: der Preis ist jetzt
    ableitbar, also gibt es keinen Grund mehr fuer eine Luecke — und es ist
    derselbe Satz, den auch die E-Tankstelle abrechnet."""
    zid = _objekt("kette-ohne-eigenpreis")
    with Session(db.engine) as s:
        sj = s.exec(select(Stromjahr).where(Stromjahr.jahr == 2025)).all()[-1]
        sj.solar_preis, sj.akku_preis = 0.0, 0.0
        s.add(sj)
        s.commit()
    d = _kette(zid, monkeypatch, WALLBOX)
    netz = d["schritt1"]["netz"]
    pv = d["schritt1"]["pv"]
    assert netz["betrag"] == 862.51
    # 10 % unter dem Netzpreis — und zwar fuer PV wie Akku gleichermassen.
    erwartet = round(netz["preis"] * 0.9, 5)
    assert abs(pv["preis"] - erwartet) < 1e-5, (pv["preis"], erwartet)
    assert abs(d["schritt1"]["akku"]["preis"] - erwartet) < 1e-5
    assert pv["betrag"] == round(pv["kwh"] * erwartet, 2)
    assert d["schritt1"]["vollstaendig"] is True
    assert not any("kein Preis" in w for w in d["warnungen"])


def test_ohne_netzpreis_bleibt_der_eigene_strom_ohne_betrag(monkeypatch):
    """Die 10-%-Regel braucht einen Bezugspunkt: steht der Netzpreis nicht fest,
    laesst sich auch der eigene Strom nicht bepreisen. Dann `null` statt 0 €."""
    zid = _objekt("kette-ohne-netzpreis")
    with Session(db.engine) as s:
        sj = s.exec(select(Stromjahr).where(Stromjahr.jahr == 2025)).all()[-1]
        sj.solar_preis, sj.akku_preis = 0.0, 0.0
        s.add(sj)
        s.commit()
        for p in s.exec(select(Kostenposition)
                        .where(Kostenposition.zeitraum_id == zid)).all():
            p.betrag = 0.0
            s.add(p)
        s.commit()
    d = _kette(zid, monkeypatch, WALLBOX)
    assert d["schritt1"]["pv"]["betrag"] is None
    assert d["schritt1"]["akku"]["betrag"] is None
    assert d["schritt1"]["vollstaendig"] is False


def test_jeder_block_nennt_seine_herkunft(monkeypatch):
    """Der Nutzer will die Herkunft jeder Zahl sehen: aus welcher Kostenposition
    der Betrag stammt und welcher Beleg daran hängt."""
    zid = _objekt("kette-herkunft")
    d = _kette(zid, monkeypatch, WALLBOX)
    s1 = d["schritt1"]

    assert s1["netz"]["herkunft"]["kostenart"] == "Strom"
    assert s1["netz"]["herkunft"]["beleg"] == "netzrechnung.pdf"
    assert "862,51" in s1["netz"]["herkunft"]["text"]
    # PV und Akku kommen aus den Sätzen am Strom-Jahr — jede Zeile nennt ihren
    # EIGENEN Satz, nicht beide. Sonst stünde dieselbe Angabe zweimal da.
    assert s1["pv"]["herkunft"]["kostenart"] == "Strom-Jahr"
    assert s1["pv"]["herkunft"]["text"] == "Satz am Strom-Jahr: 10,00 ct/kWh"
    assert s1["akku"]["herkunft"]["text"] == "Satz am Strom-Jahr: 20,00 ct/kWh"
    assert s1["pv"]["herkunft"]["text"] != s1["akku"]["herkunft"]["text"]
    assert s1["vollstaendig"] is True


def test_beleg_traegt_den_betrag_wenn_die_position_fehlt(monkeypatch):
    """Hängt die Rechnung am Zeitraum, aber noch nicht an einer Position, wird
    sie benutzt — sichtbar als Ersatzquelle, nicht als gesetzte Wahrheit."""
    zid = _objekt("kette-beleg", rechnung=None, beleg=862.51)
    d = _kette(zid, monkeypatch, WALLBOX)
    assert d["schritt1"]["netz"]["betrag"] == 862.51
    assert "strom.pdf" in d["schritt1"]["quelle_betrag"]
    assert d["schritt1"]["netz"]["herkunft"]["beleg"] == "strom.pdf"
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
    # N173 — das E-Auto wird zum GEEICHTEN Satz bepreist, nicht zum
    # Durchschnittspreis der drei Blöcke. Bewusste Fachlogik-Änderung: so rechnet
    # auch die Tankstelle die Fahrer ab (Netz zum geeichten Satz, eigener Strom
    # 10 % darunter) — Kette und Fahrer-Abrechnung ergeben dieselbe Summe. Die
    # geeichte Menge (Kostenposition.menge = 2592) fällt hier mit der
    # SolarEdge-Netzmenge zusammen, der geeichte Netzsatz also mit dem
    # Verteilungssatz; der Unterschied liegt allein im eigenen Strom (10 % statt
    # der Blockpreise 0,10/0,20).
    netz_g = round(862.51 / 2592.0, 5)
    eigen_g = round(netz_g * 0.9, 5)
    erwartet = (round(522.34 * netz_g, 2) + round(444.94 * eigen_g, 2)
                + round(383.25 * eigen_g, 2))
    assert s2["betrag"] == round(erwartet, 2)
    # Und in keiner Zeile taucht ein Name auf.
    assert "person" not in str(s2).lower()


def _ohne_eauto_stand(zid):
    """N166 — die vom Aufbau angelegte „Elektroauto"-Ablesung entfernen, damit
    der Zaehler-Stand nicht greift und der jeweils getestete Rueckfall
    (Handeingabe bzw. leer) zum Zug kommt."""
    with Session(db.engine) as s:
        z = s.get(Zeitraum, zid)
        for zae in s.exec(select(Zaehler).where(
                Zaehler.objekt_id == z.objekt_id)).all():
            if "Elektroauto" in zae.name or (zae.art or "") == "E-Tankstelle":
                for a in s.exec(select(Ablesung).where(
                        Ablesung.zaehler_id == zae.id)).all():
                    s.delete(a)
        s.commit()


def test_wallbox_aus_dann_greift_die_handeingabe(monkeypatch):
    """Ist die Box weg, tragen die von Hand gepflegten Mengen die Kette weiter."""
    zid = _objekt("kette-hand", hand=(522.34, 828.19))
    _ohne_eauto_stand(zid)                 # kein Zaehler-Stand -> Hand greift
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
    _ohne_eauto_stand(zid)                 # kein Zaehler-Stand, keine Ladungen
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
    zid = _objekt("kette-ohne-zaehler", mit_zaehler=False, anteile=(0.0, 0.0, 0.0))
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


def test_wallbox_aus_dann_zaehlt_der_eauto_zaehlerstand(monkeypatch):
    """N166 — ist die Box stumm, nimmt die Kette den Stand des E-Tankstellen-
    Zählers (dieselbe Zahl wie die Zählermaske), nicht die erfassten Ladungen
    oder die Handeingabe. Sonst zeigten Maske und Kette zwei Mengen."""
    zid = _objekt("kette-eauto-zaehler", hand=(999.0, 999.0))  # Hand absichtlich anders
    with Session(db.engine) as s:
        z = s.get(Zeitraum, zid)
        zae = Zaehler(objekt_id=z.objekt_id, name="Stromverbrauch E-Tankstelle",
                      kostenart="Strom", messeinheit="kWh", typ="direkt",
                      art="E-Tankstelle")
        s.add(zae)
        s.commit()
        s.refresh(zae)
        # Der aus der Box gezogene Stand, als Ablesung des Zeitraums abgelegt.
        s.add(Ablesung(zaehler_id=zae.id, datum=ENDE, stand=1373.84,
                       zeitraum_id=zid))
        s.commit()

    d = _kette(zid, monkeypatch)          # ohne Wallbox-Antwort
    s2 = d["schritt2"]
    assert s2["quelle"] == "zaehler"
    assert s2["gemessen_kwh"] == 1373.84
    # Aufgeteilt nach den SolarEdge-Anteilen (Netz 24 %, PV 50 %, Akku 26 %).
    assert s2["netz_kwh"] == round(1373.84 * 24.0 / 100.0, 3)
    # Die Handeingabe (999/999) darf NICHT gewonnen haben.
    assert s2["netz_kwh"] != 999.0


def _geeichte_menge_setzen(zid: int, menge: float) -> None:
    """Die geeichte Rechnungsmenge an der externen Strom-Position setzen (N173).

    Der Aufbau (`_objekt`) legt sie mit menge == SolarEdge-Netzmenge an, sodass
    beide Sätze zusammenfallen. Für die N173-Fälle muss sie abweichen — das
    ist der Sinn der zwei Sätze."""
    with Session(db.engine) as s:
        kp = s.exec(select(Kostenposition).where(
            Kostenposition.zeitraum_id == zid,
            Kostenposition.herkunft == "extern")).first()
        kp.menge = menge
        s.add(kp)
        s.commit()


def test_n173_zwei_netzsaetze_verteilung_und_geeicht(monkeypatch):
    """N173 — der Netzstrom trägt zwei ct/kWh-Werte für zwei Zwecke:

    - Verteilung (Mieter): voller Netzbetrag ÷ SolarEdge-Netzmenge (2.910 kWh).
    - geeicht (E-Auto):     voller Netzbetrag ÷ geeichte Rechnungsmenge (4.021).

    1.499,34 € / 4.021 kWh = 0,3729 €/kWh — der geeichte Satz (exakter
    Referenztest). Er ist günstiger als der Verteilungssatz, weil die geeichte
    Menge größer ist als die am Wechselrichter gemessene."""
    zid = _objekt("kette-n173", anteile=(2910.0, 5400.0, 2490.0),
                  rechnung=1499.34)
    _geeichte_menge_setzen(zid, 4021.0)
    # Wie im echten Objekt: keine gepflegten PV/Akku-Sätze, also folgt der eigene
    # Strom der 10-%-Regel unter dem Verteilungssatz (N158) — nicht künstlich
    # billige Blockpreise wie im Aufbau-Standard.
    with Session(db.engine) as s:
        sj = s.exec(select(Stromjahr).where(Stromjahr.jahr == 2025)).all()[-1]
        sj.solar_preis, sj.akku_preis = 0.0, 0.0
        s.add(sj)
        s.commit()
    d = _kette(zid, monkeypatch, WALLBOX)
    s1 = d["schritt1"]

    # SolarEdge-Netzmenge: ~2910 kWh (die Prozent-Rundung driftet um Bruchteile).
    assert abs(s1["netz"]["kwh"] - 2910.0) < 1.0
    assert s1["geeichte_menge"] == 4021.0
    # Verteilungssatz auf die SolarEdge-Menge (~0,5152) …
    assert s1["netz_preis"] == round(1499.34 / s1["netz"]["kwh"], 5)
    assert abs(s1["netz_preis"] - 0.5152) < 0.001
    # … geeichter Satz auf die Rechnungsmenge (exakt 0,3729).
    assert round(s1["netz_preis_geeicht"], 4) == 0.3729
    assert s1["netz_preis_geeicht"] < s1["netz_preis"]

    # Cent-genau: E-Auto + Einheiten == der volle Strombetrag, kein Cent
    # entsteht oder verschwindet durch die zwei Sätze.
    assert d["kontrolle"]["stimmt"] is True
    assert d["kontrolle"]["differenz"] == 0.0
    assert d["kontrolle"]["verteilt"] == s1["betrag"]

    # Das E-Auto ist günstiger als der Mieter-Mischpreis — genau der Effekt, den
    # der geeichte (kleinere) Netzsatz erzeugt.
    s2, s3 = d["schritt2"], d["schritt3"]
    eauto_preis = s2["betrag"] / s2["eauto_kwh"]
    eg = s3["je_einheit"]["EG"]
    mieter_preis = eg["betrag"] / eg["kwh"]
    assert eauto_preis < mieter_preis


def test_n173_ohne_geeichte_menge_faellt_auf_die_verteilung(monkeypatch):
    """N173 — fehlt die geeichte Rechnungsmenge, nutzt der E-Auto-Satz
    ersatzweise den Verteilungssatz (auf SolarEdge-Menge), mit Hinweis und ohne
    Absturz. Nie eine Null."""
    zid = _objekt("kette-n173-ohne", anteile=(2910.0, 5400.0, 2490.0),
                  rechnung=1499.34)
    _geeichte_menge_setzen(zid, 0.0)
    d = _kette(zid, monkeypatch, WALLBOX)
    s1 = d["schritt1"]

    assert s1["geeichte_menge"] == 0.0
    assert s1["netz_preis_geeicht"] == s1["netz_preis"]
    assert s1["netz_preis_geeicht"] is not None
    assert any("geeichte Rechnungsmenge" in w for w in d["warnungen"])
    assert d["kontrolle"]["stimmt"] is True


def test_ohne_gesamtwert_zaehlt_die_summe_der_drei_mengen(monkeypatch):
    """N167 — sind nur die drei SolarEdge-Mengen erfasst (kein Gesamtzähler,
    kein Jahreswert), ist ihre Summe der Gesamtverbrauch. Sonst blieben die
    Blöcke bei 0 kWh und die Kette meldete „kein Durchschnittspreis", obwohl
    Menge und Betrag da sind."""
    zid = _objekt("kette-ohne-gesamt", mit_zaehler=False,
                  anteile=(2910.0, 3595.0, 2054.0))
    with Session(db.engine) as s:
        sj = s.exec(select(Stromjahr).where(Stromjahr.jahr == 2025)).all()[-1]
        sj.gesamt_kwh = 0.0
        s.add(sj)
        s.commit()
    d = _kette(zid, monkeypatch)
    s1 = d["schritt1"]
    # Die Prozent-Umrechnung driftet um Bruchteile — die Summe bleibt exakt.
    assert abs(s1["netz"]["kwh"] - 2910.0) < 0.5
    assert abs(s1["pv"]["kwh"] - 3595.0) < 0.5
    assert abs(s1["akku"]["kwh"] - 2054.0) < 0.5
    assert abs((s1["netz"]["kwh"] + s1["pv"]["kwh"] + s1["akku"]["kwh"])
               - 8559.0) < 0.01
    # Der Netzpreis lässt sich jetzt bilden — kein „kein Preis"-Hinweis mehr.
    assert s1["netz"]["preis"] is not None
    assert not any("Gesamtverbrauch der Periode fehlt" in w for w in d["warnungen"])
