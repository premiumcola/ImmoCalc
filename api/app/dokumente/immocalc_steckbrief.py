"""Der `.immocalc`-Steckbrief (CCLXXIV) — reiner Text, der neben das PDF legt.

`_immocalc_text` baut den menschenlesbaren Steckbrief aus dem Dokument und dem
per KI-Auslese gezogenen Raster; `_FELD_TITEL` übersetzt die technischen
Rasterschlüssel in Klartext. Beides reine Textbausteine ohne Datenbank- oder
Cloud-Zugriff — das Schreiben der Datei und das additive Festhalten am
Dokument bleiben im Router (`app/routers/dokumente.py`), wo sie eng an die
Session hängen.

`body` kommt als `ImmoCalcIn` (Pydantic-Model im Router) herein, wird hier
aber nur über Attribute gelesen (duck-typed) — ein Rückimport aus dem Router
würde einen Zirkel öffnen.
"""
from __future__ import annotations

from ..cloudkern import ZIELORDNER
from .darstellung import _feld_wert
from .datum import _zum_datum

# Wie die Rasterfelder im Steckbrief heissen — technischer Schlüssel → Klartext.
# Was nicht in der Karte steht, wird mit seinem Schlüssel gezeigt (nichts geht
# verloren), damit ein neues Feld nicht stumm bleibt.
_FELD_TITEL = {
    "mieter": "Mieter", "kaltmiete": "Kaltmiete",
    "nebenkosten_vz": "Nebenkosten-Vorauszahlung",
    "stellplatzmiete": "Stellplatzmiete",
    "sonstige_einnahmen": "Sonstige Einnahmen", "mietbeginn": "Mietbeginn",
    "kaution": "Kaution", "personen": "Personen",
    "mieter_email": "E-Mail Mieter", "mieter_telefon": "Telefon Mieter",
    "art": "Art", "anbieter": "Anbieter", "police_nr": "Police-Nr.",
    "jahresbeitrag": "Jahresbeitrag", "turnus": "Turnus",
    "versicherungssumme": "Versicherungssumme", "beginn": "Beginn",
    "ende": "Ende", "umlagefaehig": "Umlagefähig",
    "bezeichnung": "Bezeichnung", "bank": "Bank",
    "darlehensnummer": "Darlehensnummer", "darlehenssumme": "Darlehenssumme",
    "bausparsumme": "Bausparsumme", "angespart": "Angespart",
    "restschuld": "Restschuld", "zinssatz": "Zinssatz",
    "rate_monatlich": "Rate monatlich", "zinsbindung_bis": "Zinsbindung bis",
    "schuldzinsen_jahr": "Schuldzinsen im Jahr", "jahr": "Jahr",
    "grundsteuerwert": "Grundsteuerwert",
    "grundsteuer_messbetrag": "Grundsteuer-Messbetrag",
    "grundsteuer_hebesatz": "Hebesatz", "jahresbetrag": "Jahresbetrag",
    "kaufpreis": "Kaufpreis", "kaufdatum": "Kaufdatum",
    "gemarkung": "Gemarkung", "flurstueck": "Flurstück",
    "grundbuch_blatt": "Grundbuchblatt", "glaeubiger": "Gläubiger",
    "grundschuld_betrag": "Grundschuld-Betrag", "rang": "Rang",
    "verwalter": "Verwalter", "hausgeld_monatlich": "Hausgeld monatlich",
    "ruecklage_zufuehrung": "Rücklagenzuführung",
    "zeitraum": "Zeitraum", "s35a": "Haushaltsnahe Dienstleistung (§ 35a)",
    "verbrauch": "Verbrauch",
}


def _immocalc_text(d, body) -> str:
    """Der menschenlesbare Steckbrief, der neben dem PDF landet.

    Zeigt Datei, Dokumenttyp/Kategorie samt Zielordner, Liegenschaft, Einheit,
    Belegdatum, Betrag, Umlagefähigkeit und die erkannten Rasterangaben — knapp
    und ohne technische Wortwahl, damit der Steckbrief auch in der Cloud gelesen
    werden kann, ohne ImmoCalc zu öffnen."""
    zeilen: list[str] = ["ImmoCalc — Steckbrief zum Beleg", ""]
    zeilen.append(f"Datei: {d.dateiname}")
    kategorie = body.kategorie or d.kategorie
    if kategorie:
        ordner = ZIELORDNER.get(kategorie, "99_Sonstiges")
        zeilen.append(f"Kategorie: {kategorie} → {ordner}")
    if body.immobilie:
        zeilen.append(f"Immobilie: {body.immobilie}")
    if body.einheit:
        zeilen.append(f"Einheit: {body.einheit}")
    belegdatum = _zum_datum(body.datum or "") or d.belegdatum
    if belegdatum:
        zeilen.append(f"Belegdatum: {belegdatum.isoformat()}")
    betrag = body.betrag if body.betrag is not None else d.betrag
    if betrag is not None:
        zeilen.append(f"Betrag: {betrag:.2f} €".replace(".", ","))
    umlage = (body.felder or {}).get("umlagefaehig")
    if isinstance(umlage, bool):
        zeilen.append(f"Umlagefähig: {'Ja' if umlage else 'Nein'}")

    weitere = {k: v for k, v in (body.felder or {}).items()
               if k != "umlagefaehig"}
    if weitere:
        zeilen += ["", "Erkannte Angaben:"]
        for schluessel, wert in weitere.items():
            titel = _FELD_TITEL.get(schluessel, schluessel)
            zeilen.append(f"  - {titel}: {_feld_wert(wert)}")

    einordnung = (body.einordnung or d.ki_einordnung or "").strip()
    if einordnung:
        zeilen += ["", "Einordnung:", f"  {einordnung}"]
    return "\n".join(zeilen) + "\n"
