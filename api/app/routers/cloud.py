"""Nextcloud-Anbindung: einrichten, Ordner durchsehen, Struktur anlegen."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from ..bezeichnung import (PLATZHALTER, STANDARD_VORLAGE, VERBOTENE_ZEICHEN,
                           doppelt_geschachtelt, nach_vorlage, ordnerpfad,
                           pfadteile, vorlage_pruefen)
from ..db import get_session
from ..models import Dokument, Einstellung, Objekt
from ..nextcloud import Nextcloud, NextcloudFehler

log = logging.getLogger("immocalc")
router = APIRouter(prefix="/api/nextcloud", tags=["nextcloud"])

# Vereinheitlichte Struktur je Immobilie — Zehnerschritte lassen Platz zum
# Einfuegen, die Nummern folgen dem gewachsenen Bestand.
STRUKTUR = [
    "01_Allgemein_Hauskonto",
    "10_Fotos_Lage",
    "20_Mietvertraege_Vermietung",
    "30_Kommunikation",
    "40_Kauf_Eigentum_Finanzierung",
    "50_Bauphase_Projekte",
    "60_Nebenkosten",
    "70_Steuer_Finanzamt",
    "80_Hausverwaltung",
    "98_Archiv",
    "99_Sonstiges",
]

S_URL, S_BENUTZER, S_PASSWORT, S_HOME, S_TLS, S_VORLAGE = (
    "nc_url", "nc_benutzer", "nc_passwort", "nc_home", "nc_tls_pruefen",
    "nc_ordner_vorlage")


def ordner_fuer(session: Session, objekt: Objekt) -> str:
    """Ordnername nach der eingestellten Vorlage."""
    return nach_vorlage(
        _lies(session, S_VORLAGE) or STANDARD_VORLAGE,
        ort=objekt.ort, strasse=objekt.strasse, name=objekt.name,
        plz=objekt.plz, typ=objekt.typ, nutzung=objekt.nutzung)


def _pfad(pfad: str) -> str:
    """Ein Pfad in einer Schreibweise: führender Trenner, keine Doppelungen."""
    return "/" + "/".join(pfadteile(pfad))


def _eltern(pfad: str) -> str:
    return "/" + "/".join(pfadteile(pfad)[:-1])


def zielordner_fuer(session: Session, objekt: Objekt, home: str) -> str:
    """Wo der Ordner dieser Immobilie nach dem aktuellen Schema läge."""
    return _pfad(ordnerpfad(home, ordner_fuer(session, objekt)))


def _lies(session: Session, schluessel: str, vorgabe: str = "") -> str:
    eintrag = session.get(Einstellung, schluessel)
    return eintrag.wert if eintrag else vorgabe


def _schreib(session: Session, schluessel: str, wert: str) -> None:
    eintrag = session.get(Einstellung, schluessel)
    if eintrag:
        eintrag.wert = wert
    else:
        eintrag = Einstellung(schluessel=schluessel, wert=wert)
    session.add(eintrag)


def verbindung(session: Session) -> Nextcloud:
    url = _lies(session, S_URL)
    benutzer = _lies(session, S_BENUTZER)
    passwort = _lies(session, S_PASSWORT)
    if not (url and benutzer and passwort):
        raise HTTPException(400, "Nextcloud ist noch nicht eingerichtet")
    # heimat begrenzt jeden schreibenden Zugriff auf den gewählten Ordner
    return Nextcloud(url, benutzer, passwort,
                     zertifikat_pruefen=_lies(session, S_TLS) == "1",
                     heimat=_lies(session, S_HOME))


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
        "struktur": STRUKTUR,
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
        "fehlend": [n for n in STRUKTUR if n not in vorhanden],
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
        neu = client.ordner_baum_anlegen(ziel, STRUKTUR)
    except NextcloudFehler as e:
        raise HTTPException(400, str(e)) from e

    objekt.nc_ordner = "/" + ziel.strip("/")
    session.add(objekt)
    session.commit()
    return {"ordner": objekt.nc_ordner, "neu_angelegt": neu,
            "unveraendert": len(STRUKTUR) + 1 - len(neu)}


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
    """Alle Belege, die unterhalb dieses Ordners liegen."""
    praefix = _pfad(ordner) + "/"
    return [d for d in session.exec(select(Dokument)).all()
            if _pfad(d.pfad).startswith(praefix)]


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
    """Hängt die Belege an den neuen Ordner. Erst nach geglücktem MOVE."""
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


@router.get("/umzug")
def umzug_pruefen(session: Session = Depends(get_session)) -> dict:
    """Trockenlauf — zeigt alt → neu, je Ordner und je Beleg. Ändert nichts."""
    return umzug_plan(session)


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
