"""N474 — Sicherung und Wiederherstellung: Archivformat, Verschlüsselung,
Instanz-Schnappschuss, nächtlicher Lauf.

Zwei Ebenen, weil sie zwei verschiedene Fragen beantworten:

* **Instanz** (Betreiber): die komplette SQLite-Datei als Schnappschuss —
  „die App ist kaputt, ich setze sie neu auf". Ein Archiv, alles ist exakt
  wie vorher, alle Familien, Konten, 2FA-Geheimnisse.
* **Familie** (jeder Nutzer): nur die eigenen Daten als JSON — „ich will
  meine Daten selbst in der Hand haben". Geht in die eigene Nextcloud oder
  einen WebDAV-Speicher (Koofr o. ä.) und funktioniert auch dann, wenn das
  Instanz-Backup weg wäre.

`cryptography` ist die eine Abhängigkeit, die sich nicht vermeiden liess:
Python bringt Hashing und HMAC mit (`auth.py`, `totp.py`), aber keinen
einzigen Cipher — und einen Cipher baut man nicht selbst. AES-256-GCM ist
authentifiziert: ein falsches Passwort oder ein verändertes Byte fällt beim
Entschlüsseln auf, statt Datenmüll zu liefern. Der Schlüssel kommt per
scrypt aus dem Backup-Passwort, wie beim Login.

Archivformat — selbstbeschreibend, damit sich ein Archiv auf jeder frischen
Instanz allein mit dem Passwort öffnen lässt:

    MAGIC (16) | SALZ (16) | NONCE (12) | AES-GCM( gzip(inhalt) )

Weil das Archiv VOR dem Upload verschlüsselt wird, sieht der Anbieter nur
einen undurchsichtigen Blob — Vertrauen in ihn ist keine Voraussetzung."""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import re
import secrets
import sqlite3
import tempfile
from datetime import datetime, timedelta

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

log = logging.getLogger("immocalc")

MAGIC = b"IMMOCALC-BACKUP1"
_SALZ_LAENGE = 16
_NONCE_LAENGE = 12
_KOPF_LAENGE = len(MAGIC) + _SALZ_LAENGE + _NONCE_LAENGE
_SQLITE_KOPF = b"SQLite format 3\x00"

# Dieselben scrypt-Parameter wie beim Login (auth.py) — ein Backup-Passwort
# wird genauso von Menschen gewählt und genauso angegriffen.
_SCRYPT_N = 2 ** 14
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCHLUESSEL_LAENGE = 32              # AES-256

# Das nächtliche Fenster: wer tagsüber gearbeitet hat, ist um diese Zeit
# fertig — dann wird gesichert, und nur, wenn sich etwas geändert hat.
NACHT_VON = 2
NACHT_BIS = 5

# Instanz-Schnappschüsse im lokalen Ordner: 30 Tage lückenlos, danach je
# Monat der erste Stand, ein Jahr lang. Bewusst nur HIER ein Aufräumen: die
# Familien-Archive in Nextcloud/WebDAV gehören dem Nutzer, „nie löschen"
# gilt dort weiter — durch „nur bei Änderung" bleiben sie ohnehin wenige.
_TAGE_LUECKENLOS = 30
_TAGE_MONATSSTAND = 400


class BackupFehler(ValueError):
    """Mit einem Satz für den Nutzer."""


# ---- Verschlüsselung --------------------------------------------------------

def neues_salz() -> bytes:
    return secrets.token_bytes(_SALZ_LAENGE)


def schluessel_ableiten(passwort: str, salz: bytes) -> bytes:
    return hashlib.scrypt(passwort.encode("utf-8"), salt=salz, n=_SCRYPT_N,
                          r=_SCRYPT_R, p=_SCRYPT_P, dklen=_SCHLUESSEL_LAENGE)


def verschluesseln(inhalt: bytes, schluessel: bytes, salz: bytes) -> bytes:
    """Ein Archiv aus rohem Inhalt. `salz` wandert mit in den Kopf — wer das
    Passwort kennt, kann den Schlüssel daraus überall neu ableiten."""
    nonce = secrets.token_bytes(_NONCE_LAENGE)
    gepackt = gzip.compress(inhalt, compresslevel=6)
    return MAGIC + salz + nonce + AESGCM(schluessel).encrypt(nonce, gepackt, MAGIC)


