"""Dokumentenablage: aufnehmen, zuordnen, korrigieren, wiederfinden.

Ein Dokument nimmt genau einen Weg: es kommt herein — abfotografiert oder als
Datei im Hauptordner der Immobilie —, bekommt Immobilie, Art und Jahr und liegt
danach am richtigen Platz. Wo die Zuordnung sicher ist (nur eine Immobilie oder
der Beleg lag schon in ihrem Ordner, und die Art ist erkannt), geschieht sie
ohne Rückfrage.

Alles Weitere ist Korrektur und läuft über einen einzigen Endpunkt: `PATCH`
ändert Immobilie, Art, Jahr und Namen — und verschiebt die Datei in der Cloud
mit. `DELETE` entfernt nur den Eintrag; die Datei in der Nextcloud bleibt
liegen, gelöscht wird dort grundsätzlich nichts.
"""
import logging
import re
from datetime import date

from fastapi import (APIRouter, Depends, File, Form, HTTPException, Response,
                     UploadFile)
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from .. import ocr
from ..db import get_session
from ..models import Dokument, Objekt
from ..nextcloud import NextcloudFehler
from ..wachdienst import sperre
from ..wachdienst import zustand as wachdienst_zustand
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


def _saubere_datei(text_: str) -> str:
    text_ = re.sub(r"[^\wäöüÄÖÜß.\- ]+", "", text_).strip()
    return re.sub(r"\s+", "-", text_)


def dateiname(jahr: int | None, kategorie: str, beschreibung: str,
              endung: str) -> str:
    """JJJJ-MM_Kategorie_Beschreibung.pdf — sortiert sich von selbst."""
    teile = [str(jahr) if jahr else "ohne-Jahr", _saubere_datei(kategorie)]
    if beschreibung:
        teile.append(_saubere_datei(beschreibung))
    return "_".join(t for t in teile if t) + endung


def _endung(name: str) -> str:
    return ("." + name.rsplit(".", 1)[-1]) if "." in name else ""


# --------------------------------------------------------------------------
# Vermutung und Darstellung
# --------------------------------------------------------------------------

def _vorschlag(d: Dokument) -> dict:
    """Was die Ablage vermutet: Art und Jahr.

    Die Worterkennung kommt aus `ocr.kategorie_aus_text` — dieselbe Liste, die
    auch den abfotografierten Beleg einordnet. Zwei Listen wären zwei
    Wahrheiten. Beim Dateinamen hilft sie nur, wenn er etwas hergibt; ein
    Kamerascan heißt „scan.pdf", dort liefert die Texterkennung den Vorschlag
    schon beim Hochladen mit.
    """
    name = d.dateiname.lower()
    lesbar = name.replace("_", " ").replace("-", " ")
    kategorie = (d.kategorie
                 or next((a for a in DOKUMENTARTEN if a.lower() in lesbar), "")
                 or ocr.kategorie_aus_text(lesbar))
    jahre = re.findall(r"(20\d{2})", d.dateiname)
    return {"kategorie": kategorie,
            "jahr": d.jahr or (int(jahre[0]) if jahre else None)}


def _zeige(d: Dokument, objekte: dict[int, Objekt]) -> dict:
    o = objekte.get(d.objekt_id) if d.objekt_id else None
    return {
        "id": d.id, "dateiname": d.dateiname, "pfad": d.pfad,
        "groesse": d.groesse, "status": d.status,
        "kategorie": d.kategorie, "jahr": d.jahr,
        "erkannt_am": d.erkannt_am.isoformat() if d.erkannt_am else None,
        "objekt": o.slug if o else None,
        "objekt_name": o.name if o else None,
        # Ein Eintrag ohne Datei in der Cloud — nur noch zu entfernen oder
        # neu einzuscannen. Ehrlich anzeigen statt so tun, als läge er dort.
        "abgelegt": d.pfad.startswith("/"),
        "vorschlag": _vorschlag(d),
    }


# --------------------------------------------------------------------------
# Ablegen in der Cloud — eine Stelle für Zuordnen, Korrigieren und Automatik
# --------------------------------------------------------------------------

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


def _zielordner(o: Objekt, kategorie: str) -> str:
    unterordner = ZIELORDNER.get(kategorie, "99_Sonstiges")
    if unterordner not in STRUKTUR:
        raise HTTPException(400, f"Unbekannter Zielordner '{unterordner}'")
    return f"{o.nc_ordner.strip('/')}/{unterordner}"


