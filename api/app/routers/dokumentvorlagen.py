"""N240/N247 — das Vorlagenarchiv: leere Formulare (Übergabeprotokoll,
Mieterselbstauskunft, Rauchwarnmelder-Abnahme, Wohnungsgeberbestätigung …),
getrennt von den echten Belegen des Nutzers.

Liegt in der Cloud unter `<Home>/00_Vorlagen/<verwendungszweck>/`, NICHT unter
einem Objekt-Ordner — eine Vorlage gehört zu keiner bestimmten Immobilie.
**Unterhalb des Home-Ordners** allerdings sehr wohl: N247 — die erste Fassung
schrieb nach `/Vorlagen` und lief damit zu Recht in den Riegel aus
`nextcloud.py::_pruefe_schreibrecht` („liegt ausserhalb von …"). Der Riegel
bleibt, der Pfad zieht um.

Der Nutzer legt seine Vorlagen selbst ab (Roh-PDF per Drop/Dateiauswahl) —
**kein Download aus dem Netz** und **kein Foto-Scan**: für ein leeres Formular
zum Ausdrucken taugt eine abfotografierte Seite nicht.

* `GET    /api/dokumentvorlagen`              — Liste + Typen-Katalog
* `POST   /api/dokumentvorlagen`              — eigene Vorlage hochladen
* `GET    /api/dokumentvorlagen/{id}/inhalt`  — die Datei zur Ansicht
* `DELETE /api/dokumentvorlagen/{id}`         — nur den Datenbankeintrag
"""
import json
import logging
import os
from datetime import date

from fastapi import (APIRouter, Depends, File, HTTPException, Query,
                     Response, UploadFile)
from pydantic import BaseModel
from sqlmodel import Session, select

from .. import drucker as druckdienst
from .. import ocr
from ..cloudkern import _lies, verbindung
from ..db import get_session
from ..dokumente.namen import _dateiname_kopfzeile, _endung, _saubere_datei
from ..models import Dokumentvorlage
from ..nextcloud import NextcloudFehler
from .cloud import _schreib

log = logging.getLogger("immocalc")
drucker_router = APIRouter(prefix="/api/drucker", tags=["drucker"])
router = APIRouter(prefix="/api/dokumentvorlagen", tags=["dokumentvorlagen"])

# Unter dem Home-Ordner, nicht daneben (N247). Die „00_" hält den Ordner in der
# Nextcloud oben — er gehört zu keiner Immobilie und soll nicht zwischen ihnen
# untergehen.
VORLAGEN_ORDNER = "00_Vorlagen"

# N247 — nur diese Dateiarten. Ein leeres Formular wird ausgedruckt und
# ausgefüllt; ein abfotografiertes JPEG taugt dafür nicht. Der Riegel steht
# hier UND im Frontend (`accept`), damit auch ein direkter API-Aufruf ihn nicht
# umgeht.
ERLAUBTE_ENDUNGEN = (".pdf", ".doc", ".docx", ".odt")

