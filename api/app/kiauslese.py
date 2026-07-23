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

import base64
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

# CCLXXIV: Das Modell zieht NUR die App-Eingabefelder je Dokumenttyp — das
# „Raster". Was auf dem Beleg fehlt, lässt es weg (kein erfundener Wert). Immer
# dabei: die IMMOBILIE (Liegenschaft/Anwesen, NICHT die Postanschrift), ggf. die
# Einheit, und die Einordnung. Knappe, deutsche Anweisung; das Modell soll NUR
# JSON liefern.
SYSTEM_PROMPT = (
    "Du liest einen deutschen Immobilien-Beleg (Rechnung/Bescheid/Vertrag). "
    "Gib NUR JSON zurück, kein weiterer Text:\n"
    '{"dokumenttyp":"…","kategorie":"…","immobilie":"…","einheit":"…",'
    '"datum":"YYYY-MM-DD|null","betrag":<Zahl|null>,"ist_kosten":true|false,'
    '"kostenart":"…","felder":{…},"einordnung":"…"}\n'
    "dokumenttyp = kurze Bezeichnung der Belegart (Mietvertrag, Versicherung, "
    "Kredit, Grundsteuerbescheid, Kaufvertrag, Grundbuch, WEG-Abrechnung, "
    "Nebenkosten-Rechnung, Zählerstand …). "
    "kategorie = bestimmt den Ablage-Ordner und MUSS EXAKT EINER dieser Werte "
    "sein: \"Nebenkosten\", \"Steuer\", \"Versicherung\", \"Kredit\", "
    "\"Mietvertrag\", \"Hausverwaltung\", \"Korrespondenz\", \"Sonstiges\". "
    "immobilie = Adresse der LIEGENSCHAFT/des Objekts, um die es geht "
    "(Straße + Nr, PLZ, Ort). Suche die Bezeichnungen \"Anwesen\", "
    "\"Liegenschaft\", \"Objekt\", \"Grundstück\", \"Verbrauchsstelle\", "
    "\"Lieferadresse\". Das ist NICHT die Empfänger-/Postanschrift. Beispiel: "
    "Ein Brief geht an \"Tauchersreuther Str. 7\", nennt aber \"Anwesen: Laufer "
    "Str. 5\" → immobilie = \"Laufer Str. 5\". Steht keine Liegenschaft dabei, "
    "immobilie weglassen. "
    "einheit = die betroffene Wohnung/Einheit, falls genannt (z. B. \"Whg 1. "
    "OG\", \"EG rechts\"), sonst weglassen. "
    "datum = Ausstellungs-/Rechnungsdatum aus dem Briefkopf, NICHT das "
    "Zahlungsziel, NICHT eine Zeitraumgrenze. "
    "betrag = Gesamt-/Rechnungsbetrag in Euro als Zahl (Punkt als Dezimal-"
    "trenner, ohne Währungszeichen). "
    "ist_kosten = false bei reinen Info-Belegen (SEPA-Mandat, Zählerstand, "
    "Ableseprotokoll), sonst true. "
    "kostenart = worum es GENAU geht, kurz (z. B. Heizöl, Grundsteuer, Wasser, "
    "Gebäudeversicherung, Schornsteinfeger, Müll, Darlehen). "
    "einordnung = ein bis zwei kurze deutsche Sätze: was für ein Beleg das ist, "
    "von wem, worum es geht, mit Datum und Betrag.\n"
    "felder = NUR die zum Typ passenden Angaben, die WIRKLICH auf dem Beleg "
    "stehen (Fehlendes weglassen). Raster je Typ:\n"
    "MIETVERTRAG: mieter, kaltmiete, nebenkosten_vz, stellplatzmiete, "
    "sonstige_einnahmen, mietbeginn, kaution, personen, mieter_email, "
    "mieter_telefon.\n"
    "VERSICHERUNG: art, anbieter, police_nr, jahresbeitrag, turnus, "
    "versicherungssumme, beginn, ende, umlagefaehig.\n"
    "KREDIT/BAUSPAREN: bezeichnung, bank, darlehensnummer, darlehenssumme, "
    "bausparsumme, angespart, restschuld, zinssatz, rate_monatlich, "
    "zinsbindung_bis, beginn, schuldzinsen_jahr, jahr.\n"
    "GRUNDSTEUER: grundsteuerwert, grundsteuer_messbetrag, "
    "grundsteuer_hebesatz, jahresbetrag.\n"
    "KAUFVERTRAG: kaufpreis, kaufdatum.\n"
    "GRUNDBUCH/GRUNDSCHULD: gemarkung, flurstueck, grundbuch_blatt, glaeubiger, "
    "grundschuld_betrag, rang.\n"
    "WEG: verwalter, hausgeld_monatlich, ruecklage_zufuehrung.\n"
    "NEBENKOSTEN-RECHNUNG: kostenart, betrag, zeitraum, s35a (true bei "
    "haushaltsnaher Dienstleistung: Schornsteinfeger, Wartung, Hausmeister, "
    "Winterdienst, Gartenpflege), verbrauch.\n"
    "INFO-BELEG (Zählerstand/Ableseprotokoll/SEPA-Mandat): keine felder, "
    "ist_kosten=false.\n"
    "Nimm KEINE Felder wie Zahlstatus/\"bezahlt\", KEINE fremde IBAN, KEINE "
    "Notar- oder Sachbearbeiternamen auf."
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


def _adresse(wert) -> str:
    """Eine Adresse (Liegenschaft/Einheit) — etwas länger als ein Klartextfeld,
    weil „Laufer Str. 5, 91207 Lauf" hineinpassen muss, aber ohne Umbrüche."""
    if not isinstance(wert, str):
        return ""
    return " ".join(wert.strip().split())[:120]


# So viele Felder nimmt ein Raster höchstens auf — genug für den grössten Typ
# (Mietvertrag/Kredit), eng genug, dass eine ausufernde Modellantwort nicht
# beliebig viel Müll ins Dokument schreibt.
_MAX_FELDER = 30


def _felder(wert) -> dict:
    """Das Raster-Feld der KI säubern: nur ein flaches dict mit knappen, string-
    fähigen Schlüsseln und Werten. Verschachteltes, Listen und Unfug fliegen
    raus — lieber ein Feld weniger als ein kaputtes."""
    if not isinstance(wert, dict):
        return {}
    sauber: dict = {}
    for schluessel, roh in wert.items():
        if len(sauber) >= _MAX_FELDER:
            break
        name = str(schluessel).strip().replace("\n", " ")[:40]
        if not name:
            continue
        if isinstance(roh, bool):
            sauber[name] = roh
        elif isinstance(roh, (int, float)):
            sauber[name] = roh
        elif isinstance(roh, str):
            gekuerzt = " ".join(roh.split())[:120]
            if gekuerzt:
                sauber[name] = gekuerzt
        # Listen/dicts/None werden bewusst übergangen.
    return sauber


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
        # Kurze Klartext-Einordnung für die Anzeige unter dem Dokument (CCLXXIII).
        "einordnung": _text(block.get("einordnung")),
        # CCLXXIV: das Raster — Liegenschaft (nicht Postanschrift), Einheit und
        # die typspezifischen App-Eingabefelder.
        "dokumenttyp": _text(block.get("dokumenttyp")),
        "immobilie": _adresse(block.get("immobilie")),
        "einheit": _adresse(block.get("einheit")),
        "felder": _felder(block.get("felder")),
    }
    # Dezent loggen — OHNE Datum, Betrag oder Namen (Datenschutz). Nur, dass
    # eine Antwort kam und ob ein Datum darin stand.
    log.info("KI-Auslese gelesen (Datum %s)",
             "vorhanden" if ergebnis["datum"] else "keins")
    return ergebnis