def entschluesseln(archiv: bytes, passwort: str) -> bytes:
    if len(archiv) < _KOPF_LAENGE + 16 or archiv[:len(MAGIC)] != MAGIC:
        raise BackupFehler("Das ist keine ImmoCalc-Sicherung.")
    salz = archiv[len(MAGIC):len(MAGIC) + _SALZ_LAENGE]
    nonce = archiv[len(MAGIC) + _SALZ_LAENGE:_KOPF_LAENGE]
    try:
        gepackt = AESGCM(schluessel_ableiten(passwort, salz)).decrypt(
            nonce, archiv[_KOPF_LAENGE:], MAGIC)
    except InvalidTag as fehler:
        raise BackupFehler("Falsches Backup-Passwort — oder die Datei ist "
                           "beschädigt.") from fehler
    try:
        return gzip.decompress(gepackt)
    except (OSError, EOFError) as fehler:
        raise BackupFehler("Die Sicherung lässt sich nicht entpacken.") from fehler


# ---- Familien-Archiv ---------------------------------------------------------

FAMILIEN_FORMAT = "immocalc-familie/1"


def fingerabdruck(daten: dict) -> str:
    """Was sich zwischen zwei Nächten geändert hat, entscheidet ein Hash über
    den Export — ohne den Zeitstempel, sonst wäre jede Nacht „geändert"."""
    ohne_zeit = {k: v for k, v in daten.items() if k != "erstellt"}
    return hashlib.sha256(json.dumps(
        ohne_zeit, sort_keys=True, ensure_ascii=False, default=str
    ).encode("utf-8")).hexdigest()


def familie_archiv(daten: dict, schluessel: bytes, salz: bytes) -> bytes:
    return verschluesseln(json.dumps(daten, ensure_ascii=False).encode("utf-8"),
                          schluessel, salz)


def familie_aus_archiv(archiv: bytes, passwort: str) -> dict:
    inhalt = entschluesseln(archiv, passwort)
    if inhalt.startswith(_SQLITE_KOPF):
        raise BackupFehler("Das ist eine Instanz-Sicherung, keine Familien-"
                           "Sicherung — die gehört auf die Anmeldeseite einer "
                           "frischen Instanz.")
    try:
        daten = json.loads(inhalt)
    except (ValueError, UnicodeDecodeError) as fehler:
        raise BackupFehler("Die Sicherung enthält keine lesbaren Daten.") from fehler
    if not isinstance(daten, dict) or daten.get("format") != FAMILIEN_FORMAT:
        raise BackupFehler("Das ist keine Familien-Sicherung von ImmoCalc.")
    return daten


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "familie").lower()).strip("-") or "familie"


def dateiname_familie(familienname: str, jetzt: datetime | None = None) -> str:
    return f"immocalc-{_slug(familienname)}-{(jetzt or datetime.now()):%Y%m%d-%H%M%S}.json.gz.enc"


def faellig(rhythmus: str, letzte_pruefung: datetime | None,
            jetzt: datetime | None = None) -> bool:
    """Ist im nächtlichen Fenster eine Prüfung dran? „Geprüft" heisst: der
    Export wurde mit dem letzten Fingerabdruck verglichen — gesichert wird nur
    bei Änderung. Einmal je Nacht, damit der Takt (alle 15 Minuten) nicht
    fünfmal hintereinander exportiert."""
    jetzt = jetzt or datetime.now()
    if rhythmus not in ("taeglich", "woechentlich"):
        return False
    if not NACHT_VON <= jetzt.hour < NACHT_BIS:
        return False
    if letzte_pruefung is not None and letzte_pruefung.date() == jetzt.date():
        return False
    if rhythmus == "woechentlich" and jetzt.weekday() != 6:     # Sonntagnacht
        return False
    return True


# ---- Instanz-Schnappschuss ---------------------------------------------------

