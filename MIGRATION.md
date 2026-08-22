# MIGRATION.md — ImmoCalc auf das plexdice-Muster

ImmoCalc ist die Referenz-Migration für die einheitliche Deploy-Kette:
**ein Repo → GitHub Actions baut → `ghcr.io` → Watchtower rollt aus.**
Auf dem Unraid wird danach nirgends mehr gebaut, nur noch `image:` gezogen.

Diese Datei ist die Schrittliste dafür — in der Reihenfolge, in der sie
abzuarbeiten ist. Nichts davon wurde von hier aus bereits ausgeführt: alle
Schritte unten brauchen entweder GitHub-Zugriff oder Docker-/Boot-Zugriff auf
dem Unraid-Host, beides hat diese Sitzung nicht.

**Der laufende Stack (`docker-compose.yml`, `build:`) ist zu keinem Zeitpunkt
angefasst worden** — er läuft unverändert weiter, bis Schritt 5 bewusst
ausgeführt wird.

## Was hier im Repo bereits fertig ist

| Datei | Zweck |
|---|---|
| `services/api/Dockerfile` | wie `api/Dockerfile`, nur am neuen Pfad — Build-Context bleibt die Repo-Wurzel |
| `services/dashboard/Dockerfile` | wie `dashboard/Dockerfile`, nur am neuen Pfad |
| `.github/workflows/build.yml` | baut beide Images bei jedem Push auf `main`, nächtlich (03:17, mit `--pull`) und manuell; pusht nach `ghcr.io/premiumcola/immocalc-{api,dashboard}` |
| `renovate.json` | hält `api/requirements.txt`, die `FROM`-Zeilen und Compose-Image-Tags aktuell, Dependency Dashboard an |
| `docker-compose.ghcr.yml` | die Ziel-Compose (`image:`, Labels, neuer Datenpfad) — **noch nicht aktiv**, siehe Schritt 5 |
| `docker-compose.override.yml.example` | Live-Mount fürs Entwickeln, lokal zu kopieren, `.gitignore`-geschützt |
| `assets/icon-512.png` / `icon-api-512.png` | 512×512-Icons, künftig per `raw.githubusercontent`-URL statt vom Container ausgeliefert |
| `GET /healthz` (API) | prüft die Datenbank wirklich (503 statt 200 bei Fehler) — `/api/health` bleibt unverändert als reine Lebensmeldung |
| `GET /status` (API) | `app`, `version`, `last_run`, `last_result`, `next_run` — aus `wachdienst.zustand()` gespeist |

Die alten `api/Dockerfile` und `dashboard/Dockerfile` sind bewusst noch da —
der laufende Stack baut weiter daraus, bis Schritt 5 vollzogen ist. Danach
können sie weg (Aufräum-Hinweis am Ende).

---

## Schritt 1 — Einmalig auf GitHub einrichten

1. **Actions erlauben:** *Settings → Actions → General → Actions permissions*
   → „Allow all actions and reusable workflows" (meist schon Standard).
2. **Schreibrecht für GHCR:** *Settings → Actions → General → Workflow
   permissions* → **„Read and write permissions"** aktivieren. Ohne das darf
   der mitgelieferte `GITHUB_TOKEN` nicht nach `ghcr.io` pushen — der erste
   Build schlägt sonst mit einem 403 beim Push fehl.
