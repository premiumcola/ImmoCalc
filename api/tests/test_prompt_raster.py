"""N280-D — Prompt-Raster und Feldzuordnung gegeneinander halten.

Zwischen KI und Eingabemaske liegen zwei Listen, die zusammenpassen müssen:

* `kiauslese.SYSTEM_PROMPT` sagt der KI, welche Felder sie je Belegart lesen
  soll (die „Raster"),
* `feldzuordnung.ZUORDNUNG` übersetzt diese Namen auf die Felder der Masken.

Laufen sie auseinander, passiert **nichts Sichtbares**: das Formularfeld bleibt
leer, der Nutzer tippt weiter ab, und niemand erfährt, dass die Zuordnung auf
einen Namen zeigt, den der Prompt gar nicht abfragt. Genau diesen stillen
Ausfall macht diese Datei rot.

Der Wächter liest die Raster **aus dem Prompt-String selbst**. Eine zweite,
handgepflegte Feldliste wäre sinnlos: sie liefe irgendwann genauso auseinander
wie die beiden, die sie bewachen soll. Von Hand steht hier nur, welches Raster
welche Maske füttert (`RASTER_JE_BEREICH`) — eine Zuordnung von Namen, keine
Kopie von Inhalten; dass es die genannten Raster wirklich gibt, wird geprüft.

`test_feldzuordnung.py` bewacht die andere Seite: dass die ZIELfelder der
Zuordnung im Modell existieren.
"""
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "pr.db"))

from app import feldzuordnung, kiauslese                        # noqa: E402

# --------------------------------------------------------------------------
# Den Prompt auslesen
# --------------------------------------------------------------------------
# Erklärungen in Klammern („(nur bei befristetem Vertrag)") sind kein Feld.
_KLAMMER = re.compile(r"\([^()]*\)")
# Ein Feldname, wie ihn die KI im JSON zurückgibt: klein, ohne Leerzeichen.
_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
# Die Feldliste eines Rasters endet spätestens am ersten Gedankenstrich —
# dahinter steht Fließtext („erwerbsart — EXAKT einer dieser Werte: …").
_GEDANKENSTRICH = "—"
_MARKE = "Raster je Typ:\n"


def raster_aus_prompt(prompt: str = "") -> dict[str, tuple[str, ...]]:
    """Die typspezifischen Raster, so wie sie im Prompt stehen.

    Ergibt `{"MIETVERTRAG": ("mieter", "kaltmiete", …), …}`. Eine Zeile zählt
    als Raster, wenn vor dem Doppelpunkt eine Belegart in Großbuchstaben steht;
    als Feld zählt, was zwischen den Kommas allein für sich steht — Fließtext
    („keine felder", „ist_kosten=false") fällt heraus."""
    _, marke, rumpf = (prompt or kiauslese.SYSTEM_PROMPT).partition(_MARKE)
    assert marke, f"Der Prompt hat keine Zeile '{_MARKE.strip()}' mehr"
    raster: dict[str, tuple[str, ...]] = {}
    for zeile in rumpf.split("\n"):
        art, trenner, rest = zeile.partition(":")
        if not trenner:
            continue
        art = _KLAMMER.sub("", art).strip()
        if not art.isupper():
            continue
        rest = _KLAMMER.sub("", rest).split(_GEDANKENSTRICH)[0]
        raster[art] = tuple(stueck for stueck in
                            (teil.strip(" .") for teil in rest.split(","))
                            if _NAME.match(stueck))
    return raster


def antwortfelder_aus_prompt(prompt: str = "") -> tuple[str, ...]:
    """Die Felder der JSON-Vorlage ganz oben im Prompt (`betrag`, `datum`, …).

    Sie stehen in JEDER Antwort, unabhängig von der Belegart — eine Zuordnung
    darf sich also auf sie stützen."""
    text = prompt or kiauslese.SYSTEM_PROMPT
    anfang = text.index("{")
    # Das verschachtelte `"felder":{…}` schliesst ohne Zeilenumbruch; die
    # äussere Klammer ist die, hinter der die Zeile endet.
    ende = text.index("}\n", anfang)
    return tuple(treffer.group(1)
                 for treffer in re.finditer(r'"([a-z][a-z0-9_]*)"\s*:',
                                            text[anfang:ende]))


