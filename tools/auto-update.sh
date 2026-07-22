#!/usr/bin/env bash
# ImmoCalc – Auto-Update. Hält die laufende App zum Code im Repo aktuell und
# entscheidet selbst, ob dafür ein Deploy nötig ist.
#
#   Frontend (public/, docs, *.md, tests)  → nichts zu tun: das Verzeichnis ist
#     in den Container gemountet und sofort live.
#   API/Docker/nginx/Compose               → ./deploy.sh (~30 s).
#
# Ausgelöst wird über den lokalen Stand (HEAD), nicht über einen Git-Pull:
# in dieser Umgebung landen Änderungen direkt im geteilten Repo, nicht über
# GitHub. Was doch auf origin liegt, wird trotzdem mit vorgespult — schadet nie.
#
# Für einen Cron-Lauf alle paar Minuten gedacht (Unraid → User Scripts).
# Läuft nie zweimal gleichzeitig und schreibt alles nach tools/auto-update.log.
set -euo pipefail

cd "$(dirname "$0")/.."
REPO="$(pwd)"
BRANCH="${IMMO_BRANCH:-main}"
LOG="$REPO/tools/auto-update.log"
STAND="$REPO/tools/.zuletzt-deployt"        # SHA, der zuletzt live gebracht wurde

log() { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >>"$LOG"; }

# Nur ein Lauf gleichzeitig — sonst überholen sich zwei Ticks beim Bauen.
exec 9>"$REPO/tools/.auto-update.lock"
flock -n 9 || exit 0

# Was einen Deploy erzwingt: alles außerhalb des gemounteten Frontends.
BRAUCHT_DEPLOY='^(api/|dashboard/|docker-compose\.yml|deploy\.sh|\.env\.example$)|(^|/)Dockerfile'

# Falls doch etwas auf origin liegt, vorspulen. Ist der lokale Stand voraus
# (der Normalfall hier), passiert nichts — deshalb Fehler bewusst schlucken.
git fetch --quiet origin "$BRANCH" 2>/dev/null || true
git merge --ff-only --quiet "origin/$BRANCH" 2>/dev/null || true

HEAD="$(git rev-parse HEAD)"
LETZTER="$(cat "$STAND" 2>/dev/null || echo '')"

[ "$HEAD" = "$LETZTER" ] && exit 0          # nichts Neues seit dem letzten Lauf

deploy() {
  if ./deploy.sh >>"$LOG" 2>&1; then
    echo "$HEAD" >"$STAND"
    log "Deploy fertig ($HEAD)"
  else
    log "FEHLER: deploy.sh scheiterte — App läuft noch auf dem alten Stand"
    exit 1
  fi
}

# Erster Lauf: kein gemerkter Stand. Einmal deployen, damit die laufende App
# sicher zum Code passt — heute stünden sonst die vielen noch nicht ausgerollten
# API-Änderungen weiter aus.
if [ -z "$LETZTER" ]; then
  log "Erststart — einmal deployen, damit App und Code zusammenpassen ($HEAD)"
  deploy
  exit 0
fi

GEAENDERT="$(git diff --name-only "$LETZTER" "$HEAD" 2>/dev/null || echo '?')"
ANZAHL="$(git rev-list --count "$LETZTER..$HEAD" 2>/dev/null || echo '?')"

# Bei „?" (unbekannter alter Stand) im Zweifel deployen — sicherer als raten.
if [ "$GEAENDERT" = "?" ] || grep -qE "$BRAUCHT_DEPLOY" <<<"$GEAENDERT"; then
  log "Deploy nötig — $ANZAHL neue(r) Commit(s), API/Docker/nginx betroffen:"
  grep -E "$BRAUCHT_DEPLOY" <<<"$GEAENDERT" 2>/dev/null | sed 's/^/    /' >>"$LOG" || true
  deploy
else
  echo "$HEAD" >"$STAND"
  log "kein Deploy — $ANZAHL neue(r) Commit(s), nur Frontend/Doku, sofort live ($HEAD)"
fi
