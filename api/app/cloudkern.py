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

from . import familienraum
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

# N332 — nach dem Lebenslauf einer Immobilie geordnet, Themen in 10er-Blöcken,
# und bewusst schlank auf der obersten Ebene. Drei Entscheidungen des Nutzers
# stecken darin:
#   * die Bauphase gehört zu Kauf & Finanzierung — sie steht ganz am Anfang und
#     ist kein laufender Unterhalt (das ist „50_Renovierung_Instandsetzung");
#   * es gibt KEINEN Auffangordner mehr. Was sich nicht sicher zuordnen lässt,
#     liegt offen auf der obersten Ebene der Immobilie: im Explorer sofort
#     sichtbar und von Hand einsortierbar, statt in „99_Sonstiges" zu
#     verschwinden (siehe ZIELORDNER unten);
#   * Mieterhöhungen, Eigentümerversammlungen und Hausverwaltung waren je ein
#     eigener Hauptordner für Fälle, die nur bei einer von fünf Immobilien
#     vorkamen — sie sind jetzt Unterordner bzw. zusammengelegt.
# Die Ordnernamen bleiben bewusst ohne Umlaute (wie „Mietvertraege" zuvor);
# lesbar wird es über HAUPTORDNER_LESBAR, nicht über den Dateinamen selbst.

STRUKTUR_GRUNDSTUECK = [                # schlank: Pacht + Grundsteuer
    "10_Fotos_Lageplaene",
    "11_Kauf_Bau_Finanzierung",        # Kaufvertrag, Notar, Grundbuch
    "20_Kommunikation",
    "30_Vermietung_Verpachtung",       # Pachtverträge, Pächter
    "32_Nebenkosten",                  # Grundsteuer als jährliche NK
    "70_Steuer_Finanzamt",
]

STRUKTUR_WEG = [
    "10_Fotos_Lageplaene",
    "11_Kauf_Bau_Finanzierung",
    "20_Kommunikation",
    "30_Vermietung_Verpachtung",
    "31_WEG_Verwaltung",               # nur WEG: Versammlungen + Verwalter
    "32_Nebenkosten",
    "50_Renovierung_Instandsetzung",
    "70_Steuer_Finanzamt",
]

STRUKTUR_MFH = [                       # selbstverwaltet (eigene NK-Verteilung)
    "10_Fotos_Lageplaene",
    "11_Kauf_Bau_Finanzierung",
    "20_Kommunikation",
    "30_Vermietung_Verpachtung",
    "32_Nebenkosten",
    "50_Renovierung_Instandsetzung",
    "70_Steuer_Finanzamt",
]


def struktur_fuer(objekt) -> list[str]:
    """Die passende Ordnerstruktur zum Fall der Immobilie."""
    from .models import ist_grundstueck
    if ist_grundstueck(objekt):
        return STRUKTUR_GRUNDSTUECK
    if getattr(objekt, "weg", False):
        return STRUKTUR_WEG
    return STRUKTUR_MFH


# N332 — die Hauptordner der bisherigen Fassung. Sie werden NICHT mehr angelegt
# (sie stehen in keiner der drei Vorlagen oben), gelten aber weiter als
# Hauptordner: solange noch ein Beleg in einem davon liegt, soll er im Baum
# richtig einsortiert und lesbar beschriftet erscheinen statt als fremder
# Sachordner. Nach dem Umzug bleiben sie leer stehen — gelöscht wird in der
# Cloud grundsätzlich nichts.
STRUKTUR_ALTBESTAND = [
    "00_Fotos_Lageplan",
    "01_Allgemein_Hauskonto",
    "10_Fotos_Lage",
    "10_Fotos_Lageplan",
    "10_Fotos_Lagepläne",
    "10_Kauf_Finanzierung",
    "11_Bauphase",
    "20_Mietvertraege_Vermietung",
    "20_Vermietung_Mietverträge",
    "30_Kommunikation",
    "30_Mietvertraege_Vermietung",
    "31_Mieterhoehungen",
    "40_Eigentuemerversammlungen",
    "40_Kauf_Eigentum_Finanzierung",
    "41_Hausverwaltung",
    "50_Bauphase_Projekte",
    "50_Instandsetzung_Renovierung",
    "50_Pacht_und_Paechter",
    "50_Renovierung, Instandhaltung",
    "51_Mieterhoehungen",
    "55_Eigentuemerversammlungen",
    "60_Nebenkosten",
    "80_Garten",
    "80_Hausverwaltung",
    "98_Archiv",
    "99_Sonstiges",
]

# Obermenge aller möglichen Hauptordner — für die Prüfung „ist das ein
# Hauptordner (und kein Sachordner darunter)?" und als neutraler Bezug.
STRUKTUR = sorted(set(STRUKTUR_GRUNDSTUECK + STRUKTUR_WEG + STRUKTUR_MFH
                      + STRUKTUR_ALTBESTAND))

