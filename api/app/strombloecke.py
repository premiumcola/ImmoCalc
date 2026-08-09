"""N124/N142 — Stromkosten aus DREI Blöcken auf die Einheiten verteilen.

Strom kommt aus drei Töpfen mit je eigenem Preis:

* **Netz** — beim Versorger zugekauft, der teuerste. Menge und Betrag stehen auf
  der Rechnung; der Preis je kWh ist schlicht ``betrag / menge`` (die Umlage des
  Grundpreises auf ct/kWh braucht es dafür nicht).
* **PV** — direkt vom Dach verbraucht.
* **Akku** — aus dem Speicher entnommen. Er kostet mehr als der Direktverbrauch:
  der Speicher will bezahlt und ersetzt werden.

N142 — PV und Speicher waren früher **ein** Topf („eigener Strom"). Der Nutzer
trennt sie jetzt bewusst, weil beide Quellen einen eigenen Preis tragen und die
Daten getrennt vorliegen: SolarEdge weist die drei Anteile einzeln aus, und das
Ladeprotokoll der Wallbox führt „Energieanteil Netz", „…PV" und „…Speicher" je
Ladung getrennt. Die zusammengefasste Zwei-Topf-Sicht bleibt als
:func:`aus_solaredge` erhalten (Bestandsaufrufer), gerechnet wird darüber aber
nicht mehr.

Verteilt wird in zwei Schritten:

1. **Das E-Auto zuerst.** Für die Ladungen ist taggenau bekannt, wie viel davon
   aus dem Netz, wie viel direkt aus der PV und wie viel aus dem Speicher kam.
   Diese Mengen werden vorab aus allen drei Blöcken herausgenommen und exakt
   bepreist. Sie dürfen **nicht** auf die Bewohner der Einheiten verteilt
   werden — das Auto lädt für sich, nicht für das Haus.
2. **Der Rest anteilig.** Was übrig bleibt, wird nach Verbrauch verteilt —
   jede Einheit trägt denselben Anteil an *allen drei* Blöcken und zahlt damit
   denselben Mischpreis. Niemand bekommt „nur den teuren" Strom.

Cent-genau über :func:`engine.verteile_nach_wert`: die Summe der Anteile ist
exakt der Gesamtbetrag.
"""
from dataclasses import dataclass, field

from . import engine

# Die drei Töpfe in fester Reihenfolge — teuer nach günstig, so wie sie auch in
# der Oberfläche stehen.
BLOCKNAMEN: tuple[str, str, str] = ("netz", "pv", "akku")

# Rundungsluft beim Vergleich zweier Mengen (kWh).
_LUFT = 1e-9


@dataclass
class Block:
    """Ein Kostenblock: wie viel kWh zu wie viel Euro."""
    kwh: float = 0.0
    betrag: float = 0.0

    @property
    def preis(self) -> float:
        """€ je kWh — der Durchschnittspreis dieses Blocks."""
        return (self.betrag / self.kwh) if self.kwh else 0.0


@dataclass
class Bloecke:
    """Die drei Töpfe eines Abrechnungszeitraums zusammen."""
    netz: Block = field(default_factory=Block)
    pv: Block = field(default_factory=Block)
    akku: Block = field(default_factory=Block)

    def paare(self) -> tuple[tuple[str, Block], ...]:
        """(Name, Block) in fester Reihenfolge — die Schleifenform der Verteilung."""
        return (("netz", self.netz), ("pv", self.pv), ("akku", self.akku))

    @property
    def kwh(self) -> float:
        """Die gesamte verbrauchte Menge."""
        return round(sum(b.kwh for _, b in self.paare()), 3)

    @property
    def betrag(self) -> float:
        """Was der Strom des Zeitraums insgesamt gekostet hat."""
        return round(sum(b.betrag for _, b in self.paare()), 2)

    @property
    def eigen_kwh(self) -> float:
        """PV und Speicher zusammen — der selbst erzeugte Anteil."""
        return round(self.pv.kwh + self.akku.kwh, 3)


