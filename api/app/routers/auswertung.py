"""Auswertung über alle Objekte: Einnahmen gegen Ausgaben, Kostenblöcke,
Mietverlauf.

Zwei Sichten, die nicht vermischt werden dürfen:

  mieter       Was auf die Mieter umgelegt wird — die umlagefähigen
               Kostenpositionen, je Kostenart. Speist die Nebenkostenseite.
  eigentuemer  Was der Eigentümer selbst trägt — Kredit, Versicherung, Steuer,
               Instandhaltung, Sonstiges. Speist die Wertentwicklung.

Jeder Betrag steckt in genau einer der beiden Sichten; zusammen ergeben sie
dieselbe Summe wie die gewachsene Aufteilung `gesamt`, die für Bestandsaufrufe
unverändert bleibt."""
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from fastapi import HTTPException
from sqlmodel import Session as DBSession

from ..cashflow import EinheitZahlen, cashflow, monate_im_jahr, sankey
from ..turnus import jahresbetrag
from ..vermoegen import kapitaldienst_jahr
from ..db import get_session
from ..models import (Einheit, Kostenart, Kostenposition, Kredit, Miete, Objekt,
                      Versicherung, Zahlung, Zeitraum, ist_grundstueck)

router = APIRouter(prefix="/api/auswertung", tags=["auswertung"])

BLOCK_NAMEN = ["Kredit", "Versicherung", "Steuer", "Nebenkosten", "Sonstiges"]
EIGENTUEMER_NAMEN = ["Kredit", "Versicherung", "Steuer", "Instandhaltung", "Sonstiges"]

# Der Kostenfluss der Mietersicht speist sich nicht aus der Miete, sondern aus
# den Vorauszahlungen. Die Knoten kommen aus cashflow.sankey und heißen dort
# nach der Eigentümersicht — hier tragen sie den Namen der Mietersicht.
# „Fehlbetrag“ ist in dieser Sicht die Nachzahlung: was der Mieter über seine
# Vorauszahlungen hinaus schuldet, und damit die Quelle, die den Fluss schliesst.
MIETER_KNOTEN = {"Einnahmen": "Vorauszahlungen", "Überschuss": "Guthaben",
                 "Fehlbetrag": "Nachzahlung"}


def _sichtname(sicht: str | None) -> str:
    """Angeforderte Sicht auf einen bekannten Namen bringen.

    Alles Unbekannte fällt auf die gewachsene Aufteilung zurück — ein Tippfehler
    im Aufruf soll eine Auswertung nicht mit einem Fehler beenden."""
    return sicht if sicht in ("mieter", "eigentuemer") else "gesamt"


def _mietwort(o: Objekt) -> str:
    """Wie das Entgelt bei diesem Objekt heisst.

    Ein Grundstück wird verpachtet, nicht vermietet. Geführt wird beides über
    dasselbe `Miete`-Modell — die Rechnung ist dieselbe, nur das Wort nicht.
    Die Auswertung gibt es mit, damit die Oberfläche nicht am Objekttyp
    herumraten muss."""
    return "Pacht" if ist_grundstueck(o) else "Miete"


def _monate_im_jahr(m: Miete, jahr: int) -> float:
    """Wie viele Monate des Jahres war dieser Mietstand gültig? (taggenau)"""
    return monate_im_jahr(m.ab_datum, m.bis_datum, jahr)


def _monatlich(betrag: float | None, turnus: str | None) -> float:
    """Ein Betrag je Turnus als Monatswert.

    Die Kennzahlen der Einheiten (Kaltmiete, €/m²) sind Monatsgrößen; im
    Datensatz steht der Betrag aber je Turnus. Ohne diese Umrechnung wies eine
    vierteljährlich gezahlte Miete den dreifachen €/m² aus."""
    return round(jahresbetrag(betrag, turnus) / 12, 2)


def _mittel_im_jahr(m: Miete, jahr: int, mittel: str = "miete") -> float:
    """Jahresbetrag eines Mieteintrags — Turnus und Laufzeit berücksichtigt.

    `mittel` wählt, worum es geht: die Miete (Eigentümersicht) oder die
    Nebenkosten-Vorauszahlung (Mietersicht). Beide folgen derselben taggenauen
    Laufzeit, sonst hätte ein Mieterwechsel zwei unterschiedliche Jahre."""
    betrag = (m.nebenkosten_vz if mittel == "vorauszahlung"
              else m.kaltmiete + m.stellplatz + m.sonstige)
    return jahresbetrag(betrag, m.turnus) * _monate_im_jahr(m, jahr) / 12


