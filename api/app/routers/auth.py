"""N436 — Familien-Anmeldung. `GET /familien` ist die einzige Route hier, die
absichtlich OHNE Anmeldung erreichbar ist (die Auswahlliste auf dem
Anmeldescreen selbst) — nie den Passwort-Hash ausliefern.

Reihenfolge egal (kein zweisegmentiger Fänger hier wie bei stammdaten.py),
aber registriert VOR `stammdaten` wie jeder andere Router auch (main.py)."""
from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlmodel import Session, select

from ..auth import (MAX_FEHLVERSUCHE, SITZUNG_COOKIE, SPERRDAUER,
                    cookie_sicher, neuer_sitzungstoken, passwort_hashen,
                    passwort_pruefen, token_hashen)
from ..db import get_session
from ..deps import aktuelle_familie
from ..models import Familie, Sitzung

log = logging.getLogger("immocalc")
router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegistrierenIn(BaseModel):
    name: str
    passwort: str
    logo_pfad: str | None = None


class PasswortFestlegenIn(BaseModel):
    familie_id: int
    passwort: str


class LoginIn(BaseModel):
    familie_id: int
    passwort: str


def _familie_oeffentlich(f: Familie) -> dict:
    return {"id": f.id, "name": f.name, "logo_pfad": f.logo_pfad,
            "hat_passwort": f.passwort_hash is not None}


def _sitzung_setzen(response: Response, familie_id: int, session: Session) -> None:
    token, token_hash, laeuft_ab = neuer_sitzungstoken()
    session.add(Sitzung(familie_id=familie_id, token_hash=token_hash,
                        laeuft_ab=laeuft_ab))
    session.commit()
    response.set_cookie(SITZUNG_COOKIE, token, httponly=True, samesite="lax",
                        secure=cookie_sicher(),
                        max_age=int((laeuft_ab - datetime.utcnow())
                                    .total_seconds()))


@router.get("/familien")
def familien_liste(session: Session = Depends(get_session)) -> list[dict]:
    """Öffentlich — die Auswahlliste auf dem Anmeldescreen. Nie den Hash."""
    return [_familie_oeffentlich(f)
           for f in session.exec(select(Familie).order_by(Familie.name)).all()]


@router.post("/registrieren", status_code=201)
def registrieren(daten: RegistrierenIn, response: Response,
                 session: Session = Depends(get_session)) -> dict:
    name = daten.name.strip()
    if not name:
        raise HTTPException(400, "Bitte einen Namen eingeben")
    if len(daten.passwort) < 8:
        raise HTTPException(400, "Das Passwort braucht mindestens 8 Zeichen")
    if session.exec(select(Familie).where(Familie.name == name)).first():
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
    familie = session.get(Familie, daten.familie_id)
    if not familie:
        raise HTTPException(404, "Familie nicht gefunden")
    if familie.passwort_hash is not None:
        raise HTTPException(409, "Für diese Familie ist schon ein Passwort gesetzt")
    if len(daten.passwort) < 8:
        raise HTTPException(400, "Das Passwort braucht mindestens 8 Zeichen")
    familie.passwort_hash, familie.passwort_salz = passwort_hashen(daten.passwort)
    session.add(familie)
    session.commit()
    _sitzung_setzen(response, familie.id, session)
    return _familie_oeffentlich(familie)


@router.post("/login")
def login(daten: LoginIn, response: Response,
         session: Session = Depends(get_session)) -> dict:
    familie = session.get(Familie, daten.familie_id)
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
    if len(daten.neu) < 8:
        raise HTTPException(400, "Das Passwort braucht mindestens 8 Zeichen")
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
