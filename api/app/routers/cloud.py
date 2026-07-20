"""Nextcloud-Anbindung: einrichten, Ordner durchsehen, Struktur anlegen."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from ..bezeichnung import (PLATZHALTER, STANDARD_VORLAGE, VERBOTENE_ZEICHEN,
                           nach_vorlage, vorlage_pruefen)
from ..db import get_session
from ..models import Einstellung, Objekt
from ..nextcloud import Nextcloud, NextcloudFehler

log = logging.getLogger("immocalc")
router = APIRouter(prefix="/api/nextcloud", tags=["nextcloud"])

# Vereinheitlichte Struktur je Immobilie — Zehnerschritte lassen Platz zum
# Einfuegen, die Nummern folgen dem gewachsenen Bestand.
STRUKTUR = [
    "01_Allgemein_Hauskonto",
    "10_Fotos_Lage",
    "20_Mietvertraege_Vermietung",
    "30_Kommunikation",
    "40_Kauf_Eigentum_Finanzierung",
    "50_Bauphase_Projekte",
    "60_Nebenkosten",
    "70_Steuer_Finanzamt",
    "80_Hausverwaltung",
    "98_Archiv",
    "99_Sonstiges",
]

S_URL, S_BENUTZER, S_PASSWORT, S_HOME, S_TLS, S_VORLAGE = (
    "nc_url", "nc_benutzer", "nc_passwort", "nc_home", "nc_tls_pruefen",
    "nc_ordner_vorlage")


def ordner_fuer(session: Session, objekt: Objekt) -> str:
    """Ordnername nach der eingestellten Vorlage."""
    return nach_vorlage(
        _lies(session, S_VORLAGE) or STANDARD_VORLAGE,
        ort=objekt.ort, strasse=objekt.strasse, name=objekt.name,
        plz=objekt.plz, typ=objekt.typ, nutzung=objekt.nutzung)


def _lies(session: Session, schluessel: str, vorgabe: str = "") -> str:
    eintrag = session.get(Einstellung, schluessel)
    return eintrag.wert if eintrag else vorgabe


def _schreib(session: Session, schluessel: str, wert: str) -> None:
    eintrag = session.get(Einstellung, schluessel)
    if eintrag:
        eintrag.wert = wert
    else:
        eintrag = Einstellung(schluessel=schluessel, wert=wert)
    session.add(eintrag)


def verbindung(session: Session) -> Nextcloud:
    url = _lies(session, S_URL)
    benutzer = _lies(session, S_BENUTZER)
    passwort = _lies(session, S_PASSWORT)
    if not (url and benutzer and passwort):
        raise HTTPException(400, "Nextcloud ist noch nicht eingerichtet")
    return Nextcloud(url, benutzer, passwort,
                     zertifikat_pruefen=_lies(session, S_TLS) == "1")


class VerbindungIn(BaseModel):
    url: str
    benutzer: str
    passwort: str
    tls_pruefen: bool = False


@router.get("/status")
def status(session: Session = Depends(get_session)) -> dict:
    """Zustand der Verbindung — ohne das Passwort preiszugeben."""
    url, benutzer = _lies(session, S_URL), _lies(session, S_BENUTZER)
    passwort = _lies(session, S_PASSWORT)
    return {
        "eingerichtet": bool(url and benutzer and passwort),
        "url": url,
        "benutzer": benutzer,
        "passwort": "•••• gespeichert" if passwort else "",
        "home": _lies(session, S_HOME),
        "tls_pruefen": _lies(session, S_TLS) == "1",
        "struktur": STRUKTUR,
    }


@router.post("/verbindung")
def verbindung_speichern(data: VerbindungIn,
                         session: Session = Depends(get_session)) -> dict:
    """Prüft die Zugangsdaten und speichert sie erst bei Erfolg."""
    client = Nextcloud(data.url, data.benutzer, data.passwort,
                       zertifikat_pruefen=data.tls_pruefen)
    try:
        ergebnis = client.pruefe()
    except NextcloudFehler as e:
        raise HTTPException(400, str(e)) from e

    _schreib(session, S_URL, data.url.rstrip("/"))
    _schreib(session, S_BENUTZER, data.benutzer)
    _schreib(session, S_PASSWORT, data.passwort)
    _schreib(session, S_TLS, "1" if data.tls_pruefen else "0")
    session.commit()
    log.info("Nextcloud verbunden als %s", data.benutzer)
    return ergebnis


@router.get("/ordner")
def ordner(pfad: str = Query(default=""),
           session: Session = Depends(get_session)) -> dict:
    """Unterordner eines Pfades — Grundlage für die Ordnerauswahl."""
    client = verbindung(session)
    try:
        eintraege = client.liste(pfad)
    except NextcloudFehler as e:
        raise HTTPException(400, str(e)) from e
    hoch = "/".join(pfad.strip("/").split("/")[:-1]) if pfad.strip("/") else None
    return {
        "pfad": "/" + pfad.strip("/") if pfad.strip("/") else "",
        "hoch": hoch,
        "ordner": [{"name": e.name, "pfad": e.pfad}
                   for e in eintraege if e.ordner],
        "dateien": sum(1 for e in eintraege if not e.ordner),
    }


class HomeIn(BaseModel):
    pfad: str


@router.post("/home")
def home_speichern(data: HomeIn, session: Session = Depends(get_session)) -> dict:
    """Legt den Ordner fest, unter dem alle Immobilien angelegt werden."""
    client = verbindung(session)
    try:
        client.liste(data.pfad)          # muss existieren
    except NextcloudFehler as e:
        raise HTTPException(400, str(e)) from e
    _schreib(session, S_HOME, "/" + data.pfad.strip("/"))
    session.commit()
    return {"home": "/" + data.pfad.strip("/")}


class VorlageIn(BaseModel):
    vorlage: str


@router.get("/vorlage")
def vorlage_lesen(session: Session = Depends(get_session)) -> dict:
    """Aktuelle Namensvorlage mit Beispielen aus den echten Objekten."""
    vorlage = _lies(session, S_VORLAGE) or STANDARD_VORLAGE
    objekte = session.exec(select(Objekt)).all()[:4]
    return {
        "vorlage": vorlage,
        "standard": STANDARD_VORLAGE,
        "platzhalter": list(PLATZHALTER),
        "verboten": VERBOTENE_ZEICHEN,
        "beispiele": [{"objekt": o.name,
                       "ordner": nach_vorlage(vorlage, ort=o.ort, strasse=o.strasse,
                                              name=o.name, plz=o.plz, typ=o.typ,
                                              nutzung=o.nutzung)}
                      for o in objekte],
    }


@router.post("/vorlage")
def vorlage_speichern(data: VorlageIn,
                      session: Session = Depends(get_session)) -> dict:
    """Speichert die Vorlage. Bereits angelegte Ordner bleiben, wie sie sind."""
    hinweise = vorlage_pruefen(data.vorlage)
    if any("keinen Platzhalter" in h or "leer" in h for h in hinweise):
        raise HTTPException(400, " ".join(hinweise))
    _schreib(session, S_VORLAGE, data.vorlage.strip())
    session.commit()
    return {"vorlage": data.vorlage.strip(), "hinweise": hinweise}


@router.get("/objekte/{slug}/status")
def objekt_status(slug: str, session: Session = Depends(get_session)) -> dict:
    """Ist dieses Objekt schon mit einem Ordner verknüpft? Was fehlt noch?"""
    objekt = session.exec(select(Objekt).where(Objekt.slug == slug)).first()
    if not objekt:
        raise HTTPException(404, "Objekt nicht gefunden")
    home = _lies(session, S_HOME)
    verbunden = bool(_lies(session, S_URL) and _lies(session, S_PASSWORT))
    return {
        "cloud_verbunden": verbunden,
        "home": home,
        "ordner": objekt.nc_ordner,
        "bereit": bool(verbunden and home),
        "angelegt": bool(objekt.nc_ordner),
        "vorschlag": f"{home.strip('/')}/"
                     f"{ordner_fuer(session, objekt)}"
                     if home else "",
        "struktur": STRUKTUR,
    }


@router.post("/objekte/{slug}/struktur")
def struktur_anlegen(slug: str, session: Session = Depends(get_session)) -> dict:
    """Legt Objektordner samt Unterstruktur unter dem Home-Ordner an.
    Bestehende Ordner und Dateien bleiben unberührt."""
    home = _lies(session, S_HOME)
    if not home:
        raise HTTPException(400, "Kein Home-Ordner gewählt")
    objekt = session.exec(select(Objekt).where(Objekt.slug == slug)).first()
    if not objekt:
        raise HTTPException(404, "Objekt nicht gefunden")

    # Sprechender Ordnername statt "Wohnung 1.OG" — sonst kollidieren
    # gleichnamige Einheiten verschiedener Adressen.
    if objekt.nc_ordner:
        ziel = objekt.nc_ordner.strip("/")
    else:
        ziel = f"{home.strip('/')}/" \
               f"{ordner_fuer(session, objekt)}"
    client = verbindung(session)
    try:
        neu = client.ordner_baum_anlegen(ziel, STRUKTUR)
    except NextcloudFehler as e:
        raise HTTPException(400, str(e)) from e

    objekt.nc_ordner = "/" + ziel.strip("/")
    session.add(objekt)
    session.commit()
    return {"ordner": objekt.nc_ordner, "neu_angelegt": neu,
            "unveraendert": len(STRUKTUR) + 1 - len(neu)}