def instanz_ordner() -> str:
    return os.environ.get("BACKUP_ORDNER", "/backups")


def instanz_passwort() -> str:
    """Aus der Server-Umgebungsdatei (wie der KI-Schlüssel), nie aus der
    Datenbank — sonst läge der Schlüssel neben dem, was er schützt."""
    return os.environ.get("BACKUP_PASSWORT", "").strip()


def instanz_eingerichtet() -> bool:
    return bool(instanz_passwort()) and os.path.isdir(instanz_ordner())


def schnappschuss(db_pfad: str) -> bytes:
    """Konsistente Kopie im laufenden Betrieb über SQLites Backup-API — kein
    blosses Kopieren der Datei, das könnte mitten in einer Transaktion
    erwischt werden."""
    with tempfile.TemporaryDirectory() as tmp:
        ziel = os.path.join(tmp, "schnappschuss.db")
        quelle = sqlite3.connect(db_pfad)
        kopie = sqlite3.connect(ziel)
        try:
            quelle.backup(kopie)
        finally:
            kopie.close()
            quelle.close()
        with open(ziel, "rb") as datei:
            return datei.read()


def dateiname_instanz(jetzt: datetime | None = None) -> str:
    return f"immocalc-{(jetzt or datetime.now()):%Y%m%d-%H%M%S}.db.gz.enc"


_INSTANZ_MUSTER = re.compile(r"^immocalc-(\d{8})-(\d{6})\.db\.gz\.enc$")


def instanz_sichern(db_pfad: str, ordner: str | None = None,
                    passwort: str | None = None) -> dict:
    ordner = ordner or instanz_ordner()
    passwort = instanz_passwort() if passwort is None else passwort
    if not passwort:
        raise BackupFehler("BACKUP_PASSWORT ist nicht gesetzt.")
    if not os.path.isdir(ordner):
        raise BackupFehler(f"Backup-Ordner fehlt: {ordner}")
    salz = neues_salz()
    archiv = verschluesseln(schnappschuss(db_pfad),
                            schluessel_ableiten(passwort, salz), salz)
    name = dateiname_instanz()
    pfad = os.path.join(ordner, name)
    # Erst vollständig schreiben, dann umbenennen — ein halb geschriebenes
    # Archiv darf nie unter dem endgültigen Namen liegen.
    with open(pfad + ".teil", "wb") as datei:
        datei.write(archiv)
    os.replace(pfad + ".teil", pfad)
    return {"dateiname": name, "groesse": len(archiv), "pfad": pfad}


def _zeitpunkt_aus_name(name: str) -> datetime | None:
    treffer = _INSTANZ_MUSTER.match(name)
    if not treffer:
        return None
    try:
        return datetime.strptime(treffer.group(1) + treffer.group(2), "%Y%m%d%H%M%S")
    except ValueError:
        return None


def instanz_liste(ordner: str | None = None) -> list[dict]:
    ordner = ordner or instanz_ordner()
    if not os.path.isdir(ordner):
        return []
    eintraege = []
    for name in os.listdir(ordner):
        zeitpunkt = _zeitpunkt_aus_name(name)
        if zeitpunkt is None:
            continue
        eintraege.append({
            "dateiname": name,
            "groesse": os.path.getsize(os.path.join(ordner, name)),
            "zeitpunkt": zeitpunkt.isoformat(timespec="minutes"),
        })
    return sorted(eintraege, key=lambda e: e["dateiname"], reverse=True)


