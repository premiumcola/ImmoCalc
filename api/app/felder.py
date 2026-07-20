"""Was ein geleertes Formularfeld bedeutet.

Die Oberfläche schickt für ein geleertes Feld `null` — anders liesse sich ein
einmal gesetztes Enddatum nie wieder entfernen. Für das Datenmodell ist das
aber zweierlei:

* `Optional[date]`, `Optional[float]` — dort ist `None` ein gültiger Wert und
  heisst schlicht „nicht erfasst".
* `float = 0.0`, `str = ""` — dort ist `None` ungültig. Gemeint ist trotzdem
  „leer", und das ist bei diesen Feldern der Vorgabewert.

Ohne diese Unterscheidung antwortet die API auf ein geleertes Betragsfeld mit
einem Validierungsfehler, und der Nutzer kann eine einmal eingetragene
Stellplatzmiete nie wieder loswerden.
"""
from __future__ import annotations

from types import UnionType
from typing import Any, Type, Union, get_args, get_origin

from sqlmodel import SQLModel


def darf_leer_sein(modell: Type[SQLModel], feld: str) -> bool:
    """Verträgt dieses Feld ein `None`?"""
    info = modell.model_fields.get(feld)
    if info is None:
        return False
    annotation = info.annotation
    if annotation is None or annotation is type(None):
        return True
    # Optional[X] ist Union[X, None] — sowohl als typing.Union als auch als
    # neue Schreibweise `X | None`.
    if get_origin(annotation) in (Union, UnionType):
        return type(None) in get_args(annotation)
    return False


def vorgabe_fuer(modell: Type[SQLModel], feld: str) -> Any:
    """Der Wert, der „leer" bei einem Pflichtfeld bedeutet."""
    info = modell.model_fields.get(feld)
    if info is None:
        return None
    if info.default is not None and repr(info.default) != "PydanticUndefined":
        return info.default
    if info.default_factory is not None:
        return info.default_factory()
    # Kein Vorgabewert hinterlegt: aus dem Typ ableiten, was „nichts" ist.
    return {float: 0.0, int: 0, str: "", bool: False}.get(info.annotation)


def bereinige(modell: Type[SQLModel], felder: dict) -> dict:
    """Übersetzt `null` aus dem Formular in das, was das Modell erwartet."""
    sauber = {}
    for name, wert in felder.items():
        if wert is None and not darf_leer_sein(modell, name):
            wert = vorgabe_fuer(modell, name)
        sauber[name] = wert
    return sauber
