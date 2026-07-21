"""Leichtgewichtige Schema-Angleichung für SQLite.

`SQLModel.metadata.create_all` legt ausschliesslich fehlende *Tabellen* an —
neue *Spalten* an bereits bestehenden Tabellen bleiben unberuecksichtigt. Eine
gewachsene Datenbank wuerde dadurch beim ersten Zugriff brechen. Hier werden
fehlende Spalten nachgezogen, damit bestehende Daten erhalten bleiben.
"""
import json
import logging

from sqlalchemy import Engine, inspect, text
from sqlmodel import SQLModel

log = logging.getLogger("immocalc")


def _literal(wert) -> str | None:
    if isinstance(wert, bool):
        return "1" if wert else "0"
    if isinstance(wert, (int, float)):
        return str(wert)
    if isinstance(wert, str):
        return "'" + wert.replace("'", "''") + "'"
    if isinstance(wert, (dict, list)):
        # JSON-Spalten (Kostenposition.anteile) liegen als Text in SQLite.
        return "'" + json.dumps(wert).replace("'", "''") + "'"
    return None


def _sql_vorgabe(spalte) -> str | None:
    """SQL-Literal für den Default einer Spalte.

    Auch für erzeugte Vorgaben (`default_factory`, in SQLAlchemy ein Callable):
    ohne sie bliebe `Kostenposition.anteile` in Bestandszeilen NULL, und die
    Abrechnung stolpert später über `None.values()` — die Zeitraumseite
    antwortet dann mit 500, obwohl die Daten unversehrt sind.
    """
    default = getattr(spalte, "default", None)
    if default is None:
        # Kein Default im Modell: den leeren Wert aus dem Spaltentyp ableiten,
        # damit eine gewachsene Datenbank nicht NULL enthält, wo eine frisch
        # angelegte NOT NULL hätte.
        return _neutral_fuer(spalte)
    if getattr(default, "is_callable", False):
        try:
            return _literal(default.arg(None))
        except Exception:       # noqa: BLE001 — eine Vorgabe ist kein Muss
            return None
    return _literal(getattr(default, "arg", None))


def _neutral_fuer(spalte) -> str | None:
    """„Nichts" in der Sprache des Spaltentyps."""
    typ = spalte.type.__class__.__name__.upper()
    # JSON auch dann, wenn die Spalte NULL erlaubt: der Lesecode erwartet ein
    # dict. Ein NULL dort legt die ganze Zeitraumseite lahm.
    if "JSON" in typ:
        return "'{}'"
    if spalte.nullable or spalte.primary_key:
        return None
    if any(t in typ for t in ("INT", "FLOAT", "NUMERIC", "DECIMAL")):
        return "0"
    if any(t in typ for t in ("VARCHAR", "TEXT", "STRING")):
        return "''"
    return None


# Eindeutigkeiten, die `create_all` nur an einer *neuen* Tabelle anlegt. An
# einer gewachsenen Datenbank fehlen sie sonst für immer — der Index kommt
# additiv hinzu, keine Spalte ändert sich, gelöscht wird nichts.
EINDEUTIG: list[tuple[str, str, str]] = [
    # Tabelle, Spalte, Indexname
    ("dokument", "pfad", "ux_dokument_pfad"),
]


# Suchindizes, die `create_all` ebenfalls nur an einer *neuen* Tabelle anlegt.
# Eine per ALTER ergänzte Spalte bekommt ihren Index sonst nie —
# `Dokument.position_id` wird an jeder Position der Zeitraumseite abgefragt
# (CLXXXIII). Rein additiv: angelegt wird nur, was fehlt, entfernt wird nichts.
INDEXE: list[tuple[str, str, str]] = [
    # Tabelle, Spalte, Indexname
    ("dokument", "position_id", "ix_dokument_position_id"),
]


