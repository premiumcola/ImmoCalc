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

# N177 — der **Kosten**vergleich mit Benzin (nicht zu verwechseln mit dem
# energetischen Äquivalent darüber). Zwei Größen tragen ihn:
#
# * Der reale Verbrauch eines *vergleichbaren Benziners* (ähnliche Klasse und
#   Leistung wie das E-Modell) kommt über die KI — plausibel ist grob 4–12
#   l/100km (Kleinwagen bis großer Kombi/SUV). Alles darunter/darüber ist keine
#   belastbare Angabe und wird verworfen, genau wie beim Stromverbrauch.
# * Der Benzinpreis ist eine **dokumentierte Annahme** (wie „9,7 kWh je Liter"):
#   sie steht sichtbar im PDF, damit die Zahl nicht wie eine Behauptung wirkt.
BENZIN_PREIS_JE_LITER = 1.80
BENZIN_VERBRAUCH_MIN = 4.0
BENZIN_VERBRAUCH_MAX = 12.0

# Der ehrliche Rückfall-Hinweis, wenn sich der Verbrauch nicht ermitteln lässt.
# Wortgleich für alle Fehlerfälle: der Handeintrag ist immer der Ausweg.
HINWEIS_HAND = ("Verbrauch nicht automatisch ermittelbar — bitte kWh/100km "
                "von Hand eintragen.")

# Scheitert die Benziner-Ermittlung, entfällt der Kostenvergleich — ohne
# erfundene Zahl. Dieser Hinweis sagt das ehrlich (er erscheint nicht im PDF,
# das den Block schlicht weglässt, sondern begleitet den Aufruf und die Logs).
HINWEIS_BENZIN = ("Vergleichbarer Benzinverbrauch nicht automatisch "
                  "ermittelbar — kein Kostenvergleich.")

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

