"""N240 — das Vorlagenarchiv: leere Formulare (Übergabeprotokoll,
Mieterselbstauskunft, Rauchwarnmelder-Abnahme, Wohnungsgeberbestätigung …),
getrennt von den echten Belegen des Nutzers.

Liegt in der Cloud unter einem eigenen Home-Unterordner
`/Vorlagen/<verwendungszweck>/`, NICHT unter einem Objekt-Ordner — eine
Vorlage gehört zu keiner bestimmten Immobilie. Fünf dünne Endpunkte, gerechnet
wird nichts:

* `GET    /api/dokumentvorlagen`            — Liste, optional gefiltert
* `POST   /api/dokumentvorlagen`            — eigene Vorlage hochladen
* `GET    /api/dokumentvorlagen/{id}/inhalt`  — die Datei zur Ansicht
* `DELETE /api/dokumentvorlagen/{id}`       — nur den Datenbankeintrag
"""
import logging
from datetime import date

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlmodel import Session, select

from ..cloudkern import verbindung
from ..db import get_session
from ..dokumente.namen import _dateiname_kopfzeile, _saubere_datei
from ..models import Dokumentvorlage
from ..nextcloud import NextcloudFehler

log = logging.getLogger("immocalc")
router = APIRouter(prefix="/api/dokumentvorlagen", tags=["dokumentvorlagen"])

VORLAGEN_ORDNER = "Vorlagen"

# N240 — der Startbestand für Vermietung. Jede Quelle ist ein bekannter,
# seriöser Anbieter (Haus & Grund — Deutschlands größter privater
# Eigentümerverband); `quelle_url` bleibt am Eintrag stehen, damit der Nutzer
# nachvollziehen und die Vorlage bei Bedarf gegen eine eigene austauschen
# kann. Bewusst OHNE Mietvertrag — der ist zu individuell für eine Vorlage.
STARTBESTAND = [
    {"name": "Übergabeprotokoll (Einzug)", "typ": "Übergabeprotokoll Einzug",
     "dateiname": "Uebergabeprotokoll-Einzug.pdf",
     "quelle_url": "https://www.hausundgrund.de/verband/thueringen/sites/"
                   "default/files/lv/downloads/uebergabeprotokollwohnung.pdf",
     "hinweis": "Haus & Grund Thüringen — Muster-Übergabeprotokoll für Wohnraum."},
    {"name": "Übergabeprotokoll (Auszug)", "typ": "Übergabeprotokoll Auszug",
     "dateiname": "Uebergabeprotokoll-Auszug.pdf",
     "quelle_url": "https://www.hausundgrund.de/verband/thueringen/sites/"
                   "default/files/lv/downloads/abnahmeprotokollwohnung.pdf",
     "hinweis": "Haus & Grund Thüringen — Muster-Abnahmeprotokoll für Wohnraum."},
    {"name": "Mieterselbstauskunft", "typ": "Mieterselbstauskunft",
     "dateiname": "Mieterselbstauskunft.pdf",
     "quelle_url": "https://www.hausundgrund-aachen.de/fileadmin/aachen/media/"
                   "pdfs/2019/Mieterselbstauskunft_H_G_11_-_2019.pdf",
     "hinweis": "Haus & Grund Aachen — Muster-Mieterselbstauskunft."},
    {"name": "Abnahmeprotokoll Rauchwarnmelder",
     "typ": "Abnahmeprotokoll Rauchwarnmelder",
     "dateiname": "Installationsprotokoll-Rauchwarnmelder.pdf",
     "quelle_url": "https://www.hausundgrund-aachen.de/fileadmin/aachen/media/"
                   "pdfs/Installationsprotokoll_fuer_Rauchwarnmelder_09_-_2015.pdf",
     "hinweis": "Haus & Grund Aachen — Installations-/Abnahmeprotokoll für "
                "Rauchwarnmelder."},
    {"name": "Wohnungsgeberbestätigung", "typ": "Wohnungsgeberbestätigung",
     "dateiname": "Wohnungsgeberbestaetigung.pdf",
     "quelle_url": "https://www.hausundgrund.de/verein/unna/sites/default/"
                   "files/downloads/wohnungsgeberbescheinigung.pdf",
     "hinweis": "Nach § 19 Bundesmeldegesetz (BMG) — wird für die Anmeldung "
                "beim Bürgeramt gebraucht."},
]


def _zeige(v: Dokumentvorlage) -> dict:
    return {
        "id": v.id, "name": v.name, "verwendungszweck": v.verwendungszweck,
        "typ": v.typ, "pfad": v.pfad, "dateiname": v.dateiname,
        "quelle_url": v.quelle_url, "hinweis": v.hinweis,
        "erstellt_am": v.erstellt_am.isoformat() if v.erstellt_am else None,
    }


def _eintrag(session: Session, vorlage_id: int) -> Dokumentvorlage:
    v = session.get(Dokumentvorlage, vorlage_id)
    if not v:
        raise HTTPException(404, "Vorlage nicht gefunden")
    return v


def _ordner_sichern(client, verwendungszweck: str) -> str:
    """Legt `Vorlagen/<Zweck>` an (405-sicher) und gibt den Pfad zurück."""
    client.ordner_anlegen(VORLAGEN_ORDNER)
    ordner = f"{VORLAGEN_ORDNER}/{verwendungszweck}"
    client.ordner_anlegen(ordner)
    return ordner


def _freier_name(client, ordner: str, name: str) -> str:
    """Wie in `dokumente.py` — nie überschreiben, `-2`/`-3` bei Kollision."""
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


