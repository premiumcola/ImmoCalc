"""Sicherung und Wiederherstellung einer Immobilie.

Eine Immobilie wird vollständig als JSON ausgegeben — Stammdaten, Einheiten,
Zeiträume samt Positionen, Mieten samt Bewohnern, Versicherungen, Kredite samt
Jahresständen, Zahlungen und die Verweise auf die Dokumente in der Nextcloud.

Beim Löschen wird diese Sicherung zuerst geschrieben, dann erst gelöscht. Die
Dateien in der Nextcloud bleiben dabei unangetastet — gelöscht wird nur, was in
der Datenbank steht. Der Import legt daraus wieder ein Objekt an; ein
bestehendes wird nie überschrieben, sondern ein neuer Datensatz angelegt.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Type

from sqlmodel import Session, SQLModel, or_, select

from .models import (Ablesung, Anteil, Belegdaten, Bewohner, Dokument,
                     Eigentuemer, Einheit, Grundschuld, GrundschuldKredit,
                     Heizoellieferung, Heizverteiler, Kontakt, Kostenart,
                     Kostenposition, Kredit, Kreditstand, Kundennummer, Miete,
                     Notarvertrag, Objekt, Partei, Renovierung,
                     Renovierungsposten, Stromjahr, Versicherung,
                     Versandprotokoll, Vorauszahlung, WegVorauszahlung, Zahlung,
                     Zaehler, Zeitraum, PVAnlage, Tankladung, Tanknutzer)

log = logging.getLogger("immocalc")

FORMAT = "immocalc-objekt/1"

# Alles, was am Objekt hängt. Reihenfolge = Reihenfolge beim Wiederanlegen.
ANHAENGSEL: dict[str, Type[SQLModel]] = {
    "einheiten": Einheit,
    "parteien": Partei,
    "kostenarten": Kostenart,
    "versicherungen": Versicherung,
    "mieten": Miete,
    "kredite": Kredit,
    "zahlungen": Zahlung,
    "anteile": Anteil,
    # N105 - die spaeter dazugekommenen objektgebundenen Tabellen. Ohne sie
    # blieben ihre Saetze beim Loeschen eines Objekts als Waisen stehen und
    # fehlten in der Sicherung.
    "heizoellieferungen": Heizoellieferung,
    "heizverteiler": Heizverteiler,
    "stromjahre": Stromjahr,
    "belegdaten": Belegdaten,
    # N112/N139 — Ladungen der E-Tankstelle und die Stammdaten der PV-Anlage.
    "tanknutzer": Tanknutzer,
    "tankladungen": Tankladung,
    "pv_anlagen": PVAnlage,
    # N314(c) — acht objektgebundene Tabellen fehlten hier: weder gesichert
    # noch beim Löschen entfernt. Die Sätze blieben als Waisen stehen, und
    # SQLite vergibt frei gewordene rowids neu — ein neu angelegtes Objekt
    # konnte so fremde Notarverträge oder Zähler "erben".
    "notarvertraege": Notarvertrag,
    "renovierungen": Renovierung,
    "zaehler": Zaehler,
    "grundschulden": Grundschuld,
    # Kundennummer ist an ein Objekt *und* einen Kontakt gebunden. Der Kontakt
    # selbst gehört mehreren Objekten gemeinsam und wird beim Löschen eines
    # einzelnen Objekts nicht angetastet.
    "kundennummern": Kundennummer,
}

# N366 — was am ZEITRAUM hängt. `Kostenposition` steht bewusst nicht hier: sie
# braucht eine id-Abbildung (ein Beleg zeigt auf sie) und wird darum einzeln
# behandelt. Diese drei nicht — sie werden nur angelegt und entfernt.
# `WegVorauszahlung` und `Versandprotokoll` fehlten vorher ganz: sie wurden
# weder gesichert noch beim Löschen entfernt. Die Folgen waren real —
# ein stehen gebliebenes Versandprotokoll ließ SQLite nach der
# rowid-Wiederverwendung glauben, eine Partei sei schon beliefert, und sie
# bekam ihre Abrechnung nie; die WEG-Monatsbeträge waren nach
# Löschen+Wiederherstellen ersatzlos weg und die Nachforderung um den vollen
# Jahresbetrag zu hoch.
ZEITRAUM_KINDER: dict[str, Type[SQLModel]] = {
    "vorauszahlungen": Vorauszahlung,
    "wegvorauszahlungen": WegVorauszahlung,
    "versandprotokolle": Versandprotokoll,
}

# N366 — jedes Feld, das auf ein Dokument zeigt. Beim Import wird es über die
# Abbildung alte→neue Dokument-id aufgelöst; lässt es sich nicht auflösen,
# wird es geleert statt auf einen inzwischen fremden Beleg zu zeigen. Ohne das
# zeigte der „Beleg"-Knopf am eigenen Eintrag auf den Mietvertrag eines
# anderen Objekts, das die frei gewordene rowid geerbt hatte.
DOKUMENT_VERWEISE = ("quelle_dokument_id", "dokument_id",
                     "screenshot_dokument_id")

# Was nicht am Objekt hängt, sondern an einem seiner Sätze: die Jahresstände am
# Kredit, die Bewohner am Mietverhältnis. Ohne sie wäre die Sicherung
# unvollständig — und beim Löschen blieben sie als Waisen stehen. SQLite
# vergibt frei gewordene rowids neu: der nächste Kredit erbte sonst die
# Jahresstände des gelöschten, der nächste Mieter fremde Bewohner.
# Name in der Sicherung -> (Modell, Fremdschlüssel, Name des Elternteils)
KINDER: dict[str, tuple[Type[SQLModel], str, str]] = {
    "kreditstaende": (Kreditstand, "kredit_id", "kredite"),
    "bewohner": (Bewohner, "miete_id", "mieten"),
    # N314(c)
    "renovierungsposten": (Renovierungsposten, "renovierung_id", "renovierungen"),
    "ablesungen": (Ablesung, "zaehler_id", "zaehler"),
}


def _rein(wert):
    """date/datetime nach ISO — json.dumps kann sie sonst nicht schreiben."""
    if isinstance(wert, (date, datetime)):
        return wert.isoformat()
    return wert


def _zeilen(session: Session, modell: Type[SQLModel], objekt_id: int) -> list[dict]:
    treffer = session.exec(
        select(modell).where(modell.objekt_id == objekt_id)).all()
    return [{k: _rein(v) for k, v in z.model_dump().items()} for z in treffer]


def _kinder(session: Session, modell: Type[SQLModel], schluessel: str,
            eltern_ids: list[int]) -> list[SQLModel]:
    """Alle Sätze eines Kindmodells zu einer Menge von Elternteilen — in einem
    Zug, nicht je Elternteil einzeln."""
    if not eltern_ids:
        return []
    return list(session.exec(
        select(modell).where(getattr(modell, schluessel).in_(eltern_ids))).all())


def exportiere(session: Session, objekt: Objekt) -> dict:
    """Vollständige Sicherung eines Objekts als reines JSON-Gerüst."""
    daten: dict = {
        "format": FORMAT,
        "erstellt": date.today().isoformat(),
        "objekt": {k: _rein(v) for k, v in objekt.model_dump().items()},
    }
    for name, modell in ANHAENGSEL.items():
        daten[name] = _zeilen(session, modell, objekt.id)

    # Jahresstände und Bewohner hängen einen Schritt tiefer. Ihr Fremdschlüssel
    # bleibt in der Sicherung stehen und wird beim Import auf die neu vergebene
    # id des Kredits bzw. des Mietverhältnisses umgehängt.
    for name, (modell, schluessel, eltern) in KINDER.items():
        ids = [z["id"] for z in daten[eltern] if z.get("id") is not None]
        daten[name] = [{k: _rein(v) for k, v in z.model_dump().items()}
                       for z in _kinder(session, modell, schluessel, ids)]

    # Der Anteil zeigt auf eine Eigentümer-id. SQLite vergibt frei gewordene
    # Nummern neu — nach Löschen und Neuanlegen zeigt dieselbe id auf eine
    # andere Person. Deshalb den Namen mitschreiben und beim Import danach
    # auflösen, sonst hält am Ende eine fremde Gesellschaft 100 %.
    for zeile in daten["anteile"]:
        eigner = session.get(Eigentuemer, zeile.get("eigentuemer_id"))
        zeile["eigentuemer_name"] = eigner.name if eigner else ""

    # Dieselbe Regel für die Kundennummer: der Kontakt gehört mehreren Objekten
    # und wird nicht mitgesichert. Sein Schlüssel reicht, um ihn beim Import
    # wiederzufinden — die id kann bis dahin längst einem anderen gehören.
    for zeile in daten["kundennummern"]:
        kontakt = session.get(Kontakt, zeile.get("kontakt_id"))
        zeile["kontakt_schluessel"] = kontakt.schluessel if kontakt else ""

    # Grundschuld-Kredit ist eine m:n-Verknüpfung ohne eigene id und ohne
    # objekt_id — und kann auf einen Kredit an einem ANDEREN Objekt zeigen
    # (eine Grundschuld auf Haus A sichert das Darlehen für Haus B kommt im
    # Bestand vor). Deshalb über beide Fremdschlüssel gesucht, nicht per
    # ANHAENGSEL/KINDER, die nur eine Elternspalte kennen.
    grundschuld_ids = [z["id"] for z in daten["grundschulden"]]
    kredit_ids = [z["id"] for z in daten["kredite"]]
    gks = session.exec(select(GrundschuldKredit).where(or_(
        GrundschuldKredit.grundschuld_id.in_(grundschuld_ids),
        GrundschuldKredit.kredit_id.in_(kredit_ids)))).all()
    daten["grundschuldkredite"] = [
        {"grundschuld_id": g.grundschuld_id, "kredit_id": g.kredit_id} for g in gks]

    zeitraeume = session.exec(
        select(Zeitraum).where(Zeitraum.objekt_id == objekt.id)).all()
    daten["zeitraeume"] = []
    for z in zeitraeume:
        positionen = session.exec(
            select(Kostenposition).where(Kostenposition.zeitraum_id == z.id)).all()
        eintrag = {
            **{k: _rein(v) for k, v in z.model_dump().items()},
            "positionen": [{k: _rein(v) for k, v in p.model_dump().items()}
                           for p in positionen],
        }
        for name, modell in ZEITRAUM_KINDER.items():
            eintrag[name] = [
                {k: _rein(v) for k, v in kind.model_dump().items()}
                for kind in session.exec(
                    select(modell).where(modell.zeitraum_id == z.id)).all()]
        daten["zeitraeume"].append(eintrag)

    daten["dokumente"] = [{k: _rein(v) for k, v in d.model_dump().items()}
                          for d in session.exec(
                              select(Dokument).where(
                                  Dokument.objekt_id == objekt.id)).all()]
    return daten


def als_datei(daten: dict) -> bytes:
    return json.dumps(daten, ensure_ascii=False, indent=2).encode("utf-8")


def dateiname(objekt: Objekt) -> str:
    return f"ImmoCalc-Sicherung_{objekt.slug}_{date.today():%Y-%m-%d}.json"


def loesche(session: Session, objekt: Objekt) -> dict:
    """Entfernt das Objekt und alles, was daran hängt — aus der Datenbank.

    Die Dateien in der Nextcloud bleiben bestehen; sie gehören dem Nutzer.
    Auch die Dokument-Einträge werden nur aus der Datenbank genommen, damit
    ein späterer Scan sie wiederfindet."""
    entfernt: dict[str, int] = {}

    zeitraeume = session.exec(
        select(Zeitraum).where(Zeitraum.objekt_id == objekt.id)).all()
    for z in zeitraeume:
        for modell in (Kostenposition, *ZEITRAUM_KINDER.values()):
            for eintrag in session.exec(
                    select(modell).where(modell.zeitraum_id == z.id)).all():
                session.delete(eintrag)
                entfernt[modell.__name__] = entfernt.get(modell.__name__, 0) + 1
        session.delete(z)
    entfernt["Zeitraum"] = len(zeitraeume)

    # Erst die Kinder der Sätze, dann die Sätze selbst — sonst kennt niemand
    # mehr die Kredite und Mietverhältnisse, an denen sie hängen.
    for name, (modell, schluessel, eltern) in KINDER.items():
        eltern_modell = ANHAENGSEL[eltern]
        saetze = session.exec(select(eltern_modell).where(
            eltern_modell.objekt_id == objekt.id)).all()
        ids = [s.id for s in saetze if s.id is not None]
        kinder = _kinder(session, modell, schluessel, ids)
        for kind in kinder:
            session.delete(kind)
        entfernt[name] = len(kinder)

    # Grundschuld-Kredit hat zwei Elternspalten (siehe exportiere) — hier
    # anhand beider geloest, auch wenn die Gegenseite an einem anderen Objekt
    # haengt, dessen Kredit gerade mit geloescht wird.
    grundschuld_ids = [g.id for g in session.exec(
        select(Grundschuld).where(Grundschuld.objekt_id == objekt.id)).all()]
    kredit_ids = [k.id for k in session.exec(
        select(Kredit).where(Kredit.objekt_id == objekt.id)).all()]
    gks = session.exec(select(GrundschuldKredit).where(or_(
        GrundschuldKredit.grundschuld_id.in_(grundschuld_ids),
        GrundschuldKredit.kredit_id.in_(kredit_ids)))).all()
    for gk in gks:
        session.delete(gk)
    entfernt["grundschuldkredite"] = len(gks)

    for name, modell in ANHAENGSEL.items():
        treffer = session.exec(
            select(modell).where(modell.objekt_id == objekt.id)).all()
        for eintrag in treffer:
            session.delete(eintrag)
        entfernt[name] = len(treffer)

    dokumente = session.exec(
        select(Dokument).where(Dokument.objekt_id == objekt.id)).all()
    for d in dokumente:
        session.delete(d)
    entfernt["dokumente"] = len(dokumente)

    session.delete(objekt)
    session.commit()
    log.info("Objekt %s gelöscht (%s)", objekt.slug, entfernt)
    return entfernt


def _passender_eigner(session: Session, anteil: dict) -> Eigentuemer | None:
    """Der Eigentümer zu einem gesicherten Anteil — über den Namen, nicht die id.

    Die id allein genügt nicht: sie kann inzwischen einer anderen Person
    gehören. Nur wenn Name *und* id zusammenpassen, ist es sicher dieselbe."""
    name = (anteil.get("eigentuemer_name") or "").strip()
    if name:
        treffer = session.exec(
            select(Eigentuemer).where(Eigentuemer.name == name)).first()
        if treffer:
            return treffer
        return None
    # Alte Sicherungen ohne Namen: nur die id, und die muss belegt sein.
    return session.get(Eigentuemer, anteil.get("eigentuemer_id"))


def _live_oder_neu(session: Session, modell: Type[SQLModel], alte_id,
                   neue_ids: dict[int, int]):
    """Die neue id, falls dieser Satz Teil DIESER Wiederherstellung war —
    sonst die alte id, falls sie noch unverändert existiert.

    Für Grundschuld-Kredit: eine Grundschuld auf Objekt A kann einen Kredit an
    Objekt B sichern. Wird nur A gelöscht und wiederhergestellt, blieb Kredit
    B die ganze Zeit unangetastet stehen — seine alte id ist weiterhin
    korrekt und darf nicht durch "keine Verknüpfung" ersetzt werden."""
    if alte_id is None:
        return None
    neu = neue_ids.get(alte_id)
    if neu is not None:
        return neu
    return alte_id if session.get(modell, alte_id) else None


def _dokumente_umhaengen(eintrag: dict, karte: dict[int, int]) -> None:
    """Jeden Beleg-Verweis auf die neue id abbilden — oder leeren (N366).

    Die alte Nummer stehen zu lassen ist die gefährlichere Wahl: SQLite vergibt
    frei gewordene rowids neu, der Verweis zeigte dann auf den Beleg eines
    fremden Objekts, und die Oberfläche öffnet ihn wortlos. Kein Verweis ist
    ehrlicher als ein falscher."""
    for feld in DOKUMENT_VERWEISE:
        if eintrag.get(feld) is not None:
            eintrag[feld] = karte.get(eintrag[feld])


def importiere(session: Session, daten: dict, freier_slug) -> Objekt:
    """Legt aus einer Sicherung wieder ein Objekt an — immer als neuer Datensatz.

    `freier_slug(session, name)` liefert einen noch unbenutzten Slug; so bleibt
    ein gleichnamiges Objekt, das noch existiert, unangetastet."""
    roh = dict(daten.get("objekt") or {})
    roh.pop("id", None)
    roh["name"] = roh.get("name") or "Wiederhergestellt"
    roh["slug"] = freier_slug(session, roh["name"])
    objekt = Objekt.model_validate(roh)
    session.add(objekt)
    session.commit()
    session.refresh(objekt)

    # alte Zeitraum-id -> neue. Zuerst angelegt, weil Ablesungen (unten, als
    # KINDER der Zähler) ihren Zeitraum darüber wiederfinden.
    zeitraeume: dict[int, int] = {}
    # dasselbe für die Kostenpositionen (CLXXXIII): ein Beleg zeigt über die id
    # auf seine Position. Bliebe die alte Nummer stehen, zeigte er nach dem
    # Wiederherstellen auf eine fremde Zeile — SQLite vergibt Nummern neu.
    positionen: dict[int, int] = {}
    eigene = ("id", "positionen", *ZEITRAUM_KINDER)
    for z in daten.get("zeitraeume") or []:
        roh_z = {k: v for k, v in z.items() if k not in eigene}
        roh_z["objekt_id"] = objekt.id
        zeitraum = Zeitraum.model_validate(roh_z)
        session.add(zeitraum)
        session.commit()
        session.refresh(zeitraum)
        if z.get("id") is not None:
            zeitraeume[z["id"]] = zeitraum.id
        for p in z.get("positionen") or []:
            roh_p = dict(p)
            alte_id = roh_p.pop("id", None)
            roh_p["zeitraum_id"] = zeitraum.id
            # Der Beleg, aus dem die Position entstand, wird erst weiter unten
            # angelegt — der Verweis kommt danach (siehe `nachtrag_dokumente`).
            roh_p["quelle_dokument_id"] = None
            position = Kostenposition.model_validate(roh_p)
            session.add(position)
            if alte_id is not None:
                session.commit()
                session.refresh(position)
                positionen[alte_id] = position.id
        for name, modell in ZEITRAUM_KINDER.items():
            for kind in z.get(name) or []:
                roh_k = dict(kind)
                roh_k.pop("id", None)
                roh_k["zeitraum_id"] = zeitraum.id
                session.add(modell.model_validate(roh_k))

    # N366 — die Dokumente VOR allem, was auf sie zeigt. Sie brauchen selbst
    # nur Zeitraum und Position, die schon stehen; danach lässt sich jeder
    # Beleg-Verweis auf seine neue id abbilden statt auf die alte Nummer, die
    # inzwischen einem fremden Objekt gehören kann.
    dokumente: dict[int, int] = {}
    for d in daten.get("dokumente") or []:
        roh_d = dict(d)
        alte_id = roh_d.pop("id", None)
        roh_d["objekt_id"] = objekt.id
        roh_d["zeitraum_id"] = zeitraeume.get(roh_d.get("zeitraum_id"))
        roh_d["position_id"] = positionen.get(roh_d.get("position_id"))
        vorhanden = session.exec(select(Dokument).where(
            Dokument.pfad == roh_d.get("pfad"))).first()
        if vorhanden:                      # steht schon in der Datenbank
            if alte_id is not None:
                dokumente[alte_id] = vorhanden.id
            continue
        neu_d = Dokument.model_validate(roh_d)
        session.add(neu_d)
        if alte_id is not None:
            session.commit()
            session.refresh(neu_d)
            dokumente[alte_id] = neu_d.id

    # Die Positionen wurden ohne ihren Beleg angelegt — jetzt nachtragen.
    for z in daten.get("zeitraeume") or []:
        for p in z.get("positionen") or []:
            neue_id = positionen.get(p.get("id"))
            quelle = dokumente.get(p.get("quelle_dokument_id"))
            if neue_id is None or quelle is None:
                continue
            pos = session.get(Kostenposition, neue_id)
            if pos is not None:
                pos.quelle_dokument_id = quelle
                session.add(pos)

    # alte Satz-id -> neue, damit Jahresstände und Bewohner ihren Kredit bzw.
    # ihr Mietverhältnis wiederfinden. "grundschulden" hängt an keinem KINDER,
    # wird aber für die Grundschuld-Kredit-Verknüpfung unten gebraucht.
    eltern_ids: dict[str, dict[int, int]] = {
        eltern: {} for _, _, eltern in KINDER.values()}
    eltern_ids.setdefault("grundschulden", {})

    for name, modell in ANHAENGSEL.items():
        for zeile in daten.get(name) or []:
            eintrag = dict(zeile)
            alte_id = eintrag.pop("id", None)
            eintrag["objekt_id"] = objekt.id
            _dokumente_umhaengen(eintrag, dokumente)
            if name == "mieten":
                # Die Mieterhöhungskette zeigt auf eine andere Miete derselben
                # Tabelle — verknüpft wird sie unten, wenn alle neuen ids
                # feststehen (dasselbe Muster wie beim Hauptzähler).
                eintrag["vorgaenger_id"] = None
            if name == "anteile":
                eigner = _passender_eigner(session, eintrag)
                # Eigentümer werden getrennt gepflegt und beim Löschen eines
                # Objekts nicht mitgelöscht. Passt keiner, bleibt der Anteil
                # weg — lieber keine Beteiligung als die falsche.
                if eigner is None:
                    log.info("Anteil ohne passenden Eigentümer übersprungen: %s",
                             eintrag.get("eigentuemer_name") or "ohne Namen")
                    continue
                eintrag["eigentuemer_id"] = eigner.id
                eintrag.pop("eigentuemer_name", None)
            if name == "kundennummern":
                # Derselbe Grundsatz wie beim Eigentümer: der Kontakt ist
                # geteilt, seine id kann inzwischen jemand anderem gehören.
                schluessel = eintrag.pop("kontakt_schluessel", "")
                kontakt = session.exec(select(Kontakt).where(
                    Kontakt.schluessel == schluessel)).first() if schluessel else None
                eintrag["kontakt_id"] = kontakt.id if kontakt else None
            if name == "zaehler":
                # Der Hauptzähler wird erst unten, nach dieser Schleife,
                # verknüpft — die neue id des eigenen Hauptzählers steht
                # innerhalb dieser Schleife noch nicht immer schon fest.
                eintrag["hauptzaehler_id"] = None
            neu = modell.model_validate(eintrag)
            session.add(neu)
            if name in eltern_ids:
                session.commit()
                session.refresh(neu)
                if alte_id is not None:
                    eltern_ids[name][alte_id] = neu.id

    # Rest-Zähler zeigen auf ihren eigenen Hauptzähler (dieselbe Tabelle) —
    # erst jetzt sind alle neuen ids bekannt. Lässt sich der alte Hauptzähler
    # nicht wiederfinden, bleibt der Verweis leer statt auf einen inzwischen
    # fremden Zähler zu zeigen (rowid-Wiederverwendung, wie bei N314a).
    for alt in daten.get("zaehler") or []:
        if alt.get("hauptzaehler_id") is None:
            continue
        neue_id = eltern_ids["zaehler"].get(alt.get("id"))
        neuer_haupt = eltern_ids["zaehler"].get(alt["hauptzaehler_id"])
        if neue_id is None or neuer_haupt is None:
            continue
        zaehler_neu = session.get(Zaehler, neue_id)
        zaehler_neu.hauptzaehler_id = neuer_haupt
        session.add(zaehler_neu)

    # N366 — dieselbe Selbst-Referenz bei der Mieterhöhungskette. Ohne das
    # zeigte `vorgaenger_id` auf eine fremde Miete: die Belegkette und der
    # Kautions-Backfill (`migrate.miete_kaution_vorgaenger_uebernehmen`) zogen
    # dann die Daten eines fremden Mieters an den eigenen Mietstand.
    for alt in daten.get("mieten") or []:
        if alt.get("vorgaenger_id") is None:
            continue
        neue_id = eltern_ids["mieten"].get(alt.get("id"))
        neuer_vor = eltern_ids["mieten"].get(alt["vorgaenger_id"])
        if neue_id is None or neuer_vor is None:
            continue
        miete_neu = session.get(Miete, neue_id)
        if miete_neu is not None:
            miete_neu.vorgaenger_id = neuer_vor
            session.add(miete_neu)

    # Grundschuld-Kredit: beide Seiten müssen aus diesem Import stammen. Eine
    # Verknüpfung zu einem Kredit an einem anderen, nicht wiederhergestellten
    # Objekt lässt sich nicht auf eine gültige neue id abbilden — lieber die
    # Verknüpfung weglassen als eine falsche Sicherheit vortäuschen.
    for gk in daten.get("grundschuldkredite") or []:
        neue_grundschuld = _live_oder_neu(
            session, Grundschuld, gk.get("grundschuld_id"), eltern_ids["grundschulden"])
        neuer_kredit = _live_oder_neu(
            session, Kredit, gk.get("kredit_id"), eltern_ids["kredite"])
        if neue_grundschuld is None or neuer_kredit is None:
            log.info("Grundschuld-Kredit-Verknüpfung übersprungen: %s", gk)
            continue
        session.add(GrundschuldKredit(grundschuld_id=neue_grundschuld,
                                      kredit_id=neuer_kredit))

    # Alte Sicherungen kennen diese Schlüssel noch nicht — dann bleibt es
    # schlicht bei nichts, und die Wiederherstellung läuft wie zuvor durch.
    for name, (modell, schluessel, eltern) in KINDER.items():
        for zeile in daten.get(name) or []:
            kind = dict(zeile)
            kind.pop("id", None)
            neuer_elternteil = eltern_ids[eltern].get(kind.get(schluessel))
            if neuer_elternteil is None:
                log.info("%s ohne passenden Satz übersprungen: %s=%s",
                         name, schluessel, kind.get(schluessel))
                continue
            kind[schluessel] = neuer_elternteil
            _dokumente_umhaengen(kind, dokumente)
            if "zeitraum_id" in kind:
                # Ablesungen können an einen Zeitraum gebunden sein — auf die
                # neue id abbilden, sonst wieder ein Verweis ins Leere.
                kind["zeitraum_id"] = zeitraeume.get(kind.get("zeitraum_id"))
            session.add(modell.model_validate(kind))

    session.commit()
    log.info("Objekt aus Sicherung angelegt: %s", objekt.slug)
    return objekt
