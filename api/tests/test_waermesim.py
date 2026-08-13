"""N340 — der nachgebaute Rechenweg gegen eine echte Delta-t-Abrechnung.

Die Zahlen stammen Zeile für Zeile aus der Heizkostenabrechnung der Laufer
Str. 5 für 01.10.2018 – 30.09.2019 (Objekt 103536-002, Delta-t Messdienst
Wenzel GmbH, Abrechnungsdatum 18.02.2020). Sie sind der Prüfstein: solange
dieser Test grün ist, rechnet ImmoCalc genau wie der Messdienst.

Der einzige Wert, der nicht aus der Abrechnung abgeleitet, sondern ihr
entnommen ist, ist die Aufteilung der Verbrauchskosten auf H1 (Heizkosten-
verteiler) und H2 (Wärmezähler Anbau) — genau die Größe, die der Nutzer über
mehrere Jahre bestimmen will.
"""
import os
import sys
import tempfile

os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "test_wsim.db"))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.waermesim import brennstoff, h2_anteil_aus_soll, rechne  # noqa: E402

# --- die Abrechnung 2018/2019, so wie sie auf dem Papier steht --------------

BESTAENDE = [
    {"datum": "2018-10-01", "liter": 1990.0, "eur": 1430.21},   # Anfangsbestand
    {"datum": "2019-01-04", "liter": 1000.0, "eur": 765.17},
    {"datum": "2019-02-11", "liter": 1000.0, "eur": 777.07},
    {"datum": "2019-04-29", "liter": 2000.0, "eur": 1560.09},
]
REST = {"datum": "2019-09-30", "liter": 1544.0, "eur": 1204.39}

# „NEBENKOSTEN HEIZUNG" 572,20 € und „ZUSATZKOSTEN HEIZUNG" 295,36 €.
# Die Zusatzkosten (Miete der Zähler) trägt die Heizung allein — auf der
# Abrechnung steht in der Warmwasser-Spalte nichts.
BLOECKE = [
    {"name": "Nebenkosten Heizung", "betrag": 572.20},
    {"name": "Zusatzkosten Heizung", "betrag": 295.36, "nur_heizung": True},
]

# Je Nutzer: Einheiten der Heizkostenverteiler, Wohnfläche und — bei zwei
# Nutzern derselben Dachgeschosswohnung — der Zeitanteil, den Delta-t als
# „× 360,0/1000,0" bzw. „× 640,0/1000,0" schreibt.
NUTZER = [
    {"name": "EGL",   "ehkv": 1862.222, "flaeche": 26.0},
    {"name": "EGR",   "ehkv": 1914.624, "flaeche": 20.0},
    {"name": "1GL",   "ehkv": 681.076,  "flaeche": 33.0},
    {"name": "1GR",   "ehkv": 804.761,  "flaeche": 23.0},
    {"name": "DG-1",  "ehkv": 578.158,  "flaeche": 30.0, "zeitanteil": 0.360},
    {"name": "DG-2",  "ehkv": 1027.836, "flaeche": 30.0, "zeitanteil": 0.640},
    {"name": "EG1G-1", "ehkv": 555.750, "flaeche": 30.0},
    {"name": "EG1G-2", "ehkv": 3579.816, "flaeche": 30.0, "ww_m3": 13.900},
    {"name": "Anbau", "kwh": 10092.0,   "flaeche": 115.0, "ww_m3": 16.210},
]

# Die Heizkosten, die Delta-t je Nutzer ausgewiesen hat.
SOLL = {"EGL": 393.90, "EGR": 379.56, "1GL": 232.79, "1GR": 214.66,
        "DG-1": 132.60, "DG-2": 235.73, "EG1G-1": 201.56, "EG1G-2": 681.76,
        "Anbau": 1392.97}

# 1.747,30 € von 2.705,87 € Verbrauchskosten gingen an H1, 958,57 € an H2.
H2_ANTEIL = 958.57 / 2705.87

EINGABE = {
    "heizwert": 10.0,
    "bestaende": BESTAENDE,
    "rest": REST,
    "ww_m3": 30.110,
    "bloecke": BLOECKE,
    "fest_anteil": 0.30,
    "h2_anteil": H2_ANTEIL,
    "nutzer": NUTZER,
    "soll": SOLL,
}


