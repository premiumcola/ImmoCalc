"""N311 — wer den Namen einer Einheit als TEXT trägt, und wie er mitwandert.

Eine Einheit heisst „Wohnung 2". Dieser Name steht nicht nur an der `Einheit`
selbst, sondern als Zeichenkette in sieben weiteren Spalten — bei der Miete,
bei den Anteilen, an Kostenpositionen (`nur_einheit`, `vorab_einheit`), am
Heizverteiler, am Strom-Jahr und an der WEG-Vorauszahlung. Das ist gewachsen
und hat einen Grund: ein Name überlebt das Löschen und Neuanlegen einer
Einheit, eine Id nicht.

Der Preis: **beim Umbenennen muss er überall mitwandern.** Bis N311 zog
`einheiten.py` nur `Miete.einheit` nach (das war der Fund XCII). Alles andere
blieb auf dem alten Namen stehen — und `verteilung.nur_einheit_gewichte` gibt
bei fehlender Übereinstimmung **stumm `{}` zurück**. Ergebnis: eine
Kostenposition „nur für Wohnung 2", 300 €, wurde nach dem Umbenennen auf
niemanden mehr verteilt. Die Engine-Invariante „Summe der Anteile == Gesamt-
kosten" war für diese Position gebrochen, ohne einen einzigen Hinweis.

Das Register wird deshalb **aus dem Datenmodell erzeugt**, nicht von Hand
gepflegt: eine Textspalte, deren Name auf „einheit" endet, trägt einen
Einheitennamen. Kommt morgen ein Modell dazu, ist es von selbst dabei.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlmodel import Session, SQLModel, text

log = logging.getLogger("immocalc")

# Die Tabelle der Einheiten selbst — dort steht der Name in `bezeichnung` und
# wird vom Aufrufer schon gesetzt.
_EIGEN = "einheit"

# Spalten, die zwar „einheit" heissen, aber KEINEN Namen tragen: die
# Fremdschlüssel. Sie wandern von selbst mit, weil sie auf die Id zeigen.
# N454 — dazu die Spalten, die zwar auf „einheit" enden, aber eine MASS-
# einheit tragen ('m³' | 'kWh' | 'Liter' | 'Einheiten') statt des Namens
# einer Wohneinheit. Ohne diesen Ausschluss hätte eine Einheit namens
# „Liter" beim Umbenennen quer durch den Bestand Zählertypen umgeschrieben.
_KEIN_NAME = ("einheit_id", "einheiten", "messeinheit", "menge_einheit")


@dataclass(frozen=True)
class Namensfeld:
    tabelle: str
    spalte: str

    def __str__(self) -> str:
        return f"{self.tabelle}.{self.spalte}"


def register() -> list[Namensfeld]:
    """Alle Textspalten, die den Namen einer Einheit tragen."""
    from . import models  # noqa: F401,PLC0415 — füllt die Metadaten

    gefunden: list[Namensfeld] = []
    for name, tabelle in SQLModel.metadata.tables.items():
        if name == _EIGEN:
            continue
        for spalte in tabelle.columns:
            if spalte.name in _KEIN_NAME or spalte.foreign_keys:
                continue
            if not spalte.name.endswith("einheit"):
                continue
            # Nur Text — eine Zahl trägt keinen Namen.
            if "CHAR" not in str(spalte.type).upper() and \
                    "TEXT" not in str(spalte.type).upper():
                continue
            gefunden.append(Namensfeld(name, spalte.name))
    return sorted(gefunden, key=lambda f: (f.tabelle, f.spalte))


def _nur_dieses_objekt(f: Namensfeld) -> str:
    """Die WHERE-Bedingung, die den Namenswechsel auf EIN Objekt begrenzt.

    N454 — ohne sie traf das UPDATE jede Zeile mit demselben Namen, in jedem
    Objekt und (seit N436) in jeder Familie: „Wohnung 2" heisst in jedem Haus
    so. Tabellen mit `objekt_id` werden direkt eingegrenzt, die am Zeitraum
    hängenden über ihn."""
    spalten = {s.name for s in SQLModel.metadata.tables[f.tabelle].columns}
    if "objekt_id" in spalten:
        return "objekt_id = :oid"
    if "zeitraum_id" in spalten:
        return ("zeitraum_id IN (SELECT id FROM zeitraum "
                "WHERE objekt_id = :oid)")
    # Bewusst hart: eine neue Namensspalte ohne Objektbezug darf NICHT
    # stillschweigend global umgeschrieben werden.
    raise ValueError(f"{f} lässt sich keinem Objekt zuordnen")


def benenne_um(session: Session, alt: str, neu: str,
               objekt_id: int) -> dict[str, int]:
    """Zieht den Einheitennamen überall nach — NUR innerhalb `objekt_id`.

    Gibt je Feld die Trefferzahl. Committet NICHT — der Aufrufer benennt
    gerade die Einheit selbst um und schliesst die Transaktion ab, damit
    beides zusammen gilt oder gar nicht."""
    alt = (alt or "").strip()
    neu = (neu or "").strip()
    if not alt or not neu or alt == neu:
        return {}
    stand: dict[str, int] = {}
    for f in register():
        try:
            ergebnis = session.exec(text(  # noqa: S608 — Namen aus den Metadaten
                f'UPDATE "{f.tabelle}" SET "{f.spalte}" = :neu '
                f'WHERE "{f.spalte}" = :alt AND {_nur_dieses_objekt(f)}'
            ).bindparams(neu=neu, alt=alt, oid=objekt_id))
        except Exception as fehler:                        # noqa: BLE001
            # Eine Tabelle, die es in dieser Datenbank noch nicht gibt, darf das
            # Umbenennen nicht anhalten — der Rest wandert trotzdem.
            log.info("Einheitenname in %s nicht nachgezogen: %s", f, fehler)
            continue
        anzahl = getattr(ergebnis, "rowcount", 0) or 0
        if anzahl:
            stand[str(f)] = anzahl
    if stand:
        log.info("N311: Einheit „%s“ → „%s“ — nachgezogen: %s", alt, neu, stand)
    return stand


def haengt_daran(session: Session, name: str) -> dict[str, int]:
    """Wo dieser Einheitenname überall steht — für die Rückfrage vor dem
    Löschen. Leer heisst: an dieser Einheit hängt nichts mehr."""
    name = (name or "").strip()
    if not name:
        return {}
    stand: dict[str, int] = {}
    for f in register():
        try:
            n = session.exec(text(  # noqa: S608
                f'SELECT COUNT(*) FROM "{f.tabelle}" WHERE "{f.spalte}" = :n'
            ).bindparams(n=name)).one()[0]
        except Exception:                                  # noqa: BLE001
            continue
        if n:
            stand[str(f)] = n
    return stand
