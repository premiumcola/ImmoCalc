# tankstelle/ — Modul-Landkarte (N215)

Die frueher inline in `public/tankstelle.html` liegende `<script type="module">`
ist nach Themen aufgeteilt. Jedes Modul hat einen klaren Zustaendigkeitsbereich;
gemeinsamer Zustand liegt in `state.js` als Objekt `S` und wird von allen
Modulen geteilt (ES-Modul-Bindings, live).

| Modul           | Aufgabe |
| --------------- | ------- |
| `state.js`      | Geteilter Zustand `S` (objektSlug, Nutzer, Verlaufsdaten, Zeitraumauswahl, abgerechnet-Marker, Einstellungen, Vorschau-Timer), Farben (NETZ/PV/AKKU/EIGEN/OFFEN), Kalender-Konstanten (MONKURZ, QMON), Grafik-Parameter, Zahlenformatter (kwh/proz/zahl/satzText/datum) und `zeigeFehler`. |
| `infos.js`      | Die Erklärtexte im i-Popup (N181): INFOS-Verzeichnis, `infoKnopf`, `infoKnopfText`, `infoOeffnen`/`infoSchliessen`. |
| `matrix.js`     | Der Quartal×Monat-Chooser (N193): `zeitraumWahl` (UI), Interaktion (`monatUmschalten`, `quartalUmschalten`, `normalisiereAuswahl`), Auswahl-Helfer (`monatAktiv`, `quartalAktiv`, `aktiveMonate`, `monateDerQuartale`, `zeitraumParams`, `periodeKurz`, `jahrWert`, `jahreUebernehmen`, `monatIstOffen`) und alle abgerechnet-Marker-Helfer (`markerDeckt`, `monatAbgerechnet`, `quartalAbgerechnet`, `jahrAbgerechnet`, `periodeAbgerechnet`, `nutzerPeriodeAbgerechnet`, `QUARTAL_VON`). |
| `verlauf.js`    | Die Verlauf-Karte: `grafik` (SVG-Balken je Monat), `verlaufTabelle` (paginiert mit Heatmap in der Kosten-Spalte, N188), `tabelleNeu`, `verlaufZeigen`. |
| `blatt.js`      | Die inline HTML-Vorschau der Abrechnung (N179/N184/N184b/N194): `abrechnungBlatt`, `blattTabelleEauto`, `blattTabelleStrom`, `periodeMonate`, `periodeSumme`, `verbrauchsTrend`, `vorschauZeigen`, `vorschauRendern`, `vorschauEntprellt`. |
| `nutzer.js`     | Die Nutzer-Karte: Liste, Anlegen, Inline-Bearbeitung, Loeschen, KI-Verbrauch (`nutzerZeigen`, `nutzerBearbeiten`, `nutzerSpeichern`, `nutzerAnlegen`, `nutzerEntfernen`, `eautoErmitteln`). |
| `abrechnung.js` | Die Abrechnungs-Karte (N148/N182/N186/N193/N195/N202): `abrechnungKopf` (Automatik-Schalter), `satzBlock` (Ø-Satz + Netz/Eigen-Karten), `abrechnungZeigen` (Nutzerliste mit Betragen + Sende-Buttons), `abgerechnetLaden`/`abgerechnetUmschalten` (N182), `autoversandUmschalten`, `einstellungenLaden`. Bindet Matrix (`zeitraumWahl`), Vorschau-Entprellung und `ladungenZeigen` ein. |
| `zuordnen.js`   | Die Karte „Ladungen zuordnen" (N165/2): `ladungenZeigen` (Regelblock + Liste + Neu-Ladung-Formular), `zuordnungSpeichern`, `ausschlussUmschalten`. |
| `ladungen.js`   | Neue Ladung erfassen + Ladung entfernen (`ladungBuchen`, `ladungEntfernen`). |
| `versand.js`    | Sende-Orchestrierung mit Rueckfrage (`versenden`). |

Was in `tankstelle.html` bleibt: `installNav`, die Skelett-Karten, die Click-
und Change-Delegation, die Objekt-Auswahl im Kopf und `laden()` — die
Verdrahtung der Seite, nicht die Fachlogik.
