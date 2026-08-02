"""N126 — den SolarEdge-Screenshot auslesen: die reine Logik ohne Netzaufruf.

Der Nutzer liest seine Stromdaten in der SolarEdge-Oberfläche ab und lädt statt
abzutippen den Screenshot hoch. Darauf stehen zwei waagerechte Balken:

* **Produktion** — z. B. ``12.5 MWh``, aufgeteilt in „Ins Netz" · „Ins Gebäude"
  · „Zum Speicher" (in dieser Reihenfolge im Balken).
* **Verbrauch** — z. B. ``10.8 MWh``, aufgeteilt in „Vom Netz" ·
  „Aus PV-Energie" · „Vom Speicher".

Gebraucht wird vor allem die Verbrauchszeile: aus ihren drei Anteilen macht
:func:`strombloecke.aus_solaredge` die beiden Kostenblöcke (zugekauft / eigen).
Die Produktionszeile kommt mit, weil daraus die Einspeisung folgt.

Dieses Modul enthält **nur** die prüfbare Rechnung:

* Einheiten — die Balken sind meist in **MWh** beschriftet, gerechnet wird in
  **kWh**. Die Einheit wird mitgelesen, nicht angenommen.
* Plausibilität — die drei Anteile eines Balkens müssen 100 % ergeben.
  Tun sie das nicht, gibt es eine **Warnung**, keinen Fehler: der Nutzer sieht
  die Zahlen ohnehin, bevor er sie übernimmt.
* Prozent → kWh.

Der KI-Aufruf lebt in ``kiauslese.lies_solaredge``, der Endpunkt in
``routers/solaredge.py``. Was das Bild nicht hergibt, bleibt ``None`` — nie 0,
denn eine 0 sähe aus wie eine Messung.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Die drei Anteile eines Balkens ergeben zusammen 100 %. SolarEdge rundet auf
# ganze Prozent, deshalb ist eine halbe Prozentspanne erlaubt — mehr ist ein
# Lesefehler und wird gemeldet, statt stillschweigend geglättet zu werden.
TOLERANZ = 0.5

# Umrechnung auf kWh. Mehr Einheiten kennt die Oberfläche nicht.
FAKTOR = {"wh": 0.001, "kwh": 1.0, "mwh": 1000.0}

# Die Bildformate, die die Bilderkennung annimmt (PNG oder JPEG kommt vom
# Handy, WEBP von manchen Browsern).
_SIGNATUREN: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)
ERLAUBTE_TYPEN = ("image/png", "image/jpeg", "image/gif", "image/webp")

_ZAHL = re.compile(r"-?\d[\d.,\s ]*")
_EINHEIT = re.compile(r"(?i)([km]?)\s*wh\b")
_VORSATZ = {"": "Wh", "k": "kWh", "m": "MWh"}


def _zahl(wert) -> float | None:
    """Eine Zahl aus dem, was das Modell liefert — ``None``, wenn nichts drin
    steht.

    Nimmt Punkt wie Komma als Dezimaltrenner (``12.5`` und ``12,5``). Ein
    einzelner Trenner mit genau drei Ziffern dahinter ist ein Tausendertrenner
    (``12.500`` → 12500), sonst ein Dezimaltrenner — die Regel, mit der auch
    Menschen deutsche und englische Schreibweise auseinanderhalten."""
    if isinstance(wert, bool):        # bool ist eine Zahl in Python — hier nicht
        return None
    if isinstance(wert, (int, float)):
        return float(wert)
    if not isinstance(wert, str):
        return None
    treffer = _ZAHL.search(wert)
    if not treffer:
        return None
    roh = re.sub(r"[\s ]", "", treffer.group())
    letzte = max(roh.rfind("."), roh.rfind(","))
    if letzte < 0:
        ganz, rest = roh, ""
    else:
        ganz, rest = roh[:letzte], roh[letzte + 1:]
        if len(rest) == 3 and roh.count(".") + roh.count(",") == 1:
            ganz, rest = ganz + rest, ""    # Tausendertrenner
    ganz = re.sub(r"[.,]", "", ganz)
    try:
        return float(f"{ganz}.{rest}" if rest else ganz)
    except ValueError:
        return None


def einheit(text) -> str:
    """Die Mengeneinheit aus einer Angabe („MWh", „12.5 MWh", „kwh") — leer,
    wenn keine erkennbar ist. Groß/Klein spielt keine Rolle, die Oberfläche
    schreibt „MWh", das Modell manchmal „mwh"."""
    if not isinstance(text, str):
        return ""
    treffer = _EINHEIT.search(text)
    return _VORSATZ[treffer.group(1).lower()] if treffer else ""


def nach_kwh(wert, mass: str = "", bereich: str = "") -> tuple[float | None, str]:
    """Eine abgelesene Menge in kWh — plus eine Warnung, falls etwas unklar war.

    Gibt ``(kwh, warnung)`` zurück; die Warnung ist leer, wenn alles glatt war.
    Fehlt die Einheit ganz, wird kWh angenommen **und** gewarnt — der Nutzer
    soll den Faktor 1000 nicht übersehen. Steht die Einheit im Wert selbst
    („12.5 MWh"), zählt sie auch."""
    menge = _zahl(wert)
    if menge is None:
        return None, ""
    name = bereich or "Der Wert"
    if menge < 0:
        return None, f"{name} wurde negativ gelesen — bitte von Hand eintragen."
    gefunden = einheit(mass) or einheit(wert if isinstance(wert, str) else "")
    faktor = FAKTOR.get(gefunden.lower())
    if faktor is None:
        return (round(menge, 3),
                f"{name}: keine Einheit erkannt — als kWh gewertet. "
                "Steht auf dem Bild MWh, ist der Wert mal 1000 zu nehmen.")
    return round(menge * faktor, 3), ""


def prozent(wert) -> float | None:
    """Ein Anteil in Prozent (0 bis 100) — alles andere ist ``None``.

    Ein Wert über 100 ist kein Anteil, sondern ein Lesefehler; lieber keine
    Angabe als eine falsche."""
    anteil = _zahl(wert)
    if anteil is None or not 0.0 <= anteil <= 100.0:
        return None
    return round(anteil, 2)


def pruefe_anteile(bereich: str, anteile: dict[str, float | None]) -> list[str]:
    """Ergeben die drei Anteile eines Balkens 100 %?

    Fehlende Anteile und eine Summe außerhalb der Toleranz werden gemeldet —
    als Warnung, nicht als Fehler. Sind alle drei Anteile gar nicht gelesen
    worden, gibt es keine Warnung: dann fehlt der Balken schlicht, und das sagt
    schon das leere Ergebnis."""
    fehlend = [name for name, wert in anteile.items() if wert is None]
    if len(fehlend) == len(anteile):
        return []
    if fehlend:
        return [f"{bereich}: {', '.join(fehlend)} nicht erkannt — "
                "bitte den Anteil von Hand eintragen."]
    summe = sum(wert for wert in anteile.values() if wert is not None)
    if abs(summe - 100.0) > TOLERANZ:
        return [f"{bereich}: die Anteile ergeben {summe:.0f} % statt 100 % — "
                "bitte die Werte am Bildschirm prüfen."]
    return []


def kwh_je_anteil(gesamt_kwh: float | None,
                  anteile: dict[str, float | None]) -> dict[str, float | None]:
    """Die Anteile eines Balkens in kWh — ``None``, wo eine Angabe fehlt.

    Beispiel des Nutzers: 10,8 MWh Verbrauch mit 24 % / 50 % / 26 % →
    2592 kWh vom Netz, 5400 kWh aus PV, 2808 kWh aus dem Speicher."""
    if gesamt_kwh is None:
        return {name: None for name in anteile}
    return {name: (None if wert is None else round(gesamt_kwh * wert / 100.0, 3))
            for name, wert in anteile.items()}


@dataclass
class Ablesung:
    """Was auf dem Screenshot stand — Mengen in kWh, Anteile in Prozent.

    Jedes Feld darf ``None`` sein: was das Bild nicht hergibt, wird nicht
    geraten. `warnungen` sammelt, was nachzuprüfen ist."""
    produktion_kwh: float | None = None
    produktion_netz_prozent: float | None = None
    produktion_gebaeude_prozent: float | None = None
    produktion_speicher_prozent: float | None = None
    verbrauch_kwh: float | None = None
    verbrauch_netz_prozent: float | None = None
    verbrauch_pv_prozent: float | None = None
    verbrauch_speicher_prozent: float | None = None
    warnungen: list[str] = field(default_factory=list)

    @property
    def erkannt(self) -> bool:
        """Steht wenigstens die Verbrauchszeile? Ohne sie ist nichts gewonnen —
        sie ist es, aus der die beiden Kostenblöcke entstehen."""
        return self.verbrauch_kwh is not None

    def als_dict(self) -> dict:
        """Die flache Form für die API — dieselben Namen wie im Datenmodell."""
        return {
            "produktion_kwh": self.produktion_kwh,
            "produktion_netz_prozent": self.produktion_netz_prozent,
            "produktion_gebaeude_prozent": self.produktion_gebaeude_prozent,
            "produktion_speicher_prozent": self.produktion_speicher_prozent,
            "verbrauch_kwh": self.verbrauch_kwh,
            "verbrauch_netz_prozent": self.verbrauch_netz_prozent,
            "verbrauch_pv_prozent": self.verbrauch_pv_prozent,
            "verbrauch_speicher_prozent": self.verbrauch_speicher_prozent,
            "verbrauch_kwh_je_anteil": kwh_je_anteil(self.verbrauch_kwh, {
                "netz": self.verbrauch_netz_prozent,
                "pv": self.verbrauch_pv_prozent,
                "speicher": self.verbrauch_speicher_prozent,
            }),
            "produktion_kwh_je_anteil": kwh_je_anteil(self.produktion_kwh, {
                "netz": self.produktion_netz_prozent,
                "gebaeude": self.produktion_gebaeude_prozent,
                "speicher": self.produktion_speicher_prozent,
            }),
            "erkannt": self.erkannt,
            "warnungen": list(self.warnungen),
        }


def _flach(roh) -> dict:
    """Die Modellantwort flach machen.

    Der Prompt fragt flache Felder ab; liefert das Modell doch zwei Blöcke
    (`{"verbrauch": {...}}`), werden sie mit dem Bereichsnamen davor
    eingereiht. Alles andere (Text statt JSON, Liste, ``None``) ergibt ein
    leeres dict — der Aufrufer bekommt dann ein leeres Ergebnis, keine
    Exception."""
    if not isinstance(roh, dict):
        return {}
    flach: dict = {}
    for schluessel, wert in roh.items():
        name = str(schluessel).strip().lower()
        if isinstance(wert, dict) and name in ("produktion", "verbrauch"):
            for unter, tiefer in wert.items():
                if not isinstance(tiefer, (dict, list)):
                    flach[f"{name}_{str(unter).strip().lower()}"] = tiefer
        elif not isinstance(wert, (dict, list)):
            flach[name] = wert
    return flach


def aufbereiten(roh) -> Ablesung:
    """Aus der (unsicheren) Modellantwort eine geprüfte Ablesung machen.

    Nimmt entgegen, was kommt — leeres dict, Text statt JSON, Prozente über
    100, fehlende Einheit — und liefert immer eine `Ablesung`. Unbrauchbares
    wird zu ``None`` mit Warnung, nie zu 0."""
    daten = _flach(roh)
    a = Ablesung()

    for bereich, anzeige in (("produktion", "Produktion"), ("verbrauch", "Verbrauch")):
        menge = daten.get(f"{bereich}_wert")
        if menge is None:
            menge = daten.get(f"{bereich}_kwh")
        mass = daten.get(f"{bereich}_einheit", "")
        kwh, warnung = nach_kwh(menge, mass if isinstance(mass, str) else "", anzeige)
        setattr(a, f"{bereich}_kwh", kwh)
        if warnung:
            a.warnungen.append(warnung)

    a.produktion_netz_prozent = prozent(daten.get("produktion_netz_prozent"))
    a.produktion_gebaeude_prozent = prozent(daten.get("produktion_gebaeude_prozent"))
    a.produktion_speicher_prozent = prozent(daten.get("produktion_speicher_prozent"))
    a.verbrauch_netz_prozent = prozent(daten.get("verbrauch_netz_prozent"))
    a.verbrauch_pv_prozent = prozent(daten.get("verbrauch_pv_prozent"))
    a.verbrauch_speicher_prozent = prozent(daten.get("verbrauch_speicher_prozent"))

    a.warnungen += pruefe_anteile("Verbrauch", {
        "„Vom Netz“": a.verbrauch_netz_prozent,
        "„Aus PV-Energie“": a.verbrauch_pv_prozent,
        "„Vom Speicher“": a.verbrauch_speicher_prozent,
    })
    a.warnungen += pruefe_anteile("Produktion", {
        "„Ins Netz“": a.produktion_netz_prozent,
        "„Ins Gebäude“": a.produktion_gebaeude_prozent,
        "„Zum Speicher“": a.produktion_speicher_prozent,
    })
    if a.verbrauch_kwh is None:
        a.warnungen.append(
            "Die Verbrauchszeile wurde nicht gelesen — bitte die Werte von Hand "
            "eintragen.")
    return a


def medientyp(rohdaten: bytes, angabe: str = "") -> str:
    """Der Bildtyp des Uploads — am Inhalt erkannt, nicht am Wort des Browsers.

    Handys schicken oft „application/octet-stream"; die Bilderkennung braucht
    aber den richtigen Typ. Deshalb entscheidet die Signatur der Datei, und die
    Angabe des Browsers gilt nur, wenn sie zu einem erlaubten Typ passt und die
    Signatur nichts hergibt. Ist beides unbrauchbar, kommt ein leerer String —
    der Aufrufer lehnt dann ab, statt Unsinn hochzuladen."""
    kopf = rohdaten[:16] if rohdaten else b""
    for signatur, typ in _SIGNATUREN:
        if kopf.startswith(signatur):
            return typ
    if kopf[:4] == b"RIFF" and kopf[8:12] == b"WEBP":
        return "image/webp"
    gemeldet = (angabe or "").split(";")[0].strip().lower()
    if gemeldet == "image/jpg":                      # verbreitete Falschschreibung
        gemeldet = "image/jpeg"
    return gemeldet if gemeldet in ERLAUBTE_TYPEN else ""
