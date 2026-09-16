# public/assets/settings/ — Module der Einstellungen-Seite

N216 (C). Aufgeteilt aus dem bisherigen Inline-`<script type="module">` in
`public/settings.html`. Import aus HTML über `./assets/settings/…`.

**N479 hat die Seite umgebaut.** Sie hat nur noch zwei Abschnitte: oben
„Verbundene Dienste" als Kachel-Reihe, unten „Konto und Sicherheit". Die
Kacheln sind nicht mehr eine Übersicht ÜBER Zeilen darunter, sondern der Weg
selbst — eine Kachel je Dienst, ein Knopf, der direkt in dessen Dialog führt.
Vorher gab es beides: eine Kachel, die zu einer Zeile rollte, und die Zeile,
die den Dialog öffnete.

## Module

| Datei              | Zustaendig                                                   |
|--------------------|--------------------------------------------------------------|
| `state.js`         | Geteilte Helfer: Meldungen (`feldmeldung`, `meldungWeg`), Statusabruf (`vHole`, `vHoleGeteilt`, `vGeteiltReset`), Formatierer (`vKurz`, `vModell`, `ortszeit`), Passwortfeld (`passwortFeld`, `augenBinden`, `passwortAbfrage`) und `diensteAuffrischen` |
| `symbole.js`       | N479 — `VSYMBOLE`: sieben Zeichen für die Dienst-Kacheln (wolke, beleg, brief, drucker, tresor, solar, wallbox). Nur Markup; die Regungen dazu stehen als CSS in `settings.html` |
| `verknuepfungen.js`| Die Kachel-Reihe: `verknuepfungenInit`, `vAlleLaden`. Je Dienst ein Eintrag mit `pruefe` (Stand holen) und `tun` (Dialog öffnen) |
| `version.js`       | `versionZeigen` — Fußzeile „ImmoCalc · Build <sha> · <zeit>" + die letzten fünf Änderungen aus `version.json` (Fallback `/health`) |
| `nextcloud.js`     | Nextcloud-Verbindung samt Home-Ordner-Wähler: `nextcloudInit`, `nextcloudOeffnen` |
| `ki.js`            | Belegerkennung (Anthropic-Schlüssel): `kiInit`, `kiOeffnen` |
| `mail.js`          | Postfach (SMTP) + Testmail: `mailInit`, `mailOeffnen` |
| `drucker.js`       | Drucker im Haus: `druckerInit`, `druckerOeffnen`, `druckerStand` |
| `backup.js`        | N474/N478/N479 — Sicherung dieser Familie: `backupInit`, `backupOeffnen`, `backupStand` |
| `vorlage.js`       | Ordner-Benennung (Vorlage für Objektordner): `vorlageInit`, `vorlageLaden`. Die Zeile steht im Nextcloud-Dialog |
| `logoZuschnitt.js` | N471 — `logoZuschneiden`: Verschieben, Zoomen, Drehen vor dem Hochladen |

## Zwei Muster, die jedes Fach-Modul benutzt

**`xOeffnen()` statt `xZustandLaden()` beim Seitenaufbau.** Früher holte jedes
Modul beim Laden der Seite seinen Stand, um eine Statuszeile zu füllen. Die
Zeilen gibt es nicht mehr — den Stand liefert die Kachel über `pruefe`. Die
Vorbelegung der Formulare passiert erst beim Öffnen des Dialogs. Vier Abrufe
weniger beim Seitenaufbau.

**`diensteAuffrischen()` statt Import der Kachel-Leiste.** Wer eine Verbindung
frisch eingerichtet hat, will sie sofort grün sehen. Das Modul schickt dafür
ein Ereignis `dienste:aendern` ans Dokument; `settings.html` hängt daran
`vAlleLaden`. Ein direkter Import wäre ein Ringschluss — `verknuepfungen.js`
importiert schon jedes Fach-Modul.

## Der Stand einer Kachel

`pruefe()` liefert `{stand, text}` mit `stand` aus vier Werten:

- `gut` (grün) — verbunden und einsatzbereit
- `warte` (gelb) — verbunden, aber noch nicht nutzbar: Nextcloud ohne
  Home-Ordner, eine Sicherung, die noch nie gelaufen ist
- `weg` (rot) — eingerichtet, antwortet aber nicht
- `aus` (gedeckt grau) — nicht eingerichtet. **Ausdrücklich kein Fehler**,
  deshalb ohne Signalfarbe und ohne Bewegung

## Die Regungen der Zeichen (N479)

