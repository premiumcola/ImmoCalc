// Prüft den Scan-Weg im echten Browser: Kamerabilder -> PDF -> Upload.
// Statt der Kamera werden erzeugte Bilder in das Dateifeld gelegt.
import { chromium } from 'playwright';
import { mkdirSync, writeFileSync } from 'fs';

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

await page.goto(base + '/eingang.html', { waitUntil: 'networkidle' });
await page.waitForSelector('#kamera', { timeout: 8000 })
  .catch(() => pruefe(false, 'Kamera-Knopf fehlt'));

// Das Dateifeld muss die Kamera ansteuern — sonst öffnet iOS nur die Galerie
const capture = await page.getAttribute('#kameraFeld', 'capture');
const accept = await page.getAttribute('#kameraFeld', 'accept');
const mehrfach = await page.getAttribute('#kameraFeld', 'multiple');
pruefe(capture === 'environment', `capture ist "${capture}" statt "environment"`);
pruefe(accept === 'image/*', `accept ist "${accept}"`);
pruefe(mehrfach !== null, 'multiple fehlt — mehrseitige Belege gingen nicht');

// PDF-Bau im Browser prüfen: zwei erzeugte Seiten
const ergebnis = await page.evaluate(async () => {
  const { scanZuPdf } = await import('./assets/scan.js');

  const malen = (text, farbe) => new Promise(fertig => {
    const c = document.createElement('canvas');
    c.width = 1400; c.height = 2000;
    const g = c.getContext('2d');
    g.fillStyle = '#fff'; g.fillRect(0, 0, c.width, c.height);
    g.fillStyle = farbe; g.fillRect(80, 80, 1240, 300);
    g.fillStyle = '#111'; g.font = '90px sans-serif';
    g.fillText(text, 120, 600);
    c.toBlob(b => fertig(new File([b], 'seite.jpg', { type: 'image/jpeg' })), 'image/jpeg', 0.9);
  });

  const dateien = [await malen('Rechnung 2026', '#0F6E5C'),
                   await malen('Seite zwei', '#916212')];
  const roh = dateien.reduce((s, d) => s + d.size, 0);
  const { pdf, seiten } = await scanZuPdf(dateien);
  const kopf = new TextDecoder().decode(
    new Uint8Array(await pdf.slice(0, 8).arrayBuffer()));
  const ende = new TextDecoder().decode(
    new Uint8Array(await pdf.slice(-8).arrayBuffer()));
  const bytes = new Uint8Array(await pdf.arrayBuffer());
  return { seiten, groesse: pdf.size, roh, kopf, ende, typ: pdf.type,
           daten: Array.from(bytes.slice(0, 0)) };
});

pruefe(ergebnis.seiten === 2, `${ergebnis.seiten} Seiten statt 2`);
pruefe(ergebnis.typ === 'application/pdf', 'falscher MIME-Typ: ' + ergebnis.typ);
pruefe(ergebnis.kopf.startsWith('%PDF-1.'), 'kein PDF-Kopf: ' + ergebnis.kopf);
pruefe(ergebnis.ende.includes('%%EOF'), 'kein EOF am Ende');
// Verkleinerung muss wirken: kleiner als die Rohaufnahmen
pruefe(ergebnis.groesse < ergebnis.roh,
  `PDF (${ergebnis.groesse}) nicht kleiner als Rohbilder (${ergebnis.roh})`);
pruefe(ergebnis.groesse < 900_000, `PDF zu gross: ${ergebnis.groesse} Bytes`);

console.log(`   PDF: ${ergebnis.seiten} Seiten, ${Math.round(ergebnis.groesse / 1024)} KB ` +
  `(Rohbilder ${Math.round(ergebnis.roh / 1024)} KB)`);

// Datei aus dem Browser holen und für die Sichtprüfung ablegen
const pdfBytes = await page.evaluate(async () => {
  const { scanZuPdf } = await import('./assets/scan.js');
  const c = document.createElement('canvas');
  c.width = 1200; c.height = 1700;
  const g = c.getContext('2d');
  g.fillStyle = '#fff'; g.fillRect(0, 0, c.width, c.height);
  g.fillStyle = '#0F6E5C'; g.fillRect(60, 60, 1080, 220);
  g.fillStyle = '#111'; g.font = '70px sans-serif';
  g.fillText('Stadtwerke Jahresabrechnung', 90, 500);
  g.fillText('Betrag: 412,90 EUR', 90, 620);
  const blob = await new Promise(f => c.toBlob(f, 'image/jpeg', 0.9));
  const { pdf } = await scanZuPdf([new File([blob], 's.jpg', { type: 'image/jpeg' })]);
  return Array.from(new Uint8Array(await pdf.arrayBuffer()));
});
writeFileSync('tests/screenshots/scan-beispiel.pdf', Buffer.from(pdfBytes));

// Dialog: eine echte Aufnahme ins Feld legen (ein 1x1-Bild überlebt
// createImageBitmap nicht) und den Ablauf bis zum Ziel-Dialog fahren
await page.evaluate(async () => {
  const c = document.createElement('canvas');
  c.width = 1000; c.height = 1400;
  const g = c.getContext('2d');
  g.fillStyle = '#fff'; g.fillRect(0, 0, c.width, c.height);
  g.fillStyle = '#111'; g.font = '60px sans-serif';
  g.fillText('Testbeleg', 80, 300);
  const blob = await new Promise(f => c.toBlob(f, 'image/jpeg', 0.9));
  const feld = document.getElementById('kameraFeld');
  const daten = new DataTransfer();
  daten.items.add(new File([blob], 'aufnahme.jpg', { type: 'image/jpeg' }));
  feld.files = daten.files;
  feld.dispatchEvent(new Event('change', { bubbles: true }));
});
await page.waitForSelector('#zielDlg[open]', { timeout: 8000 })
  .catch(() => pruefe(false, 'Ziel-Dialog öffnet nicht'));
await page.screenshot({ path: 'tests/screenshots/scan-dialog.png', fullPage: true });

const objekte = await page.$$eval('#zielObjekt option', o => o.length);
const arten = await page.$$eval('#zielArt option', o => o.length);
pruefe(objekte > 0, 'keine Immobilie zur Auswahl');
pruefe(arten > 0, 'keine Dokumentart zur Auswahl');

await page.click('#zielOk');
await page.waitForTimeout(1500);
const text = await page.textContent('.kamera');
pruefe(/Abgelegt|Eingang|Nextcloud/i.test(text), 'keine Rückmeldung: ' + text.trim());
console.log('   Rückmeldung: ' + text.replace(/\s+/g, ' ').trim().slice(0, 80));

pruefe(fehler.length === 0, 'JS-Fehler: ' + fehler.slice(0, 2).join(' | '));

await browser.close();
console.log(fails ? `\n${fails} Prüfung(en) fehlgeschlagen` : '\nScan-Weg OK ✔');
process.exit(fails ? 1 : 0);
