"""Der Mieter-Onepager als PDF — Aufbau, Umlaute, Heatmap, eine Seite."""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.abrechnung_pdf import (SEITE_H, _breite, _kuerzen, _monate_aus,  # noqa: E402
                                _zahl, abrechnung_pdf, pdf_dateiname)

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


def echte_positionen() -> list[dict]:
    return [{"kostenart": n, "betrag": b, "s35": s} for n, b, s in ECHT]


def echte_werte() -> dict:
    kosten = round(sum(b for _, b, _ in ECHT), 2)
    return {"kosten": kosten, "vorauszahlungen": 2640.0,
            "saldo": round(2640.0 - kosten, 2),
            "s35": round(sum(b for _, b, s in ECHT if s), 2)}


def y_werte(daten: bytes) -> list[float]:
    """Alle Textgrundlinien der Seite, samt globalem Versatz."""
    versatz = re.search(rb"stream\n1 0 0 1 0 (-?\d+\.\d+) cm", daten)
    dy = float(versatz.group(1)) if versatz else 0.0
    return [float(y) + dy for y in
            re.findall(rb"1 0 0 1 -?\d+\.\d+ (-?\d+\.\d+) Tm", daten)]


# ------------------------------------------------------------------ Grundgerüst
def test_pdf_ist_ein_gueltiges_pdf():
    daten = abrechnung_pdf("Musterstraße 1", "01.01.2025 – 31.12.2025",
                           "Wohnung EG", WERTE, POSTEN)
    assert daten.startswith(b"%PDF-1.4")
    assert daten.rstrip().endswith(b"%%EOF")
    assert b"xref" in daten and b"trailer" in daten
    assert daten.count(b" obj") == 7   # Katalog, Seiten, Seite, Strom, 2 Fonts, Info


def test_onepager_hat_genau_eine_seite():
    """Der Nutzer nennt es ausdrücklich Onepager — eine zweite Seite darf es
    strukturell nicht geben."""
    daten = abrechnung_pdf("Haus", "01.01.2023 – 31.12.2023", "Wohnung 1",
                           echte_werte(), echte_positionen())
    assert b"/Count 1" in daten
    assert daten.count(b"/Type /Page /Parent") == 1


def test_viele_positionen_bleiben_auf_der_seite():
    """40 Posten werden gestaucht, nicht umgebrochen: nichts läuft über den
    Rand hinaus, weder oben noch unten."""
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
    assert min(y) > 15 and max(y) < SEITE_H - 15


def test_drei_positionen_lassen_die_seite_nicht_leer():
    """Eine kurze Abrechnung wird gedehnt und mittig gesetzt, statt oben zu
    kleben und zwei Drittel Papier leer zu lassen."""
    kurz = [{"kostenart": "Grundsteuer", "betrag": 240.0},
            {"kostenart": "Müllabfuhr", "betrag": 96.5},
            {"kostenart": "Hausreinigung", "betrag": 480.0, "s35": True}]
    daten = abrechnung_pdf("Haus", "01.07.2024 – 31.12.2024", "Dachgeschoss",
                           {"kosten": 816.5, "vorauszahlungen": 1200.0,
                            "saldo": 383.5}, kurz)
    y = y_werte(daten)
    # Der Block sitzt nicht mehr am oberen Rand: die oberste Zeile ist nach
    # unten gerückt, die unterste bleibt weit über dem Seitenfuß.
    assert max(y) < SEITE_H - 100
    assert min(y) > 200


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


def test_ergebnis_flaeche_ist_farblich_getoent_nicht_reinweiss():
    """N407 — vorher reines Weiß (SHEET) auf dem hellgrauen Kasten, im PDF
    kaum als eigene Karte zu erkennen. Jetzt dieselbe blasse Pos/Neg-Tönung
    wie die Chips in der App (--pos-bg/--neg-bg)."""
    nachzahlung = abrechnung_pdf("Haus", "01.01.2023 – 31.12.2023", "EG",
                                 {"kosten": 2823.63, "vorauszahlungen": 2640.0,
                                  "saldo": -183.63})
    guthaben = abrechnung_pdf("Haus", "01.01.2023 – 31.12.2023", "EG",
                              {"kosten": 2400.0, "vorauszahlungen": 2640.0,
                               "saldo": 240.0})
    assert b"1.000 1.000 1.000 rg" not in nachzahlung   # kein reines Weiss mehr
    assert b"0.969 0.914 0.890 rg" in nachzahlung        # NEG_BG
    assert b"0.906 0.957 0.925 rg" in guthaben           # POS_BG


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


def test_betragsspalte_ist_rechtsbuendig():
    """Alle Beträge enden auf derselben Kante — das geht nur mit echten
    Zeichenbreiten, nicht mit 'Zeichenzahl mal halber Schriftgrad'."""
    daten = abrechnung_pdf("Haus", "01.01.2023 – 31.12.2023", "EG",
                           echte_werte(), echte_positionen())
    kanten = {round(float(x) + _breite(inhalt.decode(), float(grad)), 1)
              for grad, x, inhalt in re.findall(
                  rb"/F1 (\d+\.\d+) Tf 1 0 0 1 (\d+\.\d+) \d+\.\d+ Tm "
                  rb"\(([\d.,]+)\) Tj", daten)
              if float(x) > 300}          # nicht das Datum der Fußzeile
    assert len(kanten) == 1
    assert len([g for g, _, _ in re.findall(
        rb"/F1 (\d+\.\d+) Tf 1 0 0 1 (\d+\.\d+) \d+\.\d+ Tm "
        rb"\(([\d.,]+)\) Tj", daten)]) >= 15


def test_zahl_schreibt_deutsch():
    assert _zahl(2823.63) == "2.823,63"
    assert _zahl(-183.63) == "-183,63"
    assert _zahl(183.63, vorzeichen=True) == "+183,63"
    assert _zahl(None) == "0,00"


def test_heatmap_faerbt_den_groessten_posten_am_kraeftigsten():
    daten = abrechnung_pdf("Haus", "01.01.2023 – 31.12.2023", "EG",
                           {"kosten": 800.0, "vorauszahlungen": 800.0,
                            "saldo": 0.0},
                           [{"kostenart": "Groß", "betrag": 776.42},
                            {"kostenart": "Klein", "betrag": 4.17}])
    # N407 — die Heatmap zielt seit hier auf TEAL statt NEG (kein Rot mehr für
    # bloße Kostenzeilen, siehe abrechnung_pdf.py-Kopf). Rotanteil der
    # Füllfarben: je kräftiger die Einfärbung, desto kleiner der Rotwert.
    # Papier liegt bei 0.910, Vollton TEAL bei 0.059.
    rot = {float(r) for r, _, _ in re.findall(
        rb"(\d\.\d{3}) (\d\.\d{3}) (\d\.\d{3}) rg\n\d", daten)}
    assert any(r < 0.50 for r in rot)            # der große Posten, kräftig
    assert any(0.85 < r < 0.92 for r in rot)     # der kleine, fast Papierton


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
