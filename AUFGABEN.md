# ImmoCalc — Aufgabenliste

Alle Anforderungen aus den Gesprächen, fortlaufend nummeriert. Erledigtes mit
Commit, Offenes mit dem, was noch fehlt. Diese Liste wird bei jeder neuen
Anforderung fortgeschrieben — nichts muss doppelt gesagt werden.

Stand: 21.07.2026 · 166 pytest grün · Prüfung des Standes `0acdaa1` durch
fünf Agents, jeder Fund gegengeprüft

**Grundsatz aus dem Gespräch:** möglichst direkt bedienbar. Was man häufig
tut, gehört an die Oberfläche — nicht hinter einen zweiten Klick. Und nichts,
was der Browser zeichnet: keine `alert`, keine `confirm`, keine Systemlisten.

---

## Erledigt

| Nr. | Aufgabe | Commit |
|---|---|---|
| I | Download statt Anzeige beheben (Content-Type, `no-store`) | `4b1106d` |
| II | DEV-Stack abschaffen, `public/` mounten, sofort wirksam | `4b1106d` |
| III | CLAUDE.md: Autonomie, Parallelität, Modularisierung, Design | `ababbe5` |
| IV | Visuelle Abnahme als Pflicht (Screenshots wirklich ansehen) | `a7d17c9` |
| V | Startseite = echte App, Objekt-Kacheln aus der API | `632bce7` |
| VI | Entwicklungswerkzeuge in die Einstellungen verschoben | `632bce7` |
| VII | Objektseite mit Mieten, Versicherungen, Krediten, Zahlungen | `632bce7` |
| VIII | Auswertung mit Kennzahlen, Kostenblöcken, Mietverlauf | `632bce7` |
| IX | Onboarding legt wirklich an (`POST /api/objekte`) | `632bce7` |
| X | Schreib-API: Objekte, Stammdaten, Auswertung | `98d9d32` |
| XI | Migration: bestehende Daten überleben Schema-Erweiterungen | `c98cb1c`, `43e81a5` |
| XII | Nextcloud-Verbindung mit Ordner-Browser und Home-Ordner | `7c4bbd7` |
| XIII | X-Knopf im Wizard, Escape schließt | `7c4bbd7` |
| XIV | Layout für iPhone, iPad, Desktop + iOS-Icon, PWA-Manifest | `0dbb093` |
| XV | Geräte-Matrix: jede Seite in drei Größen geprüft | `a7d17c9` |
| XVI | Mockup-Bearbeitenmodus samt Fantasiedaten entfernt | `a7d17c9` |
| XVII | Sankey-Kostenfluss, Cashflow je Einheit, €/m² | `2110249` |
| XVIII | Eigener Turnus je Kostenart + Belegmonat + Erinnerungen | `2110249` |
| XIX | Kontodaten je Objekt (Bank, IBAN, Inhaber) — Modell | `2110249` |
| XX | Eingangsordner mit Zuordnung und automatischer Benennung | `fa935da` |
| XXI | Postfach verbinden (GMX u. a.) mit Testmail | `fa935da` |
| XXII | Nextcloud nachträglich verbinden, Struktur später anlegen | `43e81a5` |
| XXIII | Automatischer Ordner-Scan alle 15 Minuten | `43e81a5` |
| XXIV | Abrechnungs-Checkliste mit Ampel, Belegen, Nachbearbeiten | `693f24e` |
| XXV | Mehrere Zeiträume + Beispielbelege in den Demodaten | `693f24e` |
| XXVI | Einheitliche Kategorie-Icons (grau/grün) | `bc717f8` |
| XXVII | Sortierung nach Offene/Größe/Name, Zusatzinfos je Zeile | `bc717f8` |
| XXVIII | Abschluss-Knopf + Versand der Abrechnungen an die Mieter | `bc717f8` |
| XXIX | Kamera-Scan → PDF (klein, mehrseitig) → Nextcloud | `cdbcb06` |
| XXX | Nextcloud-URL mit `/login` abfangen (der 405-Fehler) | `d0905c7` |
| XXXI | Wizard-Bugs: klebender Turnus-Text, Kachelraster, Knopfhöhe | `d0905c7` |
| XXXII | Kategorien ergänzt: Bankspesen, Hauskonto, Internet u. a. | `d0905c7` |
| XXXIII | Ordner-Benennung von grob nach fein, mit Vorlage | `d0905c7` |
| XXXIV | Schreibschutz: nichts außerhalb des Home-Ordners | `d28d3b4` |
| XXXV | Zahlungsturnus (monatlich … jährlich) — Rechenlogik | `d28d3b4` |
| XXXVI | Fristen erst ab Ende des Zeitraums erinnern | `d28d3b4` |
| XXXVII | Sankey: Bandfarbe = Quellfarbe, nichts wird abgeschnitten | `d28d3b4` |
| XXXVIII | Ordnerliste im Dialog als Raster statt Fließtext | `d28d3b4` |
| XXXIX | Immobilie löschen — mit Nachfrage, Cloud-Dateien bleiben | `d5a5550`, `f068042` |
| XL | Export/Sicherung als JSON, wieder importierbar | `d5a5550` |
| XLI | Objekt-Stammdaten sichtbar und bearbeitbar | `f068042` |
| XLII | Mieter-Kontaktdaten in der Oberfläche | `f068042` |
| XLIII | Scan-Knopf an jeder offenen Position | `f068042` |
| XLIV | Texterkennung schlägt Betrag und Datum vor | `d5a5550`, `f068042` |
| XLV | Symbole für Mieten, Versicherungen, Kredite, Zahlungen | `f068042` |
| XLVI | Weitere Zeiträume anlegen, Vorauszahlungen übernehmen | `d5a5550` |
| XLVII | Nachpflege-Hinweise, wenn Angaben fehlen | `d5a5550`, `f068042` |
| XLVIII | Turnus-Auswahlfeld in allen Formularen | `f068042` |
| XLIX | Eigentümerliste und Tausendstel je Objekt | `d5a5550`, `f068042` |
| L | Vermögensübersicht: Wert, Restschuld, Eigenkapital | `d5a5550`, `f068042` |
| LI | Einheiten gleicher Adresse gruppiert | `f068042` |
| LII | Marke in der Navigation führt zur Startseite | `f068042` |
| LIII | Verbundene Dienste mit grünem Punkt | `f068042` |
| LIV | „Fehlende Unterordner“ tritt zurück, wenn angelegt | `f068042` |
| LV | Selbst angelegte Ordner werden angezeigt, nie verändert | `d5a5550`, `f068042` |
| LVI | PDF-Anhang beim Versand | `d5a5550` |
| LVII | Belege im Browser öffnen | `d5a5550`, `f068042` |
| LX | „Beleg erfassen“ direkt in der Zeile, ohne Aufklappen | `f496e6a` |
| LXI | App-Symbol in der Kopfzeile jeder Seite | `f496e6a` |
| LXII | Auswahlmenüs im eigenen Design statt Systemliste | `f496e6a` |
| LXIII | Name aus Straße, Ort und Einheit — Feld entfällt | `f496e6a` |
| LXIV | Löschen per Schiebe-Regler statt Browser-Kasten | `f496e6a` |
| LXVII | Doppelklick legt keine zwei Eigentümer mehr an | `19fdf4f` |
| LXXIII | Texterkennung: Betrag, Datum **und** Kategorieart aus dem Text | `19fdf4f` |
| LXXIV | Mehrseitig fotografieren → ein PDF (mit pypdf gegengeprüft) | `19fdf4f` |
| LXXVII | Benennung Ort → Straße → Einheit in den Kacheln | `19fdf4f` |
| LXXVIII | Hauslogos in den Kacheln größer | `19fdf4f` |
| LXXIX | Zusammengehörige Einheiten: Oberkachel mit angedockten Kacheln | `19fdf4f` |
| LXXX | Eigentümer als eigener Menüpunkt | `19fdf4f` |
| LXXXI | Rolle wird aus dem Anteil abgeleitet, je Objekt | `19fdf4f` |
| LXXXII | Tausendstel auf eine Nachkommastelle, Fehlendes wird angezeigt | `19fdf4f` |
| LXXXIII | Auswertung geteilt: Wertentwicklung und Nebenkostenabrechnung | `19fdf4f` |
| LXXXIV | Menüleiste mit sechs Einträgen | `19fdf4f` |
| LXXXV | „Eingang" heißt jetzt „Dokumente" | `19fdf4f` |
| LXXXVI | Menüleiste auf dem Handy: vier Wege plus „Mehr" | `821a925` |
| LXVI | Abschluss rückgängig: Zeitraum wieder öffnen | `a8952a8` |
| LXVIII | Wachdienst legt nichts doppelt an (Sperre, 409) | `b692b10` |
| LXIX | Zuordnen ohne Cloud-Ordner meldet jetzt 409 statt Erfolg | `b692b10` |
| LXXI | Fänger entschärft: `/api/stammdaten/{bereich}/{id}` | `822e928` |
| LXXII | Je Testmodul eine eigene Datenbank (`conftest.py`) | `822e928` |
| LXXXVII | Verteilungsschlüssel aus Stammdaten ableiten (API) | `a8952a8` |
| LXXXVIII | Dokumentenablage flach: Filter, Suche, Korrigieren, Neu-Scan | `b692b10` |
| LXXXIX | „Was ansteht" auf der Startseite, Sicherung einlesen | `0acdaa1` |

