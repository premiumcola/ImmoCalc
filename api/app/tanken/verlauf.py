"""Monatsverlauf der E-Tankstelle — Balken je Monat in den drei Blöcken Netz,
PV und Akku.

Grundlage der Übersicht auf der Seite. Ohne Datenbank — die Fetcher liegen in
:mod:`app.tanken.posten`. Die Anreicherung mit €-Kosten und km-Reichweite
(N188) sitzt darunter, weil sie Session und Nutzer braucht."""
from __future__ import annotations

from calendar import monthrange
from datetime import date

from sqlmodel import Session

from .. import eauto
from ..models import Objekt
from .nutzer import nutzer_lesen
from .perioden import MONATSKURZ, monatsfolge
from .satz import Satz, satz_ableiten
from .typen import Posten


def _prozent(teil: float, ganz: float) -> float | None:
    """Prozentanteil — ``None``, wenn es nichts zu teilen gibt.

    ``or 0.0`` fängt die negative Null ab: sie käme als „−0,0 %" auf die
    Seite und sähe aus wie ein Vorzeichenfehler."""
    return (round(teil / ganz * 100.0, 1) or 0.0) if ganz > 0 else None


def verlauf(posten: list[Posten], von: date, bis: date) -> list[dict]:
    """Je Monat: wie viel geladen wurde und in welchen Blöcken.

    Gefiltert wird über den Tag der Ladung (beide Ränder zählen). Kennt auch
    nur eine Ladung des Monats ihre Herkunft nicht, gilt die Aufteilung des
    Monats als unvollständig (`aufteilung: false`) — dann steht die Menge da,
    aber keine Prozentzahl, die niemand belegen kann. Kennt der Monat zwar
    Netz und eigen, aber nicht die Trennung PV/Akku, steht `dreiteilig` auf
    ``false``; das ist der Fall bei der aus Jahreswerten übertragenen
    Schätzung.

    kWh, die die Wallbox keinem Anteil zuordnet, zählen zum **PV-Block** und
    damit zum eigenen Strom (N143, Entscheidung des Nutzers). Sie stecken
    bereits in `pv_kwh`/`eigen_kwh`; `rest_kwh` sagt, wie viel auf diesem Weg
    dazukam. Ein eigener Topf „nicht zugeordnet" entsteht daraus nicht mehr —
    dafür gilt wieder ``Netz + eigen == geladen``."""
    eimer: dict[tuple[int, int], dict] = {
        (j, m): {"jahr": j, "monat": m, "kurz": MONATSKURZ[m - 1],
                 "label": f"{MONATSKURZ[m - 1]} {j}", "anzahl": 0, "kwh": 0.0,
                 "extern_kwh": 0.0, "eigen_kwh": 0.0, "pv_kwh": 0.0,
                 "speicher_kwh": 0.0, "rest_kwh": 0.0,
                 "aufteilung": True, "dreiteilig": True}
        for j, m in monatsfolge(von, bis)}

    for p in posten:
        if p.tag is None or not (von <= p.tag <= bis):
            continue
        eimer_monat = eimer.get((p.tag.year, p.tag.month))
        if eimer_monat is None:
            continue
        eimer_monat["kwh"] += p.kwh
        if p.kwh > 0:
            eimer_monat["anzahl"] += 1
        if p.extern_kwh is None or p.eigen_kwh is None:
            eimer_monat["aufteilung"] = False
            eimer_monat["dreiteilig"] = False
            continue
        eimer_monat["extern_kwh"] += p.extern_kwh
        eimer_monat["eigen_kwh"] += p.eigen_kwh
        eimer_monat["rest_kwh"] += p.rest_kwh
        if p.pv_kwh is None or p.speicher_kwh is None:
            eimer_monat["dreiteilig"] = False
        else:
            eimer_monat["pv_kwh"] += p.pv_kwh
            eimer_monat["speicher_kwh"] += p.speicher_kwh

    return [_monatszeile(eimer[s]) for s in monatsfolge(von, bis)]


def _monatszeile(m: dict) -> dict:
    """Ein gefüllter Eimer als Ausgabezeile — gerundet, mit Prozenten."""
    kwh = round(m["kwh"], 2)
    offen = not m["aufteilung"]
    grob = not m["dreiteilig"]

    def menge(name: str, unbekannt: bool) -> float | None:
        # `or 0.0` macht aus der negativen Null eine glatte 0 — „−0,00 kWh"
        # wäre eine Irritation ohne Aussage.
        return None if unbekannt else (round(m[name], 2) or 0.0)

    werte = {"extern_kwh": menge("extern_kwh", offen),
             "eigen_kwh": menge("eigen_kwh", offen),
             "rest_kwh": menge("rest_kwh", offen),
             "pv_kwh": menge("pv_kwh", grob),
             "speicher_kwh": menge("speicher_kwh", grob)}
    prozente = {name.replace("_kwh", "_prozent"):
                None if wert is None else _prozent(wert, kwh)
                for name, wert in werte.items()}
    return {**m, "kwh": kwh, **werte, **prozente}


