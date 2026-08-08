"""N291 — die zwei Arten, „ein Monat" zu zählen, und warum es zwei bleiben.

Eine Modularisierungs-Analyse hat die beiden Fassungen (`cashflow.monate_im_jahr`
und `weg._monate`) als Doppelung gemeldet: für den Februar 2025 lieferten sie
0,9205 gegen 1,0000 — knapp 8 % Unterschied in derselben Abrechnung. Sie sind
aber keine Doppelung, sondern zwei Antworten auf zwei Fragen.

Dieser Test hält den Unterschied fest. Wer die beiden zusammenlegt, verfälscht
je nach Richtung entweder die Nebenkosten-Verteilung oder die WEG-Vorauszahlung
— und beides fällt niemandem auf, weil die Summen weiterhin plausibel aussehen.
"""
import os
import sys
import tempfile
from datetime import date

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_zeit.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.zeit import jahresanteil_monate, zahlmonate  # noqa: E402


# --------------------------------------------------------------------------
# Der Unterschied ist gewollt
# --------------------------------------------------------------------------

def test_kurzer_monat_zaehlt_verschieden_und_das_ist_richtig():
    """Februar 2025: 28 Tage.

    Für die VERTEILUNG eines Jahresbetrags trägt er weniger als ein Juli mit
    31 Tagen — die Referenzzahlen aus den Excel-Dateien rechnen genau so.
    Für die ZAHLUNG eines Monatsbetrags zählt er voll: wer im Februar wohnt,
    überweist die vollen 244 €, nicht 224,60 €."""
    verteilung = jahresanteil_monate(date(2025, 2, 1), date(2025, 2, 28), 2025)
    zahlung = zahlmonate(date(2025, 2, 1), date(2025, 2, 28))

    assert round(verteilung, 4) == 0.9205
    assert zahlung == 1.0
    # Der Abstand ist gross genug, um in einer echten Abrechnung sichtbar zu
    # werden — deshalb steht er hier als Zahl und nicht nur als Kommentar.
    assert abs(verteilung - zahlung) / zahlung > 0.07


def test_langer_monat_kippt_in_die_andere_richtung():
    """Juli 2025: 31 Tage — hier liegt der Jahresanteil ÜBER einem Monat."""
    assert jahresanteil_monate(date(2025, 7, 1), date(2025, 7, 31), 2025) > 1.0
    assert zahlmonate(date(2025, 7, 1), date(2025, 7, 31)) == 1.0


# --------------------------------------------------------------------------
# Was beide erfüllen müssen
# --------------------------------------------------------------------------

def test_ein_volles_jahr_ergibt_in_beiden_regeln_genau_zwoelf():
    for jahr in (2024, 2025):                       # Schaltjahr und Normaljahr
        anfang, ende = date(jahr, 1, 1), date(jahr, 12, 31)
        assert jahresanteil_monate(anfang, ende, jahr) == 12.0
        assert round(zahlmonate(anfang, ende), 9) == 12.0


def test_mieterwechsel_erzeugt_in_keiner_regel_einen_dreizehnten_monat():
    """Der Fehler, der beide Fassungen überhaupt entstehen liess: angebrochene
    Monate wurden an beiden Enden voll gezählt, ein Wechsel am 15. Juli ergab
    zusammen 13 Monate Miete."""
    vor_a = jahresanteil_monate(date(2025, 1, 1), date(2025, 7, 15), 2025)
    nach_a = jahresanteil_monate(date(2025, 7, 16), date(2025, 12, 31), 2025)
    assert round(vor_a + nach_a, 6) == 12.0

    vor_z = zahlmonate(date(2025, 1, 1), date(2025, 7, 15))
    nach_z = zahlmonate(date(2025, 7, 16), date(2025, 12, 31))
    assert round(vor_z + nach_z, 9) == 12.0


def test_halbes_jahr_ist_in_der_zahlregel_glatt():
    """01.01.–30.06. sind sechs Monatszahlungen, nicht 5,95."""
    assert round(zahlmonate(date(2025, 1, 1), date(2025, 6, 30)), 9) == 6.0
    assert jahresanteil_monate(date(2025, 1, 1), date(2025, 6, 30), 2025) < 6.0


def test_verdrehte_grenzen_ergeben_null_statt_eines_negativen_monats():
    assert jahresanteil_monate(date(2025, 8, 1), date(2025, 3, 1), 2025) == 0.0
    assert zahlmonate(date(2025, 8, 1), date(2025, 3, 1)) == 0.0


def test_zeitraum_ausserhalb_des_jahres_zaehlt_nicht():
    assert jahresanteil_monate(date(2023, 1, 1), date(2023, 12, 31), 2025) == 0.0


