"""Orientierungswert für die Quadratmetermiete.

Geprüft wird in vier Schichten, damit ein roter Test sofort sagt, wo es klemmt:
Projektion, Datengrundlage, Statistik, Einordnung.

Die Referenzpunkte sind echt: das amtliche Rechenbeispiel der EPSG Guidance
Note für die Projektion, die Objektlagen des Nutzers in Mittelfranken und
Nürnberg als Großstadt für die Auswertung.
"""
import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import mietvergleich as mv  # noqa: E402

# Objektlagen des Nutzers und ein städtischer Gegenpol
ESCHENAU = (49.5983, 11.2225)
UNTERSCHOELLENBACH = (49.5836, 11.1494)
ECKENHAID = (49.5876, 11.2478)
NUERNBERG = (49.4521, 11.0767)
HAMBURG = (53.5503, 9.9920)
# Nordsee westlich Helgoland — Wasser, dort wohnt niemand
NORDSEE = (54.5000, 7.0000)


# --------------------------------------------------------------------------
# Projektion WGS84 -> ETRS89-LAEA (EPSG:3035)
# --------------------------------------------------------------------------

def test_amtliches_rechenbeispiel():
    """IOGP Geomatics Guidance Note 7-2, Methode 9820, Rechenbeispiel:
    50° N / 5° O ergibt E 3.962.799,45 m / N 2.999.718,85 m."""
    x, y = mv.nach_laea(50.0, 5.0)
    assert x == pytest.approx(3962799.45, abs=0.01)
    assert y == pytest.approx(2999718.85, abs=0.01)


def test_ursprung_liegt_auf_dem_versatz():
    """Im Projektionsursprung 52° N / 10° O stehen genau False Easting und
    False Northing."""
    assert mv.nach_laea(52.0, 10.0) == pytest.approx((4321000.0, 3210000.0))


def test_rueckweg_trifft_wieder_den_ausgangspunkt():
    for breite, laenge in (ESCHENAU, NUERNBERG, HAMBURG, (47.5, 7.6), (54.9, 13.4)):
        x, y = mv.nach_laea(breite, laenge)
        zurueck = mv.nach_wgs84(x, y)
        assert zurueck[0] == pytest.approx(breite, abs=1e-7)
        assert zurueck[1] == pytest.approx(laenge, abs=1e-7)


def test_rueckweg_des_amtlichen_beispiels():
    breite, laenge = mv.nach_wgs84(3962799.45, 2999718.85)
    assert breite == pytest.approx(50.0, abs=1e-6)
    assert laenge == pytest.approx(5.0, abs=1e-6)


def test_gitterzelle_ist_die_linke_untere_ecke():
    ost, nord = mv.gitterzelle(*ESCHENAU)
    x, y = mv.nach_laea(*ESCHENAU)
    assert ost * 1000 <= x < (ost + 1) * 1000
    assert nord * 1000 <= y < (nord + 1) * 1000
    assert mv.gitter_id(ost, nord) == f"CRS3035RES1000mN{nord*1000}E{ost*1000}"


def test_gitterzelle_von_eschenau():
    """Aus dem Rohdatensatz nachgeschlagen: Eschenau liegt in E4409 N2943."""
    assert mv.gitterzelle(*ESCHENAU) == (4409, 2943)


def test_ein_kilometer_versatz_wechselt_hoechstens_eine_zelle():
    """Zwei Punkte knapp 1 km auseinander dürfen nicht drei Zellen weit
    springen — das würde einen Vorzeichen- oder Einheitenfehler verraten."""
    ost1, nord1 = mv.gitterzelle(49.5983, 11.2225)
    ost2, nord2 = mv.gitterzelle(49.5983 + 0.009, 11.2225)   # rund 1 km nördlich
    assert abs(ost2 - ost1) <= 1
    assert nord2 - nord1 == 1


# --------------------------------------------------------------------------
# Datengrundlage
# --------------------------------------------------------------------------

def test_datei_liegt_beim_modul():
    assert os.path.exists(mv.DATEI)


def test_gitter_hat_die_erwartete_groesse():
    """Der Zensus liefert 136.024 belegte 1-km-Zellen. Weicht das ab, ist beim
    Umpacken der Datengrundlage etwas verloren gegangen."""
    assert len(mv.lade()) == 136024


