"""Checkliste eines Abrechnungszeitraums (`GET /zeitraeume/{zid}`).

Der Endpunkt fasst zusammen, was für einen Zeitraum vorliegt und was fehlt:
je Kostenart eine Zeile, Belege je Position, Vorauszahlungen, ein
Kostenfluss-Sankey auf Einheiten (CCCLVII). Die Rechenlogik hier ist bewusst
zeitraum-lokal — keine Engine-Aufrufe, nur Zusammenfassen.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..belegposten import belege_je_position, handanteil, kurz
from ..db import get_session
from ..frist import frist_tage
from ..models import (Bewohner, Dokument, Einheit, Kostenart, Kostenposition,
                      Miete, Objekt, Partei, Vorauszahlung, Zeitraum)
from ..verteilung import SCHLUESSEL, anteil_details, bezuege
from .zeitraeume import zeitraum_label_jahr

router = APIRouter(tags=["objekte"])


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
    # CCCLVII — Einheiten, Mieten und Bewohner, um den Kostenfluss-Sankey rechts
    # strikt auf Einheiten zu aggregieren (nie Partei- oder Bewohnernamen, wie
    # beim Nebenkosten-Sankey). Bewohner tragen die Schlüssel bei „bewohner-
    # monate"; auch sie zählen über ihre Miete zu einer Einheit.
    einheiten = session.exec(select(Einheit).where(Einheit.objekt_id == o.id)).all()
    mieten = session.exec(select(Miete).where(Miete.objekt_id == o.id)).all()
    _mieten_ids = [m.id for m in mieten]
    bewohner = (session.exec(select(Bewohner).where(Bewohner.miete_id.in_(_mieten_ids))).all()
                if _mieten_ids else [])
    parteien = session.exec(select(Partei).where(Partei.objekt_id == o.id)).all()
    # N29 — je Partei: Einheit, Mieter (bzw. Leerstand) und belegte Monate, damit
    # die Aufteilungszeile nicht nur den Parteinamen zeigt. Einmal je Zeitraum
    # abgeleitet (gilt für alle Positionen gleich), an der Position nur die
    # tatsächlich verteilten Parteien angehängt.
    _bez = bezuege(list(einheiten), list(mieten), list(parteien), z.start, z.ende)
    detail_map = anteil_details(_bez, z.start, z.ende)

    nach_art = {p.kostenart: p for p in positionen}
    # CLXXXIII: der Rückweg. Welche Belege in eine Position eingerechnet sind,
    # steht an ihnen selbst (`Dokument.position_id`) — nicht am Dateinamen und
    # nicht an der Kostenart, die sich umbenennen liesse.
    beleg_map = belege_je_position(session, list(positionen))

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
            # N29 — Einheit · Mieter · belegte Monate je verteilter Partei.
            "anteil_details": [detail_map[name] for name in anteile
                               if name in detail_map],
            # CCCLIX — Vorab-Anteil direkt auf eine Einheit (für Anzeige + Sankey)
            "vorab_betrag": round(p.vorab_betrag or 0, 2) if p else 0,
            "vorab_einheit": (p.vorab_einheit if p else "") or "",
            "vorab_s35": bool(p and p.vorab_s35),
            "vorab_netto": round(p.vorab_netto or 0, 2) if p else 0,
            "ohne_verteilung": bool(
                p and p.status == "erledigt" and (p.betrag or 0) != 0
                and sum(anteile.values()) <= 0),
        }

    belege = {}
    for d in dokumente:
        belege.setdefault(d.kategorie or "", []).append(
            {"id": d.id, "dateiname": d.dateiname, "pfad": d.pfad})

    def _zusammensetzung(p: Optional[Kostenposition]) -> dict:
        """Woraus der Betrag besteht — und welche Belege dahinterstehen.

        Vier Abschlagsrechnungen ergeben eine Position (CLXXXII); ohne diese
        Aufschlüsselung stünde dort nur eine Summe, die niemand mehr auf ihre
        Belege zurückführen kann."""
        eigene = beleg_map.get(p.id, []) if p else []
        return {
            "belege": [kurz(d) for d in eigene],
            "beleg_summe": round((p.beleg_summe or 0.0) if p else 0.0, 2),
            "handanteil": handanteil(p) if p else 0.0,
        }

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
            "nur_einheit": p.nur_einheit if p else "",
            "wertquelle": p.wertquelle if p else None,
            # N122 — dieselben Felder wie im Waisen-Zweig weiter unten. Fehlten
            # sie hier, blieb die Strom-Maske jeder Kostenart leer, die im
            # Katalog der Immobilie steht: PATCH speicherte, die Anzeige zeigte
            # nichts.
            "menge": p.menge if p else None,
            "menge_einheit": p.menge_einheit if p else None,
            "herkunft": p.herkunft if p else None,
            "arbeitspreis": p.arbeitspreis if p else None,
            "grundpreis_monat": p.grundpreis_monat if p else None,
            "preis_je_menge": (round(p.betrag / p.menge, 4)
                               if p and p.menge else None),
            **_verteilung(p),
            **_zusammensetzung(p),
            "position_id": p.id if p else None,
            # CCLXXVIII: eine vorläufige (orange) Position wartet auf Bestätigung.
            "vorlaeufig": bool(p and p.vorlaeufig),
            "quelle_dokument_id": p.quelle_dokument_id if p else None,
            "beleg_monat": k.beleg_monat,
            # CCCLXIII — Anbieter/Gewerk der Kostenart (z. B. WWK, Zweckverband),
            # für den Tag in der Zeitraum-Zeile. Feld `lieferant` gibt es schon.
            # Die Kostenart-ID, damit sich der Anbieter dort setzen lässt.
            "anbieter": k.lieferant or "", "kostenart_id": k.id,
            # N189 — Pflicht/optional der Kostenart: steuert im Frontend das rote
            # Pflicht-Signal. Optionale Positionen ohne Betrag mahnen nicht.
            "optional": bool(k.optional),
            "zustand": "erledigt" if erledigt else ("offen" if p else "fehlt"),
        })
    # Positionen zu Kostenarten, die nicht im Katalog stehen, gehen sonst verloren.
    # CCCXCVI — ausgeblendete (inaktive) Kostenarten bleiben aber ausgeblendet,
    # auch wenn sie schon eine Position tragen (sonst käme die Zeile als Waise zurück).
    inaktiv = {k.name for k in arten if not k.aktiv}
    sichtbar = {k["kostenart"] for k in checkliste}
    for p in positionen:
        if p.kostenart in sichtbar or p.kostenart in inaktiv:
            continue
        checkliste.append({
            "kostenart": p.kostenart, "s35": p.s35,
            "erledigt": p.status == "erledigt", "betrag": p.betrag,
            "schluessel": p.schluessel, "nur_einheit": p.nur_einheit,
            "wertquelle": p.wertquelle,
            # N122 — Menge und Herkunft der Position (kWh extern/eigen).
            "menge": p.menge, "menge_einheit": p.menge_einheit,
            "herkunft": p.herkunft, "arbeitspreis": p.arbeitspreis,
            "grundpreis_monat": p.grundpreis_monat,
            # Der Durchschnittspreis ist abgeleitet: Betrag je Menge.
            "preis_je_menge": (round(p.betrag / p.menge, 4)
                               if p.menge else None),
            **_verteilung(p),
            **_zusammensetzung(p),
            "position_id": p.id,
            # CCLXXVIII: eine vorläufige (orange) Position wartet auf Bestätigung.
            "vorlaeufig": bool(p.vorlaeufig),
            "quelle_dokument_id": p.quelle_dokument_id,
            "beleg_monat": None,
            # Waisen-Positionen (aus einem Beleg, ohne Katalog-Eintrag) tragen
            # kein Pflicht/optional-Flag — sie gelten als Pflicht (Default).
            "optional": False,
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
        # CCCLVII — rechts stehen nur Einheiten, nie Partei- oder Bewohnernamen.
        # Jede Partei (Miete) und jeder Bewohner zählt über seine Miete zu einer
        # Einheit; ein Schlüssel, der schon ein Einheitsname ist (leerstehende
        # Einheit), bleibt; alles Unzuordenbare sammelt sich unter „Ohne Einheit"
        # (dieselbe Regel wie CCCXLI). So erscheint keine Einheit doppelt als
        # Einheit UND als Partei und kein Personenname als eigener Empfänger.
        einheit_kanon = {e.bezeichnung.strip().lower(): e.bezeichnung
                         for e in einheiten if (e.bezeichnung or "").strip()}

        def _miete_einheit(m) -> str:
            return (einheit_kanon.get((m.einheit or "").strip().lower())
                    or (m.einheit.strip() if (m.einheit or "").strip() else "Ohne Einheit"))

        partei_zu_einheit = {m.partei.strip(): _miete_einheit(m)
                             for m in mieten if (m.partei or "").strip()}
        miete_einheit = {m.id: _miete_einheit(m) for m in mieten}
        bewohner_zu_einheit = {b.name.strip(): miete_einheit.get(b.miete_id, "Ohne Einheit")
                               for b in bewohner if (b.name or "").strip()}

        def zu_einheit(schluessel: str) -> str:
            p = (schluessel or "").strip()
            if p in partei_zu_einheit:
                return partei_zu_einheit[p]
            if p in bewohner_zu_einheit:
                return bewohner_zu_einheit[p]
            if p.lower() in einheit_kanon:
                return einheit_kanon[p.lower()]
            return "Ohne Einheit"

        gewichte = {}
        for k in checkliste:
            if not k["erledigt"]:
                continue
            # CCCLIX — ein Vorab-Anteil geht direkt auf seine Einheit; nur der
            # Rest (Betrag − Vorab) wird über den Schlüssel verteilt.
            vorab = k.get("vorab_betrag") or 0
            veinheit = (k.get("vorab_einheit") or "").strip()
            if vorab > 0 and veinheit:
                ziel = zu_einheit(veinheit)
                gewichte[ziel] = gewichte.get(ziel, 0.0) + vorab
            rest = (k["betrag"] or 0) - (vorab if veinheit else 0)
            gesamt_anteil = sum(k["anteile"].values()) or 1
            for partei, anteil in (k["anteile"] or {}).items():
                ziel = zu_einheit(partei)
                gewichte[ziel] = gewichte.get(ziel, 0.0) + \
                    rest * anteil / gesamt_anteil
        for ziel, betrag in sorted(gewichte.items(), key=lambda p: -p[1]):
            knoten.append({"name": ziel, "spalte": 2})
            fluss.append({"von": 0, "nach": len(knoten) - 1, "wert": round(betrag, 2)})

    return {
        "id": z.id, "objekt": o.slug, "objekt_name": o.name,
        # CCVIII: ist das Objekt Teil einer WEG, verteilt die Hausverwaltung —
        # die Abrechnungsseite bietet dann den Mieter-Direkteintrag an, statt
        # selbst über einen Schlüssel zu verteilen.
        "weg": bool(o.weg),
        # N213 — Objektmodell (`standard` | `laufer_spezial`); die
        # Zeitraumseite blendet Laufer-spezifische Blöcke (Stromkette, HKV,
        # Wärmemengenverteilung) für andere Objekte aus.
        "modell": o.modell or "standard",
        "label": f"{z.start:%d.%m.%Y} – {z.ende:%d.%m.%Y}",
        # N34 — das Jahr des Zeitraums (Jahr mit den meisten Tagen), für Titel
        # „Abrechnungszeitraum <Jahr> · von–bis" und die jahr-basierte Zuordnung.
        "jahr": zeitraum_label_jahr(z.start, z.ende),
        "start": z.start.isoformat(), "ende": z.ende.isoformat(),
        "typ": z.typ, "status": z.status,
        # N71 — ein leerer Zeitraum (0 Kostenpositionen) trägt keine Frist.
        "frist_tage": (frist_tage(z) if z.status == "in Arbeit"
                       and positionen else None),
        "fortschritt": {"fertig": fertig, "gesamt": len(checkliste),
                        "summe": round(summe_erledigt, 2)},
        # Was an diesem Zeitraum wirklich hängt. Ist alles null, gilt er als
        # leer und wird automatisch entfernt — kein Löschknopf nötig.
        "verknuepft": {"positionen": len(positionen), "belege": len(dokumente),
                       "vorauszahlungen": len(vzs)},
        "checkliste": checkliste,
        "sankey": {"knoten": knoten, "fluss": fluss},
        # N108 (Fund 12) — Betrag, Kostenart und Groesse gehoeren mit: ohne sie
        # verglich die Duplikat-Pruefung im Beleg-Dialog `undefined` mit
        # `undefined` und hielt jeden beliebigen Beleg fuer das Doppel.
        "dokumente": [{"id": d.id, "dateiname": d.dateiname, "pfad": d.pfad,
                       "kategorie": d.kategorie, "betrag": d.betrag,
                       "kostenart": d.kostenart, "groesse": d.groesse}
                      for d in dokumente],
        "belege_je_art": belege,
        "vorauszahlungen": [{"partei": v.partei, "betrag": v.betrag} for v in vzs],
    }
