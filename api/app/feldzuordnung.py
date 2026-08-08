"""N263 — vom KI-Raster zu den Formularfeldern einer Eintragsart.

Die KI liefert je Belegtyp ein Raster (`felder`, CCLXXIV) plus die grossen
Einzelwerte (`betrag`, `datum`, `absender`, `dokumenttyp`). Die Formulare im
Frontend haben eigene Feldnamen — „Beurkundet am" heisst dort `datum`, der
Kaufpreis `betrag`. Dazwischen fehlte die Übersetzung: das Raster wurde nur
angezeigt, nie in ein Formular übernommen.

Diese Zuordnung wohnt bewusst **hier auf dem Server**, direkt neben der
KI-Auslese:

* Es gibt sie damit **einmal**. Läge sie im Frontend, brauchte jede Seite, die
  einen Eintrag anlegt, ihre eigene Kopie — und die liefen mit der Zeit
  auseinander (genau der Fehler, den `belegscan.js` schon einmal heilen musste).
* Der Prompt, der die Rasternamen vorgibt, steht ebenfalls hier
  (`kiauslese.SYSTEM_PROMPT`). Wer dort ein Feld ergänzt, sieht die Zuordnung
  daneben und vergisst sie nicht.

Die Formularfeldnamen sind die des Modells — dieselben, die
`objekt-felder.js` zeigt und die die generischen Stammdaten-Endpunkte per
`hasattr` durchlassen. Ändert sich dort ein Name, muss er hier mitwandern;
`test_feldzuordnung.py` prüft die Namen gegen das Modell, damit ein
Auseinanderlaufen auffällt statt still zu wirken.
"""
from __future__ import annotations

from datetime import date

# Welche Quellen ein Formularfeld füttern, in dieser Reihenfolge. Ein Name wird
# zuerst im KI-Raster (`felder`) gesucht, dann unter den Einzelwerten der
# Auslese. Der erste belegte Treffer gewinnt — mehrere Kandidaten, weil die KI
# je nach Beleg mal „kaufpreis", mal „betrag" schreibt.
ZUORDNUNG: dict[str, dict[str, tuple[str, ...]]] = {
    "notarvertraege": {
        "art": ("art", "vertragsart", "dokumenttyp"),
        "notar": ("notar", "notariat", "absender"),
        "urnr": ("urnr", "urkundenrolle", "urkundennummer"),
        "datum": ("beurkundet_am", "kaufdatum", "datum"),
        "betrag": ("kaufpreis", "betrag"),
        "beteiligte": ("beteiligte", "vertragsparteien", "kaeufer"),
    },
    "versicherungen": {
        "art": ("art", "sparte", "dokumenttyp"),
        "anbieter": ("anbieter", "versicherer", "absender"),
        "police_nr": ("police_nr", "policennummer", "versicherungsschein_nr"),
        "jahresbeitrag": ("jahresbeitrag", "beitrag", "betrag"),
        "turnus": ("turnus", "zahlweise"),
        "versicherungswert": ("versicherungssumme", "versicherungswert"),
        "beginn": ("beginn", "versicherungsbeginn"),
        "ende": ("ende", "ablauf"),
        "umlagefaehig": ("umlagefaehig",),
    },
    "kredite": {
        "bezeichnung": ("bezeichnung", "dokumenttyp"),
        "bank": ("bank", "kreditinstitut", "bausparkasse", "absender"),
        "darlehensnummer": ("darlehensnummer", "vertragsnummer", "kontonummer"),
        "urspruenglich": ("darlehenssumme", "urspruenglich"),
        "restschuld": ("restschuld",),
        "bausparsumme": ("bausparsumme",),
        "angespart": ("angespart", "guthaben"),
        "zinssatz": ("zinssatz", "sollzins"),
        "rate_monatlich": ("rate_monatlich", "rate", "monatsrate"),
        "beginn": ("beginn", "vertragsbeginn"),
        "zinsbindung_bis": ("zinsbindung_bis",),
    },
    "mieten": {
        "partei": ("mieter", "partei"),
        "kaltmiete": ("kaltmiete", "grundmiete"),
        "nebenkosten_vz": ("nebenkosten_vz", "nebenkosten"),
        "stellplatz": ("stellplatzmiete", "stellplatz"),
        "sonstige": ("sonstige_einnahmen", "sonstige"),
        "ab_datum": ("mietbeginn", "beginn"),
        "bis_datum": ("mietende", "ende"),
        "personen": ("personen",),
        "kaution": ("kaution",),
    },
    "zahlungen": {
        "art": ("art", "kostenart", "dokumenttyp"),
        "jahr": ("jahr", "abrechnungsjahr"),
        "betrag": ("jahresbetrag", "betrag"),
        "turnus": ("turnus",),
    },
    # N270 — die Renovierungsposten-Maske: eine Rechnung eines Handwerkers,
    # bereits einem Gewerk zugeordnet (`kiauslese._gewerk`, gegen die feste
    # Liste geprüft — hier wird nur noch durchgereicht, nicht erneut geprüft).
    "renovierungsposten": {
        "datum": ("datum",),
        "betrag": ("betrag",),
        "firma": ("firma", "absender"),
        "gewerk": ("gewerk",),
        # Erst eine eigens genannte Notiz, sonst die knappe Kostenart, sonst
        # notfalls die lange Zusammenfassung — lieber ein Fließtext als leer.
        "notiz": ("notiz", "kostenart", "zusammenfassung"),
    },
}

