"""Geteilte Nextcloud-Infrastruktur — von `cloud` und `dokumente` gebraucht.

Neutraler Grund für beide Router: hier steht nur, was wirklich von beiden
Seiten benutzt wird (Struktur, Verbindungsaufbau, Unterordner-Vorlagen,
Zielordner je Dokumentart). Dieses Modul importiert selbst nie aus `cloud`
oder `dokumente` — sonst wäre der Zirkel nur verschoben, nicht aufgelöst.
"""
import json
import logging
import re

from fastapi import HTTPException
from sqlmodel import Session

from .bezeichnung import STANDARD_UNTERORDNER, hierarchie, unterordner_name
from .models import Einstellung, Objekt
from .nextcloud import Nextcloud

log = logging.getLogger("immocalc")

# Vereinheitlichte Struktur je Immobilie — Zehnerschritte lassen Platz zum
# Einfuegen, die Nummern folgen dem gewachsenen Bestand.
# CCL — die Ordnerstruktur hängt vom Fall der Immobilie ab. Ein Grundstück
# braucht keine Nebenkosten oder Mietverträge; eine Eigentumswohnung in einer
# WEG führt Eigentümerversammlungen und Hausverwaltung statt eigener
# NK-Verteilung; ein selbstverwaltetes Haus verteilt die Nebenkosten selbst und
# hat objekteigene Projekte (Garten, Hof, Umbau). Die Ordnernamen bleiben über
# alle Typen gleich (damit ZIELORDNER weiter greift) — nur die Auswahl ändert
# sich. Abgeleitet aus den Vorgabeordnern des Nutzers.

STRUKTUR_GRUNDSTUECK = [                # CCXCVIII — schlank: Pacht + Grundsteuer
    "10_Fotos_Lage",
    "30_Kommunikation",
    "40_Kauf_Eigentum_Finanzierung",   # Kaufvertrag, Notar, Grundbuch
    "50_Pacht_und_Paechter",           # Pachtverträge, Pächter
    "60_Nebenkosten",                  # Grundsteuer als jährliche NK
    "70_Steuer_Finanzamt",
]

STRUKTUR_WEG = [
    "01_Allgemein_Hauskonto",
    "10_Fotos_Lage",
    "20_Mietvertraege_Vermietung",
    "40_Kauf_Eigentum_Finanzierung",
    "50_Bauphase_Projekte",
    "51_Mieterhoehungen",
    "60_Nebenkosten",
    "70_Steuer_Finanzamt",
    "55_Eigentuemerversammlungen",     # nur WEG
    "80_Hausverwaltung",               # nur WEG
    "99_Sonstiges",
]

STRUKTUR_MFH = [                       # selbstverwaltet (eigene NK-Verteilung)
    "01_Allgemein_Hauskonto",
    "10_Fotos_Lage",
    "20_Mietvertraege_Vermietung",
    "30_Kommunikation",
    "40_Kauf_Eigentum_Finanzierung",
    "50_Bauphase_Projekte",            # Umbau/Renovierung, Garten, Hof
    "60_Nebenkosten",
    "70_Steuer_Finanzamt",
    "98_Archiv",
    "99_Sonstiges",
]


def struktur_fuer(objekt) -> list[str]:
    """Die passende Ordnerstruktur zum Fall der Immobilie."""
    from .models import ist_grundstueck
    if ist_grundstueck(objekt):
        return STRUKTUR_GRUNDSTUECK
    if getattr(objekt, "weg", False):
        return STRUKTUR_WEG
    return STRUKTUR_MFH


# Obermenge aller möglichen Hauptordner — für die Prüfung „ist das ein
# Hauptordner (und kein Sachordner darunter)?" und als neutraler Bezug.
STRUKTUR = sorted(set(STRUKTUR_GRUNDSTUECK + STRUKTUR_WEG + STRUKTUR_MFH))

