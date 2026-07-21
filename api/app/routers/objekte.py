"""Objekte, Zeiträume, Positionen, Abrechnung."""
import logging
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlmodel import Session, select

from ..db import get_session
from ..bezeichnung import anzeigename
from ..export import als_datei, dateiname, exportiere, importiere, loesche
from ..felder import bereinige
from ..engine import Position, abrechnung
from ..erinnerungen import beleg_erinnerung, frist_erinnerung, in_sicht
from ..frist import frist_tage
from ..nachpflege import hinweise, zusammenfassung
from ..models import (Dokument, Einheit, Kostenart, Kostenposition, Miete,
                      Objekt, Partei, Vorauszahlung, Zeitraum)
from ..verteilung import (SCHLUESSEL, VORGABE, UnbekannterSchluessel, ableiten,
                          fehlende_angaben, stammdaten, vorschau)

log = logging.getLogger("immocalc")
router = APIRouter(prefix="/api", tags=["objekte"])

# Sicherungen liegen im Home-Ordner, nicht bei den Unterlagen einer Immobilie —
# die bleibt beim Löschen ja gerade bestehen.
SICHERUNGSORDNER = "00_ImmoCalc_Sicherungen"


def _slugify(name: str) -> str:
    umlaute = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}
    s = name.lower()
    for k, v in umlaute.items():
        s = s.replace(k, v)
    s = "".join(c if c.isalnum() else "-" for c in s)
    return "-".join(t for t in s.split("-") if t) or "objekt"


def _freier_slug(session: Session, name: str) -> str:
    basis = _slugify(name)
    slug, n = basis, 2
    while session.exec(select(Objekt).where(Objekt.slug == slug)).first():
        slug = f"{basis}-{n}"
        n += 1
    return slug


class EinheitIn(BaseModel):
    bezeichnung: str
    nutzungsart: str = "Wohnen"
    flaeche: Optional[float] = None
    partei: str = ""
    personen: int = 1


class ObjektIn(BaseModel):
    name: str
    ort: str = ""
    strasse: str = ""
    plz: str = ""
    typ: str = "lg-mfhA"
    nutzung: str = "Wohnen"
    turnus: str = "kalender"
    start_monat: int = 1
    flaeche: Optional[float] = None
    kaufpreis: Optional[float] = None
    verkehrswert: Optional[float] = None
    kostenarten: list[str] = []
    einheiten: list[EinheitIn] = []


def _je_objekt(zeilen: list, ids: list[int]) -> dict[int, list]:
    """Ordnet Zeilen ihrem Objekt zu — jedes Objekt kommt vor, auch leer."""
    eimer: dict[int, list] = {i: [] for i in ids}
    for zeile in zeilen:
        eimer.setdefault(zeile.objekt_id, []).append(zeile)
    return eimer


