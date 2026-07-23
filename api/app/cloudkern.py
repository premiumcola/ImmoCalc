"""Geteilte Nextcloud-Infrastruktur — von `cloud` und `dokumente` gebraucht.

Neutraler Grund für beide Router: hier steht nur, was wirklich von beiden
Seiten benutzt wird (Struktur, Verbindungsaufbau, Unterordner-Vorlagen,
Zielordner je Dokumentart). Dieses Modul importiert selbst nie aus `cloud`
oder `dokumente` — sonst wäre der Zirkel nur verschoben, nicht aufgelöst.
"""
import json
import logging

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

STRUKTUR_GRUNDSTUECK = [
    "01_Allgemein_Hauskonto",
    "10_Fotos_Lage",
    "40_Kauf_Eigentum_Finanzierung",   # Kaufvertrag, Notar, Grundbuch
    "70_Steuer_Finanzamt",             # Grundsteuer
    "30_Kommunikation",
    "99_Sonstiges",
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

# Wohin eine Kategorie einsortiert wird. Alles Abrechnungsrelevante landet
# unter Nebenkosten, der Rest bei seinem Thema.
ZIELORDNER = {
    "Nebenkosten": "60_Nebenkosten",
    "Steuer": "70_Steuer_Finanzamt",
    "Kredit": "40_Kauf_Eigentum_Finanzierung",
    "Versicherung": "01_Allgemein_Hauskonto",
    "Mietvertrag": "20_Mietvertraege_Vermietung",
    "Korrespondenz": "30_Kommunikation",
    "Hausverwaltung": "80_Hausverwaltung",
    "Sonstiges": "99_Sonstiges",
}

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