def _einsortieren(session: Session, d: Dokument, o: Objekt, kategorie: str,
                  name: str, client=None) -> tuple[str, str]:
    """Verschiebt die Datei an ihren Platz. Gibt (Pfad, Dateiname) zurück.

    Liegt sie schon dort, passiert nichts — MOVE auf sich selbst wäre ein
    Fehler, und ein zweiter Name („…-2") wäre eine Lüge."""
    ordner = _zielordner(o, kategorie)
    if d.pfad.strip("/") == f"{ordner}/{name}":
        return d.pfad, name
    client = client or verbindung(session)
    client.ordner_anlegen(ordner)
    frei = _freier_name(client, ordner, name)
    client.verschiebe(d.pfad, f"{ordner}/{frei}")
    return f"/{ordner}/{frei}", frei


# --------------------------------------------------------------------------
# Eingang einlesen
# --------------------------------------------------------------------------

_index_geprueft = False


def _eindeutigkeit_sichern(session: Session) -> None:
    """Ein Pfad, ein Eintrag — durchgesetzt von der Datenbank.

    Additiv: der Index kommt hinzu, keine Spalte ändert sich. Enthält eine
    gewachsene Datenbank bereits Doppel, scheitert das Anlegen — dann bleibt
    es bei der Sperre im Code, und die Doppel entfernt der Nutzer selbst.
    """
    global _index_geprueft
    if _index_geprueft:
        return
    _index_geprueft = True
    try:
        session.connection().execute(text(
            'CREATE UNIQUE INDEX IF NOT EXISTS "ux_dokument_pfad" '
            'ON dokument (pfad)'))
        session.commit()
    except Exception as fehler:                       # noqa: BLE001
        session.rollback()
        log.warning("Doppelte Pfade in der Ablage — Index nicht gesetzt: %s",
                    fehler)


def _aufnehmen(session: Session, o: Objekt, eintrag) -> Dokument | None:
    """Legt einen Eingangseintrag an. `None`, wenn es ihn schon gibt."""
    if session.exec(select(Dokument)
                    .where(Dokument.pfad == eintrag.pfad)).first():
        return None
    d = Dokument(pfad=eintrag.pfad, dateiname=eintrag.name,
                 groesse=eintrag.groesse, objekt_id=o.id, status="neu",
                 erkannt_am=date.today())
    session.add(d)
    try:
        session.commit()
    except IntegrityError:
        # Der andere Rufer war schneller — genau dafür ist der Index da.
        session.rollback()
        return None
    session.refresh(d)
    return d


def _automatisch(session: Session, d: Dokument, o: Objekt, client) -> bool:
    """Ordnet zu, wo nichts zu raten bleibt: die Immobilie steht durch den
    Ordner fest, die Art ergibt sich aus dem Namen. Alles andere wartet auf
    eine Entscheidung."""
    vorschlag = _vorschlag(d)
    if not vorschlag["kategorie"] or not o.nc_ordner:
        return False
    name = dateiname(vorschlag["jahr"], vorschlag["kategorie"], "",
                     _endung(d.dateiname))
    try:
        d.pfad, d.dateiname = _einsortieren(session, d, o,
                                            vorschlag["kategorie"], name, client)
    except NextcloudFehler as fehler:
        log.warning("Automatik übersprungen für %s: %s", d.pfad, fehler)
        return False
    d.kategorie = vorschlag["kategorie"]
    d.jahr = vorschlag["jahr"]
    d.status = "zugeordnet"
    session.add(d)
    session.commit()
    return True


@router.post("/scan")
def scan(session: Session = Depends(get_session)) -> dict:
    """Liest die Objektordner in der Nextcloud und nimmt neue Dateien auf.

    Läuft nie zweimal gleichzeitig: der Wachdienst und dieser Handlauf teilen
    sich eine Sperre. Wer zu spät kommt, wartet nicht — er bekommt Bescheid,
    denn der andere Lauf liest ohnehin gerade dieselben Ordner."""
    if not sperre.acquire(blocking=False):
        raise HTTPException(409, "Der Eingang wird gerade geprüft — "
                                 "einen Moment, dann noch einmal versuchen.")
    try:
        return _scanne(session)
    finally:
        sperre.release()


