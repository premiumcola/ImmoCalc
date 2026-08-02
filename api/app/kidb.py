"""N84 — die interne Wissens-Datenbank der ausgelesenen Belegdaten.

Die KI-Auslese lag bisher verstreut am Dokument (`ki_einordnung`, `ki_felder`,
`ki_immobilie`, `ki_einheit`) und musste bei jedem Ansehen neu
zusammengesucht werden. Dieses Modul baut daraus je Beleg **einen** Datensatz
(`models.Belegdaten`) — mit dem Cloud-Pfad als Link auf die Datei statt einer
lokalen Kopie — und macht ihn über Jahre hinweg durchsuchbar.

Drei reine Funktionen, keine Datenbank, kein Netz:

* `aus_dokument(d)`      — Datensatz aus einem `Dokument` bauen
* `zusammenfuehren(a, b) — additiv mischen: leer überschreibt nie gefüllt
* `suche(eintraege, q)`  — Volltextsuche, gross-/kleinschreib- und umlauttolerant

**Kein KI-Aufruf.** Hier wird ausschliesslich verwendet, was bereits in der
Datenbank steht — die Anthropic-API wird nie angefragt und keine Datei
geladen. Das ist ausdrücklicher Nutzerwunsch (Tokens).
"""
from __future__ import annotations

import logging
import unicodedata
from datetime import date
from typing import Any, Iterable

log = logging.getLogger("immocalc")

# Die Felder eines Datensatzes — dieselbe Reihenfolge wie in `Belegdaten`.
# Ein Datensatz ist ein schlichtes dict: so bleibt das Modul testbar, ohne
# eine Session zu brauchen.
FELDER: tuple[str, ...] = (
    "dokument_id", "objekt_id", "jahr", "kategorie", "kostenart", "betrag",
    "belegdatum", "anbieter", "zusammenfassung", "felder", "pfad",
    "dateiname", "quelle", "erfasst_am",
)

# Felder, über die die Volltextsuche läuft (die Werte von `felder` kommen
# zusätzlich dazu).
SUCHFELDER: tuple[str, ...] = (
    "zusammenfassung", "anbieter", "kostenart", "dateiname", "kategorie",
)

# Woher der Anbieter im KI-Raster steht: Versicherungen liefern `anbieter`,
# alles andere `absender` (siehe `kiauslese`); `lieferant` kommt aus der
# Hand-Pflege.
ANBIETER_SCHLUESSEL: tuple[str, ...] = ("anbieter", "absender", "lieferant")

_UMLAUTE = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
            "Ä": "ae", "Ö": "oe", "Ü": "ue"}


# --------------------------------------------------------------------------
# Kleinkram: Werte lesen, falten, auf „leer" prüfen
# --------------------------------------------------------------------------

def falte(wert: Any) -> str:
    """Vergleichsform eines Textes: klein, ohne Umlaute, ohne Akzente.

    „Zählerablesung" und „Zaehlerablesung" sollen dieselbe Trefferliste
    ergeben — der Nutzer tippt mal so, mal so, und die KI schreibt, was auf
    dem Beleg steht."""
    text = _text(wert)
    for zeichen, ersatz in _UMLAUTE.items():
        text = text.replace(zeichen, ersatz)
    zerlegt = unicodedata.normalize("NFKD", text)
    ohne_akzente = "".join(z for z in zerlegt if not unicodedata.combining(z))
    return ohne_akzente.casefold().strip()


def _text(wert: Any) -> str:
    """Ein Wert als Text — None wird leer, Zahlen werden lesbar."""
    if wert is None:
        return ""
    if isinstance(wert, str):
        return wert
    if isinstance(wert, date):
        return wert.isoformat()
    return str(wert)


def _feld(eintrag: Any, name: str) -> Any:
    """Ein Feld aus einem Datensatz — egal ob dict oder `Belegdaten`."""
    if isinstance(eintrag, dict):
        return eintrag.get(name)
    return getattr(eintrag, name, None)


def ist_leer(wert: Any) -> bool:
    """Ist dieser Wert „nichts"? None, leerer Text, leeres dict/list.

    Bewusst **nicht** die Null: ein Betrag von 0,00 € ist eine Aussage und
    darf einen vorhandenen Wert ersetzen dürfen — nur „noch nichts erfasst"
    darf es nicht."""
    if wert is None:
        return True
    if isinstance(wert, str):
        return not wert.strip()
    if isinstance(wert, (dict, list, tuple, set)):
        return not wert
    return False


def anbieter_aus(felder: dict | None) -> str:
    """Der Aussteller aus dem KI-Raster — `anbieter`, sonst `absender`."""
    for schluessel in ANBIETER_SCHLUESSEL:
        roh = (felder or {}).get(schluessel)
        if isinstance(roh, str) and roh.strip():
            return roh.strip()
    return ""


# --------------------------------------------------------------------------
# Aus einem Dokument einen Datensatz bauen
# --------------------------------------------------------------------------

