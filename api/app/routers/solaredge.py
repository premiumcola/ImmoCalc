"""N126 — den SolarEdge-Screenshot hochladen statt die Zahlen abzutippen.

Ein Endpunkt, rein lesend: `POST /api/solaredge/lesen` nimmt das Bild entgegen,
lässt es vom Vision-Modell lesen und gibt die erkannten Zahlen samt Warnungen
zurück. **Gespeichert wird nichts** — weder in der Datenbank noch in der Cloud.
Der Nutzer sieht die Werte, bestätigt sie und trägt sie selbst ein.

Fällt die Erkennung aus (kein Schlüssel, kein Netz, unbrauchbare Antwort), ist
das kein Fehler: die Antwort kommt mit leeren Feldern und einem Hinweis, dass
die vier Werte von Hand einzutragen sind. Genau so hat der Nutzer es sich
gewünscht.

N161 — beim Übernehmen der erkannten Werte wird der Screenshot zusätzlich als
Beleg in der Nextcloud abgelegt (`POST …/screenshot`). Die Ablage selbst gehört
`dokumente.py`: dieser Router ruft deren vorhandene Ablagelogik auf
(`_ablageordner`/`_ordner_sichern`/`_freier_name`/`lege_ab`), statt sie zu
doppeln. Der Screenshot ist der Beleg hinter der Strom-Position der
Nebenkostenabrechnung und landet daher im Jahresordner unter `60_Nebenkosten`
(Kategorie „Nebenkosten", Ablageort aus der bestehenden Struktur). Ist keine
Nextcloud eingerichtet, entfällt nur die Ablage — die Zahlen sind über den
Strom-PUT ohnehin schon gespeichert; die Antwort sagt das ruhig mit
`abgelegt: False` statt eines Fehlers.
"""
import logging
from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from .. import kiauslese, solaredge
from ..cloudkern import verbindung
from ..db import get_session
from ..deps import objekt_holen
from ..models import Dokument, Objekt, Stromjahr
from ..nextcloud import NextcloudFehler
from .dokumente import (_ablageordner, _endung, _freier_name, _ordner_sichern,
                        dateiname)
from .ki import ki_key, ki_modell
from .. import upload

log = logging.getLogger("immocalc")
router = APIRouter(prefix="/api/solaredge", tags=["solaredge"])

# Ein Screenshot ist ein paar hundert Kilobyte. Fünf Megabyte sind reichlich
# Luft und zugleich die Grenze, die die Bilderkennung selbst zieht.
MAX_BYTES = 5 * 1024 * 1024

VON_HAND = ("Bitte die vier Werte aus der SolarEdge-Oberfläche von Hand "
            "eintragen.")


@router.post("/lesen")
async def lesen(datei: UploadFile = File(...),
                session: Session = Depends(get_session)) -> dict:
    """Liest Produktion und Verbrauch aus einem SolarEdge-Screenshot.

    Gibt die erkannten Mengen in kWh, die drei Anteile je Balken, deren
    Umrechnung in kWh und etwaige Warnungen zurück. `erkannt` sagt, ob die
    Verbrauchszeile stand — nur sie wird für die Kostenblöcke gebraucht.

    Nichts wird gespeichert."""
    # N292 — Leere, Grösse und Dateiart prüft `upload.lies` für alle
    # Endpunkte gleich; die Bildart selbst prüft `solaredge.medientyp`
    # gleich darunter am Inhalt, nicht am Namen.
    rohdaten = await upload.lies(datei, max_bytes=MAX_BYTES,
                                 was="Das Bild")
    typ = solaredge.medientyp(rohdaten, datei.content_type or "")
    if not typ:
        raise HTTPException(400, "Das ist kein Bild (PNG, JPEG, GIF oder WEBP).")

    schluessel = ki_key(session)
    if not kiauslese.verfuegbar(schluessel):
        ergebnis = solaredge.aufbereiten({}).als_dict()
        ergebnis["hinweis"] = ("Die Bilderkennung ist nicht eingerichtet. "
                               + VON_HAND)
        return ergebnis

    roh = kiauslese.lies_solaredge(rohdaten, typ, schluessel=schluessel,
                                   modell=ki_modell(session))
    ergebnis = solaredge.aufbereiten(roh).als_dict()
    ergebnis["hinweis"] = ("" if ergebnis["erkannt"] else
                           "Der Screenshot konnte nicht gelesen werden. " + VON_HAND)
    return ergebnis


# --------------------------------------------------------------------------
# N161 — den Screenshot als Beleg ablegen
#
# Der Screenshot ist der Beleg der eingetragenen Zahlen. Beim Übernehmen wandert
# er zusätzlich in die Nextcloud: als `Dokument` in den Jahresordner unter
# `60_Nebenkosten` (er belegt die Strom-Position der Abrechnung), und
# `Stromjahr.screenshot_dokument_id` zeigt darauf.
#
# Die Ablage selbst gehört nicht hierher: sie läuft über die vorhandene
# Ablagelogik aus `dokumente.py` (Zielordner ermitteln → MKCOL → freier Name →
# PUT). Der Schreibriegel greift dabei unverändert — `nextcloud.lege_ab` prüft
# vor jedem PUT `_pruefe_schreibrecht`. Gelöscht oder überschrieben wird nie:
# ein neuer Screenshot bekommt über `_freier_name` einen eigenen Namen, der alte
# bleibt als Datei stehen, nur die Verknüpfung zeigt künftig auf den neuen.
#
# Die Ablage ist eine Zugabe: ohne eingerichtete Nextcloud (kein Zugang oder
# kein verknüpfter Objektordner) kommt `abgelegt: False` mit einem ruhigen Grund
# zurück — kein Fehler, denn die Zahlen sind über den Strom-PUT schon gesichert.
# --------------------------------------------------------------------------