---

## Offen

### Blocker — aus der Prüfung vom 21.07.2026

| Nr. | Fund | Warum es zählt |
|---|---|---|
| LXV | **Kostenposition lässt sich in der Oberfläche nicht anlegen** | Das Backend leitet Gewichte jetzt ab (`a8952a8`), aber `POST /api/zeitraeume/{zid}/positionen` hat keinen Aufrufer. Für ein selbst angelegtes Objekt bleibt `position_id: null`, das Betragsfeld erscheint nie — die Abrechnung bleibt 0,00 € |
| XC | **Beleg landet nie am Zeitraum** | `Dokument.zeitraum_id` wird außer im Seed von keinem Weg gesetzt; der Reiter „Belege" ist für echte Daten dauerhaft leer |

### Rechenlogik — Geld wird falsch verteilt

| Nr. | Fund | Warum es zählt |
|---|---|---|
| XCI | Mieterwechsel zählt Fläche, Personen und Einheiten doppelt | `verteilung.py:157-168` verteilt ohne Zeitanteil. Bei einem Wechsel im Jahr trägt die andere Einheit 42,86 % statt 60 % — unabhängig davon, wann gewechselt wurde |
| XCII | Mietverhältnis ohne Einheit fällt stumm aus der Verteilung | `Miete.einheit` ist Freitext; passt der Name nicht, verschwindet die Partei aus den Gewichten, bekommt keine Kosten und ihre Vorauszahlung voll erstattet. Kein Wächter meldet das |

