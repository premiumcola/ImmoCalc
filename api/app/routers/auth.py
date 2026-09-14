"""N436 — Familien-Anmeldung. Ohne Anmeldung erreichbar sind hier nur die
Wege HINEIN (`/zustand`, `/login`, `/login/2fa`, `/registrieren`,
`/passwort-festlegen`) — und keiner davon nennt je einen Namen, den der
Aufrufer nicht selbst geschickt hat. N469 #2: die frühere öffentliche
Auswahlliste `GET /familien` ist weg; auf einer Domain wäre sie eine
Nutzerliste zum Durchprobieren gewesen.

Reihenfolge egal (kein zweisegmentiger Fänger hier wie bei stammdaten.py),
aber registriert VOR `stammdaten` wie jeder andere Router auch (main.py)."""
from __future__ import annotations

import base64
import binascii
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import Session, select

from .. import totp
from ..auth import (MAX_FEHLVERSUCHE, MIN_PASSWORT, SITZUNG_COOKIE, SPERRDAUER,
                    cookie_sicher, einladungscode_noetig, einladungscode_stimmt,
                    neuer_sitzungstoken, neues_zweifaktorticket,
                    passwort_hashen, passwort_pruefen, token_hashen)
from ..db import get_session
from ..deps import aktuelle_familie
from ..models import Familie, Sitzung, ZweiFaktorTicket

log = logging.getLogger("immocalc")
router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegistrierenIn(BaseModel):
    name: str
    passwort: str
    logo_pfad: str | None = None
    einladungs_code: str | None = None


class PasswortFestlegenIn(BaseModel):
    familie_id: int | None = None
    name: str | None = None
    passwort: str


class LoginIn(BaseModel):
    """N469 #2 — der Anmeldescreen kennt keine Liste mehr, er schickt den
    NAMEN. `familie_id` bleibt als zweiter Weg erhalten (Tests, ältere
    Aufrufer); einer von beiden muss da sein."""
    familie_id: int | None = None
    name: str | None = None
    passwort: str


def _familie_oeffentlich(f: Familie) -> dict:
    """Die eigenen Daten der handelnden Familie — nur nach geprüftem Passwort
    oder mit laufender Sitzung. `hat_2fa` gehört genau deshalb hierher und
    in keine unangemeldete Antwort."""
    return {"id": f.id, "name": f.name, "logo_pfad": f.logo_pfad,
            "hat_passwort": f.passwort_hash is not None,
            "hat_2fa": f.totp_bestaetigt}


def _nach_name(session: Session, name: str) -> Familie | None:
    """Gross-/Kleinschreibung egal — „heidenreich" meint „Heidenreich"."""
    return session.exec(select(Familie).where(
        func.lower(Familie.name) == name.strip().lower())).first()


def _familie_finden(session: Session, familie_id: int | None,
                    name: str | None) -> Familie | None:
    if familie_id is not None:
        return session.get(Familie, familie_id)
    if name and name.strip():
        return _nach_name(session, name)
    return None


def _sitzung_setzen(response: Response, familie_id: int, session: Session) -> None:
    token, token_hash, laeuft_ab = neuer_sitzungstoken()
    session.add(Sitzung(familie_id=familie_id, token_hash=token_hash,
                        laeuft_ab=laeuft_ab))
    session.commit()
    response.set_cookie(SITZUNG_COOKIE, token, httponly=True, samesite="lax",
                        secure=cookie_sicher(),
                        max_age=int((laeuft_ab - datetime.utcnow())
                                    .total_seconds()))


@router.get("/zustand")
def zustand(session: Session = Depends(get_session)) -> dict:
    """Öffentlich, aber ohne einen einzigen Namen: nur das, was der
    Anmeldescreen braucht, um die richtigen Zeilen zu zeigen.
    `erstanmeldung_offen` ist nur auf einer frischen Instanz wahr — die per
    Migration angelegte Bestandsfamilie hat dort noch kein Passwort."""
    offen = session.exec(select(Familie).where(
        Familie.passwort_hash.is_(None))).first() is not None      # noqa: E711
    return {"erstanmeldung_offen": offen,
            "einladung_noetig": einladungscode_noetig()}