def _miete_im_jahr(m: Miete, jahr: int) -> float:
    """Mieteinnahmen eines Eintrags im Jahr."""
    return _mittel_im_jahr(m, jahr)


def _positionen(session: DBSession, o: Objekt,
                jahr: int) -> list[tuple[str, float, bool]]:
    """Erledigte Kostenpositionen des Jahres: Kostenart, Betrag, umlagefähig.

    Ob eine Position auf die Mieter umgelegt wird, steht am Katalogeintrag der
    Kostenart. Fehlt er, gilt die Vorgabe des Datenmodells: umlagefähig."""
    umlage = {k.name.strip().lower(): k.umlagefaehig for k in session.exec(
        select(Kostenart).where(Kostenart.objekt_id == o.id)).all()}

    posten: list[tuple[str, float, bool]] = []
    for z in session.exec(select(Zeitraum).where(Zeitraum.objekt_id == o.id)).all():
        if z.ende.year != jahr:
            continue
        for p in session.exec(
                select(Kostenposition).where(Kostenposition.zeitraum_id == z.id)).all():
            if p.status != "erledigt":
                continue
            posten.append((p.kostenart, p.betrag,
                           umlage.get(p.kostenart.strip().lower(), True)))
    return posten


def _zahlungsblock(kategorie: str) -> str:
    """Eine Zahlung dem Eigentümerblock zuordnen, dem sie sachlich gehört."""
    passend = {"steuer": "Steuer", "instandhaltung": "Instandhaltung",
               "kredit": "Kredit"}
    return passend.get((kategorie or "").strip().lower(), "Sonstiges")


def _sichten(session: DBSession, o: Objekt, jahr: int) -> dict[str, dict[str, float]]:
    """Jahreskosten eines Objekts in allen drei Zuschnitten.

    Ein Durchgang für alle drei, damit dieselben Datensätze nicht dreimal
    gelesen werden. `gesamt` bleibt exakt die gewachsene Aufteilung."""
    kredite = session.exec(select(Kredit).where(Kredit.objekt_id == o.id)).all()
    vers = session.exec(select(Versicherung).where(Versicherung.objekt_id == o.id)).all()
    zahlungen = session.exec(
        select(Zahlung).where(Zahlung.objekt_id == o.id, Zahlung.jahr == jahr)).all()
    posten = _positionen(session, o, jahr)

    # Ohne Sparraten: was in einen Bausparvertrag fliesst, ist keine Ausgabe,
    # sondern eine Umschichtung in eigenes Vermögen (CXLIX). Sie hier
    # mitzuzählen machte den Cashflow schlechter, als er ist.
    kredit = kapitaldienst_jahr(kredite)
    versicherung = round(sum(jahresbetrag(v.jahresbeitrag, v.turnus) for v in vers), 2)

    # Mietersicht: nur die umlagefähigen Positionen, aufgeschlüsselt nach
    # Kostenart — „Nebenkosten“ als eine Zahl sagt dem Mieter nichts.
    mieter: dict[str, float] = {}
    for art, betrag, umlagefaehig in posten:
        if umlagefaehig:
            mieter[art] = round(mieter.get(art, 0.0) + betrag, 2)

    # Eigentümersicht: alles Übrige. Nicht umlagefähige Positionen sind der
    # Sache nach Instandhaltung und landen im selben Block wie die Zahlungen.
    eigentuemer = {n: 0.0 for n in EIGENTUEMER_NAMEN}
    eigentuemer["Kredit"] = kredit
    eigentuemer["Versicherung"] = versicherung
    eigentuemer["Instandhaltung"] = round(
        sum(b for _, b, umlagefaehig in posten if not umlagefaehig), 2)
    for z in zahlungen:
        block = _zahlungsblock(z.kategorie)
        eigentuemer[block] = round(
            eigentuemer[block] + jahresbetrag(z.betrag, z.turnus), 2)

    return {
        "gesamt": {
            "Kredit": kredit,
            "Versicherung": versicherung,
            "Steuer": round(sum(jahresbetrag(z.betrag, z.turnus) for z in zahlungen
                                if z.kategorie == "Steuer"), 2),
            "Nebenkosten": round(sum(b for _, b, _u in posten), 2),
            "Sonstiges": round(sum(jahresbetrag(z.betrag, z.turnus) for z in zahlungen
                                   if z.kategorie != "Steuer"), 2),
        },
        "mieter": mieter,
        "eigentuemer": eigentuemer,
    }