def test_alle_werte_sind_plausibel():
    for (ost, nord), (cent, wohnungen, unsicher) in mv.lade().items():
        assert 50 <= cent <= 10000, (ost, nord, cent)
        assert wohnungen >= 1
        assert isinstance(unsicher, bool)
        assert 3900 <= ost <= 4800 and 2600 <= nord <= 3600


def test_summe_der_wohnungen_stimmt_mit_der_quelle():
    """Gegenprobe gegen die Rohdatei: 21.247.058 vermietete Wohnungen."""
    assert sum(w for _, w, _ in mv.lade().values()) == 21247058


def test_unsichere_zellen_sind_erhalten():
    """6.689 Zellen tragen im Zensus das Zeichen KLAMMERN."""
    assert sum(1 for _, _, u in mv.lade().values() if u) == 6689


def test_zelle_kennt_ihre_herkunft():
    ost, nord = mv.gitterzelle(*ESCHENAU)
    z = mv.zelle(ost, nord)
    assert z is not None
    assert z["gitter_id"] == "CRS3035RES1000mN2943000E4409000"
    assert z["miete_qm"] == 6.26
    assert z["wohnungen"] == 149


def test_zelle_ohne_wohnungen_gibt_es_nicht():
    """Über der Nordsee ist keine Zelle belegt."""
    assert mv.zelle(*mv.gitterzelle(*NORDSEE)) is None


def test_umgebung_waechst_mit_dem_radius():
    ost, nord = mv.gitterzelle(*NUERNBERG)
    klein = mv.umgebung(ost, nord, 1)
    gross = mv.umgebung(ost, nord, 3)
    assert 0 < len(klein) <= 9
    assert len(gross) > len(klein)
    assert all(abs(z["ost"] - ost) <= 3 and abs(z["nord"] - nord) <= 3
               for z in gross)


def test_umgebung_ohne_treffer_ist_leer():
    assert mv.umgebung(*mv.gitterzelle(*NORDSEE), 3) == []


# --------------------------------------------------------------------------
# Gewichtete Quantile
# --------------------------------------------------------------------------

def test_quantil_ohne_gewichtsunterschied():
    werte = [(float(w), 1.0) for w in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10)]
    assert mv.gewichtetes_quantil(werte, 0.5) == 5.0
    assert mv.gewichtetes_quantil(werte, 0.25) == 3.0
    assert mv.gewichtetes_quantil(werte, 0.75) == 8.0


def test_gewicht_verschiebt_den_median():
    """Eine Zelle mit 1000 Wohnungen zu 10 € wiegt schwerer als neun Zellen mit
    je einer Wohnung zu 2 € — genau darum wird gewichtet."""
    werte = [(2.0, 1.0)] * 9 + [(10.0, 1000.0)]
    assert mv.gewichtetes_quantil(werte, 0.5) == 10.0
    ungewichtet = [(2.0, 1.0)] * 9 + [(10.0, 1.0)]
    assert mv.gewichtetes_quantil(ungewichtet, 0.5) == 2.0


def test_quantile_sind_geordnet():
    werte = [(3.0, 5.0), (9.0, 2.0), (5.5, 40.0), (12.0, 1.0), (7.25, 18.0)]
    q = [mv.gewichtetes_quantil(werte, x) for x in (0.0, 0.25, 0.5, 0.75, 1.0)]
    assert q == sorted(q)


def test_quantil_ohne_werte_meldet_sich():
    with pytest.raises(ValueError):
        mv.gewichtetes_quantil([], 0.5)


# --------------------------------------------------------------------------
# Fortschreibung über den Mietpreisindex
# --------------------------------------------------------------------------

@pytest.fixture
def eigene_reihe(monkeypatch):
    """Eine erfundene, glatte Reihe — so prüft die Rechenlogik sich selbst,
    ohne bei jeder Aktualisierung der echten Reihe rot zu werden."""
    monkeypatch.setattr(mv, "MIETINDEX", {2020: 100.0, 2021: 110.0, 2022: 120.0,
                                          2023: 130.0})
    monkeypatch.setattr(mv, "MIETINDEX_FORTSCHREIBUNG", 0.10)


def test_jahresmitte_trifft_den_jahresdurchschnitt(eigene_reihe):
    wert, geschaetzt = mv._index_am(date(2021, 7, 1))
    assert wert == pytest.approx(110.0, abs=0.2)
    assert geschaetzt is False


