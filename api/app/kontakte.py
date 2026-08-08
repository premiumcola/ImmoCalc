"""N309 — das Kontaktbuch: Firmen, Gewerke, Kundennummern.

Der Nutzer will „die Firmennamen aller Handwerker, Versicherer, unsere
Kundennummern und Kontaktdaten immobilienzugehörig" an einer Stelle — und
ausdrücklich: „Sammle alle Infos aus allen Belegen ein!"

Hier steht die Ernte und die Zusammenführung; die Endpunkte bleiben dünn
(`routers/kontakte.py`).

**Der Grundsatz dieser Datei: nie überschreiben, was der Nutzer gepflegt hat.**
Die Ernte läuft wiederholt — nach jedem neuen Beleg, nach jeder Renovierung.
Ein Lauf, der eine von Hand korrigierte Telefonnummer wieder durch die
schlechtere aus dem Beleg ersetzt, macht die Pflege sinnlos. Deshalb merkt sich
jeder Kontakt in `handgepflegt`, welche Felder ihm der Nutzer gegeben hat, und
die Ernte füllt nur, was leer ist.

Woher die Daten kommen — fünf Quellen, alle schon im Bestand:

* `Renovierungsposten.firma` + `.gewerk`  → Handwerker samt Gewerk
* `Versicherung.anbieter`                 → Versicherer
* `Kredit.bank`                           → Bank
* `Dokument.ki_felder`                    → Anbieter, Police-, Darlehensnummer
* `Belegdaten.anbieter` / `.felder`       → dasselbe aus der Wissensdatenbank
"""
from __future__ import annotations

import logging
import re
from datetime import date

from sqlmodel import Session, select

from .models import (Belegdaten, Dokument, Kontakt, Kredit, Kundennummer,
                     Objekt, Renovierung, Renovierungsposten, Versicherung)

log = logging.getLogger("immocalc")

# Die Arten, nach denen das Kontaktbuch gruppiert. Bewusst wenige — je mehr
# Schubladen, desto öfter liegt etwas in der falschen.
ARTEN = ("Handwerker", "Versicherung", "Bank", "Versorger", "Hausverwaltung",
         "Behörde", "Sonstiges")

# Rechtsformen und Füllwörter, die zwei Schreibweisen derselben Firma trennen
# würden. „Elektro Müller GmbH" und „Elektro Müller" sind dieselbe Firma.
_RECHTSFORM = re.compile(
    r"\b(gmbh|mbh|ag|kg|ohg|gbr|e\.?\s?k\.?|ug|se|co|kgaa|"
    r"& ?co|und ?co|gmbh ?& ?co ?kg|inh\.?|e\.?\s?v\.?)\b", re.I)
_MUELL = re.compile(r"[^\w\säöüß&+-]", re.I)

# Welche Felder eine Firma zur Art führen. Erst der eindeutigste Treffer.
_ART_WORTE = (
    ("Versicherung", ("versicherung", "assekuranz", "allianz", "versicherer",
                      "vhv", "huk", "gothaer", "ergo", "axa", "provinzial")),
    ("Bank", ("bank", "sparkasse", "volksbank", "raiffeisen", "lbs",
              "bausparkasse", "kreditanstalt")),
    ("Versorger", ("stadtwerke", "energie", "strom", "gas", "wasser",
                   "n-ergie", "eon", "e.on", "zweckverband", "entsorgung",
                   "abfallwirtschaft", "telekom", "vodafone")),
    ("Hausverwaltung", ("hausverwaltung", "immobilienverwaltung", "weg-verwalt",
                        "verwaltung")),
    ("Behörde", ("finanzamt", "gemeinde", "markt ", "stadt ", "landratsamt",
                 "amtsgericht", "grundbuchamt", "kataster")),
)