def test_brennstoff_aus_bestaenden():
    """Anfangsbestand + Anlieferungen − Restbestand = 4.446,000 l / 3.328,15 €."""
    s = brennstoff({"bestaende": BESTAENDE, "rest": REST})
    assert s["liter"] == 4446.0
    assert s["eur"] == 3328.15


def test_energie_und_warmwasseranteil():
    """44.460 kWh gesamt, Qtw 3.764 kWh → 376,4 l → 8,47 % Warmwasser."""
    erg = rechne(EINGABE)
    assert erg["energie"]["gesamt_kwh"] == 44460.0
    assert erg["energie"]["ww_kwh"] == 3763.75          # 2,5 · 30,110 · 50
    assert round(erg["anteile"]["warmwasser"] * 100, 2) == 8.47
    assert round(erg["anteile"]["heizung"] * 100, 2) == 91.53


def test_kostenbloecke_wie_auf_der_abrechnung():
    """Brennstoff 3.046,41/281,74 · Nebenkosten 523,76/48,44 · Zusatz 295,36/0.

    In Summe 3.865,53 € Heizkosten und 330,18 € Warmwasserkosten."""
    erg = rechne(EINGABE)
    nach_name = {b["name"]: b for b in erg["bloecke"]}
    assert (nach_name["Brennstoffkosten"]["heizung"],
            nach_name["Brennstoffkosten"]["warmwasser"]) == (3046.41, 281.74)
    assert (nach_name["Nebenkosten Heizung"]["heizung"],
            nach_name["Nebenkosten Heizung"]["warmwasser"]) == (523.76, 48.44)
    assert (nach_name["Zusatzkosten Heizung"]["heizung"],
            nach_name["Zusatzkosten Heizung"]["warmwasser"]) == (295.36, 0.0)
    assert erg["heizung"]["gesamt"] == 3865.53
    assert erg["warmwasser"]["gesamt"] == 330.18


def test_fest_und_verbrauchsanteil():
    """30 % Festkosten (1.159,66 €), 70 % Verbrauch (2.705,87 €), davon
    1.747,30 € auf die Heizkostenverteiler und 958,57 € auf den Wärmezähler."""
    erg = rechne(EINGABE)
    assert erg["heizung"]["fest"] == 1159.66
    assert erg["heizung"]["verbrauch"] == 2705.87
    assert erg["heizung"]["verbrauch_h1"] == 1747.30
    assert erg["heizung"]["verbrauch_h2"] == 958.57


def test_fest_schluessel_flaeche_ist_die_vorgabe():
    """Ohne Angabe (und mit dem ausdrücklichen Wert) verteilen sich die
    Grundkosten wie bisher nach Fläche — die Vorgabe bleibt der gesetzliche
    Regelfall, keine Verhaltensänderung für bestehende Aufrufer."""
    ohne_angabe = rechne(EINGABE)
    mit_angabe = rechne({**EINGABE, "fest_schluessel": "flaeche"})
    fest = {z["name"]: z["festkosten"] for z in ohne_angabe["nutzer"]}
    fest2 = {z["name"]: z["festkosten"] for z in mit_angabe["nutzer"]}
    assert fest == fest2
    assert ohne_angabe["anteile"]["fest_schluessel"] == "flaeche"
    # EGR hat weniger Fläche (20 m²) als 1GL (33 m²) — trägt entsprechend
    # weniger Grundkosten.
    assert fest["EGR"] < fest["1GL"]


