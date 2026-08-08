"""N288-B2 — der eine Weg zum Modell (`kiclient.frage_modell`).

Der HTTP-Rumpf stand sieben Mal wörtlich im Haus (sechs Fassungen in
`kiauslese.py`, eine in `eauto.py`). Er steht jetzt ein Mal — und wird hier ein
Mal geprüft: Kopfzeilen, Nutzlast, Bildweg, Zeitlimit, Wiederholung und die
Übersetzung jedes Fehlers in eine `Antwort`, die nie eine Exception trägt.

**Kein Netz.** Jeder Aufruf bekommt ein HTTP-Doppel; zusätzlich verriegelt eine
Fixture das echte `httpx` im Modul, damit auch ein vergessenes `http=`-Argument
nicht heimlich telefoniert.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import kiclient  # noqa: E402


# --------------------------------------------------------------------------
# Doppel — der Aufruf geht nie ins Netz
# --------------------------------------------------------------------------

class _Antwort:
    """Eine gespielte HTTP-Antwort: fester Status, feste Nutzlast."""

    def __init__(self, status=200, nutzlast=None, kaputt=False):
        self.status_code = status
        self._nutzlast = nutzlast if nutzlast is not None else {}
        self._kaputt = kaputt

    def json(self):
        if self._kaputt:
            raise ValueError("kein JSON")
        return self._nutzlast


def _text_antwort(text: str, status: int = 200) -> _Antwort:
    """Die Anthropic-Nutzlast in der Form, die der Leser erwartet."""
    return _Antwort(status, {"content": [{"type": "text", "text": text}]})


class _Http:
    """Ein httpx-Ersatz, der jeden Aufruf mitschreibt und Antworten austeilt."""

    def __init__(self, *antworten):
        self._antworten = list(antworten) or [_text_antwort("ok")]
        self.aufrufe: list[dict] = []

    def post(self, url, headers=None, json=None, timeout=None):
        self.aufrufe.append({"url": url, "headers": headers, "rumpf": json,
                             "timeout": timeout})
        return self._antworten[min(len(self.aufrufe) - 1,
                                   len(self._antworten) - 1)]


class _Kracht:
    """Ein Transport, der gar nicht erst zustande kommt."""

    def __init__(self):
        self.aufrufe = 0

    def post(self, *_a, **_k):
        self.aufrufe += 1
        raise OSError("kein Netz")


@pytest.fixture(autouse=True)
def kein_echtes_netz(monkeypatch):
    """Der Riegel: das Modul-eigene `httpx` fliegt raus. Wer es doch nimmt,
    bekommt einen Fehlschlag statt einer Rechnung bei Anthropic."""
    class _Verboten:
        @staticmethod
        def post(*_a, **_k):
            raise AssertionError("Ein Test darf nie ins Netz gehen.")

    monkeypatch.setattr(kiclient, "httpx", _Verboten)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")


# --------------------------------------------------------------------------
# 1) Was gesendet wird
# --------------------------------------------------------------------------

def test_kopf_und_nutzlast_stehen_wie_vorher():
    """Ein Aufruf trägt Schlüssel, Version, Modell, Systemprompt und Text —
    genau die Felder, die jede der sieben Fassungen einzeln aufgebaut hat."""
    http = _Http(_text_antwort("hallo"))
    antwort = kiclient.frage_modell("Beleg-Text", schluessel="geheim",
                                    modell="mein-modell", system="Sei knapp.",
                                    max_tokens=42, zeitlimit=7.5, http=http)

    assert antwort.ok and antwort.text == "hallo"
    ruf = http.aufrufe[0]
    assert ruf["url"] == kiclient.API_URL
    assert ruf["timeout"] == 7.5
    assert ruf["headers"] == {"x-api-key": "geheim",
                              "anthropic-version": kiclient.API_VERSION,
                              "content-type": "application/json"}
    assert ruf["rumpf"]["model"] == "mein-modell"
    assert ruf["rumpf"]["max_tokens"] == 42
    assert ruf["rumpf"]["system"] == "Sei knapp."
    assert ruf["rumpf"]["messages"] == [{"role": "user",
                                         "content": "Beleg-Text"}]


def test_ohne_systemprompt_steht_kein_leeres_feld_im_rumpf():
    """Orientierung, SolarEdge und der Ping schickten nie ein `system` mit —
    ein leeres Feld wäre eine Änderung an der Anfrage."""
    http = _Http()
    kiclient.frage_modell("ping", schluessel="k", max_tokens=1, http=http)
    assert "system" not in http.aufrufe[0]["rumpf"]


def test_bild_geht_als_base64_mit_seinem_typ_voran():
    """Der Bildweg (Orientierung, SolarEdge): erst das Bild, dann die Frage —
    und ein JPEG darf nicht als PNG angekündigt werden."""
    http = _Http()
    kiclient.frage_modell("Wie herum?", schluessel="k", bild=b"\x89PNG-Daten",
                          media_type="image/jpeg", http=http)

    inhalt = http.aufrufe[0]["rumpf"]["messages"][0]["content"]
    assert inhalt[0]["type"] == "image"
    assert inhalt[0]["source"]["type"] == "base64"
    assert inhalt[0]["source"]["media_type"] == "image/jpeg"
    assert inhalt[0]["source"]["data"] == "iVBORy1EYXRlbg=="
    assert inhalt[1] == {"type": "text", "text": "Wie herum?"}


def test_modell_und_schluessel_haben_vorrang_vor_der_umgebung(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "aus-der-env")
    monkeypatch.setenv("ANTHROPIC_MODEL", "env-modell")
    http = _Http()

    kiclient.frage_modell("x", schluessel="uebergeben", modell="uebergeben-m",
                          http=http)
    assert http.aufrufe[0]["headers"]["x-api-key"] == "uebergeben"
    assert http.aufrufe[0]["rumpf"]["model"] == "uebergeben-m"

    kiclient.frage_modell("x", http=http)
    assert http.aufrufe[1]["headers"]["x-api-key"] == "aus-der-env"
    assert http.aufrufe[1]["rumpf"]["model"] == "env-modell"


def test_ohne_beides_gilt_das_kleinste_modell(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    assert kiclient.api_modell() == kiclient.STANDARD_MODELL


# --------------------------------------------------------------------------
# 2) Was zurückkommt — und was bei jedem Fehler passiert
# --------------------------------------------------------------------------

def test_json_block_kommt_auch_aus_einem_umschliessenden_satz():
    """Das Modell hält sich meist an „NUR JSON" — ein Markdown-Zaun oder ein
    Begleitsatz darf die Auslese trotzdem nicht scheitern lassen."""
    http = _Http(_text_antwort("Gerne!\n```json\n{\"betrag\": 12.5}\n```\n"))
    antwort = kiclient.frage_modell("x", http=http)
    assert antwort.ok and antwort.block == {"betrag": 12.5}


def test_ohne_json_bleibt_der_block_leer_und_der_text_steht():
    """Die Zahl-Antworten (Orientierung, E-Auto-Verbrauch) sind kein JSON —
    sie kommen über `text` durch, ohne dass der Aufruf als Fehler gilt."""
    http = _Http(_text_antwort("90"))
    antwort = kiclient.frage_modell("x", http=http)
    assert antwort.ok and antwort.block is None and antwort.text == "90"


def test_netzfehler_wird_zur_antwort_und_nie_zur_exception():
    antwort = kiclient.frage_modell("x", http=_Kracht())
    assert antwort.ok is False
    assert antwort.status == 0
    assert antwort.fehler == "OSError"


def test_http_fehler_traegt_status_und_die_meldung_der_gegenseite():
    """`pruefe` zeigt dem Nutzer, WARUM der Schlüssel abgelehnt wurde — die
    Meldung wird gelesen (und laut Modulkopf nie geloggt)."""
    http = _Http(_Antwort(400, {"error": {"message": "model: not found"}}))
    antwort = kiclient.frage_modell("x", http=http)
    assert antwort.ok is False
    assert antwort.status == 400
    assert antwort.fehler == "HTTP 400"
    assert antwort.grund == "model: not found"


def test_antwort_ohne_lesbares_json_ist_kein_erfolg():
    antwort = kiclient.frage_modell("x", http=_Http(_Antwort(200, kaputt=True)))
    assert antwort.ok is False
    assert antwort.status == 200
    assert antwort.fehler == "Antwort unlesbar"


def test_ohne_schluessel_wird_gar_nicht_erst_gefragt(monkeypatch):
    """Opt-in: ohne Schlüssel verlässt kein Beleginhalt das Haus."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    http = _Http()
    antwort = kiclient.frage_modell("Beleg", http=http)
    assert antwort.ok is False and antwort.fehler == "kein Key"
    assert http.aufrufe == []


