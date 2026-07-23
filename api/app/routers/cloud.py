"""Nextcloud-Anbindung: einrichten, Ordner durchsehen, Struktur anlegen."""
import json
import logging
import re
from datetime import date

from fastapi import (APIRouter, Depends, File, Form, HTTPException, Query,
                     UploadFile)
from pydantic import BaseModel
from sqlmodel import Session, select

from ..bezeichnung import (PLATZHALTER, STANDARD_UNTERORDNER, STANDARD_VORLAGE,
                           UNTERORDNER_PLATZHALTER, VERBOTENE_ZEICHEN,
                           datum_aus_namen, doppelt_geschachtelt,
                           gleicher_ordner, lagebezeichnung, nach_vorlage,
                           ordnerpfad, pfadteile, unterordner_finden,
                           unterordner_name, unterordner_pruefen, vorlage_pruefen)
from ..cloudkern import (ARTKUERZEL, STRUKTUR, S_HOME, S_TLS, S_UNTERORDNER,
                        S_URL, S_BENUTZER, S_PASSWORT, ZIELORDNER, _lies,
                        einheit_von, struktur_fuer, unterordner_fuer,
                        unterordner_vorlagen, verbindung)
from ..db import get_session
from ..models import Dokument, Einstellung, Objekt
from ..nextcloud import Nextcloud, NextcloudFehler
from .dokumente import _einsortieren

log = logging.getLogger("immocalc")
router = APIRouter(prefix="/api/nextcloud", tags=["nextcloud"])

S_VORLAGE = "nc_ordner_vorlage"


def ordner_fuer(session: Session, objekt: Objekt) -> str:
    """Ordnername nach der eingestellten Vorlage."""
    return nach_vorlage(
        _lies(session, S_VORLAGE) or STANDARD_VORLAGE,
        ort=objekt.ort, strasse=objekt.strasse, name=objekt.name,
        plz=objekt.plz, typ=objekt.typ, nutzung=objekt.nutzung,
        gemarkung=getattr(objekt, "gemarkung", "") or "",
        flurstueck=getattr(objekt, "flurstueck", "") or "",
        # Fuer ein Grundstueck tritt Gemarkung/Flurstueck an die Stelle der
        # Strasse — sonst bliebe der Ordnername an dieser Stelle leer.
        lage=lagebezeichnung(objekt.strasse,
                             getattr(objekt, "gemarkung", "") or "",
                             getattr(objekt, "flurstueck", "") or ""))


def _pfad(pfad: str) -> str:
    """Ein Pfad in einer Schreibweise: führender Trenner, keine Doppelungen."""
    return "/" + "/".join(pfadteile(pfad))


def _eltern(pfad: str) -> str:
    return "/" + "/".join(pfadteile(pfad)[:-1])


def zielordner_fuer(session: Session, objekt: Objekt, home: str) -> str:
    """Wo der Ordner dieser Immobilie nach dem aktuellen Schema läge."""
    return _pfad(ordnerpfad(home, ordner_fuer(session, objekt)))


def _schreib(session: Session, schluessel: str, wert: str) -> None:
    eintrag = session.get(Einstellung, schluessel)
    if eintrag:
        eintrag.wert = wert
    else:
        eintrag = Einstellung(schluessel=schluessel, wert=wert)
    session.add(eintrag)


class VerbindungIn(BaseModel):
    url: str
    benutzer: str
    passwort: str
    tls_pruefen: bool = False


@router.get("/status")
def status(session: Session = Depends(get_session)) -> dict:
    """Zustand der Verbindung — ohne das Passwort preiszugeben."""
    url, benutzer = _lies(session, S_URL), _lies(session, S_BENUTZER)
    passwort = _lies(session, S_PASSWORT)
    return {
        "eingerichtet": bool(url and benutzer and passwort),
        "url": url,
        "benutzer": benutzer,
        "passwort": "•••• gespeichert" if passwort else "",
        "home": _lies(session, S_HOME),
        "tls_pruefen": _lies(session, S_TLS) == "1",
        "struktur": STRUKTUR,
    }


@router.post("/verbindung")
def verbindung_speichern(data: VerbindungIn,
                         session: Session = Depends(get_session)) -> dict:
    """Prüft die Zugangsdaten und speichert sie erst bei Erfolg."""
    client = Nextcloud(data.url, data.benutzer, data.passwort,
                       zertifikat_pruefen=data.tls_pruefen)
    try:
        ergebnis = client.pruefe()
    except NextcloudFehler as e:
        raise HTTPException(400, str(e)) from e

    _schreib(session, S_URL, data.url.rstrip("/"))
    _schreib(session, S_BENUTZER, data.benutzer)
    _schreib(session, S_PASSWORT, data.passwort)
    _schreib(session, S_TLS, "1" if data.tls_pruefen else "0")
    session.commit()
    log.info("Nextcloud verbunden als %s", data.benutzer)
    return ergebnis


@router.get("/ordner")
def ordner(pfad: str = Query(default=""),
           session: Session = Depends(get_session)) -> dict:
    """Unterordner eines Pfades — Grundlage für die Ordnerauswahl."""
    client = verbindung(session)
    try:
        eintraege = client.liste(pfad)
    except NextcloudFehler as e:
        raise HTTPException(400, str(e)) from e
    hoch = "/".join(pfad.strip("/").split("/")[:-1]) if pfad.strip("/") else None
    return {
        "pfad": "/" + pfad.strip("/") if pfad.strip("/") else "",
        "hoch": hoch,
        "ordner": [{"name": e.name, "pfad": e.pfad}
                   for e in eintraege if e.ordner],
        "dateien": sum(1 for e in eintraege if not e.ordner),
    }


class HomeIn(BaseModel):
    pfad: str