def test_fest_schluessel_personen_wirkt_wirklich():
    """N395 — der eigentliche Bug: der Umschalter griff bisher gar nicht.
    Mit `personen` verteilen sich die Grundkosten nach Kopfzahl, nicht nach
    Quadratmetern — eine kleine, dicht bewohnte Einheit trägt jetzt mehr."""
    nutzer = [{"name": "Klein", "flaeche": 20.0, "personen": 4},
              {"name": "Gross", "flaeche": 80.0, "personen": 1}]
    eingabe = {**EINGABE, "nutzer": nutzer, "soll": {}}
    nach_flaeche = rechne({**eingabe, "fest_schluessel": "flaeche"})
    nach_personen = rechne({**eingabe, "fest_schluessel": "personen"})
    f = {z["name"]: z["festkosten"] for z in nach_flaeche["nutzer"]}
    p = {z["name"]: z["festkosten"] for z in nach_personen["nutzer"]}
    # Nach Fläche trägt „Klein" (20 m² von 100 m²) nur ein Fünftel.
    assert f["Klein"] < f["Gross"]
    # Nach Personen dreht sich das Verhältnis um: 4 von 5 Personen wohnen dort.
    assert p["Klein"] > p["Gross"]
    assert nach_personen["anteile"]["fest_schluessel"] == "personen"
    # Beide Verteilungen treffen exakt denselben Gesamtbetrag.
    gesamt = nach_flaeche["heizung"]["fest"]
    assert round(sum(f.values()), 2) == gesamt
    assert round(sum(p.values()), 2) == gesamt


def test_fest_schluessel_einheiten_teilt_gleich():
    """„Einheiten" heisst: jede Einheit gleich viel, unabhängig von Fläche
    oder Personenzahl."""
    nutzer = [{"name": "Klein", "flaeche": 20.0, "personen": 4},
              {"name": "Gross", "flaeche": 80.0, "personen": 1}]
    erg = rechne({**EINGABE, "nutzer": nutzer, "soll": {},
                  "fest_schluessel": "einheiten"})
    fest = {z["name"]: z["festkosten"] for z in erg["nutzer"]}
    assert fest["Klein"] == fest["Gross"]
    assert erg["anteile"]["fest_schluessel"] == "einheiten"


def test_unbekannter_fest_schluessel_faellt_auf_flaeche_zurueck():
    """Ein ungültiger Wert bricht die Rechnung nicht ab, sondern verhält sich
    wie ohne Angabe — der gesetzliche Regelfall."""
    erg = rechne({**EINGABE, "fest_schluessel": "quadratwurzel"})
    assert erg["anteile"]["fest_schluessel"] == "flaeche"
    assert erg["heizung"]["fest"] == 1159.66


def test_preise_je_einheit():
    """Die drei Preise, mit denen jede Nutzerzeile gerechnet wird:
    3,777394 €/m² · 0,158784 €/EHKV-Einheit · 0,094983 €/kWh — dazu
    10,965792 €/m³ Warmwasser."""
    p = rechne(EINGABE)["preise"]
    assert p["fest_je_m2"] == 3.777394
    assert p["h1_je_einheit"] == 0.158784
    assert p["h2_je_kwh"] == 0.094983
    assert p["ww_je_m3"] == 10.965792


def test_jede_nutzerzeile_trifft_den_echten_betrag():
    """Der eigentliche Prüfstein: neun Nutzer, neun Beträge, keine Abweichung."""
    erg = rechne(EINGABE)
    for zeile in erg["nutzer"]:
        assert zeile["abweichung"] == 0.0, (
            f'{zeile["name"]}: gerechnet {zeile["heizkosten"]} € gegen '
            f'{zeile["soll"]} € von Delta-t')
    assert erg["abgleich"]["verglichen"] == 9
    assert erg["abgleich"]["groesste_abweichung"] == 0.0
    # 3.865,53 € Heizkosten gehen vollständig an die Nutzer.
    assert erg["abgleich"]["summe_ist"] == 3865.53


def test_warmwasser_geht_an_die_zwei_bezieher():
    """Zwei Parteien haben Warmwasser bezogen: 13,900 m³ → 152,42 € und
    16,210 m³ → 177,76 €. Zusammen 30,110 m³ und die vollen 330,18 €."""
    erg = rechne(EINGABE)
    zeilen = {z["name"]: z for z in erg["nutzer"]}
    assert zeilen["EG1G-2"]["warmwasser"] == 152.42
    assert zeilen["Anbau"]["warmwasser"] == 177.76
    assert erg["mengen"]["ww_m3"] == 30.110
    assert round(sum(z["warmwasser"] for z in erg["nutzer"]), 2) == 330.18


