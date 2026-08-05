# HANDOVER — Wiederaufnahme dieser Session

**Stand:** unmittelbar vor Wochenlimit (99 %). Diese Datei dokumentiert alles,
was ein neuer Chat/Agent braucht, um exakt hier weiterzumachen.

## Baumzustand

- Branch: `main`, tree **clean** (alle Änderungen committet + gepusht).
- Letzter Commit: `a868b32 docs: N213 registriert (Abrechnungs-Modell splitten)`.
- Remote: `origin/main` synchron.

## Was in dieser Session fertig wurde (in AUFGABEN.md erledigt-markiert)

Neu abgeschlossen (Commit-Hashes):
- **N187/N188/N193/N194/N195/N196** — E-Tankstelle (Auswahl, Verlauf-Heatmap,
  Blatt, Satz-Karten, KPI-Doppelung raus, Doppelstrich+Sende-Button, Matrix
  kompakt) — Commits `e6d8f77` … `4dff235`.
- **N189/N190** — NK-Positionen Inline-Konfig + Pflicht/Optional + Warmwasser
  grün wenn errechnet — `32f1ac7`.
- **N191/N192** — Stromkette grafisch + Belege verwaltbar + geeichte Menge —
  `18e1b53`.
- **N197/N201/N205** — PV-Sonne animiert, groß, kreuz-und-quer-Strahlen —
  `6c7dd18` `f00015e`.
- **N198(a)/N199** — Heizkörper-Wärmemenge amber bis verteilt; Heizungs-Zähler
  unter „Heizöl & Lieferungen" — `dd2071e`.
- **N200** — PV-Amortisation live E-Tanken + kWh/€-Kringel — `fae26f1`.
- **N202** — Abrechnung-Matrix kompakt + Doppelstrich + Zeitraum/€ im
  Sende-Button — `4dff235`.
