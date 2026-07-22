#!/usr/bin/env bash
# ImmoCalc – Auto-Update. Holt neue Commits und entscheidet selbst, ob ein
# Deploy nötig ist.
#
#   Frontend-Änderungen (public/, docs, *.md, tests)  → nichts zu tun,
#     das Verzeichnis ist in den Container gemountet und sofort live.
#   API/Docker/nginx/Compose                          → ./deploy.sh (~30 s).
#
# Gedacht für einen Cron-Lauf alle paar Minuten (siehe unten). Läuft nie zwei
# Mal gleichzeitig, bricht bei divergierter Historie sauber ab und schreibt
# alles nach tools/auto-update.log.
set -euo pipefail

# Immer im Repo arbeiten, egal von wo das Skript gerufen wird.
cd "$(dirname "$0")/.."
REPO="$(pwd)"
BRANCH="${IMMO_BRANCH:-main}"
LOG="$REPO/tools/auto-update.log"

log() { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >>"$LOG"; }

# Nur ein Lauf gleichzeitig — sonst überholen sich zwei Cron-Ticks beim Bauen.
exec 9>"$REPO/tools/.auto-update.lock"
if ! flock -n 9; then
  log "übersprungen (läuft bereits)"; exit 0
fi

# Was einen Deploy erzwingt: alles außerhalb des gemounteten Frontends.
# Ein Treffer genügt. Muster gegen `git diff --name-only` (Pfade ab Repo-Wurzel).
BRAUCHT_DEPLOY='^(api/|dashboard/|docker-compose\.yml|deploy\.sh|\.env\.example$)|(^|/)Dockerfile'

git fetch --quiet origin "$BRANCH"

ALT="$(git rev-parse HEAD)"
NEU="$(git rev-parse "origin/$BRANCH")"

if [ "$ALT" = "$NEU" ]; then
  exit 0                      # nichts Neues — still bleiben, kein Log-Rauschen
fi

# Nur vorspulen. Gibt es lokale Abweichungen (eigene Commits, dirty tree),
# lieber abbrechen als etwas zu überschreiben.
if ! git merge-base --is-ancestor "$ALT" "$NEU"; then
  log "ABBRUCH: lokale Historie weicht ab ($ALT), $NEU nicht vorspulbar"
  exit 1
fi
if ! git pull --ff-only --quiet origin "$BRANCH"; then
  log "ABBRUCH: git pull fehlgeschlagen (arbeitsverzeichnis nicht sauber?)"
  exit 1
fi

ANZAHL="$(git rev-list --count "$ALT..$NEU")"
GEAENDERT="$(git diff --name-only "$ALT" "$NEU")"

if grep -qE "$BRAUCHT_DEPLOY" <<<"$GEAENDERT"; then
  log "Deploy nötig — $ANZAHL neue(r) Commit(s), API/Docker/nginx betroffen:"
  grep -E "$BRAUCHT_DEPLOY" <<<"$GEAENDERT" | sed 's/^/    /' >>"$LOG"
  if ./deploy.sh >>"$LOG" 2>&1; then
    log "Deploy fertig ($NEU)"
  else
    log "FEHLER: deploy.sh scheiterte — App läuft noch auf dem alten Stand"
    exit 1
  fi
else
  log "kein Deploy nötig — $ANZAHL neue(r) Commit(s), nur Frontend/Doku, sofort live ($NEU)"
fi
