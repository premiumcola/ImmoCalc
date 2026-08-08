"""N78 — der wasser-spezifische Auslese-Zweig.

Ein Wasser-/Abwasserbescheid rechnet drei Bereiche ab (Frisch-, Schmutz-,
Niederschlagswasser). Beim Ablegen auf die Wasser-Sammelposition schickt das
Frontend einen Kontext-Hinweis (`kostenart`) mit; die KI liest dann gezielt die
drei Bereichs-Gebühren und gibt sie als Feld `wasser` zurück.

Alles hier läuft ohne echten Netzaufruf: der KI-Parser wird mit einer gestellten
Modellantwort geprüft, der Endpunkt mit gemockten Bausteinen.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402

from app import kiauslese, ocr  # noqa: E402
from app.main import app  # noqa: E402
from app.routers import dokumente  # noqa: E402


# --------------------------------------------------------------------------
# 1) Der Prompt-Zweig: lies_wasser parst die drei Bereiche
# --------------------------------------------------------------------------

class _FakeAntwort:
    status_code = 200

    def __init__(self, text):
        self._text = text

    def json(self):
        return {"content": [{"type": "text", "text": self._text}]}


class _FakeHttpx:
    def __init__(self, text):
        self._text = text
        self.aufrufe = 0

    def post(self, *_a, **_k):
        self.aufrufe += 1
        return _FakeAntwort(self._text)


def test_ist_wasser_kontext_erkennt_die_bereiche():
    assert kiauslese.ist_wasser_kontext("Wasser") is True
    assert kiauslese.ist_wasser_kontext("Frischwasser") is True
    assert kiauslese.ist_wasser_kontext("Abwasser") is True
    assert kiauslese.ist_wasser_kontext("Niederschlagswasser") is True
    assert kiauslese.ist_wasser_kontext("Grundsteuer") is False
    assert kiauslese.ist_wasser_kontext("") is False


def test_lies_wasser_parst_drei_bereiche(monkeypatch):
    """Die drei Bereichs-Gebühren kommen als Floats durch; ein deutsches Komma
    oder Währungszeichen wird aufgeräumt, die Werte sind immer positiv."""
    antwort = ('{"wasser":298.05,"schmutz":362.56,"niederschlag":186.91,'
               '"gesamt_m3":122}')
    monkeypatch.setattr(kiauslese, "httpx", _FakeHttpx(antwort))
    ki = kiauslese.lies_wasser("irgendein OCR-Text", schluessel="test-key")
    assert ki == {"wasser": 298.05, "schmutz": 362.56, "niederschlag": 186.91,
                  "gesamt_m3": 122.0}


def test_lies_wasser_fehlender_bereich_bleibt_none(monkeypatch):
    antwort = ('{"wasser":"298,05 €","schmutz":null,"niederschlag":-186.91}')
    monkeypatch.setattr(kiauslese, "httpx", _FakeHttpx(antwort))
    ki = kiauslese.lies_wasser("text", schluessel="test-key")
    assert ki["wasser"] == 298.05
    assert ki["schmutz"] is None
    # Ein Betrag ist die Höhe der Forderung — immer positiv.
    assert ki["niederschlag"] == 186.91


def test_lies_wasser_ohne_key_ist_stumm(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert kiauslese.lies_wasser("text") is None


# --------------------------------------------------------------------------
# 1b) N102b — der Gesamtwasserverbrauch in m³
# --------------------------------------------------------------------------

def test_gesamt_m3_deutsches_komma_und_einheit(monkeypatch):
    """Der Bescheid nennt die Bemessungsgrundlage als \"122,00 cbm\" — daraus
    wird die Zahl 122.0."""
    antwort = ('{"wasser":298.05,"schmutz":362.56,"niederschlag":186.91,'
               '"gesamt_m3":"122,00 cbm"}')
    monkeypatch.setattr(kiauslese, "httpx", _FakeHttpx(antwort))
    ki = kiauslese.lies_wasser("text", schluessel="test-key")
    assert ki["gesamt_m3"] == 122.0
    # Die drei Beträge bleiben davon unberührt.
    assert (ki["wasser"], ki["schmutz"], ki["niederschlag"]) == (
        298.05, 362.56, 186.91)


def test_gesamt_m3_mit_einheit_m3_und_tausendertrenner(monkeypatch):
    antwort = '{"wasser":null,"schmutz":null,"niederschlag":null,' \
              '"gesamt_m3":"1.234,50 m³"}'
    monkeypatch.setattr(kiauslese, "httpx", _FakeHttpx(antwort))
    ki = kiauslese.lies_wasser("text", schluessel="test-key")
    assert ki["gesamt_m3"] == 1234.5


def test_gesamt_m3_teilmengen_werden_summiert(monkeypatch):
    """Nach einem Zählerwechsel führt der Wasser-Block Teilmengen. Summiert das
    Modell sie nicht selbst, addiert der Parser die Liste (102 + 40 = 142)."""
    antwort = ('{"wasser":298.05,"schmutz":null,"niederschlag":null,'
               '"gesamt_m3":["102 m³","40 m3"]}')
    monkeypatch.setattr(kiauslese, "httpx", _FakeHttpx(antwort))
    ki = kiauslese.lies_wasser("text", schluessel="test-key")
    assert ki["gesamt_m3"] == 142.0


def test_gesamt_m3_teilmengen_als_text_werden_summiert(monkeypatch):
    """Schreibt das Modell die Teilmengen in EINEN String, wird ebenfalls
    addiert — und die \"3\" aus \"m3\" rutscht nicht in die Zahl."""
    antwort = '{"wasser":null,"schmutz":null,"niederschlag":null,' \
              '"gesamt_m3":"102 m³ + 40 m3"}'
    monkeypatch.setattr(kiauslese, "httpx", _FakeHttpx(antwort))
    ki = kiauslese.lies_wasser("text", schluessel="test-key")
    assert ki["gesamt_m3"] == 142.0


