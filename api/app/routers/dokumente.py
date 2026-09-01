"""Dokumentenablage: aufnehmen, zuordnen, korrigieren, wiederfinden.

Ein Dokument nimmt genau einen Weg: es kommt herein — abfotografiert oder als
Datei im Hauptordner der Immobilie —, bekommt Immobilie, Art und Jahr und liegt
danach am richtigen Platz. Wo die Zuordnung sicher ist (nur eine Immobilie oder
der Beleg lag schon in ihrem Ordner, und die Art ist erkannt), geschieht sie
ohne Rückfrage.

Alles Weitere ist Korrektur und läuft über einen einzigen Endpunkt: `PATCH`
ändert Immobilie, Art, Jahr und Namen — und verschiebt die Datei in der Cloud
mit. `DELETE` entfernt nur den Eintrag; die Datei in der Nextcloud bleibt
liegen, gelöscht wird dort grundsätzlich nichts.
"""
import hashlib
import json
import logging
from datetime import date
from typing import Optional

from fastapi import (APIRouter, Depends, File, Form, HTTPException, Query,
                     Response, UploadFile)
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from .. import (belegposten, dokumentlinks, familienraum, feldzuordnung,
                kiauslese, kicache, kidb, ocr, pdftext, upload)
from ..belegposten import BelegFehler
from ..bezeichnung import betrag_aus_namen, datum_aus_namen, objekt_titel
from ..cloudkern import (ZIELORDNER, _lies, hauptordner_lesbar, struktur_fuer,
                        verbindung)
from ..deps import (aktuelle_familie, dokument_holen, objekt_holen,
                    pruefe_familienbesitz, zeitraum_holen)
from ..kostenarten import _fold as _fold_kostenart
from ..kostenarten import normalisieren as kostenart_normalisieren
from .ki import S_KI_KEY, S_KI_MODELL
from ..db import get_session
from ..migrate import eindeutigkeit_sichern
from ..models import (Bewohner, Dokument, Einheit, Erkennungsregel, Familie,
                      Grundschuld, Kostenart, Kostenposition, Kredit, Miete,
                      Notarvertrag, Objekt, Renovierung, Renovierungsposten,
                      Versicherung, Zahlung, Zeitraum)
from ..renovierung import projektordner
from ..verteilung import UnbekannterSchluessel
from ..nextcloud import NextcloudFehler
from ..wachdienst import sperre
from ..wachdienst import zustand as wachdienst_zustand

# --------------------------------------------------------------------------
# Re-Exports aus dem `app.dokumente`-Paket (N216/N288)
#
# Die Bausteine wohnen in eigenen Modulen — Namensbildung, KI-Wertparser,
# Datumsrechnung, Strom-Auslese-Formatter, Anzeigehelfer (N216), dazu die
# Ablage, der Cloud-Abgleich, die Grabsteine, die Entwurfs-Baupläne, die
# Duplikat-Mechanik und das Pfad-Heilen (N288). Sie werden hier gezogen und am
# Router-Namensraum bereitgestellt — so bleibt jeder bestehende
# `from app.routers.dokumente import …`-Zugriff (aus anderen Routern und
# Tests) unverändert lesbar. Zirkelfrei: die Bausteine kennen den Router nicht.
#
# Ein Name, der hier steht, aber im Router selbst nicht mehr vorkommt, ist
# deshalb kein toter Import, sondern genau dieser Zweck: der Namensraum bleibt
# vollständig, damit ein Umzug niemandes Aufruf bricht.
#
# Was hier NICHT hinwandert: alles, was sich den Nextcloud-Client selbst holt
# (`verbindung`). Die Tests reichen ihn über
# `monkeypatch.setattr(dok, "verbindung", …)` am Router-Modul durch — eine
# Funktion in einem Nebenmodul schlüge diesen Namen dort nicht mehr nach.
# --------------------------------------------------------------------------
from ..dokumente.abgleich import (ABGLEICH_TIEFE, _abgleiche_objekt, _baum,
                                  _kennzeichen_nachtragen, _mehrdeutig,
                                  _nachweislich_geloescht, _umzugsart,
                                  _wiedergefunden)
from ..dokumente.ablage import (_ablageordner, _beleg_umziehen, _freier_name,
                                _ordner_sichern, _projektordner,
                                _sidecar_mitnehmen, _ziel_im_objekt,
                                _zielordner)
from ..dokumente.darstellung import (VERMISST, _anh_zeige, _beleg_anbieter,
                                     _beleg_karte, _feld_wert,
                                     _ist_kostenfrei, _kurz, _vorschlag, _zeige)
from ..dokumente.datum import _aus_datum, _jahr_mit_fallback, _zum_datum
from ..dokumente.dedup import (DUPLIKAT_ORDNER, _dedup_rang, _duplikat_rang,
                               _duplikat_ziel, _keeper_erbt_luecken)
from ..dokumente.duplikate import (_NichtByteGleich, _VERWEIS_TITEL,
                                   _byte_gleiche_geschwister, _dedup_nach_scan,
                                   _duplikat_gruppen, _duplikat_weg,
                                   _kopie_zeigen, _verknuepfungen)
from ..dokumente.eintraege import (_UMKLASS_ZIEL, _bewahrt, _eintrag_kern,
                                   _eintrag_wo)
from ..dokumente.entwuerfe import (_ENTWURF_BAUER, _ZIEL_BAUER,
                                   _entwurf_erwerb, _entwurf_kredit,
                                   _entwurf_miete, _entwurf_nebenkosten,
                                   _entwurf_notarvertrag, _entwurf_steuer,
                                   _entwurf_versicherung, _schon_vorlaeufig,
                                   _zeitraum_fuer_beleg)
from ..dokumente.grabstein import (GRABSTEIN, _eintraege_auf,
                                   _grabstein_setzen, _ist_grabstein,
                                   _ohne_grabsteine,
                                   _verwaisten_eintrag_freigeben)
from ..dokumente.ki_beleg import (_ki_am_beleg_festhalten, _ki_aus_db,
                                  _pruefsumme_nachtragen, _rechnungssumme)
from ..dokumente.ki_werte import _ki_datum, _ki_text, _ki_zahl
from ..dokumente.namen import (DOKUMENTARTEN, LAGEPLAN, _NICHTSSAGEND, _adr_norm,
                               _art_im_namen, _bezeichnung, _dateiname_kopfzeile,
                               _dateistamm, _einziger, _elternordner, _elternteil,
                               _endung, _ist_sidecar, _kern, _norm, _ohne_dopplung,
                               _ordner_aus_pfad, _ordner_titel, _sagt_nichts,
                               _saubere_datei, _sidecar_pfad, dateiname)
from ..dokumente.pfade import (_datei_holen, _dateien_im_objekt,
                               _pfad_belegt_von, _pfad_heilen)
from ..dokumente.strom_hilfen import (_strom_hinweis, _strom_in_felder,
                                      _zeitraum_text)
from ..dokumente.warten import (_entwuerfe_des_belegs,
                                _leere_zeitraeume_raeumen, _zurueck_ins_warten)
from ..dokumente.zuordnung import (_AN_TYP_MODELLE, _INFO_RUBRIK,
                                   _ZUORDNUNG_MODELLE, _eintrag_holen,
                                   _gehoert_zum_objekt)
# N297 — `dokumente/immocalc_steckbrief.py` ist entfallen: der `.immocalc`-
# Steckbrief wird nicht mehr geschrieben, damit blieb das Modul ohne Aufrufer.
from ..dokumente.filter import _dokument_passt

log = logging.getLogger("immocalc")
router = APIRouter(prefix="/api/dokumente", tags=["dokumente"])


def _ki_key(session: Session) -> str:
    """Der in den Einstellungen hinterlegte Anthropic-Schlüssel (CCLXXI) —
    leer, wenn keiner gespeichert ist. Dann greift der env-Fallback in
    `kiauslese`."""
    return _lies(session, S_KI_KEY)


def _ki_modell(session: Session) -> str:
    """Das hinterlegte KI-Modell — leer heißt: Vorgabe aus `kiauslese`."""
    return _lies(session, S_KI_MODELL)


# --------------------------------------------------------------------------
# Ablegen in der Cloud — eine Stelle für Zuordnen, Korrigieren und Automatik
# --------------------------------------------------------------------------

def _einsortieren(session: Session, d: Dokument, o: Objekt, kategorie: str,
                  name: str, client=None, jahr: int | None = None) -> tuple[str, str]:
    """Verschiebt die Datei an ihren Platz. Gibt (Pfad, Dateiname) zurück.

    Liegt sie schon dort, passiert nichts — MOVE auf sich selbst wäre ein
    Fehler, und ein zweiter Name („…-2") wäre eine Lüge."""
    client = client or verbindung(session)
    sach, ordner = _ablageordner(session, o, kategorie, jahr, client)
    if d.pfad.strip("/") == f"{ordner}/{name}":
        return d.pfad, name
    _ordner_sichern(client, sach, ordner)
    frei = _freier_name(session, client, ordner, name)
    client.verschiebe(d.pfad, f"{ordner}/{frei}")
    return f"/{ordner}/{frei}", frei


# --------------------------------------------------------------------------
# Eingang einlesen
# --------------------------------------------------------------------------

_index_geprueft = False


def _eindeutigkeit_sichern(session: Session) -> None:
    """Ein Pfad, ein Eintrag — durchgesetzt von der Datenbank.

    Gesetzt wird der Index beim Start (`migrate.migriere`); hier steht nur das
    Netz darunter, falls er dort nicht durchkam. Der Merker fällt erst nach
    dem Erfolg — ein misslungener Versuch soll wiederholt werden, sonst liefe
    die Datenbank bis zum nächsten Neustart ohne Eindeutigkeit.
    """
    global _index_geprueft
    if _index_geprueft:
        return
    try:
        gesetzt = eindeutigkeit_sichern(session.connection())
        session.commit()
        # Doppel in der Ablage? Dann steht der Index noch aus — beim nächsten
        # Lauf erneut versuchen, der Nutzer räumt die Doppel ja auf.
        _index_geprueft = bool(gesetzt)
    except Exception as fehler:                       # noqa: BLE001
        session.rollback()
        log.warning("Eindeutigkeit der Ablage nicht gesetzt: %s", fehler)


def _aufnehmen(session: Session, o: Objekt, eintrag) -> Dokument | None:
    """Legt einen Eingangseintrag an. `None`, wenn es ihn schon gibt oder wenn
    es ein `.immocalc`-Steckbrief ist (der gehört zum Beleg, nicht daneben)."""
    if _ist_sidecar(eintrag.name):
        return None
    if session.exec(select(Dokument)
                    .where(Dokument.pfad == eintrag.pfad)).first():
        return None
    d = Dokument(pfad=eintrag.pfad, dateiname=eintrag.name,
                 groesse=eintrag.groesse, objekt_id=o.id, status="neu",
                 nc_fileid=getattr(eintrag, "fileid", "") or "",
                 sha1=getattr(eintrag, "sha1", "") or "",
                 erkannt_am=date.today())
    session.add(d)
    try:
        session.commit()
    except IntegrityError:
        # Der andere Rufer war schneller — genau dafür ist der Index da.
        session.rollback()
        return None
    session.refresh(d)
    return d


def _automatisch(session: Session, d: Dokument, o: Objekt, client) -> bool:
    """Ordnet zu, wo nichts zu raten bleibt: die Immobilie steht durch den
    Ordner fest, die Art steht erkennbar im Namen. Alles andere wartet auf
    eine Entscheidung — eine unsichere Vermutung wird angezeigt, nicht
    ausgeführt."""
    vorschlag = _vorschlag(d)
    if not vorschlag["kategorie"] or not vorschlag["sicher"] or not o.nc_ordner:
        return False
    # Die eigene Benennung des Nutzers hat Vorrang; der erkannte Sachbegriff
    # springt nur ein, wo der Name nichts hergibt („scan.pdf", „IMG_4711.pdf").
    sache = _bezeichnung(d.dateiname) or vorschlag["sache"]
    name = dateiname(vorschlag["jahr"], vorschlag["kategorie"], sache,
                     _endung(d.dateiname), vorschlag["monat"],
                     vorschlag["betrag"], d.kostenart)
    alt = d.pfad
    try:
        d.pfad, d.dateiname = _einsortieren(session, d, o,
                                            vorschlag["kategorie"], name, client,
                                            vorschlag["jahr"])
    except NextcloudFehler as fehler:
        log.warning("Automatik übersprungen für %s: %s", alt, fehler)
        return False
    d.kategorie = vorschlag["kategorie"]
    d.jahr = vorschlag["jahr"]
    d.status = "zugeordnet"
    session.add(d)
    try:
        session.commit()
    except IntegrityError:
        # Der Zielpfad ist inzwischen vergeben. Die Datei liegt jetzt zwar am
        # neuen Platz, der Eintrag bleibt aber offen — der Nutzer sieht sie im
        # Eingang und entscheidet. Der Scanlauf geht weiter.
        session.rollback()
        log.warning("Automatik nicht gespeichert (Pfad doppelt): %s", alt)
        return False
    return True


@router.post("/scan")
def scan(session: Session = Depends(get_session),
         familie: Familie | None = Depends(aktuelle_familie)) -> dict:
    """Liest die Objektordner in der Nextcloud und nimmt neue Dateien auf.

    Läuft nie zweimal gleichzeitig: der Wachdienst und dieser Handlauf teilen
    sich eine Sperre. Wer zu spät kommt, wartet nicht — er bekommt Bescheid,
    denn der andere Lauf liest ohnehin gerade dieselben Ordner.

    N436 — nur die Objektordner der angemeldeten Familie. `familie=None`
    ist dem internen Wachdienst-Aufruf vorbehalten (`wachdienst.
    einmal_scannen`, ohne Sitzung): er läuft absichtlich über ALLE Familien —
    über HTTP liefert `aktuelle_familie` immer eine echte Familie oder einen
    401, `None` ist von aussen nie erreichbar."""
    if not sperre.acquire(blocking=False):
        raise HTTPException(409, "Der Eingang wird gerade geprüft — "
                                 "einen Moment, dann noch einmal versuchen.")
    try:
        return _scanne(session, familie.id if familie else None)
    finally:
        sperre.release()


def _je_familie(session: Session, lauf) -> list[dict]:
    """N436 (Häppchen 8) — ruft `lauf(familie_id)` für jede Familie einzeln
    auf, mit passend gesetztem `familienraum`-Kontext.

    Die Cloud-Hintergrundläufe (`_scanne`, `_abgleiche`, `nachtraeglich_ocren`,
    `verwaiste_immocalc_aufraeumen`, `pruefsummen_nachtragen`) lösten ihren
    Nextcloud-Client bisher EINMAL für den ganzen Lauf auf — richtig, solange
    alle Familien dieselbe Verbindung teilten. Seit N436 (Häppchen 7) hat
    jede Familie ihre eigene, und `verbindung()` liest sie über den aktuellen
    `familienraum`-Kontext; ohne ihn griff der Wachdienst auf den „kein
    Kontext"-Namensraum zu und fand für KEINE Familie mehr eine Verbindung.

    Eine Familie ohne eingerichtete Nextcloud (`HTTPException(400)` aus
    `verbindung()`) wird übersprungen statt den ganzen Lauf abzubrechen —
    dasselbe Prinzip, das `wachdienst.takt()` schon zwischen den Schritten
    anwendet, hier je Familie innerhalb eines Schritts. Das Zusammenführen
    der Teilergebnisse bleibt beim Aufrufer, weil die Form von Lauf zu Lauf
    unterschiedlich ist (mal Zahlen zum Summieren, mal Listen zum Verketten)."""
    ergebnisse = []
    for f in session.exec(select(Familie)).all():
        familienraum.setzen(f.id)
        try:
            ergebnisse.append(lauf(f.id))
        except HTTPException as fehler:
            if fehler.status_code != 400:
                raise
    return ergebnisse


def _scanne(session: Session, familie_id: int | None = None) -> dict:
    if familie_id is None:
        teile = _je_familie(session, lambda fid: _scanne(session, fid))
        return {"neu": sum(t["neu"] for t in teile),
                "automatisch": sum(t["automatisch"] for t in teile),
                "offen": sum(t["offen"] for t in teile)}
    _eindeutigkeit_sichern(session)
    client = verbindung(session)
    neu = automatisch = 0
    frage = select(Objekt)
    if familie_id is not None:
        frage = frage.where(Objekt.familie_id == familie_id)
    for o in session.exec(frage).all():
        if not o.nc_ordner:
            continue
        try:
            eintraege = client.liste(o.nc_ordner)
        except NextcloudFehler as e:
            log.warning("Ordner %s nicht lesbar: %s", o.nc_ordner, e)
            continue
        for e in eintraege:
            if e.ordner:
                continue      # nur lose Dateien im Hauptordner sind Eingang
            d = _aufnehmen(session, o, e)
            if not d:
                continue
            neu += 1
            try:
                if _automatisch(session, d, o, client):
                    automatisch += 1
            except Exception as fehler:               # noqa: BLE001
                # Eine Datei darf den ganzen Lauf nicht anhalten — der Rest des
                # Eingangs soll trotzdem hereinkommen.
                session.rollback()
                log.warning("Automatik gescheitert für %s: %s", e.pfad, fehler)
    return {"neu": neu, "automatisch": automatisch,
            "offen": neu - automatisch}


# --------------------------------------------------------------------------
# CXXVII: den Ordner vollständig neu einlesen
#
# Der Scanlauf findet neue Dateien. Der Abgleich schaut in die andere
# Richtung: stimmt noch, was die Ablage über die vorhandenen Einträge sagt?
# Der Nutzer räumt in der Nextcloud selbst auf — er verschiebt, benennt um und
# löscht. Ein Eintrag, dessen Datei weg ist, darf nicht so tun, als läge sie
# noch da.
#
# Was der Abgleich tut:
#   * Datei am selben Platz            -> nichts
#   * Datei woanders, gleicher Name    -> der Eintrag zieht mit (nur Datenbank)
#   * Datei umbenannt, gleiche Grösse  -> der Eintrag zieht mit (nur Datenbank)
#   * Datei nirgends mehr, Ordner gelesen   -> aus der Ablage genommen (N248)
#   * Datei nirgends mehr, Ordner unlesbar  -> nur Status `vermisst`
#
# N248 — der Nutzer löscht Fehlscans direkt in der Nextcloud und will sie
# danach auch in ImmoCalc nicht mehr sehen. Das geschieht jetzt von selbst,
# ohne Rückfrage. Die Bedingung dafür ist streng: es muss FESTSTEHEN, dass die
# Datei weg ist — also der Ordner, in dem sie lag, tatsächlich gelesen worden
# sein. Antwortet die Cloud nicht, bleibt jeder Eintrag unangetastet; lieber
# eine Runde später aufräumen als auf Verdacht.
#
# Aus der Datenbank gelöscht wird auch dann nichts: der Eintrag behält
# Zeitraum, Zuordnung, Betrag und KI-Auslese und legt nur seinen Pfad als
# Grabstein beiseite (`_grabstein_setzen`). Der Wachdienst stösst den Abgleich
# im 15-Minuten-Takt selbst an.
# --------------------------------------------------------------------------

def _abgleiche(session: Session, trocken: bool,
              familie_id: int | None = None) -> dict:
    """Ein vollständiger Durchgang über alle verknüpften Objektordner.

    N436 — `familie_id` grenzt auf die Objekte einer Familie ein. `None`
    (Vorgabe) läuft über ALLE Familien und bleibt dem internen Wachdienst-
    Takt vorbehalten (`wachdienst._abgleich_lauf`, ohne Sitzung); die
    HTTP-Endpunkte `abgleich`/`abgleich_plan` geben immer die angemeldete
    Familie mit."""
    if familie_id is None:
        teile = _je_familie(session, lambda fid: _abgleiche(session, trocken, fid))
        return {
            "trockenlauf": trocken,
            "geprueft": sum(t["geprueft"] for t in teile),
            "unveraendert": sum(t["unveraendert"] for t in teile),
            "verschoben": [x for t in teile for x in t["verschoben"]],
            "umbenannt": [x for t in teile for x in t["umbenannt"]],
            "vermisst": [x for t in teile for x in t["vermisst"]],
            "wiederda": [x for t in teile for x in t["wiederda"]],
            "entfernt": [x for t in teile for x in t["entfernt"]],
            "neu": sum(t["neu"] for t in teile),
            "automatisch": sum(t["automatisch"] for t in teile),
            "offen": sum(t["offen"] for t in teile),
            "ohne_eintrag": sum(t["ohne_eintrag"] for t in teile),
            "kennzeichen_nachgetragen": sum(t["kennzeichen_nachgetragen"] for t in teile),
            "hinweise": [x for t in teile for x in t["hinweise"]],
        }
    _eindeutigkeit_sichern(session)
    client = verbindung(session)
    zusammen: dict[str, list] = {"verschoben": [], "umbenannt": [],
                                 "vermisst": [], "wiederda": [], "entfernt": []}
    unveraendert = geprueft = ohne_eintrag = neu = automatisch = 0
    nachgetragen = 0                    # N290 — Kennzeichen frisch festgehalten
    hinweise: list[str] = []
    # Über alle Immobilien hinweg: eine Datei gehört immer nur einem Eintrag.
    vergeben = {_norm(d.pfad) for d in session.exec(select(Dokument)).all()}

    frage = select(Objekt)
    if familie_id is not None:
        frage = frage.where(Objekt.familie_id == familie_id)
    for o in session.exec(frage).all():
        if not o.nc_ordner:
            continue
        try:
            dateien, gelesen = _baum(client, o.nc_ordner)
        except NextcloudFehler as fehler:
            # Nicht lesbar heisst nicht verschwunden. Lieber diese Immobilie
            # überspringen, als ihren ganzen Bestand als vermisst zu melden.
            hinweise.append(f"{o.name}: Ordner nicht lesbar — übersprungen "
                            f"({fehler})")
            log.warning("Abgleich übersprungen für %s: %s", o.nc_ordner, fehler)
            continue

        # Vergeben sind zunächst nur die Pfade fremder Einträge; die eigenen
        # gibt `_abgleiche_objekt` frei zum Wiederfinden.
        eigene = list(session.exec(select(Dokument)
                                   .where(Dokument.objekt_id == o.id)).all())
        geprueft += len(eigene)
        vergeben -= {_norm(d.pfad) for d in eigene}

        teil = _abgleiche_objekt(session, o, eigene, dateien, gelesen,
                                 vergeben, trocken, client)
        for schluessel in zusammen:
            zusammen[schluessel] += teil[schluessel]
        unveraendert += teil["unveraendert"]
        nachgetragen += teil["kennzeichen_nachgetragen"]

        if not trocken:
            try:
                session.commit()
            except IntegrityError as fehler:
                # Ein Zielpfad war doch belegt. Nichts geht verloren: die
                # Einträge bleiben, wie sie waren, und der Nutzer erfährt es.
                session.rollback()
                hinweise.append(f"{o.name}: Änderungen nicht gespeichert "
                                f"({fehler.orig})")
                log.warning("Abgleich nicht gespeichert für %s: %s",
                            o.slug, fehler)
                continue
            teil_neu, teil_auto = _neue_aufnehmen(session, o, dateien, client,
                                                  vergeben)
            neu += teil_neu
            automatisch += teil_auto
        ohne_eintrag += sum(1 for p in dateien if p not in vergeben)

    return {
        "trockenlauf": trocken,
        "geprueft": geprueft,
        "unveraendert": unveraendert,
        "verschoben": zusammen["verschoben"],
        "umbenannt": zusammen["umbenannt"],
        "vermisst": zusammen["vermisst"],
        "wiederda": zusammen["wiederda"],
        # N248 — vom Nutzer in der Cloud gelöscht und deshalb automatisch aus
        # der Ablage genommen. Der Datensatz bleibt (Betrag, KI-Auslese,
        # Verweise), nur sein Pfad ist ein Grabstein.
        "entfernt": zusammen["entfernt"],
        "neu": neu,
        "automatisch": automatisch,
        "offen": neu - automatisch,
        # Dateien in der Cloud, zu denen es keinen Eintrag gibt. Nur eine
        # Zahl: aufgenommen wird weiterhin nur, was lose im Hauptordner
        # liegt — der gewachsene Bestand in den Unterordnern gehört dem
        # Nutzer und wird nicht ungefragt in die Ablage gezogen.
        "ohne_eintrag": ohne_eintrag,
        # N290 — wie viele Einträge in diesem Lauf ihre Dateinummer/Prüfsumme
        # bekommen haben. Fällt die Zahl auf 0, ist der Bestand durchgezogen
        # und übersteht ab dann Umbenennen und Verschieben zugleich.
        "kennzeichen_nachgetragen": nachgetragen,
        "hinweise": hinweise,
    }


def _neue_aufnehmen(session: Session, o: Objekt, dateien: dict, client,
                    vergeben: set[str]) -> tuple[int, int]:
    """Lose Dateien im Hauptordner aufnehmen — wie beim Scanlauf.

    Der gewachsene Bestand in den Unterordnern bleibt aussen vor: er gehört
    dem Nutzer, und ihn ungefragt in die Ablage zu ziehen wäre keine
    Aufräumhilfe, sondern ein Eingang mit zweihundert Einträgen."""
    neu = automatisch = 0
    wurzel = _norm(o.nc_ordner)
    for pfad, e in sorted(dateien.items()):
        if _elternteil(pfad) != wurzel:
            continue      # nur lose Dateien im Hauptordner sind Eingang
        d = _aufnehmen(session, o, e)
        if not d:
            continue
        neu += 1
        vergeben.add(pfad)
        try:
            if _automatisch(session, d, o, client):
                automatisch += 1
        except Exception as fehler:                   # noqa: BLE001
            session.rollback()
            log.warning("Automatik gescheitert für %s: %s", pfad, fehler)
    return neu, automatisch


@router.get("/abgleich")
def abgleich_plan(session: Session = Depends(get_session),
                  familie: Familie = Depends(aktuelle_familie)) -> dict:
    """Trockenlauf: was ein vollständiges Neueinlesen ändern würde.

    Ändert nichts — weder in der Cloud noch in der Datenbank."""
    if not sperre.acquire(blocking=False):
        raise HTTPException(409, "Der Eingang wird gerade geprüft — "
                                 "einen Moment, dann noch einmal versuchen.")
    try:
        return _abgleiche(session, trocken=True, familie_id=familie.id)
    finally:
        sperre.release()


@router.post("/abgleich")
def abgleich(session: Session = Depends(get_session),
            familie: Familie = Depends(aktuelle_familie)) -> dict:
    """Liest die Objektordner vollständig neu ein (CXXVII).

    Neue Dateien kommen herein, umgezogene Einträge ziehen mit, und was der
    Nutzer in der Cloud gelöscht hat, nimmt die App von sich aus aus der
    Ablage (N248) — aber nur, wo der Ordner auch wirklich gelesen werden
    konnte. War er es nicht, bleibt es beim reversiblen Vermerk `vermisst`.
    Der Datensatz selbst wird nie gelöscht."""
    if not sperre.acquire(blocking=False):
        raise HTTPException(409, "Der Eingang wird gerade geprüft — "
                                 "einen Moment, dann noch einmal versuchen.")
    try:
        ergebnis = _abgleiche(session, trocken=False, familie_id=familie.id)
    finally:
        sperre.release()
    log.info("Abgleich: %d geprüft, %d entfernt, %d vermisst, %d umgehängt, "
             "%d neu",
             ergebnis["geprueft"], len(ergebnis["entfernt"]),
             len(ergebnis["vermisst"]),
             len(ergebnis["verschoben"]) + len(ergebnis["umbenannt"]),
             ergebnis["neu"])
    return ergebnis


# --------------------------------------------------------------------------
# Liste mit Filtern — eine Ansicht für Eingang und Ablage
# --------------------------------------------------------------------------

