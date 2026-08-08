"""Byte-gleiche Zweitkopien erkennen, bündeln und auflösen.

Dieselbe Datei kommt im Alltag zwangsläufig mehrfach herein: zweimal
fotografiert, in zwei Objektordnern abgelegt, nach einem Umsortieren erneut
gescannt. Alle Wege, die das behandeln, teilen sich dieselbe Mechanik — und
die steht hier:

* **Beweisen statt vermuten.** Byte-Gleichheit heisst: beide Dateien geladen,
  beide selbst per SHA1 gehasht, Hashes gleich (`_byte_gleiche_geschwister`,
  `_duplikat_gruppen`). Kein Namens- und kein Grössenvergleich entscheidet je
  allein — die Grösse dient nur als billiger Vorfilter.
* **Erst umhängen, dann weichen.** `_duplikat_weg` zieht jeden Verweis auf die
  erhaltene Kopie (N300), bevor irgendetwas verschwindet; wer nicht
  nachweislich byte-gleich ist, weicht gar nicht (`_NichtByteGleich`).
* **Nie die letzte Kopie.** Je Gruppe bleibt genau eine — die beste nach den
  Rangregeln aus `dedup.py`.

Was der Nutzer zur Entscheidung sieht, entsteht ebenfalls hier:
`_verknuepfungen` übersetzt die rohen Verweis-Schlüssel in Klartext
(`_VERWEIS_TITEL`), `_kopie_zeigen` macht daraus die Zeile je Kopie.

Der Nextcloud-Client kommt von aussen; die Endpunkte, die ihn besorgen
(`/duplikat-entfernen`, `/duplikate-buendeln`, `/zusammenfuehren`), bleiben im
Router.
"""
from __future__ import annotations

import logging

from sqlmodel import Session, select

from .. import belegposten, dokumentlinks
from ..bezeichnung import objekt_titel
from ..models import Dokument, Objekt
from ..nextcloud import NextcloudFehler
from .dedup import (_dedup_rang, _duplikat_rang, _duplikat_ziel,
                    _keeper_erbt_luecken)
from .namen import LAGEPLAN, _elternordner, _ist_sidecar, _sidecar_pfad

log = logging.getLogger("immocalc")


class _NichtByteGleich(Exception):
    """Die beiden Belege sind NICHT byte-identisch — es darf nichts weichen."""


def _duplikat_weg(session: Session, client, weg: Dokument,
                  behalten: Dokument) -> list[str]:
    """N16b — entfernt `weg` NUR, wenn er byte-gleich zu `behalten` ist.

    Die Byte-Gleichheit wird durch Herunterladen und SHA1-Vergleich beider
    Dateien bewiesen — nie wird eine einzigartige Datei gelöscht (der Grundsatz
    „nie Daten verlieren" bleibt gewahrt, es geht nur eine nachweislich
    identische Zweitkopie, während `behalten` erhalten bleibt). Löst eine
    Verbuchung (die erhaltene Kopie trägt die Kosten weiter), entfernt Datei,
    `.immocalc`-Sidecar und den DB-Eintrag. Committet NICHT — das überlässt der
    Helfer dem Aufrufer, damit er es in seine eigene Transaktion einbetten kann.

    Wirft `NextcloudFehler`, wenn eine Datei nicht ladbar ist, und
    `_NichtByteGleich`, wenn die Inhalte sich unterscheiden — in beiden Fällen
    ist noch nichts geändert (nichts gelöscht). Gibt die entfernten Cloud-Pfade
    zurück."""
    import hashlib
    b_weg, _ = client.hole(weg.pfad)
    b_behalten, _ = client.hole(behalten.pfad)
    if hashlib.sha1(b_weg).hexdigest() != hashlib.sha1(b_behalten).hexdigest():
        raise _NichtByteGleich(weg.pfad)
    # N300 — ZUERST jeden Verweis auf die erhaltene Kopie ziehen. Vorher fiel
    # der Eintrag ersatzlos, und alles, was an ihm hing (Renovierungsrechnung,
    # Versicherung, Kredit, Notarvertrag, Belegdaten …) zeigte danach auf eine
    # tote Nummer. Das ist derselbe Weg wie in `/zusammenfuehren`.
    dokumentlinks.haenge_um(session, weg.id, behalten.id)
    # Verbuchung lösen (die erhaltene Kopie trägt die Kosten weiter), dann Datei
    # und Sidecar entfernen — nur unterhalb des Home-Ordners (loesche-Riegel).
    belegposten.loese(session, weg)
    geloescht: list[str] = []
    for pfad in (weg.pfad, _sidecar_pfad(weg.pfad)):
        try:
            client.loesche(pfad)
            geloescht.append(pfad)
        except NextcloudFehler as fehler:
            log.info("Duplikat-Datei nicht löschbar (%s): %s", pfad, fehler)
    session.delete(weg)
    return geloescht