def _bloecke(session: DBSession, o: Objekt, jahr: int,
             sicht: str | None = None) -> dict[str, float]:
    """Kostenblöcke eines Objekts in der gewünschten Sicht."""
    return _sichten(session, o, jahr)[_sichtname(sicht)]


def _umlagearten(session: DBSession, objekte: list[Objekt]) -> list[str]:
    """Umlagefähige Kostenarten der Objekte — die Filterschalter der Mietersicht.

    Bewusst aus dem Katalog und nicht aus den Positionen des Jahres: sonst
    verschwänden die Schalter, sobald ein Jahr noch keine Belege hat."""
    namen = set()
    for o in objekte:
        for k in session.exec(select(Kostenart).where(Kostenart.objekt_id == o.id)).all():
            if k.aktiv and k.umlagefaehig:
                namen.add(k.name)
    return sorted(namen)


def _einheiten_zahlen(session: DBSession, o: Objekt, jahr: int,
                      mittel: str = "miete") -> list[EinheitZahlen]:
    """Einheiten mit ihren Einnahmen im gewählten Jahr.

    `mittel='vorauszahlung'` setzt statt der Miete die Nebenkosten-Voraus-
    zahlung als Einnahme — dieselbe Zuordnung Einheit ↔ Mietstand, nur die
    Mietersicht darauf."""
    einheiten = session.exec(select(Einheit).where(Einheit.objekt_id == o.id)).all()
    mieten = session.exec(select(Miete).where(Miete.objekt_id == o.id)).all()

    zahlen = []
    for e in einheiten:
        passend = [m for m in mieten
                   if (m.einheit or "").strip().lower() == e.bezeichnung.strip().lower()
                   and _monate_im_jahr(m, jahr) > 0]
        # jüngster gültiger Mietstand zählt für die Kennzahlen
        aktuell = max(passend, key=lambda m: m.ab_datum, default=None)
        monatlich = sum(_mittel_im_jahr(m, jahr, mittel) for m in passend) / 12 \
            if passend else 0.0
        zahlen.append(EinheitZahlen(
            bezeichnung=e.bezeichnung, nutzungsart=e.nutzungsart,
            flaeche=e.flaeche, terrasse=e.terrasse, nebenflaeche=e.nebenflaeche,
            einnahmen_monat=monatlich,
            kaltmiete=_monatlich(aktuell.kaltmiete, aktuell.turnus) if aktuell else 0.0,
            stellplatz=_monatlich(aktuell.stellplatz, aktuell.turnus) if aktuell else 0.0,
            sonstige=_monatlich(aktuell.sonstige, aktuell.turnus) if aktuell else 0.0,
            nebenkosten_vz=_monatlich(aktuell.nebenkosten_vz, aktuell.turnus)
            if aktuell else 0.0,
            partei=aktuell.partei if aktuell else "",
        ))

    # Mieten ohne passende Einheit (z.B. ganzes Objekt vermietet) nicht verlieren.
    # Ein Grundstück hat gar keine Einheiten — sein Pachtverhältnis läuft immer
    # über diesen Weg. Deshalb steht hier seine Nutzungsart (Ackerland, Wald …)
    # statt der Objektnutzung: „Wohnen“ an einem Acker wäre schlicht falsch.
    zugeordnet = {e.bezeichnung.strip().lower() for e in einheiten}
    lose = [m for m in mieten
            if (m.einheit or "").strip().lower() not in zugeordnet
            and _monate_im_jahr(m, jahr) > 0]
    grundstueck = ist_grundstueck(o)
    for m in lose:
        zahlen.append(EinheitZahlen(
            bezeichnung=m.einheit or m.partei
            or ("Gesamtgrundstück" if grundstueck else "Gesamtobjekt"),
            nutzungsart=(o.grundstueck_nutzungsart or o.nutzung) if grundstueck
            else o.nutzung,
            flaeche=None, terrasse=None, nebenflaeche=None,
            einnahmen_monat=_mittel_im_jahr(m, jahr, mittel) / 12,
            kaltmiete=_monatlich(m.kaltmiete, m.turnus),
            stellplatz=_monatlich(m.stellplatz, m.turnus),
            sonstige=_monatlich(m.sonstige, m.turnus),
            nebenkosten_vz=_monatlich(m.nebenkosten_vz, m.turnus), partei=m.partei,
        ))
    return zahlen


def _vz_quellen(session: DBSession, o: Objekt, jahr: int) -> list[dict]:
    """Nebenkosten-Vorauszahlungen je Einheit — die Mittel der Mietersicht.

    Der Schlüssel heißt `einnahmen_jahr`, weil `cashflow.sankey` seine Quellen
    so liest; inhaltlich sind es die Vorauszahlungen."""
    return [{"bezeichnung": e.bezeichnung, "einnahmen_jahr": e.einnahmen_jahr}
            for e in _einheiten_zahlen(session, o, jahr, "vorauszahlung")]