# Welches Raster füttert welche Eingabemaske. Von Hand, weil der Prompt selbst
# es nicht sagen kann — dafür klein, gut lesbar und geprüft (siehe
# `test_die_genannten_raster_gibt_es_wirklich`).
RASTER_JE_BEREICH: dict[str, tuple[str, ...]] = {
    "notarvertraege": ("NOTARVERTRAG/BEURKUNDUNG", "KAUFVERTRAG"),
    "versicherungen": ("VERSICHERUNG",),
    "kredite": ("KREDIT/BAUSPAREN",),
    "mieten": ("MIETVERTRAG",),
    "zahlungen": ("GRUNDSTEUER",),
    "erwerbskosten": ("ERWERBSNEBENKOSTEN",),
    "renovierungsposten": ("HANDWERKERRECHNUNG",),
    "nebenkosten": ("NEBENKOSTEN-RECHNUNG", "STROM-/ENERGIE-RECHNUNG"),
    "stammdaten": ("KAUFVERTRAG", "GRUNDSTEUER", "GRUNDBUCH/GRUNDSCHULD",
                   "WEG"),
    "grundschulden": ("GRUNDBUCH/GRUNDSCHULD",),
}


def _quellen_fuer(bereich: str) -> set[str]:
    """Alle Namen, die bei diesem Bereich belegt sein KÖNNEN: die Felder der
    zugehörigen Raster plus die immer vorhandenen Antwortfelder."""
    raster = raster_aus_prompt()
    namen = set(antwortfelder_aus_prompt())
    for art in RASTER_JE_BEREICH[bereich]:
        # Fehlt das Raster, meldet das `test_die_genannten_raster_gibt_es_wirklich`
        # mit klarem Namen — hier soll deswegen kein KeyError dazwischenfahren.
        namen.update(raster.get(art, ()))
    return namen


# --------------------------------------------------------------------------
# 1) Liest der Wächter den Prompt richtig?
# --------------------------------------------------------------------------

def test_der_parser_findet_die_raster():
    """Ein Wächter, der den Prompt falsch liest, bewacht nichts. Deshalb erst
    einmal an bekannten Zeilen nachgewiesen, dass er Felder von Fließtext
    unterscheidet."""
    raster = raster_aus_prompt()
    assert raster["KAUFVERTRAG"] == ("kaufpreis", "kaufdatum")
    assert raster["WEG"] == ("verwalter", "hausgeld_monatlich",
                             "ruecklage_zufuehrung")
    # Klammer-Erklärungen fliegen raus, das Feld davor bleibt.
    assert "mietende" in raster["MIETVERTRAG"]
    assert "s35a" in raster["NEBENKOSTEN-RECHNUNG"]
    # Alles hinter dem Gedankenstrich ist Fließtext, nicht Feld.
    assert raster["ERWERBSNEBENKOSTEN"] == ("erwerbsart",)
    # „keine felder, ist_kosten=false" ist keine Feldliste.
    assert raster["INFO-BELEG"] == ()
    # Und nirgends ein eingesammeltes deutsches Wort.
    assert all(_NAME.match(feld)
               for felder in raster.values() for feld in felder)


def test_der_parser_findet_die_antwortfelder():
    felder = antwortfelder_aus_prompt()
    for name in ("dokumenttyp", "kategorie", "absender", "datum", "betrag",
                 "kostenart", "gewerk", "abrechnungsjahr", "felder",
                 "zusammenfassung"):
        assert name in felder, f"{name} fehlt in der JSON-Vorlage"


def test_die_antwortfelder_kommen_auch_wirklich_zurueck():
    """Was die Vorlage verspricht, muss `lies_beleg` auch durchreichen — sonst
    zeigt eine Zuordnung auf ein Feld, das der Aufrufer nie zu sehen bekommt
    (genau der Fehler, den CD beim `absender` heilen musste)."""
    ergebnis = _gestellte_auslese()
    for name in antwortfelder_aus_prompt():
        assert name in ergebnis, f"lies_beleg reicht '{name}' nicht durch"