@router.get("/objekte")
def objekte(session: Session = Depends(get_session)) -> list[dict]:
    """Die Objektliste der Startseite — mit den Einheiten je Objekt.

    Geholt wird in wenigen Abfragen für alle Objekte zusammen und danach in
    Python zugeordnet: je Objekt einzeln nachzuladen ergäbe bei zwanzig
    Immobilien hundert Abfragen für eine einzige Seite."""
    alle = session.exec(select(Objekt)).all()
    ids = [o.id for o in alle if o.id is not None]
    if not ids:
        return []

    zeitraeume = _je_objekt(session.exec(
        select(Zeitraum).where(Zeitraum.objekt_id.in_(ids))).all(), ids)
    einheiten = _je_objekt(session.exec(
        select(Einheit).where(Einheit.objekt_id.in_(ids))).all(), ids)
    mieten = _je_objekt(session.exec(
        select(Miete).where(Miete.objekt_id.in_(ids))).all(), ids)

    aktive = {oid: next((z for z in zs if z.status == "in Arbeit"), None)
              for oid, zs in zeitraeume.items()}
    zids = [z.id for z in aktive.values() if z is not None]
    offene: dict[int, int] = {}
    if zids:
        for p in session.exec(select(Kostenposition).where(
                Kostenposition.zeitraum_id.in_(zids))).all():
            if p.status == "offen":
                offene[p.zeitraum_id] = offene.get(p.zeitraum_id, 0) + 1

    out = []
    for o in alle:
        aktiv = aktive.get(o.id)
        laufend = [m for m in mieten[o.id] if m.bis_datum is None]
        # Eine Miete ohne Einheitsangabe meint das ganze Objekt — dann gilt
        # jede Einheit als vermietet, sonst keine einzige.
        ganzes_objekt = any(not m.einheit.strip() for m in laufend)
        belegt = {m.einheit.strip() for m in laufend if m.einheit.strip()}
        out.append({
            "id": o.id, "slug": o.slug, "name": o.name, "ort": o.ort,
            "anzeigename": anzeigename(o.name, o.ort, o.strasse, o.plz),
            "strasse": o.strasse, "plz": o.plz,
            "typ": o.typ, "turnus": o.turnus, "aktiv": o.aktiv,
            "einheiten": len(einheiten[o.id]),
            # Die Einheiten selbst — die Startseite zeigt sie als Bubbles.
            # `einheiten` bleibt die Anzahl, damit bestehende Aufrufer bleiben.
            "einheiten_liste": [
                {"id": e.id, "bezeichnung": e.bezeichnung,
                 "nutzungsart": e.nutzungsart, "flaeche": e.flaeche,
                 "vermietet": ganzes_objekt or e.bezeichnung.strip() in belegt}
                for e in einheiten[o.id]],
            "offene_positionen": offene.get(aktiv.id, 0) if aktiv else 0,
            "frist_tage": frist_tage(aktiv) if aktiv else None,
            "miete_monatlich": round(sum(m.kaltmiete for m in laufend), 2),
        })
    return out


@router.post("/objekte", status_code=201)
def objekt_anlegen(data: ObjektIn, session: Session = Depends(get_session)) -> dict:
    o = Objekt(
        slug=_freier_slug(session, data.name), name=data.name, ort=data.ort,
        strasse=data.strasse, plz=data.plz, typ=data.typ, nutzung=data.nutzung,
        turnus=data.turnus, start_monat=data.start_monat, flaeche=data.flaeche,
        kaufpreis=data.kaufpreis, verkehrswert=data.verkehrswert,
    )
    session.add(o)
    session.commit()
    session.refresh(o)

    for e in data.einheiten:
        session.add(Einheit(objekt_id=o.id, bezeichnung=e.bezeichnung,
                            nutzungsart=e.nutzungsart, flaeche=e.flaeche))
        if e.partei:
            session.add(Partei(objekt_id=o.id, name=e.partei, personen=e.personen))
    for name in data.kostenarten:
        session.add(Kostenart(objekt_id=o.id, name=name, aktiv=True))

    # Erster Zeitraum ergibt sich aus dem Turnus — sonst hat das Objekt nichts zu tun.
    heute = date.today()
    start = date(heute.year if data.start_monat <= heute.month else heute.year - 1,
                 data.start_monat, 1)
    ende = date(start.year + 1, start.month, 1) - timedelta(days=1)
    session.add(Zeitraum(objekt_id=o.id, start=start, ende=ende,
                         typ="regulär", status="in Arbeit"))
    session.commit()
    return {"slug": o.slug, "id": o.id, "name": o.name}