# --------------------------------------------------------------------------
# Orientierung eines gescannten Blattes über das Vision-Modell.
#
# Tesseract-OSD verfehlt bei zerknitterten Foto-Scans die Drehrichtung (ein
# Mietvertrag wurde kopfüber gedreht). Ein Vision-Modell erkennt die
# Orientierung dagegen zuverlässig — es „sieht" das Blatt statt Zeichenkanten
# zu zählen. Gesendet wird nur das gerenderte Seitenbild, kein OCR-Text; die
# Antwort ist eine einzige Zahl.
# --------------------------------------------------------------------------
ORIENT_PROMPT = (
    "Um wie viel Grad im Uhrzeigersinn muss dieses gescannte Dokument gedreht "
    "werden, damit der Text normal aufrecht (nicht kopfüber, nicht seitlich) "
    "steht? Antworte NUR mit einer Zahl: 0, 90, 180 oder 270."
)
ORIENT_TOKENS = 10
ORIENT_ZEITLIMIT = 20.0
_ORIENT_ZAHL = re.compile(r"\d+")


def _winkel(text: str) -> int:
    """Die erste Zahl der Modellantwort, auf 0/90/180/270 gerundet.

    Alles andere (kein Treffer, krummer Winkel) wird zu 0 — lieber nicht drehen
    als falsch drehen."""
    treffer = _ORIENT_ZAHL.search(text or "")
    if not treffer:
        return 0
    grad = int(treffer.group()) % 360
    # Auf das nächste rechte-Winkel-Vielfache runden (91 → 90, 179 → 180).
    gerundet = (round(grad / 90) * 90) % 360
    return gerundet if gerundet in (90, 180, 270) else 0


