"""N436 — Namensraum für `Einstellung.schluessel`.

Nextcloud-Zugang, Postfach, KI-Schlüssel, Wallbox-Adresse und alle
objektbezogenen Versand-Marker (PV, E-Tankstelle) gehören seit der
Mandantentrennung einer Familie, nicht mehr der ganzen Instanz. Statt das
Schema von `Einstellung` zu ändern (ein zusammengesetzter Primärschlüssel auf
einer bestehenden SQLite-Tabelle ist nicht sicher per `ALTER TABLE`
nachrüstbar), bekommt der Schlüssel selbst den Namensraum vorangestellt —
dasselbe Prinzip, das `tanken/marker.py` und `pv/versand.py` für
Objekt/Jahr/Periode schon vorher genutzt haben, nur eine Ebene höher.

Der Namensraum wird über eine `ContextVar` transportiert statt als Parameter
durch jede Funktion gereicht: `verbindung()` (`cloudkern.py`) wird aus gut
einem Dutzend Modulen tief in Geschäftslogik aufgerufen (OCR, Ablage,
Benennung, PV-/Tankstellen-Versand, Objekt-Löschen …) — ein expliziter
`familie_id`-Parameter hätte sich durch jede dieser Ketten ziehen müssen.
`ContextVar` ist Task-sicher (anders als `threading.local`) und überlebt
Starlettes `run_in_threadpool` für synchrone Endpunkte korrekt — die
Standardlösung für genau diesen „aktueller Benutzer"-Fall.

Für HTTP-Anfragen setzt `deps.aktuelle_familie` den Kontext automatisch. Für
Hintergrundläufe ohne Sitzung (`wachdienst.py`) muss `setzen()` vor jedem
Verarbeitungsschritt für eine Familie von Hand aufgerufen werden — siehe
dort."""
from contextvars import ContextVar

_KONTEXT: ContextVar[int | None] = ContextVar("familienraum_kontext", default=None)


def setzen(familie_id: int | None) -> None:
    _KONTEXT.set(familie_id)


def aktuelle_id() -> int | None:
    return _KONTEXT.get()


def schluessel(basis: str) -> str:
    """Der tatsächliche Datenbank-Schlüssel: `<familie_id>:<basis>`.

    Ohne gesetzten Kontext (ein Hintergrundlauf, der `setzen()` vergessen hat)
    entsteht bewusst ein Schlüssel, den es nie geben wird (`?:…`) — lieber
    eine leere Einstellung als eine versehentlich geteilte."""
    fid = _KONTEXT.get()
    return f"{fid}:{basis}" if fid is not None else f"?:{basis}"
