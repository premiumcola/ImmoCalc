"""N264/N275 — Drucken: direkt an den Drucker (Port 9100), CUPS als Rückfall.

N275 — der Weg über CUPS (IPP, Port 631) legt die Aufträge sauber in die
Warteschlange und bringt sie **nicht** zu den Geräten; selbst die Testseite von
CUPS bleibt hängen. Bewiesen funktioniert dagegen der direkte Weg: rohe Bytes
auf **Port 9100** (RAW/JetDirect) kamen als Ausdruck heraus. Deshalb pflegt der
Nutzer seine Drucker jetzt in den Einstellungen mit IP und Port, und wir
sprechen sie unmittelbar an — ohne Zwischenstation.

**Ehrlich bleiben:** über Port 9100 nimmt der Drucker die Bytes so, wie sie
kommen — es gibt keine Rückmeldung, ob er sie versteht. Ob ein PDF direkt
gedruckt wird, hängt allein am Gerät („PDF Direct Print"): der Konica kann das
sehr wahrscheinlich, ein kleiner HP LaserJet (nur PCL/hostbasiert) vermutlich
nicht — dann kommt entweder nichts oder eine Seite Zeichensalat. Konvertiert
wird hier bewusst nichts (das hiesse eine Bibliothek ins Image holen). Die
Meldung sagt deshalb „an den Drucker geschickt" und nie „gedruckt".

Der CUPS-Teil unten bleibt als Rückfall stehen, solange kein Drucker
konfiguriert ist.

IPP ist ein Binärformat über HTTP. Statt `cups-client` ins Image zu holen
(neues Systempaket, neuer Deploy-Grund) werden die beiden gebrauchten
Operationen hier von Hand zusammengesetzt: die Druckerliste holen und einen
Auftrag abschicken. Mehr braucht es nicht.

Gesprochen wird IPP 2.0. Aufbau einer Anfrage:

    2 Byte  Version (0x02 0x00)
    2 Byte  Operation
    4 Byte  Request-Id
    0x01    Beginn der Operations-Attribute
      je Attribut: 1 Byte Typ, 2 Byte Namenslänge, Name,
                   2 Byte Wertlänge, Wert
    0x02    Beginn der Auftrags-Attribute (nur beim Drucken)
    0x03    Ende der Attribute
    danach  das Dokument selbst

Ohne Zugangsdaten: die Drucker stehen im eigenen Netz und nehmen Aufträge
direkt an (vom Nutzer bestätigt). Kommt später doch eine Anmeldung dazu,
gehört sie in die Umgebung, nicht in den Code.
"""
from __future__ import annotations

import logging
import re
import socket
import struct

try:                                              # pragma: no cover
    import httpx
except Exception:                                 # pragma: no cover
    httpx = None                                  # type: ignore[assignment]

log = logging.getLogger("immocalc")

ZEITLIMIT = 20.0

# --------------------------------------------------------------------------
# N275 — der direkte Weg: rohe Bytes auf Port 9100
# --------------------------------------------------------------------------

RAW_PORT = 9100                                   # RAW/JetDirect, die Vorgabe
ZEITLIMIT_TCP = 4.0                               # kurz: der Drucker steht im
                                                  # eigenen Netz oder gar nicht

# Die Adresse kommt aus den Einstellungen und wandert in eine TCP-Verbindung.
# Erlaubt ist nur, was eine IPv4 oder ein Hostname sein kann — kein Pfad, kein
# Semikolon, kein Leerzeichen. So kann aus der Eingabe nichts anderes werden.
_ADRESSE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.\-]{0,60}[A-Za-z0-9])?$")


def pruefe_ziel(ip: str, port: int) -> str:
    """Prüft Adresse und Port. Leerer String heisst „in Ordnung", sonst der
    Klartext-Grund — der Aufrufer reicht ihn unverändert an die Oberfläche."""
    if not _ADRESSE.match((ip or "").strip()):
        return "Keine gültige IP-Adresse"
    try:
        nummer = int(port)
    except (TypeError, ValueError):
        return "Kein gültiger Port"
    if not 1 <= nummer <= 65535:
        return "Port muss zwischen 1 und 65535 liegen"
    return ""


