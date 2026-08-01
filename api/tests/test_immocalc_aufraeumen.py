"""N30 — verwaiste `.immocalc`-Steckbriefe aufräumen.

Löscht der Nutzer ein PDF/Bild von Hand in der Nextcloud, bleibt die
`.immocalc`-Sidecar als Waise liegen. Der Wachdienst entfernt genau die
`.immocalc`-Dateien, zu denen kein gleichnamiger Beleg mehr im selben Ordner
liegt — eine Sidecar MIT Beleg bleibt unangetastet.
"""
import os
import sys
import tempfile

os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(),
                                     "test_immocalc_aufraeumen.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

import app.routers.dokumente as dok  # noqa: E402
from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Objekt  # noqa: E402
from app.nextcloud import Eintrag  # noqa: E402


class _FakeCloud:
    """Nextcloud-Ersatz: liefert einen festen Baum und merkt sich Löschungen."""

    def __init__(self, baum):
        self.baum = baum
        self.geloescht = []

    def liste(self, pfad):
        return self.baum.get(pfad, [])

    def loesche(self, pfad):
        self.geloescht.append(pfad)


def test_verwaiste_immocalc_weg_paar_bleibt(monkeypatch):
    with TestClient(app) as c:
        slug = c.post("/api/objekte", json={"name": "Waisenweg 1"}).json()["slug"]
        with Session(engine) as s:
            o = s.exec(select(Objekt).where(Objekt.slug == slug)).first()
            o.nc_ordner = "Obj"
            s.add(o)
            s.commit()

        baum = {
            "Obj": [
                Eintrag("60_NK", "Obj/60_NK", True),
                Eintrag("rechnung.pdf", "Obj/rechnung.pdf", False),
                # Sidecar MIT Beleg → bleibt.
                Eintrag("rechnung.immocalc", "Obj/rechnung.immocalc", False),
                # Waise (kein „weg.*"-Beleg) → wird gelöscht.
                Eintrag("weg.immocalc", "Obj/weg.immocalc", False),
            ],
            "Obj/60_NK": [
                # Waise auch eine Ebene tiefer.
                Eintrag("verwaist.immocalc", "Obj/60_NK/verwaist.immocalc", False),
            ],
        }
        fake = _FakeCloud(baum)
        monkeypatch.setattr(dok, "verbindung", lambda session: fake)

        with Session(engine) as s:
            res = dok.verwaiste_immocalc_aufraeumen(s)

        assert res["geloescht"] == 2, res
        assert "Obj/weg.immocalc" in fake.geloescht
        assert "Obj/60_NK/verwaist.immocalc" in fake.geloescht
        # Die Sidecar mit Beleg bleibt unangetastet.
        assert "Obj/rechnung.immocalc" not in fake.geloescht
