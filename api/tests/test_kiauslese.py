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
import json
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


# --------------------------------------------------------------------------
# N263 — die Auslese auf die Felder einer Eingabemaske übersetzt.
#
# Der Endpunkt bekommt zusätzlich `bereich`. Damit kommt `formwerte` zurück:
# dieselbe Auslese, aber auf die Feldnamen des Formulars gebracht. Das ist der
# Unterschied zwischen „die KI hat etwas erkannt" und „die Maske geht gefüllt
# auf" — vorher stand das Raster nur zur Anzeige da.
# --------------------------------------------------------------------------
def _notar_erkennung(*_a, **_k):
    """Was `ocr.erkenne` bei einem Notarvertrag zurückgäbe."""
    return {
        "moeglich": True, "betrag": 250000.0, "datum": "2024-05-17",
        "jahr": 2024, "monat": 5, "kategorie": "Notarvertrag",
        "sache": "Kaufvertrag", "ist_kosten": True, "zeichen": 900,
        "kosten_relevant": True, "nebenkosten": False,
        "zeitraum_hinweis": "", "zusammenfassung": "", "einordnung": "",
        "absender": "Notariat Dr. Vogel", "dokumenttyp": "Kaufvertrag",
        "felder": {"art": "Kaufvertrag", "notar": "Dr. Vogel, Nürnberg",
                   "urnr": "123/2024", "beurkundet_am": "2024-05-17",
                   "kaufpreis": 250000, "beteiligte": "Meier → Schmidt"},
    }


def _post_bereich(bereich):
    with TestClient(app) as c:
        return c.post("/api/dokumente/erkennen",
                      data={"bereich": bereich},
                      files={"datei": ("vertrag.pdf", b"%PDF-1.4 test",
                                       "application/pdf")})


def test_erkennen_uebersetzt_auf_die_felder_der_maske(monkeypatch):
    monkeypatch.setattr(ocr, "erkenne", _notar_erkennung)
    monkeypatch.setattr(kiauslese, "verfuegbar", lambda *_a, **_k: False)
    body = _post_bereich("notarvertraege").json()
    werte = body["formwerte"]
    # „Beurkundet am" heisst im Modell `datum`, der Kaufpreis `betrag` — genau
    # diese Übersetzung fehlte.
    assert werte["datum"] == "2024-05-17"
    assert werte["betrag"] == 250000.0
    assert werte["urnr"] == "123/2024"
    assert werte["notar"] == "Dr. Vogel, Nürnberg"
    # Der Namensvorschlag trägt Art und Nummer — die Urkundenrolle behält ihr
    # Jahr (ein Datumsfilter hatte sie zwischenzeitlich gekürzt).
    assert body["formname"] == "Notarvertrag Kaufvertrag URNr 123/2024"


def test_erkennen_ohne_bereich_bleibt_wie_zuvor(monkeypatch):
    """Additiv: bestehende Aufrufer schicken keinen Bereich und bekommen die
    Antwort unverändert — kein `formwerte`, das sie nicht erwarten."""
    monkeypatch.setattr(ocr, "erkenne", _notar_erkennung)
    monkeypatch.setattr(kiauslese, "verfuegbar", lambda *_a, **_k: False)
    body = _post_bereich("").json()
    assert "formwerte" not in body
    assert "formname" not in body


# --------------------------------------------------------------------------
# N262 — Teilzahlungen auf den Jahresbetrag hochrechnen
#
# Der ausloesende Fall: eine Abbuchungsvorankuendigung der Stadt Eckental fuer
# Grundsteuer B nennt zweimal 87,00 EUR (faellig 15.08. und 15.11.). Die
# Auslese schrieb dazu „nennt aber keine konkreten Betraege" — obwohl die
# Grundsteuer vierteljaehrlich faellig wird und damit 348,00 EUR im Jahr
# kostet. Gerechnet wird bewusst SERVERSEITIG: das Produkt ist die schwaechste
# Stelle einer Modellantwort, und ein falscher Jahreswert landete sonst
# ungeprueft in der Nebenkostenabrechnung.
# --------------------------------------------------------------------------
GRUNDSTEUER = ('{"dokumenttyp":"Abbuchungsvorank\\u00fcndigung",'
               '"kategorie":"Nebenkosten","kostenart":"Grundsteuer",'
               '"datum":"2026-06-11","betrag":348,'
               '"teilbetrag":87,"teilzahlungen":4,'
               '"ist_kosten":true,"kosten_relevant":true,"nebenkosten":true,'
               '"zusammenfassung":"Grundsteuer B, vierteljaehrlich."}')


