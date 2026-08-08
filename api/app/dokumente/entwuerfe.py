"""CCLXXVIII: Aus dem KI-Raster wird ein vorläufiger (orange) Datensatz.

Der Beleg ist erkannt und trägt sein KI-Raster (`ki_felder`, `ki_einheit`,
Kategorie, Belegdatum, Betrag, Kostenart). Daraus wird an der richtigen Stelle
ein **vorläufiger** Datensatz angelegt — orange, weil noch unbestätigt. Der
Nutzer bestätigt ihn später (`/entwuerfe/{typ}/{id}/bestaetigen`) oder verwirft
ihn (`/verwerfen`); bis dahin bleibt der Beleg im Prüfmodus.

Datensicher: nur NEUE Datensätze mit `vorlaeufig=True`, nichts wird
überschrieben. Idempotent: existiert zum Beleg bereits ein vorläufiger
Datensatz desselben Typs, entsteht kein zweiter (`_schon_vorlaeufig`).

Je Kategorie ein Bauplan (`_ENTWURF_BAUER`), dieselben Baupläne noch einmal
über die Rubrik adressiert (`_ZIEL_BAUER`, CCCIX). Nur Datenbank, keine Cloud —
den Beleg selbst legt der Router ab, bevor er hier hereinkommt.
"""
from __future__ import annotations

from datetime import date

from sqlmodel import Session, select

from ..kostenarten import normalisieren as kostenart_normalisieren
from ..models import (Bewohner, Dokument, Kostenposition, Kredit, Miete,
                      Notarvertrag, Objekt, Versicherung, Zahlung, Zeitraum)
from .ki_werte import _ki_datum, _ki_text, _ki_zahl


def _schon_vorlaeufig(session: Session, modell, dokument_id: int):
    """Der bereits aus diesem Beleg entstandene vorläufige Datensatz — oder None.

    Die Sperre gegen ein zweites Anlegen: ein erneutes Zuordnen findet den
    vorhandenen Entwurf wieder, statt einen Zwilling zu erzeugen."""
    return session.exec(select(modell).where(
        modell.quelle_dokument_id == dokument_id,
        modell.vorlaeufig == True)).first()      # noqa: E712


def _zeitraum_fuer_beleg(session: Session, o: Objekt, d: Dokument):
    """Der Abrechnungszeitraum, in den der Beleg fällt — vorhandener oder neuer.

    Nach dem Belegdatum (Rückfall: gespeichertes Jahr). Gibt es schon einen
    Zeitraum, der den Tag umfasst, gilt der; sonst wird der passende nach der
    Turnus-Regel des Objekts angelegt (`_zeitraum_grenzen`/`_zeitraum_jahr` aus
    `objekte`, damit Anlegen und Erkennen deckungsgleich bleiben). `None`, wenn
    sich weder Tag noch Jahr bestimmen lassen."""
    from ..routers.objekte import (_zeitraum_grenzen,         # zirkelfrei zur
                                   _zeitraum_jahr)            # Laufzeit
    belegdatum = d.belegdatum or _ki_datum((d.ki_felder or {}).get("datum"))
    bestehende = session.exec(
        select(Zeitraum).where(Zeitraum.objekt_id == o.id)).all()
    if belegdatum:
        treffer = next((z for z in bestehende
                        if z.start <= belegdatum <= z.ende), None)
        if treffer:
            return treffer
        jahr = _zeitraum_jahr(o, belegdatum)
    elif d.jahr:
        jahr = d.jahr
    else:
        return None
    start, ende = _zeitraum_grenzen(o, jahr)
    treffer = next((z for z in bestehende
                    if z.start == start and z.ende == ende), None)
    if treffer:
        return treffer
    z = Zeitraum(objekt_id=o.id, start=start, ende=ende, typ="regulär",
                 status="in Arbeit")
    session.add(z)
    session.flush()
    return z


