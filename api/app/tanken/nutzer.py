"""Nutzerliste der E-Tankstelle — Tabelle `Tanknutzer` (N164).

Bis N164 lagen die Nutzer als JSON in einer `Einstellung` — das trug nur Name
und E-Mail. Für die Quartalsabrechnung braucht es Anschrift und Bankverbindung;
die gehören in eine eigene Tabelle. Der alte JSON-Schlüssel bleibt unangetastet
stehen (CLAUDE.md: nie löschen); sein Inhalt wird einmalig in die Tabelle
übernommen (:func:`_migriere_json_nutzer`)."""
from __future__ import annotations

import json
import logging

from fastapi import HTTPException
from sqlmodel import Session, select

from ..cloudkern import _lies
from ..models import Einstellung, Objekt, Tanknutzer

log = logging.getLogger("immocalc")

# Schlüssel der Nutzerliste — je Objekt einer. Eigener Namensraum, es wird kein
# bestehender Schlüssel angefasst.
S_NUTZER = "tankstelle_nutzer"


def schluessel(name: str) -> str:
    """Ein Name als Vergleichsschlüssel — die Brücke zwischen der Nutzerliste
    und den erfassten Ladungen.

    Beide führen den Namen als Text; „Marvin " und „marvin" sind dieselbe
    Person."""
    return " ".join((name or "").split()).casefold()


def _nutzer_schluessel(slug: str) -> str:
    return f"{S_NUTZER}:{slug}"


def _migriert_schluessel(slug: str) -> str:
    return f"{S_NUTZER}_migriert:{slug}"


def _json_nutzer_lesen(session: Session, slug: str) -> list[dict]:
    """Der alte JSON-Bestand (nur Name + E-Mail + Notiz). Unlesbares JSON ergibt
    eine leere Liste und einen Log-Eintrag; es wird nichts überschrieben."""
    roh = _lies(session, _nutzer_schluessel(slug))
    if not roh:
        return []
    try:
        daten = json.loads(roh)
    except ValueError:
        log.warning("Nutzerliste der E-Tankstelle (%s) unlesbar — übergangen",
                    slug)
        return []
    if not isinstance(daten, list):
        return []
    liste = []
    for eintrag in daten:
        if not isinstance(eintrag, dict) or not str(eintrag.get("name", "")).strip():
            continue
        liste.append({"name": str(eintrag["name"]).strip(),
                      "email": str(eintrag.get("email", "")).strip(),
                      "notiz": str(eintrag.get("notiz", "")).strip()})
    return liste


def _migriere_json_nutzer(session: Session, o: Objekt) -> None:
    """Den alten JSON-Bestand einmalig in die Tabelle übernehmen.

    Läuft genau einmal je Objekt (ein Marker in der Einstellungs-Ablage sperrt
    weitere Läufe). So wird ein gelöschter Nutzer nicht bei der nächsten Lesung
    aus dem alten JSON wieder auferstehen. Der JSON-Schlüssel selbst bleibt
    unangetastet stehen — er wird nur gelesen, nie überschrieben."""
    if _lies(session, _migriert_schluessel(o.slug)):
        return
    schon_da = session.exec(select(Tanknutzer).where(
        Tanknutzer.objekt_id == o.id)).first()
    if schon_da is None:
        for e in _json_nutzer_lesen(session, o.slug):
            session.add(Tanknutzer(objekt_id=o.id, name=e["name"],
                                   email=e["email"], notiz=e["notiz"]))
        log.info("E-Tankstelle %s: alte Nutzerliste in die Tabelle übernommen",
                 o.slug)
    session.add(Einstellung(schluessel=_migriert_schluessel(o.slug), wert="1"))
    session.commit()


def _nutzer_dict(n: Tanknutzer) -> dict:
    """Ein Tanknutzer als das dict, mit dem die Rechen- und Anzeigelogik
    arbeitet — dieselben Schlüssel wie früher der JSON-Eintrag, plus die
    Stammdaten für den Versand."""
    return {"id": n.id, "name": n.name, "email": n.email or "",
            "person_id": n.person_id,
            "strasse": n.strasse or "", "plz": n.plz or "", "ort": n.ort or "",
            "iban": n.iban or "", "bic": n.bic or "",
            "kontoinhaber": n.kontoinhaber or "", "notiz": n.notiz or "",
            # N170 — das E-Auto und sein Verbrauch (0 = noch nicht gesetzt).
            "e_auto_modell": getattr(n, "e_auto_modell", "") or "",
            "verbrauch_kwh_100km": getattr(n, "verbrauch_kwh_100km", 0.0) or 0.0}


def nutzer_lesen(session: Session, objekt: Objekt | str) -> list[dict]:
    """Die Nutzer eines Objekts aus der Tabelle — vor dem ersten Lesen wird der
    alte JSON-Bestand einmalig übernommen.

    Nimmt ein :class:`Objekt` **oder** einen Slug: die eigenen Endpunkte reichen
    das aufgelöste Objekt herein, fremde Aufrufer (``routers/zaehler``) nur den
    Slug. Ein unbekannter Slug ergibt eine leere Liste statt eines Fehlers."""
    o = objekt
    if isinstance(o, str):
        o = session.exec(select(Objekt).where(Objekt.slug == o)).first()
        if o is None:
            return []
    _migriere_json_nutzer(session, o)
    liste = session.exec(select(Tanknutzer).where(
        Tanknutzer.objekt_id == o.id, Tanknutzer.aktiv == True)  # noqa: E712
        .order_by(Tanknutzer.id)).all()
    return [_nutzer_dict(n) for n in liste]


def _pruefe_name(name: str, liste: list[dict], eigene_id: int = 0) -> str:
    """Ein Name muss da und eindeutig sein — sonst lässt sich eine Ladung
    keiner Person zuordnen."""
    sauber = " ".join((name or "").split())
    if not sauber:
        raise HTTPException(400, "Der Nutzer braucht einen Namen.")
    if any(schluessel(n["name"]) == schluessel(sauber) and n["id"] != eigene_id
           for n in liste):
        raise HTTPException(400, f"„{sauber}“ steht schon in der Liste.")
    return sauber


def _pruefe_email(email: str) -> str:
    """Locker geprüft: eine Adresse ohne @ ist mit Sicherheit keine. Leer ist
    erlaubt — verschickt wird dann eben nichts."""
    sauber = (email or "").strip()
    if sauber and ("@" not in sauber or " " in sauber):
        raise HTTPException(400, f"„{sauber}“ sieht nicht wie eine "
                                 "E-Mail-Adresse aus.")
    return sauber
