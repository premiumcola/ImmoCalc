"""Wohin ein Beleg gehört — und wie er dorthin kommt, ohne etwas zu zerstören.

Zwei Fragen, eine Stelle. **Wohin:** aus Immobilie, Kategorie und Jahr wird der
Sachordner (`_zielordner`) und darin der Ablageordner (`_ablageordner`) —
wobei ein bereits vorhandener Jahresordner immer Vorrang vor einem neu
gebildeten Namen hat; N289 gibt die Renovierungsmaske ihren Projektordner
direkt mit (`_projektordner`). Ein frei gewählter Ordner wird auf den
Objektordner eingesperrt (`_ziel_im_objekt`), damit ein Beleg nie im Ordner
einer fremden Immobilie landet.

**Wie:** angelegt wird mit MKCOL (`_ordner_sichern`, 405 = existiert schon),
verschoben mit MOVE (`_beleg_umziehen`), und der Name wird vorher live gegen
die Cloud geprüft (`_freier_name`) — nie überschreiben, nie löschen. Der
`.immocalc`-Steckbrief zieht als Beiwerk mit (`_sidecar_mitnehmen`); scheitert
das, ist der Beleg trotzdem richtig abgelegt.

Der Nextcloud-Client kommt bei jeder dieser Funktionen von aussen. Wer ihn
selbst besorgt (`verbindung`), bleibt im Router — die Tests reichen ihn dort
über `monkeypatch.setattr(dok, "verbindung", …)` durch.
"""
from __future__ import annotations

import logging

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from .. import kidb
from ..bezeichnung import unterordner_finden
from ..cloudkern import ARTKUERZEL, STRUKTUR, ZIELORDNER, unterordner_fuer
from ..models import Dokument, Objekt, Renovierung
from ..nextcloud import NextcloudFehler
from ..renovierung import projektordner
from .grabstein import _verwaisten_eintrag_freigeben
from .namen import _elternordner, _sidecar_pfad

log = logging.getLogger("immocalc")


def _freier_name(session: Session, client, ordner: str, name: str) -> str:
    """Haengt -2, -3 an, falls der Name schon vergeben ist — nie ueberschreiben.

    Gefragt wird die Cloud, live per WebDAV. Nur eine Datei, die dort WIRKLICH
    noch liegt, führt zu einem zweiten Namen.

    N242: meldet die Cloud den Platz als frei, zeigt aber noch ein Eintrag
    dorthin, hat der Nutzer die Datei ausserhalb der App gelöscht — dann gibt
    `_verwaisten_eintrag_freigeben` den Namen wieder frei, statt auf „-2"
    auszuweichen. Ohne dieses Aufräumen verschöbe die Automatik die Datei und
    scheiterte danach am Unique-Index des alten Eintrags."""
    stamm, punkt, endung = name.rpartition(".")
    stamm = stamm or name
    endung = f".{endung}" if punkt else ""
    kandidat, n = name, 2
    while client.existiert(f"{ordner}/{kandidat}"):
        kandidat = f"{stamm}-{n}{endung}"
        n += 1
        if n > 50:
            # Notausgang: hier ist nichts nachweislich frei — nichts freigeben.
            return kandidat
    _verwaisten_eintrag_freigeben(session, f"{ordner}/{kandidat}")
    return kandidat


def _zielordner(o: Objekt, kategorie: str) -> str:
    """Der Sachordner der Immobilie — „…/60_Nebenkosten"."""
    unterordner = ZIELORDNER.get(kategorie, "99_Sonstiges")
    if unterordner not in STRUKTUR:
        raise HTTPException(400, f"Unbekannter Zielordner '{unterordner}'")
    return f"{o.nc_ordner.strip('/')}/{unterordner}"


def _projektordner(session: Session, renovierung_id: int | None) -> str:
    """N289 — der Ordnername des Bauvorhabens, zu dem eine Rechnung gehört.

    Leer heisst: keine Renovierung gemeint (oder sie gibt es nicht mehr) — dann
    bleibt alles wie bisher. Eine unbekannte Nummer ist bewusst kein Fehler:
    der Beleg soll abgelegt werden, notfalls eine Ebene höher."""
    if not renovierung_id:
        return ""
    r = session.get(Renovierung, renovierung_id)
    if r is None:
        log.info("Renovierung %s nicht gefunden — Beleg ohne Projektordner",
                 renovierung_id)
        return ""
    return projektordner(r.name, r.von)


def _ablageordner(session: Session, o: Objekt, kategorie: str,
                  jahr: int | None, client, unterordner: str = "") -> tuple[str, str]:
    """(Sachordner, Ablageordner) — CXCI: in NK liegt nichts mehr flach.

    `unterordner` schlägt die Vorlage: N289 gibt die Renovierungsmaske den
    Projektordner („2025.01_Generalsanierung") direkt mit, weil er sich aus
    Jahr und Einheit nicht bilden lässt.

    Der Ablageordner ist der Sachordner selbst, solange die Vorlage nichts
    hergibt (leere Vorlage, Beleg ohne Jahr). Sonst der Jahresordner darin —
    und zwar **der vorhandene**, wenn es ihn schon gibt: liegt „2025" da,
    wandert der Beleg dorthin und nicht in ein zweites „2025_Nebenkosten".

    Lässt sich der Sachordner nicht auflisten (er ist meist noch gar nicht
    angelegt), wird der Name aus der Vorlage genommen — das ist kein Fehler,
    nur eine Auskunft, die es noch nicht gibt."""
    sach = _zielordner(o, kategorie)
    ziel = unterordner or unterordner_fuer(session, o, kategorie, jahr)
    if not ziel:
        return sach, sach
    if unterordner:
        # Ein Projektordner trägt seinen Namen selbst; die Jahres-Erkennung von
        # `unterordner_finden` würde hier „2025.01_Generalsanierung" mit einem
        # blossen „2025" verwechseln und die Rechnung dorthin sortieren.
        return sach, f"{sach}/{unterordner}"
    try:
        vorhandene = [e.name for e in client.liste(sach) if e.ordner]
    except NextcloudFehler as fehler:
        log.info("Unterordner von %s nicht gelesen: %s", sach, fehler)
        vorhandene = []
    treffer = unterordner_finden(vorhandene, jahr, ziel,
                                 (kategorie, ARTKUERZEL.get(kategorie, "")))
    return sach, f"{sach}/{treffer or ziel}"


