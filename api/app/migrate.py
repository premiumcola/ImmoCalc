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
