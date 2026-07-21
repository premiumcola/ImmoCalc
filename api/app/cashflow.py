"""Cashflow je Einheit und Kostenfluss für das Sankey-Diagramm.

Einnahmen stehen je Einheit fest (Miete). Ausgaben fallen dagegen meist fürs
ganze Objekt an (Kredit, Versicherung, Steuer) — sie werden nach Fläche auf
die Einheiten verteilt; ohne Flächenangabe zu gleichen Teilen.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class EinheitZahlen:
    bezeichnung: str
    nutzungsart: str
    flaeche: float | None
    terrasse: float | None
    nebenflaeche: float | None
    einnahmen_monat: float = 0.0
    kaltmiete: float = 0.0
    stellplatz: float = 0.0
    sonstige: float = 0.0
    nebenkosten_vz: float = 0.0
    partei: str = ""
    kosten_jahr: float = 0.0
    bloecke: dict[str, float] = field(default_factory=dict)

    @property
    def einnahmen_jahr(self) -> float:
        return round(self.einnahmen_monat * 12, 2)

    @property
    def saldo_jahr(self) -> float:
        return round(self.einnahmen_jahr - self.kosten_jahr, 2)

    @property
    def miete_pro_qm(self) -> float | None:
        """Kaltmiete je m² Wohnfläche — die übliche Vergleichsgröße."""
        if not self.flaeche:
            return None
        return round(self.kaltmiete / self.flaeche, 2)

    @property
    def gesamtflaeche(self) -> float:
        """Terrasse zählt üblicherweise anteilig (hier zur Hälfte)."""
        return round((self.flaeche or 0) + (self.terrasse or 0) * 0.5
                     + (self.nebenflaeche or 0) * 0.5, 2)


def verteile(betrag: float, einheiten: list[EinheitZahlen]) -> list[float]:
    """Verteilt einen Objektbetrag nach Fläche, sonst zu gleichen Teilen."""
    if not einheiten:
        return []
    flaechen = [e.flaeche or 0 for e in einheiten]
    summe = sum(flaechen)
    if summe <= 0:
        gleich = betrag / len(einheiten)
        return [gleich] * len(einheiten)
    return [betrag * f / summe for f in flaechen]


def cashflow(einheiten: list[EinheitZahlen], bloecke: dict[str, float]) -> dict:
    """Verteilt die Kostenblöcke auf die Einheiten und liefert die Übersicht."""
    for name, betrag in bloecke.items():
        if not betrag:
            continue
        for e, anteil in zip(einheiten, verteile(betrag, einheiten)):
            e.bloecke[name] = round(e.bloecke.get(name, 0.0) + anteil, 2)
            e.kosten_jahr = round(e.kosten_jahr + anteil, 2)

    einnahmen = round(sum(e.einnahmen_jahr for e in einheiten), 2)
    kosten = round(sum(e.kosten_jahr for e in einheiten), 2)
    return {
        "einheiten": [{
            "bezeichnung": e.bezeichnung,
            "nutzungsart": e.nutzungsart,
            "partei": e.partei,
            "flaeche": e.flaeche,
            "terrasse": e.terrasse,
            "nebenflaeche": e.nebenflaeche,
            "gesamtflaeche": e.gesamtflaeche,
            "kaltmiete": round(e.kaltmiete, 2),
            "stellplatz": round(e.stellplatz, 2),
            "sonstige": round(e.sonstige, 2),
            "nebenkosten_vz": round(e.nebenkosten_vz, 2),
            "miete_pro_qm": e.miete_pro_qm,
            "einnahmen_monat": round(e.einnahmen_monat, 2),
            "einnahmen_jahr": e.einnahmen_jahr,
            "kosten_jahr": e.kosten_jahr,
            "saldo_jahr": e.saldo_jahr,
            "bloecke": e.bloecke,
        } for e in einheiten],
        "gesamt": {
            "einnahmen": einnahmen,
            "kosten": kosten,
            "saldo": round(einnahmen - kosten, 2),
        },
    }


def sankey(einheiten: list[dict], bloecke: dict[str, float]) -> dict:
    """Knoten und Flüsse für das Sankey-Diagramm.

    Einheit ─────┐
                 ├─> Einnahmen ─┬─> Kostenblock
    Fehlbetrag ──┘              └─> Überschuss

    Beide Seiten der Mitte tragen dieselbe Summe — sonst ist das Bild eine
    Behauptung, keine Rechnung. Übersteigen die Kosten die Einnahmen, fehlt
    der Unterschied nicht einfach: er wird zugeschossen. In der Mietersicht
    ist das die Nachzahlung, die der Mieter zusätzlich zu seinen Voraus-
    zahlungen leistet; sie kommt von aussen und steht deshalb als eigene
    Quelle in der ersten Spalte. Der umgekehrte Fall bleibt der Überschuss
    (Mietersicht: das Guthaben) auf der Ausgabenseite.
    """
    knoten: list[dict] = []
    fluss: list[dict] = []

    def index(name: str, spalte: int, rolle: str = "") -> int:
        """Knoten holen oder anlegen. `rolle` faerbt die beiden Ausgleichsknoten:
        ein Überschuss ist ein Plus, ein Fehlbetrag ein Minus — welche Farbe
        das heisst, entscheidet das Diagramm."""
        for i, k in enumerate(knoten):
            if k["name"] == name and k["spalte"] == spalte:
                return i
        knoten.append({"name": name, "spalte": spalte, **({"rolle": rolle}
                                                          if rolle else {})})
        return len(knoten) - 1

    mitte = index("Einnahmen", 1)
    einnahmen_gesamt = 0.0
    for e in einheiten:
        if e["einnahmen_jahr"] <= 0:
            continue
        einnahmen_gesamt += e["einnahmen_jahr"]
        fluss.append({"von": index(e["bezeichnung"], 0), "nach": mitte,
                      "wert": e["einnahmen_jahr"]})

    kosten_gesamt = 0.0
    for name, betrag in sorted(bloecke.items(), key=lambda p: -p[1]):
        if betrag <= 0:
            continue
        kosten_gesamt += betrag
        fluss.append({"von": mitte, "nach": index(name, 2), "wert": round(betrag, 2)})

    saldo = round(einnahmen_gesamt - kosten_gesamt, 2)
    ueberschuss = saldo if saldo > 0 else 0.0
    fehlbetrag = -saldo if saldo < 0 else 0.0
    if ueberschuss:
        fluss.append({"von": mitte, "nach": index("Überschuss", 2, "plus"),
                      "wert": ueberschuss})
    if fehlbetrag:
        fluss.append({"von": index("Fehlbetrag", 0, "minus"), "nach": mitte,
                      "wert": fehlbetrag})

    return {"knoten": knoten, "fluss": fluss,
            "einnahmen": round(einnahmen_gesamt, 2),
            "kosten": round(kosten_gesamt, 2),
            "ueberschuss": ueberschuss,
            "fehlbetrag": fehlbetrag}


def monate_im_jahr(ab: date, bis: date | None, jahr: int) -> float:
    """Wie viele Monate des Jahres deckt dieser Zeitraum ab — taggenau.

    Bewusst keine ganzen Monate: gezählt wurden früher angebrochene Monate an
    beiden Enden voll. Bei einem Mieterwechsel am 15. Juli ergab das für den
    Vorgänger 7 und für den Nachfolger 6 Monate — zusammen 13 Monate Miete in
    einem Jahr, also gut 8 % zu viel Einnahmen. Taggenau summieren sich zwei
    lückenlos aufeinanderfolgende Mietverhältnisse wieder exakt auf 12.

    Das Ende ist einschliesslich zu verstehen: wer am 31.12. auszieht, hat
    diesen Tag noch gewohnt.
    """
    von = max(ab, date(jahr, 1, 1))
    ende = min(bis or date(jahr, 12, 31), date(jahr, 12, 31))
    if ende < von:
        return 0.0
    tage = (ende - von).days + 1
    im_jahr = (date(jahr, 12, 31) - date(jahr, 1, 1)).days + 1   # 365 oder 366
    return round(tage / im_jahr * 12, 6)
