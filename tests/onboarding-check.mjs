// Legt über den Wizard eine echte Immobilie an und prüft, dass sie
// danach in der API und auf der Startseite auftaucht.
import { chromium } from 'playwright';
import { mkdirSync } from 'fs';

const base = process.env.BASE_URL || 'http://127.0.0.1:8199';
mkdirSync('tests/screenshots', { recursive: true });

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 430, height: 932 } });
const page = await ctx.newPage();
const errors = [];
page.on('pageerror', e => errors.push(String(e)));
page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });

const name = 'Prüfweg ' + String(Date.now()).slice(-5);
let fails = 0;
const pruefe = (ok, text) => { if (!ok) { fails++; console.log('   ⚠ ' + text); } };

const vorher = await (await fetch(base + '/api/objekte')).json();

await page.goto(base + '/onboarding.html', { waitUntil: 'networkidle' });
await page.fill('[data-field="name"]', name);
await page.fill('[data-field="ort"]', 'Teststadt');

for (let i = 0; i < 4; i++) {
  await page.click('[data-next]');
  await page.waitForTimeout(150);
}
// Schritt 5: eine Einheit anlegen
await page.click('[data-add]').catch(() => {});
await page.fill('[data-ei="0"][data-ek="bez"]', 'EG').catch(() => {});
await page.fill('[data-ei="0"][data-ek="partei"]', 'Testmieter').catch(() => {});

await page.click('[data-next]');
await page.waitForSelector('#done.open', { timeout: 8000 })
  .catch(() => pruefe(false, 'Abschluss-Overlay erscheint nicht'));
await page.screenshot({ path: 'tests/screenshots/onboarding-fertig.png', fullPage: true });

const nachher = await (await fetch(base + '/api/objekte')).json();
pruefe(nachher.length === vorher.length + 1,
  `API hat ${nachher.length} statt ${vorher.length + 1} Objekte`);
pruefe(nachher.some(o => o.name === name), `"${name}" fehlt in der API`);

// "Zur Immobilie" muss auf die Detailseite des neuen Objekts führen
await page.click('#doneBtn');
await page.waitForLoadState('networkidle');
pruefe(page.url().includes('objekt.html?o='), 'führt nicht zur Objektseite: ' + page.url());
const detail = await page.textContent('body');
pruefe(detail.includes(name), 'Objektseite zeigt den Namen nicht');

// und auf der Startseite als Kachel auftauchen
await page.goto(base + '/index.html', { waitUntil: 'networkidle' });
await page.waitForSelector('.tile', { timeout: 8000 }).catch(() => {});
const kacheln = await page.$$eval('.tile .name', ns => ns.map(n => n.textContent.trim()));
pruefe(kacheln.includes(name), 'neue Kachel fehlt auf der Startseite');
await page.screenshot({ path: 'tests/screenshots/onboarding-start-danach.png', fullPage: true });

pruefe(errors.length === 0, 'JS-Fehler: ' + errors.slice(0, 3).join(' | '));

await browser.close();
console.log(fails ? `\n${fails} Prüfung(en) fehlgeschlagen` : `\nImmobilie "${name}" angelegt ✔`);
process.exit(fails ? 1 : 0);
