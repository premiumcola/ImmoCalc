.PHONY: deploy down logs rebuild ps check test test-seq t
deploy:  ; ./deploy.sh                      ## bauen + starten
down:    ; docker compose down              ## stoppen
logs:    ; docker compose logs -f
rebuild: ; docker compose up -d --build --force-recreate
ps:      ; docker compose ps
check:   ; node tests/smoke.mjs             ## echter Browser gegen die laufende Instanz

# --------------------------------------------------------------------------
# Tests in drei Stufen — je Aufgabe die kleinste, die die Frage beantwortet.
#
#   make t F=dokumente   gezielt, Sekunden — waehrend der Arbeit
#   make test            voll, parallel, ~2 min — vor jedem Commit
#   make test-seq        voll, sequenziell, ~7 min — nur bei Reihenfolge-Verdacht
#
# Warum parallel gefahrlos ist: `api/tests/conftest.py` gibt JEDER Testdatei
# ihre eigene Datenbank. Mit `--dist loadfile` bleibt eine Datei komplett in
# einem Prozess — die Isolation, auf die die Tests ohnehin gebaut sind, gilt
# unveraendert. Gemessen: 434 s sequenziell -> 106 s mit 12 Prozessen.
#
# `test-seq` bleibt, weil Parallelitaet Reihenfolge-Abhaengigkeiten VERSTECKEN
# und selten auch mal eine flaky Stelle aufdecken kann. Wer einen solchen
# Verdacht hat, prueft ihn hier — nicht im Normalbetrieb.
# --------------------------------------------------------------------------
## voll, parallel (~2 min). Fehlt pytest-xdist, laeuft es sequenziell weiter
## (langsam, aber nie kaputt) und sagt einmal, wie man es schneller bekommt.
test:
	@cd api && if python3 -c "import xdist" 2>/dev/null; then \
	  python3 -m pytest -q -n 12 --dist loadfile; \
	else \
	  echo "Hinweis: 'pip install pytest-xdist' macht diesen Lauf ~4x schneller."; \
	  python3 -m pytest -q; \
	fi

test-seq: ; cd api && python3 -m pytest -q                        ## voll, sequenziell (~7 min)

## Gezielt: make t F=dokumente  -> alle Testdateien, deren Name "dokumente" enthaelt
t:
	@test -n "$(F)" || { echo "Nutzung: make t F=<teil-des-dateinamens>"; exit 2; }
	@cd api && python3 -m pytest -q $$(ls tests/test_*$(F)*.py 2>/dev/null) \
	  || { echo "Keine Testdatei mit '$(F)' gefunden."; exit 2; }

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
