"""Sprechende Bezeichnungen für Objekte und ihre Ordner.

Von grob nach fein: Ort, dann Straße, dann die Einheit. "Wohnung 1. OG" allein
sagt nichts und kollidiert, sobald eine zweite Immobilie ebenso heißt.
"""
from __future__ import annotations

import re


def _sauber(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _ohne_doppelung(stuecke: list[str]) -> list[str]:
    """Überschneidende Angaben zusammenführen — der genauere Teil gewinnt.

    "Eschenau" + "Eschenau - Laufer Str. 5" ergibt den längeren der beiden,
    nicht beides und nicht den kürzeren."""
    teile: list[str] = []
    for stueck in stuecke:
        if not stueck:
            continue
        erledigt = False
        for i, vorhanden in enumerate(teile):
            if vorhanden.lower() in stueck.lower():
                teile[i] = stueck          # neuer Teil ist der genauere
                # Der genauere Teil kann weitere frühere Stücke mitverschlucken.
                # Ohne diese Zeile stand "Prüfweg 5" hinterher noch ein zweites
                # Mal hinter dem Namen, der ihn bereits enthält.
                teile = [t for j, t in enumerate(teile)
                         if j == i or t.lower() not in stueck.lower()]
                erledigt = True
                break
            if stueck.lower() in vorhanden.lower():
                erledigt = True            # schon enthalten
                break
        if not erledigt:
            teile.append(stueck)
    return teile


def anzeigename(name: str, ort: str = "", strasse: str = "", plz: str = "") -> str:
    """Baut die Bezeichnung von grob nach fein und vermeidet Wiederholungen."""
    teile = _ohne_doppelung([_sauber(ort), _sauber(strasse), _sauber(name)])
    if not teile:
        return _sauber(name) or "Immobilie"
    return " · ".join(teile)


# Im Feld "ort" steht im Bestand vereinzelt die Nutzung statt einer Ortschaft
# ("Mixed-Use · 7 Einheiten"). Solche Stücke dürfen nie als Ort erscheinen.
_KEIN_ORT = re.compile(
    r"mixed[\s-]?use|mfh|efh|zfh|mehrfamilien|einfamilien|zweifamilien|"
    r"doppelhaus|reihenhaus|wohnanlage|gewerbe|stellplatz|garage|"
    r"\d\s*(einheit|wohnung|gewerbe|zimmer|partei|stellplatz)", re.I)

# Feinste Ebene: benennt eine Einheit im Haus, nie eine Straße.
_IST_EINHEIT = re.compile(
    r"^(whg|wohnung|einheit|eg|og|ug|dg|kg|souterrain|dachgeschoss|"
    r"stellplatz|garage|laden|b[üu]ro|praxis|gewerbe|halle|keller)\b", re.I)

# Mittlere Ebene: sieht aus wie eine Straße — Grundwort oder Hausnummer am Ende.
_IST_STRASSE = re.compile(
    r"(stra(ß|ss)e|str\.|weg|allee|platz|gasse|ring|winkel|damm|ufer|steig|"
    r"zeile|chaussee|pfad|hof|berg|feld|anger|markt)\b|\d+\s*[a-z]?$", re.I)

_TRENNER = re.compile(r"\s*[·•]\s*|\s+[-–—]\s+")


def hierarchie(name: str, ort: str = "", strasse: str = "",
               plz: str = "") -> dict[str, str]:
    """Zerlegt ein Objekt in die drei Ebenen Ort → Straße → Einheit.

    Die Felder sind historisch gewachsen: die Straße steht mal in `strasse`,
    mal im Namen, der Ort mal in `ort`, mal als "(Ort)" vor dem Namen — und
    manchmal steht in `ort` gar kein Ort. Diese Funktion sortiert das, damit
    die Kachel eine echte Hierarchie zeigen kann statt roher Feldinhalte.
    """
    ort_teile = [t for t in _TRENNER.split(_sauber(ort))
                 if t and not _KEIN_ORT.search(t)]
    ergebnis_ort = ort_teile[0] if ort_teile else ""

    rest = _sauber(name)
    klammer = re.match(r"^\((.+?)\)\s*(.*)$", rest)
    if klammer:                       # "(Teststadt) Prüfweg 5 · EG"
        if not ergebnis_ort and not _KEIN_ORT.search(klammer.group(1)):
            ergebnis_ort = _sauber(klammer.group(1))
        rest = _sauber(klammer.group(2))

    ergebnis_strasse = _sauber(strasse)
    einheiten: list[str] = []
    for stueck in (s for s in _TRENNER.split(rest) if s):
        klein = stueck.lower()
        if klein == ergebnis_ort.lower() or klein == ergebnis_strasse.lower():
            continue                  # schon auf einer gröberen Ebene genannt
        if not ergebnis_strasse and not _IST_EINHEIT.match(stueck) \
                and _IST_STRASSE.search(stueck):
            ergebnis_strasse = stueck
            continue
        einheiten.append(stueck)

    if not ergebnis_strasse and einheiten:
        # Ohne erkennbare Straße ist der Name selbst die mittlere Ebene —
        # eine leere Straßenzeile mit gefüllter Einheit wäre kopflastig.
        ergebnis_strasse = einheiten.pop(0)

    return {"ort": ergebnis_ort, "strasse": ergebnis_strasse,
            "einheit": " · ".join(einheiten), "plz": _sauber(plz)}


# Zeichen, die in Datei- und Ordnernamen Ärger machen. Windows verbietet sie,
# Nextcloud reicht sie an das Dateisystem durch.
_VERBOTEN = r'[<>:"/\\|?*\x00-\x1f]'
VERBOTENE_ZEICHEN = '< > : " / \\ | ? *'

# Vorlage für den Ordnernamen. Platzhalter werden ersetzt; leere Felder lassen
# ihre Umgebung mitverschwinden, damit keine "() " Reste stehenbleiben.
STANDARD_VORLAGE = "({ort}) {strasse} · {name}"
PLATZHALTER = ("ort", "strasse", "name", "plz", "typ", "nutzung")


def _entferne_leere_gruppen(text: str) -> str:
    """Klammern und Trenner um weggefallene Platzhalter aufräumen."""
    text = re.sub(r"\(\s*\)", "", text)          # leere Klammern
    text = re.sub(r"\[\s*\]", "", text)
    text = re.sub(r"\s*[·•–—~|/]{1,2}\s*(?=[·•–—~|/]|$)", "", text)   # Trenner am Ende
    text = re.sub(r"^\s*[·•–—~|/]{1,2}\s*", "", text)                 # Trenner am Anfang
    return re.sub(r"\s{2,}", " ", text).strip(" ·–—~|-")


def nach_vorlage(vorlage: str, **werte: str) -> str:
    """Setzt eine Namensvorlage um und macht daraus einen gültigen Ordnernamen."""
    text = vorlage or STANDARD_VORLAGE
    for schluessel in PLATZHALTER:
        wert = _sauber(werte.get(schluessel, ""))
        # sowohl {ort} als auch %ort werden verstanden
        text = text.replace("{" + schluessel + "}", wert)
        text = re.sub(r"%" + schluessel + r"\b", wert, text, flags=re.IGNORECASE)
    text = re.sub(_VERBOTEN, " ", text)          # Schrägstriche etc. entfernen
    return _entferne_leere_gruppen(text) or "Immobilie"


def vorlage_pruefen(vorlage: str) -> list[str]:
    """Meldet, was an einer Vorlage nicht funktioniert."""
    fehler = []
    if not (vorlage or "").strip():
        return ["Die Vorlage ist leer."]
    treffer = sorted(set(re.findall(_VERBOTEN, vorlage)))
    if treffer:
        fehler.append("Diese Zeichen sind in Ordnernamen nicht erlaubt und "
                      f"werden entfernt: {' '.join(treffer)}")
    bekannt = set(PLATZHALTER)
    genutzt = set(re.findall(r"\{(\w+)\}", vorlage)) | \
        {t.lower() for t in re.findall(r"%(\w+)", vorlage)}
    unbekannt = sorted(genutzt - bekannt)
    if unbekannt:
        fehler.append("Unbekannte Platzhalter: " + ", ".join(unbekannt))
    if not genutzt:
        fehler.append("Die Vorlage enthält keinen Platzhalter — "
                      "alle Ordner hießen gleich.")
    return fehler


def ordnername(name: str, ort: str = "", strasse: str = "") -> str:
    """Ordnername im Stil des Bestands: "Eschenau - Laufer Str. 5"."""
    teile = _ohne_doppelung([_sauber(ort), _sauber(strasse), _sauber(name)])
    if not teile:
        teile = [_sauber(name) or "Immobilie"]
    roh = " - ".join(teile)
    roh = re.sub(_VERBOTEN, "", roh)
    return re.sub(r"\s+", " ", roh).strip(" .")


# --------------------------------------------------------------------------
# Ordnerpfade: wo ein Objektordner hingehört und wann er doppelt dasteht
# --------------------------------------------------------------------------

def vergleichsname(name: str) -> str:
    """Vergleichsform eines Ordnernamens.

    Groß-/Kleinschreibung, Leerzeichen und Satzzeichen spielen keine Rolle:
    "Wohnung 1.OG" und "Wohnung 1. OG" meinen dieselbe Einheit."""
    return re.sub(r"\W+", "", (name or "").lower())


def gleicher_ordner(a: str, b: str) -> bool:
    """Zwei Ordnernamen, die dasselbe meinen."""
    links, rechts = vergleichsname(a), vergleichsname(b)
    return bool(links) and links == rechts


def pfadteile(pfad: str) -> list[str]:
    """Die Ebenen eines Pfades, ohne leere Stücke."""
    return [t for t in (pfad or "").split("/") if t and t != "."]


def doppelt_geschachtelt(pfad: str) -> bool:
    """Liegt der Ordner in einem Ordner desselben Namens? ("X/X")

    Genau das entstand, als der Objektordner ein zweites Mal unterhalb seiner
    selbst angelegt wurde — doppelt gemoppelt ohne Mehrwert."""
    teile = pfadteile(pfad)
    return len(teile) >= 2 and gleicher_ordner(teile[-1], teile[-2])


def ordnerpfad(home: str, ordner: str) -> str:
    """Pfad des Objektordners unter dem Home-Ordner, ohne führenden Trenner.

    Ist der Home-Ordner bereits dieser Ordner, wird er nicht ein zweites Mal
    darunter angelegt — sonst entstünde "(Eschenau) Laufer Str. 5 /
    (Eschenau) Laufer Str. 5"."""
    teile = pfadteile(home)
    name = _sauber(ordner)
    if name and not (teile and gleicher_ordner(teile[-1], name)):
        teile.append(name)
    return "/".join(teile)


def adresse(strasse: str = "", plz: str = "", ort: str = "") -> str:
    """Einzeilige Adresse für Anschreiben."""
    unten = " ".join(x for x in (_sauber(plz), _sauber(ort)) if x)
    return ", ".join(x for x in (_sauber(strasse), unten) if x)
