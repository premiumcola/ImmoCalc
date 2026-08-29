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

## Aufgabenstand

`AUFGABEN.md` führt alle Anforderungen mit römischer Nummer, Status und Commit.
**Bei jeder neuen Anforderung dort eintragen, bei Fertigstellung abhaken.** Der
Nutzer soll nichts zweimal sagen müssen.

Das gilt auch für Anforderungen, die mitten in einer laufenden Arbeit kommen:
sofort eintragen, bevor sie im Gesprächsverlauf untergehen. Ebenso für alles,
was bei einer Prüfung gefunden und nicht sofort behoben wird — ein Fund ohne
Eintrag ist ein vergessener Fund.

## Parallel arbeiten

Unabhängige Arbeit wird auf Subagents verteilt, statt sie nacheinander
abzuarbeiten. Drei Regeln machen das verlässlich:

- **Dateibesitz ist exklusiv.** Jeder Agent bekommt genannt, welche Dateien
  ihm gehören, und fasst keine anderen an. Was mehrere brauchen (die
  Navigationsleiste, `immo.css`, gemeinsame Bausteine), wird vorher zentral
  festgelegt und im Auftrag mitgegeben.
- **Prüfen gehört zum Auftrag.** Jeder Agent lässt seine Tests laufen und
  sieht sich seine Screenshots mit dem Read-Tool an. „Fertig" ohne Nachweis
  gilt nicht.
- **Committet wird zentral**, nicht von den Agents — sonst überholen sich die
  Stände.

Bei einer Fehlersuche lohnt derselbe Schnitt: je ein Agent für Rechenlogik,
Datenintegrität, Ablauflogik und Modularisierung. Sie melden nur, geändert
wird zentral — und jeder Fund wird nachgeprüft, bevor er als Fehler gilt.

## Architektur

```
public/        statisches Frontend (Vanilla HTML/CSS/JS, kein Build-Step)
  assets/      immo.css, immo.js, charts.js, scan.js, kostenicons.js,
               auswahl.js
  index.html         Objekte · eingang.html      Dokumente
  wertentwicklung.html  Wert & Cashflow
  nebenkosten.html   Nebenkostenabrechnung
  eigentuemer.html   Eigentümer und Anteile
  settings.html      Einstellungen · objekt.html · zeitraum.html · onboarding.html
dashboard/     nginx: serviert public/, proxyt /api/ an den API-Container
api/app/
  engine.py      Rechen-Engine (Verteilung, Interpolation, § 35a)
  models.py      Datenmodell
  migrate.py     ergänzt fehlende Spalten — nie löschen, nie umbenennen
  nextcloud.py   WebDAV; Schreibzugriff nur unterhalb des Home-Ordners
  mailversand.py SMTP über das Postfach des Nutzers
  abrechnung_pdf.py  Abrechnung als PDF, handgeschrieben, ohne Bibliothek
  cashflow.py    Cashflow je Einheit, Sankey-Fluss
  vermoegen.py   Wert, Restschuld, Eigenkapital, Beleihung
  export.py      Sicherung als JSON, Wiederherstellung, Löschen
  nachpflege.py  welche Angaben nach einer Erweiterung noch fehlen
  ocr.py         Texterkennung — optional, ohne tesseract einfach stumm
  bezeichnung.py Ordnernamen von grob nach fein, Vorlagen
  turnus.py      Zahlungsturnus monatlich … jährlich
  erinnerungen.py Fristen und erwartete Belege
  wachdienst.py  prüft den Eingang alle 15 Minuten
  routers/       objekte, stammdaten, besitz, auswertung, cloud, dokumente,
                 mail, versand
  ../tests/      pytest — Referenzzahlen aus den Excel-Dateien
```

## Nutzerdaten in der Cloud

Nextcloud enthält die echten Unterlagen. Deshalb:

- **Schreibzugriffe nur unterhalb des Home-Ordners.** `nextcloud.py` prüft das
  vor jedem MKCOL, PUT und MOVE (`_pruefe_schreibrecht`). Diesen Riegel nie
  umgehen, auch nicht „nur kurz“.
