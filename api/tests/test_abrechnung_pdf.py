"""Die Abrechnungs-PDF — Aufbau, Umlaute, Verteilerschlüssel-Tabelle,
Ein-/Zweiseitigkeit (N419)."""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.abrechnung_pdf import (AKZENT_MAX, AKZENT_MIN, NEG, POS, SEITE_H,  # noqa: E402
                                TEAL, _breite, _kuerzen, _mische,
                                _monate_aus, _zahl, abrechnung_pdf,
                                pdf_dateiname)

WERTE = {"kosten": 1240.55, "vorauszahlungen": 1500.0, "saldo": 259.45}
POSTEN = [{"kostenart": "Heizung", "betrag": 800.30},
          {"kostenart": "Wasser", "betrag": 440.25}]

ECHT = [("Heizkosten", 776.42, False), ("Warmwasser", 218.24, False),
        ("Wasserkosten", 99.24, False), ("Abwasserkosten", 129.39, False),
        ("Müllgebühren", 148.05, False), ("Versicherungen", 355.97, False),
        ("Hausmeister", 687.83, True), ("Gartenpflege", 59.50, True),
        ("Mieter Rauchwarnmelder/Prüfung Rauchwarnmelder", 4.17, True),
        ("Abrechn. Kaltwasserzähler", 10.71, True),
        ("Miete Kaltwasserzähler", 40.46, True), ("Bankspesen", 40.38, False),
        ("Niederschlagswasser", 16.94, False),
        ("Allgemeinstrom , WM", 120.00, False), ("Grundsteuer", 116.33, False)]

HEIZNACHWEIS = {
    "zaehler": [{"name": "Wärmemengenzähler Studio", "nummer": "12345",
                "kostenart": "Heizung", "messeinheit": "kWh", "typ": "gemessen",
                "bewertungsfaktor": None, "start": 1000.0, "ende": 1450.5,
                "verbrauch": 450.5}],
    "eigener_verbrauch_kwh": 450.5, "gesamt_verbrauch_kwh": 2200.0,
    "eigener_verbrauch_ww_m3": None, "gesamt_verbrauch_ww_m3": None,
    "kosten_je_kostenart": {"Heizung": 612.30},
    "kosten_gesamt_eigen": 612.30, "kosten_gesamt_haus": 3013.19,
    "kostenanteil_pct": 20.3, "flaeche": 62.0, "personen": 2,
}


def echte_positionen() -> list[dict]:
    return [{"kostenart": n, "betrag": b, "s35": s} for n, b, s in ECHT]


def echte_werte() -> dict:
    kosten = round(sum(b for _, b, _ in ECHT), 2)
    return {"kosten": kosten, "vorauszahlungen": 2640.0,
            "saldo": round(2640.0 - kosten, 2),
            "s35": round(sum(b for _, b, s in ECHT if s), 2)}


def y_werte(daten: bytes) -> list[float]:
    """Alle Textgrundlinien der Seite."""
    return [float(y) for y in
            re.findall(rb"1 0 0 1 -?\d+\.\d+ (-?\d+\.\d+) Tm", daten)]


# ------------------------------------------------------------------ Grundgerüst
def test_pdf_ist_ein_gueltiges_pdf():
    daten = abrechnung_pdf("Musterstraße 1", "01.01.2025 – 31.12.2025",
                           "Wohnung EG", WERTE, POSTEN)
    assert daten.startswith(b"%PDF-1.4")
    assert daten.rstrip().endswith(b"%%EOF")
    assert b"xref" in daten and b"trailer" in daten
    assert daten.count(b" obj") == 7   # Katalog, Seiten, Seite, Strom, 2 Fonts, Info


def test_ohne_heiznachweis_bleibt_einseitig():
    daten = abrechnung_pdf("Haus", "01.01.2023 – 31.12.2023", "Wohnung 1",
                           echte_werte(), echte_positionen())
    assert b"/Count 1" in daten
    assert daten.count(b"/Type /Page /Parent") == 1


def test_mit_heiznachweis_entstehen_zwei_seiten():
    """N419 — die Berechnungsgrundlage der Heizkosten (Zählerstände) kommt
    auf eine zweite Seite, nur wenn `heiznachweis` mitgegeben wird."""
    daten = abrechnung_pdf("Haus", "01.01.2023 – 31.12.2023", "Wohnung 1",
                           echte_werte(), echte_positionen(),
                           heiznachweis=HEIZNACHWEIS)
    assert b"/Count 2" in daten
    assert daten.count(b"/Type /Page /Parent") == 2
    assert daten.count(b" obj") == 9   # + eine Page + ein Contents mehr
    assert b"Nachweis Heizung" in daten
    assert b"W\xe4rmemengenz\xe4hler Studio" in daten
    assert b"20,3" in daten                        # Kostenanteil-%


