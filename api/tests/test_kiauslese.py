"""N162 — der strom-spezifische Auslese-Zweig.

Beim Strom ist der einzige Beleg in der Hochlage der externe Zukauf. Gebraucht
werden daraus zwei Zahlen: die verbrauchten Kilowattstunden und der Bruttopreis
dafür (Grundpreis enthalten). Betrag je Menge ist der Netzpreis, aus dem die
Stromkette PV und Akku mit 10 % Abschlag ableitet.

Die Prüfsteine hier drehen sich um das Auseinanderhalten der drei Beträge, die
auf einer Jahresabrechnung nebeneinander stehen — am echten Beleg des Nutzers
(Elektrizitätsversorgung Berlin, 15.06.2024–14.06.2025):

    Bruttobetrag der Lieferung   862,51 €   ← damit wird gerechnet
    Nachzahlung nach Abschlägen   55,51 €   ← ein Zwanzigstel davon
    monatlicher Abschlag          72,00 €
    Jahresverbrauch            2.416   kWh  → 0,357 €/kWh

Alles läuft ohne echten Netzaufruf: der Parser wird mit einer gestellten
Modellantwort geprüft, der Endpunkt mit gemockten Bausteinen.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402

from app import kiauslese, ocr  # noqa: E402
from app.main import app  # noqa: E402
from app.routers import dokumente  # noqa: E402

# Die Modellantwort zum echten Beleg — genau die Zahlen, die auf dem Blatt
# stehen. Sie ist der Maßstab für alles Folgende.
ECHTER_BELEG = ('{"menge_kwh":2416,"brutto":862.51,"netto":724.80,'
                '"nachzahlung":55.51,"guthaben":null,"abschlag_monat":72.00,'
                '"von":"2024-06-15","bis":"2025-06-14"}')


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


# --------------------------------------------------------------------------
# 1) Zahlen lesen: eine Menge ist kein Geldbetrag
# --------------------------------------------------------------------------

def test_zahl_de_haelt_tausender_und_dezimal_auseinander():
    """„2.416" sind zweitausendvierhundertsechzehn, nicht 2,416. Genau hier
    verliest sich die Betragslogik, in der der letzte Punkt dezimal ist."""
    assert kiauslese._zahl_de("2.416") == 2416.0
    assert kiauslese._zahl_de("2.416,0") == 2416.0
    assert kiauslese._zahl_de("1.234.567") == 1234567.0
    assert kiauslese._zahl_de("862,51") == 862.51
    # Ohne Dreiergliederung bleibt der Punkt der Dezimaltrenner (12,5 MWh).
    assert kiauslese._zahl_de("12.5") == 12.5
    assert kiauslese._zahl_de("") is None
    assert kiauslese._zahl_de("kWh") is None


def test_kwh_liest_menge_mit_einheit():
    assert kiauslese._kwh(2416) == 2416.0
    assert kiauslese._kwh("2.416 kWh") == 2416.0
    assert kiauslese._kwh("2.416,0 kWh") == 2416.0
    assert kiauslese._kwh("2416 Kilowattstunden") == 2416.0


def test_kwh_rechnet_megawattstunden_um():
    assert kiauslese._kwh("12,5 MWh") == 12500.0
    assert kiauslese._kwh("1 MWh") == 1000.0


def test_kwh_summiert_teilmengen():
    """Wegen des Preiswechsels zum 01.01. führt der Beleg zwei Teilmengen
    (1256 + 1160). Summiert das Modell sie nicht, addiert der Parser."""
    assert kiauslese._kwh(["1256 kWh", "1160 kWh"]) == 2416.0
    assert kiauslese._kwh("1256 kWh + 1160 kWh") == 2416.0


def test_kwh_ohne_belastbare_angabe_ist_none():
    for roh in (None, "", "kWh", 0, True, {"a": 1}):
        assert kiauslese._kwh(roh) is None, roh
    # Ein Vorzeichen ist ein Lesefehler, kein Verbrauch — die Menge ist ihr
    # Betrag (dieselbe Regel wie bei Geld und bei m³).
    assert kiauslese._kwh(-2416) == 2416.0


# --------------------------------------------------------------------------
# 2) Die drei Beträge auseinanderhalten
# --------------------------------------------------------------------------

def test_lies_strom_am_echten_beleg(monkeypatch):
    """Menge und Bruttobetrag der Lieferung — nicht die Nachzahlung."""
    monkeypatch.setattr(kiauslese, "httpx", _FakeHttpx(ECHTER_BELEG))
    ki = kiauslese.lies_strom("OCR-Text der Rechnung", schluessel="test-key")
    assert ki["menge_kwh"] == 2416.0
    assert ki["einheit"] == "kWh"
    assert ki["betrag"] == 862.51
    assert ki["betrag_art"] == "lieferung"
    # Der Grundpreis steckt im Bruttobetrag und wird nicht getrennt umgelegt:
    # Betrag durch Menge ergibt den Netzpreis der Excel-Referenz.
    assert ki["preis_kwh"] == 0.357
    assert ki["von"] == "2024-06-15" and ki["bis"] == "2025-06-14"


def test_lies_strom_nimmt_nie_die_nachzahlung_als_betrag(monkeypatch):
    """55,51 € ist der Restsaldo nach Abzug der Abschläge, 72,00 € der Abschlag.
    Beide stehen einzeln bereit, aber gerechnet wird mit 862,51 €."""
    monkeypatch.setattr(kiauslese, "httpx", _FakeHttpx(ECHTER_BELEG))
    ki = kiauslese.lies_strom("text", schluessel="test-key")
    assert ki["betrag"] != 55.51 and ki["betrag"] != 72.00
    assert ki["nachzahlung"] == 55.51
    assert ki["abschlag_monat"] == 72.00
    assert ki["netto"] == 724.80


def test_lies_strom_zeigt_alle_kandidaten_benannt(monkeypatch):
    """Mehrere plausible Beträge werden nicht verschwiegen — sie kommen alle
    mit, jeder mit seiner Bezeichnung, der beste zuerst."""
    monkeypatch.setattr(kiauslese, "httpx", _FakeHttpx(ECHTER_BELEG))
    ki = kiauslese.lies_strom("text", schluessel="test-key")
    assert [k["art"] for k in ki["kandidaten"]] == ["lieferung", "nachzahlung",
                                                    "abschlag"]
    assert [k["betrag"] for k in ki["kandidaten"]] == [862.51, 55.51, 72.00]
    assert all(k["label"] for k in ki["kandidaten"])
    assert "Grundpreis enthalten" in ki["betrag_label"]


def test_lies_strom_nur_nachzahlung_bleibt_nicht_stumm(monkeypatch):
    """Steht auf dem Beleg wirklich nur eine Nachzahlung, ist ein benannter
    Betrag besser als ein leeres Feld — aber er heißt dann auch so."""
    antwort = ('{"menge_kwh":2416,"brutto":null,"netto":null,'
               '"nachzahlung":55.51,"abschlag_monat":null,'
               '"von":null,"bis":null}')
    monkeypatch.setattr(kiauslese, "httpx", _FakeHttpx(antwort))
    ki = kiauslese.lies_strom("text", schluessel="test-key")
    assert ki["betrag"] == 55.51
    assert ki["betrag_art"] == "nachzahlung"
    assert "Nachzahlung" in ki["betrag_label"]
    assert ki["brutto"] is None


def test_lies_strom_deutsche_schreibweise_wird_aufgeraeumt(monkeypatch):
    antwort = ('{"menge_kwh":"2.416,0 kWh","brutto":"862,51 EUR",'
               '"nachzahlung":"-55,51","abschlag_monat":null,'
               '"von":"2024-06-15","bis":"2025-06-14"}')
    monkeypatch.setattr(kiauslese, "httpx", _FakeHttpx(antwort))
    ki = kiauslese.lies_strom("text", schluessel="test-key")
    assert ki["menge_kwh"] == 2416.0
    assert ki["brutto"] == 862.51
    # Ein Betrag ist die Höhe der Forderung — immer positiv.
    assert ki["nachzahlung"] == 55.51


def test_lies_strom_ohne_strombeleg_ist_none(monkeypatch):
    """Kein Strombeleg — dann nichts erfinden, auch keine leere Hülle."""
    antwort = ('{"menge_kwh":null,"brutto":null,"netto":null,'
               '"nachzahlung":null,"abschlag_monat":null,'
               '"von":null,"bis":null}')
    monkeypatch.setattr(kiauslese, "httpx", _FakeHttpx(antwort))
    assert kiauslese.lies_strom("text", schluessel="test-key") is None


def test_lies_strom_ohne_key_ist_stumm(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert kiauslese.lies_strom("text") is None


def test_ist_strom_kontext():
    for ja in ("Strom", "Allgemeinstrom", "Hausstrom", "Stromkosten",
               "Elektrizitätsversorgung Berlin ElVeBe GmbH"):
        assert kiauslese.ist_strom_kontext(ja) is True, ja
    for nein in ("Wasser", "Grundsteuer", "Heizöl", ""):
        assert kiauslese.ist_strom_kontext(nein) is False, nein


def test_strom_prompt_haelt_die_betraege_auseinander():
    """Ohne die ausdrückliche Abgrenzung im Prompt greift das Modell zur
    Nachzahlung — der Prompt ist hier die eigentliche Fachlogik."""
    p = kiauslese.STROM_SYSTEM_PROMPT
    assert '"menge_kwh"' in p and '"brutto"' in p
    assert "Nachzahlung" in p and "Abschlag" in p
    assert "Grundpreis" in p
    assert "862.51" in p and "55.51" in p          # das Beispiel steht drin
    assert "Zählerstand" in p                       # und die Abgrenzung dazu


def test_allgemeiner_prompt_kennt_das_strom_raster():
    """Auch ohne den gezielten Zweig soll das Raster Menge und Bruttobetrag
    tragen — additiv ergänzt, die übrigen Belegarten bleiben unberührt."""
    p = kiauslese.SYSTEM_PROMPT
    assert "verbrauch_kwh" in p and "bruttobetrag" in p
    assert "abschlag_monat" in p
    assert "MIETVERTRAG" in p and "NEBENKOSTEN-RECHNUNG" in p   # unverändert


# --------------------------------------------------------------------------
# 3) Die Antwortform des Endpunkts
# --------------------------------------------------------------------------

def _strom_auslese(*_a, **_k):
    return {"menge_kwh": 2416.0, "einheit": "kWh", "betrag": 862.51,
            "betrag_art": "lieferung",
            "betrag_label": kiauslese.STROM_BETRAGSARTEN["lieferung"],
            "kandidaten": [], "brutto": 862.51, "netto": 724.80,
            "nachzahlung": 55.51, "guthaben": None, "abschlag_monat": 72.0,
            "von": "2024-06-15", "bis": "2025-06-14", "preis_kwh": 0.357}


def _erkennung_mit_regel(*_a, **_k):
    """Was der allgemeine Weg am echten Beleg liefert: Die Nutzerregel
    „N-ERGIE Netz" trifft die Fußzeile der Rechnung, stellt sie auf „keine
    Kosten" — und der Betrag ist weg. Im Raster steht die Nachzahlung."""
    return {"moeglich": True, "betrag": None, "datum": "2025-06-28",
            "jahr": 2024, "kategorie": "Sonstiges", "sache": "Zählerablesung",
            "ist_kosten": False, "kosten_relevant": True, "regel": True,
            "absender": "Elektrizitätsversorgung Berlin ElVeBe GmbH",
            "felder": {"kostenart": "Strom", "betrag": 55.51,
                       "verbrauch": 2416.0},
            "ki": True}