@router.get("")
def liste(objekt: str = "", kategorie: str = "", jahr: int | None = None,
          status: str = "", suche: str = "", zeitraum: int | None = None,
          kostenart: str = "",
          session: Session = Depends(get_session),
          familie: Familie = Depends(aktuelle_familie)) -> dict:
    """Alle Dokumente, gefiltert. Die Auswahlwerte kommen mit — die Oberfläche
    baut ihre Filter aus dem, was wirklich da ist.

    N436 — nur die Objekte und Dokumente der angemeldeten Familie, sonst
    zeigte der Eingang jeder Familie den Bestand aller anderen mit."""
    objekte = {o.id: o for o in session.exec(
        select(Objekt).where(Objekt.familie_id == familie.id)).all()}
    nach_slug = {o.slug: o for o in objekte.values()}
    # N253 — Grabsteine gelöschter Belege gehören in keine Liste; auch die
    # Facetten-Zahlen unten sollen sie nicht mitzählen.
    alle = _ohne_grabsteine(session.exec(select(Dokument).where(
        Dokument.objekt_id.in_(list(objekte.keys())))).all()) if objekte else []

    if objekt and objekt not in nach_slug:
        raise HTTPException(404, "Objekt nicht gefunden")
    ziel_id = nach_slug[objekt].id if objekt else None
    begriff = suche.strip().lower()

    # Ein Filter, mehrere Verwender: die übrigen Kriterien einmal bündeln, die
    # Kostenart variiert (Liste: gewählte; Facette: alle).
    flt = dict(ziel_id=ziel_id, kategorie=kategorie, jahr=jahr, status=status,
               zeitraum=zeitraum, begriff=begriff)
    gefiltert = [d for d in alle if _dokument_passt(d, kostenart=kostenart, **flt)]
    # Offenes zuerst, dann Vermisstes, danach das Neueste — so steht oben,
    # was etwas will.
    rang = {"neu": 0, VERMISST: 1}
    gefiltert.sort(key=lambda d: (rang.get(d.status, 2), -(d.jahr or 0),
                                  d.dateiname.lower()))

    genutzt = {d.kategorie for d in alle if d.kategorie}
    # Kostenart-Facette mit Anzahl — gezählt über die ÜBRIGEN Filter (Objekt,
    # Jahr, Status …), aber NICHT über die Kostenart-Wahl selbst. So ziehen die
    # Zahlen an den Buttons mit, sobald man das Objekt oder Jahr wechselt.
    _ka_zahl: dict[str, int] = {}
    for d in alle:
        if d.kostenart and _dokument_passt(d, kostenart="", **flt):
            kanon = kostenart_normalisieren(d.kostenart)
            _ka_zahl[kanon] = _ka_zahl.get(kanon, 0) + 1
    kostenarten = [{"name": k, "anzahl": n} for k, n in
                   sorted(_ka_zahl.items(), key=lambda kv: (-kv[1], kv[0]))]
    jahre = sorted({d.jahr for d in alle if d.jahr}, reverse=True)
    je_objekt: dict[int, int] = {}
    for d in alle:
        if d.objekt_id:
            je_objekt[d.objekt_id] = je_objekt.get(d.objekt_id, 0) + 1

    return {
        "anzahl": len(gefiltert),
        "gesamt": len(alle),
        "offen": sum(1 for d in alle if d.status == "neu"),
        # CXXVII: wie viele Einträge auf eine Datei zeigen, die es in der
        # Cloud nicht mehr gibt. Null heisst: alles am Platz.
        "vermisst": sum(1 for d in alle if d.status == VERMISST),
        "arten": DOKUMENTARTEN,
        "kategorien": [a for a in DOKUMENTARTEN if a in genutzt],
        "kostenarten": kostenarten,
        "jahre": jahre,
        "objekte": [{"slug": o.slug, "name": o.name, "titel": objekt_titel(o),
                     "kuerzel": o.kuerzel,
                     "anzahl": je_objekt.get(o.id, 0),
                     "cloud": bool(o.nc_ordner)}
                    for o in objekte.values()],
        "dokumente": [_zeige(d, objekte) for d in gefiltert],
    }


# --------------------------------------------------------------------------
# CCLXXXI/CCLXXXII: Belege gesammelt zurück ins Warten
#
# „Zurück ins Warten" macht einen Beleg wieder zum offenen Fall: die aus ihm
# vorläufig (orange) angelegten Datensätze werden gelöscht, seine NK-Bindung
# (Kostenposition-Anteil, Zeitraum) gelöst, der Status auf „neu". Das Quell-
# Dokument und die Datei in der Cloud bleiben unangetastet — es wird nur die
# App-seitige Zuordnung zurückgenommen, nichts in der Nextcloud angefasst.
# --------------------------------------------------------------------------

@router.post("/warte-archiv")
def warte_archiv(objekt: str = "", kategorie: str = "", jahr: int | None = None,
                 status: str = "", suche: str = "", zeitraum: int | None = None,
                 kostenart: str = "", vorschau: bool = True,
                 session: Session = Depends(get_session),
                 familie: Familie = Depends(aktuelle_familie)) -> dict:
    """Schickt alle aktuell gefilterten Belege gesammelt zurück ins Warten.

    Dieselben Filter wie die Liste — was der Nutzer sieht, wird verschoben.
    `?vorschau=true` (Vorgabe, N314h) zählt nur, ohne etwas zu ändern; die
    Oberfläche fragt vorher selbst nach und ruft explizit `vorschau=false`.
    Sidecars bleiben außen vor.

    N436 — nur Objekte/Belege der angemeldeten Familie, sonst liesse sich mit
    leeren Filtern der komplette Bestand aller Familien zurück ins Warten
    schicken."""
    nach_slug = {o.slug: o for o in session.exec(
        select(Objekt).where(Objekt.familie_id == familie.id)).all()}
    if objekt and objekt not in nach_slug:
        raise HTTPException(404, "Objekt nicht gefunden")
    ziel_id = nach_slug[objekt].id if objekt else None
    begriff = suche.strip().lower()

    eigene_ids = [o.id for o in nach_slug.values()]
    treffer = [d for d in (session.exec(select(Dokument).where(
                   Dokument.objekt_id.in_(eigene_ids))).all()
                   if eigene_ids else [])
               if _dokument_passt(d, ziel_id=ziel_id, kategorie=kategorie,
                                   kostenart=kostenart, jahr=jahr, status=status,
                                   zeitraum=zeitraum, begriff=begriff)]
    if vorschau:
        return {"vorschau": True, "belege": len(treffer)}
    beruehrt: set[int] = set()
    for d in treffer:
        beruehrt |= _zurueck_ins_warten(session, d)
    session.commit()
    entfernt = _leere_zeitraeume_raeumen(session, beruehrt)
    log.info("Warte-Archiv: %d Belege zurückgestellt, %d leere Zeiträume weg",
             len(treffer), entfernt)
    return {"ok": True, "belege": len(treffer), "zeitraeume_entfernt": entfernt}


@router.post("/nk-vor-jahr-entfernen")
def nk_vor_jahr_entfernen(grenze_jahr: int = 2025, vorschau: bool = True,
                          session: Session = Depends(get_session),
                          familie: Familie = Depends(aktuelle_familie)) -> dict:
    """Nimmt automatisch (orange) aus Belegen angelegte NK-Eintragungen zu
    Abrechnungszeiträumen VOR `grenze_jahr` wieder heraus, Belege zurück ins
    Warten. Bestätigte/geseedete Positionen bleiben unberührt (nur
    `vorlaeufig=True` wird gelöscht). `?vorschau=true` (Vorgabe, N314h)
    zählt nur.

    N436 — wirkte bisher global über alle Familien; ein Aufräumwerkzeug
    greift jetzt nur auf die eigenen Zeiträume/Belege zu, wie jede andere
    Aktion auch."""
    eigene_objekt_ids = set(session.exec(select(Objekt.id).where(
        Objekt.familie_id == familie.id)).all())
    vor = {z.id for z in session.exec(select(Zeitraum)).all()
           if z.start and z.start.year < grenze_jahr
           and z.objekt_id in eigene_objekt_ids}
    drafts = [p for p in session.exec(select(Kostenposition).where(
                  Kostenposition.vorlaeufig == True)).all()   # noqa: E712
              if p.zeitraum_id in vor and p.quelle_dokument_id]
    beleg_ids = {p.quelle_dokument_id for p in drafts}
    for d in session.exec(select(Dokument)).all():
        if d.zeitraum_id in vor:
            beleg_ids.add(d.id)
    if vorschau:
        return {"vorschau": True, "grenze_jahr": grenze_jahr,
                "zeitraeume_vor_grenze": len(vor),
                "orange_positionen": len(drafts), "belege": len(beleg_ids)}
    beruehrt: set[int] = set(vor)
    for did in beleg_ids:
        d = session.get(Dokument, did)
        if d:
            beruehrt |= _zurueck_ins_warten(session, d)
    session.commit()
    entfernt = _leere_zeitraeume_raeumen(session, beruehrt)
    log.info("NK vor %d entfernt: %d orange Positionen, %d Belege zurück, "
             "%d Zeiträume weg", grenze_jahr, len(drafts), len(beleg_ids), entfernt)
    return {"ok": True, "grenze_jahr": grenze_jahr,
            "orange_positionen_geloescht": len(drafts),
            "belege_zurueck": len(beleg_ids), "zeitraeume_entfernt": entfernt}


@router.post("/kostenarten-normalisieren")
def kostenarten_normalisieren(vorschau: bool = False,
                              session: Session = Depends(get_session)) -> dict:
    """Fasst Kostenart-Dubletten im Bestand auf ihre kanonische Form zusammen
    (CCLXXX) — an Belegen wie an Kostenpositionen. `vorschau=1` zählt nur."""
    geaendert = 0
    proben: list[str] = []
    for d in session.exec(select(Dokument)).all():
        if d.kostenart:
            kanon = kostenart_normalisieren(d.kostenart)
            if kanon != d.kostenart:
                if len(proben) < 12:
                    proben.append(f"{d.kostenart} → {kanon}")
                if not vorschau:
                    d.kostenart = kanon
                    session.add(d)
                geaendert += 1
    for p in session.exec(select(Kostenposition)).all():
        if p.kostenart:
            kanon = kostenart_normalisieren(p.kostenart)
            if kanon != p.kostenart:
                if not vorschau:
                    p.kostenart = kanon
                    session.add(p)
                geaendert += 1
    if not vorschau:
        session.commit()
    return {"vorschau": vorschau, "geaendert": geaendert, "proben": proben}


@router.get("/objekt/{slug}")
def je_objekt(slug: str, session: Session = Depends(get_session),
              familie: Familie = Depends(aktuelle_familie)) -> list[dict]:
    """Die zugeordneten Dokumente einer Immobilie — dieselbe Auswahl wie
    `?objekt=…&status=zugeordnet`, nur als schlichte Liste für Aufrufer, die
    keine Filterwerte brauchen."""
    return liste(objekt=slug, status="zugeordnet", session=session,
                familie=familie)["dokumente"]


# --------------------------------------------------------------------------
# CCXCIX — der Dokumentenbaum einer Immobilie
#
# Die Ablage als Gliederung: je Kategorie ein Ast (mit ihrem Cloud-Ordner),
# daran die Dokumente. Entscheidend ist `zugeordnet`: hängt an dem Beleg schon
# ein Datensatz (Kostenposition, Miete, Versicherung, Kredit, Notarvertrag) —
# oder wartet er noch? Nur das Wartende muss der Nutzer anfassen.
# --------------------------------------------------------------------------

@router.post("/objekt/{slug}/pfade-reparieren")
def pfade_reparieren(vorschau: bool = False,
                     session: Session = Depends(get_session),
                     o: Objekt = Depends(objekt_holen)) -> dict:
    """Zieht veraltete Dateipfade nach (CCCVII).

    Wandert eine Datei in der Nextcloud in einen Unterordner (von Hand oder
    beim Einsortieren), zeigt der gespeicherte Pfad ins Leere — die Vorschau
    meldet dann „Datei nicht gefunden". Hier wird jede vermisste Datei in den
    Unterordnern des Objekts unter ihrem Namen gesucht und der Pfad berichtigt.
    Verschoben oder gelöscht wird nichts.

    Ein Pfad, ein Eintrag: hält bereits ein anderes Dokument den berichtigten
    Pfad (zwei Einträge zu derselben Datei), wird dieser Eintrag übersprungen
    und in `uebersprungen` mitgezählt — statt den Commit an der Eindeutigkeit
    scheitern zu lassen.

    N436 — `o` kommt über `objekt_holen`, das den Slug zusätzlich auf die
    angemeldete Familie eingrenzt (404 bei fremdem Objekt)."""
    if not o.nc_ordner:
        raise HTTPException(400, "Für dieses Objekt ist kein Ordner verknüpft.")
    client = verbindung(session)

    # Wo liegt welche Datei wirklich? Hauptordner + eine Ebene darunter —
    # dieselbe Suche, die auch die Vorschau einzeln benutzt (`_pfad_heilen`).
    try:
        wo = _dateien_im_objekt(client, o)
    except NextcloudFehler as fehler:
        raise HTTPException(400, str(fehler)) from fehler

    geprueft = berichtigt = uebersprungen = 0
    proben: list[str] = []
    for d in session.exec(select(Dokument).where(Dokument.objekt_id == o.id)).all():
        if _ist_sidecar(d.dateiname):
            continue
        geprueft += 1
        richtig = wo.get(d.dateiname)
        if not richtig or richtig == d.pfad:
            continue
        belegt = _pfad_belegt_von(session, richtig, d.id)
        if belegt:
            # Zwei Einträge zu derselben Datei — der zweite bliebe an der
            # Eindeutigkeit hängen. Also stehen lassen und ehrlich melden.
            uebersprungen += 1
            if len(proben) < 10:
                proben.append(f"{d.dateiname}: übersprungen — Pfad schon von "
                              f"Dokument #{belegt} belegt")
            continue
        if len(proben) < 10:
            proben.append(f"{d.dateiname}: {d.pfad} → {richtig}")
        if not vorschau:
            d.pfad = richtig
            kidb.pfad_nachziehen(session, d)   # N299
            if d.status == VERMISST:
                d.status = "zugeordnet"
            session.add(d)
        berichtigt += 1
    if not vorschau:
        try:
            session.commit()
        except IntegrityError as fehler:
            # Rest-Konflikt (nebenläufig dazwischengekommen): nichts speichern
            # ist besser als ein 500er. Die Datei bleibt unangetastet.
            session.rollback()
            log.warning("Pfade reparieren (%s): Konflikt beim Speichern: %s",
                        o.slug, fehler)
            proben.append("Nicht gespeichert: ein Zielpfad ist doppelt belegt.")
            return {"vorschau": vorschau, "geprueft": geprueft, "berichtigt": 0,
                    "uebersprungen": uebersprungen + berichtigt,
                    "proben": proben}
    log.info("Pfade repariert (%s): %d von %d, %d übersprungen",
             o.slug, berichtigt, geprueft, uebersprungen)
    return {"vorschau": vorschau, "geprueft": geprueft,
            "berichtigt": berichtigt, "uebersprungen": uebersprungen,
            "proben": proben}


@router.get("/objekt/{slug}/baum")
def baum(session: Session = Depends(get_session),
         o: Objekt = Depends(objekt_holen)) -> dict:
    """Dokumentenbaum nach dem ECHTEN Ordner (CCCXVI): jeder Ast ist ein
    Nextcloud-Unterordner, so wie er in Windows steht. Untergeordnete Info-
    Belege stehen eingerückt unter ihrer Hauptdatei (CCCXVII).

    N436 — `o` kommt über `objekt_holen`, familiengrenzend."""
    # Woran hängt ein Beleg? (Beleg-Id → Rubrik) und: welcher Datensatz stammt
    # aus welchem Beleg (Datensatz → Quell-Beleg), um die Hierarchie zu bauen.
    haengt_an: dict[int, str] = {}
    quelle_von: dict[tuple[str, int], int] = {}   # (typ, id) → Quell-Beleg-Id
    # N334g — diese Tabelle MUSS jedes Modell aus `_ZUORDNUNG_MODELLE` kennen.
    # Als N331c die Grundschuld dort ergänzte, fehlte sie hier: der Zugriff
    # `typname[modell]` warf einen KeyError, und zwar unabhängig von den Daten
    # (die Schleife läuft über alle Modelle). Der ganze Dokumentenbaum
    # antwortete danach mit 500. `test_baum_kennt_jedes_zuordnungsmodell`
    # hält das jetzt fest.
    typname = {Notarvertrag: "notarvertrag", Zahlung: "zahlung", Kredit: "kredit",
               Versicherung: "versicherung", Miete: "miete",
               Kostenposition: "kostenposition", Bewohner: "bewohner",
               Grundschuld: "grundschuld"}
    for modell, rubrik in _ZUORDNUNG_MODELLE:
        for e in session.exec(select(modell).where(
                modell.quelle_dokument_id.is_not(None))).all():
            haengt_an.setdefault(e.quelle_dokument_id, rubrik)
            quelle_von[(typname[modell], e.id)] = e.quelle_dokument_id

    # N253 — Grabsteine gelöschter Belege stehen in keinem Ordner mehr und
    # gehören deshalb auch in keinen Ast des Baums.
    dokumente = [d for d in _ohne_grabsteine(session.exec(select(Dokument).where(
        Dokument.objekt_id == o.id)).all()) if not _ist_sidecar(d.dateiname)]

    aeste: dict[str, dict] = {}
    for d in sorted(dokumente, key=lambda x: (-(x.jahr or 0), x.dateiname.lower())):
        ordner = _ordner_aus_pfad(d.pfad, o.nc_ordner)
        ast = aeste.setdefault(ordner, {
            "ordner": ordner, "titel": _ordner_titel(ordner), "dokumente": []})
        # Eine Kostenposition zählt auch über `position_id` als Zuordnung.
        rubrik = haengt_an.get(d.id) or ("Nebenkosten" if d.position_id else "")
        # CCCXVII: hängt der Beleg als Info an einem Eintrag, der selbst aus
        # einem anderen Beleg stammt, ist jener andere Beleg seine Hauptdatei.
        info = False
        unter = None
        if not rubrik and (d.info_zu_typ or ""):
            rubrik = _INFO_RUBRIK.get(d.info_zu_typ, "objekt")
            info = True
            if d.info_zu_typ and d.info_zu_id:
                unter = quelle_von.get((d.info_zu_typ, d.info_zu_id))
        ast["dokumente"].append({
            "id": d.id, "dateiname": d.dateiname, "pfad": d.pfad, "jahr": d.jahr,
            "betrag": d.betrag, "kostenart": d.kostenart, "kategorie": d.kategorie,
            "status": d.status, "zugeordnet": bool(rubrik), "rubrik": rubrik,
            "info": info, "unter": unter,
        })

    for ast in aeste.values():
        ast["anzahl"] = len(ast["dokumente"])
        ast["offen"] = sum(1 for x in ast["dokumente"] if not x["zugeordnet"])

    reihe = sorted(aeste.values(), key=lambda a: (a["ordner"] or "￿"))
    return {
        "objekt": o.slug, "name": o.name, "titel": objekt_titel(o),
        "gesamt": len(dokumente),
        "offen": sum(a["offen"] for a in reihe),
        "aeste": reihe,
    }


def _miete_kette(session: Session, eid: int) -> list[int]:
    """N228 — ein Mietstand und alle Vorgänger (Mieterhöhungen), über
    `vorgaenger_id` verkettet. Ihre Dokumente gelten auch am neuen Stand —
    kein Kopieren, dieselbe Datei zählt für die ganze Kette. Gegen einen
    versehentlichen Ring (Vorgänger zeigt zurück auf sich selbst) bricht die
    Kette am ersten Wiederholungsfund ab, statt endlos zu laufen."""
    kette = [eid]
    gesehen = {eid}
    aktuell = eid
    while True:
        m = session.get(Miete, aktuell)
        vorgaenger = getattr(m, "vorgaenger_id", None) if m else None
        if not vorgaenger or vorgaenger in gesehen:
            break
        kette.append(vorgaenger)
        gesehen.add(vorgaenger)
        aktuell = vorgaenger
    return kette


@router.get("/objekt/{slug}/eintrag/{typ}/{eid}/belege")
def belege_zum_eintrag(typ: str, eid: int,
                       session: Session = Depends(get_session),
                       o: Objekt = Depends(objekt_holen)) -> dict:
    """Die Belege eines einzelnen Eintrags für die Detailansicht (CCCXIII).

    `haupt` ist der Beleg, aus dem der Eintrag entstand (`quelle_dokument_id`).
    `unter` sind die Info-Belege, die als Nachweis an ihm hängen
    (`info_zu_typ`/`info_zu_id`) — im Baum stehen sie eingerückt darunter.

    N228 — bei einem Mietverhältnis (`typ == "miete"`) zählen zusätzlich die
    Belege aller Vorgänger-Mietstände (Mieterhöhungen derselben Partei) als
    hinterlegt, und die Reihenfolge wird chronologisch (Einzug → Auszug) statt
    „neueste zuerst" — anders als bei den übrigen Eintragstypen.

    N436 — `o` kommt über `objekt_holen`, familiengrenzend."""
    paar = _AN_TYP_MODELLE.get(typ)
    if not paar:
        raise HTTPException(404, f"Unbekannter Eintragstyp: {typ}")
    modell, _rubrik = paar
    eintrag = session.get(modell, eid)
    if not eintrag or getattr(eintrag, "objekt_id", o.id) != o.id:
        raise HTTPException(404, "Eintrag nicht gefunden")

    haupt = None
    quelle = getattr(eintrag, "quelle_dokument_id", None)
    if quelle:
        d = session.get(Dokument, quelle)
        # N253 — ein Grabstein ist kein vorzeigbarer Beleg mehr.
        if d and not _ist_sidecar(d.dateiname) and not _ist_grabstein(d.pfad):
            haupt = _beleg_karte(d)

    kette = _miete_kette(session, eid) if typ == "miete" else [eid]
    unter = [_beleg_karte(d) for d in _ohne_grabsteine(session.exec(
        select(Dokument).where(
            Dokument.info_zu_typ == typ, Dokument.info_zu_id.in_(kette))).all())
        if not _ist_sidecar(d.dateiname) and d.id != quelle]
    # Der Hauptbeleg jedes Vorgängers hat keinen eigenen `haupt`-Platz mehr
    # (der gehört dem aktuellen Stand) — er zählt hier als weiterer Beleg.
    for vid in kette[1:]:
        vm = session.get(Miete, vid)
        vquelle = getattr(vm, "quelle_dokument_id", None) if vm else None
        if vquelle and vquelle != quelle:
            d = session.get(Dokument, vquelle)
            if d and not _ist_sidecar(d.dateiname):
                unter.append(_beleg_karte(d))
    if typ == "miete":
        unter.sort(key=lambda x: (x["jahr"] or 0, x["dateiname"].lower()))
    else:
        unter.sort(key=lambda x: (-(x["jahr"] or 0), x["dateiname"].lower()))
    return {"haupt": haupt, "unter": unter}


class UmklassifizierenIn(BaseModel):
    ziel: str


@router.post("/eintrag/{typ}/{eid}/umklassifizieren")
def umklassifizieren(typ: str, eid: int, data: UmklassifizierenIn,
                     session: Session = Depends(get_session),
                     familie: Familie = Depends(aktuelle_familie)) -> dict:
    """Überführt einen Eintrag in eine andere Rubrik (CCCXXIV).

    Beispiel: der „Notarvertrag Kaufvertrag" ist eigentlich die Notargebühren-
    Rechnung und gehört zu den einmaligen Erwerbsnebenkosten. Die Belege
    (Quell-Beleg + Info-Belege) wandern mit; der alte Eintrag wird gelöscht.
    Innerhalb derselben Tabelle (Zahlung → Zahlung) bleibt die id erhalten und
    es wird nur die Kategorie umgestellt — dann muss gar nichts umgehängt werden.
    Datensicher: erst das Ziel anlegen, dann den alten Eintrag entfernen."""
    paar = _AN_TYP_MODELLE.get(typ)
    if not paar:
        raise HTTPException(404, f"Unbekannter Eintragstyp: {typ}")
    modell, _rubrik = paar
    eintrag = session.get(modell, eid)
    if not eintrag:
        raise HTTPException(404, "Eintrag nicht gefunden")
    o = session.get(Objekt, getattr(eintrag, "objekt_id", None))
    if not o or o.familie_id != familie.id:
        raise HTTPException(404, "Objekt nicht gefunden")

    ziel = (data.ziel or "").strip().lower()
    cfg = _UMKLASS_ZIEL.get(ziel)
    if not cfg:
        raise HTTPException(400, f"Unbekanntes Ziel „{data.ziel}“")
    ziel_typ = cfg["typ"]

    # Gleiche Tabelle (Zahlung → Zahlung): nur die Kategorie umstellen. id und
    # alle Belege bleiben hängen — nichts wird gelöscht oder umgehängt.
    if typ == ziel_typ == "zahlung":
        eintrag.kategorie = cfg["kategorie"]
        eintrag.turnus = cfg["turnus"]
        eintrag.absetzbar = cfg["absetzbar"]
        session.add(eintrag)
        session.commit()
        return {"ok": True, "neu": {"typ": "zahlung", "id": eintrag.id,
                                    "art": eintrag.art}}

    kern = _eintrag_kern(eintrag)
    if ziel_typ == "zahlung":
        neu = Zahlung(objekt_id=o.id, jahr=kern["jahr"] or date.today().year,
                      art=kern["art"], kategorie=cfg["kategorie"],
                      turnus=cfg["turnus"], absetzbar=cfg["absetzbar"],
                      betrag=kern["betrag"], notiz=_bewahrt(kern),
                      quelle_dokument_id=kern["quelle_dokument_id"])
    elif ziel_typ == "notarvertrag":
        # Das tagesgenaue Beurkundungsdatum hat Vorrang. Nur wenn die Quelle gar
        # keines hat (eine Zahlung kennt bloß das Jahr), bleibt der 1. Januar.
        datum = kern["datum"] or (date(kern["jahr"], 1, 1) if kern["jahr"] else None)
        neu = Notarvertrag(objekt_id=o.id, art=kern["art"], betrag=kern["betrag"],
                           datum=datum, beteiligte=kern["beteiligte"],
                           notar=kern["notar"], urnr=kern["urnr"],
                           notiz=kern["notiz"],
                           quelle_dokument_id=kern["quelle_dokument_id"])
    else:                                               # pragma: no cover
        raise HTTPException(400, f"Ziel „{ziel}“ wird nicht unterstützt")
    session.add(neu)
    session.flush()

    # Info-Belege des alten Eintrags an den neuen hängen.
    for d in session.exec(select(Dokument).where(
            Dokument.info_zu_typ == typ, Dokument.info_zu_id == eid)).all():
        d.info_zu_typ = ziel_typ
        d.info_zu_id = neu.id
        session.add(d)
    session.delete(eintrag)
    session.commit()
    log.info("Eintrag %s#%s nach %s umklassifiziert → %s#%s", typ, eid,
             ziel, ziel_typ, neu.id)
    return {"ok": True, "neu": {"typ": ziel_typ, "id": neu.id, "art": neu.art}}


@router.get("/wachdienst")
def wachdienst_status() -> dict:
    """Wann zuletzt automatisch nachgesehen wurde."""
    return wachdienst_zustand()


@router.get("/erkennung")
def erkennung_status() -> dict:
    """Ist die Texterkennung eingerichtet? Steuert den Hinweis in der App.

    `verfuegbar` sagt, ob überhaupt etwas gelesen werden kann. Das ist mehr
    als früher: ein maschinengeschriebenes PDF wird auch ohne Bilderkennung
    gelesen. `bilder` und `pdf` sagen, welcher der beiden Wege offen ist —
    fehlt Tesseract, bleiben nur Fotos stumm. `scan` sagt, ob auch ein
    eingescanntes PDF gelesen wird (CLXXIX): das braucht beides — die
    Rasterbibliothek *und* Tesseract."""
    return {"verfuegbar": ocr.erkennung_moeglich(),
            "bilder": ocr.verfuegbar(),
            "pdf": pdftext.verfuegbar(),
            "scan": pdftext.kann_rastern() and ocr.verfuegbar()}


def _regeln(session: Session) -> list[Erkennungsregel]:
    """Die aktiven Erkennungsregeln des Nutzers."""
    return list(session.exec(select(Erkennungsregel)
                             .where(Erkennungsregel.aktiv == True)).all())  # noqa: E712


# --------------------------------------------------------------------------
# N162 — Strombelege: Menge und Bruttobetrag der Lieferung
#
# Der einzige Strombeleg in der Hochlage ist der externe Zukauf. Gebraucht
# werden daraus die wirklich verbrauchten Kilowattstunden und der Bruttopreis
# dafür (Grundpreis enthalten, er wird nicht getrennt umgelegt). Betrag je Menge
# ist der Netzpreis; die Stromkette leitet PV und Akku mit 10 % Abschlag daraus
# ab — das passiert dort, nicht hier.
#
# Der allgemeine Auslese-Zweig greift auf einer Jahresabrechnung leicht daneben:
# neben dem Bruttobetrag der Lieferung stehen dort die Nachzahlung nach Abzug
# der Abschläge und der monatliche Abschlag. Deshalb ein zweiter, gezielter
# Aufruf, der die drei getrennt liest und benennt.
# --------------------------------------------------------------------------

