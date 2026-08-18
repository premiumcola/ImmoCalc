"""Abrechnung abschließen: je Partei ein Ergebnis erzeugen und versenden."""
import logging
from contextlib import ExitStack
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlmodel import Session, select

from ..abrechnung_pdf import abrechnung_pdf, pdf_dateiname
from ..cloudkern import _lies
from ..db import get_session
from ..engine import abrechnung
from ..heizkosten import nachweis_fuer_einheit
from ..mailversand import MailFehler, versandlauf
from ..models import (Anteil, Bewohner, Eigentuemer, Miete, Objekt,
                      Versandprotokoll, Zeitraum)
from ..verteilung import (SCHLUESSEL, _laufend, fehlende_angaben, leerstaende,
                         positionen_fuer_abrechnung, stammdaten,
                         unbekannte_anteile, unbekannte_vorauszahlungen)
from .mail import S_NAME, zugang

log = logging.getLogger("immocalc")
router = APIRouter(prefix="/api/zeitraeume", tags=["versand"])


def _ergebnis(session: Session, z: Zeitraum) -> dict:
    # N274 — lief bis hierhin komplett am Vorschau-Endpunkt vorbei: kein
    # N125-Filter, kein CCCLIX-Vorab-Split, und vor allem keine CCCLXIV-
    # Vorauszahlung-aus-der-Miete. Eine Partei ohne eigenen `Vorauszahlung`-
    # Datensatz bekam beim ECHTEN Versand 0,00 € Vorauszahlung angerechnet,
    # während dieselbe Partei in der Vorschau (`GET .../abrechnung`) den
    # korrekten, aus der Miete abgeleiteten Betrag sah — live an Laufer
    # Str. 5 gefunden (alle fünf Parteien betroffen). Jetzt dieselbe Stelle
    # wie die Vorschau: `verteilung.positionen_fuer_abrechnung`.
    positionen, vorausz, umlegbar, vzs, optionale = positionen_fuer_abrechnung(session, z)
    res = abrechnung(positionen, vorausz)
    # `abrechnung` selbst kennt keine offenen Posten — ohne diese Ergänzung
    # las der Abschluss `res["offen"]` und bekam immer eine leere Liste.
    res.update(fehlende_angaben(list(umlegbar), optionale))
    # N314(g) — eine Vorauszahlung ohne passende Partei fliesst in
    # `gesamt.abschlaege` ein, ohne in einer Partei-Zeile aufzutauchen.
    res["vorauszahlungen_ohne_partei"] = unbekannte_vorauszahlungen(session, z, vzs)
    # N402 — das Gegenstück: ein Anteil, dessen Partei es im Zeitraum nicht
    # gibt, verteilt echtes Geld an einen Empfänger, den keine Abrechnung je
    # erreicht (live gefunden: Müll 85,45 € auf „Wohnug 1.OG" statt auf
    # „Alicia & Roman").
    res["anteile_ohne_partei"] = unbekannte_anteile(session, z)
    return res


def _empfaenger(session: Session, objekt_id: int,
                start: date, ende: date) -> dict[str, dict]:
    """Mietverhältnisse, die den Zeitraum berühren, je Partei — dort hängen die
    Kontaktdaten.

    Maßgeblich ist dieselbe Menge wie in der Verteilung (`verteilung._laufend`):
    auch ein Mieter, der mitten im Jahr ausgezogen ist, steht mit seinem Anteil
    in der Abrechnung und muss sie bekommen. Zählte man hier nur die laufenden
    (`bis_datum is None`), verlöre der ausgezogene Mieter seine Abrechnung samt
    Nachzahlungsforderung, obwohl seine Adresse gespeichert ist.

    Neben dem Hauptkontakt am Mietverhältnis zählen die Bewohner mit eigener
    Adresse: wohnen zwei Personen in der Wohnung und haben beide eine
    Mailadresse hinterlegt, bekommen auch beide die Abrechnung. `adressen`
    enthält jede Adresse genau einmal, Hauptkontakt zuerst.
    """
    mieten = session.exec(select(Miete).where(Miete.objekt_id == objekt_id)).all()
    laufend = _laufend(mieten, start, ende)
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
    kontakte = _empfaenger(session, z.objekt_id, z.start, z.ende)

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
        # N314(g) — `_ergebnis` berechnet das schon; ohne diese Zeile blieb es
        # im Endpunkt stecken und das Frontend musste `/abrechnung` extra holen.
        "vorauszahlungen_ohne_partei": res.get("vorauszahlungen_ohne_partei", []),
    }


def _objekt_adresse(o: Objekt) -> str:
    """Postanschrift für den Kopf der Abrechnung — die Straße, wenn gepflegt,
    sonst der freie Objektname (der auch nur ein Kürzel sein kann, z. B.
    'TAU5'). Onepager (N274) will hier eine echte Anschrift sehen."""
    if o.strasse:
        ort = " ".join(x for x in [o.plz, o.ort] if x)
        return ", ".join(x for x in [o.strasse, ort] if x)
    return o.name