def test_viele_positionen_bleiben_auf_der_seite():
    """40 Posten werden im Zeilenabstand gestaucht, nicht umgebrochen: nichts
    läuft über den Rand hinaus, weder oben noch unten."""
    viele = [{"kostenart": f"Sehr lange Kostenartbezeichnung Nummer {i}",
              "betrag": 12.0 + i * 88.5, "s35": i % 3 == 0} for i in range(40)]
    daten = abrechnung_pdf(
        "Haus", "01.01.2023 – 31.12.2023", "Wohnung 12",
        {"kosten": 69510.0, "vorauszahlungen": 20000.0, "saldo": -49510.0},
        viele, "Roman Heidenreich",
        anlage_hinweis="Ergänzend erhalten Sie in der Anlage die von delta-t "
                       "erstellte Heizkosten- und Betriebskostenabrechnung "
                       "sowie sämtliche Einzelbelege dieser Abrechnung.",
        abschlag_hinweis="Der NK Abschlag wird ab 01.01.2025 angepasst.")
    assert daten.count(b"/Type /Page /Parent") == 1
    y = y_werte(daten)
    assert len(y) > 45                        # alle Zeilen sind gesetzt
    assert min(y) > 5 and max(y) < SEITE_H - 15


def test_kurze_abrechnung_bleibt_ein_ordentlicher_brief():
    """Ein kurzer Brief muss die Seite nicht künstlich füllen — anders als
    der frühere Onepager wird hier nichts mehr gedehnt/zentriert."""
    kurz = [{"kostenart": "Grundsteuer", "betrag": 240.0},
            {"kostenart": "Müllabfuhr", "betrag": 96.5},
            {"kostenart": "Hausreinigung", "betrag": 480.0, "s35": True}]
    daten = abrechnung_pdf("Haus", "01.07.2024 – 31.12.2024", "Dachgeschoss",
                           {"kosten": 816.5, "vorauszahlungen": 1200.0,
                            "saldo": 383.5}, kurz)
    y = y_werte(daten)
    assert max(y) < SEITE_H - 15               # nichts läuft über den Kopf hinaus
    assert min(y) > 5                          # nichts läuft unten heraus


# ------------------------------------------------------------------ Zeichensatz
def test_umlaute_und_klammern_brechen_nichts():
    daten = abrechnung_pdf("Größenstraße (Hinterhaus)", "2025", "Müller & Söhne",
                           WERTE)
    assert b"Gr\xf6\xdfenstra\xdfe" in daten          # cp1252 = WinAnsi
    assert br"\(Hinterhaus\)" in daten                # Klammer maskiert


def test_gedankenstrich_im_zeitraum_bleibt_erhalten():
    """Der Zeitraum steht überall mit '–'. In latin-1 gäbe es dafür ein '?'."""
    daten = abrechnung_pdf("Haus", "01.01.2025 – 31.12.2025", "EG", WERTE)
    assert b"01.01.2025 \x96 31.12.2025" in daten
    assert b"?" not in daten


def test_euro_und_accent_ueberleben_die_kodierung():
    """Euro-Zeichen (0x80) und das à der Vorauszahlungszeile gibt es nur in
    cp1252 — in latin-1 wären beide ein Fragezeichen."""
    daten = abrechnung_pdf("Haus", "01.01.2024 – 31.12.2024", "EG",
                           {"kosten": 1200.0, "vorauszahlungen": 1440.0,
                            "saldo": 240.0})
    assert b"\xe0 120,00 \x80/mtl" in daten
    assert b"?" not in daten


# ------------------------------------------------------------------ Rechnerisch
def test_summenzeile_stimmt_rechnerisch():
    werte = echte_werte()
    daten = abrechnung_pdf("Unterschöllenbacher Hauptstr. 6a",
                           "01.01.2023 – 31.12.2023", "Wohnung 1. OG",
                           werte, echte_positionen())
    assert werte["kosten"] == 2823.63
    assert b"2.823,63" in daten                       # Summe der Positionen
    assert b"235,30" in daten                         # entspricht monatlich
    assert b"2.640,00" in daten                       # Vorauszahlungen
    assert b"12 Monate" in daten


def test_nachzahlung_bekommt_ein_minus():
    """Vorzeichen wie beim Nutzer: Nachzahlung (-) / Guthaben (+)."""
    daten = abrechnung_pdf("Haus", "01.01.2023 – 31.12.2023", "EG",
                           {"kosten": 2823.63, "vorauszahlungen": 2640.0,
                            "saldo": -183.63})
    assert b"Nachzahlung \\(-\\) / Guthaben \\(+\\)" in daten
    assert b"(-183,63)" in daten
    assert b"(+183,63)" not in daten


