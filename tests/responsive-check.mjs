// Prüft die App auf iPhone, iPad und Desktop: kein waagerechtes Scrollen,
// Navigation vorhanden, Touch-Ziele groß genug, PWA-Angaben vollständig.
import { chromium, devices } from 'playwright';
import { mkdirSync } from 'fs';

const base = process.env.BASE_URL || 'http://127.0.0.1:8199';
mkdirSync('tests/screenshots', { recursive: true });

const GERAETE = [
  { name: 'iphone', viewport: { width: 390, height: 844 }, touch: true },
  { name: 'ipad', viewport: { width: 820, height: 1180 }, touch: true },
  { name: 'desktop', viewport: { width: 1440, height: 900 }, touch: false },
];
const SEITEN = ['index.html', 'objekt.html?o=obj-a', 'statistik.html', 'settings.html'];

const browser = await chromium.launch();
let fails = 0;
const pruefe = (ok, text) => { if (!ok) { fails++; console.log('   ⚠ ' + text); } };

for (const geraet of GERAETE) {
  const ctx = await browser.newContext({
    viewport: geraet.viewport,
    hasTouch: geraet.touch,
    isMobile: geraet.touch,
    deviceScaleFactor: 2,
  });
  const vorher = fails;

  for (const seite of SEITEN) {
    const page = await ctx.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(String(e)));
    await page.goto(`${base}/${seite}`, { waitUntil: 'networkidle' });
    await page.waitForTimeout(400);

    // Die Seite darf nie waagerecht scrollen
    const ueberlauf = await page.evaluate(() =>
      document.documentElement.scrollWidth - document.documentElement.clientWidth);
    pruefe(ueberlauf <= 1, `${geraet.name}/${seite}: ${ueberlauf}px waagerechter Überlauf`);

    // Navigation muss auf jeder Breite erreichbar sein
    pruefe(await page.$('.nav a[aria-current=page]') !== null,
      `${geraet.name}/${seite}: keine aktive Navigation`);

    // Touch-Ziele mindestens 44px hoch
    if (geraet.touch) {
      // nur sichtbare Elemente — in geschlossenen Dialogen ist die Höhe 0
      const zuKlein = await page.$$eval('.nav a, .row, .btn, .add',
        els => els.filter(e => e.offsetParent !== null &&
                               e.getBoundingClientRect().height < 43).length);
      pruefe(zuKlein === 0, `${geraet.name}/${seite}: ${zuKlein} Ziele unter 44px`);
    }

    pruefe(errors.length === 0, `${geraet.name}/${seite}: ${errors[0] || ''}`);

    if (seite === 'index.html' || seite === 'statistik.html') {
      const kurz = seite.replace('.html', '');
      await page.screenshot({
        path: `tests/screenshots/${geraet.name}-${kurz}.png`, fullPage: true });
    }
    await page.close();
  }

  console.log(`${fails > vorher ? '✗' : '✓'} ${geraet.name} ` +
    `(${geraet.viewport.width}×${geraet.viewport.height})`);
  await ctx.close();
}

// PWA-Angaben
{
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  const vorher = fails;
  await page.goto(base + '/index.html', { waitUntil: 'networkidle' });

  pruefe(await page.$('link[rel="apple-touch-icon"]') !== null, 'apple-touch-icon fehlt');
  pruefe(await page.$('link[rel="manifest"]') !== null, 'manifest fehlt');
  pruefe(await page.$('meta[name="apple-mobile-web-app-capable"]') !== null,
    'apple-mobile-web-app-capable fehlt');
  pruefe(await page.$('meta[name="theme-color"]') !== null, 'theme-color fehlt');
  const viewport = await page.getAttribute('meta[name=viewport]', 'content');
  pruefe(/viewport-fit=cover/.test(viewport || ''), 'viewport-fit=cover fehlt');

  for (const pfad of ['/icons/apple-touch-icon.png', '/manifest.webmanifest']) {
    const antwort = await fetch(base + pfad);
    pruefe(antwort.ok, `${pfad} liefert ${antwort.status}`);
  }
  const manifest = await (await fetch(base + '/manifest.webmanifest')).json();
  pruefe(manifest.icons?.length >= 3, 'Manifest hat zu wenige Icons');
  pruefe(manifest.display === 'standalone', 'Manifest nicht standalone');

  console.log(`${fails > vorher ? '✗' : '✓'} PWA / iOS-Angaben`);
  await ctx.close();
}

await browser.close();
console.log(fails ? `\n${fails} Prüfung(en) fehlgeschlagen` : '\niPhone, iPad, Desktop OK ✔');
process.exit(fails ? 1 : 0);