def indizes_sichern(conn, tabellen: set[str] | None = None) -> list[str]:
    """Legt die Suchindizes aus `INDEXE` an. Gibt die gesetzten zurück."""
    gesetzt: list[str] = []
    for tabelle, spalte, name in INDEXE:
        if tabellen is not None and tabelle not in tabellen:
            continue
        conn.execute(text(f'CREATE INDEX IF NOT EXISTS "{name}" '
                          f'ON "{tabelle}" ("{spalte}")'))
        gesetzt.append(name)
    return gesetzt


def _doppel(conn, tabelle: str, spalte: str) -> list[tuple[str, int]]:
    """Werte, die mehrfach vorkommen — die einzige Hürde für den Index."""
    zeilen = conn.execute(text(
        f'SELECT "{spalte}", count(*) AS anzahl FROM "{tabelle}" '
        f'GROUP BY "{spalte}" HAVING count(*) > 1')).all()
    return [(str(z[0]), int(z[1])) for z in zeilen]


def eindeutigkeit_sichern(conn, tabellen: set[str] | None = None) -> list[str]:
    """Legt die Unique-Indizes aus `EINDEUTIG` an. Gibt die gesetzten zurück.

    Findet sich ein Wert doppelt, scheitert das Anlegen — dann wird der
    Doppel-Wert protokolliert, statt still nichts zu tun. Entfernt wird
    nichts: welcher der beiden Einträge weg soll, entscheidet der Nutzer.
    """
    gesetzt: list[str] = []
    for tabelle, spalte, name in EINDEUTIG:
        if tabellen is not None and tabelle not in tabellen:
            continue
        doppel = _doppel(conn, tabelle, spalte)
        if doppel:
            log.warning("%s.%s ist nicht eindeutig — kein Index. Mehrfach: %s",
                        tabelle, spalte,
                        ", ".join(f"{w} ({n}x)" for w, n in doppel[:10]))
            continue
        conn.execute(text(f'CREATE UNIQUE INDEX IF NOT EXISTS "{name}" '
                          f'ON "{tabelle}" ("{spalte}")'))
        gesetzt.append(name)
    return gesetzt


def migriere(engine: Engine) -> list[str]:
    """Ergänzt fehlende Spalten. Gibt die durchgeführten Änderungen zurück."""
    inspector = inspect(engine)
    bestehende = set(inspector.get_table_names())
    geaendert: list[str] = []

    with engine.begin() as conn:
        for tabelle in SQLModel.metadata.sorted_tables:
            if tabelle.name not in bestehende:
                continue  # create_all hat sich darum gekümmert
            vorhanden = {s["name"] for s in inspector.get_columns(tabelle.name)}
            for spalte in tabelle.columns:
                if spalte.name in vorhanden:
                    continue
                typ = spalte.type.compile(engine.dialect)
                # Bewusst ohne NOT NULL: bestehende Zeilen haben keinen Wert.
                conn.execute(text(
                    f'ALTER TABLE "{tabelle.name}" ADD COLUMN "{spalte.name}" {typ}'))
                vorgabe = _sql_vorgabe(spalte)
                if vorgabe is not None:
                    conn.execute(text(
                        f'UPDATE "{tabelle.name}" SET "{spalte.name}" = {vorgabe} '
                        f'WHERE "{spalte.name}" IS NULL'))
                geaendert.append(f"{tabelle.name}.{spalte.name}")

        # Erst nach den Spalten: der Index braucht die Tabelle, wie sie
        # danach aussieht.
        try:
            geaendert += indizes_sichern(conn, bestehende)
            geaendert += eindeutigkeit_sichern(conn, bestehende)
        except Exception as fehler:                   # noqa: BLE001
            # Ein fehlender Index darf den Start nicht verhindern — die Sperre
            # im Code greift weiter, der Betrieb geht ohne ihn.
            log.warning("Eindeutigkeit nicht gesetzt: %s", fehler)

    if geaendert:
        log.info("Schema ergänzt: %s", ", ".join(geaendert))
    return geaendert