@router.get("/objekte/{slug}")
def objekt(slug: str, session: Session = Depends(get_session)) -> dict:
    o = session.exec(select(Objekt).where(Objekt.slug == slug)).first()
    if not o:
        raise HTTPException(404, "Objekt nicht gefunden")
    einheiten = session.exec(select(Einheit).where(Einheit.objekt_id == o.id)).all()
    parteien = session.exec(select(Partei).where(Partei.objekt_id == o.id)).all()
    zeitraeume = session.exec(select(Zeitraum).where(Zeitraum.objekt_id == o.id)).all()
    mieten = session.exec(select(Miete).where(Miete.objekt_id == o.id)).all()
    offen = hinweise(o, einheiten, mieten)
    return {
        "objekt": o, "einheiten": einheiten, "parteien": parteien,
        "nachpflege": {**zusammenfassung(offen), "offen": offen},
        "zeitraeume": [{"id": z.id, "label": f"{z.start:%d.%m.%Y} – {z.ende:%d.%m.%Y}",
                        "typ": z.typ, "status": z.status,
                        "frist_tage": frist_tage(z) if z.status == "in Arbeit" else None}
                       for z in zeitraeume],
    }


@router.patch("/objekte/{slug}")
def objekt_aendern(slug: str, data: dict, session: Session = Depends(get_session)) -> dict:
    o = session.exec(select(Objekt).where(Objekt.slug == slug)).first()
    if not o:
        raise HTTPException(404, "Objekt nicht gefunden")
    erlaubt = {"name", "ort", "strasse", "plz", "typ", "nutzung", "turnus",
               "start_monat", "flaeche", "kaufpreis", "kaufdatum", "verkehrswert",
               "aktiv", "nc_ordner", "bank", "iban", "kontoinhaber"}
    felder = bereinige(Objekt, {k: v for k, v in data.items() if k in erlaubt})
    if not felder.get("name", "x"):
        raise HTTPException(400, "Der Name darf nicht leer sein")
    # ueber model_validate, damit Datumsstrings aus JSON zu echten date-Objekten
    # werden — als Zeichenkette gespeichert liesse sich das Feld nicht mehr lesen.
    geprueft = Objekt.model_validate({**o.model_dump(), **felder})
    for k in felder:
        setattr(o, k, getattr(geprueft, k))
    session.add(o)
    session.commit()
    return {"ok": True, "slug": o.slug}


@router.get("/objekte/{slug}/export")
def objekt_export(slug: str, session: Session = Depends(get_session)) -> Response:
    """Vollständige Sicherung als JSON-Datei zum Herunterladen."""
    o = session.exec(select(Objekt).where(Objekt.slug == slug)).first()
    if not o:
        raise HTTPException(404, "Objekt nicht gefunden")
    daten = exportiere(session, o)
    return Response(
        content=als_datei(daten), media_type="application/json",
        headers={"Content-Disposition":
                 f'attachment; filename="{dateiname(o)}"'})


def _sicherung_in_die_cloud(session: Session, objekt: Objekt,
                            daten: dict) -> dict:
    """Legt die Sicherung neben den Unterlagen ab — best effort.

    Scheitert das (keine Verbindung, kein Home-Ordner), wird trotzdem
    gelöscht: die Sicherung geht ohnehin auch an den Browser."""
    from .cloud import S_HOME, _lies, verbindung          # zirkelfrei zur Laufzeit
    home = _lies(session, S_HOME)
    if not home:
        return {"gesichert": False, "grund": "Kein Home-Ordner gewählt"}
    ordner = f"{home.strip('/')}/{SICHERUNGSORDNER}"
    ziel = f"{ordner}/{dateiname(objekt)}"
    try:
        client = verbindung(session)
        client.ordner_anlegen(ordner)
        name, n = ziel, 2
        while client.existiert(name):        # nie überschreiben
            name = ziel[:-5] + f"_{n}.json"
            n += 1
        client.lege_ab(name, als_datei(daten), typ="application/json")
        return {"gesichert": True, "pfad": "/" + name}
    except Exception as fehler:              # noqa: BLE001 — Löschen soll laufen
        log.warning("Sicherung in die Cloud fehlgeschlagen: %s", fehler)
        return {"gesichert": False, "grund": str(fehler)}