def _strom_ergaenzen(session: Session, rohdaten: bytes, ergebnis: dict,
                     dateiname: str = "", kostenart: str = "",
                     text: str | None = None) -> None:
    """Ergänzt einen Strombeleg um Menge und Bruttobetrag (N162).

    Rein additiv: ohne Strom-Kontext, ohne eingerichtete KI oder bei jedem
    Fehler bleibt `ergebnis` unverändert — es kostet dann auch keinen Aufruf.

    `text`: optional schon anderswo erkannter Text (N328(ii)) — erspart den
    zweiten OCR-Lauf, wenn der Aufrufer ihn schon hat."""
    ki_key = _ki_key(session)
    if not kiauslese.verfuegbar(ki_key):
        return
    if not kiauslese.ist_strom_kontext(_strom_hinweis(kostenart, ergebnis)):
        return
    if text is None:
        text = ocr.text_aus_beleg(rohdaten)
    if not (text or "").strip():
        return
    strom = kiauslese.lies_strom(text, dateiname, schluessel=ki_key,
                                 modell=_ki_modell(session))
    if not strom:
        return
    ergebnis["strom"] = strom
    ergebnis["ki"] = True
    _strom_in_felder(ergebnis, strom)


# N296 — was am Ergebnis vom KONTEXT der Anfrage abhängt und deshalb nie
# unbesehen aus dem Zwischenspeicher kommen darf. Der Inhalt einer Datei ist
# immer derselbe; welche dieser Zusätze gefragt sind, entscheidet erst der
# Aufruf: `wasser`/`strom` hängen an der Kostenart, `formwerte` an der Maske.
_KONTEXTFELDER = ("wasser", "strom", "formwerte", "formname")


def _aus_zwischenspeicher(session: Session, gemerkt: dict, kostenart: str,
                          bereich: str, ergebnis_hinweis: dict | None = None) -> dict:
    """N296 — eine gemerkte Auslese auf den aktuellen Kontext zuschneiden.

    Der teure Teil — die Auslese der Bytes — ist erledigt und wird übernommen.
    Die kontextabhängigen Zusätze werden NICHT unbesehen mitgegeben, sondern
    nur, wenn dieser Aufruf sie auch verlangt hätte. Ohne diese Trennung bekäme
    die Notarvertragsmaske die Felder einer Wasserrechnung, nur weil dieselbe
    Datei einmal von dort gelesen wurde — genau das ist beim Bauen passiert und
    hat fünf Tests umgeworfen.

    Ein Aufruf kostet das trotzdem nicht: `wasser`/`strom` kommen ebenfalls aus
    dem Zwischenspeicher, sie werden nur nach Kontext ein- oder ausgeblendet."""
    basis = {k: v for k, v in gemerkt.items() if k not in _KONTEXTFELDER}
    # Der Zwischenspeicher spart Budget — er verleiht keine Fähigkeit. Ist
    # keine KI eingerichtet, könnte dieser Aufruf `wasser`/`strom` gar nicht
    # erzeugen; dann darf er sie auch nicht aus dem Speicher bekommen. Dieselbe
    # erste Prüfung wie in `_strom_ergaenzen`.
    mit_ki = kiauslese.verfuegbar(_ki_key(session))
    if mit_ki and "wasser" in gemerkt and kiauslese.ist_wasser_kontext(kostenart):
        basis["wasser"] = gemerkt["wasser"]
    if mit_ki and "strom" in gemerkt and kiauslese.ist_strom_kontext(
            _strom_hinweis(kostenart, ergebnis_hinweis or basis)):
        basis["strom"] = gemerkt["strom"]
        _strom_in_felder(basis, gemerkt["strom"])
    return _mit_formwerten(basis, bereich)


def _mit_formwerten(ergebnis: dict, bereich: str) -> dict:
    """N263/N296 — die Auslese auf die Felder der gemeinten Eingabemaske
    übersetzen. Rein additiv: ohne `bereich` bleibt die Antwort unverändert.

    Ausgelagert, weil es an ZWEI Stellen gebraucht wird — nach einem frischen
    KI-Lauf und nach einem Treffer im Zwischenspeicher. Der Zwischenspeicher
    hält bewusst nur das Bereichsunabhängige; alles andere entstünde sonst
    einmal falsch und bliebe es."""
    if not bereich:
        return ergebnis
    formwerte = feldzuordnung.werte_fuer(bereich, ergebnis)
    if not formwerte:
        return ergebnis
    # N331b — der Dateiname darf mehr wissen als die Eingabemaske: eine
    # Erwerbsnebenkosten-Sammelrechnung nennt zwei Positionen, aber `Zahlung`
    # hat kein Feld dafür. Deshalb NICHT über `formwerte` (das geht roh in
    # den Speicher-Aufruf) — nur lose für den Namensvorschlag beigemischt.
    namenswerte = formwerte
    teile = ergebnis.get("felder", {}).get("erwerb_teile")
    if bereich == "erwerbskosten" and teile:
        namenswerte = {**formwerte, "teile": teile}
    return {**ergebnis, "formwerte": formwerte,
            "formname": feldzuordnung.namensvorschlag(bereich, namenswerte)}


@router.post("/erkennen")
async def erkennen(datei: UploadFile = File(...),
                   kostenart: str = Form(""),
                   bereich: str = Form(""),
                   session: Session = Depends(get_session)) -> dict:
    """Liest Betrag, Datum und Art aus einer Aufnahme oder einem PDF.

    Die Erkennungsregeln des Nutzers haben Vorrang: trifft ein Muster, gilt
    dessen Richtung. Nichts wird gespeichert.

    N78 — optionaler Kontext-Hinweis `kostenart`: additiv, bestehende Aufrufer
    ohne das Feld laufen unverändert. Deutet er auf einen Wasser-Beleg (die
    Wasser-Sammelposition ist das Ziel), liest die KI zusätzlich die drei
    Bereichs-Gebühren (Frisch-/Schmutz-/Niederschlagswasser) und gibt sie als
    Feld `wasser: {wasser, schmutz, niederschlag}` zurück. Fällt die KI aus oder
    ist es kein Wasserbeleg, bleibt `wasser` weg — der Rest der Antwort ist
    unverändert.

    N263 — optionaler Hinweis `bereich` (`notarvertraege`, `versicherungen`,
    `kredite`, `mieten`, `zahlungen`): dann kommt zusätzlich `formwerte` zurück
    — die Auslese schon auf die Feldnamen dieser Eingabemaske übersetzt, damit
    das Formular vorausgefüllt aufgeht. Ebenfalls additiv: ohne den Hinweis
    fehlt `formwerte` und für bestehende Aufrufer ändert sich nichts."""
    # N292 — Grösse und Dateiart prüft `upload.lies`, für alle Endpunkte
    # gleich. Vorher las diese Stelle jede Datei ungeprüft und in voller
    # Länge in den Speicher.
    rohdaten = await upload.lies(datei, was="Der Beleg")
    # N296 — fotografiert der Nutzer denselben Beleg ein zweites Mal (oder
    # schickt dieselbe PDF erneut hoch), ist der Inhalt byte-gleich und die
    # Auslese längst bezahlt. Der Zwischenspeicher antwortet dann sofort.
    sha1 = kicache.pruefsumme(rohdaten)
    gemerkt = kicache.hole(session, sha1)
    if gemerkt is not None:
        return {**_aus_zwischenspeicher(session, gemerkt, kostenart, bereich),
                "aus_zwischenspeicher": True}
    # Der Dateiname als zusätzlicher Kontext für die KI-Auslese (CCLXVIII):
    # „2025-10-oel-2729,91€.pdf" nennt Datum und Betrag schon mit.
    ergebnis = ocr.erkenne(rohdaten, _regeln(session), datei.filename or "",
                           ki_key=_ki_key(session), ki_modell=_ki_modell(session))
    # N296 — der Stand VOR jeder kontextabhängigen Anreicherung. `_strom_in_felder`
    # schreibt den Lieferbetrag in `betrag` und `felder`; würde das mitgemerkt,
    # trüge ein Aufruf ohne Strom-Kontext später einen Strombetrag, den er
    # selbst nie erzeugt hätte.
    kern = dict(ergebnis)
    # N78 — nur beim Wasser-Hinweis und nur mit eingerichteter KI ein zweiter,
    # gezielter Aufruf für die drei Bereichsbeträge. Rein additiv; scheitert er,
    # bleibt die Antwort wie bisher.
    ki_key = _ki_key(session)
    if kiauslese.ist_wasser_kontext(kostenart) and kiauslese.verfuegbar(ki_key):
        text = ocr.text_aus_beleg(rohdaten)
        if text and text.strip():
            wasser = kiauslese.lies_wasser(text, datei.filename or "",
                                           schluessel=ki_key,
                                           modell=_ki_modell(session))
            if wasser:
                ergebnis["wasser"] = wasser
    # N162 — dasselbe für Strom: Menge (kWh) und Bruttobetrag der Lieferung,
    # sauber getrennt von Nachzahlung und Abschlag. Greift auch ohne Hinweis,
    # wenn die allgemeine Auslese einen Strombeleg erkannt hat.
    _strom_ergaenzen(session, rohdaten, ergebnis, datei.filename or "", kostenart)
    # N296 — gemerkt wird der Kern plus die beiden teuren Zusatzauslesen als
    # eigene Blöcke. Ob sie später gezeigt werden, entscheidet der Kontext des
    # jeweiligen Aufrufs (`_aus_zwischenspeicher`), nicht dieser hier.
    kicache.merke(session, sha1, {
        **kern,
        **({"wasser": ergebnis["wasser"]} if "wasser" in ergebnis else {}),
        **({"strom": ergebnis["strom"]} if "strom" in ergebnis else {}),
    }, _ki_modell(session))
    return _mit_formwerten(ergebnis, bereich)


# --------------------------------------------------------------------------
# CCXLIX — Erkennungsmuster: der Nutzer bringt der Erkennung eigene Wörter bei.
# --------------------------------------------------------------------------
class RegelIn(BaseModel):
    muster: str
    kategorie: str = "Nebenkosten"
    kostenart: str = ""
    ist_kosten: bool = True
    rang: int = 0
    aktiv: bool = True


@router.get("/erkennungsregeln", response_model=None)
def regeln_liste(session: Session = Depends(get_session)) -> list:
    reihe = session.exec(select(Erkennungsregel)
                         .order_by(Erkennungsregel.rang, Erkennungsregel.id)).all()
    return [r.model_dump() for r in reihe]


@router.post("/erkennungsregeln", status_code=201)
def regel_anlegen(data: RegelIn, session: Session = Depends(get_session)) -> dict:
    if not (data.muster or "").strip():
        raise HTTPException(400, "Das Muster darf nicht leer sein")
    r = Erkennungsregel(**data.model_dump())
    r.muster = r.muster.strip()
    session.add(r)
    session.commit()
    session.refresh(r)
    return r.model_dump()


@router.patch("/erkennungsregeln/{rid}")
def regel_aendern(rid: int, data: dict,
                  session: Session = Depends(get_session)) -> dict:
    r = session.get(Erkennungsregel, rid)
    if not r:
        raise HTTPException(404, "Regel nicht gefunden")
    for feld in ("muster", "kategorie", "kostenart", "ist_kosten", "rang", "aktiv"):
        if feld in data:
            setattr(r, feld, data[feld])
    session.add(r)
    session.commit()
    return {"ok": True}


@router.delete("/erkennungsregeln/{rid}")
def regel_loeschen(rid: int, session: Session = Depends(get_session)) -> dict:
    r = session.get(Erkennungsregel, rid)
    if not r:
        raise HTTPException(404, "Regel nicht gefunden")
    session.delete(r)
    session.commit()
    return {"ok": True}


@router.post("/neu-klassifizieren")
def neu_klassifizieren(session: Session = Depends(get_session)) -> dict:
    """Wendet die Erkennungsregeln auf den ganzen Bestand an — liest je Beleg
    den OCR-Text und setzt Kategorie/Kostenart, wo ein Muster trifft. Die
    Dateien bleiben, wo sie liegen (nur die Zuordnung ändert sich); ein
    Nicht-Kostenbeleg verliert eine etwaige Kostenposition."""
    regeln = _regeln(session)
    if not regeln:
        return {"geprueft": 0, "geaendert": 0, "hinweis": "Keine aktiven Regeln"}
    client = verbindung(session)
    geprueft = geaendert = geloest = 0
    for d in session.exec(select(Dokument).where(Dokument.status != VERMISST)).all():
        if not (d.pfad or "").startswith("/"):
            continue
        geprueft += 1
        try:
            rohdaten, _typ = client.hole(d.pfad)
            text = ocr.text_aus_beleg(rohdaten)
        except Exception:                    # noqa: BLE001 — ein Beleg blockt nicht alle
            continue
        treffer = ocr.regel_richtung(text, regeln)
        if not treffer:
            continue
        kat, art, ist_kosten = treffer
        if d.kategorie == kat and (d.kostenart or "") == (art or "") \
                and (ist_kosten or not d.position_id):
            continue
        d.kategorie = kat
        d.kostenart = kostenart_normalisieren(art)
        if not ist_kosten and d.position_id:
            belegposten.loese(session, d)
            geloest += 1
        session.add(d)
        geaendert += 1
    session.commit()
    log.info("Neu klassifiziert: %d von %d geprüft, %d Positionen gelöst",
             geaendert, geprueft, geloest)
    return {"geprueft": geprueft, "geaendert": geaendert, "positionen_geloest": geloest}


# --------------------------------------------------------------------------
# CCXXVII: Textschicht im laufenden Betrieb nachtragen
#
# Der Upload selbst bleibt schnell — OCR kostet Sekunden je Seite, das darf
# den Nutzer nie warten lassen (siehe `wachdienst.py`, das diese Funktion im
# 15-Minuten-Takt ruft). Ein Beleg bekommt seine Textschicht deshalb nach dem
# Ablegen, nicht davor: erst liegt die Datei wie immer, danach zieht der
# Wachdienst nach.
#
# Ersetzt wird nur per MOVE, nie durch Überschreiben (CLAUDE.md: „nichts
# überschrieben"): das Original wandert zuerst unangetastet in einen
# Punkt-Ordner neben der Datei — von Cloud-Clients meist ausgeblendet, aber
# nie gelöscht —, erst danach bekommt der freigewordene Platz die geprüfte,
# durchsuchbare Fassung. Scheitert das Ablegen, wandert das Original sofort
# zurück.
# --------------------------------------------------------------------------

# Wie viele Belege ein Lauf höchstens ansieht (billige Prüfung: Datei holen,
# Text zählen) bzw. wirklich neu erkennt (teuer: ~10 s Bilderkennung je
# Datei). Letzteres begrenzt, damit ein einzelner Wachdienst-Takt nicht durch
# einen grossen Rückstau blockiert — der Rest kommt beim nächsten Takt dran.
OCR_PRUEF_GRENZE = 200
OCR_STAPEL = 5

# Versteckt neben der Originaldatei, nicht in einem globalen Sammelordner —
# so bleibt die Sicherung auffindbar genau dort, wo der Beleg auch liegt.
OCR_SICHERUNGSORDNER = ".ocr-original"


def _ocr_kandidaten(session: Session, familie_id: int | None = None) -> list[Dokument]:
    """PDFs, die noch keine Textschicht haben könnten.

    Vermisste Einträge fallen weg — ihre Datei ist ja nicht mehr da (CXXVII).
    Alles andere wird angesehen; ob wirklich OCR nötig ist, entscheidet erst
    `ocr.durchsuchbar_machen` anhand des eingebetteten Texts.

    N436 — `familie_id` grenzt über `Objekt` ein (`Dokument` selbst trägt
    keine eigene Familienspalte, siehe deps.py); `None` lässt wie bisher
    jedes Dokument zu (Vorgabe für den expliziten `client=`-Testpfad)."""
    frage = (select(Dokument)
            .where(Dokument.status != VERMISST)
            .where(Dokument.dateiname.ilike("%.pdf")))
    if familie_id is not None:
        objekt_ids = [o.id for o in session.exec(
            select(Objekt).where(Objekt.familie_id == familie_id)).all()]
        if not objekt_ids:
            return []
        frage = frage.where(Dokument.objekt_id.in_(objekt_ids))
    return list(session.exec(frage.order_by(Dokument.id).limit(OCR_PRUEF_GRENZE)))


def _ocr_ersetzen(client, pfad: str, neu: bytes) -> None:
    """Setzt die geprüfte, durchsuchbare Fassung an die Stelle des Originals —
    ausschliesslich per MOVE, nie durch Überschreiben.

    Das Original wandert zuerst in `OCR_SICHERUNGSORDNER` neben der Datei
    (MKCOL verträgt 405, falls der Ordner schon besteht), erst danach bekommt
    der freie Platz die neue Fassung. Scheitert das Ablegen, wandert das
    Original sofort zurück — der Beleg darf nie unerreichbar werden."""
    ordner, trenner, name = pfad.strip("/").rpartition("/")
    sicher = f"{ordner}/{OCR_SICHERUNGSORDNER}/{name}" if trenner \
        else f"{OCR_SICHERUNGSORDNER}/{name}"
    client.ordner_anlegen(f"{ordner}/{OCR_SICHERUNGSORDNER}" if trenner
                          else OCR_SICHERUNGSORDNER)
    client.verschiebe(pfad, sicher)
    try:
        client.lege_ab(pfad, neu)
    except NextcloudFehler:
        client.verschiebe(sicher, pfad)     # zurück — nichts geht verloren
        raise


def nachtraeglich_ocren(session: Session, client=None,
                        familie_id: int | None = None) -> dict:
    """Ein Nachpflege-Lauf: legt liegen gebliebenen Scans ihre Textschicht
    unter. Vom Wachdienst gerufen, nie vom Upload selbst.

    Rein additiv gegenüber dem normalen Betrieb: ein Beleg, der schon Text
    trägt — ob von Anfang an oder aus einem früheren Lauf —, wird nie
    zweimal angefasst. Fehlen die Bibliotheken (rapidocr-onnxruntime,
    PyMuPDF), meldet der erste Blick das sofort, und es passiert nichts.

    N436 — ohne `client` UND ohne `familie_id` (der Wachdienst-Aufruf) läuft
    über jede Familie einzeln, mit ihrer eigenen Nextcloud-Verbindung. Wer
    (wie die Tests) einen `client` direkt mitgibt, bekommt weiterhin genau
    den einen Lauf ohne Familienschleife."""
    ergebnis = {"geprueft": 0, "ergaenzt": 0, "uebersprungen": 0}
    if not ocr.durchsuchbar_verfuegbar():
        return ergebnis
    if familie_id is None and client is None:
        for teil in _je_familie(
                session, lambda fid: nachtraeglich_ocren(session, familie_id=fid)):
            for schluessel in ergebnis:
                ergebnis[schluessel] += teil[schluessel]
        return ergebnis
    client = client or verbindung(session)
    for d in _ocr_kandidaten(session, familie_id):
        if ergebnis["ergaenzt"] >= OCR_STAPEL:
            break
        try:
            roh, _typ = client.hole(d.pfad)
        except NextcloudFehler as fehler:
            log.info("OCR-Nachpflege: %s nicht lesbar (%s)", d.pfad, fehler)
            continue
        ergebnis["geprueft"] += 1
        try:
            neu = ocr.durchsuchbar_machen(roh)
        except Exception as fehler:                        # noqa: BLE001
            log.warning("OCR fehlgeschlagen für %s: %s", d.pfad, fehler)
            continue
        if neu is None:
            ergebnis["uebersprungen"] += 1
            continue
        try:
            _ocr_ersetzen(client, d.pfad, neu)
        except NextcloudFehler as fehler:
            log.warning("Textschicht konnte nicht abgelegt werden (%s): %s",
                       d.pfad, fehler)
            continue
        d.groesse = len(neu)
        session.add(d)
        session.commit()
        ergebnis["ergaenzt"] += 1
        log.info("Textschicht ergänzt: %s", d.pfad)
    return ergebnis


# --------------------------------------------------------------------------
# Abfotografieren
# --------------------------------------------------------------------------

def _eindeutiges_objekt(session: Session, slug: str, familie_id: int) -> Objekt:
    """Die gemeinte Immobilie. Ohne Angabe nur dann, wenn es genau eine gibt —
    raten wäre hier keine Hilfe, sondern eine falsche Ablage.

    N436 — beides, die Suche per Slug UND die „genau eine"-Regel, gilt nur
    innerhalb der angemeldeten Familie."""
    if slug:
        o = session.exec(select(Objekt).where(
            Objekt.slug == slug, Objekt.familie_id == familie_id)).first()
        if not o:
            raise HTTPException(404, "Objekt nicht gefunden")
        return o
    alle = session.exec(select(Objekt).where(
        Objekt.familie_id == familie_id)).all()
    if len(alle) != 1:
        raise HTTPException(400, "Bitte die Immobilie angeben")
    return alle[0]


def _cloud_pflicht(o: Objekt) -> None:
    """Ohne verknüpften Ordner gibt es keinen Ort für den Beleg. Das jetzt
    sagen ist besser, als ihn später nirgends zu finden."""
    if not o.nc_ordner:
        raise HTTPException(409, f"{o.name} ist mit keinem Nextcloud-Ordner "
                                 "verknüpft — der Beleg hätte dort keinen "
                                 "Platz. Bitte zuerst den Ordner verknüpfen.")


def _pruefe_zeitraum(session: Session, zeitraum_id: int | None) -> int | None:
    """Der Beleg gehört zu einer Abrechnung — aber nur zu einer, die es gibt."""
    if zeitraum_id is None:
        return None
    if not session.get(Zeitraum, zeitraum_id):
        raise HTTPException(404, "Zeitraum nicht gefunden")
    return zeitraum_id


def _pfad_konflikt(session: Session, pfad: str) -> HTTPException:
    """Nimmt die Änderung zurück und liefert die Meldung dazu.

    Ein Eintrag zeigt schon auf diesen Ablageort. Früher lief das in einen
    IntegrityError und damit in einen 500 — die Datei lag am Ziel, die
    Datenbank zeigte auf den Eingang. Ehrlich sagen ist besser."""
    session.rollback()
    log.warning("Pfad bereits vergeben: %s", pfad)
    return HTTPException(409, "Zu diesem Ablageort gibt es schon einen "
                              "Eintrag. Bitte den vorhandenen Eintrag prüfen "
                              "und gegebenenfalls entfernen.")


@router.post("/scannen", status_code=201)
async def scannen(objekt: str = Form(""), kategorie: str = Form("Sonstiges"),
                  kostenart: str = Form(""),
                  jahr: int | None = Form(None), beschreibung: str = Form(""),
                  zeitraum_id: int | None = Form(None),
                  monat: int | None = Form(None),
                  betrag: float | None = Form(None),
                  datum: str = Form(""),
                  datei_jahr: int | None = Form(None),
                  an_typ: str = Form(""),
                  an_id: int | None = Form(None),
                  ki_json: str = Form(""),
                  renovierung_id: int | None = Form(None),
                  datei: UploadFile = File(...),
                  session: Session = Depends(get_session),
                  familie: Familie = Depends(aktuelle_familie)) -> dict:
    """Nimmt ein abfotografiertes Dokument entgegen, benennt es nach Schema
    und legt es direkt im richtigen Unterordner der Immobilie ab.

    Kommt der Beleg von einer Abrechnung, wandert deren `zeitraum_id` mit —
    sonst wäre er zwar abgelegt, aber am Zeitraum nie wiederzufinden.

    `betrag` und `datum` kommen von `/erkennen` durchgereicht: der Betrag
    gehört an das Ende des Dateinamens (CXXIII), das Datum an seinen Anfang.
    Beide werden zusätzlich gespeichert — das Datum, weil tagesgenau
    entscheidet, in welchen Abrechnungszeitraum der Beleg fällt (CLXXII), der
    Betrag, weil aus ihm eine Kostenposition wird (CLXXXI). Im Namen stehen
    sie weiterhin; dort sieht man sie im Ordner.

    `kostenart` ist die genaue Position innerhalb der Art (CLXXI) —
    „Kaminkehrer" unter „Nebenkosten".

    `ki_json` ist die Auslese, die die Oberfläche vor dem Ablegen schon geholt
    hat (N255) — als JSON durchgereicht und hier am frischen Beleg festgehalten.
    Ohne das ginge sie verloren: `/erkennen` läuft auf den nackten Bytes, da
    gibt es den Datensatz noch nicht, an dem `ki_einordnung`/`ki_felder` hängen
    könnten. Der Beleg stünde später ohne Dokumentenerkennung da, und ein
    erneutes Lesen kostete Tokens des Nutzers. Freiwillig: fehlt das Feld oder
    ist es unbrauchbar, läuft alles wie zuvor.

    `datei_jahr` ist ein freiwilliger Rückfall (CCCLXXXIV): das Jahr des
    Datei-Datums (`File.lastModified`), das die Oberfläche mitschickt. Es greift
    nur, wenn weder Auswahl noch erkanntes Datum noch der Dateiname ein
    plausibles Jahr liefern — so entsteht aus einer Artikelnummer kein
    Unsinnsjahr, ein Beleg ohne Jahr im Namen bekommt aber wenigstens eins.

    `an_typ`/`an_id` sind freiwillig (CCCLXVII): sind sie gesetzt, hängt der
    frische Scan gleich am gemeinten Eintrag — so lässt sich der Mietvertrag
    direkt am Mietverhältnis abfotografieren, statt ihn danach im Baum zu
    suchen. Ohne die beiden Felder bleibt alles wie bisher; jeder bestehende
    Aufrufer läuft unverändert weiter.

    `renovierung_id` ist freiwillig (N289): ist sie gesetzt, landet die
    Rechnung im Projektordner ihres Bauvorhabens
    („50_Bauphase_Projekte/2025.01_Generalsanierung") statt flach im
    Sachordner. Eine unbekannte Nummer legt den Beleg eine Ebene höher ab,
    statt den Scan scheitern zu lassen.

    Geprüft wird das Ziel **vor** der Ablage: ein unbekannter Typ oder ein
    Eintrag einer fremden Immobilie soll nicht erst eine Datei in der Cloud
    und einen halben Eintrag in der Datenbank hinterlassen."""
    o = _eindeutiges_objekt(session, objekt, familie.id)
    _cloud_pflicht(o)
    zeitraum_id = _pruefe_zeitraum(session, zeitraum_id)
    # „objekt" (und ein leer übergebenes null) meint: an keinem einzelnen
    # Eintrag — dieselbe Lesart wie in `/zuordnen`.
    an_typ = (an_typ or "").strip().lower()
    if an_typ in ("objekt", "null", "none"):
        an_typ, an_id = "", None
    ziel_eintrag = (_eintrag_holen(session, an_typ, an_id, o)[0]
                    if an_typ else None)

    inhalt = await upload.lies(datei, was="Der Beleg")

    erkannt_jahr, erkannt_monat = _aus_datum(datum)
    jahr = jahr or erkannt_jahr
    # CCCLXXXIV — kommt aus Auswahl und erkanntem Datum kein plausibles Jahr,
    # springt der Dateiname ein und, wenn auch er nichts hergibt, das vom
    # Browser mitgeschickte Datei-Datum (`File.lastModified`). So entsteht kein
    # Unsinnsjahr aus einer Artikelnummer, aber ein Beleg ohne Jahr im Namen
    # bekommt wenigstens das Jahr seiner Datei.
    jahr = _jahr_mit_fallback(jahr, datei.filename or "", datei_jahr)
    monat = monat or erkannt_monat
    kategorie = kategorie or "Sonstiges"
    # Die Endung der hochgeladenen Datei erhalten — ein Foto oder eine Tabelle
    # darf nicht als „.pdf" abgelegt werden. Ohne Endung (z. B. Kamerascan
    # „scan.pdf") bleibt es beim PDF.
    endung = _endung(datei.filename or "") or ".pdf"
    name = dateiname(jahr, kategorie, beschreibung or "Scan", endung,
                     monat, betrag, kostenart)
    client = verbindung(session)
    try:
        sach, ziel_ordner = _ablageordner(session, o, kategorie, jahr, client,
                                          _projektordner(session, renovierung_id))
        _ordner_sichern(client, sach, ziel_ordner)
        name = _freier_name(session, client, ziel_ordner, name)
        client.lege_ab(f"{ziel_ordner}/{name}", inhalt)
    except NextcloudFehler as e:
        raise HTTPException(400, str(e)) from e

    # N328(ii) — den Volltext gleich mit ablegen: die Bytes liegen ohnehin vor
    # (dieselben, die gerade in die Cloud geschrieben wurden), damit ist jeder
    # frische Scan von Anfang an über seinen ganzen Inhalt durchsuchbar, nicht
    # nur über Dateiname und die kurze KI-Zusammenfassung. Scheitert die
    # Texterkennung an einem einzelnen Beleg, bleibt das Feld leer statt den
    # Scan zu gefährden — er ist an dieser Stelle längst erfolgreich abgelegt.
    try:
        erkannter_text = ocr.text_aus_beleg(inhalt)
    except Exception as fehler:                       # noqa: BLE001
        erkannter_text = ""
        log.warning("Text nicht erkannt für frischen Scan %s: %s", name, fehler)

    d = Dokument(pfad=f"/{ziel_ordner}/{name}", dateiname=name,
                 groesse=len(inhalt), objekt_id=o.id, kategorie=kategorie,
                 # N290 — die Prüfsumme steht hier ohne jeden Zusatzaufwand
                 # fest: die Bytes liegen vor. Die Dateinummer trägt der
                 # nächste Abgleich nach, sie kennt nur die Cloud.
                 sha1=hashlib.sha1(inhalt).hexdigest(),
                 kostenart=kostenart_normalisieren(kostenart),
                 betrag=betrag if betrag and betrag > 0 else None,
                 jahr=jahr, belegdatum=_zum_datum(datum),
                 zeitraum_id=zeitraum_id, status="zugeordnet",
                 erkannt_am=date.today(), erkannter_text=erkannter_text)
    session.add(d)
    try:
        session.commit()
    except IntegrityError as e:
        raise _pfad_konflikt(session, f"/{ziel_ordner}/{name}") from e
    session.refresh(d)
    log.info("Scan abgelegt: %s", d.pfad)

    # N255 — die Auslese, die die Oberfläche schon geholt hat, gleich am
    # frischen Beleg festhalten. Sie lief auf den nackten Bytes, bevor es
    # diesen Datensatz gab; ohne diesen Schritt bliebe `ki_einordnung`/
    # `ki_felder` für JEDEN gescannten Beleg dauerhaft leer — die
    # Dokumentenerkennung fehlte im Beleg-Fenster, und ein Nachholen kostete
    # Tokens des Nutzers. Streng defensiv: unbrauchbares JSON wird verworfen,
    # der Scan ist längst erfolgreich und darf daran nie scheitern.
    if ki_json:
        try:
            gelesen = json.loads(ki_json)
            if isinstance(gelesen, dict):
                _ki_am_beleg_festhalten(session, d, gelesen)
        except Exception as fehler:                   # noqa: BLE001
            session.rollback()
            d = session.get(Dokument, d.id) or d
            log.warning("KI-Auslese nicht am Scan festgehalten: %s", fehler)

    # CD — byte-gleiche Zweitkopie desselben Objekts nicht stehen lassen: legt
    # der Nutzer denselben Beleg unter einem detaillierteren Namen erneut ab,
    # weicht die schlechtere Kopie (Keeper-Regel `_dedup_rang`). Best-effort und
    # streng gekapselt — schlägt der Cloud-Zugriff fehl oder ist nichts
    # byte-gleich, bleibt der Scan unangetastet erfolgreich; der Dedup darf den
    # Upload nie scheitern lassen.
    dublette_entfernt = False
    try:
        d, entfernt = _dedup_nach_scan(session, client, d, inhalt)
        dublette_entfernt = entfernt > 0
    except Exception as fehler:                       # noqa: BLE001
        session.rollback()
        d = session.get(Dokument, d.id) or d
        log.warning("Dedup nach Scan übersprungen: %s", fehler)

    # CCCLXVII — der Scan hängt sich gleich an den gemeinten Eintrag. Der
    # Quellbeleg des Eintrags wird nur gesetzt, wenn er noch leer ist: eine
    # bestehende Verknüpfung bleibt unangetastet, nie überschrieben.
    if ziel_eintrag is not None:
        d.info_zu_typ, d.info_zu_id = an_typ, an_id
        session.add(d)
        if getattr(ziel_eintrag, "quelle_dokument_id", None) is None:
            ziel_eintrag.quelle_dokument_id = d.id
            session.add(ziel_eintrag)
        session.commit()
        session.refresh(d)
        log.info("Scan %s an bestehenden %s#%s gehängt", d.id, an_typ, an_id)

    # Der behaltene Beleg wird zurückgegeben — nach dem Dedup kann das eine
    # ANDERE (die bessere, ältere) Kopie sein als die gerade abgelegte.
    return {"id": d.id, "dateiname": d.dateiname, "pfad": d.pfad,
            "abgelegt": True, "objekt": o.slug, "zeitraum_id": d.zeitraum_id,
            "dublette_entfernt": dublette_entfernt,
            "an_typ": an_typ, "an_id": an_id if an_typ else None}


