"""Bausteine des Cloud-Abgleichs — was liegt noch da, was ist umgezogen?

Der Scanlauf schaut nach neuen Dateien; der Abgleich schaut in die andere
Richtung: stimmt noch, was die Ablage über die vorhandenen Einträge sagt? Der
Nutzer räumt in der Nextcloud selbst auf — er verschiebt, benennt um und
löscht. Hier wohnen die Bausteine, die daraus einen Schluss ziehen:

* `_baum` liest den Objektordner rein lesend aus und sagt dazu, welche Ordner
  sich WIRKLICH lesen liessen (N248 — ohne das hiesse „nicht in der Liste"
  fälschlich „gelöscht").
* `_wiedergefunden` erkennt eine umgezogene Datei wieder — zuerst an
  Nextclouds Dateinummer und der Prüfsumme (N290), dann an Name und Grösse.
* `_mehrdeutig`/`_nachweislich_geloescht` sind die beiden Bremsen davor:
  aufgeräumt wird nur, was beweisbar weg ist, nie auf Verdacht.
* `_kennzeichen_nachtragen` hält Dateinummer und Prüfsumme am Eintrag fest,
  solange die Datei zweifelsfrei identifiziert ist.
* `_abgleiche_objekt` zieht damit die Einträge EINER Immobilie nach.

Der Lauf über alle Immobilien (`_abgleiche`) bleibt im Router: er besorgt sich
den Nextcloud-Client selbst (`verbindung`) und nimmt neue Dateien über die
Scan-Automatik auf. Alles hier bekommt den Client von aussen gereicht.
"""
from __future__ import annotations

import logging

from sqlmodel import Session

from .. import kidb
from ..models import Dokument, Objekt
from ..nextcloud import NextcloudFehler
from .ablage import _sidecar_mitnehmen
from .darstellung import VERMISST, _kurz
from .grabstein import _grabstein_setzen, _ist_grabstein
from .namen import _einziger, _elternteil, _norm

log = logging.getLogger("immocalc")


# Wie tief unter dem Objektordner gesucht wird. ImmoCalc legt eine Ebene an;
# der Nutzer schachtelt darunter selbst weiter ("60_Nebenkosten/2025/").
ABGLEICH_TIEFE = 4


def _baum(client, wurzel: str,
          tiefe: int = ABGLEICH_TIEFE) -> tuple[dict, set[str]]:
    """Alle Dateien unterhalb eines Ordners, nach Pfad. Rein lesend.

    Gibt zwei Dinge zurück: die gefundenen Dateien **und** die Menge der
    Ordner, die sich wirklich lesen liessen (`gelesen`).

    Ein *Unterordner*, der sich nicht lesen lässt, hält den Abgleich nicht an;
    er wird protokolliert, der Rest wird trotzdem geprüft. Der Objektordner
    selbst dagegen schon: käme dort eine leere Liste zurück, weil die Cloud
    gerade nicht antwortet, gälten mit einem Schlag alle Belege als vermisst.
    Deshalb reicht sein Fehler nach oben durch.

    N248 — genau deshalb ist `gelesen` nötig: „Datei nicht in der Liste" heisst
    nur dann „gelöscht", wenn ihr Ordner auch tatsächlich gelesen wurde. Bei
    einem übersprungenen Unterordner fehlen SEINE Dateien selbstverständlich —
    ohne diese Unterscheidung würden sie beim Aufräumen fälschlich als vom
    Nutzer gelöscht gelten."""
    gefunden: dict = {}
    gelesen: set[str] = set()
    besucht: set[str] = set()
    offen = [(_norm(wurzel), 0)]
    while offen:
        ordner, ebene = offen.pop()
        if ordner in besucht:
            continue
        besucht.add(ordner)
        try:
            eintraege = client.liste(ordner)
        except NextcloudFehler as fehler:
            if ebene == 0:
                raise
            log.warning("Ordner %s nicht lesbar: %s", ordner, fehler)
            continue
        gelesen.add(ordner)
        for e in eintraege:
            if e.ordner:
                if ebene < tiefe:
                    offen.append((_norm(e.pfad), ebene + 1))
            else:
                gefunden[_norm(e.pfad)] = e
    return gefunden, gelesen


def _kennzeichen_nachtragen(d: Dokument, eintrag) -> bool:
    """N290 — Dateinummer und Prüfsumme am Eintrag festhalten. `True`, wenn
    sich etwas geändert hat.

    Streng additiv: ein bereits gesetztes Kennzeichen wird überschrieben, wenn
    die Cloud ein anderes meldet (der Nutzer hat die Datei ersetzt), aber ein
    LEERER Wert aus der Cloud löscht nie einen vorhandenen — nicht jede
    Nextcloud-Installation liefert für jede Datei eine Prüfsumme, und ein
    einzelner Lauf ohne Angabe darf das Kennzeichen nicht wegräumen."""
    geaendert = False
    for feld, wert in (("nc_fileid", getattr(eintrag, "fileid", "")),
                       ("sha1", getattr(eintrag, "sha1", ""))):
        wert = (wert or "").strip()
        if wert and getattr(d, feld, "") != wert:
            setattr(d, feld, wert)
            geaendert = True
    return geaendert


