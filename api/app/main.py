"""ImmoCalc API — FastAPI + SQLite. Seedet beim Start, rechnet über die Engine."""
import os
from contextlib import asynccontextmanager
from datetime import date
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import SQLModel, Session, create_engine, select

from .models import (Objekt, Einheit, Partei, Kostenart, Zeitraum,
                     Kostenposition, Vorauszahlung)
from .engine import abrechnung, Position
from .seed import seed

DB_PATH = os.environ.get("DB_PATH", "/data/immocalc.db")
os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})


@asynccontextmanager
async def lifespan(app: FastAPI):
    SQLModel.metadata.create_all(engine)
    seed(engine)
    yield

app = FastAPI(title="ImmoCalc API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def frist_tage(z: Zeitraum) -> int:
    dl = date(z.ende.year + 1, z.ende.month, z.ende.day)   # § 556: Ende + 12 Monate
    return (dl - date.today()).days


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "immocalc-api"}


@app.get("/api/objekte")
def objekte():
    with Session(engine) as s:
        out = []
        for o in s.exec(select(Objekt)).all():
            zs = s.exec(select(Zeitraum).where(Zeitraum.objekt_id == o.id)).all()
            aktiv = next((z for z in zs if z.status == "in Arbeit"), None)
            offen = 0
            if aktiv:
                pos = s.exec(select(Kostenposition).where(Kostenposition.zeitraum_id == aktiv.id)).all()
                offen = sum(1 for p in pos if p.status == "offen")
            out.append({"id": o.id, "slug": o.slug, "name": o.name, "ort": o.ort,
                        "typ": o.typ, "turnus": o.turnus,
                        "offene_positionen": offen,
                        "frist_tage": frist_tage(aktiv) if aktiv else None})
        return out


@app.get("/api/objekte/{slug}")
def objekt(slug: str):
    with Session(engine) as s:
        o = s.exec(select(Objekt).where(Objekt.slug == slug)).first()
        if not o:
            raise HTTPException(404, "Objekt nicht gefunden")
        einheiten = s.exec(select(Einheit).where(Einheit.objekt_id == o.id)).all()
        parteien = s.exec(select(Partei).where(Partei.objekt_id == o.id)).all()
        zeitraeume = s.exec(select(Zeitraum).where(Zeitraum.objekt_id == o.id)).all()
        return {"objekt": o, "einheiten": einheiten, "parteien": parteien,
                "zeitraeume": [{"id": z.id, "label": f"{z.start:%d.%m.%Y} – {z.ende:%d.%m.%Y}",
                                "typ": z.typ, "status": z.status,
                                "frist_tage": frist_tage(z) if z.status == "in Arbeit" else None}
                               for z in zeitraeume]}


@app.get("/api/objekte/{slug}/kostenarten")
def kostenarten(slug: str):
    with Session(engine) as s:
        o = s.exec(select(Objekt).where(Objekt.slug == slug)).first()
        if not o:
            raise HTTPException(404, "Objekt nicht gefunden")
        return s.exec(select(Kostenart).where(Kostenart.objekt_id == o.id)).all()


@app.get("/api/zeitraeume/{zid}/positionen")
def positionen(zid: int):
    with Session(engine) as s:
        return s.exec(select(Kostenposition).where(Kostenposition.zeitraum_id == zid)).all()


@app.get("/api/zeitraeume/{zid}/abrechnung")
def abrechnung_endpoint(zid: int):
    with Session(engine) as s:
        z = s.get(Zeitraum, zid)
        if not z:
            raise HTTPException(404, "Zeitraum nicht gefunden")
        pos = s.exec(select(Kostenposition).where(Kostenposition.zeitraum_id == zid)).all()
        vzs = s.exec(select(Vorauszahlung).where(Vorauszahlung.zeitraum_id == zid)).all()
        # offene Positionen (Betrag noch nicht da) fließen nicht in die Rechnung ein
        positionen = [Position(p.kostenart, p.betrag, p.schluessel, p.anteile, p.s35)
                      for p in pos if p.status == "erledigt"]
        res = abrechnung(positionen, {v.partei: v.betrag for v in vzs})
        res["offen"] = [p.kostenart for p in pos if p.status == "offen"]
        return res


@app.get("/")
def root():
    return {"immocalc": "api", "docs": "/docs", "health": "/api/health"}
