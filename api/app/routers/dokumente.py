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
import logging
import re
import unicodedata
from datetime import date
from urllib.parse import quote

from fastapi import (APIRouter, Depends, File, Form, HTTPException, Response,
                     UploadFile)
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from .. import belegposten, ocr, pdftext
from ..belegposten import BelegFehler
from ..bezeichnung import (betrag_aus_namen, betragsteil, datum_aus_namen,
                           datumsteil, ohne_betrag, ohne_datum,
                           ohne_ordnerwort, unterordner_finden, vergleichsname)
from ..cloudkern import (ARTKUERZEL, STRUKTUR, ZIELORDNER, unterordner_fuer,
                        verbindung)
from ..db import get_session
from ..migrate import eindeutigkeit_sichern
from ..models import Dokument, Erkennungsregel, Objekt, Zeitraum
from ..verteilung import UnbekannterSchluessel
from ..nextcloud import NextcloudFehler
from ..wachdienst import sperre
from ..wachdienst import zustand as wachdienst_zustand

log = logging.getLogger("immocalc")
router = APIRouter(prefix="/api/dokumente", tags=["dokumente"])

DOKUMENTARTEN = list(ZIELORDNER.keys())

# Status eines Eintrags, dessen Datei beim Abgleich nicht mehr auffindbar war
# (CXXVII). Ein vierter Wert neben "neu" und "zugeordnet" — additiv, das
# Datenmodell bleibt unverändert. Kommt die Datei zurück, fällt er wieder weg.
VERMISST = "vermisst"


def _saubere_datei(text_: str) -> str:
    """Ein Stück Dateiname: keine Pfadtrenner, keine Trennzeichen am Rand.

    Unerlaubte Zeichen werden zum Bindestrich, nicht gelöscht — sonst klebte
    aus „231€+10€+180€" ein „23110180" zusammen und aus „Fitness&Büro" ein
    „FitnessBüro"."""
    text_ = re.sub(r"[^\wäöüÄÖÜß.\- ]+", "-", text_ or "").strip()
    text_ = re.sub(r"\s+", "-", text_)
    # Wo etwas herausgeschnitten wurde — Datum, Betrag, Ordnerwort —, blieben
    # sonst "--", "_-" oder ".-" stehen.
    return re.sub(r"[-_.]{2,}", "-", text_).strip("-_.")


def dateiname(jahr: int | None, kategorie: str, beschreibung: str,
              endung: str, monat: int | None = None,
              betrag: float | None = None, kostenart: str = "") -> str:
    """JJJJ-MM_Sache_1234,56€.pdf — drei Stücke, jedes genau einmal.

    * **Datum vorn.** Nur so sortiert sich der Ordner von selbst; der Monat
      kommt mit, sobald er bekannt ist.
    * **Die Sache in der Mitte** — und nur, was der Ordner *nicht* schon sagt
      (CXXII): im Ordner 60_Nebenkosten heisst nichts „…_Nebenkosten_…".
      Was der Nutzer selbst benannt hat, bleibt dabei stehen (XCVII); erkannt
      wird nur, was sonst niemand beisteuert.
    * **Der Betrag hinten** (CXXIII), damit man ihn im Ordner sofort sieht.

    Die Funktion ist absichtlich idempotent: ein Name, der schon so aussieht,
    kommt unverändert wieder heraus. Beim Korrigieren wird der bestehende Name
    zerlegt und neu gesetzt — ohne das ginge bei jeder Änderung des Jahres die
    Bezeichnung samt Betrag verloren.
    """
    roh = ohne_datum(ohne_betrag(beschreibung or ""))
    sache = _saubere_datei(ohne_ordnerwort(roh, kategorie))
    # Der Name bleibt idempotent: steht das Kürzel schon vorn — weil dieser
    # Name schon einmal durch diese Funktion lief —, wird es nicht doppelt
    # gesetzt („NK-NK-Kaminkehrer").
    vorn = ARTKUERZEL.get(kategorie, "")
    if vorn and _kern(sache).startswith(_kern(vorn)):
        sache = sache[len(vorn):].lstrip("-_ ") or sache
    # Die Kostenposition sagt genauer, worum es geht, als eine Bezeichnung wie
    # „Rechnung": aus 2026-02_Rechnung wird 2026-02_NK-Schornsteinfeger.
    # Heisst die Position wie die Art („Nebenkosten" unter Nebenkosten), sagt
    # sie nichts Neues — das Kürzel steht ohnehin schon vorn.
    if kostenart and _kern(kostenart) != _kern(kategorie):
        genau = _saubere_datei(kostenart)
        # „Wasser" unter der Position „Wasser" braucht nicht zweimal dazustehen
        doppelt = _kern(sache) and _kern(sache) in _kern(genau)
        sache = (genau if not sache or _sagt_nichts(sache) or doppelt
                 else f"{genau}-{sache}")
    kuerzel = ARTKUERZEL.get(kategorie, "")
    mitte = f"{kuerzel}-{sache}" if kuerzel and sache else (sache or kuerzel)
    teile = [datumsteil(jahr, monat), mitte or "Beleg", betragsteil(betrag)]
    return "_".join(t for t in teile if t) + endung