def _strom_umgebung(monkeypatch):
    monkeypatch.setattr(ocr, "text_aus_beleg", lambda *_a, **_k: "Stromrechnung")
    monkeypatch.setattr(kiauslese, "verfuegbar", lambda *_a, **_k: True)
    monkeypatch.setattr(dokumente, "_ki_key", lambda _s: "test-key")
    monkeypatch.setattr(kiauslese, "lies_strom", _strom_auslese)


def _post(kostenart=""):
    with TestClient(app) as c:
        return c.post("/api/dokumente/erkennen",
                      data={"kostenart": kostenart},
                      files={"datei": ("beleg.pdf", b"%PDF-1.4 test",
                                       "application/pdf")})


def test_erkennen_liefert_menge_und_bruttobetrag(monkeypatch):
    monkeypatch.setattr(ocr, "erkenne", _erkennung_mit_regel)
    _strom_umgebung(monkeypatch)
    r = _post("Strom")
    assert r.status_code == 200
    body = r.json()
    assert body["strom"]["menge_kwh"] == 2416.0
    assert body["strom"]["betrag"] == 862.51
    assert body["strom"]["von"] == "2024-06-15"


def test_erkennen_fuellt_das_leere_betragsfeld(monkeypatch):
    """Der gemeldete Fehler: die Zahlen standen im Fließtext, das Betragsfeld
    blieb leer. Jetzt trägt `betrag` den Bruttobetrag der Lieferung."""
    monkeypatch.setattr(ocr, "erkenne", _erkennung_mit_regel)
    _strom_umgebung(monkeypatch)
    body = _post("Strom").json()
    assert body["betrag"] == 862.51
    # Und nicht die Nachzahlung — auch nicht im Raster, aus dem das Prüfblatt
    # seine Eingaben vorbelegt.
    assert body["felder"]["betrag"] == 862.51
    assert body["felder"]["verbrauch_kwh"] == 2416.0
    assert body["felder"]["nachzahlung"] == 55.51
    assert body["felder"]["abschlag_monat"] == 72.0
    assert "Grundpreis enthalten" in body["felder"]["betrag_art"]
    assert body["felder"]["zeitraum"] == "15.06.2024 – 14.06.2025"