def test_ohne_httpx_bleibt_es_stumm(monkeypatch):
    monkeypatch.setattr(kiclient, "httpx", None)
    antwort = kiclient.frage_modell("x")
    assert antwort.ok is False and antwort.fehler == "httpx fehlt"


# --------------------------------------------------------------------------
# 3) Die Wiederholung — Vorgabe ist der eine Versuch
# --------------------------------------------------------------------------

def test_vorgabe_ist_genau_ein_versuch():
    """Keine der sieben Fassungen wiederholte. Die strengste Variante bleibt
    die Vorgabe — sonst würde ein Timeout still das Doppelte kosten."""
    kaputt = _Kracht()
    kiclient.frage_modell("x", http=kaputt)
    assert kaputt.aufrufe == 1


def test_wiederholt_wird_nur_was_sich_lohnt():
    """429 und 5xx sind eine Wiederholung wert, ein abgelehnter Schlüssel
    nicht — der wird beim zweiten Mal genauso abgelehnt."""
    ausgebremst = _Http(_Antwort(429, {}), _Antwort(429, {}),
                        _text_antwort("endlich"))
    antwort = kiclient.frage_modell("x", versuche=3, http=ausgebremst)
    assert antwort.ok and antwort.text == "endlich"
    assert len(ausgebremst.aufrufe) == 3

    abgelehnt = _Http(_Antwort(401, {}))
    antwort = kiclient.frage_modell("x", versuche=3, http=abgelehnt)
    assert antwort.status == 401 and len(abgelehnt.aufrufe) == 1