def instanz_aufraeumen(ordner: str | None = None,
                       jetzt: datetime | None = None) -> list[str]:
    """Siehe `_TAGE_LUECKENLOS`/`_TAGE_MONATSSTAND`. Der jeweils erste Stand
    eines Monats bleibt ein Jahr lang stehen, alles andere 30 Tage."""
    ordner = ordner or instanz_ordner()
    jetzt = jetzt or datetime.now()
    entfernt: list[str] = []
    monats_erster: dict[str, str] = {}
    alle = sorted(instanz_liste(ordner), key=lambda e: e["dateiname"])
    for e in alle:
        monat = e["dateiname"][9:15]
        monats_erster.setdefault(monat, e["dateiname"])
    for e in alle:
        alter = jetzt - _zeitpunkt_aus_name(e["dateiname"])
        if alter <= timedelta(days=_TAGE_LUECKENLOS):
            continue
        ist_monatsstand = monats_erster.get(e["dateiname"][9:15]) == e["dateiname"]
        if ist_monatsstand and alter <= timedelta(days=_TAGE_MONATSSTAND):
            continue
        os.remove(os.path.join(ordner, e["dateiname"]))
        entfernt.append(e["dateiname"])
    return entfernt


def instanz_heute_schon(ordner: str | None = None,
                        jetzt: datetime | None = None) -> bool:
    jetzt = jetzt or datetime.now()
    liste = instanz_liste(ordner)
    return bool(liste) and liste[0]["dateiname"][9:17] == jetzt.strftime("%Y%m%d")


def instanz_wiederherstellen(archiv: bytes, passwort: str, db_pfad: str) -> None:
    """Ersetzt die Datenbankdatei durch die aus dem Archiv. Der Aufrufer
    muss danach die Engine verwerfen (`engine.dispose()`), damit keine
    Verbindung mehr an der alten Datei hängt, und `migriere()` laufen lassen."""
    inhalt = entschluesseln(archiv, passwort)
    if not inhalt.startswith(_SQLITE_KOPF):
        raise BackupFehler("Das Archiv enthält keine Datenbank — vermutlich "
                           "eine Familien-Sicherung. Die gehört in die "
                           "Einstellungen unter Backups → Einspielen.")
    # Vor dem Ersetzen prüfen, dass SQLite die Datei überhaupt für gesund hält.
    with tempfile.TemporaryDirectory() as tmp:
        probe = os.path.join(tmp, "probe.db")
        with open(probe, "wb") as datei:
            datei.write(inhalt)
        verbindung = sqlite3.connect(probe)
        try:
            ergebnis = verbindung.execute("PRAGMA integrity_check").fetchone()
        finally:
            verbindung.close()
        if not ergebnis or ergebnis[0] != "ok":
            raise BackupFehler("Die Datenbank in der Sicherung ist beschädigt.")
    # Reste einer früheren Sitzung (WAL/Journal) gehören zur ALTEN Datei und
    # würden SQLite auf die neue anwenden.
    for anhang in ("-wal", "-shm", "-journal"):
        try:
            os.remove(db_pfad + anhang)
        except FileNotFoundError:
            pass
    with open(db_pfad + ".neu", "wb") as datei:
        datei.write(inhalt)
    os.replace(db_pfad + ".neu", db_pfad)
    log.info("Datenbank aus Sicherung wiederhergestellt (%d Bytes)", len(inhalt))


# ---- Nächtlicher Lauf ---------------------------------------------------------

# ---- Dateien: inhaltsadressiert, inkrementell --------------------------------

DATEI_ORDNER = "dateien"
# Grösse, ab der eine einzelne Datei übersprungen wird. Ein Beleg ist ein
# PDF oder ein Foto; was deutlich grösser ist, ist kein Beleg mehr und würde
# nur den Speicher des Nutzers füllen.
DATEI_MAX_BYTES = 80 * 1024 * 1024


def _datei_ziel(ordner: str, sha1: str) -> str:
    """`dateien/ab/abcdef….enc` — zwei Ebenen, damit kein Verzeichnis mit
    tausenden Einträgen entsteht (manche WebDAV-Speicher werden dabei sehr
    langsam)."""
    return f"{ordner}/{DATEI_ORDNER}/{sha1[:2]}/{sha1}.enc"


def _dokumente_der_familie(session, familie_id: int) -> list:
    from sqlmodel import select                          # noqa: PLC0415

    from .models import Dokument, Objekt                 # noqa: PLC0415

    objekte = [o.id for o in session.exec(select(Objekt).where(
        Objekt.familie_id == familie_id)).all()]
    if not objekte:
        return []
    return list(session.exec(select(Dokument).where(
        Dokument.objekt_id.in_(objekte))).all())


