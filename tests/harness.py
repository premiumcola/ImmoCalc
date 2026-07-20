"""Lokaler Prüfstand: serviert die API und public/ unter EINER Herkunft,
damit der Browser-Check gegen ungebaute Änderungen laufen kann.

    python3 tests/harness.py        # -> http://127.0.0.1:8199

Nur für Tests — im Betrieb serviert nginx public/ und proxyt /api/.
"""
import os
import sys
import tempfile

WURZEL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(WURZEL, "api"))
os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "harness.db"))

import uvicorn  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from app.main import app  # noqa: E402

app.mount("/", StaticFiles(directory=os.path.join(WURZEL, "public"), html=True),
          name="public")

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", 8199)),
                log_level="warning")
