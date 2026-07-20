# ImmoCalc — Projektleitfaden für den Code-Agent

Nebenkosten-/Betriebskostenabrechnung. Monorepo im jFlow-Stil, LIVE + DEV.

## Architektur
- `dashboard/` — nginx serviert `public/` (Frontend: klickbare UI + Mockups),
  proxyt `/api/` an den API-Service (envsubst `${API_UPSTREAM}`).
- `api/` — FastAPI + SQLite. Enthält die **Rechen-Engine** (`api/app/engine.py`),
  Datenmodell (`api/app/models.py`), Seed der zwei echten Objekte (`api/app/seed.py`),
  Endpunkte (`api/app/main.py`). Seedet beim Start, wenn DB leer.
- `public/workflow.json` — Frontend-Konfig (aktive Kostenarten je Immo), jFlow-Muster.

## Konventionen (wie jFlow)
- `build: context: .` + `dockerfile: <service>/Dockerfile`
- `container_name`-Präfix `immocalc-`
- `.env`-getrieben (`${VAR:-default}`), `PUID/PGID/TZ`, Ports über `.env`
- YAML-Anchors für LIVE/DEV, top-level `volumes:`

## Bauen / Starten / Testen
```bash
./deploy.sh            # seedet .env+Config, baut & startet live+dev
make test              # Engine- + API-Tests (pytest)  -> MUSS grün sein
./check.sh             # Headless-Browser-Selfcheck der Frontend-Seiten (Playwright)
```
- LIVE UI: http://<host>:8091 · DEV UI: http://<host>:8092 · API intern (nicht published)
- API-Docs (bei laufendem Stack): `/docs` hinter dem Dashboard-Proxy: `http://<host>:8091/api` → besser direkt über `docs` am API-Container.

## Engine — Invarianten (nicht brechen!)
- `verteile_nach_wert`: Summe der Anteile == Gesamtkosten (exakt).
- Interpolation: `ist_diff * soll_tage/ist_tage` (Musterstraße-Wasser: 142.577).
- Referenzzahlen aus den Excel-Dateien sind als Tests fixiert
  (`api/tests/test_engine.py`, `test_api.py`). Bei Engine-Änderungen Tests anpassen
  nur, wenn die Fachlogik sich bewusst ändert — sonst sind rote Tests ein Fehler.

## Agenten-Loop (empfohlen)
1. Code ändern. 2. `make test`. 3. `./deploy.sh dev` (dev mountet `public/`, kein
Rebuild fürs Frontend). 4. Browser auf `http://<host>:8092` bzw. `./check.sh` →
Screenshots in `tests/screenshots/`. 5. Report lesen, nachbessern.

## Nächste Schritte
Siehe `ROADMAP.md`. Kurz: Anteile aus Zählern/Schlüsseln in der Engine berechnen
(statt vorberechnet im Seed), Beleg-Upload + OCR-Worker, PDF-Worker, Auth, Excel-Import.