# Wörter, die jeder Beleg trägt und die niemandem beim Wiederfinden helfen.
# Steht nur so etwas da, tritt die Kostenposition an ihre Stelle.
_NICHTSSAGEND = {"rechnung", "beleg", "scan", "dokument", "schreiben",
                 "abrechnung", "jahresabrechnung", "kopie", "pdf"}


def _kern(text: str) -> str:
    """Vergleichsform für Kürzel/Kostenart/Sache (CCXXII).

    Dasselbe wie `bezeichnung.vergleichsname` — dort für Ordnernamen gedacht,
    hier für die Bausteine des Dateinamens wiederverwendet, damit es nicht
    zweimal dieselbe Regel gibt. Ziffern bleiben absichtlich erhalten (wie
    dort): ein `§35a` in einer Kostenart soll nicht mit einem beliebigen
    zufällig anderen Textfetzen verwechselt werden, nur weil beide nach dem
    Entfernen der Ziffern gleich aussehen."""
    return vergleichsname(text)


def _sagt_nichts(text: str) -> bool:
    """Ist das nur ein Allerweltswort wie „Rechnung"?"""
    return _kern(text) in _NICHTSSAGEND


def _endung(name: str) -> str:
    return ("." + name.rsplit(".", 1)[-1]) if "." in name else ""


# --------------------------------------------------------------------------
# Vermutung und Darstellung
# --------------------------------------------------------------------------

def _art_im_namen(lesbar: str) -> str:
    """Steht die Art wörtlich im Namen („2024_Steuer_…"), gilt sie.

    Ab Wortanfang gesucht — sonst macht „Steuerberater" jede Post zur
    Steuerakte und „Nebenkostenwiderspruch" bliebe zufällig richtig."""
    for art in DOKUMENTARTEN:
        if re.search(r"\b" + re.escape(art.lower()), lesbar):
            return art
    return ""


def _vorschlag(d: Dokument) -> dict:
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


def _zeige(d: Dokument, objekte: dict[int, Objekt]) -> dict:
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
        "vorschlag": _vorschlag(d),
    }


# --------------------------------------------------------------------------
# Ablegen in der Cloud — eine Stelle für Zuordnen, Korrigieren und Automatik
# --------------------------------------------------------------------------

def _pfad_vergeben(session: Session, pfad: str) -> bool:
    """Zeigt schon ein Eintrag dorthin? Der Unique-Index würde es später
    ohnehin verhindern — nur dann läge die Datei bereits am neuen Platz und
    die Datenbank am alten. Also vorher fragen."""
    ohne = pfad.strip("/")
    return session.exec(
        select(Dokument).where(Dokument.pfad.in_((f"/{ohne}", ohne)))).first() is not None


def _freier_name(session: Session, client, ordner: str, name: str) -> str:
    """Haengt -2, -3 an, falls der Name schon vergeben ist — nie ueberschreiben.

    Gefragt wird in der Cloud *und* in der Datenbank. Hat der Nutzer die Datei
    dort gelöscht, ist der Platz in der Cloud frei, der Eintrag zeigt aber
    weiter darauf — ohne diese zweite Frage verschöbe die Automatik die Datei
    und scheiterte danach am Eintrag."""
    stamm, punkt, endung = name.rpartition(".")
    stamm = stamm or name
    endung = f".{endung}" if punkt else ""
    kandidat, n = name, 2
    while (client.existiert(f"{ordner}/{kandidat}")
           or _pfad_vergeben(session, f"{ordner}/{kandidat}")):
        kandidat = f"{stamm}-{n}{endung}"
        n += 1
        if n > 50:
            break
    return kandidat


def _zielordner(o: Objekt, kategorie: str) -> str:
    """Der Sachordner der Immobilie — „…/60_Nebenkosten"."""
    unterordner = ZIELORDNER.get(kategorie, "99_Sonstiges")
    if unterordner not in STRUKTUR:
        raise HTTPException(400, f"Unbekannter Zielordner '{unterordner}'")
    return f"{o.nc_ordner.strip('/')}/{unterordner}"


