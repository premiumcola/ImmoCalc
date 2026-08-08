"""Der eine Weg zum Anthropic-Endpunkt — N288-B2.

Der HTTP-Rumpf stand sieben Mal wörtlich im Repo: sechs Mal in `kiauslese.py`
(Beleg, Wasser, Strom, WEG-Abrechnung, Orientierung, SolarEdge, Ping) und
einmal in `eauto.py`. Jede Fassung baute dieselben drei Kopfzeilen, dieselbe
Nutzlast und dieselben zwei `try/except` neu auf, und jede zog den Antworttext
mit derselben Zeile aus den `content`-Blöcken. Wich eine davon ab, war das ein
Versehen und keine Absicht — nur eine einzige prüfte am Ende die Summen ihrer
Antwort, obwohl das mit dem Transport nichts zu tun hat.

Hier steht er ein Mal. `frage_modell` nimmt Modell, Prompt, Text **oder** Bild,
Zeitlimit und Wiederholungszahl, macht den Aufruf und gibt eine `Antwort`
zurück — **nie** eine Exception: kein httpx, kein Schlüssel, Netz, Timeout,
HTTP-Status, unlesbare Antwort werden alle zu `Antwort.ok is False`. Was die
Fassungen daraus machen (None, 0, `{}` oder ein Hinweis für den Nutzer), bleibt
ihre Sache — das ist Fachlogik, kein Transport.

Wo die Fassungen sich unterschieden, gilt die strengste/sicherste Variante:

* **Zeitlimit** — 10 s (`pruefe`) bis 60 s (WEG-Abrechnung). Der Unterschied ist
  fachlich begründet (ein dreiseitiges Abrechnungsblatt braucht länger als ein
  Ping), deshalb bleibt es ein Parameter je Aufruf; die Vorgabe ist die
  strengste der *inhaltlichen* Ausleser: 15 s wie in `kiauslese`/`eauto`.
* **Wiederholung** — keine Fassung wiederholte. Ein Versuch ist damit die
  strengste Variante und bleibt die Vorgabe; wiederholt wird auf Wunsch nur bei
  Netzfehler, 429 und 5xx — nie bei einer abgelehnten oder fehlerhaften Anfrage.
* **Fehlermeldung** — nur `pruefe` las die Meldung von Anthropic aus dem
  Antwort-Body; alle anderen loggten bewusst nur den Statuscode, weil der Body
  Beleginhalt zitieren könnte. Beides zusammen ist die sicherste Fassung: die
  Meldung wird gelesen und in `Antwort.grund` **zurückgegeben**, aber niemals
  geloggt. Geloggt wird wie bisher nur, dass und mit welchem Status es scheiterte.

Datenschutz: dieses Modul schreibt weder Prompt noch Beleginhalt noch die
Antwort ins Log — dieselbe Regel wie in `kiauslese.py`.
"""
from __future__ import annotations

import base64
import json
import logging
import os
from dataclasses import dataclass

try:                                                     # pragma: no cover
    import httpx
except ImportError:                                      # pragma: no cover
    httpx = None

log = logging.getLogger("immocalc")

# Der günstige, schnelle Endpunkt. Über ANTHROPIC_MODEL austauschbar, aber der
# Vorgabewert bleibt bewusst das kleinste Modell — wenige Tokens je Beleg.
STANDARD_MODELL = "claude-haiku-4-5-20251001"
API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"

# Die Vorgaben der inhaltlichen Ausleser; wer länger braucht (WEG) oder kürzer
# darf (Ping), sagt es beim Aufruf.
ZEITLIMIT = 15.0
VERSUCHE = 1

# Nur diese Lagen sind eine Wiederholung wert: der Aufruf kam gar nicht an (0),
# wurde ausgebremst (429) oder scheiterte an der Gegenseite (5xx). Ein 400/401
# wird beim zweiten Mal genauso abgelehnt.
_WIEDERHOLBAR = {0, 429, 500, 502, 503, 504}


def api_schluessel(schluessel: str = "") -> str:
    """Der zu nutzende Schlüssel — der übergebene hat Vorrang vor der Env."""
    return (schluessel or os.environ.get("ANTHROPIC_API_KEY") or "").strip()


def api_modell(modell: str = "") -> str:
    """Das zu nutzende Modell — ein übergebenes hat Vorrang, dann die Env, dann
    der Vorgabewert (das kleinste, günstigste Modell)."""
    return (modell or os.environ.get("ANTHROPIC_MODEL") or "").strip() or STANDARD_MODELL


def json_block(text: str) -> dict | None:
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