def test_guthaben_bekommt_ein_plus():
    daten = abrechnung_pdf("Haus", "01.01.2023 – 31.12.2023", "EG",
                           {"kosten": 2400.0, "vorauszahlungen": 2640.0,
                            "saldo": 240.0})
    assert b"(+240,00)" in daten
    assert b"(-240,00)" not in daten


def test_ergebnisbetrag_ist_farbig_keine_flaeche_mehr():
    """N419 — die frühere große Pos/Neg-Fläche wich einer schlichten
    Brief-Zeile: nur noch der Betrag selbst trägt Farbe, keine Fläche."""
    nachzahlung = abrechnung_pdf("Haus", "01.01.2023 – 31.12.2023", "EG",
                                 {"kosten": 2823.63, "vorauszahlungen": 2640.0,
                                  "saldo": -183.63})
    guthaben = abrechnung_pdf("Haus", "01.01.2023 – 31.12.2023", "EG",
                              {"kosten": 2400.0, "vorauszahlungen": 2640.0,
                               "saldo": 240.0})
    neg_farbe = b"%.3f %.3f %.3f rg BT" % NEG
    pos_farbe = b"%.3f %.3f %.3f rg BT" % POS
    assert neg_farbe in nachzahlung
    assert pos_farbe in guthaben
    # Keine große Fläche mehr in Pos/Neg-Farbe (nur der Text-Op "rg BT").
    assert (b"%.3f %.3f %.3f rg\n" % NEG) not in nachzahlung
    assert (b"%.3f %.3f %.3f rg\n" % POS) not in guthaben


def test_monate_werden_aus_dem_zeitraum_abgeleitet():
    assert _monate_aus("01.01.2023 – 31.12.2023") == 12
    assert _monate_aus("01.07.2024 – 31.12.2024") == 6
    assert _monate_aus("15.03.2024 – 14.06.2024") == 3
    assert _monate_aus("2024") is None                # dann keine Monatszeile


def test_monatsbetrag_kann_vorgegeben_werden():
    """Der tatsächlich gezahlte Abschlag kann von vz/Monate abweichen."""
    daten = abrechnung_pdf("Haus", "01.01.2023 – 31.12.2023", "EG",
                           {"kosten": 2823.63, "vorauszahlungen": 2640.0,
                            "saldo": -183.63}, monatsbetrag=220.0)
    assert b"12 Monate \xe0 220,00" in daten


# ------------------------------------------------------------------ § 35a
def test_s35_positionen_bekommen_stern_und_fussnote():
    daten = abrechnung_pdf("Haus", "01.01.2023 – 31.12.2023", "EG",
                           echte_werte(), echte_positionen())
    assert b"(Hausmeister *)" in daten
    assert b"(Bankspesen)" in daten                   # ohne Stern
    assert b"35a EStG" in daten


def test_ohne_s35_keine_fussnote():
    daten = abrechnung_pdf("Haus", "01.01.2023 – 31.12.2023", "EG", WERTE,
                           POSTEN)
    assert b"haushaltsnahe Dienstleistungen" not in daten


def test_s35_summe_der_engine_wird_ausgewiesen():
    """`abrechnung()` liefert je Partei ein Feld `s35` — das wird gezeigt,
    statt eine zweite Rechnung dafür aufzumachen."""
    daten = abrechnung_pdf("Haus", "01.01.2023 – 31.12.2023", "EG",
                           dict(WERTE, s35=802.67), POSTEN)
    assert b"802,67" in daten
    assert b"haushaltsnah" in daten


def test_s35a_schreibweise_der_ki_auslese_zaehlt_auch():
    daten = abrechnung_pdf("Haus", "2023", "EG", WERTE,
                           [{"kostenart": "Gartenpflege", "s35a": True,
                             "kosten": 59.5}])
    assert b"(Gartenpflege *)" in daten
    assert b"59,50" in daten


# ------------------------------------------------------------------ Satzspiegel
def test_lange_kostenart_wird_gekappt_statt_ueberzulaufen():
    lang = "Mieter Rauchwarnmelder/Prüfung Rauchwarnmelder Zusatzleistung Nord"
    gekappt = _kuerzen(lang, 120.0, 9.0)
    assert gekappt.endswith("…")
    assert _breite(gekappt, 9.0) <= 120.0


def test_kurze_kostenart_bleibt_unangetastet():
    assert _kuerzen("Heizkosten", 300.0, 10.5) == "Heizkosten"


def test_zahl_schreibt_deutsch():
    assert _zahl(2823.63) == "2.823,63"
    assert _zahl(-183.63) == "-183,63"
    assert _zahl(183.63, vorzeichen=True) == "+183,63"
    assert _zahl(None) == "0,00"