@router.delete("/objekte/{slug}")
def objekt_loeschen(slug: str, session: Session = Depends(get_session)) -> dict:
    """Löscht eine Immobilie samt allem, was in der Datenbank daran hängt.

    Vorher wird eine JSON-Sicherung in die Nextcloud geschrieben. Die dort
    liegenden Unterlagen bleiben unberührt — sie gehören dem Nutzer."""
    o = session.exec(select(Objekt).where(Objekt.slug == slug)).first()
    if not o:
        raise HTTPException(404, "Objekt nicht gefunden")
    daten = exportiere(session, o)
    sicherung = _sicherung_in_die_cloud(session, o, daten)
    name, ordner = o.name, o.nc_ordner
    entfernt = loesche(session, o)
    return {"ok": True, "name": name, "entfernt": entfernt,
            "sicherung": sicherung,
            "cloud_ordner_bleibt": ordner or None}


@router.post("/objekte/import", status_code=201)
def objekt_import(daten: dict, session: Session = Depends(get_session)) -> dict:
    """Legt aus einer Sicherung wieder ein Objekt an — immer als neuer Eintrag."""
    if not isinstance(daten.get("objekt"), dict):
        raise HTTPException(400, "Keine ImmoCalc-Sicherung: 'objekt' fehlt")
    o = importiere(session, daten, _freier_slug)
    return {"slug": o.slug, "id": o.id, "name": o.name}


@router.get("/objekte/{slug}/kostenarten")
def kostenarten(slug: str, session: Session = Depends(get_session)) -> list[Kostenart]:
    o = session.exec(select(Objekt).where(Objekt.slug == slug)).first()
    if not o:
        raise HTTPException(404, "Objekt nicht gefunden")
    return session.exec(select(Kostenart).where(Kostenart.objekt_id == o.id)).all()


@router.get("/erinnerungen")
def erinnerungen(session: Session = Depends(get_session)) -> dict:
    """Was ansteht: Abrechnungsfristen und erwartete Jahresabrechnungen.
    Grundlage für Benachrichtigungen."""
    heute = date.today()
    offen = []
    for o in session.exec(select(Objekt)).all():
        if not o.aktiv:
            continue
        for z in session.exec(select(Zeitraum).where(Zeitraum.objekt_id == o.id)).all():
            if z.status != "in Arbeit":
                continue
            label = f"{z.start:%d.%m.%Y} – {z.ende:%d.%m.%Y}"
            hinweis = frist_erinnerung(label, frist_tage(z),
                                       zeitraum_beendet=z.ende <= heute)
            if in_sicht(hinweis):
                offen.append({"objekt": o.slug, "name": o.name, **hinweis})

            vorhanden = {p.kostenart for p in session.exec(
                select(Kostenposition).where(
                    Kostenposition.zeitraum_id == z.id)).all()
                if p.status == "erledigt"}
            for k in session.exec(
                    select(Kostenart).where(Kostenart.objekt_id == o.id)).all():
                if not k.aktiv:
                    continue
                hinweis = beleg_erinnerung(k.name, k.beleg_monat, k.erinnerung_tage,
                                           k.name in vorhanden, heute)
                if in_sicht(hinweis):
                    offen.append({"objekt": o.slug, "name": o.name, **hinweis})

    offen.sort(key=lambda e: (not e["faellig"], e["tage"]))
    return {"heute": heute.isoformat(),
            "faellig": sum(1 for e in offen if e["faellig"]),
            "erinnerungen": offen}


@router.get("/zeitraeume/{zid}/positionen")
def positionen(zid: int, session: Session = Depends(get_session)) -> list[Kostenposition]:
    return session.exec(
        select(Kostenposition).where(Kostenposition.zeitraum_id == zid)).all()


