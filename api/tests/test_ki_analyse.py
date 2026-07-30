"""CCCLXVII — die KI-Analyse: kein Betrag aus einer Geräte-Kennung, und die
erweiterte, inhaltliche Einschätzung (Kosten? NK? Zeitraum? Zusammenfassung).

Der belegte Fehlgriff: eine Schornsteinfeger-*Messbescheinigung* (kein
Rechnungsbeleg) bekam 2.003,03 € vorgeschlagen — der Wert stammte aus der
Geräte-Kennung „Weishaupt,WTU 30 G,6138521,2003,03/2004" (ein Herstelldatum).

Alles hier läuft ohne echten Netzaufruf: die Betragsheuristik ist rein, und der
KI-Parser wird mit einer gestellten Modellantwort geprüft.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import kiauslese, ocr  # noqa: E402


# --------------------------------------------------------------------------
# 1) Kein Betrag aus einer Kennung/Serien-/Datumsfolge
# --------------------------------------------------------------------------

def test_geraete_kennung_ergibt_keinen_betrag():
    """Die Weishaupt-Plakette darf nie einen Rechnungsbetrag hergeben — weder
    als ganze Zeile noch, wenn die OCR sie in Stücke zerlegt."""
    assert ocr.betrag_aus_text("Weishaupt,WTU 30 G,6138521,2003,03/2004") is None
    # Zerlegt die OCR die Plakette, beginnt „2003,03/2004" eine eigene Zeile —
    # genau der Weg, auf dem 2.003,03 € durchrutschte.
    assert ocr.betrag_aus_text("2003,03/2004") is None
    assert ocr.betrag_aus_text("Zaehler-Nr 2003,03/2004") is None
    # Eine trennerlose Seriennummer ist kein Betrag.
    assert ocr.betrag_aus_text("Serie 6138521,20") is None


def test_echter_rechnungsbetrag_bleibt_erhalten():
    """Was fixiert werden muss, damit die Härtung nicht zu viel wegnimmt: ein
    echter Rechnungsbetrag wird weiterhin gelesen."""
    assert ocr.betrag_aus_text("Rechnungsbetrag 91,80 €") == 91.80
    assert ocr.betrag_aus_text("Gesamtbetrag 1.071,00") == 1071.00
    assert ocr.betrag_aus_text("Rechnungsbetrag EUR 104.15") == 104.15


# --------------------------------------------------------------------------
# 2) Der Parser der erweiterten KI-Antwort — mit Defaults, ohne Netz
# --------------------------------------------------------------------------

class _FakeAntwort:
    status_code = 200

    def __init__(self, text):
        self._text = text

    def json(self):
        return {"content": [{"type": "text", "text": self._text}]}


class _FakeHttpx:
    """Ein httpx-Ersatz, der immer dieselbe gestellte Modellantwort liefert."""

    def __init__(self, text):
        self._text = text
        self.aufrufe = 0

    def post(self, *_a, **_k):
        self.aufrufe += 1
        return _FakeAntwort(self._text)


def _lies_mit_antwort(monkeypatch, json_text):
    monkeypatch.setattr(kiauslese, "httpx", _FakeHttpx(json_text))
    return kiauslese.lies_beleg("irgendein OCR-Text", schluessel="test-key")


def test_erweiterte_felder_werden_geparst(monkeypatch):
    """Die neuen Felder kommen durch — bool als bool, die Zusammenfassung
    ungekürzt (nicht auf 60 Zeichen abgeschnitten wie die alte Einordnung)."""
    lange = ("Dies ist eine Schornsteinfeger-Messbescheinigung der Firma Muster "
             "vom Maerz 2025. Es sind keine umlagefaehigen Kosten entstanden, "
             "da nur eine Messung bescheinigt wird. Sie gehoert nicht in die "
             "Nebenkostenabrechnung und betrifft keinen Abrechnungszeitraum.")
    antwort = (
        '{"dokumenttyp":"Messbescheinigung","kategorie":"Nebenkosten",'
        '"datum":"2025-03-10","betrag":null,"ist_kosten":false,'
        '"kosten_relevant":false,"nebenkosten":false,'
        '"zeitraum_hinweis":"kein Abrechnungsbeleg",'
        '"kostenart":"Schornsteinfeger","felder":{},'
        '"zusammenfassung":"' + lange + '"}')
    ki = _lies_mit_antwort(monkeypatch, antwort)
    assert ki is not None
    assert ki["kosten_relevant"] is False
    assert ki["nebenkosten"] is False
    assert ki["zeitraum_hinweis"] == "kein Abrechnungsbeleg"
    assert ki["betrag"] is None
    # Die Zusammenfassung steht ungekürzt (mehr als die alten 60 Zeichen) und
    # dient zugleich als Einordnung.
    assert ki["zusammenfassung"] == lange
    assert ki["einordnung"] == lange
    assert len(ki["zusammenfassung"]) > 60


def test_fehlende_felder_bleiben_offen_nicht_falsch(monkeypatch):
    """Eine ältere/knappe Antwort ohne die neuen Felder darf sie nicht
    stillschweigend auf false setzen — sonst verlöre ein echter Beleg seinen
    Betrag. `einordnung` (alt) füllt die Zusammenfassung."""
    antwort = ('{"dokumenttyp":"Rechnung","kategorie":"Nebenkosten",'
               '"betrag":91.8,"ist_kosten":true,"kostenart":"Wasser",'
               '"einordnung":"Wasserrechnung der Stadtwerke."}')
    ki = _lies_mit_antwort(monkeypatch, antwort)
    assert ki["kosten_relevant"] is None
    assert ki["nebenkosten"] is None
    assert ki["betrag"] == 91.8
    assert ki["zusammenfassung"] == "Wasserrechnung der Stadtwerke."
    assert ki["einordnung"] == "Wasserrechnung der Stadtwerke."


def test_hilfsparser_wahrheit_und_langtext():
    assert kiauslese._wahrheit(True) is True
    assert kiauslese._wahrheit("ja") is True
    assert kiauslese._wahrheit("nein") is False
    assert kiauslese._wahrheit(None) is None
    assert kiauslese._wahrheit("vielleicht") is None
    # Langtext säubert Whitespace, kürzt hart erst bei 400 Zeichen.
    assert kiauslese._langtext("  a\n\n b ") == "a b"
    assert len(kiauslese._langtext("x " * 500)) <= 400


# --------------------------------------------------------------------------
# 3) Die Kosten-Schranke in _ki_ergaenzen: false ⇒ kein Betrag
# --------------------------------------------------------------------------

def _ki_dict(**ueber):
    basis = {"datum": None, "betrag": None, "kostenart": "", "kategorie": "",
             "ist_kosten": True, "kosten_relevant": None, "nebenkosten": None,
             "zeitraum_hinweis": "", "zusammenfassung": "", "einordnung": "",
             "dokumenttyp": "", "immobilie": "", "einheit": "", "felder": {}}
    basis.update(ueber)
    return basis


def test_kosten_relevant_false_streicht_den_betrag(monkeypatch):
    """Sagt die KI, es sind keine echten Kosten entstanden, verschwindet der
    Betrag — auch aus dem Raster, das das Prüfblatt sonst vorbelegt."""
    monkeypatch.setattr(kiauslese, "verfuegbar", lambda *_a, **_k: True)
    monkeypatch.setattr(kiauslese, "lies_beleg", lambda *a, **k: _ki_dict(
        betrag=2003.03, kosten_relevant=False, nebenkosten=False,
        felder={"betrag": 2003.03, "kostenart": "Schornsteinfeger"},
        zusammenfassung="Messbescheinigung, keine Kosten."))
    ergebnis = {"betrag": 2003.03, "ist_kosten": True, "kategorie": "",
                "sache": ""}
    ocr._ki_ergaenzen(ergebnis, "text", ki_key="test")
    assert ergebnis["betrag"] is None
    assert ergebnis["kosten_relevant"] is False
    assert "betrag" not in ergebnis.get("felder", {})
    assert ergebnis["einordnung"] == "Messbescheinigung, keine Kosten."


def test_kosten_relevant_true_behaelt_den_betrag(monkeypatch):
    """Der Gegentest: bei echten Kosten bleibt der KI-Betrag stehen."""
    monkeypatch.setattr(kiauslese, "verfuegbar", lambda *_a, **_k: True)
    monkeypatch.setattr(kiauslese, "lies_beleg", lambda *a, **k: _ki_dict(
        betrag=91.8, kosten_relevant=True, nebenkosten=True,
        zusammenfassung="Wasserrechnung."))
    ergebnis = {"betrag": None, "ist_kosten": True, "kategorie": "", "sache": ""}
    ocr._ki_ergaenzen(ergebnis, "text", ki_key="test")
    assert ergebnis["betrag"] == 91.8
    assert ergebnis["kosten_relevant"] is True
    assert ergebnis["nebenkosten"] is True
