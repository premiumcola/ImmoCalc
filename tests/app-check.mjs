// Prüft die App-Seiten gegen den lokalen Prüfstand (tests/harness.py):
// Startseite, Objektdetail, Auswertung, Einstellungen. Klickt die Kern-Flows,
// legt Stammdaten an und macht Screenshots.
//
//   python3 tests/harness.py &
//   node tests/app-check.mjs
import { chromium } from 'playwright';
import { mkdirSync } from 'fs';

const base = process.env.BASE_URL || 'http://127.0.0.1:8199';
mkdirSync('tests/screenshots', { recursive: true });

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 430, height: 932 } });
let fails = 0;

async function seite(pfad) {
  const page = await ctx.newPage();
  const errors = [];
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', e => errors.push(String(e)));
  const resp = await page.goto(base + pfad, { waitUntil: 'networkidle' });
  return { page, errors, status: resp ? resp.status() : 0 };
}

function melde(name, status, errors, extra = []) {
  const bad = status !== 200 || errors.length || extra.length;
  if (bad) fails++;
  console.log(`${bad ? '✗' : '✓'} ${name}  status=${status}  jsErrors=${errors.length}`);
  [...errors.slice(0, 3), ...extra].forEach(e => console.log('   ⚠ ' + e));
}

// 1) Startseite: Kacheln kommen aus der API
{
  const { page, errors, status } = await seite('/index.html');
  const extra = [];
  await page.waitForSelector('.tile, .empty', { timeout: 8000 }).catch(() => {});
  const kacheln = await page.$$('.tile');
  if (!kacheln.length) extra.push('keine Objekt-Kacheln gerendert');
  if (await page.$('.nav a[aria-current=page]') === null) extra.push('Navigation ohne aktiven Tab');
  await page.screenshot({ path: 'tests/screenshots/app-start.png', fullPage: true });
  melde('index.html (Kacheln)', status, errors, extra);
  await page.close();
}

// 2) Objektdetail über Klick auf die erste Kachel + Stammdatensatz anlegen
{
  const { page, errors, status } = await seite('/index.html');
  const extra = [];
  await page.waitForSelector('.tile', { timeout: 8000 }).catch(() => {});
  await page.click('.tile').catch(e => extra.push('Kachel nicht klickbar: ' + e.message));
  await page.waitForSelector('h2.sec', { timeout: 8000 })
    .catch(() => extra.push('Objektseite ohne Abschnitte'));

  const abschnitte = await page.$$eval('h2.sec', hs => hs.map(h => h.textContent.trim()));
  for (const soll of ['Mieten', 'Versicherungen', 'Kredite']) {
    if (!abschnitte.some(a => a.includes(soll))) extra.push(`Abschnitt fehlt: ${soll}`);
  }

  // Versicherung anlegen — der Dialog muss speichern und die Liste nachladen
  await page.click('[data-add="versicherungen"]').catch(() => extra.push('Hinzufügen fehlt'));
  await page.waitForSelector('dialog[open]', { timeout: 4000 })
    .catch(() => extra.push('Dialog öffnet nicht'));
  await page.fill('#f_art', 'Gebäude').catch(() => {});
  await page.fill('#f_anbieter', 'Testversicherer').catch(() => {});
  await page.fill('#f_jahresbeitrag', '480').catch(() => {});
  await page.screenshot({ path: 'tests/screenshots/app-objekt-dialog.png', fullPage: true });
  await page.click('dialog button[value=ok]').catch(() => {});
  await page.waitForTimeout(900);
  const text = await page.textContent('body');
  if (!text.includes('Testversicherer')) extra.push('angelegte Versicherung erscheint nicht');

  await page.screenshot({ path: 'tests/screenshots/app-objekt.png', fullPage: true });
  melde('objekt.html (Detail + Anlegen)', status, errors, extra);
  await page.close();
}

// 3) Auswertung: Diagramme müssen gezeichnet sein
{
  const { page, errors, status } = await seite('/statistik.html');
  const extra = [];
  await page.waitForSelector('.karte', { timeout: 8000 }).catch(() => {});
  const charts = await page.$$('svg.chart, .chartleer');
  if (charts.length < 3) extra.push(`nur ${charts.length} Diagramme gerendert`);
  if (await page.$('.kpi .kv') === null) extra.push('Kennzahlen fehlen');
  await page.screenshot({ path: 'tests/screenshots/app-auswertung.png', fullPage: true });
  melde('statistik.html (Diagramme)', status, errors, extra);
  await page.close();
}

// 4) Einstellungen: Entwicklungswerkzeuge liegen hier, nicht auf der Startseite
{
  const { page, errors, status } = await seite('/settings.html');
  const extra = [];
  for (const href of ['app.html', 'status.html', 'logos.html', 'docs/rechenlogik.md']) {
    if (await page.$(`a[href="${href}"]`) === null) extra.push(`Verweis fehlt: ${href}`);
  }
  await page.screenshot({ path: 'tests/screenshots/app-settings.png', fullPage: true });
  melde('settings.html (Diagnose)', status, errors, extra);
  await page.close();
}

// 5) Startseite darf die Entwicklungswerkzeuge NICHT mehr zeigen
{
  const { page, errors, status } = await seite('/index.html');
  const extra = [];
  for (const href of ['app.html', 'status.html', 'logos.html']) {
    if (await page.$(`a[href="${href}"]`) !== null) extra.push(`Startseite zeigt noch: ${href}`);
  }
  melde('index.html (frei von Diagnose)', status, errors, extra);
  await page.close();
}

await browser.close();
console.log(fails ? `\n${fails} Prüfung(en) fehlgeschlagen` : '\nApp-Flows OK ✔');
process.exit(fails ? 1 : 0);