def test_erfolg_beendet_die_wiederholung_sofort():
    http = _Http(_text_antwort("da"), _Antwort(500, {}))
    antwort = kiclient.frage_modell("x", versuche=3, http=http)
    assert antwort.ok and len(http.aufrufe) == 1


# --------------------------------------------------------------------------
# 4) Die Fassaden hängen wirklich an diesem einen Weg
# --------------------------------------------------------------------------

def test_kiauslese_und_eauto_rufen_ueber_den_kiclient(monkeypatch):
    """Der Sinn des Zusammenzugs: beide Module gehen durch dieselbe Funktion.
    Wäre irgendwo noch ein eigener `httpx.post` übrig, käme hier nichts an."""
    from app import eauto, kiauslese

    gesehen: list[str] = []
    echt = kiclient.frage_modell

    def merken(*a, **k):
        gesehen.append(k.get("etikett", ""))
        return echt(*a, **k)

    monkeypatch.setattr(kiclient, "frage_modell", merken)
    monkeypatch.setattr(kiauslese, "httpx",
                        _Http(_text_antwort(json.dumps({"betrag": 5}))))
    monkeypatch.setattr(eauto, "httpx", _Http(_text_antwort("16.5")))

    kiauslese.lies_beleg("Text", schluessel="k")
    kiauslese.lies_wasser("Text", schluessel="k")
    kiauslese.lies_strom("Text", schluessel="k")
    kiauslese.lies_weg_abrechnung("Text", schluessel="k")
    kiauslese.orientierung(b"PNG", "k")
    kiauslese.lies_solaredge(b"PNG", "image/png", schluessel="k")
    kiauslese.pruefe("k")
    eauto.verbrauch_ermitteln("VW ID.3", schluessel="k")

    assert gesehen == ["KI-Auslese", "KI-Wasserauslese", "KI-Stromauslese",
                       "KI-WEG-Auslese", "KI-Orientierung", "KI-SolarEdge",
                       "KI-Prüfung", "KI-Verbrauch"]