# N331g — Nutzer-Fund: die „Ordner verschieben"-Auswahl (routers/dokumente.py
# ::ablageziele) zeigte den rohen Ordnercode („40_Kauf_Eigentum_Finanzierung")
# unverändert als Beschriftung — kein Umlaut, keine Satzzeichen, keine
# Auftrennung von der laufenden Nummer. Die Auswahl selbst ist längst das
# eigene, gestaltete Listenfeld (auswahl.js), nur die Beschriftung sah aus wie
# ein technischer Rohwert. Von Hand statt per Regel: die Menge der Ordnernamen
# ist klein und fest (`STRUKTUR` oben), ein Rateversuch (Regex, ae→ä) träfe
# nicht jeden Fall zuverlässig.
HAUPTORDNER_LESBAR = {
    "01_Allgemein_Hauskonto": "Allgemein & Hauskonto",
    "10_Fotos_Lage": "Fotos & Lage",
    "20_Mietvertraege_Vermietung": "Mietverträge & Vermietung",
    "30_Kommunikation": "Kommunikation",
    "40_Kauf_Eigentum_Finanzierung": "Kauf, Eigentum & Finanzierung",
    "50_Bauphase_Projekte": "Bauphase & Projekte",
    "50_Pacht_und_Paechter": "Pacht & Pächter",
    "51_Mieterhoehungen": "Mieterhöhungen",
    "55_Eigentuemerversammlungen": "Eigentümerversammlungen",
    "60_Nebenkosten": "Nebenkosten",
    "70_Steuer_Finanzamt": "Steuer & Finanzamt",
    "80_Hausverwaltung": "Hausverwaltung",
    "98_Archiv": "Archiv",
    "99_Sonstiges": "Sonstiges",
}


def hauptordner_lesbar(art: str) -> str:
    """Der Hauptordnercode in Klartext für die Oberfläche.

    Kommt ein neuer Ordnercode dazu, ohne dass diese Tabelle mitgepflegt
    wird, bleibt es nicht stumm bei einer leeren Beschriftung — die
    laufende Nummer fällt weg und Unterstriche werden zu Leerzeichen; kein
    hübsches Ergebnis, aber ein lesbares."""
    if art in HAUPTORDNER_LESBAR:
        return HAUPTORDNER_LESBAR[art]
    ohne_nummer = re.sub(r"^\d+_", "", art)
    return ohne_nummer.replace("_", " ") or art

# Wohin eine Kategorie einsortiert wird. Alles Abrechnungsrelevante landet
# unter Nebenkosten, der Rest bei seinem Thema.
ZIELORDNER = {
    "Nebenkosten": "60_Nebenkosten",
    "Steuer": "70_Steuer_Finanzamt",
    # CCCII — notariell beurkundete Verträge (Kauf, Auflassung, Grundschuld­
    # bestellung) sind eine eigene Art: aus ihnen entsteht ein Notarvertrag.
    "Notarvertrag": "40_Kauf_Eigentum_Finanzierung",
    "Kredit": "40_Kauf_Eigentum_Finanzierung",
    "Versicherung": "01_Allgemein_Hauskonto",
    "Mietvertrag": "20_Mietvertraege_Vermietung",
    "Korrespondenz": "30_Kommunikation",
    "Hausverwaltung": "80_Hausverwaltung",
    # N9 — Lagepläne gehören zu Fotos & Lage, nicht in „Sonstiges".
    "Lageplan": "10_Fotos_Lage",
    # N283d — die einmaligen Erwerbsnebenkosten (Notarrechnung, Grunderwerb-
    # steuer, Grundbuchamt, Makler) sind KEINE laufende Steuersache. Sie landeten
    # mangels eigener Art unter „70_Steuer_Finanzamt", gehören aber zum Erwerb
    # selbst — dort liegt auch der Kaufvertrag, auf den sie sich beziehen.
    "Erwerbsnebenkosten": "40_Kauf_Eigentum_Finanzierung",
    # N331c — die Eintragungsbekanntmachung einer Grundschuld gehört zu
    # denselben Kauf-/Finanzierungsunterlagen wie Notarvertrag und Kredit.
    "Grundschuld": "40_Kauf_Eigentum_Finanzierung",
    # N289 — Handwerkerrechnungen eines Bauvorhabens gehören zur Bauphase.
    # Ohne diesen Eintrag fiel die Kategorie „Renovierung" auf den Vorgabewert
    # „99_Sonstiges" zurück: die Rechnungen einer Generalsanierung lagen
    # zwischen allem anderen. Der Projektordner darunter kommt aus der
    # Renovierung selbst (`renovierung.projektordner`).
    "Renovierung": "50_Bauphase_Projekte",
    "Sonstiges": "99_Sonstiges",
}

