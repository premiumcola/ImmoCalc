#!/usr/bin/env bash
# ImmoCalc – Standard-Deploy. Idempotent: seedet .env + Config und startet den Stack.
# Nutzung:  ./deploy.sh
#
# Frontend-Aenderungen (public/) brauchen KEIN Deploy — das Verzeichnis ist in
# den Container gemountet und sofort wirksam. Dieses Skript ist fuer alles
# andere: API-Code, Dockerfiles, nginx-Config, Compose.
set -euo pipefail
cd "$(dirname "$0")"

# docker compose v2 oder v1 erkennen
DC="docker compose"; docker compose version >/dev/null 2>&1 || DC="docker-compose"

# 1) .env seeden
if [ ! -f .env ]; then cp .env.example .env; echo "→ .env aus .env.example erstellt – bei Bedarf anpassen."; fi
set -a; . ./.env; set +a
: "${CONFIG_DIR:=/mnt/user/appdata/immocalc-live}"
: "${DASHBOARD_PORT:=8091}"

# 2) Config-Verzeichnis seeden (workflow.json), falls noch nicht vorhanden
mkdir -p "$CONFIG_DIR/dashboard"
[ -f "$CONFIG_DIR/dashboard/workflow.json" ]       || cp public/workflow.json       "$CONFIG_DIR/dashboard/workflow.json"
[ -f "$CONFIG_DIR/dashboard/workflow.local.json" ] || cp public/workflow.local.json "$CONFIG_DIR/dashboard/workflow.local.json"
mkdir -p "${DATA_DIR:-/mnt/user/appdata/immocalc-live/data}"

# 3) GIT_SHA fürs build.txt (falls Git vorhanden)
export GIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo local)"

# 3b) Vor dem Bauen aufraeumen. Jeder Rebuild hinterlaesst verwaiste (dangling)
# Image-Layer und Build-Cache; ohne Aufraeumen laeuft die Docker-Platte mit der
# Zeit voll ("No space left on device" beim pip install). Dangling Images und
# Build-Cache sind gefahrlos wegraeumbar — laufende Container, getaggte Images
# und Volumes (die Daten!) bleiben unangetastet.
docker image prune -f >/dev/null 2>&1 || true
docker builder prune -af >/dev/null 2>&1 || true

# 4) Bauen und starten. --remove-orphans raeumt Container weg, die nicht mehr
#    im Compose stehen (z.B. der frueher separate DEV-Stack).
echo "→ Deploy ($DC up -d --build --remove-orphans) …"
$DC up -d --build --remove-orphans

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"; IP="${IP:-<unraid-ip>}"
echo
echo "✔ ImmoCalc läuft → http://$IP:${DASHBOARD_PORT}"
echo
echo "Persistente Konfiguration: $CONFIG_DIR/dashboard/workflow.json"
