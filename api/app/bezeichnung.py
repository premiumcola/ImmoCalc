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


def adresse(strasse: str = "", plz: str = "", ort: str = "") -> str:
    """Einzeilige Adresse für Anschreiben."""
    unten = " ".join(x for x in (_sauber(plz), _sauber(ort)) if x)
    return ", ".join(x for x in (_sauber(strasse), unten) if x)