@router.get("/zeitraeume/{zid}")
def zeitraum(zid: int, session: Session = Depends(get_session)) -> dict:
    """Checkliste eines Abrechnungszeitraums: was liegt vor, was fehlt.

    Jede aktive Kostenart des Objekts ist eine Zeile. Ohne Position gilt sie
    als offen — so sieht man auch, was noch gar nicht erfasst wurde."""
    z = session.get(Zeitraum, zid)
    if not z:
        raise HTTPException(404, "Zeitraum nicht gefunden")
    o = session.get(Objekt, z.objekt_id)

    positionen = session.exec(
        select(Kostenposition).where(Kostenposition.zeitraum_id == zid)).all()
    arten = session.exec(select(Kostenart).where(Kostenart.objekt_id == o.id)).all()
    dokumente = session.exec(
        select(Dokument).where(Dokument.zeitraum_id == zid)).all()
    vzs = session.exec(select(Vorauszahlung).where(Vorauszahlung.zeitraum_id == zid)).all()

    nach_art = {p.kostenart: p for p in positionen}

    def _verteilung(p: Optional[Kostenposition]) -> dict:
        """Wie die Position verteilt wird — und ob sie das überhaupt tut.

        `ohne_verteilung` ist der ehrliche Hinweis: eine erledigte Position
        ohne Gewichte fällt aus der Abrechnung heraus, ohne dass es jemand
        merkt. Die Zeile sieht fertig aus, ihr Betrag taucht aber nirgends
        wieder auf."""
        anteile = (p.anteile or {}) if p else {}
        meta = SCHLUESSEL.get((p.schluessel if p else "") or "", {})
        return {
            "anteile": anteile,
            "anteile_einheit": meta.get("einheit", ""),
            "anteile_summe": round(sum(anteile.values()), 4),
            "ohne_verteilung": bool(
                p and p.status == "erledigt" and (p.betrag or 0) != 0
                and sum(anteile.values()) <= 0),
        }

    belege = {}
    for d in dokumente:
        belege.setdefault(d.kategorie or "", []).append(
            {"id": d.id, "dateiname": d.dateiname, "pfad": d.pfad})

    checkliste = []
    for k in arten:
        if not k.aktiv:
            continue
        p = nach_art.get(k.name)
        erledigt = bool(p and p.status == "erledigt")
        checkliste.append({
            "kostenart": k.name, "s35": k.s35 or (p.s35 if p else False),
            "erledigt": erledigt,
            "betrag": p.betrag if p else None,
            "schluessel": p.schluessel if p else None,
            "wertquelle": p.wertquelle if p else None,
            **_verteilung(p),
            "position_id": p.id if p else None,
            "beleg_monat": k.beleg_monat,
            "zustand": "erledigt" if erledigt else ("offen" if p else "fehlt"),
        })
    # Positionen zu Kostenarten, die nicht im Katalog stehen, gehen sonst verloren
    for p in positionen:
        if p.kostenart in {k["kostenart"] for k in checkliste}:
            continue
        checkliste.append({
            "kostenart": p.kostenart, "s35": p.s35,
            "erledigt": p.status == "erledigt", "betrag": p.betrag,
            "schluessel": p.schluessel, "wertquelle": p.wertquelle,
            **_verteilung(p),
            "position_id": p.id, "beleg_monat": None,
            "zustand": "erledigt" if p.status == "erledigt" else "offen",
        })

    fertig = sum(1 for k in checkliste if k["erledigt"])
    # Fluss fuer das Diagramm: erledigte Kostenarten -> Abrechnung -> Parteien
    summe_erledigt = sum(k["betrag"] or 0 for k in checkliste if k["erledigt"])
    knoten = [{"name": "Abrechnung", "spalte": 1}]
    fluss = []
    for k in sorted((k for k in checkliste if k["erledigt"] and (k["betrag"] or 0) > 0),
                    key=lambda k: -(k["betrag"] or 0)):
        knoten.append({"name": k["kostenart"], "spalte": 0})
        fluss.append({"von": len(knoten) - 1, "nach": 0, "wert": round(k["betrag"], 2)})
    if summe_erledigt > 0:
        gewichte = {}
        for k in checkliste:
            if not k["erledigt"]:
                continue
            gesamt_anteil = sum(k["anteile"].values()) or 1
            for partei, anteil in (k["anteile"] or {}).items():
                gewichte[partei] = gewichte.get(partei, 0.0) + \
                    (k["betrag"] or 0) * anteil / gesamt_anteil
        for partei, betrag in sorted(gewichte.items(), key=lambda p: -p[1]):
            knoten.append({"name": partei, "spalte": 2})
            fluss.append({"von": 0, "nach": len(knoten) - 1, "wert": round(betrag, 2)})

    return {
        "id": z.id, "objekt": o.slug, "objekt_name": o.name,
        "label": f"{z.start:%d.%m.%Y} – {z.ende:%d.%m.%Y}",
        "start": z.start.isoformat(), "ende": z.ende.isoformat(),
        "typ": z.typ, "status": z.status,
        "frist_tage": frist_tage(z) if z.status == "in Arbeit" else None,
        "fortschritt": {"fertig": fertig, "gesamt": len(checkliste),
                        "summe": round(summe_erledigt, 2)},
        "checkliste": checkliste,
        "sankey": {"knoten": knoten, "fluss": fluss},
        "dokumente": [{"id": d.id, "dateiname": d.dateiname, "pfad": d.pfad,
                       "kategorie": d.kategorie} for d in dokumente],
        "belege_je_art": belege,
        "vorauszahlungen": [{"partei": v.partei, "betrag": v.betrag} for v in vzs],
    }


