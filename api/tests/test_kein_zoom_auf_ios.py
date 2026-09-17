"""N486 — kein Eingabefeld darf auf dem iPhone unter 16px liegen.

iOS-Safari zoomt beim Fokus in ein Feld mit computed `font-size < 16px` hinein
und zoomt danach **nicht zurück**. Die Seite bleibt vergrössert, die festen
Kopf- und Fussleisten verrutschen, man kann quer scrollen. Gemeldet mit
Screenshot: „bleibt nach dem Schliessen des Bearbeitungsmodus irgendwie
gezoomt dastehen, oben ist die Kante hart, man hat nicht mehr das ganze
Fenster in der Ansicht."

Das war schon zweimal behoben (CCCLI, dann punktuell in objekt.html) und kam
beide Male zurück — weil der Riegel in `immo.css` mit `input, select,
textarea` nur die Spezifität (0,0,1) hatte und von JEDER klassenbasierten
Regel überboten wurde. Die Ausnahme in objekt.html stand zusätzlich VOR den
Regeln, die sie überstimmen sollte.

Dieser Test prüft nicht die Optik, sondern die Kaskade: er rechnet je Regel
die Spezifität aus und stellt sicher, dass der Riegel jede Regel schlägt, die
ein Eingabefeld unter 16px setzt. Ein reiner „steht das CSS noch da"-Test
hätte beide Rückfälle durchgelassen.
"""
from __future__ import annotations

import os
import pathlib
import re
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_zoom.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

WURZEL = pathlib.Path(__file__).resolve().parents[2] / "public"

# Was iOS beim Fokus zoomen lässt — `button` nimmt keinen Text auf.
FELD = re.compile(r"\b(?:input|select|textarea)\b|\.inp\b")
GROESSE = re.compile(r"font(?:-size)?\s*:\s*[^;{}]*?(\d+(?:\.\d+)?)px")
# Der Riegel selbst.
RIEGEL = "input:not(#_), select:not(#_), textarea:not(#_)"


def _spezifitaet(selektor: str) -> tuple[int, int, int]:
    """(ids, klassen, elemente) — die üblichen drei Stellen.

    `:not(x)` zählt wie `x` (genau darauf beruht der Riegel), Pseudoelemente
    zählen als Element, Pseudoklassen als Klasse.
    """
    s = selektor
    ids = klassen = 0
    # `:not(...)` zählt wie sein Inhalt. ERST auswerten, DANN die Hülle weg —
    # sonst zählt das `#_` darin zweimal (einmal hier, einmal in der Rekursion).
    for inhalt in re.findall(r":not\(([^)]*)\)", s):
        i2, k2, _e2 = _spezifitaet(inhalt)
        ids += i2
        klassen += k2
    s = re.sub(r":not\([^)]*\)", " ", s)
    ids += len(re.findall(r"#[\w-]+", s))
    klassen += (len(re.findall(r"\.[\w-]+", s))
               + len(re.findall(r"\[[^\]]+\]", s))
               + len(re.findall(r"(?<!:):(?!:)[\w-]+", s)))
    elemente = (len(re.findall(r"(?:^|[\s>+~])([a-zA-Z][\w-]*)", s))
                + len(re.findall(r"::[\w-]+", s)))
    return ids, klassen, elemente


def _css_bloecke(pfad: pathlib.Path) -> list[tuple[str, int]]:
    text = pfad.read_text(encoding="utf-8")
    if pfad.suffix == ".css":
        return [(text, 0)]
    return [(t.group(1), text.count("\n", 0, t.start(1)))
            for t in re.finditer(r"<style[^>]*>(.*?)</style>", text, re.S)]


def _regeln(css: str):
    """(selektor, koerper, zeile) je Regel — @media-Hüllen übersprungen."""
    i = 0
    while True:
        auf = css.find("{", i)
        zu = css.find("}", i)
        if auf == -1 and zu == -1:
            return
        if zu != -1 and (auf == -1 or zu < auf):
            i = zu + 1
            continue
        kopf = re.sub(r"/\*.*?\*/", " ", css[i:auf], flags=re.S).strip()
        if kopf.startswith("@"):
            i = auf + 1
            continue
        ende = css.find("}", auf)
        if ende == -1:
            return
        yield " ".join(kopf.split()), css[auf + 1:ende], css.count("\n", 0, i) + 1
        i = ende + 1


def _felder_unter_16() -> list[tuple[str, int, str, float]]:
    aus = []
    for pfad in sorted(list(WURZEL.rglob("*.css")) + list(WURZEL.rglob("*.html"))):
        for css, versatz in _css_bloecke(pfad):
            for selektor, koerper, zeile in _regeln(css):
                if not FELD.search(selektor) or selektor == RIEGEL:
                    continue
                t = GROESSE.search(koerper)
                if not t or float(t.group(1)) >= 16:
                    continue
                for teil in selektor.split(","):
                    teil = teil.strip()
                    if FELD.search(teil):
                        aus.append((str(pfad.relative_to(WURZEL.parent)),
                                    zeile + versatz, teil, float(t.group(1))))
    return aus


# ---- N486 — der Riegel ------------------------------------------------

def test_der_riegel_steht_noch_da():
    css = (WURZEL / "assets/immo.css").read_text(encoding="utf-8")
    assert "@media (pointer:coarse)" in css
    assert RIEGEL in css, (
        "Der 16px-Riegel für Touch-Geräte fehlt oder ist umformuliert. Er MUSS "
        "die Spezifität einer ID mitbringen (`:not(#_)`), sonst überbietet ihn "
        "jede Klassenregel — siehe Kopf dieser Datei.")


def test_der_riegel_schlaegt_jede_regel_unter_16px():
    """Der eigentliche Wächter: nicht ob der Riegel da steht, sondern ob er
    gewinnt. Beide früheren Rückfälle hätten hier angeschlagen."""
    riegel = _spezifitaet("input:not(#_)")
    schwaecher = [(datei, zeile, sel, px)
                  for datei, zeile, sel, px in _felder_unter_16()
                  if _spezifitaet(sel) > riegel]
    assert not schwaecher, (
        "Diese Regeln setzen ein Eingabefeld unter 16px UND schlagen den "
        "Touch-Riegel — auf dem iPhone zoomt die Seite dort hinein und kommt "
        "nicht zurück:\n"
        + "\n".join(f"  {d}:{z}  {p:g}px  {s}" for d, z, s, p in schwaecher))


def test_die_spezifitaets_rechnung_stimmt():
    """Wenn dieser Test schläft, schläft der Wächter darüber mit."""
    assert _spezifitaet("input") == (0, 0, 1)
    assert _spezifitaet("input:not(#_)") == (1, 0, 1)
    assert _spezifitaet(".bwzeile input") == (0, 1, 1)
    assert _spezifitaet(".ho-neu input[type=text]") == (0, 2, 1)
    assert _spezifitaet("#dlg input") == (1, 0, 1)
    # Der Kern der Sache: eine Klassenregel schlägt den nackten Element-
    # Selektor, aber nicht den Riegel.
    assert _spezifitaet(".zu-rolle select") > _spezifitaet("select")
    assert _spezifitaet(".zu-rolle select") < _spezifitaet("select:not(#_)")


def test_es_gibt_ueberhaupt_felder_zu_pruefen():
    """Gegenprobe: findet der Scanner noch Regeln? Ein leerer Fund wäre sonst
    ein grüner Test, der nichts mehr ansieht."""
    assert len(_felder_unter_16()) > 5
