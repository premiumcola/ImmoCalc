"""N35 — Abrechnungszeiträume umstellen: Grenzen verschieben, teilen, Belege
nach Datum neu zuordnen.

Kern der Turnus-Umstellung (Wirtschaftsjahr → Kalenderjahr): ein Beleg gehört in
genau EINEN Zeitraum — den, in dessen Fenster sein Belegdatum fällt. Verschiebt
man Grenzen oder teilt einen Zeitraum, wandern die Belege automatisch dorthin.
"""
import os
import sys
import tempfile
from datetime import date

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(),
                                     "test_zeitraum_umstellen.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session  # noqa: E402

from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from sqlmodel import select  # noqa: E402
from app.models import Dokument, Objekt  # noqa: E402


def _objekt(c, name):
    return c.post("/api/objekte", json={"name": name}).json()["slug"]


def _zeitraum(c, slug, start, ende):
    return c.post(f"/api/objekte/{slug}/zeitraeume",
                  json={"start": start, "ende": ende}).json()["id"]


def _beleg(objekt_id, zid, belegdatum, kostenart="Müll", betrag=100.0):
    with Session(engine) as s:
        d = Dokument(objekt_id=objekt_id, dateiname=f"beleg-{belegdatum}.pdf",
                     pfad=f"/Obj/{belegdatum}.pdf", kategorie="Nebenkosten",
                     kostenart=kostenart, betrag=betrag, zeitraum_id=zid,
                     belegdatum=date.fromisoformat(belegdatum) if belegdatum else None)
        s.add(d)
        s.commit()
        return d.id


def _oid(c, slug):
    with Session(engine) as s:
        return s.exec(select(Objekt).where(Objekt.slug == slug)).first().id


def test_grenzen_verschieben_und_teilen():
    with TestClient(app) as c:
        slug = _objekt(c, "Umstellung A")
        a = _zeitraum(c, slug, "2024-10-01", "2025-09-30")  # Wirtschaftsjahr
        # verlängern bis 30.04.2026
        r = c.patch(f"/api/zeitraeume/{a}", json={"ende": "2026-04-30",
                                                  "typ": "Zwischen"})
        assert r.status_code == 200, r.text
        assert r.json()["label"] == "01.10.2024 – 30.04.2026"
        assert r.json()["typ"] == "Zwischen"
        # teilen am 01.01.2026 → [.. – 31.12.2025] und [01.01.2026 – 30.04.2026]
        t = c.post(f"/api/zeitraeume/{a}/teilen", json={"datum": "2026-01-01"})
        assert t.status_code == 201, t.text
        assert t.json()["alt"]["label"] == "01.10.2024 – 31.12.2025"
        assert t.json()["neu"]["label"] == "01.01.2026 – 30.04.2026"
        # Ende vor Start wird abgelehnt
        assert c.patch(f"/api/zeitraeume/{a}",
                       json={"ende": "2020-01-01"}).status_code == 400


def test_belege_wandern_nach_datum():
    with TestClient(app) as c:
        slug = _objekt(c, "Umstellung B")
        oid = _oid(c, slug)
        a = _zeitraum(c, slug, "2025-01-01", "2025-06-30")
        b = _zeitraum(c, slug, "2025-07-01", "2025-12-31")
        # Beleg liegt fälschlich in A, sein Datum gehört aber in B
        falsch = _beleg(oid, a, "2025-09-15")
        # Beleg korrekt in A
        richtig = _beleg(oid, a, "2025-03-10")
        # Beleg ohne Datum → Grenzfall
        ohne = _beleg(oid, a, None)
        # Beleg außerhalb aller Zeiträume → Grenzfall
        weit = _beleg(oid, b, "2030-01-01")

        vs = c.post(f"/api/objekte/{slug}/zeitraeume/belege-abgleichen").json()
        assert vs["vorschau"] is True
        ids_wandern = {m["id"] for m in vs["moves"]}
        assert falsch in ids_wandern and richtig not in ids_wandern
        typen = {g["id"]: g["typ"] for g in vs["grenzfaelle"]}
        assert typen.get(ohne) == "kein_datum"
        assert typen.get(weit) == "kein_zeitraum"

        # Anwenden
        ap = c.post(f"/api/objekte/{slug}/zeitraeume/"
                    "belege-abgleichen?vorschau=false").json()
        assert ap["vorschau"] is False and ap["verschoben"] == 1
        with Session(engine) as s:
            assert s.get(Dokument, falsch).zeitraum_id == b
            assert s.get(Dokument, richtig).zeitraum_id == a

        # Idempotent: zweiter Lauf verschiebt nichts mehr
        ap2 = c.post(f"/api/objekte/{slug}/zeitraeume/"
                     "belege-abgleichen?vorschau=false").json()
        assert ap2["verschoben"] == 0