def _ablageordner(session: Session, o: Objekt, kategorie: str,
                  jahr: int | None, client) -> tuple[str, str]:
    """(Sachordner, Ablageordner) — CXCI: in NK liegt nichts mehr flach.

    Der Ablageordner ist der Sachordner selbst, solange die Vorlage nichts
    hergibt (leere Vorlage, Beleg ohne Jahr). Sonst der Jahresordner darin —
    und zwar **der vorhandene**, wenn es ihn schon gibt: liegt „2025" da,
    wandert der Beleg dorthin und nicht in ein zweites „2025_Nebenkosten".

    Lässt sich der Sachordner nicht auflisten (er ist meist noch gar nicht
    angelegt), wird der Name aus der Vorlage genommen — das ist kein Fehler,
    nur eine Auskunft, die es noch nicht gibt."""
    sach = _zielordner(o, kategorie)
    ziel = unterordner_fuer(session, o, kategorie, jahr)
    if not ziel:
        return sach, sach
    try:
        vorhandene = [e.name for e in client.liste(sach) if e.ordner]
    except NextcloudFehler as fehler:
        log.info("Unterordner von %s nicht gelesen: %s", sach, fehler)
        vorhandene = []
    treffer = unterordner_finden(vorhandene, jahr, ziel,
                                 (kategorie, ARTKUERZEL.get(kategorie, "")))
    return sach, f"{sach}/{treffer or ziel}"


