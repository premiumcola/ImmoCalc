"""N273 — der WEG-Modus einer Nebenkostenabrechnung.

Liegt die vermietete Einheit in einer Wohnungseigentümergemeinschaft, rechnet
nicht der Vermieter ab, sondern die Messfirma. Er bekommt **eine fertige
Einzelabrechnung** und reicht sie an den Mieter weiter. Damit fällt der ganze
übliche Weg weg: keine eigenen Rechnungen, keine Zähler, keine Belegjagd — nur
noch eine Dateiübernahme.

Die drei Regeln, auf denen dieses Modul steht:

1.  **Der Block „Nicht umlagefähig" darf nie auf den Mieter.** Instandhaltung,
    Anschaffungen und Schädlingsbekämpfung trägt die Eigentümergemeinschaft.
    Solche Positionen entstehen hier gar nicht erst als `Kostenposition`; sie
    bleiben im aufbewahrten Beleg stehen und werden nur *gezeigt*. Eine einmal
    angelegte Kostenposition wäre sonst irgendwann verteilt — und der Fehler
    fiele erst dem Mieter auf.
2.  **Die übernommenen Positionen gehen in die bestehende `Kostenposition`.**
    Eine eigene Tabelle bliebe für die Engine unsichtbar, die Abrechnung würde
    an ihr vorbeirechnen. Erkennbar sind sie an `wertquelle == "WEG"` — daran
    hängt auch die Idempotenz und die Anzeige „nicht editierbar".
3.  **Von Hand gepflegte Positionen bleiben unangetastet.** Eine Übernahme
    fasst ausschließlich ihre eigenen WEG-Zeilen an.

Die Vorauszahlung wird monatsgenau aus Abschnitten gerechnet
(`WegVorauszahlung`) — ein halbes Jahr kann höher gezahlt worden sein als das
andere. Der Saldo folgt der Schreibweise des Belegs: **negativ = Nachzahlung
des Mieters, positiv = Guthaben**.
"""
from __future__ import annotations

import calendar
import logging
from datetime import date
from typing import Optional

from sqlmodel import Session, select

from .belegposten import anlegen as position_bauen
from .models import Dokument, Kostenposition, WegVorauszahlung, Zeitraum
from .verteilung import VORGABE, ableiten, ableiten_einheit

log = logging.getLogger("immocalc")

# Woran eine übernommene Position erkennbar ist. Die Oberfläche zeigt sie
# dadurch als „kommt aus der WEG-Abrechnung" und lässt sie nicht bearbeiten —
# geändert wird am Papier, nicht an der Kopie.
QUELLE = "WEG"

# Heiz- und Warmwasserkosten stehen auf dem Beleg auf einem eigenen Blatt und
# sind KEINE Betriebskostenposition. Sie bekommen deshalb eigene Zeilen mit
# diesen Namen.
HEIZKOSTEN = "Heizkosten"
WARMWASSER = "Warmwasser"


def _geld(wert) -> float:
    """Ein Betrag auf den Cent — und nie None, damit nichts weiterrechnet."""
    try:
        return round(float(wert or 0.0), 2)
    except (TypeError, ValueError):
        return 0.0


# --------------------------------------------------------------------------
# Was aus dem gelesenen Beleg eine Kostenposition wird — und was nicht.
# --------------------------------------------------------------------------
def umlagefaehige(gelesen: dict) -> list[dict]:
    """Die Positionen, die auf den Mieter dürfen — als `{kostenart, betrag}`.

    Das sind die umlagefähigen Betriebskosten-Positionen (jeweils die Spalte
    „Ihre Kosten", nicht die Gesamtkosten der Liegenschaft) plus Heiz- und
    Warmwasserkosten als eigene Zeilen."""
    zeilen: list[dict] = []
    for p in (gelesen or {}).get("positionen") or []:
        if not isinstance(p, dict) or not p.get("umlagefaehig", True):
            continue
        name = str(p.get("bezeichnung") or "").strip()
        betrag = _geld(p.get("ihre_kosten"))
        if not name or not betrag:
            continue
        zeilen.append({"kostenart": name, "betrag": betrag,
                       "schluessel_text": str(p.get("schluessel") or "")})
    for name, feld in ((HEIZKOSTEN, "heizkosten"), (WARMWASSER, "warmwasserkosten")):
        betrag = _geld((gelesen or {}).get(feld))
        if betrag:
            zeilen.append({"kostenart": name, "betrag": betrag,
                           "schluessel_text": ""})
    return zeilen


def nicht_umlagefaehige(gelesen: dict) -> list[dict]:
    """Die Positionen aus dem Block „Nicht umlagefähig".

    Sie werden ausschließlich zurückgemeldet — nie angelegt."""
    zeilen: list[dict] = []
    for p in (gelesen or {}).get("positionen") or []:
        if not isinstance(p, dict) or p.get("umlagefaehig", True):
            continue
        name = str(p.get("bezeichnung") or "").strip()
        if not name:
            continue
        zeilen.append({"kostenart": name, "betrag": _geld(p.get("ihre_kosten")),
                       "gesamtkosten": _geld(p.get("gesamtkosten"))})
    return zeilen


