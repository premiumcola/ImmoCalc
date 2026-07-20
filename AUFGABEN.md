# ImmoCalc — Aufgabenliste

Alle Anforderungen aus den Gesprächen, fortlaufend nummeriert. Erledigtes mit
Commit, Offenes mit dem, was noch fehlt. Diese Liste wird bei jeder neuen
Anforderung fortgeschrieben — nichts muss doppelt gesagt werden.

Stand: 20.07.2026 · 52 pytest grün · 7 Seiten × 3 Geräteklassen geprüft

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

---

## Offen

### Hohe Priorität — von dir mehrfach genannt

| Nr. | Aufgabe | Was fehlt |
|---|---|---|
| XXXIX | **Immobilie löschen** | Roter Knopf mit Bestätigung; Nextcloud-Dateien bleiben |
| XL | **Export / Backup** | Beim Löschen eine JSON-Sicherung in die Nextcloud, wieder importierbar |
| XLI | **Objekt-Stammdaten sichtbar** | Quadratmeter, Kaufpreis, Verkehrswert, IBAN auf der Objektseite anzeigen und bearbeiten |
| XLII | **Mieter-Kontaktdaten in der Oberfläche** | Modell hat E-Mail, Telefon, Anschrift, Kaution — die Formularfelder fehlen |
| XLIII | **Scan-Knopf an jeder offenen Position** | In der Checkliste, dezent grün, Beleg direkt zur Kostenart |
| XLIV | **OCR** | Betrag und Datum aus dem Scan vorschlagen; braucht Tesseract im Image |

### Mittel

| Nr. | Aufgabe | Was fehlt |
|---|---|---|
| XLV | Icons für Mieten, Versicherungen, Kredite | bisher nur in der Abrechnungs-Checkliste |
| XLVI | Vorjahres-Zeiträume anlegen | mit Übernahme der Kostenarten aus dem Vorgänger |
| XLVII | Nachpflege-Hinweise | orange Meldung, wenn ein Update neue Felder braucht |
| XLVIII | Turnus-Auswahl in den Formularen | Rechenlogik steht, Auswahlfeld fehlt |
| XLIX | Eigentümerliste + Tausendstel-Anteile | neue Einstellung, Zuordnung je Objekt, änderbar |
| L | Vermögensübersicht | Restschulden, Verkehrswert, Volumen aus Kaufpreis und Kredit |
| LI | Einheiten gleicher Adresse zusammenfassen | Gruppierung in der Objektliste |
| LII | Logo oben führt zur Startseite | Markenzeile in der Kopfleiste verlinken |
| LIII | Verbundene Dienste grün und animiert | Nextcloud- und Postfach-Symbol, wenn aktiv |
| LIV | „Struktur anlegen“ dezenter | kleiner, rechts, weniger hoch, wenn schon angelegt |
| LV | Manuell angelegte Unterordner erkennen | werden nicht verändert, sollen aber angezeigt werden |
| LVI | PDF-Anhang beim Versand | Abrechnung geht bisher als reiner Text |
| LVII | Belege im Browser öffnen | zeigt bisher nur den Nextcloud-Pfad |

### Bewusst zurückgestellt

| Nr. | Aufgabe | Grund |
|---|---|---|
| LVIII | Push-Benachrichtigungen auf iOS | von dir zurückgestellt; braucht HTTPS über den Reverse Proxy |
| LIX | Umbenennung der App | „ImmoCalc“ bleibt vorerst; Vorschläge lagen vor (Hausflow, Immoflow) |

---

## Woran du dich erinnern solltest

- **Deploy nötig:** Die API läuft erst nach `./deploy.sh` mit dem neuen Stand.
- **Push scheitert:** In der Entwicklungsumgebung fehlen GitHub-Zugangsdaten —
  `git push origin main` musst du selbst ausführen.
- **Nextcloud und Postfach** brauchen deine Zugangsdaten in der Oberfläche.
