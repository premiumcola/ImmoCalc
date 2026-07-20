# ImmoCalc — Aufgabenliste

Alle Anforderungen aus den Gesprächen, fortlaufend nummeriert. Erledigtes mit
Commit, Offenes mit dem, was noch fehlt. Diese Liste wird bei jeder neuen
Anforderung fortgeschrieben — nichts muss doppelt gesagt werden.

Stand: 20.07.2026 · 82 pytest grün · 7 Seiten × 3 Geräteklassen geprüft

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

---

## Offen

### Aus der Prüfung vom 20.07.2026 — noch nicht behoben

| Nr. | Fund | Warum es zählt |
|---|---|---|
| LXV | **Kein Endpunkt setzt `anteile`** | Für selbst angelegte Objekte bleibt jede Abrechnung 0,00 €. Nur der Seed schreibt Verteilungsgewichte |
| LXVI | Abschluss ist unumkehrbar | Ein versehentlich abgeschlossener Zeitraum lässt sich nicht wieder öffnen |
| LXVII | Doppelklick legt zwei Eigentümer an | `#eignerSpeichern` wird nicht deaktiviert |
| LXVIII | Wachdienst kann Dokumente doppelt anlegen | `Dokument.pfad` ist nicht eindeutig; zwei Sessions sehen denselben Pfad als neu |
| LXIX | Zuordnen ohne Cloud-Ordner meldet Erfolg ohne Wirkung | Datei bleibt liegen, verschwindet aber aus dem Eingang |
| LXX | Sieben Endpunkte ohne Aufrufer | u. a. Erinnerungen, PDF-Vorschau, Import, OCR-Status — gebaut, aber nirgends erreichbar |
| LXXI | Fänger `/api/{bereich}/{id}` verschluckt zweisegmentige Pfade | Der nächste Endpunkt fällt lautlos hinein |
| LXXII | Tests teilen sich eine Datenbank | Die Reihenfolge entscheidet, welche `DB_PATH` gilt — Funde können sich gegenseitig verdecken |

### Neu aus dem Gespräch vom 20.07.2026

| Nr. | Aufgabe | Was gemeint ist |
|---|---|---|
| LXXIII | **Texterkennung wirklich nachweisen** | Betrag, Datum und Kategorieart aus einem echten gescannten PDF herauslesen und eintragen — belegt, nicht behauptet |
| LXXIV | **Mehrseitig fotografieren → ein PDF** | im Ablauf durchprüfen, nicht nur im Code |
| LXXV | **Dokumentenablage ohne Verschachtelung** | direkter, effizienter Weg; so viel wie möglich automatisch zuordnen, aber Verschieben, Korrigieren, Löschen und Neu-Scannen bleiben möglich |
| LXXVI | **Dynamisch, filterbar, smart** | keine Dopplungen in der Darstellung |
| LXXVII | **Benennung: Ort → Straße → Einheit** | oberste Ebene Ortschaft, darunter Straße, darunter Wohnungseinheit — die Kacheln heißen noch anders |
| LXXVIII | **Hauslogos in den Kacheln größer** | |
| LXXIX | **Zusammengehörige Einheiten als Gruppe** | Oberkachel mit den Stammdaten, darunter angedockte Einzelkacheln je Einheit — nicht fünf gleichrangige Kacheln |
| LXXX | **Eigentümer als eigener Menüpunkt** | raus aus den Einstellungen |
| LXXXI | **Rolle gehört ans Objekt, nicht an die Person** | Ob jemand Eigentümer oder Miteigentümer ist, entscheidet sich je Immobilie — dieselbe Person soll nicht zweimal angelegt werden müssen |
| LXXXII | **Tausendstel prüfen und Fehlendes anzeigen** | eine Nachkommastelle genügt: 333,3 + 333,3 + 333,3 gilt als vollständig |

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