@dataclass
class Antwort:
    """Was ein Aufruf hergibt — nie eine Exception, immer dieses Objekt.

    `status` ist 0, wenn es gar nicht bis zu einer HTTP-Antwort kam (kein httpx,
    kein Schlüssel, Netzfehler). `grund` trägt die Meldung von Anthropic, falls
    die Gegenseite eine genannt hat — sie wird nie geloggt (siehe Modulkopf),
    der Aufrufer entscheidet, ob er sie zeigt."""

    status: int = 0
    text: str = ""
    block: dict | None = None
    fehler: str = ""
    grund: str = ""

    @property
    def ok(self) -> bool:
        """Kam eine lesbare 200er-Antwort zurück?"""
        return self.status == 200 and not self.fehler


def _grund(antwort) -> str:
    """Anthropics eigene Fehlermeldung — „HTTP 400" allein sagt nichts,
    „model: … not found" schon. Enthält nie den Beleginhalt, wird nie geloggt."""
    try:
        return ((antwort.json().get("error") or {}).get("message") or "").strip()
    except Exception:                                      # noqa: BLE001
        return ""


def _versuch(http, kopf: dict, rumpf: dict, zeitlimit: float,
             etikett: str) -> Antwort:
    """Ein einzelner Aufruf — der Rumpf, den es vorher sieben Mal gab."""
    try:
        antwort = http.post(API_URL, headers=kopf, json=rumpf, timeout=zeitlimit)
    except Exception as fehler:                            # noqa: BLE001
        # Netzwerk, Timeout, DNS — nie nach außen werfen.
        log.info("%s nicht erreichbar: %s", etikett, type(fehler).__name__)
        return Antwort(fehler=type(fehler).__name__)

    status = getattr(antwort, "status_code", 0)
    if status != 200:
        # Kein Beleginhalt ins Log, nur der Statuscode — der Body könnte Text
        # zitieren. Die Meldung wandert ungeloggt in `grund`.
        log.info("%s meldete HTTP %s", etikett, status)
        return Antwort(status=status, fehler=f"HTTP {status}",
                       grund=_grund(antwort))

    try:
        daten = antwort.json()
        bloecke = daten.get("content") or []
        roh = "".join(b.get("text", "") for b in bloecke
                      if isinstance(b, dict) and b.get("type") == "text")
    except Exception:                                      # noqa: BLE001
        return Antwort(status=status, fehler="Antwort unlesbar")

    return Antwort(status=status, text=roh, block=json_block(roh))


def frage_modell(inhalt: str = "", *, schluessel: str = "", modell: str = "",
                 system: str = "", max_tokens: int = 256,
                 bild: bytes | None = None, media_type: str = "image/png",
                 zeitlimit: float = ZEITLIMIT, versuche: int = VERSUCHE,
                 etikett: str = "KI", http=None) -> Antwort:
    """Ein Aufruf beim Modell — der einzige im Haus.

    `inhalt` ist der Nutzertext (bei einem Bild-Aufruf die Frage zum Bild),
    `system` der Systemprompt (leer = keiner). Ist `bild` gesetzt, geht es als
    base64 mit `media_type` voran, der Text dahinter — genau wie bisher in
    `orientierung` und `lies_solaredge`.

    `etikett` ist der Name im Log („KI-Auslese", „KI-Wasserauslese" …), damit
    die Meldungen wortgleich bleiben. `http` ist das HTTP-Modul: die Fassaden
    reichen ihr eigenes `httpx` durch, damit ein Test es dort ersetzen kann und
    aus einem Testlauf niemals ein echter Netzaufruf wird.

    Wirft nie — jeder Fehler steckt in der zurückgegebenen `Antwort`."""
    if http is None:
        http = httpx
    if http is None:
        return Antwort(fehler="httpx fehlt")
    key = api_schluessel(schluessel)
    if not key:
        return Antwort(fehler="kein Key")

    if bild is not None:
        try:
            b64 = base64.b64encode(bild).decode("ascii")
        except Exception:                                  # noqa: BLE001
            return Antwort(fehler="Bild unlesbar")
        nachricht = [
            {"type": "image", "source": {
                "type": "base64", "media_type": media_type, "data": b64}},
            {"type": "text", "text": inhalt},
        ]
    else:
        nachricht = inhalt

    rumpf: dict = {"model": api_modell(modell), "max_tokens": max_tokens}
    if system:
        rumpf["system"] = system
    rumpf["messages"] = [{"role": "user", "content": nachricht}]
    kopf = {
        "x-api-key": key,
        "anthropic-version": API_VERSION,
        "content-type": "application/json",
    }

    ergebnis = Antwort(fehler="kein Versuch")
    for _ in range(max(1, versuche)):
        ergebnis = _versuch(http, kopf, rumpf, zeitlimit, etikett)
        if ergebnis.ok or ergebnis.status not in _WIEDERHOLBAR:
            break
    return ergebnis
