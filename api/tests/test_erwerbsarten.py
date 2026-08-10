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

from app import erwerb, feldzuordnung, kiauslese  # noqa: E402

FELDER_JS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "public", "assets", "objekt-felder.js")


class _FakeAntwort:
    status_code = 200

    def __init__(self, text):
        self._text = text

    def json(self):
        return {"content": [{"type": "text", "text": self._text}]}


class _FakeHttpx:
    """Stellt die Modellantwort — kein echter Netzaufruf (wie in
    test_kiauslese.py)."""

    def __init__(self, text):
        self._text = text

    def post(self, *_a, **_k):
        return _FakeAntwort(self._text)


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


def test_alte_sammelbezeichnungen_bleiben_gueltig():
    """Additiv, nicht umbenannt: ein Objekt, das schon vor N276 mit einer der
    drei alten Sammelbezeichnungen getaggt wurde, muss weiterhin einen Treffer
    in `ERWERB_ARTEN`/`ERWERBSARTEN` finden. Sonst faellt auswahl.js (siehe
    `zeichne()` in auswahl.js — ohne Treffer zeigt es den ERSTEN Listeneintrag)
    auf "Notar" zurueck, obwohl am Objekt "Makler" oder "Gutachter" steht."""
    for alt in ("Grundbuch / Grundschuld", "Makler", "Gutachter"):
        assert alt in erwerb.ERWERBSARTEN
        assert erwerb.erwerbsart(alt) == alt


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


# --------------------------------------------------------------------------
# Der eigentliche Fachpunkt end-to-end: die KV-Nummer der GNotKG-Rechnung
# entscheidet, nicht der Absender „Notar" allein. Modelliert nach den zwei
# echten Notarrechnungen desselben Tages (siehe Modul-Docstring); der
# Netzaufruf ist gestellt (`_FakeHttpx`), geprueft wird die Kette
# Prompt-Anweisung -> Modellantwort -> `erwerb.erwerbsart`-Kanonisierung.
# --------------------------------------------------------------------------
KV_21100_BAUTRAEGERVERTRAG = """
Notare Dr. Schwanecke und Christian Braun
Kostenrechnung gemäß GNotKG

URNr. S 848/17 vom 13.04.2017 — Bauträgervertrag
Geschäftswert: 280.000,00 EUR

KV 21100 Beurkundungsverfahren (Satz 2,0)              1.560,00 EUR
KV 22200 Betreuungsgebühr                                120,00 EUR
KV 32011 Dokumentenpauschale (210 Seiten)                  52,50 EUR
Auslagenpauschale                                          20,00 EUR
zzgl. 19% USt.                                             76,53 EUR
-----------------------------------------------------------------
Rechnungsbetrag                                        1.829,03 EUR
"""

KV_21200_GRUNDSCHULD = """
Notare Dr. Schwanecke und Christian Braun
Kostenrechnung gemäß GNotKG

URNr. S 849/17 vom 13.04.2017 — Grundschuldbestellung
Geschäftswert: 240.000,00 EUR

KV 21200 Beurkundungsverfahren                           540,00 EUR
Auslagenpauschale                                         20,00 EUR
zzgl. 19% USt.                                             87,00 EUR
-----------------------------------------------------------------
Rechnungsbetrag                                          647,00 EUR
"""

KV_14110_EIGENTUMSUMSCHREIBUNG = """
Landesjustizkasse Bamberg
Kostenrechnung in der Grundbuchsache

KV 14110 Eigentumsumschreibung                           620,00 EUR
KatFortGebG Katasterfortführungsgebühr                    45,00 EUR
KV 14152 Löschung Auflassungsvormerkung                  120,50 EUR
-----------------------------------------------------------------
Rechnungsbetrag                                          785,50 EUR
"""

KV_14121_GRUNDPFANDRECHT = """
Landesjustizkasse Bamberg
Kostenrechnung in der Grundbuchsache

KV 14150 Auflassungsvormerkung                           140,00 EUR
KV 14121 Grundpfandrecht                                 700,50 EUR
KV 17000 Grundbuchausdruck                                47,00 EUR
-----------------------------------------------------------------
Rechnungsbetrag                                          887,50 EUR
"""


def _modellantwort(erwerbsart: str, betrag: float) -> str:
    """Was das Modell laut SYSTEM_PROMPT fuer eine dieser Rechnungen liefern
    soll — hier gestellt statt ueber einen echten Netzaufruf."""
    return (
        '{"dokumenttyp":"Kostenrechnung","kategorie":"Erwerbsnebenkosten",'
        '"betrag":%s,"ist_kosten":true,"kosten_relevant":true,'
        '"felder":{"erwerbsart":"%s"}}' % (betrag, erwerbsart)
    )


def _lies(monkeypatch, text, erwerbsart_laut_modell, betrag):
    monkeypatch.setattr(
        kiauslese, "httpx",
        _FakeHttpx(_modellantwort(erwerbsart_laut_modell, betrag)))
    return kiauslese.lies_beleg(text, "kostenrechnung.pdf",
                                schluessel="test-key")


def test_kv_21100_wird_notar_nicht_grundschuldbestellung(monkeypatch):
    """Der Bautraegervertrag/Kaufvertrag (KV 21100) ist ERWERB — die
    Anschaffungskosten, nicht die Finanzierung."""
    ergebnis = _lies(monkeypatch, KV_21100_BAUTRAEGERVERTRAG, "Notar", 1829.03)
    assert ergebnis["felder"]["erwerbsart"] == "Notar"


