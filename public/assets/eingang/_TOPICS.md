# eingang/ — Modul-Landkarte (N216)

Die frueher inline in `public/eingang.html` liegende `<script type="module">`
ist nach Themen aufgeteilt. Jedes Modul hat einen klaren Zustaendigkeits-
bereich; gemeinsamer Zustand liegt in `state.js` als Objekt `S` und wird von
allen Modulen geteilt (ES-Modul-Bindings, live).

| Modul          | Aufgabe |
| -------------- | ------- |
| `state.js`     | Der geteilte Zustand `S` (Filter, API-Antwort, gewaehlter Beleg, Erfassung, Caches je Immobilie/Beleg, Zeitraum-Feld, Kostenposition-Plan, Timer). `els` — einmal ausgelesene DOM-Referenzen. Konstanten `ALLE`, `ANLEGEN`, `MONATE`, `jetzt`. Die kurze Meldezeile `melde(text, art)` am Fuss des Pruefblatts. |
| `helpers.js`   | Reine Hilfsfunktionen ohne DOM/Netz: `sacheAusNamen`, `endungVon`, `datumText`, `alsDatum`, `dmy`, `tagText`, `betragText`, `befund`, `belegDatumText`, `titelVon`, `kurzObjekt`, `jahresliste`, `dok`, `zumDatum`, `umfasst`, `passenderZeitraum`, `belegTag`, `isoTag`, `zahlAus`, `kiLabel`, `kiWert`. Konstanten `DATUM_IM_NAMEN`, `BETRAG_IM_NAMEN`, `KI_LABELS`, `KI_EINHEITEN`, `KI_UEBERNAHME`, `BRAUCHT_POSITION`, `fertig`. |
| `filter.js`    | Die Filterleiste (Immobilien-Buttons als Kurzcodes „lau 5" CCLXXXVIII, Art/Jahr/Zustand-Auswahl, aufklappbares Kostenart-Dropdown CCLXXIX), Suche mit Tipp-Entprellung, Filter-Reset, „Angezeigte ins Warten" (CCLXXXII). `filterFuellen` beschriftet nach jedem Ladevorgang neu. |
| `liste.js`     | Die Dokumentenliste (Karten `karte`, offene Karte mit `felder`, `erfassungBeleben`, `stand`, `feldstandZeigen` CLXXV, `jahresfachZeigen`), Kartenauswahl (`waehle`, Klick/Keydown), das Neuzeichnen (`zeichne`, `erledigt`-Abschnitt CCCLXX). Auch die Umschaltung Telefon/Schreibtisch: `blattPlatzieren`, `kameraPlatzieren`, `blattZeigen` (CCCLXVII). |
| `plan.js`      | Das Pruefblatt (CXXV): `planZeichnen` (Gegenueberstellung „erkannt → wird eingetragen"), `zielName` (Dateiname, den die Ablage vergeben wird). |
| `zeitraum.js`  | Der Abrechnungszeitraum (CCLVIII/CLXXII): `zeitraeumeFuer`, `zeitraeumeFuellen`, `zeitraumErkennen`, `zeitraumGewaehlt`, `zeitraumAnlegenUndWaehlen`, `zeitraumHinweisZeigen`. |
| `kostenart.js` | Die Kostenposition (CLXXI/CCLXXIV): `kostenartenFuer`, `kostenartenFuellen`, `passendeKostenart`. |
| `vorschau.js`  | Die Beleg-Vorschau (CXXIX/N99): `vorschauLeeren`, `vorschauText`, `vorschauLaden` (Server-gerendertes Bild), `grossAnsehen`. |
| `ki.js`        | Texterkennung (CLXXVII), KI-Einschaetzung (CCLXXIII), KI-Vorbelegung (CCLXXIV) und Neustart der KI-Analyse (CCCLXVII): `erkennungZeigen`, `kiEinschaetzungZeigen`, `kiVorbelegungZeigen`, `kiFelderEinsetzen`, `kiWerteUebernehmen`, `erkennungHolen`, `vorschlagEinsetzen`. |
| `position.js`  | Aus dem Beleg wird eine Kostenposition (CLXXX/CLXXXII): `posUngespeichert`, `posPlanZeichnen`, `posZeigen` sowie die Klick-Handler „Als Kostenposition uebernehmen" und „Loesen". |
| `scan.js`      | Beleg abfotografieren und ersetzen (`bNeu`) auf der gemeinsamen Kette (N280): `belegVorbereiten`/`belegBestaetigen`/`belegAblegen` aus `belegscan.js`+`belegbestaetigung.js`. Eigen bleibt nur `zielAbfragen` (Immobilie/Art/Jahr, nur wenn die Kette sie nicht selbst fuellt) und `BEREICH_ZU_ART` (N263-Hinweis fuer die Auslese). Handler fuer `kameraKnopf`/`kameraFeld`/`erneutFeld`. |
| `aktionen.js`  | Die Seiten-Orchestrierung: `laden` (Liste vom Server holen), `fussnoteZeigen` (Wachdienst + OCR-Hinweis), `nkKontextInit` (Sprung aus der NK-Abrechnung — CCLXXXIII/CCCLXXII), „Ordner einlesen" (CXXVII), „Uebernehmen" (bOk) und „Entfernen" (bWeg, mit „Wirklich?"-Rueckfrage). |

Was in `eingang.html` bleibt: `installNav()`, die Start-Aufrufe
`nkKontextInit()` → `laden()` → `fussnoteZeigen()` — der Rest wird durch die
Modul-Imports installiert. Zyklische Abhaengigkeiten (liste ↔ plan ↔
zeitraum/kostenart/ki/position/aktionen) sind zulaessig, weil alle
Cross-Modul-Aufrufe erst zur Laufzeit stattfinden (Event-Handler, PATCH nach
Nutzeraktion) und die exportierten Funktionsdeklarationen bereits beim ersten
Auswerten des jeweiligen Moduls sichtbar sind.