def _ordner_sichern(client, sach: str, ordner: str) -> None:
    """Legt Sach- und Ablageordner an. MKCOL verträgt 405 (existiert schon),
    und der tiefere Ordner braucht seinen Eltern vorher."""
    client.ordner_anlegen(sach)
    if ordner != sach:
        client.ordner_anlegen(ordner)


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
    """Legt einen Eingangseintrag an. `None`, wenn es ihn schon gibt."""
    if session.exec(select(Dokument)
                    .where(Dokument.pfad == eintrag.pfad)).first():
        return None
    d = Dokument(pfad=eintrag.pfad, dateiname=eintrag.name,
                 groesse=eintrag.groesse, objekt_id=o.id, status="neu",
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


def _bezeichnung(name: str) -> str:
    """Der ursprüngliche Name als Bezeichnung — ohne Endung, Datum und Betrag.

    Ohne sie hießen alle Belege eines Jahres gleich: aus
    „Grundsteuerbescheid 2024.pdf" wurde „2024_Steuer.pdf" und aus dem
    zweiten Bescheid „2024_Steuer-2.pdf". Was der Nutzer selbst benannt hat,
    bleibt erhalten (XCVII).

    Datum und Betrag fallen hier heraus, weil `dateiname` sie an ihrem festen
    Platz neu setzt — vorn und hinten. Sonst stünden sie zweimal da."""
    stamm = name.rsplit(".", 1)[0] if "." in name else name
    return ohne_datum(ohne_betrag(stamm))


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
def scan(session: Session = Depends(get_session)) -> dict:
    """Liest die Objektordner in der Nextcloud und nimmt neue Dateien auf.

    Läuft nie zweimal gleichzeitig: der Wachdienst und dieser Handlauf teilen
    sich eine Sperre. Wer zu spät kommt, wartet nicht — er bekommt Bescheid,
    denn der andere Lauf liest ohnehin gerade dieselben Ordner."""
    if not sperre.acquire(blocking=False):
        raise HTTPException(409, "Der Eingang wird gerade geprüft — "
                                 "einen Moment, dann noch einmal versuchen.")
    try:
        return _scanne(session)
    finally:
        sperre.release()


def _scanne(session: Session) -> dict:
    _eindeutigkeit_sichern(session)
    client = verbindung(session)
    neu = automatisch = 0
    for o in session.exec(select(Objekt)).all():
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
#   * Datei nirgends mehr              -> Status `vermisst`, sonst nichts
#
# Gelöscht wird nichts, weder in der Cloud noch in der Datenbank: ein Eintrag
# kann Zeitraum und Zuordnung tragen, die der Nutzer mühsam gesetzt hat. Er
# wird gekennzeichnet und gemeldet, entfernen darf ihn nur der Nutzer.
# Angestossen wird das ausdrücklich — der Wachdienst rührt es nie an.
# --------------------------------------------------------------------------

# Wie tief unter dem Objektordner gesucht wird. ImmoCalc legt eine Ebene an;
# der Nutzer schachtelt darunter selbst weiter ("60_Nebenkosten/2025/").
ABGLEICH_TIEFE = 4


def _norm(pfad: str) -> str:
    """Vergleichsform eines Cloud-Pfades: führender Trenner, keiner am Ende."""
    return "/" + "/".join(t for t in (pfad or "").split("/") if t)


def _elternteil(pfad: str) -> str:
    return _norm(pfad).rsplit("/", 1)[0] or "/"


def _baum(client, wurzel: str, tiefe: int = ABGLEICH_TIEFE) -> dict:
    """Alle Dateien unterhalb eines Ordners, nach Pfad. Rein lesend.

    Ein *Unterordner*, der sich nicht lesen lässt, hält den Abgleich nicht an;
    er wird protokolliert, der Rest wird trotzdem geprüft. Der Objektordner
    selbst dagegen schon: käme dort eine leere Liste zurück, weil die Cloud
    gerade nicht antwortet, gälten mit einem Schlag alle Belege als vermisst.
    Deshalb reicht sein Fehler nach oben durch."""
    gefunden: dict = {}
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
        for e in eintraege:
            if e.ordner:
                if ebene < tiefe:
                    offen.append((_norm(e.pfad), ebene + 1))
            else:
                gefunden[_norm(e.pfad)] = e
    return gefunden


def _einziger(kandidaten: list[str]) -> str:
    """Genau ein Treffer zählt. Bei mehreren wird nicht geraten — zwei gleich
    heissende Dateien lassen sich nicht auseinanderhalten, und ein falsch
    umgehängter Eintrag ist schlimmer als ein gemeldeter."""
    return kandidaten[0] if len(kandidaten) == 1 else ""


def _wiedergefunden(d: Dokument, frei: dict, vergeben: set[str]) -> tuple[str, str]:
    """Wohin die Datei gewandert ist: (Pfad, Art) oder ("", "").

    Zuerst nach dem Namen — verschieben ist der häufigere Fall und der
    sicherere Schluss. Danach nach Ordner und Grösse: dieselbe Datei, im
    selben Ordner, nur anders benannt."""
    name = d.dateiname.lower()
    gleicher_name = [p for p, e in frei.items()
                     if e.name.lower() == name and p not in vergeben]
    treffer = _einziger(gleicher_name)
    if treffer:
        return treffer, "verschoben"

    if d.groesse:
        ordner = _elternteil(d.pfad)
        gleiche_datei = [p for p, e in frei.items()
                         if e.groesse == d.groesse and _elternteil(p) == ordner
                         and p not in vergeben]
        treffer = _einziger(gleiche_datei)
        if treffer:
            return treffer, "umbenannt"
    return "", ""


def _abgleiche_objekt(session: Session, o: Objekt, eigene: list[Dokument],
                      dateien: dict, vergeben: set[str],
                      trocken: bool) -> dict:
    """Zieht die Einträge einer Immobilie an den Stand der Cloud nach."""
    ergebnis: dict[str, list] = {"verschoben": [], "umbenannt": [],
                                 "vermisst": [], "wiederda": []}
    unveraendert = 0

    # Erst alle, die noch an ihrem Platz liegen — sie belegen ihre Datei,
    # bevor die Suche nach den Umgezogenen beginnt.
    offen: list[Dokument] = []
    for d in eigene:
        if _norm(d.pfad) in dateien:
            vergeben.add(_norm(d.pfad))
            unveraendert += 1
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
        d.pfad = ziel
        d.dateiname = dateien[ziel].name
        if d.status == VERMISST:
            d.status = "zugeordnet" if d.kategorie else "neu"
        session.add(d)

    ergebnis["unveraendert"] = unveraendert
    return ergebnis


def _kurz(d: Dokument, o: Objekt) -> dict:
    """Ein Eintrag, so knapp wie die Rückmeldung ihn braucht."""
    return {"id": d.id, "dateiname": d.dateiname, "pfad": d.pfad,
            "objekt": o.slug, "objekt_name": o.name}


def _abgleiche(session: Session, trocken: bool) -> dict:
    """Ein vollständiger Durchgang über alle verknüpften Objektordner."""
    _eindeutigkeit_sichern(session)
    client = verbindung(session)
    zusammen: dict[str, list] = {"verschoben": [], "umbenannt": [],
                                 "vermisst": [], "wiederda": []}
    unveraendert = geprueft = ohne_eintrag = neu = automatisch = 0
    hinweise: list[str] = []
    # Über alle Immobilien hinweg: eine Datei gehört immer nur einem Eintrag.
    vergeben = {_norm(d.pfad) for d in session.exec(select(Dokument)).all()}

    for o in session.exec(select(Objekt)).all():
        if not o.nc_ordner:
            continue
        try:
            dateien = _baum(client, o.nc_ordner)
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

        teil = _abgleiche_objekt(session, o, eigene, dateien, vergeben, trocken)
        for schluessel in zusammen:
            zusammen[schluessel] += teil[schluessel]
        unveraendert += teil["unveraendert"]

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
        "neu": neu,
        "automatisch": automatisch,
        "offen": neu - automatisch,
        # Dateien in der Cloud, zu denen es keinen Eintrag gibt. Nur eine
        # Zahl: aufgenommen wird weiterhin nur, was lose im Hauptordner
        # liegt — der gewachsene Bestand in den Unterordnern gehört dem
        # Nutzer und wird nicht ungefragt in die Ablage gezogen.
        "ohne_eintrag": ohne_eintrag,
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
def abgleich_plan(session: Session = Depends(get_session)) -> dict:
    """Trockenlauf: was ein vollständiges Neueinlesen ändern würde.

    Ändert nichts — weder in der Cloud noch in der Datenbank."""
    if not sperre.acquire(blocking=False):
        raise HTTPException(409, "Der Eingang wird gerade geprüft — "
                                 "einen Moment, dann noch einmal versuchen.")
    try:
        return _abgleiche(session, trocken=True)
    finally:
        sperre.release()


@router.post("/abgleich")
def abgleich(session: Session = Depends(get_session)) -> dict:
    """Liest die Objektordner vollständig neu ein (CXXVII).

    Neue Dateien kommen herein, umgezogene Einträge ziehen mit, und was in der
    Cloud nicht mehr auffindbar ist, wird als `vermisst` gekennzeichnet statt
    stillschweigend weiterzuleben. Gelöscht wird nichts."""
    if not sperre.acquire(blocking=False):
        raise HTTPException(409, "Der Eingang wird gerade geprüft — "
                                 "einen Moment, dann noch einmal versuchen.")
    try:
        ergebnis = _abgleiche(session, trocken=False)
    finally:
        sperre.release()
    log.info("Abgleich: %d geprüft, %d vermisst, %d umgehängt, %d neu",
             ergebnis["geprueft"], len(ergebnis["vermisst"]),
             len(ergebnis["verschoben"]) + len(ergebnis["umbenannt"]),
             ergebnis["neu"])
    return ergebnis


# --------------------------------------------------------------------------
# Liste mit Filtern — eine Ansicht für Eingang und Ablage
# --------------------------------------------------------------------------

@router.get("")
def liste(objekt: str = "", kategorie: str = "", jahr: int | None = None,
          status: str = "", suche: str = "", zeitraum: int | None = None,
          session: Session = Depends(get_session)) -> dict:
    """Alle Dokumente, gefiltert. Die Auswahlwerte kommen mit — die Oberfläche
    baut ihre Filter aus dem, was wirklich da ist."""
    objekte = {o.id: o for o in session.exec(select(Objekt)).all()}
    nach_slug = {o.slug: o for o in objekte.values()}
    alle = session.exec(select(Dokument)).all()

    if objekt and objekt not in nach_slug:
        raise HTTPException(404, "Objekt nicht gefunden")
    ziel_id = nach_slug[objekt].id if objekt else None
    begriff = suche.strip().lower()

    def passt(d: Dokument) -> bool:
        return ((not ziel_id or d.objekt_id == ziel_id)
                and (not kategorie or d.kategorie == kategorie)
                and (jahr is None or d.jahr == jahr)
                and (not status or d.status == status)
                and (zeitraum is None or d.zeitraum_id == zeitraum)
                and (not begriff or begriff in d.dateiname.lower()))

    gefiltert = [d for d in alle if passt(d)]
    # Offenes zuerst, dann Vermisstes, danach das Neueste — so steht oben,
    # was etwas will.
    rang = {"neu": 0, VERMISST: 1}
    gefiltert.sort(key=lambda d: (rang.get(d.status, 2), -(d.jahr or 0),
                                  d.dateiname.lower()))

    genutzt = {d.kategorie for d in alle if d.kategorie}
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
        "jahre": jahre,
        "objekte": [{"slug": o.slug, "name": o.name,
                     "anzahl": je_objekt.get(o.id, 0),
                     "cloud": bool(o.nc_ordner)}
                    for o in objekte.values()],
        "dokumente": [_zeige(d, objekte) for d in gefiltert],
    }


