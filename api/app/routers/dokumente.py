"""Eingangsordner: neue Dateien erkennen, zuordnen, einsortieren.

Der Hauptordner jeder Immobilie ist ihr Eingang. Was dort direkt liegt und
noch nicht zugeordnet ist, wartet in der App auf eine Entscheidung. Nach der
Zuordnung wird die Datei umbenannt und in die Struktur verschoben.
"""
import logging
import re
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlmodel import Session, select

from ..db import get_session
from ..models import Dokument, Kostenart, Objekt
from ..nextcloud import NextcloudFehler
from .cloud import STRUKTUR, verbindung

log = logging.getLogger("immocalc")
router = APIRouter(prefix="/api/dokumente", tags=["dokumente"])

# Wohin eine Kategorie einsortiert wird. Alles Abrechnungsrelevante landet
# unter Nebenkosten, der Rest bei seinem Thema.
ZIELORDNER = {
    "Nebenkosten": "60_Nebenkosten",
    "Steuer": "70_Steuer_Finanzamt",
    "Kredit": "40_Kauf_Eigentum_Finanzierung",
    "Versicherung": "01_Allgemein_Hauskonto",
    "Mietvertrag": "20_Mietvertraege_Vermietung",
    "Korrespondenz": "30_Kommunikation",
    "Hausverwaltung": "80_Hausverwaltung",
    "Sonstiges": "99_Sonstiges",
}

DOKUMENTARTEN = list(ZIELORDNER.keys())


def _saubere_datei(text: str) -> str:
    text = re.sub(r"[^\wäöüÄÖÜß.\- ]+", "", text).strip()
    return re.sub(r"\s+", "-", text)


def dateiname(jahr: int | None, kategorie: str, beschreibung: str,
              endung: str) -> str:
    """JJJJ-MM_Kategorie_Beschreibung.pdf — sortiert sich von selbst."""
    teile = [str(jahr) if jahr else "ohne-Jahr", _saubere_datei(kategorie)]
    if beschreibung:
        teile.append(_saubere_datei(beschreibung))
    return "_".join(t for t in teile if t) + endung


@router.get("/wachdienst")
def wachdienst_status() -> dict:
    """Wann zuletzt automatisch nachgesehen wurde."""
    from ..wachdienst import zustand
    return zustand()


@router.get("/inbox")
def inbox(session: Session = Depends(get_session)) -> dict:
    """Alle noch nicht zugeordneten Dokumente."""
    offen = session.exec(
        select(Dokument).where(Dokument.status == "neu")).all()
    objekte = {o.id: o for o in session.exec(select(Objekt)).all()}
    return {
        "anzahl": len(offen),
        "arten": DOKUMENTARTEN,
        "dokumente": [{
            "id": d.id, "dateiname": d.dateiname, "pfad": d.pfad,
            "groesse": d.groesse,
            "erkannt_am": d.erkannt_am.isoformat() if d.erkannt_am else None,
            "objekt": objekte[d.objekt_id].slug if d.objekt_id in objekte else None,
            "objekt_name": objekte[d.objekt_id].name if d.objekt_id in objekte else None,
            "vorschlag": _vorschlag(d, session),
        } for d in offen],
    }


def _vorschlag(d: Dokument, session: Session) -> dict:
    """Einfache Vermutung aus dem Dateinamen — bis OCR die Inhalte liest."""
    name = d.dateiname.lower()
    jahre = re.findall(r"(20\d{2})", d.dateiname)
    kategorie = ""
    for art in DOKUMENTARTEN:
        if art.lower() in name:
            kategorie = art
            break
    if not kategorie:
        for wort, art in [("grundsteuer", "Steuer"), ("steuer", "Steuer"),
                          ("versicherung", "Versicherung"), ("police", "Versicherung"),
                          ("darlehen", "Kredit"), ("zins", "Kredit"),
                          ("miete", "Mietvertrag"), ("wasser", "Nebenkosten"),
                          ("strom", "Nebenkosten"), ("heiz", "Nebenkosten"),
                          ("müll", "Nebenkosten"), ("abrechnung", "Nebenkosten")]:
            if wort in name:
                kategorie = art
                break
    return {"kategorie": kategorie, "jahr": int(jahre[0]) if jahre else None}


@router.post("/scan")
def scan(session: Session = Depends(get_session)) -> dict:
    """Liest die Objektordner in der Nextcloud und nimmt neue Dateien auf."""
    client = verbindung(session)
    neu = 0
    for o in session.exec(select(Objekt)).all():
        if not o.nc_ordner:
            continue
        try:
            eintraege = client.liste(o.nc_ordner)
        except NextcloudFehler as e:
            log.warning("Ordner %s nicht lesbar: %s", o.nc_ordner, e)
            continue
        for e in eintraege:
            if e.ordner:
                continue      # nur lose Dateien im Hauptordner sind Eingang
            vorhanden = session.exec(
                select(Dokument).where(Dokument.pfad == e.pfad)).first()
            if vorhanden:
                continue
            session.add(Dokument(pfad=e.pfad, dateiname=e.name, groesse=e.groesse,
                                 objekt_id=o.id, status="neu",
                                 erkannt_am=date.today()))
            neu += 1
    session.commit()
    return {"neu": neu}


class ZuordnungIn(BaseModel):
    objekt: str
    kategorie: str
    jahr: int | None = None
    beschreibung: str = ""
    verschieben: bool = True


