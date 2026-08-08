"""N313 — die deutsche Zahlenschreibweise, einmal.

Es gab acht Fassungen im Backend mit **drei** verschiedenen Regeln. Was das
praktisch heisst, an einem einzigen Beleg gemessen:

    Die KI liest einen Kaufpreis als „250.000 €".
      `feldzuordnung._als_zahl`  →      250.0   → das Formular zeigt 250,00 €
      `dokumente.ki_werte._ki_zahl` → 250000.0  → der Datensatz trägt 250.000 €

Dasselbe Feld, derselbe Beleg, Faktor 1000. Und es ist kein neuer Verdacht: der
Kommentar in `kiauslese._zahl_de` hält denselben Fehler schon fest, weil er
einmal in eine Abrechnung geraten ist — „aus ‚2.416 m³' würde ein Verbrauch von
2,416 m³" (N287).

**Die Regel**, in dieser Reihenfolge:

1. Ein Komma ist IMMER der Dezimaltrenner; Punkte davor sind Tausender.
   „1.234,56" → 1234.56
2. Ohne Komma entscheidet die Gliederung: stehen hinter jedem Punkt genau drei
   Ziffern, sind es Tausenderpunkte. „1.250" → 1250 · „1.234.567" → 1234567
3. Sonst ist der Punkt dezimal. „12.5" → 12.5 — so kommen Werte aus der API
   zurück, und „12,5 m³" schreibt niemand als „12.500".

Dieselbe Regel gilt im Frontend (`immo.js`, `zahlAus`) — sie ist an beiden
Enden dieselbe, damit ein getippter und ein gelesener Wert nie auseinanderlaufen.

**Nicht hierher gehört die Politik drumherum.** Ob ein Betrag positiv sein muss
(eine Forderung ist es), ob 0 als „keine Angabe" gilt (bei einer Menge ja, bei
einem Preis nein), welche Plausibilitätsgrenzen greifen — das ist je Aufrufer
verschieden und bewusst dort geblieben. Geteilt wird nur das Lesen der Ziffern.
"""
from __future__ import annotations

import re

# Nur Ziffern, Punkt, Komma und Vorzeichen bleiben stehen — Währung, Einheit
# und Leerzeichen fallen heraus.
_UNRAT = re.compile(r"[^\d,.\-+]")
# Tausendergliederung: eine bis drei Ziffern, dann lauter Dreiergruppen.
_TAUSENDER = re.compile(r"\d{1,3}(?:\.\d{3})+")


def deutsch(wert) -> float | None:
    """Eine Zahl aus deutscher (oder englischer) Schreibweise. `None`, wenn
    nichts Brauchbares dasteht.

    Zahlen kommen unverändert zurück — nur Text wird gelesen. `bool` ist in
    Python eine Zahl, hier aber nie eine: `True` als Betrag wäre ein Fehler,
    kein Wert."""
    if isinstance(wert, bool):
        return None
    if isinstance(wert, (int, float)):
        return float(wert)
    roh = _UNRAT.sub("", str(wert or "")).strip()
    if not roh or roh in ("-", "+", ".", ","):
        return None
    # Ein Vorzeichen darf nur vorn stehen; alles Weitere ist Trennstrich.
    vorzeichen = -1.0 if roh[0] == "-" else 1.0
    roh = roh.lstrip("+-").replace("-", "")
    if not roh:
        return None
    if "," in roh:
        roh = roh.replace(".", "").replace(",", ".")
    elif _TAUSENDER.fullmatch(roh):
        roh = roh.replace(".", "")
    try:
        return vorzeichen * float(roh)
    except ValueError:
        return None
