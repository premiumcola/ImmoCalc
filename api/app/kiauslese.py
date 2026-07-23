"""KI-gestützte Beleg-Auslese über ein günstiges Claude-Modell (CCLXVIII).

Die regelbasierte Heuristik in `ocr.py` verwechselt auf manchen Belegen die
Datumsangaben — sie nimmt ein Zahlungsziel oder eine Zeitraumgrenze statt des
Kopf-/Rechnungsdatums und schlägt dadurch den falschen NK-Zeitraum vor. Dieses
Modul lässt stattdessen ein sprachverstehendes Modell den (gekürzten) OCR-Text
lesen und das *richtige* Belegdatum sowie Betrag und eine Klassifizierungs-
Andeutung herausziehen.

Datenschutz — WICHTIG
---------------------
Der OCR-Text enthält echte Namen, IBANs und Beträge. Mit gesetztem
`ANTHROPIC_API_KEY` wird er an die Anthropic-API gesendet. Deshalb:

* **Opt-in.** Ohne vom Nutzer gesetzten Key ist das Feature stumm — genau wie
  die Bilderkennung ohne Tesseract. Standardmäßig ist es nie aktiv.
* **Kein Beleginhalt ins Log.** Bei Erfolg wird nur dezent geloggt, dass etwas
  gelesen wurde — nie der Text, nie die extrahierten Beträge oder Namen.

Bei JEDEM Fehler (kein Key, Netzwerk, Timeout, ungültige Antwort) gibt
`lies_beleg` `None` zurück und wirft nie eine Exception nach außen. Der Scan
funktioniert dann wie bisher, nur ohne KI-Vorschlag.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import date

try:                                                     # pragma: no cover
    import httpx
except ImportError:                                      # pragma: no cover
    httpx = None
    logging.getLogger("immocalc").info(
        "httpx fehlt — KI-Auslese bleibt stumm")

log = logging.getLogger("immocalc")

# Der günstige, schnelle Endpunkt. Über ANTHROPIC_MODEL austauschbar, aber der
# Vorgabewert bleibt bewusst das kleinste Modell — wenige Tokens je Beleg.
STANDARD_MODELL = "claude-haiku-4-5-20251001"
API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"

# Mehr Text kostet mehr Tokens, ohne dass der Briefkopf (mit dem Datum) besser
# würde — er steht ohnehin oben. 6000 Zeichen decken die erste Seite ab.
MAX_ZEICHEN = 6000
MAX_TOKENS = 300
ZEITLIMIT = 15.0

# Knappe, deutsche Anweisung. Das Modell soll NUR JSON liefern — der Rest wird
# beim Parsen ohnehin verworfen, aber eine klare Vorgabe spart Tokens.
SYSTEM_PROMPT = (
    "Du liest einen deutschen Beleg (Rechnung/Bescheid). Gib NUR JSON zurück, "
    "kein weiterer Text:\n"
    '{"datum":"YYYY-MM-DD|null","betrag":<Zahl|null>,"kostenart":"…",'
    '"kategorie":"…","ist_kosten":true|false}\n'
    "datum = Ausstellungs-/Rechnungsdatum aus dem Briefkopf, NICHT das "
    "Zahlungsziel, NICHT eine Zeitraumgrenze, NICHT handschriftliche Notizen. "
    "betrag = Gesamt-/Rechnungsbetrag in Euro als Zahl (Punkt als Dezimal-"
    "trenner, ohne Währungszeichen). "
    "kostenart = worum es GENAU geht, kurz für den Dateinamen (z. B. Heizöl, "
    "Grundsteuer, Wasser, Gebäudeversicherung, Schornsteinfeger, Müll, "
    "Darlehen). "
    "kategorie = bestimmt den Ablage-Ordner und MUSS EXAKT einer dieser Werte "
    "sein: \"Nebenkosten\" (Betriebs-/Heizkosten, Wasser, Strom, Müll, "
    "Schornsteinfeger, Grundsteuer als Betriebskosten), \"Steuer\" (Finanzamt, "
    "Steuerbescheid), \"Versicherung\" (Gebäude-, Haftpflicht-, Elementar-"
    "versicherung, Policen), \"Kredit\" (Darlehen, Tilgung, Zinsen, "
    "Finanzierung), \"Mietvertrag\" (Mietvertrag, Mieterhöhung, Kaution), "
    "\"Hausverwaltung\" (Wohngeld, Eigentümerversammlung, WEG-Verwalter), "
    "\"Korrespondenz\" (Schreiben, Briefe, Mandate ohne Kostenbezug), "
    "\"Sonstiges\" (wenn nichts davon passt). Wähle den treffendsten Ordner. "
    "ist_kosten = false bei reinen Info-Belegen (SEPA-Mandat, Zählerstand, "
    "Ableseprotokoll), sonst true."
)


def verfuegbar(schluessel: str = "") -> bool:
    """Ist die KI-Auslese eingerichtet?

    Mit einem ausdrücklich übergebenen Schlüssel (aus den Einstellungen) ODER
    einem gesetzten `ANTHROPIC_API_KEY`. Ohne beides bleibt das Feature stumm,
    damit kein Beleginhalt ungewollt das Haus verlässt."""
    return bool((schluessel or os.environ.get("ANTHROPIC_API_KEY") or "").strip())


def _schluessel(schluessel: str = "") -> str:
    """Der zu nutzende Schlüssel — der übergebene hat Vorrang vor der Env."""
    return (schluessel or os.environ.get("ANTHROPIC_API_KEY") or "").strip()


def _modell(modell: str = "") -> str:
    """Das zu nutzende Modell — ein übergebenes hat Vorrang, dann die Env, dann
    der Vorgabewert (das kleinste, günstigste Modell)."""
    return (modell or os.environ.get("ANTHROPIC_MODEL") or "").strip() or STANDARD_MODELL


def _json_block(text: str) -> dict | None:
    """Der erste JSON-Block aus der Modellantwort.

    Das Modell hält sich meist an „NUR JSON", aber ein umschließender Satz oder
    ein Markdown-Zaun (```json) darf die Auslese nicht scheitern lassen: gesucht
    wird die erste geschweifte Klammer bis zur passenden schließenden."""
    if not text:
        return None
    anfang = text.find("{")
    ende = text.rfind("}")
    if anfang < 0 or ende <= anfang:
        return None
    try:
        wert = json.loads(text[anfang:ende + 1])
    except (ValueError, TypeError):
        return None
    return wert if isinstance(wert, dict) else None


def _datum(wert) -> str | None:
    """Ein gültiges ISO-Datum oder None. Alles andere (Zeitraum, Unfug) fliegt
    raus — lieber kein Datum als ein falsches."""
    if not wert or not isinstance(wert, str):
        return None
    roh = wert.strip()[:10]
    try:
        return date.fromisoformat(roh).isoformat()
    except ValueError:
        return None


def _betrag(wert) -> float | None:
    """Ein Betrag als Zahl. Das Modell soll schon einen Punkt liefern; kommt
    doch ein deutsches Komma oder ein Währungszeichen, wird es aufgeräumt."""
    if isinstance(wert, bool):        # bool ist eine Zahl in Python — hier nicht
        return None
    if isinstance(wert, (int, float)):
        return round(float(wert), 2)
    if isinstance(wert, str):
        roh = re.sub(r"[^\d,.-]", "", wert).replace(",", ".")
        # Mehrere Punkte (Tausendertrenner) → nur der letzte zählt als Dezimal
        if roh.count(".") > 1:
            ganz, _, rest = roh.rpartition(".")
            roh = ganz.replace(".", "") + "." + rest
        try:
            return round(float(roh), 2)
        except ValueError:
            return None
    return None


def _text(wert) -> str:
    """Ein Klartextfeld (kostenart/kategorie) — knapp und ohne Zeilenumbrüche."""
    if not isinstance(wert, str):
        return ""
    return wert.strip().replace("\n", " ")[:60]


def lies_beleg(text: str, dateiname: str = "", schluessel: str = "",
               modell: str = "") -> dict | None:
    """Liest einen Beleg mit dem günstigen Claude-Modell.

    Gibt bei Erfolg ein dict mit den Schlüsseln `datum` (ISO-String oder None),
    `betrag` (float oder None), `kostenart`, `kategorie` und `ist_kosten`
    zurück. Bei jedem Fehler — fehlender Key, kein httpx, Netzwerk, Timeout,
    ungültige Antwort — `None`, nie eine Exception.

    `schluessel`/`modell` (aus den Einstellungen) haben Vorrang vor der Env;
    ohne beides bleibt die Auslese stumm.

    `dateiname` ist optional und dient nur als zusätzlicher Kontext (ein Name
    wie „2025-10-oel-2729,91€.pdf" nennt Datum und Betrag mit)."""
    if httpx is None:
        return None
    schluessel = _schluessel(schluessel)
    if not schluessel:
        return None
    inhalt = (text or "").strip()
    if not inhalt:
        return None

    gekuerzt = inhalt[:MAX_ZEICHEN]
    nutzer = gekuerzt if not dateiname else f"Dateiname: {dateiname}\n\n{gekuerzt}"
    rumpf = {
        "model": _modell(modell),
        "max_tokens": MAX_TOKENS,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": nutzer}],
    }
    kopf = {
        "x-api-key": schluessel,
        "anthropic-version": API_VERSION,
        "content-type": "application/json",
    }

    try:
        antwort = httpx.post(API_URL, headers=kopf, json=rumpf, timeout=ZEITLIMIT)
    except Exception as fehler:                            # noqa: BLE001
        # Netzwerk, Timeout, DNS — nie nach außen werfen.
        log.info("KI-Auslese nicht erreichbar: %s", type(fehler).__name__)
        return None
    if antwort.status_code != 200:
        # Kein Beleginhalt, nur der Statuscode — der Body könnte Text zitieren.
        log.info("KI-Auslese meldete HTTP %s", antwort.status_code)
        return None

    try:
        daten = antwort.json()
        bloecke = daten.get("content") or []
        roh = "".join(b.get("text", "") for b in bloecke
                      if isinstance(b, dict) and b.get("type") == "text")
    except Exception:                                      # noqa: BLE001
        return None

    block = _json_block(roh)
    if block is None:
        log.info("KI-Auslese lieferte kein verwertbares JSON")
        return None

    ergebnis = {
        "datum": _datum(block.get("datum")),
        "betrag": _betrag(block.get("betrag")),
        "kostenart": _text(block.get("kostenart")),
        "kategorie": _text(block.get("kategorie")),
        "ist_kosten": bool(block.get("ist_kosten", True)),
    }
    # Dezent loggen — OHNE Datum, Betrag oder Namen (Datenschutz). Nur, dass
    # eine Antwort kam und ob ein Datum darin stand.
    log.info("KI-Auslese gelesen (Datum %s)",
             "vorhanden" if ergebnis["datum"] else "keins")
    return ergebnis


# Ein winziger, günstiger Ping: ein Zeichen Prompt, eine Antwort-Token, kurzer
# Timeout. Genug, um zu wissen, ob Schlüssel und Netz stehen — ohne echte Kosten.
PRUEF_TOKENS = 1
PRUEF_ZEITLIMIT = 10.0


def pruefe(schluessel: str = "", modell: str = "") -> dict:
    """Prüft, ob die KI erreichbar ist — ein minimaler echter Call.

    Gibt `{"erreichbar": bool, "fehler": str}` zurück. Jeder Fehler — kein Key,
    kein httpx, Netzwerk, Timeout, HTTP-Status — wird zu `erreichbar: false`
    mit knappem Grund; nie fliegt eine Exception nach außen. `schluessel`/
    `modell` (aus den Einstellungen) haben Vorrang vor der Env.

    Der Beleginhalt spielt hier keine Rolle: gesendet wird nur „ping", damit
    keine echten Daten für den bloßen Erreichbarkeitstest das Haus verlassen."""
    if httpx is None:
        return {"erreichbar": False, "fehler": "httpx fehlt"}
    schluessel = _schluessel(schluessel)
    if not schluessel:
        return {"erreichbar": False, "fehler": "kein Key"}
    rumpf = {
        "model": _modell(modell),
        "max_tokens": PRUEF_TOKENS,
        "messages": [{"role": "user", "content": "ping"}],
    }
    kopf = {
        "x-api-key": schluessel,
        "anthropic-version": API_VERSION,
        "content-type": "application/json",
    }
    try:
        antwort = httpx.post(API_URL, headers=kopf, json=rumpf,
                             timeout=PRUEF_ZEITLIMIT)
    except Exception as fehler:                            # noqa: BLE001
        return {"erreichbar": False, "fehler": type(fehler).__name__}
    if antwort.status_code == 200:
        return {"erreichbar": True, "fehler": ""}
    if antwort.status_code == 401:
        return {"erreichbar": False, "fehler": "Schlüssel abgelehnt (401)"}
    # Anthropics eigene Fehlermeldung durchreichen — „HTTP 400" allein sagt
    # nichts; „model: … not found" schon. Enthält nie den Beleginhalt.
    grund = ""
    try:
        grund = ((antwort.json().get("error") or {}).get("message") or "").strip()
    except Exception:                                      # noqa: BLE001
        grund = ""
    return {"erreichbar": False,
            "fehler": f"HTTP {antwort.status_code}: {grund}" if grund
                      else f"HTTP {antwort.status_code}"}
