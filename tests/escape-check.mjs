/* N369 — Wächter für das HTML-Escaping im Frontend.
 *
 * `charts.js` hatte keins: Objekt-, Einheiten-, Gewerke- und Firmennamen
 * (letztere aus der Beleg-Erkennung, also nicht vom Nutzer getippt) gingen roh
 * in SVG und HTML — auf sieben Seiten. Ein zweiter Fall war `sicher` in
 * `immo.js`, das `"` stehen ließ, obwohl es in doppelt quotierte Attribute
 * geschrieben wurde.
 *
 * Der Test füttert jeden Diagramm-Baustein mit einem bösartigen Namen und
 * prüft, dass nichts davon als Markup zurückkommt. Zusätzlich sucht er im
 * ganzen `public/`-Baum nach neuen eigenen esc-Kopien.
 *
 *   node tests/escape-check.mjs
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const WURZEL = join(fileURLToPath(new URL('.', import.meta.url)), '..');
const ASSETS = join(WURZEL, 'public/assets');

const { esc } = await import(join(ASSETS, 'escape.js'));
const charts = await import(join(ASSETS, 'charts.js'));

const BOESE = '<img src=x onerror=alert(1)>"zitat"&amp;';
let fehler = 0;
const meld = t => { console.log('  ✗', t); fehler++; };

/* 1) esc selbst — alle vier Zeichen, auch das Anführungszeichen. */
for (const [zeichen, ersatz] of
     [['<', '&lt;'], ['>', '&gt;'], ['"', '&quot;'], ['&', '&amp;']]) {
  if (!esc(BOESE).includes(ersatz)) meld(`esc() ersetzt ${zeichen} nicht`);
}
if (esc(null) !== '' || esc(undefined) !== '') meld('esc() verträgt kein null');

/* 2) Die Diagramm-Bausteine dürfen kein Markup durchlassen. */
const bausteine = {
  balken: () => charts.balken([{ name: BOESE, wert: 10, text: BOESE }], {}),
  legende: () => charts.legende([{ name: BOESE }]),
  saeulen: () => charts.saeulen([{ name: `(${BOESE}) Weg 1`, a: 5, b: 3 }], {}),
  leer: () => charts.leer?.(BOESE) ?? '',
};
for (const [name, bauen] of Object.entries(bausteine)) {
  let ausgabe = '';
  try { ausgabe = bauen(); } catch (f) { meld(`${name}() wirft: ${f.message}`); continue; }
  const roh = ausgabe.match(/<img|<script|<iframe/g);
  if (roh) meld(`${name}() gibt rohes Markup aus: ${roh.join(', ')}`);
}

/* 3) Keine neuen eigenen esc-Kopien im Baum. `escape.js` ist die eine Quelle. */
const dateien = [];
(function sammeln(ordner) {
  for (const eintrag of readdirSync(ordner)) {
    const pfad = join(ordner, eintrag);
    if (statSync(pfad).isDirectory()) sammeln(pfad);
    else if (pfad.endsWith('.js')) dateien.push(pfad);
  }
})(join(WURZEL, 'public'));

const KOPIE = /const\s+(esc|sicher)\s*=\s*s\s*=>\s*String/;
for (const pfad of dateien) {
  if (pfad.endsWith('/escape.js')) continue;
  if (KOPIE.test(readFileSync(pfad, 'utf8')))
    meld(`eigene esc-Kopie in ${relative(WURZEL, pfad)} — aus escape.js importieren`);
}

console.log(fehler
  ? `\n${fehler} Beanstandung(en)`
  : `\nEscaping sauber ✔ (${dateien.length} JS-Dateien geprüft)`);
process.exit(fehler ? 1 : 0);
