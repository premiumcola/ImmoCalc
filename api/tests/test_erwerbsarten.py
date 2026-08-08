"""N276 — die Arten der einmaligen Erwerbsnebenkosten.

Der Anlass: die Auswahl kannte sechs Werte, die echten Belege des Nutzers
brauchten fuenfzehn. Wichtiger als die Zahl ist eine Trennung, die vorher
fehlte — auf zwei Notarrechnungen desselben Tages:

    Bautraegervertrag  URNr. S 848/17  KV 21100  1.829,03 EUR  → Erwerb
    Grundschuld        URNr. S 849/17  KV 21200    647,00 EUR  → Finanzierung

Erwerbsnebenkosten wandern in die Anschaffungskosten und werden abgeschrieben,
Finanzierungskosten sind sofort abzugsfaehige Werbungskosten. Wer beides unter
„Notar" fuehrt, rechnet die AfA falsch. Dieselbe Trennung beim Grundbuchamt:
KV 14110/14150 gehoert zum Erwerb, KV 14121 (Grundpfandrecht) zur Finanzierung.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import erwerb, feldzuordnung  # noqa: E402

FELDER_JS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "public", "assets", "objekt-felder.js")


def test_die_liste_gibt_es_nur_einmal():
    """Waechter: `ERWERB_ARTEN` in der Oberflaeche und `ERWERBSARTEN` im Server
    muessen deckungsgleich sein. Liefen sie auseinander, schluege die KI eine
    Art vor, die die Auswahl nicht kennt — das Feld bliebe leer und niemand
    wuesste warum."""
    with open(FELDER_JS, encoding="utf-8") as f:
        quelle = f.read()
    block = re.search(r"const ERWERB_ARTEN = \[(.*?)\];", quelle, re.S)
    assert block, "ERWERB_ARTEN nicht gefunden — wurde die Liste umbenannt?"
    aus_js = re.findall(r"'([^']+)'", block.group(1))
    assert aus_js == erwerb.ERWERBSARTEN


def test_erwerb_und_finanzierung_sind_getrennte_arten():
    """Der eigentliche Fachpunkt — beide muessen es geben und sie duerfen
    nicht dasselbe sein."""
    assert "Notar" in erwerb.ERWERBSARTEN
    assert "Notar – Grundschuldbestellung" in erwerb.ERWERBSARTEN
    assert "Grundbuchamt – Eigentumsumschreibung" in erwerb.ERWERBSARTEN
    assert "Grundbuchamt – Grundpfandrecht" in erwerb.ERWERBSARTEN


def test_die_belege_des_nutzers_haben_ihre_art():
    """Was auf den fotografierten Rechnungen steht, muss zuzuordnen sein."""
    for art in ("Vermessung / Gebäudeeinmessung", "Katasterfortführung",
                "Grunderwerbsteuer"):
        assert erwerb.erwerbsart(art) == art


def test_schreibweise_wird_toleriert():
    """Das Modell vertauscht Halbgeviert- und Bindestrich und variiert die
    Gross-/Kleinschreibung — beides darf die Zuordnung nicht kosten."""
    assert erwerb.erwerbsart("notar - grundschuldbestellung") == \
        "Notar – Grundschuldbestellung"
    assert erwerb.erwerbsart("  GRUNDERWERBSTEUER ") == "Grunderwerbsteuer"


def test_erfundene_art_wird_verworfen():
    """Lieber ein leeres Feld als ein falsch gefuelltes: eine Art, die es
    nicht gibt, saehe im Formular aus wie eine erkannte."""
    assert erwerb.erwerbsart("Vermessungsgebühr") is None
    assert erwerb.erwerbsart("") is None
    assert erwerb.erwerbsart(None) is None


def test_maske_wird_aus_der_auslese_gefuellt():
    ergebnis = {"felder": {"erwerbsart": "Grundbuchamt – Grundpfandrecht"},
                "betrag": 887.50, "datum": "2017-05-24", "jahr": 2017}
    werte = feldzuordnung.werte_fuer("erwerbskosten", ergebnis)
    assert werte["art"] == "Grundbuchamt – Grundpfandrecht"
    assert werte["betrag"] == 887.50
    assert werte["jahr"] == 2017


def test_ohne_erwerbsart_bleibt_die_art_leer():
    """Kein Rueckfall auf `kostenart`/`dokumenttyp` — die liefern Freitext wie
    „Kostenrechnung", und der passt in keine Auswahl."""
    werte = feldzuordnung.werte_fuer(
        "erwerbskosten",
        {"kostenart": "Kostenrechnung", "dokumenttyp": "Kostenrechnung",
         "betrag": 379.19})
    assert "art" not in werte
    assert werte["betrag"] == 379.19