def test_der_schluessel_h2_ist_der_anteil_an_der_heizenergie():
    """N340b — die gesuchte Größe, an vier echten Jahren nachgewiesen.

    Der Wärmezähler des Anbaus bekommt seinen Anteil an der **Heizenergie**,
    also an der Ölenergie NACH Abzug des Warmwassers — und zwar als Anteil an
    den GESAMTEN Heizkosten. Deshalb ergeben H01 und H02 auf der Abrechnung
    zusammen die 70 % Verbrauchskosten.

        H02-Prozent = kWh Wärmezähler / (Liter × Heizwert × Heizungsanteil)

    Zuvor lag die Vermutung auf „Anteil an der Rohenergie" — die trifft nicht
    (2018/19 wären das 22,7 % statt der ausgewiesenen 24,80 %).
    """
    # (Bezeichnung, Liter, Warmwasser-m³, kWh Wärmezähler, ausgewiesenes H02-%)
    jahre = [
        ("2018/19", 4446.0, 30.110, 10092.0, 24.80),
        ("2020/21", 4049.0, 28.140, 11102.0, 30.03),
        ("2022/23", 3128.7, 18.470,  7162.0, 24.71),
    ]
    for name, liter, ww_m3, kwh, ist_prozent in jahre:
        erg = rechne({"liter": liter, "eur": 0.0, "ww_m3": ww_m3,
                      "nutzer": [{"name": "Anbau", "kwh": kwh}]})
        gerechnet = round(erg["anteile"]["h2_von_gesamt"] * 100, 2)
        assert abs(gerechnet - ist_prozent) <= 0.02, (
            f"{name}: gerechnet {gerechnet} % gegen {ist_prozent} % "
            "auf der Abrechnung")


def test_ein_jahr_weicht_ab_und_das_bleibt_sichtbar():
    """2023/24 passt als einziges nicht: 23,34 % gerechnet gegen 23,23 % auf
    der Abrechnung. 0,11 Prozentpunkte — zu wenig für einen Zufall, zu viel
    für eine Rundung. Der Fall steht hier fest, damit er nicht untergeht: er
    ist der Grund, warum `h2_anteil` überschreibbar bleibt und die Simulation
    die Abweichung anzeigt, statt sie zu glätten."""
    erg = rechne({"liter": 3257.0, "eur": 0.0, "ww_m3": 9.800,
                  "nutzer": [{"name": "Anbau", "kwh": 7316.0}]})
    gerechnet = round(erg["anteile"]["h2_von_gesamt"] * 100, 2)
    assert gerechnet == 23.34
    assert abs(gerechnet - 23.23) > 0.05          # die offene Abweichung


def test_der_beste_h2_anteil_laesst_sich_aus_den_sollwerten_finden():
    """Statt von Hand zu drehen: die Eingabelung trifft den Anteil, mit dem
    Delta-t gerechnet hat, auf ein Promille genau."""
    gefunden = h2_anteil_aus_soll({**EINGABE, "h2_anteil": None})
    assert abs(gefunden - H2_ANTEIL) <= 0.001


def test_ohne_nutzer_bleibt_alles_ruhig():
    """Ein leeres Jahr ergibt keine Fehler, nur Nullen — die Maske startet so."""
    erg = rechne({})
    assert erg["nutzer"] == []
    assert erg["heizung"]["gesamt"] == 0.0
    assert erg["preise"]["fest_je_m2"] == 0.0


def test_der_rundungsrest_ist_eine_annahme_kein_gesetz():
    """Ehrlichkeit über die eine Stelle, die nicht bewiesen ist.

    Acht Heizkostenverteiler-Zeilen treffen kaufmännisch gerundet exakt; nur
    die größte steht bei Delta-t 2 Cent höher, und genau diese 2 Cent fehlen
    der Summe der gerundeten Zeilen zu den ausgewiesenen 1.747,30 €. Daraus
    ist die Regel „Rest an die größte Zeile" abgeleitet — aus einem einzigen
    Beleg. Das Größte-Reste-Verfahren der Engine hält dieselbe Summe ein,
    legt die Cent aber woanders hin. Ein zweites Abrechnungsjahr muss das
    entscheiden; bis dahin steht der Unterschied hier schwarz auf weiß."""
    wie_deltat = rechne(EINGABE)
    wie_engine = rechne({**EINGABE, "rundung": "engine"})

    # Beide halten die Summe exakt ein — es geht kein Cent verloren.
    assert wie_deltat["abgleich"]["summe_ist"] == 3865.53
    assert wie_engine["abgleich"]["summe_ist"] == 3865.53

    # Aber nur die Delta-t-Regel trifft jede einzelne Zeile.
    assert wie_deltat["abgleich"]["groesste_abweichung"] == 0.0
    assert 0 < wie_engine["abgleich"]["groesste_abweichung"] <= 0.02


