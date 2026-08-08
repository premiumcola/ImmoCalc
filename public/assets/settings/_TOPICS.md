# public/assets/settings/ — Module der Einstellungen-Seite

N216 (C). Aufgeteilt aus dem bisherigen Inline-`<script type="module">` in
`public/settings.html`. Reines Refactoring — kein Verhaltensunterschied.
Import aus HTML über `./assets/settings/…`.

## Module

| Datei              | Zustaendig                                                   |
|--------------------|--------------------------------------------------------------|
| `state.js`         | Geteilte Helfer (`feldmeldung`, `meldungWeg`, `vHole`, `vHoleGeteilt`, `vGeteiltReset`, `vKurz`, `vModell`, `ortszeit`, `belegText`); Konstanten `VZEITGRENZE`, `VSTRICH`, `VSYMBOLE` |
| `verknuepfungen.js`| N133 Live-Kacheln: `verknuepfungenInit` — baut die Kachelreihe, verdrahtet „Erneut prüfen", steuert Klicks (Kachel→Zeile scrollen, Wallbox einrichten) |
| `version.js`       | `versionZeigen` — Kopfzeile „ImmoCalc · <sha> · <zeit>" + die letzten fünf Änderungen aus `version.json` (Fallback `/health`) |
| `nextcloud.js`     | Nextcloud-Verbindung + Home-Ordner-Wähler: `nextcloudInit`, `zustandLaden` |
| `ki.js`            | KI-Beleg-Auslese (Anthropic-Schlüssel): `kiInit`, `kiZustandLaden` |
| `mail.js`          | Postfach (SMTP) + Testmail: `mailInit`, `mailZustand` |
| `vorlage.js`       | Ordner-Benennung (Vorlage für Objektordner): `vorlageInit`, `vorlageLaden` — löst nach Speichern `umzugLaden` aus; die Zeile erscheint nur ohne gesetzte Vorlage (N310) |
| `umzug.js`         | Benennung nachziehen (Trockenlauf + Rückfrage + Ergebnis): `umzugInit`, `umzugLaden` |
| `import.js`        | Sicherung einlesen (JSON → neues Objekt): `importInit` |
| `rechenlogik.js`   | Rechenlogik-Übersicht (statischer Inhalt): `rechenlogikInit` — öffnet nur den Dialog |

## `state.js`-Vertrag

`state.js` hat keinen mutierten Objekt-Zustand — die Einstellungen-Seite
teilt zwischen den Modulen keinen. Was gebraucht wird, sind Helfer:

- **Meldungen im Dialog**: `feldmeldung(feld, text, gut?)`, `meldungWeg(feld)`.
- **Statusabruf für Kacheln**: `vHole(pfad, frist?)` mit knapper Frist, nie
  werfend — gibt `{da:false}` / `{fehler:'…'}` / `{da:true, daten:…}`.
- **Geteilter Cache** für Kacheln, die am selben Endpunkt hängen (KI +
  SolarEdge lesen beide `/ki/status`): `vHoleGeteilt(pfad)`; das Setzen der
  Kachel-Farbe `vGeteiltReset()` — leert den Cache beim erneuten Prüfen.
- **Formatierer**: `vKurz(url)` (Schema/Trailing weg), `vModell(name)` (Datums-
  Suffix weg), `ortszeit(iso)` (deutsche Kurzform), `belegText(n)` (Ein-/
  Mehrzahl).
- **Konstanten**: `VZEITGRENZE = 6000` (ms), `VSTRICH` (SVG-Attribute für die
  Kachel-Symbole), `VSYMBOLE` (fünf Pfad-Sets: wolke, wallbox, solar, funke,
  brief).

`vGeteilt` liegt als Modul-`let` intern — nicht exportiert, weil ES-Modul-
Bindings für Primitive unveränderlich sind; stattdessen kapseln
`vHoleGeteilt` und `vGeteiltReset` den Zugriff.

Der pro-Section-Zustand (`ncZustand`, `kiZustand`, `trockenlauf`,
`anbieterListe`) bleibt in seinem jeweiligen Modul — er wird nirgends geteilt.

## N310 — was 2026-08 aus den Einstellungen verschwand

`unterordner.js` und `einsortieren.js` sind gelöscht: „Unterordner je Art" war
seit N285 gegenstandslos (Jahresordner gibt es nur noch bei den Nebenkosten),
„Belege in Jahresordner einsortieren" ist eine Aufräumaktion und läuft im
Wachdienst. Home-Ordner und Ordner-Benennung sind Einrichtungsschritte: ihre
Zeilen stehen nur da, solange der Wert fehlt. Das Belegarchiv ist eine Ansicht
und hängt als Verweis im Dialog der KI-Auslese, die es füllt.

## Was in settings.html bleibt

Das Inline-`<script type="module">` schrumpft auf:

1. Imports aus `./assets/settings/*.js`.
2. Ein Aufruf je `*Init()` (bindet Zeilen/Formulare/Dialoge).
3. Der gemeinsame Schließen-Handler `[data-schliessen]` — er trifft alle
   Dialoge auf der Seite gleich.
4. Die initiale Sequenz `await zustandLaden(); await kiZustandLaden(); …` —
   verhaltensgleich zum bisherigen Skript (die Reihenfolge macht keinen
   Unterschied, wird aber beibehalten, damit die Meldungen und HTTP-Calls
   in derselben Ordnung erscheinen).

Der ganze CSS-Block im `<head>` bleibt unverändert stehen — er gehört zum
Aussehen der Dialoge und Kacheln und wird nirgends importiert.

## Modul-Abhängigkeiten

- `vorlage.js` importiert `umzugLaden` aus `umzug.js` — nach dem Speichern
  einer neuen Vorlage soll die „Benennung nachziehen"-Zeile den neuen Stand
  zeigen. Kein Zyklus.
- Alles andere ist strikt hierarchisch: Fach-Module importieren aus
  `state.js` (und ggf. aus `immo.js`/`auswahl.js`).

## Delegation

Jedes Init-Modul verdrahtet seine eigenen Handler auf seinen Zeilen und
Dialogen. Der `[data-schliessen]`-Handler bleibt zentral in settings.html —
er ist eine reine Cross-cutting-Convenience, keinem Modul zugehörig.
