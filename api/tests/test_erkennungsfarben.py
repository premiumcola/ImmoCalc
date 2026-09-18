"""N491 — die Farben der Belegerkennung müssen zusammenpassen.

Nutzer: „färb die Elemente, die erkannt wurden, als Kategorie bunt — dann
hast du das Datum, dann den Betrag … und auch oben im Erklärtext die
Schlagworte. Dann kriegt man ein Gefühl dafür, was die KI erkannt hat."

Die Zuordnung steht an zwei Orten: welche Art welchen TON bekommt, liegt in
`belegbestaetigung.js` (`FUNDTON`); wie ein Ton AUSSIEHT, liegt in
`immo.css` (`.scanbest-dlg .t<n>`). Läuft beides auseinander, fällt eine
Angabe stillschweigend auf den neutralen Ton zurück oder — schlimmer — trägt
gar keine Farbe, ohne dass irgendwo etwas bricht.

Genau solche stillen Entkopplungen hat dieses Projekt schon mehrfach
getroffen (zuletzt N486: ein CSS-Riegel, der dastand und nichts hielt).
Deshalb hier ein Wächter statt eines Kommentars.
"""
from __future__ import annotations

import os
import pathlib
import re
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test_farben.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

WURZEL = pathlib.Path(__file__).resolve().parents[2] / "public" / "assets"
JS = (WURZEL / "belegbestaetigung.js").read_text(encoding="utf-8")
CSS = (WURZEL / "immo.css").read_text(encoding="utf-8")
IMMO = (WURZEL / "immo.js").read_text(encoding="utf-8")


def _fundton() -> dict[str, int]:
    block = JS.split("const FUNDTON = {", 1)[1].split("};", 1)[0]
    return {a: int(t) for a, t in re.findall(r"(\w+)\s*:\s*(\d+)", block)}


def _arten_aus_kiangaben() -> set[str]:
    """Welche Arten `kiAngaben` überhaupt vergibt — aus der Quelle gelesen,
    nicht abgeschrieben."""
    block = IMMO.split("export function kiAngaben(w) {", 1)[1].split("\n}", 1)[0]
    return set(re.findall(r"dazu\('(\w+)'", block))


def test_jede_vergebene_art_hat_einen_ton():
    """Sonst fiele die Angabe stumm auf den neutralen Ton zurück."""
    fehlt = _arten_aus_kiangaben() - set(_fundton())
    assert not fehlt, (
        f"`kiAngaben` vergibt Arten ohne Eintrag in FUNDTON: {sorted(fehlt)}")


def test_kein_ton_ohne_verwendung():
    """Die Gegenrichtung — eine Art in FUNDTON, die es gar nicht mehr gibt,
    ist toter Code und verschleiert, welche Farben wirklich vorkommen."""
    zuviel = set(_fundton()) - _arten_aus_kiangaben()
    assert not zuviel, (
        f"FUNDTON nennt Arten, die `kiAngaben` nie vergibt: {sorted(zuviel)}")


def test_jeder_benutzte_ton_hat_eine_farbe_im_css():
    ohne = [t for t in sorted(set(_fundton().values()))
            if f".scanbest-dlg .t{t}{{" not in CSS]
    assert not ohne, f"Töne ohne Farbe in immo.css: {ohne}"


def test_jede_farbe_setzt_beide_variablen():
    """Die Markierung im Text braucht `--fund-bg`, der Punkt in der Liste
    `--fund`. Fehlt eine, erbt sie stillschweigend vom vorigen Ton."""
    for t in sorted(set(_fundton().values())):
        regel = CSS.split(f".scanbest-dlg .t{t}{{", 1)[1].split("}", 1)[0]
        assert "--fund:" in regel, f"Ton {t} ohne --fund"
        assert "--fund-bg:" in regel, f"Ton {t} ohne --fund-bg"


def test_die_toene_sind_voneinander_unterscheidbar():
    """Zwei Angaben in derselben Farbe wären schlimmer als gar keine Farbe —
    der Nutzer ordnete sie derselben Quelle zu. Kategorie und Kostenart teilen
    sich bewusst einen Ton (beides sagt „was für eine Kosten­art"), alle
    übrigen müssen eigen sein."""
    farben = {}
    for t in sorted(set(_fundton().values())):
        regel = CSS.split(f".scanbest-dlg .t{t}{{", 1)[1].split("}", 1)[0]
        farben[t] = re.search(r"--fund:\s*(#[0-9A-Fa-f]{6})", regel).group(1)
    assert len(set(farben.values())) == len(farben), (
        f"zwei Töne tragen dieselbe Farbe: {farben}")


def test_die_maske_haelt_ihre_verankerungen():
    """`tests/scan-check.mjs` und fünf Aufrufer hängen an diesen Namen. Der
    Umbau auf die ganzseitige Maske (N491) darf sie nicht mitnehmen."""
    for haken in ('id="sbName"', "data-ok", "data-ab", "data-blaetter",
                  "'beleg-dlg', 'scanbest-dlg'", "sb-rumpf"):
        assert haken in JS, f"Verankerung fehlt: {haken}"


def test_der_erklaertext_wird_stueckweise_maskiert():
    """Die Markierung baut HTML in einen Text, der vom Sprachmodell kommt.
    Maskiert werden muss deshalb JEDER Abschnitt einzeln — ein `esc` über das
    fertige HTML würde die Markierung sichtbar machen, gar keins wäre eine
    offene Tür."""
    block = JS.split("function satzMitFunden(", 1)[1].split("\n}", 1)[0]
    assert block.count("esc(satz.slice(") >= 3, (
        "satzMitFunden maskiert die Textabschnitte nicht mehr einzeln")
    assert "esc(t.label)" in block, "der Titel der Markierung ist unmaskiert"