def _absender_name(session: Session, objekt_id: int) -> str:
    """Der Name unten auf der Abrechnung — bevorzugt der im Mailversand
    hinterlegte Absendername, sonst der Eigentümer mit dem größten Anteil.

    Die Vorschau (`abrechnung_als_pdf`) läuft auch ohne verbundenes Postfach;
    ohne diesen Rückfall bliebe die Unterschriftszeile dort leer, obwohl der
    Eigentümer längst gepflegt ist."""
    name = _lies(session, S_NAME)
    if name:
        return name
    anteile = session.exec(
        select(Anteil).where(Anteil.objekt_id == objekt_id)).all()
    if not anteile:
        return ""
    haupt = max(anteile, key=lambda a: a.promille
               if a.promille is not None else a.tausendstel)
    eigentuemer = session.get(Eigentuemer, haupt.eigentuemer_id)
    return eigentuemer.name if eigentuemer else ""


def _einzelposten(res: dict, partei: str) -> list[dict]:
    """Anteil dieser Partei je Kostenart — der Nachweis in der Anlage.

    N419 — trägt jetzt zusätzlich den Verteilerschlüssel (Klartext) und die
    Gesamtkosten der Kostenart, für die Verteilerschlüssel-Tabelle auf Seite 1
    der Abrechnungs-PDF."""
    zeilen = []
    for eintrag in res.get("positionen") or []:
        betrag = (eintrag.get("verteilung") or {}).get(partei)
        if betrag:
            zeilen.append({
                "kostenart": eintrag.get("kostenart"),
                "betrag": round(betrag, 2),
                "gesamtkosten": eintrag.get("kosten"),
                "schluessel": SCHLUESSEL.get(eintrag.get("schluessel"), {})
                                        .get("titel", ""),
            })
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
    kontakt = _empfaenger(session, z.objekt_id, z.start, z.ende).get(partei, {})
    einheit = kontakt.get("einheit", "")
    inhalt = abrechnung_pdf(o.name, zeitraum_text, partei, werte,
                            _einzelposten(res, partei),
                            absender=_absender_name(session, o.id),
                            anschrift=_objekt_adresse(o),
                            einheit=einheit,
                            heiznachweis=nachweis_fuer_einheit(
                                session, z, einheit, partei, res.get("positionen")))
    return Response(content=inhalt, media_type="application/pdf", headers={
        "Content-Disposition":
            f'inline; filename="{pdf_dateiname(o.name, zeitraum_text, partei)}"'})


class AbschlussIn(BaseModel):
    versenden: bool = False
    offene_uebergehen: bool = False
    pdf_anhaengen: bool = True
    # Manche Adressen gibt es schlicht nicht — ein Mieter ist ohne neue
    # Anschrift ausgezogen. Dann darf der Zeitraum trotzdem zu, aber weil der
    # Nutzer es ausdrücklich sagt, nicht weil der Versand stillschweigend
    # nichts getan hat.
    ohne_adresse_abschliessen: bool = False
    # Ausdrücklich nötig, um einen bereits abgeschlossenen Zeitraum erneut
    # anzufassen — sonst genügt ein zweiter Tab für einen zweiten Versand.
    erneut: bool = False