@router.post("/namensvorschlag")
def namensvorschlag(kategorie: str = Form("Sonstiges"),
                    kostenart: str = Form(""),
                    jahr: int | None = Form(None),
                    beschreibung: str = Form(""),
                    monat: int | None = Form(None),
                    betrag: float | None = Form(None),
                    datum: str = Form(""),
                    datei_jahr: int | None = Form(None),
                    dateiname_roh: str = Form("")) -> dict:
    """N250 — wie hiesse dieser Beleg? Rechnet nur, legt nichts ab.

    Die Bestätigungsmaske nach dem Scan zeigt den vorgeschlagenen Namen, bevor
    gespeichert wird. Damit dort nicht eine zweite, langsam auseinanderlaufende
    Namensregel im Browser entsteht, fragt sie dieselbe Funktion, die auch
    `/scannen` benutzt (`dateiname`) — eine Wahrheit, zwei Aufrufer.

    Bewusst ohne Datei und ohne Datenbank: der Aufruf ist rein rechnerisch,
    kostet nichts und darf deshalb bei jeder Änderung im Feld erneut laufen.
    Der Kollisions-Zusatz („-2") fehlt hier absichtlich — ob ein Name frei ist,
    entscheidet erst die Ablage in `_freier_name`, live gegen die Cloud."""
    erkannt_jahr, erkannt_monat = _aus_datum(datum)
    jahr = jahr or erkannt_jahr
    jahr = _jahr_mit_fallback(jahr, dateiname_roh or "", datei_jahr)
    endung = _endung(dateiname_roh or "") or ".pdf"
    # N331c — Nutzer-Fund: „Erwerb-Scan" statt „Erwerb" im Dateinamen. Der
    # Platzhalter „Scan" hier war überflüssig UND falsch — `dateiname()` hat
    # längst einen eigenen, saubereren Rückfall (`mitte or "Beleg"`, siehe
    # dort), der ohne diesen künstlichen Zwischenwert einfach beim Kürzel
    # allein bliebe (z. B. „Erwerb" statt „Erwerb-Scan").
    name = dateiname(jahr, kategorie or "Sonstiges", beschreibung,
                     endung, monat or erkannt_monat, betrag, kostenart)
    return {"name": name}


# --------------------------------------------------------------------------
# CCCLXXXVI: byte-exakte Duplikaterkennung
#
# Bevor ein Beleg hochgeladen wird, lässt sich fragen: liegt genau diese Datei
# (byte-identisch, per SHA1) schon in der Cloud? Zwei schlanke Endpunkte:
#   * `/duplikat-pruefen` schaut nur nach — rein lesend (PROPFIND).
#   * `/vorhandenen-zuordnen` legt für eine schon vorhandene Datei einen
#     Dokument-Eintrag an, ohne sie erneut hochzuladen (kein PUT/MOVE).
# Beide fassen die Nextcloud nie schreibend an; das Zuordnen ist reine
# Datenbank-Arbeit. Idempotent: derselbe Pfad ergibt denselben Eintrag.
# --------------------------------------------------------------------------

def _objekt_nach_slug(session: Session, slug: str, familie_id: int) -> Objekt:
    """N436 — der Slug gilt nur innerhalb der angemeldeten Familie; ein
    fremdes Objekt ist von einem nicht existierenden nicht zu unterscheiden
    (404 in beiden Fällen)."""
    o = session.exec(select(Objekt).where(
        Objekt.slug == slug, Objekt.familie_id == familie_id)).first()
    if not o:
        raise HTTPException(404, "Objekt nicht gefunden")
    return o


def _dokument_am_pfad(session: Session, pfad: str) -> Dokument | None:
    """Der Eintrag, der auf diesen Pfad zeigt — mit und ohne führenden Trenner
    gesucht, weil beide Schreibweisen im Bestand vorkommen können."""
    ohne = pfad.strip("/")
    return session.exec(select(Dokument).where(
        Dokument.pfad.in_((f"/{ohne}", ohne)))).first()


class DuplikatPruefung(BaseModel):
    objekt: str
    sha1: str
    name: str = ""
    jahr: int | None = None


@router.post("/duplikat-pruefen")
def duplikat_pruefen(data: DuplikatPruefung,
                     session: Session = Depends(get_session),
                     familie: Familie = Depends(aktuelle_familie)) -> dict:
    """Liegt eine byte-gleiche Datei (SHA1) schon in der Cloud? (CCCLXXXVI)

    Sucht im gesamten Objektbaum. `im_ziel_ordner` sagt, ob der Fund im
    erwarteten NK-Jahr-Ordner liegt oder anderswo im Baum; `schon_erfasst`, ob
    es zu ihm bereits einen Dokument-Eintrag gibt. Rein lesend — nichts wird
    angelegt. Ohne verknüpften Cloud-Ordner ein ehrlicher 409."""
    o = _objekt_nach_slug(session, data.objekt, familie.id)
    _cloud_pflicht(o)
    client = verbindung(session)
    # Wo ein NK-Beleg dieses Jahres landen würde — daran misst sich, ob der
    # Fund schon am richtigen Platz liegt.
    _sach, ziel_ordner = _ablageordner(session, o, "Nebenkosten", data.jahr,
                                        client)
    treffer = client.finde_nach_checksum(o.nc_ordner, data.sha1)
    if not treffer:
        return {"gefunden": False, "pfad": None, "dateiname": None,
                "im_ziel_ordner": False, "schon_erfasst": False,
                "dokument_id": None}
    pfad = _norm(treffer.pfad)
    im_ziel = _elternteil(pfad) == _norm(ziel_ordner)
    vorhanden = _dokument_am_pfad(session, pfad)
    return {"gefunden": True, "pfad": pfad, "dateiname": treffer.name,
            "im_ziel_ordner": im_ziel,
            "schon_erfasst": vorhanden is not None,
            "dokument_id": vorhanden.id if vorhanden else None}


class VorhandenerBeleg(BaseModel):
    objekt: str
    pfad: str
    kategorie: str = "Nebenkosten"
    beschreibung: str = ""
    # CCCXCII — Kostenart/Betrag mit, damit der zugeordnete Beleg über `verbuche`
    # gleich an seiner Kostenposition landet (position_id wird gesetzt).
    kostenart: str = ""
    betrag: float | None = None
    jahr: int | None = None
    zeitraum_id: int | None = None


@router.post("/vorhandenen-zuordnen")
def vorhandenen_zuordnen(data: VorhandenerBeleg,
                         session: Session = Depends(get_session),
                         familie: Familie = Depends(aktuelle_familie)) -> dict:
    """Legt für eine schon in der Cloud liegende Datei einen Dokument-Eintrag
    an — ohne erneuten Upload (CCCLXXXVI). Kein PUT/MOVE, reine Datenbank.

    Idempotent: gibt es zu diesem Pfad bereits einen Eintrag, wird er nicht
    verdoppelt. Fehlende Bezüge (Objekt, Kategorie, Zeitraum) werden dann nur
    additiv ergänzt — nichts Bestehendes überschrieben."""
    o = _objekt_nach_slug(session, data.objekt, familie.id)
    zeitraum_id = _pruefe_zeitraum(session, data.zeitraum_id)
    pfad = _norm(data.pfad)
    name = pfad.rstrip("/").split("/")[-1]

    vorhanden = _dokument_am_pfad(session, pfad)
    if vorhanden:
        if vorhanden.objekt_id is None:
            vorhanden.objekt_id = o.id
        if not vorhanden.kategorie and data.kategorie:
            vorhanden.kategorie = data.kategorie
        if vorhanden.zeitraum_id is None and zeitraum_id is not None:
            vorhanden.zeitraum_id = zeitraum_id
        if not vorhanden.kostenart and data.kostenart:
            vorhanden.kostenart = kostenart_normalisieren(data.kostenart)
        if vorhanden.betrag is None and data.betrag and data.betrag > 0:
            vorhanden.betrag = data.betrag
        # N14 — auch das Abrechnungsjahr additiv nachtragen: ohne es fiel der
        # Eintrag aus dem Jahresfilter und der Jahres-Facette, und der
        # Beleg-Abgleich meldete ihn als Grenzfall „kein_datum", statt ihn in
        # seinen Zeitraum zu schieben. Ein bereits gepflegtes Jahr bleibt.
        if vorhanden.jahr is None and data.jahr:
            vorhanden.jahr = data.jahr
        session.add(vorhanden)
        session.commit()
        session.refresh(vorhanden)
        return {"id": vorhanden.id, "dateiname": vorhanden.dateiname,
                "pfad": vorhanden.pfad, "abgelegt": True, "vorhanden": True}

    d = Dokument(pfad=pfad, dateiname=name, groesse=0, objekt_id=o.id,
                 kategorie=data.kategorie, zeitraum_id=zeitraum_id,
                 # N14 — das mitgeschickte Abrechnungsjahr wurde bislang
                 # verworfen; der Eintrag entstand ohne Jahr und war damit im
                 # Jahresfilter unsichtbar.
                 jahr=data.jahr,
                 kostenart=kostenart_normalisieren(data.kostenart),
                 betrag=data.betrag if data.betrag and data.betrag > 0 else None,
                 status="zugeordnet", erkannt_am=date.today())
    session.add(d)
    try:
        session.commit()
    except IntegrityError as e:
        raise _pfad_konflikt(session, pfad) from e
    session.refresh(d)
    log.info("Vorhandener Beleg zugeordnet: %s", d.pfad)
    return {"id": d.id, "dateiname": d.dateiname, "pfad": d.pfad,
            "abgelegt": True, "vorhanden": True}


# --------------------------------------------------------------------------
# CCCXXVI: Lageplan je Einheit
#
# Ein Lageplan (Foto oder PDF) gehört zu einer Einheit und wird später unter
# ihr angezeigt. Er braucht kein eigenes Modell: es ist ein ganz normaler
# `Dokument`, der über die vorhandenen Info-Felder an die Einheit gehängt wird
# (`info_zu_typ="einheit"`, `info_zu_id=<Einheit.id>`) und über `kategorie=
# "Lageplan"` als solcher markiert ist. Die Datei landet — wie jeder Scan —
# im Objektordner der zugehörigen Immobilie (99_Sonstiges), über dieselbe
# Ablagelogik (`_ablageordner`/`_ordner_sichern`/`_freier_name`/`lege_ab`).
#
# Der eigentliche Inhalt/die Vorschau läuft über die bestehenden Endpunkte
# `/api/dokumente/{id}/vorschau|inhalt|seiten` — hier wird nur aufgenommen und
# aufgelistet.
#
# Wohnt an einem eigenen Router mit Präfix `/einheiten`, den `objekte.py` (das
# den `/api`-Router hält) einhängt — so entsteht `/api/einheiten/{id}/…`, ohne
# dass die Ablagelogik doppelt geschrieben werden muss.
# --------------------------------------------------------------------------

lageplan_router = APIRouter(prefix="/einheiten", tags=["lageplan"])


def _einheit_holen(session: Session, einheit_id: int) -> Einheit:
    e = session.get(Einheit, einheit_id)
    if not e:
        raise HTTPException(404, "Einheit nicht gefunden")
    return e


def lageplaene_der_einheit(session: Session, einheit_id: int) -> list[dict]:
    """Die Lagepläne einer Einheit als [{id, dateiname, pfad}] (CCCXXVI).

    Eine Wahrheit für den Listen-Endpunkt und für `_einheit_zeile` in
    `objekte.py`. Defensiv: leere Liste, wenn keine da sind."""
    treffer = session.exec(
        select(Dokument).where(
            Dokument.info_zu_typ == "einheit",
            Dokument.info_zu_id == einheit_id,
            Dokument.kategorie == LAGEPLAN)).all()
    return [{"id": d.id, "dateiname": d.dateiname, "pfad": d.pfad} for d in treffer]


@lageplan_router.post("/{einheit_id}/lageplan", status_code=201)
async def lageplan_hochladen(einheit_id: int,
                             datei: UploadFile = File(...),
                             bezeichnung: str = Form(""),
                             session: Session = Depends(get_session)) -> dict:
    """Hinterlegt einen Lageplan (Foto/PDF) zu einer Einheit (CCCXXVI).

    Die Datei wandert in den Objektordner der zugehörigen Immobilie — über
    dieselbe Ablagelogik wie ein Scan (Bezeichnung, freier Name, MKCOL/PUT).
    Der Eintrag hängt über `info_zu_*` an der Einheit und trägt
    `kategorie="Lageplan"`. Ohne verknüpften Nextcloud-Ordner gibt es einen
    ehrlichen 409 statt eines 500 — wie bei den anderen Upload-Endpunkten."""
    e = _einheit_holen(session, einheit_id)
    o = session.get(Objekt, e.objekt_id)
    if not o:
        raise HTTPException(404, "Zur Einheit gehört keine Immobilie")
    _cloud_pflicht(o)

    inhalt = await upload.lies(datei, was="Der Beleg")

    # Die Endung der hochgeladenen Datei erhalten — ein Foto darf nicht als
    # „.pdf" abgelegt werden. Ohne Endung bleibt es beim PDF.
    endung = _endung(datei.filename or "") or ".pdf"
    # N9 — sauberer Name OHNE „ohne-Jahr_"-Präfix und ohne Datum: ein Lageplan
    # hat kein Belegjahr. Name = „Lageplan <Einheit>[ - <Zusatztitel>]"; der
    # Zusatztitel (z. B. „Bad") kommt beim Erstellen direkt mit und steht so im
    # Dateinamen wie im Anzeigenamen.
    tag = (bezeichnung or "").strip()
    roh = f"Lageplan {e.bezeichnung}" + (f" - {tag}" if tag else "")
    name = _saubere_datei(roh) + endung
    client = verbindung(session)
    try:
        # N9 — in den Fotos-/Lage-Ordner (10_Fotos_Lage) statt 99_Sonstiges.
        sach, ziel_ordner = _ablageordner(session, o, "Lageplan", None, client)
        _ordner_sichern(client, sach, ziel_ordner)
        name = _freier_name(session, client, ziel_ordner, name)
        client.lege_ab(f"{ziel_ordner}/{name}", inhalt)
    except NextcloudFehler as fehler:
        raise HTTPException(400, str(fehler)) from fehler

    d = Dokument(pfad=f"/{ziel_ordner}/{name}", dateiname=name,
                 groesse=len(inhalt), objekt_id=o.id, kategorie=LAGEPLAN,
                 info_zu_typ="einheit", info_zu_id=e.id,
                 status="zugeordnet", erkannt_am=date.today())
    session.add(d)
    try:
        session.commit()
    except IntegrityError as fehler:
        raise _pfad_konflikt(session, f"/{ziel_ordner}/{name}") from fehler
    session.refresh(d)
    log.info("Lageplan abgelegt: %s (Einheit %s)", d.pfad, e.id)
    return {"id": d.id, "dateiname": name, "pfad": d.pfad,
            "einheit_id": e.id, "objekt": o.slug}


@lageplan_router.get("/{einheit_id}/lageplaene")
def lageplaene_liste(einheit_id: int,
                     session: Session = Depends(get_session)) -> list[dict]:
    """Die Lagepläne einer Einheit — [{id, dateiname}] (CCCXXVI).

    Die Vorschau/der Inhalt läuft über die bestehenden Dokument-Endpunkte
    (`/api/dokumente/{id}/vorschau|inhalt|seiten`)."""
    _einheit_holen(session, einheit_id)
    return lageplaene_der_einheit(session, einheit_id)


def _lageplan_holen(session: Session, einheit_id: int, dokument_id: int,
                    familie: Familie) -> Dokument:
    """Der Lageplan-Datensatz einer Einheit — oder 404 (CCCLXXXI).

    Trifft nur einen echten Lageplan (`kategorie="Lageplan"`), der auch wirklich
    an genau dieser Einheit hängt. So kann ein Aufruf über die falsche Einheit —
    oder auf einen fremden Beleg — nichts anrichten.

    N436 — der Dokument-Zugriff läuft über `dokument_holen`, das zusätzlich
    prüft, dass der Beleg zu einem Objekt der angemeldeten Familie gehört."""
    _einheit_holen(session, einheit_id)
    d = dokument_holen(dokument_id, session, familie)
    if (d.kategorie != LAGEPLAN or d.info_zu_typ != "einheit"
            or d.info_zu_id != einheit_id):
        raise HTTPException(404, "Lageplan nicht gefunden")
    return d


class LageplanNameIn(BaseModel):
    """Der neue Anzeigename eines Lageplans (CCCLXXXI)."""
    name: str


@lageplan_router.patch("/{einheit_id}/lageplan/{dokument_id}")
def lageplan_umbenennen(einheit_id: int, dokument_id: int,
                        data: LageplanNameIn,
                        session: Session = Depends(get_session),
                        familie: Familie = Depends(aktuelle_familie)) -> dict:
    """Gibt einem Lageplan einen Anzeigenamen (CCCLXXXI).

    Bewusst nur der Name am Datensatz: die Datei in der Nextcloud wird NICHT
    berührt und NICHT verschoben. Das ist der sichere Weg — sie liegt weiter
    unter `pfad`, über den die App sie immer holt (Ansehen, Vorschau, Abgleich),
    und der Abgleich findet sie dort per Pfad wieder und lässt den Anzeigenamen
    stehen. Die Endung bleibt erhalten, damit Vorschau und Download den Dateityp
    weiter erkennen."""
    d = _lageplan_holen(session, einheit_id, dokument_id, familie)
    name = (data.name or "").strip()
    if not name:
        raise HTTPException(400, "Bitte einen Namen angeben")
    endung = _endung(d.dateiname)
    if endung and not name.lower().endswith(endung.lower()):
        name += endung
    d.dateiname = name
    session.add(d)
    session.commit()
    session.refresh(d)
    log.info("Lageplan umbenannt: %s (Einheit %s, Datei unberührt)",
             d.id, einheit_id)
    return {"id": d.id, "dateiname": d.dateiname}


@lageplan_router.delete("/{einheit_id}/lageplan/{dokument_id}")
def lageplan_entfernen(einheit_id: int, dokument_id: int,
                       session: Session = Depends(get_session),
                       familie: Familie = Depends(aktuelle_familie)) -> dict:
    """Nimmt einen Lageplan aus der App (CCCLXXXI).

    Entfernt ausschließlich den Datensatz. Die Datei in der Nextcloud bleibt
    unangetastet — dort wird grundsätzlich nichts gelöscht. Der Aufruf fasst die
    Cloud gar nicht erst an (kein Client, kein DELETE, kein MOVE)."""
    d = _lageplan_holen(session, einheit_id, dokument_id, familie)
    pfad = d.pfad
    session.delete(d)
    session.commit()
    log.info("Lageplan-Eintrag entfernt: %s (Datei bleibt in der Cloud)", pfad)
    return {"ok": True, "pfad": pfad, "datei_bleibt": True,
            "hinweis": "Der Eintrag ist weg, die Datei liegt weiter in der "
                       "Nextcloud."}


# --------------------------------------------------------------------------
# Kontrolle: ändern, verschieben, ersetzen, entfernen
# --------------------------------------------------------------------------

class AenderungIn(BaseModel):
    """Alles, was sich an einem Dokument ändern lässt. Was nicht mitkommt,
    bleibt wie es war — ein Endpunkt für Zuordnen und Korrigieren.

    Ohne Schalter „nur umbenennen": der Name in der Datenbank ist der Name in
    der Cloud. Beides auseinanderlaufen zu lassen hieße, einen Beleg zu
    verlieren, den die App als abgelegt führt."""
    objekt: str | None = None
    kategorie: str | None = None
    # Die genaue Position innerhalb der Art (CLXXI): „Kaminkehrer" statt nur
    # „Nebenkosten". Sie steht nicht im Dateinamen — der Ordner sagt die Art,
    # die Bezeichnung sagt die Sache; ein drittes Mal wäre eins zu viel.
    kostenart: str | None = None
    jahr: int | None = None
    # Belegmonat — steht mit im Dateinamen, sobald er bekannt ist (CXXIII).
    monat: int | None = None
    # Das Rechnungsdatum, tagesgenau (CLXXII). Kommt es mit, gelten Jahr und
    # Monat daraus, sofern nicht ausdrücklich eigene mitgeschickt werden.
    belegdatum: date | None = None
    # Der Dateiname entsteht immer aus Datum, Bezeichnung und Betrag — eine
    # Regel für die ganze Ablage. Umbenannt wird über die Bezeichnung.
    beschreibung: str | None = None
    # Der Rechnungsbetrag. Er wandert an das Ende des Dateinamens (CXXIII) —
    # dort sieht ihn der Nutzer im Ordner — und wird zusätzlich am Dokument
    # gespeichert (CLXXXI): aus ihm wird die Kostenposition, und dafür ist ein
    # Name, der bei jeder Korrektur neu zusammengesetzt wird, zu wackelig.
    betrag: float | None = None
    # Zu welcher Abrechnung der Beleg gehört. Mitgeschickt heißt gesetzt,
    # `null` heißt gelöst.
    zeitraum_id: int | None = None