def _scanne(session: Session) -> dict:
    _eindeutigkeit_sichern(session)
    client = verbindung(session)
    neu = automatisch = 0
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
            d = _aufnehmen(session, o, e)
            if not d:
                continue
            neu += 1
            if _automatisch(session, d, o, client):
                automatisch += 1
    return {"neu": neu, "automatisch": automatisch,
            "offen": neu - automatisch}


# --------------------------------------------------------------------------
# Liste mit Filtern — eine Ansicht für Eingang und Ablage
# --------------------------------------------------------------------------

@router.get("")
def liste(objekt: str = "", kategorie: str = "", jahr: int | None = None,
          status: str = "", suche: str = "",
          session: Session = Depends(get_session)) -> dict:
    """Alle Dokumente, gefiltert. Die Auswahlwerte kommen mit — die Oberfläche
    baut ihre Filter aus dem, was wirklich da ist."""
    objekte = {o.id: o for o in session.exec(select(Objekt)).all()}
    nach_slug = {o.slug: o for o in objekte.values()}
    alle = session.exec(select(Dokument)).all()

    if objekt and objekt not in nach_slug:
        raise HTTPException(404, "Objekt nicht gefunden")
    ziel_id = nach_slug[objekt].id if objekt else None
    begriff = suche.strip().lower()

    def passt(d: Dokument) -> bool:
        return ((not ziel_id or d.objekt_id == ziel_id)
                and (not kategorie or d.kategorie == kategorie)
                and (jahr is None or d.jahr == jahr)
                and (not status or d.status == status)
                and (not begriff or begriff in d.dateiname.lower()))

    gefiltert = [d for d in alle if passt(d)]
    # Offenes zuerst, danach das Neueste — so steht oben, was etwas will.
    gefiltert.sort(key=lambda d: (d.status != "neu", -(d.jahr or 0),
                                  d.dateiname.lower()))

    genutzt = {d.kategorie for d in alle if d.kategorie}
    jahre = sorted({d.jahr for d in alle if d.jahr}, reverse=True)
    je_objekt: dict[int, int] = {}
    for d in alle:
        if d.objekt_id:
            je_objekt[d.objekt_id] = je_objekt.get(d.objekt_id, 0) + 1

    return {
        "anzahl": len(gefiltert),
        "gesamt": len(alle),
        "offen": sum(1 for d in alle if d.status == "neu"),
        "arten": DOKUMENTARTEN,
        "kategorien": [a for a in DOKUMENTARTEN if a in genutzt],
        "jahre": jahre,
        "objekte": [{"slug": o.slug, "name": o.name,
                     "anzahl": je_objekt.get(o.id, 0),
                     "cloud": bool(o.nc_ordner)}
                    for o in objekte.values()],
        "dokumente": [_zeige(d, objekte) for d in gefiltert],
    }


@router.get("/objekt/{slug}")
def je_objekt(slug: str, session: Session = Depends(get_session)) -> list[dict]:
    """Die zugeordneten Dokumente einer Immobilie — dieselbe Auswahl wie
    `?objekt=…&status=zugeordnet`, nur als schlichte Liste für Aufrufer, die
    keine Filterwerte brauchen."""
    return liste(objekt=slug, status="zugeordnet", session=session)["dokumente"]


@router.get("/wachdienst")
def wachdienst_status() -> dict:
    """Wann zuletzt automatisch nachgesehen wurde."""
    return wachdienst_zustand()


@router.get("/erkennung")
def erkennung_status() -> dict:
    """Ist die Texterkennung eingerichtet? Steuert den Hinweis in der App."""
    return {"verfuegbar": ocr.verfuegbar()}


@router.post("/erkennen")
async def erkennen(datei: UploadFile = File(...)) -> dict:
    """Liest Betrag, Datum und Art aus einer Aufnahme — als Vorschlag.

    Nichts wird gespeichert: das Bild geht durch die Erkennung und wieder weg.
    Fehlt Tesseract, kommt eine leere Antwort statt eines Fehlers zurück."""
    rohdaten = await datei.read()
    if not rohdaten:
        raise HTTPException(400, "Leere Datei")
    return ocr.erkenne(rohdaten)


# --------------------------------------------------------------------------
# Abfotografieren
# --------------------------------------------------------------------------

def _eindeutiges_objekt(session: Session, slug: str) -> Objekt:
    """Die gemeinte Immobilie. Ohne Angabe nur dann, wenn es genau eine gibt —
    raten wäre hier keine Hilfe, sondern eine falsche Ablage."""
    if slug:
        o = session.exec(select(Objekt).where(Objekt.slug == slug)).first()
        if not o:
            raise HTTPException(404, "Objekt nicht gefunden")
        return o
    alle = session.exec(select(Objekt)).all()
    if len(alle) != 1:
        raise HTTPException(400, "Bitte die Immobilie angeben")
    return alle[0]