@router.post("/home")
def home_speichern(data: HomeIn, session: Session = Depends(get_session)) -> dict:
    """Legt den Ordner fest, unter dem alle Immobilien angelegt werden."""
    client = verbindung(session)
    try:
        client.liste(data.pfad)          # muss existieren
    except NextcloudFehler as e:
        raise HTTPException(400, str(e)) from e
    # Der Ordner einer Immobilie ist kein Heimatordner: darunter entstünde er
    # gleich noch einmal, und alle anderen Immobilien lägen in seinem Inneren.
    gewaehlt = _pfad(data.pfad)
    for o in session.exec(select(Objekt)).all():
        if o.nc_ordner and _pfad(o.nc_ordner) == gewaehlt:
            raise HTTPException(
                400, f"'{gewaehlt}' ist der Ordner von {o.name}. Bitte den "
                     "übergeordneten Ordner wählen, in dem alle Immobilien liegen.")
    _schreib(session, S_HOME, "/" + data.pfad.strip("/"))
    session.commit()
    return {"home": "/" + data.pfad.strip("/")}


class VorlageIn(BaseModel):
    vorlage: str


@router.get("/vorlage")
def vorlage_lesen(session: Session = Depends(get_session)) -> dict:
    """Aktuelle Namensvorlage mit Beispielen aus den echten Objekten."""
    vorlage = _lies(session, S_VORLAGE) or STANDARD_VORLAGE
    objekte = session.exec(select(Objekt)).all()[:4]
    return {
        "vorlage": vorlage,
        "standard": STANDARD_VORLAGE,
        "platzhalter": list(PLATZHALTER),
        "verboten": VERBOTENE_ZEICHEN,
        "beispiele": [{"objekt": o.name,
                       "ordner": nach_vorlage(vorlage, ort=o.ort, strasse=o.strasse,
                                              name=o.name, plz=o.plz, typ=o.typ,
                                              nutzung=o.nutzung)}
                      for o in objekte],
    }


@router.post("/vorlage")
def vorlage_speichern(data: VorlageIn,
                      session: Session = Depends(get_session)) -> dict:
    """Speichert die Vorlage.

    Bereits angelegte Ordner bleiben zunächst, wie sie sind — verschoben wird
    nur auf Knopfdruck. `umzug_noetig` sagt, wie viele Ordner der neuen
    Benennung noch nachziehen müssten (siehe /umzug)."""
    hinweise = vorlage_pruefen(data.vorlage)
    if any("keinen Platzhalter" in h or "leer" in h for h in hinweise):
        raise HTTPException(400, " ".join(hinweise))
    _schreib(session, S_VORLAGE, data.vorlage.strip())
    session.commit()
    try:
        offen = umzug_plan(session, mit_cloud=False)["anzahl"]
    except HTTPException:
        offen = 0                      # ohne Home-Ordner gibt es nichts zu ziehen
    return {"vorlage": data.vorlage.strip(), "hinweise": hinweise,
            "umzug_noetig": offen}


# --------------------------------------------------------------------------
# CXCI: Unterordner im Sachordner — eine Vorlage je Dokumentart
#
# Dieselbe Mechanik wie beim Objektordner, eine Ebene tiefer: eine Vorlage,
# Platzhalter, Beispielvorschau. Nur die Vorgaben unterscheiden sich, und die
# stammen aus dem Bestand des Nutzers (siehe `bezeichnung.STANDARD_UNTERORDNER`).
# --------------------------------------------------------------------------

class UnterordnerIn(BaseModel):
    vorlagen: dict[str, str]


def _unterordner_antwort(session: Session) -> dict:
    """Vorlagen, Platzhalter und ein Beispiel je Art — wie bei /vorlage.

    Das Beispiel rechnet mit dem laufenden Jahr und der Einheit der ersten
    Immobilie, die eine hat: so sieht der Nutzer den Ordnernamen, der heute
    entstünde, statt einer Vorlage mit geschweiften Klammern."""
    vorlagen = unterordner_vorlagen(session)
    objekte = session.exec(select(Objekt)).all()
    einheit = next((e for e in (einheit_von(o) for o in objekte) if e), "")
    jahr = date.today().year
    return {
        "jahr": jahr,
        "einheit": einheit,
        "platzhalter": list(UNTERORDNER_PLATZHALTER),
        "verboten": VERBOTENE_ZEICHEN,
        "arten": [{
            "art": art,
            "ordner": ordner,
            "vorlage": vorlagen.get(art, ""),
            "standard": STANDARD_UNTERORDNER.get(art, ""),
            "beispiel": unterordner_name(vorlagen.get(art, ""), jahr,
                                         einheit=einheit, art=art),
        } for art, ordner in ZIELORDNER.items()],
    }


@router.get("/unterordner")
def unterordner_lesen(session: Session = Depends(get_session)) -> dict:
    """Die Unterordner-Vorlagen je Dokumentart samt Beispiel für dieses Jahr."""
    return _unterordner_antwort(session)


@router.post("/unterordner")
def unterordner_speichern(data: UnterordnerIn,
                          session: Session = Depends(get_session)) -> dict:
    """Speichert die Vorlagen.

    Bereits abgelegte Belege bleiben liegen, wo sie liegen — verschoben wird
    hier nichts. Die neue Ordnung gilt für alles, was ab jetzt hereinkommt."""
    unbekannt = sorted(set(data.vorlagen) - set(ZIELORDNER))
    if unbekannt:
        raise HTTPException(400, "Unbekannte Dokumentart: "
                                 + ", ".join(unbekannt))
    hinweise: list[str] = []
    for art, vorlage in data.vorlagen.items():
        hinweise += [f"{art}: {h}" for h in unterordner_pruefen(vorlage)]
    if any("Platzhalter:" in h for h in hinweise):
        raise HTTPException(400, " ".join(hinweise))

    gespeichert = {**unterordner_vorlagen(session),
                   **{a: v.strip() for a, v in data.vorlagen.items()}}
    _schreib(session, S_UNTERORDNER, json.dumps(gespeichert, ensure_ascii=False))
    session.commit()
    log.info("Unterordner-Vorlagen gespeichert: %s", gespeichert)
    return {"hinweise": hinweise, **_unterordner_antwort(session)}