class ZeitraumIn(BaseModel):
    """Ein Jahr genügt — Start und Ende ergeben sich aus dem Turnus des Objekts.
    Wer abweichende Grenzen braucht, gibt sie direkt an."""
    jahr: Optional[int] = None
    start: Optional[date] = None
    ende: Optional[date] = None
    typ: str = "regulär"


@router.post("/objekte/{slug}/zeitraeume", status_code=201)
def zeitraum_anlegen(slug: str, data: ZeitraumIn,
                     session: Session = Depends(get_session)) -> dict:
    """Legt einen weiteren Abrechnungszeitraum an — typisch ein Vorjahr.

    Die Kostenarten stehen am Objekt, nicht am Zeitraum; die Checkliste des
    neuen Zeitraums ist damit sofort vollständig. Übernommen werden zusätzlich
    die Vorauszahlungen des Vorgängers, denn die ändern sich selten."""
    o = session.exec(select(Objekt).where(Objekt.slug == slug)).first()
    if not o:
        raise HTTPException(404, "Objekt nicht gefunden")

    if data.start and data.ende:
        start, ende = data.start, data.ende
    else:
        jahr = data.jahr or (date.today().year - 1)
        start = date(jahr, o.start_monat or 1, 1)
        ende = date(start.year + 1, start.month, 1) - timedelta(days=1)
    if ende <= start:
        raise HTTPException(400, "Das Ende muss nach dem Start liegen")

    bestehende = session.exec(
        select(Zeitraum).where(Zeitraum.objekt_id == o.id)).all()
    if any(z.start == start and z.ende == ende for z in bestehende):
        raise HTTPException(409, "Diesen Zeitraum gibt es bereits")

    z = Zeitraum(objekt_id=o.id, start=start, ende=ende, typ=data.typ,
                 status="in Arbeit")
    session.add(z)
    session.commit()
    session.refresh(z)

    # Vorauszahlungen vom zeitlich nächsten Vorgänger übernehmen
    vorgaenger = sorted((b for b in bestehende if b.ende <= start),
                        key=lambda b: b.ende)
    uebernommen = 0
    if vorgaenger:
        for v in session.exec(select(Vorauszahlung).where(
                Vorauszahlung.zeitraum_id == vorgaenger[-1].id)).all():
            session.add(Vorauszahlung(zeitraum_id=z.id, partei=v.partei,
                                      betrag=v.betrag))
            uebernommen += 1
        session.commit()

    arten = [k for k in session.exec(
        select(Kostenart).where(Kostenart.objekt_id == o.id)).all() if k.aktiv]
    return {"id": z.id, "label": f"{z.start:%d.%m.%Y} – {z.ende:%d.%m.%Y}",
            "kostenarten": len(arten), "vorauszahlungen": uebernommen}


