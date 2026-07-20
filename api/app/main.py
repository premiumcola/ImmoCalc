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
app.include_router(besitz.router)
app.include_router(stammdaten.router)
app.include_router(auswertung.router)
app.include_router(cloud.router)
app.include_router(dokumente.router)
app.include_router(mail.router)
app.include_router(versand.router)


def _build() -> str:
    """Git-Kurz-SHA aus dem Image; im Prüfstand nicht vorhanden."""
    try:
        with open("/srv/build.txt", encoding="utf-8") as f:
            return f.read().strip() or "local"
    except OSError:
        return "local"


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "service": "immocalc-api",
            "version": app.version, "build": _build()}


@app.get("/")
def root() -> dict:
    return {"immocalc": "api", "docs": "/docs", "health": "/api/health"}