@dataclass
class Ergebnis:
    """Was jede Einheit trägt — Geld und Menge je Block."""
    kosten: dict[str, float] = field(default_factory=dict)
    # {Blockname: {Einheit: kWh}} — je Block, damit jede Einheit belegen kann,
    # woher ihr Strom kam.
    mengen: dict[str, dict[str, float]] = field(
        default_factory=lambda: {n: {} for n in BLOCKNAMEN})
    eauto: dict = field(default_factory=dict)
    gesamt: float = 0.0
    eigenverbrauchsquote: float = 0.0
    warnungen: list[str] = field(default_factory=list)

    @property
    def netz_kwh(self) -> dict[str, float]:
        return self.mengen["netz"]

    @property
    def pv_kwh(self) -> dict[str, float]:
        return self.mengen["pv"]

    @property
    def akku_kwh(self) -> dict[str, float]:
        return self.mengen["akku"]

    @property
    def eigen_kwh(self) -> dict[str, float]:
        """PV und Speicher je Einheit zusammengezogen — für die Anzeige."""
        return {name: round(self.mengen["pv"].get(name, 0.0)
                            + self.mengen["akku"].get(name, 0.0), 3)
                for name in self.kosten}

    def kwh(self, einheit: str) -> float:
        """Die gesamte Menge einer Einheit über alle drei Blöcke."""
        return round(sum(m.get(einheit, 0.0) for m in self.mengen.values()), 3)


def verteile(bloecke: Bloecke, verbrauch: dict[str, float],
             eauto_einheit: str = "", eauto_netz_kwh: float = 0.0,
             eauto_pv_kwh: float = 0.0, eauto_akku_kwh: float = 0.0) -> Ergebnis:
    """Die Kosten aller drei Blöcke auf die Einheiten verteilen.

    `verbrauch` ist der kWh-Verbrauch je Einheit aus den Zählern — beim E-Auto
    ist das die Summe seiner Ladungen. Ist eine E-Auto-Einheit genannt, wird
    sie mit ihren exakten Mengen vorab bedient und nimmt an der anteiligen
    Verteilung nicht mehr teil: diese kWh gehören dem Auto und dürfen nicht auf
    die Bewohner der Einheiten weiterverrechnet werden.
    """
    e = Ergebnis()
    paare = bloecke.paare()
    if any(b.kwh < 0 for _, b in paare):
        e.warnungen.append("Negative Strommenge — bitte die Rechnung prüfen.")
        return e

    rest = {name: b.kwh for name, b in paare}
    vorab = {"netz": eauto_netz_kwh, "pv": eauto_pv_kwh, "akku": eauto_akku_kwh}
    offen = dict(verbrauch)

    # ---- Schritt 1: das E-Auto mit seiner bekannten Aufteilung -------------
    if eauto_einheit:
        zu_viel = [name for name, b in paare if vorab[name] > b.kwh + _LUFT]
        if zu_viel:
            e.warnungen.append(
                f"Die Ladungen von „{eauto_einheit}“ übersteigen die erfasste "
                "Strommenge — die Vorab-Verrechnung wurde ausgelassen.")
        else:
            betrag = round(sum(vorab[name] * b.preis for name, b in paare), 2)
            e.kosten[eauto_einheit] = betrag
            for name, _ in paare:
                e.mengen[name][eauto_einheit] = round(vorab[name], 3)
                rest[name] -= vorab[name]
            e.eauto = {"einheit": eauto_einheit, "betrag": betrag,
                       "kwh": round(sum(vorab.values()), 3),
                       **{f"{name}_kwh": round(vorab[name], 3)
                          for name, _ in paare}}
            offen.pop(eauto_einheit, None)

    # ---- Schritt 2: der Rest nach Verbrauch, alle Blöcke gleichermaßen -----
    summe = sum(v for v in offen.values() if v and v > 0)
    # `rest[name] * b.preis` verliert den Betrag, sobald ein Block ganz ohne
    # Menge dasteht (`kwh == 0`): dort gibt es keinen Durchschnittspreis,
    # `Block.preis` fällt auf 0 zurück. Das Auto kann aus einem solchen Block
    # nichts vorab entnehmen (das würde die Plausibilitätsprüfung oben schon
    # melden), also bleibt sein gesamter Betrag für die anteilige Verteilung
    # übrig — er darf nicht mit dem Preis auf 0 fallen.
    rest_betrag = round(sum(
        b.betrag if not b.kwh else rest[name] * b.preis for name, b in paare), 2)
    if summe > 0:
        anteile = engine.verteile_nach_wert(
            rest_betrag, {n: v for n, v in offen.items() if v and v > 0})
        for name, betrag in anteile.items():
            e.kosten[name] = round(e.kosten.get(name, 0.0) + betrag, 2)
            quote = offen[name] / summe
            for block, _ in paare:
                e.mengen[block][name] = round(rest[block] * quote, 3)
    elif rest_betrag > 0.005:
        e.warnungen.append(
            "Es bleibt Strom übrig, dem keine Einheit zugeordnet ist — die "
            "Zuordnung bitte an den Zählern nachtragen.")

    e.gesamt = round(sum(e.kosten.values()), 2)
    gesamt_kwh = bloecke.kwh
    e.eigenverbrauchsquote = (round(bloecke.eigen_kwh / gesamt_kwh, 4)
                              if gesamt_kwh else 0.0)
    return e


