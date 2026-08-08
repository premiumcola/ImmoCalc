"""Hochgeladene Dateien entgegennehmen — eine Stelle, ein Riegel.

N292. Es gibt neun Endpunkte, die eine Datei annehmen. Sie lasen alle
`await datei.read()` und prüften danach unterschiedlich viel:

* Grössenlimit: an **drei** von neun (SolarEdge 5 MB, WEG 20 MB, Profilbild).
* Erlaubte Dateiart: an **einer** von neun (Dokumentvorlagen).

Wo beides fehlte — darunter `POST /api/dokumente/scannen`, der Weg, über den
fast jeder Beleg hereinkommt — wanderte eine beliebig grosse Datei zuerst
vollständig in den Arbeitsspeicher des Containers und danach in die Cloud. Es
brauchte keine böse Absicht dafür: ein versehentlich gewähltes Video vom
Telefon genügt.

Der Riegel gehört an genau eine Stelle, sonst gilt er wieder nur dort, wo
jemand daran gedacht hat. `lies()` ist die einzige Art, den Rumpf einer
hochgeladenen Datei zu bekommen.

Bewusst NICHT hier: was mit der Datei danach geschieht. Ablage, Benennung und
Zuordnung sind Fachlogik und stehen weiter bei ihren Endpunkten.
"""
from __future__ import annotations

import logging

from fastapi import HTTPException, UploadFile

log = logging.getLogger("immocalc")

# Vorgabe für Belege: grosszügig genug für einen mehrseitigen Farbscan, klein
# genug, dass ein versehentlich gewähltes Video auffällt statt durchzugehen.
MAX_BELEG = 30 * 1024 * 1024
# Bilder werden vor dem Senden verkleinert; was deutlich grösser ankommt, ist
# kein Beleg-Foto.
MAX_BILD = 5 * 1024 * 1024

# In Häppchen lesen: der Abbruch soll fallen, BEVOR die ganze Datei im Speicher
# liegt. Ein `await datei.read()` mit anschliessender Längenprüfung hat das
# Gegenteil getan — es hat erst geladen und dann abgelehnt.
_HAPPEN = 1024 * 1024


def _mb(bytes_: int) -> str:
    return f"{bytes_ / 1024 / 1024:.0f} MB"


async def lies(datei: UploadFile, *, max_bytes: int = MAX_BELEG,
               endungen: tuple[str, ...] = (), was: str = "Die Datei") -> bytes:
    """Den Rumpf einer hochgeladenen Datei lesen — mit Riegel.

    `max_bytes` bricht ab, sobald die Grenze überschritten ist; gelesen wird in
    Häppchen, damit eine 2-GB-Datei nicht erst vollständig im Speicher landet.
    `endungen` (z. B. `(".pdf", ".jpg")`) lässt nur diese Dateiarten durch —
    leer heisst: jede. Eine leere Datei ist immer ein Fehler; sie kam bisher an
    manchen Endpunkten als gültiger, aber unbrauchbarer Beleg durch.

    Wirft `HTTPException(400)` mit einem Text, der dem Nutzer sagt, was zu tun
    ist — nicht „Bad Request"."""
    name = (datei.filename or "").strip()
    if endungen:
        punkt = name.rfind(".")
        endung = name[punkt:].lower() if punkt > 0 else ""
        if endung not in endungen:
            raise HTTPException(400, (
                f'{was} hat die Endung „{endung or "—"}“. Möglich sind: '
                f'{", ".join(endungen)}.'))

    teile: list[bytes] = []
    gelesen = 0
    while True:
        happen = await datei.read(_HAPPEN)
        if not happen:
            break
        gelesen += len(happen)
        if gelesen > max_bytes:
            log.info("Upload abgewiesen: %s ist grösser als %s",
                     name or "(ohne Namen)", _mb(max_bytes))
            raise HTTPException(400, (
                f"{was} ist zu groß (mehr als {_mb(max_bytes)}). "
                "Bitte kleiner scannen oder das Bild verkleinern."))
        teile.append(happen)

    if not gelesen:
        raise HTTPException(400, f"{was} ist leer.")
    return b"".join(teile)
