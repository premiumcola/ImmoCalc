"""N170 — vom geladenen Strom zur gefahrenen Strecke.

Jeder Tanknutzer bekommt ein E-Auto zugeordnet. Aus seinem Durchschnitts-
verbrauch (kWh/100km) werden die geladenen Kilowattstunden zu gefahrenen
Kilometern, zu einem Preis je 100 km und zu einem energetischen Benzin-
Äquivalent.

Zwei Ebenen, streng getrennt:

* **Reine, netzfreie Rechenlogik** — km, Preis je 100 km, Benzin-Äquivalent,
  die Plausibilitätsgrenzen und das Parsen der KI-Zahl. Sie wird vollständig
  getestet und kommt ohne Netz und ohne Datenbank aus.
* **Ein einziger Netz-Aufruf** (`verbrauch_ermitteln`): die KI nennt zum
  eingegebenen Modell den realistischen Durchschnittsverbrauch bei defensiver
  Fahrweise. Er läuft über denselben Anthropic-Endpunkt und denselben
  Schlüssel-Vorrang wie `kiauslese` und wirft — wie dort — bei jedem Fehler
  **nie** eine Exception nach außen: kein Schlüssel, kein Netz, unplausible
  Antwort → ``(None, Hinweis)``. Der Handeintrag ist der Rückfallweg.

Das **Benzin-Äquivalent** ist ein *physikalischer Energievergleich*, kein
Kostenvergleich: der Energiegehalt von Benzin liegt bei rund
:data:`BENZIN_KWH_PRO_LITER` kWh je Liter, also entspricht ein E-Auto mit
18 kWh/100km energetisch ~1,9 l/100km. Ein Verbrenner braucht real deutlich
mehr — die Zahl sagt nur, wie viel Energie stecken bliebe, nicht was ein
Verbrenner verbrauchte. Die Annahme (9,7 kWh/l) wird überall sichtbar
mitgenannt, damit die Zahl nicht wie eine Behauptung wirkt.
"""
from __future__ import annotations

import logging
import re

try:                                                     # pragma: no cover
    import httpx
except ImportError:                                      # pragma: no cover
    httpx = None

from . import kiauslese

log = logging.getLogger("immocalc")

# Ein reales E-Auto verbraucht zwischen ~12 und ~30 kWh/100km (Kleinwagen bis
# schwerer SUV, inkl. Ladeverluste). Alles darunter oder darüber ist keine
# belastbare Angabe — sonst käme später eine absurde Kilometerzahl heraus.
VERBRAUCH_MIN = 12.0
VERBRAUCH_MAX = 30.0

# Energiegehalt von Benzin: rund 9,7 kWh je Liter (unterer Heizwert). Grundlage
# des energetischen Benzin-Äquivalents — kein Kostenvergleich (siehe Modul-Kopf).
BENZIN_KWH_PRO_LITER = 9.7

# Der ehrliche Rückfall-Hinweis, wenn sich der Verbrauch nicht ermitteln lässt.
# Wortgleich für alle Fehlerfälle: der Handeintrag ist immer der Ausweg.
HINWEIS_HAND = ("Verbrauch nicht automatisch ermittelbar — bitte kWh/100km "
                "von Hand eintragen.")

# Der KI-Aufruf ist knapp: eine Modellbezeichnung rein, eine Zahl raus.
MAX_TOKENS = 24
ZEITLIMIT = 15.0

SYSTEM_PROMPT = (
    "Du bist Fachmann für Elektroautos. Zu einer Modellbezeichnung nennst du "
    "den realistischen durchschnittlichen Stromverbrauch im Alltag in "
    "Kilowattstunden je 100 Kilometer (kWh/100km), INKLUSIVE Ladeverluste und "
    "bei DEFENSIVER, vorausschauender Fahrweise — also eher am unteren Ende des "
    "realen Bereichs (mehr Kilometer je Kilowattstunde). Ein Wert zwischen etwa "
    "12 und 30 kWh/100km ist plausibel. "
    "Antworte mit NUR EINER ZAHL — dem Verbrauch in kWh/100km, Punkt als "
    "Dezimaltrenner, ohne Einheit, ohne Erklärung, ohne weiteren Text. Kennst "
    "du das Modell nicht sicher, antworte 0."
)


# ==========================================================================
# Reine Rechenlogik — netzfrei, datenbankfrei, vollständig getestet.
# ==========================================================================

def plausibel(wert) -> bool:
    """Liegt ein Verbrauch im realen Bereich (~12–30 kWh/100km)?

    Werte außerhalb sind keine belastbare Angabe — sie werden verworfen, statt
    gespeichert zu werden, sonst käme später eine absurde km-Zahl heraus. Ein
    ``bool`` ist in Python zwar eine Zahl, hier aber nie ein Verbrauch."""
    if isinstance(wert, bool) or not isinstance(wert, (int, float)):
        return False
    return VERBRAUCH_MIN <= float(wert) <= VERBRAUCH_MAX


def gefahrene_km(kwh: float | None, verbrauch_kwh_100km: float | None) -> float | None:
    """Aus geladenen kWh die gefahrenen Kilometer: ``kwh / verbrauch × 100``.

    Ohne Verbrauch (0 oder ``None``) oder ohne Menge gibt es keine Strecke —
    ``None`` statt einer erfundenen 0."""
    if not verbrauch_kwh_100km or verbrauch_kwh_100km <= 0 or kwh is None:
        return None
    return round(kwh / verbrauch_kwh_100km * 100.0, 1)