def test_zwischen_zwei_jahren_wird_interpoliert(eigene_reihe):
    wert, _ = mv._index_am(date(2022, 1, 1))
    assert 110.0 < wert < 120.0


def test_ueber_die_reihe_hinaus_wird_gekennzeichnet(eigene_reihe):
    wert, geschaetzt = mv._index_am(date(2025, 7, 1))
    assert geschaetzt is True
    assert wert == pytest.approx(130.0 * 1.10 ** 2, rel=0.02)


def test_faktor_steigt_mit_der_zeit(eigene_reihe):
    frueh = mv.fortschreibungsfaktor(bis=date(2023, 1, 1))
    spaet = mv.fortschreibungsfaktor(bis=date(2026, 1, 1))
    assert 1.0 < frueh["faktor"] < spaet["faktor"]
    assert frueh["von"] == mv.STICHTAG.isoformat()


def test_faktor_nennt_seine_herleitung(eigene_reihe):
    fort = mv.fortschreibungsfaktor(bis=date(2026, 7, 1))
    for feld in ("faktor", "von", "bis", "index_von", "index_bis", "geschaetzt",
                 "reihe", "reihe_quelle", "reihe_bis_jahr"):
        assert feld in fort
    assert fort["index_bis"] / fort["index_von"] == pytest.approx(fort["faktor"],
                                                                 rel=1e-3)


def test_faktor_auf_den_stichtag_selbst_ist_eins(eigene_reihe):
    assert mv.fortschreibungsfaktor(bis=mv.STICHTAG)["faktor"] == 1.0


# --------------------------------------------------------------------------
# Die mitgelieferte Reihe
# --------------------------------------------------------------------------

def test_reihe_ist_hinterlegt_und_steigt():
    jahre = sorted(mv.MIETINDEX)
    assert jahre[0] <= 2020
    assert jahre[-1] >= 2024, "Indexreihe ist zu alt für eine Fortschreibung"
    assert jahre == list(range(jahre[0], jahre[-1] + 1)), "Lücke in der Reihe"
    werte = [mv.MIETINDEX[j] for j in jahre]
    assert werte == sorted(werte), "Nettokaltmieten sind nie gefallen"


def test_reihe_hat_die_basis_2020():
    assert mv.MIETINDEX[2020] == 100.0


def test_interpolation_trifft_den_veroeffentlichten_monatswert():
    """Prüfstein für das Modell „Jahresdurchschnitt gilt zur Jahresmitte":
    für Mai 2022 ist der Monatswert 103,0 veröffentlicht (GENESIS 61111-0004).
    Die Interpolation aus den Jahresdurchschnitten muss ihn treffen."""
    wert, geschaetzt = mv._index_am(mv.STICHTAG)
    assert wert == pytest.approx(mv.MIETINDEX_MAI_2022, abs=0.15)
    assert geschaetzt is False


def test_hochrechnung_trifft_den_letzten_veroeffentlichten_stand():
    """Juni 2026 ist mit 112,4 veröffentlicht — die Hochrechnung über das Ende
    der Jahresreihe hinaus muss dort landen."""
    wert, geschaetzt = mv._index_am(date(2026, 6, 15))
    assert wert == pytest.approx(112.4, abs=0.2)
    assert geschaetzt is True


def test_fortschreibung_bleibt_in_massvollen_grenzen():
    """Zwischen Zensus-Stichtag und heute darf sich die Miete nicht verdoppeln —
    ein Tippfehler in der Reihe fiele hier auf."""
    faktor = mv.fortschreibungsfaktor(bis=date(2026, 7, 1))["faktor"]
    assert 1.05 < faktor < 1.30


# --------------------------------------------------------------------------
# Spanne
# --------------------------------------------------------------------------

@pytest.mark.parametrize("ort", [ESCHENAU, UNTERSCHOELLENBACH, ECKENHAID,
                                 NUERNBERG, HAMBURG])
def test_spanne_traegt_in_bewohnten_lagen(ort):
    e = mv.spanne(*ort, stichtag=date(2026, 7, 1))
    assert e["tragfaehig"] is True
    assert e["unten"] <= e["mitte"] <= e["oben"]
    assert 1.0 < e["unten"] and e["oben"] < 50.0


