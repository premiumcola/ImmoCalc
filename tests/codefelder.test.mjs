/* N503 — Verhaltenstest für die sechs Ziffernfelder (`codeFelder`/`codeBinden`
 * in `public/assets/immo.js`).
 *
 * Warum überhaupt: die Eingabelogik ist genau die Sorte Code, die statisch
 * gut aussieht und sich trotzdem falsch anfühlt — Vorrücken, Rücktaste auf
 * einem leeren Feld, Einfügen aus der Zwischenablage, und die Sperre, die
 * denselben Code nicht zweimal abschickt. Chromium läuft in dieser Umgebung
 * nicht, also steht hier ein sehr kleiner DOM-Ersatz: nur das, was der
 * Baustein tatsächlich anfasst.
 *
 * Lauf: `node tests/codefelder.test.mjs`
 */
import { readFileSync } from 'node:fs';
import { strict as assert } from 'node:assert';

/* ---- Ein DOM, so klein wie möglich ---- */

class Knoten {
  constructor(tag, attribute = {}) {
    this.tag = tag;
    this.attribute = attribute;
    this.kinder = [];
    this.horcher = {};
    this.value = '';
    this.classList = new Set();
    this.classList.contains = w => Set.prototype.has.call(this.classList, w);
    this.classList.add = w => Set.prototype.add.call(this.classList, w);
    this.classList.remove = w => Set.prototype.delete.call(this.classList, w);
  }
  addEventListener(art, fn) { (this.horcher[art] ||= []).push(fn); }
  ausloesen(art, ereignis = {}) {
    let verhindert = false;
    const e = { preventDefault() { verhindert = true; }, ...ereignis };
    (this.horcher[art] || []).forEach(fn => fn(e));
    // Was der Browser von sich aus täte, wenn niemand es abfängt: Rücktaste
    // auf einem gefüllten Feld löscht das Zeichen und löst `input` aus.
    // Ohne diesen Nachbau prüfte der Test einen Ablauf, den es nicht gibt.
    if (art === 'keydown' && e.key === 'Backspace' && !verhindert && this.value) {
      this.value = '';
      this.ausloesen('input');
    }
  }
  focus() { dokument.aktiv = this; }
  select() {}
  querySelector(wahl) { return this.querySelectorAll(wahl)[0] || null; }
  querySelectorAll(wahl) {
    const passt = k => (wahl.startsWith('[')
      ? wahl.slice(1, -1).split('=')[0] in k.attribute
      : (k.attribute.class || '').split(' ').includes(wahl.slice(1)));
    const treffer = [];
    const gehe = k => { k.kinder.forEach(kind => { if (passt(kind)) treffer.push(kind); gehe(kind); }); };
    gehe(this);
    return treffer;
  }
}

const dokument = { aktiv: null };

/* Der kleinste Parser, der für dieses Markup reicht: eine `div`-Gruppe, darin
   `input`- und `span`-Elemente. Mehr erzeugt `codeFelder` nicht.
 *
 * Die Gruppe hängt bewusst in einem äusseren Knoten — genau wie in echt, wo
 * sie im Dialog steht. `codeBinden` bekommt den äusseren und muss die Gruppe
 * darin FINDEN; gäbe man ihm die Gruppe selbst, bliebe genau dieser Schritt
 * ungeprüft (und war beim ersten Anlauf dieses Tests der Fehler). */
function baue(html) {
  const aussen = new Knoten('div', {});
  const gruppe = new Knoten('div', lies(html.match(/<div ([^>]*?)>/s)[1]));
  aussen.kinder.push(gruppe);
  for (const treffer of html.matchAll(/<(input|span)\s([^>]*?)>|<(span) class="([^"]*)"><\/span>/gs)) {
    const tag = treffer[1] || treffer[3];
    const attr = treffer[1] ? lies(treffer[2]) : { class: treffer[4] };
    gruppe.kinder.push(new Knoten(tag, attr));
  }
  return { aussen, gruppe };
}

function lies(roh) {
  const attribute = {};
  for (const t of roh.matchAll(/([\w-]+)="([^"]*)"/gs)) attribute[t[1]] = t[2];
  return attribute;
}

/* ---- Den Baustein aus immo.js holen, ohne den Rest des Moduls zu laden ---- */

const quelle = readFileSync(new URL('../public/assets/immo.js', import.meta.url), 'utf8');
const anfang = quelle.indexOf('const ZIFFERN_IM_CODE');
const ende = quelle.indexOf('\n/**\n * Verdrahtet alle Augen');
assert.ok(anfang > 0 && ende > anfang, 'Baustein in immo.js nicht gefunden');
const { codeFelder, codeBinden } = await import(
  'data:text/javascript,' + encodeURIComponent(quelle.slice(anfang, ende)));

/* ---- Die Prüfungen ---- */

let geprueft = 0;
const pruefe = (name, fn) => {
  fn();
  geprueft++;
  console.log('  ok  ' + name);
};

pruefe('sechs Felder, Lücke genau in der Mitte', () => {
  const html = codeFelder('code');
  const felder = [...html.matchAll(/<input /g)].length;
  assert.equal(felder, 6);
  const vorLuecke = html.slice(0, html.indexOf('codeluecke'));
  assert.equal([...vorLuecke.matchAll(/<input /g)].length, 3,
    'drei Felder vor der Lücke, drei danach');
});

