"""ImmoCalc API — FastAPI + SQLite. Seedet beim Start, rechnet über die Engine."""
import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlmodel import SQLModel

from sqlalchemy import text

from . import wachdienst
from .db import engine
from .deps import aktuelle_familie
from .engine import NegativesGewicht
from .migrate import migriere, pflicht_kostenarten_sichern
from .routers import (auswertung, auth, besitz, cloud, dokumente,
                      dokumentvorlagen, heizkosten, heizoel, ki, kidb,
                      kontakte, mail, objekte, openwb, renovierung,
                      solaredge, stammdaten, strom, stromkette, tankstelle,
                      versand, waerme, waermesim, weg, zaehler)
from .seed import seed

log = logging.getLogger("immocalc")


@asynccontextmanager
async def lifespan(app: FastAPI):
    SQLModel.metadata.create_all(engine)
    migriere(engine)          # muss vor dem Seed laufen — der liest die Tabellen
    seed(engine)
    # CCCXCVIII — Pflichtversicherungen (Gebäudeversicherung/-haftpflicht) auch
    # für frisch geseedete Objekte sicherstellen; für den Bestand lief der
    # Backfill schon in `migriere`. Idempotent, additiv.
    pflicht_kostenarten_sichern(engine)
    log.info("ImmoCalc API bereit")

    # Zwei Takte: der ruhige für Texterkennung, Aufräumen und Autoversand, und
    # der schnelle nur für den Abgleich (N290) — er ist rein lesend und stellt
    # die Verknüpfung wieder her, sobald der Nutzer in der Cloud umbenennt oder
    # verschiebt.
    wachen = [asyncio.create_task(wachdienst.schleife()),
              asyncio.create_task(wachdienst.abgleich_schleife())]
    try:
        yield
    finally:
        for wache in wachen:
            wache.cancel()
        for wache in wachen:
            with suppress(asyncio.CancelledError):
                await wache


app = FastAPI(title="ImmoCalc API", version="0.2.0", lifespan=lifespan)


@app.exception_handler(NegativesGewicht)
async def negatives_gewicht(request: Request, fehler: NegativesGewicht):
    """Ein negatives Verteilungsgewicht ist ein Datenfehler, kein Serverfehler.

    Er entsteht, wenn Unterzähler mehr ausweisen als der Hauptzähler. Der
    Nutzer soll den Zählerstand korrigieren — dafür braucht er eine Ansage,
    keinen 500er."""
    log.warning("Verteilung abgelehnt: %s", fehler)
    return JSONResponse(status_code=400, content={
        "detail": f"{fehler} — bitte die Zählerstände prüfen. "
                  "Ein Unterzähler weist mehr aus als der Hauptzähler."})
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])

# N436 — eigener Prefix /api/auth, unabhaengig von jedem Objekt-Faenger;
# Reihenfolge relativ zu den anderen Routern unkritisch, steht ganz oben,
# weil sie das Login selbst betrifft. Bewusst OHNE `_ANMELDUNG_NOETIG` — genau
# hier liegen die Endpunkte, die ohne Sitzung erreichbar sein müssen
# (Familienliste, Registrierung, Login).
app.include_router(auth.router)

# N436 — jeder andere Router braucht eine gültige Sitzung. Einzeln an
# `objekt_holen`/`zeitraum_holen`/`dokument_holen` zu hängen wäre an den
# reinen Einstellungs-Endpunkten (mail, ki, openwb, …) durchgerutscht — die
# haben keinen Objekt-/Zeitraum-Bezug und blieben dadurch sowohl ohne
# Anmeldeprüfung ALS AUCH ohne gesetzten `familienraum`-Namensraum (der
# Schlüssel landete unter dem "?:"-Präfix statt unter der echten Familie).
# Ein einziger Ort statt ~30 einzelne Endpunkt-Signaturen: `dependencies=`
# hier gilt nachweislich auch für Sub-Router, die ein Router VOR diesem
# `include_router`-Aufruf schon in sich aufgenommen hat (per Testskript
# geprüft — genau das Muster von `objekte.router`, der seine ~11 Unterrouter
# aus `api/app/objekt/` bereits beim Modul-Import einhängt).
_ANMELDUNG_NOETIG = [Depends(aktuelle_familie)]

