"""N474 — Backups: Einstellungen, Liste, Sichern, Herunterladen, Einspielen
(je Familie) — und der Instanz-Weg für die frische Installation.

Zwei Router: `router` (mit Anmeldung, wie alles andere) und `offen` (ohne):
`offen` ist der einzige Weg, eine komplett neue Installation aus einem
Instanz-Schnappschuss zurückzuholen — und er funktioniert AUSSCHLIESSLICH,
solange noch keine Familie ein Passwort gesetzt hat. Eine beanspruchte
Instanz kann niemand von aussen überschreiben; zurückrollen heisst dort:
Datenbankdatei löschen, neu starten, dann ist der Weg wieder offen."""
from __future__ import annotations

import logging
import os
from datetime import datetime

from fastapi import (APIRouter, Depends, File, Form, HTTPException, Response,
                     UploadFile)
from pydantic import BaseModel
from sqlmodel import Session, select

from .. import backup, cloudkern, db, upload
from ..auth import passwort_pruefen
from ..db import get_session
from ..deps import aktuelle_familie
from ..export import (exportiere_familie, familie_ist_leer,
                      importiere_familie)
from ..migrate import migriere
from ..models import Backup, Familie
from ..nextcloud import Nextcloud, NextcloudFehler
from ..objekt.stammdaten import _freier_slug

log = logging.getLogger("immocalc")
router = APIRouter(prefix="/api/backup", tags=["backup"])
offen = APIRouter(prefix="/api/backup/instanz", tags=["backup"])

RHYTHMEN = ("", "taeglich", "woechentlich")
ZIELE = ("", "nextcloud", "webdav")
ARCHIV_MAX_BYTES = 200 * 1024 * 1024


def _dazu(neu: dict, alt: dict | None) -> dict:
    """„Wie viel ist dazugekommen" — der Vergleich mit dem vorigen Eintrag."""
    if not alt:
        return {}
    return {k: neu.get(k, 0) - alt.get(k, 0)
            for k in ("objekte", "zeitraeume", "belege", "kontakte")
            if neu.get(k, 0) != alt.get(k, 0)}


def _liste(session: Session, familie: Familie) -> list[dict]:
    zeilen = session.exec(select(Backup).where(
        Backup.familie_id == familie.id).order_by(Backup.zeitpunkt)).all()
    liste: list[dict] = []
    vorher: dict | None = None
    for z in zeilen:
        liste.append({
            "id": z.id, "zeitpunkt": z.zeitpunkt.isoformat(timespec="minutes"),
            "dateiname": z.dateiname, "groesse": z.groesse, "ziel": z.ziel,
            "ausloeser": z.ausloeser, "zusammenfassung": z.zusammenfassung or {},
            "dazu": _dazu(z.zusammenfassung or {}, vorher),
        })
        vorher = z.zusammenfassung or {}
    liste.reverse()
    return liste


def _instanz_stand() -> dict:
    dateien = backup.instanz_liste() if backup.instanz_eingerichtet() else []
    return {"eingerichtet": backup.instanz_eingerichtet(),
            "anzahl": len(dateien),
            "letzte": dateien[0] if dateien else None}


@router.get("/einstellungen")
def einstellungen(session: Session = Depends(get_session),
                  familie: Familie = Depends(aktuelle_familie)) -> dict:
    return {
        "rhythmus": familie.backup_rhythmus,
        "ziel": familie.backup_ziel,
        "webdav_url": familie.backup_webdav_url,
        "webdav_benutzer": familie.backup_webdav_benutzer,
        "hat_passwort": bool(familie.backup_schluessel),
        "hat_webdav_passwort": bool(familie.backup_webdav_passwort),
        "nextcloud_moeglich": bool(cloudkern._lies(session, cloudkern.S_HOME)),
        "letzte_pruefung": (familie.backup_letzte_pruefung.isoformat(timespec="minutes")
                            if familie.backup_letzte_pruefung else None),
        "nacht_von": backup.NACHT_VON,
        "nacht_bis": backup.NACHT_BIS,
        "backups": _liste(session, familie),
        "instanz": _instanz_stand(),
    }


