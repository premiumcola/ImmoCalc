"""N273 — Endpunkte für den WEG-Modus eines Abrechnungszeitraums.

Der Ablauf ist zweistufig wie beim Belegscan: erst **lesen** (`/weg/lesen` gibt
nur zurück, was es erkannt hat und speichert nichts), dann **übernehmen**
(`/weg/uebernehmen` bekommt das vom Nutzer bestätigte Ergebnis). So landet
nichts in der Abrechnung, was der Nutzer nicht gesehen hat — und ein
verlesenes „Ihre Kosten" fällt vor dem Anlegen auf, nicht danach.

Gerechnet wird hier nicht: das gehört in `app/weg.py`. Der Router sammelt ein,
reicht weiter und gibt zurück.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlmodel import Session

from .. import kiauslese, ocr, weg
from ..db import get_session
from ..models import WegVorauszahlung, Zeitraum
from ..verteilung import UnbekannterSchluessel
from .ki import ki_key, ki_modell
from .. import upload

log = logging.getLogger("immocalc")
router = APIRouter(prefix="/api", tags=["weg"])

# Eine Abrechnung sind drei Seiten PDF oder ein Handyfoto davon.
MAX_BYTES = 20 * 1024 * 1024

VON_HAND = ("Bitte die Positionen von Hand eintragen — die Datei bleibt "
            "unverändert.")


def _zeitraum(session: Session, zid: int) -> Zeitraum:
    z = session.get(Zeitraum, zid)
    if not z:
        raise HTTPException(404, "Zeitraum nicht gefunden")
    return z


# --------------------------------------------------------------------------
# Stand und Schalter
# --------------------------------------------------------------------------
@router.get("/zeitraeume/{zid}/weg")
def weg_stand(zid: int, session: Session = Depends(get_session)) -> dict:
    """Der WEG-Stand: Schalter, Summen, Positionen, Vorauszahlungsabschnitte.

    `stand` trägt neben den übernommenen Zeilen auch `direkt` (die von Hand
    eingetragenen NK-Summen des früheren Direkteintrags, N283 a) und die
    Hinweise `uebersprungen`/`entfernt` der letzten Übernahme (N283 e) — sie
    stehen hier und nicht nur in der Antwort auf `/uebernehmen`, damit sie ein
    Neuladen überleben."""
    z = _zeitraum(session, zid)
    return {"aktiv": bool(z.weg_modus), "stand": weg.stand(session, z),
            "vorauszahlungen": weg.abschnitte(session, z)}


class SchalterIn(BaseModel):
    aktiv: bool


@router.patch("/zeitraeume/{zid}/weg")
def weg_schalten(zid: int, data: SchalterIn,
                 session: Session = Depends(get_session)) -> dict:
    """Schaltet den WEG-Modus für diesen Zeitraum ein oder aus.

    Beim Ausschalten bleiben die übernommenen Positionen zunächst stehen — sie
    zu löschen wäre ein stiller Datenverlust. Wer sie loswerden will, nimmt sie
    einzeln zurück; der Schalter allein ändert nur die Ansicht."""
    z = _zeitraum(session, zid)
    z.weg_modus = data.aktiv
    session.add(z)
    session.commit()
    session.refresh(z)
    log.info("WEG-Modus für Zeitraum %s: %s", zid, "an" if data.aktiv else "aus")
    return {"aktiv": bool(z.weg_modus), "stand": weg.stand(session, z),
            "vorauszahlungen": weg.abschnitte(session, z)}


# --------------------------------------------------------------------------
# Schritt 1 — lesen. Speichert nichts.
# --------------------------------------------------------------------------
@router.post("/zeitraeume/{zid}/weg/lesen")
async def weg_lesen(zid: int, datei: UploadFile = File(...),
                    session: Session = Depends(get_session)) -> dict:
    """Liest eine WEG-Einzelabrechnung — und legt nichts an.

    Rückgabe `{"gelesen": {...}|null, "hinweis": "…"}`. Fällt die Erkennung aus
    (keine KI eingerichtet, kein Text im PDF, unbrauchbare Antwort), ist das
    kein Fehler: `gelesen` bleibt leer und der Hinweis sagt, was zu tun ist."""
    _zeitraum(session, zid)
    # N292 — Leere und Grösse prüft `upload.lies` für alle Endpunkte gleich.
    rohdaten = await upload.lies(datei, max_bytes=MAX_BYTES,
                                 was="Die WEG-Abrechnung")

    schluessel = ki_key(session)
    if not kiauslese.verfuegbar(schluessel):
        return {"gelesen": None,
                "hinweis": "Die Belegerkennung ist nicht eingerichtet. " + VON_HAND}

    text = ocr.text_aus_beleg(rohdaten)
    if not (text or "").strip():
        return {"gelesen": None,
                "hinweis": "Aus dieser Datei ließ sich kein Text lesen. " + VON_HAND}

    # N330 — die Betriebskostentabelle verliert beim Text-Auszug aus dem PDF
    # bei manchen Belegen Trennzeichen und einzelne Ziffern; das Seitenbild
    # daneben lässt das Modell die echten Zeichen lesen statt zu raten. Kein
    # PDF oder keine Rasterbibliothek geben still eine leere Liste zurück —
    # dann läuft die Erkennung wie zuvor rein textbasiert weiter.
    bilder = ocr.seiten_als_png(rohdaten)

    gelesen = kiauslese.lies_weg_abrechnung(text, datei.filename or "",
                                            schluessel=schluessel,
                                            modell=ki_modell(session),
                                            bilder=bilder)
    if not gelesen:
        return {"gelesen": None,
                "hinweis": "Die Abrechnung konnte nicht gelesen werden. " + VON_HAND}
    return {"gelesen": gelesen, "hinweis": gelesen.get("warnung", "")}


# --------------------------------------------------------------------------
# Schritt 2 — übernehmen. Erst jetzt entstehen Kostenpositionen.
# --------------------------------------------------------------------------
class WegPositionIn(BaseModel):
    bezeichnung: str = ""
    gesamtkosten: Optional[float] = None
    ihre_kosten: Optional[float] = None
    schluessel: str = ""
    umlagefaehig: bool = True
    # N351 — haushaltsnahe Dienstleistung/Handwerkerleistung nach § 35a EStG;
    # `s35a` ist die Schreibweise der KI-Auslese, `s35` die des Datenmodells.
    s35: bool = False
    s35a: bool = False


class WegBelegIn(BaseModel):
    """Das vom Nutzer bestätigte Leseergebnis. Alle Felder optional — der
    Nutzer darf jede Zahl vor dem Übernehmen korrigiert haben."""
    firma: str = ""
    liegenschaft: str = ""
    nutzer_nr: str = ""
    von: Optional[str] = None
    bis: Optional[str] = None
    datum: Optional[str] = None
    positionen: list[WegPositionIn] = []
    heizkosten: Optional[float] = None
    warmwasserkosten: Optional[float] = None
    betriebskosten: Optional[float] = None
    rechnungsbetrag: Optional[float] = None
    vorauszahlung: Optional[float] = None
    nachzahlung: Optional[float] = None
    warnung: str = ""
    # Auf welche Einheit die Abrechnung geht. Genannt trägt sie den Posten zu
    # 100 % — der Regelfall, denn die WEG-Abrechnung gilt für genau eine Wohnung.
    einheit: str = ""


@router.post("/zeitraeume/{zid}/weg/uebernehmen")
def weg_uebernehmen(zid: int, data: WegBelegIn,
                    session: Session = Depends(get_session)) -> dict:
    """Legt aus dem bestätigten Beleg die Kostenpositionen an.

    Nicht umlagefähige Positionen entstehen dabei **nie** — sie bleiben im
    aufbewahrten Beleg und kommen unter `stand.nicht_umlagefaehig` zurück.
    Ein zweiter Aufruf schreibt dieselben Zeilen fort statt sie zu verdoppeln;
    von Hand gepflegte Positionen bleiben unangetastet."""
    z = _zeitraum(session, zid)
    gelesen = data.model_dump()
    einheit = (gelesen.pop("einheit", "") or "").strip()
    try:
        ergebnis = weg.uebernehmen(session, z, gelesen, einheit=einheit)
    except UnbekannterSchluessel as fehler:
        raise HTTPException(400, str(fehler)) from fehler
    return {"aktiv": True, "stand": ergebnis,
            "vorauszahlungen": weg.abschnitte(session, z)}


# --------------------------------------------------------------------------
# Vorauszahlung des Mieters — in Abschnitten, weil sie sich unterjährig ändert.
# --------------------------------------------------------------------------
class VorauszahlungIn(BaseModel):
    einheit: str = ""
    von: Optional[date] = None
    bis: Optional[date] = None
    betrag_monat: float = 0.0


@router.post("/zeitraeume/{zid}/weg/vorauszahlung", status_code=201)
def vorauszahlung_anlegen(zid: int, data: VorauszahlungIn,
                          session: Session = Depends(get_session)) -> dict:
    """Ein weiterer Abschnitt — z. B. „ab Juli 235 € statt 220 €"."""
    z = _zeitraum(session, zid)
    v = weg.vorauszahlung_setzen(session, z, data.einheit, data.von, data.bis,
                                 data.betrag_monat)
    return {"id": v.id, "vorauszahlungen": weg.abschnitte(session, z),
            "summe": weg.vorauszahlung(session, z)}