@router.patch("/{dokument_id}")
def aendern(dokument_id: int, data: AenderungIn,
            session: Session = Depends(get_session),
            familie: Familie = Depends(aktuelle_familie)) -> dict:
    """Ordnet zu oder korrigiert: andere Immobilie, andere Art, andere
    Kostenposition, anderes Belegdatum, anderer Name — die Datei wandert in der
    Nextcloud mit.

    N436 — `d` kommt über `dokument_holen` (404 bei fremdem Beleg); ein
    Umhängen per `data.objekt` ist zusätzlich auf die Objekte der angemeldeten
    Familie eingegrenzt, sonst liesse sich ein Beleg auf ein fremdes Objekt
    umhängen."""
    d = dokument_holen(dokument_id, session, familie)
    gesetzt = data.model_fields_set

    if data.objekt:
        o = session.exec(select(Objekt).where(
            Objekt.slug == data.objekt, Objekt.familie_id == familie.id)).first()
        if not o:
            raise HTTPException(404, "Objekt nicht gefunden")
    else:
        o = session.get(Objekt, d.objekt_id) if d.objekt_id else None
        if not o:
            raise HTTPException(400, "Bitte die Immobilie angeben")

    kategorie = data.kategorie or d.kategorie or "Sonstiges"
    # Die Kostenposition steht im Namen (CLXXI): „NK-Schornsteinfeger" statt
    # „Rechnung". Kommt sie nicht mit, gilt die bisherige.
    kostenart = data.kostenart if "kostenart" in gesetzt else d.kostenart
    jahr = data.jahr if "jahr" in gesetzt else d.jahr
    endung = _endung(d.dateiname)
    # Vor dem ersten MOVE prüfen: was hier scheitert, soll die Datei in der
    # Cloud noch nicht bewegt haben.
    zeitraum_id = (_pruefe_zeitraum(session, data.zeitraum_id)
                   if "zeitraum_id" in gesetzt else d.zeitraum_id)

    # Was nicht mitkommt, wird aus dem bestehenden Namen zurückgelesen. Ohne
    # das verlöre eine Korrektur am Jahr die Bezeichnung und den Betrag —
    # beide stehen nur im Namen.
    alt_jahr, alt_monat = datum_aus_namen(d.dateiname)
    monat = data.monat if "monat" in gesetzt else alt_monat
    # N26 — Betrag aus dem Namen, aber der am Beleg gespeicherte Betrag ist der
    # Rückfall: ein Jahreswechsel darf die Summe nicht verlieren, nur weil der
    # Dateiname (noch) keinen Betrag trägt.
    betrag = (data.betrag if "betrag" in gesetzt
              else (betrag_aus_namen(d.dateiname) or d.betrag))
    beschreibung = (data.beschreibung if "beschreibung" in gesetzt
                    else _bezeichnung(d.dateiname))
    if jahr is None and "jahr" not in gesetzt:
        jahr = alt_jahr

    # CLXXII: das Belegdatum ist die genauere Angabe. Wo Jahr und Monat nicht
    # ausdrücklich mitkommen, gilt der Tag, der auf der Rechnung steht.
    belegdatum = data.belegdatum if "belegdatum" in gesetzt else d.belegdatum
    if belegdatum:
        if "jahr" not in gesetzt:
            jahr = belegdatum.year
        if "monat" not in gesetzt:
            monat = belegdatum.month

    if {"kategorie", "jahr", "monat", "betrag", "belegdatum",
            "beschreibung", "objekt"} & gesetzt:
        name = dateiname(jahr, kategorie, beschreibung or "", endung,
                         monat, betrag, kostenart)
    else:
        name = d.dateiname

    # Die Datei wandert immer mit. Ein Eintrag, dessen Name nur in der
    # Datenbank wechselt, wäre in der Cloud nicht mehr zu finden — und stünde
    # trotzdem als „zugeordnet" da.
    _cloud_pflicht(o)
    if _ist_grabstein(d.pfad):
        # N248 — hier wissen wir es genau: die Datei wurde in der Nextcloud
        # gelöscht. Das gehört gesagt, statt es als „gibt es keine Datei"
        # abzutun.
        raise HTTPException(409, "Diese Datei liegt nicht mehr in der Nextcloud "
                                 "— sie wurde dort gelöscht. Bitte den Beleg "
                                 "neu einscannen.")
    if not d.pfad.startswith("/"):
        # Eintrag ohne Datei in der Cloud: Ehrlichkeit vor Erfolgsmeldung.
        raise HTTPException(409, "Zu diesem Eintrag gibt es keine Datei in der "
                                 "Cloud — bitte neu einscannen oder entfernen.")
    if d.status == VERMISST:
        # CXXVII: der Abgleich hat die Datei nicht mehr gefunden. Ein MOVE
        # liefe ins Leere und der Eintrag hiesse danach „zugeordnet".
        raise HTTPException(409, "Diese Datei liegt nicht mehr in der Nextcloud "
                                 "— bitte den Ordner neu einlesen, den Beleg "
                                 "neu einscannen oder den Eintrag entfernen.")
    try:
        neuer_pfad, name = _einsortieren(session, d, o, kategorie, name,
                                         jahr=jahr)
    except NextcloudFehler as e:
        raise HTTPException(400, str(e)) from e
    verschoben = neuer_pfad != d.pfad
    d.pfad = neuer_pfad
    kidb.pfad_nachziehen(session, d)   # N299

    d.objekt_id = o.id
    d.kategorie = kategorie
    if "kostenart" in gesetzt:
        d.kostenart = kostenart_normalisieren(data.kostenart)
    d.jahr = jahr
    d.belegdatum = belegdatum
    # CLXXXI: der Betrag steht ab hier auch am Beleg, nicht nur im Namen.
    d.betrag = betrag if betrag and betrag > 0 else None
    d.dateiname = name
    d.status = "zugeordnet"
    # N26 — ändert sich das Jahr/Belegdatum und ist kein Zeitraum ausdrücklich
    # genannt, wandert der Beleg in den Abrechnungszeitraum des NEUEN Jahres
    # (vorhandener oder neu angelegter, nach dem Turnus des Objekts). Ohne das
    # blieb die Kostenposition im alten Jahr hängen, obwohl die Datei längst ins
    # richtige Jahr verschoben war.
    if "zeitraum_id" not in gesetzt and ({"jahr", "belegdatum"} & gesetzt):
        if "jahr" in gesetzt and jahr:
            # Ein AUSDRÜCKLICH gesetztes Jahr (das Abrechnungsjahr) hat Vorrang
            # vor dem Belegdatum — das ist das Rechnungsdatum, und der
            # abgerechnete Zeitraum kann davon abweichen (N14). Zeitraum nach der
            # Turnus-Regel des Objekts finden oder anlegen.
            from .objekte import _zeitraum_grenzen
            start_z, ende_z = _zeitraum_grenzen(o, jahr)
            ziel = next((z for z in session.exec(select(Zeitraum).where(
                Zeitraum.objekt_id == o.id)).all()
                if z.start == start_z and z.ende == ende_z), None)
            if ziel is None:
                ziel = Zeitraum(objekt_id=o.id, start=start_z, ende=ende_z,
                                typ="regulär", status="in Arbeit")
                session.add(ziel)
                session.flush()
        else:
            ziel = _zeitraum_fuer_beleg(session, o, d)
        if ziel is not None:
            zeitraum_id = ziel.id
    alt_position_id = d.position_id
    d.zeitraum_id = zeitraum_id
    session.add(d)
    # N26 — war der Beleg verbucht und wechselt er den Abrechnungszeitraum, zieht
    # die KOSTENPOSITION mit: im alten Jahr gelöst, im neuen neu gebildet. Andere
    # Belege der alten Position (z. B. ein SEPA-Mandat ohne Kosten) bleiben
    # unberührt. Ohne Zeitraumwechsel bleibt es beim ehrlichen Nachziehen (die
    # Summe darf bei geändertem Betrag/Kostenart nicht falsch stehenbleiben).
    alt_pos = (session.get(Kostenposition, alt_position_id)
               if alt_position_id else None)
    if alt_pos is not None and alt_pos.zeitraum_id != zeitraum_id:
        belegposten.loese(session, d)              # Kosten aus dem alten Jahr nehmen
        if d.betrag and (d.kostenart or "").strip():
            try:
                belegposten.verbuche(session, d)   # im neuen Jahr neu verbuchen
                buchung = "verschoben"
            except BelegFehler:
                buchung = "geloest"
        else:
            buchung = "geloest"
    else:
        buchung = belegposten.nachziehen(session, d)
    try:
        session.commit()
    except IntegrityError as e:
        raise _pfad_konflikt(session, neuer_pfad) from e
    return {"ok": True, "id": d.id, "pfad": d.pfad, "dateiname": d.dateiname,
            "objekt": o.slug, "kategorie": kategorie, "jahr": jahr,
            "kostenart": d.kostenart, "betrag": d.betrag,
            "belegdatum": d.belegdatum.isoformat() if d.belegdatum else None,
            "zeitraum_id": d.zeitraum_id, "verschoben": verschoben,
            "position_id": d.position_id, "buchung": buchung}


# --------------------------------------------------------------------------
# Aus dem Beleg wird eine Kostenposition (CLXXX)
#
# Bewusst ein eigener, sichtbarer Schritt und keine Automatik beim
# „Übernehmen": Einsortieren und Abrechnen sind zwei Entscheidungen. Ein Beleg
# darf am richtigen Platz liegen, ohne dass er schon in der Abrechnung steht —
# eine Rechnung, die noch geprüft wird, ein Doppel, ein Beleg fürs Archiv. Und
# weil ein zweiter Beleg den Betrag der vorhandenen Position erhöht (CLXXXII),
# ist das eine Rechnung, die man vorher sehen will. Der `GET` zeigt sie, der
# `POST` führt sie aus.
# --------------------------------------------------------------------------

def _beleg(session: Session, dokument_id: int, familie: Familie) -> Dokument:
    """N436 — dünner Wrapper um `dokument_holen`: 404 auch bei einem Beleg
    einer fremden Familie."""
    return dokument_holen(dokument_id, session, familie)


def _an_anbieter_position_angleichen(session: Session, d: Dokument) -> None:
    """N37: Ein Beleg soll auf der spezifischen Kostenposition landen, die
    seinen Anbieter führt — nicht auf einer zweiten, generischen daneben.

    Der gemeldete Fall (Laufer Str. 5 · 2026): der Anbieter „WWK" hing an der
    Position „Gebäudeversicherung", der Beleg trug aber die generische Kostenart
    „Versicherung" und legte dadurch eine zweite Position an. Hier bekommt der
    Beleg die spezifische Kostenart, sodass `verbuche` ihn in die vorhandene
    Position einrechnet, statt eine generische zu erzeugen.

    Streng doppelt abgesichert, damit keine Verbuchung kaputtgeht und nie
    geraten wird — rein additiv, legt nichts an, löscht nichts:

    * Der Beleg ist noch in keine Position eingerechnet, und für seine eigene
      Kostenart gibt es in diesem Zeitraum noch keine Position (sonst wäre die
      Zuordnung schon eindeutig und würde hier nur gestört).
    * Der Beleg nennt einen Anbieter.
    * Es gibt GENAU EINE vorhandene Position, deren Katalog-Kostenart denselben
      Anbieter (`Kostenart.lieferant`) trägt. Bei mehreren wird nicht geraten.
    * Diese Kostenart ist eine Spezialisierung der Beleg-Kostenart
      (`Versicherung` ⊂ `Gebäudeversicherung`) — oder der Beleg trägt noch gar
      keine. So kann ein fremder Anbieter-Zufallstreffer keinen „Müll"-Beleg auf
      eine Versicherungszeile umhängen."""
    if not d.zeitraum_id or d.position_id:
        return
    if belegposten.finde(session, d.zeitraum_id, d.kostenart) is not None:
        return
    anbieter = _fold_kostenart(_beleg_anbieter(d))
    if not anbieter:
        return
    z = session.get(Zeitraum, d.zeitraum_id)
    if z is None:
        return
    # Kostenarten des Objekts, deren Anbieter (Lieferant) zum Beleg passt.
    passende = {k.name for k in session.exec(select(Kostenart).where(
        Kostenart.objekt_id == z.objekt_id)).all()
        if k.lieferant and _fold_kostenart(k.lieferant) == anbieter}
    if not passende:
        return
    # ... und davon die, für die es in diesem Zeitraum schon eine Position gibt.
    treffer = [p for p in session.exec(select(Kostenposition).where(
        Kostenposition.zeitraum_id == d.zeitraum_id)).all()
        if p.kostenart in passende]
    if len(treffer) != 1:
        return
    ziel = (treffer[0].kostenart or "").strip()
    eigen = _fold_kostenart(d.kostenart)
    # Spezialisierung: die Ziel-Kostenart enthält die generische des Belegs
    # (oder der Beleg trägt noch keine). Nie in die andere Richtung.
    if ziel == (d.kostenart or "").strip() or (eigen and eigen not in _fold_kostenart(ziel)):
        return
    log.info("Beleg %s über Anbieter auf Kostenart „%s“ ausgerichtet (statt „%s“)",
             d.id, ziel, d.kostenart or "—")
    d.kostenart = ziel
    session.add(d)


@router.get("/{dokument_id}/position")
def position_vorschau(dokument_id: int,
                      session: Session = Depends(get_session),
                      familie: Familie = Depends(aktuelle_familie)) -> dict:
    """Was aus diesem Beleg würde. Ändert nichts.

    Fehlt eine der drei Angaben (Kostenposition, Zeitraum, Betrag), steht hier
    `moeglich: false` samt Grund — die Oberfläche sagt dann, was noch fehlt,
    statt einen Knopf anzubieten, der scheitert."""
    d = _beleg(session, dokument_id, familie)
    # N37 — dieselbe Anbieter-Ausrichtung wie beim Übernehmen, damit die
    # Vorschau zeigt, wo der Beleg wirklich landet. Der GET committet nicht;
    # die Angleichung bleibt in dieser Anfrage und wird nicht gespeichert.
    _an_anbieter_position_angleichen(session, d)
    try:
        return {"moeglich": True, **belegposten.vorschau(session, d).als_dict()}
    except BelegFehler as fehler:
        return {"moeglich": False, "grund": str(fehler),
                "kostenart": d.kostenart, "zeitraum_id": d.zeitraum_id,
                "betrag": d.betrag, "position_id": d.position_id}


@router.post("/{dokument_id}/position", status_code=201)
def position_uebernehmen(dokument_id: int,
                         session: Session = Depends(get_session),
                         familie: Familie = Depends(aktuelle_familie)) -> dict:
    """Rechnet den Beleg in seine Kostenposition ein — und legt sie an, wenn es
    sie noch nicht gibt.

    Zweimal geklickt bleibt es bei derselben Summe: gerechnet wird aus allen
    verknüpften Belegen, nie durch Draufrechnen."""
    d = _beleg(session, dokument_id, familie)
    # N37 — vor dem Verbuchen den Beleg über seinen Anbieter auf die vorhandene
    # spezifische Position ausrichten, statt eine zweite generische zu erzeugen.
    _an_anbieter_position_angleichen(session, d)
    try:
        ergebnis = belegposten.verbuche(session, d)
    except BelegFehler as fehler:
        raise HTTPException(400, str(fehler)) from fehler
    except UnbekannterSchluessel as fehler:
        raise HTTPException(400, str(fehler)) from fehler
    session.commit()
    return {"ok": True, **ergebnis.als_dict()}


@router.delete("/{dokument_id}/position")
def position_loesen(dokument_id: int,
                    session: Session = Depends(get_session),
                    familie: Familie = Depends(aktuelle_familie)) -> dict:
    """Nimmt den Beleg wieder aus seiner Kostenposition heraus.

    Die Position bleibt stehen — ihr Betrag schrumpft um das, was dieser Beleg
    beigesteuert hat. Am Beleg selbst ändert sich nichts, die Datei bleibt, wo
    sie liegt."""
    d = _beleg(session, dokument_id, familie)
    if not d.position_id:
        raise HTTPException(409, "Dieser Beleg ist in keine Kostenposition "
                                 "eingerechnet.")
    p = belegposten.loese(session, d)
    session.commit()
    return {"ok": True, "position_id": p.id if p else None,
            "kostenart": p.kostenart if p else "",
            "betrag": p.betrag if p else None}


# --------------------------------------------------------------------------
# Einen Beleg zuordnen (CCLXXVIII/CCCIX/CCCXI)
#
# Zwei Wege: entweder entsteht aus dem KI-Raster ein neuer vorläufiger
# (oranger) Datensatz — die Baupläne dafür stehen in
# `app/dokumente/entwuerfe.py` —, oder der Beleg wird an einen bereits
# vorhandenen Eintrag gehängt (`_eintrag_holen`). Was dabei entsteht, ist immer
# neu und nie überschrieben.
# --------------------------------------------------------------------------

class ZuordnenIn(BaseModel):
    """Wohin ein Beleg gehört — alles freiwillig (CCCIX/CCCX/CCCXI).

    Ohne Body bleibt es beim alten Weg: die Kategorie bestimmt den Bauplan."""
    # Rubrik statt Kategorie: 'notarvertraege' | 'zahlungen' | 'kredite' |
    # 'versicherungen' | 'mieten' | 'nebenkosten'
    ziel: Optional[str] = ""
    # 'position' = ein Datensatz entsteht · 'beleg' = nur ein Info-Beleg
    art: Optional[str] = "position"
    # bestehender Eintrag: 'notarvertrag' | 'zahlung' | 'kredit' |
    # 'versicherung' | 'miete' | 'kostenposition' | 'objekt' | null
    an_typ: Optional[str] = ""
    an_id: Optional[int] = None


@router.post("/{dokument_id}/zuordnen")
def zuordnen(dokument_id: int, data: Optional[ZuordnenIn] = None,
             session: Session = Depends(get_session),
             familie: Familie = Depends(aktuelle_familie)) -> dict:
    """Legt aus dem Beleg einen vorläufigen (orange) Datensatz an (CCLXXVIII).

    Aus der Kategorie ergibt sich, was entsteht: Nebenkosten → Kostenposition,
    Mietvertrag → Miete (+ Bewohner), Versicherung → Versicherung, Kredit →
    Kredit. Andere Kategorien legen nichts an (`angelegt: []`). Alle Datensätze
    tragen `vorlaeufig=True` und `quelle_dokument_id`; idempotent — ein zweiter
    Aufruf findet den vorhandenen Entwurf wieder, statt einen zweiten zu bauen.

    Der Body ist freiwillig; ohne ihn bleibt alles wie bisher (CCCIX):

    * `ziel` schlägt die Kategorie — ein Beleg unter „Sonstiges" lässt sich so
      bewusst als Notarvertrag anlegen.
    * `art: "beleg"` legt gar keinen Datensatz an: der Beleg hängt nur als
      Info an einem Eintrag — oder, ohne `an_*`, an der Immobilie (CCCX).
    * `an_typ`/`an_id` hängen den Beleg an einen **bestehenden** Eintrag,
      statt einen zweiten daneben zu bauen (CCCXI).

    Datensicher: nichts wird überschrieben, nur Neues additiv angelegt. Fehlt
    das Objekt, wird das ehrlich gemeldet statt in einen 500 zu laufen."""
    d = dokument_holen(dokument_id, session, familie)
    o = session.get(Objekt, d.objekt_id) if d.objekt_id else None
    if not o:
        return {"ok": False, "angelegt": [],
                "grund": "Dem Beleg fehlt die Immobilie — bitte zuerst zuordnen."}

    wahl = data or ZuordnenIn()
    ziel = (wahl.ziel or "").strip().lower()
    art = (wahl.art or "position").strip().lower()
    an_typ = (wahl.an_typ or "").strip().lower()
    an_id = wahl.an_id
    # „objekt" (und ein leer übergebenes null) meint: an keinem einzelnen
    # Eintrag, sondern an der Immobilie selbst.
    if an_typ in ("objekt", "null", "none"):
        an_typ, an_id = "", None

    eintrag = _eintrag_holen(session, an_typ, an_id, o)[0] if an_typ else None

    # ---- Info-Beleg: kein Datensatz, nur ein Hinweis am Eintrag (CCCX) -----
    if art == "beleg":
        d.info_zu_typ = an_typ or "objekt"
        d.info_zu_id = an_id if an_typ else o.id
        woran = _eintrag_wo(eintrag) if eintrag else (o.name or o.slug)
        session.add(d)
        session.commit()
        log.info("Dokument %s hängt als Info-Beleg an %s#%s", dokument_id,
                 d.info_zu_typ, d.info_zu_id)
        return {"ok": True, "info": True,
                "angelegt": [{"typ": "Beleg", "id": d.id, "objekt": o.slug,
                              "wo": woran}]}

    # ---- an einen bestehenden Eintrag hängen, statt einen neuen zu bauen ---
    if eintrag is not None:
        d.info_zu_typ, d.info_zu_id = an_typ, an_id
        session.add(d)
        # Kennt der Eintrag noch keinen Quellbeleg, wird dieser es. Ein
        # vorhandener Verweis bleibt unangetastet — nie überschreiben.
        if getattr(eintrag, "quelle_dokument_id", None) is None:
            eintrag.quelle_dokument_id = d.id
            session.add(eintrag)
        session.commit()
        log.info("Dokument %s an bestehenden %s#%s gehängt", dokument_id,
                 an_typ, an_id)
        return {"ok": True,
                "angelegt": [{"typ": type(eintrag).__name__, "id": eintrag.id,
                              "objekt": o.slug, "wo": _eintrag_wo(eintrag)}]}

    # ---- neuer vorläufiger Datensatz: Rubrik schlägt Kategorie (CCCIX) -----
    if ziel:
        bauer = _ZIEL_BAUER.get(ziel)
        if not bauer:
            raise HTTPException(400, f"Unbekanntes Ziel „{wahl.ziel}“")
    else:
        bauer = _ENTWURF_BAUER.get((d.kategorie or "").strip())
    if not bauer:
        return {"ok": True, "angelegt": [],
                "grund": f"Für die Kategorie „{d.kategorie or 'unbekannt'}“ "
                         f"wird kein Datensatz angelegt."}
    try:
        angelegt = bauer(session, d, o, d.ki_felder or {})
        session.commit()
    except HTTPException:
        # N376 — eine HTTPException ist bereits eine beantwortete Frage: der
        # Entwurfs-Bauer sagt mit 404/409 genau, was fehlt oder kollidiert.
        # Sie in eine generische 400 („konnte nicht angelegt werden") zu
        # verwandeln nahm dem Nutzer den einzigen Hinweis, den er hatte.
        session.rollback()
        raise
    except Exception as fehler:                       # noqa: BLE001
        session.rollback()
        log.warning("Zuordnen von Dokument %s gescheitert: %s", dokument_id, fehler)
        raise HTTPException(
            400, f"Der vorläufige Datensatz konnte nicht angelegt werden: "
                 f"{fehler}") from fehler
    log.info("Dokument %s zugeordnet: %s", dokument_id,
             ", ".join(f"{e['typ']}#{e['id']}" for e in angelegt) or "nichts")
    return {"ok": True, "angelegt": angelegt}


@router.post("/{dokument_id}/loese-zuordnung")
def loese_zuordnung(dokument_id: int,
                    session: Session = Depends(get_session),
                    familie: Familie = Depends(aktuelle_familie)) -> dict:
    """Nimmt die Zuordnung eines Belegs zurück (CCCXXI — Umhängen).

    Löst die Info-Verknüpfung (`info_zu_*`) und löscht die aus diesem Beleg
    entstandenen VORLÄUFIGEN (orange) Datensätze wieder. Ein bereits bestätigter
    Datensatz bleibt unangetastet — er ist gewollter Bestand; dann wird nur die
    Info-Verknüpfung gelöst. Danach lässt sich der Beleg neu zuordnen."""
    d = dokument_holen(dokument_id, session, familie)
    geloest = []
    # Info-Verknüpfung lösen.
    if d.info_zu_typ:
        d.info_zu_typ, d.info_zu_id = "", None
        session.add(d)
        geloest.append("Info-Verknüpfung")
    # Vorläufige Entwürfe dieses Belegs entfernen; bestätigte bleiben stehen.
    for e in _entwuerfe_des_belegs(session, d.id):
        session.delete(e)
        geloest.append(type(e).__name__)
    # Ein in eine Kostenposition eingerechneter Beleg wird herausgelöst.
    if d.position_id:
        belegposten.loese(session, d)
        geloest.append("Kostenposition")
    session.commit()
    log.info("Zuordnung von Dokument %s gelöst: %s", dokument_id,
             ", ".join(geloest) or "nichts")
    return {"ok": True, "geloest": geloest}


class DuplikatEntfernenIn(BaseModel):
    """N16b — welches byte-gleiche Dokument erhalten bleibt."""
    behalten_id: int
    # N97 — zwei Scans DERSELBEN Unterlage sind nie byte-gleich. Hat der Nutzer
    # sie verglichen und als Doppel bestätigt, darf er das Duplikat trotzdem
    # entfernen: die Datei wird dann nicht gelöscht, sondern nach „99_Duplikate"
    # verschoben (nie Daten verlieren) und aus der Abrechnung genommen.
    bestaetigt: bool = False


@router.post("/{dokument_id}/duplikat-entfernen")
def duplikat_entfernen(dokument_id: int, data: DuplikatEntfernenIn,
                       session: Session = Depends(get_session),
                       familie: Familie = Depends(aktuelle_familie)) -> dict:
    """N16b — ein Dokument NUR entfernen, wenn es byte-gleich zu einem anderen
    ist, das ERHALTEN bleibt (`behalten_id`).

    Die Byte-Gleichheit wird durch Herunterladen und SHA1-Vergleich beider
    Dateien bewiesen — nie wird eine einzigartige Datei gelöscht (der Grundsatz
    „nie Daten verlieren" bleibt gewahrt, es geht nur eine identische Kopie).
    Entfernt Datei, `.immocalc`-Sidecar und den DB-Eintrag; eine Verbuchung wird
    vorher gelöst (die erhaltene Kopie trägt die Kosten weiter).

    N436 — beide Belege (`dokument_id` UND `behalten_id`) kommen über
    `dokument_holen`: ein Duplikat liesse sich sonst auch über einen Beleg
    einer fremden Familie „entfernen"."""
    weg = dokument_holen(dokument_id, session, familie)
    behalten = dokument_holen(data.behalten_id, session, familie)
    if weg.id == behalten.id:
        raise HTTPException(400, "Beide Angaben zeigen auf dasselbe Dokument.")
    o = session.get(Objekt, weg.objekt_id) if weg.objekt_id else None
    if not o:
        raise HTTPException(400, "Zum Dokument gehört keine Immobilie.")
    _cloud_pflicht(o)
    client = verbindung(session)
    weg_pfad, behalten_pfad = weg.pfad, behalten.pfad
    try:
        geloescht = _duplikat_weg(session, client, weg, behalten)
    except NextcloudFehler as fehler:
        raise HTTPException(400, str(fehler)) from fehler
    except _NichtByteGleich as fehler:
        # N97 — der Nutzer hat die beiden Scans verglichen und als dasselbe
        # Dokument bestätigt: dann wandert die Datei in „99_Duplikate" statt
        # gelöscht zu werden, und der Beleg verlässt die Abrechnung.
        if not data.bestaetigt:
            raise HTTPException(
                409, "Die Dateien sind NICHT byte-gleich — es wird nichts "
                     "gelöscht. Als Doppel bestätigen, um sie nach "
                     "„99_Duplikate\" zu verschieben."
            ) from fehler
        try:
            belegposten.loese(session, weg)
            weg.zeitraum_id = None
            session.add(weg)
            _beleg_umziehen(session, client, weg, _duplikat_ziel(o),
                            weg.dateiname)
        except NextcloudFehler as f2:
            raise HTTPException(400, str(f2)) from f2
        session.commit()
        log.info("Bestätigtes Doppel verschoben: %s → %s", weg_pfad,
                 DUPLIKAT_ORDNER)
        return {"ok": True, "geloescht": False, "verschoben": True,
                "behalten_pfad": behalten_pfad}
    session.commit()
    log.info("Duplikat entfernt: %s (behalten: %s)", weg_pfad, behalten_pfad)
    return {"ok": True, "geloescht": geloescht, "behalten_pfad": behalten_pfad}


# --------------------------------------------------------------------------
# CCLXXIV: Das KI-Raster festhalten — am Dokument UND als `.immocalc`-Steckbrief
# neben dem PDF in der Nextcloud.
#
# Der Massenlauf schickt je Beleg das ausgelesene Raster (Dokumenttyp,
# Liegenschaft, Einheit, typspezifische Felder). Es wird additiv am Dokument
# gespeichert — leere Werte überschreiben nie einen vorhandenen — und als
# menschenlesbarer Steckbrief neben die Datei geschrieben. Die Cloud-Datei
# selbst wird NICHT verschoben; scheitert das Sidecar-Schreiben, bleibt die
# DB-Speicherung trotzdem bestehen (`sidecar: false`), nie fliegt eine Exception.
# --------------------------------------------------------------------------

class ImmoCalcIn(BaseModel):
    """Das von der KI-Auslese gezogene Raster für einen Beleg — alles optional.

    Was mitkommt, wird gesetzt; was fehlt, lässt den bestehenden Wert stehen."""
    datum: str | None = None
    betrag: float | None = None
    kategorie: str | None = None
    kostenart: str | None = None
    ist_kosten: bool | None = None
    immobilie: str | None = None
    einheit: str | None = None
    felder: dict = {}
    einordnung: str | None = None


# N30 — Ordner nicht endlos tief absteigen: Belege liegen ein bis zwei Ebenen
# unter dem Objektordner (60_Nebenkosten/2025/…). Fünf Ebenen decken alles ab
# und begrenzen die WebDAV-Aufrufe je Lauf.
_IMMOCALC_MAX_TIEFE = 5


def verwaiste_immocalc_aufraeumen(session: Session,
                                  familie_id: int | None = None) -> dict:
    """N30 — verwaiste `.immocalc`-Steckbriefe aufräumen.

    Löscht der Nutzer ein PDF/Bild von Hand in der Nextcloud, bleibt die
    `.immocalc`-Sidecar (CCLXXIV) als Waise liegen. Dieser Hintergrundlauf sucht
    je Objektordner nach `.immocalc`-Dateien, zu denen KEIN gleichnamiger Beleg
    (mit anderer Endung) mehr im selben Ordner liegt, und entfernt genau diese —
    nur unterhalb des Home-Ordners (der `loesche`-Riegel `_pruefe_schreibrecht`
    greift). Rein zurückhaltend: eine `.immocalc` MIT Beleg wird nie angefasst.

    Gibt `{"geloescht": n, "geprueft": m}` zurück. Bei jedem Cloud-Fehler wird
    der betroffene Ordner/das Objekt übersprungen, nie eine Exception geworfen.

    N436 — `familie_id=None` (der Wachdienst-Aufruf) läuft über jede Familie
    einzeln, mit ihrer eigenen Nextcloud-Verbindung."""
    if familie_id is None:
        teile = _je_familie(
            session, lambda fid: verwaiste_immocalc_aufraeumen(session, fid))
        return {"geloescht": sum(t["geloescht"] for t in teile),
                "geprueft": sum(t["geprueft"] for t in teile)}
    try:
        client = verbindung(session)
    except Exception:                                    # noqa: BLE001
        return {"geloescht": 0, "geprueft": 0}
    objekte = session.exec(
        select(Objekt).where(Objekt.nc_ordner.is_not(None),
                             Objekt.familie_id == familie_id)).all()
    geloescht = 0
    geprueft = 0
    for o in objekte:
        wurzel = (o.nc_ordner or "").strip()
        if not wurzel:
            continue
        offen: list[tuple[str, int]] = [(wurzel, 0)]
        besucht: set[str] = set()
        while offen:
            ordner, tiefe = offen.pop()
            if ordner in besucht:
                continue
            besucht.add(ordner)
            try:
                eintraege = client.liste(ordner)
            except NextcloudFehler:
                continue
            dateien = [e for e in eintraege if not e.ordner]
            for e in eintraege:
                if e.ordner and tiefe < _IMMOCALC_MAX_TIEFE and e.pfad not in besucht:
                    offen.append((e.pfad, tiefe + 1))
            # Die Stämme der echten Belege in DIESEM Ordner (ohne .immocalc).
            belegstaemme = {_dateistamm(e.name) for e in dateien
                            if not e.name.lower().endswith(".immocalc")}
            for e in dateien:
                if not e.name.lower().endswith(".immocalc"):
                    continue
                geprueft += 1
                if _dateistamm(e.name) in belegstaemme:
                    continue                             # hat noch seinen Beleg
                try:
                    client.loesche(e.pfad)
                    geloescht += 1
                    log.info("Verwaiste .immocalc entfernt: %s", e.pfad)
                except NextcloudFehler as fehler:
                    log.info("Verwaiste .immocalc nicht löschbar: %s", fehler)
    return {"geloescht": geloescht, "geprueft": geprueft}