def _byte_gleiche_geschwister(session: Session, client, d: Dokument,
                              inhalt: bytes) -> list[Dokument]:
    """Andere Belege desselben Objekts, die byte-gleich zu `d` sind (CD).

    Rein über den Inhalt, kein Namensvergleich: der SHA1 des frisch abgelegten
    Inhalts wird gegen den jeder anderen Datei gehalten. Nach Grösse vorgefiltert
    — was anders gross ist, kann nie byte-gleich sein und wird gar nicht erst
    geladen. Sidecars und Belege ohne abgelegte Datei bleiben aussen vor. Ein
    nicht ladbarer Beleg wird übersprungen, nie als gleich behandelt."""
    import hashlib
    ziel_sha1 = hashlib.sha1(inhalt).hexdigest()
    gleiche: list[Dokument] = []
    andere = session.exec(select(Dokument).where(
        Dokument.objekt_id == d.objekt_id, Dokument.id != d.id)).all()
    for k in andere:
        if _ist_sidecar(k.dateiname) or not (k.pfad or "").startswith("/"):
            continue
        if k.groesse and d.groesse and k.groesse != d.groesse:
            continue
        try:
            roh, _ = client.hole(k.pfad)
        except NextcloudFehler as fehler:
            log.info("Dedup: %s nicht ladbar (%s)", k.pfad, fehler)
            continue
        if hashlib.sha1(roh).hexdigest() == ziel_sha1:
            gleiche.append(k)
    return gleiche


def _dedup_nach_scan(session: Session, client, d: Dokument,
                     inhalt: bytes) -> tuple[Dokument, int]:
    """Best-effort: entfernt byte-gleiche Zweitkopien des frisch abgelegten
    Belegs `d` im selben Objekt (CD). Gibt `(keeper, anzahl_entfernt)` zurück.

    Von allen byte-gleichen Belegen (der neue `d` und seine Geschwister) bleibt
    der beste stehen (`_dedup_rang`), die übrigen weichen über `_duplikat_weg`
    (Byte-Gleichheit erneut bewiesen, Sidecar + DB-Eintrag + Verbuchung sauber
    behandelt). Ist die ALTE Kopie besser, weicht der gerade angelegte `d`, und
    zurück kommt der erhaltene Beleg. Gelöscht wird nur, solange der Keeper
    bleibt — nie die einzige/letzte Kopie."""
    gleiche = _byte_gleiche_geschwister(session, client, d, inhalt)
    if not gleiche:
        return d, 0
    kandidaten = sorted([d, *gleiche], key=_dedup_rang)
    keeper = kandidaten[0]
    # N54 — der Keeper erbt fehlende Angaben von den weichenden Kopien, den
    # frischen `d` zuerst. Ohne das ging die gerade bewusst gesetzte Zuordnung
    # verloren, wenn die ältere byte-gleiche Kopie als Keeper bestehen blieb:
    # der Nutzer zog den Beleg in einen Zeitraum, der Keeper hatte aber keinen —
    # und das Verbuchen scheiterte an „fehlt der Abrechnungszeitraum". Additiv:
    # nur Lücken werden gefüllt, nie ein vorhandener Wert überschrieben. Vor dem
    # Entfernen, solange die Verlierer-Objekte noch gültig sind.
    geerbt = _keeper_erbt_luecken(
        keeper, [k for k in ([d, *kandidaten[1:]]) if k is not keeper])
    entfernt = 0
    for verlierer in kandidaten[1:]:
        try:
            _duplikat_weg(session, client, verlierer, keeper)
            entfernt += 1
        except (NextcloudFehler, _NichtByteGleich) as fehler:
            # Nicht (mehr) byte-gleich oder nicht ladbar: nichts entfernen.
            log.warning("Dedup: %s nicht entfernt (%s)", verlierer.pfad, fehler)
    if entfernt or geerbt:
        session.add(keeper)
        session.commit()
        session.refresh(keeper)
    return keeper, entfernt