@router.get("/objekte/{slug}/status")
def objekt_status(slug: str, session: Session = Depends(get_session)) -> dict:
    """Ist dieses Objekt schon mit einem Ordner verknüpft? Was fehlt noch?"""
    objekt = session.exec(select(Objekt).where(Objekt.slug == slug)).first()
    if not objekt:
        raise HTTPException(404, "Objekt nicht gefunden")
    home = _lies(session, S_HOME)
    verbunden = bool(_lies(session, S_URL) and _lies(session, S_PASSWORT))
    return {
        "cloud_verbunden": verbunden,
        "home": home,
        "ordner": objekt.nc_ordner,
        "bereit": bool(verbunden and home),
        "angelegt": bool(objekt.nc_ordner),
        "vorschlag": zielordner_fuer(session, objekt, home).lstrip("/")
                     if home else "",
        "struktur": struktur_fuer(objekt),
    }


@router.get("/objekte/{slug}/ordner")
def objekt_ordner(slug: str, session: Session = Depends(get_session)) -> dict:
    """Was wirklich im Objektordner liegt.

    Selbst angelegte Ordner werden ausgewiesen und bleiben unangetastet —
    ImmoCalc legt nur an, was in STRUKTUR steht, und ändert nichts daran."""
    objekt = session.exec(select(Objekt).where(Objekt.slug == slug)).first()
    if not objekt:
        raise HTTPException(404, "Objekt nicht gefunden")
    if not objekt.nc_ordner:
        return {"verknuepft": False, "ordner": [], "eigene": [], "fehlend": []}

    try:
        eintraege = verbindung(session).liste(objekt.nc_ordner)
    except NextcloudFehler as e:
        raise HTTPException(400, str(e)) from e

    vorhanden = [e.name for e in eintraege if e.ordner]
    bekannt = set(STRUKTUR)
    return {
        "verknuepft": True,
        "wurzel": objekt.nc_ordner,
        "ordner": [{"name": n, "eigen": n not in bekannt} for n in vorhanden],
        "eigene": [n for n in vorhanden if n not in bekannt],
        "fehlend": [n for n in struktur_fuer(objekt) if n not in vorhanden],
        "dateien": sum(1 for e in eintraege if not e.ordner),
    }


@router.post("/objekte/{slug}/struktur")
def struktur_anlegen(slug: str, session: Session = Depends(get_session)) -> dict:
    """Legt Objektordner samt Unterstruktur unter dem Home-Ordner an.
    Bestehende Ordner und Dateien bleiben unberührt."""
    home = _lies(session, S_HOME)
    if not home:
        raise HTTPException(400, "Kein Home-Ordner gewählt")
    objekt = session.exec(select(Objekt).where(Objekt.slug == slug)).first()
    if not objekt:
        raise HTTPException(404, "Objekt nicht gefunden")

    # Sprechender Ordnername statt "Wohnung 1.OG" — sonst kollidieren
    # gleichnamige Einheiten verschiedener Adressen. Ist der Home-Ordner selbst
    # schon dieser Ordner, wird er nicht ein zweites Mal darunter angelegt.
    ziel = (_pfad(objekt.nc_ordner) if objekt.nc_ordner
            else zielordner_fuer(session, objekt, home)).strip("/")
    client = verbindung(session)
    try:
        neu = client.ordner_baum_anlegen(ziel, struktur_fuer(objekt))
    except NextcloudFehler as e:
        raise HTTPException(400, str(e)) from e

    objekt.nc_ordner = "/" + ziel.strip("/")
    session.add(objekt)
    session.commit()
    return {"ordner": objekt.nc_ordner, "neu_angelegt": neu,
            "unveraendert": len(struktur_fuer(objekt)) + 1 - len(neu)}


# --------------------------------------------------------------------------
# CCLI — Originalgetreu spiegeln: den eigenen Ordnerbaum 1:1 in die Cloud.
#
# Anders als der Beleg-Scan (der nach Kategorie umsortiert und umbenennt) legt
# `spiegeln` eine Datei UNVERÄNDERT an ihrem Ort im Objektordner ab — gleiche
# Unterordner, gleicher Name. `leeren` räumt den Objektordner davor, damit ein
# sauberer Neuaufbau möglich ist. Beides ausdrücklich vom Nutzer angestoßen.
# --------------------------------------------------------------------------
def _saubere_teile(subpfad: str) -> list[str]:
    """Relativer Pfad → sichere Teile (kein '..', keine leeren, kein führendes /)."""
    roh = (subpfad or "").replace("\\", "/").split("/")
    return [t.strip() for t in roh if t.strip() and t.strip() != ".."]


# Hauptordner → Kategorie, damit ein gespiegelter Beleg gleich eine sinnvolle
# Kategorie trägt (die genaue Kostenart bestimmt später der Nutzer/die Regeln).
_HAUPT_KATEGORIE = {
    "60_Nebenkosten": "Nebenkosten",
    "70_Steuer_Finanzamt": "Steuer",
    "40_Kauf_Eigentum_Finanzierung": "Kredit",
    "20_Mietvertraege_Vermietung": "Mietvertrag",
    "51_Mieterhoehungen": "Mietvertrag",
    "30_Kommunikation": "Korrespondenz",
    "80_Hausverwaltung": "Hausverwaltung",
    "55_Eigentuemerversammlungen": "Hausverwaltung",
}


