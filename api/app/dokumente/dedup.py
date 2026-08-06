"""Reine Rang- und Merge-Regeln für byte-gleiche Duplikate.

Zwei Stellen entscheiden „welche Kopie bleibt": der Scan-Dedup direkt nach dem
Ablegen (`_dedup_rang`, CD) und das Bündeln bestehender Duplikate in einen
Sammelordner (`_duplikat_rang`/`_duplikat_ziel`). Beide Ränge sind reine
Sortierschlüssel über Attribute eines `Dokument` — keine Datenbank, keine
Cloud. Ebenso rein: `_keeper_erbt_luecken` (N54) füllt additiv Lücken des
Keepers aus den weichenden Kopien.

Das eigentliche Feststellen der Byte-Gleichheit (Download + SHA1) und das
Verschieben/Löschen bleiben im Router — dort hängt es eng an Session und
Nextcloud-Client und wird in den Tests darüber (`monkeypatch.setattr(dok,
"verbindung", …)`) gezielt durchgereicht.
"""
from __future__ import annotations

# Sammelordner für gebündelte Duplikate — „<Objektordner>/99_Duplikate".
DUPLIKAT_ORDNER = "99_Duplikate"


def _dedup_rang(d) -> tuple[int, int, int, int]:
    """Keeper-Wahl beim Scan-Dedup — der kleinste Schlüssel bleibt (CD).

    Vorrang: verbucht (`position_id`) vor unverbucht, dann ein Beleg mit Betrag
    vor einem ohne, dann der detailliertere (längere) Name, zuletzt der neuere
    (grössere `id`). Also: verbucht > hat Betrag > detaillierterer Name > neuer."""
    return (0 if d.position_id else 1,
            0 if d.betrag else 1,
            -len(d.dateiname or ""),
            -(d.id or 0))


def _keeper_erbt_luecken(keeper, quellen: list) -> bool:
    """Füllt fehlende Angaben des Keepers additiv aus den weichenden byte-
    gleichen Kopien (N54). Nur Lücken werden gefüllt, nie ein vorhandener Wert
    überschrieben; die Quellen stehen in Vorzugsreihenfolge (der frisch
    abgelegte Beleg zuerst). Gibt zurück, ob sich etwas geändert hat."""
    geaendert = False
    for q in quellen:
        if keeper.zeitraum_id is None and q.zeitraum_id is not None:
            keeper.zeitraum_id = q.zeitraum_id
            geaendert = True
        if not keeper.kostenart and q.kostenart:
            keeper.kostenart = q.kostenart
            geaendert = True
        if keeper.betrag is None and q.betrag is not None:
            keeper.betrag = q.betrag
            geaendert = True
        if not keeper.jahr and q.jahr:
            keeper.jahr = q.jahr
            geaendert = True
        if keeper.belegdatum is None and q.belegdatum is not None:
            keeper.belegdatum = q.belegdatum
            geaendert = True
        if not keeper.kategorie and q.kategorie:
            keeper.kategorie = q.kategorie
            geaendert = True
    return geaendert


def _duplikat_ziel(o) -> str:
    """Der Sammelordner für verschobene Duplikate: „<Objektordner>/99_Duplikate"."""
    return f"{o.nc_ordner.strip('/')}/{DUPLIKAT_ORDNER}"


def _duplikat_rang(d) -> tuple[int, int, int]:
    """Sortierschlüssel für die „behalten"-Wahl — der kleinste bleibt.

    Vorrang: verbucht (`position_id` gesetzt) vor unverbucht, dann ein Beleg mit
    `zeitraum_id` vor einem ohne, zuletzt die kleinste `id`. So bleibt die
    „beste" Kopie am Platz und verschoben werden bevorzugt die nicht verbuchten."""
    return (0 if d.position_id else 1, 0 if d.zeitraum_id else 1, d.id or 0)
