"""Abrechnung abschließen: je Partei ein Ergebnis erzeugen und versenden."""
import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlmodel import Session, select

from ..abrechnung_pdf import abrechnung_pdf, pdf_dateiname
from ..db import get_session
from ..engine import Position, abrechnung
from ..mailversand import MailFehler
from ..models import (Bewohner, Kostenposition, Miete, Objekt,
                      Versandprotokoll, Vorauszahlung, Zeitraum)
from ..verteilung import fehlende_angaben, leerstaende, stammdaten
from .mail import zugang

log = logging.getLogger("immocalc")
router = APIRouter(prefix="/api/zeitraeume", tags=["versand"])


def _ergebnis(session: Session, z: Zeitraum) -> dict:
    pos = session.exec(
        select(Kostenposition).where(Kostenposition.zeitraum_id == z.id)).all()
    vzs = session.exec(
        select(Vorauszahlung).where(Vorauszahlung.zeitraum_id == z.id)).all()
    positionen = [Position(p.kostenart, p.betrag, p.schluessel, p.anteile or {}, p.s35)
                  for p in pos if p.status == "erledigt"]
    res = abrechnung(positionen, {v.partei: v.betrag for v in vzs})
    # `abrechnung` selbst kennt keine offenen Posten — ohne diese Ergänzung
    # las der Abschluss `res["offen"]` und bekam immer eine leere Liste.
    res.update(fehlende_angaben(list(pos)))
    return res


def _empfaenger(session: Session, objekt_id: int) -> dict[str, dict]:
    """Aktuelle Mietverhältnisse je Partei — dort hängen die Kontaktdaten.

    Neben dem Hauptkontakt am Mietverhältnis zählen die Bewohner mit eigener
    Adresse: wohnen zwei Personen in der Wohnung und haben beide eine
    Mailadresse hinterlegt, bekommen auch beide die Abrechnung. `adressen`
    enthält jede Adresse genau einmal, Hauptkontakt zuerst.
    """
    mieten = session.exec(select(Miete).where(Miete.objekt_id == objekt_id)).all()
    laufend = [m for m in mieten if m.bis_datum is None]
    ids = [m.id for m in laufend if m.id is not None]
    bewohner: dict[int, list[Bewohner]] = {i: [] for i in ids}
    if ids:
        for b in session.exec(
                select(Bewohner).where(Bewohner.miete_id.in_(ids))).all():
            bewohner.setdefault(b.miete_id, []).append(b)

    treffer = {}
    for m in laufend:
        if not m.partei:
            continue
        adressen: list[str] = []
        for adresse in [m.email] + [b.email for b in bewohner.get(m.id, [])
                                    if b.abrechnung]:
            adresse = (adresse or "").strip()
            if adresse and adresse not in adressen:
                adressen.append(adresse)
        treffer[m.partei] = {"email": adressen[0] if adressen else "",
                             "adressen": adressen,
                             "einheit": m.einheit, "telefon": m.telefon}
    return treffer


@router.get("/{zid}/versand")
def uebersicht(zid: int, session: Session = Depends(get_session)) -> dict:
    """Wer bekommt was — und wem fehlt die Mailadresse?"""
    z = session.get(Zeitraum, zid)
    if not z:
        raise HTTPException(404, "Zeitraum nicht gefunden")
    res = _ergebnis(session, z)
    kontakte = _empfaenger(session, z.objekt_id)

    # Leerstand ist kein Empfänger, sondern der Anteil, den der Eigentümer
    # selbst trägt. Ohne diese Unterscheidung stand er unter „ohne
    # Mailadresse" und las sich wie ein vergessener Mieter.
    leer = set(leerstaende(stammdaten(session, z)))

    zeilen = []
    for partei, werte in (res.get("parteien") or {}).items():
        kontakt = kontakte.get(partei, {})
        ist_leerstand = partei in leer
        zeilen.append({
            "partei": partei,
            "einheit": kontakt.get("einheit", ""),
            "email": kontakt.get("email", ""),
            "adressen": kontakt.get("adressen", []),
            "kosten": werte.get("kosten"),
            "vz": werte.get("vorauszahlungen"),
            "saldo": werte.get("saldo"),
            "leerstand": ist_leerstand,
            "versandbereit": bool(kontakt.get("email")) and not ist_leerstand,
        })
    zeilen.sort(key=lambda r: r["partei"])
    return {
        "zeitraum": f"{z.start:%d.%m.%Y} – {z.ende:%d.%m.%Y}",
        "status": z.status,
        "offen": res.get("offen", []),
        "parteien": zeilen,
        "ohne_mail": [r["partei"] for r in zeilen
                      if not r["versandbereit"] and not r["leerstand"]],
        "leerstand": [r["partei"] for r in zeilen if r["leerstand"]],
    }