def _zeitraum(session: Session, zid: int) -> Zeitraum:
    z = session.get(Zeitraum, zid)
    if not z:
        raise HTTPException(404, "Zeitraum nicht gefunden")
    return z


def _gewichte(session: Session, z: Zeitraum, schluessel: str) -> dict[str, float]:
    try:
        return ableiten(session, z, schluessel)
    except UnbekannterSchluessel as fehler:
        raise HTTPException(400, str(fehler)) from fehler


@router.get("/zeitraeume/{zid}/schluessel")
def schluessel_vorschau(zid: int, session: Session = Depends(get_session)) -> dict:
    """Welche Verteilungsschlüssel für dieses Objekt taugen — und welche
    Gewichte dabei herauskämen.

    Vorschau vor der Festlegung: `moeglich` sagt, ob sich der Schlüssel aus den
    Stammdaten ergibt. `unbekannte_vorauszahlungen` deckt den stillen Fehler
    auf, bei dem eine Vorauszahlung auf einen Parteinamen lautet, den die
    Verteilung gar nicht kennt — die Engine rechnet dann an ihr vorbei."""
    z = _zeitraum(session, zid)
    bezuege = stammdaten(session, z)
    parteien = sorted({b.partei for b in bezuege})
    vzs = session.exec(
        select(Vorauszahlung).where(Vorauszahlung.zeitraum_id == zid)).all()
    return {
        "zeitraum": zid, "vorgabe": VORGABE,
        "parteien": [{"partei": b.partei, "einheit": b.einheit,
                      "flaeche": b.flaeche, "personen": b.personen}
                     for b in bezuege],
        "schluessel": vorschau(bezuege, z.start, z.ende),
        "unbekannte_vorauszahlungen": sorted(
            {v.partei for v in vzs} - set(parteien)),
    }


class PositionNeu(BaseModel):
    """Ohne `anteile` werden die Gewichte aus dem Schlüssel abgeleitet."""
    kostenart: str
    betrag: float = 0.0
    schluessel: str = VORGABE
    wertquelle: str = "manuell"
    status: Optional[str] = None
    s35: Optional[bool] = None
    anteile: Optional[dict[str, float]] = None


@router.post("/zeitraeume/{zid}/positionen", status_code=201)
def position_anlegen(zid: int, data: PositionNeu,
                     session: Session = Depends(get_session)) -> dict:
    """Legt eine Kostenposition an — mit Gewichten, nicht ohne.

    Bisher entstanden Positionen nur beiläufig (Beleg-Scan) und blieben ohne
    `anteile`; ihr Betrag fiel damit aus der Abrechnung heraus."""
    z = _zeitraum(session, zid)
    if not data.kostenart.strip():
        raise HTTPException(400, "Die Kostenart darf nicht leer sein")
    vorhanden = session.exec(select(Kostenposition).where(
        Kostenposition.zeitraum_id == zid)).all()
    if any(p.kostenart == data.kostenart for p in vorhanden):
        raise HTTPException(409, f"'{data.kostenart}' ist in diesem Zeitraum "
                                 f"bereits erfasst")

    anteile = (data.anteile if data.anteile is not None
               else _gewichte(session, z, data.schluessel))
    # Der §35a-Vermerk hängt am Katalog des Objekts; eine neue Position erbt ihn.
    s35 = data.s35
    if s35 is None:
        art = session.exec(select(Kostenart).where(
            Kostenart.objekt_id == z.objekt_id,
            Kostenart.name == data.kostenart)).first()
        s35 = bool(art and art.s35)

    p = Kostenposition(
        zeitraum_id=zid, kostenart=data.kostenart, betrag=data.betrag,
        schluessel=data.schluessel, wertquelle=data.wertquelle, s35=s35,
        status=data.status or ("erledigt" if data.betrag else "offen"),
        anteile=anteile)
    session.add(p)
    session.commit()
    session.refresh(p)
    return {"id": p.id, "kostenart": p.kostenart, "status": p.status,
            "anteile": p.anteile, "abgeleitet": data.anteile is None}


