"""N83 — Strom/PV-Subsystem: Stromkosten je Verbrauchsgruppe und PV-Ertrag.

Strom ist zu vielschichtig für einen einzigen Betrag. Diese Engine rechnet —
rein und testbar, ohne Datenbank — die drei Teile, die die Excel
`NK-ALL-Strom-Verbrauch` vorgibt:

**1) Zwei Verbrauchsgruppen aus drei Zählerständen.**
Drei Stände werden abgelesen: der *Gesamtverbrauch* des Hauses (Stromzähler
666), der *Zwischenzähler WG/Haus* (die beiden Wohnungen EG + 1.OG) und die
*Garage*. Was übrig bleibt, ist Büro + Studio:

    buero_kwh = gesamt_kwh − wg_kwh − garage_kwh

So entstehen die zwei Gruppen, auf die alles verteilt wird:
**WG** (Wohnungen) und **Büro/Studio**.

**2) Bezugsquellen Netz / Solar / Akku auf die Gruppen aufteilen.**
Der Strom kommt aus drei Quellen mit je eigenem €/kWh: **Netz** (Zukauf),
**Solar** (Direktverbrauch) und **Akku**. Menge und Kosten jeder Quelle werden
im Verhältnis der beiden Gruppen aufgeteilt. Das Verhältnis ist entweder fest
vorgegeben (`wg_anteil_prozent` — die Excel nutzt grob WG 60 % / Büro 40 %
„ohne Tanken") oder wird aus den gemessenen kWh abgeleitet, wobei der
E-Auto-Ladestrom (`tanken_kwh`) vorher aus der Büro-Seite herausgerechnet wird.

**3) PV-Anlage: Ertrag und Verteilung auf die Eigentümer.**
Der PV-Ertrag ist Einspeisevergütung + ersparter Zukauf durch Eigenverbrauch:

    eigenverbrauch_kwh = pv_produktion_kwh − einspeisung_kwh
    einspeiseverguetung = einspeisung_kwh × satz(kwp)
    ersparnis           = eigenverbrauch_kwh × netz_preis
    ertrag              = einspeiseverguetung + ersparnis

Der Vergütungssatz folgt den EEG-Stufen (0–10 kWp: 8,2 ct, 10–40 kWp: 7,1 ct)
als mit der Anlagengröße gemischter Satz. Ertrag *und* Anschaffung der Anlage
werden cent-genau auf die Eigentümer verteilt (Vorgabe 5/6 + 1/6).

**4) Von der Gruppe zur Einheit (N89).**
Zwei Gruppen sind noch keine Abrechnung: die Nebenkostenabrechnung braucht
einen Betrag je *Immobilien-Einheit*. Wer zu welcher Gruppe gehört, sagen die
Felder `wg_einheiten` und `buero_einheiten` (je eine komma-separierte Liste von
Einheiten-Bezeichnungen). Die Gruppenkosten werden gleichmäßig und cent-genau
auf die zugeordneten Einheiten verteilt — es gilt

    Σ einheiten.kosten == Σ gruppen.kosten == quellen_kosten_gesamt

(sofern beide Gruppen zugeordnet sind; ist nur eine zugeordnet, deckt der Block
nur deren Kosten ab). Fehlt die Zuordnung ganz, bleibt `einheiten` leer und
alles rechnet wie bisher.

Der Modul ist rein: er kennt keine Datenbank, sondern liest die Eingaben aus
einem Objekt mit Attributen ODER einem dict (wie `models.Stromjahr` bzw. ein
Testobjekt) und gibt ein verschachteltes Ergebnis-dict zurück. Cent-Summen
stimmen über `engine.verteile_nach_wert`.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from .engine import verteile_nach_wert

log = logging.getLogger("immocalc")

# EEG-Einspeisevergütung (Teileinspeisung, ct/kWh) nach Anlagengröße. Der Satz
# gilt anteilig je Leistungsstufe; der effektive Satz einer Anlage ist der mit
# ihrer kWp gemischte Wert (siehe `einspeise_satz_ct`).
_STUFE_KLEIN_KWP = 10.0
_STUFE_GROSS_KWP = 40.0
_SATZ_KLEIN_CT = 8.2      # 0–10 kWp
_SATZ_GROSS_CT = 7.1      # 10–40 kWp (und darüber, vereinfacht)

# Namen der beiden Verbrauchsgruppen — überall gleich, damit die Oberfläche
# sich darauf verlassen kann.
GRUPPE_WG = "WG"
GRUPPE_BUERO = "Büro/Studio"

# Vorgabe-Eigentümeranteile der PV-Anlage: 5/6 und 1/6.
EIGENTUEMER_ANTEILE: tuple[tuple[str, float], ...] = (("5/6", 5.0), ("1/6", 1.0))

_QUELLEN = ("netz", "solar", "akku")


def _feld(daten: Any, name: str, vorgabe: float = 0.0) -> float:
    """Liest ein Zahlenfeld aus Attribut oder dict-Schlüssel und macht daraus
    einen float. Fehlt es oder ist es unlesbar, gilt die Vorgabe (meist 0)."""
    wert = daten.get(name, vorgabe) if isinstance(daten, dict) \
        else getattr(daten, name, vorgabe)
    try:
        return float(wert if wert is not None else vorgabe)
    except (ValueError, TypeError):
        return float(vorgabe)


def _text(daten: Any, name: str, vorgabe: str = "") -> Any:
    """Liest ein Textfeld aus Attribut oder dict-Schlüssel (wie `_feld`, nur
    ohne Zahlenwandlung — der Wert kommt roh zurück, damit auch eine fertige
    Liste durchgereicht werden kann). `None`/fehlend ergibt die Vorgabe."""
    wert = daten.get(name, vorgabe) if isinstance(daten, dict) \
        else getattr(daten, name, vorgabe)
    return vorgabe if wert is None else wert


def einheiten_liste(roh: Any) -> list[str]:
    """Eine Zuordnungsangabe zu einer sauberen Liste von Bezeichnungen machen.

    Angenommen wird eine komma-separierte Zeichenkette („EG, 1.OG") oder eine
    fertige Liste. Leerraum fällt weg, leere Einträge fallen weg, Dubletten
    fallen weg — die Reihenfolge der ersten Nennung bleibt erhalten."""
    if not roh:
        return []
    teile = roh if isinstance(roh, (list, tuple)) else str(roh).split(",")
    namen: list[str] = []
    for t in teile:
        name = str(t).strip()
        if name and name not in namen:
            namen.append(name)
    return namen


def _gleichmaessig(menge: float, anzahl: int, stellen: int = 3) -> list[float]:
    """Eine Menge gleichmäßig auf `anzahl` Empfänger aufteilen, ohne dass durch
    das Runden etwas verloren geht: gerechnet wird in ganzen Einheiten der
    letzten Stelle, der Rest geht der Reihe nach an die vorderen Empfänger."""
    if anzahl <= 0:
        return []
    faktor = 10 ** stellen
    ziel = round(float(menge) * faktor)
    basis, rest = divmod(ziel, anzahl)
    werte = [basis] * anzahl
    for i in range(rest):
        werte[i] += 1
    return [w / faktor for w in werte]


def verteile_auf_einheiten(gruppen: dict[str, dict],
                           zuordnung: dict[str, list[str]]) -> list[dict]:
    """N89 — die Gruppenkosten auf die zugeordneten Einheiten herunterbrechen.

    `gruppen` ist der Gruppenblock aus `rechne` ({Gruppe: {kwh, kosten, …}}),
    `zuordnung` sagt, welche Einheiten-Bezeichnungen zu welcher Gruppe gehören.
    Innerhalb einer Gruppe wird gleichmäßig geteilt — die Kosten cent-genau über
    `verteile_nach_wert` (Größte-Reste), damit die Summe der Einheiten exakt der
    Gruppensumme entspricht; die kWh entsprechend auf drei Stellen.

    Rückgabe: [{"name", "gruppe", "kwh", "kosten"}] in der Reihenfolge der
    Gruppen und innerhalb einer Gruppe in der Reihenfolge der Nennung. Gruppen
    ohne Zuordnung liefern keine Zeilen."""
    zeilen: list[dict] = []
    for gruppe, namen in zuordnung.items():
        if not namen:
            continue
        werte = gruppen.get(gruppe, {})
        kosten = verteile_nach_wert(float(werte.get("kosten", 0.0)),
                                    {n: 1.0 for n in namen})
        mengen = _gleichmaessig(float(werte.get("kwh", 0.0)), len(namen))
        zeilen.extend(
            {"name": name, "gruppe": gruppe, "kwh": kwh,
             "kosten": kosten.get(name, 0.0)}
            for name, kwh in zip(namen, mengen))
    return zeilen


def nk_positionen(rechnung: dict) -> dict:
    """N89 — das Rechenergebnis auf das eindampfen, was die
    Nebenkostenabrechnung braucht: je Einheit ein Betrag.

    Rückgabe: `positionen` ([{einheit, betrag, kwh}]), `gesamt` (Summe der
    Beträge), `kwh_gesamt` und die `warnungen` der Rechnung — damit die
    Oberfläche einen Ablesefehler nicht stillschweigend übernimmt."""
    positionen = [{"einheit": z["name"], "betrag": z["kosten"], "kwh": z["kwh"]}
                  for z in rechnung.get("einheiten", [])]
    return {
        "positionen": positionen,
        "gesamt": round(sum(p["betrag"] for p in positionen), 2),
        "kwh_gesamt": round(sum(p["kwh"] for p in positionen), 3),
        "warnungen": rechnung.get("warnungen", []),
    }


def buero_kwh(gesamt: float, wg: float, garage: float) -> float:
    """Der Rest-Verbrauch Büro + Studio = Gesamt − WG/Haus − Garage.

    Nie negativ: weisen die Unterzähler zusammen mehr aus als der Gesamtzähler,
    ist das ein Ablesefehler — der Rest wird auf 0 geklemmt (der Aufrufer setzt
    dazu eine Warnung)."""
    return round(max(0.0, float(gesamt) - float(wg) - float(garage)), 3)


def gruppen_anteil(wg: float, buero: float, tanken: float = 0.0,
                   wg_anteil_prozent: float = 0.0) -> float:
    """WG-Anteil am aufzuteilenden Strom als Faktor 0..1.

    Ist `wg_anteil_prozent` gesetzt (> 0), gilt dieser feste Split (die Excel
    trägt hier die „60 % ohne Tanken" ein). Sonst wird das Verhältnis aus den
    gemessenen kWh abgeleitet — der E-Auto-Ladestrom (`tanken`) wird vorher aus
    der Büro-Seite herausgerechnet, weil er nicht wie normaler Verbrauch geteilt
    werden soll. Fehlt jede Grundlage (alles 0), wird hälftig geteilt."""
    if wg_anteil_prozent and wg_anteil_prozent > 0:
        return max(0.0, min(1.0, wg_anteil_prozent / 100.0))
    buero_ohne_tanken = max(0.0, float(buero) - float(tanken))
    basis = float(wg) + buero_ohne_tanken
    if basis <= 0:
        return 0.5
    return max(0.0, min(1.0, float(wg) / basis))


def einspeise_satz_ct(kwp: float) -> float:
    """Effektiver EEG-Einspeisesatz in ct/kWh, mit der Anlagengröße gemischt.

    Bis 10 kWp gilt 8,2 ct, der Leistungsanteil 10–40 kWp bekommt 7,1 ct; der
    effektive Satz ist der leistungsgewichtete Mittelwert. Ohne kWp-Angabe (0)
    gilt der kleine Satz. Über 40 kWp wird der 7,1-ct-Satz vereinfacht
    fortgeschrieben."""
    p = float(kwp or 0)
    if p <= 0:
        return _SATZ_KLEIN_CT
    klein = min(p, _STUFE_KLEIN_KWP)
    gross = max(0.0, p - _STUFE_KLEIN_KWP)
    satz = (klein * _SATZ_KLEIN_CT + gross * _SATZ_GROSS_CT) / p
    return round(satz, 4)


def einspeiseverguetung(einspeisung_kwh: float, kwp: float = 0.0,
                        verguetung_eur: float = 0.0) -> tuple[float, float]:
    """Einspeisevergütung in € und der zugrunde liegende Satz in ct/kWh.

    Ist `verguetung_eur` vorgegeben (> 0), gilt dieser Betrag direkt (aus einer
    Jahresabrechnung des Netzbetreibers abgetippt); der zurückgegebene Satz ist
    dann der rechnerische ct/kWh (Betrag ÷ Menge). Sonst wird
    `einspeisung_kwh × satz(kwp)` gerechnet."""
    menge = max(0.0, float(einspeisung_kwh or 0))
    if verguetung_eur and verguetung_eur > 0:
        betrag = round(float(verguetung_eur), 2)
        satz = round(betrag / menge * 100, 4) if menge else 0.0
        return betrag, satz
    satz = einspeise_satz_ct(kwp)
    return round(menge * satz / 100.0, 2), satz


def verteile_eigentuemer(betrag: float,
                         anteile: tuple[tuple[str, float], ...] = EIGENTUEMER_ANTEILE
                         ) -> list[dict]:
    """Einen Betrag cent-genau auf die Eigentümer verteilen (Vorgabe 5/6 + 1/6).

    Nutzt `verteile_nach_wert` (Größte-Reste), damit die Summe der Anteile exakt
    dem Betrag entspricht. Gibt die Anteile in der vorgegebenen Reihenfolge
    zurück: [{"anteil": "5/6", "betrag": …}, …]."""
    gewichte = {label: gewicht for label, gewicht in anteile}
    verteilt = verteile_nach_wert(betrag, gewichte)
    return [{"anteil": label, "betrag": verteilt.get(label, 0.0)}
            for label, _ in anteile]


def _pv_anteile(daten: Any) -> tuple[tuple[str, float], ...]:
    """Die Eigentümer-Anteile der PV-Anlage (N87): eigene Tausendstel, unabhängig
    von den Objekt-Anteilen. Aus dem Feld `pv_anteile` (JSON {Name: ‰}); ist es
    leer/unlesbar, gilt die Vorgabe 5/6 + 1/6."""
    roh = daten.get("pv_anteile", "") if isinstance(daten, dict) \
        else getattr(daten, "pv_anteile", "")
    if roh:
        try:
            d = json.loads(roh) if isinstance(roh, str) else dict(roh)
            paare = tuple((str(k), float(v)) for k, v in d.items() if float(v) > 0)
            if paare:
                return paare
        except (ValueError, TypeError, AttributeError):
            log.warning("pv_anteile unlesbar — Vorgabe 5/6+1/6")
    return EIGENTUEMER_ANTEILE


def pv_investitions_ertrag(rechnung: dict) -> float:
    """N87 — der jährliche Ertrag, der der PV-ANLAGE als Investment zufließt:
    was die Mieter für PV-Strom (**Solar + Akku**, NICHT Netzzukauf) an die
    Immobilie zahlen, PLUS die Einspeisevergütung. Der Eigenverbrauchs-
    „Ersparnis"-Posten ist kein Zahlungsfluss und zählt hier bewusst NICHT."""
    q = rechnung.get("quellen", {})
    intern = round(q.get("solar", {}).get("kosten", 0.0)
                   + q.get("akku", {}).get("kosten", 0.0), 2)
    extern = rechnung.get("pv", {}).get("einspeiseverguetung", 0.0)
    return round(intern + extern, 2)


def amortisation(jahre: list[dict], anschaffung: float) -> dict:
    """N87 — Amortisierung der PV-Anlage: der kumulierte Investitions-Ertrag über
    die Jahre gegen die Anschaffung. `jahre` = [{"jahr", "ertrag"}].

    Rückgabe: `reihe` (je Jahr {jahr, ertrag, kumuliert}), `anschaffung`,
    `kumuliert`, `rest` (noch nicht amortisiert), `amortisiert_prozent`,
    `break_even_jahr` (das Jahr, in dem der kumulierte Ertrag die Anschaffung
    erreicht, sonst None)."""
    anschaffung = round(float(anschaffung or 0), 2)
    reihe, kum, break_even = [], 0.0, None
    for j in sorted(jahre, key=lambda x: x.get("jahr", 0)):
        ertrag = round(float(j.get("ertrag", 0) or 0), 2)
        kum = round(kum + ertrag, 2)
        if break_even is None and anschaffung > 0 and kum >= anschaffung:
            break_even = j.get("jahr")
        reihe.append({"jahr": j.get("jahr"), "ertrag": ertrag, "kumuliert": kum})
    rest = round(max(0.0, anschaffung - kum), 2)
    prozent = round(min(100.0, kum / anschaffung * 100), 1) if anschaffung > 0 else None
    return {"anschaffung": anschaffung, "kumuliert": kum, "rest": rest,
            "amortisiert_prozent": prozent, "break_even_jahr": break_even,
            "reihe": reihe}


def rechne(daten: Any) -> dict:
    """Das vollständige Strom-/PV-Ergebnis eines Objekt-Jahres.

    `daten` ist ein Objekt mit Attributen ODER ein dict mit denselben Feldern
    (siehe `models.Stromjahr`). Rückgabe (dict):

      * `verbrauch`  — gesamt/wg/garage/buero/tanken in kWh.
      * `wg_anteil`, `buero_anteil` — die Aufteilungsfaktoren (Summe 1).
      * `quellen`    — je Quelle {kwh, preis, kosten}.
      * `quellen_kosten_gesamt` — Summe der Quellenkosten.
      * `gruppen`    — je Gruppe (WG, Büro/Studio) die auf sie entfallenden
                       kWh und € je Quelle plus Summen (`kwh`, `kosten`).
      * `einheiten`  — N89: die Gruppenkosten heruntergebrochen auf die
                       zugeordneten Einheiten ([{name, gruppe, kwh, kosten}]);
                       leer, solange `wg_einheiten`/`buero_einheiten` fehlen.
      * `pv`         — Produktion/Einspeisung/Eigenverbrauch, Satz, Vergütung,
                       Ersparnis, Ertrag, Anschaffung.
      * `eigentuemer`— Ertrag und Anschaffung je Eigentümer (5/6 + 1/6).
      * `warnungen`  — Liste von Hinweisen (Ablesefehler u. Ä.).

    Cent-Invarianten: die Gruppen-Kosten summieren sich exakt auf
    `quellen_kosten_gesamt`; die Einheiten-Kosten exakt auf ihre Gruppe; die
    Eigentümer-Anteile exakt auf Ertrag bzw. Anschaffung."""
    warnungen: list[str] = []

    gesamt = _feld(daten, "gesamt_kwh")
    wg = _feld(daten, "wg_kwh")
    garage = _feld(daten, "garage_kwh")
    tanken = _feld(daten, "tanken_kwh")
    buero = buero_kwh(gesamt, wg, garage)
    if gesamt - wg - garage < -0.001:
        warnungen.append(
            "WG- und Garagenzähler weisen zusammen mehr aus als der "
            "Gesamtzähler — Büro/Studio auf 0 gesetzt, bitte die Stände prüfen.")

    wg_anteil_prozent = _feld(daten, "wg_anteil_prozent")
    wg_anteil = gruppen_anteil(wg, buero, tanken, wg_anteil_prozent)
    buero_anteil = round(1.0 - wg_anteil, 6)
    wg_anteil = round(wg_anteil, 6)

    # Quellen: Menge, Preis, Kosten je Bezugsart.
    quellen: dict[str, dict] = {}
    for q in _QUELLEN:
        kwh = _feld(daten, f"{q}_kwh")
        preis = _feld(daten, f"{q}_preis")
        quellen[q] = {"kwh": round(kwh, 3), "preis": round(preis, 4),
                      "kosten": round(kwh * preis, 2)}
    quellen_kosten_gesamt = round(sum(q["kosten"] for q in quellen.values()), 2)
    # Plausibilität: was aus Netz/Solar/Akku kommt, muss ungefähr dem entsprechen,
    # was der Gesamtzähler ausweist (inkl. E-Auto-Ladung). Weicht es stark ab,
    # stimmt eine Eingabe nicht — lieber sagen als still falsch verteilen.
    quellen_kwh = round(sum(q["kwh"] for q in quellen.values()), 3)
    if gesamt > 0 and abs(quellen_kwh - gesamt) > max(50.0, gesamt * 0.05):
        warnungen.append(
            f"Netz+Solar+Akku ergeben {quellen_kwh:.0f} kWh, der Gesamtzähler "
            f"{gesamt:.0f} kWh — bitte die Mengen prüfen (Differenz "
            f"{quellen_kwh - gesamt:+.0f} kWh).")

    # Jede Quelle cent-genau auf die beiden Gruppen aufteilen; die Gruppensumme
    # ist die Summe ihrer Quellenanteile — so stimmt die Gesamtsumme exakt.
    gruppen: dict[str, dict] = {
        GRUPPE_WG: {"kwh": 0.0, "kosten": 0.0},
        GRUPPE_BUERO: {"kwh": 0.0, "kosten": 0.0},
    }
    verhaeltnis = {GRUPPE_WG: wg_anteil, GRUPPE_BUERO: buero_anteil}
    for q in _QUELLEN:
        kosten_split = verteile_nach_wert(quellen[q]["kosten"], verhaeltnis)
        for gruppe, faktor in verhaeltnis.items():
            k_kwh = round(quellen[q]["kwh"] * faktor, 3)
            k_kosten = kosten_split.get(gruppe, 0.0)
            gruppen[gruppe][f"{q}_kwh"] = k_kwh
            gruppen[gruppe][f"{q}_kosten"] = k_kosten
            gruppen[gruppe]["kwh"] = round(gruppen[gruppe]["kwh"] + k_kwh, 3)
            gruppen[gruppe]["kosten"] = round(
                gruppen[gruppe]["kosten"] + k_kosten, 2)

    # N89 — von der Gruppe zur Einheit: die Gruppenkosten gleichmäßig auf die
    # zugeordneten Einheiten. Ohne Zuordnung bleibt der Block leer.
    zuordnung = {
        GRUPPE_WG: einheiten_liste(_text(daten, "wg_einheiten")),
        GRUPPE_BUERO: einheiten_liste(_text(daten, "buero_einheiten")),
    }
    doppelt = sorted(set(zuordnung[GRUPPE_WG]) & set(zuordnung[GRUPPE_BUERO]))
    if doppelt:
        warnungen.append(
            "Diese Einheiten stehen in beiden Gruppen und bekommen deshalb "
            "zweimal einen Anteil: " + ", ".join(doppelt) + ".")
    einheiten = verteile_auf_einheiten(gruppen, zuordnung)

    # PV-Ertrag.
    produktion = _feld(daten, "pv_produktion_kwh")
    einspeisung = _feld(daten, "einspeisung_kwh")
    eigenverbrauch = round(max(0.0, produktion - einspeisung), 3)
    if einspeisung - produktion > 0.001:
        warnungen.append(
            "Einspeisung übersteigt die PV-Produktion — Eigenverbrauch auf 0 "
            "gesetzt, bitte die kWh prüfen.")
    kwp = _feld(daten, "pv_kwp")
    verguetung_eur = _feld(daten, "verguetung_eur")
    verguetung, satz_ct = einspeiseverguetung(einspeisung, kwp, verguetung_eur)
    netz_preis = quellen["netz"]["preis"]
    ersparnis = round(eigenverbrauch * netz_preis, 2)
    ertrag = round(verguetung + ersparnis, 2)
    anschaffung = round(_feld(daten, "anschaffung_eur"), 2)

    pv = {
        "produktion_kwh": round(produktion, 3),
        "einspeisung_kwh": round(einspeisung, 3),
        "eigenverbrauch_kwh": eigenverbrauch,
        "satz_ct": satz_ct,
        "einspeiseverguetung": verguetung,
        "eigenverbrauch_ersparnis": ersparnis,
        "ertrag": ertrag,
        "anschaffung": anschaffung,
    }

    # N89 — die E-Tankstelle hängt an der PV-Anlage: der geladene Strom wird der
    # ladenden Person zum vereinbarten Satz berechnet und fließt der Anlage zu
    # (nicht in die Gruppen-Verteilung, deshalb ist `tanken_kwh` dort heraus).
    tank_preis = _feld(daten, "tanken_preis")
    tankstelle = {
        "kwh": round(tanken, 3),
        "preis": round(tank_preis, 4),
        "betrag": round(tanken * tank_preis, 2),
        "person": (daten.get("tanken_person", "") if isinstance(daten, dict)
                   else getattr(daten, "tanken_person", "")) or "",
    }
    pv["tanken_ertrag"] = tankstelle["betrag"]

    # N87 — der Ertrag des PV-INVESTMENTS: was Mieter für PV-Strom zahlen
    # (Solar + Akku), die Einspeisevergütung und der Tank-Erlös. Das ist die
    # Grundlage der Amortisation — anders als `pv.ertrag`, der die kalkulatorische
    # Eigenverbrauchs-Ersparnis enthält (kein Zahlungsfluss).
    invest_ertrag = round(
        quellen["solar"]["kosten"] + quellen["akku"]["kosten"]
        + verguetung + tankstelle["betrag"], 2)
    pv["investitions_ertrag"] = invest_ertrag

    # Ertrag und Anschaffung je PV-Eigentümer (cent-genau, eigene ‰ oder 5/6+1/6).
    anteile = _pv_anteile(daten)
    eigentuemer = [
        {"anteil": e_ertrag["anteil"],
         "ertrag": e_ertrag["betrag"],
         "investitions_ertrag": e_inv["betrag"],
         "anschaffung": e_invest["betrag"]}
        for e_ertrag, e_inv, e_invest in zip(
            verteile_eigentuemer(ertrag, anteile),
            verteile_eigentuemer(invest_ertrag, anteile),
            verteile_eigentuemer(anschaffung, anteile))
    ]

    return {
        "verbrauch": {
            "gesamt_kwh": round(gesamt, 3),
            "wg_kwh": round(wg, 3),
            "garage_kwh": round(garage, 3),
            "buero_kwh": buero,
            "tanken_kwh": round(tanken, 3),
        },
        "wg_anteil": wg_anteil,
        "buero_anteil": buero_anteil,
        "quellen": quellen,
        "quellen_kosten_gesamt": quellen_kosten_gesamt,
        "gruppen": gruppen,
        "einheiten": einheiten,
        "pv": pv,
        "tankstelle": tankstelle,
        "eigentuemer": eigentuemer,
        "warnungen": warnungen,
    }
