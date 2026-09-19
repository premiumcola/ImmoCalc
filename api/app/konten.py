"""N501 — E-Mail am Familienzugang und die Frage, wer Administrator ist.

Bewusst ohne FastAPI, wie `auth.py` und `totp.py`: die Regeln sollen sich
prüfen lassen, ohne einen Request zu bauen.

Zur Einordnung: die App ist ab hier „nur mit Einladung". Der Administrator
stellt eine Einladung auf eine E-Mail-Adresse aus, und genau diese Adresse
landet beim Registrieren am Zugang — sie ist damit eine Angabe des Betreibers
und keine selbst behauptete. Beim Anmelden wird sie mitgeprüft.
"""
from __future__ import annotations

import logging
import os
import re

from sqlalchemy import func
from sqlmodel import Session, select

from .models import Familie

log = logging.getLogger("immocalc")

# Absichtlich grob. Eine Adresse wirklich zu prüfen geht nur mit einem
# Zustellversuch — RFC 5322 erlaubt mehr, als ein Ausdruck abbilden kann, und
# jeder strengere Ausdruck lehnt irgendwann eine echte Adresse ab. Geprüft
# wird nur, was Tippfehler abfängt: genau ein @, etwas davor, ein Punkt danach.
_FORM = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")

MAX_EMAIL = 254          # RFC 5321 §4.5.3.1.3 — die Obergrenze eines Pfades


def email_normalisieren(roh: str | None) -> str | None:
    """Klein geschrieben und ohne Rand-Leerzeichen — „R.Oman@GMX.de" und
    „r.oman@gmx.de " sind dieselbe Adresse. Leer wird zu `None`, damit ein
    leeres Formularfeld nicht als Adresse „" in der Datenbank landet.

    Der lokale Teil ist nach RFC theoretisch gross-/kleinschreibungssensitiv;
    kein Anbieter von Rang behandelt ihn so, und zwei Zugänge nach Schreibweise
    zu trennen wäre hier eine Falle statt einer Eigenschaft."""
    if roh is None:
        return None
    sauber = roh.strip().lower()
    return sauber or None


def email_gueltig(email: str | None) -> bool:
    return bool(email) and len(email) <= MAX_EMAIL and bool(_FORM.match(email))


def nach_email(session: Session, email: str | None) -> Familie | None:
    """Vergleich über `lower()` in der Datenbank statt über den Index-Wert
    allein: ein Bestand, der vor der Normalisierung angelegt wurde, könnte
    noch Grossbuchstaben tragen."""
    if not email:
        return None
    return session.exec(select(Familie).where(
        func.lower(Familie.email) == email.strip().lower())).first()


def email_frei(session: Session, email: str | None,
               ausser_id: int | None = None) -> bool:
    """Zwei Zugänge mit derselben Adresse wären beim Zurücksetzen des
    Passworts nicht mehr auseinanderzuhalten — die Mail ginge an beide."""
    vorhanden = nach_email(session, email)
    return vorhanden is None or vorhanden.id == ausser_id


def admin_sicherstellen(session: Session) -> Familie | None:
    """Sorgt dafür, dass es genau einen Administrator gibt — beim Start,
    idempotent, ohne Zutun des Nutzers.

    Reihenfolge: gibt es schon einen, bleibt es dabei (nie still umhängen —
    sonst verlöre ein Betreiber seine Verwaltung, weil jemand eine Umgebungs-
    variable geändert hat). Sonst entscheidet `ADMIN_FAMILIE`, und ohne diese
    Angabe die zuerst angelegte Familie: das ist der Zugang dessen, der die
    Installation aufgesetzt hat.

    Es wird nichts gelöscht und nichts überschrieben, nur ein Schalter von
    `False` auf `True` gesetzt."""
    vorhanden = session.exec(select(Familie).where(
        Familie.ist_admin == True)).first()                       # noqa: E712
    if vorhanden:
        return vorhanden

    gewuenscht = (os.getenv("ADMIN_FAMILIE") or "").strip()
    familie = None
    if gewuenscht:
        familie = session.exec(select(Familie).where(
            func.lower(Familie.name) == gewuenscht.lower())).first()
        if not familie:
            log.warning("ADMIN_FAMILIE=%r gesetzt, aber keine Familie mit "
                        "diesem Namen gefunden — nehme die erste.", gewuenscht)
    if not familie:
        familie = session.exec(select(Familie).order_by(Familie.id)).first()
    if not familie:
        return None           # frische Instanz, noch keine Familie

    familie.ist_admin = True
    session.add(familie)
    session.commit()
    log.info("Administratorkonto: %s", familie.name)
    return familie