@router.get("/objekt/{slug}")
def je_objekt(slug: str, session: Session = Depends(get_session)) -> list[dict]:
    """Die zugeordneten Dokumente einer Immobilie — dieselbe Auswahl wie
    `?objekt=…&status=zugeordnet`, nur als schlichte Liste für Aufrufer, die
    keine Filterwerte brauchen."""
    return liste(objekt=slug, status="zugeordnet", session=session)["dokumente"]


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


@router.post("/erkennen")
async def erkennen(datei: UploadFile = File(...),
                   session: Session = Depends(get_session)) -> dict:
    """Liest Betrag, Datum und Art aus einer Aufnahme oder einem PDF.

    Die Erkennungsregeln des Nutzers haben Vorrang: trifft ein Muster, gilt
    dessen Richtung. Nichts wird gespeichert."""
    rohdaten = await datei.read()
    if not rohdaten:
        raise HTTPException(400, "Leere Datei")
    return ocr.erkenne(rohdaten, _regeln(session))


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
        d.kostenart = art or ""
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


def _ocr_kandidaten(session: Session) -> list[Dokument]:
    """PDFs, die noch keine Textschicht haben könnten.

    Vermisste Einträge fallen weg — ihre Datei ist ja nicht mehr da (CXXVII).
    Alles andere wird angesehen; ob wirklich OCR nötig ist, entscheidet erst
    `ocr.durchsuchbar_machen` anhand des eingebetteten Texts."""
    return list(session.exec(
        select(Dokument)
        .where(Dokument.status != VERMISST)
        .where(Dokument.dateiname.ilike("%.pdf"))
        .order_by(Dokument.id)
        .limit(OCR_PRUEF_GRENZE)))


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