@router.get("")
def liste(verwendungszweck: str = "", typ: str = "",
         session: Session = Depends(get_session)) -> dict:
    """Die Vorlagen, optional nach Verwendungszweck/Typ gefiltert."""
    frage = select(Dokumentvorlage)
    if verwendungszweck:
        frage = frage.where(Dokumentvorlage.verwendungszweck == verwendungszweck)
    if typ:
        frage = frage.where(Dokumentvorlage.typ == typ)
    alle = session.exec(frage).all()
    alle = sorted(alle, key=lambda v: (v.verwendungszweck, v.name.lower()))
    return {"anzahl": len(alle), "vorlagen": [_zeige(v) for v in alle]}


@router.post("", status_code=201)
async def hochladen(name: str, verwendungszweck: str = "Vermietung",
                    typ: str = "", quelle_url: str = "", hinweis: str = "",
                    datei: UploadFile = File(...),
                    session: Session = Depends(get_session)) -> dict:
    """Legt eine eigene Vorlage ab — dieselbe Ablage wie der Startbestand,
    damit der Nutzer eigene Formulare nachtragen oder ersetzen kann."""
    client = verbindung(session)
    ordner = _ordner_sichern(client, verwendungszweck)
    inhalt = await datei.read()
    dateiname = _saubere_datei(datei.filename or f"{name}.pdf")
    frei = _freier_name(client, ordner, dateiname)
    try:
        client.lege_ab(f"{ordner}/{frei}", inhalt,
                       datei.content_type or "application/pdf")
    except NextcloudFehler as e:
        raise HTTPException(400, str(e)) from e
    v = Dokumentvorlage(name=name, verwendungszweck=verwendungszweck, typ=typ,
                        pfad=f"/{ordner}/{frei}", dateiname=frei,
                        quelle_url=quelle_url, hinweis=hinweis,
                        erstellt_am=date.today())
    session.add(v)
    session.commit()
    session.refresh(v)
    log.info("Dokumentvorlage abgelegt: %s (%s)", v.pfad, v.verwendungszweck)
    return _zeige(v)


@router.get("/{vorlage_id}/inhalt")
def inhalt(vorlage_id: int, session: Session = Depends(get_session)):
    """Liefert die Vorlagendatei zur Ansicht — `inline`, rein lesend."""
    from fastapi import Response
    v = _eintrag(session, vorlage_id)
    if not v.pfad.startswith("/"):
        raise HTTPException(409, "Diese Vorlage liegt noch nicht in der Cloud")
    client = verbindung(session)
    try:
        rohdaten, typ = client.hole(v.pfad)
    except NextcloudFehler as e:
        raise HTTPException(400, str(e)) from e
    if typ == "application/octet-stream" and v.dateiname.lower().endswith(".pdf"):
        typ = "application/pdf"
    return Response(content=rohdaten, media_type=typ, headers={
        "Content-Disposition": f"inline; {_dateiname_kopfzeile(v.dateiname)}",
        "Cache-Control": "private, max-age=300",
    })


def _startbestand_sichern(session: Session) -> dict:
    """Legt den fehlenden Teil des Startbestands an (additiv, nie doppelt).

    Bewusst NICHT automatisch beim Programmstart (anders als
    `pflicht_kostenarten_sichern`) — das würde bei jedem Testlauf und jedem
    Neustart Netzwerkzugriffe auf fremde Server auslösen. Stattdessen ein
    expliziter Aufruf über `POST /api/dokumentvorlagen/startbestand`, genau
    wie die Übernahme in `kidb.py`. Ein Netzwerkfehler bei einer Datei bricht
    die anderen nicht ab."""
    vorhandene_typen = {v.typ for v in session.exec(select(Dokumentvorlage)).all()}
    fehlend = [e for e in STARTBESTAND if e["typ"] not in vorhandene_typen]
    if not fehlend:
        return {"angelegt": 0, "fehler": []}
    client = verbindung(session)
    ordner = None
    angelegt = 0
    fehlerliste: list[dict] = []
    for eintrag in fehlend:
        try:
            antwort = httpx.get(eintrag["quelle_url"], timeout=20.0,
                                follow_redirects=True)
            antwort.raise_for_status()
            if ordner is None:
                ordner = _ordner_sichern(client, "Vermietung")
            frei = _freier_name(client, ordner, eintrag["dateiname"])
            client.lege_ab(f"{ordner}/{frei}", antwort.content, "application/pdf")
        except Exception as fehler:                        # noqa: BLE001
            log.warning("Vorlagen-Startbestand: '%s' nicht geladen (%s)",
                       eintrag["name"], fehler)
            fehlerliste.append({"name": eintrag["name"], "grund": str(fehler)})
            continue
        session.add(Dokumentvorlage(
            name=eintrag["name"], verwendungszweck="Vermietung",
            typ=eintrag["typ"], pfad=f"/{ordner}/{frei}", dateiname=frei,
            quelle_url=eintrag["quelle_url"], hinweis=eintrag["hinweis"],
            erstellt_am=date.today()))
        angelegt += 1
    if angelegt:
        session.commit()
    return {"angelegt": angelegt, "fehler": fehlerliste}


@router.post("/startbestand")
def startbestand(session: Session = Depends(get_session)) -> dict:
    """Legt den Vermietungs-Startbestand an — nur was fehlt, wiederholbar."""
    return _startbestand_sichern(session)


@router.delete("/{vorlage_id}")
def loeschen(vorlage_id: int, session: Session = Depends(get_session)) -> dict:
    """Entfernt nur den Datenbankeintrag — die Datei bleibt in der Cloud und
    lässt sich jederzeit neu verlinken oder von Hand aufräumen."""
    v = _eintrag(session, vorlage_id)
    session.delete(v)
    session.commit()
    log.info("Dokumentvorlage-Eintrag %d entfernt (Datei bleibt)", vorlage_id)
    return {"ok": True}
