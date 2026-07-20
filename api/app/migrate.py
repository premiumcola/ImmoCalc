"""Leichtgewichtige Schema-Angleichung für SQLite.

`SQLModel.metadata.create_all` legt ausschliesslich fehlende *Tabellen* an —
neue *Spalten* an bereits bestehenden Tabellen bleiben unberuecksichtigt. Eine
gewachsene Datenbank wuerde dadurch beim ersten Zugriff brechen. Hier werden
fehlende Spalten nachgezogen, damit bestehende Daten erhalten bleiben.
"""
import logging

from sqlalchemy import Engine, inspect, text
from sqlmodel import SQLModel

log = logging.getLogger("immocalc")


def _sql_vorgabe(spalte) -> str | None:
    """SQL-Literal für den Default einer Spalte, falls es ein einfacher Wert ist."""
    default = getattr(spalte, "default", None)
    if default is None or getattr(default, "is_callable", False):
        return None
    wert = getattr(default, "arg", None)
    if isinstance(wert, bool):
        return "1" if wert else "0"
    if isinstance(wert, (int, float)):
        return str(wert)
    if isinstance(wert, str):
        return "'" + wert.replace("'", "''") + "'"
    return None


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

    if geaendert:
        log.info("Schema ergänzt: %s", ", ".join(geaendert))
    return geaendert
