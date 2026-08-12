"""N79 — Heizöl-Bestand und FIFO-Bewertung des Verbrauchs.

Heizöl wird getankt, nicht abgelesen: der Nutzer erfasst mehrere Lieferungen
(Liter + Gesamtpreis + Datum) und einen Anfangsbestand. Der Verbrauch einer
Abrechnungsperiode (in Litern) wird nach dem FIFO-Prinzip bewertet — das
**älteste Öl zuerst**. So entstehen zwei Zahlen: die Kosten des in der Periode
verbrauchten Öls (der Heizkosten-Betrag der Periode) und der Restbestand
(Liter + Wert) danach.

Der Modul ist rein und testbar: er kennt keine Datenbank, sondern rechnet auf
einer Liste von Lieferungen. Eine Lieferung ist alles, was `datum`, `liter`,
`wert` und (optional) `id` als Attribut ODER als dict-Schlüssel trägt — so
funktionieren Modell-Instanzen (`models.Heizoellieferung`) und einfache
Testobjekte gleichermassen.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Any

log = logging.getLogger("immocalc")


def _feld(lieferung: Any, name: str, vorgabe: Any = None) -> Any:
    """Liest ein Feld aus Attribut oder dict-Schlüssel — je nachdem, was da ist."""
    if isinstance(lieferung, dict):
        return lieferung.get(name, vorgabe)
    return getattr(lieferung, name, vorgabe)


def _sortierschluessel(lieferung: Any) -> tuple:
    """FIFO-Ordnung: nach Datum, bei gleichem Datum nach id (frühe zuerst).

    Ein fehlendes Datum gilt als „ganz früh" (date.min) — so verdrängt eine
    unvollständige Zeile die echten Lieferungen nicht ans Ende der Schlange.
    Eine fehlende id sortiert als 0, damit die Ordnung stabil bleibt."""
    datum = _feld(lieferung, "datum") or date.min
    ident = _feld(lieferung, "id") or 0
    return (datum, ident)


def gesamtbestand(lieferungen: list) -> dict:
    """Aktueller Gesamtbestand ohne Verbrauch: Summe Liter und Wert.

    Der Durchschnittspreis ist informativ (Gesamtwert ÷ Gesamtliter); bewertet
    wird ein Verbrauch NICHT mit ihm, sondern FIFO (`verbrauch_bewerten`)."""
    liter = round(sum(float(_feld(l, "liter", 0) or 0) for l in lieferungen), 3)
    wert = round(sum(float(_feld(l, "wert", 0) or 0) for l in lieferungen), 2)
    preis = round(wert / liter, 4) if liter > 0 else 0.0
    return {"bestand_liter": liter, "bestand_wert": wert, "preis_schnitt": preis}


def verbrauch_bewerten(lieferungen: list, verbrauch_liter: float) -> dict:
    """Bewertet einen Liter-Verbrauch FIFO — das älteste Öl zuerst.

    Die Lieferungen werden nach Datum (dann id) aufsteigend sortiert; der
    Verbrauch wird von der ältesten Lieferung an abgezogen, jede Teilmenge zum
    Einstandspreis ihrer Lieferung (`wert / liter`) bewertet.

    Rückgabe (dict):
      * `verbrauch_liter`  — tatsächlich verbrauchte Liter (auf den Bestand
                             gedeckelt; bei Überschreitung < angefragt).
      * `verbrauch_kosten` — Kosten des verbrauchten Öls in € (2 Stellen).
      * `rest_liter`       — Restbestand in Litern nach der Periode.
      * `rest_wert`        — Wert des Restbestands in € (2 Stellen).
      * `preis_schnitt`    — Schnittpreis des Verbrauchs (€/L, 4 Stellen).
      * `warnung`          — nur gesetzt, wenn der Verbrauch den Bestand
                             übersteigt (Text mit der Fehlmenge).

    Cent-sauber: `verbrauch_kosten + rest_wert == round(Σ Lieferungswerte, 2)`.
    Der Rundungsrest wird dem Restwert zugeschlagen, damit die Summe stimmt.

    Randfälle: kein Bestand → alles 0. Verbrauch ≤ 0 → Kosten 0, Rest = Gesamt.
    Verbrauch > Bestand → alles verbraucht, Rest 0, `warnung` gesetzt."""
    alle = sorted(lieferungen, key=_sortierschluessel)
    # N368 — eine Lieferung ohne Litermenge zählt gar nicht mit. Vorher steckte
    # ihr Wert in `gesamt_wert`, die FIFO-Schleife übersprang sie aber (`liter
    # <= 0: continue`) — ihr Betrag konnte also nie im Restwert landen und
    # wanderte über `verbrauch_kosten = gesamt_wert − rest_wert` vollständig in
    # die Verbrauchskosten. Eine erfasste Rechnung, deren Litermenge noch fehlt
    # (der Normalfall beim Eintragen), belastete die Periode damit voll.
    geordnet = [l for l in alle if float(_feld(l, "liter", 0) or 0) > 0]
    ohne_liter = [l for l in alle
                  if float(_feld(l, "liter", 0) or 0) <= 0
                  and abs(float(_feld(l, "wert", 0) or 0)) > 0.005]
    gesamt_liter = round(sum(float(_feld(l, "liter", 0) or 0) for l in geordnet), 6)
    gesamt_wert = round(sum(float(_feld(l, "wert", 0) or 0) for l in geordnet), 6)

    # Angefragten Verbrauch bändigen: nie negativ, nie mehr als der Bestand.
    angefragt = max(0.0, float(verbrauch_liter or 0))
    verbraucht = min(angefragt, gesamt_liter)

    ergebnis: dict = {}
    warnungen: list[str] = []
    if angefragt > gesamt_liter + 1e-9:
        fehlmenge = round(angefragt - gesamt_liter, 3)
        warnungen.append(f"Verbrauch übersteigt Bestand um {fehlmenge:g} L")
    if ohne_liter:
        # Bedienbar statt stumm: der Nutzer sieht, welcher Betrag noch nicht
        # zählt und warum — die Litermenge fehlt einfach noch.
        summe = round(sum(float(_feld(l, "wert", 0) or 0) for l in ohne_liter), 2)
        warnungen.append(
            f"{len(ohne_liter)} Lieferung(en) über {summe:.2f} € ohne "
            f"Litermenge — sie zählen erst mit, wenn die Menge nachgetragen ist")
    if warnungen:
        ergebnis["warnung"] = " · ".join(warnungen)

    # FIFO: vom ältesten Öl an abziehen. Der Restwert ergibt sich aus den
    # Litern, die in den Lieferungen liegen bleiben — je zu ihrem eigenen Preis.
    offen = verbraucht
    rest_wert_roh = 0.0
    for l in geordnet:
        liter = float(_feld(l, "liter", 0) or 0)
        wert = float(_feld(l, "wert", 0) or 0)
        if liter <= 0:
            continue
        preis = wert / liter
        entnommen = min(offen, liter) if offen > 0 else 0.0
        offen -= entnommen
        rest_in_lieferung = liter - entnommen
        rest_wert_roh += rest_in_lieferung * preis

    # Cent-sauber ableiten: Verbrauch = Gesamt − Rest, dann runden, den
    # Rundungsrest bekommt der Restwert (Summe bleibt exakt der Gesamtwert).
    verbrauch_kosten_roh = gesamt_wert - rest_wert_roh
    verbrauch_kosten = round(verbrauch_kosten_roh, 2)
    gesamt_wert_ct = round(gesamt_wert, 2)
    rest_wert = round(gesamt_wert_ct - verbrauch_kosten, 2)

    rest_liter = round(gesamt_liter - verbraucht, 3)
    preis_schnitt = round(verbrauch_kosten / verbraucht, 4) if verbraucht > 0 else 0.0

    ergebnis.update({
        "verbrauch_liter": round(verbraucht, 3),
        "verbrauch_kosten": verbrauch_kosten,
        "rest_liter": rest_liter,
        "rest_wert": rest_wert,
        "preis_schnitt": preis_schnitt,
    })
    return ergebnis