def _gefiltert(bloecke: dict[str, float], kategorien: str | None) -> dict[str, float]:
    """Auf die gewählten Kostenarten eindampfen; ohne Angabe bleibt alles."""
    if not kategorien:
        return bloecke
    gewaehlt = {k.strip().lower() for k in kategorien.split(",") if k.strip()}
    return {n: b for n, b in bloecke.items() if n.lower() in gewaehlt}


def _summe(bloecke: dict[str, float]) -> float:
    return round(sum(bloecke.values()), 2)


def _dazu(summen: dict[str, float], bloecke: dict[str, float]) -> None:
    """Kostenblöcke eines Objekts auf die Gesamtsumme addieren."""
    for name, betrag in bloecke.items():
        summen[name] = round(summen.get(name, 0.0) + betrag, 2)


@router.get("")
def auswertung(jahr: int = Query(default=None),
               objekt: str = Query(default=None),
               kategorien: str = Query(default=None),
               sicht: str = Query(default=None),
               session: Session = Depends(get_session)) -> dict:
    """Einnahmen gegen Ausgaben je Objekt.

    `sicht` schneidet die Kostenblöcke zu: 'mieter' zeigt nur die umlage-
    fähigen Kosten, 'eigentuemer' nur die selbst getragenen. Ohne Angabe
    bleibt die gewachsene Aufteilung. Unabhängig davon trägt jede Zeile beide
    Sichten vollständig mit — so lässt sich die Trennung zeigen, ohne ein
    zweites Mal zu fragen."""
    jahr = jahr or date.today().year
    objekte = session.exec(select(Objekt)).all()
    if objekt:
        objekte = [o for o in objekte if o.slug == objekt]

    zeilen: list[dict] = []
    kostenbloecke: dict[str, float] = {}
    mieter_gesamt: dict[str, float] = {}
    eigentuemer_gesamt: dict[str, float] = {}

    for o in objekte:
        mieten = session.exec(select(Miete).where(Miete.objekt_id == o.id)).all()
        einnahmen = sum(_miete_im_jahr(m, jahr) for m in mieten)
        sichten = _sichten(session, o, jahr)
        bloecke = _gefiltert(
            sichten[_sichtname(sicht)],
            kategorien)
        ausgaben = sum(bloecke.values())
        vz = sum(q["einnahmen_jahr"] for q in _vz_quellen(session, o, jahr))

        zeilen.append({
            "slug": o.slug, "name": o.name, "typ": o.typ,
            "mietwort": _mietwort(o),
            "einnahmen": round(einnahmen, 2),
            "ausgaben": round(ausgaben, 2),
            "saldo": round(einnahmen - ausgaben, 2),
            "bloecke": bloecke,
            "vorauszahlungen": round(vz, 2),
            "mieter": {"bloecke": sichten["mieter"],
                       "summe": _summe(sichten["mieter"])},
            "eigentuemer": {"bloecke": sichten["eigentuemer"],
                            "summe": _summe(sichten["eigentuemer"])},
        })
        _dazu(kostenbloecke, bloecke)
        _dazu(mieter_gesamt, sichten["mieter"])
        _dazu(eigentuemer_gesamt, sichten["eigentuemer"])

    return {
        "jahr": jahr,
        "sicht": _sichtname(sicht),
        "objekte": zeilen,
        "kostenbloecke": kostenbloecke,
        "kategorien": BLOCK_NAMEN,
        "mieter_kategorien": _umlagearten(session, objekte),
        "eigentuemer_kategorien": EIGENTUEMER_NAMEN,
        "mieter": {"bloecke": mieter_gesamt, "summe": _summe(mieter_gesamt)},
        "eigentuemer": {"bloecke": eigentuemer_gesamt,
                        "summe": _summe(eigentuemer_gesamt)},
        "gesamt": {
            "einnahmen": round(sum(z["einnahmen"] for z in zeilen), 2),
            "ausgaben": round(sum(z["ausgaben"] for z in zeilen), 2),
            "saldo": round(sum(z["saldo"] for z in zeilen), 2),
            "vorauszahlungen": round(sum(z["vorauszahlungen"] for z in zeilen), 2),
        },
    }