# --------------------------------------------------------------------------
# N125 — Einspeisevergütung
# --------------------------------------------------------------------------

def einspeiseverguetung(kwh_bis10: float, kwh_ab10: float,
                        satz_bis10: float = 0.082,
                        satz_ab10: float = 0.071) -> float:
    """Die Vergütung aus den beiden EEG-Stufen der Rechnung.

    Excel „Gesamtstrom" D18 = D19 × 0,082 + D20 × 0,071
    → 2595 × 0,082 + 2013 × 0,071 = 355,71 €.

    Die Vergütung gehört dem Eigentümer der Anlage: sie wird in der Nebenkosten-
    abrechnung geführt, damit sie zeitlich richtig zugeordnet ist, aber **nicht**
    auf die Mieter verteilt. Von dort fließt sie in den Jahresertrag der Anlage
    und damit in die Amortisation.
    """
    return round(max(0.0, kwh_bis10) * satz_bis10
                 + max(0.0, kwh_ab10) * satz_ab10, 2)


# --------------------------------------------------------------------------
# N126/N142 — die Verbrauchsaufteilung aus der SolarEdge-Oberfläche
# --------------------------------------------------------------------------

def bloecke_aus_solaredge(verbrauch_kwh: float, netz_prozent: float,
                          pv_prozent: float, speicher_prozent: float,
                          netz_betrag: float = 0.0, pv_betrag: float = 0.0,
                          akku_betrag: float = 0.0) -> tuple[Bloecke, list[str]]:
    """Die drei Kostenblöcke aus der SolarEdge-Verbrauchsleiste.

    SolarEdge weist den Verbrauch in drei Anteilen aus — „Vom Netz",
    „Aus PV-Energie" und „Vom Speicher". Genau diese drei sind die Blöcke: jeder
    trägt seine Menge und seinen eigenen Preis.

    Beispiel des Nutzers (01.10.24–30.09.25): 10,8 MWh Verbrauch, 24 % Netz,
    50 % PV, 26 % Speicher → 2592 kWh Netz, 5400 kWh PV, 2808 kWh Speicher.
    """
    warnungen: list[str] = []
    summe = netz_prozent + pv_prozent + speicher_prozent
    if abs(summe - 100.0) > 0.5:
        warnungen.append(
            f"Die Anteile ergeben {summe:.0f} % statt 100 % — bitte die "
            "SolarEdge-Werte prüfen.")
    def menge(prozent: float) -> float:
        return round(verbrauch_kwh * prozent / 100.0, 3)

    return (Bloecke(netz=Block(kwh=menge(netz_prozent), betrag=netz_betrag),
                    pv=Block(kwh=menge(pv_prozent), betrag=pv_betrag),
                    akku=Block(kwh=menge(speicher_prozent), betrag=akku_betrag)),
            warnungen)


def aus_solaredge(verbrauch_kwh: float, netz_prozent: float,
                  pv_prozent: float, speicher_prozent: float,
                  extern_betrag: float = 0.0,
                  eigen_betrag: float = 0.0) -> tuple[Block, Block, list[str]]:
    """Dieselbe Aufteilung in der **zusammengefassten** Zwei-Topf-Sicht.

    Zugekauft (Netz) und selbst erzeugt (PV + Speicher). Sie wird dort gebraucht,
    wo nur die Eigenverbrauchsquote interessiert und der Unterschied zwischen
    Dach und Akku keine Rolle spielt. Gerechnet wird die Verteilung über
    :func:`bloecke_aus_solaredge` und :func:`verteile` mit drei Blöcken.
    """
    b, warnungen = bloecke_aus_solaredge(
        verbrauch_kwh, netz_prozent, pv_prozent, speicher_prozent,
        netz_betrag=extern_betrag)
    return (b.netz, Block(kwh=b.eigen_kwh, betrag=eigen_betrag), warnungen)
