# ImmoCalc – Deploy auf Unraid (Git-Clone, LIVE + DEV)

Ergebnis: zwei gespiegelte Umgebungen aus demselben Code —
**LIVE** `:8091` (stabil) und **DEV** `:8092` (iterieren, `public/` live gemountet).
**Echte Mieter-/Objektdaten kommen NIE ins Git** (siehe unten).

## 0) Einmalig: Repo auf GitHub anlegen (ohne Nutzerdaten)
Im Projektordner (lokal):
```bash
cd immocalc
git init && git add . && git commit -m "ImmoCalc initial"
# Sicherheits-Check: dürfen NICHT auftauchen -> Ausgabe muss leer sein:
git ls-files | grep -Ei '(^|/)\.env$|\.db$|(^|/)data/|uploads/' && echo "STOP: Nutzerdaten!" || echo "clean ✔"
git remote add origin git@github.com:<user>/ImmoCalc.git   # privat empfohlen
git branch -M main && git push -u origin main
```
`.env`, DB, `data/`, Uploads sind per `.gitignore` ausgeschlossen. Der ausgelieferte
Code enthält nur **fiktive Demo-Daten** – deine echten Objekte gibst du erst in der
laufenden App ein; die landen ausschließlich in `DATA_DIR` (außerhalb des Clones).

## 1) Auf Unraid klonen
SSH auf den Server:
```bash
cd /mnt/user/appdata
git clone https://github.com/<user>/ImmoCalc.git immocalc
cd immocalc
```

## 2) Konfigurieren
```bash
cp .env.example .env
nano .env        # Ports/IP/PUID/PGID prüfen (Defaults passen meist)
```
`DATA_DIR`/`CONFIG_DIR` zeigen bewusst NACH AUSSERHALB des Clones
(`/mnt/user/appdata/immocalc-live` bzw. `-dev`) → `git pull` fasst deine Daten nie an.

## 3) Starten (LIVE + DEV)
```bash
./deploy.sh            # baut & startet alle 4 Container, seedet DB-Verzeichnisse
```
Danach:
- **LIVE**  UI  → `http://<unraid-ip>:8091`   (Container `immocalc-dashboard` + `immocalc-api`)
- **DEV**   UI  → `http://<unraid-ip>:8092`   (Container `immocalc-dashboard-dev` + `immocalc-api-dev`)

Nur eine Umgebung: `./deploy.sh live` bzw. `./deploy.sh dev`.
Alternativ via GUI: Plugin **Compose Manager** → Stack auf den Ordner zeigen → *Compose Up*.

## 4) Updaten
```bash
cd /mnt/user/appdata/immocalc
git pull
./deploy.sh            # baut die geänderten Images neu, ersetzt Container
```
Deine Daten (SQLite in `DATA_DIR`, Belege) bleiben unberührt.

## 5) Tests & Selfcheck (für den Code-Agent)
```bash
make test              # Engine- + API-Tests (pytest)
npm install && npx playwright install chromium && ./check.sh   # Browser-Selfcheck
```

## Was garantiert NICHT im Git landet
- `.env` (Ports/Secrets)   · SQLite-DB (`*.db`) · `data/` und alle Uploads/Belege
- Der committete Code hat nur fiktive Demo-Objekte (Musterstraße 5, Beispielweg 6a).
- Echte Daten leben nur zur Laufzeit in `DATA_DIR` außerhalb des Clones.
