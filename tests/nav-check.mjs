// Die Navigationsleiste auf schmalen Schirmen.
//
// N327-b: unten stehen auf dem Handy fünf feste Ziele (Objekte, Nebenkosten,
// Dokumente als runder Knopf in der Mitte, PV Anlagen, Wertentwicklung), kein
// „Mehr" mehr dort. Alles andere (Vermietung, E-Tankstelle, Eigentümer,
// Vorlagen, Lexikon) hängt an der Kopfzeilen-„…"; Einstellungen und Kontakte
// sind eigene Kopfzeilen-Symbole. Auf dem Desktop stehen weiterhin alle Ziele
// in der Seitenleiste.
import { chromium } from 'playwright';
import { mkdirSync } from 'fs';

const base = process.env.BASE_URL || 'http://127.0.0.1:8199';
mkdirSync('tests/screenshots', { recursive: true });

const browser = await chromium.launch();
let fails = 0;
const pruefe = (ok, text) => { if (!ok) { fails++; console.log('   ⚠ ' + text); } };

/* ---- iPhone: genau vier feste Ziele, kein „Mehr" ---- */
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
    as => as.filter(a => a.offsetParent !== null).map(a => a.getAttribute('href')));
  const erwartet = ['index.html', 'nebenkosten.html', 'eingang.html',
                    'strom.html', 'wertentwicklung.html'];
  pruefe(erwartet.every(h => sichtbar.includes(h)) && sichtbar.length === 5,
    `untere Leiste zeigt ${JSON.stringify(sichtbar)} statt der fünf festen Ziele`);

  const mehr = await page.$('nav.nav .mehr');
  pruefe(mehr === null, '„Mehr" gibt es unten nicht mehr — sollte verschwunden sein');

  // Jedes Ziel muss mit dem Daumen treffbar sein
  for (const el of await page.$$('nav.nav a:not(.brand)')) {
    if (!await el.isVisible()) continue;
    const kasten = await el.boundingBox();
    if (kasten.width < 56 || kasten.height < 44) {
      pruefe(false, `Ziel zu klein: ${Math.round(kasten.width)}×${Math.round(kasten.height)} px`);
      break;
    }
  }
  await page.screenshot({ path: 'tests/screenshots/nav-iphone.png' });

  // Die Kopfzeilen-„…" muss die übrigen Wege anbieten
  await page.click('.kopfakt .ka-mehr');
  await page.waitForSelector('dialog.immo-dlg[open] .mehrliste', { timeout: 4000 })
    .catch(() => pruefe(false, 'Kopfzeilen-„…" öffnet kein Blatt'));
  const ziele = await page.$$eval('.mehrliste a',
    as => as.map(a => a.getAttribute('href')));
  pruefe(ziele.includes('eigentuemer.html') && ziele.includes('vermietungen.html')
    && !ziele.includes('eingang.html') && !ziele.includes('settings.html')
    && !ziele.includes('kontakte.html'),
    'Kopfzeilen-„…" zeigt die falschen Einträge: ' + ziele.join(', '));
  await page.screenshot({ path: 'tests/screenshots/nav-mehr.png' });

  pruefe(fehler.length === 0, 'JS-Fehler: ' + fehler.slice(0, 2).join(' | '));
  await ctx.close();
}

/* ---- Handy: Einstellungen/Kontakte sind eigene Kopfzeilen-Symbole ----
   N327-b — nicht mehr hinter „…" versteckt (Nutzer-Feedback): stehen sie
   selbst als eigenes `.ka-ziel`, muss GENAU dieses Symbol `aria-current`
   tragen, wenn man auf der jeweiligen Seite steht — nicht die „…". */
{
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await ctx.newPage();
  await page.goto(base + '/settings.html', { waitUntil: 'networkidle' });
  await page.waitForTimeout(300);
  const markiert = await page.$eval('.kopfakt a[href="settings.html"]',
    el => el.getAttribute('aria-current') === 'page').catch(() => false);
  pruefe(markiert, 'Einstellungen-Symbol in der Kopfzeile zeigt nicht „hier"');
  const mehrMarkiert = await page.$eval('.kopfakt .ka-mehr',
    el => el.getAttribute('aria-current') === 'page').catch(() => false);
  pruefe(!mehrMarkiert, 'die „…" markiert sich faelschlich mit, obwohl Einstellungen ihr eigenes Symbol hat');
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
  const mehrDa = await page.$('nav.nav .mehr');
  pruefe(mehrDa === null, 'auf dem Desktop gibt es kein unteres „Mehr" mehr — sollte fehlen');
  await ctx.close();
}

await browser.close();
console.log(fails ? `\n${fails} Prüfung(en) fehlgeschlagen`
                  : '\nNavigation auf Handy und Desktop OK ✔');
process.exit(fails ? 1 : 0);
