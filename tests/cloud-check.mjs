// Prüft den Nextcloud-Einrichtungsdialog und den X-Button im Wizard.
import { chromium } from 'playwright';
import { mkdirSync } from 'fs';

const base = process.env.BASE_URL || 'http://127.0.0.1:8199';
mkdirSync('tests/screenshots', { recursive: true });

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 430, height: 932 } });
let fails = 0;
const pruefe = (ok, text) => { if (!ok) { fails++; console.log('   ⚠ ' + text); } };

// 1) Einstellungen: Dialog muss sich öffnen und Felder zeigen
{
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  // Der Fehlversuch unten erzeugt bewusst eine 400-Antwort; die meldet der
  // Browser als Ressourcenfehler. Nur echte Skriptfehler sollen zählen.
  page.on('console', m => {
    if (m.type() === 'error' && !/Failed to load resource/.test(m.text()))
      errors.push(m.text());
  });

  await page.goto(base + '/settings.html', { waitUntil: 'networkidle' });
  await page.click('#ncRow');
  await page.waitForSelector('#ncDlg[open]', { timeout: 4000 })
    .catch(() => pruefe(false, 'Einrichtungsfenster öffnet nicht'));

  for (const feld of ['#ncUrl', '#ncUser', '#ncPass']) {
    pruefe(await page.$(feld) !== null, `Feld fehlt: ${feld}`);
  }
  pruefe(await page.$('#ncDlg .close') !== null, 'X-Button im Dialog fehlt');
  await page.screenshot({ path: 'tests/screenshots/cloud-dialog.png', fullPage: true });

  // Falsche Daten -> verständliche Fehlermeldung statt Statuscode
  await page.fill('#ncUrl', 'https://192.168.178.10:444');
  await page.fill('#ncUser', 'testuser');
  await page.fill('#ncPass', 'falsch');
  await page.click('#ncSpeichern');
  await page.waitForSelector('#ncMeldung.an', { timeout: 20000 })
    .catch(() => pruefe(false, 'keine Rückmeldung nach Fehlversuch'));
  const meldung = await page.textContent('#ncMeldung');
  pruefe(/App-Passwort|Anmeldung/i.test(meldung), 'unklare Fehlermeldung: ' + meldung);
  await page.screenshot({ path: 'tests/screenshots/cloud-fehler.png', fullPage: true });

  // X schließt wieder
  await page.click('#ncDlg .close');
  await page.waitForTimeout(300);
  pruefe(await page.$('#ncDlg[open]') === null, 'X schließt den Dialog nicht');

  pruefe(errors.length === 0, 'JS-Fehler: ' + errors.slice(0, 2).join(' | '));
  console.log(`${fails ? '✗' : '✓'} settings.html (Nextcloud-Dialog)`);
  await page.close();
}

// 2) Wizard: X-Button vorhanden, schließt ohne Eingaben sofort
{
  const vorher = fails;
  const page = await ctx.newPage();
  await page.goto(base + '/onboarding.html', { waitUntil: 'networkidle' });
  pruefe(await page.$('#abbrechen') !== null, 'X-Button im Wizard fehlt');
  await page.screenshot({ path: 'tests/screenshots/wizard-x.png', fullPage: true });
  await page.click('#abbrechen');
  await page.waitForLoadState('networkidle');
  pruefe(page.url().includes('index.html'), 'X führt nicht zurück: ' + page.url());
  console.log(`${fails > vorher ? '✗' : '✓'} onboarding.html (X-Button)`);
  await page.close();
}

await browser.close();
console.log(fails ? `\n${fails} Prüfung(en) fehlgeschlagen` : '\nNextcloud-Dialog und X-Button OK ✔');
process.exit(fails ? 1 : 0);