def _einzelposten(res: dict, partei: str) -> list[dict]:
    """Anteil dieser Partei je Kostenart — der Nachweis in der Anlage."""
    zeilen = []
    for eintrag in res.get("positionen") or []:
        betrag = (eintrag.get("verteilung") or {}).get(partei)
        if betrag:
            zeilen.append({"kostenart": eintrag.get("kostenart"),
                           "betrag": round(betrag, 2)})
    zeilen.sort(key=lambda p: -p["betrag"])
    return zeilen


@router.get("/{zid}/abrechnung.pdf")
def abrechnung_als_pdf(zid: int, partei: str,
                       session: Session = Depends(get_session)) -> Response:
    """Die Abrechnung einer Partei als PDF — zum Ansehen vor dem Versand."""
    z = session.get(Zeitraum, zid)
    if not z:
        raise HTTPException(404, "Zeitraum nicht gefunden")
    o = session.get(Objekt, z.objekt_id)
    res = _ergebnis(session, z)
    werte = (res.get("parteien") or {}).get(partei)
    if werte is None:
        raise HTTPException(404, f"Keine Abrechnung für '{partei}'")
    zeitraum_text = f"{z.start:%d.%m.%Y} – {z.ende:%d.%m.%Y}"
    inhalt = abrechnung_pdf(o.name, zeitraum_text, partei, werte,
                            _einzelposten(res, partei))
    return Response(content=inhalt, media_type="application/pdf", headers={
        "Content-Disposition":
            f'inline; filename="{pdf_dateiname(o.name, zeitraum_text, partei)}"'})


class AbschlussIn(BaseModel):
    versenden: bool = False
    offene_uebergehen: bool = False
    pdf_anhaengen: bool = True
    # Ausdrücklich nötig, um einen bereits abgeschlossenen Zeitraum erneut
    # anzufassen — sonst genügt ein zweiter Tab für einen zweiten Versand.
    erneut: bool = False


def _bereits_versendet(session: Session, zid: int) -> set[str]:
    return {p.partei for p in session.exec(
        select(Versandprotokoll).where(Versandprotokoll.zeitraum_id == zid)).all()
        if p.versendet_am}


