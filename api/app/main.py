"""ImmoCalc API — FastAPI + SQLite. Seedet beim Start, rechnet über die Engine."""
import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlmodel import SQLModel

from . import wachdienst
from .db import engine
from .engine import NegativesGewicht
from .migrate import migriere
from .routers import (auswertung, besitz, cloud, dokumente, mail, objekte,
                      stammdaten, versand)
from .seed import seed

log = logging.getLogger("immocalc")


@asynccontextmanager
async def lifespan(app: FastAPI):
    SQLModel.metadata.create_all(engine)
    migriere(engine)          # muss vor dem Seed laufen — der liest die Tabellen
    seed(engine)
    log.info("ImmoCalc API bereit")

    wache = asyncio.create_task(wachdienst.schleife())
    try:
        yield
    finally:
        wache.cancel()
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

app.include_router(objekte.router)
# besitz vor stammdaten: dort faengt /objekte/{slug}/{bereich} sonst
# /objekte/{slug}/anteile ab und meldet einen unbekannten Bereich.
# Der zweite Fänger (frueher /{bereich}/{eintrag_id} direkt unter /api) ist
# entschaerft: er liegt jetzt unter /api/stammdaten/… und verschluckt keine
# zweisegmentigen Pfade mehr (siehe stammdaten.py:_altpfad).
app.include_router(besitz.router)
app.include_router(stammdaten.router)
app.include_router(auswertung.router)
app.include_router(cloud.router)
app.include_router(dokumente.router)
app.include_router(mail.router)
app.include_router(versand.router)


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


@app.get("/")
def root() -> dict:
    return {"immocalc": "api", "docs": "/docs", "health": "/api/health"}