- Nie löschen. Ordner werden per MKCOL angelegt (405 = existiert bereits),
  Dateien per MOVE verschoben, nichts überschrieben — der Aufrufer sorgt für
  einen freien Namen.
- Vom Nutzer selbst angelegte Ordner bleiben unangetastet.

**Kein DEV-Stack, und seit 23.08.2026 auch kein Live-Mount mehr.** Früher war
`public/` in den Container gemountet und jede Frontend-Änderung sofort auf der
Seite — **das gilt nicht mehr.** Das Frontend steckt jetzt im Image. Der Weg
auf den Server ist für ALLE Änderungen derselbe:

```
git push  →  GitHub Actions baut  →  ghcr.io  →  Watchtower rollt aus (~5 min)
```

Auf dem Unraid wird nichts gebaut und nichts von Hand deployt. Das bedeutet
konkret: **nie behaupten, eine Frontend-Änderung sei „sofort live"** — nach
einem Push dauert es einige Minuten, und der Nutzer muss neu laden. Wer die
Änderung sofort sehen will, nutzt lokal `docker-compose.override.yml.example`
(holt den Mount zurück, ohne die Produktion anzufassen).

`./deploy.sh` ist damit **kein Deploy-Weg mehr**, sondern ein Altbestand aus
der Zeit lokaler Builds — nicht mehr benutzen.

- UI: http://192.168.178.10:8091 · API intern, nicht published
- Container: `immocalc-dashboard`, `immocalc-api`
- Repo: github.com/premiumcola/ImmoCalc · Branch `main`
- **Die laufende Stack-Definition liegt NICHT in diesem Repo**, sondern in
  `premiumcola/devBox` → `immocalc/docker-compose.yml`. Das
  `docker-compose.yml` hier ist eine Abbildung davon; weichen beide ab, gilt
  die Datei im devBox-Repo. Stand und offene Punkte: `MIGRATION.md`.

## Bauen / Testen — in dieser Reihenfolge

```bash
make t F=dokumente     # gezielt, ~10 s — WÄHREND der Arbeit
make test              # voll, parallel, ~2 min — vor JEDEM Commit, MUSS grün sein
                       # (kein Deploy-Schritt mehr — Watchtower rollt aus)
make check             # Browser gegen die laufende Instanz
make check-app         # Prüfstand: alle Flows in drei Geräteklassen
make test-seq          # voll, sequenziell, ~7 min — nur bei Reihenfolge-Verdacht
```

**Die kleinste Stufe nehmen, die die Frage beantwortet.** Wer eine Funktion in
`dokumente.py` ändert, prüft sie mit `make t F=dokumente` in zehn Sekunden —
nicht mit sieben Minuten Vollauf. Der volle Lauf gehört vor den Commit, nicht
zwischen zwei Zeilen. Gemessen: gezielt ~10 s · voll parallel 106 s ·
voll sequenziell 434 s.

Parallel ist gefahrlos, weil `api/tests/conftest.py` **jeder Testdatei eine
eigene Datenbank** gibt und `--dist loadfile` eine Datei komplett in einem
Prozess hält — es gilt genau die Isolation, auf die die Tests ohnehin gebaut
sind. `make test-seq` bleibt für den Fall, dass eine Reihenfolge-Abhängigkeit
im Verdacht steht; im Normalbetrieb ist es Verschwendung.

**Klein schneiden, früh committen.** Nach jeder fertigen Teilfunktion prüfen
(gezielt), committen, weitermachen — nicht fünf Themen sammeln und am Ende
einmal groß testen. Sonst hängen fertige Änderungen unnötig lange
unveröffentlicht herum und lassen sich bei einem Fehler nicht mehr einzeln
zurücknehmen.

`tests/harness.py` serviert API und `public/` unter einer Herkunft — damit
lassen sich neue Endpunkte prüfen, ohne auf einen Deploy zu warten. Aus dem
Repo-Wurzelverzeichnis starten, nicht aus `api/`.

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

## Der rote Faden — bei JEDER sichtbaren Änderung mitdenken

Verdichtetes, wiederkehrendes Nutzer-Feedback. Diese Punkte gehören von selbst
in jede Gestaltungsentscheidung — nicht erst, wenn der Nutzer sie erneut nennt.
Er sagt nichts gern zweimal.

