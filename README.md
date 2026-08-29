# ImmoCalc — Deployment (Docker / Unraid, plexdice-Muster)

Nebenkosten-/Betriebskostenabrechnung. Ein Repo, zwei Images, ein Stack:
GitHub Actions baut aus `services/<name>/Dockerfile` nach
`ghcr.io/premiumcola/immocalc-{api,dashboard}`, **Watchtower** auf dem Unraid
pollt die Registry und rollt neue Images selbstständig aus. Auf dem Server
wird nichts gebaut.

**Eine Umgebung** auf Port `8091` — Container `immocalc-dashboard` und
`immocalc-api`.

> **Die laufende Stack-Definition liegt NICHT in diesem Repo**, sondern in
> `premiumcola/devBox` → `immocalc/docker-compose.yml`. Das
> `docker-compose.yml` hier ist eine Abbildung davon für Entwicklung und
> Nachschlagen; weichen beide ab, gilt die Datei im devBox-Repo.
> Stand und offene Punkte: **MIGRATION.md**.

**Kein Live-Mount mehr.** Das Frontend steckt seit dem 23.08.2026 im
Dashboard-Image, nicht mehr im Arbeitsordner der Devbox. Eine Änderung an
`public/` ist damit **nicht** sofort auf der Seite: sie braucht Push → CI-Build
→ Watchtower (pollt alle 5 Minuten). Das ist der Preis der Trennung — vorher
servierte die Produktion Dateien direkt aus dem Entwicklungsverzeichnis.

**Dev-Schleife** für sofort wirksame Frontend-Änderungen, ohne die Produktion
anzufassen:

```
cp docker-compose.override.yml.example docker-compose.override.yml
docker compose up -d
```

`docker-compose.override.yml` ist in `.gitignore` — sie bleibt lokal und
gelangt nie per `git pull` auf den Server.

## Was die App kann

- **Objekte** — Kacheln mit Frist und offenen Belegen; auf der Objektseite
  Stammdaten, Einheiten, Mieten samt Kontaktdaten, Versicherungen, Kredite,
  Zahlungen — jeweils mit eigenem Zahlungsturnus. Sicherung und Löschen ganz
  unten; die Unterlagen in der Nextcloud bleiben dabei unberührt.
- **Abrechnung** — Checkliste mit Ampel, Kostenfluss als Sankey, Belege,
  Beträge nachtragen, an jeder offenen Position direkt einen Beleg
  abfotografieren, abschließen und als PDF an die Mieter versenden
- **Eingang** — Belege abfotografieren (mehrseitig → PDF) oder aus dem
  Nextcloud-Ordner einlesen, zuordnen, automatisch benennen und einsortieren
- **Auswertung** — Einnahmen gegen Ausgaben, Vermögen (Wert, Restschuld,
  Eigenkapital), Kostenblöcke, Mietverlauf, Cashflow je Einheit inklusive
  €/m², Filter nach Jahr, Objekt und Kostenart
- **Einstellungen** — Nextcloud, Postfach für den Versand, Ordner-Benennung,
  Eigentümer (Anteile in Tausendsteln je Objekt)

## Struktur
```
immocalc/
├── docker-compose.yml       # api + dashboard, .env-getrieben
├── .env / .env.example      # Port, CONFIG_DIR, DATA_DIR, PUID/PGID, TZ, LOG_LEVEL
├── AUFGABEN.md              # Was erledigt ist und was offen — fortgeschrieben
├── dashboard/               # nginx: serviert public/, proxyt /api/
├── api/
│   ├── app/
│   │   ├── engine.py        # Rechen-Engine (Verteilung, Interpolation, §35a)
│   │   ├── models.py        # Datenmodell
│   │   ├── migrate.py       # ergänzt fehlende Spalten — Daten bleiben erhalten
│   │   ├── nextcloud.py     # WebDAV, Schreibzugriff nur im Home-Ordner
│   │   ├── mailversand.py   # SMTP über das eigene Postfach
│   │   ├── abrechnung_pdf.py# Abrechnung als PDF, ohne Fremdbibliothek
│   │   ├── cashflow.py      # Cashflow je Einheit, Sankey-Fluss
│   │   ├── vermoegen.py     # Wert, Restschuld, Eigenkapital je Objekt
│   │   ├── export.py        # Sicherung, Wiederherstellung, Löschen
│   │   ├── nachpflege.py    # welche Angaben nach einem Update noch fehlen
│   │   ├── ocr.py           # Texterkennung (optional, braucht tesseract)
│   │   ├── bezeichnung.py   # Ordnernamen von grob nach fein
│   │   ├── turnus.py        # monatlich … jährlich
│   │   ├── wachdienst.py    # prüft den Eingang alle 15 Minuten
│   │   └── routers/         # objekte, stammdaten, besitz, auswertung,
│   │                        # cloud, dokumente, mail, versand
│   └── tests/               # pytest
├── public/                  # Vanilla HTML/CSS/JS, kein Build-Step
│   ├── index.html           # Objekte
│   ├── objekt.html          # Objektdetail
│   ├── zeitraum.html        # Abrechnung mit Checkliste
│   ├── eingang.html         # Belege scannen und zuordnen
│   ├── statistik.html       # Auswertung
│   ├── settings.html        # Einstellungen
│   ├── onboarding.html      # Immobilie anlegen
│   └── assets/              # immo.css, immo.js, charts.js, scan.js,
│                            # kostenicons.js
└── tests/                   # Browser-Prüfungen (Playwright)
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
- API: FastAPI + SQLite unter `api/` (Rechen-Engine + Seed der Demo-Objekte).
- `make test` — Engine- und API-Tests (pytest), müssen grün sein.
- `make check` — Browser gegen die laufende Instanz.
- `make check-app` — startet den Prüfstand (`tests/harness.py`: API + `public/`
  auf einem Port) und klickt alle Flows in drei Geräteklassen durch.
  Einmalig: `npm install && npx playwright install chromium`.
- Frontend ruft same-origin `/api/...` (nginx proxyt an `immocalc-api`).

## Verbindungen einrichten
In der App unter **Einstellungen**:
- **Nextcloud** — Serveradresse (nur der Host, ohne `/login`), Benutzername und
  ein **App-Passwort** aus *Einstellungen → Sicherheit*. Danach den Home-Ordner
  wählen; darunter legt ImmoCalc je Immobilie die Ordnerstruktur an.
  Geschrieben wird ausschließlich unterhalb dieses Ordners.
- **Postfach** — GMX, WEB.DE, Gmail, IONOS, mailbox.org oder frei. Abrechnungen
  gehen dann von deiner eigenen Adresse an die Mieter.

- Aufgabenstand: **AUFGABEN.md** · Agenten-Leitfaden: **CLAUDE.md** ·
  Feature-Plan: **ROADMAP.md**
