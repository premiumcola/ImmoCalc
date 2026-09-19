"""N503 — die sechsstellige Code-Eingabe: ein Baustein, drei Aufrufer.

Nutzer: „gestalte die sechs Zeichen so, dass die gruppiert sind, also drei und
drei … wenn ich alle sechs eingegeben habe, probier selber, ob es korrekt ist,
und bring nur eine Meldung, wenn es nicht korrekt ist … am Handy bitte die
Zahlentastatur automatisch öffnen."

Zwei Sorten Prüfung, weil eine allein nicht reicht:

* **Hier** steht, was sich am Quelltext entscheiden lässt — dass alle drei
  Stellen wirklich den geteilten Baustein benutzen und keine mehr ihr eigenes
  Codefeld baut. Genau das schleicht sich sonst beim nächsten Umbau wieder ein.
* **Das Verhalten** (Vorrücken, Rücktaste, Einfügen, die Sperre gegen einen
  doppelten Versuch) prüft `tests/codefelder.test.mjs` mit einem kleinen
  DOM-Ersatz in Node — der Lauf wird hier mit angestossen, damit er nicht
  neben dem Testlauf herläuft und vergessen wird. Dieser Test hat beim
  Schreiben einen echten Fehler gefunden: nach einer Korrektur wurde
  derselbe Code stumm verschluckt.
"""
from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

import pytest

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_codefelder.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

WURZEL = pathlib.Path(__file__).resolve().parents[2]
PUBLIC = WURZEL / "public"
IMMO_JS = (PUBLIC / "assets" / "immo.js").read_text(encoding="utf-8")
IMMO_CSS = (PUBLIC / "assets" / "immo.css").read_text(encoding="utf-8")

# Die drei Stellen, an denen ein sechsstelliger Code eingegeben wird.
AUFRUFER = ("anmeldung.html", "settings.html", "zweifaktor.html")


def _seite(name: str) -> str:
    return (PUBLIC / name).read_text(encoding="utf-8")


# ---- N503 — ein Baustein, keine Kopien --------------------------------

def test_der_baustein_steht_genau_einmal():
    assert IMMO_JS.count("export function codeFelder") == 1
    assert IMMO_JS.count("export function codeBinden") == 1


@pytest.mark.parametrize("seite", AUFRUFER)
def test_jede_seite_benutzt_den_baustein(seite):
    text = _seite(seite)
    assert "codeFelder(" in text, f"{seite} baut das Feld nicht über den Baustein"
    assert "codeBinden(" in text, f"{seite} verdrahtet den Baustein nicht"


@pytest.mark.parametrize("seite", AUFRUFER)
def test_keine_seite_baut_sich_ein_eigenes_codefeld(seite):
    """Der Rückfall, den es zu verhindern gilt: irgendwo steht wieder ein
    einzelnes `maxlength="6"`-Feld und die Gruppierung gilt nur noch woanders."""
    text = _seite(seite)
    eigene = re.findall(r'<input[^>]*maxlength="6"[^>]*>', text)
    assert not eigene, f"{seite}: eigenes Codefeld statt Baustein → {eigene}"


@pytest.mark.parametrize("seite", AUFRUFER)
def test_das_alte_einzelfeld_ist_ueberall_weg(seite):
    """`.code-feld` war die alte, seitenlokale Fassung. Bleibt sie irgendwo
    stehen, hat jemand nur die Hälfte umgestellt."""
    assert "code-feld" not in _seite(seite)


# ---- N503 — was der Baustein erzeugt ----------------------------------

def test_sechs_felder_und_die_luecke_in_der_mitte():
    """Nutzer: „drei einzelne Eingabefelder, ein bisschen Abstand, wieder
    drei." Die Lücke ist ein eigenes Element, kein Abstand am dritten Feld —
    sonst verschöbe sie sich, sobald jemand die Anzahl ändert."""
    assert 'i === Math.floor(anzahl / 2)' in IMMO_JS
    assert "codeluecke" in IMMO_JS
    assert "const ZIFFERN_IM_CODE = 6" in IMMO_JS