# N331g — Nutzer-Fund: die „Ordner verschieben"-Auswahl (routers/dokumente.py
# ::ablageziele) zeigte den rohen Ordnercode („40_Kauf_Eigentum_Finanzierung")
# unverändert als Beschriftung — kein Umlaut, keine Satzzeichen, keine
# Auftrennung von der laufenden Nummer. Die Auswahl selbst ist längst das
# eigene, gestaltete Listenfeld (auswahl.js), nur die Beschriftung sah aus wie
# ein technischer Rohwert. Von Hand statt per Regel: die Menge der Ordnernamen
# ist klein und fest (`STRUKTUR` oben), ein Rateversuch (Regex, ae→ä) träfe
# nicht jeden Fall zuverlässig.
HAUPTORDNER_LESBAR = {
    # N332 — der geltende Standard
    "10_Fotos_Lageplaene": "Fotos & Lagepläne",
    "11_Kauf_Bau_Finanzierung": "Kauf, Bau & Finanzierung",
    "20_Kommunikation": "Kommunikation",
    "30_Vermietung_Verpachtung": "Vermietung & Verpachtung",
    "31_WEG_Verwaltung": "WEG-Verwaltung",
    "32_Nebenkosten": "Nebenkosten",
    "50_Renovierung_Instandsetzung": "Renovierung & Instandsetzung",
    "70_Steuer_Finanzamt": "Steuer & Finanzamt",
    # Altbestand — bleibt lesbar, solange noch etwas darin liegt
    "00_Fotos_Lageplan": "Fotos & Lageplan",
    "01_Allgemein_Hauskonto": "Allgemein & Hauskonto",
    "10_Fotos_Lage": "Fotos & Lage",
    "10_Fotos_Lageplan": "Fotos & Lageplan",
    "10_Fotos_Lagepläne": "Fotos & Lagepläne",
    "10_Kauf_Finanzierung": "Kauf & Finanzierung",
    "11_Bauphase": "Bauphase",
    "20_Mietvertraege_Vermietung": "Mietverträge & Vermietung",
    "20_Vermietung_Mietverträge": "Vermietung & Mietverträge",
    "30_Kommunikation": "Kommunikation",
    "30_Mietvertraege_Vermietung": "Mietverträge & Vermietung",
    "31_Mieterhoehungen": "Mieterhöhungen",
    "40_Eigentuemerversammlungen": "Eigentümerversammlungen",
    "40_Kauf_Eigentum_Finanzierung": "Kauf, Eigentum & Finanzierung",
    "41_Hausverwaltung": "Hausverwaltung",
    "50_Bauphase_Projekte": "Bauphase & Projekte",
    "50_Instandsetzung_Renovierung": "Instandsetzung & Renovierung",
    "50_Pacht_und_Paechter": "Pacht & Pächter",
    "50_Renovierung, Instandhaltung": "Renovierung & Instandhaltung",
    "51_Mieterhoehungen": "Mieterhöhungen",
    "55_Eigentuemerversammlungen": "Eigentümerversammlungen",
    "60_Nebenkosten": "Nebenkosten",
    "80_Garten": "Garten",
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
    "Nebenkosten": "32_Nebenkosten",
    "Steuer": "70_Steuer_Finanzamt",
    # CCCII — notariell beurkundete Verträge (Kauf, Auflassung, Grundschuld­
    # bestellung) sind eine eigene Art: aus ihnen entsteht ein Notarvertrag.
    "Notarvertrag": "11_Kauf_Bau_Finanzierung",
    "Kredit": "11_Kauf_Bau_Finanzierung",
    # N332 — „01_Allgemein_Hauskonto" gibt es nicht mehr. Die Gebäude- und
    # Haftpflichtversicherung ist die klassische umlagefähige Betriebskosten-
    # position; ihre Policen und Rechnungen liegen deshalb bei den Nebenkosten.
    "Versicherung": "32_Nebenkosten",
    "Mietvertrag": "30_Vermietung_Verpachtung",
    "Korrespondenz": "20_Kommunikation",
    "Hausverwaltung": "31_WEG_Verwaltung",
    # N9 — Lagepläne gehören zu Fotos & Lage, nicht in „Sonstiges".
    "Lageplan": "10_Fotos_Lageplaene",
    # N283d — die einmaligen Erwerbsnebenkosten (Notarrechnung, Grunderwerb-
    # steuer, Grundbuchamt, Makler) sind KEINE laufende Steuersache. Sie landeten
    # mangels eigener Art unter „70_Steuer_Finanzamt", gehören aber zum Erwerb
    # selbst — dort liegt auch der Kaufvertrag, auf den sie sich beziehen.
    "Erwerbsnebenkosten": "11_Kauf_Bau_Finanzierung",
    # N331c — die Eintragungsbekanntmachung einer Grundschuld gehört zu
    # denselben Kauf-/Finanzierungsunterlagen wie Notarvertrag und Kredit.
    "Grundschuld": "11_Kauf_Bau_Finanzierung",
    # N289 — Handwerkerrechnungen eines Bauvorhabens gehören zur Bauphase.
    # Ohne diesen Eintrag fiel die Kategorie „Renovierung" auf den Vorgabewert
    # „99_Sonstiges" zurück: die Rechnungen einer Generalsanierung lagen
    # zwischen allem anderen. Der Projektordner darunter kommt aus der
    # Renovierung selbst (`renovierung.projektordner`).
    "Renovierung": "50_Renovierung_Instandsetzung",
    # N332 — kein Auffangordner mehr: „Sonstiges" heisst jetzt „oberste Ebene
    # der Immobilie". Ein Beleg, den die Erkennung nicht sicher einordnen kann,
    # liegt damit offen zwischen den Ordnern — im Explorer sofort als
    # unsortiert erkennbar und mit einem Zug an seinen Platz zu ziehen. Vorher
    # verschwand er in „99_Sonstiges" und fiel nie wieder auf.
    "Sonstiges": "",
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
# N332 — Ordner → Kategorie für den Altbestand (siehe STRUKTUR_ALTBESTAND).
# „98_Archiv" und „99_Sonstiges" stehen bewusst NICHT darin: ihre Kategorie
# zeigt inzwischen auf die oberste Ebene, ein automatisches Einsortieren von
# dort wäre eine Bewegung ohne Ziel. Was darin liegt, wird beim Umzug von Hand
# verteilt und danach nicht mehr angefasst.
_ALTBESTAND_KATEGORIE = {
    "00_Fotos_Lageplan": "Lageplan",
    "01_Allgemein_Hauskonto": "Versicherung",
    "10_Fotos_Lage": "Lageplan",
    "10_Fotos_Lageplan": "Lageplan",
    "10_Fotos_Lagepläne": "Lageplan",
    "10_Kauf_Finanzierung": "Kredit",
    "11_Bauphase": "Renovierung",
    "20_Mietvertraege_Vermietung": "Mietvertrag",
    "20_Vermietung_Mietverträge": "Mietvertrag",
    "30_Kommunikation": "Korrespondenz",
    "30_Mietvertraege_Vermietung": "Mietvertrag",
    "31_Mieterhoehungen": "Mietvertrag",
    "40_Eigentuemerversammlungen": "Hausverwaltung",
    "40_Kauf_Eigentum_Finanzierung": "Kredit",
    "41_Hausverwaltung": "Hausverwaltung",
    "50_Bauphase_Projekte": "Renovierung",
    "50_Instandsetzung_Renovierung": "Renovierung",
    "50_Pacht_und_Paechter": "Mietvertrag",
    "50_Renovierung, Instandhaltung": "Renovierung",
    "51_Mieterhoehungen": "Mietvertrag",
    "55_Eigentuemerversammlungen": "Hausverwaltung",
    "60_Nebenkosten": "Nebenkosten",
}

_MEHRDEUTIGE_ORDNER_KATEGORIE = {
    "40_Kauf_Eigentum_Finanzierung": "Kredit",   # Altbestand
    "11_Kauf_Bau_Finanzierung": "Kredit",        # N332 — dessen Nachfolger
    # N332 — Versicherungen teilen sich den Nebenkosten-Ordner, sind aber nicht
    # dessen Leitkategorie: was dort landet, ist im Zweifel eine NK-Sache.
    "32_Nebenkosten": "Nebenkosten",
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
        if not ordner:      # N332 — „oberste Ebene" ist kein Sachordner
            continue
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
    # N332 — die abgelösten Ordner behalten ihre Kategorie. Sonst gälte ein
    # Beleg, der noch in „60_Nebenkosten" liegt, plötzlich als beliebiger
    # Fremdordner: er würde beim Einsortieren in Jahresordner übersehen und im
    # Baum falsch einsortiert. Die neuen Namen haben Vorrang.
    for ordner, kategorie in _ALTBESTAND_KATEGORIE.items():
        ergebnis.setdefault(ordner, kategorie)
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
    """N436 — jede Einstellung liegt unter dem Namensraum der Familie im
    aktuellen Kontext (`familienraum.setzen`, von `deps.aktuelle_familie` je
    Anfrage automatisch gesetzt). Gilt für JEDEN Schlüssel, der hier
    ankommt — auch einen bereits zusammengesetzten wie
    `pv_versendet:<slug>:<jahr>:<name>`."""
    eintrag = session.get(Einstellung, familienraum.schluessel(schluessel))
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