@router.post("/registrieren", status_code=201)
def registrieren(daten: RegistrierenIn, response: Response,
                 session: Session = Depends(get_session)) -> dict:
    if not einladungscode_stimmt(daten.einladungs_code):
        raise HTTPException(403, "Der Einladungscode stimmt nicht")
    name = daten.name.strip()
    if not name:
        raise HTTPException(400, "Bitte einen Namen eingeben")
    if len(daten.passwort) < MIN_PASSWORT:
        raise HTTPException(400, f"Das Passwort braucht mindestens {MIN_PASSWORT} Zeichen")
    if _nach_name(session, name):
        raise HTTPException(409, "Diesen Namen gibt es schon")
    hash_, salz = passwort_hashen(daten.passwort)
    familie = Familie(name=name, logo_pfad=daten.logo_pfad,
                      passwort_hash=hash_, passwort_salz=salz)
    session.add(familie)
    session.commit()
    session.refresh(familie)
    _sitzung_setzen(response, familie.id, session)
    return _familie_oeffentlich(familie)


@router.post("/passwort-festlegen")
def passwort_festlegen(daten: PasswortFestlegenIn, response: Response,
                       session: Session = Depends(get_session)) -> dict:
    """Der einmalige Erstanmeldungs-Flow für eine per Migration angelegte
    Familie (`passwort_hash IS NULL`) — die Migration selbst darf kein
    Passwort erfinden. Ist schon eines gesetzt, geht es nur über `/login`."""
    familie = _familie_finden(session, daten.familie_id, daten.name)
    if not familie:
        raise HTTPException(404, "Familie nicht gefunden")
    if familie.passwort_hash is not None:
        raise HTTPException(409, "Für diese Familie ist schon ein Passwort gesetzt")
    if len(daten.passwort) < MIN_PASSWORT:
        raise HTTPException(400, f"Das Passwort braucht mindestens {MIN_PASSWORT} Zeichen")
    familie.passwort_hash, familie.passwort_salz = passwort_hashen(daten.passwort)
    session.add(familie)
    session.commit()
    _sitzung_setzen(response, familie.id, session)
    return _familie_oeffentlich(familie)


@router.post("/login")
def login(daten: LoginIn, response: Response,
         session: Session = Depends(get_session)) -> dict:
    familie = _familie_finden(session, daten.familie_id, daten.name)
    if not familie:
        raise HTTPException(401, "Familie oder Passwort falsch")
    if familie.gesperrt_bis and familie.gesperrt_bis > datetime.utcnow():
        raise HTTPException(429, "Zu viele Fehlversuche — kurz warten und erneut versuchen")
    if familie.passwort_hash is None:
        raise HTTPException(409, "Für diese Familie ist noch kein Passwort gesetzt")

    if not passwort_pruefen(daten.passwort, familie.passwort_hash, familie.passwort_salz):
        familie.fehlversuche += 1
        if familie.fehlversuche >= MAX_FEHLVERSUCHE:
            familie.gesperrt_bis = datetime.utcnow() + SPERRDAUER
            familie.fehlversuche = 0
        session.add(familie)
        session.commit()
        raise HTTPException(401, "Familie oder Passwort falsch")

    familie.fehlversuche = 0
    familie.gesperrt_bis = None
    session.add(familie)
    session.commit()

    # N472 — mit aktivem zweiten Faktor entsteht HIER noch KEINE Sitzung:
    # `deps.aktuelle_familie` (der Prüfpunkt für jeden geschützten Endpunkt)
    # bleibt dadurch komplett unangetastet, ein unbestätigtes Ticket kann
    # nirgends etwas freischalten.
    if familie.totp_bestaetigt:
        ticket, ticket_hash, laeuft_ab = neues_zweifaktorticket()
        session.add(ZweiFaktorTicket(familie_id=familie.id, ticket_hash=ticket_hash,
                                     laeuft_ab=laeuft_ab))
        session.commit()
        response.status_code = 202
        return {"zwei_faktor_noetig": True, "ticket": ticket}

    _sitzung_setzen(response, familie.id, session)
    return _familie_oeffentlich(familie)


class LoginZweiFaktorIn(BaseModel):
    ticket: str
    code: str


