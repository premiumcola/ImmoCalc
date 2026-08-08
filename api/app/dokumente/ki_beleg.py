"""Was die KI-Auslese am Beleg hinterlässt — festhalten und wieder hervorholen.

Ein KI-Aufruf kostet Geld und Zeit. Deshalb wandert jedes Ergebnis an den
Beleg (`_ki_am_beleg_festhalten`: Einordnung, Raster, Immobilie, Einheit) und
kommt beim nächsten Ansehen von dort zurück (`_ki_aus_db`, N98) — neu gelesen
wird nur, wenn der Nutzer es ausdrücklich verlangt.

Zwei Regeln gelten dabei durchweg: ein leeres Feld überschreibt nie einen
vorhandenen Wert, und das Raster wird nur nachgezogen, wenn die KI wirklich
lief — die blosse Heuristik liefert keine Felder und darf ein vorhandenes
Raster nicht leeren.

Dazu zwei Beigaben, die am selben Ort entstehen: `_pruefsumme_nachtragen`
(N296 — wer die Bytes ohnehin in der Hand hat, hält den SHA1 gleich fest) und
`_rechnungssumme` (N103 — bei einer auf mehrere Positionen aufgeteilten
Rechnung die Summe des Ganzen, nicht nur des Buchungsanteils).

Reine Datenbank-Arbeit; die Bytes holt der Router (`_hole_beleg_bytes`).
"""
from __future__ import annotations

import logging

from sqlmodel import Session, select

from ..bezeichnung import ohne_betrag, ohne_datum
from ..kostenarten import normalisieren as kostenart_normalisieren
from ..models import Dokument, Kostenposition

log = logging.getLogger("immocalc")


def _pruefsumme_nachtragen(session: Session, d: Dokument, sha1: str) -> None:
    """N296 — die Prüfsumme am Beleg festhalten, sobald sie ohnehin errechnet
    ist. Der Abgleich trägt sie im 2-Minuten-Takt nach (N290), aber wer einen
    Beleg ansieht, hat die Bytes gerade in der Hand — dann kostet es nichts."""
    if not sha1 or d.sha1 == sha1:
        return
    d.sha1 = sha1
    session.add(d)
    try:
        session.commit()
    except Exception as fehler:                            # noqa: BLE001
        session.rollback()
        log.info("Prüfsumme an Beleg %s nicht gespeichert: %s", d.id, fehler)


def _ki_am_beleg_festhalten(session: Session, d: Dokument, ergebnis: dict) -> bool:
    """Hält die frische KI-Auslese am Beleg fest — nur, wo die KI wirklich etwas
    geliefert hat (CCLXXIII/CCCLXVII).

    Die (jetzt mehrsätzige) Zusammenfassung steht als `ki_einordnung`, das
    Raster als `ki_felder`/`ki_immobilie`/`ki_einheit`. So sieht der Nutzer die
    Einschätzung später wieder, ohne den Beleg erneut lesen zu lassen. Ein
    leeres Feld überschreibt nie einen vorhandenen Wert; nur was sich wirklich
    ändert, wird geschrieben. Gibt zurück, ob etwas geändert wurde."""
    geaendert = False
    einordnung = (ergebnis.get("einordnung") or "").strip()
    if einordnung and einordnung != (d.ki_einordnung or ""):
        d.ki_einordnung = einordnung
        geaendert = True
    # Das Raster nur nachziehen, wenn die KI-Auslese wirklich lief (`ki`) — die
    # reine Heuristik liefert keine Felder und soll ein vorhandenes Raster nicht
    # leeren.
    if ergebnis.get("ki"):
        felder = ergebnis.get("felder")
        if isinstance(felder, dict) and felder != (d.ki_felder or {}):
            d.ki_felder = felder
            geaendert = True
        immobilie = (ergebnis.get("immobilie") or "").strip()
        if immobilie and immobilie != (d.ki_immobilie or ""):
            d.ki_immobilie = immobilie
            geaendert = True
        einheit = (ergebnis.get("einheit") or "").strip()
        if einheit and einheit != (d.ki_einheit or ""):
            d.ki_einheit = einheit
            geaendert = True
    if geaendert:
        session.add(d)
        session.commit()
    return geaendert


def _rechnungssumme(session: Session, d: Dokument) -> float | None:
    """N103 — die Summe der ganzen Rechnung, wenn ein Beleg auf mehrere
    Positionen aufgeteilt ist.

    Ein Wasser-Bescheid trägt drei Gebühren (Frisch-, Schmutz-, Niederschlags-
    wasser). Verbucht wird der Beleg auf der Frischwasser-Position, sein
    `betrag` ist deshalb nur ein Drittel der Rechnung — im Beleg-Fenster wirkt
    das wie ein Lesefehler. Hier kommt die Summe der zusammengehörigen
    Positionen desselben Zeitraums dazu. `None`, wenn es nichts zu summieren
    gibt (dann zeigt die Oberfläche nur den Betrag)."""
    if not d.zeitraum_id or not (d.kostenart or "").strip():
        return None
    geschwister = ("Wasser", "Abwasser", "Niederschlagswasser")
    if kostenart_normalisieren(d.kostenart) not in geschwister:
        return None
    summe = sum(p.betrag or 0.0 for p in session.exec(
        select(Kostenposition).where(
            Kostenposition.zeitraum_id == d.zeitraum_id)).all()
        if kostenart_normalisieren(p.kostenart) in geschwister)
    summe = round(summe, 2)
    return summe if summe > 0 and summe != round(d.betrag or 0.0, 2) else None


def _ki_aus_db(d: Dokument, session: Session | None = None) -> dict | None:
    """N98 — die schon gespeicherte KI-Auslese eines Belegs, wenn sie taugt.

    Ein KI-Aufruf kostet Geld und Zeit; das Ergebnis steht bereits am Beleg
    (`ki_einordnung`/`ki_felder`/`ki_immobilie`, dazu Betrag und Belegdatum).
    Wer denselben Beleg erneut ansieht, soll die gespeicherte Einschätzung
    bekommen statt eines neuen Aufrufs — neu gelesen wird nur ausdrücklich über
    `/neu-analysieren`. `None`, solange noch nichts gespeichert ist."""
    if not (d.ki_einordnung or d.ki_felder):
        return None
    return {
        "betrag": d.betrag, "datum": d.belegdatum.isoformat() if d.belegdatum else None,
        "jahr": d.jahr, "kategorie": d.kategorie, "kostenart": d.kostenart,
        # Eine eigene „Bezeichnung" gibt es am Dokument nicht — sie steckt im
        # Dateinamen (ohne Datums- und Betragsteil, siehe `bezeichnung.py`).
        "sache": ohne_betrag(ohne_datum(d.dateiname or "")).strip(" _-"),
        "zusammenfassung": d.ki_einordnung,
        "einordnung": d.ki_einordnung, "immobilie": d.ki_immobilie,
        "einheit": getattr(d, "ki_einheit", "") or "",
        "felder": d.ki_felder or {}, "ki": True, "aus_db": True,
        # N103 — bei aufgeteilten Rechnungen (Wasser: drei Gebühren) die
        # Summe der ganzen Rechnung mitgeben, nicht nur den Buchungsanteil.
        "rechnungssumme": _rechnungssumme(session, d) if session else None,
    }
