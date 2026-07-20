# ImmoCalc — Projektleitfaden für den Code-Agent

Nebenkosten-/Betriebskostenabrechnung für echte Objekte mit echten Mieterdaten.
Eine Umgebung, ein Stack, eine URL.

## Grundhaltung

**Autonom.** Selbstständig arbeiten, keine Rückfragen, keine Bestätigungen
abwarten. Bei Unklarheit die sinnvollste Lösung wählen und weitermachen.
Nach Abschluss: kurze Zusammenfassung, was gemacht wurde.

**Parallel.** Unabhängige Schritte gleichzeitig ausführen — mehrere Tool-Calls
in einem Block, breite Recherche über Subagents. Nie sequenziell abarbeiten,
was nebenläufig gehen kann.

**Hochwertig statt schnell.** Lieber eine Sache fertig und verifiziert als drei
halbe. Jede Änderung wird belegt: Tests grün, Browser-Check grün, Logs sauber.
Nie behaupten, etwas funktioniere, ohne es geprüft zu haben.

**Fehler:** zweimal selbst zu fixen versuchen. Nach dem dritten Fehlschlag
stoppen und den exakten Fehlertext zeigen. Nie auf kaputter Basis weiterbauen —
erst `git log` prüfen und ggf. revertieren.

## Architektur

```
public/        statisches Frontend (Vanilla HTML/CSS/JS, kein Build-Step)
dashboard/     nginx: serviert public/, proxyt /api/ an den API-Container
api/           FastAPI + SQLModel/SQLite
  app/engine.py   Rechen-Engine (Verteilung, Interpolation, § 35a)
  app/models.py   Datenmodell
  app/main.py     Endpunkte
  app/seed.py     Seed der zwei echten Objekte
  tests/          pytest — Referenzzahlen aus den Excel-Dateien
```

**Kein DEV-Stack.** `public/` ist in den Container gemountet: jede
Frontend-Änderung ist ohne Deploy sofort auf der Seite. Nur Änderungen an
API-Code, Dockerfiles, nginx-Config oder Compose brauchen `./deploy.sh` (~30 s).

- UI: http://192.168.178.10:8091 · API intern, nicht published
- Container: `immocalc-dashboard`, `immocalc-api`
- Repo: github.com/premiumcola/ImmoCalc · Branch `main`

## Bauen / Testen — in dieser Reihenfolge

```bash
make test              # Engine- + API-Tests (pytest) — MUSS grün sein
./deploy.sh            # nur nötig bei API/Docker/nginx-Änderungen
make check             # echter Browser gegen die laufende Instanz
```

`make check` (tests/smoke.mjs) prüft Status, Content-Type, Pflicht-Elemente,
JS-Konsolenfehler und erkennt ungewollte Downloads.

Fertig gemeldet wird erst, wenn Tests grün sind und `docker logs immocalc-api
--tail 50` keine Fehler zeigt.

## Visuelle Abnahme — Pflicht bei jeder UI-Änderung

Ein grüner Exit-Code sagt nichts über das Aussehen. Zu jeder Änderung, die
sichtbare Oberfläche betrifft, gehört: Screenshot machen **und die Bilder mit
dem Read-Tool tatsächlich ansehen** — nicht nur erzeugen. Playwright und
Chromium sind eingerichtet.

**In allen drei Geräteklassen.** `node tests/matrix.mjs` fährt jede Seite in
iPhone (390), iPad (820) und Desktop (1440) ab und legt die Bilder in
`tests/screenshots/matrix/`. Jede Klasse wird einzeln angesehen — Fehler
treten fast immer nur in einer davon auf: das Kachelraster kippt nur auf dem
iPhone, die Seitenleiste nur auf dem Desktop, Umbrüche nur auf dem iPad.

Dabei die betroffenen Flows wirklich durchklicken (Objekt → Zeitraum →
Ergebnis, Wizard bis zum Abschluss), nicht nur die Startseite laden.

Worauf geachtet wird:

- **Kein klebender Text.** Überschrift und Beschreibung brauchen sichtbaren
  Abstand. Klassiker: `margin` auf einem `<span>` — wirkt bei inline-Elementen
  nicht. `display:block` setzen.
- **Luft.** Großzügige Abstände zwischen Blöcken, nichts drängt sich.
- **Kein Überlauf.** Nichts läuft aus Karten heraus, nichts wird abgeschnitten,
  die Seite scrollt nie horizontal. Auch mit langen Namen und großen Beträgen.
- **Ausrichtung.** Kanten fluchten, Icons sitzen mittig zur Textzeile.
- **Lesbarkeit.** Ausreichend Kontrast, keine zu kleinen Schriftgrade,
  Buttons klar erkennbar.
- **Zustände.** Wie sieht es mit null Objekten aus, wie mit vielen? Leere
  Zustände brauchen eine sinnvolle Ansicht statt einer leeren Fläche.