def _umzugsart(alt: str, neu: str) -> str:
    """N290 — „verschoben" oder „umbenannt"? Der Ordner entscheidet.

    Hat sich beides geändert, wiegt der Ordnerwechsel schwerer; der neue Name
    steht ohnehin in derselben Meldung."""
    return "umbenannt" if _elternteil(alt) == _elternteil(neu) else "verschoben"


def _wiedergefunden(d: Dokument, dateien: dict, vergeben: set[str]) -> tuple[str, str]:
    """Wohin die Datei gewandert ist: (Pfad, Art) oder ("", "").

    N290 — zuerst nach Nextclouds Dateinummer, dann nach der Prüfsumme: das
    sind die beiden Kennzeichen, die ein Umbenennen UND Verschieben im
    Explorer zugleich überstehen. Erst danach die alten Wege über Namen und
    Grösse, die je für sich nur EINE der beiden Änderungen verkraften.

    Danach nach dem Namen — verschieben allein ist der häufigere Fall und der
    sicherere Schluss. Zuletzt nach Ordner und Grösse: dieselbe Datei, im
    selben Ordner, nur anders benannt."""
    if _ist_grabstein(d.pfad):
        # N242 — dieser Eintrag hat seinen Namen abgegeben, weil der Nutzer die
        # Datei gelöscht hat. Eine gleichnamige Datei anderswo ist nicht „seine"
        # zurückgekehrte Datei — er bleibt vermisst.
        return "", ""

    # Die Dateinummer ist eindeutig: mehr als ein Treffer kann es nicht geben,
    # und ein Treffer ist ein Beweis, keine Vermutung.
    if d.nc_fileid:
        for pfad, e in dateien.items():
            if e.fileid == d.nc_fileid and pfad not in vergeben:
                return pfad, _umzugsart(d.pfad, pfad)
    # Die Prüfsumme deckt den Fall ab, dass die Datei neu hochgeladen wurde
    # (dann ist die Nummer eine andere). Byte-Gleichheit heisst hier aber nicht
    # zwingend „dieselbe Datei": zwei Kopien desselben Belegs sind ebenfalls
    # byte-gleich. Deshalb nur bei GENAU einem Kandidaten — sonst liesse sich
    # nicht entscheiden, welcher gemeint ist.
    if d.sha1:
        treffer = _einziger([p for p, e in dateien.items()
                             if e.sha1 and e.sha1 == d.sha1 and p not in vergeben])
        if treffer:
            return treffer, _umzugsart(d.pfad, treffer)

    name = d.dateiname.lower()
    gleicher_name = [p for p, e in dateien.items()
                     if e.name.lower() == name and p not in vergeben]
    treffer = _einziger(gleicher_name)
    if treffer:
        return treffer, "verschoben"

    if d.groesse:
        ordner = _elternteil(d.pfad)
        gleiche_datei = [p for p, e in dateien.items()
                         if e.groesse == d.groesse and _elternteil(p) == ordner
                         and p not in vergeben]
        treffer = _einziger(gleiche_datei)
        if treffer:
            return treffer, "umbenannt"
    return "", ""


def _mehrdeutig(d: Dokument, frei: dict, vergeben: set[str]) -> bool:
    """Gibt es mehrere Dateien, die diese hier sein KÖNNTEN?

    `_wiedergefunden` hängt bewusst nicht um, wenn zwei gleich grosse Dateien
    im selben Ordner liegen — es liesse sich nicht entscheiden, welche die
    umbenannte ist. Genau dann ist die Datei aber sehr wahrscheinlich noch da,
    nur anders benannt, und darf nicht als gelöscht aufgeräumt werden."""
    if not d.groesse:
        return False
    ordner = _elternteil(d.pfad)
    passende = [p for p, e in frei.items()
                if e.groesse == d.groesse and _elternteil(p) == ordner
                and p not in vergeben]
    return len(passende) > 1


def _nachweislich_geloescht(d: Dokument, gelesen: set[str], frei: dict,
                            vergeben: set[str]) -> bool:
    """N248 — ist diese Datei BEWEISBAR aus der Cloud verschwunden?

    Der Nutzer war hier ausdrücklich: automatisch aufräumen ja, aber niemals
    auf Verdacht. „Nicht in der Dateiliste" allein genügt deshalb nicht — es
    muss feststehen, dass der Ordner, in dem sie lag, auch WIRKLICH gelesen
    wurde. Genau daran unterscheiden sich die beiden Fälle:

    * Ordner gelesen, Datei nicht darin  -> der Nutzer hat sie gelöscht.
    * Ordner nicht lesbar (Verbindung, Zeitüberschreitung, Rechte)
      -> gar keine Aussage; der Eintrag bleibt unangetastet.

    Ein Objektordner, der sich nicht lesen liess, kommt hier nie an: sein
    Fehler bricht `_baum` ab und `_abgleiche` überspringt die ganze Immobilie.
    Diese Prüfung deckt die Ebene darunter ab — den Unterordner, den `_baum`
    protokolliert und überspringt.

    Dazu die zweite Bremse: liegen mehrere gleich grosse Kandidaten im Ordner,
    wurde die Datei vermutlich nur umbenannt (`_mehrdeutig`). Dann bleibt es
    beim reversiblen `vermisst`."""
    return (_elternteil(d.pfad) in gelesen
            and not _mehrdeutig(d, frei, vergeben))