# N247 — der Katalog: welche Vorlagen für eine Vermietung sinnvoll sind. Die
# Typen entsprechen den Zeilen der Mietverhältnis-Checkliste (`SCAN_TYPEN` in
# `objekt/state.js`), damit die Vorlage dort neben der passenden Zeile auftaucht.
# Bewusst OHNE Mietvertrag — der ist zu individuell für eine Vorlage.
# Die Liste beschreibt nur, WELCHE Zeilen es gibt; gefüllt wird von Hand.
TYPEN_KATALOG = [
    {"verwendungszweck": "Vermietung", "typ": "Übergabeprotokoll Einzug",
     "name": "Übergabeprotokoll (Einzug)",
     "hinweis": "Zustand und Zählerstände bei Übergabe an den Mieter."},
    {"verwendungszweck": "Vermietung", "typ": "Übergabeprotokoll Auszug",
     "name": "Übergabeprotokoll (Auszug)",
     "hinweis": "Zustand und Zählerstände bei Rückgabe der Wohnung."},
    {"verwendungszweck": "Vermietung", "typ": "Mieterselbstauskunft",
     "name": "Mieterselbstauskunft",
     "hinweis": "Angaben des Bewerbers vor Abschluss des Mietvertrags."},
    {"verwendungszweck": "Vermietung", "typ": "Abnahmeprotokoll Rauchwarnmelder",
     "name": "Abnahmeprotokoll Rauchwarnmelder",
     "hinweis": "Einbau und Abnahme der Rauchwarnmelder je Raum."},
    {"verwendungszweck": "Vermietung", "typ": "Wohnungsgeberbestätigung",
     "name": "Wohnungsgeberbestätigung",
     "hinweis": "Nach § 19 Bundesmeldegesetz — der Mieter braucht sie für die "
                "Anmeldung beim Bürgeramt."},
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
    """Legt `<Home>/00_Vorlagen/<Zweck>` an (405-sicher) und gibt ihn zurück.

    N247 — der Home-Ordner kommt aus der Einstellung (`client.heimat`), nicht
    aus einer festen Zeichenkette: er heisst bei jedem Nutzer anders. Ohne ihn
    schriebe ImmoCalc nirgends, das sagt der Riegel selbst — hier aber vorher
    im Klartext, statt den Nutzer an einer WebDAV-Meldung raten zu lassen."""
    heim = (getattr(client, "heimat", "") or "").strip("/")
    if not heim:
        raise HTTPException(400, "Kein Home-Ordner in den Einstellungen "
                                 "gewählt — ImmoCalc legt dort nichts ab.")
    ordner = f"{heim}/{VORLAGEN_ORDNER}"
    client.ordner_anlegen(ordner)
    ordner = f"{ordner}/{_saubere_datei(verwendungszweck)}"
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
    """Die Vorlagen, optional nach Verwendungszweck/Typ gefiltert.

    Dazu der `typen`-Katalog (N247): welche Vorlagen es überhaupt geben
    sollte. Die Oberfläche zeigt dadurch für JEDE Art eine Zeile — auch für
    die noch leeren — und braucht die Liste nicht selbst zu kennen."""
    frage = select(Dokumentvorlage)
    katalog = TYPEN_KATALOG
    if verwendungszweck:
        frage = frage.where(Dokumentvorlage.verwendungszweck == verwendungszweck)
        katalog = [t for t in katalog
                   if t["verwendungszweck"] == verwendungszweck]
    if typ:
        frage = frage.where(Dokumentvorlage.typ == typ)
        katalog = [t for t in katalog if t["typ"] == typ]
    alle = session.exec(frage).all()
    alle = sorted(alle, key=lambda v: (v.verwendungszweck, v.name.lower()))
    return {"anzahl": len(alle), "vorlagen": [_zeige(v) for v in alle],
            "typen": katalog}


def _pruefe_dateiart(dateiname: str) -> None:
    """N247 — nur ausdruckbare Formulare, keine Fotos.

    Der Nutzer war ausdrücklich: hier gehören Roh-PDFs hin, keine Scans — ein
    abfotografiertes Formular ist als Vordruck unbrauchbar. Das Frontend bietet
    deshalb gar keine Kamera an; dieser Riegel hält auch einen direkten
    API-Aufruf davon ab."""
    if _endung(dateiname).lower() not in ERLAUBTE_ENDUNGEN:
        raise HTTPException(
            400, "Für Vorlagen sind nur PDF- oder Textdokumente vorgesehen "
                 f"({', '.join(ERLAUBTE_ENDUNGEN)}) — ein abfotografiertes "
                 "Formular taugt nicht als Vordruck.")


@router.post("", status_code=201)
async def hochladen(name: str, verwendungszweck: str = "Vermietung",
                    typ: str = "", quelle_url: str = "", hinweis: str = "",
                    datei: UploadFile = File(...),
                    session: Session = Depends(get_session)) -> dict:
    """Legt eine eigene Vorlage ab — der einzige Weg, wie eine Vorlage in das
    Archiv kommt (N247: kein Download aus dem Netz mehr).

    Gibt es zu diesem Typ schon eine Vorlage, ERSETZT die neue sie: der alte
    Datenbankeintrag verschwindet, seine Datei bleibt unangetastet in der
    Cloud liegen. So bleibt es bei einer Vorlage je Art, ohne je etwas zu
    löschen, das dem Nutzer gehört."""
    _pruefe_dateiart(datei.filename or "")
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
    if typ:
        for alt in session.exec(select(Dokumentvorlage).where(
                Dokumentvorlage.verwendungszweck == verwendungszweck,
                Dokumentvorlage.typ == typ)).all():
            log.info("Vorlage ersetzt: %s weicht %s (Datei bleibt)",
                     alt.pfad, frei)
            session.delete(alt)
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


def _vorlage_bytes(session: Session, vorlage_id: int) -> tuple[Dokumentvorlage, bytes, str]:
    """Die Vorlage samt Datei — gemeinsame Vorstufe von Seitenzahl und Vorschau."""
    v = _eintrag(session, vorlage_id)
    if not v.pfad.startswith("/"):
        raise HTTPException(409, "Diese Vorlage liegt noch nicht in der Cloud")
    client = verbindung(session)
    try:
        rohdaten, typ = client.hole(v.pfad)
    except NextcloudFehler as e:
        raise HTTPException(400, str(e)) from e
    return v, rohdaten, typ


# N265 — dieselben zwei Endpunkte, die auch ein Beleg hat. Der gemeinsame
# Betrachter (`belegAnsehen`) fragt erst `/seiten` und holt dann je Seite ein
# Bild; fehlten sie, fiel er auf „Im neuen Tab öffnen" zurück — die Vorlage
# lag korrekt in der Cloud, sah aber aus wie kaputt.
@router.get("/{vorlage_id}/seiten")
def seiten(vorlage_id: int, session: Session = Depends(get_session)) -> dict:
    """Wie viele Bildseiten die Vorschau dieser Vorlage hat. 0 heisst: nicht
    als Bild darstellbar (z. B. docx) — dann bleibt der neue Tab der Weg."""
    v, rohdaten, typ = _vorlage_bytes(session, vorlage_id)
    name = (v.dateiname or "").lower()
    if name.endswith(".pdf") or typ == "application/pdf":
        return {"seiten": ocr.seiten_anzahl(rohdaten)}
    if typ.startswith("image/") or name.endswith(
            (".jpg", ".jpeg", ".png", ".gif", ".webp")):
        return {"seiten": 1}
    return {"seiten": 0}


@router.get("/{vorlage_id}/vorschau")
def vorschau(vorlage_id: int, seite: int = Query(0, ge=0),
             session: Session = Depends(get_session)) -> Response:
    """Seite `seite` als Bild. 416, wenn es die Seite nicht gibt; 415, wenn
    sich die Datei gar nicht rendern lässt — beides beantwortet die Oberfläche
    mit dem Hinweis statt mit einem leeren Rahmen."""
    v, rohdaten, typ = _vorlage_bytes(session, vorlage_id)
    name = (v.dateiname or "").lower()
    if name.endswith(".pdf") or typ == "application/pdf":
        anzahl = ocr.seiten_anzahl(rohdaten)
        if anzahl and seite >= anzahl:
            raise HTTPException(416, f"Diese Vorlage hat nur {anzahl} Seite(n)")
        png = ocr.seite_png(rohdaten, seite)
        if png is None:
            raise HTTPException(415, "Vorschau nicht möglich")
        return Response(content=png, media_type="image/png",
                        headers={"Cache-Control": "private, max-age=300"})
    if typ.startswith("image/") or name.endswith(
            (".jpg", ".jpeg", ".png", ".gif", ".webp")):
        if seite > 0:
            raise HTTPException(416, "Diese Vorlage hat nur eine Seite")
        return Response(content=rohdaten,
                        media_type=typ if typ.startswith("image/") else "image/jpeg",
                        headers={"Cache-Control": "private, max-age=300"})
    raise HTTPException(415, "Für diese Datei gibt es keine Bildvorschau")


# --------------------------------------------------------------------------
# N264/N275 — Vorlage direkt auf einen Drucker im Haus
#
# Eine Vorlage ist ein leeres Formular; man will sie in der Hand haben, nicht
# auf dem Schirm. Deshalb je Drucker ein Knopf statt Herunterladen-Öffnen-
# Drucken.
#
# N275 — der Nutzer pflegt seine Drucker mit IP und Port selbst in den
# Einstellungen; geschickt wird direkt dorthin (Port 9100). Der Weg über einen
# CUPS-Dienst bleibt als Rückfall, solange kein Drucker eingetragen ist.
# Ist beides nicht da, bleibt die Liste leer — die Oberfläche zeigt dann gar
# keine Druckknöpfe, statt welche anzubieten, die ins Leere laufen.
#
# Gespeichert wird als JSON in EINER Einstellungszeile, wie schon bei den
# Unterordner-Vorlagen: ein Schlüssel je Drucker und Feld wäre ein Dutzend
# Zeilen für eine Liste. Keine neue Tabelle.
# --------------------------------------------------------------------------

S_DRUCKER = "drucker_liste"


class DruckerIn(BaseModel):
    name: str
    ip: str
    port: int = druckdienst.RAW_PORT
    standort: str = ""


def _druckdienst() -> str:
    return os.environ.get("DRUCKDIENST", "").strip()


def _konfiguriert(session: Session) -> list[dict]:
    """Die eingetragenen Drucker. Unlesbar Gespeichertes wird gemeldet und
    übergangen, nie zum Fehler — eine kaputte Zeile darf keine Seite kippen."""
    roh = _lies(session, S_DRUCKER)
    if not roh:
        return []
    try:
        geladen = json.loads(roh)
    except ValueError as fehler:
        log.warning("Druckerliste unlesbar: %s", fehler)
        return []
    if not isinstance(geladen, list):
        return []
    return [d for d in geladen if isinstance(d, dict) and d.get("name")]


def _drucker_mit_namen(session: Session, name: str) -> dict:
    for d in _konfiguriert(session):
        if d.get("name") == name:
            return d
    raise HTTPException(404, f"Kein Drucker namens {name} eingetragen")


@drucker_router.get("")
def drucker_liste(session: Session = Depends(get_session)) -> dict:
    """Die Drucker des Hauses: `[{name, ip, port, standort}]`.

    Zuerst die eingetragenen; nur wenn gar keiner gepflegt ist, kommen die
    Warteschlangen eines CUPS-Dienstes (ohne IP — dort geht es über den
    Dienst). Leer heisst: keine Druckknöpfe.

    `quelle` sagt, welcher der beiden Fälle vorliegt: die Einstellungsseite
    darf nur eigene Einträge zum Bearbeiten anbieten — eine CUPS-Warteschlange
    gehört ihr nicht."""
    eigene = _konfiguriert(session)
    if eigene:
        return {"drucker": eigene, "dienst": "", "quelle": "eigene"}
    dienst = _druckdienst()
    if not dienst:
        return {"drucker": [], "dienst": "", "quelle": "eigene"}
    return {"drucker": [{"name": d["name"], "ip": "", "port": 0,
                         "standort": d.get("ort", "")}
                        for d in druckdienst.drucker_liste(dienst)],
            "dienst": dienst, "quelle": "cups"}


@drucker_router.put("")
def drucker_speichern(liste: list[DruckerIn],
                      session: Session = Depends(get_session)) -> dict:
    """Die ganze Liste auf einmal — Anlegen, Ändern und Entfernen sind
    derselbe Vorgang. Geprüft wird VOR dem Speichern: eine Adresse, aus der
    keine TCP-Verbindung werden kann, kommt gar nicht erst in die Ablage."""
    sauber: list[dict] = []
    for d in liste:
        name = (d.name or "").replace("/", " ").strip()
        if not name:
            raise HTTPException(400, "Jeder Drucker braucht einen Namen")
        grund = druckdienst.pruefe_ziel(d.ip, d.port)
        if grund:
            raise HTTPException(400, f"{name}: {grund}")
        sauber.append({"name": name, "ip": d.ip.strip(), "port": int(d.port),
                       "standort": (d.standort or "").strip()})
    _schreib(session, S_DRUCKER, json.dumps(sauber, ensure_ascii=False))
    session.commit()
    log.info("Druckerliste gespeichert: %d Gerät(e)", len(sauber))
    return {"drucker": sauber}


@drucker_router.post("/{name}/pruefen")
def drucker_pruefen(name: str, session: Session = Depends(get_session)) -> dict:
    """Nur ein TCP-Handschlag auf IP:Port — es wird nichts gedruckt.
    Papier und Toner gehören dem Nutzer."""
    d = _drucker_mit_namen(session, name)
    return {"erreichbar": druckdienst.erreichbar(d.get("ip", ""),
                                                 int(d.get("port") or 0))}


@router.post("/{vorlage_id}/drucken")
def vorlage_drucken(vorlage_id: int, drucker: str,
                    session: Session = Depends(get_session)) -> dict:
    """Schickt die Vorlage an einen Drucker. Rein lesend, was die Ablage
    angeht — die Datei wird geholt und weitergereicht, nichts verändert.

    N275 — ist der Drucker eingetragen, gehen die Bytes direkt an IP:Port.
    Die Meldung sagt bewusst „geschickt", nicht „gedruckt": über Port 9100
    gibt es keine Rückmeldung, ob das Gerät ein PDF versteht."""
    eigene = _konfiguriert(session)
    if not eigene and not _druckdienst():
        raise HTTPException(503, "Es ist kein Drucker eingerichtet")
    v, rohdaten, _typ = _vorlage_bytes(session, vorlage_id)
    titel = v.name or v.dateiname
    if eigene:
        ziel = _drucker_mit_namen(session, drucker)
        geklappt, meldung = druckdienst.roh_drucken(
            ziel.get("ip", ""), int(ziel.get("port") or 0), rohdaten, titel)
    else:
        geklappt, meldung = druckdienst.drucken(
            _druckdienst(), drucker, rohdaten, titel=titel)
    if not geklappt:
        raise HTTPException(502, meldung)
    log.info("Vorlage %s an %s geschickt", vorlage_id, drucker)
    return {"ok": True, "meldung": meldung, "drucker": drucker}


@router.delete("/{vorlage_id}")
def loeschen(vorlage_id: int, session: Session = Depends(get_session)) -> dict:
    """Entfernt nur den Datenbankeintrag — die Datei bleibt in der Cloud und
    lässt sich jederzeit neu verlinken oder von Hand aufräumen."""
    v = _eintrag(session, vorlage_id)
    session.delete(v)
    session.commit()
    log.info("Dokumentvorlage-Eintrag %d entfernt (Datei bleibt)", vorlage_id)
    return {"ok": True}
