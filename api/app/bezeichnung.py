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
STANDARD_VORLAGE = "({ort}) {lage} · {name}"
# `lage` ist kein eigenes Feld, sondern das, was den Ort genauer benennt: bei
# einem Haus die Strasse, bei einem Grundstueck Gemarkung und Flurstueck. Ohne
# das hiess ein Feldgrundstueck nur „(Eckental) · Steigaecker" — die Strasse,
# die es nicht hat, liess eine Luecke.
PLATZHALTER = ("ort", "strasse", "name", "plz", "typ", "nutzung",
               "gemarkung", "flurstueck", "lage")


def lagebezeichnung(strasse: str = "", gemarkung: str = "",
                    flurstueck: str = "") -> str:
    """Was die Immobilie im Ort verortet — Strasse, ersatzweise das Flurstück.

    Ein Grundstueck hat keine Hausnummer; im Grundbuch steht es als
    „Gemarkung Eckenhaid, Flurstueck 619". Genau das nimmt hier die Stelle der
    Strasse ein, damit der Ordnername etwas aussagt.
    """
    if _sauber(strasse):
        return _sauber(strasse)
    teile = [t for t in (_sauber(gemarkung), _sauber(flurstueck)) if t]
    if not teile:
        return ""
    return "Flurstück " + " ".join(teile) if len(teile) == 1 and \
        _sauber(flurstueck) and not _sauber(gemarkung) else " ".join(teile)


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
    # `lage` ergibt sich aus den anderen Angaben, wenn es niemand mitgibt —
    # sonst verlöre jeder Aufrufer, der nur `strasse` kennt, die Adresse.
    if not werte.get("lage"):
        werte = {**werte, "lage": lagebezeichnung(werte.get("strasse", ""),
                                                  werte.get("gemarkung", ""),
                                                  werte.get("flurstueck", ""))}
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


# --------------------------------------------------------------------------
# CXCI — Unterordner im Sachordner: „In NK kann nicht einfach alles flach drin
# liegen, das sollte schon in Ordnern sein."
#
# Abgesehen ist das dem eigenen Bestand des Nutzers:
#
#   60_Nebenkosten/{2022, 2023, 2024, 2025, 2026}  und im Archiv 2000-2021
#                 darunter noch einmal {2014 … 2021}   -> das nackte Jahr
#   06_Nebenkosten/{NK-2018-1OG … NK-2024-1OG}         -> Jahr und Einheit
#   07_STEUER_…/{Steuer_2017, Steuer_2018_Unterlagen, … Steuer_2024}
#
# Gewählt ist je Art die Schreibweise, die er selbst am häufigsten und am
# ruhigsten führt: bei den Nebenkosten das nackte Jahr — der Ordner
# „60_Nebenkosten" sagt die Sache bereits, ein „NK-" davor wäre dieselbe
# Doppelnennung, die für Dateinamen schon in CXXII abgeschafft wurde. Beim
# Finanzamt dagegen „Steuer_JJJJ": so schreibt er es dort sechsmal
# hintereinander, und dieser Ordner verlässt sein Zuhause — er wird gepackt
# und weitergereicht, „2023" allein sagte beim Empfänger nichts.
#
# Ohne Jahr entsteht kein Unterordner. Ein Ordner „ohne-Jahr" hülfe niemandem
# beim Wiederfinden; der Beleg bleibt dann im Sachordner liegen, wie bisher.
# --------------------------------------------------------------------------

# Platzhalter der Unterordner-Vorlage. Bewusst wenige: das Jahr trägt fast
# alles, die Einheit braucht nur, wer mehrere Wohnungen getrennt abrechnet.
UNTERORDNER_PLATZHALTER = ("jahr", "einheit", "art")

# Vorgabe je Dokumentart. Die Schlüssel sind dieselben wie in `ZIELORDNER`
# (`routers/dokumente.py`) — ein Test wacht darüber, dass keine Art fehlt.
STANDARD_UNTERORDNER = {
    "Nebenkosten": "{jahr}",
    "Steuer": "Steuer_{jahr}",
    "Kredit": "{jahr}",
    "Versicherung": "{jahr}",
    "Mietvertrag": "{jahr}",
    "Korrespondenz": "{jahr}",
    "Hausverwaltung": "{jahr}",
    "Sonstiges": "{jahr}",
}


