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

N280-D — dieselbe Gefahr gibt es auf der anderen Seite: nennt die Zuordnung
eine Quelle, die im Prompt gar nicht abgefragt wird, bleibt das Formularfeld
für immer leer, ohne dass irgendetwas rot wird. `test_prompt_raster.py` liest
deshalb die Raster direkt aus `kiauslese.SYSTEM_PROMPT` und hält beide Seiten
gegeneinander.
"""
from __future__ import annotations

from . import zahlen

import re
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
        # N280-D — `betrag` ist hier IMMER der Jahreswert: das Raster liefert
        # `jahresbetrag`, und `kiauslese._hochrechnung` macht aus vier Quartals-
        # raten den Jahresbetrag (N262). Dazu passt genau ein Turnus, nämlich
        # der Vorgabewert „jaehrlich" der Maske. Ein aus dem Beleg gelesener
        # Turnus („vierteljährlich", weil vier Fälligkeiten daraufstehen) würde
        # denselben Betrag ein zweites Mal mit vier multiplizieren — deshalb
        # steht hier bewusst KEIN `turnus`.
        "betrag": ("jahresbetrag", "betrag"),
    },
    # N276 — die Maske der einmaligen Erwerbsnebenkosten. `art` kommt aus
    # `erwerbsart`, das `kiauslese` schon gegen die feste Liste geprüft hat —
    # hier steht bewusst KEIN Rückfall auf `kostenart`/`dokumenttyp`: die
    # lieferten Freitext („Kostenrechnung"), und der passt in keine Auswahl.
    "erwerbskosten": {
        "art": ("erwerbsart",),
        "jahr": ("jahr", "abrechnungsjahr"),
        # N338 — das Belegdatum, damit die Erwerbsnebenkosten eines Kaufs in
        # ihrer echten Reihenfolge stehen können. Die Erkennung liefert es
        # ohnehin; bisher fiel es hier unter den Tisch.
        "datum": ("datum", "rechnungsdatum", "belegdatum"),
        "betrag": ("betrag",),
        # N280-D — „notiz" fragt der Prompt nirgends ab; allein damit blieb das
        # Feld strukturell immer leer. Die knappe Kostenart („Beurkundung
        # Kaufvertrag") sagt hier genau das Richtige und steht in jeder Antwort.
        "notiz": ("notiz", "kostenart"),
    },
    # N270 — die Renovierungsposten-Maske: eine Rechnung eines Handwerkers,
    # bereits einem Gewerk zugeordnet (`kiauslese._gewerk`, gegen die feste
    # Liste geprüft — hier wird nur noch durchgereicht, nicht erneut geprüft).
    "renovierungsposten": {
        "datum": ("datum",),
        "betrag": ("betrag",),
        "firma": ("firma", "absender"),
        "gewerk": ("gewerk",),
        # Erst eine eigens genannte Notiz, dann die im Raster genannte Leistung
        # („Zählerschrank erneuert"), sonst die knappe Kostenart, sonst notfalls
        # die lange Zusammenfassung — lieber ein Fließtext als leer.
        "notiz": ("notiz", "leistung", "kostenart", "zusammenfassung"),
    },
    # N280-D — die Nebenkosten-Kostenposition (`Kostenposition`): eine Rechnung,
    # die als Position in einen Abrechnungszeitraum wandert. Der Zeitraum selbst
    # steht bewusst NICHT hier — er ist keine Eigenschaft der Position, sondern
    # wird beim Anlegen gewählt (`zeitraum_id`); wofür der Beleg zählt, sagt die
    # Auslese ohnehin getrennt (`abrechnungsjahr`, `zeitraum_hinweis`).
    "nebenkosten": {
        "kostenart": ("kostenart", "art"),
        # Bei einer Energieabrechnung ist der Bruttobetrag der Lieferung
        # gemeint, nicht die Nachzahlung — `betrag` trägt ihn laut Prompt
        # bereits, `bruttobetrag` ist der Rückfall aus dem Strom-Raster.
        "betrag": ("betrag", "bruttobetrag"),
        # § 35a: haushaltsnahe Dienstleistung (Schornsteinfeger, Wartung,
        # Hausmeister). Im Modell heisst das Feld `s35`.
        "s35": ("s35a", "s35"),
        # Die Menge hinter dem Betrag (m³ Wasser, kWh Strom) — sie trägt die
        # Verbrauchsanzeige und die Stromkette.
        "menge": ("verbrauch_kwh", "verbrauch"),
    },
    # N280-D — die Stammdaten des Objekts. Vier Belegarten füllen dieselbe
    # Maske, und sie stören sich nicht: `werte_fuer` gibt nur zurück, was der
    # jeweilige Beleg hergibt. Kaufvertrag → Kaufpreis/Kaufdatum,
    # Grundsteuerbescheid → die dreistufige Rechenkette, Grundbuchauszug →
    # Gemarkung/Flurstück, WEG-Abrechnung → Hausgeld, Rücklage, Verwalter.
    "stammdaten": {
        "kaufpreis": ("kaufpreis",),
        "kaufdatum": ("kaufdatum", "beurkundet_am"),
        "gemarkung": ("gemarkung",),
        "flurstueck": ("flurstueck",),
        "grundsteuerwert": ("grundsteuerwert",),
        "grundsteuer_messbetrag": ("grundsteuer_messbetrag",),
        "grundsteuer_hebesatz": ("grundsteuer_hebesatz",),
        "hausgeld_monatlich": ("hausgeld_monatlich",),
        "weg_ruecklage_zufuehrung": ("ruecklage_zufuehrung",),
        # Ohne Rückfall auf `absender`: der ist bei einem Kaufvertrag das
        # Notariat, und das stünde dann als Hausverwaltung im Objekt.
        "weg_verwalter": ("verwalter",),
    },
    # N280-D — die Grundschuld-Maske (`GRUNDSCHULDFELDER`). Aus demselben
    # Raster wie Gemarkung/Flurstück, aber ein eigener Datensatz: die Belastung
    # hängt am Objekt, nicht in seinen Stammdaten.
    "grundschulden": {
        "betrag": ("grundschuld_betrag", "betrag"),
        "rang": ("rang",),
        "grundbuch_blatt": ("grundbuch_blatt",),
        "glaeubiger": ("glaeubiger",),
    },
}

# Welcher Typ welchen Wert braucht. Ohne das käme ein Datum als „11.06.2026"
# ins `type=date`-Feld (und bliebe leer) und ein Betrag als „87,00 €" ins
# Zahlenfeld.
DATUMSFELDER = {"datum", "beginn", "ende", "ab_datum", "bis_datum",
                "zinsbindung_bis", "kaution_eingang", "kaufdatum"}
ZAHLFELDER = {"betrag", "jahresbeitrag", "versicherungswert", "kaltmiete",
              "nebenkosten_vz", "stellplatz", "sonstige", "kaution",
              "personen", "jahr", "urspruenglich", "restschuld",
              "bausparsumme", "angespart", "zinssatz", "rate_monatlich",
              # N280-D — Stammdaten, Grundschuld und Kostenposition
              "kaufpreis", "grundsteuerwert", "grundsteuer_messbetrag",
              "grundsteuer_hebesatz", "hausgeld_monatlich",
              "weg_ruecklage_zufuehrung", "menge"}
JANEIN_FELDER = {"umlagefaehig", "absetzbar", "s35"}
# N280-D — der Turnus ist kein Freitext, sondern einer von fünf Schlüsseln
# (`turnus.TURNUS`). Die KI schreibt „jährlich" mit Umlaut; so kam der Wert bis
# jetzt zwar an, passte aber zu keiner Option der Maske und fiel dort auf den
# Vorgabewert zurück — sichtbar wirkungslos.
TURNUSFELDER = {"turnus"}


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


# Eine Zahl am Anfang des Textes, samt Tausenderpunkt und Dezimalkomma.
_FUEHRENDE_ZAHL = re.compile(r"[-+]?\d[\d.,]*")


def _reine_zahl(text: str) -> float | None:
    """Eine Zahl in deutscher Schreibweise — die gemeinsame Regel aus `zahlen`.

    N313 — hier stand eine eigene Fassung, die OHNE Komma jeden Punkt als
    Dezimaltrenner nahm. „250.000 €" wurde damit zu **250,00 €**, während
    derselbe Beleg über `ki_werte._ki_zahl` als **250.000,00 €** in den
    Datensatz ging: Faktor 1000 im selben Feld. Jetzt gilt überall dieselbe
    Regel."""
    return zahlen.deutsch(text)


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
    zahl = _reine_zahl(text)
    if zahl is not None:
        return zahl
    # N280-D — eine Menge trägt ihre Einheit mit („122,00 cbm", „2416 kWh").
    # Ohne diesen Rückfall bliebe das Mengenfeld leer, obwohl die Zahl dasteht.
    # Nur am Anfang gesucht: aus „Rechnung 2024" soll keine Zahl werden.
    treffer = _FUEHRENDE_ZAHL.match(text)
    return _reine_zahl(treffer.group()) if treffer else None


# Welche Wörter auf welchen Turnus-Schlüssel führen. Die Schlüssel sind die von
# `turnus.TURNUS` — `test_feldzuordnung` hält sie dagegen. Die Reihenfolge ist
# Absicht: „vierteljährlich" enthält „jährlich" und wäre sonst jährlich.
_TURNUS_WOERTER: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("einmalig", ("einmalig", "einmal")),
    ("monatlich", ("monatlich", "monat", "mtl")),
    ("vierteljaehrlich", ("viertel", "quartal")),
    ("halbjaehrlich", ("halbjaehr", "halbjahr", "halb")),
    ("jaehrlich", ("jaehrlich", "jahr", "p.a")),
)


def _als_turnus(wert) -> str | None:
    """Ein Turnus-Schlüssel der App — oder `None`, wenn nichts passt.

    Lieber kein Turnus als ein unbekannter: ein Freitext, den die Auswahl nicht
    kennt, sähe im Formular wie eine leere Angabe aus und ginge beim Speichern
    doch mit."""
    text = " ".join(str(wert or "").split()).lower()
    text = (text.replace("ä", "ae").replace("ö", "oe")
                .replace("ü", "ue").replace("ß", "ss"))
    if not text:
        return None
    return next((schluessel for schluessel, woerter in _TURNUS_WOERTER
                 if any(wort in text for wort in woerter)), None)


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
        elif feld in TURNUSFELDER:
            wert = _als_turnus(roh)
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
    if bereich == "erwerbskosten" and werte.get("teile"):
        # N331b — eine Sammelrechnung mit mehreren benannten Positionen (z. B.
        # Landesjustizkasse: Auflassungsvormerkung UND Grundpfandrecht) heisst
        # nach beiden, nicht nur nach der Kategorie der grössten — die Summe
        # ist dort kein eigener Wert, sondern nur zweier verschiedener Kosten
        # Addition. „teile" kommt bewusst NICHT über `ZUORDNUNG`/`werte_fuer`
        # (der Aufrufer mischt es lose bei) — `Zahlung` hat kein Feld dafür,
        # und `ZUORDNUNG` darf nur auf echte Modellfelder zeigen (siehe
        # `test_zuordnung_nennt_nur_felder_die_es_im_modell_gibt`).
        return werte["teile"]
    stuecke: list[str] = []
    # N280-D — „nebenkosten" und „stammdaten" stehen bewusst NICHT hier: eine
    # Wasserrechnung heisst „Wasser", nicht „Nebenkosten Wasser", und ein
    # Kaufvertrag, der die Stammdaten füllt, heisst nach seiner Art — das Wort
    # „Stammdaten" sagt am Beleg nichts.
    einzahl = {"notarvertraege": "Notarvertrag", "versicherungen": "Versicherung",
               "kredite": "Vertrag", "mieten": "Mietvertrag",
               "zahlungen": "Zahlung",
               "grundschulden": "Grundschuld"}.get(bereich, "")
    if einzahl:
        stuecke.append(einzahl)
    art = str(werte.get("art") or werte.get("bezeichnung")
              or werte.get("partei") or werte.get("kostenart")
              or werte.get("glaeubiger") or "").strip()
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