app.include_router(objekte.router, dependencies=_ANMELDUNG_NOETIG)
# besitz vor stammdaten: dort faengt /objekte/{slug}/{bereich} sonst
# /objekte/{slug}/anteile ab und meldet einen unbekannten Bereich.
# Der zweite Fänger (frueher /{bereich}/{eintrag_id} direkt unter /api) ist
# entschaerft: er liegt jetzt unter /api/stammdaten/… und verschluckt keine
# zweisegmentigen Pfade mehr (siehe stammdaten.py:_altpfad).
app.include_router(besitz.router, dependencies=_ANMELDUNG_NOETIG)
app.include_router(zaehler.router, dependencies=_ANMELDUNG_NOETIG)  # /objekte/{slug}/zaehler VOR dem Stammdaten-Fänger
app.include_router(heizkosten.router, dependencies=_ANMELDUNG_NOETIG)
# /objekte/{slug}/heizoel ebenfalls VOR dem Stammdaten-Fänger (N79).
app.include_router(heizoel.router, dependencies=_ANMELDUNG_NOETIG)
# /objekte/{slug}/heizverteiler|waerme|heizung ebenfalls VOR dem Fänger (N80/N81).
app.include_router(waerme.router, dependencies=_ANMELDUNG_NOETIG)
# /objekte/{slug}/strom ebenfalls VOR dem Stammdaten-Fänger (N83).
app.include_router(strom.router, dependencies=_ANMELDUNG_NOETIG)
# N84 — eigener Prefix /api/kidb (Belegdaten-Wissensdatenbank), trotzdem vor
# dem Stammdaten-Fänger eingehängt.
app.include_router(kidb.router, dependencies=_ANMELDUNG_NOETIG)
# N240 — eigener Prefix /api/dokumentvorlagen (Vorlagenarchiv, objekt-
# übergreifend), ebenfalls vor dem Stammdaten-Fänger eingehängt.
app.include_router(dokumentvorlagen.router, dependencies=_ANMELDUNG_NOETIG)
# N264 — Drucker des Hauses (eigener Prefix /api/drucker).
app.include_router(dokumentvorlagen.drucker_router, dependencies=_ANMELDUNG_NOETIG)
# N126 — eigener Prefix /api/solaredge (Screenshot lesen, rein lesend),
# ebenfalls vor dem Stammdaten-Fänger eingehängt.
app.include_router(solaredge.router, dependencies=_ANMELDUNG_NOETIG)
# N130 — eigener Prefix /api/openwb (Ladeprotokoll der Wallbox, rein lesend),
# ebenfalls vor dem Stammdaten-Fänger eingehängt.
app.include_router(openwb.router, dependencies=_ANMELDUNG_NOETIG)
# N132 — eigener Prefix /api/tankstelle (E-Tankstelle: Nutzer, Verlauf,
# Abrechnung, Versand), ebenfalls vor dem Stammdaten-Fänger eingehängt.
app.include_router(tankstelle.router, dependencies=_ANMELDUNG_NOETIG)
# N142 — /zeitraeume/{zid}/stromkette (Netz·PV·Akku → E-Tankstelle → Einheiten).
app.include_router(stromkette.router, dependencies=_ANMELDUNG_NOETIG)
# N270 — /objekte/{slug}/renovierungen ebenfalls VOR dem Stammdaten-Fänger.
app.include_router(renovierung.router, dependencies=_ANMELDUNG_NOETIG)
# N309 — das Kontaktbuch. Eigener Prefix `/api/kontakte`, kollidiert mit
# keinem Fänger; die Reihenfolge INNERHALB des Routers ist dort erklärt.
app.include_router(kontakte.router, dependencies=_ANMELDUNG_NOETIG)
# N273 — /zeitraeume/{zid}/weg (WEG-Modus). Früh eingehängt, damit kein anderer
# Router ein zweisegmentiges /zeitraeume/{zid}/… vorher abfängt.
app.include_router(weg.router, dependencies=_ANMELDUNG_NOETIG)
app.include_router(stammdaten.router, dependencies=_ANMELDUNG_NOETIG)
app.include_router(auswertung.router, dependencies=_ANMELDUNG_NOETIG)
app.include_router(cloud.router, dependencies=_ANMELDUNG_NOETIG)
app.include_router(dokumente.router, dependencies=_ANMELDUNG_NOETIG)
app.include_router(mail.router, dependencies=_ANMELDUNG_NOETIG)
app.include_router(versand.router, dependencies=_ANMELDUNG_NOETIG)
# Eigener Prefix /api/ki — Reihenfolge unkritisch.
app.include_router(ki.router, dependencies=_ANMELDUNG_NOETIG)
app.include_router(waermesim.router, dependencies=_ANMELDUNG_NOETIG)


