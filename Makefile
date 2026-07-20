.PHONY: deploy down logs rebuild ps check test
deploy:  ; ./deploy.sh                      ## bauen + starten
down:    ; docker compose down              ## stoppen
logs:    ; docker compose logs -f
rebuild: ; docker compose up -d --build --force-recreate
ps:      ; docker compose ps
check:   ; node tests/smoke.mjs             ## echter Browser gegen die laufende Instanz
test:    ; cd api && python3 -m pytest -q   ## Engine + API Tests

## App-Flows ohne Deploy pruefen: startet den Pruefstand (API + public/ auf
## einem Port) und klickt Startseite, Objekt, Auswertung, Wizard durch.
check-app:
	@python3 tests/harness.py & echo $$! > /tmp/immocalc-harness.pid; \
	sleep 3; \
	node tests/app-check.mjs; A=$$?; \
	node tests/onboarding-check.mjs; B=$$?; \
	node tests/cloud-check.mjs; C=$$?; \
	node tests/responsive-check.mjs; D=$$?; \
	node tests/matrix.mjs; E=$$?; \
	node tests/zeitraum-check.mjs; F=$$?; \
	node tests/scan-check.mjs; G=$$?; \
	kill $$(cat /tmp/immocalc-harness.pid) 2>/dev/null; \
	exit $$((A + B + C + D + E + F + G))

icons:   ; node tools/make-icons.mjs   ## App-Icons aus icons/icon.svg erzeugen
