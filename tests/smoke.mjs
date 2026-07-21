// ImmoCalc Selfcheck gegen die laufende Instanz: lädt jede Seite in einem
// echten Browser, prüft Status + Content-Type + Pflicht-Elemente + JS-Fehler,
// erkennt ungewollte Downloads, klickt die Kern-Flows durch und legt
// Screenshots nach tests/screenshots/. Exit-Code != 0 bei Problemen.
//
//   node tests/smoke.mjs
//   BASE_URL=http://localhost:8091 node tests/smoke.mjs
import { chromium } from 'playwright';
import { mkdirSync } from 'fs';

const base = process.env.BASE_URL || 'http://192.168.178.10:8091';
mkdirSync('tests/screenshots', { recursive: true });

const browser = await chromium.launch();
const ctx = await browser.newContext({
  viewport: { width: 430, height: 900 },
  acceptDownloads: true,
});
let fails = 0;

async function open(path) {
  const page = await ctx.newPage();
  const errors = [], downloads = [];
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', e => errors.push(String(e)));
  page.on('download', d => downloads.push(d.url()));
  let status = 0, ctype = '';
  try {
    const resp = await page.goto(base + path, { waitUntil: 'networkidle' });
    if (resp) { status = resp.status(); ctype = resp.headers()['content-type'] || ''; }
  } catch (e) { errors.push('navigation: ' + e.message); }
  return { page, errors, downloads, status, ctype };
}

async function must(page, sels) {
  const miss = [];
  for (const s of sels) if (await page.$(s) === null) miss.push(s);
  return miss;
}

function report(name, { status, ctype, errors, downloads }, miss, expectType = 'text/html') {
  // Ein ausgelöster Download bedeutet: der Browser hat die Seite nicht
  // gerendert, sondern als Datei gespeichert -- fast immer ein MIME-Fehler.
  // expectType darf ein Präfix oder ein Muster sein — dieselbe Datei kommt
  // hinter nginx und im Prüfstand mit unterschiedlichem, aber gleich gutem Typ.
  const typeBad = expectType && !(expectType instanceof RegExp
    ? expectType.test(ctype) : ctype.startsWith(expectType));
  const bad = status !== 200 || miss.length || errors.length || downloads.length || typeBad;
  if (bad) fails++;
  console.log(`${bad ? '✗' : '✓'} ${name}  status=${status}  type=${ctype || '-'}  missing=[${miss}]  jsErrors=${errors.length}`);
  if (downloads.length) console.log('   ⚠ DOWNLOAD statt Anzeige: ' + downloads.join(', '));
  errors.slice(0, 3).forEach(e => console.log('   ⚠ ' + e));
}

// 1) index — Einstieg in die App
{ const r = await open('/index.html');
  const miss = await must(r.page, ['a[href="onboarding.html"]', '.nav a[href="settings.html"]']);
  await r.page.screenshot({ path: 'tests/screenshots/index.png', fullPage: true });
  report('index.html', r, miss); await r.page.close(); }

// 2) app – Objekt anklicken -> Zeiträume -> Tab Ergebnis
{ const r = await open('/app.html');
  const miss = await must(r.page, ['#scroll', '.card']);
  try {
    await r.page.click('[data-obj]'); await r.page.waitForSelector('[data-zr]');
    await r.page.click('[data-zr]'); await r.page.waitForSelector('.pos, .frist');
    await r.page.click('.tab[data-tab="res"]'); await r.page.waitForSelector('.total');
  } catch (e) { r.errors.push('flow: ' + e.message); }
  await r.page.screenshot({ path: 'tests/screenshots/app-ergebnis.png', fullPage: true });
  report('app.html (Klick-Flow)', r, miss); await r.page.close(); }

// 3) onboarding – 5 Schritte durchklicken bis Abschluss
// Bewusst NICHT bis zum Anlegen: `make check` läuft gegen die laufende
// Instanz, und dort stehen echte Immobilien. Der letzte Klick würde eine
// Testimmobilie in die Daten des Nutzers schreiben. Geprüft wird deshalb nur,
// dass der Wizard bis zum letzten Schritt trägt — das vollständige Anlegen
// deckt tests/onboarding-check.mjs gegen den Prüfstand ab.
{ const r = await open('/onboarding.html');
  const miss = await must(r.page, ['#stepper', '#content', '#foot']);
  try {
    // Der Name entsteht aus der Adresse — ohne Straße oder Ort trägt der
    // Wizard am Ende nicht.
    await r.page.fill('[data-field="strasse"]', 'Rauchweg 3');
    await r.page.fill('[data-field="ort"]', 'Prüfstadt');
    // Die Vorschau steht in Schritt 1 und zeigt, wie die Immobilie heißen wird
    const vorschau = (await r.page.textContent('.namevz')).replace(/\s+/g, ' ');
    if (!vorschau.includes('Rauchweg 3') || !vorschau.includes('Prüfstadt')) {
      throw new Error('Name wird nicht aus der Adresse gebildet: ' + vorschau);
    }
    for (let i = 0; i < 4; i++) await r.page.click('[data-next]');
    const schritt = await r.page.textContent('#content');
    if (!/Einheit/i.test(schritt)) throw new Error('letzter Schritt nicht erreicht');
  } catch (e) { r.errors.push('wizard: ' + e.message); }
  await r.page.screenshot({ path: 'tests/screenshots/onboarding-done.png', fullPage: true });
  report('onboarding.html (Wizard)', r, miss); await r.page.close(); }

// 4) status – echte API-Daten hinter dem nginx-Proxy
{ const r = await open('/status.html');
  const miss = await must(r.page, ['body']);
  await r.page.screenshot({ path: 'tests/screenshots/status.png', fullPage: true });
  report('status.html (API)', r, miss); await r.page.close(); }

// 5) Dokumente müssen im Browser ANGEZEIGT werden, nicht heruntergeladen
// nginx liefert text/plain (so wird es im Browser angezeigt statt geladen);
// der Prüfstand serviert dieselbe Datei als text/markdown. Beides ist in
// Ordnung — verboten ist nur ein Typ, der einen Download auslöst.
{ const r = await open('/docs/rechenlogik.md');
  report('docs/rechenlogik.md', r, [], /^text\/(plain|markdown)/);
  await r.page.close(); }

await browser.close();
console.log(fails ? `\n${fails} Seite(n) mit Problemen` : '\nAlle Seiten OK ✔');
process.exit(fails ? 1 : 0);