3. **Sichtbarkeit der Images:** ein öffentliches Repo erzeugt standardmäßig
   öffentliche Packages — dann reicht Watchtower ohne jede Anmeldung. Sollen
   die Images **privat** bleiben (*Package Settings* am jeweiligen Package
   nach dem ersten Build, dort auf „Private" umstellen):
   - Personal Access Token erzeugen: *Settings → Developer settings →
     Personal access tokens* → Scope **`read:packages`**.
   - Einmalig auf dem Unraid: `docker login ghcr.io -u premiumcola` (Token
     als Passwort). Das schreibt `/root/.docker/config.json` — genau dort
     liest Watchtower die Zugangsdaten automatisch mit.
4. Sonst nichts weiter — der Workflow liegt schon im Repo.

## Schritt 2 — Ersten Build auslösen & prüfen

- Der Push, der diese Migration einspielt, löst ihn **bereits aus**
  (`on: push` auf `main`) — kein separater Schritt nötig.
- GitHub → Tab **Actions** → Lauf „Build & Push" grün abwarten
  (Matrix `api`/`dashboard`, je ca. 2–4 Min, OCR-Layer macht `api` am
  langsamsten).
- GitHub → Tab **Packages** (oder direkt
  `github.com/premiumcola/ImmoCalc/pkgs/container/immocalc-api`) prüfen: Tag
  `latest` und ein Kurz-SHA-Tag müssen dort auftauchen.
- Rot? Fehlertext im Actions-Log lesen — am häufigsten fehlt Schritt 1.2.

## Schritt 3 — Testen, BEVOR umgeschaltet wird

`docker-compose.ghcr.yml` benutzt dieselben `container_name`s und denselben
Port wie der laufende Stack — **nicht parallel starten**. Sauberer Testlauf
unter einem anderen Projektnamen und Port, ohne den laufenden Stack zu
berühren:

```bash
DASHBOARD_PORT=8092 docker compose -p immocalc-test -f docker-compose.ghcr.yml \
  --env-file .env up -d
curl -s http://localhost:8092/api/health
curl -s http://192.168.178.10:8092/api/... # UI im Browser stichprobenartig
docker compose -p immocalc-test -f docker-compose.ghcr.yml down
```

Erst wenn das sauber läuft (UI lädt, `/healthz`/`/status` antworten,
`docker ps` zeigt beide Test-Container „healthy"), weiter zu Schritt 4/5.

## Schritt 4 — Datenmigration (optional, vor Schritt 5)

Der neue Standardpfad ist `/mnt/user/appdata/immocalc/data` (ohne `-live`).
**Automatisch verschoben wird hier nichts** — das entscheidet der Nutzer:

- **Ohne Migration:** `DATA_DIR` in `.env` weiter auf
  `/mnt/user/appdata/immocalc-live/data` zeigen lassen — funktioniert
  unverändert, nur der Pfad bleibt „historisch" benannt.
- **Mit Migration** (sauberer Neuanfang): Stack kurz stoppen (SQLite verträgt
  kein Kopieren bei laufendem Schreibzugriff), dann
  ```bash
  docker compose down
  mkdir -p /mnt/user/appdata/immocalc/data
  rsync -a /mnt/user/appdata/immocalc-live/data/ /mnt/user/appdata/immocalc/data/
  ```
  und danach `DATA_DIR=/mnt/user/appdata/immocalc/data` in `.env` setzen. Die
  alten Dateien unter `immocalc-live/` bleiben als Sicherheitsnetz liegen.

## Schritt 5 — Umschalten (Kernschritt)

```bash
docker compose down                                   # laufenden Stack stoppen
cp docker-compose.yml docker-compose.yml.bak-vor-migration   # Rollback-Netz
cp docker-compose.ghcr.yml docker-compose.yml
docker compose pull
docker compose up -d
```

Danach prüfen:
- `http://192.168.178.10:8091` lädt.
- `curl http://192.168.178.10:8091/api/health` → `{"status":"ok",...}`.
- `docker ps` zeigt `immocalc-api` und `immocalc-dashboard` als `healthy`
  (nicht nur „running").

## Schritt 6 — Im Compose Manager registrieren

Damit ImmoCalc als **ein** Eintrag in der Unraid-Docker-Übersicht auftaucht
(bisher lief der Stack nur per CLI, unregistriert):

1. Plugin **„Compose Manager Plus"** installieren (Community Applications —
   Nachfolger des mittlerweile deprecateten „Docker Compose Manager").
2. Dort **„Add Stack" → „Indirect Path"** (weil `docker-compose.yml` außerhalb
   des Plugin-eigenen Projekte-Ordners liegt) → auf den Repo-Ordner zeigen.
3. Im Stack-eigenen **„Settings"-Tab** Namen („ImmoCalc") und Icon-URL setzen
   (dieselbe `raw.githubusercontent`-URL wie in den Container-Labels).

Danach gruppiert die Unraid-Oberfläche `immocalc-api` und `immocalc-dashboard`
unter einem gemeinsamen „ImmoCalc"-Stack-Eintrag.

## Rollback

- **Vor Schritt 5:** nichts zu tun — der alte Stack lief die ganze Zeit
  unverändert weiter.
- **Nach Schritt 5**, falls etwas klemmt:
  ```bash
  docker compose down
  cp docker-compose.yml.bak-vor-migration docker-compose.yml
  # falls Schritt 4 die Daten verschoben hat: DATA_DIR in .env zurück auf
  # /mnt/user/appdata/immocalc-live/data setzen — sonst startet der alte
  # Stack mit einer leeren Datenbank.
  docker compose up -d --build
  ```

## Vermutete Ursache: Dashboard zeigt „unhealthy"

Von dieser Sitzung aus nicht am laufenden Container nachprüfbar (kein
Docker-Zugriff). Wahrscheinlichste Erklärung: das laufende Image wurde
gebaut, bevor die `/healthz`-Location in `dashboard/nginx/default.conf.template`
existierte, und seitdem nie neu gebaut — der bisherige Dev-Loop änderte nur
den Bind-Mount (`./public`), nie das Image selbst. Zur Bestätigung auf dem
Host:
```bash
docker inspect immocalc-dashboard --format '{{json .State.Health}}'
docker exec immocalc-dashboard wget -qO- http://localhost/healthz
```
Antwortet der zweite Befehl nicht mit `ok`, ist es kein Health-Endpoint-,
sondern ein echtes nginx-Problem — dann bitte Ausgabe mitschicken. Mit der
neuen Pipeline erledigt sich die „stilles altes Image"-Variante von selbst:
jeder Build ist frisch, Watchtower zieht ihn nach.

## Aufräumen (erst nach ein paar Tagen stabilem Betrieb mit dem neuen Stack)

- `api/Dockerfile`, `dashboard/Dockerfile` (durch `services/*/Dockerfile` ersetzt)
- `docker-compose.yml.bak-vor-migration`
- `docker-compose.ghcr.yml` selbst kann dann entfallen — sein Inhalt ist ja
  in `docker-compose.yml` aufgegangen