@router.post("/login/2fa")
def login_zweifaktor(daten: LoginZweiFaktorIn, response: Response,
                     session: Session = Depends(get_session)) -> dict:
    """N472 — der zweite Schritt, nachdem `/login` mit `zwei_faktor_noetig`
    geantwortet hat. Dieselbe generische Fehlermeldung wie bei einem falschen
    Passwort — ob das Ticket abgelaufen war oder der Code falsch ist, bleibt
    für den Aufrufer ununterscheidbar. `code` wird zuerst als TOTP-Code
    geprüft, sonst gegen die Wiederherstellungscodes — ein Feld für beides,
    kein Umschalter in der Oberfläche nötig."""
    ticket = session.exec(select(ZweiFaktorTicket).where(
        ZweiFaktorTicket.ticket_hash == token_hashen(daten.ticket))).first()
    if not ticket or ticket.laeuft_ab < datetime.utcnow():
        raise HTTPException(401, "Anmeldung abgelaufen — bitte erneut versuchen")

    familie = session.get(Familie, ticket.familie_id)
    if not familie or not familie.totp_bestaetigt:
        raise HTTPException(401, "Anmeldung abgelaufen — bitte erneut versuchen")
    if familie.gesperrt_bis and familie.gesperrt_bis > datetime.utcnow():
        raise HTTPException(429, "Zu viele Fehlversuche — kurz warten und erneut versuchen")

    stimmt = totp.code_pruefen(familie.totp_geheimnis, daten.code)
    wiederherstellung_treffer = None
    if not stimmt and familie.totp_wiederherstellung:
        versucht = totp.code_hashen(daten.code)
        if versucht in familie.totp_wiederherstellung:
            stimmt = True
            wiederherstellung_treffer = versucht

    if not stimmt:
        # Derselbe Zähler wie beim Passwort (siehe oben) — ein falscher
        # zweiter Faktor zählt genauso als Fehlversuch, kein eigener Riegel
        # nötig. Das Ticket bleibt bis zu seinem Ablauf gültig, ein Tippfehler
        # darf noch einmal versucht werden.
        familie.fehlversuche += 1
        if familie.fehlversuche >= MAX_FEHLVERSUCHE:
            familie.gesperrt_bis = datetime.utcnow() + SPERRDAUER
            familie.fehlversuche = 0
        session.add(familie)
        session.commit()
        raise HTTPException(401, "Anmeldung fehlgeschlagen — Code falsch oder abgelaufen")

    if wiederherstellung_treffer:
        # Neue Liste statt In-Place-Entfernen: nur so erkennt SQLAlchemy die
        # Änderung am JSON-Feld zuverlässig als geändert.
        familie.totp_wiederherstellung = [h for h in familie.totp_wiederherstellung
                                          if h != wiederherstellung_treffer]
    familie.fehlversuche = 0
    familie.gesperrt_bis = None
    session.add(familie)
    session.delete(ticket)
    session.commit()
    _sitzung_setzen(response, familie.id, session)
    return _familie_oeffentlich(familie)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response,
          session: Session = Depends(get_session)) -> None:
    """Löscht die Sitzung serverseitig (nicht nur das Cookie im Browser) —
    ein zuvor kopiertes Cookie darf nach dem Abmelden nicht weiter gelten."""
    token = request.cookies.get(SITZUNG_COOKIE)
    if token:
        sitzung = session.exec(
            select(Sitzung).where(Sitzung.token_hash == token_hashen(token))).first()
        if sitzung:
            session.delete(sitzung)
            session.commit()
    response.delete_cookie(SITZUNG_COOKIE)


@router.get("/ich")
def ich(familie: Familie = Depends(aktuelle_familie)) -> dict:
    return _familie_oeffentlich(familie)


class PasswortAendernIn(BaseModel):
    alt: str
    neu: str
    neu_wiederholung: str


