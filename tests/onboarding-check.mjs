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

// Der Wizard hat kein eigenes Namensfeld mehr — der Name entsteht aus
// Straße, Ort und (bei genau einer Einheit) deren Bezeichnung.
const strasse = 'Prüfweg ' + String(Date.now()).slice(-5);
const ort = 'Teststadt';
const name = `(${ort}) ${strasse} · EG`;
let fails = 0;
const pruefe = (ok, text) => { if (!ok) { fails++; console.log('   ⚠ ' + text); } };

const vorher = await (await fetch(base + '/api/objekte')).json();

await page.goto(base + '/onboarding.html', { waitUntil: 'networkidle' });
await page.fill('[data-field="strasse"]', strasse);
await page.fill('[data-field="ort"]', ort);
const vorschau = await page.textContent('.namevz .nvn');
pruefe(vorschau.trim() === `(${ort}) ${strasse}`, `Namensvorschau falsch: "${vorschau}"`);

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

// und auf der Startseite als Kachel auftauchen. Die Kachel zeigt den Namen
// nicht mehr am Stück, sondern zerlegt: Ort klein darüber, Straße gross,
// Einheit darunter. Geprüft wird deshalb der gesamte Kacheltext.
await page.goto(base + '/index.html', { waitUntil: 'networkidle' });
await page.waitForSelector('.tile', { timeout: 8000 }).catch(() => {});
const kacheln = await page.$$eval('.tile', ns =>
  ns.map(n => n.textContent.replace(/\s+/g, ' ').trim()));
// „(Teststadt) Prüfweg 12345 · EG" steht jetzt als Ort + Straße + Einheit da
const teile = name.replace(/[()]/g, '').split('·').map(t => t.trim())
  .flatMap(t => t.split(' ').filter(Boolean));
pruefe(kacheln.some(k => teile.every(t => k.includes(t))),
  `neue Kachel fehlt auf der Startseite (gesucht: ${teile.join(' + ')})`);
await page.screenshot({ path: 'tests/screenshots/onboarding-start-danach.png', fullPage: true });

pruefe(errors.length === 0, 'JS-Fehler: ' + errors.slice(0, 3).join(' | '));

await browser.close();
console.log(fails ? `\n${fails} Prüfung(en) fehlgeschlagen` : `\nImmobilie "${name}" angelegt ✔`);
process.exit(fails ? 1 : 0);