def test_nur_oel_verteilt_genau_die_verbrauchten_liter():
    """N340c — die Variante des Nutzers: keine Nebenkosten, keine Zusatz-
    kosten, kein Strom. Nur die 4.446 l Öl über die abgelesenen Werte.

    Rein nach Verbrauch (Vorgabe): wer nichts abgelesen hat, zahlt nichts."""
    from app.waermesim import nur_oel

    erg = nur_oel({"liter": 4446.0, "eur": 3328.15, "ww_m3": 30.110,
                   "nutzer": NUTZER})
    # Keine fremden Kosten mehr im Topf — nur der Brennstoff.
    assert [b["name"] for b in erg["bloecke"]] == ["Brennstoffkosten"]
    # Und keine Grundkosten: alles hängt am Verbrauch.
    assert erg["heizung"]["fest"] == 0.0
    assert erg["heizung"]["verbrauch"] == erg["heizung"]["gesamt"]
    # Die Liter gehen restlos an die Nutzer — Heizung plus Warmwasser.
    verteilt = sum(z["liter"] + z["liter_warmwasser"] for z in erg["nutzer"])
    assert abs(verteilt - 4446.0) < 0.01
    # Ebenso das Geld.
    assert abs(sum(z["summe"] for z in erg["nutzer"]) - 3328.15) < 0.02
    # Wer weder Heizkörper noch Zähler abgelesen hat, trägt nichts.
    ohne = nur_oel({"liter": 1000.0, "eur": 900.0,
                    "nutzer": [{"name": "A", "ehkv": 100.0, "flaeche": 50.0},
                               {"name": "B", "ehkv": 0.0, "flaeche": 50.0}]})
    zeilen = {z["name"]: z for z in ohne["nutzer"]}
    assert zeilen["B"]["summe"] == 0.0
    assert zeilen["A"]["liter"] == 1000.0


def test_nur_oel_mit_gesetzlichem_grundanteil():
    """Wer den Regelfall will, gibt 30 % an — dann geht dieser Teil nach
    Fläche, der Rest weiter nach Verbrauch. Die Liter bleiben vollständig."""
    from app.waermesim import nur_oel

    erg = nur_oel({"liter": 1000.0, "eur": 900.0,
                   "nutzer": [{"name": "A", "ehkv": 100.0, "flaeche": 50.0},
                              {"name": "B", "ehkv": 0.0, "flaeche": 50.0}]},
                  fest_anteil=0.30, warmwasser_abziehen=False)
    zeilen = {z["name"]: z for z in erg["nutzer"]}
    assert zeilen["B"]["liter"] == 150.0          # nur der halbe Grundanteil
    assert zeilen["A"]["liter"] == 850.0          # Grundanteil + ganzer Verbrauch
    assert round(sum(z["liter"] for z in erg["nutzer"]), 3) == 1000.0


def test_liter_und_euro_bleiben_zueinander_stimmig():
    """Die Litermenge folgt denselben Gewichten wie das Geld — sonst stünde in
    der Ansicht ein Anteil in Litern neben einem anderen in Euro."""
    erg = rechne(EINGABE)
    heiz_liter = sum(z["liter"] for z in erg["nutzer"])
    assert abs(heiz_liter - 4446.0 * erg["anteile"]["heizung"]) < 0.01
    fuer_ww = sum(z["liter_warmwasser"] for z in erg["nutzer"])
    assert abs(fuer_ww - erg["energie"]["ww_liter"]) < 0.01
