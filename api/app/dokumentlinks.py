"""N300 — wer alles auf einen Beleg zeigt, und wie man zwei Belege zusammenführt.

Nachgemessen: **zehn** Tabellen tragen einen Fremdschlüssel auf `dokument.id`.
Beim Löschen eines Belegs wurde bisher **keiner** davon umgehängt oder gelöst —
im Probelauf zeigten Renovierungsposten, Versicherung, Kredit, Notarvertrag und
Belegdaten danach weiter auf die tote Nummer. Auch das vorhandene
`duplikat-entfernen` löschte ersatzlos.

Die Liste, die es im Router gab (`_ZUORDNUNG_MODELLE`), kannte nur sieben der
zehn — es fehlten genau die drei jüngsten (`belegdaten`, `renovierungsposten`,
`stromjahr`) — und diente ohnehin nur der Anzeige. Eine von Hand gepflegte
Liste hängt hinterher, sobald jemand ein Modell ergänzt; deshalb wird das
Register hier **aus dem Datenmodell erzeugt**. Ein neues Feld
`quelle_dokument_id` ist damit von selbst erfasst.

`zusammenfuehren` ist die einzige Stelle, an der ein Beleg zugunsten eines
anderen verschwindet: erst wandert jeder Verweis auf den Bleibenden, dann fällt
der Eintrag. Nie umgekehrt — sonst entstünde genau der Zustand, den diese Datei
beseitigt.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlmodel import Session, SQLModel, text

log = logging.getLogger("immocalc")

# Tabellen, die kein Verweis im Sinne dieser Datei sind: `dokument` selbst.
_EIGEN = "dokument"


@dataclass(frozen=True)
class Verweis:
    """Eine Spalte, die auf `dokument.id` zeigt."""
    tabelle: str
    spalte: str

    def __str__(self) -> str:                              # für Meldungen
        return f"{self.tabelle}.{self.spalte}"


def register() -> list[Verweis]:
    """Alle Spalten, die auf `dokument.id` zeigen — aus dem Datenmodell gelesen.

    Bewusst über die Metadaten und nicht über eine Aufzählung: eine Aufzählung
    ist genau dreimal veraltet gewesen, und das Ergebnis war ein Verweis ins
    Leere, den niemand bemerkt."""
    from . import models  # noqa: F401,PLC0415 — füllt die Metadaten
    gefunden: list[Verweis] = []
    for name, tabelle in SQLModel.metadata.tables.items():
        if name == _EIGEN:
            continue
        for spalte in tabelle.columns:
            for fk in spalte.foreign_keys:
                if fk.column.table.name == _EIGEN and fk.column.name == "id":
                    gefunden.append(Verweis(name, spalte.name))
    return sorted(gefunden, key=lambda v: (v.tabelle, v.spalte))


def zaehle(session: Session, dokument_id: int) -> dict[str, int]:
    """Wie viele Datensätze je Tabelle auf diesen Beleg zeigen.

    Für die Anzeige im Duplikat-Assistenten: ein Beleg ohne jeden Verweis ist
    der unverfänglichste Kandidat zum Wegwerfen, und das soll man sehen."""
    stand: dict[str, int] = {}
    for v in register():
        try:
            n = session.exec(text(  # noqa: S608 — Namen kommen aus den Metadaten
                f'SELECT COUNT(*) FROM "{v.tabelle}" WHERE "{v.spalte}" = :id'
            ).bindparams(id=dokument_id)).one()[0]
        except Exception as fehler:                        # noqa: BLE001
            log.info("Verweise in %s nicht zählbar: %s", v, fehler)
            continue
        if n:
            stand[str(v)] = n
    return stand


def haenge_um(session: Session, von_id: int, auf_id: int) -> int:
    """Zieht jeden Verweis von `von_id` auf `auf_id`. Gibt die Anzahl zurück.

    Committet NICHT — der Aufrufer bettet das in seine eigene Transaktion ein,
    damit Umhängen und Löschen zusammen gelingen oder zusammen ausbleiben.

    Zeigt ein Datensatz schon auf `auf_id`, ändert sich für ihn nichts; das
    `WHERE` trifft ihn gar nicht erst."""
    if von_id == auf_id:
        return 0
    umgehaengt = 0
    for v in register():
        try:
            ergebnis = session.exec(text(  # noqa: S608 — Namen aus den Metadaten
                f'UPDATE "{v.tabelle}" SET "{v.spalte}" = :auf WHERE "{v.spalte}" = :von'
            ).bindparams(auf=auf_id, von=von_id))
        except Exception as fehler:                        # noqa: BLE001
            # Eine Tabelle, die es in dieser Datenbank noch nicht gibt, darf das
            # Zusammenführen nicht anhalten — der Rest wandert trotzdem.
            log.info("Verweise in %s nicht umgehängt: %s", v, fehler)
            continue
        anzahl = getattr(ergebnis, "rowcount", 0) or 0
        if anzahl:
            log.info("N300: %d Verweis(e) in %s von Beleg %d auf %d gezogen",
                     anzahl, v, von_id, auf_id)
            umgehaengt += anzahl
    return umgehaengt


def loese(session: Session, dokument_id: int) -> int:
    """N314 — jeden Verweis auf diesen Beleg lösen. Gibt die Anzahl zurück.

    Für das Entfernen eines Belegs OHNE Nachfolger. `haenge_um` braucht ein
    Ziel; hier gibt es keins, also bleibt nur das Nullsetzen — und das ist
    zwingend, nicht kosmetisch:

    SQLite läuft in diesem Projekt ohne `PRAGMA foreign_keys` und **vergibt
    eine frei gewordene id neu**. Ein stehen gelassener Verweis zeigt deshalb
    nicht ins Leere, sondern nach kurzer Zeit auf einen **fremden** Beleg — der
    nächste Scan erbt die Nummer und erscheint als „Quelle" einer Versicherung,
    die er nie gesehen hat. Gemessen und reproduziert.

    Committet NICHT — der Aufrufer löscht gerade und schliesst selbst ab."""
    geloest = 0
    for v in register():
        try:
            ergebnis = session.exec(text(  # noqa: S608 — Namen aus den Metadaten
                f'UPDATE "{v.tabelle}" SET "{v.spalte}" = NULL '
                f'WHERE "{v.spalte}" = :id'
            ).bindparams(id=dokument_id))
        except Exception as fehler:                        # noqa: BLE001
            log.info("Verweise in %s nicht gelöst: %s", v, fehler)
            continue
        anzahl = getattr(ergebnis, "rowcount", 0) or 0
        if anzahl:
            log.info("N314: %d Verweis(e) in %s auf Beleg %d gelöst",
                     anzahl, v, dokument_id)
            geloest += anzahl
    return geloest


def ohne_verweise(session: Session, dokument_id: int) -> bool:
    """Hängt an diesem Beleg wirklich nichts mehr? Die Probe nach dem Umhängen."""
    return not zaehle(session, dokument_id)
