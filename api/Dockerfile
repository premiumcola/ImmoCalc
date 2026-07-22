# immocalc-api — FastAPI + SQLite (Build-Context = Repo-Wurzel)
FROM python:3.12-slim
ARG GIT_SHA=local
WORKDIR /srv
# Texterkennung fuer abfotografierte Belege. Rein optional: fehlt tesseract,
# laeuft der Scan weiter, nur ohne Vorschlag fuer Betrag und Datum.
#
# libgl1/libglib2.0-0: keine Texterkennung selbst, sondern eine Abhaengigkeit
# von opencv-python, das rapidocr-onnxruntime mitbringt (CCXXVII, unsichtbare
# Textschicht fuer Scans). Ohne die beiden Bibliotheken scheitert schon der
# Import mit "libGL.so.1: cannot open shared object file" — das python:slim-
# Image bringt sie nicht mit.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-deu \
    libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*
COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY api/app ./app
RUN printf '%s\n' "$GIT_SHA" > /srv/build.txt
ENV DB_PATH=/data/immocalc.db
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/api/health')" || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
