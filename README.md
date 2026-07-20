# ImmoCalc — Deployment (Docker / Unraid, aufgehängt wie jFlow)

> **Schnellstart:** `./deploy.sh` – siehe **DEPLOY.md** für die Unraid-Anleitung.

Nebenkosten-/Betriebskostenabrechnung. Monorepo im jFlow-Stil: ein Build-Context
(`.`), pro Service eine `<service>/Dockerfile`, `.env`-getrieben,
`container_name`-Präfix `immocalc-`, Konfiguration über persistierte
`workflow.json` (+ `workflow.local.json`).

**Eine Umgebung** auf Port `8091` — Container `immocalc-dashboard` und
`immocalc-api`. `public/` ist read-only in den Container gemountet: jede
Frontend-Änderung ist ohne Rebuild sofort auf der Seite. Nur Änderungen an
API-Code, Dockerfiles, nginx-Config oder Compose brauchen `./deploy.sh`.

## Struktur
```
immocalc/
├── docker-compose.yml       # api + dashboard, .env-getrieben
├── .env / .env.example      # Port, CONFIG_DIR, DATA_DIR, PUID/PGID, TZ, LOG_LEVEL
├── .dockerignore
├── dashboard/               # Web-UI-Service
│   ├── Dockerfile           # context = Repo-Wurzel; kopiert public/
│   └── nginx/default.conf.template
├── api/                     # FastAPI + SQLite, Rechen-Engine, Tests
└── public/
    ├── index.html app.html onboarding.html logos.html status.html
    ├── workflow.json / workflow.local.json   # KONFIG: aktive Kostenarten je Immo
    ├── icons/  docs/
```

## Auf Unraid ausrollen (Compose Manager)
1. Repo nach `/mnt/user/appdata/immocalc/` klonen.
2. `.env.example` → `.env`, Ports/Pfade prüfen.
3. Compose Manager → *Add New Stack* → Ordner wählen → **Compose Up**
   (oder einfach `./deploy.sh`).
4. UI: `http://<unraid-ip>:8091`

## Konfiguration persistieren (jFlow-Muster)
Default `workflow.json` ist ins Image gebaut. `./deploy.sh` legt beim ersten
Lauf eine bearbeitbare Kopie unter `${CONFIG_DIR}/dashboard/` an; zum Aktivieren
den entsprechenden `volumes:`-Eintrag bei `dashboard` ergänzen.

## Was von jFlow später andockt (Hooks im compose vorbereitet)
`./.git:/repo/.git:ro` (Git-Stand) · `${DATA_DIR}:/data` (Beleg-PDFs) ·
`${CONFIG_DIR}/logs:/logs` · weitere Services `immocalc-ocr`, `immocalc-pdf`, …

## Backend & Tests
- API: FastAPI + SQLite unter `api/` (Rechen-Engine + Seed der echten Objekte).
- `make test` — Engine- und API-Tests (pytest), müssen grün sein.
- `make check` — echter Browser gegen die laufende Instanz, Screenshots in
  `tests/screenshots/`. Einmalig: `npm install && npx playwright install chromium`.
- Frontend ruft same-origin `/api/...` (nginx proxyt an `immocalc-api`).
- Agenten-Leitfaden: **CLAUDE.md** · Feature-Plan: **ROADMAP.md**
