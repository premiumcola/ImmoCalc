"""N170 — vom geladenen Strom zur gefahrenen Strecke.

Drei Dinge werden hier geprüft, alle ohne Netz:

1. Die reine Rechenlogik — km, Preis je 100 km, Benzin-Äquivalent — trifft die
   erwarteten Zahlen und erfindet nichts, wo die Grundlage fehlt.
2. Die Plausibilitätsgrenzen (~12–30 kWh/100km) fangen Ausreißer und die 0
   („Modell unbekannt") ab.
3. Die KI-Ermittlung stürzt bei keinem Fehler ab: kein Schlüssel, Netzfehler,
   HTTP-Fehler, kaputte oder unplausible Antwort führen alle zum ehrlichen
   Hinweis — nie zu einer Exception, nie zu einer erfundenen Zahl. Der
   Handeintrag ist der Rückfallweg.

Der einzige Netz-Aufruf (`httpx.post`) wird durchweg durch ein Doppel ersetzt;
kein Test geht ins Internet.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest  # noqa: E402

from app import eauto  # noqa: E402


# --------------------------------------------------------------------------
# 1) Reine Rechenlogik
# --------------------------------------------------------------------------

def test_gefahrene_km():
    # 100 kWh bei 20 kWh/100km → 500 km.
    assert eauto.gefahrene_km(100.0, 20.0) == 500.0
    # 50 kWh bei 16 kWh/100km → 312,5 km.
    assert eauto.gefahrene_km(50.0, 16.0) == 312.5
    # Ohne Verbrauch oder Menge keine Strecke — None statt einer erfundenen 0.
    assert eauto.gefahrene_km(100.0, 0.0) is None
    assert eauto.gefahrene_km(100.0, None) is None
    assert eauto.gefahrene_km(None, 20.0) is None


def test_preis_je_100km_passt_zum_betrag():
    # 32 € für 500 km → 6,40 € je 100 km.
    assert eauto.preis_je_100km(32.0, 500.0) == 6.4
    # Ohne Betrag oder ohne Strecke: None (keine 0).
    assert eauto.preis_je_100km(None, 500.0) is None
    assert eauto.preis_je_100km(32.0, 0.0) is None
    assert eauto.preis_je_100km(32.0, None) is None


def test_preis_je_100km_gleich_satz_mal_verbrauch():
    """Der Preis je 100 km ist konsistent, egal welchen Weg man rechnet:
    Betrag ÷ km × 100 == Satz je kWh × Verbrauch."""
    kwh, satz, verbrauch = 100.0, 0.32, 18.0
    betrag = kwh * satz
    km = eauto.gefahrene_km(kwh, verbrauch)
    ueber_betrag = eauto.preis_je_100km(betrag, km)
    ueber_satz = round(satz * verbrauch, 2)
    assert ueber_betrag == ueber_satz == 5.76


def test_benzin_aequivalent_mit_annahme():
    # 18 kWh/100km ÷ 9,7 ≈ 1,9 l/100km.
    assert eauto.benzin_aequivalent(18.0) == 1.9
    assert eauto.benzin_aequivalent(24.25) == 2.5
    assert eauto.benzin_aequivalent(0.0) is None
    assert eauto.benzin_aequivalent(None) is None
    # Die Annahme steht als Konstante bereit, damit sie überall mitgenannt wird.
    assert eauto.BENZIN_KWH_PRO_LITER == 9.7


def test_kennzahlen_bündelt_die_drei_groessen():
    kz = eauto.kennzahlen(100.0, 32.0, 20.0)
    assert kz["km"] == 500.0
    assert kz["preis_100km"] == 6.4
    # 20 / 9,7 ≈ 2,1 l/100km.
    assert kz["liter_100km"] == 2.1
    # Ohne Verbrauch bleibt alles leer — keine erfundene Zahl.
    leer = eauto.kennzahlen(100.0, 32.0, 0.0)
    assert leer == {"km": None, "preis_100km": None, "liter_100km": None}
    # Menge da, aber kein Betrag (Satz fehlt): km ja, Preis nein.
    ohne_preis = eauto.kennzahlen(100.0, None, 20.0)
    assert ohne_preis["km"] == 500.0 and ohne_preis["preis_100km"] is None
    assert ohne_preis["liter_100km"] == 2.1


# --------------------------------------------------------------------------
# 2) Plausibilitätsgrenzen
# --------------------------------------------------------------------------

def test_plausibel_haelt_reale_werte():
    assert eauto.plausibel(12.0) is True
    assert eauto.plausibel(18.5) is True
    assert eauto.plausibel(30.0) is True
    # Außerhalb 12–30: kein belastbarer E-Auto-Verbrauch.
    assert eauto.plausibel(11.9) is False
    assert eauto.plausibel(30.1) is False
    assert eauto.plausibel(0.0) is False        # „Modell unbekannt"
    assert eauto.plausibel(-5.0) is False
    # bool ist in Python eine Zahl — hier nie ein Verbrauch.
    assert eauto.plausibel(True) is False
    assert eauto.plausibel(None) is False
    assert eauto.plausibel("18") is False


def test_erste_zahl_liest_deutsche_und_englische_schreibweise():
    assert eauto._erste_zahl("16.5") == 16.5
    assert eauto._erste_zahl("16,5") == 16.5
    assert eauto._erste_zahl("etwa 18 kWh/100km") == 18.0
    assert eauto._erste_zahl("18,3 kWh") == 18.3
    assert eauto._erste_zahl("keine Ahnung") is None
    assert eauto._erste_zahl("") is None


# --------------------------------------------------------------------------
# 3) Die KI-Ermittlung — der einzige Netz-Aufruf, durchweg als Doppel
# --------------------------------------------------------------------------

class _Antwort:
    """Ein httpx-Antwortdoppel: fester Status, feste JSON-Nutzlast."""

    def __init__(self, status_code=200, nutzlast=None):
        self.status_code = status_code
        self._nutzlast = nutzlast or {}

    def json(self):
        return self._nutzlast


def _ki_antwort(text: str):
    """Die Anthropic-Nutzlast in der Form, die der Reader erwartet."""
    return {"content": [{"type": "text", "text": text}]}


def _fake_post(antwort):
    def post(url, headers=None, json=None, timeout=None):
        return antwort
    return post


def test_ermittelt_plausiblen_verbrauch(monkeypatch):
    """Die KI nennt eine Zahl; sie wird gelesen und (weil plausibel) übernommen."""
    monkeypatch.setattr(eauto.httpx, "post",
                        _fake_post(_Antwort(200, _ki_antwort("16.5"))))
    verbrauch, hinweis = eauto.verbrauch_ermitteln("VW ID.3", schluessel="k")
    assert verbrauch == 16.5 and hinweis == ""


def test_unplausibler_wert_wird_verworfen(monkeypatch):
    """Ein Ausreißer (99) oder die 0 wird nicht gespeichert — Hinweis statt
    absurder km-Zahl."""
    monkeypatch.setattr(eauto.httpx, "post",
                        _fake_post(_Antwort(200, _ki_antwort("99"))))
    verbrauch, hinweis = eauto.verbrauch_ermitteln("Rennwagen", schluessel="k")
    assert verbrauch is None
    assert hinweis == eauto.HINWEIS_HAND

    monkeypatch.setattr(eauto.httpx, "post",
                        _fake_post(_Antwort(200, _ki_antwort("0"))))
    verbrauch, hinweis = eauto.verbrauch_ermitteln("Unbekannt XYZ", schluessel="k")
    assert verbrauch is None and hinweis == eauto.HINWEIS_HAND


def test_ohne_schluessel_bleibt_stumm(monkeypatch):
    """Ohne Schlüssel (und ohne Env) wird gar nicht erst gefragt — Handeintrag."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    verbrauch, hinweis = eauto.verbrauch_ermitteln("VW ID.3", schluessel="")
    assert verbrauch is None and hinweis == eauto.HINWEIS_HAND