Jedes Zeichen bewegt sich auf seine Weise, und zwar **nur** bei `gut` und
`weg`. Eine Kachel, die gar nicht eingerichtet ist, bleibt still — sonst
zappelte die halbe Seite grundlos. Die Fehler-Regungen zucken einmal gegen
Ende eines langen Zyklus; ein Dauerblinken wäre ein Warnbanner mit anderen
Mitteln, und die sind laut Leitfaden nicht gewollt.

Zwei Fallstricke, die beim Bauen aufgefallen sind:

- **`transform-box:fill-box` ist Pflicht** für alles, was sich dreht. Ohne das
  dreht ein SVG-Teil um die Ecke des 24er-Feldes, nicht um seine eigene Mitte.
  Und die Mitte ist die Mitte der Bounding-Box: `sy-sonne` und `sy-rad` sind
  deshalb bewusst symmetrisch um ihren Drehpunkt gezeichnet, sonst eiert es.
- **Ein `transform`-Attribut und eine CSS-`transform` teilen sich einen
  Platz.** Die Wolke sitzt deshalb in einer äußeren Gruppe mit dem
  `translate`-Attribut und einer inneren, die animiert wird.

## Passwortfelder — ein Muster für alle

Nutzer: „leer = beibehalten ist sehr verwirrend, das ist nicht der Standard."
Also gibt es genau ein Muster: `passwortFeld(id, label, zusatz)` baut das
Markup, `augenBinden(wurzel)` verdrahtet die Augen. Der Knopf verhindert per
`mousedown`-preventDefault, dass er den Fokus an sich zieht — sonst springt
beim Aufdecken die Schreibmarke aus dem Feld.

Was ein Feld zeigen kann, hängt daran, was der Server hergeben DARF:

- **WebDAV-App-Passwort der Sicherung** — kommt zurück, das Auge deckt es auf.
  Es reicht nur an den Archiv-Ordner beim Backup-Anbieter und ist dort
  widerrufbar; wer die Antwort lesen kann, hat eine Sitzung und damit längst
  Zugriff auf alle Daten.
- **Backup-Passwort** — kommt grundsätzlich nicht zurück: in der Datenbank
  liegt nur ein abgeleiteter Schlüssel. Das Feld sagt das ausdrücklich und
  bietet „ersetzen" an, statt ein leeres Feld hinzustellen.
- **Nextcloud-App-Passwort und KI-Schlüssel** — bleiben schreibend-nur. Das
  eine öffnet den ganzen Home-Ordner (mehr als ImmoCalc selbst sieht), das
  andere ein fremdes Konto mit Abrechnung.

## Was aus den Einstellungen verschwunden ist

**N310:** `unterordner.js` und `einsortieren.js` — „Unterordner je Art" war
seit N285 gegenstandslos, „Belege in Jahresordner einsortieren" läuft im
Wachdienst. Das Belegarchiv ist eine Ansicht und hängt als Verweis im Dialog
der Belegerkennung, die es füllt.

**N479:** `umzug.js` („Benennung nachziehen" — bereits angelegte Ordner
behalten ihren Namen, das steht jetzt im Benennungs-Dialog), `import.js`
(„JSON-Sicherung einlesen" — die Familien-Sicherung kann das vollständiger)
und `rechenlogik.js`. Die Rechenlogik-Übersicht war nie eine Einstellung: sie
steht als eigenständiges Modul `assets/rechenlogik-info.js` unter Nebenkosten,
wo gerechnet wird. Der Abschnitt „System" ist zur Fußzeile geworden.

Home-Ordner und Ordner-Benennung stehen seit N479 **im** Nextcloud-Dialog —
Einrichtungsschritte der Cloud, keine eigenen Punkte der App.

## Was in settings.html bleibt

1. Imports aus `./assets/settings/*.js`.
2. Die Zeichen der Konto- und Cloud-Zeilen (`[data-zeichen]`) und das
   Einsetzen der Passwortfelder in die statischen Dialoge (`[data-pwfeld]`).
   **Muss vor den Init-Aufrufen laufen** — die Module holen ihre Felder per ID.
3. Ein Aufruf je `*Init()`.
4. Der gemeinsame Schließen-Handler `[data-schliessen]` und der Lauscher auf
   `dienste:aendern`.
5. Konto und Sicherheit: Familie/Logo, Zwei-Faktor, Passwort ändern, Abmelden.

Der CSS-Block im `<head>` gehört zum Aussehen der Dialoge, Kacheln und
Regungen und wird nirgends importiert.

## Modul-Abhängigkeiten

`verknuepfungen.js` importiert die `xOeffnen`/`xStand`-Funktionen aller
Fach-Module. Alles andere ist strikt hierarchisch: Fach-Module importieren aus
`state.js` (und ggf. aus `immo.js`/`auswahl.js`). Kein Zyklus — dafür gibt es
`diensteAuffrischen()` statt eines Rück-Imports.