def preis_je_100km(betrag: float | None, km: float | None) -> float | None:
    """Der Preis je 100 km: ``betrag / km × 100``.

    Der Weg passt bewusst zum ausgewiesenen Rechnungsbetrag: ist der Betrag der
    des Zeitraums und ``km`` die im selben Zeitraum gefahrene Strecke, ist das
    exakt der Preis je 100 km. Ohne Betrag oder ohne Strecke: ``None``."""
    if betrag is None or not km or km <= 0:
        return None
    return round(betrag / km * 100.0, 2)


def benzin_aequivalent(verbrauch_kwh_100km: float | None) -> float | None:
    """Das energetische Benzin-Äquivalent in l/100km: ``kWh/100km ÷ 9,7``.

    Ein reiner Energievergleich (Benzin trägt rund :data:`BENZIN_KWH_PRO_LITER`
    kWh je Liter), **kein** Kostenvergleich — die Annahme gehört überall sichtbar
    daneben. Ohne Verbrauch: ``None``."""
    if not verbrauch_kwh_100km or verbrauch_kwh_100km <= 0:
        return None
    return round(verbrauch_kwh_100km / BENZIN_KWH_PRO_LITER, 1)


def kennzahlen(kwh: float | None, betrag: float | None,
               verbrauch_kwh_100km: float | None) -> dict:
    """Die drei E-Auto-Größen eines Zeitraums in einem Rutsch.

    Gibt ``{"km", "preis_100km", "liter_100km"}`` zurück — jede Größe ``None``,
    solange ihre Grundlage fehlt (kein Verbrauch, keine Menge, kein Betrag).
    So bleibt eine Spalte leer, statt eine Null zu behaupten."""
    km = gefahrene_km(kwh, verbrauch_kwh_100km)
    return {"km": km,
            "preis_100km": preis_je_100km(betrag, km),
            "liter_100km": benzin_aequivalent(verbrauch_kwh_100km)}


_ZAHL = re.compile(r"\d+(?:[.,]\d+)?")


def _erste_zahl(text: str) -> float | None:
    """Die erste Zahl aus der Modellantwort — deutsches Komma wird zum Punkt.

    Die KI soll „nur die Zahl" liefern; ein umschließendes Wort oder eine
    Einheit dahinter darf das Lesen trotzdem nicht scheitern lassen."""
    treffer = _ZAHL.search(text or "")
    if not treffer:
        return None
    try:
        return float(treffer.group().replace(",", "."))
    except ValueError:
        return None


# ==========================================================================
# Der einzige Netz-Aufruf — die KI nennt den Durchschnittsverbrauch.
# ==========================================================================

def verbrauch_ermitteln(modell: str, schluessel: str = "",
                        ki_modell: str = "") -> tuple[float | None, str]:
    """Zum E-Auto-Modell den Durchschnittsverbrauch (kWh/100km) ermitteln.

    Rückgabe ``(verbrauch, hinweis)``: bei Erfolg ``(Zahl, "")``, sonst
    ``(None, Hinweis)``. **Nie eine Exception** — kein Schlüssel, kein httpx,
    Netzwerk, Timeout, ungültige oder unplausible Antwort führen alle zum
    ehrlichen Hinweis, dass der Wert von Hand einzutragen ist. Der Handeintrag
    ist der ausdrücklich gewünschte Rückfallweg.

    `schluessel`/`ki_modell` (aus den Einstellungen) haben Vorrang vor der
    Umgebung — derselbe Vorrang und dieselbe Fehlerhaltung wie in `kiauslese`."""
    name = " ".join((modell or "").split())
    if not name:
        return None, "Bitte zuerst ein E-Auto-Modell eintragen."
    if httpx is None:
        return None, HINWEIS_HAND
    schluessel = kiauslese._schluessel(schluessel)
    if not schluessel:
        return None, HINWEIS_HAND

    rumpf = {
        "model": kiauslese._modell(ki_modell),
        "max_tokens": MAX_TOKENS,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": name}],
    }
    kopf = {
        "x-api-key": schluessel,
        "anthropic-version": kiauslese.API_VERSION,
        "content-type": "application/json",
    }

    try:
        antwort = httpx.post(kiauslese.API_URL, headers=kopf, json=rumpf,
                             timeout=ZEITLIMIT)
    except Exception as fehler:                            # noqa: BLE001
        log.info("KI-Verbrauch nicht erreichbar: %s", type(fehler).__name__)
        return None, HINWEIS_HAND
    if antwort.status_code != 200:
        log.info("KI-Verbrauch meldete HTTP %s", antwort.status_code)
        return None, HINWEIS_HAND

    try:
        daten = antwort.json()
        bloecke = daten.get("content") or []
        roh = "".join(b.get("text", "") for b in bloecke
                      if isinstance(b, dict) and b.get("type") == "text")
    except Exception:                                      # noqa: BLE001
        return None, HINWEIS_HAND

    wert = _erste_zahl(roh)
    if not plausibel(wert):
        # Eine 0 (Modell unbekannt) oder ein Ausreißer außerhalb 12–30: nicht
        # speichern, sondern zum Handeintrag raten.
        log.info("KI-Verbrauch unplausibel oder unbekannt — Handeintrag nötig")
        return None, HINWEIS_HAND
    return round(float(wert), 1), ""