def unterordner_name(vorlage: str, jahr: int | None, einheit: str = "",
                     art: str = "") -> str:
    """Der Ordnername für einen Beleg innerhalb seines Sachordners.

    Leer heisst: kein Unterordner — die Datei bleibt im Sachordner. Das ist
    der Fall bei leerer Vorlage und immer dann, wenn die Vorlage das Jahr
    verlangt, der Beleg aber keines hat."""
    text = (vorlage or "").strip()
    if not text:
        return ""
    braucht_jahr = bool(re.search(r"\{jahr\}|%jahr\b", text, re.I))
    if braucht_jahr and not jahr:
        return ""
    werte = {"jahr": str(jahr) if jahr else "", "einheit": einheit, "art": art}
    for schluessel, wert in werte.items():
        sauber = _sauber(wert)
        text = text.replace("{" + schluessel + "}", sauber)
        text = re.sub(r"%" + schluessel + r"\b", sauber, text, flags=re.IGNORECASE)
    # Ein Unterordner ist genau eine Ebene: ein Schrägstrich in der Vorlage
    # legte sonst ungefragt einen Baum an.
    text = re.sub(_VERBOTEN, " ", text)
    return _entferne_leere_gruppen(text)


def unterordner_pruefen(vorlage: str) -> list[str]:
    """Meldet, was an einer Unterordner-Vorlage nicht funktioniert.

    Anders als beim Objektordner ist leer erlaubt: das heisst schlicht
    „flach ablegen, wie bisher"."""
    fehler = []
    if not (vorlage or "").strip():
        return fehler
    treffer = sorted(set(re.findall(_VERBOTEN, vorlage)))
    if treffer:
        fehler.append("Diese Zeichen sind in Ordnernamen nicht erlaubt und "
                      f"werden entfernt: {' '.join(treffer)}")
    bekannt = set(UNTERORDNER_PLATZHALTER)
    genutzt = set(re.findall(r"\{(\w+)\}", vorlage)) | \
        {t.lower() for t in re.findall(r"%(\w+)", vorlage)}
    unbekannt = sorted(genutzt - bekannt)
    if unbekannt:
        fehler.append("Unbekannte Platzhalter: " + ", ".join(unbekannt))
    if not genutzt:
        fehler.append("Ohne Platzhalter hiesse jeder Unterordner gleich — "
                      "dann lieber leer lassen.")
    return fehler


# Ein Jahr als eigenständige Zahl, kein Stück einer längeren.
def _jahr_muster(jahr: int) -> re.Pattern:
    return re.compile(rf"(?<!\d){jahr}(?!\d)")


# „2000-2021" — ein Ordner, der eine ganze Spanne aufnimmt. Genau so führt der
# Nutzer sein Nebenkosten-Archiv.
_SPANNE = re.compile(r"^\D*((?:19|20)\d{2})\s*[-–—/_]\s*((?:19|20)\d{2})\D*$")

# Bezeichnung einer Einheit, wie sie neben dem Jahr im Ordnernamen steht:
# „1OG", „W2", „EG", „Whg".
_EINHEIT_KURZ = re.compile(
    r"^(\d{0,2}[.,]?\s*(og|ug|dg|eg|kg)|w\d{1,2}|whg\d*|\d{1,2})$", re.I)

# Allerweltswörter, die neben dem Jahr stehen dürfen, ohne dass der Ordner
# etwas anderes meint — „Steuer_2018_Unterlagen" ist der Steuerordner 2018.
_BEIWERK = {"unterlagen", "belege", "beleg", "rechnungen", "rechnung",
            "abrechnung", "abrechnungen", "dokumente", "ordner", "archiv",
            "gesamt", "alle", "komplett"}


def _spanne(name: str) -> tuple[int, int] | None:
    """Deckt dieser Ordnername eine Jahresspanne ab?"""
    treffer = _SPANNE.match(name or "")
    if not treffer:
        return None
    von, bis = int(treffer.group(1)), int(treffer.group(2))
    return (von, bis) if von <= bis else None


def _nur_beiwerk(rest: str, woerter: tuple[str, ...]) -> bool:
    """Steht neben dem Jahr nur, was der Ordner ohnehin sagt?

    „2025" und „NK-2025-1OG" und „Steuer_2025" meinen dasselbe Jahr;
    „2025_Renovierung Bad EG" meint ein Vorhaben und wird nicht angerührt."""
    marken = {w.lower() for w in woerter if w} | _BEIWERK
    for stueck in re.split(r"[\s._\-–—()\[\]]+", rest):
        if not stueck:
            continue
        if stueck.lower() in marken or _EINHEIT_KURZ.match(stueck):
            continue
        return False
    return True