- **Kopfzeilen einzeilig.** Titel und Untertitel dürfen nicht umbrechen —
  meist ein Zeichen dafür, dass dieselbe Information doppelt drinsteht.
- **Menüleisten.** Navigation auf jeder Breite erreichbar, aktiver Eintrag
  erkennbar, Einträge nicht auseinandergezogen (geerbtes `flex:1` in einer
  Spalte) und nichts vom Inhalt verdeckt.

Sieht etwas gedrängt oder schief aus: nachbessern und erneut ansehen. Beim
Melden sagen, was visuell geprüft wurde. Auffällige Screenshots dem Nutzer
mitschicken.

## Git — autonom, kleinteilig, nachvollziehbar

Nach jeder abgeschlossenen Teilfunktion sofort committen und pushen. Jeder
Git-Befehl ein eigener Tool-Call, nie verkettet, nie mit `cd`:

```
git add -A
git commit -m "feat: add POST /api/objekte"
git push origin main
```

Commit-Message englisch, präzise, max 60 Zeichen, eine Funktion pro Commit —
so bleibt jeder Schritt einzeln revertierbar. Kaputtes selbst revertieren, ohne
zu fragen.

## Engine — Invarianten, nicht brechen

- `verteile_nach_wert`: Summe der Anteile == Gesamtkosten (exakt)
- Interpolation: `ist_diff * soll_tage/ist_tage` (Musterstraße-Wasser: 142.577)
- Referenzzahlen aus den Excel-Dateien sind in `api/tests/` fixiert.
  Rote Tests sind ein Fehler. Tests nur anpassen, wenn sich die Fachlogik
  bewusst ändert — nie, um sie grün zu bekommen.

## Code

**Modular.** Kleine Einheiten mit einer klaren Aufgabe. Rechenlogik gehört in
die Engine, nicht in Endpunkte; Endpunkte bleiben dünn. Frontend-Seiten teilen
sich Stil und Bausteine, statt sie zu kopieren. Vor dem Neuschreiben prüfen, ob
es die Funktion schon gibt.

**Sauber.** Kein toter Code, keine ungenutzten Variablen, keine Dopplungen.
Python: Type-Hints auf Funktions-Signaturen, `logging` statt `print()`.
JavaScript: kein `console.log` im Produktionscode.

**Dynamisch.** Nichts hartcodieren, was aus Daten kommen kann — Objekte,
Kostenarten, Zeiträume, Fristen kommen aus der API. Keine Mockup-Daten in
produktivem Code. Die UI baut sich aus dem, was da ist, und funktioniert auch
bei null Objekten oder zwanzig.

**Kein Framework.** Vanilla HTML/CSS/JS, kein Build-Step, keine externen
Libraries außer Google Fonts.

## Design — ruhig, klar, wertig

Die bestehende Sprache konsequent weiterführen. Sanft statt laut: viel Weißraum,
gedeckte Farben, ein Akzent.

- Farben: `--paper #E8ECEC` · `--sheet #FFF` · `--ink #16262C` ·
  `--teal #0F6E5C` · `--amber #916212` · `--pos #2E7D4F` · `--neg #B24229`
- Schriften: Space Grotesk (Display) · Inter (Body) · IBM Plex Mono (Labels)
- Icons: Inline-SVG-`<symbol>`-Sprites im bestehenden flachen Stil,
  keine Icon-Libraries
- Weniger Text, mehr Icon. Jede Information nur einmal zeigen.
- Abgerundete Ecken überall (min. 8 px), Tiefe über Farbabstufung statt
  dünner Rahmenlinien
- Mobil zuerst: 440 px Spalte, muss auf dem iPhone gut aussehen.
  Touch-Targets min. 44×44 px, kein hover-only Verhalten, `dvh` statt `vh`

## Daten schützen

Echte Mieter- und Objektdaten. Die SQLite liegt außerhalb des Repos unter
`/mnt/user/appdata/immocalc-live/data/immocalc.db`.

- Bestehende Daten nur additiv ergänzen (merge/setdefault), nie überschreiben
- `.env`, `data/`, `*.db` gehören nicht ins Repo (stehen in `.gitignore`)
- Bei "Daten weg": zuerst Bind-Mount und `docker volume ls` prüfen
- Bei seltsamem Frontend-Verhalten zuerst Browser-Cache prüfen
  (Strg+Shift+R). HTML wird mit `Cache-Control: no-store` ausgeliefert.

## Shell

Ein Tool-Call = ein Befehl. Keine Inline-Heredocs (erst Datei schreiben, dann
ausführen, dann aufräumen — Skripte nach `scratch/`, steht in `.gitignore`).
Kein `cd <pfad> && <befehl>`, kein `eval`, kein `curl … | bash`, keine Backticks.

## Nächste Schritte

Siehe `ROADMAP.md`.