@router.post("/passwort-aendern")
def passwort_aendern(daten: PasswortAendernIn, request: Request,
                     response: Response,
                     session: Session = Depends(get_session),
                     familie: Familie = Depends(aktuelle_familie)) -> dict:
    """N442 — das eigene Passwort ändern.

    Drei Prüfungen, in dieser Reihenfolge: das ALTE Passwort muss stimmen
    (sonst könnte jeder an einem offenen Browser das Passwort übernehmen),
    die beiden neuen Eingaben müssen übereinstimmen (Tippfehler beim Setzen
    eines Passworts merkt man sonst erst beim nächsten Anmelden, wenn man
    ausgesperrt ist), und das neue muss lang genug sein.

    Danach werden ALLE bestehenden Sitzungen dieser Familie verworfen und
    eine neue ausgestellt: ein anderswo mitgenommenes Cookie soll nach einer
    Passwortänderung nicht weitergelten — genau dafür ändert man es ja."""
    if familie.passwort_hash is None:
        raise HTTPException(409, "Für diese Familie ist noch kein Passwort "
                                 "gesetzt.")
    if not passwort_pruefen(daten.alt, familie.passwort_hash,
                            familie.passwort_salz):
        raise HTTPException(403, "Das bisherige Passwort stimmt nicht.")
    if daten.neu != daten.neu_wiederholung:
        raise HTTPException(400, "Die beiden neuen Passwörter sind nicht "
                                 "gleich.")
    if len(daten.neu) < MIN_PASSWORT:
        raise HTTPException(400, f"Das Passwort braucht mindestens {MIN_PASSWORT} Zeichen")
    if daten.neu == daten.alt:
        raise HTTPException(400, "Das neue Passwort ist das bisherige.")

    familie.passwort_hash, familie.passwort_salz = passwort_hashen(daten.neu)
    familie.fehlversuche = 0
    familie.gesperrt_bis = None
    session.add(familie)
    for alte in session.exec(select(Sitzung).where(
            Sitzung.familie_id == familie.id)).all():
        session.delete(alte)
    session.commit()

    _sitzung_setzen(response, familie.id, session)
    log.info("Passwort geändert für Familie %s", familie.name)
    return {"geaendert": True}


# ---- N472 — Zwei-Faktor-Authentifizierung verwalten ----
# Jede der folgenden Aktionen ändert den Zwei-Faktor-Zustand und verlangt
# deshalb — wie `passwort_aendern` oben — das aktuelle Passwort erneut: eine
# gekaperte offene Sitzung darf den zweiten Faktor nicht auf eigene Faust
# austauschen oder abschalten.


class ZweiFaktorPasswortIn(BaseModel):
    passwort: str


def _passwort_bestaetigen(familie: Familie, passwort: str) -> None:
    if familie.passwort_hash is None or not passwort_pruefen(
            passwort, familie.passwort_hash, familie.passwort_salz):
        raise HTTPException(403, "Das Passwort stimmt nicht.")


@router.post("/2fa/einrichten")
def zweifaktor_einrichten(daten: ZweiFaktorPasswortIn,
                          session: Session = Depends(get_session),
                          familie: Familie = Depends(aktuelle_familie)) -> dict:
    """Erzeugt ein neues, noch UNBESTÄTIGTES Geheimnis in
    `totp_geheimnis_ausstehend` — ein bereits AKTIVES `totp_geheimnis` bleibt
    unangetastet, bis `/2fa/bestaetigen` einen echten Code daraus vorweist.
    So sperrt ein Scan-Fehler beim Gerätewechsel niemanden aus."""
    _passwort_bestaetigen(familie, daten.passwort)
    geheimnis = totp.geheimnis_neu()
    familie.totp_geheimnis_ausstehend = geheimnis
    session.add(familie)
    session.commit()
    return {"geheimnis": geheimnis,
            "otpauth_url": totp.otpauth_url(geheimnis, familie.name)}


class ZweiFaktorCodeIn(BaseModel):
    code: str


@router.post("/2fa/bestaetigen")
def zweifaktor_bestaetigen(daten: ZweiFaktorCodeIn,
                           session: Session = Depends(get_session),
                           familie: Familie = Depends(aktuelle_familie)) -> dict:
    """Der erste echte Code aus der Authenticator-App macht das ausstehende
    Geheimnis zum aktiven. Die Wiederherstellungscodes werden hier neu
    erzeugt (auch bei einem Gerätewechsel) und nur DIESES eine Mal im
    Klartext zurückgegeben — genau wie bei GitHub/Google."""
    if not familie.totp_geheimnis_ausstehend:
        raise HTTPException(409, "Erst die Einrichtung starten.")
    if not totp.code_pruefen(familie.totp_geheimnis_ausstehend, daten.code):
        raise HTTPException(400, "Der Code stimmt nicht.")
    familie.totp_geheimnis = familie.totp_geheimnis_ausstehend
    familie.totp_geheimnis_ausstehend = None
    familie.totp_bestaetigt = True
    codes = totp.wiederherstellungscodes_neu()
    familie.totp_wiederherstellung = [totp.code_hashen(c) for c in codes]
    session.add(familie)
    session.commit()
    log.info("Zwei-Faktor aktiviert für Familie %s", familie.name)
    return {"aktiviert": True, "wiederherstellungscodes": codes}


