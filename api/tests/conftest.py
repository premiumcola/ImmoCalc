"""Jede Testdatei bekommt ihre eigene Datenbank.

Die Testdateien setzen zwar alle `os.environ["DB_PATH"]` auf ein eigenes
tmp-Verzeichnis, aber `app.db.engine` entsteht nur **einmal** — beim ersten
Import. Im Gesamtlauf gewann deshalb die Datei, die zuerst importiert wurde,
und alle anderen schrieben in dieselbe Datei. Ein Fund konnte so einen anderen
verdecken (ein Test in `test_datenschutz.py` schlug nur im Gesamtlauf fehl,
weil `test_besitz.py` einen Eigentümer hinterlassen hatte).

Die Fixture bindet die Engine je Testmodul neu — an `app.db`, an die Module,
die sie beim Import an sich gezogen haben (`app.main`, `app.wachdienst`), und
am Testmodul selbst, falls es `from app.db import engine` gemacht hat.
Danach liefert jede Datei einzeln dasselbe Ergebnis wie im Gesamtlauf.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Damit der allererste Import von app.db nicht auf /data/immocalc.db zielt —
# gleich, welche Testdatei zuerst geladen wird.
os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "start.db"))

import pytest  # noqa: E402
from sqlmodel import SQLModel, create_engine  # noqa: E402

# Namen, unter denen die Engine ausserhalb von app.db gehalten wird.
NAMEN = ("engine", "db_engine")


@pytest.fixture(autouse=True, scope="module")
def eigene_datenbank(request):
    from app import db as db_modul
    from app import main as main_modul
    from app import wachdienst
    from app.migrate import migriere

    pfad = os.path.join(tempfile.mkdtemp(), f"{request.module.__name__}.db")
    os.environ["DB_PATH"] = pfad
    neu = create_engine(f"sqlite:///{pfad}",
                        connect_args={"check_same_thread": False})
    # Schema gleich mitbringen: Module ohne TestClient kaemen sonst an keine
    # Tabelle. Geseedet wird nicht — das macht der Lifespan, wo er gebraucht wird.
    SQLModel.metadata.create_all(neu)
    migriere(neu)

    alt = db_modul.engine
    gebunden = [(modul, name)
                for modul in (db_modul, main_modul, wachdienst, request.module)
                for name in NAMEN if getattr(modul, name, None) is alt]
    for modul, name in gebunden:
        setattr(modul, name, neu)
    yield
    for modul, name in gebunden:
        setattr(modul, name, alt)