def test_leeres_modell_verlangt_eine_eingabe():
    verbrauch, hinweis = eauto.verbrauch_ermitteln("   ", schluessel="k")
    assert verbrauch is None and "Modell" in hinweis


def test_netzfehler_stuerzt_nicht_ab(monkeypatch):
    """Wirft der Aufruf (Timeout, DNS, …), kommt ein Hinweis — nie eine
    Exception nach außen."""
    def post(*a, **k):
        raise RuntimeError("Netzwerk weg")
    monkeypatch.setattr(eauto.httpx, "post", post)
    verbrauch, hinweis = eauto.verbrauch_ermitteln("VW ID.3", schluessel="k")
    assert verbrauch is None and hinweis == eauto.HINWEIS_HAND


def test_http_fehler_stuerzt_nicht_ab(monkeypatch):
    monkeypatch.setattr(eauto.httpx, "post",
                        _fake_post(_Antwort(429, {})))
    verbrauch, hinweis = eauto.verbrauch_ermitteln("VW ID.3", schluessel="k")
    assert verbrauch is None and hinweis == eauto.HINWEIS_HAND


def test_kaputte_antwort_stuerzt_nicht_ab(monkeypatch):
    """Eine Antwort ohne verwertbare Zahl (oder mit kaputtem JSON) führt zum
    Hinweis, nicht zum Absturz."""
    monkeypatch.setattr(eauto.httpx, "post",
                        _fake_post(_Antwort(200, _ki_antwort("keine Angabe"))))
    verbrauch, hinweis = eauto.verbrauch_ermitteln("VW ID.3", schluessel="k")
    assert verbrauch is None and hinweis == eauto.HINWEIS_HAND

    class _Kaputt:
        status_code = 200

        def json(self):
            raise ValueError("kein JSON")

    monkeypatch.setattr(eauto.httpx, "post", _fake_post(_Kaputt()))
    verbrauch, hinweis = eauto.verbrauch_ermitteln("VW ID.3", schluessel="k")
    assert verbrauch is None and hinweis == eauto.HINWEIS_HAND


def test_handeintrag_ist_der_rueckfallweg():
    """Der Handeintrag geht immer, unabhängig von der KI: die reine Rechenlogik
    setzt ihn direkt in km/Preis/Benzin um."""
    # Ein von Hand gesetzter Verbrauch (z. B. 17,4) trägt die ganze Rechnung.
    kz = eauto.kennzahlen(50.0, 16.0, 17.4)
    assert kz["km"] == round(50.0 / 17.4 * 100.0, 1)
    assert kz["liter_100km"] == round(17.4 / 9.7, 1)
    assert kz["preis_100km"] is not None