# --------------------------------------------------------------------------
# N316e — die Rückrichtung (Ordner → Kategorie) war zweimal von Hand gepflegt
# (`_HAUPT_KATEGORIE` und `_sachordner_kategorie` in routers/cloud.py) und
# widersprach sich für "40_Kauf_Eigentum_Finanzierung": die eine Stelle sagte
# "Kredit", die andere (ein blindes `{ordner: art for art, ordner in
# ZIELORDNER.items()}`) landete zufällig bei "Erwerbsnebenkosten" — je
# nachdem, welche Kategorie zuletzt in ZIELORDNER auf denselben Ordner zeigt.
# ZIELORDNER ist absichtlich viele-zu-eins (mehrere Kategorien teilen sich
# einen Ordner), die Umkehrung braucht deshalb eine bewusste Entscheidung
# statt eines impliziten Dict-Rücklaufs.
#
# Für "40_Kauf_Eigentum_Finanzierung" gilt "Kredit": das ist die Kategorie,
# mit der dieser Ordner in der allerersten Fassung dieser Datei entstand
# (der Ordnername trägt "Finanzierung" nicht zufällig). "Notarvertrag"
# (CCCII) und "Erwerbsnebenkosten" (N283d) kamen später dazu und teilen sich
# den Ordner mit dem Kauf/Finanzierungs-Vorgang, verdrängen ihn aber nicht
# als dessen Leitkategorie.
_MEHRDEUTIGE_ORDNER_KATEGORIE = {
    "40_Kauf_Eigentum_Finanzierung": "Kredit",
}


def _baue_sachordner_kategorie() -> dict[str, str]:
    """Ordner → Kategorie, deterministisch aus `ZIELORDNER` abgeleitet.

    Ein Ordner mit genau einer Kategorie ist eindeutig. Ein Ordner mit
    mehreren (aktuell nur der Kauf/Finanzierungs-Ordner) braucht einen
    Eintrag in `_MEHRDEUTIGE_ORDNER_KATEGORIE` — fehlt er, ist das eine Lücke
    im Katalog und wird laut gemeldet statt still nach Einfügereihenfolge
    zu raten."""
    kategorien_je_ordner: dict[str, list[str]] = {}
    for kategorie, ordner in ZIELORDNER.items():
        kategorien_je_ordner.setdefault(ordner, []).append(kategorie)

    ergebnis: dict[str, str] = {}
    for ordner, kategorien in kategorien_je_ordner.items():
        if len(kategorien) == 1:
            ergebnis[ordner] = kategorien[0]
            continue
        gewaehlt = _MEHRDEUTIGE_ORDNER_KATEGORIE.get(ordner)
        if gewaehlt is None or gewaehlt not in kategorien:
            raise RuntimeError(
                f'Ordner „{ordner}" hat mehrere Kategorien {kategorien} '
                "ohne eindeutige Entscheidung in "
                "_MEHRDEUTIGE_ORDNER_KATEGORIE.")
        ergebnis[ordner] = gewaehlt
    return ergebnis


# Sachordner-Name → Dokumentart — die einzige Quelle der Wahrheit für die
# Rückrichtung. Beim Import einmal berechnet, damit eine Lücke im Katalog
# sofort auffällt statt erst beim ersten Aufruf einer der Nutzerinnen.
SACHORDNER_KATEGORIE = _baue_sachordner_kategorie()