def _jahr_aus_name(name: str) -> int | None:
    treffer = re.search(r"(19|20)\d{2}", name or "")
    return int(treffer.group(0)) if treffer else None


@router.post("/objekte/{slug}/leeren")
def objekt_leeren(slug: str, session: Session = Depends(get_session)) -> dict:
    """Löscht ALLE Inhalte des Objektordners (Dateien und Unterordner) — für
    einen sauberen Neuaufbau. Der Objektordner selbst bleibt. Nur unterhalb des
    Home-Ordners (Schreibschutz)."""
    objekt = session.exec(select(Objekt).where(Objekt.slug == slug)).first()
    if not objekt:
        raise HTTPException(404, "Objekt nicht gefunden")
    if not objekt.nc_ordner:
        return {"geloescht": 0}
    client = verbindung(session)
    wurzel = _pfad(objekt.nc_ordner).strip("/")
    geloescht = 0
    try:
        for e in client.liste(objekt.nc_ordner):
            client.loesche(f"{wurzel}/{e.name}")
            geloescht += 1
    except NextcloudFehler as e:
        raise HTTPException(400, str(e)) from e
    return {"ordner": objekt.nc_ordner, "geloescht": geloescht}


@router.post("/objekte/{slug}/spiegeln", status_code=201)
async def objekt_spiegeln(slug: str, subpfad: str = Form(...),
                          datei: UploadFile = File(...),
                          session: Session = Depends(get_session)) -> dict:
    """Legt eine Datei UNVERÄNDERT unter `subpfad` im Objektordner ab — die
    Ordnerkette wird angelegt, der Dateiname bleibt. Für die 1:1-Übertragung
    des eigenen Archivs, ohne Umbenennung oder Umsortierung."""
    objekt = session.exec(select(Objekt).where(Objekt.slug == slug)).first()
    if not objekt:
        raise HTTPException(404, "Objekt nicht gefunden")
    if not objekt.nc_ordner:
        raise HTTPException(400, "Objekt ist mit keinem Cloud-Ordner verknüpft")
    teile = _saubere_teile(subpfad)
    if not teile:
        raise HTTPException(400, "Kein gültiger Zielpfad")
    inhalt = await datei.read()
    if not inhalt:
        raise HTTPException(400, "Leere Datei")
    client = verbindung(session)
    pfad = _pfad(objekt.nc_ordner).strip("/")
    try:
        for ordner in teile[:-1]:            # Ordnerkette anlegen (405 = existiert)
            pfad = f"{pfad}/{ordner}"
            client.ordner_anlegen(pfad)
        ziel = f"{pfad}/{teile[-1]}"
        client.lege_ab(ziel, inhalt,
                       typ=datei.content_type or "application/octet-stream")
    except NextcloudFehler as e:
        raise HTTPException(400, str(e)) from e
    # Beim Spiegeln gleich indexieren, damit die App die Datei kennt (der
    # Abgleich adoptiert direkt platzierte Dateien sonst nicht). Kategorie aus
    # dem Hauptordner, Jahr aus dem Namen — genau wird es später bestimmt.
    haupt = teile[0] if len(teile) >= 2 else ""
    d = Dokument(pfad="/" + ziel, dateiname=teile[-1], groesse=len(inhalt),
                 objekt_id=objekt.id,
                 kategorie=_HAUPT_KATEGORIE.get(haupt, "Sonstiges"),
                 jahr=_jahr_aus_name(teile[-1]), status="zugeordnet",
                 erkannt_am=date.today())
    session.add(d)
    try:
        session.commit()
    except Exception:                       # noqa: BLE001 — Pfad schon indexiert
        session.rollback()
    return {"pfad": "/" + ziel}


# --------------------------------------------------------------------------
# Umzug: das Benennungsschema für alle Immobilien nachziehen
#
# Ändert sich die Vorlage, heißen die bestehenden Ordner weiter wie früher.
# Dieser Vorgang zieht sie nach — ausdrücklich angestoßen, nie automatisch und
# nie im Wachdienst: hier wandern echte Unterlagen.
#
# Erst der Trockenlauf (GET /umzug), dann die Ausführung (POST /umzug).
# Verschoben wird per MOVE, gelöscht wird nichts, überschrieben nichts, und
# `Dokument.pfad` wandert nur mit, wenn der MOVE wirklich geklappt hat.
# --------------------------------------------------------------------------

class UmzugFehler(RuntimeError):
    """Dieser Ordner bleibt, wo er ist — der Rest zieht trotzdem um."""


def _dokumente_unter(session: Session, ordner: str) -> list[Dokument]:
    """Alle Belege unterhalb dieses Pfades — und der Beleg, der genau er ist.

    Beim Entschachteln wandert jedes Kind einzeln, und ein Kind kann auch eine
    lose Datei sein, die direkt im Objektordner liegt. Ohne den Gleichstand
    bliebe ihr `Dokument.pfad` stehen, während die Datei längst eine Ebene
    höher läge — der Eintrag zeigte ins Leere, und gezählt würde sie auch
    nicht. Bei einem Ordner ändert die Gleichheit nichts: ein Beleg ist eine
    Datei, nie der Ordner selbst."""
    selbst = _pfad(ordner)
    praefix = selbst + "/"
    return [d for d in session.exec(select(Dokument)).all()
            if _pfad(d.pfad) == selbst or _pfad(d.pfad).startswith(praefix)]


def _umgehaengt(pfad: str, von: str, nach: str) -> str:
    """Derselbe Beleg, gesehen vom neuen Ordner aus."""
    return _pfad(nach) + _pfad(pfad)[len(_pfad(von)):]