def _auslese(text, monkeypatch):
    """Die Auslese mit einer gestellten Modellantwort — kein Netzaufruf."""
    monkeypatch.setattr(kiauslese, "httpx", _FakeHttpx(text))
    return kiauslese.lies_beleg("Abbuchungsvorankündigung Grundsteuer B",
                                "beleg.pdf", schluessel="test")


def test_quartalszahlung_wird_auf_das_jahr_hochgerechnet(monkeypatch):
    ergebnis = _auslese(GRUNDSTEUER, monkeypatch)
    assert ergebnis is not None
    assert ergebnis["betrag"] == 348.0
    # Die Herleitung bleibt sichtbar — sonst stuende ein Jahreswert da, den
    # niemand nachvollziehen kann.
    assert ergebnis["teilbetrag"] == 87.0
    assert ergebnis["teilzahlungen"] == 4
    assert ergebnis["kosten_relevant"] is True


def test_falsches_produkt_des_modells_wird_korrigiert(monkeypatch):
    """Rechnen ist die schwaechste Seite eines Sprachmodells. Liegen Teilbetrag
    und Anzahl vor, gilt das nachgerechnete Produkt — nicht die genannte Summe."""
    ergebnis = _auslese(GRUNDSTEUER.replace('"betrag":348', '"betrag":174'),
                        monkeypatch)
    assert ergebnis["betrag"] == 348.0


def test_einzelne_zahlung_ist_keine_hochrechnung(monkeypatch):
    """Eine jaehrliche Faelligkeit ist der Betrag selbst — dann darf keine
    Herleitung angezeigt werden, es gibt nichts herzuleiten."""
    ergebnis = _auslese(GRUNDSTEUER.replace('"teilzahlungen":4',
                                            '"teilzahlungen":1'), monkeypatch)
    assert ergebnis["teilbetrag"] is None
    assert ergebnis["teilzahlungen"] is None
    assert ergebnis["betrag"] == 348.0


def test_unplausible_anzahl_wird_verworfen(monkeypatch):
    """36 Zahlungen im Jahr gibt es nicht — dann lieber ohne Hochrechnung als
    mit einem erfundenen Vielfachen."""
    ergebnis = _auslese(GRUNDSTEUER.replace('"teilzahlungen":4',
                                            '"teilzahlungen":36'), monkeypatch)
    assert ergebnis["teilbetrag"] is None
    assert ergebnis["betrag"] == 348.0


def test_beleg_ohne_teilzahlungen_bleibt_unveraendert(monkeypatch):
    """Additiv: eine gewoehnliche Rechnung kennt die neuen Felder nicht und
    behaelt ihren Betrag."""
    ergebnis = _auslese(GRUNDSTEUER.replace('"teilbetrag":87,', '')
                        .replace('"teilzahlungen":4,', ''), monkeypatch)
    assert ergebnis["betrag"] == 348.0
    assert ergebnis["teilbetrag"] is None


# --------------------------------------------------------------------------
# N270 — das Gewerk einer Renovierungsrechnung
#
# Die Kreisdiagramm-Auswertung je Gewerk (Elektro, Sanitär, Maler …) braucht
# eine feste, kanonische Liste. Ein vom Modell erfundener Wert wäre eine
# Tortenscheibe, die es dort gar nicht gibt — deshalb wird serverseitig
# geprüft, nicht nur durchgereicht.
# --------------------------------------------------------------------------
ELEKTRIKER_RECHNUNG = (
    '{"dokumenttyp":"Rechnung","kategorie":"Sonstiges",'
    '"absender":"Elektro Mustermann GmbH","kostenart":"Zählerschrank erneuert",'
    '"gewerk":"Elektro","datum":"2026-03-04","betrag":1450.0,'
    '"ist_kosten":true,"kosten_relevant":true,"nebenkosten":false,'
    '"zusammenfassung":"Elektrorechnung fuer die Erneuerung des Zaehlerschranks."}'
)


