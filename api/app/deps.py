"""Gemeinsame FastAPI-Dependencies, von mehreren Routern geteilt.

CCXV: `_objekt(session, slug)` gab es dreifach identisch in stammdaten.py,
besitz.py und objekte.py — hier als eine Dependency statt drei Kopien.

N374: dasselbe für den Zeitraum. „Zeitraum nicht gefunden" stand wörtlich in
neun Modulen, teils fünfmal in derselben Datei — und an drei Stellen fehlte
die Prüfung ganz, sodass der Code mit `None` weiterrechnete. Ein Nachschlagen,
eine Fehlermeldung.
"""
from datetime import datetime

from fastapi import Depends, HTTPException, Request
from sqlmodel import Session, select

from .auth import SITZUNG_COOKIE, token_hashen
from .db import get_session
from .models import Familie, Objekt, Sitzung, Zeitraum


def aktuelle_familie(request: Request,
                     session: Session = Depends(get_session)) -> Familie:
    """N436 — liest das Sitzungs-Cookie, löst es über den (gehashten) Token
    auf eine Familie auf. 401 ohne gültige Sitzung — der Frontend-Gate in
    `immo.js` fängt das ab und leitet auf die Anmeldung um."""
    token = request.cookies.get(SITZUNG_COOKIE)
    if not token:
        raise HTTPException(401, "Nicht angemeldet")
    sitzung = session.exec(
        select(Sitzung).where(Sitzung.token_hash == token_hashen(token))).first()
    if not sitzung or sitzung.laeuft_ab < datetime.utcnow():
        raise HTTPException(401, "Sitzung abgelaufen")
    familie = session.get(Familie, sitzung.familie_id)
    if not familie:
        raise HTTPException(401, "Nicht angemeldet")
    return familie


def objekt_holen(slug: str, session: Session = Depends(get_session),
                 familie: Familie = Depends(aktuelle_familie)) -> Objekt:
    """N436 — jetzt IMMER zusätzlich auf die angemeldete Familie eingegrenzt.
    Das behebt die Mandantentrennung für jeden Router, der diese Dependency
    schon nutzt, in einem einzigen Edit — und macht zugleich einen fremden
    Slug ununterscheidbar von einem nicht existierenden (404 in beiden
    Fällen), statt einer Familie zu verraten, dass ein Slug bei einer ANDEREN
    Familie existiert."""
    o = session.exec(select(Objekt).where(
        Objekt.slug == slug, Objekt.familie_id == familie.id)).first()
    if not o:
        raise HTTPException(404, "Objekt nicht gefunden")
    return o


def _gehoert_zur_familie(session: Session, objekt_id: int | None,
                         familie: Familie) -> bool:
    if objekt_id is None:
        return False
    objekt = session.get(Objekt, objekt_id)
    return bool(objekt and objekt.familie_id == familie.id)


def pruefe_familienbesitz(session: Session, zeile, familie: Familie,
                          objekt_id: int | None = None) -> None:
    """N436 — die generische Besitzprüfung für Endpunkte, die eine Zeile per
    roher numerischer ID holen (`session.get(Modell, id)`), ohne über
    `objekt_holen`/den Slug zu laufen. `zeile` muss ein `objekt_id`-Feld
    tragen (direkt oder per `objekt_id=` übergeben, z. B. wenn erst über
    einen Zwischenschritt wie Zeitraum/Kredit/Miete aufgelöst werden muss).
    404 statt 403 — ein fremder Datensatz soll sich nicht von einem nicht
    existierenden unterscheiden lassen."""
    oid = objekt_id if objekt_id is not None else getattr(zeile, "objekt_id", None)
    if not _gehoert_zur_familie(session, oid, familie):
        raise HTTPException(404, "Nicht gefunden")


def zeitraum_holen(zid: int, session: Session = Depends(get_session),
                   familie: Familie = Depends(aktuelle_familie)) -> Zeitraum:
    """Der Zeitraum zu einer id — oder 404, auch wenn er einer anderen
    Familie gehört (N436).

    Als Dependency verwendbar (`z: Zeitraum = Depends(zeitraum_holen)` — dann
    lösen sich `zid`, `session` UND `familie` automatisch aus dem
    Anfrage-Kontext auf, auch wenn nur `zid` im Pfad steht) und ebenso als
    schlichter Aufruf `zeitraum_holen(zid, session, familie)`, weil viele
    Stellen ihn mitten in einer Funktion brauchen."""
    z = session.get(Zeitraum, zid)
    if not z or not _gehoert_zur_familie(session, z.objekt_id, familie):
        raise HTTPException(404, "Zeitraum nicht gefunden")
    return z


def objekt_zum_zeitraum(z: Zeitraum, session: Session) -> Objekt:
    """Das Objekt eines Zeitraums — mit Prüfung.

    N374 — mehrere Stellen machten `session.get(Objekt, z.objekt_id)` und
    griffen sofort auf `o.name` zu. Über den regulären Löschweg ist das nicht
    erreichbar (die Zeiträume gehen mit), aber eine fehlende Absicherung bleibt
    eine: ein verwaister Zeitraum ergäbe einen 500er ohne erkennbare Ursache.
    Keine eigene familie-Prüfung hier: wer schon einen geprüften `Zeitraum`
    (über `zeitraum_holen`) hat, hat die Zugehörigkeit bereits nachgewiesen."""
    o = session.get(Objekt, z.objekt_id)
    if not o:
        raise HTTPException(404, "Objekt zu diesem Zeitraum nicht gefunden")
    return o
