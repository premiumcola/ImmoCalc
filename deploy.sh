#!/usr/bin/env bash
# ImmoCalc – Standard-Deploy. Idempotent: seedet .env + Config und startet den Stack.
# Nutzung:  ./deploy.sh [all|live|dev]     (Default: all)
set -euo pipefail
cd "$(dirname "$0")"

# docker compose v2 oder v1 erkennen
DC="docker compose"; docker compose version >/dev/null 2>&1 || DC="docker-compose"

# 1) .env seeden
if [ ! -f .env ]; then cp .env.example .env; echo "→ .env aus .env.example erstellt – bei Bedarf anpassen."; fi
set -a; . ./.env; set +a
: "${CONFIG_DIR:=/mnt/user/appdata/immocalc-live}"
: "${CONFIG_DIR_DEV:=/mnt/user/appdata/immocalc-dev}"
: "${DASHBOARD_PORT:=8091}"; : "${DASHBOARD_PORT_DEV:=8092}"

# 2) Config-Verzeichnisse seeden (workflow.json), falls noch nicht vorhanden
seed(){ mkdir -p "$1/dashboard"
  [ -f "$1/dashboard/workflow.json" ]       || cp public/workflow.json       "$1/dashboard/workflow.json"
  [ -f "$1/dashboard/workflow.local.json" ] || cp public/workflow.local.json "$1/dashboard/workflow.local.json"; }
seed "$CONFIG_DIR"; seed "$CONFIG_DIR_DEV"
mkdir -p "${DATA_DIR:-/mnt/user/appdata/immocalc-live/data}" "${DATA_DIR_DEV:-/mnt/user/appdata/immocalc-dev/data}"

# 3) GIT_SHA fürs build.txt (falls Git vorhanden)
export GIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo local)"

# 4) Ziel wählen und bauen/starten
case "${1:-all}" in
  live) SVC="dashboard-live";;
  dev)  SVC="dashboard-dev";;
  all|"") SVC="";;
  *) echo "Nutzung: ./deploy.sh [all|live|dev]"; exit 1;;
esac
echo "→ Standard-Deploy ($DC up -d --build ${SVC:-all}) …"
$DC up -d --build $SVC

IP="$(hostname -I 2>/dev/null | awk '{print $1}')"; IP="${IP:-<unraid-ip>}"
echo
echo "✔ ImmoCalc läuft:"
echo "   LIVE → http://$IP:${DASHBOARD_PORT}"
echo "   DEV  → http://$IP:${DASHBOARD_PORT_DEV}"
echo
echo "Persistente Konfiguration liegt bereit unter:"
echo "   $CONFIG_DIR/dashboard/workflow.json   (live)"
echo "   $CONFIG_DIR_DEV/dashboard/workflow.json (dev)"
echo "Zum Aktivieren den volumes:-Block in docker-compose.yml einkommentieren."