def _entwurf_nebenkosten(session: Session, d: Dokument, o: Objekt,
                         felder: dict) -> list[dict]:
    """Vorläufige Kostenposition im passenden Zeitraum — eine je (Zeitraum,
    Kostenart), keine zweite."""
    if _schon_vorlaeufig(session, Kostenposition, d.id):
        p = _schon_vorlaeufig(session, Kostenposition, d.id)
        return [{"typ": "Kostenposition", "id": p.id, "objekt": o.slug,
                 "wo": f"{p.kostenart} (schon angelegt)"}]
    z = _zeitraum_fuer_beleg(session, o, d)
    if z is None:
        return []
    kostenart = (kostenart_normalisieren(d.kostenart)
                 or kostenart_normalisieren(_ki_text(felder.get("kostenart")))
                 or "Nebenkosten")
    betrag = (d.betrag if d.betrag is not None
              else _ki_zahl(felder.get("betrag"))) or 0.0
    # Eine Kostenart, eine Zeile (CLXXXII): gibt es die Position schon, keine
    # zweite — auch keine vorläufige daneben.
    for p in session.exec(select(Kostenposition).where(
            Kostenposition.zeitraum_id == z.id)).all():
        if p.kostenart == kostenart:
            return []
    p = Kostenposition(
        zeitraum_id=z.id, kostenart=kostenart, betrag=round(betrag, 2),
        wertquelle="Scan", status="erledigt" if betrag else "offen",
        s35=bool(felder.get("s35a")), anteile={},
        vorlaeufig=True, quelle_dokument_id=d.id)
    session.add(p)
    session.flush()
    return [{"typ": "Kostenposition", "id": p.id, "objekt": o.slug,
             "wo": f"Zeitraum {z.start:%d.%m.%Y}–{z.ende:%d.%m.%Y} · {kostenart}"}]


def _entwurf_miete(session: Session, d: Dokument, o: Objekt,
                   felder: dict) -> list[dict]:
    """Vorläufiges Mietverhältnis (+ optional Bewohner) aus dem Mietvertrag."""
    if _schon_vorlaeufig(session, Miete, d.id):
        m = _schon_vorlaeufig(session, Miete, d.id)
        return [{"typ": "Miete", "id": m.id, "objekt": o.slug,
                 "wo": f"{m.partei or m.einheit or 'Mietverhältnis'} (schon angelegt)"}]
    einheit = (d.ki_einheit or _ki_text(felder.get("einheit"))).strip()
    mieter = _ki_text(felder.get("mieter"))
    ab = (_ki_datum(felder.get("mietbeginn")) or d.belegdatum or date.today())
    m = Miete(
        objekt_id=o.id, einheit=einheit, partei=mieter,
        kaltmiete=_ki_zahl(felder.get("kaltmiete")) or 0.0,
        nebenkosten_vz=_ki_zahl(felder.get("nebenkosten_vz")) or 0.0,
        stellplatz=_ki_zahl(felder.get("stellplatzmiete")) or 0.0,
        sonstige=_ki_zahl(felder.get("sonstige_einnahmen")) or 0.0,
        ab_datum=ab, kaution=_ki_zahl(felder.get("kaution")),
        personen=int(_ki_zahl(felder.get("personen")) or 1),
        email=_ki_text(felder.get("mieter_email")),
        telefon=_ki_text(felder.get("mieter_telefon")),
        vorlaeufig=True, quelle_dokument_id=d.id)
    session.add(m)
    session.flush()
    angelegt = [{"typ": "Miete", "id": m.id, "objekt": o.slug,
                 "wo": f"Einheit {einheit or 'ganzes Objekt'}"
                       + (f" · {mieter}" if mieter else "")}]
    if mieter:
        b = Bewohner(miete_id=m.id, name=mieter,
                     email=_ki_text(felder.get("mieter_email")),
                     telefon=_ki_text(felder.get("mieter_telefon")),
                     rolle="Hauptmieter", vorlaeufig=True,
                     quelle_dokument_id=d.id)
        session.add(b)
        session.flush()
        angelegt.append({"typ": "Bewohner", "id": b.id, "objekt": o.slug,
                         "wo": f"{mieter} in {einheit or 'ganzes Objekt'}"})
    return angelegt