# N177 — der Prompt für den vergleichbaren Benziner. Eingabe ist dieselbe
# E-Auto-Modellbezeichnung; die KI wählt selbst einen ähnlichen Verbrenner und
# nennt dessen realen Verbrauch.
SYSTEM_PROMPT_BENZIN = (
    "Du bist Fachmann für Autos. Zu einer angegebenen ELEKTROAUTO-"
    "Modellbezeichnung nennst du den realistischen durchschnittlichen "
    "Kraftstoffverbrauch eines VERGLEICHBAREN BENZINERS (ähnliche Fahrzeug"
    "klasse, Größe und Motorleistung) im Alltag in Litern je 100 Kilometer "
    "(l/100km). Ein Wert zwischen etwa 4 und 12 l/100km ist plausibel. "
    "Antworte mit NUR EINER ZAHL — dem Verbrauch in l/100km, Punkt als "
    "Dezimaltrenner, ohne Einheit, ohne Erklärung, ohne weiteren Text. Fällt "
    "dir kein vergleichbares Modell ein, antworte 0."
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


def plausibel_benzin(wert) -> bool:
    """Liegt ein Benzinverbrauch im realen Bereich (~4–12 l/100km)?

    Wie :func:`plausibel`, nur für den vergleichbaren Verbrenner: darunter
    (unter 4 l) oder darüber (über 12 l) ist keine belastbare Angabe. Ein
    ``bool`` ist zwar eine Zahl, hier aber nie ein Verbrauch."""
    if isinstance(wert, bool) or not isinstance(wert, (int, float)):
        return False
    return BENZIN_VERBRAUCH_MIN <= float(wert) <= BENZIN_VERBRAUCH_MAX


def benzinkosten_je_100km(verbrauch_l_100km: float | None,
                          preis_je_liter: float | None) -> float | None:
    """Was ein Benziner je 100 km an Sprit kostet: ``Verbrauch × Literpreis``.

    Ohne Verbrauch oder ohne Preis: ``None`` — keine erfundene 0."""
    if not verbrauch_l_100km or verbrauch_l_100km <= 0 \
            or not preis_je_liter or preis_je_liter <= 0:
        return None
    return round(verbrauch_l_100km * preis_je_liter, 2)


def ersparnis_je_100km(benzinkosten_100km: float | None,
                       e_preis_100km: float | None) -> float | None:
    """Die Kostenersparnis Elektro gegenüber Benzin je 100 km:
    ``Benzinkosten − E-Auto-Kosten``.

    Beide Größen müssen vorliegen; sonst ``None``. Das Vorzeichen bleibt
    ehrlich — wäre der Strom teurer, käme ein negativer Wert heraus, keine
    geschönte 0."""
    if benzinkosten_100km is None or e_preis_100km is None:
        return None
    return round(benzinkosten_100km - e_preis_100km, 2)


def benzin_vergleich(benzin_verbrauch_l: float | None,
                     e_preis_100km: float | None, km: float | None,
                     preis_je_liter: float = BENZIN_PREIS_JE_LITER) -> dict | None:
    """Der ganze Kostenvergleich in einem Rutsch — die reine, getestete Logik.

    Braucht einen **plausiblen** Benzinverbrauch (sonst ``None``: kein Vergleich
    statt einer erfundenen Zahl) und den echten E-Auto-Preis je 100 km, den das
    PDF ohnehin ausweist. Gibt Benzinkosten und Ersparnis je 100 km zurück und —
    wenn die im Zeitraum gefahrene Strecke bekannt ist — die Gesamtersparnis.

    Der Literpreis ist die dokumentierte Annahme und wandert als `preis_liter`
    mit heraus, damit das PDF sie sichtbar mitnennen kann."""
    if not plausibel_benzin(benzin_verbrauch_l) or e_preis_100km is None:
        return None
    benzin_100km = benzinkosten_je_100km(benzin_verbrauch_l, preis_je_liter)
    ersparnis_100km = ersparnis_je_100km(benzin_100km, e_preis_100km)
    ersparnis_gesamt = (None if ersparnis_100km is None or not km or km <= 0
                        else round(ersparnis_100km * km / 100.0, 2))
    return {"verbrauch_l": round(float(benzin_verbrauch_l), 1),
            "preis_liter": preis_je_liter,
            "benzin_100km": benzin_100km,
            "e_100km": e_preis_100km,
            "ersparnis_100km": ersparnis_100km,
            "km": km,
            "ersparnis_gesamt": ersparnis_gesamt}


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

def _ki_verbrauch(modell: str, system: str, pruefer, leer_hinweis: str,
                  fehl_hinweis: str, schluessel: str,
                  ki_modell: str) -> tuple[float | None, str]:
    """Der gemeinsame Netz-Aufruf: ein Modellname rein, eine geprüfte Zahl raus.

    Trägt beide Ermittlungen — Strom- wie Benzinverbrauch —, die sich nur im
    `system`-Prompt und im `pruefer` (der Plausibilitätsgrenze) unterscheiden.
    **Nie eine Exception**: kein Schlüssel, kein httpx, Netz-, Timeout-, HTTP-,
    Parse- oder Plausibilitätsfehler führen alle zu ``(None, fehl_hinweis)``.
    Ein leerer Modellname ergibt ``(None, leer_hinweis)``."""
    name = " ".join((modell or "").split())
    if not name:
        return None, leer_hinweis
    if httpx is None:
        return None, fehl_hinweis
    schluessel = kiauslese._schluessel(schluessel)
    if not schluessel:
        return None, fehl_hinweis

    rumpf = {
        "model": kiauslese._modell(ki_modell),
        "max_tokens": MAX_TOKENS,
        "system": system,
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
        return None, fehl_hinweis
    if antwort.status_code != 200:
        log.info("KI-Verbrauch meldete HTTP %s", antwort.status_code)
        return None, fehl_hinweis

    try:
        daten = antwort.json()
        bloecke = daten.get("content") or []
        roh = "".join(b.get("text", "") for b in bloecke
                      if isinstance(b, dict) and b.get("type") == "text")
    except Exception:                                      # noqa: BLE001
        return None, fehl_hinweis

    wert = _erste_zahl(roh)
    if not pruefer(wert):
        # Eine 0 (Modell unbekannt) oder ein Ausreißer außerhalb der Grenze:
        # nicht speichern, sondern ehrlich zurückmelden.
        log.info("KI-Verbrauch unplausibel oder unbekannt — kein Wert")
        return None, fehl_hinweis
    return round(float(wert), 1), ""


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
    return _ki_verbrauch(modell, SYSTEM_PROMPT, plausibel,
                         "Bitte zuerst ein E-Auto-Modell eintragen.",
                         HINWEIS_HAND, schluessel, ki_modell)


def verbrauch_benzin_ermitteln(modell: str, schluessel: str = "",
                               ki_modell: str = "") -> tuple[float | None, str]:
    """N177 — zum E-Auto-Modell den Verbrauch eines vergleichbaren Benziners
    (l/100km) ermitteln.

    Gleicher Schlüssel-Vorrang, gleiche Fehlerhaltung und derselbe eine
    Netz-Aufruf wie :func:`verbrauch_ermitteln` — nur Prompt und
    Plausibilitätsgrenze (4–12 l/100km) unterscheiden sich. Scheitert die
    Ermittlung, entfällt der Kostenvergleich (``None``) statt einer erfundenen
    Zahl; der Hinweis sagt das."""
    return _ki_verbrauch(modell, SYSTEM_PROMPT_BENZIN, plausibel_benzin,
                         "Bitte zuerst ein E-Auto-Modell eintragen.",
                         HINWEIS_BENZIN, schluessel, ki_modell)