### Datenintegrität — Wachdienst und echte Dateien

| Nr. | Fund | Warum es zählt |
|---|---|---|
| XCIII | Kategorie-Erkennung per Teilstring legt automatisch falsch ab | `klein.count(wort)` ohne Wortgrenzen: „Kaufvertrag Berg**gas**se 5.pdf" gilt als Nebenkosten. Der Wachdienst verschiebt und benennt solche Dateien alle 15 Minuten ungefragt um |
| XCIV | Unique-Index auf `dokument.pfad` fehlt in `migrate.py` | Für die Bestands-DB wirkungslos; er entsteht nur beim ersten Scan, ein Fehlschlag wird bis zum Neustart nie wiederholt. LXVIII besteht live weiter |
| XCV | `IntegrityError` nur in `_aufnehmen` abgefangen | Wurde eine Datei in der Cloud gelöscht, scheitert der Scan mit HTTP 500 — die Datei liegt schon im Zielordner, der Eintrag zeigt noch auf den Eingang |
| XCVI | `verschieben:false` benennt nur in der Datenbank um | Umgeht die 409-Sperre: DB-Name und Cloud-Datei laufen auseinander, der Eintrag gilt als „zugeordnet". Derselbe Schaden wie LXIX, nur hinter einem Schalter |
| XCVII | Automatische Ablage wirft den Originalnamen weg | Aus „Grundsteuerbescheid 2024.pdf" wird „2024_Steuer.pdf" — unumkehrbar, ohne Nutzeraktion. Zwei Belege eines Jahres sind danach nur noch durch Öffnen unterscheidbar |