# --------------------------------------------------------------------------
# Übernahme
# --------------------------------------------------------------------------
def _gewichte(session: Session, z: Zeitraum, einheit: str) -> dict[str, float]:
    """Die Anteile, mit denen eine WEG-Position auf die Parteien geht.

    Ist eine Einheit genannt, trägt sie den Posten zu 100 % — genau das ist der
    Regelfall: die WEG-Abrechnung gilt für GENAU die eine Wohnung des
    Vermieters. Ohne Angabe bleibt es beim Standardschlüssel des Hauses."""
    if einheit:
        return ableiten_einheit(session, z, einheit)
    return ableiten(session, z, VORGABE)


def _weg_positionen(session: Session, zid: int) -> list[Kostenposition]:
    return [p for p in session.exec(select(Kostenposition).where(
        Kostenposition.zeitraum_id == zid)).all() if p.wertquelle == QUELLE]


def uebernehmen(session: Session, z: Zeitraum, gelesen: dict,
                einheit: str = "") -> dict:
    """Legt aus dem bestätigten Beleg die Kostenpositionen an.

    **Idempotent**: ein zweiter Durchlauf schreibt dieselben WEG-Zeilen neu,
    statt sie zu verdoppeln. Zeilen, die im neuen Beleg nicht mehr vorkommen,
    verschwinden — aber nur die eigenen (`wertquelle == "WEG"`); eine von Hand
    gepflegte Position wird nie angefasst.

    Kollidiert eine WEG-Zeile mit einer Handeingabe gleichen Namens, gewinnt die
    Handeingabe und die WEG-Zeile wird übersprungen (eine Kostenart, eine Zeile
    — sonst stünde derselbe Posten zweimal in der Abrechnung). Der Nutzer
    erfährt das über `uebersprungen`, statt es zu erraten.
    """
    zeilen = umlagefaehige(gelesen)
    anteile = _gewichte(session, z, einheit)

    vorhanden = session.exec(select(Kostenposition).where(
        Kostenposition.zeitraum_id == z.id)).all()
    weg_alt = {p.kostenart: p for p in vorhanden if p.wertquelle == QUELLE}
    fremd = {p.kostenart for p in vorhanden if p.wertquelle != QUELLE}

    uebersprungen: list[str] = []
    behalten: set[str] = set()
    for zeile in zeilen:
        name = zeile["kostenart"]
        if name in fremd:
            uebersprungen.append(name)
            continue
        behalten.add(name)
        alt = weg_alt.get(name)
        if alt is not None:
            # Bestehende WEG-Zeile fortschreiben statt löschen und neu anlegen:
            # so bleiben angehängte Belege und die id erhalten.
            alt.betrag = zeile["betrag"]
            alt.anteile = anteile
            alt.nur_einheit = einheit
            alt.status = "erledigt" if zeile["betrag"] else "offen"
            session.add(alt)
            continue
        p = position_bauen(session, z, name, betrag=zeile["betrag"],
                           schluessel="individuell" if einheit else VORGABE,
                           wertquelle=QUELLE, anteile=anteile)
        p.nur_einheit = einheit
        # Die Gewichte kommen aus dem Beleg bzw. der genannten Einheit und
        # dürfen sich nicht bei jeder Stammdatenänderung neu ableiten.
        p.abgeleitet = not einheit
        session.add(p)

    # Was der neue Beleg nicht mehr nennt, war eine WEG-Zeile aus einem früheren
    # Lauf und ist jetzt gegenstandslos. Belege verlieren nur die Verknüpfung —
    # die Dateien in der Cloud bleiben unberührt.
    entfernt: list[str] = []
    for name, alt in weg_alt.items():
        if name in behalten:
            continue
        for d in session.exec(select(Dokument).where(
                Dokument.position_id == alt.id)).all():
            d.position_id = None
            session.add(d)
        session.delete(alt)
        entfernt.append(name)

    # Den Beleg unverändert aufbewahren: er trägt die nicht umlagefähigen
    # Positionen, die es als Kostenposition bewusst nie gibt.
    z.weg_beleg = dict(gelesen or {})
    z.weg_modus = True
    session.add(z)
    session.commit()

    log.info("WEG-Abrechnung übernommen (Zeitraum %s): %d Positionen, "
             "%d übersprungen, %d entfallen",
             z.id, len(behalten), len(uebersprungen), len(entfernt))
    ergebnis = stand(session, z)
    ergebnis["uebersprungen"] = uebersprungen
    ergebnis["entfernt"] = entfernt
    return ergebnis