# Welcher Typ welchen Wert braucht. Ohne das käme ein Datum als „11.06.2026"
# ins `type=date`-Feld (und bliebe leer) und ein Betrag als „87,00 €" ins
# Zahlenfeld.
DATUMSFELDER = {"datum", "beginn", "ende", "ab_datum", "bis_datum",
                "zinsbindung_bis", "kaution_eingang"}
ZAHLFELDER = {"betrag", "jahresbeitrag", "versicherungswert", "kaltmiete",
              "nebenkosten_vz", "stellplatz", "sonstige", "kaution",
              "personen", "jahr", "urspruenglich", "restschuld",
              "bausparsumme", "angespart", "zinssatz", "rate_monatlich"}
JANEIN_FELDER = {"umlagefaehig", "absetzbar"}


def _als_datum(wert) -> str | None:
    """Ein Datum als ISO-String — oder `None`, wenn nichts Brauchbares kommt.

    Die KI liefert meist schon ISO; ein deutsches „11.06.2026" wird trotzdem
    angenommen, sonst bliebe das Feld leer und der Nutzer tippt es doch ab."""
    if isinstance(wert, date):
        return wert.isoformat()
    text = str(wert or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        pass
    teile = text.replace("/", ".").split(".")
    if len(teile) == 3 and all(t.strip().isdigit() for t in teile):
        tag, monat, jahr = (t.strip() for t in teile)
        if len(jahr) == 2:
            jahr = f"20{jahr}"
        try:
            return date(int(jahr), int(monat), int(tag)).isoformat()
        except ValueError:
            return None
    return None


def _als_zahl(wert) -> float | None:
    """Eine Zahl aus dem, was die KI schreibt — „1.234,56 €" ebenso wie 1234.56.

    Bewusst eigenständig statt `kiauslese._betrag`: dort geht es um den einen
    Rechnungsbetrag (immer positiv, mit Plausibilitätsgrenzen). Hier zählt auch
    ein Zinssatz oder eine Personenzahl."""
    if isinstance(wert, bool):
        return None
    if isinstance(wert, (int, float)):
        return float(wert)
    text = str(wert or "").strip()
    if not text:
        return None
    text = (text.replace("€", "").replace("EUR", "").replace("%", "")
                .replace(" ", "").replace(" ", "").strip())
    # Deutsches Format: Punkt trennt Tausender, Komma die Nachkommastellen.
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _als_wahrheit(wert):
    """Ja/Nein — nur bei einem klaren Signal, sonst `None` (Feld bleibt leer)."""
    if isinstance(wert, bool):
        return wert
    text = str(wert or "").strip().lower()
    if text in ("ja", "true", "wahr", "1", "umlagefähig", "umlagefaehig"):
        return True
    if text in ("nein", "false", "falsch", "0"):
        return False
    return None


def _quelle(ergebnis: dict, name: str):
    """Einen Namen erst im KI-Raster suchen, dann unter den Einzelwerten."""
    raster = ergebnis.get("felder")
    if isinstance(raster, dict) and raster.get(name) not in (None, ""):
        return raster[name]
    wert = ergebnis.get(name)
    return wert if wert not in (None, "") else None


def werte_fuer(bereich: str, ergebnis: dict) -> dict:
    """Die Formularwerte einer Eintragsart aus einer KI-Auslese.

    Gibt nur zurück, was wirklich belegt ist — ein leeres Feld bleibt leer,
    statt mit „" oder 0 überschrieben zu werden. Der Nutzer sieht danach ein
    vorausgefülltes Formular und ändert, was nicht stimmt; nichts wird ohne
    seine Bestätigung gespeichert."""
    zuordnung = ZUORDNUNG.get(bereich)
    if not zuordnung or not isinstance(ergebnis, dict):
        return {}
    werte: dict = {}
    for feld, kandidaten in zuordnung.items():
        roh = next((w for w in (_quelle(ergebnis, k) for k in kandidaten)
                    if w is not None), None)
        if roh is None:
            continue
        if feld in DATUMSFELDER:
            wert = _als_datum(roh)
        elif feld in ZAHLFELDER:
            wert = _als_zahl(roh)
        elif feld in JANEIN_FELDER:
            wert = _als_wahrheit(roh)
        else:
            wert = str(roh).strip() or None
        if wert is not None:
            werte[feld] = wert
    return werte


def namensvorschlag(bereich: str, werte: dict) -> str:
    """Wie die Datei zu diesem Eintrag heissen soll — Art, Nummer, Datum.

    Beispiel Notarvertrag: „Notarvertrag Kaufvertrag URNr 123" plus das Datum,
    das `dateiname()` ohnehin vorne setzt. Bewusst ohne Endung und ohne Betrag:
    beides hängt `dateiname()` selbst an, sonst stünde es doppelt.

    Hier wird NICHT `ohne_datum()` angewandt, obwohl das nahe läge: eine
    Urkundenrollennummer trägt oft die Jahreszahl (`123/2024`), und der Filter
    hielte sie für ein Datum und schnitte sie weg. `dateiname()` räumt eine
    doppelte Jahresangabe später ohnehin auf."""
    if bereich == "renovierungsposten":
        # N270 — eigenes Muster statt Art+Nummer: „Renovierung Elektro Muster
        # GmbH". Datum und Betrag hängt `dateiname()` selbst an, die stünden
        # sonst doppelt.
        return " ".join(stueck for stueck in
                        ("Renovierung", werte.get("gewerk"), werte.get("firma"))
                        if stueck).strip()
    stuecke: list[str] = []
    einzahl = {"notarvertraege": "Notarvertrag", "versicherungen": "Versicherung",
               "kredite": "Vertrag", "mieten": "Mietvertrag",
               "zahlungen": "Zahlung"}.get(bereich, "")
    if einzahl:
        stuecke.append(einzahl)
    art = str(werte.get("art") or werte.get("bezeichnung")
              or werte.get("partei") or "").strip()
    # „Notarvertrag Notarvertrag" wäre albern — die Art nur, wenn sie etwas
    # Neues sagt.
    if art and art.lower() != einzahl.lower():
        stuecke.append(art)
    nummer = str(werte.get("urnr") or werte.get("police_nr")
                 or werte.get("darlehensnummer") or "").strip()
    if nummer:
        marke = "URNr" if werte.get("urnr") else "Nr"
        stuecke.append(f"{marke} {nummer}")
    return " ".join(stuecke).strip()
