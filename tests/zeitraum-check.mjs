// Klickt die Abrechnungsseite durch: Checkliste aufklappen, Betrag nachtragen,
// Ergebnis und Belege ansehen. Prüft, dass der Fortschritt mitzieht.
import { chromium } from 'playwright';
import { mkdirSync } from 'fs';

const base = process.env.BASE_URL || 'http://127.0.0.1:8199';
mkdirSync('tests/screenshots', { recursive: true });

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 430, height: 932 }, deviceScaleFactor: 2 });
const page = await ctx.newPage();
const fehler = [];
page.on('pageerror', e => fehler.push(String(e)));
page.on('console', m => {
  if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) fehler.push(m.text());
});

let fails = 0;
const pruefe = (ok, text) => { if (!ok) { fails++; console.log('   ⚠ ' + text); } };

// Ausgangslage herstellen: eine Position wieder öffnen, damit der Lauf
// wiederholbar ist (ein früherer Durchlauf hat sie sonst schon gefüllt).
{
  const zeitraum = await (await fetch(base + '/api/zeitraeume/1')).json();
  const kandidat = zeitraum.checkliste.find(k => k.position_id);
  if (kandidat) {
    await fetch(`${base}/api/positionen/${kandidat.position_id}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ betrag: 0, status: 'offen' }),
    });
  }
}

// Von der Objektseite über den Zeitraum in die Abrechnung
await page.goto(base + '/objekt.html?o=obj-a', { waitUntil: 'networkidle' });
await page.waitForSelector('[data-zeitraum]', { timeout: 8000 })
  .catch(() => pruefe(false, 'Zeiträume nicht anklickbar'));
await page.click('[data-zeitraum]');
await page.waitForLoadState('networkidle');
pruefe(page.url().includes('zeitraum.html'), 'führt nicht zur Abrechnung: ' + page.url());

await page.waitForSelector('.pruef', { timeout: 8000 })
  .catch(() => pruefe(false, 'keine Checkliste'));

const vorher = await page.textContent('.fortschritt .gross');
pruefe(/\d+ von \d+/.test(vorher), 'Fortschritt fehlt: ' + vorher);

// Ampel: es muss erledigte und offene Zeilen geben
const gruen = await page.$$('.haken.gruen');
const rot = await page.$$('.haken.rot');
const grau = await page.$$('.haken.grau');
pruefe(gruen.length > 0, 'keine erledigte Position');
pruefe(rot.length + grau.length > 0, 'keine offene Position');

// Gezielt eine Zeile mit fehlendem Betrag aufklappen (roter Haken = erfasst,
// aber Betrag offen). Nur dort gibt es das Nachtrage-Feld.
const offeneZeile = await page.$('.pruef:has(.haken.rot) .zeile');
await (offeneZeile || await page.$('.pruef .zeile')).click();
await page.waitForTimeout(400);
pruefe(await page.$('.pruef .auf') !== null, 'Zeile klappt nicht auf');
await page.screenshot({ path: 'tests/screenshots/zeitraum-aufgeklappt.png', fullPage: true });

// Betrag nachtragen — der Kern des Nachbearbeitens
const feld = await page.$('[data-betrag]');
pruefe(feld !== null, 'kein Feld zum Nachtragen bei offener Position');
if (feld) {
  await feld.fill('412.90');
  await page.click('[data-speichern]');
  await page.waitForTimeout(1400);
  const nachher = await page.textContent('.fortschritt .gross');
  pruefe(nachher !== vorher, `Fortschritt zieht nicht mit (${vorher} -> ${nachher})`);
  pruefe((await page.textContent('body')).includes('412,90'),
    'nachgetragener Betrag erscheint nicht');
}

// Ergebnis-Tab
await page.click('[data-tab="ergebnis"]');
await page.waitForTimeout(900);
const ergebnis = await page.textContent('body');
pruefe(/Saldo/.test(ergebnis), 'Ergebnis zeigt keinen Saldo');
await page.screenshot({ path: 'tests/screenshots/zeitraum-ergebnis.png', fullPage: true });

// Belege-Tab am abgeschlossenen Zeitraum (dort liegen die PDFs)
await page.goto(base + '/zeitraum.html?z=2', { waitUntil: 'networkidle' });
await page.waitForSelector('.tabs', { timeout: 8000 });
await page.click('[data-tab="belege"]');
await page.waitForTimeout(500);
const belege = await page.$$('.belege a');
pruefe(belege.length >= 3, `nur ${belege.length} Belege sichtbar`);
await page.screenshot({ path: 'tests/screenshots/zeitraum-belege.png', fullPage: true });

pruefe(fehler.length === 0, 'JS-Fehler: ' + fehler.slice(0, 2).join(' | '));

await browser.close();
console.log(fails ? `\n${fails} Prüfung(en) fehlgeschlagen` : '\nAbrechnungsseite OK ✔');
process.exit(fails ? 1 : 0);
