"""Einstellungen der E-Tankstelle: der schmale Zugriff auf ``Einstellung``.

Alle Werte liegen in der vorhandenen Schlüssel/Wert-Ablage. Eigene Namensräume
(``tankstelle_*``) — kein bestehender Schlüssel wird angefasst."""
from __future__ import annotations

import json
import logging
from datetime import date

from sqlmodel import Session

from ..cloudkern import _lies
from ..models import Einstellung

log = logging.getLogger("immocalc")

# N165 Teil 2 — der Schalter „automatische Abrechnung" je Objekt. Standardmässig
# aus: verschickt wird nur, was der Nutzer bewusst freigegeben hat.
S_AUTOVERSAND = "tankstelle_autoversand"
# Die Mehrnutzer-Zuordnung je Objekt: Zeitraum-Regeln und ausgeschlossene
# Ladungen, als JSON in einer Einstellung.
S_ZUORDNUNG = "tankstelle_zuordnung"


def _setze(session: Session, schluessel: str, wert: str) -> None:
    """Eine Einstellung setzen (anlegen oder überschreiben) — ohne commit."""
    e = session.get(Einstellung, schluessel)
    if e is None:
        e = Einstellung(schluessel=schluessel, wert=wert)
    else:
        e.wert = wert
    session.add(e)


def autoversand_aktiv(session: Session, slug: str) -> bool:
    """Ist der automatische Versand für dieses Objekt eingeschaltet? Default aus."""
    return _lies(session, f"{S_AUTOVERSAND}:{slug}") == "1"


def _regel_pruefen(regel: dict, nach_id: dict[int, dict]) -> dict | None:
    """Eine rohe Regel aus der Einstellung in ``{nutzer_id, von, bis}`` mit
    ``date``-Rändern übersetzen — unbrauchbare Regeln fallen still weg.

    Eine kaputte gespeicherte Regel darf die Abrechnung nicht zum Absturz
    bringen: fehlt ein Feld oder liegt das Ende vor dem Beginn, wird sie
    übergangen (und beim nächsten Speichern von der Oberfläche berichtigt)."""
    try:
        nid = int(regel.get("nutzer_id"))
        von = date.fromisoformat(regel["von"])
        bis = date.fromisoformat(regel["bis"])
    except (TypeError, ValueError, KeyError):
        return None
    if nid not in nach_id or bis < von:
        return None
    return {"nutzer_id": nid, "von": von, "bis": bis}


def zuordnung_lesen(session: Session, slug: str,
                    nutzer: list[dict]) -> tuple[list[dict], set[int]]:
    """Die Mehrnutzer-Zuordnung eines Objekts: geprüfte Zeitraum-Regeln und die
    Menge ausgeschlossener Ladungs-Ids.

    Unlesbares JSON ergibt eine leere Zuordnung und einen Log-Eintrag — nie
    einen Fehler, der die Abrechnung anhält. Regeln auf gelöschte Nutzer fallen
    weg (`nutzer` ist die aktuelle Liste)."""
    roh = _lies(session, f"{S_ZUORDNUNG}:{slug}")
    if not roh:
        return [], set()
    try:
        daten = json.loads(roh)
    except ValueError:
        log.warning("Zuordnung der E-Tankstelle (%s) unlesbar — übergangen", slug)
        return [], set()
    if not isinstance(daten, dict):
        return [], set()
    nach_id = {n["id"]: n for n in nutzer}
    regeln = [g for g in (_regel_pruefen(r, nach_id)
                          for r in daten.get("regeln", []) if isinstance(r, dict))
              if g is not None]
    ausschluss = {int(x) for x in daten.get("ausschluss", [])
                  if isinstance(x, (int, str)) and str(x).lstrip("-").isdigit()}
    return regeln, ausschluss