def test_elektriker_rechnung_wird_als_elektro_gelesen(monkeypatch):
    ergebnis = _auslese(ELEKTRIKER_RECHNUNG, monkeypatch)
    assert ergebnis["gewerk"] == "Elektro"


def test_erfundenes_gewerk_wird_verworfen(monkeypatch):
    """„Fensterputzen" steht nicht in der festen Liste — das Feld bleibt leer,
    statt eine eigene, nicht existierende Tortenscheibe zu erzeugen."""
    erfunden = ELEKTRIKER_RECHNUNG.replace('"gewerk":"Elektro"',
                                           '"gewerk":"Fensterputzen"')
    ergebnis = _auslese(erfunden, monkeypatch)
    assert ergebnis["gewerk"] is None


def test_gewerk_wird_gross_klein_und_leerzeichen_tolerant_erkannt():
    assert kiauslese._gewerk("elektro ") == "Elektro"
    assert kiauslese._gewerk("  FASSADE & DÄMMUNG") == "Fassade & Dämmung"
    assert kiauslese._gewerk("Estrich  &   Böden") == "Estrich & Böden"


def test_beleg_ohne_gewerk_angabe_bleibt_none(monkeypatch):
    """Additiv: ein gewöhnlicher Beleg (Grundsteuer) kennt kein Gewerk und
    bricht daran nicht — bestehende Belege ändern sich nicht."""
    ergebnis = _auslese(GRUNDSTEUER, monkeypatch)
    assert ergebnis["gewerk"] is None


# --------------------------------------------------------------------------
# N270 — das Gewerk muss die GANZE Kette ueberleben
#
# Zwischen `kiauslese` (liest das Gewerk) und `feldzuordnung` (setzt es in die
# Maske) liegt `ocr.erkenne` als Nadeloehr: was dort nicht durchgereicht wird,
# kommt am Formular nie an. Genau diese Luecke gab es — beide Enden waren
# richtig, die Mitte reichte `gewerk` nicht weiter. Der Test haelt die Kette
# als Ganzes fest, nicht ihre Einzelteile.
# --------------------------------------------------------------------------

def _leeres_ergebnis() -> dict:
    return {"sache": "", "kategorie": "", "betrag": None, "datum": None,
            "jahr": None, "monat": None, "ist_kosten": True}


def _mit_auslese(monkeypatch, auslese):
    """`_ki_ergaenzen` ruft die Auslese selbst auf und aendert `ergebnis` an
    Ort und Stelle. Statt eines Netzaufrufs wird hier die fertige Auslese
    untergeschoben — geprueft wird die Weitergabe, nicht das Modell."""
    monkeypatch.setattr(kiauslese, "verfuegbar", lambda *_a, **_k: True)
    monkeypatch.setattr(kiauslese, "lies_beleg", lambda *_a, **_k: auslese)
    ergebnis = _leeres_ergebnis()
    ocr._ki_ergaenzen(ergebnis, "Rechnungstext", "rechnung.pdf", ki_key="test")
    return ergebnis


def test_gewerk_ueberlebt_ocr_bis_in_die_formularwerte(monkeypatch):
    from app import feldzuordnung
    ergebnis = _mit_auslese(monkeypatch, {
        "gewerk": "Elektro", "absender": "Muster Elektro GmbH",
        "betrag": 2450.0, "datum": "2025-03-14"})
    assert ergebnis["gewerk"] == "Elektro"
    werte = feldzuordnung.werte_fuer("renovierungsposten", ergebnis)
    assert werte["gewerk"] == "Elektro"
    assert werte["firma"] == "Muster Elektro GmbH"


def test_ohne_gewerk_bleibt_das_feld_weg(monkeypatch):
    """Additiv: ein Beleg ohne Gewerk darf kein leeres Feld erzeugen — ein ""
    saehe in der Maske aus wie eine Angabe."""
    ergebnis = _mit_auslese(monkeypatch, {"absender": "Muster GmbH"})
    assert "gewerk" not in ergebnis