def nachtraeglich_ocren(session: Session, client=None) -> dict:
    """Ein Nachpflege-Lauf: legt liegen gebliebenen Scans ihre Textschicht
    unter. Vom Wachdienst gerufen, nie vom Upload selbst.

    Rein additiv gegenüber dem normalen Betrieb: ein Beleg, der schon Text
    trägt — ob von Anfang an oder aus einem früheren Lauf —, wird nie
    zweimal angefasst. Fehlen die Bibliotheken (rapidocr-onnxruntime,
    PyMuPDF), meldet der erste Blick das sofort, und es passiert nichts."""
    ergebnis = {"geprueft": 0, "ergaenzt": 0, "uebersprungen": 0}
    if not ocr.durchsuchbar_verfuegbar():
        return ergebnis
    client = client or verbindung(session)
    for d in _ocr_kandidaten(session):
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

def _eindeutiges_objekt(session: Session, slug: str) -> Objekt:
    """Die gemeinte Immobilie. Ohne Angabe nur dann, wenn es genau eine gibt —
    raten wäre hier keine Hilfe, sondern eine falsche Ablage."""
    if slug:
        o = session.exec(select(Objekt).where(Objekt.slug == slug)).first()
        if not o:
            raise HTTPException(404, "Objekt nicht gefunden")
        return o
    alle = session.exec(select(Objekt)).all()
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


def _aus_datum(datum: str) -> tuple[int | None, int | None]:
    """Jahr und Monat aus einem ISO-Datum, wie `/erkennen` es liefert.

    Unvollständiges oder Unsinniges wird still verworfen — der Beleg ist
    wichtiger als sein Datum."""
    teile = (datum or "").split("-")
    try:
        jahr = int(teile[0]) if teile[0] else None
        monat = int(teile[1]) if len(teile) > 1 and teile[1] else None
    except ValueError:
        return None, None
    return jahr, (monat if monat and 1 <= monat <= 12 else None)


def _zum_datum(datum: str) -> date | None:
    """Ein vollständiges ISO-Datum, sonst nichts (CLXXII).

    Ein halbes Datum („2025-11") ist kein Belegdatum: den Tag zu erfinden
    hiesse, den Beleg in einen Zeitraum zu schieben, in den er vielleicht gar
    nicht gehört."""
    try:
        return date.fromisoformat((datum or "").strip())
    except ValueError:
        return None