@router.post("/{zid}/abschliessen")
def abschliessen(zid: int, data: AbschlussIn,
                 session: Session = Depends(get_session)) -> dict:
    """Schließt den Zeitraum ab und verschickt die Abrechnungen.

    Offene Positionen blockieren, solange sie nicht ausdrücklich übergangen
    werden — sonst ginge eine unvollständige Abrechnung an die Mieter."""
    z = session.get(Zeitraum, zid)
    if not z:
        raise HTTPException(404, "Zeitraum nicht gefunden")
    if z.status != "in Arbeit" and not data.erneut:
        raise HTTPException(409, "Dieser Zeitraum ist bereits abgeschlossen. "
                                 "Ein erneuter Versand muss ausdrücklich "
                                 "angefordert werden.")
    o = session.get(Objekt, z.objekt_id)

    res = _ergebnis(session, z)
    offen = res.get("offen", [])
    if offen and not data.offene_uebergehen:
        raise HTTPException(400, "Noch offene Positionen: " + ", ".join(offen))

    kontakte = _empfaenger(session, z.objekt_id)
    leer = set(leerstaende(stammdaten(session, z)))
    zeitraum_text = f"{z.start:%d.%m.%Y} – {z.ende:%d.%m.%Y}"
    versendet, uebersprungen, schon_da = [], [], []

    if data.versenden:
        z_mail = zugang(session)          # wirft, wenn kein Postfach verbunden
        fertig = _bereits_versendet(session, zid)
        for partei, werte in (res.get("parteien") or {}).items():
            # Ein zweiter Anlauf nach einem Fehler in der Mitte darf nicht bei
            # Partei eins wieder anfangen.
            if partei in fertig:
                schon_da.append(partei)
                continue
            # Alle Bewohner mit eigener Adresse bekommen die Abrechnung, nicht
            # nur wer den Vertrag unterschrieben hat. Der Leerstand bekommt
            # nichts — hinter ihm steht keine Partei, sondern der Eigentümer.
            adressen = [a for a in kontakte.get(partei, {}).get("adressen", [])
                        if partei not in leer]
            if not adressen:
                uebersprungen.append(partei)
                continue
            saldo = werte.get("saldo") or 0
            richtung = ("Guthaben zu Ihren Gunsten" if saldo >= 0
                        else "Nachzahlung")
            text = (
                f"Guten Tag {partei},\n\n"
                f"anbei die Betriebskostenabrechnung für {o.name}, "
                f"Zeitraum {zeitraum_text}.\n\n"
                f"Umlagefähige Kosten: {werte.get('kosten'):.2f} EUR\n"
                f"Geleistete Vorauszahlungen: {werte.get('vorauszahlungen'):.2f} EUR\n"
                f"{richtung}: {abs(saldo):.2f} EUR\n\n"
                f"Bei Rückfragen melden Sie sich gerne.\n\n"
                f"Freundliche Grüße\n"
            )
            anhang = None
            if data.pdf_anhaengen:
                inhalt = abrechnung_pdf(o.name, zeitraum_text, partei, werte,
                                        _einzelposten(res, partei),
                                        absender=z_mail.absender_name)
                anhang = (pdf_dateiname(o.name, zeitraum_text, partei),
                          inhalt, "pdf")
            for adresse in adressen:
                try:
                    z_mail.sende(adresse,
                                 f"Betriebskostenabrechnung {o.name} · {zeitraum_text}",
                                 text, anhang=anhang)
                except MailFehler as e:
                    # Sofort festhalten, was bis hierher rausging — sonst steht
                    # beim naechsten Versuch niemand in der Liste.
                    session.commit()
                    raise HTTPException(
                        400, f"Versand an {partei} ({adresse}) fehlgeschlagen: "
                             f"{e}. Bereits verschickt: "
                             f"{', '.join(versendet) or 'niemand'}.") from e
                # Je Adresse eine Zeile: erst wenn alle Bewohner einer Partei
                # ihre Mail haben, gilt die Partei als versorgt.
                session.add(Versandprotokoll(
                    zeitraum_id=zid, partei=partei, empfaenger=adresse,
                    versendet_am=date.today()))
                session.commit()
            versendet.append(partei)

    z.status = "abgeschlossen"
    session.add(z)
    session.commit()
    log.info("Zeitraum %s abgeschlossen, %d Mail(s) versendet", zid, len(versendet))
    return {"ok": True, "status": z.status, "versendet": versendet,
            "ohne_mail": uebersprungen, "schon_versendet": schon_da,
            "uebergangen": offen if data.offene_uebergehen else []}


@router.post("/{zid}/oeffnen")
def oeffnen(zid: int, session: Session = Depends(get_session)) -> dict:
    """Öffnet einen abgeschlossenen Zeitraum wieder.

    Ein Abschluss passiert schnell — ein Beleg kommt nach, ein Betrag war
    falsch, eine Position hatte keine Verteilung. Ohne diesen Weg bliebe der
    Zeitraum für immer zu und verschwände zugleich aus Fristen, offenen
    Belegen und Erinnerungen: der Fehler wäre danach nicht mehr sichtbar.

    Das Versandprotokoll bleibt dabei ausdrücklich stehen. Es ist kein
    Zustand des Zeitraums, sondern die Erinnerung daran, wer seine Abrechnung
    schon in Händen hält. Würde es beim Öffnen gelöscht, bekäme beim nächsten
    Abschluss jeder Mieter die Mail ein zweites Mal — auch die, bei denen sich
    gar nichts geändert hat. Wer nach einer Korrektur bewusst erneut
    verschicken will, tut das gezielt über den Abschluss mit `erneut`."""
    z = session.get(Zeitraum, zid)
    if not z:
        raise HTTPException(404, "Zeitraum nicht gefunden")
    if z.status == "in Arbeit":
        return {"ok": True, "status": z.status, "geaendert": False,
                "bereits_versendet": sorted(_bereits_versendet(session, zid))}
    z.status = "in Arbeit"
    session.add(z)
    session.commit()
    versendet = sorted(_bereits_versendet(session, zid))
    log.info("Zeitraum %s wieder geöffnet (%d Partei(en) bereits beliefert)",
             zid, len(versendet))
    return {"ok": True, "status": z.status, "geaendert": True,
            "bereits_versendet": versendet}