pruefe('jedes Feld öffnet die Zahlentastatur und nimmt genau eine Ziffer', () => {
  const html = codeFelder('code');
  assert.equal([...html.matchAll(/inputmode="numeric"/g)].length, 6);
  assert.equal([...html.matchAll(/pattern="\[0-9\]\*"/g)].length, 6,
    'ältere iOS-Fassungen brauchen zusätzlich pattern');
  assert.equal([...html.matchAll(/maxlength="1"/g)].length, 6);
});

pruefe('nur das erste Feld bietet den Einmalcode an', () => {
  // Sonst schlägt iOS denselben Code an sechs Stellen vor.
  const html = codeFelder('code');
  assert.equal([...html.matchAll(/autocomplete="one-time-code"/g)].length, 1);
});

function frischerKasten() {
  const { aussen, gruppe } = baue(codeFelder('code'));
  const gemeldet = [];
  const steuerung = codeBinden(aussen, code => gemeldet.push(code));
  assert.ok(steuerung, 'codeBinden hat die Gruppe nicht gefunden');
  const felder = gruppe.querySelectorAll('.codeziffer');
  assert.equal(felder.length, 6);
  const tippe = (i, zeichen) => { felder[i].value = zeichen; felder[i].ausloesen('input'); };
  return { wurzel: gruppe, felder, gemeldet, steuerung, tippe };
}

pruefe('Tippen rückt vor und meldet erst bei der sechsten Ziffer', () => {
  const { felder, gemeldet, steuerung, tippe } = frischerKasten();
  '12345'.split('').forEach((z, i) => tippe(i, z));
  assert.equal(gemeldet.length, 0, 'fünf Ziffern lösen noch nichts aus');
  assert.equal(dokument.aktiv, felder[5], 'der Fokus steht im sechsten Feld');
  tippe(5, '6');
  assert.deepEqual(gemeldet, ['123456']);
  assert.equal(steuerung.wert(), '123456');
});

pruefe('derselbe volle Code wird nicht zweimal abgeschickt', () => {
  const { felder, gemeldet } = frischerKasten();
  '123456'.split('').forEach((z, i) => { felder[i].value = z; felder[i].ausloesen('input'); });
  assert.equal(gemeldet.length, 1);
  felder[5].ausloesen('focus');
  felder[5].value = '6';
  felder[5].ausloesen('input');
  assert.equal(gemeldet.length, 1, 'ein zweiter Versuch mit demselben Code wäre ein Fehlversuch');
});

pruefe('nach einer Korrektur darf derselbe Code wieder laufen', () => {
  const { felder, gemeldet, tippe } = frischerKasten();
  '123456'.split('').forEach((z, i) => tippe(i, z));
  felder[5].ausloesen('keydown', { key: 'Backspace' });   // letzte Ziffer weg
  tippe(5, '6');
  assert.equal(gemeldet.length, 2, 'erneut vollständig heisst erneut versuchen');
});

pruefe('Rücktaste auf leerem Feld löscht die Ziffer davor', () => {
  const { felder, tippe } = frischerKasten();
  tippe(0, '1');
  tippe(1, '2');
  felder[2].ausloesen('keydown', { key: 'Backspace' });
  assert.equal(felder[1].value, '');
  assert.equal(dokument.aktiv, felder[1]);
});

pruefe('Buchstaben kommen gar nicht erst an', () => {
  const { felder, tippe } = frischerKasten();
  tippe(0, 'a');
  assert.equal(felder[0].value, '');
});

pruefe('Einfügen verteilt alle sechs Ziffern', () => {
  const { wurzel, felder, gemeldet } = frischerKasten();
  wurzel.ausloesen('paste', {
    clipboardData: { getData: () => '  123 456 ' },
  });
  assert.equal(felder.map(f => f.value).join(''), '123456');
  assert.deepEqual(gemeldet, ['123456']);
});

pruefe('das Ausfüllen des Betriebssystems landet nicht in einem Feld', () => {
  // iOS schreibt alle sechs Ziffern in das Feld mit `one-time-code`.
  const { felder, gemeldet } = frischerKasten();
  felder[0].value = '987654';
  felder[0].ausloesen('input');
  assert.equal(felder.map(f => f.value).join(''), '987654');
  assert.deepEqual(gemeldet, ['987654']);
});

pruefe('leeren setzt zurück und markiert den Fehler', () => {
  const { wurzel, felder, gemeldet, steuerung, tippe } = frischerKasten();
  '123456'.split('').forEach((z, i) => tippe(i, z));
  steuerung.leeren();
  assert.equal(felder.map(f => f.value).join(''), '');
  assert.ok(wurzel.classList.contains('falsch'));
  assert.equal(dokument.aktiv, felder[0]);
  '123456'.split('').forEach((z, i) => tippe(i, z));
  assert.equal(gemeldet.length, 2, 'nach dem Leeren zählt derselbe Code als neuer Versuch');
});

console.log(`\n${geprueft} Prüfungen bestanden.`);