@router.post("/2fa/deaktivieren", status_code=204)
def zweifaktor_deaktivieren(daten: ZweiFaktorPasswortIn,
                            session: Session = Depends(get_session),
                            familie: Familie = Depends(aktuelle_familie)) -> None:
    _passwort_bestaetigen(familie, daten.passwort)
    familie.totp_geheimnis = None
    familie.totp_geheimnis_ausstehend = None
    familie.totp_bestaetigt = False
    familie.totp_wiederherstellung = []
    session.add(familie)
    session.commit()
    log.info("Zwei-Faktor deaktiviert für Familie %s", familie.name)


@router.post("/2fa/wiederherstellungscodes-neu")
def zweifaktor_codes_neu(daten: ZweiFaktorPasswortIn,
                         session: Session = Depends(get_session),
                         familie: Familie = Depends(aktuelle_familie)) -> dict:
    """Neue Codes machen die alten ungültig — für den Fall, dass das Blatt
    mit den bisherigen verlegt wurde."""
    _passwort_bestaetigen(familie, daten.passwort)
    if not familie.totp_bestaetigt:
        raise HTTPException(409, "Zwei-Faktor ist nicht aktiv.")
    codes = totp.wiederherstellungscodes_neu()
    familie.totp_wiederherstellung = [totp.code_hashen(c) for c in codes]
    session.add(familie)
    session.commit()
    return {"wiederherstellungscodes": codes}


class LogoIn(BaseModel):
    logo: str        # Data-URL oder blankes Base64


LOGO_MAX_BYTES = 4 * 1024 * 1024


@router.put("/logo")
def logo_setzen(daten: LogoIn, session: Session = Depends(get_session),
                familie: Familie = Depends(aktuelle_familie)) -> dict:
    """N444 — das Familienlogo setzen.

    Es erscheint in den Einstellungen und auf dem Anmeldescreen neben dem
    Familiennamen — `Familie.logo_pfad` und die Anzeige dafür gab es seit
    N436 bereits, nur keinen Weg, eines zu hinterlegen. Das Bild wird
    serverseitig auf ein quadratisches PNG gebracht (mittiger Ausschnitt,
    höchstens 256 px), damit die Kachel nicht verzerrt und die Data-URL die
    Datenbankzeile nicht sprengt."""
    roh_text = (daten.logo or "").strip()
    if "," in roh_text and roh_text.lower().startswith("data:"):
        roh_text = roh_text.split(",", 1)[1]
    try:
        rohdaten = base64.b64decode(roh_text, validate=True)
    except (ValueError, binascii.Error) as fehler:
        raise HTTPException(400, "Die Datei kam beschädigt an.") from fehler
    if not rohdaten:
        raise HTTPException(400, "Es kam keine Datei an.")
    if len(rohdaten) > LOGO_MAX_BYTES:
        raise HTTPException(400, "Das Bild ist zu groß (höchstens 4 MB).")

    from ..pdfbild import BildFehler, als_logo        # noqa: PLC0415
    try:
        fertig = als_logo(rohdaten)
    except BildFehler as fehler:
        raise HTTPException(400, str(fehler)) from fehler

    familie.logo_pfad = ("data:image/png;base64,"
                         + base64.b64encode(fertig).decode("ascii"))
    session.add(familie)
    session.commit()
    log.info("Familienlogo gesetzt für %s (%d Bytes)", familie.name,
             len(fertig))
    return _familie_oeffentlich(familie)


@router.delete("/logo", status_code=204)
def logo_entfernen(session: Session = Depends(get_session),
                   familie: Familie = Depends(aktuelle_familie)) -> None:
    """Zurück zum Standard-Symbol."""
    familie.logo_pfad = None
    session.add(familie)
    session.commit()