def unterordner_finden(vorhandene: list[str], jahr: int | None, ziel: str = "",
                       woerter: tuple[str, ...] = ()) -> str:
    """Welcher vorhandene Ordner dieses Jahr schon führt — oder "".

    Was der Nutzer selbst angelegt hat, wird benutzt statt danebengestellt:
    liegt „2025" schon da, wandert der Beleg dorthin und nicht in ein zweites
    „2025_Nebenkosten". Erkannt werden seine Schreibweisen — „2025",
    „NK-2025-1OG", „Steuer_2025" — und die Jahresspanne „2000-2021".

    Die Reihenfolge sagt, was gewinnt: der Name aus der Vorlage, dann der
    nackte Jahresordner, dann einer mit Beiwerk, zuletzt die Spanne. Ein
    eigener Jahresordner ist immer besser als ein Archiv.
    """
    if not jahr:
        return ""
    ziel_vergleich = vergleichsname(ziel)
    if ziel_vergleich:
        for name in vorhandene:
            if vergleichsname(name) == ziel_vergleich:
                return name

    muster = _jahr_muster(jahr)
    nackt: list[str] = []
    mit_beiwerk: list[str] = []
    spannen: list[str] = []
    for name in vorhandene:
        bereich = _spanne(name)
        if bereich:
            if bereich[0] <= jahr <= bereich[1]:
                spannen.append(name)
            continue
        if not muster.search(name):
            continue
        rest = muster.sub(" ", name)
        if not _nur_beiwerk(rest, woerter):
            continue
        (nackt if not rest.strip(" -_.·") else mit_beiwerk).append(name)

    for gruppe in (nackt, mit_beiwerk, spannen):
        if gruppe:
            # Der kürzeste Name ist der, der am wenigsten nebenher behauptet.
            return sorted(gruppe, key=lambda n: (len(n), n.lower()))[0]
    return ""


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


# --------------------------------------------------------------------------
# Dateinamen: Datum vorn, Sache in der Mitte, Betrag hinten
#
# CXXII — der Ordner ist Kontext, der Name nennt nur, was er hinzufügt. Im
# Ordner "60_Nebenkosten" heisst nichts "2026_Nebenkosten_Heizkosten".
# CXXIII — hinten steht der Betrag, damit man ihn im Ordner sofort sieht.
#
# Die Schreibweise ist dem Bestand des Nutzers abgesehen: er schreibt
# "2025_Muell_256,36€.pdf", "2025-10-oel-2729,91€.pdf",
# "111_2025-Brennstoff-4158,98€.pdf" — deutsches Komma, Euro-Zeichen hinten,
# nie ein Tausenderpunkt. Genau so wird hier gebaut:
#
#   * Das Datum steht vorn, sonst sortiert sich der Ordner nicht von selbst.
#   * Kein Tausenderpunkt — ein zweiter Punkt im Namen macht die Endung
#     mehrdeutig (und `_freier_name` müsste raten, wo der Stamm endet).
#   * Das Euro-Zeichen ist unproblematisch: `nextcloud._url` schickt jeden
#     Pfadteil durch `quote()`, das € als %E2%82%AC überträgt — auch im
#     Destination-Header eines MOVE, der damit reines ASCII bleibt.
# --------------------------------------------------------------------------

# "1.234,56 €", "256,36€" — deutsche Schreibweise, Punkt als Tausendertrenner.
_BETRAG_IM_NAMEN = re.compile(r"(?<![\d,.])(\d{1,3}(?:\.\d{3})+|\d+),(\d{2})\s*€")

# Datum im Namen: 2025, 2025-10, 2025.10, 2025_10, 2023-04-03 — alle Trenner
# kommen im Bestand vor ("2022.08_Öl", "2025-10-oel", "2021.09_PROKON",
# "2023-04-03 Mietvertrag"). Der Tag wird mitgelesen, damit er nicht als Rest
# im Namen stehenbleibt; im Dateinamen steht später nur Jahr und Monat.
# Die Ziffernwächter halten längere Zahlen heraus: "20230915" ist kein Datum,
# "WWK-2025-1196,09€" hat keinen Monat 11.
_DATUM_IM_NAMEN = re.compile(
    r"(?<!\d)(20\d{2})(?:[-._](0[1-9]|1[0-2])(?:[-._](0[1-9]|[12]\d|3[01]))?)?"
    r"(?!\d)")