def erreichbar(ip: str, port: int = RAW_PORT) -> bool:
    """Nur ein TCP-Handschlag: Verbindung auf, Verbindung zu. Druckt nichts —
    Papier und Toner gehören dem Nutzer."""
    if pruefe_ziel(ip, port):
        return False
    try:
        with socket.create_connection((ip.strip(), int(port)), ZEITLIMIT_TCP):
            return True
    except OSError as fehler:                     # noqa: BLE001
        log.info("Drucker %s:%s nicht erreichbar (%s)", ip, port,
                 type(fehler).__name__)
        return False


def roh_drucken(ip: str, port: int, daten: bytes,
                titel: str = "ImmoCalc") -> tuple[bool, str]:
    """Schiebt die Bytes unverändert auf Port 9100. `(geklappt, Meldung)`.

    Jeder Fehler ergibt `(False, Klartext)` statt einer Ausnahme — Drucken ist
    Beiwerk und darf nie eine Seite mitreissen. `True` heisst ausschliesslich:
    die Daten sind beim Gerät angekommen. Ob es sie versteht, sagt uns niemand
    (siehe Modul-Kopf)."""
    grund = pruefe_ziel(ip, port)
    if grund:
        return False, grund
    if not daten:
        return False, "Nichts zu drucken"
    try:
        with socket.create_connection((ip.strip(), int(port)),
                                      ZEITLIMIT_TCP) as verbindung:
            verbindung.settimeout(ZEITLIMIT)
            verbindung.sendall(daten)
    except OSError as fehler:                     # noqa: BLE001
        log.info("Druckdaten für %s:%s nicht losgeworden: %s", ip, port,
                 type(fehler).__name__)
        return False, f"Der Drucker unter {ip}:{port} antwortet nicht"
    log.info("%d Byte an %s:%s geschickt (%s)", len(daten), ip, port, titel)
    return True, "An den Drucker geschickt"

# --------------------------------------------------------------------------
# N264 — CUPS/IPP: der Rückfall, solange kein Drucker konfiguriert ist
# --------------------------------------------------------------------------

# IPP-Kennungen, nur die hier gebrauchten.
_OP_DRUCKEN = 0x0002                              # Print-Job
_OP_DRUCKER_HOLEN = 0x4002                        # CUPS-Get-Printers
_TAG_OPERATION = 0x01
_TAG_AUFTRAG = 0x02
_TAG_ENDE = 0x03
_TAG_KEYWORD = 0x44
_TAG_NAME = 0x42
_TAG_URI = 0x45
_TAG_CHARSET = 0x47
_TAG_SPRACHE = 0x48
_TAG_TEXT = 0x41
_TAG_MIME = 0x49                                  # mimeMediaType


def _attribut(tag: int, name: bytes, wert: bytes) -> bytes:
    return struct.pack(">BH", tag, len(name)) + name + struct.pack(">H", len(wert)) + wert


def _folgewert(wert: bytes) -> bytes:
    """Ein weiterer Wert zum vorigen Attribut — Name leer (IPP 1:1-Regel)."""
    return struct.pack(">BHH", _TAG_KEYWORD, 0, len(wert)) + wert


def _kopf(operation: int, request_id: int = 1) -> bytes:
    return struct.pack(">BBHI", 2, 0, operation, request_id) + bytes([_TAG_OPERATION]) \
        + _attribut(_TAG_CHARSET, b"attributes-charset", b"utf-8") \
        + _attribut(_TAG_SPRACHE, b"attributes-natural-language", b"de")


def _status(antwort: bytes) -> int:
    """Der IPP-Statuscode steht in Byte 2–3. < 0x0100 heisst erfolgreich."""
    return struct.unpack(">H", antwort[2:4])[0] if len(antwort) >= 4 else 0xFFFF


def _texte(antwort: bytes, feld: bytes) -> list[str]:
    """Alle Werte eines Attributnamens aus der Antwort — genügt für die
    Druckerliste; ein vollständiger IPP-Parser wäre hier Überbau."""
    raus: list[str] = []
    stelle = 0
    while True:
        stelle = antwort.find(feld, stelle)
        if stelle < 0:
            return raus
        ende = stelle + len(feld)
        if ende + 2 <= len(antwort):
            laenge = struct.unpack(">H", antwort[ende:ende + 2])[0]
            wert = antwort[ende + 2:ende + 2 + laenge]
            if wert:
                raus.append(wert.decode("utf-8", "replace"))
        stelle = ende