def _versendete_adressen(session: Session, zid: int) -> set[tuple[str, str]]:
    """Welche (Partei, Empfänger)-Paare schon eine Mail bekommen haben.

    Adressgenau, nicht nur je Partei: hat ein Ehepaar zwei Adressen und schlug
    die zweite Mail beim ersten Anlauf fehl, muss der zweite Anlauf genau diese
    eine Adresse nachliefern — nicht die Partei als Ganzes überspringen und die
    zweite Person nie erreichen."""
    return {(p.partei, p.empfaenger) for p in session.exec(
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

    kontakte = _empfaenger(session, z.objekt_id, z.start, z.ende)
    leer = set(leerstaende(stammdaten(session, z)))
    zeitraum_text = f"{z.start:%d.%m.%Y} – {z.ende:%d.%m.%Y}"
    versendet, uebersprungen, schon_da = [], [], []

    if data.versenden:
        z_mail = zugang(session)          # wirft, wenn kein Postfach verbunden
        # Ein ausdrücklicher Neuversand nach einer Korrektur (`erneut`) soll
        # wirklich alle wieder erreichen — dann zählt das alte Protokoll nicht
        # mehr. Ohne `erneut` bleibt es stehen und schützt vor Doppelversand.
        if data.erneut:
            for p in session.exec(select(Versandprotokoll).where(
                    Versandprotokoll.zeitraum_id == zid)).all():
                session.delete(p)
            session.commit()
        fertig = _versendete_adressen(session, zid)
        # Eine Verbindung für den ganzen Lauf: je Empfänger eine eigene
        # Anmeldung liess GMX/Web.de nach kurzer Zeit drosseln, und der Versand
        # kippte mitten im Haus.
        with ExitStack() as stapel:
            try:
                sende = stapel.enter_context(versandlauf(z_mail))
            except MailFehler as e:
                # Kommt die Verbindung gar nicht erst zustande, ist noch nichts
                # rausgegangen — das gehört in die Meldung, sonst rät der Nutzer.
                raise HTTPException(
                    400, f"Postfach nicht erreichbar: {e} Es wurde noch nichts "
                         f"versendet.") from e
            for partei, werte in (res.get("parteien") or {}).items():
                # Alle Bewohner mit eigener Adresse bekommen die Abrechnung,
                # nicht nur wer den Vertrag unterschrieben hat. Der Leerstand
                # bekommt nichts — hinter ihm steht keine Partei, sondern der
                # Eigentümer.
                adressen = [a for a in kontakte.get(partei, {}).get("adressen", [])
                            if partei not in leer]
                if not adressen:
                    uebersprungen.append(partei)
                    continue
                # Adressgenau: nur die noch nicht belieferten Adressen dieser
                # Partei. Ein zweiter Anlauf nach einem Fehler in der Mitte
                # fängt so genau dort an, wo er abbrach, statt eine Partei ganz
                # zu überspringen.
                adressen = [a for a in adressen if (partei, a) not in fertig]
                if not adressen:
                    schon_da.append(partei)
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
                    einheit = kontakte.get(partei, {}).get("einheit", "")
                    inhalt = abrechnung_pdf(o.name, zeitraum_text, partei, werte,
                                            _einzelposten(res, partei),
                                            absender=z_mail.absender_name,
                                            anschrift=_objekt_adresse(o),
                                            einheit=einheit,
                                            heiznachweis=nachweis_fuer_einheit(
                                                session, z, einheit, partei,
                                                res.get("positionen")))
                    anhang = (pdf_dateiname(o.name, zeitraum_text, partei),
                              inhalt, "pdf")
                for adresse in adressen:
                    try:
                        sende(adresse,
                              f"Betriebskostenabrechnung {o.name} · {zeitraum_text}",
                              text, anhang=anhang)
                    except MailFehler as e:
                        # Sofort festhalten, was bis hierher rausging — sonst
                        # steht beim naechsten Versuch niemand in der Liste.
                        session.commit()
                        raise HTTPException(
                            400, f"Versand an {partei} ({adresse}) "
                                 f"fehlgeschlagen: {e}. Bereits verschickt: "
                                 f"{', '.join(versendet) or 'niemand'}.") from e
                    # Je Adresse eine Zeile: erst wenn alle Bewohner einer
                    # Partei ihre Mail haben, gilt die Partei als versorgt.
                    session.add(Versandprotokoll(
                        zeitraum_id=zid, partei=partei, empfaenger=adresse,
                        versendet_am=date.today()))
                    session.commit()
                versendet.append(partei)

    # „Abgeschlossen" heisst: jede versandbereite Partei hat ihre Abrechnung.
    # Der Status stand früher ausserhalb jeder Bedingung — hatte keine Partei
    # eine Mailadresse, ging keine einzige Mail raus und der Zeitraum galt
    # trotzdem als erledigt. Er verschwand damit aus Fristen und Erinnerungen,
    # obwohl niemand seine Abrechnung hatte. Der Leerstand zählt hier nicht:
    # hinter ihm steht kein Empfänger, sondern der Eigentümer selbst.
    fehlt_adresse = sorted(p for p in uebersprungen if p not in leer)
    if data.versenden and fehlt_adresse and not data.ohne_adresse_abschliessen:
        raise HTTPException(
            409, f"Ohne Mailadresse und deshalb nicht versendet: "
                 f"{', '.join(fehlt_adresse)}. Bereits verschickt: "
                 f"{', '.join(versendet) or 'niemand'}. Adresse im "
                 f"Mietverhältnis nachtragen und erneut versenden — oder den "
                 f"Abschluss ausdrücklich ohne diese Partei bestätigen.")

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
    beliefert = lambda: sorted({p for p, _ in _versendete_adressen(session, zid)})
    if z.status == "in Arbeit":
        return {"ok": True, "status": z.status, "geaendert": False,
                "bereits_versendet": beliefert()}
    z.status = "in Arbeit"
    session.add(z)
    session.commit()
    versendet = beliefert()
    log.info("Zeitraum %s wieder geöffnet (%d Partei(en) bereits beliefert)",
             zid, len(versendet))
    return {"ok": True, "status": z.status, "geaendert": True,
            "bereits_versendet": versendet}