def _duplikat_gruppen(session: Session, client, o: Objekt
                      ) -> tuple[list[tuple[str, Dokument, list[Dokument]]],
                                 list[dict]]:
    """Bildet die Duplikatgruppen einer Immobilie über einen SHA1 des Inhalts.

    Gibt `(gruppen, fehler)` zurück. `gruppen`: je echtem Duplikat ein Tupel
    `(sha1, behalten, [verschieben…])`, wobei `verschieben` nie leer und
    `behalten` die beste Kopie ist. `fehler`: nicht ladbare Belege, die
    übersprungen (nicht abgebrochen) wurden.

    Ausgenommen sind Sidecars, Lagepläne (mehrere Fotos desselben Plans sind
    gewollt) und Belege, die bereits im Sammelordner liegen (Idempotenz)."""
    import hashlib
    ziel = _duplikat_ziel(o).strip("/")
    kandidaten = [
        d for d in session.exec(
            select(Dokument).where(Dokument.objekt_id == o.id)).all()
        if (d.pfad or "").startswith("/")
        and not _ist_sidecar(d.dateiname)
        and d.kategorie != LAGEPLAN
        and _elternordner(d.pfad) != ziel]

    nach_sha1: dict[str, list[Dokument]] = {}
    fehler: list[dict] = []
    for d in kandidaten:
        try:
            rohdaten, _typ = client.hole(d.pfad)
        except NextcloudFehler as f:
            # Ein nicht ladbarer Beleg hält den Lauf nicht an — er wird
            # übersprungen, nie als Duplikat behandelt (byte-genau geht nicht).
            log.info("Duplikat-Prüfung übersprungen (%s): %s", d.pfad, f)
            fehler.append({"id": d.id, "name": d.dateiname, "grund": str(f)})
            continue
        sha1 = hashlib.sha1(rohdaten).hexdigest()
        nach_sha1.setdefault(sha1, []).append(d)

    gruppen: list[tuple[str, Dokument, list[Dokument]]] = []
    for sha1, docs in nach_sha1.items():
        if len(docs) < 2:
            continue                                   # keine Kopie = kein Duplikat
        docs.sort(key=_duplikat_rang)
        gruppen.append((sha1, docs[0], docs[1:]))
    return gruppen, fehler


_VERWEIS_TITEL = {
    "kostenposition.quelle_dokument_id": "Kostenposition",
    "miete.quelle_dokument_id": "Mietverhältnis",
    "versicherung.quelle_dokument_id": "Versicherung",
    "kredit.quelle_dokument_id": "Kredit",
    "notarvertrag.quelle_dokument_id": "Notarvertrag",
    "bewohner.quelle_dokument_id": "Bewohner",
    "zahlung.quelle_dokument_id": "Zahlung",
    "renovierungsposten.quelle_dokument_id": "Renovierungsrechnung",
    "stromjahr.screenshot_dokument_id": "Stromjahr (Screenshot)",
    "belegdaten.dokument_id": "Belegdaten",
    # N313 — kam mit dem Kontaktbuch dazu und fehlte hier; im Duplikat-
    # Assistenten stand dem Nutzer sonst der rohe Tabellenname.
    "kundennummer.quelle_dokument_id": "Kundennummer",
}


def _verknuepfungen(session: Session, dokument_id: int) -> list[dict]:
    """Woran dieser Beleg hängt — in Klartext für die Oberfläche.

    Der Nutzer entscheidet anhand dieser Liste, welche Kopie bleibt: eine ohne
    jeden Verweis ist der unverfänglichste Kandidat zum Wegwerfen."""
    return [{"typ": schluessel,
             "titel": _VERWEIS_TITEL.get(schluessel, schluessel),
             "anzahl": anzahl}
            for schluessel, anzahl in
            sorted(dokumentlinks.zaehle(session, dokument_id).items())]


def _kopie_zeigen(session: Session, d: Dokument, objekte: dict) -> dict:
    o = objekte.get(d.objekt_id)
    return {
        "id": d.id, "dateiname": d.dateiname, "pfad": d.pfad,
        "objekt": o.slug if o else "", "objekt_name": objekt_titel(o) if o else "",
        "kategorie": d.kategorie, "kostenart": d.kostenart,
        "betrag": d.betrag, "jahr": d.jahr, "status": d.status,
        "belegdatum": d.belegdatum.isoformat() if d.belegdatum else None,
        "verknuepfungen": _verknuepfungen(session, d.id),
    }