def test_die_zahlentastatur_geht_am_telefon_auf():
    """`inputmode` allein reicht älteren iOS-Fassungen nicht — `pattern`
    gehört dazu."""
    baustein = IMMO_JS[IMMO_JS.index("export function codeFelder"):
                       IMMO_JS.index("export function codeBinden")]
    assert 'inputmode="numeric"' in baustein
    assert 'pattern="[0-9]*"' in baustein
    assert 'maxlength="1"' in baustein


def test_nur_das_erste_feld_bietet_den_einmalcode_an():
    """Sonst schlägt iOS denselben Code an sechs Stellen vor."""
    assert "i === 0 ? 'one-time-code' : 'off'" in IMMO_JS


@pytest.mark.parametrize("seite", AUFRUFER)
def test_der_knopf_sagt_was_laeuft(seite):
    """Nutzer: „wandel den OK-Button dann automatisch zu 'Melde an' um."
    Geprüft wird, dass es überhaupt einen Wechsel gibt — den Wortlaut
    entscheidet die jeweilige Stelle (anmelden vs. einschalten)."""
    text = _seite(seite)
    assert re.search(r"(knopf|codeKnopf|tfaKnopf)\.textContent\s*=", text), \
        f"{seite}: der Knopf ändert seine Beschriftung nicht"


# ---- N503 — die Zoom-Sperre darf die Ziffern nicht schrumpfen ---------

def test_die_ziffern_schlagen_die_ios_zoomsperre():
    """`input:not(#_){font-size:16px}` (N486) hat Spezifität (1,0,1). Eine
    reine Klassenregel `.codeziffer` (0,1,0) verlöre — die Ziffern wären am
    Telefon plötzlich klein. Deshalb steht dort dasselbe `:not(#_)`."""
    assert ".codeziffer:not(#_){" in IMMO_CSS
    # Und die Schriftgrösse ist gross genug, damit iOS gar nicht erst zoomt.
    regel = IMMO_CSS.split(".codeziffer:not(#_){", 1)[1].split("}", 1)[0]
    groesse = re.search(r"font:[^;]*?(\d+)px", regel)
    assert groesse and int(groesse.group(1)) >= 16, regel


# ---- N503 — das Verhalten, in Node -------------------------------------

def test_die_eingabelogik_verhaelt_sich_richtig():
    """Startet `tests/codefelder.test.mjs`. Ohne node wird übersprungen —
    aber mit einer Meldung, die sagt, was dann NICHT geprüft wurde."""
    if not shutil.which("node"):
        pytest.skip("node nicht vorhanden — Eingabelogik ungeprüft")
    lauf = subprocess.run(["node", str(WURZEL / "tests" / "codefelder.test.mjs")],
                          capture_output=True, text=True, cwd=WURZEL)
    assert lauf.returncode == 0, lauf.stdout + lauf.stderr
    assert "Prüfungen bestanden" in lauf.stdout


# ---- N503 — der Wiederherstellungscode bleibt erreichbar --------------

def test_der_wiederherstellungscode_hat_weiter_einen_weg():
    """Der wichtigste Punkt an dieser Umstellung, und der, den der Wunsch
    nicht nennt: in das Anmeldefeld darf auch ein Wiederherstellungscode
    (`xxxxx-xxxxx`). In sechs Ziffernkästchen passt der nicht. Ohne einen
    zweiten Weg wäre er unbenutzbar — und er existiert genau für den Fall,
    dass die Authenticator-App nicht erreichbar ist."""
    text = _seite("anmeldung.html")
    assert "notweg" in text and "code-not" in text
    assert "Wiederherstellungscode" in text


def test_bei_der_einrichtung_gibt_es_keinen_notweg():
    """Dort entstehen die Wiederherstellungscodes erst — ein Angebot, sie
    schon zu benutzen, wäre eine Sackgasse."""
    for seite in ("settings.html", "zweifaktor.html"):
        assert "code-not" not in _seite(seite), seite
