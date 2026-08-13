"""Eigentümer, Beteiligungen in Tausendsteln und die Vermögensübersicht."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from ..bezeichnung import objekt_titel
from ..db import get_session
from ..deps import objekt_holen
from ..models import (Anteil, Einheit, Eigentuemer, Grundschuld,
                      GrundschuldKredit, Kredit, Kreditstand, Miete,
                      Objekt, PVAnlage, Tankladung, Tanknutzer,
                      ist_grundstueck)
from ..turnus import jahresbetrag
from ..vermoegen import (PROMILLE_TOLERANZ, VOLLE_PROMILLE, attributionswert,
                         eigentuemer_fraktion, gesamt, kreditstand,
                         objekt_vermoegen, pv_zurechnung)

router = APIRouter(prefix="/api", tags=["besitz"])

# N370 — beide aus `vermoegen`, damit „voll vergeben" überall dasselbe heißt.
VOLL = VOLLE_PROMILLE          # ein ganzes Objekt in Promille
TOLERANZ = PROMILLE_TOLERANZ


def promille_von(a: Anteil) -> float:
    """Massgeblicher Anteil einer Beteiligung.

    Bestandszeilen haben noch kein `promille` — dort gilt weiter das
    ganzzahlige `tausendstel`. So ueberlebt jede eingegebene Beteiligung die
    Erweiterung auf Dezimalwerte."""
    return float(a.promille if a.promille is not None else (a.tausendstel or 0))


def rolle_von(promille: float) -> str:
    """Rolle aus dem Anteil ableiten statt sie waehlen zu lassen.

    Wer alles haelt, ist Alleineigentuemer; wer weniger haelt, teilt sich das
    Objekt mit jemandem. Von Hand gewaehlt koennte die Rolle den Tausendsteln
    widersprechen — abgeleitet kann sie das nie."""
    return "Alleineigentümer" if runde(promille) >= VOLL else "Miteigentümer"


def runde(wert: float) -> float:
    """Eine Nachkommastelle — 333,3 dreimal soll als vollstaendig gelten."""
    return round(wert + 0.0, 1)


# CCCXXXIV — Fallback Objektart aus dem Logo-/Gebäudetyp, solange am Objekt
# keine freie Objektart gepflegt ist. So zeigt die Übersicht immer etwas
# Sprechendes statt eines leeren Feldes.
_TYP_OBJEKTART = {
    "lg-grundstueck": "Grundstück",
    "lg-villa": "Villa",
    "lg-mfhA": "Mehrfamilienhaus",
    "lg-mfhB": "Zwei-/Doppelhaus",
    "lg-wohnung": "Einzelne Wohnung",
    "lg-bauernhof": "Bauernhof",
    "lg-gewerbe": "Gewerbe",
}


def objektart_von(o: Objekt) -> str:
    """Anzuzeigende Objektart: die gepflegte, sonst aus `typ` abgeleitet."""
    frei = (getattr(o, "objektart", "") or "").strip()
    if frei:
        return frei
    return _TYP_OBJEKTART.get(getattr(o, "typ", ""), "Immobilie")


class EigentuemerIn(BaseModel):
    name: str
    email: str = ""
    telefon: str = ""
    anschrift: str = ""
    steuernummer: str = ""
    notiz: str = ""
    # N218 — Profilbild als Data-URI, vom Vanilla-Cropper auf 320×320 JPEG
    # gerendert. Leer = kein Bild (Initialen-Icon bleibt der Normalfall).
    bild: str = ""


# N218 — grobes Größenlimit: der Cropper liefert ein 320×320-JPEG (typischerweise
# wenige Dutzend KB als Data-URI). Kein Overengineering, nur ein Riegel gegen
# eine unbegrenzte Blob-Explosion in der SQLite bei Fehlbedienung/Missbrauch.
BILD_MAX_ZEICHEN = 2_000_000


def _bild_pruefen(bild: str) -> None:
    if len(bild or "") > BILD_MAX_ZEICHEN:
        raise HTTPException(400, "Profilbild ist zu groß")


@router.get("/eigentuemer", response_model=None)
def liste(session: Session = Depends(get_session)) -> list:
    """Alle Eigentümer mit ihren Beteiligungen — die Liste in den Einstellungen."""
    objekte = {o.id: o for o in session.exec(select(Objekt)).all()}
    anteile = session.exec(select(Anteil)).all()
    out = []
    for e in session.exec(select(Eigentuemer)).all():
        meine = [a for a in anteile if a.eigentuemer_id == e.id]
        out.append({
            **e.model_dump(),
            "objekte": [{"anteil_id": a.id, "slug": objekte[a.objekt_id].slug,
                         "name": objekte[a.objekt_id].name,
                         "titel": objekt_titel(objekte[a.objekt_id]),
                         "tausendstel": a.tausendstel,
                         "promille": runde(promille_von(a)),
                         # CLXI: die Rolle beschreibt das Eigentum am Bezugspunkt
                         # — am ganzen Haus oder an genau der Einheit.
                         "einheit": (getattr(a, "einheit", "") or "").strip(),
                         "rolle": rolle_von(promille_von(a)),
                         # CCCXXXIV — Objektart und Adresse für die dreigeteilte
                         # Darstellung (Objektart · Einheit / Adresse). Beim
                         # Grundstück ist die Flurnummer die Adresse.
                         "objektart": objektart_von(objekte[a.objekt_id]),
                         "typ": objekte[a.objekt_id].typ,
                         "strasse": objekte[a.objekt_id].strasse,
                         "plz": objekte[a.objekt_id].plz,
                         "ort": objekte[a.objekt_id].ort,
                         "flurstueck": objekte[a.objekt_id].flurstueck,
                         "gemarkung": objekte[a.objekt_id].gemarkung,
                         "notiz": a.notiz}
                        for a in meine if a.objekt_id in objekte],
        })
    return out


@router.post("/eigentuemer", status_code=201)
def anlegen(data: EigentuemerIn, session: Session = Depends(get_session)) -> dict:
    _bild_pruefen(data.bild)
    e = Eigentuemer.model_validate(data.model_dump())
    session.add(e)
    session.commit()
    session.refresh(e)
    return {"id": e.id, "name": e.name}


@router.patch("/eigentuemer/{eid}")
def aendern(eid: int, data: dict, session: Session = Depends(get_session)) -> dict:
    e = session.get(Eigentuemer, eid)
    if not e:
        raise HTTPException(404, "Eigentümer nicht gefunden")
    if "bild" in data:
        _bild_pruefen(data.get("bild") or "")
    # N370 — `hasattr` war die einzige Prüfung: ein `{"telefon": 123}` landete
    # als Zahl in einer Text-Spalte, ein ausdrückliches `null` in einer
    # Pflichtspalte brach mit 500. Jetzt entscheidet das Eingabemodell, welche
    # Felder es gibt und welchen Typ sie haben — dasselbe wie beim Anlegen.
    erlaubt = set(EigentuemerIn.model_fields)
    unbekannt = [k for k in data if k not in erlaubt and k != "id"]
    if unbekannt:
        raise HTTPException(400, f"Unbekannte Felder: {', '.join(sorted(unbekannt))}")
    geprueft = EigentuemerIn.model_validate(
        {**{k: getattr(e, k) for k in erlaubt if hasattr(e, k)},
         **{k: v for k, v in data.items() if k in erlaubt and v is not None}})
    for feld in erlaubt:
        if feld in data and data[feld] is not None:
            setattr(e, feld, getattr(geprueft, feld))
    session.add(e)
    session.commit()
    return {"ok": True}


@router.delete("/eigentuemer/{eid}")
def loeschen(eid: int, session: Session = Depends(get_session)) -> dict:
    """Entfernt den Eigentümer und seine Beteiligungen. Objekte bleiben."""
    e = session.get(Eigentuemer, eid)
    if not e:
        raise HTTPException(404, "Eigentümer nicht gefunden")
    for a in session.exec(select(Anteil).where(Anteil.eigentuemer_id == eid)).all():
        session.delete(a)
    # N366 — Ladungen und Tanknutzer zeigen ebenfalls auf diese Person. Der
    # Verweis wird gelöst, die Zeilen bleiben: SQLite vergibt die frei
    # gewordene Nummer neu, und die Ladungen liefen sonst plötzlich auf den
    # nächsten angelegten Eigentümer — samt seiner Bankdaten auf der
    # Ladeabrechnung. `_person` fällt ohne Verweis sauber auf den in der
    # Ladung gespeicherten Namen zurück.
    for modell in (Tanknutzer, Tankladung):
        for zeile in session.exec(
                select(modell).where(modell.person_id == eid)).all():
            zeile.person_id = None
            session.add(zeile)
    session.delete(e)
    session.commit()
    return {"ok": True}


class AnteilIn(BaseModel):
    eigentuemer_id: int
    # `tausendstel` bleibt als Eingang bestehen, damit die Objektseite
    # unveraendert weiterschreiben kann; `promille` hat Vorrang.
    tausendstel: float = 1000
    promille: float | None = None
    # CLXI: leer = ganzes Objekt (der gewachsene Fall), sonst die Bezeichnung
    # einer Einheit dieses Objekts. „Mir gehört Wohnung 2" statt nur „mir
    # gehören 200 ‰ des Hauses". Nicht mitgesendet (None) = ganzes Objekt.
    einheit: str | None = None
    # Nicht mitgesendet (None) heisst „lass sie, wie sie ist" — der Endpunkt ist
    # ein Upsert, und ein Aufrufer, der nur den Anteil setzt, darf eine
    # gepflegte Notiz nicht mitlöschen (Fund N118).
    notiz: str | None = None


def _ist_objektanteil(a: Anteil) -> bool:
    """Hängt dieser Anteil am ganzen Objekt (statt an einer Einheit)?"""
    return not (getattr(a, "einheit", "") or "").strip()


def _stand(zeilen: list[Anteil], einheiten: list[Einheit] | None = None) -> dict:
    """Verteilungsstand eines Objekts — auf eine Nachkommastelle genau.

    Ohne Einheit-Anteile ist es der gewachsene Fall: die Summe muss 1000 ‰
    ergeben. Mit Einheit-Anteilen (CLXI) gilt zusätzlich: je Einheit müssen
    1000 ‰ verteilt sein, und der Objekt-Anteil deckt die Einheiten, die keine
    eigene Zuordnung tragen ("der Rest"). Ist jede Einheit einzeln zugeordnet,
    braucht es keinen Objekt-Anteil mehr — dann wäre er sogar zu viel."""
    einheiten = einheiten or []
    namen = {e.bezeichnung.strip() for e in einheiten}
    objektanteile = [a for a in zeilen if _ist_objektanteil(a)]
    je_einheit: dict[str, list[Anteil]] = {}
    for a in zeilen:
        b = (getattr(a, "einheit", "") or "").strip()
        if b:
            je_einheit.setdefault(b, []).append(a)

    vergeben = runde(sum(promille_von(a) for a in objektanteile))
    rest = [e for e in einheiten if e.bezeichnung.strip() not in je_einheit]
    # Der Objekt-Anteil wird gebraucht, solange es Einheiten ohne eigene
    # Zuordnung gibt — oder wenn es (noch) gar keine Einheit-Anteile gibt.
    objekt_noetig = bool(rest) or not je_einheit

    probleme: list[str] = []
    if objekt_noetig:
        if not (vergeben and abs(VOLL - vergeben) <= TOLERANZ + 1e-9):
            probleme.append("objekt")
    elif vergeben > TOLERANZ:
        probleme.append("objekt_zuviel")

    einheiten_stand = []
    for b, zs in je_einheit.items():
        v = runde(sum(promille_von(a) for a in zs))
        unbekannt = bool(namen) and b not in namen
        ok = abs(VOLL - v) <= TOLERANZ + 1e-9 and not unbekannt
        if not ok:
            probleme.append(f"einheit:{b}")
        einheiten_stand.append({
            "einheit": b, "vergeben": v, "frei": runde(VOLL - v),
            "stimmig": ok, "unbekannt": unbekannt})

    return {
        "vergeben": vergeben,
        "frei": runde(VOLL - vergeben),
        "stimmig": bool(zeilen) and not probleme,
        # Braucht dieses Objekt (noch) einen Objekt-Anteil, oder ist schon
        # jede Einheit einzeln zugeordnet?
        "objekt_noetig": objekt_noetig,
        "einheiten_stand": einheiten_stand,
    }


@router.get("/objekte/{slug}/anteile", response_model=None)
def anteile(slug: str, session: Session = Depends(get_session),
           o: Objekt = Depends(objekt_holen)) -> dict:
    """Beteiligungen an einem Objekt. `frei` zeigt, was noch nicht verteilt ist.

    Ein Anteil kann am ganzen Objekt hängen (`einheit` leer) oder an einer
    Einheit (CLXI). Die Einheiten kommen mit, damit die Oberfläche zur Auswahl
    stellt, worauf ein Anteil zeigt."""
    eigner = {e.id: e for e in session.exec(select(Eigentuemer)).all()}
    einheiten = list(session.exec(
        select(Einheit).where(Einheit.objekt_id == o.id)).all())
    zeilen = session.exec(select(Anteil).where(Anteil.objekt_id == o.id)).all()
    return {
        "anteile": [{"id": a.id, "eigentuemer_id": a.eigentuemer_id,
                     "name": eigner[a.eigentuemer_id].name
                     if a.eigentuemer_id in eigner else "unbekannt",
                     "tausendstel": a.tausendstel,
                     "promille": runde(promille_von(a)),
                     "rolle": rolle_von(promille_von(a)),
                     "prozent": round(promille_von(a) / 10, 2),
                     "einheit": (getattr(a, "einheit", "") or "").strip(),
                     "notiz": a.notiz}
                    for a in zeilen],
        "einheiten": [{"id": e.id, "bezeichnung": e.bezeichnung,
                       "verkehrswert": e.verkehrswert} for e in einheiten],
        **_stand(list(zeilen), einheiten),
    }


@router.get("/anteile/stand", response_model=None)
def anteilsstand(session: Session = Depends(get_session)) -> list:
    """Verteilungsstand aller aktiven Objekte — fuer die Eigentuemerseite.

    Bewusst auch Objekte ohne jede Beteiligung: gerade die fehlen sonst
    unbemerkt in der Uebersicht."""
    alle = session.exec(select(Anteil)).all()
    alle_einheiten: dict[int, list[Einheit]] = {}
    for e in session.exec(select(Einheit)).all():
        alle_einheiten.setdefault(e.objekt_id, []).append(e)
    out = []
    for o in session.exec(select(Objekt)).all():
        if not o.aktiv:
            continue
        zeilen = [a for a in alle if a.objekt_id == o.id]
        out.append({"slug": o.slug, "name": o.name, "titel": objekt_titel(o),
                    "beteiligte": len(zeilen),
                    **_stand(zeilen, alle_einheiten.get(o.id, []))})
    out.sort(key=lambda z: (z["stimmig"], z["name"]))
    return out


@router.post("/objekte/{slug}/anteile", status_code=201)
def anteil_setzen(slug: str, data: AnteilIn,
                  session: Session = Depends(get_session),
                  o: Objekt = Depends(objekt_holen)) -> dict:
    """Legt eine Beteiligung an oder ändert eine bestehende desselben Eigners.

    Bewusst kein zweiter Eintrag pro Person *und Einheit*: sonst stünde dieselbe
    Beteiligung doppelt in der Liste und die Tausendstel gingen nicht mehr auf.
    Dieselbe Person kann aber sehr wohl am ganzen Objekt *und* an einer Einheit
    beteiligt sein — das sind zwei verschiedene Zuordnungen (CLXI)."""
    if not session.get(Eigentuemer, data.eigentuemer_id):
        raise HTTPException(404, "Eigentümer nicht gefunden")
    wert = runde(data.promille if data.promille is not None else data.tausendstel)
    if not 0 < wert <= VOLL:
        raise HTTPException(400, "Anteile müssen zwischen 0,1 und 1000 ‰ liegen")

    einheit = (data.einheit or "").strip()
    if einheit:
        if ist_grundstueck(o):
            raise HTTPException(400, "Ein Grundstück hat keine Einheiten — "
                                     "der Anteil hängt am ganzen Objekt.")
        namen = {e.bezeichnung.strip() for e in session.exec(
            select(Einheit).where(Einheit.objekt_id == o.id)).all()}
        if einheit not in namen:
            raise HTTPException(404, f"„{einheit}“ ist keine Einheit dieses Objekts")

    vorhanden = session.exec(
        select(Anteil).where(Anteil.objekt_id == o.id,
                             Anteil.eigentuemer_id == data.eigentuemer_id,
                             Anteil.einheit == einheit)).first()

    # CCCVIII — mehr als das Ganze lässt sich nicht verteilen. Die Summe je
    # Ebene (ganzes Objekt oder eine Einheit) bleibt bei höchstens 1000 ‰; der
    # eigene bisherige Anteil zählt beim Ändern nicht doppelt mit.
    schon = runde(sum(promille_von(a) for a in session.exec(
        select(Anteil).where(Anteil.objekt_id == o.id,
                             Anteil.einheit == einheit)).all()
        if not (vorhanden and a.id == vorhanden.id)))
    if runde(schon + wert) > VOLL:
        frei = runde(VOLL - schon)
        wo = f"an „{einheit}“" if einheit else "am Objekt"
        raise HTTPException(400, (
            f"{wo} sind bereits {schon:.10g} ‰ von 1000 ‰ vergeben — "
            + (f"frei sind noch {frei:.10g} ‰."
               if frei > 0 else
               "es ist nichts mehr frei. Bitte zuerst einen bestehenden "
               "Anteil löschen oder verkleinern, dann neu zuordnen.")))
    eintrag = vorhanden or Anteil(objekt_id=o.id,
                                  eigentuemer_id=data.eigentuemer_id,
                                  einheit=einheit)
    eintrag.einheit = einheit
    eintrag.promille = wert
    # Gerundet mitgefuehrt, damit Leser, die noch `tausendstel` erwarten,
    # weiterhin eine sinnvolle Zahl sehen.
    eintrag.tausendstel = int(round(wert))
    eintrag.rolle = rolle_von(wert)
    # Nur schreiben, was mitgeschickt wurde: das Zuweisen-Fenster auf der
    # Eigentümerseite sendet bloß Eigner und Promille — es darf eine gepflegte
    # Notiz nicht stillschweigend leeren (Fund N118).
    if data.notiz is not None:
        eintrag.notiz = data.notiz
    session.add(eintrag)
    session.commit()
    session.refresh(eintrag)
    return {"id": eintrag.id, "promille": eintrag.promille,
            "einheit": eintrag.einheit, "rolle": eintrag.rolle}


@router.delete("/anteile/{aid}")
def anteil_loeschen(aid: int, session: Session = Depends(get_session)) -> dict:
    a = session.get(Anteil, aid)
    if not a:
        raise HTTPException(404, "Anteil nicht gefunden")
    session.delete(a)
    session.commit()
    return {"ok": True}


@router.get("/vermoegen")
def uebersicht(session: Session = Depends(get_session)) -> dict:
    """Wert, Restschuld und Eigenkapital je Objekt und in Summe.

    Die Jahresstände werden in einem Zug geladen und je Kredit zugeordnet —
    nicht je Kredit einzeln nachgeschlagen. Ohne sie nannte diese Übersicht
    den roh eingetragenen Wert, während die Objektseite den fortgeschriebenen
    zeigte: zwei Zahlen für dieselbe Restschuld."""
    kredite = session.exec(select(Kredit)).all()
    anteile_alle = session.exec(select(Anteil)).all()
    staende: dict[int, list[Kreditstand]] = {}
    for s in session.exec(select(Kreditstand)).all():
        staende.setdefault(s.kredit_id, []).append(s)
    zeilen = [
        objekt_vermoegen(o,
                         [k for k in kredite if k.objekt_id == o.id],
                         [a for a in anteile_alle if a.objekt_id == o.id],
                         staende=staende)
        for o in session.exec(select(Objekt)).all() if o.aktiv
    ]
    zeilen.sort(key=lambda z: -(z["wert"] or 0))
    return {"objekte": zeilen, "gesamt": gesamt(zeilen)}


# --------------------------------------------------------------------------
# CLXII — Auswertung je Eigentümer
#
# Gehört einem nur Wohnung 2, darf in seiner Übersicht nicht die Miete des
# ganzen Hauses stehen. Wert und Restschuld werden nach dem wertgewichteten
# Anteil zugerechnet (`eigentuemer_fraktion`), die Miete dagegen konkret aus
# den Einheiten, die dem Eigentümer gehören — eine Miete ist kein Bruchteil
# eines Objektwerts, sondern der Ertrag genau dieser Wohnung.
# --------------------------------------------------------------------------

def _laufende_miete_jahr(mieten: list[Miete], heute: date) -> float:
    """Jahres-Kaltmiete (inkl. Stellplatz/Sonstiges) der heute laufenden
    Mietverhältnisse — geplante zählen noch nicht, beendete nicht mehr."""
    return round(sum(
        jahresbetrag(m.kaltmiete + m.stellplatz + m.sonstige, m.turnus)
        for m in mieten
        if m.ab_datum <= heute and (m.bis_datum is None or m.bis_datum >= heute)), 2)


def _einheit_von(m: Miete, einheiten: list[Einheit]) -> str:
    """Auf welche Einheit ein Mietverhältnis zeigt — ohne Angabe bei genau
    einer Einheit auf diese (wie `verteilung.bezuege`)."""
    b = (m.einheit or "").strip()
    if b:
        return b
    return einheiten[0].bezeichnung.strip() if len(einheiten) == 1 else ""


def _objektkopf(o: Objekt) -> dict:
    """Die Angaben, mit denen die Oberfläche eine Objektzeile beschriftet.

    Dieselben Felder wie in `/eigentuemer` — damit eine Zeile, die es dort nicht
    gibt (Objekt ohne Gebäudeanteil, aber mit Anteil an der PV-Anlage, N146),
    genauso dargestellt werden kann wie jede andere."""
    return {"slug": o.slug, "name": o.name, "titel": objekt_titel(o),
            "typ": o.typ, "objektart": objektart_von(o),
            "strasse": o.strasse, "plz": o.plz, "ort": o.ort,
            "flurstueck": o.flurstueck, "gemarkung": o.gemarkung}


def _objekt_je_eigentuemer(o: Objekt, einheiten: list[Einheit],
                           anteile: list[Anteil], kredite: list[Kredit],
                           mieten: list[Miete],
                           staende: dict[int, list[Kreditstand]],
                           heute: date,
                           anlage: PVAnlage | None = None,
                           personen: dict[int, str] | None = None) -> dict[int, dict]:
    """Zurechnung eines Objekts je Eigentümer-id.

    Wert und Restschuld folgen dem wertgewichteten Anteil; die Miete wird je
    Einheit zugeordnet und mit dem Anteil des Eigentümers an genau dieser
    Einheit gewichtet.

    N146: hängt am Objekt eine PV-Anlage, kommt sie als untergeordnete Zeile
    dazu — mit ihren eigenen Anteilen. Ohne Anlage (`anlage=None`) ändert sich
    an keiner Zahl etwas."""
    fraktion = eigentuemer_fraktion(o, einheiten, anteile)
    wert = attributionswert(o, einheiten)
    lagen = [kreditstand(k, staende.get(getattr(k, "id", None)), heute)
             for k in kredite]
    restschuld = round(sum(l["restschuld"] for l in lagen), 2)
    guthaben = round(sum(l["guthaben"] for l in lagen), 2)
    eigenkapital = (round((wert or 0) - restschuld + guthaben, 2)
                    if wert is not None else None)

    # Anteil je Eigentümer an einer Einheit: eigener Einheit-Anteil, sonst der
    # Objekt-Anteil (der „Rest").
    objektanteile = [a for a in anteile if _ist_objektanteil(a)]
    je_einheit: dict[str, list[Anteil]] = {}
    for a in anteile:
        b = (getattr(a, "einheit", "") or "").strip()
        if b:
            je_einheit.setdefault(b, []).append(a)

    def anteil_an(bezeichnung: str) -> list[Anteil]:
        return je_einheit.get(bezeichnung.strip()) or objektanteile

    # Miete je Einheit (heute laufend)
    miete_je_einheit: dict[str, float] = {}
    for e in einheiten:
        eigene = [m for m in mieten
                  if _einheit_von(m, einheiten) == e.bezeichnung.strip()]
        miete_je_einheit[e.bezeichnung.strip()] = _laufende_miete_jahr(eigene, heute)
    # Mieten ohne Einheit (ganzes Objekt / Grundstück) — dem Objekt-Anteil.
    zugeordnet = {e.bezeichnung.strip() for e in einheiten}
    lose = [m for m in mieten if _einheit_von(m, einheiten) not in zugeordnet]
    miete_ohne_einheit = _laufende_miete_jahr(lose, heute)

    def zeile(f: float) -> dict:
        """Eine Objektzeile zum Bruchteil `f`. Die PV-Felder stehen von Anfang
        an drin — ohne Anlage bleiben sie leer, und `wert_gesamt` ist dann
        exakt der Immobilienwert."""
        w = round((wert or 0) * f, 2) if wert is not None else None
        ek = round(eigenkapital * f, 2) if eigenkapital is not None else None
        return {**_objektkopf(o),
                "fraktion": round(f, 4),
                "wert": w,
                "restschuld": round(restschuld * f, 2),
                "guthaben": round(guthaben * f, 2),
                "eigenkapital": ek,
                # N146 — die PV-Anlage steht neben dem Immobilienwert, nicht
                # darin: `wert`/`eigenkapital` tragen weiter die Beleihung.
                "pv": None, "pv_wert": 0.0,
                "wert_gesamt": w, "eigenkapital_gesamt": ek,
                "miete_jahr": 0.0, "einheiten": []}

    out: dict[int, dict] = {}
    for eid, f in fraktion.items():
        out.setdefault(eid, zeile(f))

    def miete_zuweisen(betrag: float, zeilen: list[Anteil],
                       einheit_name: str | None) -> None:
        for a in zeilen:
            eid = a.eigentuemer_id
            if eid not in out:
                continue
            anteil_betrag = round(betrag * promille_von(a) / 1000, 2)
            out[eid]["miete_jahr"] = round(out[eid]["miete_jahr"] + anteil_betrag, 2)
            if einheit_name:
                out[eid]["einheiten"].append({
                    "bezeichnung": einheit_name,
                    "promille": runde(promille_von(a)),
                    "miete_jahr": anteil_betrag})

    for e in einheiten:
        b = e.bezeichnung.strip()
        miete_zuweisen(miete_je_einheit.get(b, 0.0), anteil_an(b), e.bezeichnung)
    if miete_ohne_einheit:
        miete_zuweisen(miete_ohne_einheit, objektanteile, None)

    _pv_anhaengen(o, out, anlage, personen or {})
    return out


def _pv_anhaengen(o: Objekt, out: dict[int, dict], anlage: PVAnlage | None,
                  personen: dict[int, str]) -> None:
    """N146 — die PV-Anlage unter ihre Immobilie hängen.

    Der auf eine Person entfallende Anlagenwert erhöht `wert_gesamt` und
    `eigenkapital_gesamt` dieser Objektzeile — **nicht** `wert`: der bleibt der
    reine Immobilienwert und damit die Basis für Beleihung und Spielraum.

    Wem die Anlage gehört, muss nicht das Haus gehören. Für eine solche Person
    entsteht die Objektzeile hier — mit Bruchteil 0, denn am Gebäude hält sie
    nichts. Ohne diese Zeile verschwände ihr Anteil an der Anlage."""
    pv = pv_zurechnung(anlage, personen)
    if not pv:
        return
    for eid, teil in pv["je_person"].items():
        if eid not in out:
            out[eid] = {**_objektkopf(o), "fraktion": 0.0, "wert": 0.0,
                        "restschuld": 0.0, "guthaben": 0.0, "eigenkapital": 0.0,
                        "pv": None, "pv_wert": 0.0,
                        "wert_gesamt": 0.0, "eigenkapital_gesamt": 0.0,
                        "miete_jahr": 0.0, "einheiten": []}
        z = out[eid]
        z["pv"] = {"titel": pv["titel"], "promille": teil["promille"],
                   "wert": teil["wert"], "wert_gesamt": pv["wert"],
                   "wertquelle": pv["wertquelle"], "kwp": pv["kwp"],
                   "anteile_summe": pv["anteile_summe"],
                   "hinweise": pv["hinweise"]}
        z["pv_wert"] = teil["wert"]
        z["wert_gesamt"] = round((z["wert"] or 0) + teil["wert"], 2)
        z["eigenkapital_gesamt"] = (
            round(z["eigenkapital"] + teil["wert"], 2)
            if z["eigenkapital"] is not None else teil["wert"])


@router.get("/eigentuemer/uebersicht", response_model=None)
def eigentuemer_uebersicht(session: Session = Depends(get_session)) -> dict:
    """Vermögen und Miete je Eigentümer — auf seine Einheiten eingeschränkt.

    Für die Eigentümerseite: jede Person mit dem, was ihr tatsächlich zugerechnet
    wird, nicht mit den Zahlen des ganzen Hauses. Die Gesamtsicht (`/vermoegen`)
    bleibt davon unberührt."""
    heute = date.today()
    eigner = {e.id: e for e in session.exec(select(Eigentuemer)).all()}
    objekte = {o.id: o for o in session.exec(select(Objekt)).all() if o.aktiv}
    anteile_alle = session.exec(select(Anteil)).all()
    kredite = session.exec(select(Kredit)).all()
    mieten_alle = session.exec(select(Miete)).all()
    einheiten_alle: dict[int, list[Einheit]] = {}
    for e in session.exec(select(Einheit)).all():
        einheiten_alle.setdefault(e.objekt_id, []).append(e)
    staende: dict[int, list[Kreditstand]] = {}
    for s in session.exec(select(Kreditstand)).all():
        staende.setdefault(s.kredit_id, []).append(s)
    # N146 — die PV-Anlagen je Objekt (höchstens eine). Nur gelesen.
    anlagen = {a.objekt_id: a for a in session.exec(select(PVAnlage)).all()}
    personen = {eid: e.name for eid, e in eigner.items()}

    # eid -> Liste der Objektzeilen
    je_eigner: dict[int, list[dict]] = {eid: [] for eid in eigner}
    for oid, o in objekte.items():
        zurechnung = _objekt_je_eigentuemer(
            o, einheiten_alle.get(oid, []),
            [a for a in anteile_alle if a.objekt_id == oid],
            [k for k in kredite if k.objekt_id == oid],
            [m for m in mieten_alle if m.objekt_id == oid],
            staende, heute, anlagen.get(oid), personen)
        for eid, zeile in zurechnung.items():
            if eid in je_eigner:
                je_eigner[eid].append(zeile)

    def summe(zeilen: list[dict], feld: str) -> float:
        return round(sum(z[feld] or 0 for z in zeilen), 2)

    out = []
    for eid, e in eigner.items():
        zeilen = sorted(je_eigner[eid], key=lambda z: -(z["wert_gesamt"] or 0))
        wert_bekannt = any(z["wert"] is not None for z in zeilen)
        wert = summe(zeilen, "wert") if wert_bekannt else None
        eigenkapital = summe(zeilen, "eigenkapital") if wert_bekannt else None
        # N146 — der Anlagenanteil summiert sich neben dem Immobilienwert.
        # `wert`/`eigenkapital` bleiben die Immobilie allein: an ihnen hängen
        # Beleihungsquote und Investitionsspielraum, und eine PV-Anlage ist
        # nichts, was eine Bank beleiht.
        pv_wert = summe(zeilen, "pv_wert")
        out.append({
            "id": eid, "name": e.name,
            "objekte": zeilen,
            "gesamt": {
                "objekte": len(zeilen),
                "wert": wert,
                "restschuld": summe(zeilen, "restschuld"),
                "guthaben": summe(zeilen, "guthaben"),
                "eigenkapital": eigenkapital,
                "miete_jahr": summe(zeilen, "miete_jahr"),
                "pv_wert": pv_wert,
                "wert_gesamt": (round((wert or 0) + pv_wert, 2)
                                if wert_bekannt or pv_wert else None),
                "eigenkapital_gesamt": (round((eigenkapital or 0) + pv_wert, 2)
                                        if wert_bekannt or pv_wert else None),
            },
        })
    return {"eigentuemer": out}


# --------------------------------------------------------------------------
# CCXXIX — Grundschulden. Eine Grundschuld belastet ein Objekt, sichert aber
# über die Verknüpfungstabelle einen oder mehrere Kredite — auch Kredite an
# anderen Objekten (Cross-Collateral). Additiv: ohne Eintrag ändert sich nichts.
# --------------------------------------------------------------------------
class GrundschuldIn(BaseModel):
    betrag: float | None = None
    rang: str = ""
    grundbuch_blatt: str = ""
    glaeubiger: str = ""
    brief: bool = False
    notiz: str = ""
    # None: Verknüpfung unangetastet lassen; eine (auch leere) Liste: neu setzen.
    kredit_ids: list[int] | None = None


def _grundschuld_dict(session: Session, g: Grundschuld) -> dict:
    kredit_ids = [v.kredit_id for v in session.exec(
        select(GrundschuldKredit).where(
            GrundschuldKredit.grundschuld_id == g.id)).all()]
    return {**g.model_dump(), "kredit_ids": kredit_ids}


def _setze_kredite(session: Session, gid: int, kredit_ids: list[int]) -> None:
    """Die gesicherten Kredite neu verknüpfen: alte Zuordnung weg, gewünschte
    anlegen. Unbekannte oder doppelte IDs werden still übergangen."""
    for v in session.exec(select(GrundschuldKredit).where(
            GrundschuldKredit.grundschuld_id == gid)).all():
        session.delete(v)
    gesehen: set[int] = set()
    for kid in kredit_ids:
        if kid in gesehen or not session.get(Kredit, kid):
            continue
        gesehen.add(kid)
        session.add(GrundschuldKredit(grundschuld_id=gid, kredit_id=kid))


@router.get("/grundschulden/kredit-auswahl", response_model=None)
def grundschuld_kredit_auswahl(session: Session = Depends(get_session)) -> list:
    """Alle Kredite über alle Objekte — die Auswahl, welche eine Grundschuld
    sichert. Eine Grundschuld kann einen Kredit an einem anderen Objekt decken,
    darum objektübergreifend."""
    objekte = {o.id: o for o in session.exec(select(Objekt)).all()}
    reihe = session.exec(select(Kredit)).all()
    return [{"id": k.id, "bezeichnung": k.bezeichnung, "bank": k.bank,
             "objekt": (objekte.get(k.objekt_id).name
                        if objekte.get(k.objekt_id) else "")}
            for k in reihe]


@router.get("/objekte/{slug}/grundschulden", response_model=None)
def grundschulden(slug: str, session: Session = Depends(get_session),
                  o: Objekt = Depends(objekt_holen)) -> list:
    reihe = session.exec(select(Grundschuld)
                         .where(Grundschuld.objekt_id == o.id)).all()
    return [_grundschuld_dict(session, g) for g in reihe]


@router.post("/objekte/{slug}/grundschulden", status_code=201)
def grundschuld_anlegen(slug: str, data: GrundschuldIn,
                        session: Session = Depends(get_session),
                        o: Objekt = Depends(objekt_holen)) -> dict:
    if data.betrag is not None and data.betrag < 0:
        raise HTTPException(400, "Der Betrag einer Grundschuld ist nie negativ")
    g = Grundschuld(objekt_id=o.id, betrag=data.betrag, rang=data.rang,
                    grundbuch_blatt=data.grundbuch_blatt,
                    glaeubiger=data.glaeubiger, brief=data.brief, notiz=data.notiz)
    session.add(g)
    session.commit()
    session.refresh(g)
    _setze_kredite(session, g.id, data.kredit_ids or [])
    session.commit()
    return _grundschuld_dict(session, g)


@router.patch("/grundschulden/{gid}")
def grundschuld_aendern(gid: int, data: GrundschuldIn,
                        session: Session = Depends(get_session)) -> dict:
    g = session.get(Grundschuld, gid)
    if not g:
        raise HTTPException(404, "Grundschuld nicht gefunden")
    if data.betrag is not None and data.betrag < 0:
        raise HTTPException(400, "Der Betrag einer Grundschuld ist nie negativ")
    # N370 — PATCH ändert, was mitkommt; alles andere bleibt stehen. Vorher
    # wurde jedes Feld bedingungslos kopiert, und weil `GrundschuldIn` für
    # jedes einen Default hat, war ein `PATCH {"betrag": 120000}` in Wahrheit
    # ein PUT: Rang, Grundbuchblatt, Gläubiger und Notiz standen danach leer,
    # `brief` auf False. Die Oberfläche schickt zufällig alle Felder mit —
    # jeder andere Aufrufer verlor die gepflegten Grundbuchdaten stillschweigend.
    for feld in ("betrag", "rang", "grundbuch_blatt", "glaeubiger",
                 "brief", "notiz"):
        if feld in data.model_fields_set:
            setattr(g, feld, getattr(data, feld))
    session.add(g)
    if data.kredit_ids is not None:
        _setze_kredite(session, gid, data.kredit_ids)
    session.commit()
    session.refresh(g)
    return _grundschuld_dict(session, g)


@router.delete("/grundschulden/{gid}")
def grundschuld_loeschen(gid: int,
                         session: Session = Depends(get_session)) -> dict:
    g = session.get(Grundschuld, gid)
    if not g:
        raise HTTPException(404, "Grundschuld nicht gefunden")
    for v in session.exec(select(GrundschuldKredit).where(
            GrundschuldKredit.grundschuld_id == gid)).all():
        session.delete(v)
    session.delete(g)
    session.commit()
    return {"ok": True}
