// Die Navigationsleiste auf schmalen Schirmen.
//
// Sieben Einträge nebeneinander sind auf einem iPhone zu eng — die
// Beschriftungen schrumpfen und die Ziele werden schmaler als ein Daumen.
// Geprüft wird: auf dem Handy stehen vier Einträge plus „Mehr", der Rest ist
// über das Blatt erreichbar; auf dem Desktop sind alle sieben sichtbar.
import { chromium } from 'playwright';
import { mkdirSync } from 'fs';

const base = process.env.BASE_URL || 'http://127.0.0.1:8199';
mkdirSync('tests/screenshots', { recursive: true });

const browser = await chromium.launch();
let fails = 0;
const pruefe = (ok, text) => { if (!ok) { fails++; console.log('   ⚠ ' + text); } };

/* ---- iPhone: vier Einträge plus „Mehr" ---- */
{
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 },
                                         deviceScaleFactor: 2 });
  const page = await ctx.newPage();
  const fehler = [];
  page.on('pageerror', e => fehler.push(String(e)));

  await page.goto(base + '/index.html', { waitUntil: 'networkidle' });
  await page.waitForSelector('nav.nav', { timeout: 8000 });
  await page.waitForTimeout(300);

  const sichtbar = await page.$$eval('nav.nav a:not(.brand)',
    as => as.filter(a => a.offsetParent !== null).length);
  pruefe(sichtbar === 4, `${sichtbar} Einträge sichtbar statt 4`);

  const mehr = await page.$('nav.nav .mehr');
  pruefe(mehr !== null && await mehr.isVisible(), '„Mehr" fehlt auf dem Handy');

  // Jedes Ziel muss mit dem Daumen treffbar sein
  for (const el of await page.$$('nav.nav a:not(.brand), nav.nav .mehr')) {
    if (!await el.isVisible()) continue;
    const kasten = await el.boundingBox();
    if (kasten.width < 56 || kasten.height < 44) {
      pruefe(false, `Ziel zu klein: ${Math.round(kasten.width)}×${Math.round(kasten.height)} px`);
      break;
    }
  }
  await page.screenshot({ path: 'tests/screenshots/nav-iphone.png' });

  // Das Blatt muss die übrigen Wege anbieten
  await page.click('nav.nav .mehr');
  await page.waitForSelector('dialog.immo-dlg[open] .mehrliste', { timeout: 4000 })
    .catch(() => pruefe(false, '„Mehr" öffnet kein Blatt'));
  const ziele = await page.$$eval('.mehrliste a',
    as => as.map(a => a.getAttribute('href')));
  // N327 — Einstellungen/Kontakte stehen nicht mehr in diesem Blatt, sondern
  // an jeder Kopfzeile hinter `.ka-mehr` (installKopfAktionen).
  pruefe(ziele.includes('eigentuemer.html'),
    'im Blatt fehlen Einträge: ' + ziele.join(', '));
  await page.screenshot({ path: 'tests/screenshots/nav-mehr.png' });

  pruefe(fehler.length === 0, 'JS-Fehler: ' + fehler.slice(0, 2).join(' | '));
  await ctx.close();
}

/* ---- Handy, auf einer Seite hinter der Kopfzeilen-„…" ----
   N327 — Einstellungen/Kontakte stehen nicht mehr im NAV-Array und damit
   auch nicht mehr hinter der unteren „Mehr"; sie haengen jetzt an jeder
   Kopfzeile (`.kopfakt .ka-mehr`), die dafuer selbst `aria-current` traegt. */
{
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await ctx.newPage();
  await page.goto(base + '/settings.html', { waitUntil: 'networkidle' });
  await page.waitForTimeout(300);
  const markiert = await page.$eval('.kopfakt .ka-mehr',
    el => el.getAttribute('aria-current') === 'page').catch(() => false);
  pruefe(markiert, 'Kopfzeilen-„…" zeigt nicht, dass die aktuelle Seite dahinter liegt');
  await ctx.close();
}

/* ---- Desktop: ALLE stehen in der Seitenleiste ----
   N313 — hier stand die feste Zahl 7. Die Leiste ist seitdem auf zwölf
   Einträge gewachsen, und der Test war rot, ohne dass etwas kaputt war. Die
   geprüfte Aussage ist ohnehin eine andere: auf dem Desktop darf NICHTS hinter
   „Mehr" verschwinden. Gemessen wird deshalb gegen die tatsächliche Zahl der
   Einträge — das bleibt richtig, egal wie viele es werden. */
{
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  await page.goto(base + '/index.html', { waitUntil: 'networkidle' });
  await page.waitForTimeout(300);
  const { sichtbar, gesamt } = await page.$$eval('nav.nav a:not(.brand)',
    as => ({ sichtbar: as.filter(a => a.offsetParent !== null).length,
             gesamt: as.length }));
  pruefe(sichtbar === gesamt,
         `Desktop zeigt nur ${sichtbar} von ${gesamt} Einträgen`);
  pruefe(gesamt >= 7, `nur ${gesamt} Einträge — die Leiste ist geschrumpft`);
  const mehrDa = await page.$eval('nav.nav .mehr', el => el.offsetParent !== null)
    .catch(() => false);
  pruefe(!mehrDa, 'auf dem Desktop steht „Mehr" im Weg');
  await ctx.close();
}

await browser.close();
console.log(fails ? `\n${fails} Prüfung(en) fehlgeschlagen`
                  : '\nNavigation auf Handy und Desktop OK ✔');
process.exit(fails ? 1 : 0);