def _objekt_aus_immobilie(session: Session, immobilie: str,
                          familie_id: int) -> Objekt | None:
    """Sucht das Objekt, dessen Straße in der erkannten Liegenschaft steckt.

    Bewusst einfach: normalisierter Teilstring-Abgleich der `Objekt.strasse`.
    Kein eindeutiger Treffer → None (dann bleibt die Zuordnung offen).

    N436 — der Kandidatenkreis ist auf die Objekte der angemeldeten Familie
    eingegrenzt; ohne das hätte der Fuzzy-Abgleich einen Beleg an ein Objekt
    einer FREMDEN Familie hängen können."""
    ziel = _adr_norm(immobilie)
    if not ziel:
        return None
    treffer = [o for o in session.exec(
                   select(Objekt).where(Objekt.familie_id == familie_id)).all()
               if o.strasse and _adr_norm(o.strasse) in ziel]
    return treffer[0] if len(treffer) == 1 else None


@router.post("/{dokument_id}/immocalc")
def immocalc(dokument_id: int, body: ImmoCalcIn,
             session: Session = Depends(get_session),
             familie: Familie = Depends(aktuelle_familie)) -> dict:
    """Hält das KI-Raster am Beleg fest und legt einen `.immocalc`-Steckbrief
    neben das PDF (CCLXXIV).

    Additiv: gesetzte Werte gewinnen, leere lassen den Bestand unberührt. Die
    Cloud-Datei wird nicht verschoben. Scheitert das Sidecar-Schreiben, wird
    trotzdem gespeichert und `sidecar: false` gemeldet — nie eine Exception.

    N436 — `familie` sichert zweierlei ab: `dokument_holen` prüft den Beleg
    selbst (404 bei einem fremden Dokument), und derselbe Wert grenzt den
    Fuzzy-Abgleich in `_objekt_aus_immobilie` auf die eigenen Objekte ein."""
    d = dokument_holen(dokument_id, session, familie)
    gesetzt = body.model_fields_set

    # Das Raster am Dokument festhalten (additiv, leere Werte überschreiben nie).
    if body.felder:
        d.ki_felder = body.felder
    if body.immobilie:
        d.ki_immobilie = body.immobilie
    if body.einheit:
        d.ki_einheit = body.einheit
    if body.einordnung:
        d.ki_einordnung = body.einordnung
    # Kernangaben zusätzlich in die regulären Felder — nur wenn gesetzt.
    if "kategorie" in gesetzt and body.kategorie:
        d.kategorie = body.kategorie
    if "kostenart" in gesetzt and body.kostenart:
        d.kostenart = kostenart_normalisieren(body.kostenart)
    if "datum" in gesetzt:
        neu_datum = _zum_datum(body.datum or "")
        if neu_datum:
            d.belegdatum = neu_datum
            if d.jahr is None:
                d.jahr = neu_datum.year
    if "betrag" in gesetzt and body.betrag and body.betrag > 0:
        d.betrag = body.betrag

    # Immobilie → Objekt zuordnen, wenn der Beleg noch keins hat.
    if not d.objekt_id and body.immobilie:
        o = _objekt_aus_immobilie(session, body.immobilie, familie.id)
        if o:
            d.objekt_id = o.id

    # N297 — der `.immocalc`-Steckbrief wird NICHT mehr geschrieben.
    #
    # Er lag als zusätzliche Datei neben jedem PDF und machte die Ordner des
    # Nutzers unübersichtlich — sein ausdrücklicher Wunsch, sie loszuwerden.
    # Fachlich kostet das nichts: der Steckbrief wurde aus den Feldern dieses
    # Datensatzes ERZEUGT und an keiner Stelle je wieder eingelesen (jede
    # Fundstelle im Code schrieb, verschob, löschte oder filterte ihn nur aus
    # den Ansichten heraus). Die Auslese steht in der Datenbank —
    # `ki_einordnung`, `ki_felder`, `ki_immobilie`, `ki_einheit` — und seit
    # N296 zusätzlich am Dateiinhalt (`KiAuslese`), damit sie kein zweites Mal
    # bezahlt werden muss.
    #
    # Das Aufräumen des Bestands macht `immocalc-entfernen`.
    sidecar_ok = False

    session.add(d)
    session.commit()
    session.refresh(d)
    o = session.get(Objekt, d.objekt_id) if d.objekt_id else None
    # N376 — `sidecar_pfad` gibt es hier gar nicht (der Steckbrief wurde
    # abgeschafft, siehe oben). Der Ausdruck stand nur deshalb ohne Folgen da,
    # weil `sidecar_ok` fest False ist und Python den anderen Zweig nie
    # auswertet — ein NameError in Wartestellung, der beim ersten Wiederbeleben
    # des Merkmals zugeschlagen hätte. Die beiden Felder bleiben in der Antwort,
    # damit ältere Aufrufer nicht über ein fehlendes Feld stolpern.
    return {"ok": True, "gespeichert": True, "sidecar": sidecar_ok,
            "sidecar_pfad": "",
            "objekt": o.slug if o else None}


# --------------------------------------------------------------------------
# CCLV: Kostenfreie Belege als Themen-Anhänger
#
# Manche Belege sind Zusatzinformationen zu einer Kostenart, tragen aber
# keinen eigenen Kostenanteil — ein SEPA-Lastschriftmandat, ein Zählerstand.
# Sie hängen am **Thema** (Zeitraum + Kostenart), nicht an einer
# Kostenposition: wird die Position getauscht oder entfernt, bleibt der
# Anhänger. Schlüssel ist deshalb (`zeitraum_id` + `kostenart`), und
# `position_id` bleibt bewusst leer — es entsteht keine Kostenposition und es
# wird kein Betrag verrechnet.
# --------------------------------------------------------------------------

class AnhaengerIn(BaseModel):
    """Ein kostenfreier Beleg wird an ein Kostenart-Thema gehängt."""
    zeitraum_id: int
    kostenart: str


@router.get("/anhaenger/{zeitraum_id}")
def anhaenger_liste(zeitraum_id: int,
                    session: Session = Depends(get_session),
                    familie: Familie = Depends(aktuelle_familie)) -> dict:
    """Die kostenfreien Themen-Anhänger eines Zeitraums, nach Kostenart
    gruppiert — und die Belege, die sich noch anhängen ließen.

    Angehängt ist, was auf diesen Zeitraum zeigt, ohne in eine Kostenposition
    eingerechnet zu sein (`position_id` leer), mit einer Kostenart als Thema.
    Kandidaten sind die übrigen kostenfreien Belege derselben Immobilie.

    N436 — der Zeitraum kommt über `zeitraum_holen` (404 bei fremdem
    Zeitraum); ohne das liesse sich über eine geratene `zeitraum_id` der
    Anhänger-Bestand einer fremden Familie einsehen."""
    z = zeitraum_holen(zeitraum_id, session, familie)
    alle = session.exec(
        select(Dokument).where(Dokument.status != VERMISST)).all()

    angehaengt: dict[str, list] = {}
    for d in alle:
        if (d.zeitraum_id == zeitraum_id and d.position_id is None
                and (d.kostenart or "").strip()):
            angehaengt.setdefault(d.kostenart, []).append(_anh_zeige(d))

    schon = {e["id"] for liste in angehaengt.values() for e in liste}
    kandidaten = [
        _anh_zeige(d) for d in alle
        if d.objekt_id == z.objekt_id and _ist_kostenfrei(d)
        and d.id not in schon]
    # Neueste zuerst — der frisch abgelegte Beleg steht oben.
    kandidaten.sort(key=lambda e: (-(e["jahr"] or 0), e["dateiname"].lower()))
    for liste in angehaengt.values():
        liste.sort(key=lambda e: e["dateiname"].lower())
    return {"zeitraum_id": zeitraum_id, "angehaengt": angehaengt,
            "kandidaten": kandidaten}


@router.post("/{dokument_id}/anhaenger")
def anhaenger_setzen(dokument_id: int, data: AnhaengerIn,
                     session: Session = Depends(get_session),
                     familie: Familie = Depends(aktuelle_familie)) -> dict:
    """Hängt einen kostenfreien Beleg an ein Kostenart-Thema.

    Setzt nur `zeitraum_id` und `kostenart` am Beleg — es entsteht keine
    Kostenposition, `position_id` bleibt leer, kein Betrag wird verrechnet. Die
    Datei in der Cloud bleibt unangetastet, wo sie liegt."""
    d = _beleg(session, dokument_id, familie)
    if d.position_id:
        raise HTTPException(409, "Dieser Beleg ist in eine Kostenposition "
                                 "eingerechnet — er trägt einen Kostenanteil "
                                 "und ist kein kostenfreier Anhänger.")
    kostenart = kostenart_normalisieren(data.kostenart)
    if not kostenart:
        raise HTTPException(400, "Für den Anhänger fehlt das Kostenart-Thema.")
    _pruefe_zeitraum(session, data.zeitraum_id)
    d.zeitraum_id = data.zeitraum_id
    d.kostenart = kostenart
    session.add(d)
    session.commit()
    session.refresh(d)
    log.info("Anhänger gesetzt: Dokument %s an Zeitraum %s · %s",
             d.id, data.zeitraum_id, kostenart)
    return {"ok": True, **_anh_zeige(d), "zeitraum_id": d.zeitraum_id}


@router.delete("/{dokument_id}/anhaenger")
def anhaenger_loesen(dokument_id: int,
                     session: Session = Depends(get_session),
                     familie: Familie = Depends(aktuelle_familie)) -> dict:
    """Löst einen Themen-Anhänger wieder vom Zeitraum.

    Nimmt nur die Zeitraum-Zuordnung zurück (`zeitraum_id` leer); die
    Klassifizierung (Art, Kostenart) und die Datei bleiben unangetastet. Eine
    Kostenposition war nie im Spiel, `position_id` bleibt unberührt leer."""
    d = _beleg(session, dokument_id, familie)
    d.zeitraum_id = None
    session.add(d)
    session.commit()
    log.info("Anhänger gelöst: Dokument %s", d.id)
    return {"ok": True, "id": d.id, "kostenart": d.kostenart}


@router.delete("/{dokument_id}")
def entfernen(dokument_id: int,
              session: Session = Depends(get_session),
              familie: Familie = Depends(aktuelle_familie)) -> dict:
    """Nimmt das Dokument aus der App. Die Datei in der Nextcloud bleibt —
    dort wird grundsätzlich nichts gelöscht."""
    d = dokument_holen(dokument_id, session, familie)
    pfad = d.pfad
    # War der Beleg in eine Kostenposition eingerechnet, schrumpft deren Summe
    # um seinen Anteil. Sonst bliebe dort ein Betrag stehen, zu dem es keinen
    # Beleg mehr gibt.
    belegposten.loese(session, d)
    # N314 — und JEDEN anderen Verweis lösen. Bis hierher blieben alle zehn
    # stehen: Versicherung, Kredit, Notarvertrag, Renovierungsrechnung,
    # Belegdaten … Weil SQLite hier ohne `PRAGMA foreign_keys` läuft und eine
    # frei gewordene id neu vergibt, zeigte so ein Verweis nach kurzer Zeit
    # nicht ins Leere, sondern auf einen FREMDEN Beleg — der nächste Scan erbt
    # die Nummer und stand dann als „Quelle" einer Versicherung da, die er nie
    # gesehen hat. `_duplikat_weg` und `/zusammenfuehren` machen es längst
    # richtig; der einfache Löschknopf war die Lücke.
    geloest = dokumentlinks.loese(session, dokument_id)
    session.delete(d)
    session.commit()
    log.info("Dokumenteintrag entfernt: %s (Datei bleibt, %d Verweise gelöst)",
             pfad, geloest)
    return {"ok": True, "pfad": pfad, "datei_bleibt": True,
            "verweise_geloest": geloest,
            "hinweis": "Der Eintrag ist weg, die Datei liegt weiter in der "
                       "Nextcloud."}


@router.post("/{dokument_id}/neu")
async def neu_einscannen(dokument_id: int, datei: UploadFile = File(...),
                         session: Session = Depends(get_session),
                         familie: Familie = Depends(aktuelle_familie)) -> dict:
    """Ersetzt den Beleg durch eine neue Aufnahme.

    Die alte Datei bleibt liegen — überschrieben oder gelöscht wird in der
    Nextcloud nichts. Der Eintrag zeigt danach auf die neue Aufnahme."""
    d = dokument_holen(dokument_id, session, familie)
    o = session.get(Objekt, d.objekt_id) if d.objekt_id else None
    if not o:
        raise HTTPException(400, "Dem Dokument fehlt die Immobilie")
    _cloud_pflicht(o)

    inhalt = await upload.lies(datei, was="Der Beleg")

    alt = d.pfad
    kategorie = d.kategorie or "Sonstiges"
    # Die Aufnahme kommt als PDF; ein Eintrag, der vorher anders hieß, bekommt
    # seinen Schemanamen.
    jahr, monat = datum_aus_namen(d.dateiname)
    name = (d.dateiname if d.dateiname.lower().endswith(".pdf")
            else dateiname(d.jahr or jahr, kategorie, _bezeichnung(d.dateiname),
                           ".pdf", monat, betrag_aus_namen(d.dateiname),
                           d.kostenart))
    client = verbindung(session)
    try:
        sach, ordner = _ablageordner(session, o, kategorie, d.jahr or jahr,
                                     client)
        _ordner_sichern(client, sach, ordner)
        name = _freier_name(session, client, ordner, name)
        client.lege_ab(f"{ordner}/{name}", inhalt)
    except NextcloudFehler as e:
        raise HTTPException(400, str(e)) from e

    d.pfad = f"/{ordner}/{name}"
    d.dateiname = name
    kidb.pfad_nachziehen(session, d)   # N299
    d.kategorie = kategorie
    d.groesse = len(inhalt)
    d.status = "zugeordnet"
    d.erkannt_am = date.today()
    session.add(d)
    try:
        session.commit()
    except IntegrityError as e:
        raise _pfad_konflikt(session, f"/{ordner}/{name}") from e
    return {"ok": True, "id": d.id, "pfad": d.pfad, "dateiname": name,
            "alt": alt,
            "hinweis": "Die vorherige Datei bleibt in der Nextcloud liegen."}


@router.get("/{dokument_id}/inhalt")
def inhalt(dokument_id: int, session: Session = Depends(get_session),
          familie: Familie = Depends(aktuelle_familie)) -> Response:
    """Liefert die Datei aus der Nextcloud zur Ansicht im Browser.

    `inline` statt `attachment`: PDFs und Bilder sollen sich öffnen, nicht
    herunterladen. Rein lesend — an der Datei ändert sich nichts."""
    d = dokument_holen(dokument_id, session, familie)
    if not d.pfad.startswith("/"):
        raise HTTPException(409, "Dieses Dokument liegt noch nicht in der Cloud")
    client = verbindung(session)
    rohdaten, typ = _datei_holen(session, client, d)
    # Nextcloud liefert für unbekannte Endungen octet-stream; das laedt der
    # Browser herunter, statt es anzuzeigen.
    if typ == "application/octet-stream" and d.dateiname.lower().endswith(".pdf"):
        typ = "application/pdf"
    return Response(content=rohdaten, media_type=typ, headers={
        "Content-Disposition": f"inline; {_dateiname_kopfzeile(d.dateiname)}",
        "Cache-Control": "private, max-age=60",
    })


@router.get("/{dokument_id}/seiten")
def seiten(dokument_id: int,
           session: Session = Depends(get_session),
           familie: Familie = Depends(aktuelle_familie)) -> dict:
    """Wie viele Bildseiten die Vorschau dieses Belegs hat (CCLIX).

    Ein PDF hat so viele Seiten, wie es Blätter trägt; ein Bild (jpg/png) ist
    eine einzelne Seite. Was sich gar nicht rendern lässt (xlsx, docx) hat
    keine Bildseiten: 0. Damit weiss das Frontend, wie viele
    `?seite=`-Anfragen es an `/vorschau` stellen kann.

    Rein lesend — die Datei wird nur geholt, nichts geändert."""
    d = dokument_holen(dokument_id, session, familie)
    if not d.pfad.startswith("/"):
        raise HTTPException(409, "Dieses Dokument liegt noch nicht in der Cloud")
    client = verbindung(session)
    rohdaten, typ = _datei_holen(session, client, d)
    name = d.dateiname.lower()
    if name.endswith(".pdf") or typ == "application/pdf":
        anzahl = ocr.seiten_anzahl(rohdaten)
        return {"seiten": anzahl}
    if typ.startswith("image/") or name.endswith(
            (".jpg", ".jpeg", ".png", ".gif", ".webp")):
        return {"seiten": 1}
    return {"seiten": 0}


@router.get("/{dokument_id}/vorschau")
def vorschau(dokument_id: int,
             seite: int = Query(0, ge=0),
             session: Session = Depends(get_session),
             familie: Familie = Depends(aktuelle_familie)) -> Response:
    """Eine Vorschau, die die GANZE Seite zeigt statt eines Ausschnitts:
    PDF → die Seite `seite` als Bild gerendert, ein Bild → direkt. So passt
    sich die Vorschau in der Seite an die Breite an, ohne dass ein Viewer
    beschneidet. Was sich nicht rendern lässt (z. B. Tabellen), meldet 415 —
    die Oberfläche bietet dann das Öffnen im neuen Tab an.

    `?seite=` (Default 0) wählt bei mehrseitigen PDFs die Seite (CCLIX). Ohne
    den Parameter verhält sich der Endpunkt exakt wie zuvor: die erste Seite.
    Eine Seite jenseits des Endes meldet 416 statt eines leeren Bildes."""
    d = dokument_holen(dokument_id, session, familie)
    if not d.pfad.startswith("/"):
        raise HTTPException(409, "Dieses Dokument liegt noch nicht in der Cloud")
    client = verbindung(session)
    rohdaten, typ = _datei_holen(session, client, d)
    name = d.dateiname.lower()
    if name.endswith(".pdf") or typ == "application/pdf":
        anzahl = ocr.seiten_anzahl(rohdaten)
        if anzahl and seite >= anzahl:
            raise HTTPException(416, f"Dieses PDF hat nur {anzahl} Seite(n)")
        # N12 — ein Lageplan behält seine im Scanner gewählte Orientierung; die
        # OSD-Auto-Aufrichtung (richtet Text auf) würde einen Querplan wieder ins
        # Hochformat kippen. Belege dagegen sollen aufrecht stehen.
        png = ocr.seite_png(rohdaten, seite, osd=(d.kategorie != LAGEPLAN))
        if png is None:
            raise HTTPException(415, "Vorschau nicht möglich")
        return Response(content=png, media_type="image/png",
                        headers={"Cache-Control": "private, max-age=300"})
    # Ein Bild hat nur eine Seite; eine höhere Anforderung geht ins Leere.
    if typ.startswith("image/") or name.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
        if seite > 0:
            raise HTTPException(416, "Dieses Dokument hat nur eine Seite")
        return Response(content=rohdaten, media_type=typ if typ.startswith("image/")
                        else "image/jpeg",
                        headers={"Cache-Control": "private, max-age=300"})
    raise HTTPException(415, "Für diese Datei gibt es keine Bildvorschau")


def _hole_beleg_bytes(session: Session, dokument_id: int,
                      familie: Familie) -> tuple[Dokument, bytes]:
    """Der Beleg und seine Bytes aus der Cloud — die gemeinsame Vorstufe von
    Erkennen und Neu-Analysieren.

    N436 — `dokument_holen` grenzt auf die angemeldete Familie ein."""
    d = dokument_holen(dokument_id, session, familie)
    if not d.pfad.startswith("/"):
        raise HTTPException(409, "Dieses Dokument liegt noch nicht in der Cloud")
    client = verbindung(session)
    try:
        rohdaten, _typ = client.hole(d.pfad)
    except NextcloudFehler as e:
        raise HTTPException(400, str(e)) from e
    return d, rohdaten


@router.get("/{dokument_id}/erkennen")
def erkennen_aus_ablage(dokument_id: int, neu: bool = False,
                        session: Session = Depends(get_session),
                        familie: Familie = Depends(aktuelle_familie)) -> dict:
    """Liest Betrag, Datum und Art aus einem Beleg, der schon in der Cloud liegt.

    `_vorschlag` kennt nur den Dateinamen. Heisst die Rechnung schlicht
    „Rechnung_2026_01.pdf", steht im Eingang „Betrag: nicht erkannt" — obwohl
    er auf dem Blatt steht (CLXX). Hier wird die Datei einmal geholt und
    gelesen.

    Bewusst ein eigener Endpunkt und nicht Teil der Liste: für jeden Eintrag
    einer Ansicht die Datei aus der Nextcloud zu holen wäre ein Zug durch die
    ganze Ablage. Gefragt wird für den einen Beleg, den der Nutzer gerade
    ansieht.

    Die KI-Einordnung und das Raster werden dabei am Beleg festgehalten
    (CCLXXIII/CCCLXVII): sie kosten einen KI-Aufruf, und der Nutzer soll die
    Einschätzung später wieder sehen, ohne den Beleg neu lesen zu lassen. Sonst
    rein lesend — die Datei wird nicht verschoben.
    """
    # N98 — zuerst die gespeicherte Auslese: derselbe Beleg wird beim Blättern
    # im Eingang immer wieder angesehen, und jeder Aufruf hier kostete bisher
    # einen KI-Call. `?neu=true` (bzw. `/neu-analysieren`) liest bewusst neu.
    if not neu:
        gespeichert = _ki_aus_db(dokument_holen(dokument_id, session, familie), session)
        if gespeichert:
            return gespeichert
    d, rohdaten = _hole_beleg_bytes(session, dokument_id, familie)
    # N296 — zweite Stufe vor der KI: dieselbe Datei kann als NEUER Eintrag
    # hereinkommen (zweiter Scan, Duplikat im anderen Objektordner, nach einem
    # Grabstein neu aufgenommen). Sie hat dann eine andere Nummer, aber
    # denselben Inhalt — und der ist schon einmal bezahlt gelesen worden.
    sha1 = kicache.pruefsumme(rohdaten)
    _pruefsumme_nachtragen(session, d, sha1)
    # N328(ii) — den Volltext nur lesen, wenn er diesem Beleg noch fehlt: sonst
    # kostete jeder Aufruf (auch ein Zwischenspeicher-Treffer) einen OCR-Lauf,
    # den die Suche gar nicht mehr braucht.
    text_neu = ("" if (d.erkannter_text or "").strip()
               else ocr.text_aus_beleg(rohdaten))
    gemerkt = kicache.hole(session, sha1)
    if gemerkt is not None:
        _ki_am_beleg_festhalten(session, d, gemerkt, text=text_neu)
        # Hier gibt es keine Kostenart und keine Maske — der Beleg wird
        # angesehen, nicht in ein Formular übersetzt. Die Zusätze bleiben
        # trotzdem am Kontext ausgerichtet, damit dieselbe Regel gilt.
        return {**_aus_zwischenspeicher(session, gemerkt, d.kostenart or "", ""),
                "aus_zwischenspeicher": True}
    # Dateiname als Kontext mitgeben — dieselbe KI-gestützte Auslese wie beim
    # frisch abfotografierten Beleg (CCLXVIII). CCLXIX: auch die Erkennungs-
    # muster (CCXLIX) anwenden, damit Nutzerregeln beim Cloud-Beleg genauso
    # greifen wie beim Foto-Upload.
    ergebnis = ocr.erkenne(rohdaten, _regeln(session), d.dateiname,
                           ki_key=_ki_key(session), ki_modell=_ki_modell(session),
                           text=text_neu or None)
    kern = dict(ergebnis)          # N296 — vor jeder Anreicherung, siehe /erkennen
    # N162 — Strombeleg: Menge und Bruttobetrag der Lieferung nachziehen, bevor
    # das Raster am Beleg festgehalten wird. Sonst bliebe dort die Nachzahlung
    # stehen und belegte später das Betragsfeld falsch vor.
    _strom_ergaenzen(session, rohdaten, ergebnis, d.dateiname or "",
                     text=text_neu or None)
    _ki_am_beleg_festhalten(session, d, ergebnis, text=text_neu)
    kicache.merke(session, sha1, {
        **kern, **({"strom": ergebnis["strom"]} if "strom" in ergebnis else {}),
    }, _ki_modell(session))
    return ergebnis


@router.post("/{dokument_id}/neu-analysieren")
def neu_analysieren(dokument_id: int,
                    session: Session = Depends(get_session),
                    familie: Familie = Depends(aktuelle_familie)) -> dict:
    """Führt die KI-Analyse für einen abgelegten Beleg erneut aus (CCCLXVII).

    Der Nutzer stößt es an, nachdem er den API-Schlüssel hinterlegt hat oder
    einen Beleg neu bewerten lassen will. Anders als `/erkennen` sagt die
    Antwort ehrlich, ob die KI überhaupt lief: ohne Schlüssel oder ohne Guthaben
    bleibt es bei der einfachen Erkennung — dann erklärt `meldung`, warum keine
    KI-Einschätzung kam. Es stürzt nichts ab, es entstehen keine Daten von
    selbst. Rein lesend an der Cloud-Datei; festgehalten werden nur die frischen
    KI-Angaben am Beleg."""
    d, rohdaten = _hole_beleg_bytes(session, dokument_id, familie)
    ki_key = _ki_key(session)
    eingerichtet = kiauslese.verfuegbar(ki_key)
    # N328(ii) — einmal lesen, für Erkennung, Strom-Ergänzung und (falls noch
    # leer) `erkannter_text` gemeinsam nutzen statt dreimal OCR zu laufen.
    text_neu = ("" if (d.erkannter_text or "").strip()
               else ocr.text_aus_beleg(rohdaten))
    ergebnis = ocr.erkenne(rohdaten, _regeln(session), d.dateiname,
                           ki_key=ki_key, ki_modell=_ki_modell(session),
                           text=text_neu or None)
    kern = dict(ergebnis)          # N296 — vor jeder Anreicherung
    _strom_ergaenzen(session, rohdaten, ergebnis, d.dateiname or "",
                     text=text_neu or None)   # N162
    _ki_am_beleg_festhalten(session, d, ergebnis, text=text_neu)
    # N296 — „neu analysieren" ist der ausdrückliche Wunsch nach einer frischen
    # Lesung: der Zwischenspeicher wird hier bewusst NICHT gefragt, sondern
    # überschrieben. Sonst bliebe der Nutzer für immer an der ersten, mit einem
    # älteren Modell erzeugten Auslese hängen.
    sha1 = kicache.pruefsumme(rohdaten)
    _pruefsumme_nachtragen(session, d, sha1)
    kicache.merke(session, sha1, {
        **kern, **({"strom": ergebnis["strom"]} if "strom" in ergebnis else {}),
    }, _ki_modell(session))
    gelaufen = bool(ergebnis.get("ki"))
    if not eingerichtet:
        meldung = ("Für die KI-Analyse ist kein Anthropic-Schlüssel hinterlegt — "
                   "in den Einstellungen eintragen, dann erneut versuchen.")
    elif not gelaufen:
        meldung = ("Die KI war nicht erreichbar (kein Guthaben oder ein "
                   "Netzwerkproblem) — es gilt weiter die einfache Erkennung.")
    else:
        meldung = "KI-Analyse aktualisiert."
    return {**ergebnis, "ki_eingerichtet": eingerichtet,
            "ki_gelaufen": gelaufen, "meldung": meldung}