def _cloud_pflicht(o: Objekt) -> None:
    """Ohne verknüpften Ordner gibt es keinen Ort für den Beleg. Das jetzt
    sagen ist besser, als ihn später nirgends zu finden."""
    if not o.nc_ordner:
        raise HTTPException(409, f"{o.name} ist mit keinem Nextcloud-Ordner "
                                 "verknüpft — der Beleg hätte dort keinen "
                                 "Platz. Bitte zuerst den Ordner verknüpfen.")


@router.post("/scannen", status_code=201)
async def scannen(objekt: str = Form(""), kategorie: str = Form("Sonstiges"),
                  jahr: int | None = Form(None), beschreibung: str = Form(""),
                  datei: UploadFile = File(...),
                  session: Session = Depends(get_session)) -> dict:
    """Nimmt ein abfotografiertes Dokument entgegen, benennt es nach Schema
    und legt es direkt im richtigen Unterordner der Immobilie ab."""
    o = _eindeutiges_objekt(session, objekt)
    _cloud_pflicht(o)

    inhalt = await datei.read()
    if not inhalt:
        raise HTTPException(400, "Leere Datei")

    kategorie = kategorie or "Sonstiges"
    name = dateiname(jahr, kategorie, beschreibung or "Scan", ".pdf")
    ziel_ordner = _zielordner(o, kategorie)
    client = verbindung(session)
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
    return {"id": d.id, "dateiname": name, "pfad": d.pfad, "abgelegt": True,
            "objekt": o.slug}


# --------------------------------------------------------------------------
# Kontrolle: ändern, verschieben, ersetzen, entfernen
# --------------------------------------------------------------------------

class AenderungIn(BaseModel):
    """Alles, was sich an einem Dokument ändern lässt. Was nicht mitkommt,
    bleibt wie es war — ein Endpunkt für Zuordnen und Korrigieren."""
    objekt: str | None = None
    kategorie: str | None = None
    jahr: int | None = None
    # Der Dateiname entsteht immer aus Jahr, Art und Bezeichnung — eine Regel
    # für die ganze Ablage. Umbenannt wird über die Bezeichnung.
    beschreibung: str | None = None
    verschieben: bool = True


@router.patch("/{dokument_id}")
def aendern(dokument_id: int, data: AenderungIn,
            session: Session = Depends(get_session)) -> dict:
    """Ordnet zu oder korrigiert: andere Immobilie, andere Art, anderes Jahr,
    anderer Name — die Datei wandert in der Nextcloud mit."""
    d = session.get(Dokument, dokument_id)
    if not d:
        raise HTTPException(404, "Dokument nicht gefunden")
    gesetzt = data.model_fields_set

    if data.objekt:
        o = session.exec(select(Objekt).where(Objekt.slug == data.objekt)).first()
        if not o:
            raise HTTPException(404, "Objekt nicht gefunden")
    else:
        o = session.get(Objekt, d.objekt_id) if d.objekt_id else None
        if not o:
            raise HTTPException(400, "Bitte die Immobilie angeben")

    kategorie = data.kategorie or d.kategorie or "Sonstiges"
    jahr = data.jahr if "jahr" in gesetzt else d.jahr
    endung = _endung(d.dateiname)

    if {"kategorie", "jahr", "beschreibung", "objekt"} & gesetzt:
        name = dateiname(jahr, kategorie, data.beschreibung or "", endung)
    else:
        name = d.dateiname

    verschoben = False
    if data.verschieben and d.pfad.startswith("/"):
        _cloud_pflicht(o)
        try:
            neuer_pfad, name = _einsortieren(session, d, o, kategorie, name)
        except NextcloudFehler as e:
            raise HTTPException(400, str(e)) from e
        verschoben = neuer_pfad != d.pfad
        d.pfad = neuer_pfad
    elif data.verschieben:
        # Eintrag ohne Datei in der Cloud: Ehrlichkeit vor Erfolgsmeldung.
        raise HTTPException(409, "Zu diesem Eintrag gibt es keine Datei in der "
                                 "Cloud — bitte neu einscannen oder entfernen.")

    d.objekt_id = o.id
    d.kategorie = kategorie
    d.jahr = jahr
    d.dateiname = name
    d.status = "zugeordnet"
    session.add(d)
    session.commit()
    return {"ok": True, "id": d.id, "pfad": d.pfad, "dateiname": d.dateiname,
            "objekt": o.slug, "kategorie": kategorie, "jahr": jahr,
            "verschoben": verschoben}