1. **Visuell statt Text.** Zahlen grafisch fassen, nicht als Fließtext: Balken
   (Höhe ∝ Wert), Donut/Kreis, Heatmap, Chips/Stat-Karten, `Menge × Satz = €`,
   Icons, kleine Animationen. Überall im Produkt ein visuelles Element streuen,
   das man lieber ansieht als liest. Text radikal kürzen.
2. **Erklärtexte ins i-Popup**, nie als Dauer-Textwand. Info-Knöpfe sparsam,
   gleiche Info-i zusammenführen (nicht je Zeile eins).
3. **Jede Information genau einmal.** Doubletten (derselbe Wert/Text an zwei
   Stellen, redundante Summenblöcke, Herleitungszeilen doppelt) sind ein Fehler.
4. **Kein Leerraum, keine „Luft".** Große leere Flächen füllen (mit sinnvollem
   Inhalt) oder wegstauchen; benachbarte Blöcke auf gleiche Höhe bringen; die
   freie Breite (Desktop) nutzen. „Zu groß / leer / dämlich" ist ein Bug.
5. **Kompakt & zusammengefasst.** Weniger Bubbles/Zeilen; Bedienelemente
   zusammenführen (Matrix statt drei gestapelter Bubble-Reihen); dichtere
   Chooser (Dropdown/Matrix/Grid) statt endloser Pillen.
6. **Konsistente Abstände.** Innenabstände, Ränder, Radien überall gleich,
   Kanten fluchten.
7. **Keine Dauer-Warnbanner.** Hinweise/Fehler bedienbar machen (Weg zum
   Beheben, Beleg löschen/wählen, Wert eintragen) oder auflösen — nicht
   dauerhaft stehen lassen.