@router.post("/scannen", status_code=201)
async def scannen(objekt: str = Form(""), kategorie: str = Form("Sonstiges"),
                  kostenart: str = Form(""),
                  jahr: int | None = Form(None), beschreibung: str = Form(""),
                  zeitraum_id: int | None = Form(None),
                  monat: int | None = Form(None),
                  betrag: float | None = Form(None),
                  datum: str = Form(""),
                  datei: UploadFile = File(...),
                  session: Session = Depends(get_session)) -> dict:
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
    „Kaminkehrer" unter „Nebenkosten"."""
    o = _eindeutiges_objekt(session, objekt)
    _cloud_pflicht(o)
    zeitraum_id = _pruefe_zeitraum(session, zeitraum_id)

    inhalt = await datei.read()
    if not inhalt:
        raise HTTPException(400, "Leere Datei")

    erkannt_jahr, erkannt_monat = _aus_datum(datum)
    jahr = jahr or erkannt_jahr
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
        sach, ziel_ordner = _ablageordner(session, o, kategorie, jahr, client)
        _ordner_sichern(client, sach, ziel_ordner)
        name = _freier_name(session, client, ziel_ordner, name)
        client.lege_ab(f"{ziel_ordner}/{name}", inhalt)
    except NextcloudFehler as e:
        raise HTTPException(400, str(e)) from e

    d = Dokument(pfad=f"/{ziel_ordner}/{name}", dateiname=name,
                 groesse=len(inhalt), objekt_id=o.id, kategorie=kategorie,
                 kostenart=(kostenart or "").strip(),
                 betrag=betrag if betrag and betrag > 0 else None,
                 jahr=jahr, belegdatum=_zum_datum(datum),
                 zeitraum_id=zeitraum_id, status="zugeordnet",
                 erkannt_am=date.today())
    session.add(d)
    try:
        session.commit()
    except IntegrityError as e:
        raise _pfad_konflikt(session, f"/{ziel_ordner}/{name}") from e
    session.refresh(d)
    log.info("Scan abgelegt: %s", d.pfad)
    return {"id": d.id, "dateiname": name, "pfad": d.pfad, "abgelegt": True,
            "objekt": o.slug, "zeitraum_id": d.zeitraum_id}


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
            session: Session = Depends(get_session)) -> dict:
    """Ordnet zu oder korrigiert: andere Immobilie, andere Art, andere
    Kostenposition, anderes Belegdatum, anderer Name — die Datei wandert in der
    Nextcloud mit."""
    d = session.get(Dokument, dokument_id)
    if not d:
        raise HTTPException(404, "Dokument nicht gefunden")
    gesetzt = data.model_fields_set

    if data.objekt:
        o = session.exec(select(Objekt).where(Objekt.slug == data.objekt)).first()
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
    betrag = (data.betrag if "betrag" in gesetzt
              else betrag_aus_namen(d.dateiname))
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

    d.objekt_id = o.id
    d.kategorie = kategorie
    if "kostenart" in gesetzt:
        d.kostenart = (data.kostenart or "").strip()
    d.jahr = jahr
    d.belegdatum = belegdatum
    # CLXXXI: der Betrag steht ab hier auch am Beleg, nicht nur im Namen.
    d.betrag = betrag if betrag and betrag > 0 else None
    d.dateiname = name
    d.status = "zugeordnet"
    d.zeitraum_id = zeitraum_id
    session.add(d)
    # Ist der Beleg bereits in eine Kostenposition eingerechnet, zieht seine
    # Summe mit — angelegt wird hier nichts, das bleibt der bestätigte Schritt.
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

def _beleg(session: Session, dokument_id: int) -> Dokument:
    d = session.get(Dokument, dokument_id)
    if not d:
        raise HTTPException(404, "Dokument nicht gefunden")
    return d


@router.get("/{dokument_id}/position")
def position_vorschau(dokument_id: int,
                      session: Session = Depends(get_session)) -> dict:
    """Was aus diesem Beleg würde. Ändert nichts.

    Fehlt eine der drei Angaben (Kostenposition, Zeitraum, Betrag), steht hier
    `moeglich: false` samt Grund — die Oberfläche sagt dann, was noch fehlt,
    statt einen Knopf anzubieten, der scheitert."""
    d = _beleg(session, dokument_id)
    try:
        return {"moeglich": True, **belegposten.vorschau(session, d).als_dict()}
    except BelegFehler as fehler:
        return {"moeglich": False, "grund": str(fehler),
                "kostenart": d.kostenart, "zeitraum_id": d.zeitraum_id,
                "betrag": d.betrag, "position_id": d.position_id}


@router.post("/{dokument_id}/position", status_code=201)
def position_uebernehmen(dokument_id: int,
                         session: Session = Depends(get_session)) -> dict:
    """Rechnet den Beleg in seine Kostenposition ein — und legt sie an, wenn es
    sie noch nicht gibt.

    Zweimal geklickt bleibt es bei derselben Summe: gerechnet wird aus allen
    verknüpften Belegen, nie durch Draufrechnen."""
    d = _beleg(session, dokument_id)
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
                    session: Session = Depends(get_session)) -> dict:
    """Nimmt den Beleg wieder aus seiner Kostenposition heraus.

    Die Position bleibt stehen — ihr Betrag schrumpft um das, was dieser Beleg
    beigesteuert hat. Am Beleg selbst ändert sich nichts, die Datei bleibt, wo
    sie liegt."""
    d = _beleg(session, dokument_id)
    if not d.position_id:
        raise HTTPException(409, "Dieser Beleg ist in keine Kostenposition "
                                 "eingerechnet.")
    p = belegposten.loese(session, d)
    session.commit()
    return {"ok": True, "position_id": p.id if p else None,
            "kostenart": p.kostenart if p else "",
            "betrag": p.betrag if p else None}


@router.delete("/{dokument_id}")
def entfernen(dokument_id: int,
              session: Session = Depends(get_session)) -> dict:
    """Nimmt das Dokument aus der App. Die Datei in der Nextcloud bleibt —
    dort wird grundsätzlich nichts gelöscht."""
    d = session.get(Dokument, dokument_id)
    if not d:
        raise HTTPException(404, "Dokument nicht gefunden")
    pfad = d.pfad
    # War der Beleg in eine Kostenposition eingerechnet, schrumpft deren Summe
    # um seinen Anteil. Sonst bliebe dort ein Betrag stehen, zu dem es keinen
    # Beleg mehr gibt.
    belegposten.loese(session, d)
    session.delete(d)
    session.commit()
    log.info("Dokumenteintrag entfernt: %s (Datei bleibt)", pfad)
    return {"ok": True, "pfad": pfad, "datei_bleibt": True,
            "hinweis": "Der Eintrag ist weg, die Datei liegt weiter in der "
                       "Nextcloud."}


@router.post("/{dokument_id}/neu")
async def neu_einscannen(dokument_id: int, datei: UploadFile = File(...),
                         session: Session = Depends(get_session)) -> dict:
    """Ersetzt den Beleg durch eine neue Aufnahme.

    Die alte Datei bleibt liegen — überschrieben oder gelöscht wird in der
    Nextcloud nichts. Der Eintrag zeigt danach auf die neue Aufnahme."""
    d = session.get(Dokument, dokument_id)
    if not d:
        raise HTTPException(404, "Dokument nicht gefunden")
    o = session.get(Objekt, d.objekt_id) if d.objekt_id else None
    if not o:
        raise HTTPException(400, "Dem Dokument fehlt die Immobilie")
    _cloud_pflicht(o)

    inhalt = await datei.read()
    if not inhalt:
        raise HTTPException(400, "Leere Datei")

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


def _dateiname_kopfzeile(name: str) -> str:
    """Der Dateiname für `Content-Disposition` — auch mit € und Umlauten.

    Ein HTTP-Kopf trägt kein €. Seit der Betrag hinten im Namen steht
    (CXXIII), heisst fast jede Rechnung „…_1234,56€.pdf" — und jede Vorschau
    darauf antwortete mit einem 500er, weil sich der Kopf nicht kodieren
    liess. Also beides (RFC 6266): ein Name ohne Sonderzeichen als Rückfall
    und daneben der vollständige, prozentkodiert. Jeder heutige Browser nimmt
    den zweiten."""
    ohne_zoll = unicodedata.normalize("NFKD", name.replace('"', ""))
    schlicht = ohne_zoll.encode("ascii", "ignore").decode("ascii").strip()
    return (f'filename="{schlicht or "beleg"}"; '
            f"filename*=UTF-8''{quote(name)}")


@router.get("/{dokument_id}/inhalt")
def inhalt(dokument_id: int, session: Session = Depends(get_session)) -> Response:
    """Liefert die Datei aus der Nextcloud zur Ansicht im Browser.

    `inline` statt `attachment`: PDFs und Bilder sollen sich öffnen, nicht
    herunterladen. Rein lesend — an der Datei ändert sich nichts."""
    d = session.get(Dokument, dokument_id)
    if not d:
        raise HTTPException(404, "Dokument nicht gefunden")
    if not d.pfad.startswith("/"):
        raise HTTPException(409, "Dieses Dokument liegt noch nicht in der Cloud")
    client = verbindung(session)
    try:
        rohdaten, typ = client.hole(d.pfad)
    except NextcloudFehler as e:
        raise HTTPException(400, str(e)) from e
    # Nextcloud liefert für unbekannte Endungen octet-stream; das laedt der
    # Browser herunter, statt es anzuzeigen.
    if typ == "application/octet-stream" and d.dateiname.lower().endswith(".pdf"):
        typ = "application/pdf"
    return Response(content=rohdaten, media_type=typ, headers={
        "Content-Disposition": f"inline; {_dateiname_kopfzeile(d.dateiname)}",
        "Cache-Control": "private, max-age=60",
    })


@router.get("/{dokument_id}/erkennen")
def erkennen_aus_ablage(dokument_id: int,
                        session: Session = Depends(get_session)) -> dict:
    """Liest Betrag, Datum und Art aus einem Beleg, der schon in der Cloud liegt.

    `_vorschlag` kennt nur den Dateinamen. Heisst die Rechnung schlicht
    „Rechnung_2026_01.pdf", steht im Eingang „Betrag: nicht erkannt" — obwohl
    er auf dem Blatt steht (CLXX). Hier wird die Datei einmal geholt und
    gelesen.

    Bewusst ein eigener Endpunkt und nicht Teil der Liste: für jeden Eintrag
    einer Ansicht die Datei aus der Nextcloud zu holen wäre ein Zug durch die
    ganze Ablage. Gefragt wird für den einen Beleg, den der Nutzer gerade
    ansieht.

    Rein lesend — nichts wird gespeichert, nichts verschoben.
    """
    d = session.get(Dokument, dokument_id)
    if not d:
        raise HTTPException(404, "Dokument nicht gefunden")
    if not d.pfad.startswith("/"):
        raise HTTPException(409, "Dieses Dokument liegt noch nicht in der Cloud")
    client = verbindung(session)
    try:
        rohdaten, _typ = client.hole(d.pfad)
    except NextcloudFehler as e:
        raise HTTPException(400, str(e)) from e
    return ocr.erkenne(rohdaten)