- **N203** — Navigation gestaffelt („Objekte" aufklappbar) + Umbenennungen —
  `d16cdaa`.
- **N204** — PV-Eigentümer verschlankt (Invest-€ inline, „+" oben, ausgegraut
  bei 1000 ‰) — `6316fb9`.
- **N206** — PV-Eigenverbrauch €/kWh nur auf verrechnete Menge — `4936805`
  (Nutzer bestätigte „ehrlichen Fix ausliefern").
- **N207** — iOS-Scan KI-Maske gefixt (Foto → JPEG vor Erkennung) — `c584706`.
- **N208/N209** — Strom-Position grün wenn verteilt, Diagramm full-width +
  iOS-Seitenränder 18→12 px — `36b787a` `91e2e82`.
- **N210/N211/N212** — Stammdaten-Objektname unter Titel, Sortierzeile
  einzeilig (⚙-Icon), Ablese-Wizard raus, Vorauszahlungen-Chip weg — `74e93e3`
  `d13d4cb`.
- Zusätzlich: **`CLAUDE.md`** um „## Der rote Faden" (11-Punkte-Checkliste
  aus wiederkehrendem Feedback) ergänzt — `9810369`.

## In Arbeit — Agent läuft (WICHTIG)

**N213 — Abrechnungs-Modell splitten: „Standard" + „Laufer-Spezial"**
- Agent-ID: `a5a5f0993f9cec441` (SendMessage `to:` diese ID zum Fortsetzen).
- Output-Transcript: `/tmp/claude-1001/-home-roman-projects-ImmoCalc/f21352ab-1435-4809-b96f-56f92e5bf3e0/tasks/a5a5f0993f9cec441.output`.
- Registriert in AUFGABEN.md als N213 (offen).
- Auftrag zusammengefasst:
  - Additives `Objekt.modell` (Default `"standard"`; Laufer einmalig auf
    `"laufer_spezial"` per idempotentem Setter).
  - Standard-Modell (für die 4 nicht-Laufer-Objekte): Strom = ein Zähler je
    Einheit direkt (KEINE Stromkette/Netz-PV-Speicher-Verteilung); Heizung =
    KEINE HKV/Wärmemengenzähler-UI, dafür einfache Werte je Einheit
    (Heizkosten + Wärmemenge, kommen von Delta t); Wasser wie überall;
    PV/PV-Amortisation/PV-Eigentümer/E-Tankstelle **komplett versteckt**;
    WEG-Variante nutzt bestehendes `Objekt.weg`.
  - Laufer bleibt **exakt** wie heute — alles ist ein `if
    modell === 'laufer_spezial'`-Gate.
  - Rechenlogik unberührt (nur UI-Gating).
- Dateien im Umfang: `api/app/models.py`, `api/app/migrate.py`,
  `api/app/routers/objekte.py`, `api/tests/` (neue Test-Datei),
  `public/index.html`, `public/zeitraum.html`, `public/strom.html`,
  `public/tankstelle.html`, `public/assets/immo.js`.
- Agent wurde jetzt zusätzlich angewiesen, seinen Fortschritt in
  `scratch/N213_STATUS.md` zu protokollieren (was gemacht, was steht noch aus,
  wo genau) — falls er vor Fertigstellung abbricht.

**Wiederaufnahme:**
1. `git status` — falls uncommitted Änderungen: `git stash push -u -m "N213 wip"`.
2. `scratch/N213_STATUS.md` lesen (falls vorhanden).
3. Ggf. Agent per SendMessage mit ID `a5a5f0993f9cec441` fortsetzen; oder in
   einer neuen Session einen frischen Agent mit dem Prompt aus dem
   Transcript-File und dem Status-File anlernen.
4. Wenn N213 fertig ist: zentral committen (Frontend + Backend Files), Tests
   grün prüfen, Screenshots eines Standard- und des Laufer-Objekts zum
   Vergleich anfertigen, in AUFGABEN.md abhaken, pushen.
5. Danach ein `! ./deploy.sh` — die Migration + N213 + alle noch offenen
   Backend-Teile (siehe unten) werden zusammen live.

## Offene Themen des Nutzers

- **N198(b)** — die volle Heizmengenverteilungs-Rechenlogik (HKV × Faktor →
  je Einheit) — der Nutzer macht das selbst „die Tage". Nur registriert, nicht
  angefangen. Der Sofort-Fix (kein falsches Grün) ist schon in `dd2071e` drin.
- Follow-up-Aufräumen: `ablesungWizard()` und die `.ablesebtn`-CSS in
  `public/zeitraum.html` sind seit N211 tot; sauber entfernen (in einem
  gezielten Cleanup, nicht mitten in einer laufenden Änderung).
- Der visuelle Screenshot des N210a-Kopfs (Stammdaten in `objekt.html`) steht
  noch aus — der Playwright/Chromium-Prozess war am Sessionende instabil.
  Änderung ist ein risikoarmer Markup/CSS-Umbau; beim nächsten Durchgang
  visuell bestätigen.

## Deploy-Lücke (Backend-Teile, die live warten)

Ein einmaliges `./deploy.sh` aktiviert alle backend-seitigen Änderungen der
Session (Migration von N213 mit, wenn der Agent fertig ist):
- N188 Verlaufs-€/km, N193 Monatsgenaue Abrechnungs-Markierung,
- N189 Pflicht/Optional-Persistenz,
- N192 geeichte Menge setzen + Netz-Belege,
- N194 2 €-Benzin,
- N200 E-Tanken-Live-Werte in der Amortisation,
- N206 PV-Eigenverbrauch €/kWh nur auf verrechnete Menge,
- N213 Migration `Objekt.modell` + Laufer-Setter (sobald Agent durch).

Alle Frontend-Änderungen sind live-gemountet und schon aktiv.

## Session-Prinzipien (jetzt in CLAUDE.md fest verankert)

`CLAUDE.md` → Abschnitt **„## Der rote Faden — bei JEDER sichtbaren Änderung
mitdenken"** (11 Punkte + Verifizierungs-/Deploy-Regel). Ein neuer Chat
lädt das automatisch mit.

## Kontakte / Environments

- Live: http://192.168.178.10:8091 (`public/` ist live-gemountet; API rebuild
  via `./deploy.sh` ~30 s auf dem Host).
- Repo: github.com/premiumcola/ImmoCalc · Branch `main`.
- Venv für Tests: `../scratch/venv/bin/python -m pytest -q` aus `api/`
  (der einzige pre-existing OCR-Fehler
  `test_ocr.py::test_bild_pdf_nimmt_den_rasterweg` ist umgebungsbedingt,
  gefahrlos zu ignorieren).