def hat_ki(d: Any) -> bool:
    """Liegt zu diesem Beleg überhaupt eine KI-Auslese vor?

    Belege ohne Auslese werden nicht übersprungen, sondern gemeldet — der
    Nutzer soll sehen, wo noch nichts steht, statt es zu erraten."""
    return bool(_text(_feld(d, "ki_einordnung")).strip()
                or _feld(d, "ki_felder")
                or _text(_feld(d, "ki_immobilie")).strip()
                or _text(_feld(d, "ki_einheit")).strip())


def aus_dokument(d: Any, *, heute: date | None = None) -> dict:
    """Den Belegdaten-Satz aus einem `Dokument` bauen.

    Nimmt ausschliesslich, was am Beleg schon gespeichert ist: die
    KI-Auslese, den Betrag, das Jahr, den Pfad. Es wird nichts nachgeladen
    und nichts nachgefragt.

    `felder` bekommt zusätzlich die erkannte Liegenschaft und Einheit
    (`immobilie`/`einheit`) — additiv per `setdefault`, damit ein gleichnamiger
    Wert aus dem KI-Raster Vorrang behält. Sie stehen sonst nirgends im
    Datensatz und sind gerade die Angaben, nach denen man später sucht."""
    felder = dict(_feld(d, "ki_felder") or {})
    for name, wert in (("immobilie", _feld(d, "ki_immobilie")),
                       ("einheit", _feld(d, "ki_einheit"))):
        if _text(wert).strip():
            felder.setdefault(name, _text(wert).strip())

    return {
        "dokument_id": _feld(d, "id"),
        "objekt_id": _feld(d, "objekt_id"),
        "jahr": _feld(d, "jahr"),
        "kategorie": _text(_feld(d, "kategorie")),
        "kostenart": _text(_feld(d, "kostenart")),
        "betrag": _feld(d, "betrag"),
        "belegdatum": _feld(d, "belegdatum"),
        "anbieter": anbieter_aus(felder),
        "zusammenfassung": _text(_feld(d, "ki_einordnung")).strip(),
        "felder": felder,
        "pfad": _text(_feld(d, "pfad")),
        "dateiname": _text(_feld(d, "dateiname")),
        "quelle": "ki" if hat_ki(d) else "regel",
        "erfasst_am": heute or date.today(),
    }


# --------------------------------------------------------------------------
# Additiv zusammenführen
# --------------------------------------------------------------------------

def zusammenfuehren(vorhanden: dict | None, neu: dict | None) -> dict:
    """Zwei Datensätze mischen — additiv, nach dem setdefault-Prinzip.

    Regel: ein **leerer** Wert überschreibt nie einen gefüllten. Was der neue
    Lauf weiss, kommt dazu; was er nicht weiss, lässt er stehen. So verliert
    eine Hand-Korrektur nichts, nur weil die KI beim nächsten Mal ein Feld
    nicht erkannt hat.

    `felder` wird Schlüssel für Schlüssel gemischt, nicht ersetzt — sonst
    fiele bei jedem Lauf heraus, was ein früherer erkannt hatte."""
    ergebnis = dict(vorhanden or {})
    for name, wert in (neu or {}).items():
        if name == "felder":
            gemischt = dict(ergebnis.get("felder") or {})
            for schluessel, unterwert in (wert or {}).items():
                if not ist_leer(unterwert):
                    gemischt[schluessel] = unterwert
            ergebnis["felder"] = gemischt
            continue
        if ist_leer(wert):
            ergebnis.setdefault(name, wert)
            continue
        ergebnis[name] = wert
    return ergebnis


# --------------------------------------------------------------------------
# Volltextsuche
# --------------------------------------------------------------------------

def _werte(wert: Any) -> Iterable[str]:
    """Alle Texte in einem verschachtelten Wert (dict/list/Skalar)."""
    if isinstance(wert, dict):
        for schluessel, unterwert in wert.items():
            yield _text(schluessel)
            yield from _werte(unterwert)
    elif isinstance(wert, (list, tuple, set)):
        for unterwert in wert:
            yield from _werte(unterwert)
    else:
        yield _text(wert)


def durchsuchbar(eintrag: Any) -> str:
    """Der Heuhaufen eines Eintrags: Zusammenfassung, Anbieter, Kostenart,
    Dateiname, Kategorie und sämtliche Werte aus `felder` — gefaltet."""
    teile = [_text(_feld(eintrag, name)) for name in SUCHFELDER]
    teile.extend(_werte(_feld(eintrag, "felder") or {}))
    return falte(" ".join(t for t in teile if t))


def suche(eintraege: Iterable[Any], text: str) -> list:
    """Einträge, die alle Suchbegriffe enthalten.

    Mehrere Wörter werden UND-verknüpft — „wasser 2024" findet den
    Wasserbeleg von 2024, nicht alles mit „wasser" oder „2024". Ohne
    Suchtext kommt alles zurück; die Reihenfolge bleibt, wie sie kam."""
    begriffe = [falte(w) for w in (text or "").split() if falte(w)]
    liste = list(eintraege)
    if not begriffe:
        return liste
    treffer = []
    for eintrag in liste:
        heuhaufen = durchsuchbar(eintrag)
        if all(b in heuhaufen for b in begriffe):
            treffer.append(eintrag)
    return treffer
