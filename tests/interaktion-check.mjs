// Eigene Bedienelemente statt Systemkästen:
//   - das Auswahlfeld der Auswertung (assets/auswahl.js)
//   - der Schiebe-Regler vor dem Löschen (immo.js: schiebeFrage)
// Beide ersetzen etwas, das der Browser sonst selbst zeichnet — deshalb wird
// hier geprüft, dass sie sich auch wirklich bedienen lassen.
import { chromium } from 'playwright';
import { mkdirSync } from 'fs';

const base = process.env.BASE_URL || 'http://127.0.0.1:8199';
mkdirSync('tests/screenshots', { recursive: true });

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 430, height: 932 },
                                       deviceScaleFactor: 2 });
const page = await ctx.newPage();
const fehler = [];
page.on('pageerror', e => fehler.push(String(e)));
page.on('console', m => {
  if (m.type() === 'error' && !/Failed to load resource/.test(m.text())) fehler.push(m.text());
});

let fails = 0;
const pruefe = (ok, text) => { if (!ok) { fails++; console.log('   ⚠ ' + text); } };

/* ---- 1) Auswahlfeld in der Auswertung ---- */
await page.goto(base + '/statistik.html', { waitUntil: 'networkidle' });
await page.waitForSelector('.auswahl-knopf', { timeout: 8000 })
  .catch(() => pruefe(false, 'kein eigenes Auswahlfeld'));

pruefe(await page.$('.filter select') === null,
  'es steht noch ein natives <select> in der Filterzeile');

const felder = await page.$$('.auswahl-knopf');
pruefe(felder.length === 2, `${felder.length} Auswahlfelder statt 2`);

// Aufklappen: die Liste muss sichtbar werden und mehr als einen Eintrag haben
await page.click('#objekt .auswahl-knopf');
await page.waitForTimeout(250);
const liste = await page.$('#objekt .auswahl-liste');
pruefe(liste !== null && await liste.isVisible(), 'Liste klappt nicht auf');
const eintraege = await page.$$('#objekt .auswahl-liste li');
pruefe(eintraege.length >= 2, `nur ${eintraege.length} Einträge in der Liste`);
pruefe(await page.getAttribute('#objekt .auswahl-knopf', 'aria-expanded') === 'true',
  'aria-expanded meldet nicht "offen"');

// Touch-Ziele: jeder Eintrag muss mit dem Daumen treffbar sein
for (const eintrag of eintraege) {
  const kasten = await eintrag.boundingBox();
  if (kasten && kasten.height < 44) {
    pruefe(false, `Listeneintrag nur ${Math.round(kasten.height)} px hoch`);
    break;
  }
}
await page.screenshot({ path: 'tests/screenshots/auswahl-offen.png' });

// Zweiten Eintrag wählen — die Beschriftung muss mitziehen
const gewaehlt = (await eintraege[1].textContent()).trim();
await eintraege[1].click();
await page.waitForTimeout(900);
const knopfText = (await page.textContent('#objekt .auswahl-text')).trim();
pruefe(knopfText === gewaehlt, `Auswahl greift nicht (${knopfText} statt ${gewaehlt})`);
pruefe(await page.$eval('#objekt .auswahl-liste', el => el.hidden),
  'Liste bleibt nach der Auswahl offen');

// Escape muss schließen, ein Klick daneben ebenso
await page.click('#jahr .auswahl-knopf');
await page.keyboard.press('Escape');
pruefe(await page.$eval('#jahr .auswahl-liste', el => el.hidden),
  'Escape schließt die Liste nicht');

/* ---- 2) Schiebe-Regler vor dem Löschen ---- */
// Eigenes Wegwerf-Objekt, damit die Demodaten unberührt bleiben
const angelegt = await (await fetch(base + '/api/objekte', {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ name: 'Löschprobe ' + (await page.evaluate(() => 1)),
                         ort: 'Prüfstadt', strasse: 'Wegweg 1' }),
})).json();

await page.goto(base + `/objekt.html?o=${angelegt.slug}`, { waitUntil: 'networkidle' });
await page.waitForSelector('[data-loeschen]', { timeout: 8000 })
  .catch(() => pruefe(false, 'kein Löschen-Knopf auf der Objektseite'));

await page.click('[data-loeschen]');
await page.waitForSelector('dialog.immo-dlg[open] .schieber', { timeout: 4000 })
  .catch(() => pruefe(false, 'kein Schiebe-Regler — kommt noch der Systemkasten?'));
await page.screenshot({ path: 'tests/screenshots/loeschen-schieber.png' });

const bahn = await page.$('dialog.immo-dlg .schieber');
const griff = await page.$('dialog.immo-dlg .griff');
if (bahn && griff) {
  const b = await bahn.boundingBox();
  const g = await griff.boundingBox();
  pruefe(g.height >= 44, `Griff nur ${Math.round(g.height)} px hoch`);

  // Ein kurzer Schubs darf NICHT auslösen — genau davor schützt der Regler
  await page.mouse.move(g.x + g.width / 2, g.y + g.height / 2);
  await page.mouse.down();
  await page.mouse.move(g.x + g.width / 2 + 30, g.y + g.height / 2, { steps: 5 });
  await page.mouse.up();
  await page.waitForTimeout(500);
  pruefe(await page.$('dialog.immo-dlg[open]') !== null,
    'halber Weg löst schon aus — der Schutz greift nicht');

  // Ganz nach rechts: jetzt muss gelöscht werden
  await page.mouse.move(g.x + g.width / 2, g.y + g.height / 2);
  await page.mouse.down();
  await page.mouse.move(b.x + b.width, g.y + g.height / 2, { steps: 12 });
  await page.mouse.up();
  await page.waitForTimeout(1500);

  const weg = await fetch(base + `/api/objekte/${angelegt.slug}`);
  pruefe(weg.status === 404, `Objekt noch da (Status ${weg.status})`);
  pruefe((await page.textContent('body')).includes('gelöscht'),
    'keine Rückmeldung nach dem Löschen');
  await page.screenshot({ path: 'tests/screenshots/loeschen-fertig.png' });
} else {
  // Aufräumen, falls der Regler gar nicht erst kam
  await fetch(base + `/api/objekte/${angelegt.slug}`, { method: 'DELETE' });
}

pruefe(fehler.length === 0, 'JS-Fehler: ' + fehler.slice(0, 2).join(' | '));

await browser.close();
console.log(fails ? `\n${fails} Prüfung(en) fehlgeschlagen`
                  : '\nAuswahlfeld und Schiebe-Regler OK ✔');
process.exit(fails ? 1 : 0);