@router.get("/cashflow")
def cashflow_endpoint(objekt: str = Query(...), jahr: int = Query(default=None),
                      kategorien: str = Query(default=None),
                      sicht: str = Query(default=None),
                      session: Session = Depends(get_session)) -> dict:
    """Einnahmen, Kosten und €/m² je Einheit — plus Fluss fürs Sankey.

    Mit `sicht=eigentuemer` trägt jede Einheit nur ihren Anteil an den Kosten
    des Eigentümers; die umlagefähigen Nebenkosten bleiben draußen, sie zahlt
    der Mieter."""
    jahr = jahr or date.today().year
    o = session.exec(select(Objekt).where(Objekt.slug == objekt)).first()
    if not o:
        raise HTTPException(404, "Objekt nicht gefunden")

    einheiten = _einheiten_zahlen(session, o, jahr)
    bloecke = _gefiltert(_bloecke(session, o, jahr, sicht), kategorien)
    ergebnis = cashflow(einheiten, bloecke)
    return {
        "jahr": jahr, "objekt": o.slug, "name": o.name, "typ": o.typ,
        "mietwort": _mietwort(o),
        "kategorien": BLOCK_NAMEN,
        "sicht": _sichtname(sicht),
        **ergebnis,
        "sankey": sankey(ergebnis["einheiten"], bloecke),
    }


@router.get("/sankey")
def sankey_endpoint(jahr: int = Query(default=None), objekt: str = Query(default=None),
                    kategorien: str = Query(default=None),
                    sicht: str = Query(default=None),
                    session: Session = Depends(get_session)) -> dict:
    """Kostenfluss über alle Objekte — folgt denselben Filtern wie die Auswertung.

    In der Mietersicht fließen nicht die Mieten, sondern die Vorauszahlungen:
    was der Mieter im Jahr gezahlt hat, gegen das, was auf ihn umgelegt wird."""
    jahr = jahr or date.today().year
    mietersicht = sicht == "mieter"
    objekte = session.exec(select(Objekt)).all()
    if objekt:
        objekte = [o for o in objekte if o.slug == objekt]

    quellen: list[dict] = []
    bloecke_gesamt: dict[str, float] = {}
    for o in objekte:
        _dazu(bloecke_gesamt, _gefiltert(_bloecke(session, o, jahr, sicht), kategorien))

        if mietersicht:
            einzeln = _vz_quellen(session, o, jahr)
            if not objekt:  # über alle Objekte zählt das Objekt, nicht die Einheit
                einzeln = [{"bezeichnung": o.name,
                            "einnahmen_jahr": round(sum(q["einnahmen_jahr"]
                                                        for q in einzeln), 2)}]
        elif objekt:    # ein Objekt -> je Einheit aufschlüsseln
            einzeln = cashflow(_einheiten_zahlen(session, o, jahr), {})["einheiten"]
        else:           # alle Objekte -> je Objekt
            mieten = session.exec(select(Miete).where(Miete.objekt_id == o.id)).all()
            einzeln = [{"bezeichnung": o.name,
                        "einnahmen_jahr": round(sum(_miete_im_jahr(m, jahr)
                                                    for m in mieten), 2)}]
        quellen.extend(einzeln)

    fluss = sankey(quellen, bloecke_gesamt)
    if mietersicht:
        for knoten in fluss["knoten"]:
            knoten["name"] = MIETER_KNOTEN.get(knoten["name"], knoten["name"])

    return {"jahr": jahr, "kategorien": BLOCK_NAMEN,
            "sicht": _sichtname(sicht),
            **fluss}


@router.get("/mietverlauf")
def mietverlauf(objekt: str = Query(default=None),
                session: Session = Depends(get_session)) -> dict:
    """Kaltmiete — beim Grundstück die Pacht — je Jahr für die Verlaufskurve.

    Jede Reihe sagt selbst, wie ihr Entgelt heisst; die Kurve kann Miet- und
    Pachtobjekte nebeneinander zeigen, ohne dass eines von beiden falsch
    beschriftet wäre."""
    objekte = session.exec(select(Objekt)).all()
    if objekt:
        objekte = [o for o in objekte if o.slug == objekt]

    heute = date.today().year
    jahre = list(range(heute - 7, heute + 1))
    reihen = []
    for o in objekte:
        mieten = session.exec(select(Miete).where(Miete.objekt_id == o.id)).all()
        werte = [round(sum(jahresbetrag(m.kaltmiete, m.turnus)
                           * _monate_im_jahr(m, j) / 12 for m in mieten), 2)
                 for j in jahre]
        if any(werte):
            reihen.append({"slug": o.slug, "name": o.name,
                           "mietwort": _mietwort(o), "werte": werte})
    return {"jahre": jahre, "reihen": reihen}