def datumsteil(jahr: int | None, monat: int | None = None) -> str:
    """JJJJ-MM, JJJJ oder "ohne-Jahr" — was bekannt ist, sortierbar."""
    if not jahr:
        return "ohne-Jahr"
    if monat and 1 <= monat <= 12:
        return f"{jahr:04d}-{monat:02d}"
    return f"{jahr:04d}"


def betragsteil(betrag: float | None) -> str:
    """"2729,91€" — oder leer, wenn kein Betrag bekannt ist.

    Nur positive Beträge: eine Gutschrift steht als solche im Beleg, im
    Dateinamen wäre ein Minuszeichen vor der Endung nur verwirrend."""
    if betrag is None:
        return ""
    try:
        wert = round(float(betrag), 2)
    except (TypeError, ValueError):
        return ""
    if wert <= 0:
        return ""
    return f"{wert:.2f}".replace(".", ",") + "€"


def betrag_aus_namen(name: str) -> float | None:
    """Der Betrag, den ein Dateiname schon trägt.

    Der Nutzer hat ihn oft selbst drangeschrieben; beim Einsortieren soll er
    nicht verlorengehen, nur weil die Texterkennung den Beleg nie gesehen hat.
    Bei mehreren Zahlen gewinnt die letzte — Beträge stehen hinten."""
    treffer = _BETRAG_IM_NAMEN.findall(name or "")
    if not treffer:
        return None
    ganz, nachkomma = treffer[-1]
    return round(float(ganz.replace(".", "") + "." + nachkomma), 2)


def ohne_betrag(name: str) -> str:
    """Derselbe Name ohne Betragsangabe — samt der Klammern drumherum.

    Der Nutzer schreibt ihn mal nackt ("Muell_256,36€"), mal eingeklammert
    ("DeltaT-2023-(200,75€)"). Beides muss weg, bevor der Betrag neu
    angehängt wird, sonst steht er zweimal da."""
    ohne = _BETRAG_IM_NAMEN.sub(" ", name or "")
    ohne = re.sub(r"\(\s*\)|\[\s*\]", " ", ohne)
    return re.sub(r"\s+", " ", ohne).strip(" -_.·")


def datum_aus_namen(name: str) -> tuple[int | None, int | None]:
    """Jahr und Monat aus einem Dateinamen. (None, None) heisst: da steht keins.

    Es gilt das erste Datum — der Nutzer schreibt es nach vorn, alles Weitere
    ist Aktenzeichen oder Zählerstand."""
    treffer = _DATUM_IM_NAMEN.search(name or "")
    if not treffer:
        return None, None
    monat = treffer.group(2)
    return int(treffer.group(1)), int(monat) if monat else None


def ohne_datum(name: str) -> str:
    """Derselbe Name ohne Datumsangaben — sie werden vorn neu gesetzt."""
    ohne = _DATUM_IM_NAMEN.sub(" ", name or "")
    return re.sub(r"\s+", " ", ohne).strip(" -_.·")


def ohne_ordnerwort(text: str, *woerter: str) -> str:
    """Streicht aus einer Bezeichnung, was der Ordner schon sagt (CXXII).

    Getroffen wird ein Wort nur *ab* seinem Anfang: "Nebenkostenabrechnung"
    wird zu "Abrechnung", "Grundsteuerbescheid" bleibt aber "Grundsteuer­-
    bescheid" — sonst hiesse er "Grundbescheid", und das ist kein Wort.

    Bleibt danach nichts übrig, kommt nichts zurück; der Aufrufer entscheidet,
    was er stattdessen einsetzt."""
    rest = _sauber(text)
    for wort in woerter:
        wort = _sauber(wort)
        if not wort:
            continue
        # Zwei Schnitte. Erst das Wort samt gebeugter Endung — "Versicherungen"
        # soll nicht als "en" zurückbleiben. Dann derselbe Wortanfang in einem
        # längeren Wort, dessen Rest stehen bleibt ("Nebenkostenabrechnung"
        # -> "Abrechnung").
        muster = re.escape(wort)
        rest = re.sub(r"\b" + muster + r"\w{0,2}\b", " ", rest, flags=re.I)
        rest = re.sub(r"\b" + muster, " ", rest, flags=re.I)
        rest = re.sub(r"\s+", " ", rest).strip(" -_.·")
    # "Nebenkostenabrechnung" liess "abrechnung" zurück — klein geschrieben,
    # weil der grosse Anfangsbuchstabe mit weggeschnitten wurde.
    return rest[:1].upper() + rest[1:] if rest else ""