def schluessel(firma: str) -> str:
    """Der Wiedererkennungsschlüssel einer Firma.

    Kleingeschrieben, ohne Rechtsform, ohne Satzzeichen, ohne doppelte
    Leerzeichen. Ohne das entstünden aus „Elektro Müller GmbH",
    „Elektro Müller gmbh" und „Elektro-Müller" drei Einträge — und das
    Kontaktbuch wäre schon nach zehn Belegen unbrauchbar."""
    text = _MUELL.sub(" ", (firma or "").lower())
    text = _RECHTSFORM.sub(" ", text)
    text = re.sub(r"[-&+]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def art_raten(firma: str, gewerk: str = "", vorgabe: str = "") -> str:
    """Die Schublade einer Firma — geraten, aber nachvollziehbar.

    `vorgabe` gewinnt immer: wer aus der Versicherungsliste kommt, IST eine
    Versicherung, egal wie er heisst. Sonst entscheidet ein Wort im Namen, und
    zuletzt das Gewerk: wer eins hat, ist Handwerker."""
    if vorgabe:
        return vorgabe
    klein = (firma or "").lower()
    for art, worte in _ART_WORTE:
        if any(w in klein for w in worte):
            return art
    return "Handwerker" if gewerk else "Sonstiges"


def _leer(wert) -> bool:
    return not str(wert or "").strip()


def zusammenfuehren(kontakt: Kontakt, neu: dict) -> bool:
    """Ergänzt einen Kontakt um neue Angaben — **ohne je zu überschreiben**.

    Gefüllt wird nur, was leer ist, und nie ein Feld, das der Nutzer selbst
    gepflegt hat (`handgepflegt`). Gibt zurück, ob sich etwas geändert hat."""
    geschuetzt = set(kontakt.handgepflegt or [])
    geaendert = False
    for feld, wert in neu.items():
        if feld in geschuetzt or _leer(wert):
            continue
        if not hasattr(kontakt, feld):
            continue
        if _leer(getattr(kontakt, feld)):
            setattr(kontakt, feld, str(wert).strip())
            geaendert = True
    return geaendert


def hole_oder_lege_an(session: Session, firma: str, **felder) -> Kontakt | None:
    """Den Kontakt zu dieser Firma — angelegt, falls es ihn noch nicht gibt."""
    s = schluessel(firma)
    if not s:
        return None
    kontakt = session.exec(
        select(Kontakt).where(Kontakt.schluessel == s)).first()
    if kontakt is None:
        kontakt = Kontakt(schluessel=s, firma=(firma or "").strip(),
                          erfasst_am=date.today(), handgepflegt=[])
        session.add(kontakt)
        session.flush()
    zusammenfuehren(kontakt, felder)
    session.add(kontakt)
    return kontakt


def nummer_merken(session: Session, kontakt: Kontakt, objekt_id: int | None,
                  nummer: str, art: str, quelle: str = "",
                  dokument_id: int | None = None) -> bool:
    """Eine Kundennummer festhalten — je Firma, Immobilie und Nummer einmal."""
    nummer = (nummer or "").strip()
    if not nummer or kontakt.id is None:
        return False
    vorhanden = session.exec(select(Kundennummer).where(
        Kundennummer.kontakt_id == kontakt.id,
        Kundennummer.objekt_id == objekt_id)).all()
    if any((k.nummer or "").strip().lower() == nummer.lower() for k in vorhanden):
        return False
    session.add(Kundennummer(kontakt_id=kontakt.id, objekt_id=objekt_id,
                             nummer=nummer, art=art or "Kundennummer",
                             quelle=quelle, quelle_dokument_id=dokument_id))
    return True


# --------------------------------------------------------------------------
# Die Ernte
# --------------------------------------------------------------------------

# Welche Felder der KI-Auslese eine Nummer tragen — und wie sie heisst.
_NUMMERNFELDER = {
    "kundennummer": "Kundennummer",
    "kunden_nr": "Kundennummer",
    "vertragsnummer": "Vertragsnummer",
    "police_nr": "Police",
    "policennummer": "Police",
    "darlehensnummer": "Darlehensnummer",
    "zaehlernummer": "Zählernummer",
    "aktenzeichen": "Aktenzeichen",
    "kassenzeichen": "Kassenzeichen",
    "steuernummer": "Steuernummer",
}


def _aus_renovierungen(session: Session) -> tuple[int, int]:
    """Handwerker samt Gewerk — die einzige Quelle, die beides zusammen kennt."""
    neu = nummern = 0
    for p in session.exec(select(Renovierungsposten)).all():
        if _leer(p.firma):
            continue
        vorher = session.exec(select(Kontakt).where(
            Kontakt.schluessel == schluessel(p.firma))).first() is None
        k = hole_oder_lege_an(session, p.firma, gewerk=(p.gewerk or "").strip(),
                              art=art_raten(p.firma, p.gewerk, ""),
                              quelle="renovierung")
        if k is not None and vorher:
            neu += 1
    return neu, nummern


def _aus_versicherungen(session: Session) -> tuple[int, int]:
    neu = nummern = 0
    for v in session.exec(select(Versicherung)).all():
        if _leer(getattr(v, "anbieter", "")):
            continue
        vorher = session.exec(select(Kontakt).where(
            Kontakt.schluessel == schluessel(v.anbieter))).first() is None
        k = hole_oder_lege_an(session, v.anbieter, art="Versicherung",
                              quelle="versicherung")
        if k is None:
            continue
        if vorher:
            neu += 1
        session.flush()
        if nummer_merken(session, k, v.objekt_id,
                         getattr(v, "police_nr", "") or "", "Police",
                         "versicherung"):
            nummern += 1
    return neu, nummern


def _aus_krediten(session: Session) -> tuple[int, int]:
    neu = nummern = 0
    for kr in session.exec(select(Kredit)).all():
        if _leer(getattr(kr, "bank", "")):
            continue
        vorher = session.exec(select(Kontakt).where(
            Kontakt.schluessel == schluessel(kr.bank))).first() is None
        k = hole_oder_lege_an(session, kr.bank, art="Bank", quelle="kredit")
        if k is None:
            continue
        if vorher:
            neu += 1
        session.flush()
        if nummer_merken(session, k, kr.objekt_id,
                         getattr(kr, "darlehensnummer", "") or "",
                         "Darlehensnummer", "kredit"):
            nummern += 1
    return neu, nummern


def _felder_von(quelle) -> dict:
    felder = getattr(quelle, "ki_felder", None) or getattr(quelle, "felder", None)
    return felder if isinstance(felder, dict) else {}


def _aus_belegen(session: Session) -> tuple[int, int]:
    """Der grösste Fang: was die KI aus 692 Belegen gelesen hat.

    Der Absender steht als `anbieter` im Raster, die Nummern unter wechselnden
    Namen (`police_nr`, `darlehensnummer`, seit N309 auch `kundennummer`)."""
    neu = nummern = 0
    quellen: list[tuple[object, int | None, int | None]] = [
        (d, d.objekt_id, d.id) for d in session.exec(select(Dokument)).all()
    ] + [
        (b, b.objekt_id, b.dokument_id)
        for b in session.exec(select(Belegdaten)).all()
    ]
    for quelle, objekt_id, dokument_id in quellen:
        felder = _felder_von(quelle)
        firma = (felder.get("anbieter") or felder.get("absender")
                 or getattr(quelle, "anbieter", "") or "")
        if _leer(firma):
            continue
        vorher = session.exec(select(Kontakt).where(
            Kontakt.schluessel == schluessel(firma))).first() is None
        k = hole_oder_lege_an(session, firma,
                              art=art_raten(firma, "", ""), quelle="beleg")
        if k is None:
            continue
        if vorher:
            neu += 1
        session.flush()
        for feld, bezeichnung in _NUMMERNFELDER.items():
            if nummer_merken(session, k, objekt_id, str(felder.get(feld) or ""),
                             bezeichnung, "beleg", dokument_id):
                nummern += 1
    return neu, nummern


def ernte(session: Session) -> dict:
    """Alle Quellen einmal durchgehen. Wiederholbar, rein ergänzend.

    Nichts wird gelöscht und nichts überschrieben — ein zweiter Lauf ändert nur
    dort etwas, wo seit dem letzten Mal Neues dazugekommen ist."""
    neu = nummern = 0
    for schritt in (_aus_renovierungen, _aus_versicherungen, _aus_krediten,
                    _aus_belegen):
        try:
            n, m = schritt(session)
        except Exception as fehler:                        # noqa: BLE001
            session.rollback()
            log.warning("Kontakt-Ernte (%s) übersprungen: %s",
                        schritt.__name__, fehler)
            continue
        neu += n
        nummern += m
    session.commit()
    gesamt = len(session.exec(select(Kontakt)).all())
    log.info("N309: %d neue Kontakte, %d neue Nummern, %d gesamt",
             neu, nummern, gesamt)
    return {"neu": neu, "nummern": nummern, "gesamt": gesamt}


# --------------------------------------------------------------------------
# Lesen
# --------------------------------------------------------------------------

def zeige(session: Session, kontakt: Kontakt, objekte: dict) -> dict:
    nummern = session.exec(select(Kundennummer).where(
        Kundennummer.kontakt_id == kontakt.id)).all()
    return {
        "id": kontakt.id, "firma": kontakt.firma, "art": kontakt.art,
        "gewerk": kontakt.gewerk, "telefon": kontakt.telefon,
        "email": kontakt.email, "web": kontakt.web, "adresse": kontakt.adresse,
        "notiz": kontakt.notiz, "quelle": kontakt.quelle,
        "handgepflegt": list(kontakt.handgepflegt or []),
        "nummern": [{
            "id": n.id, "nummer": n.nummer, "art": n.art,
            "objekt": objekte[n.objekt_id].slug if n.objekt_id in objekte else "",
            "objekt_name": (objekte[n.objekt_id].name
                            if n.objekt_id in objekte else ""),
        } for n in nummern],
        # Was noch fehlt — daran hängt die Online-Anreicherung und der Hinweis
        # in der Oberfläche.
        "fehlt": [f for f in ("telefon", "email")
                  if _leer(getattr(kontakt, f))],
    }


def gewerke_der_renovierung(session: Session, renovierung_id: int) -> list[dict]:
    """Wer hat in welchem Gewerk gearbeitet — die Frage des Nutzers.

    „Es sollen auch Renovierungen wählbar sein, um dann zu sehen, welche
    Handwerker in welchen Gewerken tätig waren.\""""
    r = session.get(Renovierung, renovierung_id)
    if r is None:
        return []
    posten = session.exec(select(Renovierungsposten).where(
        Renovierungsposten.renovierung_id == renovierung_id)).all()
    nach_gewerk: dict[str, dict] = {}
    for p in posten:
        if _leer(p.firma):
            continue
        gewerk = (p.gewerk or "").strip() or "Sonstiges"
        eintrag = nach_gewerk.setdefault(gewerk, {"gewerk": gewerk,
                                                  "firmen": {}, "summe": 0.0})
        firma = eintrag["firmen"].setdefault(schluessel(p.firma), {
            "firma": p.firma.strip(), "summe": 0.0, "anzahl": 0,
            "kontakt_id": None})
        betrag = float(p.betrag or 0.0)
        firma["summe"] = round(firma["summe"] + betrag, 2)
        firma["anzahl"] += 1
        eintrag["summe"] = round(eintrag["summe"] + betrag, 2)
    # Die Kontakt-Id nachtragen, damit die Oberfläche direkt verlinken kann.
    for eintrag in nach_gewerk.values():
        for s, firma in eintrag["firmen"].items():
            k = session.exec(select(Kontakt).where(Kontakt.schluessel == s)).first()
            firma["kontakt_id"] = k.id if k else None
        eintrag["firmen"] = sorted(eintrag["firmen"].values(),
                                   key=lambda f: -f["summe"])
    return sorted(nach_gewerk.values(), key=lambda g: -g["summe"])