def dateien_sichern(session, familie, quelle, ziel, ordner: str,
                    schluessel: bytes, salz: bytes,
                    hoechstens: int | None = None) -> dict:
    """Überträgt die Belege der Familie in den Sicherungsspeicher.

    `quelle` ist die Nextcloud des Nutzers, `ziel` der Sicherungsspeicher —
    beides `Nextcloud`-Objekte, oft dasselbe. Jede Datei wird auf dem Server
    verschlüsselt, bevor sie hinausgeht; der Anbieter sieht nur den
    Prüfsummen-Namen und einen undurchsichtigen Klumpen.

    Übersprungen wird, was schon im Merkzettel steht (`BackupDatei`) — das
    ist der inkrementelle Teil: in der zweiten Nacht wandern nur die Belege
    hinüber, die tagsüber dazugekommen sind."""
    from .models import BackupDatei                      # noqa: PLC0415
    from .nextcloud import NextcloudFehler               # noqa: PLC0415
    from sqlmodel import select                          # noqa: PLC0415

    bekannt = {z.sha1 for z in session.exec(select(BackupDatei).where(
        BackupDatei.familie_id == familie.id)).all()}
    stand = {"geprueft": 0, "neu": 0, "bytes": 0, "uebersprungen": 0,
             "fehler": []}

    for dokument in _dokumente_der_familie(session, familie.id):
        if hoechstens is not None and stand["neu"] >= hoechstens:
            break
        stand["geprueft"] += 1
        if dokument.groesse and dokument.groesse > DATEI_MAX_BYTES:
            stand["uebersprungen"] += 1
            continue
        if dokument.sha1 and dokument.sha1 in bekannt:
            continue
        try:
            inhalt, _typ = quelle.hole(dokument.pfad)
        except NextcloudFehler as fehler:
            # Ein Beleg, der in der Cloud nicht mehr liegt, hält die
            # Sicherung nicht auf — der Rest ist wichtiger.
            stand["fehler"].append(f"{dokument.dateiname}: {fehler}")
            continue
        if len(inhalt) > DATEI_MAX_BYTES:
            stand["uebersprungen"] += 1
            continue
        # Die Prüfsumme selbst rechnen: nicht jede Nextcloud liefert eine,
        # und nur der tatsächliche Inhalt darf über den Namen entscheiden.
        sha1 = hashlib.sha1(inhalt).hexdigest()
        if sha1 in bekannt:
            continue
        try:
            ziel.ordner_anlegen(f"{ordner}/{DATEI_ORDNER}")
            ziel.ordner_anlegen(f"{ordner}/{DATEI_ORDNER}/{sha1[:2]}")
            ziel.lege_ab(_datei_ziel(ordner, sha1),
                         verschluesseln(inhalt, schluessel, salz),
                         typ="application/octet-stream")
        except NextcloudFehler as fehler:
            stand["fehler"].append(f"{dokument.dateiname}: {fehler}")
            continue
        session.add(BackupDatei(familie_id=familie.id, sha1=sha1,
                                groesse=len(inhalt)))
        bekannt.add(sha1)
        stand["neu"] += 1
        stand["bytes"] += len(inhalt)
    session.commit()
    if stand["neu"]:
        log.info("Belege gesichert für %s: %d neu (%d Bytes)", familie.name,
                 stand["neu"], stand["bytes"])
    return stand