### Oberfläche und Prüfstand

| Nr. | Fund | Warum es zählt |
|---|---|---|
| XCVIII | `auswahl.js` entfernt seine `document`-Listener nie | Jedes Neuzeichnen hängt weitere an; bei zehn Dokumenten und getippter Suche sammeln sich hunderte, deren Closures abgelöste DOM-Bäume halten |
| XCIX | `scan-check.mjs` kann nicht mehr fehlschlagen | Das Muster trifft auch den Ruhetext des Knopfes — ein Scan, der gar nicht anläuft, gilt als Erfolg |
| C | Kanonischer Stammdatenpfad und Verteilungsfälle ungetestet | Getestet wird nur die Altroute; ein Fehler im neuen Pfad bliebe in `make test` unsichtbar, obwohl die Oberfläche dann nicht speichern kann |
| LXX | Fünf Endpunkte ohne Aufrufer | u. a. `POST`/`DELETE` auf Positionen, `GET /zeitraeume/{zid}/positionen` — zwei davon in `a8952a8` neu gebaut. Erinnerungen und Import sind mit `0acdaa1` angebunden |

### Reststand aus dem Gespräch vom 20.07.2026

| Nr. | Aufgabe | Was noch fehlt |
|---|---|---|
| LXXV | **Dokumentenablage ohne Verschachtelung** | Grundgerüst steht (`b692b10`). Offen: Originalname bleibt erhalten (XCVII), verwaiste Einträge aufräumbar |
| LXXVI | **Dynamisch, filterbar, smart** | Offen: Metazeile wiederholt Jahr und Art aus dem Dateinamen, Zustand „neu" dreifach signalisiert, Art-Filter bietet leere Werte an |

### Bewusst zurückgestellt

| Nr. | Aufgabe | Grund |
|---|---|---|
| LVIII | Push-Benachrichtigungen auf iOS | von dir zurückgestellt; braucht HTTPS über den Reverse Proxy |
| LIX | Umbenennung der App | „ImmoCalc“ bleibt vorerst; Vorschläge lagen vor (Hausflow, Immoflow) |

---

## Woran du dich erinnern solltest

- **Deploy nötig:** Die API läuft erst nach `./deploy.sh` mit dem neuen Stand.
  Diesmal besonders: das API-Image bekommt Tesseract, der Build dauert länger.
- **Texterkennung** schlägt nur vor. Ohne Tesseract läuft der Scan weiter,
  dann eben ohne Vorschlag für Betrag und Datum.
- **Sicherungen** landen in der Nextcloud unter `00_ImmoCalc_Sicherungen`
  im Home-Ordner — nicht beim Objekt, das beim Löschen ja gerade wegfällt.
- **Push scheitert:** In der Entwicklungsumgebung fehlen GitHub-Zugangsdaten —
  `git push origin main` musst du selbst ausführen.
- **Nextcloud und Postfach** brauchen deine Zugangsdaten in der Oberfläche.