def test_spanne_nennt_ihre_herkunft():
    e = mv.spanne(*ESCHENAU, stichtag=date(2026, 7, 1))
    h = e["herkunft"]
    assert "Zensus 2022" in h["quelle"]
    assert "dl-de/by-2-0" in h["lizenz"]
    assert h["stichtag"] == "2022-05-15"
    assert h["gitter_id"] == "CRS3035RES1000mN2943000E4409000"
    assert h["zellen"] >= mv.MINDEST_ZELLEN
    assert h["wohnungen"] >= mv.MINDEST_WOHNUNGEN
    assert 1 <= h["radius_km"] <= mv.MAX_RADIUS
    assert h["unsichere_zellen"] >= 0


def test_spanne_ueber_der_nordsee_sagt_ehrlich_nein():
    e = mv.spanne(*NORDSEE)
    assert e["tragfaehig"] is False
    assert "zu wenige" in e["grund"]
    assert e["herkunft"]["zellen"] == 0
    assert e["herkunft"]["zelle_belegt"] is False


def test_duenne_lage_holt_weiter_aus_als_dichte():
    """Auf dem Land muss der Radius wachsen, in der Stadt reicht ein Kilometer."""
    land = mv.spanne(*ECKENHAID)
    stadt = mv.spanne(*NUERNBERG)
    assert stadt["herkunft"]["radius_km"] == 1
    assert land["herkunft"]["radius_km"] > stadt["herkunft"]["radius_km"]


def test_stadt_ist_teurer_als_das_umland():
    """Nürnberg über Eckental, Hamburg über Nürnberg — sonst stimmt die
    Zuordnung von Koordinate zu Zelle nicht."""
    dorf = mv.spanne(*ECKENHAID, stichtag=date(2026, 7, 1))
    stadt = mv.spanne(*NUERNBERG, stichtag=date(2026, 7, 1))
    gross = mv.spanne(*HAMBURG, stichtag=date(2026, 7, 1))
    assert dorf["mitte"] < stadt["mitte"] < gross["mitte"]


def test_einzelne_ausreisserzelle_schlaegt_nicht_durch():
    """Unterschöllenbach hat in der eigenen Zelle 2,75 €/m² aus sechs
    Wohnungen. Die Spanne darf davon nicht bestimmt werden."""
    ost, nord = mv.gitterzelle(*UNTERSCHOELLENBACH)
    assert mv.zelle(ost, nord)["miete_qm"] == 2.75
    e = mv.spanne(*UNTERSCHOELLENBACH, stichtag=date(2026, 7, 1))
    assert e["mitte"] > 5.0


def test_fortschreibung_hebt_die_zensuswerte_an():
    e = mv.spanne(*NUERNBERG, stichtag=date(2026, 7, 1))
    assert e["mitte"] > e["zensus"]["mitte"]
    assert e["mitte"] == pytest.approx(
        e["zensus"]["mitte"] * e["fortschreibung"]["faktor"], abs=0.01)


def test_zum_stichtag_selbst_bleiben_die_werte_unveraendert():
    e = mv.spanne(*NUERNBERG, stichtag=mv.STICHTAG)
    assert e["mitte"] == e["zensus"]["mitte"]


def test_guete_ist_in_der_stadt_besser_als_auf_dem_land():
    assert mv.spanne(*NUERNBERG)["guete"] == "gut"
    assert mv.spanne(*ECKENHAID)["guete"] in ("mittel", "grob")


# --------------------------------------------------------------------------
# Einordnung
# --------------------------------------------------------------------------

def test_einordnung_kennt_drei_faelle():
    assert mv.einordnung(5.0, 6.0, 9.0) == "zu_niedrig"
    assert mv.einordnung(7.5, 6.0, 9.0) == "fair"
    assert mv.einordnung(11.0, 6.0, 9.0) == "zu_hoch"


def test_die_grenzen_gehoeren_zur_spanne():
    assert mv.einordnung(6.0, 6.0, 9.0) == "fair"
    assert mv.einordnung(9.0, 6.0, 9.0) == "fair"


