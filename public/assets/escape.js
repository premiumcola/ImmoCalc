/* HTML-Escaping — eine Fassung für das ganze Frontend (N369).

   Vorher lag dieselbe Funktion viermal im Baum: `immo.js` (kanonisch),
   `auswahl.js`, `datumwahl.js` und als `sicher` noch einmal in `immo.js`
   selbst — letztere ohne `"`, obwohl sie in doppelt quotierte Attribute
   geschrieben wurde: ein Dokumentname mit Anführungszeichen brach dort aus dem
   Attribut aus. `charts.js` hatte gar keine und schrieb Objekt-, Einheiten-
   und Gewerkenamen roh in SVG und HTML.

   Eigene Datei statt eines Exports aus `immo.js`, weil `immo.js` seinerseits
   `auswahl.js` lädt: ein Import zurück wäre ein Zyklus, und `esc` stünde beim
   Auswerten von `auswahl.js` noch in der temporalen Todeszone. */

export const esc = s => String(s ?? '')
  .replace(/&/g, '&amp;').replace(/</g, '&lt;')
  .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