def test_kv_21200_wird_grundschuldbestellung_nicht_notar(monkeypatch):
    """Dieselben Notare, derselbe Tag, aber KV 21200 — die
    Grundschuldbestellung ist FINANZIERUNG, keine Anschaffungskosten. Die
    fachlich wichtige Verwechslung, die N276 ausloeste."""
    ergebnis = _lies(monkeypatch, KV_21200_GRUNDSCHULD,
                      "Notar – Grundschuldbestellung", 647.00)
    assert ergebnis["felder"]["erwerbsart"] == "Notar – Grundschuldbestellung"
    assert ergebnis["felder"]["erwerbsart"] != "Notar"


def test_kv_14110_wird_eigentumsumschreibung(monkeypatch):
    ergebnis = _lies(monkeypatch, KV_14110_EIGENTUMSUMSCHREIBUNG,
                      "Grundbuchamt – Eigentumsumschreibung", 785.50)
    assert ergebnis["felder"]["erwerbsart"] == \
        "Grundbuchamt – Eigentumsumschreibung"


def test_kv_14121_wird_grundpfandrecht_nicht_umschreibung(monkeypatch):
    """Dieselbe Landesjustizkasse, aber KV 14121 (Grundpfandrecht) ist
    FINANZIERUNG — die andere Haelfte derselben Verwechslungsgefahr wie beim
    Notar, diesmal beim Grundbuchamt."""
    ergebnis = _lies(monkeypatch, KV_14121_GRUNDPFANDRECHT,
                      "Grundbuchamt – Grundpfandrecht", 887.50)
    assert ergebnis["felder"]["erwerbsart"] == "Grundbuchamt – Grundpfandrecht"
    assert ergebnis["felder"]["erwerbsart"] != \
        "Grundbuchamt – Eigentumsumschreibung"


def test_mehrere_positionen_liefern_einen_dateinamens_zusatz(monkeypatch):
    """N331b — der Nutzer-Fund am echten Beleg: die Kategorie der grössten
    Einzelposition sagt „Grundbuchamt – Grundpfandrecht", aber der Dateiname
    soll BEIDE grossen Positionen nennen, nicht nur die Kategorie — „die
    Summe ist ja kein wirklicher Wert, das sind zwei einzelne Sachen"."""
    antwort = (
        '{"dokumenttyp":"Kostenrechnung","kategorie":"Erwerbsnebenkosten",'
        '"betrag":887.50,"ist_kosten":true,"kosten_relevant":true,'
        '"felder":{"erwerbsart":"Grundbuchamt – Grundpfandrecht"},'
        '"erwerb_teile":[{"bezeichnung":"Auflassungsvormerkung","betrag":292.50},'
        '{"bezeichnung":"Grundpfandrecht","betrag":535.00},'
        '{"bezeichnung":"Sondernutzungsrechte","betrag":50.00}]}'
    )
    monkeypatch.setattr(kiauslese, "httpx", _FakeHttpx(antwort))
    ergebnis = kiauslese.lies_beleg("text", "kostenrechnung.pdf",
                                    schluessel="test-key")
    # Nur die zwei betragsmässig grössten — Sondernutzungsrechte (50,00) fällt
    # raus, absteigend nach Betrag sortiert (nicht in Modell-Reihenfolge).
    assert ergebnis["felder"]["erwerb_teile"] == \
        "Grundpfandrecht und Auflassungsvormerkung"


def test_eine_einzelne_position_liefert_keinen_dateinamens_zusatz(monkeypatch):
    """Nur EINE Position: der Zusatz bleibt weg — die Art allein reicht schon,
    ein „Notar und" ohne zweiten Teil wäre unsinnig."""
    ergebnis = _lies(monkeypatch, KV_21100_BAUTRAEGERVERTRAG, "Notar", 1829.03)
    assert "erwerb_teile" not in ergebnis["felder"]


def test_erwerb_teile_text_verwirft_unvollstaendige_eintraege():
    """Ein Eintrag ohne Bezeichnung oder ohne Betrag zählt nicht mit — sonst
    entstünde ein Dateiname mit einer halben, sinnlosen Angabe."""
    assert kiauslese._erwerb_teile_text([
        {"bezeichnung": "Grundpfandrecht", "betrag": 535.0},
        {"bezeichnung": "", "betrag": 292.50},
        {"betrag": 50.0},
    ]) == ""                                       # nur EIN brauchbarer Eintrag
    assert kiauslese._erwerb_teile_text("kein array") == ""
    assert kiauslese._erwerb_teile_text([]) == ""


def test_prompt_nennt_die_kv_nummern_beider_trennungen():
    """Der Prompt ist hier die eigentliche Fachlogik (wie beim Strom- und
    WEG-Prompt) — ohne die ausdrueckliche KV-Zuordnung griffe das Modell bei
    "Notar" immer zur selben Art, egal welche Rechnung."""
    p = kiauslese.SYSTEM_PROMPT
    assert "21100" in p and "21200" in p
    assert "14110" in p and "14121" in p
    assert "Notar – Grundschuldbestellung" in p
    assert "Grundbuchamt – Grundpfandrecht" in p
    assert "Landesjustizkasse" in p
    assert "Amt für Digitalisierung" in p