def test_gesamt_m3_fehlt_bleibt_none(monkeypatch):
    """Fehlt die Menge auf dem Beleg (null, gar nicht genannt, 0 oder Unfug),
    ist das Feld None — nie ein erfundener Wert."""
    for roh in ('"gesamt_m3":null', '"gesamt_m3":0', '"gesamt_m3":"cbm"', ""):
        antwort = ('{"wasser":298.05,"schmutz":362.56,"niederschlag":186.91'
                   + (("," + roh) if roh else "") + "}")
        monkeypatch.setattr(kiauslese, "httpx", _FakeHttpx(antwort))
        ki = kiauslese.lies_wasser("text", schluessel="test-key")
        assert ki["gesamt_m3"] is None, roh
        # Die drei Beträge bleiben in jedem Fall erhalten.
        assert ki["wasser"] == 298.05


def test_wasser_prompt_nennt_die_fundstellen():
    """Der Prompt muss die Menge anfordern und sagen, wo sie steht — sonst
    liefert das Modell nur die drei Beträge."""
    p = kiauslese.WASSER_SYSTEM_PROMPT
    assert '"gesamt_m3"' in p
    assert "Wasserbezug" in p
    assert "SCHMUTZWASSER" in p
    assert "cbm" in p


# --------------------------------------------------------------------------
# 2) Die Antwortform des Endpunkts: /erkennen liefert das Feld `wasser`
# --------------------------------------------------------------------------

def _basis_erkennung(*_a, **_k):
    """Eine gewöhnliche Erkennungsantwort — ohne das Wasser-Feld."""
    return {"moeglich": True, "betrag": 847.52, "datum": "2025-03-01",
            "jahr": 2025, "kategorie": "Nebenkosten", "sache": "Wasser",
            "ist_kosten": True}


def test_erkennen_mit_wasser_hinweis_liefert_wasser(monkeypatch):
    """Mit Wasser-Hinweis und eingerichteter KI trägt die Antwort zusätzlich das
    Feld `wasser` mit den drei Bereichsbeträgen — die übrigen Felder bleiben."""
    monkeypatch.setattr(ocr, "erkenne", _basis_erkennung)
    monkeypatch.setattr(ocr, "text_aus_beleg", lambda *_a, **_k: "Wasserbescheid")
    monkeypatch.setattr(kiauslese, "verfuegbar", lambda *_a, **_k: True)
    monkeypatch.setattr(dokumente, "_ki_key", lambda _s: "test-key")
    monkeypatch.setattr(kiauslese, "lies_wasser", lambda *a, **k: {
        "wasser": 298.05, "schmutz": 362.56, "niederschlag": 186.91})
    with TestClient(app) as c:
        r = c.post("/api/dokumente/erkennen",
                   data={"kostenart": "Wasser"},
                   files={"datei": ("beleg.pdf", b"%PDF-1.4 test_erkennen_mit_wasser_hinweis_liefert_wasser",
                                    "application/pdf")})
    assert r.status_code == 200
    body = r.json()
    assert body["wasser"] == {"wasser": 298.05, "schmutz": 362.56,
                              "niederschlag": 186.91}
    # Die bestehenden Felder bleiben unverändert.
    assert body["betrag"] == 847.52
    assert body["kategorie"] == "Nebenkosten"


def test_erkennen_ohne_hinweis_hat_kein_wasser(monkeypatch):
    """Der generische Aufruf (kein Wasser-Hinweis) bleibt unverändert — kein
    zweiter KI-Aufruf, kein `wasser`-Feld."""
    monkeypatch.setattr(ocr, "erkenne", _basis_erkennung)
    monkeypatch.setattr(kiauslese, "verfuegbar", lambda *_a, **_k: True)
    monkeypatch.setattr(dokumente, "_ki_key", lambda _s: "test-key")

    def _darf_nicht_laufen(*_a, **_k):
        raise AssertionError("lies_wasser ohne Wasser-Hinweis aufgerufen")

    monkeypatch.setattr(kiauslese, "lies_wasser", _darf_nicht_laufen)
    with TestClient(app) as c:
        r = c.post("/api/dokumente/erkennen",
                   data={"kostenart": "Grundsteuer"},
                   files={"datei": ("beleg.pdf", b"%PDF-1.4 test_erkennen_ohne_hinweis_hat_kein_wasser",
                                    "application/pdf")})
    assert r.status_code == 200
    assert "wasser" not in r.json()


def test_erkennen_ohne_ki_liefert_kein_wasser(monkeypatch):
    """Ohne eingerichtete KI bleibt es bei der einfachen Erkennung, auch mit
    Wasser-Hinweis — keine erfundenen Bereichsbeträge."""
    monkeypatch.setattr(ocr, "erkenne", _basis_erkennung)
    monkeypatch.setattr(kiauslese, "verfuegbar", lambda *_a, **_k: False)
    with TestClient(app) as c:
        r = c.post("/api/dokumente/erkennen",
                   data={"kostenart": "Wasser"},
                   files={"datei": ("beleg.pdf", b"%PDF-1.4 test_erkennen_ohne_ki_liefert_kein_wasser",
                                    "application/pdf")})
    assert r.status_code == 200
    assert "wasser" not in r.json()
