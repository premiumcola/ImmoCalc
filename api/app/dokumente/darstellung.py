"""Kleine Anzeige-Bausteine für Belege — knapp, dumm, wiederverwendbar.

Jedes Wörtchen, das in mehreren Endpunkten dasselbe erzählen soll, gehört an
eine Stelle: die Kurzform eines Belegs (Abgleich-Rückmeldung), die Detailkarte
(Baum), der Chip-Eintrag im Anhänger-Fenster, das Fach-Ja/Nein für Rasterwerte,
der Anbieter aus dem KI-Raster, die Vermutung zur Einordnung und die volle
Listenzeile. So bleibt die Datenform stabil, wenn dieselbe Info an einer neuen
Stelle gezeigt wird.

Die Helfer greifen nur auf Attribute vorhandener Modelle zu und legen keine
Daten an — sie sind reine Lese-Formatter.
"""
from __future__ import annotations

from .. import ocr
from ..bezeichnung import betrag_aus_namen, datum_aus_namen
from .namen import _art_im_namen

# Status eines Eintrags, dessen Datei beim Abgleich nicht mehr auffindbar war
# (CXXVII). Ein vierter Wert neben "neu" und "zugeordnet" — additiv, das
# Datenmodell bleibt unverändert. Kommt die Datei zurück, fällt er wieder weg.
VERMISST = "vermisst"


def _kurz(d, o) -> dict:
    """Ein Eintrag, so knapp wie die Rückmeldung ihn braucht."""
    return {"id": d.id, "dateiname": d.dateiname, "pfad": d.pfad,
            "objekt": o.slug, "objekt_name": o.name}


def _beleg_karte(d) -> dict:
    """Das Wenige, das die Detailansicht zu einem Beleg braucht."""
    return {"id": d.id, "dateiname": d.dateiname, "pfad": d.pfad, "jahr": d.jahr,
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


def _vorschlag(d) -> dict:
    """Was die Ablage vermutet: Art, Jahr — und wie sicher sie sich ist.

    Die Worterkennung kommt aus `ocr` — dieselbe Liste, die auch den
    abfotografierten Beleg einordnet. Zwei Listen wären zwei Wahrheiten. Beim
    Dateinamen wird sie streng gelesen (`kategorie_aus_dateiname`): ein Name
    ist kurz, ein Zufallstreffer mittelt sich dort nicht weg, und an dieser
    Vermutung hängt die Automatik. Ein Kamerascan heißt „scan.pdf"; dort
    liefert die Texterkennung den Vorschlag schon beim Hochladen mit.

    `sicher` sagt, ob die Vermutung gut genug für eine Ablage ohne Rückfrage
    ist. Alles andere wird angezeigt, aber nicht ausgeführt.
    """
    lesbar = d.dateiname.lower().replace("_", " ").replace("-", " ")
    genannt = _art_im_namen(lesbar)
    erkannt, punkte = ocr.kategorie_aus_dateiname(lesbar)
    kategorie = d.kategorie or genannt or erkannt
    jahr, monat = datum_aus_namen(d.dateiname)
    return {
        "kategorie": kategorie,
        "jahr": d.jahr or jahr,
        # Monat und Betrag stehen oft schon im Namen, den der Nutzer selbst
        # vergeben hat („2025-10-oel-2729,91€.pdf"). Beim Einsortieren sollen
        # sie nicht verlorengehen, nur weil kein Beleg gelesen wurde (CXXIII).
        "monat": monat,
        # CLXXXI: der gespeicherte Betrag hat Vorrang. Der Name bleibt die
        # Anzeige im Ordner, aber er wird bei jeder Korrektur zerlegt und neu
        # gesetzt — als Grundlage einer Kostenposition ist das zu wackelig.
        "betrag": d.betrag if d.betrag is not None
        else betrag_aus_namen(d.dateiname),
        # Worum es geht — feiner als die Art, für den Dateinamen.
        "sache": ocr.sache_aus_dateiname(lesbar),
        "sicher": bool(d.kategorie or genannt
                       or (erkannt and punkte >= ocr.MINDESTPUNKTE)),
    }


def _zeige(d, objekte: dict) -> dict:
    """Die volle Listenzeile eines Belegs, samt Objektbezug und Vermutung."""
    o = objekte.get(d.objekt_id) if d.objekt_id else None
    return {
        "id": d.id, "dateiname": d.dateiname, "pfad": d.pfad,
        "groesse": d.groesse, "status": d.status,
        "kategorie": d.kategorie, "jahr": d.jahr,
        # CLXXI: auf welche Zeile der Abrechnung der Beleg zeigt.
        "kostenart": d.kostenart,
        # CLXXXI/CLXXXIII: der Rechnungsbetrag und die Kostenposition, in die
        # er eingerechnet ist. `position_id` leer heisst: noch nicht übernommen.
        "betrag": d.betrag,
        "position_id": d.position_id,
        # CLXXII: das Rechnungsdatum tagesgenau — daran entscheidet sich, in
        # welchen Abrechnungszeitraum der Beleg fällt.
        "belegdatum": d.belegdatum.isoformat() if d.belegdatum else None,
        "erkannt_am": d.erkannt_am.isoformat() if d.erkannt_am else None,
        # CCLXXIII: die KI-Einordnung — ein bis zwei kurze Sätze zum Beleg.
        # Leer, solange die KI noch nichts geliefert hat; das Frontend zeigt
        # den Bereich dann einfach nicht.
        "ki_einordnung": d.ki_einordnung or "",
        # CCLXXIV: das Raster der KI-Auslese — erkannte Liegenschaft, Einheit
        # und die typspezifischen Felder (Mieter, Jahresbeitrag, Restschuld …).
        # Additiv; das Prüfblatt belegt daraus die Eingaben vor. Leer, solange
        # die KI nichts geliefert hat.
        "ki_immobilie": d.ki_immobilie or "",
        "ki_einheit": d.ki_einheit or "",
        "ki_felder": d.ki_felder or {},
        "zeitraum_id": d.zeitraum_id,
        "objekt": o.slug if o else None,
        "objekt_name": o.name if o else None,
        # Ein Eintrag ohne Datei in der Cloud — nur noch zu entfernen oder
        # neu einzuscannen. Ehrlich anzeigen statt so tun, als läge er dort.
        "abgelegt": d.pfad.startswith("/") and d.status != VERMISST,
        # CXXVII: der Abgleich hat die Datei in der Cloud nicht mehr gefunden.
        # Der Eintrag bleibt stehen — gelöscht wird nichts —, aber er tut nicht
        # so, als läge die Datei noch da.
        "vermisst": d.status == VERMISST,
        # N298 — die Prüfsumme des Inhalts (N290). Ohne sie kann die Oberfläche
        # keine Duplikate gruppieren und nicht zeigen, welche Belege ihr
        # Kennzeichen schon tragen. Leer heisst: der Abgleich hat sie noch
        # nicht nachgetragen (er läuft alle zwei Minuten).
        "sha1": d.sha1 or "",
        "vorschlag": _vorschlag(d),
    }