def _plan_fuer(session: Session, objekt: Objekt, home: str) -> dict | None:
    """Was mit dem Ordner dieser Immobilie geschehen müsste — oder nichts."""
    ist = _pfad(objekt.nc_ordner)
    soll = zielordner_fuer(session, objekt, home)
    if ist == soll:
        return None

    if doppelt_geschachtelt(ist) and _eltern(ist) == soll:
        art = "entschachteln"
        hinweis = ("Der Ordner liegt in einem Ordner desselben Namens. Sein "
                   "Inhalt wandert eine Ebene höher; der leere Ordner bleibt "
                   "stehen — gelöscht wird in der Nextcloud nichts.")
    else:
        art = "verschieben"
        hinweis = "Der Ordner bekommt den Namen aus der aktuellen Vorlage."

    return {
        "objekt": objekt.slug, "name": objekt.name, "art": art,
        "von": ist, "nach": soll, "hinweis": hinweis,
        "dokumente": [{"id": d.id, "dateiname": d.dateiname, "von": d.pfad,
                       "nach": _umgehaengt(d.pfad, ist, soll)}
                      for d in _dokumente_unter(session, ist)],
    }


def _verwaiste_ordner(session: Session, home: str, benutzt: set[str]) -> list[str]:
    """Ordner unter dem Home-Ordner, zu denen keine Immobilie mehr gehört.

    Reiner Hinweis: angefasst wird davon nichts. Meist Reste einer früheren
    Benennung, die der Nutzer selbst sortieren möchte."""
    from .objekte import SICHERUNGSORDNER          # zirkelfrei zur Laufzeit
    eintraege = verbindung(session).liste(home)
    return [_pfad(e.pfad) for e in eintraege
            if e.ordner and e.name != SICHERUNGSORDNER
            and _pfad(e.pfad) not in benutzt]


def umzug_plan(session: Session, mit_cloud: bool = True) -> dict:
    """Trockenlauf: was das aktuelle Schema an den Ordnern ändern würde.

    Rein rechnend — die Cloud wird nur für die verwaisten Ordner gelesen, und
    scheitert das, bleibt der Plan trotzdem stehen. `mit_cloud=False` lässt
    auch das weg, wo es nur um die Anzahl geht."""
    home = _lies(session, S_HOME)
    if not home:
        raise HTTPException(400, "Kein Home-Ordner gewählt")

    schritte, unveraendert, ohne_ordner = [], [], []
    benutzt: set[str] = set()
    for o in session.exec(select(Objekt)).all():
        if not o.nc_ordner:
            ohne_ordner.append({"objekt": o.slug, "name": o.name})
            continue
        benutzt.add(_pfad(o.nc_ordner))
        schritt = _plan_fuer(session, o, home)
        if schritt:
            benutzt.add(schritt["nach"])
            schritte.append(schritt)
        else:
            unveraendert.append({"objekt": o.slug, "name": o.name,
                                 "ordner": _pfad(o.nc_ordner)})

    hinweise: list[str] = []
    verwaist: list[str] = []
    if mit_cloud:
        try:
            verwaist = _verwaiste_ordner(session, home, benutzt)
        except (HTTPException, NextcloudFehler) as fehler:
            hinweise.append(f"Verwaiste Ordner nicht geprüft: {fehler}")

    return {
        "home": _pfad(home),
        "vorlage": _lies(session, S_VORLAGE) or STANDARD_VORLAGE,
        "schritte": schritte,
        "anzahl": len(schritte),
        "dokumente": sum(len(s["dokumente"]) for s in schritte),
        "unveraendert": unveraendert,
        "ohne_ordner": ohne_ordner,
        "verwaist": verwaist,
        "hinweise": hinweise,
    }


def _freier_ordner(client: Nextcloud, ziel: str) -> str:
    """Ein Zielname, den es noch nicht gibt — überschrieben wird nie."""
    kandidat, n = ziel, 2
    while client.existiert(kandidat):
        kandidat, n = f"{ziel}-{n}", n + 1
        if n > 50:
            raise UmzugFehler(f"Kein freier Name für '{ziel}' gefunden")
    return kandidat


def _pfade_pruefen(session: Session, von: str, nach: str) -> None:
    """Zeigt schon ein anderer Eintrag auf einen der neuen Pfade?

    Vor dem ersten MOVE gefragt: der Unique-Index würde es sonst erst danach
    verhindern — die Dateien lägen am neuen Platz und die Ablage am alten."""
    betroffen = _dokumente_unter(session, von)
    eigene = {d.id for d in betroffen}
    neue = {_umgehaengt(d.pfad, von, nach) for d in betroffen}
    for d in session.exec(select(Dokument)).all():
        if d.id not in eigene and _pfad(d.pfad) in neue:
            raise UmzugFehler(
                f"Zu '{d.pfad}' gibt es bereits einen anderen Eintrag — "
                "bitte diesen Beleg zuerst klären.")


def _pfade_umschreiben(session: Session, von: str, nach: str) -> list[int]:
    """Hängt die Belege an den neuen Ort. Erst nach geglücktem MOVE.

    `von` ist der bewegte Ordner — oder die bewegte Datei selbst. Die
    zurückgegebenen ids sind zugleich die Zählung für die Rückmeldung."""
    betroffen = _dokumente_unter(session, von)
    for d in betroffen:
        d.pfad = _umgehaengt(d.pfad, von, nach)
        session.add(d)
    return [d.id for d in betroffen]


def _verschiebe_ordner(session: Session, client: Nextcloud, von: str,
                       nach: str) -> tuple[str, list[int]]:
    """Ordner umbenennen bzw. verschieben — samt der Belege darin."""
    frei = _freier_ordner(client, nach)
    _pfade_pruefen(session, von, frei)
    client.verschiebe(von, frei)
    return frei, _pfade_umschreiben(session, von, frei)


