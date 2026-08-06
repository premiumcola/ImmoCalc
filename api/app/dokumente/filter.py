"""Der eine Filter-Prädikat für Dokumentenlisten.

`_dokument_passt` ist die einzige Wahrheit darüber, ob ein Beleg zu einer
Auswahl gehört — genutzt von der Liste, ihrer Kostenart-Facette und der
Sammelaktion „zurück ins Warten" (`warte_archiv`). Rein: prüft nur Attribute
eines `Dokument`, fasst weder Datenbank noch Cloud an.
"""
from __future__ import annotations

from ..kostenarten import normalisieren as kostenart_normalisieren
from .namen import _ist_sidecar


def _dokument_passt(d, *, ziel_id, kategorie, kostenart, jahr,
                    status, zeitraum, begriff) -> bool:
    """Ob ein Beleg in einen Filter passt — die eine Wahrheit für Liste,
    Facette und die Sammelaktion (`warte_archiv`). `.immocalc`-Steckbriefe
    fallen immer heraus; `kostenart=""` zählt über alle Kostenarten."""
    return (not _ist_sidecar(d.dateiname)
            and (not ziel_id or d.objekt_id == ziel_id)
            and (not kategorie or d.kategorie == kategorie)
            and (not kostenart
                 or kostenart_normalisieren(d.kostenart) == kostenart)
            and (jahr is None or d.jahr == jahr)
            and (not status or d.status == status)
            and (zeitraum is None or d.zeitraum_id == zeitraum)
            and (not begriff or begriff in d.dateiname.lower()))