def _ordner_sichern(client, sach: str, ordner: str) -> None:
    """Legt Sach- und Ablageordner an. MKCOL verträgt 405 (existiert schon),
    und der tiefere Ordner braucht seinen Eltern vorher."""
    client.ordner_anlegen(sach)
    if ordner != sach:
        client.ordner_anlegen(ordner)


def _sidecar_mitnehmen(client, alt_pfad: str, neu_pfad: str) -> bool:
    """Benennt die `.immocalc`-Sidecar-Datei mit um, wenn es sie gibt.

    Liegt neben dem alten Beleg ein `<altname>.immocalc`, wird er per MOVE zum
    `<neuname>.immocalc` — Steckbrief und Beleg bleiben zusammen. Kein harter
    Fehler, wenn das scheitert (oder gar kein Sidecar existiert): der Beleg ist
    schon umbenannt, der Steckbrief ist Beiwerk."""
    alt_sc = _sidecar_pfad(alt_pfad)
    neu_sc = _sidecar_pfad(neu_pfad)
    if alt_sc == neu_sc:
        return False
    try:
        if not client.existiert(alt_sc):
            return False
        client.verschiebe(alt_sc, neu_sc)
        return True
    except Exception as fehler:                            # noqa: BLE001
        log.info("Sidecar nicht mitverschoben (%s → %s): %s",
                 alt_sc, neu_sc, fehler)
        return False


def _beleg_umziehen(session: Session, client, d: Dokument, ziel_ordner: str,
                    neu_name: str) -> str | None:
    """Verschiebt Beleg `d` (Datei + `.immocalc`-Sidecar + DB-Eintrag) nach
    `ziel_ordner/neu_name`. Kollisionssicher (`_freier_name`), nie überschreiben,
    nie löschen. Gibt den tatsächlichen neuen Namen zurück — oder None, wenn der
    Beleg schon richtig liegt und heißt.

    Scheitert der Cloud-MOVE, wird die Ausnahme durchgereicht (Datei und
    Datenbank bleiben unberührt). Kippt der DB-Commit (Pfad vergeben), wird die
    Datei zurückgeschoben, damit Cloud und Datenbank zusammenbleiben."""
    alt_pfad = d.pfad
    alt_ordner = _elternordner(alt_pfad)
    ziel_ordner = (ziel_ordner or "").strip("/")
    if alt_ordner == ziel_ordner and d.dateiname == neu_name:
        return None
    frei = _freier_name(session, client, ziel_ordner, neu_name)
    ziel = f"/{ziel_ordner}/{frei}" if ziel_ordner else f"/{frei}"
    if ziel == alt_pfad:
        return None
    client.verschiebe(alt_pfad, ziel.lstrip("/"))
    d.pfad = ziel
    d.dateiname = frei
    kidb.pfad_nachziehen(session, d)   # N299
    session.add(d)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        try:
            client.verschiebe(ziel.lstrip("/"), alt_pfad.lstrip("/"))
        except Exception as zurueck:                          # noqa: BLE001
            log.warning("Rückverschieben nach Konflikt gescheitert (%s): %s",
                        ziel, zurueck)
        raise
    _sidecar_mitnehmen(client, alt_pfad, ziel)
    return frei


def _ziel_im_objekt(o: Objekt, ordner: str) -> str:
    """Ein frei gewählter Ordner, auf den Objektordner eingesperrt.

    Zusätzlich zum Home-Riegel in `nextcloud._pruefe_schreibrecht`: ein Beleg
    dieser Immobilie hat ausserhalb ihres Ordners nichts verloren, auch nicht
    auf ausdrücklichen Wunsch. Sonst liesse sich über diesen Weg ein Beleg in
    den Ordner einer FREMDEN Immobilie schieben, und der Abgleich dort würde
    ihn beim nächsten Lauf als deren Beleg aufnehmen."""
    wurzel = (o.nc_ordner or "").strip("/")
    ziel = (ordner or "").strip("/")
    if not wurzel:
        raise HTTPException(400, "Für diese Immobilie ist kein Cloud-Ordner "
                                 "hinterlegt.")
    if ".." in ziel.split("/"):
        raise HTTPException(400, "Unzulässiger Pfad.")
    if not ziel:
        return wurzel
    if ziel == wurzel or ziel.startswith(wurzel + "/"):
        return ziel
    # Eine relative Angabe („60_Nebenkosten/2025") wird unter dem Objektordner
    # verstanden — das ist die Form, in der die Oberfläche sie anbietet.
    return f"{wurzel}/{ziel}"