def _entschachtele(session: Session, client: Nextcloud, von: str,
                   nach: str) -> tuple[str, list[int], list[str]]:
    """Hebt den Inhalt eines "X/X"-Ordners eine Ebene höher.

    Der leere Ordner bleibt stehen. Was oben schon existiert, bleibt liegen und
    wird gemeldet — überschrieben wird nichts. Weil der innere Ordner unterhalb
    des äußeren liegt, bleiben auch stehengebliebene Belege auffindbar.

    Jeder Unterordner wird einzeln festgeschrieben: stolpert der dritte, sollen
    die ersten beiden nicht wieder auf ihren alten Pfad zurückfallen — dort
    liegen sie ja nicht mehr."""
    _pfade_pruefen(session, von, nach)
    bewegt: list[int] = []
    geblieben: list[str] = []
    for kind in client.liste(von):
        ziel = f"{_pfad(nach)}/{kind.name}"
        if client.existiert(ziel):
            geblieben.append(kind.name)
            continue
        client.verschiebe(_pfad(kind.pfad), ziel)
        bewegt += _pfade_umschreiben(session, _pfad(kind.pfad), ziel)
        session.commit()
    return _pfad(nach), bewegt, geblieben


# --------------------------------------------------------------------------
# CCLXIII: Objektordner beim Speichern der Stammdaten automatisch umbenennen
#
# Ändert der Nutzer Ort, Straße, Name o. Ä., ergibt die Vorlage einen anderen
# Ordnernamen. Statt eines eigenen „Umbenennen"-Knopfs zieht der Ordner direkt
# beim Speichern nach — dieselbe Mechanik wie der große Umzug, aber für genau
# eine Immobilie und in ihrem bisherigen Elternordner (reine Umbenennung, kein
# Wechsel des Home-Ordners; das Entschachteln bleibt dem expliziten Umzug).
#
# Aufgerufen aus `objekte.objekt_aendern`, NACHDEM die Stammdaten schon
# festgeschrieben sind. Reihenfolge wie beim Umzug: erst MOVE (auf einen freien
# Namen, nie überschreiben), dann `Dokument.pfad` per Präfix und `nc_ordner`
# nachziehen, dann committen. Scheitert der MOVE, bleibt in der Datenbank alles
# beim Alten — der alte Ordner ebenso — und der Aufrufer behält die übrigen
# Stammdaten-Änderungen.
# --------------------------------------------------------------------------

def ordner_nachziehen(session: Session, objekt: Objekt,
                      war_name: str = "") -> dict:
    """Benennt den Objektordner um, wenn der abgeleitete Name sich geändert hat.

    Rein additiv und still, wenn nichts zu tun ist: ohne verknüpften Ordner,
    ohne Home-Ordner, ohne eingerichtete Cloud oder bei unverändertem Namen
    passiert nichts und es fliegt kein Fehler. Der Rückgabewert sagt, was
    geschah — der Aufrufer hängt ihn nur als Hinweis an seine Antwort.

    `war_name` ist der Vorlagenname aus den *alten* Stammdaten. Ist er gesetzt
    und trägt der Ordner ihn gerade, folgte er bisher der Vorlage und darf
    nachziehen. Weicht der Ordner davon ab, hat der Nutzer ihn selbst benannt —
    dann wird nichts erzwungen."""
    if not objekt.nc_ordner:
        return {"umbenannt": False, "grund": "kein Ordner verknüpft"}
    if not _lies(session, S_HOME):
        return {"umbenannt": False, "grund": "kein Home-Ordner"}
    try:
        client = verbindung(session)
    except HTTPException as fehler:
        return {"umbenannt": False, "grund": fehler.detail}

    von = _pfad(objekt.nc_ordner)
    if war_name and not gleicher_ordner(pfadteile(von)[-1], war_name):
        return {"umbenannt": False, "grund": "Ordner folgt nicht der Vorlage"}
    # Reine Umbenennung: der neue Name entsteht im bisherigen Elternordner.
    # `ordnerpfad` verhindert dabei, dass ein Ordner gleichen Namens doppelt
    # geschachtelt würde.
    nach = _pfad(ordnerpfad(_eltern(von), ordner_fuer(session, objekt)))
    if nach == von:
        return {"umbenannt": False, "grund": "Name unverändert"}

    try:
        frei = _freier_ordner(client, nach)     # nie überschreiben
        _pfade_pruefen(session, von, frei)       # Unique-Index vor dem MOVE
        client.verschiebe(von, frei)             # MOVE, geprüftes Schreibrecht
    except (NextcloudFehler, UmzugFehler) as fehler:
        # Der MOVE ist nicht geglückt — Datenbank und alter Ordner bleiben, wie
        # sie sind. Kein Verweis zeigt ins Leere.
        log.warning("Ordner-Umbenennung übersprungen für %s: %s", von, fehler)
        return {"umbenannt": False, "von": von, "nach": nach,
                "fehler": str(fehler)}

    # MOVE geglückt — erst jetzt zieht die Datenbank nach.
    dokumente = _pfade_umschreiben(session, von, frei)
    objekt.nc_ordner = frei
    session.add(objekt)
    session.commit()
    log.info("Objektordner umbenannt: %s -> %s (%d Belege)",
             von, frei, len(dokumente))
    return {"umbenannt": True, "von": von, "nach": frei,
            "dokumente": len(dokumente)}