def _build_zeilen() -> list[str]:
    """Inhalt von build.txt: Zeile 1 = Kurz-SHA, Zeile 2 = Build-Zeit (ISO UTC).
    Im Prüfstand nicht vorhanden."""
    try:
        with open("/srv/build.txt", encoding="utf-8") as f:
            return [z.strip() for z in f.read().splitlines() if z.strip()]
    except OSError:
        return []


def _build() -> str:
    """Git-Kurz-SHA aus dem Image."""
    zeilen = _build_zeilen()
    return zeilen[0] if zeilen else "local"


def _build_zeit() -> str:
    """Zeitpunkt des Image-Builds als ISO-UTC, sofern hinterlegt — damit man in
    den Einstellungen ablesen kann, ob der Auto-Deploy den neuen Stand hat."""
    zeilen = _build_zeilen()
    return zeilen[1] if len(zeilen) > 1 else ""


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "service": "immocalc-api",
            "version": app.version, "build": _build(), "build_zeit": _build_zeit()}


@app.get("/healthz")
def healthz() -> JSONResponse:
    """Status-Vertrag der plexdice-Migration: 200 nur, wenn die Datenbank
    tatsächlich erreichbar ist — anders als /api/health (reine Lebensmeldung),
    das auch bei kaputter DB antwortet. Für den Docker-HEALTHCHECK gedacht."""
    try:
        with engine.connect() as verbindung:
            verbindung.execute(text("SELECT 1"))
    except Exception as fehler:
        log.warning("Healthcheck: Datenbank nicht erreichbar: %s", fehler)
        return JSONResponse(status_code=503, content={"status": "error"})
    return JSONResponse(status_code=200, content={"status": "ok"})


@app.get("/status")
def status() -> dict:
    """Status-Vertrag der plexdice-Migration: app/version/letzter und
    naechster Wachdienst-Lauf — fuer Monitoring/Unraid-Label, nicht fuer die
    App selbst (die liest wachdienst.zustand() direkt)."""
    from datetime import datetime, timedelta  # noqa: PLC0415

    zustand = wachdienst.zustand()
    letzter_lauf = zustand["letzter_lauf"]
    naechster_lauf = None
    if letzter_lauf:
        naechster_lauf = (datetime.fromisoformat(letzter_lauf)
                           + timedelta(seconds=wachdienst.TAKT_SEKUNDEN)).isoformat()
    letztes_ergebnis = None
    if letzter_lauf:
        letztes_ergebnis = "error" if zustand["letzter_fehler"] else "ok"
    return {"app": "immocalc-api", "version": _build() or app.version,
            "last_run": letzter_lauf, "last_result": letztes_ergebnis,
            "next_run": naechster_lauf}


@app.get("/")
def root() -> dict:
    return {"immocalc": "api", "docs": "/docs", "health": "/api/health"}