@router.post("/{dokument_id}/geradedrehen")
def geradedrehen(dokument_id: int, grad: int = Query(0),
                 session: Session = Depends(get_session),
                 familie: Familie = Depends(aktuelle_familie)) -> dict:
    """Dreht ein gedreht abgelegtes PDF dauerhaft in die aufrechte Lage.

    Manche eingescannten oder abfotografierten Seiten liegen um 90/180/270°
    gedreht. Die serverseitige Vorschau richtet sie beim Rendern schon auf
    (`ocr.seite_png`), aber die Datei in der Cloud bleibt schief — und wer sie
    herunterlädt, sieht sie gekippt. Dieser Endpunkt setzt die Drehung fest.

    Ohne `?grad=` wird je Seite zuerst die zuverlässige KI-Orientierung
    versucht (mit dem in den Einstellungen hinterlegten Schlüssel), sonst
    Tesseract-OSD — beides in `ocr.pdf_geradedrehen`.

    Datensicher: geändert wird nur die /Rotate-Angabe jeder Seite, der Inhalt
    bleibt unangetastet (`ocr.pdf_geradedrehen`). Erst wenn wirklich etwas zu
    drehen war, wird die Datei am selben Platz in der Cloud überschrieben —
    scheitert das Schreiben, bleiben Cloud-Original und Datenbank unberührt.

    Antwort: `{"ok": true, "gedreht": [{seite, grad}, …], "geaendert": <bool>}`.
    """
    d = dokument_holen(dokument_id, session, familie)
    if not d.pfad.startswith("/"):
        raise HTTPException(409, "Dieses Dokument liegt noch nicht in der Cloud")
    if not d.dateiname.lower().endswith(".pdf"):
        raise HTTPException(415, "Nur PDFs lassen sich geradedrehen")
    client = verbindung(session)
    try:
        rohdaten, _typ = client.hole(d.pfad)
    except NextcloudFehler as e:
        raise HTTPException(400, str(e)) from e

    # Manueller Override: gibt der Aufrufer `?grad=90|180|270`, wird genau das
    # gedreht (wenn die OSD-Automatik danebenlag). Ohne `grad` erkennt OSD selbst.
    if grad and grad % 90 == 0 and grad % 360 != 0:
        neu = ocr.pdf_drehen(rohdaten, grad % 360)
        gedreht = [{"seite": "alle", "grad": grad % 360}] if neu else []
    else:
        # Der in den Einstellungen hinterlegte Schlüssel gibt der zuverlässigen
        # KI-Orientierung den Vorrang; ohne Key greift OSD (env-Fallback in
        # `kiauslese`).
        neu, gedreht = ocr.pdf_geradedrehen(rohdaten, _ki_key(session))
    if neu is None or not gedreht:
        # Nichts lag schief — oder die Orientierungserkennung fehlt. Beides ist
        # kein Fehler: die Datei bleibt, wie sie ist.
        return {"ok": True, "gedreht": [], "geaendert": False}

    try:
        # N314(f) — nie per nacktem PUT überschreiben (CLAUDE.md: Cloud-Dateien
        # gehören dem Nutzer). `_ocr_ersetzen` sichert das Original zuerst per
        # MOVE weg und legt es bei einem Fehlschlag sofort zurück — dasselbe
        # Muster wie bei der Textschicht-Nachpflege.
        _ocr_ersetzen(client, d.pfad, neu)
    except NextcloudFehler as fehler:
        # Cloud-Schreiben gescheitert: Original und Datenbank unberührt, ein
        # sauberer Hinweis statt einer durchschlagenden Exception.
        log.warning("Geradegedrehtes PDF nicht abgelegt (%s): %s",
                    d.pfad, fehler)
        raise HTTPException(
            502, "Das geradegedrehte PDF konnte nicht in der Cloud "
                 "gespeichert werden — es bleibt unverändert.") from fehler

    d.groesse = len(neu)
    session.add(d)
    session.commit()
    log.info("Geradegedreht: %s (%d Seite(n))", d.pfad, len(gedreht))
    return {"ok": True, "gedreht": gedreht, "geaendert": True}


@router.post("/{dokument_id}/durchsuchbar")
def durchsuchbar(dokument_id: int,
                 session: Session = Depends(get_session),
                 familie: Familie = Depends(aktuelle_familie)) -> dict:
    """Legt einem einzelnen Beleg seine unsichtbare Textschicht unter.

    Denselben Weg geht der Wachdienst über `nachtraeglich_ocren`, nur eben für
    alle liegen gebliebenen Belege. Hier fragt der Aufrufer für genau einen —
    ein frisch abfotografierter Scan soll durchsuchbar sein, ohne auf den
    nächsten Takt zu warten.

    Datensicher wie dort: ersetzt wird ausschliesslich per MOVE
    (`_ocr_ersetzen`) — das Original wandert zuerst unangetastet in den
    Sicherungsordner neben der Datei, erst danach bekommt der freie Platz die
    geprüfte Fassung. Scheitert das Ablegen, kommt das Original sofort zurück.

    Nichts zu tun ist kein Fehler: fehlt das Werkzeug, oder trägt der Beleg
    schon Text, lautet die Antwort `ok: true, ergaenzt: false` samt Grund."""
    d = dokument_holen(dokument_id, session, familie)
    if not d.pfad.startswith("/"):
        raise HTTPException(409, "Dieses Dokument liegt noch nicht in der Cloud")
    if not d.dateiname.lower().endswith(".pdf"):
        raise HTTPException(415, "Nur PDFs bekommen eine Textschicht")
    if not ocr.durchsuchbar_verfuegbar():
        return {"ok": True, "ergaenzt": False, "grund": "Werkzeug nicht verfügbar"}

    client = verbindung(session)
    try:
        rohdaten, _typ = client.hole(d.pfad)
    except NextcloudFehler as fehler:
        raise HTTPException(400, str(fehler)) from fehler
    try:
        neu = ocr.durchsuchbar_machen(rohdaten)
    except Exception as fehler:                                # noqa: BLE001
        log.warning("Textschicht fehlgeschlagen für %s: %s", d.pfad, fehler)
        return {"ok": True, "ergaenzt": False,
                "grund": "Die Texterkennung ist gescheitert."}
    if neu is None:
        return {"ok": True, "ergaenzt": False,
                "grund": "Der Beleg trägt schon Text — nichts nachzutragen."}

    try:
        _ocr_ersetzen(client, d.pfad, neu)
    except NextcloudFehler as fehler:
        log.warning("Textschicht konnte nicht abgelegt werden (%s): %s",
                    d.pfad, fehler)
        raise HTTPException(
            502, "Die durchsuchbare Fassung konnte nicht in der Cloud "
                 "gespeichert werden — der Beleg bleibt unverändert.") from fehler

    d.groesse = len(neu)
    session.add(d)
    session.commit()
    log.info("Textschicht ergänzt: %s", d.pfad)
    return {"ok": True, "ergaenzt": True, "grund": "Textschicht ergänzt"}


# --------------------------------------------------------------------------
# Standard-Umbenennung: die KI-verarbeiteten Belege tragen noch ihre
# Originalnamen. Sie sollen den Standardnamen
# `JJJJ-MM_Kürzel-Sache_Betrag€.endung` bekommen — aber IM SELBEN ORDNER
# bleiben (kein Move in Kategorie-/Jahresordner). Gebaut wird der Name aus den
# am Dokument gespeicherten Feldern (Kategorie, Belegdatum, Betrag, Kostenart)
# und der Bezeichnung aus dem Originalnamen (XCVII — die vom Nutzer gewählte
# Benennung bleibt erhalten).
# --------------------------------------------------------------------------

def _im_ordner_umbenennen(session: Session, d: Dokument,
                          neu_name: str) -> tuple[str, str]:
    """Benennt Datei UND Eintrag um — im selben Ordner. `(pfad, name)` zurück.

    Die Reihenfolge ist der ganze Punkt: **zuerst die Cloud, dann die
    Datenbank.** Ginge es andersherum, führte die Datenbank nach einem Ausfall
    einen Namen, den es in der Cloud nicht gibt — der Beleg wäre verloren, ohne
    dass es jemand merkt.

    * Cloud-MOVE gescheitert → nichts umbenannt, nichts geschrieben; die
      angefangene Sitzung wird zurückgerollt (`_freier_name` kann einen
      Grabstein gesetzt haben) und der Aufrufer bekommt Klartext (502).
      Derselbe Weg fängt den Schreibrecht-Riegel aus `nextcloud.py`
      (`AussenhalbHome` ist ein `NextcloudFehler`) — ein Ziel ausserhalb des
      Home-Ordners führt zu einer Meldung, nicht zu einem halben Zustand.
    * DB-Commit gescheitert (Pfad vergeben) → die Datei wird zurückgeschoben,
      damit beide Stände zusammenbleiben.
    * Nie überschreiben: `_freier_name` fragt die Cloud live und weicht auf
      „…-2" aus, wenn der Zielname belegt ist.
    """
    alt_pfad = d.pfad
    alt_name = d.dateiname
    ordner = _elternordner(alt_pfad)
    client = verbindung(session)
    try:
        frei = _freier_name(session, client, ordner, neu_name)
        ziel = f"/{ordner}/{frei}" if ordner else f"/{frei}"
        client.verschiebe(alt_pfad, ziel.lstrip("/"))
    except NextcloudFehler as fehler:
        session.rollback()
        log.warning("Umbenennen fehlgeschlagen (%s → %s): %s",
                    alt_pfad, neu_name, fehler)
        raise HTTPException(
            502, "Der Beleg konnte in der Cloud nicht umbenannt werden — er "
                 f"heisst weiterhin „{alt_name}“. Grund: {fehler}") from fehler

    d.pfad = ziel
    d.dateiname = frei
    kidb.pfad_nachziehen(session, d)   # N299
    session.add(d)
    try:
        session.commit()
    except IntegrityError as e:
        # Der Zielpfad ist inzwischen in der Datenbank vergeben. Die Datei liegt
        # zwar schon am neuen Platz — sie zurückzuschieben hält die beiden
        # Stände zusammen.
        session.rollback()
        try:
            client.verschiebe(ziel.lstrip("/"), alt_pfad.lstrip("/"))
        except Exception as zurueck:                       # noqa: BLE001
            log.warning("Rückverschieben nach Konflikt gescheitert (%s): %s",
                        ziel, zurueck)
        raise _pfad_konflikt(session, ziel) from e

    # Den Steckbrief mitnehmen — kein harter Fehler, wenn das scheitert.
    _sidecar_mitnehmen(client, alt_pfad, ziel)
    return ziel, frei


@router.post("/{dokument_id}/umbenennen")
def umbenennen(dokument_id: int,
               session: Session = Depends(get_session),
               familie: Familie = Depends(aktuelle_familie)) -> dict:
    """Benennt den Beleg auf den Standardnamen um — IM SELBEN ORDNER.

    Der Name wird aus den am Dokument gespeicherten Feldern gebaut: Kategorie
    (Kürzel), Belegdatum (Jahr/Monat), Betrag, Kostenart — und die Bezeichnung
    aus dem Originalnamen (`_bezeichnung`, XCVII). Die Datei bleibt in ihrem
    aktuellen Verzeichnis; sie wird nur umbenannt, nicht in einen Kategorie-
    oder Jahresordner verschoben. Kategorie- und Objektzuordnung bleiben
    unangetastet.

    Datensicher: nie überschreiben (freier Name in demselben Ordner), nie
    löschen; scheitert der Cloud-MOVE, bleiben Datei und Datenbank unberührt.
    Idempotent: heißt die Datei schon Standard → `{"ok": true, "geaendert":
    false}`. Die `.immocalc`-Sidecar wird mit umbenannt (kein harter Fehler,
    wenn das scheitert).

    Antwort: `{"ok": true, "alt": …, "neu": …, "pfad": …, "geaendert": <bool>}`.
    """
    d = dokument_holen(dokument_id, session, familie)
    if not d.pfad.startswith("/"):
        raise HTTPException(409, "Dieses Dokument liegt noch nicht in der "
                                 "Cloud — es lässt sich nicht umbenennen.")

    alt_name = d.dateiname
    alt_pfad = d.pfad
    # Jahr/Monat aus dem Belegdatum, mit Rückfall auf das gespeicherte Jahr und
    # den Namen — genug, um den Datumsteil vorn zu setzen.
    jahr, monat = datum_aus_namen(alt_name)
    if d.belegdatum:
        jahr, monat = d.belegdatum.year, d.belegdatum.month
    elif d.jahr:
        jahr = d.jahr
    # Die Bezeichnung aus dem Originalnamen bewahrt die Benennung des Nutzers.
    sache = _bezeichnung(alt_name)
    neu_name = dateiname(jahr, d.kategorie or "", sache, _endung(alt_name),
                         monat, d.betrag, d.kostenart or "")

    # Idempotent: heisst die Datei schon so, gibt es nichts zu tun.
    if neu_name == alt_name:
        return {"ok": True, "alt": alt_name, "neu": alt_name,
                "pfad": alt_pfad, "geaendert": False}

    ziel, frei = _im_ordner_umbenennen(session, d, neu_name)

    log.info("Umbenannt: %s → %s", alt_name, frei)
    return {"ok": True, "alt": alt_name, "neu": frei, "pfad": ziel,
            "geaendert": True}


# --------------------------------------------------------------------------
# N261: den Namen eines schon abgelegten Belegs nachträglich korrigieren
#
# Bis hierher liess sich ein Beleg nur auf den *errechneten* Standardnamen
# umbenennen (`POST …/umbenennen`) — was der Nutzer selbst schreiben wollte,
# hatte keinen Weg. Sein Versuch landete in der Betrags-Korrektur und stand
# danach als „_348_" im Dateinamen statt im Betrag.
#
# Beide Wege benutzen ab hier denselben Unterbau (`_im_ordner_umbenennen`) und
# dieselbe Namensregel (`dateiname`, die auch `/scannen` und
# `/namensvorschlag` benutzen). Eine Wahrheit, drei Aufrufer.
# --------------------------------------------------------------------------

class NameIn(BaseModel):
    """Nur der Sach-Teil des Namens — Datum und Betrag setzt `dateiname`."""
    beschreibung: str


@router.patch("/{dokument_id}/name")
def name_aendern(dokument_id: int, data: NameIn,
                 session: Session = Depends(get_session),
                 familie: Familie = Depends(aktuelle_familie)) -> dict:
    """N261 — Beleg nachträglich umbenennen, IM SELBEN ORDNER.

    Übergeben wird nur die Sache („Kaminkehrer Musterfirma"), nicht der ganze
    Dateiname: Datum vorn und Betrag hinten setzt `dateiname` selbst, aus den
    am Beleg gespeicherten Feldern. Deshalb kann der Name auch dann nicht
    auseinanderlaufen, wenn der Nutzer versehentlich einen Betrag mit
    hineinschreibt — er fällt aus der Sache heraus und steht danach genau
    einmal an seinem festen Platz.

    Der Ordner bleibt, wo er ist. Umgehängt (andere Immobilie, andere Art,
    anderes Jahr) wird über `PATCH /api/dokumente/{id}` — hier geht es allein
    um den Namen.

    Antwort: `{dateiname, pfad, geaendert}`."""
    d = dokument_holen(dokument_id, session, familie)
    if _ist_grabstein(d.pfad):
        # N242 — die Datei wurde in der Nextcloud gelöscht, der Eintrag lebt
        # nur noch als Grabstein weiter. Ein MOVE griffe ins Leere.
        raise HTTPException(409, "Diese Datei liegt nicht mehr in der Nextcloud "
                                 "— sie wurde dort gelöscht und lässt sich "
                                 "nicht umbenennen.")
    if not d.pfad.startswith("/"):
        raise HTTPException(409, "Dieses Dokument liegt noch nicht in der "
                                 "Cloud — es lässt sich nicht umbenennen.")

    endung = _endung(d.dateiname)
    sache = (data.beschreibung or "").strip()
    # Die Endung gehört nicht in die Sache. Nur die WIRKLICHE Endung dieser
    # Datei wird abgeschnitten — nicht am letzten Punkt getrennt, sonst
    # verstümmelte „Rechnung Fa. Müller" zu „Rechnung Fa".
    if endung and sache.lower().endswith(endung.lower()):
        sache = sache[:-len(endung)].strip()
    if not sache:
        raise HTTPException(400, "Bitte einen Namen für den Beleg angeben.")

    # Jahr/Monat aus dem Belegdatum, mit Rückfall auf das gespeicherte Jahr und
    # den bisherigen Namen — dieselbe Staffelung wie in `umbenennen`.
    jahr, monat = datum_aus_namen(d.dateiname)
    if d.belegdatum:
        jahr, monat = d.belegdatum.year, d.belegdatum.month
    elif d.jahr:
        jahr = d.jahr
    # Der Betrag steht am Beleg — und ersatzweise im bisherigen Namen; so geht
    # er beim Umbenennen nicht verloren.
    betrag = d.betrag or betrag_aus_namen(d.dateiname)
    neu_name = dateiname(jahr, d.kategorie or "", sache, endung, monat,
                         betrag, d.kostenart or "")

    # Idempotent: heisst die Datei schon so, wird die Cloud nicht angefasst.
    if neu_name == d.dateiname:
        return {"dateiname": d.dateiname, "pfad": d.pfad, "geaendert": False}

    ziel, frei = _im_ordner_umbenennen(session, d, neu_name)
    log.info("Beleg %s auf Wunsch umbenannt: %s", dokument_id, frei)
    return {"dateiname": frei, "pfad": ziel, "geaendert": True}


# --------------------------------------------------------------------------
# N24 — Batch-Migration bestehender Cloud-Dateien: „ohne-Jahr_"-Präfix raus,
# Lagepläne in ihren Sammelordner. Beide idempotent, kollisionssicher,
# rein additiv (nie überschreiben, nie löschen) und standardmäßig „trocken".
# --------------------------------------------------------------------------

@router.post("/praefix-entfernen")
def praefix_entfernen(trocken: bool = True,
                      session: Session = Depends(get_session)) -> dict:
    """N24 — entfernt das führende „ohne-Jahr_" aus Cloud-Dateinamen.

    Das Präfix ist ein alter Sortier-Vorsatz für Dateien ohne Jahr und hilft
    beim Wiederfinden nicht. Jede betroffene Datei wird IM SELBEN Ordner
    umbenannt (MOVE), kollisionssicher; die `.immocalc`-Sidecar wandert mit.
    Rein additiv: nie überschreiben, nie löschen.

    `?trocken=true` (Vorgabe) zeigt nur den Plan; erst `?trocken=false` führt
    aus. Idempotent: ein zweiter Lauf findet nichts mehr."""
    praefix = "ohne-Jahr_"
    # `.immocalc`-Steckbriefe sind Sidecars, keine Belege — sie wandern mit ihrem
    # Beleg (`_sidecar_mitnehmen`), nicht als eigener Eintrag. Sie hier zu
    # überspringen verhindert 404-Scheinfehler (die Datei ist schon mitgezogen).
    kandidaten = [d for d in session.exec(select(Dokument)).all()
                  if (d.pfad or "").startswith("/")
                  and (d.dateiname or "").startswith(praefix)
                  and not _ist_sidecar(d.dateiname)]
    if trocken:
        return {"trocken": True, "anzahl": len(kandidaten),
                "plan": [{"id": d.id, "alt": d.dateiname,
                          "neu": d.dateiname[len(praefix):]} for d in kandidaten]}
    client = verbindung(session)
    verschoben: list[dict] = []
    uebersprungen: list[int] = []
    fehler: list[dict] = []
    for d in kandidaten:
        neu = d.dateiname[len(praefix):]
        ordner = _elternordner(d.pfad)
        try:
            frei = _beleg_umziehen(session, client, d, ordner, neu)
        except Exception as e:                                # noqa: BLE001
            session.rollback()
            log.warning("Präfix nicht entfernt (%s): %s", d.pfad, e)
            fehler.append({"id": d.id, "name": d.dateiname, "grund": str(e)})
            continue
        if frei is None:
            uebersprungen.append(d.id)
        else:
            verschoben.append({"id": d.id, "neu": frei})
    log.info("Präfix-Bereinigung: %d verschoben, %d übersprungen, %d Fehler",
             len(verschoben), len(uebersprungen), len(fehler))
    return {"trocken": False, "verschoben": verschoben,
            "übersprungen": uebersprungen, "fehler": fehler}


@router.post("/lageplaene-einsortieren")
def lageplaene_einsortieren(trocken: bool = True,
                            session: Session = Depends(get_session)) -> dict:
    """N24/N9 — zieht bestehende Lagepläne in ihren Sammelordner
    „10_Fotos_Lage/00_Lagepläne" (dieselbe Ablage, die neue Lagepläne bekommen).

    Betrifft nur Belege mit `kategorie == "Lageplan"`, die noch woanders liegen
    (etwa im alten „99_Sonstiges"). Der Zielordner wird bei Bedarf angelegt
    (MKCOL, 405-sicher), dann MOVE — kollisionssicher, Sidecar wandert mit,
    nichts wird überschrieben oder gelöscht. `?trocken=true` zeigt nur den Plan."""
    kandidaten = [d for d in session.exec(
        select(Dokument).where(Dokument.kategorie == LAGEPLAN)).all()
        if (d.pfad or "").startswith("/")]
    client = verbindung(session)
    plan: list[tuple[Dokument, str, str]] = []
    for d in kandidaten:
        o = session.get(Objekt, d.objekt_id) if d.objekt_id else None
        if not o or not (o.nc_ordner or "").strip():
            continue
        sach, ablage = _ablageordner(session, o, LAGEPLAN, None, client)
        if _elternordner(d.pfad) == ablage.strip("/"):
            continue                                          # liegt schon richtig
        plan.append((d, sach, ablage))
    if trocken:
        return {"trocken": True, "anzahl": len(plan),
                "plan": [{"id": d.id, "name": d.dateiname, "ziel": ablage}
                         for d, _sach, ablage in plan]}
    verschoben: list[dict] = []
    fehler: list[dict] = []
    for d, sach, ablage in plan:
        try:
            _ordner_sichern(client, sach, ablage)
            _beleg_umziehen(session, client, d, ablage, d.dateiname)
        except Exception as e:                                # noqa: BLE001
            session.rollback()
            log.warning("Lageplan nicht einsortiert (%s): %s", d.pfad, e)
            fehler.append({"id": d.id, "name": d.dateiname, "grund": str(e)})
            continue
        verschoben.append({"id": d.id, "ziel": d.pfad})
    log.info("Lagepläne einsortiert: %d verschoben, %d Fehler",
             len(verschoben), len(fehler))
    return {"trocken": False, "verschoben": verschoben, "fehler": fehler}


# --------------------------------------------------------------------------
# Byte-gleiche Duplikate bündeln — inhaltsbasiert, unabhängig vom Dateinamen.
#
# Zwei verschieden benannte, aber byte-identische Dateien sind Duplikate. Statt
# eine davon zu löschen (nie löschen), wird eine „behalten"-Kopie am Platz
# gelassen und die übrigen der Gruppe in einen Sammel-Unterordner
# „99_Duplikate" verschoben — per MOVE über `_beleg_umziehen`, also
# kollisionssicher, mit Sidecar und DB-Eintrag, nie überschreiben.
#
# Byte-Gleichheit wird bewiesen, indem jede Datei geladen und selbst per SHA1
# gehasht wird — namensunabhängig und wirklich byte-genau, nicht über einen
# Namens- oder Größenvergleich. Nur eine Gruppe mit mehr als einer identischen
# Datei zählt; die einzige Kopie einer Datei wird nie bewegt.
#
# Idempotent: Dokumente, die bereits im „99_Duplikate"-Ordner liegen, werden von
# der Betrachtung ausgenommen — weder als „behalten"-Kandidat noch als zu
# verschieben. So findet ein zweiter Lauf keine Duplikate mehr und nichts wandert
# ein zweites Mal (keine Endlosverschiebung).
# --------------------------------------------------------------------------

@router.post("/objekte/{slug}/duplikate-buendeln")
def duplikate_buendeln(trocken: bool = True,
                       session: Session = Depends(get_session),
                       o: Objekt = Depends(objekt_holen)) -> dict:
    """Verschiebt byte-gleiche Duplikat-Belege in den Ordner „99_Duplikate".

    Inhaltsbasiert, unabhängig vom Dateinamen: jede Datei wird geladen und per
    SHA1 gehasht; nur wirklich byte-gleiche Belege gelten als Duplikat. Je Gruppe
    bleibt die beste Kopie am Platz (`_duplikat_rang`: verbucht > mit Zeitraum >
    kleinste id), die übrigen werden nach „99_Duplikate" verschoben (`_beleg_
    umziehen`: Datei + Sidecar + DB-Eintrag, kollisionssicher, nie überschreiben,
    nie löschen). Eine einzige/letzte Kopie wird nie bewegt.

    `?trocken=true` (Vorgabe): ändert nichts, liefert nur den Plan — je Gruppe
    `{sha1, behalten:{id,name}, verschieben:[{id,name}…]}`. `?trocken=false`:
    führt aus und liefert `{gebündelt, gruppen, fehler}`.

    Idempotent: Belege, die schon in „99_Duplikate" liegen, werden nicht erneut
    betrachtet — ein zweiter Lauf verschiebt nichts mehr.

    N436 — `o` kommt über `objekt_holen`, familiengrenzend."""
    _cloud_pflicht(o)
    client = verbindung(session)
    gruppen, fehler = _duplikat_gruppen(session, client, o)

    if trocken:
        return {
            "trocken": True,
            "gruppen": [{
                "sha1": sha1,
                "behalten": {"id": behalten.id, "name": behalten.dateiname},
                "verschieben": [{"id": d.id, "name": d.dateiname}
                                for d in verschieben],
            } for sha1, behalten, verschieben in gruppen],
        }

    ziel = _duplikat_ziel(o)
    gebuendelt = 0
    for _sha1, _behalten, verschieben in gruppen:
        for d in verschieben:
            try:
                _ordner_sichern(client, ziel, ziel)
                _beleg_umziehen(session, client, d, ziel, d.dateiname)
            except Exception as e:                            # noqa: BLE001
                session.rollback()
                log.warning("Duplikat nicht gebündelt (%s): %s", d.pfad, e)
                fehler.append({"id": d.id, "name": d.dateiname, "grund": str(e)})
                continue
            gebuendelt += 1
    log.info("Duplikate gebündelt für %s: %d verschoben, %d Gruppen, %d Fehler",
             o.slug, gebuendelt, len(gruppen), len(fehler))
    return {"gebündelt": gebuendelt, "gruppen": len(gruppen), "fehler": fehler}


# --------------------------------------------------------------------------
# N289 — Bestandsrechnungen eines Bauvorhabens nachträglich einsortieren.
#
# Neue Scans landen von selbst im Projektordner. Was der Nutzer vorher schon
# fotografiert hat, liegt aber noch unter „99_Sonstiges" — und soll nicht dort
# bleiben, nur weil es zu früh gescannt wurde. Derselbe Zuschnitt wie bei den
# Lageplänen (N24): idempotent, kollisionssicher, standardmäßig trocken.
# --------------------------------------------------------------------------

@router.post("/renovierungen/{rid}/einsortieren")
def renovierung_einsortieren(rid: int, trocken: bool = True,
                             session: Session = Depends(get_session),
                             familie: Familie = Depends(aktuelle_familie)) -> dict:
    """Zieht die Belege der Renovierung `rid` in ihren Projektordner.

    Betroffen sind genau die Belege, die an einem Posten dieser Renovierung
    hängen (`quelle_dokument_id`) — nichts wird geraten. Verschoben werden nur
    die, die noch woanders liegen; alles andere bleibt unberührt."""
    r = session.get(Renovierung, rid)
    if r is None:
        raise HTTPException(404, "Renovierung nicht gefunden")
    pruefe_familienbesitz(session, r, familie)
    ordner = projektordner(r.name, r.von)
    if not ordner:
        raise HTTPException(400, "Die Renovierung hat keinen brauchbaren Namen.")
    o = session.get(Objekt, r.objekt_id)
    if o is None or not (o.nc_ordner or "").strip():
        raise HTTPException(400, "Für diese Immobilie ist kein Cloud-Ordner "
                                 "hinterlegt.")

    ids = [p.quelle_dokument_id for p in session.exec(
        select(Renovierungsposten).where(Renovierungsposten.renovierung_id == rid)
    ).all() if p.quelle_dokument_id]
    belege = [d for d in (session.get(Dokument, i) for i in dict.fromkeys(ids))
              if d is not None and (d.pfad or "").startswith("/")]

    sach = _zielordner(o, "Renovierung")
    ablage = f"{sach}/{ordner}"
    plan = [d for d in belege if _elternordner(d.pfad) != ablage.strip("/")]
    if trocken:
        return {"trocken": True, "ziel": ablage, "anzahl": len(plan),
                "plan": [{"id": d.id, "name": d.dateiname, "von": d.pfad}
                         for d in plan]}

    client = verbindung(session)
    verschoben: list[dict] = []
    fehler: list[dict] = []
    for d in plan:
        try:
            _ordner_sichern(client, sach, ablage)
            _beleg_umziehen(session, client, d, ablage, d.dateiname)
        except Exception as e:                                # noqa: BLE001
            session.rollback()
            log.warning("Renovierungsbeleg nicht einsortiert (%s): %s", d.pfad, e)
            fehler.append({"id": d.id, "name": d.dateiname, "grund": str(e)})
            continue
        verschoben.append({"id": d.id, "ziel": d.pfad})
    log.info("Renovierung %d: %d Belege einsortiert, %d Fehler",
             rid, len(verschoben), len(fehler))
    return {"ziel": ablage, "verschoben": verschoben, "fehler": fehler}