def test_erkennen_holt_den_kostenbeleg_aus_der_regel_zurueck(monkeypatch):
    """Eine Verbrauchsabrechnung mit Menge UND Bruttobetrag ist zweifelsfrei ein
    Kostenbeleg — auch wenn ein Regelmuster („N-ERGIE Netz") in der Fußzeile
    getroffen hat."""
    monkeypatch.setattr(ocr, "erkenne", _erkennung_mit_regel)
    _strom_umgebung(monkeypatch)
    body = _post("Strom").json()
    assert body["ist_kosten"] is True


def test_erkennen_greift_auch_ohne_hinweis(monkeypatch):
    """Im Dokumenteneingang schickt niemand eine Kostenart mit. Der Absender
    („Elektrizitätsversorgung") und die Raster-Kostenart genügen."""
    monkeypatch.setattr(ocr, "erkenne", _erkennung_mit_regel)
    _strom_umgebung(monkeypatch)
    body = _post().json()
    assert body["strom"]["betrag"] == 862.51


def test_erkennen_ohne_strombeleg_ruft_die_ki_nicht(monkeypatch):
    """Ein Wasserbescheid kostet keinen zusätzlichen Strom-Aufruf."""
    monkeypatch.setattr(ocr, "erkenne", lambda *_a, **_k: {
        "moeglich": True, "betrag": 847.52, "sache": "Wasser",
        "kategorie": "Nebenkosten", "ist_kosten": True})
    monkeypatch.setattr(ocr, "text_aus_beleg", lambda *_a, **_k: "Bescheid")
    monkeypatch.setattr(kiauslese, "verfuegbar", lambda *_a, **_k: True)
    monkeypatch.setattr(dokumente, "_ki_key", lambda _s: "test-key")
    monkeypatch.setattr(kiauslese, "lies_wasser", lambda *_a, **_k: None)

    def _darf_nicht_laufen(*_a, **_k):
        raise AssertionError("lies_strom ohne Strom-Kontext aufgerufen")

    monkeypatch.setattr(kiauslese, "lies_strom", _darf_nicht_laufen)
    body = _post("Wasser").json()
    assert "strom" not in body
    assert body["betrag"] == 847.52


def test_erkennen_ohne_ki_bleibt_stumm(monkeypatch):
    """Ohne eingerichtete KI keine erfundene Menge — die Antwort bleibt, wie
    sie ohne den Zweig wäre."""
    monkeypatch.setattr(ocr, "erkenne", _erkennung_mit_regel)
    monkeypatch.setattr(kiauslese, "verfuegbar", lambda *_a, **_k: False)
    body = _post("Strom").json()
    assert "strom" not in body
    assert body["betrag"] is None


def test_zeitraum_text():
    assert dokumente._zeitraum_text("2024-06-15", "2025-06-14") == \
        "15.06.2024 – 14.06.2025"
    assert dokumente._zeitraum_text("2024-06-15", None) == "15.06.2024"
    assert dokumente._zeitraum_text(None, None) == ""
    assert dokumente._zeitraum_text("Unfug", "auch") == ""