@router.patch("/zeitraeume/{zid}/weg/vorauszahlung/{vid}")
def vorauszahlung_aendern(zid: int, vid: int, data: VorauszahlungIn,
                          session: Session = Depends(get_session)) -> dict:
    z = _zeitraum(session, zid)
    v = session.get(WegVorauszahlung, vid)
    if not v or v.zeitraum_id != zid:
        raise HTTPException(404, "Vorauszahlung nicht gefunden")
    weg.vorauszahlung_setzen(session, z, data.einheit, data.von, data.bis,
                             data.betrag_monat, vid=vid)
    return {"id": vid, "vorauszahlungen": weg.abschnitte(session, z),
            "summe": weg.vorauszahlung(session, z)}


@router.delete("/zeitraeume/{zid}/weg/vorauszahlung/{vid}")
def vorauszahlung_loeschen(zid: int, vid: int,
                           session: Session = Depends(get_session)) -> dict:
    """Entfernt einen Abschnitt — eine bewusste Nutzeraktion."""
    z = _zeitraum(session, zid)
    v = session.get(WegVorauszahlung, vid)
    if not v or v.zeitraum_id != zid:
        raise HTTPException(404, "Vorauszahlung nicht gefunden")
    session.delete(v)
    session.commit()
    return {"ok": True, "vorauszahlungen": weg.abschnitte(session, z),
            "summe": weg.vorauszahlung(session, z)}
