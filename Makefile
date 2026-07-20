.PHONY: deploy live dev down logs rebuild ps
deploy:  ; ./deploy.sh all      ## bauen + live & dev starten
live:    ; ./deploy.sh live     ## nur LIVE
dev:     ; ./deploy.sh dev      ## nur DEV
down:    ; docker compose down  ## stoppen
logs:    ; docker compose logs -f
rebuild: ; docker compose up -d --build --force-recreate
ps:      ; docker compose ps
check:   ; ./check.sh          ## Headless-Browser-Selfcheck + Screenshots
test:    ; cd api && python3 -m pytest -q   ## Engine + API Tests