# --------------------------------------------------------------------------
# N273 — die fertige WEG-Einzelabrechnung lesen.
#
# Am echten Beleg (Delta-t Messdienst Wenzel GmbH, Unterschöllenbacher
# Hauptstr. 6a, 01.01.–31.12.2025). Die eine Verwechslung, um die es hier geht:
# „Ihre Kosten" ist die Spalte GANZ RECHTS (103,24), nicht die Gesamtkosten der
# Liegenschaft (788,80).
# --------------------------------------------------------------------------
WEG_ANTWORT = """{
 "firma":"Delta-t Messdienst Wenzel GmbH",
 "liegenschaft":"Unterschöllenbacher Hauptstr. 6a","nutzer_nr":"0004-001",
 "von":"2025-01-01","bis":"2025-12-31","datum":"2026-03-16",
 "positionen":[
  {"bezeichnung":"Wasserkosten","gesamtkosten":"788,80","ihre_kosten":"103,24",
   "schluessel":"Wasser gesamt","umlagefaehig":true},
  {"bezeichnung":"Müllgebühren","gesamtkosten":"690,78","ihre_kosten":"138,18",
   "schluessel":"Personen","umlagefaehig":true},
  {"bezeichnung":"Versicherungen","gesamtkosten":"1.824,55",
   "ihre_kosten":"442,18","schluessel":"m2 Betriebsk.","umlagefaehig":true},
  {"bezeichnung":"Verwalter","gesamtkosten":"1.028,16","ihre_kosten":"205,63",
   "schluessel":"Anzahl WE","umlagefaehig":true},
  {"bezeichnung":"Prüfung Rauchwarnmelder","gesamtkosten":"20,83",
   "ihre_kosten":"4,17","schluessel":"Anzahl RWM","umlagefaehig":true},
  {"bezeichnung":"Anschaffungen","gesamtkosten":"112,69","ihre_kosten":"22,54",
   "schluessel":"","umlagefaehig":false},
  {"bezeichnung":"Reparatur","gesamtkosten":"135,66","ihre_kosten":"27,13",
   "schluessel":"","umlagefaehig":false},
  {"bezeichnung":"Schädlingsbekämpfung","gesamtkosten":"821,10",
   "ihre_kosten":"164,22","schluessel":"","umlagefaehig":false}],
 "heizkosten":"730,60","warmwasserkosten":"205,67",
 "betriebskosten":"893,40","rechnungsbetrag":"1.829,67",
 "vorauszahlung":"2.928,00","nachzahlung":null}"""


def test_lies_weg_abrechnung_am_echten_beleg(monkeypatch):
    monkeypatch.setattr(kiauslese, "httpx", _FakeHttpx(WEG_ANTWORT))
    ki = kiauslese.lies_weg_abrechnung("OCR-Text", schluessel="test-key")
    assert ki["firma"] == "Delta-t Messdienst Wenzel GmbH"
    assert ki["nutzer_nr"] == "0004-001"
    assert ki["von"] == "2025-01-01" and ki["bis"] == "2025-12-31"
    assert ki["datum"] == "2026-03-16"
    # Heiz- und Warmwasserkosten sind eigene Positionen, keine Betriebskosten.
    assert ki["heizkosten"] == 730.60 and ki["warmwasserkosten"] == 205.67
    assert all(p["bezeichnung"] not in ("Heizkosten", "Warmwasser")
               for p in ki["positionen"])


def test_weg_nimmt_die_spalte_ganz_rechts():
    """788,80 sind die Kosten der ganzen Liegenschaft, 103,24 die des Nutzers.
    Wer die Spalten vertauscht, rechnet dem Mieter das Vielfache auf."""
    ki = kiauslese.weg_ergebnis(json.loads(WEG_ANTWORT))
    wasser = next(p for p in ki["positionen"] if p["bezeichnung"] == "Wasserkosten")
    assert wasser["ihre_kosten"] == 103.24
    assert wasser["gesamtkosten"] == 788.80
    assert wasser["schluessel"] == "Wasser gesamt"


def test_weg_markiert_die_nicht_umlagefaehigen():
    """Der Block „Nicht umlagefähig" wird gelesen, aber gekennzeichnet — er
    darf später nie zur Kostenposition werden."""
    ki = kiauslese.weg_ergebnis(json.loads(WEG_ANTWORT))
    nicht = {p["bezeichnung"] for p in ki["positionen"] if not p["umlagefaehig"]}
    assert nicht == {"Anschaffungen", "Reparatur", "Schädlingsbekämpfung"}
    assert len([p for p in ki["positionen"] if p["umlagefaehig"]]) == 5
    assert round(sum(p["ihre_kosten"] for p in ki["positionen"]
                     if not p["umlagefaehig"]), 2) == 213.89


