"""Der eine Filter-Prädikat für Dokumentenlisten.

`_dokument_passt` ist die einzige Wahrheit darüber, ob ein Beleg zu einer
Auswahl gehört — genutzt von der Liste, ihrer Kostenart-Facette und der
Sammelaktion „zurück ins Warten" (`warte_archiv`). Rein: prüft nur Attribute
eines `Dokument`, fasst weder Datenbank noch Cloud an.
"""
from __future__ import annotations

from ..kostenarten import _fold
from ..kostenarten import normalisieren as kostenart_normalisieren
from .namen import _ist_sidecar


def _ki_werte(wert) -> list[str]:
    """Alle Texte in einem verschachtelten `ki_felder`-Wert (dict/list/Skalar)."""
    if isinstance(wert, dict):
        werte = []
        for schluessel, unterwert in wert.items():
            werte.append(str(schluessel))
            werte.extend(_ki_werte(unterwert))
        return werte
    if isinstance(wert, (list, tuple, set)):
        werte = []
        for unterwert in wert:
            werte.extend(_ki_werte(unterwert))
        return werte
    return [str(wert)] if wert not in (None, "") else []


def _heuhaufen(d) -> str:
    """Alles, worüber ein Beleg gefunden werden kann: Dateiname, Kostenart
    und die KI-Auslese (Einordnung, Immobilie, Einheit, alle Felderwerte) —
    gefaltet wie überall sonst im Projekt. Vorher zählte nur der Dateiname;
    ein Suchbegriff, der nur im erkannten Text stand, fand nichts (N328)."""
    teile = [d.dateiname, d.kostenart, d.ki_einordnung, d.ki_immobilie, d.ki_einheit]
    teile.extend(_ki_werte(d.ki_felder or {}))
    return _fold(" ".join(t for t in teile if t))


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
            and (not begriff or _fold(begriff) in _heuhaufen(d)))
