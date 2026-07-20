.PHONY: deploy down logs rebuild ps check test
deploy:  ; ./deploy.sh                      ## bauen + starten
down:    ; docker compose down              ## stoppen
logs:    ; docker compose logs -f
rebuild: ; docker compose up -d --build --force-recreate
ps:      ; docker compose ps
check:   ; node tests/live-check.mjs        ## echter Browser gegen die laufende Instanz
test:    ; cd api && python3 -m pytest -q   ## Engine + API Tests