def dateien_zurueckholen(session, familie, quelle, ziel, ordner: str,
                         passwort: str) -> dict:
    """Legt die gesicherten Belege wieder in der Nextcloud ab — unter
    denselben Pfaden wie vorher, damit die Verknüpfungen in der Datenbank
    ohne Zutun wieder greifen.

    Vorhandene Dateien werden nicht angefasst: wer schon da ist, bleibt."""
    from .nextcloud import NextcloudFehler               # noqa: PLC0415

    stand = {"geprueft": 0, "zurueck": 0, "fehlt": 0, "fehler": []}
    for dokument in _dokumente_der_familie(session, familie.id):
        stand["geprueft"] += 1
        if not dokument.sha1:
            stand["fehlt"] += 1
            continue
        try:
            if quelle.existiert(dokument.pfad):
                continue
            archiv, _typ = ziel.hole(_datei_ziel(ordner, dokument.sha1))
        except NextcloudFehler:
            stand["fehlt"] += 1
            continue
        try:
            inhalt = entschluesseln(archiv, passwort)
        except BackupFehler as fehler:
            stand["fehler"].append(f"{dokument.dateiname}: {fehler}")
            continue
        try:
            quelle.ordner_baum_anlegen(
                "/".join(dokument.pfad.strip("/").split("/")[:-1]), [])
            quelle.lege_ab(dokument.pfad, inhalt,
                           typ="application/octet-stream")
        except NextcloudFehler as fehler:
            stand["fehler"].append(f"{dokument.dateiname}: {fehler}")
            continue
        stand["zurueck"] += 1
    log.info("Belege zurückgeholt für %s: %d von %d", familie.name,
             stand["zurueck"], stand["geprueft"])
    return stand


def familie_sichern(session, familie, ausloeser: str = "nacht",
                    nur_bei_aenderung: bool = True) -> dict | None:
    """Export → Fingerabdruck → Archiv → Ziel → Protokoll. Gibt den
    Protokolleintrag zurück, oder None, wenn nichts zu tun war.

    Spät importiert: `export`/`cloudkern` ziehen die Router-Welt mit, und
    dieses Modul wird vom Wachdienst schon beim Start geladen."""
    from . import cloudkern, export                      # noqa: PLC0415
    from .models import Backup                           # noqa: PLC0415
    from .nextcloud import Nextcloud, NextcloudFehler    # noqa: PLC0415

    if not familie.backup_schluessel or not familie.backup_salz:
        raise BackupFehler("Es ist noch kein Backup-Passwort gesetzt.")
    if familie.backup_ziel not in ("nextcloud", "webdav"):
        raise BackupFehler("Es ist kein Ziel gewählt — Nextcloud oder WebDAV.")

    daten = export.exportiere_familie(session, familie)
    abdruck = fingerabdruck(daten)
    familie.backup_letzte_pruefung = datetime.now()

    try:
        if familie.backup_ziel == "nextcloud":
            client = cloudkern.verbindung(session)
            if not client.heimat:
                raise BackupFehler("In der Nextcloud ist noch kein Home-Ordner gewählt.")
            ordner = f"{client.heimat.strip('/')}/_Backups"
        else:
            client = Nextcloud.webdav(familie.backup_webdav_url,
                                      familie.backup_webdav_benutzer,
                                      familie.backup_webdav_passwort,
                                      heimat="/ImmoCalc-Backups")
            ordner = "ImmoCalc-Backups"
        client.ordner_anlegen(ordner)
    except NextcloudFehler as fehler:
        raise BackupFehler(f"Speicher nicht erreichbar: {fehler}") from fehler
    except Exception as fehler:                          # noqa: BLE001
        # `verbindung()` wirft eine HTTPException, wenn Nextcloud nicht
        # eingerichtet ist — für den Nutzer ist das dieselbe Auskunft.
        raise BackupFehler(str(getattr(fehler, "detail", fehler))) from fehler

    # N478 — die Belege zuerst, und IMMER: ohne sie wäre die Sicherung nur
    # ein Verzeichnis von Dateien, die es nicht mehr gibt. Läuft auch, wenn
    # sich an den Daten nichts geändert hat — das kostet nichts, solange
    # nichts Neues da ist (nur ein Blick in den Merkzettel, kein Netz), und
    # holt einen abgebrochenen Lauf der Vornacht nach.
    quelle = cloudkern.verbindung(session) if familie.backup_ziel == "webdav" \
        else client
    dateien = dateien_sichern(session, familie, quelle, client, ordner,
                              bytes.fromhex(familie.backup_schluessel),
                              bytes.fromhex(familie.backup_salz))

    if nur_bei_aenderung and abdruck == familie.backup_fingerabdruck \
            and not dateien["neu"]:
        session.add(familie)
        session.commit()
        return None

    archiv = familie_archiv(daten, bytes.fromhex(familie.backup_schluessel),
                            bytes.fromhex(familie.backup_salz))
    name = dateiname_familie(familie.name)
    try:
        client.lege_ab(f"{ordner}/{name}", archiv, typ="application/octet-stream")
    except NextcloudFehler as fehler:
        raise BackupFehler(f"Ablegen fehlgeschlagen: {fehler}") from fehler

    familie.backup_fingerabdruck = abdruck
    zusammenfassung = dict(daten.get("zusammenfassung") or {})
    zusammenfassung["dateien_neu"] = dateien["neu"]
    zusammenfassung["dateien_bytes"] = dateien["bytes"]
    eintrag = Backup(familie_id=familie.id, art="familie", dateiname=name,
                     groesse=len(archiv), ziel=familie.backup_ziel,
                     ausloeser=ausloeser, zusammenfassung=zusammenfassung)
    session.add(familie)
    session.add(eintrag)
    session.commit()
    session.refresh(eintrag)
    log.info("Familien-Backup abgelegt für %s (%s, %d Bytes, %d neue Belege)",
             familie.name, familie.backup_ziel, len(archiv), dateien["neu"])
    return {"id": eintrag.id, "dateiname": name, "groesse": len(archiv),
            "ziel": familie.backup_ziel, "zusammenfassung": zusammenfassung,
            "dateien": dateien}