@router.post("/{dokument_id}/zuordnen")
def zuordnen(dokument_id: int, data: ZuordnungIn,
             session: Session = Depends(get_session)) -> dict:
    """Ordnet ein Dokument zu, benennt es um und verschiebt es."""
    d = session.get(Dokument, dokument_id)
    if not d:
        raise HTTPException(404, "Dokument nicht gefunden")
    o = session.exec(select(Objekt).where(Objekt.slug == data.objekt)).first()
    if not o:
        raise HTTPException(404, "Objekt nicht gefunden")

    unterordner = ZIELORDNER.get(data.kategorie, "99_Sonstiges")
    if unterordner not in STRUKTUR:
        raise HTTPException(400, f"Unbekannter Zielordner '{unterordner}'")

    endung = ("." + d.dateiname.rsplit(".", 1)[-1]) if "." in d.dateiname else ""
    neuer_name = dateiname(data.jahr, data.kategorie, data.beschreibung, endung)
    ziel = f"{(o.nc_ordner or '').strip('/')}/{unterordner}/{neuer_name}"

    if data.verschieben and o.nc_ordner:
        client = verbindung(session)
        try:
            client.ordner_anlegen(f"{o.nc_ordner.strip('/')}/{unterordner}")
            client.verschiebe(d.pfad, ziel)
        except NextcloudFehler as e:
            raise HTTPException(400, str(e)) from e
        d.pfad = "/" + ziel.strip("/")

    d.objekt_id = o.id
    d.kategorie = data.kategorie
    d.jahr = data.jahr
    d.dateiname = neuer_name
    d.status = "zugeordnet"
    session.add(d)
    session.commit()
    return {"ok": True, "pfad": d.pfad, "dateiname": d.dateiname}


def _freier_name(client, ordner: str, name: str) -> str:
    """Haengt -2, -3 an, falls der Name schon vergeben ist — nie ueberschreiben."""
    stamm, punkt, endung = name.rpartition(".")
    stamm = stamm or name
    endung = f".{endung}" if punkt else ""
    kandidat, n = name, 2
    while client.existiert(f"{ordner}/{kandidat}"):
        kandidat = f"{stamm}-{n}{endung}"
        n += 1
        if n > 50:
            break
    return kandidat


@router.post("/scannen", status_code=201)
async def scannen(objekt: str = Form(...), kategorie: str = Form("Sonstiges"),
                  jahr: int | None = Form(None), beschreibung: str = Form(""),
                  datei: UploadFile = File(...),
                  session: Session = Depends(get_session)) -> dict:
    """Nimmt ein abfotografiertes Dokument entgegen, benennt es nach Schema
    und legt es direkt im richtigen Unterordner der Immobilie ab."""
    o = session.exec(select(Objekt).where(Objekt.slug == objekt)).first()
    if not o:
        raise HTTPException(404, "Objekt nicht gefunden")

    inhalt = await datei.read()
    if not inhalt:
        raise HTTPException(400, "Leere Datei")

    unterordner = ZIELORDNER.get(kategorie, "99_Sonstiges")
    name = dateiname(jahr, kategorie, beschreibung or "Scan", ".pdf")

    # Ohne verknüpften Ordner bleibt der Scan in der Inbox und wartet dort.
    if not o.nc_ordner:
        d = Dokument(pfad=f"(nicht abgelegt)/{name}", dateiname=name,
                     groesse=len(inhalt), objekt_id=o.id, kategorie=kategorie,
                     jahr=jahr, status="neu", erkannt_am=date.today())
        session.add(d)
        session.commit()
        session.refresh(d)
        return {"id": d.id, "dateiname": name, "abgelegt": False,
                "hinweis": "Nextcloud-Ordner fehlt — das Dokument wartet im Eingang."}

    client = verbindung(session)
    ziel_ordner = f"{o.nc_ordner.strip('/')}/{unterordner}"
    try:
        client.ordner_anlegen(ziel_ordner)
        name = _freier_name(client, ziel_ordner, name)
        client.lege_ab(f"{ziel_ordner}/{name}", inhalt)
    except NextcloudFehler as e:
        raise HTTPException(400, str(e)) from e

    d = Dokument(pfad=f"/{ziel_ordner}/{name}", dateiname=name,
                 groesse=len(inhalt), objekt_id=o.id, kategorie=kategorie,
                 jahr=jahr, status="zugeordnet", erkannt_am=date.today())
    session.add(d)
    session.commit()
    session.refresh(d)
    log.info("Scan abgelegt: %s", d.pfad)
    return {"id": d.id, "dateiname": name, "pfad": d.pfad, "abgelegt": True}


@router.get("/objekt/{slug}")
def je_objekt(slug: str, session: Session = Depends(get_session)) -> list[dict]:
    """Alle zugeordneten Dokumente eines Objekts — zum Durchblättern."""
    o = session.exec(select(Objekt).where(Objekt.slug == slug)).first()
    if not o:
        raise HTTPException(404, "Objekt nicht gefunden")
    docs = session.exec(select(Dokument).where(Dokument.objekt_id == o.id)).all()
    return [{"id": d.id, "dateiname": d.dateiname, "pfad": d.pfad,
             "kategorie": d.kategorie, "jahr": d.jahr, "status": d.status}
            for d in docs if d.status == "zugeordnet"]


@router.get("/kategorien/{slug}")
def kategorien(slug: str, session: Session = Depends(get_session)) -> dict:
    """Dokumentarten plus die Kostenarten des Objekts — für die Zuordnung."""
    o = session.exec(select(Objekt).where(Objekt.slug == slug)).first()
    if not o:
        raise HTTPException(404, "Objekt nicht gefunden")
    arten = session.exec(select(Kostenart).where(Kostenart.objekt_id == o.id)).all()
    return {"arten": DOKUMENTARTEN,
            "kostenarten": [k.name for k in arten if k.aktiv]}
