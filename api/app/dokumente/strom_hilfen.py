"""Formatierungshelfer für den KI-Stromzweig (N162).

Der gezielte Auslesezweig für Strombelege (`kiauslese.lies_strom`) liefert
Menge, Bruttobetrag der Lieferung sowie Nachzahlung/Abschlag und den
abgerechneten Zeitraum. Damit diese Bausteine sauber in die reguläre Antwort
von `/erkennen` gezogen werden können, wohnen die drei Formatierungshelfer
hier — losgelöst von der Cloud- und Session-Umgebung des Routers.

* `_strom_hinweis` verdichtet, was auf einen Strombeleg deutet, zu einem Satz.
* `_zeitraum_text` formatiert einen Auslese-Zeitraum lesbar.
* `_strom_in_felder` zieht die spezifischen Werte in die gemeinsame `felder`-
  Struktur, ohne bestehende Angaben aus der allgemeinen Auslese zu überschreiben.
"""
from __future__ import annotations

from datetime import date


def _strom_hinweis(kostenart: str, ergebnis: dict) -> str:
    """Alles, was auf einen Strombeleg deuten kann, in einem Satz.

    Nicht nur der Kontext-Hinweis der Oberfläche (den gibt es nur beim Ablegen
    an einer Position), sondern auch, was die allgemeine Auslese schon erkannt
    hat: Sache, Belegart, Absender und die Kostenart aus dem Raster. So greift
    der Zweig auch im Dokumenteneingang, wo niemand eine Kostenart mitschickt."""
    felder = ergebnis.get("felder")
    felder = felder if isinstance(felder, dict) else {}
    teile = (kostenart, ergebnis.get("sache"), ergebnis.get("dokumenttyp"),
             ergebnis.get("absender"), felder.get("kostenart"))
    return " ".join(str(t) for t in teile if t)


def _zeitraum_text(von: str | None, bis: str | None) -> str:
    """Der abgerechnete Zeitraum lesbar — „15.06.2024 – 14.06.2025"."""
    def tag(iso: str | None) -> str:
        try:
            return date.fromisoformat(iso).strftime("%d.%m.%Y") if iso else ""
        except (ValueError, TypeError):
            return ""
    beide = [t for t in (tag(von), tag(bis)) if t]
    return " – ".join(beide)


def _strom_in_felder(ergebnis: dict, strom: dict) -> None:
    """Menge und Betrag der Stromauslese in die Antwortfelder ziehen.

    Der gezielte Zweig ist die genauere Quelle — er hält Lieferung, Nachzahlung
    und Abschlag auseinander. Sein Betrag hat deshalb Vorrang, auch im Raster
    (`felder`), aus dem das Prüfblatt seine Eingaben vorbelegt: sonst stünde
    dort weiter die Nachzahlung, ein Zwanzigstel der Rechnung."""
    menge, betrag = strom.get("menge_kwh"), strom.get("betrag")
    if betrag:
        ergebnis["betrag"] = betrag
    felder = ergebnis.get("felder")
    if not isinstance(felder, dict):
        felder = ergebnis["felder"] = {}
    if betrag:
        felder["betrag"] = betrag
        felder["betrag_art"] = strom.get("betrag_label") or ""
    if menge:
        felder["verbrauch_kwh"] = menge
    if strom.get("preis_kwh"):
        felder["preis_kwh"] = strom["preis_kwh"]
    for schluessel in ("nachzahlung", "abschlag_monat"):
        if strom.get(schluessel):
            felder[schluessel] = strom[schluessel]
    zeitraum = _zeitraum_text(strom.get("von"), strom.get("bis"))
    if zeitraum:
        felder["zeitraum"] = zeitraum
        if not (ergebnis.get("zeitraum_hinweis") or "").strip():
            ergebnis["zeitraum_hinweis"] = zeitraum
    # Eine Verbrauchsabrechnung mit Menge UND Bruttobetrag ist zweifelsfrei ein
    # Kostenbeleg. Hatte eine Erkennungsregel sie zuvor auf „keine Kosten"
    # gestellt — ein Muster wie „N-ERGIE Netz" trifft auch die Fußzeile einer
    # Stromrechnung —, wäre der Betrag sonst verloren: genau das leere
    # Betragsfeld, das gemeldet wurde.
    if menge and strom.get("brutto"):
        ergebnis["ist_kosten"] = True
        if ergebnis.get("kosten_relevant") is False:
            ergebnis["kosten_relevant"] = True