# ------------------------------------------------------------- Verteilerschlüssel
def test_verteilerschluessel_tabelle_zeigt_schluessel_und_gesamtkosten():
    """N419 — je Kostenart steht jetzt der Verteilerschlüssel und die
    Gesamtkosten dabei, nicht nur der eigene Anteil."""
    posten = [{"kostenart": "Heizung", "betrag": 612.30,
              "schluessel": "Verbrauch", "gesamtkosten": 3013.19},
              {"kostenart": "Grundsteuer", "betrag": 96.00,
              "schluessel": "Fläche", "gesamtkosten": 480.00}]
    daten = abrechnung_pdf("Haus", "01.01.2023 – 31.12.2023", "EG",
                           {"kosten": 708.30, "vorauszahlungen": 700.0,
                            "saldo": -8.30}, posten)
    assert b"Verbrauch" in daten and b"Fl\xe4che" in daten
    assert b"3.013,19" in daten and b"480,00" in daten


def test_zeilenakzent_ist_blass_nicht_kraeftig():
    """N419 — bewusst kein kräftiger Heatmap-Balken mehr wie zuvor (wirkte
    „kindisch"), nur ein blasser Zeilenakzent: der stärkste Wert bleibt weit
    von reinem Markenteal entfernt."""
    staerkster = _mische((1.0, 1.0, 1.0), TEAL, AKZENT_MAX)
    schwaechster = _mische((1.0, 1.0, 1.0), TEAL, AKZENT_MIN)
    assert staerkster[0] > 0.8                # nicht kräftig eingefärbt
    assert schwaechster[0] > staerkster[0]     # größerer Posten = mehr Farbe
    daten = abrechnung_pdf("Haus", "01.01.2023 – 31.12.2023", "EG",
                           {"kosten": 800.0, "vorauszahlungen": 800.0,
                            "saldo": 0.0},
                           [{"kostenart": "Groß", "betrag": 776.42},
                            {"kostenart": "Klein", "betrag": 4.17}])
    zeilen = re.findall(rb"(\d\.\d{3}) (\d\.\d{3}) (\d\.\d{3}) rg\n\d", daten)
    rot = {round(float(r), 3) for r, _, _ in zeilen}
    assert round(staerkster[0], 3) in rot
    assert round(schwaechster[0], 3) in rot


# ------------------------------------------------------------------ Briefkopf
def test_logo_und_unterschriftsfeld_stehen_auf_seite_eins():
    daten = abrechnung_pdf("Haus", "01.01.2023 – 31.12.2023", "EG",
                           WERTE, POSTEN, "Roman Heidenreich")
    assert b"ImmoCalc" in daten
    assert b"Unterschrift Vermieter" in daten
    assert b"Roman Heidenreich" in daten


def test_anrede_nutzt_die_partei_wenn_kein_mieter_angegeben_ist():
    daten = abrechnung_pdf("Haus", "01.01.2023 – 31.12.2023", "Alicia & Roman",
                           WERTE)
    assert b"Guten Tag Alicia & Roman," in daten


# ------------------------------------------------------------------ Kompatibel
def test_aufruf_aus_versand_py_funktioniert_unveraendert():
    """Genau die Form, mit der `routers/versand.py` das PDF baut — positional,
    ohne eine der neuen Angaben."""
    daten = abrechnung_pdf("Musterstraße 1", "01.01.2025 – 31.12.2025",
                           "Wohnung EG", WERTE,
                           [{"kostenart": "Heizung", "betrag": 800.30},
                            {"kostenart": "Wasser", "betrag": 440.25}],
                           "Roman Heidenreich")
    assert daten.count(b"/Type /Page /Parent") == 1
    assert b"Heizung" in daten and b"Wasser" in daten
    assert b"800,30" in daten                          # deutsche Schreibweise
    assert b"Wohnung EG" in daten                      # die Partei steht drin
    assert b"Roman Heidenreich" in daten


def test_ohne_positionen_entsteht_trotzdem_eine_seite():
    daten = abrechnung_pdf("Musterstraße 1", "2025", "Wohnung EG", WERTE)
    assert daten.count(b"/Type /Page /Parent") == 1
    assert b"1.240,55" in daten and b"1.500,00" in daten


def test_dateiname_ist_dateisystemtauglich():
    name = pdf_dateiname("Musterstraße 1 // Wohnung 2", "01.01.2025 – 31.12.2025",
                         "Müller, Anna")
    assert name.endswith("_2025_Mueller-Anna.pdf")
    assert name.isascii()
    assert not set(name) & set('<>:"/\\|?*')
