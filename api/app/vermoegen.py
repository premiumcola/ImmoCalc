"""Vermögensübersicht: was gehört mir, was schulde ich, was ist es wert.

Rechnet je Objekt und in Summe:
  Wert        — Verkehrswert, ersatzweise Kaufpreis
  Restschuld  — Summe der offenen Darlehen
  Guthaben    — Summe der Bausparguthaben
  Eigenkapital = Wert − Restschuld + Bausparguthaben
  Volumen     — investiertes Volumen (Kaufpreis)
  Beleihung   — Restschuld / Wert in Prozent

Fehlen Angaben, wird die Zeile trotzdem gezeigt — mit dem, was da ist. Ein
Objekt ohne Kredit hat schlicht keine Restschuld, das ist kein Fehler.

Der Stand eines Vertrags wird nicht geraten: eingetragen wird er zum 31.12.
eines Jahres — wie ein Zählerstand —, dazwischen schreibt
`stand_fortschreiben` bzw. `spar_fortschreiben` monatlich fort.

**Ein Bausparvertrag ist kein Darlehen** (CXLIX). Er läuft unter derselben
Überschrift, weil er an derselben Immobilie hängt und dieselbe Rate im Monat
kostet — gerechnet wird er aber umgekehrt:

  Darlehen         Restschuld sinkt · mindert das Eigenkapital · Zinslast
  Bausparvertrag   Guthaben wächst · erhöht das Eigenkapital · keine Zinslast

Ein Bausparguthaben in der Beleihungsquote aufzurechnen wäre falsch: die
Quote misst, wie stark das Objekt belastet ist, und das Guthaben liegt
daneben, nicht darin.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date

from .bezeichnung import objekt_titel
from .engine import verteile_nach_wert
from .models import ist_bausparer, ist_grundstueck
from .turnus import jahresbetrag
from .verteilung import _gesamtflaeche

log = logging.getLogger(__name__)


def _wert(objekt) -> float | None:
    """Verkehrswert schlägt Kaufpreis — er ist die aktuellere Angabe."""
    if objekt.verkehrswert:
        return float(objekt.verkehrswert)
    if objekt.kaufpreis:
        return float(objekt.kaufpreis)
    return None


# --------------------------------------------------------------------------
# N75 — Wertzuwachs & Gesamtrendite je Objekt
#
# Fachbegriffe (bestätigt über Homeday/Immo-Rechner):
#   • Wertsteigerung % p. a. = CAGR (Compound Annual Growth Rate) des
#     Objektwerts — die durchschnittliche jährliche Wertsteigerung.
#   • Gesamtrendite auf das Eigenkapital = (Wertzuwachs Ø/Jahr + Jahres-
#     Cashflow) ÷ eingesetztes Eigenkapital. Die reine Cashflow-Rendite
#     berücksichtigt nur die Miete; erst mit der Wertsteigerung ergibt sich
#     die „Gesamtrendite auf Eigenkapital" — die Kernzahl, was das Objekt
#     netto p. a. eingebracht hat.
#
# Gewählte Eigenkapital-Basis: das in dieser Datei bereits berechnete
# `eigenkapital` (= Wert − Restschuld + Bausparguthaben), also das **aktuell
# gebundene Eigenkapital**. Bewusst nicht das ursprünglich eingesetzte Kapital:
# das liegt nicht vor (die ursprüngliche Darlehenssumme ist nicht erfasst).
# Die Zahl beantwortet damit „was verzinst sich mein heute gebundenes
# Eigenkapital p. a., inklusive Wertsteigerung".
#
# Jede Kennzahl ist None, sobald ihre Grundlage fehlt — nichts wird erfunden.
# Annualisierte Kennzahlen (Ø/Jahr, CAGR, Gesamtrendite) erst ab einer halben
# Haltedauer-Jahr, sonst hochgerechnete Scheingenauigkeit aus wenigen Wochen.
# --------------------------------------------------------------------------

_MIN_HALTEDAUER = 0.5   # Jahre — darunter keine annualisierten Kennzahlen


def wertzuwachs_kennzahlen(kaufpreis: float | None,
                           verkehrswert: float | None,
                           kaufdatum: date | None,
                           eigenkapital: float | None = None,
                           cashflow_jahr: float | None = None,
                           stichtag: date | None = None) -> dict:
    """Wertzuwachs- und Renditekennzahlen eines Objekts (N75).

    Alle Werte sind `None`, solange ihre Grundlage fehlt. `cashflow_jahr` ist
    der Jahres-Cashflow des Eigentümers (i. d. R. negativ) — fehlt er, bleibt
    die Gesamtrendite offen, die übrigen Kennzahlen stehen trotzdem."""
    heute = stichtag or date.today()
    kp = float(kaufpreis) if kaufpreis else None
    vw = float(verkehrswert) if verkehrswert else None

    leer = {
        "wertzuwachs": None,
        "haltedauer_jahre": None,
        "wertzuwachs_pa": None,
        "wertzuwachs_pm": None,
        "wertsteigerung_pa": None,
        "gesamtrendite_pa": None,
        "gesamtrendite_basis": None,
    }

    # Wertzuwachs absolut — braucht beides: aktuellen Wert und Kaufpreis.
    if kp is None or kp <= 0 or vw is None:
        return leer
    zuwachs = round(vw - kp, 2)

    # Haltedauer — nur mit Kaufdatum, und nur wenn es in der Vergangenheit liegt.
    if kaufdatum is None:
        return {**leer, "wertzuwachs": zuwachs}
    haltedauer = (heute - kaufdatum).days / 365.25
    if haltedauer <= 0:
        return {**leer, "wertzuwachs": zuwachs}
    out = {**leer, "wertzuwachs": zuwachs,
           "haltedauer_jahre": round(haltedauer, 2)}

    # Annualisierte Kennzahlen erst ab einer halben Haltedauer-Jahr.
    if haltedauer < _MIN_HALTEDAUER:
        return out
    pa = zuwachs / haltedauer
    out["wertzuwachs_pa"] = round(pa, 2)
    out["wertzuwachs_pm"] = round(pa / 12, 2)
    # CAGR — durchschnittliche jährliche Wertsteigerung in Prozent.
    out["wertsteigerung_pa"] = round(((vw / kp) ** (1 / haltedauer) - 1) * 100, 2)

    # Gesamtrendite auf das (gebundene) Eigenkapital, inkl. Wertsteigerung.
    if eigenkapital and eigenkapital > 0:
        ertrag = pa + float(cashflow_jahr or 0)
        out["gesamtrendite_pa"] = round(ertrag / eigenkapital * 100, 2)
        out["gesamtrendite_basis"] = round(float(eigenkapital), 2)
    return out


# --------------------------------------------------------------------------
# Eigentum je Einheit (CLXI/CLXII/CLXXXVI)
#
# Ein Anteil hängt entweder am ganzen Objekt (`einheit` leer) oder an einer
# Einheit. Die Umlage auf die Mieter bleibt davon unberührt — das Eigentum
# entscheidet nur, wem Wert und Einnahmen zugerechnet werden.
#
# Zusammenspiel: **Einheit-Anteile haben Vorrang für ihre Einheit; der
# Objekt-Anteil deckt alle Einheiten ohne eigene Zuordnung ("der Rest").**
# Gehört einem Wohnung 2 (Einheit-Anteil) und einem anderen der Rest
# (Objekt-Anteil), zählt für Wohnung 2 der Einheit-Anteil, für die übrigen
# Wohnungen der Objekt-Anteil. Ohne Einheiten gilt der Objekt-Anteil
# unmittelbar fürs ganze Objekt — der gewachsene Fall bleibt unverändert.
# --------------------------------------------------------------------------

def _pm(anteil) -> float:
    """Massgeblicher Anteil in Promille — `promille`, ersatzweise `tausendstel`.

    Wie `besitz.promille_von`, hier eigenständig, damit die Engine ohne den
    Endpunkt auskommt."""
    roh = getattr(anteil, "promille", None)
    if roh is None:
        roh = getattr(anteil, "tausendstel", 0)
    return float(roh or 0)


def _gewichtsbasis(einheiten: list) -> str:
    """Eine gemeinsame Grösse für ALLE Einheiten eines Objekts — nie Euro
    gegen Quadratmeter mischen (N315b).

    Vorher wählte jede Einheit ihre Basis für sich: eine mit gepflegtem
    Verkehrswert ging mit Euro ein, ihre Nachbarin ohne Verkehrswert fiel auf
    ihre Fläche zurück — zwei Wohnungen mit demselben wahren Wert erschienen
    dann als 399.800,10 € gegen 199,90 €, weil ein sechsstelliger Eurobetrag
    gegen eine zweistellige Quadratmeterzahl gewichtet wurde. Verkehrswert
    zählt deshalb nur, wenn ihn WIRKLICH jede Einheit trägt; sonst Fläche für
    alle; sonst zu gleichen Teilen."""
    if einheiten and all(e.verkehrswert for e in einheiten):
        return "verkehrswert"
    if einheiten and all(_gesamtflaeche(e) for e in einheiten):
        return "flaeche"
    return "gleich"


def _einheit_gewicht(einheit, basis: str) -> float:
    """Womit eine Einheit in die Wertzurechnung eingeht — nach der für das
    ganze Objekt einheitlich gewählten Basis (`_gewichtsbasis`)."""
    if basis == "verkehrswert":
        return float(einheit.verkehrswert or 0) or 1.0
    if basis == "flaeche":
        return _gesamtflaeche(einheit) or 1.0
    return 1.0


def attributionswert(objekt, einheiten: list | None = None) -> float | None:
    """Der Objektwert, der auf die Eigentümer verteilt wird.

    Der Objektwert (Verkehrswert, ersatzweise Kaufpreis) ist massgeblich. Fehlt
    er ganz, tritt die Summe der je Einheit gepflegten Verkehrswerte an seine
    Stelle — so trägt CLXXXVI die Sicht auch dann, wenn am Haus noch kein Wert
    steht."""
    w = _wert(objekt)
    if w:
        return w
    summe = round(sum(float(e.verkehrswert) for e in (einheiten or [])
                      if e.verkehrswert), 2)
    return summe or None


def eigentuemer_fraktion(objekt, einheiten: list | None,
                         anteile: list) -> dict[int, float]:
    """Anteil je Eigentümer am Objekt (0..1), wertgewichtet über die Einheiten.

    Für jede Einheit gelten ihre eigenen Anteile; hat sie keine, greift der
    Objekt-Anteil. Gewichtet wird mit `_einheit_gewicht`, damit dem Eigentümer
    der teureren Wohnung auch der grössere Anteil zufällt. Ohne Einheiten
    zählt der Objekt-Anteil unmittelbar."""
    objekt_anteile = [a for a in anteile if not (getattr(a, "einheit", "") or "").strip()]
    out: dict[int, float] = {}

    # Ungerundet aufsummiert — erst der Aufrufer rundet. Ein früh gerundeter
    # Bruchteil (0,733333) verfehlte den vollen Objektwert um ein paar Cent.
    def add(eid: int, wert: float) -> None:
        out[eid] = out.get(eid, 0.0) + wert

    if not einheiten:
        for a in objekt_anteile:
            add(a.eigentuemer_id, _pm(a) / 1000)
        return out

    je_einheit: dict[str, list] = {}
    for a in anteile:
        b = (getattr(a, "einheit", "") or "").strip()
        if b:
            je_einheit.setdefault(b, []).append(a)

    basis = _gewichtsbasis(einheiten)
    gesamtgewicht = sum(_einheit_gewicht(e, basis) for e in einheiten) or 1.0
    for e in einheiten:
        anteil_gewicht = _einheit_gewicht(e, basis) / gesamtgewicht
        zeilen = je_einheit.get(e.bezeichnung.strip()) or objekt_anteile
        for a in zeilen:
            add(a.eigentuemer_id, anteil_gewicht * _pm(a) / 1000)
    return out


# --------------------------------------------------------------------------
# N146 — die PV-Anlage als Investment unter ihrer Immobilie
#
# Die Anlage ist ein eigenes Investment mit eigenen Anteilen: sie kann anderen
# gehören als das Haus (bei Laufer Str. 5 gehört sie zu einem Sechstel jemandem,
# dem am Gebäude selbst nichts gehört). In der Eigentümerübersicht steht sie
# deshalb **nicht als eigenes Objekt**, sondern als untergeordnete Zeile unter
# ihrer Immobilie — mit ihren eigenen Tausendsteln. Der auf eine Person
# entfallende Anlagenwert zählt auf ihren Wert an genau dieser Immobilie.
#
# Bewusst ausgenommen — ausdrücklicher Wunsch des Nutzers, nicht „reparieren":
#   • **Beleihung und freier Beleihungsspielraum.** Eine PV-Anlage ist kein
#     beleihbares Grundpfandobjekt. Basis der Quote bleibt darum allein der
#     Immobilienwert (`wert`); der Anlagenanteil steht daneben in `pv_wert`,
#     die Summe in `wert_gesamt`. Wer die Quote rechnet, nimmt `wert`.
#   • **Wertsteigerung.** Für die Anlage wird keine Wertentwicklung gerechnet.
#     Angesetzt wird die Anschaffung — und genau das steht auch dran
#     (`wertquelle`), statt eine Kurve zu erfinden.
# --------------------------------------------------------------------------

PV_TITEL = "Investment PV"
PV_WERTQUELLE = "Anschaffungswert"
# Die gewachsene Vorgabe aus `strom.EIGENTUEMER_ANTEILE` (5/6 zu 1/6), hier in
# Promille. Sie greift nur, solange am Objekt keine Anteile gepflegt sind — und
# ihre Bezeichnungen sind keine Personennamen, also bleibt sie unzugeordnet.
PV_VORGABE_ANTEILE: dict[str, float] = {"5/6": 833.3, "1/6": 166.7}
_PV_VOLL = 1000.0
_PV_TOLERANZ = 0.1


def pv_anteile_gepflegt(roh: str | None) -> dict[str, float]:
    """Die am Objekt **gepflegten** Anteile als {Name: ‰} — leer, wenn keine.

    Unlesbares zählt als nicht gepflegt (und wird protokolliert, nicht
    verschwiegen). Nur positive Anteile: 0 ‰ ist keine Beteiligung."""
    if not roh:
        return {}
    try:
        d = json.loads(roh) if isinstance(roh, str) else dict(roh)
        return {str(k): float(v) for k, v in d.items() if float(v) > 0}
    except (ValueError, TypeError, AttributeError):
        log.warning("PV-Anteile unlesbar — Vorgabe 5/6 zu 1/6")
        return {}


def pv_anteile(roh: str | None) -> dict[str, float]:
    """Die Anteile einer PV-Anlage als {Name: ‰}.

    Leeres oder unlesbares Feld ergibt die Vorgabe 5/6 zu 1/6 — dieselbe, mit
    der `strom.verteile_eigentuemer` den Ertrag verteilt."""
    return pv_anteile_gepflegt(roh) or dict(PV_VORGABE_ANTEILE)


def pv_wert(anlage) -> float | None:
    """Der angesetzte Wert der Anlage: ihre Anschaffung.

    Einen Zeitwert gibt es nicht — weder ein Gutachten noch eine gepflegte
    Wertreihe. Die Anschaffung ist die ehrlichste Angabe; dass es sie ist,
    sagt `PV_WERTQUELLE` dazu."""
    betrag = float(getattr(anlage, "anschaffung_eur", 0) or 0)
    return round(betrag, 2) if betrag > 0 else None


def _namensschluessel(name: str) -> str:
    """Namen vergleichbar machen: Groß-/Kleinschreibung und Leerraum egal."""
    return re.sub(r"\s+", " ", str(name or "")).strip().casefold()


def _promille_text(wert: float) -> str:
    """Eine ‰-Zahl deutsch und ohne überflüssige Nullen — wie in `strom`."""
    return f"{wert:.1f}".rstrip("0").rstrip(".").replace(".", ",")


def _pv_hinweise(vorgabe: bool, summe: float,
                 ohne_person: list[dict]) -> list[str]:
    """Was der Nutzer über diese Anlage wissen muss. Hinweise, keine Sperre.

    Ein Anteil, zu dem sich keine Person findet, wird **nicht** stillschweigend
    auf die übrigen verteilt — er bleibt unzugeordnet und wird benannt. Sonst
    verschwände er lautlos und die Summe stimmte scheinbar."""
    hinweise: list[str] = []
    if vorgabe:
        hinweise.append(
            "Für die Anlage sind noch keine Anteile gepflegt — angesetzt ist "
            "die Vorgabe 5/6 zu 1/6, die keiner Person zugeordnet ist.")
    # 1e-9 wie in `besitz._stand`: 333,3 dreimal ergibt 999,9 ‰ und soll als
    # vollständig gelten — die Binärdarstellung liegt sonst knapp daneben.
    if abs(summe - _PV_VOLL) > _PV_TOLERANZ + 1e-9:
        hinweise.append(
            f"Die Anteile der Anlage ergeben {_promille_text(summe)} ‰ statt "
            "1000 ‰ — gerechnet wird proportional.")
    if not vorgabe:
        hinweise += [
            f"Zu „{o['name']}“ ({_promille_text(o['promille'])} ‰) gibt es "
            "keinen Eigentümer — dieser Anteil bleibt unzugeordnet."
            for o in ohne_person]
    return hinweise


def pv_zurechnung(anlage, personen: dict[int, str]) -> dict | None:
    """Die PV-Anlage eines Objekts, aufgeteilt auf die Eigentümer-ids.

    `personen` ist {Eigentümer-id: Name}; die Namen in `PVAnlage.anteile` werden
    darauf abgebildet. `None`, wenn es keine Anlage gibt — dann ändert sich an
    dem Objekt nichts, und genau das ist die wichtigste Zusicherung.

    Verteilt wird über `verteile_nach_wert`, also nach dem Größte-Reste-
    Verfahren: die Summe der zugeteilten Beträge trifft den Anlagenwert auf den
    Cent. Anteile ohne Person bleiben als eigenes Gewicht in der Verteilung —
    ihr Betrag fällt niemandem zu, statt die übrigen zu vergrößern."""
    if anlage is None:
        return None
    wert = pv_wert(anlage)
    roh = getattr(anlage, "anteile", "") or ""
    # „Vorgabe" heisst: am Objekt steht nichts Lesbares — nicht, dass jemand
    # zufaellig dieselben Zahlen gepflegt hat.
    vorgabe = not pv_anteile_gepflegt(roh)
    kwp = round(float(getattr(anlage, "kwp", 0) or 0), 2) or None
    # Ein leerer Stammdatensatz (angelegt, aber nie gefüllt) ist keine Anlage.
    # Ihn zu zeigen hiesse, eine Beteiligung zu behaupten, die es nicht gibt.
    if wert is None and vorgabe and kwp is None:
        return None
    anteile = pv_anteile(roh)

    # Heissen zwei Personen gleich, gewinnt die zuerst angelegte (`setdefault`):
    # ein Name ist dann nicht eindeutig, und raten waere schlimmer als eine
    # nachvollziehbare, gleichbleibende Regel.
    nach_name: dict[str, int] = {}
    for eid, name in personen.items():
        nach_name.setdefault(_namensschluessel(name), eid)

    gewichte: dict[str, float] = {}
    zuordnung: dict[str, int] = {}
    ohne_person: list[dict] = []
    for nr, (name, promille) in enumerate(anteile.items()):
        schluessel = f"{nr}:{name}"          # eindeutig, auch bei gleichem Namen
        gewichte[schluessel] = promille
        eid = nach_name.get(_namensschluessel(name))
        if eid is None:
            ohne_person.append({"name": name, "promille": round(promille, 1)})
        else:
            zuordnung[schluessel] = eid

    summe = round(sum(gewichte.values()), 3)
    verteilt = (verteile_nach_wert(wert, gewichte)
                if wert and gewichte else {})

    je_person: dict[int, dict] = {}
    for schluessel, eid in zuordnung.items():
        teil = je_person.setdefault(eid, {"promille": 0.0, "wert": 0.0})
        teil["promille"] = round(teil["promille"] + gewichte[schluessel], 1)
        teil["wert"] = round(teil["wert"] + verteilt.get(schluessel, 0.0), 2)

    return {
        "titel": PV_TITEL,
        "wert": wert,
        "wertquelle": PV_WERTQUELLE,
        "kwp": kwp,
        "anteile_summe": summe,
        "vorgabe": vorgabe,
        "je_person": je_person,
        "ohne_person": ohne_person,
        "hinweise": _pv_hinweise(vorgabe, summe, ohne_person),
    }


# --------------------------------------------------------------------------
# Restschuld fortschreiben
# --------------------------------------------------------------------------

def monatsrate(kredit) -> float:
    """Was monatlich an die Bank geht — unabhängig vom eingetragenen Turnus.

    Eine vierteljährlich gezahlte Rate von 3000 € tilgt im Monat wie 1000 €."""
    return round(jahresbetrag(kredit.rate_monatlich, kredit.turnus) / 12, 2)


def monatszinssatz(zinssatz: float | None) -> float:
    """Der Jahreszinssatz als Faktor je Monat: 1,28 % → 0,001066…"""
    return float(zinssatz or 0) / 100 / 12


def monatszins(restschuld: float | None, zinssatz: float | None) -> float | None:
    """Zinsanteil einer Monatsrate: Restschuld × Zinssatz ÷ 12.

    Bei 140.000 € und 1,28 % sind das 149,33 € im Monat. Gerundet wird erst
    zum Schluss — die Rechnung selbst läuft ungerundet.

    `None`, solange die Restschuld fehlt oder null ist: ohne sie gibt es
    nichts umzurechnen, und 0,00 € wäre eine Behauptung statt einer Auskunft."""
    rest = float(restschuld or 0)
    if rest <= 0 or zinssatz is None:
        return None
    return round(rest * monatszinssatz(zinssatz), 2)


def zinssatz_aus_monatszins(restschuld: float | None,
                            zins_monat: float | None) -> float | None:
    """Der umgekehrte Weg: aus dem monatlichen Zinsanteil der Jahreszinssatz.

    Wer seine Rate kennt und den Satz nicht, liest den Zinsanteil aus dem
    Kontoauszug ab — 149,33 € auf 140.000 € sind 1,28 % im Jahr. Zwei
    Nachkommastellen, wie sie eine Bank auch ausweist."""
    rest = float(restschuld or 0)
    if rest <= 0 or zins_monat is None:
        return None
    return round(float(zins_monat) * 12 / rest * 100, 2)


def monate_seit_jahresende(jahr: int, stichtag: date) -> int:
    """Volle Monatsraten zwischen dem 31.12. eines Jahres und dem Stichtag.

    Negativ, wenn der Stichtag davor liegt — dann wird zurückgerechnet."""
    return (stichtag.year - jahr) * 12 + (stichtag.month - 12)


def _monatsschritt(wert: float, rate: float, satz: float | None) -> tuple[float, float]:
    """Ein Monat Annuität: Zinsanteil und die daraus folgende neue Restschuld.

    Der gemeinsame Kern von `stand_fortschreiben` und `_jahreszins_kalk`
    (N316f) — beide simulierten dieselbe Monatsrechnung unabhängig
    voneinander, ein Risiko, dass sie einmal auseinanderlaufen, sobald die
    Rate den Zins nicht mehr deckt. Jetzt rechnet nur noch diese eine Stelle;
    beide Aufrufer teilen sich das Ergebnis.

    Deckt die Rate den Zins nicht, bleibt die Restschuld unverändert (`neu ==
    wert`) — lieber der letzte bekannte Wert als eine erfundene Kurve."""
    zins = wert * monatszinssatz(satz)
    tilgung = rate - zins
    neu = max(wert - tilgung, 0.0) if tilgung > 0 else wert
    return neu, zins


def stand_fortschreiben(rest: float, rate_monat: float, zinssatz: float | None,
                        monate: int) -> float:
    """Restschuld um `monate` Monate fortschreiben (negativ: zurückrechnen).

    Je Monat: Zins = Restschuld × Zinssatz / 12, Tilgung = Rate − Zins. Weil
    die Restschuld sinkt, sinkt auch der Zinsanteil und die Tilgung wächst —
    genau das macht eine Annuität aus.

    Deckt die Rate den Zins nicht (oder ist keine Rate erfasst), bleibt die
    Restschuld stehen. Lieber der letzte bekannte Wert als eine erfundene
    Kurve."""
    zins_monat = monatszinssatz(zinssatz)
    rate = float(rate_monat or 0)
    wert = float(rest or 0)
    if rate <= 0 or wert <= 0:
        return round(wert, 2)
    for _ in range(abs(monate)):
        if monate > 0:
            neu, _ = _monatsschritt(wert, rate, zinssatz)
            if neu == wert:
                break               # Rate deckt nicht einmal die Zinsen
            wert = neu
            if wert <= 0:
                break
        else:
            # Rückwärts: aus rest_neu = rest_alt × (1 + z) − Rate folgt
            wert = (wert + rate) / (1 + zins_monat)
    return round(wert, 2)


def spar_fortschreiben(stand: float, rate_monat: float, zinssatz: float | None,
                       monate: int, ziel: float | None = None) -> float:
    """Sparstand eines Bausparvertrags fortschreiben (negativ: zurückrechnen).

    Dieselbe Mechanik wie `stand_fortschreiben`, nur andersherum: je Monat
    kommt die Rate hinzu, und das vorhandene Guthaben verzinst sich mit dem
    Habenzins. Über die Bausparsumme hinaus wächst nichts — ist sie erreicht,
    ist die Ansparphase zu Ende und der Vertrag zuteilungsreif.

    Ohne Rate bleibt der Stand stehen (bis auf die Verzinsung). Lieber der
    letzte bekannte Wert als eine erfundene Kurve — wie beim Darlehen.
    """
    zins_monat = monatszinssatz(zinssatz)
    rate = float(rate_monat or 0)
    wert = float(stand or 0)
    grenze = float(ziel) if ziel else None
    for _ in range(abs(monate)):
        if monate > 0:
            wert = wert * (1 + zins_monat) + rate
            if grenze is not None and wert >= grenze:
                return round(grenze, 2)
        else:
            # Rückwärts: aus stand_neu = stand_alt × (1 + z) + Rate folgt
            wert = max((wert - rate) / (1 + zins_monat), 0.0)
    return round(max(wert, 0.0), 2)


def _fortschreiben_darlehen(kredit, basis_jahr: int, basis_wert: float,
                            rate: float, monate: int) -> float:
    """Restschuld fortschreiben, mit Zinswechsel am Ende der Zinsbindung (CCXXX).

    Bis zum Bindungsende gilt der feste Satz, danach der variable Anschlusszins.
    Ist keiner gepflegt oder wird nur rückwärts gerechnet, verhält es sich
    exakt wie `stand_fortschreiben` — jeder Bestand bleibt unverändert."""
    fest = kredit.zinssatz
    variabel = getattr(kredit, "zinssatz_variabel", None)
    if variabel is None or kredit.zinsbindung_bis is None or monate <= 0:
        return stand_fortschreiben(basis_wert, rate, fest, monate)
    # Monate vom Basis-Jahresende bis zum Bindungsende — davor fest, danach variabel.
    m_wechsel = monate_seit_jahresende(basis_jahr, kredit.zinsbindung_bis)
    if m_wechsel <= 0:
        return stand_fortschreiben(basis_wert, rate, variabel, monate)
    if m_wechsel >= monate:
        return stand_fortschreiben(basis_wert, rate, fest, monate)
    zwischen = stand_fortschreiben(basis_wert, rate, fest, m_wechsel)
    return stand_fortschreiben(zwischen, rate, variabel, monate - m_wechsel)


def _jahreszins_kalk(kredit, basis_jahr: int, wert_start: float,
                     rate: float) -> float:
    """Kalkulierte Sollzinsen eines Jahres: die Summe der zwölf monatlichen
    Zinsanteile beim Fortschreiben (mit Zinswechsel). Das Gegenstück zum
    echten Ist-Wert vom Kontoauszug (CCXXXI).

    Dieselbe Monatsrechnung wie `stand_fortschreiben` — über `_monatsschritt`
    (N316f), damit die hier mitgerechnete Restschuld nie von der in `verlauf`
    gezeigten abweicht."""
    fest = kredit.zinssatz
    variabel = getattr(kredit, "zinssatz_variabel", None)
    m_wechsel = (monate_seit_jahresende(basis_jahr, kredit.zinsbindung_bis)
                 if variabel is not None and kredit.zinsbindung_bis else None)
    wert = float(wert_start or 0)
    r = float(rate or 0)
    zinsen = 0.0
    for i in range(12):
        satz = variabel if (m_wechsel is not None and i >= m_wechsel) else fest
        if r > 0 and wert > 0:
            wert, zins = _monatsschritt(wert, r, satz)
        else:
            zins = wert * monatszinssatz(satz)
        zinsen += zins
    return round(zinsen, 2)


def _reihe(staende: list | None) -> list:
    """Jahresstände, aufsteigend nach Jahr."""
    return sorted((s for s in (staende or []) if s.jahr), key=lambda s: s.jahr)


def _basis(reihe: list, heute: date):
    """Der Jahresstand, von dem aus gerechnet wird — der letzte vergangene."""
    vergangen = [s for s in reihe if date(s.jahr, 12, 31) <= heute]
    return vergangen[-1] if vergangen else reihe[0]


def _lage(art: str, stand: float, quelle: str, jahr: int | None,
          stand_wert: float | None, monate: int, rate: float,
          kredit) -> dict:
    """Ein Vertragsstand in der Form, die Oberfläche und Übersicht lesen.

    `restschuld` und `guthaben` schliessen sich aus: was kein Darlehen ist,
    hat keine Restschuld, und was kein Bausparvertrag ist, kein Guthaben. So
    kann keine Auswertung ein Guthaben versehentlich als Schuld addieren."""
    bausparer = ist_bausparer(kredit)
    ziel = float(kredit.bausparsumme) if bausparer and kredit.bausparsumme else None
    return {
        "art": art,
        "restschuld": 0.0 if bausparer else stand,
        "guthaben": stand if bausparer else 0.0,
        "stand": stand,
        "bausparsumme": ziel,
        "noch_zu_sparen": round(max(ziel - stand, 0.0), 2) if ziel else None,
        "zuteilungsreif": bool(ziel) and stand >= ziel,
        "quelle": quelle,
        "stand_jahr": jahr,
        "stand_wert": stand_wert,
        "monate": monate,
        "rate_monat": rate,
        # Was von der Rate an Zinsen weggeht — je kleiner die Restschuld wird,
        # desto weniger. Ein Bausparer in der Ansparphase zahlt keine Zinsen,
        # er bekommt welche: dort steht `None` und daneben der Habenzins.
        "zins_monat": None if bausparer else monatszins(stand, kredit.zinssatz),
        "habenzins_monat": monatszins(stand, kredit.zinssatz) if bausparer else None,
    }


def kreditstand(kredit, staende: list | None = None,
                stichtag: date | None = None) -> dict:
    """Der Stand eines Vertrags zum Stichtag — Restschuld oder Guthaben.

    Ohne Jahresstände gilt weiter das eingetragene Feld (`Kredit.restschuld`
    beim Darlehen, `Kredit.angespart` beim Bausparvertrag) — so bleibt jeder
    gewachsene Bestand unverändert richtig. Mit Jahresständen wird vom letzten
    Stand vor dem Stichtag monatlich fortgeschrieben."""
    heute = stichtag or date.today()
    reihe = _reihe(staende)
    rate = monatsrate(kredit)
    bausparer = ist_bausparer(kredit)
    art = "bausparvertrag" if bausparer else "darlehen"
    ziel = float(kredit.bausparsumme) if bausparer and kredit.bausparsumme else None

    if not reihe:
        roh = kredit.angespart if bausparer else kredit.restschuld
        stand = round(float(roh or 0), 2)
        if ziel:
            stand = min(stand, round(ziel, 2))
        return _lage(art, stand, "eingetragen", None, None, 0, rate, kredit)

    basis = _basis(reihe, heute)
    monate = monate_seit_jahresende(basis.jahr, heute)
    stand = (spar_fortschreiben(basis.restschuld, rate, kredit.zinssatz, monate, ziel)
             if bausparer
             else _fortschreiben_darlehen(kredit, basis.jahr, basis.restschuld,
                                          rate, monate))
    return _lage(art, stand, "jahresstand" if monate == 0 else "fortgeschrieben",
                 basis.jahr, round(float(basis.restschuld or 0), 2),
                 monate, rate, kredit)


def verlauf(kredit, staende: list | None = None,
            bis_jahr: int | None = None) -> list[dict]:
    """Der Stand zum 31.12. je Jahr — eingetragene Stände und die Rechnung
    dazwischen. Zeigt in der Oberfläche, wo gemessen und wo gerechnet wurde.

    Der Schlüssel heisst weiter `restschuld`, damit bestehende Aufrufer
    unverändert lesen; beim Bausparvertrag steht dort der Sparstand, und
    `stand` nennt denselben Wert unter neutralem Namen."""
    reihe = _reihe(staende)
    if not reihe:
        return []
    bausparer = ist_bausparer(kredit)
    ziel = float(kredit.bausparsumme) if bausparer and kredit.bausparsumme else None
    ende = max(bis_jahr or date.today().year, reihe[-1].jahr)
    eingetragen = {s.jahr: round(float(s.restschuld or 0), 2) for s in reihe}
    # CCXXXI — die echten Sollzinsen je Jahr, wo der Nutzer sie vom Kontoauszug
    # eingetragen hat. Steht neben den kalkulierten Zinsen zum Vergleich.
    ist = {s.jahr: s.zinsen_ist for s in reihe if s.zinsen_ist is not None}
    rate = monatsrate(kredit)
    zeilen: list[dict] = []
    wert = eingetragen[reihe[0].jahr]
    for jahr in range(reihe[0].jahr, ende + 1):
        start = wert                       # Restschuld zum Ende des Vorjahres
        anker = jahr == reihe[0].jahr      # erstes Jahr: kein Vorjahr zum Rechnen
        eingetragen_flag = jahr in eingetragen
        if eingetragen_flag:
            wert = eingetragen[jahr]
        else:
            wert = (spar_fortschreiben(start, rate, kredit.zinssatz, 12, ziel)
                    if bausparer
                    else _fortschreiben_darlehen(kredit, jahr - 1, start, rate, 12))
        zinsen_kalk = (None if bausparer or anker
                       else _jahreszins_kalk(kredit, jahr - 1, start, rate))
        zeilen.append({"jahr": jahr, "restschuld": wert, "stand": wert,
                       "eingetragen": eingetragen_flag,
                       "zinsen_kalk": zinsen_kalk, "zinsen_ist": ist.get(jahr)})
    return zeilen


def kapitaldienst_jahr(kredite: list) -> float:
    """Was im Jahr an die Banken geht — ohne Sparraten.

    Für jede Auswertung, die Kreditkosten als Ausgabe zeigt: die Rate eines
    Bausparvertrags ist keine Ausgabe, sondern eine Umschichtung in eigenes
    Vermögen. Sie hier mitzuzählen machte den Cashflow schlechter, als er
    ist."""
    return round(sum(jahresbetrag(k.rate_monatlich, k.turnus)
                     for k in kredite if not ist_bausparer(k)), 2)


def sparrate_jahr(kredite: list) -> float:
    """Was im Jahr in Bausparverträge fliesst — Gegenstück zum Kapitaldienst."""
    return round(sum(jahresbetrag(k.rate_monatlich, k.turnus)
                     for k in kredite if ist_bausparer(k)), 2)


def objekt_vermoegen(objekt, kredite: list, anteile: list | None = None,
                     staende: dict[int, list] | None = None,
                     stichtag: date | None = None,
                     cashflow_jahr: float | None = None) -> dict:
    """Vermögenslage eines Objekts. `anteile` sind Tausendstel je Eigentümer.

    `staende` sind die Jahresstände je Kredit-id. Ohne sie zählt weiter das
    Feld `Kredit.restschuld` — die Übersicht bleibt damit unverändert
    richtig, auch wenn noch niemand einen Jahresstand gepflegt hat."""
    wert = _wert(objekt)
    lagen = [(k, kreditstand(k, (staende or {}).get(getattr(k, "id", None)),
                             stichtag)) for k in kredite]
    darlehen = [(k, lage) for k, lage in lagen if not ist_bausparer(k)]
    bausparer = [(k, lage) for k, lage in lagen if ist_bausparer(k)]

    restschuld = round(sum(lage["restschuld"] for _, lage in darlehen), 2)
    guthaben = round(sum(lage["guthaben"] for _, lage in bausparer), 2)
    # Annuität ist Kapitaldienst — Zins und Tilgung. Eine Sparrate gehört
    # nicht dazu: sie verlässt zwar das Konto, wird aber zu eigenem Vermögen.
    annuitaet = kapitaldienst_jahr(kredite)
    sparrate = sparrate_jahr(kredite)
    zinsen = round(sum(lage["restschuld"] * float(k.zinssatz or 0) / 100
                       for k, lage in darlehen), 2)
    # Das Guthaben liegt neben der Immobilie, nicht in ihr: es erhöht das
    # Eigenkapital, mindert aber die Beleihung nicht.
    eigen = round(wert - restschuld + guthaben, 2) if wert is not None else None
    quote = round(restschuld / wert * 100, 1) if wert else None
    # N315h — massgeblich ist `promille` (Fliesskomma), `tausendstel` (int) nur
    # als aelterer Rundungswert. `int(a.tausendstel)` kappte 833,3 auf 833 und
    # verfehlte den Eigenkapitalanteil um 90 € je 300.000 € Objektwert (`_pm`,
    # wie `besitz.promille_von`, nimmt `promille` und faellt sonst zurueck).
    gehalten = sum(_pm(a) for a in (anteile or [])) or None

    # CCIX — Rücklagenkonto: der Stand ist zurückgelegtes Eigentümergeld, die
    # monatliche Rücklage ein laufender Betrag. Bewusst NICHT ins Eigenkapital
    # gemischt und nicht in die Beleihung: die Beleihung misst die Belastung des
    # Objekts, und eine Instandhaltungsrücklage ist für den Bau gebunden — sie
    # als freies Eigenkapital auszuweisen überzeichnete es. Sie steht deshalb als
    # eigene Zeile daneben (wie das Bausparguthaben eine eigene Zeile hat).
    ruecklage_saldo = (round(float(objekt.ruecklage_saldo), 2)
                       if objekt.ruecklage_saldo else None)
    ruecklage_monatlich = (round(float(objekt.ruecklage_monatlich), 2)
                           if objekt.ruecklage_monatlich else None)
    # CCVIII — Hausgeld: was der Eigentümer monatlich an die WEG zahlt, ein
    # Eigentümerkosten. Als Jahreswert mitgeführt, damit die Wertentwicklung ihn
    # neben den übrigen Eigentümerkosten zeigen kann.
    hausgeld_monatlich = (round(float(objekt.hausgeld_monatlich), 2)
                          if objekt.hausgeld_monatlich else None)
    hausgeld_jahr = (round(hausgeld_monatlich * 12, 2)
                     if hausgeld_monatlich else 0.0)

    # N75 — Wertzuwachs & Gesamtrendite. Rein additiv; jede Kennzahl None,
    # solange ihre Grundlage fehlt. `gesamtrendite_pa` braucht den Jahres-
    # Cashflow (`cashflow_jahr`); wird er nicht mitgegeben, bleibt sie offen
    # und der Aufrufer (Frontend) setzt sie aus Vermögen und Cashflow zusammen.
    kennzahlen = wertzuwachs_kennzahlen(
        objekt.kaufpreis, objekt.verkehrswert, objekt.kaufdatum,
        eigenkapital=eigen, cashflow_jahr=cashflow_jahr, stichtag=stichtag)

    return {
        "slug": objekt.slug,
        "name": objekt.name,
        # N70 — kanonischer Immobilientitel für die Anzeige.
        "titel": objekt_titel(objekt),
        "wert": wert,
        # Beim Grundstueck ist derselbe Wert der Grundstueckswert — das Wort
        # „Verkehrswert" passt dort nicht zu dem, was der Nutzer eingetragen
        # hat. Der Wert selbst ist unveraendert, nur seine Bezeichnung folgt
        # dem Objekttyp.
        "wertquelle": ("Grundstückswert" if ist_grundstueck(objekt) else
                       "Verkehrswert") if objekt.verkehrswert else (
            "Kaufpreis" if objekt.kaufpreis else None),
        "kaufpreis": float(objekt.kaufpreis) if objekt.kaufpreis else None,
        "restschuld": restschuld,
        "bauspar_guthaben": guthaben,
        "bausparvertraege": len(bausparer),
        "eigenkapital": eigen,
        "beleihung": quote,
        "annuitaet_jahr": annuitaet,
        "sparrate_jahr": sparrate,
        "zinslast_jahr": zinsen,
        "tilgung_jahr": round(max(annuitaet - zinsen, 0.0), 2),
        "kredite": len(kredite),
        "tausendstel": gehalten,
        # Anteilig bewertet — bei Alleineigentum identisch mit eigenkapital
        "eigenkapital_anteilig": round(eigen * gehalten / 1000, 2)
        if eigen is not None and gehalten else eigen,
        # CCIX — Rücklagenkonto, eigene Zeilen neben dem Eigenkapital.
        "ruecklage_saldo": ruecklage_saldo,
        "ruecklage_monatlich": ruecklage_monatlich,
        # CCVIII — WEG-Ebene: Kennzeichen und Hausgeld als Eigentümerkosten.
        "weg": bool(objekt.weg),
        "hausgeld_monatlich": hausgeld_monatlich,
        "hausgeld_jahr": hausgeld_jahr,
        # N75 — Wertzuwachs & Gesamtrendite (siehe wertzuwachs_kennzahlen).
        "kaufdatum": objekt.kaufdatum.isoformat() if objekt.kaufdatum else None,
        "erwerbsart": objekt.erwerbsart,
        **kennzahlen,
    }


def gesamt(zeilen: list[dict]) -> dict:
    """Summenzeile. `None` zählt als nicht vorhanden, nicht als Null."""
    def summe(feld: str) -> float:
        return round(sum(z[feld] or 0 for z in zeilen), 2)

    # Kennt kein einziges Objekt seinen Wert, ist die Summe nicht null, sondern
    # unbekannt — sonst stuende oben "0 €" und darunter ein rotes Eigenkapital
    # in Hoehe der gesamten Restschuld.
    bekannt = any(z["wert"] is not None for z in zeilen)
    wert = summe("wert") if bekannt else None
    restschuld = summe("restschuld")
    guthaben = summe("bauspar_guthaben")
    return {
        "objekte": len(zeilen),
        "wert": wert,
        "kaufpreis": summe("kaufpreis"),
        "restschuld": restschuld,
        "bauspar_guthaben": guthaben,
        "eigenkapital": round(wert - restschuld + guthaben, 2) if bekannt else None,
        "eigenkapital_anteilig": summe("eigenkapital_anteilig") if bekannt else None,
        "beleihung": round(restschuld / wert * 100, 1) if wert else None,
        "annuitaet_jahr": summe("annuitaet_jahr"),
        "sparrate_jahr": summe("sparrate_jahr"),
        "zinslast_jahr": summe("zinslast_jahr"),
        "tilgung_jahr": summe("tilgung_jahr"),
        # CCIX/CCVIII — Rücklagen und Hausgeld über alle Objekte.
        "ruecklage_saldo": summe("ruecklage_saldo"),
        "ruecklage_monatlich": summe("ruecklage_monatlich"),
        "hausgeld_jahr": summe("hausgeld_jahr"),
        # N75 — additive Kennzahlen über alle Objekte. Quoten (CAGR,
        # Gesamtrendite) sind nicht additiv und werden bewusst nicht summiert;
        # eine Gesamtsicht darauf setzt der Aufrufer aus den Summen zusammen.
        "wertzuwachs": summe("wertzuwachs"),
        "wertzuwachs_pa": summe("wertzuwachs_pa"),
        "ohne_wert": sum(1 for z in zeilen if z["wert"] is None),
    }
