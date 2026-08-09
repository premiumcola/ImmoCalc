# public/assets/strom/ — Module der PV-Amortisationsseite

N215 (C). Aufgeteilt aus dem bisherigen Inline-`<script>` in
`public/strom.html`. Reines Refactoring — kein Verhaltensunterschied.
Import aus HTML über `./assets/strom/…`.

## Module

| Datei              | Zustaendig                                                  |
|--------------------|-------------------------------------------------------------|
| `state.js`         | Gemeinsamer Modul-Zustand (`S.*`) + DOM-Refs `inhalt`/`sub` |
| `helpers.js`       | Formatierer: `kwh`, `kwh0`, `eur0`, `ct`, `prozent`, `tag`  |
| `farben.js`        | Farbpalette der Amortisation (`C_DIREKT`, `C_EINSP` …)      |
| `felder.js`        | `feldHtml`/`datumHtml` — Bausteine fuer ein Eingabefeld     |
| `info.js`          | N183 Info-Popups (`infoKnopf`) + Klick-Faenger am document  |
| `stammdaten.js`    | N139/N153 PV-Stammdaten: Formular, Vorlauf, `stammAngestossen` |
| `jahre.js`         | N160 Jahreseingabe, `rechnen`, `angestossen`, Autarkie-Kacheln, `tankZeigen`, Tipps |
| `solaredge.js`     | N131/N155/N161 Screenshot lesen, Bild-Vorschau, Drag&Drop   |
| `verlauf.js`       | N127 Verlauf: KPIs, Kurve (Inline-SVG), Legende, Tabelle    |
| `kringel.js`       | N200 Ringdiagramm `kWh je Kategorie` + Prozent-Aufteilung   |
| `eigentuemer.js`   | N204 PV-Eigentuemer-Karte, ‰-Zuordnung, „＋"-Formular       |
| `jahresabrechnung.js` | N308 jaehrliche PV-Eigentuemer-Abrechnung + Versand      |

## `state.js`-Vertrag

`state.js` exportiert das Objekt `S`, das alle Module mutieren und lesen.
ES-Modul-Bindings fuer Primitive sind unveraenderlich, deshalb liegt der
Zustand auf einem Objekt — jedes Modul liest dieselbe Instanz.

```js
S = {
  objektSlug: '',                 // aktueller Objekt-Slug
  jahresSatz: {},                 // zuletzt gelesener Strom-Satz des Jahres
  stammStand: {},                 // zuletzt gelesene Stammdaten
  letzteWerte: '',                // Debounce-Stempel Jahreswerte
  letzteStamm: '',                // Debounce-Stempel Stammdaten
  speicherZeit: null,             // setTimeout-Handle Jahreswerte
  stammZeit: null,                // setTimeout-Handle Stammdaten
  // PV-Eigentuemer
  pvPersonen: [],                 // Personen aus /pv/eigentuemer
  pvAnteile: {},                  // {Name: ‰} — mutiert von eigentuemer.js
  pvGeladen: false,               // Guard gegen leere Zuordnung
  pvNeuWahl: null,                // Auswahlfeld-Instanz des +Formulars
  pvAnschaffung: 0,               // Gesamt-Anschaffung fuer Invest-Chip
  pvAddOffen: false,              // +Formular offen?
  // SolarEdge
  seWerte: {},                    // erkannte Werte der Pruefansicht
  seBilder: new Map(),            // je Objekt|Jahr: gemerkter Screenshot
  // Kopf oben
  jahrWahl: null,                 // Auswahlfeld-Instanz, wird von HTML gesetzt
};
```

Zusaetzlich exportiert: `inhalt` (`<div id="inhalt">`) und `sub`
(`<div id="sub">`).

## Was in strom.html bleibt

Das Inline-`<script type="module">` ist geschrumpft auf:

1. Imports aus `./assets/strom/*.js`.
2. `skelett()` — die HTML-Struktur der Karten (nutzt `infoKnopf`, `F_*`,
   `feldHtml`, `datumHtml`).
3. `laden()` — Objekt-/Jahreswechsel, Formulare fuellen, Nebenkarten
   nachziehen.
4. Kopf-Setup: `jahrWahl`, `objektWahl` (`auswahlfeld`), N106/N110/N213-
   Weichen fuer die Objektliste (`hat_pv`, `?objekt=<slug>`).

Warum genau diese Reste? `skelett()` und `laden()` verzahnen mehrere
Module, sind aber selbst duenn — ihre Zerlegung wuerde nur Wege verlaengern,
nicht Verstaendnis erleichtern. Der Kopf-Init ist einmalig und braucht die
Wahl-Instanzen im lexikalischen Scope; ein weiteres Modul dafuer waere
Overhead ohne Nutzen.

## Delegation

Jedes Modul installiert seine eigenen Delegations-Handler beim Import:

- `info.js` hoert am `document` auf `click` (`[data-info]`, `[data-info-zu]`)
- `solaredge.js` hoert am `inhalt` auf `click`/`change` und am `document`
  auf `dragenter`/`dragover`/`dragleave`/`drop`
- `eigentuemer.js` hoert am `inhalt` auf `click`
  (`[data-pv-weg]`, `[data-pv-add]`)
- `jahresabrechnung.js` hoert am `inhalt` auf `click` (`[data-pj-send]`)

Die `input`-Handler fuer die Felder werden weiterhin in `laden()`
angebunden, weil sie nach jedem Skelett-Rebuild neu verkabelt werden
muessen und zu `laden` gehoeren.

## Modul-Zyklen

Bewusst in Kauf genommen: `stammdaten → jahre → verlauf → eigentuemer →
stammdaten`. ES-Module handhaben zyklische Imports, solange die Bindings
erst zur Laufzeit (in Event-Handlern / async-Callbacks) genutzt werden —
was hier der Fall ist. Kein Import wird auf Top-Level ausgewertet.