def _gestellte_auslese() -> dict:
    """Eine echte `lies_beleg`-Antwort auf eine gestellte Modellantwort — ohne
    Netz, mit allen Feldern der Vorlage belegt."""
    import json

    class _Antwort:
        status_code = 200

        @staticmethod
        def json():
            block = {name: "1" for name in antwortfelder_aus_prompt()}
            block["felder"] = {}
            return {"content": [{"type": "text", "text": json.dumps(block)}]}

    class _Httpx:
        @staticmethod
        def post(*_a, **_k):
            return _Antwort()

    echt = kiauslese.httpx
    kiauslese.httpx = _Httpx
    try:
        return kiauslese.lies_beleg("Text", schluessel="k") or {}
    finally:
        kiauslese.httpx = echt


# --------------------------------------------------------------------------
# 2) Der Wächter: keine Zuordnung ins Leere
# --------------------------------------------------------------------------

def test_jeder_bereich_nennt_seine_raster():
    """Ein neuer Bereich in der Zuordnung muss sagen, aus welchem Raster er
    sich speist — sonst entzieht er sich der Prüfung darunter."""
    assert set(feldzuordnung.ZUORDNUNG) == set(RASTER_JE_BEREICH)


def test_die_genannten_raster_gibt_es_wirklich():
    """Wird ein Raster im Prompt umbenannt, fällt es hier auf — und nicht erst
    daran, dass eine Maske leer bleibt."""
    raster = raster_aus_prompt()
    for bereich, arten in RASTER_JE_BEREICH.items():
        for art in arten:
            assert art in raster, f"{bereich}: Raster '{art}' gibt es nicht mehr"


def test_jedes_formularfeld_hat_eine_quelle_im_prompt():
    """DER Wächter.

    Für jedes Feld einer Maske muss mindestens einer der genannten Quellnamen
    im Prompt vorkommen — als Antwortfeld oder im Raster der jeweiligen
    Belegart. Sonst ist das Feld strukturell unbefüllbar und bleibt für immer
    leer.

    Geprüft wird „mindestens einer", nicht „jeder": die weiteren Namen sind
    absichtliche Toleranz (die KI schreibt mal `kaufpreis`, mal `betrag`).
    Welche davon der Prompt nicht kennt, sagt der Bericht weiter unten."""
    fehler: list[str] = []
    for bereich, zuordnung in feldzuordnung.ZUORDNUNG.items():
        erlaubt = _quellen_fuer(bereich)
        for feld, kandidaten in zuordnung.items():
            if not any(k in erlaubt for k in kandidaten):
                fehler.append(f"{bereich}.{feld} ← {kandidaten}")
    assert not fehler, ("Kein Quellfeld im Prompt — diese Formularfelder "
                        "bleiben immer leer: " + ", ".join(fehler))


def test_bericht_rasterfelder_ohne_zuordnung():
    """Kein Fehlschlag, sondern der Blick in die Gegenrichtung: was liest die
    KI, ohne dass es je in einer Maske ankommt? Jedes Feld hier kostet Tokens
    an jedem Beleg — es gehört entweder zugeordnet oder aus dem Prompt
    gestrichen. Erwartbar offen bleiben die Felder der Sonderzweige — die
    Strom-Beträge holt `lies_strom` mit einem eigenen Prompt und eigenen
    Regeln ab."""
    genannt = {name for zuordnung in feldzuordnung.ZUORDNUNG.values()
               for kandidaten in zuordnung.values() for name in kandidaten}
    offen = {art: tuple(f for f in felder if f not in genannt)
             for art, felder in raster_aus_prompt().items()}
    bericht = "\n".join(f"  {art}: {', '.join(felder)}"
                        for art, felder in sorted(offen.items()) if felder)
    print("\nRasterfelder ohne Zuordnung (Bericht, kein Fehler):\n"
          + (bericht or "  keine"))
    # Ein Raster, das die KI liest, muss WENIGSTENS ein Feld liefern, das
    # irgendwo ankommt — sonst wäre es komplett umsonst gefragt.
    leerlauf = [art for art, felder in raster_aus_prompt().items()
                if felder and not any(f in genannt for f in felder)]
    assert not leerlauf, f"Raster ohne jede Zuordnung: {leerlauf}"
