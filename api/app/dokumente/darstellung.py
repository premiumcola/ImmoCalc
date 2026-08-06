"""Kleine Anzeige-Bausteine für Belege — knapp, dumm, wiederverwendbar.

Jedes Wörtchen, das in mehreren Endpunkten dasselbe erzählen soll, gehört an
eine Stelle: die Kurzform eines Belegs (Abgleich-Rückmeldung), die Detailkarte
(Baum), der Chip-Eintrag im Anhänger-Fenster, das Fach-Ja/Nein für Rasterwerte,
der Anbieter aus dem KI-Raster. So bleibt die Datenform stabil, wenn dieselbe
Info an einer neuen Stelle gezeigt wird.

Die Helfer greifen nur auf Attribute vorhandener Modelle zu und legen keine
Daten an — sie sind reine Lese-Formatter.
"""
from __future__ import annotations


def _kurz(d, o) -> dict:
    """Ein Eintrag, so knapp wie die Rückmeldung ihn braucht."""
    return {"id": d.id, "dateiname": d.dateiname, "pfad": d.pfad,
            "objekt": o.slug, "objekt_name": o.name}


def _beleg_karte(d) -> dict:
    """Das Wenige, das die Detailansicht zu einem Beleg braucht."""
    return {"id": d.id, "dateiname": d.dateiname, "jahr": d.jahr,
            "status": d.status, "info": bool(d.info_zu_typ)}


def _anh_zeige(d) -> dict:
    """Ein Anhänger, so knapp wie die Chip-Anzeige ihn braucht."""
    return {"id": d.id, "dateiname": d.dateiname, "pfad": d.pfad,
            "kategorie": d.kategorie, "kostenart": d.kostenart, "jahr": d.jahr}


def _feld_wert(wert) -> str:
    """Ein Rasterwert als Klartext — Ja/Nein für Wahrheitswerte."""
    if isinstance(wert, bool):
        return "Ja" if wert else "Nein"
    return str(wert)


def _ist_kostenfrei(d) -> bool:
    """Ein Beleg ohne eigenen Kostenanteil: in keine Kostenposition
    eingerechnet (`position_id` leer) und ohne Betrag."""
    return d.position_id is None and not d.betrag


def _beleg_anbieter(d) -> str:
    """Der Aussteller/Anbieter des Belegs aus dem KI-Raster (N37).

    Für Versicherungsbelege liefert die KI-Auslese den `anbieter` im Raster
    (`kiauslese`, Raster VERSICHERUNG); andere Belege tragen ihn als
    `absender`. Leer, wenn keiner erkannt wurde."""
    felder = d.ki_felder or {}
    roh = felder.get("anbieter") or felder.get("absender") or ""
    return roh.strip() if isinstance(roh, str) else ""
