// Erzeugt Screenshots aller Seiten in allen Geräteklassen für die
// visuelle Abnahme. Prüft dabei mechanisch, was messbar ist: Überlauf,
// abgeschnittener Text, überlappende Elemente, zu kleine Touch-Ziele.
//
//   node tests/matrix.mjs
import { chromium } from 'playwright';
import { mkdirSync } from 'fs';

const base = process.env.BASE_URL || 'http://127.0.0.1:8199';
const ZIEL = 'tests/screenshots/matrix';
mkdirSync(ZIEL, { recursive: true });

const GERAETE = [
  { name: 'iphone', viewport: { width: 390, height: 844 }, touch: true },
  { name: 'ipad', viewport: { width: 820, height: 1180 }, touch: true },
  { name: 'desktop', viewport: { width: 1440, height: 900 }, touch: false },
];

const SEITEN = [
  { datei: 'index.html', name: 'start' },
  { datei: 'eingang.html', name: 'eingang' },
  { datei: 'objekt.html?o=obj-a', name: 'objekt' },
  { datei: 'zeitraum.html?z=1', name: 'zeitraum' },
  { datei: 'wertentwicklung.html', name: 'wertentwicklung' },
  { datei: 'nebenkosten.html', name: 'nebenkosten' },
  { datei: 'eigentuemer.html', name: 'eigentuemer' },
  { datei: 'settings.html', name: 'einstellungen' },
  { datei: 'onboarding.html', name: 'wizard' },
];

const browser = await chromium.launch();
let fails = 0;
const melde = (ok, text) => { if (!ok) { fails++; console.log('   ⚠ ' + text); } };

for (const geraet of GERAETE) {
  const ctx = await browser.newContext({
    viewport: geraet.viewport, hasTouch: geraet.touch, isMobile: geraet.touch,
    deviceScaleFactor: 2,
  });
  const vorher = fails;

  for (const seite of SEITEN) {
    const page = await ctx.newPage();
    const jsFehler = [];
    page.on('pageerror', e => jsFehler.push(String(e)));
    await page.goto(`${base}/${seite.datei}`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(400);

    const kennung = `${geraet.name}/${seite.name}`;

    // Waagerechter Überlauf
    const ueber = await page.evaluate(() =>
      document.documentElement.scrollWidth - document.documentElement.clientWidth);
    melde(ueber <= 1, `${kennung}: ${ueber}px waagerechter Überlauf`);

    // Beschriftungen dürfen nicht abgeschnitten werden
    const beschnitten = await page.$$eval(
      '.btn, .row .t, .nav a, .tile .name, h1, h2, .add, .chip',
      els => els.filter(e => {
        if (e.offsetParent === null) return false;
        return e.scrollWidth > e.clientWidth + 2 || e.scrollHeight > e.clientHeight + 2;
      }).map(e => `${e.tagName}.${e.className}: "${(e.textContent || '').trim().slice(0, 28)}"`));
    melde(beschnitten.length === 0, `${kennung}: abgeschnitten -> ${beschnitten.join(' | ')}`);

    // Text darf nicht aus seinem Container ragen
    const ausgebrochen = await page.$$eval('.tile, .row, .karte, .kpi .k',
      els => els.filter(e => {
        if (e.offsetParent === null) return false;
        const r = e.getBoundingClientRect();
        return [...e.children].some(k => {
          const kr = k.getBoundingClientRect();
          return kr.right > r.right + 2 || kr.left < r.left - 2;
        });
      }).map(e => e.className));
    melde(ausgebrochen.length === 0, `${kennung}: ragt heraus -> ${ausgebrochen.join(', ')}`);

    // Touch-Ziele
    if (geraet.touch) {
      const klein = await page.$$eval('.nav a, .row, .btn, .add, .close, .back',
        els => els.filter(e => e.offsetParent !== null &&
          e.getBoundingClientRect().height < 43)
          .map(e => `${e.className}:${Math.round(e.getBoundingClientRect().height)}px`));
      melde(klein.length === 0, `${kennung}: zu klein -> ${klein.join(', ')}`);
    }

    melde(jsFehler.length === 0, `${kennung}: ${jsFehler[0] || ''}`);

    // Abgefangene Fehler enden als Meldung in der Oberfläche und lösen kein
    // pageerror aus — hier würden sie sonst unbemerkt durchrutschen.
    const stoerung = await page.$$eval(
      '.hinweisbox .big, .empty .big, .chartleer, .row .d, .bar .sub',
      els => els.filter(e => e.offsetParent !== null)
        .map(e => (e.textContent || '').trim())
        .filter(t => /nicht verfügbar|nicht erreichbar|nicht abrufbar|keine verbindung|fehler/i
          .test(t)));
    melde(stoerung.length === 0, `${kennung}: Fehlerzustand -> ${stoerung.join(' | ')}`);

    await page.screenshot({
      path: `${ZIEL}/${geraet.name}-${seite.name}.png`, fullPage: true });
    await page.close();
  }

  console.log(`${fails > vorher ? '✗' : '✓'} ${geraet.name} ` +
    `${geraet.viewport.width}×${geraet.viewport.height} — ${SEITEN.length} Seiten`);
  await ctx.close();
}

await browser.close();
console.log(fails
  ? `\n${fails} Beanstandung(en) — Screenshots in ${ZIEL}/`
  : `\nAlle Seiten in allen Größen sauber ✔ — Screenshots in ${ZIEL}/`);
process.exit(fails ? 1 : 0);
