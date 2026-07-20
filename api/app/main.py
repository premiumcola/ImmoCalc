"""ImmoCalc API — FastAPI + SQLite. Seedet beim Start, rechnet über die Engine."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import SQLModel

from .db import engine
from .routers import auswertung, objekte, stammdaten
from .seed import seed

log = logging.getLogger("immocalc")


@asynccontextmanager
async def lifespan(app: FastAPI):
    SQLModel.metadata.create_all(engine)
    seed(engine)
    log.info("ImmoCalc API bereit")
    yield


app = FastAPI(title="ImmoCalc API", version="0.2.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])

app.include_router(objekte.router)
app.include_router(stammdaten.router)
app.include_router(auswertung.router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "service": "immocalc-api"}


@app.get("/")
def root() -> dict:
    return {"immocalc": "api", "docs": "/docs", "health": "/api/health"}