def verlauf_summe(zeilen: list[dict]) -> dict:
    """Die Summenzeile unter dem Verlauf — mit denselben Regeln wie oben.

    Summiert werden die **angezeigten** Monatswerte, nicht die Rohdaten: eine
    Summe, die nicht der Summe der Zeilen darüber entspricht, sieht wie ein
    Rechenfehler aus. Gegenüber der ungerundeten Summe kann das um einen
    Hundertstel-kWh abweichen."""
    kwh = round(sum(z["kwh"] for z in zeilen), 2)
    vollstaendig = all(z["aufteilung"] for z in zeilen)
    dreiteilig = all(z["dreiteilig"] for z in zeilen)

    def summe(name: str, unbekannt: bool) -> float | None:
        return (None if unbekannt
                else (round(sum(z[name] or 0.0 for z in zeilen), 2) or 0.0))

    werte = {"extern_kwh": summe("extern_kwh", not vollstaendig),
             "eigen_kwh": summe("eigen_kwh", not vollstaendig),
             "rest_kwh": summe("rest_kwh", not vollstaendig),
             "pv_kwh": summe("pv_kwh", not dreiteilig),
             "speicher_kwh": summe("speicher_kwh", not dreiteilig)}
    prozente = {name.replace("_kwh", "_prozent"):
                None if wert is None else _prozent(wert, kwh)
                for name, wert in werte.items()}
    return {"anzahl": sum(z["anzahl"] for z in zeilen), "kwh": kwh,
            **werte, **prozente,
            "aufteilung": vollstaendig, "dreiteilig": dreiteilig}


def _verlauf_kosten_km(session: Session, o: Objekt, zeilen: list[dict],
                       summe: dict) -> tuple[list[dict], dict]:
    """Je Monatszeile (und in der Summe) die Ladekosten (€) und die Reichweite
    (km) ergänzen — beide additiv (N188).

    `kosten` = Netz-kWh × Netzsatz + Eigen-kWh × Eigensatz. Der Satz stammt aus
    der Abrechnungsperiode, in der der Monat liegt (`satz_ableiten`, N148), und
    wird je Monatsspanne gemerkt — Monate derselben Periode rechnen ihn nicht
    doppelt. Fehlt der Netzsatz (kein ableitbarer Satz) oder ist die Aufteilung
    des Monats unbekannt, bleibt `kosten` leer: **keine 0,00 € als Notnagel.**

    `km` sagt, wie weit die geladenen kWh ein typisches Fahrzeug der Station
    tragen. Ohne einen einzigen gepflegten Verbrauch bleibt sie leer. Der
    Stationsverbrauch wird einmal je Abfrage bestimmt.

    Die Summe addiert nur die belegten Monate; sie ist nur dann leer, wenn
    **jeder** Monat leer ist."""
    # Import spät, um einen Zyklus mit posten.py zu vermeiden — verlauf.py wird
    # von posten.py nicht gebraucht, aber die Anreicherung ruft in dessen
    # Nachbarschaft.
    from .posten import _stations_verbrauch

    verbrauch = _stations_verbrauch(nutzer_lesen(session, o))
    cache: dict[tuple[date, date], Satz] = {}

    def _satz(von: date, bis: date) -> Satz:
        if (von, bis) not in cache:
            cache[(von, bis)] = satz_ableiten(session, o.id, von, bis)
        return cache[(von, bis)]

    def _monatskosten(z: dict) -> float | None:
        extern, eigen = z.get("extern_kwh"), z.get("eigen_kwh")
        if extern is None or eigen is None:
            return None
        von = date(z["jahr"], z["monat"], 1)
        bis = date(z["jahr"], z["monat"], monthrange(z["jahr"], z["monat"])[1])
        satz = _satz(von, bis)
        if satz.netz is None or satz.grund:
            return None
        return round(extern * satz.netz + eigen * satz.eigen, 2)

    def _monatskm(z: dict) -> int | None:
        if verbrauch is None:
            return None
        km = eauto.gefahrene_km(z["kwh"], verbrauch)
        return None if km is None else round(km)

    for z in zeilen:
        z["kosten"] = _monatskosten(z)
        z["km"] = _monatskm(z)

    kosten = [z["kosten"] for z in zeilen if z["kosten"] is not None]
    km = [z["km"] for z in zeilen if z["km"] is not None]
    summe["kosten"] = round(sum(kosten), 2) if kosten else None
    summe["km"] = round(sum(km)) if km else None
    return zeilen, summe