def test_einordnung_passt_immer_zur_spanne():
    """Die tragende Invariante: was als fair gilt, liegt zwischen den Grenzen;
    was zu hoch heißt, liegt darüber. Über ein breites Raster geprüft."""
    unten, oben = 6.40, 9.10
    for schritt in range(0, 200):
        miete = round(schritt * 0.1, 2)
        lage = mv.einordnung(miete, unten, oben)
        assert (lage == "fair") == (unten <= miete <= oben)
        assert (lage == "zu_niedrig") == (miete < unten)
        assert (lage == "zu_hoch") == (miete > oben)


# --------------------------------------------------------------------------
# Gesamtauskunft
# --------------------------------------------------------------------------

def test_bewerte_rechnet_die_quadratmetermiete():
    e = mv.bewerte(*ESCHENAU, kaltmiete=650.0, wohnflaeche=80.0,
                   stichtag=date(2026, 7, 1))
    # 650 / 80 = 8,125 — round() rundet die glatte Hälfte zur geraden Ziffer,
    # wie überall sonst im Projekt auch
    assert e["miete_qm"] == 8.12
    assert e["kaltmiete"] == 650.0
    assert e["wohnflaeche"] == 80.0
    assert mv.bewerte(*ESCHENAU, kaltmiete=648.0, wohnflaeche=80.0,
                      stichtag=date(2026, 7, 1))["miete_qm"] == 8.10


def test_bewerte_ordnet_konsistent_ein():
    for kaltmiete in (200.0, 450.0, 650.0, 1500.0):
        e = mv.bewerte(*ESCHENAU, kaltmiete=kaltmiete, wohnflaeche=80.0,
                       stichtag=date(2026, 7, 1))
        assert e["einordnung"] == mv.einordnung(e["miete_qm"], e["unten"],
                                                e["oben"])


def test_bewerte_zeigt_den_spielraum_nach_oben():
    e = mv.bewerte(*ESCHENAU, kaltmiete=400.0, wohnflaeche=80.0,
                   stichtag=date(2026, 7, 1))
    assert e["spielraum_bis_oben"] == pytest.approx(
        (e["oben"] - e["miete_qm"]) * 80.0, abs=0.01)


def test_bewerte_ohne_datenlage_ordnet_nicht_ein():
    e = mv.bewerte(*NORDSEE, kaltmiete=650.0, wohnflaeche=80.0)
    assert e["tragfaehig"] is False
    assert e["einordnung"] is None
    assert e["miete_qm"] == 8.12
    assert "kein Orientierungswert" in e["text"]


def test_bewerte_ohne_wohnflaeche_meldet_sich():
    for flaeche in (0, -5, None):
        with pytest.raises(ValueError):
            mv.bewerte(*ESCHENAU, kaltmiete=650.0, wohnflaeche=flaeche)


def test_abweichung_bezieht_sich_auf_die_mitte():
    e = mv.bewerte(*NUERNBERG, kaltmiete=1000.0, wohnflaeche=80.0,
                   stichtag=date(2026, 7, 1))
    assert e["abweichung_prozent"] == pytest.approx(
        (e["miete_qm"] / e["mitte"] - 1) * 100, abs=0.1)


def test_text_nennt_zahlen_und_richtung():
    e = mv.bewerte(*NUERNBERG, kaltmiete=1400.0, wohnflaeche=80.0,
                   stichtag=date(2026, 7, 1))
    assert e["einordnung"] == "zu_hoch"
    assert "über der Spanne" in e["text"]
    assert f"{e['mitte']:.2f}" in e["text"]


def test_quellenvermerk_erfuellt_die_lizenz():
    """Die Datenlizenz verlangt Namensnennung, Lizenzangabe und Verweis auf den
    Lizenztext."""
    v = mv.quellenvermerk()
    assert "Statistische Ämter des Bundes und der Länder" in v
    assert "Zensus 2022" in v
    assert "dl-de/by-2-0" in v
    assert "govdata.de" in v
    assert "15.05.2022" in v


def test_der_begriff_vergleichsmiete_taucht_nirgends_auf():
    """Der Rechtsbegriff nach § 558 BGB darf in keiner Ausgabe stehen — der
    Zensuswert ist kein Begründungsmittel. Er heißt Orientierungswert."""
    e = mv.bewerte(*NUERNBERG, kaltmiete=900.0, wohnflaeche=80.0,
                   stichtag=date(2026, 7, 1))
    alles = repr(e) + mv.quellenvermerk()
    assert "Vergleichsmiete" not in alles
    assert "ortsüblich" not in alles.lower()
