# ImmoCalc — Deployment (Docker / Unraid, aufgehängt wie jFlow)

> **Schnellstart:** `./deploy.sh` – siehe **DEPLOY.md** für die Unraid-Anleitung.

Nebenkosten-/Betriebskostenabrechnung. Monorepo im jFlow-Stil: ein Build-Context
(`.`), pro Service eine `<service>/Dockerfile`, `.env`-getrieben,
`container_name`-Präfix `immocalc-`, Konfiguration über persistierte
`workflow.json` (+ `workflow.local.json`).

**Gesplittet in zwei Environments:**
- **LIVE** — stabil, unveränderliches Image · Port `8091` · Container `immocalc-dashboard`
- **DEV**  — iterieren, `public/` read-only gemountet (Änderungen ohne Rebuild) ·
  Port `8092` · Container `immocalc-dashboard-dev` · `LOG_LEVEL=DEBUG`

Beide laufen parallel im selben Stack.

## Struktur
```
immocalc/
├── docker-compose.yml       # LIVE + DEV (YAML-Anchors), .env-getrieben
├── .env / .env.example      # Ports, CONFIG_DIR(_DEV), DATA_DIR(_DEV), PUID/PGID, TZ, LOG_LEVEL(_DEV)
├── .dockerignore
├── dashboard/               # Web-UI-Service
│   ├── Dockerfile           # context = Repo-Wurzel; kopiert public/
│   └── nginx/default.conf
└── public/
    ├── index.html app.html onboarding.html logos.html
    ├── workflow.json / workflow.local.json   # KONFIG: aktive Kostenarten je Immo
    ├── icons/  docs/
```

## Auf Unraid ausrollen (Compose Manager)
1. Ordner `immocalc/` nach `/mnt/user/appdata/immocalc/` kopieren.
2. `.env.example` → `.env`, Ports/Pfade prüfen.
3. Compose Manager → *Add New Stack* → Ordner wählen → **Compose Up**.
4. LIVE: `http://<unraid-ip>:8091`  ·  DEV: `http://<unraid-ip>:8092`

Nur ein Environment starten:
```bash
docker compose up -d --build dashboard-live    # nur live
docker compose up -d --build dashboard-dev     # nur dev
```

## Konfiguration persistieren (jFlow-Muster)
Default `workflow.json` ist ins Image gebaut. Zum Persistieren/Bearbeiten:
```bash
mkdir -p ${CONFIG_DIR}/dashboard
cp public/workflow.json       ${CONFIG_DIR}/dashboard/workflow.json
cp public/workflow.local.json ${CONFIG_DIR}/dashboard/workflow.local.json
```
Dann den `volumes:`-Block bei `dashboard-live` einkommentieren (dev analog mit `CONFIG_DIR_DEV`).

## Was von jFlow später andockt (Hooks im compose vorbereitet)
`./.git:/repo/.git:ro` (Git-Stand) · `${DATA_DIR}:/data` (Beleg-PDFs) ·
`${CONFIG_DIR}/logs:/logs` · weitere Services `immocalc-ocr`, `immocalc-pdf`, …

## Backend & Tests
- API: FastAPI + SQLite unter `api/` (Rechen-Engine + Seed der echten Objekte).
- `make test` — Engine- und API-Tests (pytest), müssen grün sein.
- Frontend ruft same-origin `/api/...` (nginx proxyt an `immocalc-api`).
- Live-Daten im Browser: Seite **Live-Daten (API)** auf der Startseite.
- Agenten-Leitfaden: **CLAUDE.md** · Feature-Plan: **ROADMAP.md**