@router.delete("/{dokument_id}")
def entfernen(dokument_id: int,
              session: Session = Depends(get_session)) -> dict:
    """Nimmt das Dokument aus der App. Die Datei in der Nextcloud bleibt —
    dort wird grundsätzlich nichts gelöscht."""
    d = session.get(Dokument, dokument_id)
    if not d:
        raise HTTPException(404, "Dokument nicht gefunden")
    pfad = d.pfad
    session.delete(d)
    session.commit()
    log.info("Dokumenteintrag entfernt: %s (Datei bleibt)", pfad)
    return {"ok": True, "pfad": pfad, "datei_bleibt": True,
            "hinweis": "Der Eintrag ist weg, die Datei liegt weiter in der "
                       "Nextcloud."}


@router.post("/{dokument_id}/neu")
async def neu_einscannen(dokument_id: int, datei: UploadFile = File(...),
                         session: Session = Depends(get_session)) -> dict:
    """Ersetzt den Beleg durch eine neue Aufnahme.

    Die alte Datei bleibt liegen — überschrieben oder gelöscht wird in der
    Nextcloud nichts. Der Eintrag zeigt danach auf die neue Aufnahme."""
    d = session.get(Dokument, dokument_id)
    if not d:
        raise HTTPException(404, "Dokument nicht gefunden")
    o = session.get(Objekt, d.objekt_id) if d.objekt_id else None
    if not o:
        raise HTTPException(400, "Dem Dokument fehlt die Immobilie")
    _cloud_pflicht(o)

    inhalt = await datei.read()
    if not inhalt:
        raise HTTPException(400, "Leere Datei")

    alt = d.pfad
    kategorie = d.kategorie or "Sonstiges"
    ordner = _zielordner(o, kategorie)
    # Die Aufnahme kommt als PDF; ein Eintrag, der vorher anders hieß, bekommt
    # seinen Schemanamen.
    name = (d.dateiname if d.dateiname.lower().endswith(".pdf")
            else dateiname(d.jahr, kategorie, "Scan", ".pdf"))
    client = verbindung(session)
    try:
        client.ordner_anlegen(ordner)
        name = _freier_name(client, ordner, name)
        client.lege_ab(f"{ordner}/{name}", inhalt)
    except NextcloudFehler as e:
        raise HTTPException(400, str(e)) from e

    d.pfad = f"/{ordner}/{name}"
    d.dateiname = name
    d.kategorie = kategorie
    d.groesse = len(inhalt)
    d.status = "zugeordnet"
    d.erkannt_am = date.today()
    session.add(d)
    session.commit()
    return {"ok": True, "id": d.id, "pfad": d.pfad, "dateiname": name,
            "alt": alt,
            "hinweis": "Die vorherige Datei bleibt in der Nextcloud liegen."}


@router.get("/{dokument_id}/inhalt")
def inhalt(dokument_id: int, session: Session = Depends(get_session)) -> Response:
    """Liefert die Datei aus der Nextcloud zur Ansicht im Browser.

    `inline` statt `attachment`: PDFs und Bilder sollen sich öffnen, nicht
    herunterladen. Rein lesend — an der Datei ändert sich nichts."""
    d = session.get(Dokument, dokument_id)
    if not d:
        raise HTTPException(404, "Dokument nicht gefunden")
    if not d.pfad.startswith("/"):
        raise HTTPException(409, "Dieses Dokument liegt noch nicht in der Cloud")
    client = verbindung(session)
    try:
        rohdaten, typ = client.hole(d.pfad)
    except NextcloudFehler as e:
        raise HTTPException(400, str(e)) from e
    # Nextcloud liefert für unbekannte Endungen octet-stream; das laedt der
    # Browser herunter, statt es anzuzeigen.
    if typ == "application/octet-stream" and d.dateiname.lower().endswith(".pdf"):
        typ = "application/pdf"
    name = d.dateiname.replace('"', "")
    return Response(content=rohdaten, media_type=typ, headers={
        "Content-Disposition": f'inline; filename="{name}"',
        "Cache-Control": "private, max-age=60",
    })
