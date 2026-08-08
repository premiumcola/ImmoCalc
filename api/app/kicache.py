"""N296 — Zwischenspeicher der KI-Auslese, am Dateiinhalt festgemacht.

Warum überhaupt: ein KI-Aufruf kostet Budget des Nutzers. Gespeichert war die
Auslese bisher nur am `Dokument` (N98), also an der Eintragsnummer. Dieselbe
Datei ein zweites Mal in der App — erneut gescannt, als Duplikat in einem
zweiten Objektordner, oder nach einem Grabstein neu aufgenommen — bekam eine
neue Nummer und wurde noch einmal bezahlt gelesen.

Der Schlüssel ist der SHA1 des Inhalts. Byte-gleich heisst wortgleich; was die
KI aus diesen Bytes gelesen hat, gilt für jede Kopie davon.

Die Reihenfolge beim Ansehen eines Belegs ist damit:

    1. die am Beleg gespeicherte Auslese      (N98 — unverändert)
    2. der Zwischenspeicher zu seinem SHA1    (N296 — neu)
    3. erst dann die KI                        (kostet)

Bewusst nur ein Zwischenspeicher: geht er verloren, geht keine Information
verloren, nur Budget beim nächsten Lesen. Deshalb schluckt jede Funktion hier
ihre Fehler — ein hakender Zwischenspeicher darf nie einen Beleg blockieren.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import date

from sqlmodel import Session, select

from .models import KiAuslese

log = logging.getLogger("immocalc")

# Was nicht in den Zwischenspeicher gehört: eine Auslese, die gar nichts
# gefunden hat. Sie würde einen späteren, besseren Lauf für immer verhindern.
_MINDESTENS = ("einordnung", "felder", "betrag", "datum", "kategorie",
               "kostenart", "immobilie")


def pruefsumme(inhalt: bytes) -> str:
    """Der Schlüssel zu einem Dateiinhalt — dieselbe Rechnung wie in der Cloud
    (`nextcloud._sha1_aus_checksums`) und beim Ablegen eines Scans."""
    return hashlib.sha1(inhalt).hexdigest()


def _taugt(ergebnis: dict | None) -> bool:
    """Hat die Auslese überhaupt etwas ergeben?

    Ein leeres Ergebnis zu merken wäre schädlich: der Beleg käme nie wieder an
    die KI, obwohl beim nächsten Mal (besseres Modell, ergänzter Prompt) etwas
    herauskommen könnte."""
    if not isinstance(ergebnis, dict):
        return False
    return any(ergebnis.get(feld) for feld in _MINDESTENS)


def hole(session: Session, sha1: str) -> dict | None:
    """Die gespeicherte Auslese zu diesem Inhalt — oder `None`.

    Zählt den Treffer mit; das ist die einzige Stelle, an der sich ablesen
    lässt, wie viele Aufrufe der Zwischenspeicher erspart hat."""
    if not sha1:
        return None
    try:
        eintrag = session.exec(
            select(KiAuslese).where(KiAuslese.sha1 == sha1)).first()
        if eintrag is None or not _taugt(eintrag.ergebnis):
            return None
        eintrag.treffer = (eintrag.treffer or 0) + 1
        session.add(eintrag)
        session.commit()
        log.info("KI-Auslese aus dem Zwischenspeicher (%s…, %d. Treffer)",
                 sha1[:8], eintrag.treffer)
        return dict(eintrag.ergebnis)
    except Exception as fehler:                            # noqa: BLE001
        session.rollback()
        log.info("Zwischenspeicher nicht lesbar (%s): %s", sha1[:8], fehler)
        return None


def merke(session: Session, sha1: str, ergebnis: dict, modell: str = "") -> bool:
    """Eine frische Auslese unter ihrem Inhalt ablegen. `True`, wenn gespeichert.

    Ein vorhandener Eintrag wird ÜBERSCHRIEBEN, wenn die neue Auslese taugt —
    ein ausdrückliches „neu analysieren" soll den alten Stand ersetzen, sonst
    bliebe der Nutzer für immer an der ersten, schlechteren Lesung hängen."""
    if not sha1 or not _taugt(ergebnis):
        return False
    try:
        eintrag = session.exec(
            select(KiAuslese).where(KiAuslese.sha1 == sha1)).first()
        if eintrag is None:
            eintrag = KiAuslese(sha1=sha1)
        eintrag.ergebnis = ergebnis
        eintrag.modell = modell or eintrag.modell
        eintrag.erfasst_am = date.today()
        session.add(eintrag)
        session.commit()
        return True
    except Exception as fehler:                            # noqa: BLE001
        session.rollback()
        log.info("Auslese nicht zwischengespeichert (%s): %s", sha1[:8], fehler)
        return False


def stand(session: Session) -> dict:
    """Auskunft für die Einstellungen: wie viel der Zwischenspeicher trägt."""
    try:
        eintraege = session.exec(select(KiAuslese)).all()
    except Exception:                                      # noqa: BLE001
        return {"eintraege": 0, "erspart": 0}
    return {"eintraege": len(eintraege),
            "erspart": sum(e.treffer or 0 for e in eintraege)}