# --------------------------------------------------------------------------
# Die gewohnten Namen zeigen weiterhin auf dieselbe Rechnung
# --------------------------------------------------------------------------

def test_die_alten_namen_sind_dieselbe_funktion():
    """`cashflow.monate_im_jahr` und `weg._monate` bleiben als Namen bestehen —
    ein Dutzend Aufrufstellen hängt daran. Sie dürfen aber keine zweite
    Fassung mehr sein, sonst driften sie wieder auseinander."""
    from app import weg
    from app.cashflow import monate_im_jahr

    assert monate_im_jahr is jahresanteil_monate
    assert weg._monate is zahlmonate


# --------------------------------------------------------------------------
# N312 — die Vorauszahlung zählt Zahlmonate, nicht Tagesanteile
# --------------------------------------------------------------------------

def test_vorauszahlung_rechnet_mit_zahlmonaten():
    """Der Fund aus der Rechenlogik-Prüfung, an echten Zahlen nachgerechnet.

    `vorauszahlung_je_partei` vervielfacht einen MONATSbetrag. Sie rechnete mit
    `jahresanteil_monate` (Tagesanteil) statt `zahlmonate` — ein Mieter mit
    280 €/Monat vom 01.01. bis 28.02. überweist 560,00 €, angerechnet bekam er
    **543,12 €**. Die 16,88 € gingen unbemerkt in Guthaben bzw. Nachzahlung.

    Der Verteilungsschlüssel (Wohndauer, Personenmonate) bleibt bewusst beim
    Tagesanteil — deshalb prüft dieser Test beide Wege getrennt."""
    from app.verteilung import Bezug, _monate, _zahlmonate

    b = Bezug(partei="Alicia & Roman", ab=date(2026, 1, 1), bis=date(2026, 2, 28))
    start, ende = date(2026, 1, 1), date(2026, 12, 31)

    # Die Vorauszahlung: zwei volle Kalendermonate sind zwei Zahlungen.
    assert _zahlmonate(b, start, ende) == 2.0
    assert round(280 * _zahlmonate(b, start, ende), 2) == 560.00

    # Der Verteilungsschlüssel bleibt taggenau — 59 von 365 Tagen.
    assert _monate(b, start, ende) < 2.0
    assert round(280 * _monate(b, start, ende), 2) == 543.12


def test_einzelner_februar_kostet_die_volle_monatszahlung():
    from app.verteilung import Bezug, _zahlmonate

    b = Bezug(partei="X", ab=date(2025, 2, 1), bis=date(2025, 2, 28))
    monate = _zahlmonate(b, date(2025, 1, 1), date(2025, 12, 31))
    assert monate == 1.0
    assert round(244 * monate, 2) == 244.00        # nicht 224,61


def test_unterbrochenes_mietverhaeltnis_zaehlt_beide_stuecke():
    """Wie `_monate` verkraftet auch die Zahlvariante mehrere Spannen."""
    from app.verteilung import Bezug, _zahlmonate

    b = Bezug(partei="X", zeiten=[(date(2025, 1, 1), date(2025, 3, 31)),
                                  (date(2025, 7, 1), date(2025, 9, 30))])
    assert _zahlmonate(b, date(2025, 1, 1), date(2025, 12, 31)) == 6.0


# --------------------------------------------------------------------------
# N314 — der Turnus mit Umlaut war ein stiller Faktor 4
# --------------------------------------------------------------------------

def test_turnus_versteht_beide_schreibweisen():
    """`TURNUS` kannte nur die ae-Form. Die Oberfläche zeigt und die KI-Auslese
    speichert aber die Umlautform — „vierteljährlich" fiel damit still auf
    jährlich zurück: 125 € wurden zu 125 €/Jahr statt 500 €/Jahr."""
    from app.turnus import faktor, jahresbetrag

    for schreibweise in ("vierteljaehrlich", "vierteljährlich",
                         "Vierteljährlich", "  VIERTELJÄHRLICH  ",
                         "viertelj.ährlich"):
        assert faktor(schreibweise) == 4, schreibweise
        assert jahresbetrag(125, schreibweise) == 500.00, schreibweise

    assert faktor("halbjährlich") == 2
    assert faktor("halbjaehrlich") == 2
    assert faktor("monatlich") == 12
    assert faktor("jährlich") == 1


def test_wirklich_unbekannter_turnus_bleibt_jaehrlich():
    """Der Rückfall bleibt — er darf nur nicht mehr eine bekannte Schreibweise
    treffen."""
    from app.turnus import faktor

    assert faktor("alle Jubeljahre") == 1
    assert faktor("") == 1
    assert faktor(None) == 1
