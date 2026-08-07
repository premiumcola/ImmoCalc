"""N264 — Drucken über CUPS, ohne zusätzliche Abhängigkeit.

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
import struct

try:                                              # pragma: no cover
    import httpx
except Exception:                                 # pragma: no cover
    httpx = None                                  # type: ignore[assignment]

log = logging.getLogger("immocalc")

ZEITLIMIT = 20.0

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
             + _attribut(_TAG_NAME, b"document-format", b"application/pdf")
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