# Der Screenshot belegt die Strom-Kosten der Abrechnung → er liegt bei den
# Nebenkosten (Jahresordner ergibt sich aus der Unterordner-Vorlage).
SCREENSHOT_KATEGORIE = "Nebenkosten"


def _stromjahr(session: Session, objekt_id: int, jahr: int) -> Stromjahr:
    """Den Strom-Datensatz eines Objekt-Jahres holen oder neu anlegen.

    Der Frontend-PUT legt ihn beim Speichern der Werte ebenfalls an; hier wird
    er gebraucht, um `screenshot_dokument_id` zu setzen, auch wenn der PUT (per
    Debounce) noch nicht durch ist. Additiv: die übrigen Felder bleiben 0/„"."""
    sj = session.exec(
        select(Stromjahr).where(Stromjahr.objekt_id == objekt_id,
                                Stromjahr.jahr == jahr)).first()
    if sj:
        return sj
    sj = Stromjahr(objekt_id=objekt_id, jahr=jahr)
    session.add(sj)
    session.commit()
    session.refresh(sj)
    return sj


@router.post("/objekte/{slug}/{jahr}/screenshot")
async def screenshot_ablegen(slug: str, jahr: int,
                             datei: UploadFile = File(...),
                             session: Session = Depends(get_session),
                             o: Objekt = Depends(objekt_holen)) -> dict:
    """Legt den SolarEdge-Screenshot als Beleg in der Nextcloud ab (N161).

    Rückgabe `{"abgelegt": True, "dokument_id", "pfad", "dateiname"}` bei
    Erfolg. Ohne eingerichtete Cloud `{"abgelegt": False, "grund": …}` — die
    Werte selbst sind davon unberührt (eigener Strom-PUT)."""
    # N292 — Leere, Grösse und Dateiart prüft `upload.lies` für alle
    # Endpunkte gleich; die Bildart selbst prüft `solaredge.medientyp`
    # gleich darunter am Inhalt, nicht am Namen.
    rohdaten = await upload.lies(datei, max_bytes=MAX_BYTES,
                                 was="Das Bild")
    typ = solaredge.medientyp(rohdaten, datei.content_type or "")
    if not typ:
        raise HTTPException(400, "Das ist kein Bild (PNG, JPEG, GIF oder WEBP).")

    # Zugabe, kein Muss: ohne verknüpften Ordner oder ohne Zugang entfällt die
    # Ablage ruhig, statt die Übernahme scheitern zu lassen.
    if not o.nc_ordner:
        return {"abgelegt": False,
                "grund": f"{o.name} ist mit keinem Nextcloud-Ordner verknüpft — "
                         "der Screenshot wurde nicht abgelegt. Die Werte sind "
                         "gespeichert."}
    try:
        client = verbindung(session)
    except HTTPException as fehler:
        return {"abgelegt": False, "grund": str(fehler.detail)}

    endung = _endung(datei.filename or "") or {
        "image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif",
        "image/webp": ".webp"}.get(typ, ".png")
    name = dateiname(jahr, SCREENSHOT_KATEGORIE, "SolarEdge-Screenshot", endung)
    try:
        sach, ziel_ordner = _ablageordner(session, o, SCREENSHOT_KATEGORIE, jahr,
                                          client)
        _ordner_sichern(client, sach, ziel_ordner)
        name = _freier_name(session, client, ziel_ordner, name)
        client.lege_ab(f"{ziel_ordner}/{name}", rohdaten, typ=typ)
    except NextcloudFehler as fehler:
        log.warning("Screenshot nicht abgelegt für %s: %s", o.slug, fehler)
        return {"abgelegt": False, "grund": str(fehler)}

    d = Dokument(pfad=f"/{ziel_ordner}/{name}", dateiname=name,
                 groesse=len(rohdaten), objekt_id=o.id,
                 kategorie=SCREENSHOT_KATEGORIE, jahr=jahr,
                 status="zugeordnet", erkannt_am=date.today())
    session.add(d)
    try:
        session.commit()
    except IntegrityError:
        # Der Zielpfad ist inzwischen doch vergeben (Race). Die Datei liegt am
        # Platz — das ist kein Verlust —, nur der Eintrag entfällt. Als Zugabe
        # ruhig melden statt eines 500.
        session.rollback()
        log.warning("Screenshot-Eintrag nicht gespeichert (Pfad vergeben): %s",
                    d.pfad)
        return {"abgelegt": False,
                "grund": "Zu diesem Ablageort gibt es schon einen Eintrag — der "
                         "Screenshot liegt in der Nextcloud, wurde aber nicht "
                         "erneut verknüpft."}
    session.refresh(d)

    # Die Verknüpfung zieht auf den neuen Beleg um; ein zuvor abgelegter bleibt
    # als Datei stehen (gehört dem Nutzer) und wird nicht gelöscht.
    sj = _stromjahr(session, o.id, jahr)
    sj.screenshot_dokument_id = d.id
    session.add(sj)
    session.commit()
    log.info("SolarEdge-Screenshot abgelegt: %s (Objekt %s, Jahr %d)",
             d.pfad, o.slug, jahr)
    return {"abgelegt": True, "dokument_id": d.id, "dateiname": name,
            "pfad": d.pfad}
