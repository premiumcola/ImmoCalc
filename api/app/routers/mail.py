"""Postfach verbinden und Abrechnungen versenden."""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from ..db import get_session
from ..mailversand import ANBIETER, MailFehler, Zugang
from .cloud import _lies, _schreib

log = logging.getLogger("immocalc")
router = APIRouter(prefix="/api/mail", tags=["mail"])

S_SERVER, S_PORT, S_BENUTZER, S_PASSWORT = (
    "mail_server", "mail_port", "mail_benutzer", "mail_passwort")
S_ABSENDER, S_NAME, S_TLS, S_ANBIETER = (
    "mail_absender", "mail_name", "mail_tls", "mail_anbieter")


class ZugangIn(BaseModel):
    anbieter: str = "gmx"
    server: str = ""
    port: int = 587
    benutzer: str
    passwort: str
    absender: str = ""
    absender_name: str = ""
    tls: str = "starttls"


def zugang(session: Session) -> Zugang:
    passwort = _lies(session, S_PASSWORT)
    server = _lies(session, S_SERVER)
    if not (server and passwort):
        raise HTTPException(400, "Postfach ist noch nicht verbunden")
    return Zugang(
        server=server, port=int(_lies(session, S_PORT) or 587),
        benutzer=_lies(session, S_BENUTZER), passwort=passwort,
        absender=_lies(session, S_ABSENDER), absender_name=_lies(session, S_NAME),
        tls=_lies(session, S_TLS) or "starttls",
    )


@router.get("/anbieter")
def anbieter() -> dict:
    """Serverdaten der gängigen Anbieter für die Auswahl in der Oberfläche."""
    return {"anbieter": [{"id": k, **v} for k, v in ANBIETER.items()]}


@router.get("/status")
def status(session: Session = Depends(get_session)) -> dict:
    passwort = _lies(session, S_PASSWORT)
    return {
        "verbunden": bool(passwort and _lies(session, S_SERVER)),
        "anbieter": _lies(session, S_ANBIETER),
        "server": _lies(session, S_SERVER),
        "port": _lies(session, S_PORT),
        "benutzer": _lies(session, S_BENUTZER),
        "absender": _lies(session, S_ABSENDER),
        "absender_name": _lies(session, S_NAME),
        "passwort": "•••• gespeichert" if passwort else "",
    }


@router.post("/verbindung")
def verbindung(data: ZugangIn, session: Session = Depends(get_session)) -> dict:
    """Meldet sich testweise am Postfach an und speichert erst bei Erfolg."""
    vorlage = ANBIETER.get(data.anbieter, ANBIETER["custom"])
    server = data.server or vorlage["server"]
    if not server:
        raise HTTPException(400, "Kein Mailserver angegeben")

    z = Zugang(server=server, port=data.port or vorlage["port"],
               benutzer=data.benutzer, passwort=data.passwort,
               absender=data.absender or data.benutzer,
               absender_name=data.absender_name,
               tls=data.tls or vorlage["tls"])
    try:
        ergebnis = z.pruefe()
    except MailFehler as e:
        raise HTTPException(400, str(e)) from e

    for schluessel, wert in [
        (S_ANBIETER, data.anbieter), (S_SERVER, z.server), (S_PORT, str(z.port)),
        (S_BENUTZER, z.benutzer), (S_PASSWORT, z.passwort),
        (S_ABSENDER, z.absender), (S_NAME, z.absender_name), (S_TLS, z.tls),
    ]:
        _schreib(session, schluessel, wert)
    session.commit()
    log.info("Postfach verbunden: %s", z.absender)
    return ergebnis


class TestmailIn(BaseModel):
    an: str


@router.post("/test")
def testmail(data: TestmailIn, session: Session = Depends(get_session)) -> dict:
    """Schickt eine Probemail — zeigt dem Nutzer, wie der Absender ankommt."""
    z = zugang(session)
    try:
        z.sende(data.an, "ImmoCalc — Testnachricht",
                "Diese Testnachricht bestätigt, dass ImmoCalc über dein "
                "Postfach versenden kann.\n\nNebenkostenabrechnungen gehen "
                f"künftig von {z.absender} an deine Mieter.\n")
    except MailFehler as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True, "an": data.an}