class PositionIn(BaseModel):
    betrag: Optional[float] = None
    status: Optional[str] = None
    schluessel: Optional[str] = None
    wertquelle: Optional[str] = None
    anteile: Optional[dict[str, float]] = None
    s35: Optional[bool] = None


@router.patch("/positionen/{pid}")
def position_aendern(pid: int, data: PositionIn,
                     session: Session = Depends(get_session)) -> dict:
    """Betrag nachtragen oder Zustand ändern — das Nachbearbeiten aus der App.

    Wird nur der Schlüssel umgestellt, werden die Gewichte neu abgeleitet:
    Fläche-Gewichte unter dem Schlüssel „Personen" stehen zu lassen wäre die
    unauffälligste Art, falsch abzurechnen."""
    p = session.get(Kostenposition, pid)
    if not p:
        raise HTTPException(404, "Position nicht gefunden")
    if data.betrag is not None:
        p.betrag = data.betrag
        # Ein eingetragener Betrag heisst: der Beleg liegt vor.
        if data.status is None and data.betrag > 0:
            p.status = "erledigt"
    if data.schluessel is not None and data.schluessel not in SCHLUESSEL:
        raise HTTPException(400, f"Unbekannter Verteilungsschlüssel "
                                 f"'{data.schluessel}'")
    umgestellt = data.schluessel is not None and data.schluessel != p.schluessel
    for feld in ("status", "schluessel", "wertquelle", "s35"):
        wert = getattr(data, feld)
        if wert is not None:
            setattr(p, feld, wert)
    if data.anteile is not None:
        p.anteile = data.anteile
    elif umgestellt:
        p.anteile = _gewichte(session, _zeitraum(session, p.zeitraum_id),
                              p.schluessel)
    session.add(p)
    session.commit()
    return {"ok": True, "betrag": p.betrag, "status": p.status,
            "schluessel": p.schluessel, "anteile": p.anteile}


@router.delete("/positionen/{pid}")
def position_loeschen(pid: int, session: Session = Depends(get_session)) -> dict:
    """Entfernt eine Kostenposition — eine bewusste Nutzeraktion.

    Die Kostenart bleibt im Katalog des Objekts stehen; die Zeile taucht in der
    Checkliste danach wieder als „fehlt" auf, statt zu verschwinden."""
    p = session.get(Kostenposition, pid)
    if not p:
        raise HTTPException(404, "Position nicht gefunden")
    kostenart = p.kostenart
    session.delete(p)
    session.commit()
    return {"ok": True, "kostenart": kostenart}


@router.get("/zeitraeume/{zid}/abrechnung")
def abrechnung_endpoint(zid: int, session: Session = Depends(get_session)) -> dict:
    _zeitraum(session, zid)
    pos = session.exec(select(Kostenposition).where(Kostenposition.zeitraum_id == zid)).all()
    vzs = session.exec(select(Vorauszahlung).where(Vorauszahlung.zeitraum_id == zid)).all()
    # offene Positionen (Betrag noch nicht da) fließen nicht in die Rechnung ein
    positionen = [Position(p.kostenart, p.betrag, p.schluessel, p.anteile or {}, p.s35)
                  for p in pos if p.status == "erledigt"]
    res = abrechnung(positionen, {v.partei: v.betrag for v in vzs})
    # Erledigte Positionen ohne Gewichte gehören zu den offenen: ihr Betrag
    # verschwindet sonst lautlos, und der Abschluss übergeht sie.
    res.update(fehlende_angaben(list(pos)))
    return res