@router.get("/umzug")
def umzug_pruefen(session: Session = Depends(get_session)) -> dict:
    """Trockenlauf — zeigt alt → neu, je Ordner und je Beleg. Ändert nichts.

    Ohne verbundene Cloud gibt es schlicht nichts nachzuziehen — das ist eine
    Auskunft, kein Fehler. Vorher antwortete schon der Trockenlauf mit 400,
    und die Einstellungsseite trug beim blossen Aufruf einen Fehler in die
    Konsole. Die Ausführung (POST) bleibt dagegen bei 400: dort ist der
    fehlende Home-Ordner wirklich ein Hindernis.
    """
    if not _lies(session, S_HOME):
        return {"moeglich": False,
                "grund": "Noch keine Nextcloud verbunden",
                "schritte": [], "anzahl": 0, "unveraendert": [],
                "ohne_ordner": [], "verwaist": [], "hinweise": []}
    return {"moeglich": True, "grund": "", **umzug_plan(session)}


@router.post("/umzug")
def umzug_ausfuehren(session: Session = Depends(get_session)) -> dict:
    """Zieht die Ordner aller Immobilien auf das aktuelle Schema nach.

    Ein misslungener Ordner hält den Rest nicht auf: er wird gemeldet, seine
    Immobilie bleibt verknüpft wie bisher, und kein Beleg wechselt dabei
    seinen Pfad."""
    plan = umzug_plan(session)
    client = verbindung(session)
    erledigt: list[dict] = []
    fehler: list[dict] = []
    bewegt = 0

    for schritt in plan["schritte"]:
        objekt = session.exec(
            select(Objekt).where(Objekt.slug == schritt["objekt"])).first()
        if not objekt:
            continue
        von, nach = schritt["von"], schritt["nach"]
        try:
            if schritt["art"] == "entschachteln":
                ziel, dokumente, geblieben = _entschachtele(session, client,
                                                            von, nach)
            else:
                ziel, dokumente = _verschiebe_ordner(session, client, von, nach)
                geblieben = []
            objekt.nc_ordner = ziel
            session.add(objekt)
            session.commit()
        except Exception as f:                       # noqa: BLE001
            # Die Datenbank bleibt, wie sie war — der nächste Ordner ist dran.
            session.rollback()
            log.warning("Umzug übersprungen für %s: %s", von, f)
            fehler.append({"objekt": schritt["objekt"], "von": von,
                           "nach": nach, "fehler": str(f)})
            continue
        bewegt += len(dokumente)
        log.info("Umzug: %s -> %s (%d Belege)", von, ziel, len(dokumente))
        erledigt.append({"objekt": schritt["objekt"], "name": schritt["name"],
                         "art": schritt["art"], "von": von, "nach": ziel,
                         "dokumente": len(dokumente), "geblieben": geblieben})

    return {"verschoben": erledigt, "anzahl": len(erledigt),
            "dokumente": bewegt, "fehler": fehler,
            "unveraendert": len(plan["unveraendert"]),
            "verwaist": plan["verwaist"]}


# --------------------------------------------------------------------------
# CXCII: Altbestand in die Jahres-Unterordner umziehen
#
# Seit CXCI wandert jeder neue Beleg in einen Jahresordner („60_Nebenkosten/
# 2025", „70_Steuer_Finanzamt/Steuer_2024" …). Was vorher schon abgelegt wurde,
# liegt aber noch flach im Sachordner. Dieser Vorgang zieht es nach —
# ausdrücklich angestoßen, nie im Wachdienst.
#
# Bewegt wird ausschließlich, was flach in einem bekannten Sachordner liegt UND
# einen Dokument-Eintrag hat. Selbst angelegte Unterordner
# („Ablesungsergebnisse", „M-Net Kosten", „_sonstige") bleiben unangetastet,
# ebenso Dateien ohne Eintrag. Ein Beleg ohne erkennbares Jahr bleibt liegen —
# ein Ordner „ohne-Jahr" hülfe niemandem beim Wiederfinden. Verschoben wird per
# MOVE auf einen freien Namen; `Dokument.pfad` zieht erst nach geglücktem MOVE
# mit, je Datei einzeln festgeschrieben.
# --------------------------------------------------------------------------

def _sachordner_kategorie() -> dict[str, str]:
    """Sachordner-Name → Dokumentart. Umkehrung von `ZIELORDNER`."""
    return {ordner: art for art, ordner in ZIELORDNER.items()}


def _flache_belege(session: Session, objekt: Objekt,
                   nach_ordner: dict[str, str]) -> list[tuple[Dokument, str]]:
    """Belege, die genau eine Ebene tief in einem bekannten Sachordner liegen.

    Nur solche werden umgezogen: eine lose Datei direkt im Objektordner (eine
    Ebene) gehört zum großen Umzug, ein Beleg in einem Jahresordner (drei
    Ebenen) liegt schon richtig, und ein selbst angelegter Ordner ist kein
    Sachordner und fällt hier ohnehin heraus."""
    wurzel = _pfad(objekt.nc_ordner)
    ergebnis: list[tuple[Dokument, str]] = []
    for d in session.exec(select(Dokument)
                          .where(Dokument.objekt_id == objekt.id)).all():
        if d.status == "vermisst":
            continue                     # die Datei liegt gar nicht mehr da
        rel = _pfad(d.pfad)
        if not rel.startswith(wurzel + "/"):
            continue
        teile = pfadteile(rel[len(wurzel):])
        if len(teile) != 2:              # [Sachordner, Dateiname]
            continue
        kategorie = nach_ordner.get(teile[0])
        if kategorie:
            ergebnis.append((d, kategorie))
    return ergebnis


