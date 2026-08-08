"""N270 — Rechenlogik zur Renovierung: Gewerk-Verteilung, Budgetstand,
Einheiten-Text. Duenne Endpunkte in `routers/renovierung.py`, die eigentliche
Logik hier — testbar ohne HTTP/DB.
"""
from __future__ import annotations

import re
from typing import Iterable, Sequence

from .bezeichnung import _sauber

# Einzige Wahrheit fuer die Gewerke-Liste; das Frontend holt sie ueber die API
# (`GET /api/renovierungen/gewerke`) und hardcodet sie nicht.
GEWERKE: list[str] = [
    "Rohbau", "Dach", "Fassade & Dämmung", "Fenster & Türen", "Elektro",
    "Sanitär", "Heizung", "Trockenbau", "Estrich & Böden", "Fliesen",
    "Maler", "Küche", "Außenanlagen", "Planung & Gebühren", "Sonstiges",
]

# Posten ohne (oder mit unbekanntem) Gewerk zaehlen unter "Sonstiges", statt
# aus der Verteilung zu fallen.
_SONSTIGES = "Sonstiges"


def projektordner(name: str, von: object = None) -> str:
    """Der Ordnername eines Bauvorhabens: „2025.01_Generalsanierung".

    Jahr und Monat des Starts stehen vorn, damit die Vorhaben im Dateibrowser
    von selbst chronologisch stehen — dieselbe Haltung wie beim Dateinamen
    (CXXII), wo das Datum ebenfalls führt. Ohne Startdatum bleibt der blosse
    Name; ein Ordner „ohne-Datum_…" hülfe beim Wiederfinden niemandem.

    Der Ordner ist immer genau EINE Ebene: Schrägstriche und die übrigen in
    WebDAV verbotenen Zeichen fallen heraus, sonst legte ein Vorhaben namens
    „Bad / Küche" ungefragt einen Baum an.

    `von` darf ein `date` (aus der Datenbank) oder ein ISO-Text (aus dem
    Formular) sein — beide Wege führen zur selben Antwort."""
    sauber = re.sub(r"[\\/:*?\"<>|]", " ", _sauber(name))
    sauber = _sauber(sauber).strip(" .")
    if not sauber:
        return ""
    stamm = (von.isoformat() if hasattr(von, "isoformat") else str(von or ""))
    stamm = stamm[:7].replace("-", ".")                # „2025-01-15" -> „2025.01"
    return f"{stamm}_{sauber}" if len(stamm) == 7 else sauber


def gewerk_summen(posten: Iterable[object]) -> list[dict]:
    """Summe je Gewerk aus den Renovierungsposten, absteigend nach Summe.

    Jeder Posten braucht nur `betrag` und `gewerk` als Attribut (funktioniert
    also sowohl mit ORM-Objekten als auch mit einfachen Namensraeumen/Dicts
    ueber `getattr`). Gewerke ohne Betrag (Summe 0) fallen raus.

    `anteil_pct` ist auf eine Nachkommastelle gerundet; die Summe aller
    Anteile ergibt exakt 100.0, sofern ueberhaupt etwas da ist — der
    Rundungsrest geht auf den groessten Posten (dieselbe Haltung wie
    `verteile_nach_wert` in der Engine: Groesste-Reste-Verfahren statt
    stillschweigender Differenz).
    """
    zwischensumme: dict[str, dict] = {}
    for p in posten:
        gewerk = (getattr(p, "gewerk", "") or "").strip() or _SONSTIGES
        eintrag = zwischensumme.setdefault(gewerk, {"summe": 0.0, "anzahl": 0})
        eintrag["summe"] += float(getattr(p, "betrag", 0.0) or 0.0)
        eintrag["anzahl"] += 1

    # Gewerke ohne Betrag zeigen nichts an — sie waeren eine leere Scheibe im
    # Donut und verwirren mehr, als sie helfen.
    posten_mit_betrag = {g: e for g, e in zwischensumme.items() if e["summe"] != 0}
    gesamt = sum(e["summe"] for e in posten_mit_betrag.values())
    if gesamt == 0:
        return []

    # Rohe (ungerundete) Prozentwerte in Zehntel-Prozent, damit wie bei den
    # Centbetraegen exakt gerechnet werden kann.
    roh = {g: e["summe"] * 1000 / gesamt for g, e in posten_mit_betrag.items()}
    zehntel = {g: int(w) for g, w in roh.items()}          # abschneiden
    rest = 1000 - sum(zehntel.values())
    reihenfolge = sorted(roh, key=lambda g: (-(roh[g] - zehntel[g]), g))
    for i in range(abs(rest)):
        g = reihenfolge[i % len(reihenfolge)]
        zehntel[g] += 1 if rest > 0 else -1

    ergebnis = [
        {"gewerk": g, "summe": round(e["summe"], 2),
         "anteil_pct": zehntel[g] / 10, "anzahl": e["anzahl"]}
        for g, e in posten_mit_betrag.items()
    ]
    ergebnis.sort(key=lambda r: (-r["summe"], r["gewerk"]))
    return ergebnis


def budget_stand(budget: float | None, ausgegeben: float) -> dict:
    """Budget, Ist-Ausgaben, Restbudget und Auslastung.

    `rest` darf negativ werden (`ueberzogen=True`) — er wird NICHT auf 0
    geklemmt, sonst sieht der Nutzer eine Ueberschreitung nicht.
    Ohne Budget bleibt alles bis auf `ausgegeben` `None`.
    """
    ausgegeben = round(float(ausgegeben or 0.0), 2)
    if budget is None:
        return {"budget": None, "ausgegeben": ausgegeben, "rest": None,
                "anteil_pct": None, "ueberzogen": False}
    budget = round(float(budget), 2)
    rest = round(budget - ausgegeben, 2)
    anteil_pct = round(ausgegeben / budget * 100, 1) if budget else 0.0
    return {"budget": budget, "ausgegeben": ausgegeben, "rest": rest,
            "anteil_pct": anteil_pct, "ueberzogen": rest < 0}


def einheiten_liste(text: str) -> list[str]:
    """Wandelt den gespeicherten "|"-getrennten Text in eine Liste von
    Einheitenbezeichnungen. Leer = ganzes Objekt."""
    if not text:
        return []
    return [e for e in (teil.strip() for teil in text.split("|")) if e]


def einheiten_text(liste: Sequence[str]) -> str:
    """Kehrfunktion zu `einheiten_liste` — an dieser einen Stelle die
    "|"-Umwandlung, damit sie nirgends sonst dupliziert wird."""
    return "|".join(e.strip() for e in liste if e and e.strip())