class EinstellungenIn(BaseModel):
    login_passwort: str
    backup_passwort: str | None = None       # None = unverändert lassen
    rhythmus: str = ""
    ziel: str = ""
    webdav_url: str = ""
    webdav_benutzer: str = ""
    webdav_passwort: str | None = None       # None = unverändert lassen


def _login_bestaetigen(familie: Familie, passwort: str) -> None:
    """Wie bei 2FA/Passwort ändern: eine offen gelassene Sitzung darf das
    Backup-Ziel nicht auf eigene Faust umbiegen — das wäre der Weg, alle
    Daten (verschlüsselt, aber mit selbst gesetztem Passwort) abzuziehen."""
    if familie.passwort_hash is None or not passwort_pruefen(
            passwort, familie.passwort_hash, familie.passwort_salz):
        raise HTTPException(403, "Das Passwort der Familie stimmt nicht.")


@router.put("/einstellungen")
def einstellungen_setzen(daten: EinstellungenIn,
                         session: Session = Depends(get_session),
                         familie: Familie = Depends(aktuelle_familie)) -> dict:
    _login_bestaetigen(familie, daten.login_passwort)
    if daten.rhythmus not in RHYTHMEN or daten.ziel not in ZIELE:
        raise HTTPException(400, "Unbekannter Rhythmus oder unbekanntes Ziel.")

    if daten.backup_passwort is not None:
        if len(daten.backup_passwort) < 12:
            raise HTTPException(400, "Das Backup-Passwort braucht mindestens 12 Zeichen.")
        salz = backup.neues_salz()
        familie.backup_salz = salz.hex()
        familie.backup_schluessel = backup.schluessel_ableiten(
            daten.backup_passwort, salz).hex()
        # Ein neues Passwort heisst ein neuer Schlüssel — der Fingerabdruck
        # gilt weiter (die Daten sind dieselben), das nächste Archiv wird nur
        # mit dem neuen Schlüssel geschrieben.
    if (daten.rhythmus or daten.ziel) and not familie.backup_schluessel:
        raise HTTPException(400, "Zuerst ein Backup-Passwort setzen.")

    if daten.ziel == "webdav":
        url = daten.webdav_url.strip()
        benutzer = daten.webdav_benutzer.strip()
        passwort = (daten.webdav_passwort if daten.webdav_passwort is not None
                    else familie.backup_webdav_passwort)
        if not (url and benutzer and passwort):
            raise HTTPException(400, "WebDAV braucht Adresse, Benutzer und App-Passwort.")
        client = Nextcloud.webdav(url, benutzer, passwort, heimat="/ImmoCalc-Backups")
        try:
            client.pruefe()
            client.ordner_anlegen("ImmoCalc-Backups")
        except NextcloudFehler as fehler:
            raise HTTPException(400, f"WebDAV-Speicher antwortet nicht: {fehler}") from fehler
        familie.backup_webdav_url = url
        familie.backup_webdav_benutzer = benutzer
        familie.backup_webdav_passwort = passwort
    elif daten.ziel == "nextcloud":
        if not cloudkern._lies(session, cloudkern.S_HOME):
            raise HTTPException(400, "Erst die Nextcloud samt Home-Ordner einrichten.")

    familie.backup_rhythmus = daten.rhythmus
    familie.backup_ziel = daten.ziel
    session.add(familie)
    session.commit()
    log.info("Backup-Einstellungen geändert für Familie %s (%s, %s)",
             familie.name, daten.rhythmus or "aus", daten.ziel or "kein Ziel")
    return einstellungen(session, familie)


@router.post("/jetzt")
def jetzt_sichern(session: Session = Depends(get_session),
                  familie: Familie = Depends(aktuelle_familie)) -> dict:
    """Von Hand: immer, auch ohne Änderung — wer drückt, will ein Archiv."""
    try:
        eintrag = backup.familie_sichern(session, familie, ausloeser="hand",
                                         nur_bei_aenderung=False)
    except backup.BackupFehler as fehler:
        raise HTTPException(409, str(fehler)) from fehler
    return eintrag or {}