def _senden(server: str, rumpf: bytes, pfad: str = "/") -> bytes | None:
    """Eine IPP-Anfrage abschicken. `None` bei jedem Fehler — Drucken ist
    Beiwerk und darf nie eine Seite mitreissen."""
    if httpx is None:
        return None
    try:
        antwort = httpx.post(f"http://{server}{pfad}", content=rumpf,
                             headers={"Content-Type": "application/ipp"},
                             timeout=ZEITLIMIT)
    except Exception as fehler:                   # noqa: BLE001
        log.info("Drucker nicht erreichbar (%s): %s", server, type(fehler).__name__)
        return None
    if antwort.status_code != 200:
        log.info("Druckdienst meldete HTTP %s", antwort.status_code)
        return None
    return antwort.content


def drucker_liste(server: str) -> list[dict]:
    """Die Warteschlangen des Druckdienstes: `[{name, ort}]`.

    Leere Liste, wenn der Dienst nicht erreichbar ist — die Oberfläche zeigt
    dann einfach keine Druckknöpfe, statt einen Fehler zu behaupten."""
    rumpf = _kopf(_OP_DRUCKER_HOLEN) + _attribut(
        _TAG_KEYWORD, b"requested-attributes", b"printer-name") \
        + _folgewert(b"printer-location") + bytes([_TAG_ENDE])
    antwort = _senden(server, rumpf)
    if antwort is None or _status(antwort) >= 0x0100:
        return []
    namen = _texte(antwort, b"printer-name")
    orte = _texte(antwort, b"printer-location")
    return [{"name": n, "ort": orte[i] if i < len(orte) else ""}
            for i, n in enumerate(namen)]


def _drucker_uri(server: str, drucker: str) -> bytes:
    return f"ipp://{server}/printers/{drucker}".encode()


# Ein Warteschlangenname kommt aus der Oberfläche — nur das durchlassen, was
# CUPS selbst vergibt, damit daraus kein fremder Pfad werden kann.
_ERLAUBT = re.compile(r"^[\w().\-]{1,127}$")


def drucken(server: str, drucker: str, daten: bytes, titel: str = "ImmoCalc",
            farbe: bool = False, beidseitig: bool = False) -> tuple[bool, str]:
    """Schickt ein PDF an eine Warteschlange. `(geklappt, Meldung)`.

    Schwarz-weiss und einseitig sind die Vorgabe: Vorlagen sind Formulare zum
    Ausfüllen — Farbe kostet nur Toner. `print-color-mode` und `sides` sind
    IPP-Standardnamen; versteht ein Treiber sie nicht, druckt er trotzdem und
    ignoriert sie."""
    if not _ERLAUBT.match(drucker or ""):
        return False, "Unbekannter Drucker"
    if not daten:
        return False, "Nichts zu drucken"
    rumpf = (_kopf(_OP_DRUCKEN)
             + _attribut(_TAG_URI, b"printer-uri", _drucker_uri(server, drucker))
             + _attribut(_TAG_NAME, b"requesting-user-name", b"immocalc")
             + _attribut(_TAG_TEXT, b"job-name", titel.encode()[:255])
             # `document-format` ist laut IPP ein mimeMediaType (0x49). Mit dem
             # falschen Typ nimmt CUPS den Auftrag zwar an, kann das Format aber
             # nicht sicher zuordnen — der Auftrag bleibt dann leicht hängen.
             + _attribut(_TAG_MIME, b"document-format", b"application/pdf")
             + bytes([_TAG_AUFTRAG])
             + _attribut(_TAG_KEYWORD, b"print-color-mode",
                         b"color" if farbe else b"monochrome")
             + _attribut(_TAG_KEYWORD, b"sides",
                         b"two-sided-long-edge" if beidseitig else b"one-sided")
             + bytes([_TAG_ENDE]) + daten)
    antwort = _senden(server, rumpf, f"/printers/{drucker}")
    if antwort is None:
        return False, "Der Druckdienst ist nicht erreichbar"
    code = _status(antwort)
    if code >= 0x0100:
        log.info("Druckauftrag abgelehnt (IPP 0x%04x, %s)", code, drucker)
        return False, f"Der Drucker hat den Auftrag abgelehnt (0x{code:04x})"
    log.info("Druckauftrag angenommen: %s", drucker)
    return True, "Auftrag an den Drucker geschickt"
