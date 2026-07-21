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

  // Vier Aufnahmen: eine mehrseitige Abrechnung ist der Normalfall, nicht
  // die Ausnahme. Alle vier müssen in EINE Datei wandern.
  const dateien = [await malen('Rechnung 2026', '#0F6E5C'),
                   await malen('Seite zwei', '#916212'),
                   await malen('Seite drei', '#2E7D4F'),
                   await malen('Seite vier', '#B24229')];
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

pruefe(ergebnis.seiten === 4, `${ergebnis.seiten} Seiten statt 4`);
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
  const seite = new File([blob], 's.jpg', { type: 'image/jpeg' });
  // Dreimal dieselbe Aufnahme: die Datei dient der Sichtprüfung und soll
  // zeigen, dass mehrere Seiten wirklich in einem PDF landen.
  const { pdf } = await scanZuPdf([seite, seite, seite]);
  return Array.from(new Uint8Array(await pdf.arrayBuffer()));
});
writeFileSync('tests/screenshots/scan-beispiel.pdf', Buffer.from(pdfBytes));

// Wie viele Dokumente kennt die Ablage vor dem Scan? Danach muss genau eines
// mehr dastehen — sonst hat der Weg nur so ausgesehen, als hätte er geklappt.
const gesamtVorher = await fetch(base + '/api/dokumente')
  .then(a => a.json()).then(d => d.gesamt).catch(() => null);
pruefe(typeof gesamtVorher === 'number', 'Ablage nicht abfragbar');

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
// Der Dialog kommt nur, wenn etwas offen ist: steht die Immobilie fest und hat
// die Texterkennung die Art gelesen, wird ohne Rückfrage abgelegt. Beide Wege
// sind richtig — geprüft wird, dass am Ende eine Rückmeldung steht.
const dialog = await page.waitForSelector('#zielDlg[open]', { timeout: 8000 })
  .catch(() => null);
if (dialog) {
  await page.screenshot({ path: 'tests/screenshots/scan-dialog.png', fullPage: true });
  // Auswahlfelder im eigenen Design (assets/auswahl.js), keine Systemliste
  pruefe(await page.$$eval('#zielObjekt option', o => o.length) === 0,
    'natives <select> im Ziel-Dialog');
  const objekte = await page.$$eval('#zielObjekt .auswahl-liste li', o => o.length);
  const arten = await page.$$eval('#zielArt .auswahl-liste li', o => o.length);
  pruefe(objekte > 0, 'keine Immobilie zur Auswahl');
  pruefe(arten > 0, 'keine Dokumentart zur Auswahl');
  await page.click('#zielOk');
} else {
  console.log('   Ohne Rückfrage abgelegt (Immobilie und Art eindeutig)');
}

// Der Knopf trägt genau drei Endzustände. Der Ruhetext ist keiner davon —
// stünde er noch da, wäre der change-Handler nie angelaufen (etwa weil ein
// Modul-Import gescheitert ist). Genau das muss rot werden, deshalb wird auf
// einen der drei Endzustände gewartet und nicht auf ein loses Wort im Text.
const ENDE = ['✓ Abgelegt', 'Fehlgeschlagen', 'Abgebrochen'];
const ruhe = await page.waitForFunction(
  enden => enden.includes(document.querySelector('.kamera .k1')?.textContent.trim()),
  ENDE, { timeout: 12000, polling: 100 }).catch(() => null);

const stand = (await page.textContent('.kamera .k1') || '').trim();
const grund = (await page.textContent('.kamera .k2') || '').trim();
if (!ruhe) {
  pruefe(false, `Scan lief nicht an — Knopf steht bei "${stand}" · "${grund}"`);
} else if (stand === '✓ Abgelegt') {
  const gesamtNachher = await fetch(base + '/api/dokumente')
    .then(a => a.json()).then(d => d.gesamt).catch(() => null);
  pruefe(gesamtNachher === gesamtVorher + 1,
    `Ablage meldet Erfolg, hat aber ${gesamtVorher} → ${gesamtNachher} Dokumente`);
  console.log(`   Abgelegt: ${grund} (${gesamtVorher} → ${gesamtNachher})`);
} else if (stand === 'Fehlgeschlagen'
           && /Nextcloud|Cloud|verknüpft|Zugangsdaten/i.test(grund)) {
  // Der Prüfstand hat keine Cloud. Der Weg ist bis zum Upload gelaufen und die
  // API hat sauber abgelehnt — mehr ist hier ohne echte Zugangsdaten nicht zu
  // holen. Jeder andere Fehlschlag ist ein echter.
  console.log('   Ohne Cloud-Zugang, Upload sauber abgelehnt: ' + grund.slice(0, 70));
} else {
  pruefe(false, `Scan endete mit "${stand}": ${grund}`);
}

// ---------------------------------------------------------------------------
// Arbeitsfläche: Karte -> Prüfblatt (CXXIV, CXXV, CXXIX)
// Auf dem Telefon gibt es nur eine Spalte — das Prüfblatt muss dort unter der
// gewählten Karte liegen, nicht am Ende der Liste.
// ---------------------------------------------------------------------------
await page.goto(base + '/eingang.html', { waitUntil: 'networkidle' });
const erste = await page.waitForSelector('.beleg', { timeout: 8000 })
  .catch(() => null);
if (!erste) {
  console.log('   Keine Dokumente in der Ablage — Arbeitsfläche nicht geprüft');
} else {
  // Belegdatum und Betrag gehören in die Liste, nicht nur in den Dateinamen
  const chips = await page.$$eval('.beleg .chip', n => n.map(c => c.textContent));
  pruefe(chips.length > 0, 'Karten zeigen weder Datum noch Betrag');

  await page.click('.beleg .dn');
  const blatt = await page.waitForSelector('#blatt:not([hidden])', { timeout: 5000 })
    .catch(() => null);
  pruefe(Boolean(blatt), 'Prüfblatt öffnet sich nicht');
  if (blatt) {
    pruefe(await page.$eval('#blatt', b => Boolean(b.closest('.beleg'))),
      'Prüfblatt steht auf dem Telefon nicht bei der gewählten Karte');
    pruefe(await page.isVisible('#bSchau'), 'keine Belegvorschau');
    pruefe((await page.textContent('#bName')).trim().length > 0,
      'Dateiname fehlt im Prüfblatt');
    // Die Gegenüberstellung „erkannt · wird eingetragen"
    const plan = await page.textContent('#bPlan');
    for (const wort of ['Sache', 'Datum', 'Betrag', 'Immobilie']) {
      pruefe(plan.includes(wort), `Zeile "${wort}" fehlt im Prüfblatt`);
    }
    pruefe((await page.textContent('#bZiel')).length > 0,
      'es steht nicht da, was aus dem Beleg wird');
    // Entfernen fragt zuerst nach
    await page.click('#bWeg');
    pruefe((await page.textContent('#bWeg')).includes('Wirklich'),
      'Entfernen fragt nicht nach');
    await page.screenshot({ path: 'tests/screenshots/eingang-blatt.png',
                            fullPage: true });
    await page.click('#bZu');
    pruefe(await page.$('#blatt[hidden]') !== null,
      'Prüfblatt lässt sich nicht schließen');
  }
}

pruefe(fehler.length === 0, 'JS-Fehler: ' + fehler.slice(0, 2).join(' | '));

await browser.close();
console.log(fails ? `\n${fails} Prüfung(en) fehlgeschlagen` : '\nScan-Weg OK ✔');
process.exit(fails ? 1 : 0);