def _entwurf_versicherung(session: Session, d: Dokument, o: Objekt,
                          felder: dict) -> list[dict]:
    """Vorläufige Versicherung aus dem Versicherungsbeleg."""
    if _schon_vorlaeufig(session, Versicherung, d.id):
        v = _schon_vorlaeufig(session, Versicherung, d.id)
        return [{"typ": "Versicherung", "id": v.id, "objekt": o.slug,
                 "wo": f"{v.art} (schon angelegt)"}]
    art = _ki_text(felder.get("art")) or (d.kostenart or "").strip() or "Gebäude"
    umlage = felder.get("umlagefaehig")
    v = Versicherung(
        objekt_id=o.id, art=art, anbieter=_ki_text(felder.get("anbieter")),
        police_nr=_ki_text(felder.get("police_nr")),
        jahresbeitrag=_ki_zahl(felder.get("jahresbeitrag")) or 0.0,
        turnus=_ki_text(felder.get("turnus")) or "jaehrlich",
        versicherungswert=_ki_zahl(felder.get("versicherungssumme")),
        beginn=_ki_datum(felder.get("beginn")),
        ende=_ki_datum(felder.get("ende")),
        umlagefaehig=bool(umlage) if isinstance(umlage, bool) else True,
        vorlaeufig=True, quelle_dokument_id=d.id)
    session.add(v)
    session.flush()
    return [{"typ": "Versicherung", "id": v.id, "objekt": o.slug, "wo": art}]


def _entwurf_kredit(session: Session, d: Dokument, o: Objekt,
                    felder: dict) -> list[dict]:
    """Vorläufiger Kredit/Bausparvertrag aus dem Finanzierungsbeleg."""
    if _schon_vorlaeufig(session, Kredit, d.id):
        k = _schon_vorlaeufig(session, Kredit, d.id)
        return [{"typ": "Kredit", "id": k.id, "objekt": o.slug,
                 "wo": f"{k.bezeichnung} (schon angelegt)"}]
    bezeichnung = (_ki_text(felder.get("bezeichnung"))
                   or _ki_text(felder.get("bank"))
                   or (d.kostenart or "").strip() or "Darlehen")
    k = Kredit(
        objekt_id=o.id, bezeichnung=bezeichnung,
        bank=_ki_text(felder.get("bank")),
        darlehensnummer=_ki_text(felder.get("darlehensnummer")),
        urspruenglich=_ki_zahl(felder.get("darlehenssumme")),
        restschuld=_ki_zahl(felder.get("restschuld")),
        bausparsumme=_ki_zahl(felder.get("bausparsumme")),
        angespart=_ki_zahl(felder.get("angespart")),
        zinssatz=_ki_zahl(felder.get("zinssatz")),
        rate_monatlich=_ki_zahl(felder.get("rate_monatlich")) or 0.0,
        zinsbindung_bis=_ki_datum(felder.get("zinsbindung_bis")),
        beginn=_ki_datum(felder.get("beginn")),
        vorlaeufig=True, quelle_dokument_id=d.id)
    session.add(k)
    session.flush()
    return [{"typ": "Kredit", "id": k.id, "objekt": o.slug, "wo": bezeichnung}]


def _entwurf_notarvertrag(session: Session, d: Dokument, o: Objekt,
                          felder: dict) -> list[dict]:
    """Vorläufiger Notarvertrag aus einer beurkundeten Urkunde (CCCII).

    Was die KI im PDF nicht findet, bleibt leer — der Eintrag entsteht trotzdem,
    damit der Vertrag samt PDF an seinem Platz steht und von Hand nachgepflegt
    werden kann."""
    if _schon_vorlaeufig(session, Notarvertrag, d.id):
        n = _schon_vorlaeufig(session, Notarvertrag, d.id)
        return [{"typ": "Notarvertrag", "id": n.id, "objekt": o.slug,
                 "wo": f"{n.art} (schon angelegt)"}]
    art = (_ki_text(felder.get("vertragsart")) or _ki_text(felder.get("art"))
           or (d.kostenart or "").strip() or "Kaufvertrag")
    n = Notarvertrag(
        objekt_id=o.id, art=art,
        notar=_ki_text(felder.get("notar")),
        urnr=_ki_text(felder.get("urnr")) or _ki_text(felder.get("urkundenrolle")),
        datum=_ki_datum(felder.get("datum")) or d.belegdatum,
        betrag=_ki_zahl(felder.get("kaufpreis"))
        or _ki_zahl(felder.get("betrag")) or 0.0,
        beteiligte=_ki_text(felder.get("beteiligte")),
        vorlaeufig=True, quelle_dokument_id=d.id)
    session.add(n)
    session.flush()
    return [{"typ": "Notarvertrag", "id": n.id, "objekt": o.slug, "wo": art}]


