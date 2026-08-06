# public/assets/zeitraum/ — Modul-Landkarte

`zeitraum.html` lädt seinen JS-Rumpf aus diesen Modulen (N215). Der Rahmen
im HTML (script type="module") bleibt schlank: er importiert `laden` und
`initHandlers`, ruft `installNav()` und startet `laden()`.

Grundprinzip: **State über `state.js` als lebende Bindings.** Alle Module
lesen `state.daten`, `state.chipMap` etc. aus `state.js`; Änderungen laufen
über die dort exportierten Setter. Konstante Katalogwerte (BEREICHE,
KOSTENART_ALIAS, STROM_ROLLEN etc.) stehen ebenfalls in `state.js`.

- `state.js` — mutable State + Setter + statische Konstanten.
- `icons.js` — alle inline-SVG-Icons.
- `modell.js` — Standard/Laufer-Gates + Bereichs-/Positions-Klassifikation.
- `helpers.js` — Formatter, kleine Werkzeuge, Chip- & Beleg-Renderer,
  Fortschritt/Verbrauch-Rechnungen.
- `zaehler.js` — Zähler-Panel (Wasser/Heizung/Strom) + Meter-Zeile +
  Umbenennen + Anfangs-/End-Stand + Datum + Einheiten-Zuordnung.
- `wasser.js` — Wasser-Detail (inline), Rechnungsmenge, Betragsfelder,
  Wasser-Drop-Dialog, Position leeren.
- `heizoel.js` — Öl-Manager: Lieferungen, FIFO, §9-Split, HKV, Garten.
- `strom.js` — Strom-Zähler-Block, Rollen, Anlegen/Entfernen, Menge,
  Herkunft, Jahreswert.
- `stromkette.js` — Kette (Schritt 1/2/3), Balken, Bubbles, Netz-Belege,
  geeichte Menge.
- `belege.js` — Beleg-Drop, Erkennung, Übernahme-Vorschlag, Anhänger,
  Beleg lösen, Beleg-Ansicht.
- `konfigmodus.js` — Inline-Konfig (N189): Sichtbar/Verborgen +
  Pflicht/Optional.
- `zaehler-konfig.js` — Zähler-Konfig-Dialog (Zahnrad-Knopf).
- `checkliste.js` — Haupt-Rendering `zeichnen()` + `laden()` + Zeilen
  (Aufteilung, Verteilung, Ergebnis, Abschluss, WEG-Direkteintrag) +
  zentrale Event-Delegation.

Wer welche Datei anfassen darf: jedes Modul gehört einer Aufgabe; wer eine
Kreuzänderung braucht, verändert `state.js` oder `helpers.js` (die
gemeinsame Basis). Nichts landet in zwei Modulen doppelt.