@router.get("/herunterladen")
def herunterladen(session: Session = Depends(get_session),
                  familie: Familie = Depends(aktuelle_familie)) -> Response:
    """Das Archiv als Datei — für Familien ohne Ziel, oder als Kopie in die
    eigene Hand. Zählt in der Liste wie jede andere Sicherung."""
    if not familie.backup_schluessel or not familie.backup_salz:
        raise HTTPException(409, "Zuerst ein Backup-Passwort setzen.")
    daten = exportiere_familie(session, familie)
    archiv = backup.familie_archiv(daten, bytes.fromhex(familie.backup_schluessel),
                                   bytes.fromhex(familie.backup_salz))
    name = backup.dateiname_familie(familie.name)
    familie.backup_fingerabdruck = backup.fingerabdruck(daten)
    session.add(familie)
    session.add(Backup(familie_id=familie.id, art="familie", dateiname=name,
                       groesse=len(archiv), ziel="download", ausloeser="hand",
                       zusammenfassung=daten.get("zusammenfassung") or {}))
    session.commit()
    return Response(content=archiv, media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


def _einspielen(session: Session, familie: Familie, archiv: bytes,
                passwort: str) -> dict:
    if len(archiv) > ARCHIV_MAX_BYTES:
        raise HTTPException(400, "Die Datei ist zu gross.")
    try:
        daten = backup.familie_aus_archiv(archiv, passwort)
    except backup.BackupFehler as fehler:
        raise HTTPException(400, str(fehler)) from fehler
    try:
        ergebnis = importiere_familie(
            session, daten, familie,
            lambda s, n: _freier_slug(s, n, familie.id))
    except ValueError as fehler:
        raise HTTPException(409, str(fehler)) from fehler
    return ergebnis


@router.post("/einspielen")
async def einspielen(passwort: str = Form(...), datei: UploadFile = File(...),
                     session: Session = Depends(get_session),
                     familie: Familie = Depends(aktuelle_familie)) -> dict:
    archiv = await upload.lies(datei, max_bytes=ARCHIV_MAX_BYTES,
                               endungen=(".enc",), was="Die Sicherung")
    return _einspielen(session, familie, archiv, passwort)


def _ziel_client(session: Session, familie: Familie) -> tuple[Nextcloud, str]:
    if familie.backup_ziel == "nextcloud":
        client = cloudkern.verbindung(session)
        if not client.heimat:
            raise HTTPException(400, "In der Nextcloud ist noch kein Home-Ordner gewählt.")
        return client, f"{client.heimat.strip('/')}/_Backups"
    if familie.backup_ziel == "webdav":
        return (Nextcloud.webdav(familie.backup_webdav_url, familie.backup_webdav_benutzer,
                                 familie.backup_webdav_passwort, heimat="/ImmoCalc-Backups"),
                "ImmoCalc-Backups")
    raise HTTPException(409, "Es ist kein Ziel gewählt.")


@router.post("/dateien-zurueckholen")
def dateien_zurueckholen(daten: AusSpeicherIn,
                         session: Session = Depends(get_session),
                         familie: Familie = Depends(aktuelle_familie)) -> dict:
    """N478 — die gesicherten Belege zurück in die Nextcloud legen, nachdem
    eine Familien-Sicherung eingespielt wurde. `pfad` wird hier nicht
    gebraucht (die Pfade stehen in den Dokumenten), nur das Backup-Passwort
    — dasselbe Feld, damit der Dialog derselbe bleibt."""
    client, ordner = _ziel_client(session, familie)
    quelle = cloudkern.verbindung(session)
    if not quelle.heimat:
        raise HTTPException(400, "In der Nextcloud ist noch kein Home-Ordner gewählt.")
    return backup.dateien_zurueckholen(session, familie, quelle, client,
                                       ordner, daten.passwort)


@router.get("/im-speicher")
def im_speicher(session: Session = Depends(get_session),
                familie: Familie = Depends(aktuelle_familie)) -> list[dict]:
    """Was im Ziel liegt — auch Archive, die eine frühere Instanz dort
    abgelegt hat und die in der eigenen Liste hier nicht stehen."""
    client, ordner = _ziel_client(session, familie)
    try:
        eintraege = client.liste(ordner)
    except NextcloudFehler:
        return []
    return sorted(
        [{"dateiname": e.name, "groesse": e.groesse, "pfad": e.pfad}
         for e in eintraege if not e.ordner and e.name.endswith(".json.gz.enc")],
        key=lambda e: e["dateiname"], reverse=True)


class AusSpeicherIn(BaseModel):
    pfad: str
    passwort: str


@router.post("/aus-speicher")
def aus_speicher(daten: AusSpeicherIn, session: Session = Depends(get_session),
                 familie: Familie = Depends(aktuelle_familie)) -> dict:
    client, ordner = _ziel_client(session, familie)
    erlaubt = "/" + ordner.strip("/") + "/"
    if not ("/" + daten.pfad.strip("/")).startswith(erlaubt) or "/../" in daten.pfad:
        raise HTTPException(400, "Nur Archive aus dem Backup-Ordner.")
    try:
        archiv, _typ = client.hole(daten.pfad)
    except NextcloudFehler as fehler:
        raise HTTPException(400, str(fehler)) from fehler
    return _einspielen(session, familie, archiv, daten.passwort)


# ---- Instanz: nur auf einer unbeanspruchten Installation ----------------------

def _beansprucht(session: Session) -> bool:
    return session.exec(select(Familie).where(
        Familie.passwort_hash.is_not(None))).first() is not None


@offen.get("/zustand")
def instanz_zustand(session: Session = Depends(get_session)) -> dict:
    moeglich = not _beansprucht(session) and backup.instanz_eingerichtet()
    return {"moeglich": moeglich,
            "dateien": backup.instanz_liste() if moeglich else []}


@offen.post("/wiederherstellen")
async def instanz_wiederherstellen(
        passwort: str = Form(...), dateiname: str | None = Form(None),
        datei: UploadFile | None = File(None),
        session: Session = Depends(get_session)) -> dict:
    if _beansprucht(session):
        raise HTTPException(409, "Diese Installation ist schon in Benutzung — "
                                 "wiederherstellen geht nur auf einer frischen.")
    if datei is not None:
        archiv = await upload.lies(datei, max_bytes=ARCHIV_MAX_BYTES,
                                   endungen=(".enc",), was="Die Sicherung")
    elif dateiname:
        if os.sep in dateiname or dateiname.startswith("."):
            raise HTTPException(400, "Ungültiger Dateiname.")
        pfad = os.path.join(backup.instanz_ordner(), dateiname)
        if not os.path.isfile(pfad):
            raise HTTPException(404, "Diese Sicherung gibt es nicht.")
        with open(pfad, "rb") as quelle:
            archiv = quelle.read()
    else:
        raise HTTPException(400, "Bitte eine Sicherung wählen oder hochladen.")
    if len(archiv) > ARCHIV_MAX_BYTES:
        raise HTTPException(400, "Die Datei ist zu gross.")
    session.close()
    # `db.engine` zur Laufzeit nachschlagen, nicht beim Import binden: der
    # Pfad gehört zu der Engine, die gerade läuft (siehe backup.nachtlauf).
    try:
        backup.instanz_wiederherstellen(archiv, passwort, db.engine.url.database)
    except backup.BackupFehler as fehler:
        raise HTTPException(400, str(fehler)) from fehler
    # Keine Verbindung darf mehr an der alten Datei hängen; danach die
    # additiven Migrationen, falls die Sicherung von einem älteren Stand ist.
    db.engine.dispose()
    migriere(db.engine)
    with Session(db.engine) as frisch:
        familien = frisch.exec(select(Familie)).all()
    log.info("Instanz aus %s wiederhergestellt: %d Familien",
             dateiname or "Upload", len(familien))
    return {"wiederhergestellt": True, "familien": len(familien),
            "zeitpunkt": datetime.now().isoformat(timespec="minutes")}
