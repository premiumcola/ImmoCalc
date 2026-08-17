"""N409 (Aufgabe 3, Brücke) — die Investment-KPI-Engine an ein echtes Objekt
anschließen: `GET /objekte/{slug}/kpi`.

Reine Zusammenstellung: liest Objekt/Einheiten/Kredite/laufende Mieten,
baut daraus eine `KpiEingabe` und ruft `investment_kpi.kennzahlen()` +
`investment_rating.bewertung()`. Keine eigene Rechenlogik — die steht
bewusst in den beiden reinen Modulen, hier nur das Zusammentragen aus der
Datenbank.
"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..db import get_session
from ..investment_kpi import KpiEingabe, KreditEingabe, kennzahlen
from ..investment_rating import bewertung
from ..models import (Anteil, Eigentuemer, Einheit, Kredit, Miete, Objekt,
                      ist_bausparer)
from ..turnus import jahresbetrag
from ..verteilung import _gesamtflaeche
from .stammdaten import _laufende

router = APIRouter(tags=["objekte"])


def _objekt(session: Session, slug: str) -> Objekt:
    o = session.exec(select(Objekt).where(Objekt.slug == slug)).first()
    if not o:
        raise HTTPException(404, "Objekt nicht gefunden")
    return o


def _hauptgrenzsteuersatz(session: Session, objekt_id: int) -> float | None:
    """Der Grenzsteuersatz gehört der Person (N409), nicht dem Objekt — bei
    mehreren Miteigentümern ist das kein exakter Wert. Für die Objekt-Ebene
    genügt der Satz des Eigentümers mit dem größten Anteil (bei Alleineigentum
    ohnehin der einzige); eine echte Aufteilung nach Anteil bleibt der
    Personen-Ebene vorbehalten, die dieses Modul nicht berechnet."""
    anteile = session.exec(select(Anteil).where(
        Anteil.objekt_id == objekt_id)).all()
    if not anteile:
        return None
    groesster = max(anteile, key=lambda a: a.promille or 0)
    e = session.get(Eigentuemer, groesster.eigentuemer_id)
    return e.grenzsteuersatz_pct if e else None


def _kredit_eingabe(k: Kredit) -> KreditEingabe:
    return KreditEingabe(
        restschuld=k.restschuld, zinssatz_pct=k.zinssatz,
        rate_monatlich=round(jahresbetrag(k.rate_monatlich, k.turnus) / 12, 2),
        zinsbindung_bis=k.zinsbindung_bis, ist_bausparvertrag=ist_bausparer(k))


def kpi_eingabe_fuer(session: Session, o: Objekt,
                     stichtag: date | None = None) -> KpiEingabe:
    """Die Brücke von der Datenbank zur reinen `KpiEingabe` — auch von
    anderen Aufrufern nutzbar (Eigentümer-Liste, künftige Was-wäre-wenn-
    Vorschau), damit die Zusammenstellung nur an einer Stelle steht."""
    tag = stichtag or date.today()
    einheiten = session.exec(select(Einheit).where(
        Einheit.objekt_id == o.id, Einheit.nk_abrechnung == True)).all()  # noqa: E712
    mieten = session.exec(select(Miete).where(
        Miete.objekt_id == o.id)).all()
    kredite = session.exec(select(Kredit).where(
        Kredit.objekt_id == o.id)).all()

    laufend = _laufende(list(mieten), tag)
    kaltmiete_jahr_ist = round(sum(
        jahresbetrag(m.kaltmiete or 0.0, m.turnus) for m in laufend), 2)

    wohnflaeche = None
    flaechen = [_gesamtflaeche(e) for e in einheiten]
    if any(f is not None for f in flaechen):
        wohnflaeche = round(sum(f or 0.0 for f in flaechen), 2)

    belegte_einheiten = {m.einheit for m in laufend if m.einheit}
    hat_leerstand = any(e.bezeichnung not in belegte_einheiten
                        for e in einheiten) if einheiten else False

    # Vergleichsmiete: nach Fläche gewichteter Schnitt über die Einheiten,
    # die einen Mietspiegel-Wert tragen — fehlt er überall, bleibt es `None`.
    vergleichsmiete = None
    bewertete = [(e, _gesamtflaeche(e)) for e in einheiten
                if e.vergleichsmiete_eur_qm is not None]
    flaechensumme = sum(f or 0.0 for _, f in bewertete)
    if bewertete and flaechensumme > 0:
        vergleichsmiete = round(sum(
            e.vergleichsmiete_eur_qm * (f or 0.0) for e, f in bewertete
        ) / flaechensumme, 2)

    return KpiEingabe(
        stichtag=tag,
        kaufpreis=o.kaufpreis, kaufdatum=o.kaufdatum,
        nebenkosten_grunderwerbsteuer=o.erwerb_grunderwerbsteuer,
        nebenkosten_notar=o.erwerb_notar_grundbuch,
        nebenkosten_makler=o.erwerb_makler,
        verkehrswert=o.verkehrswert,
        grundstuecksflaeche_qm=o.grundstueck_flaeche,
        wohnflaeche_qm=wohnflaeche,
        anzahl_einheiten=len(einheiten) or None,
        bodenrichtwert_eur_qm=o.grundstueck_m2_preis,
        gebaeudeanteil_pct_manuell=o.gebaeudeanteil_pct,
        afa_satz_pct=o.afa_satz_pct,
        restnutzungsdauer_jahre=o.afa_restnutzungsdauer_jahre,
        grenzsteuersatz_pct=_hauptgrenzsteuersatz(session, o.id),
        baukosten_eur_qm=o.kpi_baukosten_eur_qm,
        ruecklage_jahr_manuell=(
            round(o.ruecklage_monatlich * 12, 2)
            if o.ruecklage_monatlich else None),
        verwaltung_jahr=None,
        mietausfallwagnis_pct=o.mietausfallwagnis_pct,
        nicht_umlagefaehige_kosten_jahr=o.kpi_nicht_umlagefaehige_kosten_jahr,
        kaltmiete_jahr_ist=kaltmiete_jahr_ist,
        vergleichsmiete_eur_qm=vergleichsmiete,
        hat_leerstand=hat_leerstand,
        kredite=[_kredit_eingabe(k) for k in kredite],
        opportunitaetszins_pct=o.kpi_opportunitaetszins_pct or 4.0,
    )


@router.get("/objekte/{slug}/kpi")
def objekt_kpi(slug: str, session: Session = Depends(get_session)) -> dict:
    """Investment-Kennzahlen + Bewertung eines Objekts, aus den echten
    Stammdaten zusammengestellt (N409). Pflichtangaben zur Abrechnung
    braucht dieser Endpunkt keine — er zeigt einfach, was aus dem
    vorhandenen Bestand berechenbar ist, und lässt den Rest `None`."""
    o = _objekt(session, slug)
    eingabe = kpi_eingabe_fuer(session, o)
    k = kennzahlen(eingabe)
    return {"kennzahlen": k, "bewertung": bewertung(k)}