8. **Kontext in die Aktion.** Betrag + Zeitraum in den Button
   („Mai, Jun 2026 · 80,75 € senden"); finale Summe deutlich (Doppelstrich).
   Das „+"-Muster oben rechts fürs Hinzufügen; ausgegraut + Hinweis, wenn
   nichts hinzuzufügen ist (z. B. alle 1000 ‰ vergeben) statt Inline-Formular.
9. **Klare Namen, gestaffelte Hierarchie.** Singular; Fachjargon raus aus
   Menüs (kein „Amortisation" → „PV Anlagen"); sprechende Namen. Unterpunkte
   unter ihr Elternelement einrücken/aufklappen.
10. **Dynamisch & live.** Was ableitbar ist, nicht manuell eintragen lassen;
    live/tagesgenau mitrechnen (automatische Prozesse laufen ohnehin).
11. **„Erledigt/grün" nur wenn wirklich fertig.** Ein bloßer Betrag genügt
    nicht — eine Verteilposition ist erst erledigt, wenn verteilt. Pflicht-
    aber-leer bekommt ein konsistentes rotes Signal, Optionales nicht.

**Verifizierung & Deploy — auch das ist der rote Faden:**

- Jede sichtbare Änderung: Screenshot in iPhone/iPad/Desktop **ansehen**
  (Read-Tool), Konsole 0 Fehler, betroffene Flows durchklicken (siehe
  „Visuelle Abnahme").
- **Ausroll-Lücke aktiv nennen.** Nichts ist mehr sofort live — Frontend wie
  Backend gehen über Push → CI → Watchtower (~5 min). Nach jeder sichtbaren
  Änderung dem Nutzer klar sagen, dass sie erst nach diesem Lauf und einem
  Neuladen ankommt; vorab per Harness prüfen, damit „funktioniert nicht" nie
  am noch nicht ausgerollten Stand hängt. Nie „ist schon bei dir" sagen,
  solange die CI nicht durch ist.

## Daten schützen

Echte Mieter- und Objektdaten. Die SQLite liegt außerhalb des Repos unter
`/mnt/user/appdata/immocalc-live/data/immocalc.db`.

**Schemaänderungen sind ausnahmslos additiv.** Der Nutzer pflegt seine
Immobilien laufend ein, während das Datenmodell noch wächst. Deshalb gilt:

- Neue Felder immer mit Vorgabewert oder `Optional` — nie als Pflichtfeld
  ohne Default, sonst bricht der Bestand.
- Spalten werden ergänzt (`api/app/migrate.py`), nie umbenannt, nie entfernt.
  Ein Feld, das nicht mehr gebraucht wird, bleibt stehen und wird ignoriert.
- Kein `drop_all`, kein `DROP TABLE`, kein `DELETE FROM` — Löschen passiert
  ausschließlich durch eine bewusste Nutzeraktion über die Oberfläche.
- Der Seed legt nur an, wenn die Datenbank leer ist. Diese Bedingung nie
  aufweichen, sonst landen Demo-Objekte zwischen echten Daten.
- `test_eingegebene_daten_ueberleben_ein_update` prüft genau das. Der Test ist
  ein Wächter — schlägt er fehl, ist die Änderung falsch, nicht der Test.

Muss ein Feld inhaltlich anders belegt werden, wird es neu angelegt und die
Übernahme dem Nutzer angeboten — bestehende Eingaben nie automatisch ersetzen.

**Löschen gibt es nur an einer Stelle:** `DELETE /api/objekte/{slug}` — vom
Nutzer ausgelöst, mit Rückfrage, und erst nachdem `export.exportiere` eine
JSON-Sicherung in die Nextcloud geschrieben hat. Entfernt wird ausschließlich
aus der Datenbank; die Dateien in der Cloud gehören dem Nutzer und bleiben.

**Routen-Reihenfolge beachten.** `stammdaten.py` hat den Fänger
`/objekte/{slug}/{bereich}`. Jeder spezifischere Pfad darunter muss *vorher*
registriert werden (siehe `main.py`: `besitz` vor `stammdaten`), sonst
antwortet der Fänger mit „Unbekannter Bereich".

- Bestehende Daten nur additiv ergänzen (merge/setdefault), nie überschreiben
- `.env`, `data/`, `*.db` gehören nicht ins Repo (stehen in `.gitignore`)
- Bei "Daten weg": zuerst Bind-Mount und `docker volume ls` prüfen
- Bei seltsamem Frontend-Verhalten zuerst Browser-Cache prüfen
  (Strg+Shift+R). HTML wird mit `Cache-Control: no-store` ausgeliefert.

## Shell

Ein Tool-Call = ein Befehl. Keine Inline-Heredocs (erst Datei schreiben, dann
ausführen, dann aufräumen — Skripte nach `scratch/`, steht in `.gitignore`).
Kein `cd <pfad> && <befehl>`, kein `eval`, kein `curl … | bash`, keine Backticks.

## Arbeitsweise: Token-effizient & parallel

Ziel: Ergebnisqualität hoch halten, Token-Verbrauch niedrig.

- **Goal-first:** Zuerst das Ziel nennen, in kurze Checkliste zerlegen,
  Punkt für Punkt abarbeiten und nach jedem Schritt prüfen.
- **Delegieren:** Umfangreiche, wenig anspruchsvolle Arbeit (Dateien lesen,
  Code durchsuchen, Logs parsen, Boilerplate, Tests laufen lassen) an
  Subagenten via Task-Tool. Der Haupt-Kontext bleibt schlank — nur
  Entscheidungen und Ergebnisse landen in der Hauptschleife.
- **Parallelisieren:** Unabhängige Teilaufgaben in EINER Nachricht mit
  mehreren Task-Aufrufen starten (nicht nacheinander).
- **Modell-Sparsamkeit:** Das stärkste Modell (Opus) für Architektur,
  Planung, schwierige Entscheidungen; mechanische Ausführung an Sonnet oder
  Haiku. Standard: `opusplan` (Opus plant, Sonnet führt aus).
- **Kein Verschwenden:** Keine schon gelesenen Dateien erneut lesen, keine
  redundanten Tool-Aufrufe, keine Kontext-Wiederholungen. Antworten knapp.
- **Große Umbauten in Häppchen:** Bei Refactorings/Modularisierung
  modulweise vorgehen, nach jedem Modul committen, dann weiter.
- **Ultracode NICHT einschalten**, außer maximale Gründlichkeit ist
  wichtiger als Kosten (verbraucht bewusst mehr Tokens, >25 Agenten möglich).

## Nächste Schritte

Siehe `ROADMAP.md`.