# --------------------------------------------------------------------------
# N297 — die `.immocalc`-Steckbriefe aus der Ablage nehmen.
#
# Sie waren als menschenlesbare Beigabe neben jedem PDF gedacht (CCLXXIV), sind
# in der Praxis aber nur Unordnung: der Nutzer sieht in jedem Ordner doppelt so
# viele Dateien, und der Inhalt ist ein Abzug eines inzwischen deutlich
# weiterentwickelten Erkennungsstands.
#
# Es geht dabei nichts verloren. Der Steckbrief wurde aus den Feldern des
# Dokuments ERZEUGT (`_immocalc_text`) und im ganzen Code nie wieder
# eingelesen — jede Fundstelle schrieb, verschob, löschte oder filterte ihn nur
# aus den Ansichten. Die Auslese selbst steht in der Datenbank und seit N296
# zusätzlich am Dateiinhalt.
#
# Trotzdem standardmässig trocken: gelöscht wird in der Cloud des Nutzers, und
# er soll die Zahl vorher sehen. Erst `bestaetigt=true` vollzieht — dieselbe
# Haltung wie beim Leeren eines Objektordners (N287).
# --------------------------------------------------------------------------

@router.post("/immocalc-entfernen")
def immocalc_entfernen(bestaetigt: bool = False,
                       session: Session = Depends(get_session),
                       familie: Familie = Depends(aktuelle_familie)) -> dict:
    """Nimmt alle `.immocalc`-Steckbriefe aus den Objektordnern.

    Ohne `bestaetigt` wird nur gezählt und aufgelistet (Trockenlauf). Ein
    Ordner, der sich nicht lesen lässt, hält den Lauf nicht an — er wird
    gemeldet und übersprungen; nie wird auf Verdacht gelöscht.

    N436 — nur die Objektordner der angemeldeten Familie."""
    try:
        client = verbindung(session)
    except HTTPException:
        raise
    except Exception as fehler:                            # noqa: BLE001
        raise HTTPException(400, f"Keine Cloud-Verbindung: {fehler}") from fehler

    gefunden: list[str] = []
    hinweise: list[str] = []
    eigene_objekte = session.exec(
        select(Objekt).where(Objekt.familie_id == familie.id)).all()
    eigene_objekt_ids = {o.id for o in eigene_objekte}
    for o in eigene_objekte:
        wurzel = (o.nc_ordner or "").strip()
        if not wurzel:
            continue
        offen: list[tuple[str, int]] = [(wurzel, 0)]
        besucht: set[str] = set()
        while offen:
            ordner, tiefe = offen.pop()
            if ordner in besucht:
                continue
            besucht.add(ordner)
            try:
                eintraege = client.liste(ordner)
            except NextcloudFehler as fehler:
                hinweise.append(f"{ordner}: nicht lesbar ({fehler})")
                continue
            for e in eintraege:
                if e.ordner:
                    if tiefe < _IMMOCALC_MAX_TIEFE:
                        offen.append((e.pfad, tiefe + 1))
                elif _ist_sidecar(e.name):
                    gefunden.append(e.pfad)

    if not bestaetigt:
        return {"trocken": True, "anzahl": len(gefunden),
                "wuerde_loeschen": sorted(gefunden)[:200],
                "hinweise": hinweise}

    geloescht: list[str] = []
    fehlgeschlagen: list[dict] = []
    for pfad in gefunden:
        try:
            client.loesche(pfad)
            geloescht.append(pfad)
        except Exception as fehler:                        # noqa: BLE001
            fehlgeschlagen.append({"pfad": pfad, "grund": str(fehler)})

    # Auch die Einträge, die für eine Sidecar angelegt wurden, verschwinden —
    # sie zeigen jetzt ins Leere. Nur diese, nichts anderes.
    #
    # N436 — auf die Objekte der angemeldeten Familie eingegrenzt: ohne das
    # löschte dieser Lauf Sidecar-Einträge JEDER Familie mit, sobald irgendeine
    # Familie ihn einmal bestätigt aufrief.
    eintraege_weg = 0
    for d in list(session.exec(select(Dokument).where(
            Dokument.objekt_id.in_(eigene_objekt_ids))).all()
            if eigene_objekt_ids else []):
        if _ist_sidecar(d.dateiname or ""):
            session.delete(d)
            eintraege_weg += 1
    if eintraege_weg:
        session.commit()

    log.info("N297: %d Steckbriefe gelöscht, %d Fehler, %d Einträge entfernt",
             len(geloescht), len(fehlgeschlagen), eintraege_weg)
    return {"geloescht": len(geloescht), "eintraege_entfernt": eintraege_weg,
            "fehlgeschlagen": fehlgeschlagen, "hinweise": hinweise}


# --------------------------------------------------------------------------
# N298/N300/N301 — Duplikate finden und zusammenführen.
#
# Byte-gleiche Dateien entstehen im Alltag zwangsläufig: derselbe Beleg wird
# zweimal fotografiert, liegt in zwei Objektordnern, oder kommt nach einem
# Umsortieren erneut herein. Bisher liess sich dagegen nur „das eine löschen" —
# und das riss jede Verknüpfung, die an ihm hing (N300).
#
# Hier steht das Gegenteil: erst wandert jeder Verweis auf den Beleg, der
# bleibt, dann fällt der andere.
# --------------------------------------------------------------------------

@router.get("/duplikate")
def duplikate(session: Session = Depends(get_session),
             familie: Familie = Depends(aktuelle_familie)) -> dict:
    """Alle Belege, die sich eine Prüfsumme teilen — nach Gruppen.

    Grundlage ist `sha1` (N290). Belege ohne Prüfsumme bleiben aussen vor: der
    Abgleich trägt sie im 2-Minuten-Takt nach, und eine Vermutung anhand von
    Name oder Grösse wäre hier genau falsch — es geht ums Löschen.

    Grabsteine (extern gelöschte Belege) zählen nicht mit; sie haben keine
    Datei mehr, die doppelt liegen könnte.

    N436 — nur Objekte/Belege der angemeldeten Familie, sonst zeigte die
    Duplikat-Übersicht auch den Bestand fremder Familien."""
    objekte = {o.id: o for o in session.exec(
        select(Objekt).where(Objekt.familie_id == familie.id)).all()}
    eigene = (session.exec(select(Dokument).where(
        Dokument.objekt_id.in_(list(objekte.keys())))).all()
        if objekte else [])
    alle = [d for d in eigene
            if (d.sha1 or "").strip() and not _ist_grabstein(d.pfad)
            and not _ist_sidecar(d.dateiname or "")]
    nach_sha1: dict[str, list[Dokument]] = {}
    for d in alle:
        nach_sha1.setdefault(d.sha1, []).append(d)

    gruppen = []
    for sha1, kopien in nach_sha1.items():
        if len(kopien) < 2:
            continue
        # Vorn steht, wer die meisten Verknüpfungen trägt — das ist der
        # natürliche Kandidat zum BEHALTEN, und die Oberfläche wählt ihn vor.
        # Ein Beleg ganz ohne Verweise steht hinten; er ist der
        # unverfänglichste zum Wegwerfen.
        kopien.sort(key=lambda d: (-len(_verknuepfungen(session, d.id)), d.id))
        gruppen.append({
            "sha1": sha1, "groesse": kopien[0].groesse, "anzahl": len(kopien),
            "kopien": [_kopie_zeigen(session, d, objekte) for d in kopien],
        })
    # Die dicksten Gruppen zuerst — dort ist am meisten aufzuräumen.
    gruppen.sort(key=lambda g: (-g["anzahl"], g["kopien"][0]["dateiname"]))
    return {"gruppen": gruppen, "belege_mit_pruefsumme": len(alle),
            "belege_gesamt": len(eigene)}


class ZusammenfuehrenIn(BaseModel):
    weg_ids: list[int] = []
    # Die Zweitdatei in der Cloud mitentfernen. Vorgabe: ja — es ist eine
    # nachweislich byte-gleiche Kopie, und genau die will der Nutzer los.
    datei_loeschen: bool = True


@router.post("/{behalten_id}/zusammenfuehren")
def zusammenfuehren(behalten_id: int, data: ZusammenfuehrenIn,
                    session: Session = Depends(get_session),
                    familie: Familie = Depends(aktuelle_familie)) -> dict:
    """Führt Duplikate auf `behalten_id` zusammen — **ohne Verknüpfungen zu
    verlieren**.

    Reihenfolge, und nur diese: jeder Verweis wandert auf den Beleg, der
    bleibt; erst danach fällt der Eintrag des Duplikats. Umgekehrt entstünde
    genau der Zustand, den N300 beseitigt — ein Verweis auf eine tote Nummer.

    Geprüft wird vorher, dass die Prüfsummen übereinstimmen: zusammengeführt
    wird nur, was nachweislich derselbe Inhalt ist. Ohne Prüfsumme an einem der
    beiden bricht der Aufruf ab, statt zu raten.

    Die Datei in der Cloud wird nur entfernt, wenn `datei_loeschen` gesetzt ist
    — und auch dann erst, nachdem die Datenbank sauber ist.

    N436 — sowohl `behalten_id` als auch jede `weg_ids`-Nummer kommen über
    `dokument_holen`: ohne das liesse sich ein Beleg einer fremden Familie
    zusammenführen oder als „weg" verschwinden lassen."""
    behalten = dokument_holen(behalten_id, session, familie)
    weg_ids = [i for i in dict.fromkeys(data.weg_ids) if i != behalten_id]
    if not weg_ids:
        raise HTTPException(400, "Es ist kein zweiter Beleg angegeben.")
    if not (behalten.sha1 or "").strip():
        raise HTTPException(400, "Zu diesem Beleg gibt es noch keine Prüfsumme "
                                 "— der Abgleich trägt sie in wenigen Minuten "
                                 "nach.")

    wegzu: list[Dokument] = []
    for i in weg_ids:
        d = dokument_holen(i, session, familie)
        if (d.sha1 or "") != behalten.sha1:
            raise HTTPException(400, (
                f'„{d.dateiname}“ hat eine andere Prüfsumme als der Beleg, '
                'der bleiben soll — das sind nicht dieselben Dateien. Es wird '
                'nichts zusammengeführt.'))
        wegzu.append(d)

    umgehaengt = 0
    for d in wegzu:
        umgehaengt += dokumentlinks.haenge_um(session, d.id, behalten_id)
        # Eine Verbuchung des Duplikats darf nicht doppelt zählen — der
        # bleibende Beleg trägt die Kosten weiter.
        belegposten.loese(session, d)
    session.flush()
    # Probe vor dem Löschen: hängt wirklich nichts mehr?
    haengt_noch = {d.id: dokumentlinks.zaehle(session, d.id) for d in wegzu}
    offen = {i: s for i, s in haengt_noch.items() if s}
    if offen:
        session.rollback()
        raise HTTPException(500, (
            "Nach dem Umhängen zeigen noch Datensätze auf ein Duplikat "
            f"({offen}) — es wurde nichts gelöscht."))

    pfade = [d.pfad for d in wegzu]
    for d in wegzu:
        session.delete(d)
    session.commit()

    geloescht: list[str] = []
    fehler: list[dict] = []
    if data.datei_loeschen:
        try:
            client = verbindung(session)
        except Exception as fehler_v:                      # noqa: BLE001
            fehler.append({"pfad": "", "grund": str(fehler_v)})
            client = None
        for pfad in pfade if client else []:
            if not (pfad or "").startswith("/"):
                continue
            try:
                client.loesche(pfad)
                geloescht.append(pfad)
            except Exception as f:                         # noqa: BLE001
                fehler.append({"pfad": pfad, "grund": str(f)})

    log.info("N300: Belege %s auf %d zusammengeführt — %d Verweise umgehängt, "
             "%d Dateien gelöscht", weg_ids, behalten_id, umgehaengt,
             len(geloescht))
    return {"behalten": behalten_id, "verweise_umgehaengt": umgehaengt,
            "eintraege_entfernt": len(wegzu),
            "dateien_geloescht": len(geloescht), "fehler": fehler}


@router.get("/{dokument_id}/text")
def beleg_text(dokument_id: int, max_zeichen: int = Query(20000, ge=200, le=200000),
               session: Session = Depends(get_session),
               familie: Familie = Depends(aktuelle_familie)) -> dict:
    """N302 — der reine Text eines Belegs. Rein lesend, ohne KI, ohne Kosten.

    Gebraucht, damit die Auslese der Belege OHNE gespeicherte Einschätzung
    nachgetragen werden kann, ohne das API-Guthaben des Nutzers anzufassen —
    ausdrücklich sein Wunsch: „bitte über den Code-Prozess machen und nicht
    über die API."

    Ohne Textschicht kommt `text: ""` und `hat_text: false` zurück; dann hilft
    nur die Texterkennung (`/durchsuchbar`), und das sagt der Aufrufer selbst.
    Der Rumpf wird bewusst gekürzt: ein 40-seitiger Vertrag soll nicht in einer
    einzigen Antwort landen."""
    d, rohdaten = _hole_beleg_bytes(session, dokument_id, familie)
    # Die Prüfsumme kostet hier nichts mehr — die Bytes liegen vor (N290/N296).
    _pruefsumme_nachtragen(session, d, kicache.pruefsumme(rohdaten))
    text_roh = ocr.text_aus_beleg(rohdaten) or ""
    gekuerzt = len(text_roh) > max_zeichen
    return {
        "id": d.id, "dateiname": d.dateiname, "pfad": d.pfad,
        "kategorie": d.kategorie, "kostenart": d.kostenart,
        "jahr": d.jahr, "betrag": d.betrag,
        "belegdatum": d.belegdatum.isoformat() if d.belegdatum else None,
        "hat_ki": bool((d.ki_einordnung or "").strip() or d.ki_felder),
        "hat_text": bool(text_roh.strip()),
        "zeichen": len(text_roh),
        "gekuerzt": gekuerzt,
        "text": text_roh[:max_zeichen],
    }


@router.post("/{dokument_id}/text-nachtragen")
def text_nachtragen(dokument_id: int,
                    session: Session = Depends(get_session),
                    familie: Familie = Depends(aktuelle_familie)) -> dict:
    """N328(ii) — trägt `Dokument.erkannter_text` für einen Bestandsbeleg nach,
    der die Spalte noch nicht gefüllt hat (~667 Belege vor dieser Änderung).

    Idempotent: ist das Feld schon befüllt, passiert nichts und die Cloud wird
    gar nicht erst angefragt — ein zweiter/hundertster Aufruf für denselben
    Beleg kostet nichts. Rein lesend an der Nextcloud (`client.hole`, nie
    MKCOL/PUT/MOVE — derselbe Riegel wie überall sonst, hier greift er von
    selbst, weil nichts geschrieben wird).

    Ein einzelner unlesbarer oder unerkennbarer Beleg (fremdes Format, Datei
    in der Cloud fehlt, Tesseract stolpert) bricht die Anfrage NICHT ab —
    „ein leeres Feld ist besser als ein falscher Fehler": sie kommt mit
    `zeichen: 0` zurück, der Aufrufer schleift einfach zum nächsten Beleg
    weiter, ohne seine eigene Schleife abzusichern."""
    d = dokument_holen(dokument_id, session, familie)
    if (d.erkannter_text or "").strip():
        return {"id": d.id, "zeichen": len(d.erkannter_text), "neu": False}
    if not (d.pfad or "").startswith("/"):
        return {"id": d.id, "zeichen": 0, "neu": False,
                "hinweis": "Kein Cloud-Pfad hinterlegt"}
    client = verbindung(session)
    try:
        rohdaten, _typ = client.hole(d.pfad)
    except NextcloudFehler as e:
        log.info("Text-Nachtrag %s: Beleg nicht lesbar (%s)", dokument_id, e)
        return {"id": d.id, "zeichen": 0, "neu": False, "hinweis": str(e)}
    try:
        text = ocr.text_aus_beleg(rohdaten) or ""
    except Exception as fehler:                       # noqa: BLE001
        log.warning("Text-Nachtrag %s: Erkennung fehlgeschlagen: %s",
                   dokument_id, fehler)
        text = ""
    _pruefsumme_nachtragen(session, d, kicache.pruefsumme(rohdaten))
    if not text.strip():
        return {"id": d.id, "zeichen": 0, "neu": False}
    d.erkannter_text = text
    session.add(d)
    session.commit()
    return {"id": d.id, "zeichen": len(text), "neu": True}


@router.get("/ohne-auslese")
def ohne_auslese(session: Session = Depends(get_session),
                 familie: Familie = Depends(aktuelle_familie)) -> dict:
    """N302 — welche Belege noch gar keine KI-Einschätzung tragen.

    Die Arbeitsliste für das Nachtragen. Grabsteine und Steckbriefe bleiben
    aussen vor; sie haben keine Datei mehr bzw. sind keine Belege.

    N436 — nur Objekte/Belege der angemeldeten Familie."""
    objekte = {o.id: o for o in session.exec(
        select(Objekt).where(Objekt.familie_id == familie.id)).all()}
    eigene = (session.exec(select(Dokument).where(
        Dokument.objekt_id.in_(list(objekte.keys())))).all()
        if objekte else [])
    offen = []
    for d in eigene:
        if _ist_grabstein(d.pfad) or _ist_sidecar(d.dateiname or ""):
            continue
        if (d.ki_einordnung or "").strip() or d.ki_felder:
            continue
        o = objekte.get(d.objekt_id)
        offen.append({"id": d.id, "dateiname": d.dateiname, "pfad": d.pfad,
                      "kategorie": d.kategorie, "jahr": d.jahr,
                      "objekt": o.slug if o else "",
                      "groesse": d.groesse})
    offen.sort(key=lambda x: (x["objekt"], x["dateiname"]))
    return {"anzahl": len(offen), "belege": offen}


# --------------------------------------------------------------------------
# N303 — Prüfsummen für den Bestand nachrechnen.
#
# Der Abgleich übernimmt die Prüfsumme aus der Cloud (N290), aber Nextcloud
# liefert sie nur für Dateien, die ein Client MIT Prüfsummen-Kopfzeile
# hochgeladen hat. Gemessen: 47 von 692. Für die übrigen 93 % gäbe es damit
# keine Duplikatserkennung und keinen Auslese-Zwischenspeicher.
#
# Also einmal selbst rechnen: Datei holen, SHA1 bilden, am Beleg festhalten.
# Das kostet je Beleg einen Download, deshalb gedeckelt und wiederholbar —
# der Wachdienst holt in seinem ruhigen Takt ein Häppchen nach, bis nichts
# mehr offen ist. Rein lesend gegenüber der Cloud.
# --------------------------------------------------------------------------

def pruefsummen_nachtragen(session: Session, grenze: int = 40,
                           familie_id: int | None = None) -> dict:
    """Rechnet für bis zu `grenze` Belege ohne Prüfsumme den SHA1 aus.

    Ein Beleg, dessen Datei sich nicht holen lässt, wird übersprungen und
    gezählt — nie wird geraten und nie etwas geschrieben, das nicht aus den
    Bytes stammt.

    N436 — `familie_id=None` (der Wachdienst-Aufruf) läuft über jede Familie
    einzeln, mit ihrer eigenen Nextcloud-Verbindung; der HTTP-Endpunkt grenzt
    immer auf die angemeldete Familie ein."""
    if familie_id is None:
        teile = _je_familie(
            session, lambda fid: pruefsummen_nachtragen(session, grenze, fid))
        return {"nachgetragen": sum(t["nachgetragen"] for t in teile),
                "uebersprungen": sum(t["uebersprungen"] for t in teile),
                "noch_offen": sum(t["noch_offen"] for t in teile)}
    objekt_ids = [o.id for o in session.exec(
        select(Objekt).where(Objekt.familie_id == familie_id)).all()]
    kandidaten = session.exec(select(Dokument).where(
        Dokument.objekt_id.in_(objekt_ids))).all() if objekt_ids else []
    offen = [d for d in kandidaten
             if not (d.sha1 or "").strip()
             and (d.pfad or "").startswith("/")
             and not _ist_grabstein(d.pfad)
             and not _ist_sidecar(d.dateiname or "")]
    gesamt_offen = len(offen)
    if not offen:
        return {"nachgetragen": 0, "uebersprungen": 0, "noch_offen": 0}
    try:
        client = verbindung(session)
    except Exception as fehler:                            # noqa: BLE001
        log.info("Prüfsummen nicht nachtragbar: %s", fehler)
        return {"nachgetragen": 0, "uebersprungen": gesamt_offen,
                "noch_offen": gesamt_offen}

    nachgetragen = uebersprungen = 0
    for d in offen[:max(1, grenze)]:
        try:
            rohdaten, _typ = client.hole(d.pfad)
        except Exception as fehler:                        # noqa: BLE001
            log.info("Prüfsumme für %s nicht gebildet: %s", d.pfad, fehler)
            uebersprungen += 1
            continue
        d.sha1 = kicache.pruefsumme(rohdaten)
        d.groesse = d.groesse or len(rohdaten)
        session.add(d)
        nachgetragen += 1
    try:
        session.commit()
    except Exception as fehler:                            # noqa: BLE001
        session.rollback()
        log.warning("Prüfsummen nicht gespeichert: %s", fehler)
        return {"nachgetragen": 0, "uebersprungen": gesamt_offen,
                "noch_offen": gesamt_offen}
    log.info("N303: %d Prüfsummen nachgetragen, %d übersprungen, %d offen",
             nachgetragen, uebersprungen, gesamt_offen - nachgetragen)
    return {"nachgetragen": nachgetragen, "uebersprungen": uebersprungen,
            "noch_offen": gesamt_offen - nachgetragen}


@router.post("/pruefsummen-nachtragen")
def pruefsummen_nachtragen_endpunkt(
        grenze: int = Query(40, ge=1, le=500),
        session: Session = Depends(get_session),
        familie: Familie = Depends(aktuelle_familie)) -> dict:
    """Rechnet Prüfsummen für den Bestand nach — gedeckelt und wiederholbar.

    N436 — bisher ohne jede Familiengrenze: jede angemeldete Familie hätte
    Prüfsummen für JEDEN Beleg jeder anderen Familie mit auslösen können."""
    return pruefsummen_nachtragen(session, grenze, familie.id)


# --------------------------------------------------------------------------
# N286 — den Ablageordner eines Belegs von Hand ändern.
#
# Nutzer: „lass mich den Ordner auch einfach manuell ändern, falls es falsch
# ist und zieh dann natürlich die Verlinkung und Dings nach."
#
# Der Unterbau steht seit N261: `_beleg_umziehen` ändert **erst die Cloud, dann
# die Datenbank** und rollt zurück, wenn der zweite Schritt kippt. Hier kommt
# nur die Wahl des Ziels dazu — und der Riegel, dass sie den Objektordner nicht
# verlässt.
# --------------------------------------------------------------------------

@router.get("/{dokument_id}/ablageziele")
def ablageziele(dokument_id: int,
                session: Session = Depends(get_session),
                familie: Familie = Depends(aktuelle_familie)) -> dict:
    """Wohin dieser Beleg wandern könnte — je Dokumentart ein Vorschlag.

    Rein lesend. `aktuell` markiert den Ordner, in dem er gerade liegt; die
    Oberfläche kann ihn damit vorwählen und muss nicht raten."""
    d = dokument_holen(dokument_id, session, familie)
    o = session.get(Objekt, d.objekt_id) if d.objekt_id else None
    if o is None:
        raise HTTPException(400, "Zum Beleg gehört keine Immobilie.")
    _cloud_pflicht(o)
    jetzt = _elternordner(d.pfad)
    moeglich = []
    for art in struktur_fuer(o):
        ordner = f"{o.nc_ordner.strip('/')}/{art}"
        moeglich.append({"ordner": ordner, "name": hauptordner_lesbar(art),
                         "aktuell": ordner == jetzt})
    # Der Jahresordner der Nebenkosten ist der einzige, den die App selbst
    # anlegt (N285) — er gehört mit angeboten, sonst müsste der Nutzer ihn
    # tippen.
    if d.jahr:
        nk = f"{o.nc_ordner.strip('/')}/{ZIELORDNER['Nebenkosten']}/{d.jahr}"
        moeglich.append({"ordner": nk, "name": f"Nebenkosten · {d.jahr}",
                         "aktuell": nk == jetzt})
    return {"id": d.id, "dateiname": d.dateiname, "pfad": d.pfad,
            "aktueller_ordner": jetzt, "objekt": o.slug,
            "wurzel": o.nc_ordner.strip("/"), "ziele": moeglich}


class VerschiebenIn(BaseModel):
    # Entweder ein fertiger Ordner (aus `ablageziele`) …
    ordner: str = ""
    # … oder eine Dokumentart, aus der er abgeleitet wird.
    kategorie: str = ""
    jahr: int | None = None


@router.post("/{dokument_id}/verschieben")
def verschieben(dokument_id: int, data: VerschiebenIn,
                session: Session = Depends(get_session),
                familie: Familie = Depends(aktuelle_familie)) -> dict:
    """Schiebt einen Beleg in einen anderen Ordner — Datei und Eintrag zusammen.

    Erst die Cloud, dann die Datenbank; kippt der zweite Schritt, wandert die
    Datei zurück (`_beleg_umziehen`). Der Dateiname bleibt, nur der Ort ändert
    sich — und weicht auf „…-2" aus, falls dort schon etwas gleich heisst. Nie
    überschreiben, nie löschen.

    Die Verknüpfungen ziehen von selbst nach: sie hängen an `dokument.id`, nicht
    am Pfad (N300). Nachgezogen werden muss nur die Pfadkopie in der
    Wissensdatenbank — das erledigt `_beleg_umziehen` über `kidb` (N299)."""
    d = dokument_holen(dokument_id, session, familie)
    if not (d.pfad or "").startswith("/"):
        raise HTTPException(400, "Zu diesem Eintrag liegt keine Datei in der "
                                 "Cloud.")
    # Erst die Anfrage prüfen, dann die Infrastruktur: das kostet nichts, sagt
    # dem Nutzer das Genauere („kein Ziel angegeben" statt „keine Cloud") und
    # baut keine Verbindung auf, die ohnehin nichts zu tun bekäme.
    if not data.ordner and not data.kategorie:
        raise HTTPException(400, "Es ist kein Ziel angegeben.")
    if data.kategorie and data.kategorie not in ZIELORDNER:
        raise HTTPException(400, f"Unbekannte Dokumentart „{data.kategorie}“.")

    o = session.get(Objekt, d.objekt_id) if d.objekt_id else None
    if o is None:
        raise HTTPException(400, "Zum Beleg gehört keine Immobilie.")
    _cloud_pflicht(o)

    client = verbindung(session)
    if data.ordner:
        ziel = _ziel_im_objekt(o, data.ordner)
    else:
        _sach, ziel = _ablageordner(session, o, data.kategorie,
                                    data.jahr if data.jahr else d.jahr, client)

    alt = d.pfad
    try:
        client.ordner_anlegen(ziel)
        neu_name = _beleg_umziehen(session, client, d, ziel, d.dateiname)
    except NextcloudFehler as fehler:
        raise HTTPException(400, str(fehler)) from fehler

    if neu_name is None:
        return {"verschoben": False, "pfad": d.pfad,
                "hinweis": "Der Beleg liegt bereits dort."}
    # Die Dokumentart mitziehen, wenn der Nutzer über sie gewählt hat — sonst
    # stünde im Beleg weiter die alte Art, während die Datei woanders liegt.
    if data.kategorie and d.kategorie != data.kategorie:
        d.kategorie = data.kategorie
        session.add(d)
        session.commit()
    log.info("N286: Beleg %s von %s nach %s verschoben", d.id, alt, d.pfad)
    return {"verschoben": True, "von": alt, "pfad": d.pfad,
            "dateiname": d.dateiname, "kategorie": d.kategorie}