def _entwurf_steuer(session: Session, d: Dokument, o: Objekt,
                    felder: dict) -> list[dict]:
    """Vorläufige Zahlung aus einem Finanzamts-Beleg (CCXCIX) — z. B. der
    Grundsteuerbescheid. Jahr und Betrag kommen aus dem Beleg, wo vorhanden."""
    if _schon_vorlaeufig(session, Zahlung, d.id):
        z = _schon_vorlaeufig(session, Zahlung, d.id)
        return [{"typ": "Zahlung", "id": z.id, "objekt": o.slug,
                 "wo": f"{z.art} {z.jahr} (schon angelegt)"}]
    art = (_ki_text(felder.get("steuerart")) or (d.kostenart or "").strip()
           or "Grundsteuer")
    jahr = d.jahr or (d.belegdatum.year if d.belegdatum else date.today().year)
    z = Zahlung(objekt_id=o.id, jahr=jahr, art=art, kategorie="Steuer",
                betrag=_ki_zahl(felder.get("betrag")) or d.betrag or 0.0,
                vorlaeufig=True, quelle_dokument_id=d.id)
    session.add(z)
    session.flush()
    return [{"typ": "Zahlung", "id": z.id, "objekt": o.slug, "wo": f"{art} {jahr}"}]


def _entwurf_erwerb(session: Session, d: Dokument, o: Objekt,
                    felder: dict) -> list[dict]:
    """Vorläufige einmalige Erwerbsnebenkosten aus einem Beleg (CCCXIX) — Notar,
    Grunderwerbsteuer, Grundbuch, Makler … Eine Zahlung fester Kategorie
    „Erwerbsnebenkosten" mit Turnus „einmalig"; die Art kommt, wo erkennbar, aus
    der Kostenart, sonst „Sonstiges"."""
    if _schon_vorlaeufig(session, Zahlung, d.id):
        z = _schon_vorlaeufig(session, Zahlung, d.id)
        return [{"typ": "Zahlung", "id": z.id, "objekt": o.slug,
                 "wo": f"{z.art} {z.jahr} (schon angelegt)"}]
    art = (_ki_text(felder.get("erwerbsart")) or (d.kostenart or "").strip()
           or "Sonstiges")
    jahr = d.jahr or (d.belegdatum.year if d.belegdatum else date.today().year)
    z = Zahlung(objekt_id=o.id, jahr=jahr, art=art, kategorie="Erwerbsnebenkosten",
                turnus="einmalig", absetzbar=False,
                betrag=_ki_zahl(felder.get("betrag")) or d.betrag or 0.0,
                vorlaeufig=True, quelle_dokument_id=d.id)
    session.add(z)
    session.flush()
    return [{"typ": "Zahlung", "id": z.id, "objekt": o.slug, "wo": f"{art} {jahr}"}]


# Kategorie → Bauplan des vorläufigen Datensatzes. Was nicht hier steht
# (Hausverwaltung, Korrespondenz, Sonstiges), legt keinen an.
_ENTWURF_BAUER = {
    "Steuer": _entwurf_steuer,
    "Nebenkosten": _entwurf_nebenkosten,
    "Mietvertrag": _entwurf_miete,
    "Versicherung": _entwurf_versicherung,
    "Kredit": _entwurf_kredit,
    "Notarvertrag": _entwurf_notarvertrag,
}

# CCCIX — dieselben Baupläne, adressiert über die Rubrik statt über die
# Kategorie: so lässt sich ein Beleg der Kategorie „Sonstiges" bewusst als
# Notarvertrag anlegen, ohne ihn vorher umzuetikettieren.
_ZIEL_BAUER = {
    "nebenkosten": _entwurf_nebenkosten,
    "mieten": _entwurf_miete,
    "versicherungen": _entwurf_versicherung,
    "kredite": _entwurf_kredit,
    "notarvertraege": _entwurf_notarvertrag,
    "zahlungen": _entwurf_steuer,
    "erwerbskosten": _entwurf_erwerb,
}