# Kurzform der Art für den Dateinamen. Der Ordner sagt zwar schon, worum es
# geht — aber ein Name wandert aus dem Ordner heraus: in eine Suche, in einen
# Mailanhang, auf den Schreibtisch. „2026-02_Rechnung_104,15€.pdf" sagt dort
# nichts; „2026-02_NK-Schornsteinfeger_104,15€.pdf" sagt alles. Kurz gehalten,
# damit der Name nicht wieder in die Breite läuft (CXXII).
ARTKUERZEL = {
    "Nebenkosten": "NK",
    "Steuer": "Steuer",
    "Kredit": "Kredit",
    "Versicherung": "Vers",
    "Mietvertrag": "Miete",
    "Korrespondenz": "Post",
    "Hausverwaltung": "HV",
    # N313 — „Notarvertrag" fehlte hier kommentarlos und fiel damit still auf
    # "" zurück, während die drei bewusst leeren Kürzel eine Begründung tragen.
    # Ein Kaufvertrag heisst so, das gehört in den Dateinamen.
    "Notarvertrag": "Notar",
    # N9 — kein Kürzel für Lagepläne: der Name trägt „Lageplan …" schon selbst.
    "Lageplan": "",
    # N283d — „Erwerb" macht im Dateinamen sofort klar, worum es geht; ohne
    # Kürzel hiesse eine Notarrechnung nur „2017-11_Notar…" und wäre von der
    # laufenden Notarkorrespondenz nicht zu unterscheiden.
    "Erwerbsnebenkosten": "Erwerb",
    # N331c — „Grundschuld" statt eines leeren Kürzels: `feldzuordnung` hat für
    # `grundschulden` keinen eigenen Namensvorschlag (weder `art` noch
    # `bezeichnung`/`partei`/`kostenart` sind dort belegt), der Dateiname
    # bliebe sonst nur Datum und Betrag ohne jeden Hinweis, worum es geht.
    "Grundschuld": "Grundschuld",
    # N289 — kein Kürzel: `feldzuordnung` baut den Namen einer Handwerker-
    # rechnung bereits sprechend („Renovierung Elektro Firma"), und der
    # Projektordner sagt ohnehin, zu welchem Vorhaben sie gehört.
    "Renovierung": "",
    "Sonstiges": "",
}

S_URL, S_BENUTZER, S_PASSWORT, S_HOME, S_TLS, S_VORLAGE = (
    "nc_url", "nc_benutzer", "nc_passwort", "nc_home", "nc_tls_pruefen",
    "nc_ordner_vorlage")
# CXCI: die Unterordner-Vorlagen je Dokumentart, als JSON in einer Zeile.
# Ein Schlüssel je Art wäre ein Dutzend Einstellungen für eine Entscheidung.
S_UNTERORDNER = "nc_unterordner_vorlagen"


def _lies(session: Session, schluessel: str, vorgabe: str = "") -> str:
    eintrag = session.get(Einstellung, schluessel)
    return eintrag.wert if eintrag else vorgabe


def verbindung(session: Session) -> Nextcloud:
    url = _lies(session, S_URL)
    benutzer = _lies(session, S_BENUTZER)
    passwort = _lies(session, S_PASSWORT)
    if not (url and benutzer and passwort):
        raise HTTPException(400, "Nextcloud ist noch nicht eingerichtet")
    # heimat begrenzt jeden schreibenden Zugriff auf den gewählten Ordner
    return Nextcloud(url, benutzer, passwort,
                     zertifikat_pruefen=_lies(session, S_TLS) == "1",
                     heimat=_lies(session, S_HOME))


# --------------------------------------------------------------------------
# CXCI: Unterordner im Sachordner — eine Vorlage je Dokumentart
# --------------------------------------------------------------------------

def unterordner_vorlagen(session: Session) -> dict[str, str]:
    """Die Vorlagen je Dokumentart — eingestellte vor Vorgabe.

    Unlesbar Gespeichertes wird gemeldet und übergangen, nie zum Fehler: eine
    kaputte Einstellung darf keinen Beleg am Einsortieren hindern."""
    eigene: dict[str, str] = {}
    roh = _lies(session, S_UNTERORDNER)
    if roh:
        try:
            geladen = json.loads(roh)
        except ValueError as fehler:
            log.warning("Unterordner-Vorlagen unlesbar: %s", fehler)
            geladen = None
        if isinstance(geladen, dict):
            eigene = {str(k): str(v) for k, v in geladen.items()}
    return {**STANDARD_UNTERORDNER, **eigene}


def einheit_von(objekt: Objekt) -> str:
    """Was die Einheit im Haus benennt — „Whg 1. OG", sonst nichts.

    Nur wer mehrere Wohnungen getrennt ablegt, braucht sie im Ordnernamen;
    bei einem Haus bleibt der Platzhalter leer und fällt weg."""
    return hierarchie(objekt.name, objekt.ort or "",
                      objekt.strasse or "")["einheit"]


def unterordner_fuer(session: Session, objekt: Objekt, kategorie: str,
                     jahr: int | None) -> str:
    """Der Ordnername für diesen Beleg — leer heisst: kein Unterordner."""
    return unterordner_name(unterordner_vorlagen(session).get(kategorie, ""),
                            jahr, einheit=einheit_von(objekt), art=kategorie)