def test_weg_deutsche_schreibweise_wird_aufgeraeumt():
    """„1.824,55" ist tausendachthundert, nicht eins Komma acht — hier verliest
    sich die reine Betragslogik, in der der letzte Punkt dezimal ist."""
    ki = kiauslese.weg_ergebnis(json.loads(WEG_ANTWORT))
    versicherung = next(p for p in ki["positionen"]
                        if p["bezeichnung"] == "Versicherungen")
    assert versicherung["gesamtkosten"] == 1824.55
    assert ki["vorauszahlung"] == 2928.00
    assert kiauslese._weg_betrag("2.008") == 2008.0     # Tausender, nicht 2,008


def test_weg_warnt_wenn_die_summe_nicht_zum_deckblatt_passt():
    """Serverseitig nachgerechnet: 103,24 + 138,18 + 442,18 + 205,63 + 4,17 =
    893,40. Steht auf dem Deckblatt etwas anderes, wird das vermerkt — das
    Ergebnis aber NICHT verworfen."""
    block = json.loads(WEG_ANTWORT)
    assert kiauslese.weg_ergebnis(block)["warnung"] == ""
    block["betriebskosten"] = "2.008,28"
    schief = kiauslese.weg_ergebnis(block)
    assert schief["warnung"]
    assert "893.40" in schief["warnung"] and "2008.28" in schief["warnung"]
    assert len(schief["positionen"]) == 8         # trotzdem alles da


def test_weg_ohne_abrechnung_ist_none(monkeypatch):
    antwort = '{"positionen":[],"heizkosten":null,"warmwasserkosten":null}'
    monkeypatch.setattr(kiauslese, "httpx", _FakeHttpx(antwort))
    assert kiauslese.lies_weg_abrechnung("text", schluessel="test-key") is None


def test_weg_ohne_key_ist_stumm(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert kiauslese.lies_weg_abrechnung("text") is None


def test_weg_prompt_nennt_die_teure_verwechslung():
    """Ohne die ausdrückliche Ansage greift das Modell zur Gesamtkostenspalte —
    der Prompt ist hier die eigentliche Fachlogik."""
    p = kiauslese.WEG_SYSTEM_PROMPT
    assert "GANZ RECHTS" in p and "GANZ LINKS" in p
    assert "103,24" in p and "788,80" in p          # das Beispiel steht drin
    assert "Nicht umlagefähig" in p and "umlagefaehig = " in p
    assert "kleineren" in p                          # die Notbremse bei Zweifel


# --------------------------------------------------------------------------
# N287 — Risiken aus der Modularisierungs-Analyse
# --------------------------------------------------------------------------

def test_menge_liest_deutsche_tausender_richtig():
    """Der teuerste Lesefehler des Backends: `_menge` rief `_betrag`, und der
    nimmt den letzten Punkt als Dezimaltrenner (bei Geld richtig). Aus einem
    Wasserbescheid ueber „2.416 m3" wurden damit 2,416 m3 — der Wert geht als
    `rechnung_m3` in `wasser.verrechne` und bestimmt dort den Preis je m3 und
    die Verteilung auf ALLE Einheiten. Faktor 1000, unbemerkt."""
    assert kiauslese._menge("2.416 m\u00b3") == 2416.0
    assert kiauslese._menge("1.234,56 m3") == 1234.56
    assert kiauslese._menge("122,00 cbm") == 122.0
    # Ein Punkt mit ein bis zwei Stellen bleibt dezimal (12,5 m3).
    assert kiauslese._menge("12.5") == 12.5
    # Teilmengen bei Zaehlerwechsel werden weiter addiert.
    assert kiauslese._menge("102 m\u00b3 + 40 m\u00b3") == 142.0
    # Eine Menge ist ihr Betrag — ein Vorzeichen waere ein Lesefehler.
    assert kiauslese._menge(-2416) == 2416.0
    assert kiauslese._menge("") is None
    assert kiauslese._menge(0) is None