def _abgleiche_objekt(session: Session, o: Objekt, eigene: list[Dokument],
                      dateien: dict, gelesen: set[str], vergeben: set[str],
                      trocken: bool, client=None) -> dict:
    """Zieht die Einträge einer Immobilie an den Stand der Cloud nach."""
    ergebnis: dict[str, list] = {"verschoben": [], "umbenannt": [],
                                 "vermisst": [], "wiederda": [],
                                 "entfernt": []}
    unveraendert = 0

    # Erst alle, die noch an ihrem Platz liegen — sie belegen ihre Datei,
    # bevor die Suche nach den Umgezogenen beginnt.
    offen: list[Dokument] = []
    nachgetragen = 0
    for d in eigene:
        if _norm(d.pfad) in dateien:
            vergeben.add(_norm(d.pfad))
            unveraendert += 1
            # N290 — solange die Datei noch an ihrem Platz liegt, ist sie
            # zweifelsfrei identifiziert: genau jetzt werden Dateinummer und
            # Prüfsumme nachgetragen. Ohne dieses Nachtragen hülfe die
            # Wiedererkennung nur Dateien, die nach der Umstellung dazukamen —
            # der ganze Bestand bliebe auf Name und Grösse angewiesen.
            if not trocken and _kennzeichen_nachtragen(d, dateien[_norm(d.pfad)]):
                nachgetragen += 1
                session.add(d)
            if d.status == VERMISST:
                # Die Datei ist zurück — der Eintrag darf sie wieder führen.
                ergebnis["wiederda"].append(_kurz(d, o))
                if not trocken:
                    d.status = "zugeordnet" if d.kategorie else "neu"
                    session.add(d)
        else:
            offen.append(d)

    for d in offen:
        ziel, art = _wiedergefunden(d, dateien, vergeben)
        if not ziel:
            eintrag = _kurz(d, o)
            # N248 — steht fest, dass die Datei gelöscht wurde, nimmt der
            # Eintrag seinen Pfad zurück und verschwindet aus der Oberfläche.
            # Steht es NICHT fest (Ordner war nicht lesbar), bleibt es beim
            # blossen Vermerk „vermisst" — reversibel und ohne Datenverlust.
            if _ist_grabstein(d.pfad):
                continue                       # längst freigegeben, nichts zu tun
            if _nachweislich_geloescht(d, gelesen, dateien, vergeben):
                ergebnis["entfernt"].append(eintrag)
                if not trocken:
                    _grabstein_setzen(session, d)
                continue
            ergebnis["vermisst"].append(eintrag)
            if not trocken and d.status != VERMISST:
                d.status = VERMISST
                session.add(d)
            continue
        vergeben.add(ziel)
        eintrag = _kurz(d, o)
        eintrag.update({"von": d.pfad, "nach": ziel,
                        "neuer_name": dateien[ziel].name})
        ergebnis[art].append(eintrag)
        if trocken:
            continue
        # N290 — der Steckbrief zieht mit. Benennt der Nutzer das PDF im
        # Explorer um, bliebe „alt.immocalc" sonst als Waise liegen — und
        # `verwaiste_immocalc_aufraeumen` LÖSCHT Waisen. Die KI-Auslese eines
        # Belegs ginge damit ausgerechnet beim Aufräumen verloren. Best-effort:
        # klappt der Cloud-Zugriff nicht, bleibt die Verknüpfung trotzdem
        # richtig — die Sidecar ist Beiwerk, der Eintrag nicht.
        if client is not None:
            try:
                _sidecar_mitnehmen(client, d.pfad, ziel)
            except Exception as fehler:                   # noqa: BLE001
                log.info("Steckbrief zu %s nicht mitgezogen: %s", d.pfad, fehler)
        d.pfad = ziel
        d.dateiname = dateien[ziel].name
        kidb.pfad_nachziehen(session, d)   # N299
        _kennzeichen_nachtragen(d, dateien[ziel])
        if d.status == VERMISST:
            d.status = "zugeordnet" if d.kategorie else "neu"
        session.add(d)

    ergebnis["unveraendert"] = unveraendert
    ergebnis["kennzeichen_nachgetragen"] = nachgetragen
    return ergebnis
