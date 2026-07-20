// ImmoCalc Selfcheck: lädt jede Seite in echtem Browser, prüft Status +
// Pflicht-Elemente + JS-Konsolenfehler, klickt Kern-Flows durch und macht
// Screenshots nach tests/screenshots/. Exit-Code != 0 bei Problemen.
import { chromium } from 'playwright';
import { mkdirSync } from 'fs';

const base = process.env.BASE_URL || 'http://localhost:8099';
mkdirSync('tests/screenshots', { recursive: true });

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 430, height: 900 } });
let fails = 0;

async function open(path) {
  const page = await ctx.newPage();
  const errors = [];
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', e => errors.push(String(e)));
  const resp = await page.goto(base + path, { waitUntil: 'networkidle' });
  return { page, errors, status: resp ? resp.status() : 0 };
}
async function must(page, sels) {
  const miss = [];
  for (const s of sels) if (await page.$(s) === null) miss.push(s);
  return miss;
}
function report(name, status, miss, errors) {
  const bad = status !== 200 || miss.length || errors.length;
  if (bad) fails++;
  console.log(`${bad ? '✗' : '✓'} ${name}  status=${status}  missing=[${miss}]  jsErrors=${errors.length}`);
  errors.slice(0, 3).forEach(e => console.log('   ⚠ ' + e));
}

// 1) index
{ const { page, errors, status } = await open('/index.html');
  const miss = await must(page, ['a[href="app.html"]', 'a[href="onboarding.html"]']);
  await page.screenshot({ path: 'tests/screenshots/index.png', fullPage: true });
  report('index.html', status, miss, errors); await page.close(); }

// 2) app – Objekt anklicken -> Zeiträume -> Tab Ergebnis
{ const { page, errors, status } = await open('/app.html');
  const miss = await must(page, ['#scroll', '.card']);
  try {
    await page.click('[data-obj]'); await page.waitForSelector('[data-zr]');
    await page.click('[data-zr]'); await page.waitForSelector('.pos, .frist');
    await page.click('.tab[data-tab="res"]'); await page.waitForSelector('.total');
  } catch (e) { errors.push('flow: ' + e.message); }
  await page.screenshot({ path: 'tests/screenshots/app-ergebnis.png', fullPage: true });
  report('app.html (Klick-Flow)', status, miss, errors); await page.close(); }

// 3) onboarding – 5 Schritte durchklicken bis Abschluss
{ const { page, errors, status } = await open('/onboarding.html');
  const miss = await must(page, ['#stepper', '#content', '#foot']);
  try {
    for (let i = 0; i < 5; i++) await page.click('[data-next]');
    await page.waitForSelector('#done.open');
  } catch (e) { errors.push('wizard: ' + e.message); }
  await page.screenshot({ path: 'tests/screenshots/onboarding-done.png', fullPage: true });
  report('onboarding.html (Wizard)', status, miss, errors); await page.close(); }

// 4) logos
{ const { page, errors, status } = await open('/logos.html');
  const miss = await must(page, ['#grid', '.opt']);
  await page.screenshot({ path: 'tests/screenshots/logos.png', fullPage: true });
  report('logos.html', status, miss, errors); await page.close(); }

await browser.close();
console.log(fails ? `\n${fails} Seite(n) mit Problemen` : '\nAlle Seiten OK ✔');
process.exit(fails ? 1 : 0);