def nachtlauf(engine, jetzt: datetime | None = None) -> dict:
    """Vom Wachdienst alle 15 Minuten gerufen; tut nur im nächtlichen Fenster
    etwas, und je Familie/Instanz nur einmal pro Nacht."""
    from sqlmodel import Session, select                 # noqa: PLC0415

    from . import familienraum                           # noqa: PLC0415
    from .models import Backup, Familie                  # noqa: PLC0415

    # Der Pfad kommt aus der ENGINE, nicht aus `db.DB_PATH`: was die Engine
    # gerade benutzt, wird gesichert — nicht, was beim Import einmal galt.
    db_pfad = engine.url.database
    jetzt = jetzt or datetime.now()
    ergebnis: dict = {"familien": 0, "gesichert": 0, "instanz": None, "fehler": []}
    if not NACHT_VON <= jetzt.hour < NACHT_BIS:
        return ergebnis

    with Session(engine) as session:
        for familie in session.exec(select(Familie)).all():
            if not faellig(familie.backup_rhythmus, familie.backup_letzte_pruefung, jetzt):
                continue
            ergebnis["familien"] += 1
            familienraum.setzen(familie.id)
            try:
                if familie_sichern(session, familie, ausloeser="nacht"):
                    ergebnis["gesichert"] += 1
            except BackupFehler as fehler:
                # Auch ein Fehlschlag zählt als geprüft — sonst hämmert der
                # Takt die Nacht durch gegen ein kaputtes Ziel.
                familie.backup_letzte_pruefung = jetzt
                session.add(familie)
                session.commit()
                ergebnis["fehler"].append(f"{familie.name}: {fehler}")
                log.warning("Familien-Backup für %s fehlgeschlagen: %s",
                            familie.name, fehler)
            finally:
                familienraum.setzen(None)

        if instanz_eingerichtet() and not instanz_heute_schon(jetzt=jetzt):
            try:
                stand = instanz_sichern(db_pfad)
                session.add(Backup(art="instanz", dateiname=stand["dateiname"],
                                   groesse=stand["groesse"], ziel="ordner",
                                   ausloeser="nacht"))
                session.commit()
                stand["aufgeraeumt"] = instanz_aufraeumen(jetzt=jetzt)
                ergebnis["instanz"] = stand
                log.info("Instanz-Backup abgelegt: %s (%d Bytes)",
                         stand["dateiname"], stand["groesse"])
            except BackupFehler as fehler:
                ergebnis["fehler"].append(f"Instanz: {fehler}")
                log.warning("Instanz-Backup fehlgeschlagen: %s", fehler)
    return ergebnis