# --------------------------------------------------------------------------
# Vorauszahlung — monatsgenau aus Abschnitten
# --------------------------------------------------------------------------
def _monate(von: date, bis: date) -> float:
    """Wie viele Monate zwischen zwei Tagen liegen — anteilig gerechnet.

    Ein voller Kalendermonat zählt exakt 1,0 (auch der Februar mit 28 Tagen),
    ein angebrochener nach seinem Tagesanteil. So ergeben 01.01.–30.06. genau
    6,0 Monate, und ein Mietbeginn zur Monatsmitte kippt die Summe nicht."""
    if bis < von:
        return 0.0
    summe = 0.0
    jahr, monat = von.year, von.month
    while (jahr, monat) <= (bis.year, bis.month):
        tage = calendar.monthrange(jahr, monat)[1]
        anfang = max(von, date(jahr, monat, 1))
        ende = min(bis, date(jahr, monat, tage))
        if ende >= anfang:
            summe += ((ende - anfang).days + 1) / tage
        monat += 1
        if monat > 12:
            jahr, monat = jahr + 1, 1
    return summe


def _spanne(v: WegVorauszahlung, z: Zeitraum) -> tuple[date, date]:
    """Die Geltungsspanne eines Abschnitts, auf den Zeitraum beschnitten.

    Ohne eigene Grenzen gilt der Abschnitt für den ganzen Zeitraum — der
    häufige Fall „das ganze Jahr 244 € im Monat" braucht dann keine Daten."""
    von = max(v.von or z.start, z.start)
    bis = min(v.bis or z.ende, z.ende)
    return von, bis


def vorauszahlung(session: Session, z: Zeitraum) -> float:
    """Was der Mieter im Zeitraum vorausgezahlt hat — monatsgenau.

    Summe über alle Abschnitte: Monatsbetrag × Monate im Zeitraum. Sechs Monate
    à 220 € und sechs à 235 € ergeben 2.730 €."""
    summe = 0.0
    for v in session.exec(select(WegVorauszahlung).where(
            WegVorauszahlung.zeitraum_id == z.id)).all():
        von, bis = _spanne(v, z)
        summe += (v.betrag_monat or 0.0) * _monate(von, bis)
    return round(summe, 2)


def abschnitte(session: Session, z: Zeitraum) -> list[dict]:
    """Die Abschnitte samt gerechneter Monatszahl und Teilsumme — damit die
    Oberfläche die Herleitung zeigen kann, statt nur eine Endsumme."""
    reihe = []
    for v in session.exec(select(WegVorauszahlung)
                          .where(WegVorauszahlung.zeitraum_id == z.id)
                          .order_by(WegVorauszahlung.id)).all():
        von, bis = _spanne(v, z)
        monate = round(_monate(von, bis), 4)
        reihe.append({"id": v.id, "einheit": v.einheit,
                      "von": v.von.isoformat() if v.von else None,
                      "bis": v.bis.isoformat() if v.bis else None,
                      "betrag_monat": _geld(v.betrag_monat),
                      "monate": monate,
                      "summe": _geld((v.betrag_monat or 0.0) * monate)})
    return reihe


# --------------------------------------------------------------------------
# Stand
# --------------------------------------------------------------------------
def stand(session: Session, z: Zeitraum) -> dict:
    """Der WEG-Stand eines Zeitraums.

    `saldo` folgt der Schreibweise des Belegs: **negativ = Nachzahlung des
    Mieters, positiv = Guthaben**. Er ergibt sich aus der Vorauszahlung minus
    dem Rechnungsbetrag; der Rechnungsbetrag ist die Summe der übernommenen
    (umlagefähigen) Positionen — nicht die Gesamtkosten der Liegenschaft."""
    positionen = sorted(_weg_positionen(session, z.id), key=lambda p: p.id or 0)
    umlagefaehig_summe = round(sum(p.betrag or 0.0 for p in positionen), 2)
    nicht = nicht_umlagefaehige(z.weg_beleg or {})
    vz = vorauszahlung(session, z)
    beleg = z.weg_beleg or {}
    return {
        "umlagefaehig_summe": umlagefaehig_summe,
        "nicht_umlagefaehig_summe": round(sum(p["betrag"] for p in nicht), 2),
        "vorauszahlung_summe": vz,
        "saldo": round(vz - umlagefaehig_summe, 2),
        "positionen": [{"id": p.id, "kostenart": p.kostenart,
                        "betrag": _geld(p.betrag), "wertquelle": p.wertquelle,
                        "nur_einheit": p.nur_einheit, "status": p.status}
                       for p in positionen],
        "nicht_umlagefaehig": nicht,
        "warnung": str(beleg.get("warnung") or ""),
        "beleg": {k: beleg.get(k) for k in
                  ("firma", "liegenschaft", "nutzer_nr", "von", "bis", "datum")},
    }


def vorauszahlung_setzen(session: Session, z: Zeitraum, einheit: str,
                         von: Optional[date], bis: Optional[date],
                         betrag_monat: float,
                         vid: Optional[int] = None) -> WegVorauszahlung:
    """Legt einen Abschnitt an oder ändert ihn. Ohne `vid` entsteht ein neuer."""
    v = session.get(WegVorauszahlung, vid) if vid else None
    if v is None:
        v = WegVorauszahlung(zeitraum_id=z.id)
    v.einheit = einheit
    v.von = von
    v.bis = bis
    v.betrag_monat = _geld(betrag_monat)
    session.add(v)
    session.commit()
    session.refresh(v)
    return v