def _ziel_unterordner(session: Session, objekt: Objekt, kategorie: str,
                      jahr: int, client) -> tuple[str, str] | None:
    """(Sachordner, Ablageordner) für diesen Beleg — oder None, wenn er flach
    bleibt (leere Vorlage).

    Ein bereits vorhandener Jahresordner wird wiederverwendet statt
    danebengestellt: liegt „2025" schon da, wandert der Beleg dorthin und nicht
    in ein zweites. Ohne erreichbare Cloud gilt der Name aus der Vorlage — das
    ist kein Fehler, nur eine Auskunft, die es noch nicht gibt."""
    ziel = unterordner_fuer(session, objekt, kategorie, jahr)
    if not ziel:
        return None
    sach = f"{_pfad(objekt.nc_ordner)}/{ZIELORDNER[kategorie]}".rstrip("/")
    vorhandene: list[str] = []
    if client is not None:
        try:
            vorhandene = [e.name for e in client.liste(sach) if e.ordner]
        except NextcloudFehler as fehler:
            log.info("Unterordner von %s nicht gelesen: %s", sach, fehler)
    treffer = unterordner_finden(vorhandene, jahr, ziel,
                                 (kategorie, ARTKUERZEL.get(kategorie, "")))
    return sach, f"{sach}/{treffer or ziel}"


def unterordner_umzug_plan(session: Session, client=None) -> dict:
    """Trockenlauf: welche flach abgelegten Belege in einen Jahresordner ziehen.

    Rein rechnend bis auf das Lesen vorhandener Unterordner — und das scheitert
    lautlos, wenn die Cloud gerade nicht antwortet. Belege ohne Jahr werden
    getrennt ausgewiesen: sie bleiben liegen."""
    home = _lies(session, S_HOME)
    if not home:
        raise HTTPException(400, "Kein Home-Ordner gewählt")

    nach_ordner = _sachordner_kategorie()
    schritte: list[dict] = []
    ohne_jahr: list[dict] = []
    for o in session.exec(select(Objekt)).all():
        if not o.nc_ordner:
            continue
        dokumente: list[dict] = []
        for d, kategorie in _flache_belege(session, o, nach_ordner):
            jahr = d.jahr or datum_aus_namen(d.dateiname)[0]
            if not jahr:
                ohne_jahr.append({"id": d.id, "dateiname": d.dateiname,
                                  "objekt": o.slug, "pfad": d.pfad})
                continue
            ziel = _ziel_unterordner(session, o, kategorie, jahr, client)
            if not ziel:
                continue                 # leere Vorlage: bleibt flach
            _sach, ordner = ziel
            neu = f"{ordner}/{d.dateiname}"
            if _pfad(d.pfad) == _pfad(neu):
                continue                 # liegt schon richtig
            dokumente.append({"id": d.id, "dateiname": d.dateiname,
                              "kategorie": kategorie, "jahr": jahr,
                              "von": d.pfad, "nach": _pfad(neu)})
        if dokumente:
            schritte.append({"objekt": o.slug, "name": o.name,
                             "dokumente": dokumente})

    return {
        "home": _pfad(home),
        "schritte": schritte,
        "anzahl": len(schritte),
        "dokumente": sum(len(s["dokumente"]) for s in schritte),
        "ohne_jahr": ohne_jahr,
    }


@router.get("/unterordner-umzug")
def unterordner_umzug_pruefen(session: Session = Depends(get_session)) -> dict:
    """Trockenlauf — zeigt alt → neu je Beleg. Ändert nichts.

    Ohne verbundene Cloud gibt es nichts einzusortieren: das ist eine Auskunft,
    kein Fehler (wie bei /umzug)."""
    if not _lies(session, S_HOME):
        return {"moeglich": False, "grund": "Noch keine Nextcloud verbunden",
                "schritte": [], "anzahl": 0, "dokumente": 0, "ohne_jahr": []}
    try:
        client = verbindung(session)
    except HTTPException:
        client = None
    return {"moeglich": True, "grund": "",
            **unterordner_umzug_plan(session, client)}


@router.post("/unterordner-umzug")
def unterordner_umzug_ausfuehren(session: Session = Depends(get_session)) -> dict:
    """Zieht die flach abgelegten Belege in ihre Jahresordner.

    Jede Datei einzeln: MKCOL für den Jahresordner (405 = existiert, ok), MOVE
    auf einen freien Namen, dann erst `Dokument.pfad` nachziehen und
    festschreiben. Eine misslungene Datei hält den Rest nicht auf — sie wird
    gemeldet, ihr Eintrag bleibt unverändert."""
    client = verbindung(session)
    plan = unterordner_umzug_plan(session, client)
    erledigt: list[dict] = []
    fehler: list[dict] = []

    for schritt in plan["schritte"]:
        objekt = session.exec(
            select(Objekt).where(Objekt.slug == schritt["objekt"])).first()
        if not objekt:
            continue
        for dok in schritt["dokumente"]:
            d = session.get(Dokument, dok["id"])
            if not d:
                continue
            try:
                neu_pfad, neu_name = _einsortieren(
                    session, d, objekt, dok["kategorie"], d.dateiname, client,
                    dok["jahr"])
                d.pfad, d.dateiname = neu_pfad, neu_name
                session.add(d)
                session.commit()
            except Exception as f:                    # noqa: BLE001
                session.rollback()
                log.warning("Einsortieren übersprungen für %s: %s",
                            dok["von"], f)
                fehler.append({"id": dok["id"], "dateiname": dok["dateiname"],
                               "objekt": schritt["objekt"], "von": dok["von"],
                               "fehler": str(f)})
                continue
            log.info("Einsortiert: %s -> %s", dok["von"], neu_pfad)
            erledigt.append({"id": dok["id"], "objekt": schritt["objekt"],
                             "name": schritt["name"], "von": dok["von"],
                             "nach": neu_pfad})

    return {"verschoben": erledigt, "anzahl": len(erledigt),
            "dokumente": len(erledigt), "fehler": fehler,
            "ohne_jahr": len(plan["ohne_jahr"])}