def orientierung(png_bytes: bytes, schluessel: str = "") -> int:
    """Um wie viel Grad IM UHRZEIGERSINN ein Seitenbild gedreht werden muss,
    damit der Text aufrecht steht — erkannt vom Vision-Modell.

    Gibt 0/90/180/270 zurück. Bei JEDEM Fehler (kein httpx, kein Key, Netzwerk,
    Timeout, ungültige Antwort, kein Vielfaches von 90°) `0`, nie eine
    Exception — dann bleibt die Seite ungedreht (der Aufrufer weicht auf OSD
    aus). Denselben Key-Vorrang wie `lies_beleg`: übergebener Schlüssel vor Env.
    """
    if httpx is None or not png_bytes:
        return 0
    schluessel = _schluessel(schluessel)
    if not schluessel:
        return 0

    try:
        b64 = base64.b64encode(png_bytes).decode("ascii")
    except Exception:                                      # noqa: BLE001
        return 0
    rumpf = {
        "model": _modell(),
        "max_tokens": ORIENT_TOKENS,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image", "source": {
                    "type": "base64", "media_type": "image/png", "data": b64}},
                {"type": "text", "text": ORIENT_PROMPT},
            ],
        }],
    }
    kopf = {
        "x-api-key": schluessel,
        "anthropic-version": API_VERSION,
        "content-type": "application/json",
    }

    try:
        antwort = httpx.post(API_URL, headers=kopf, json=rumpf,
                             timeout=ORIENT_ZEITLIMIT)
    except Exception as fehler:                            # noqa: BLE001
        log.info("KI-Orientierung nicht erreichbar: %s", type(fehler).__name__)
        return 0
    if antwort.status_code != 200:
        log.info("KI-Orientierung meldete HTTP %s", antwort.status_code)
        return 0
    try:
        daten = antwort.json()
        bloecke = daten.get("content") or []
        roh = "".join(b.get("text", "") for b in bloecke
                      if isinstance(b, dict) and b.get("type") == "text")
    except Exception:                                      # noqa: BLE001
        return 0
    return _winkel(roh)


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
