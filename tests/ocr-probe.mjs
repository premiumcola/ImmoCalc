/* Beweisprobe für die Texterkennung.
 *
 * Baut aus HTML eine realistisch aussehende Rechnung, fotografiert sie mit
 * Chromium (das entspricht dem, was die Kamera liefert) und schickt sie an
 * /api/dokumente/erkennen. Der Endpunkt speichert nichts — er liest das Bild,
 * gibt einen Vorschlag zurück und vergisst es wieder. Deshalb darf er gegen
 * die Live-Instanz laufen, wo Tesseract installiert ist.
 */
import { chromium } from 'playwright';
import { readFileSync, writeFileSync, mkdirSync } from 'fs';

const ziel = process.env.OCR_BASE || 'http://192.168.178.10:8091';
mkdirSync('tests/screenshots/ocr', { recursive: true });

const RECHNUNGEN = [
  {
    name: 'stadtwerke',
    erwartet: { betrag: 1071.00, jahr: 2025, monat: 3, kategorie: 'Nebenkosten' },
    html: `
      <h1>Stadtwerke Musterstadt</h1>
      <p>Am Kraftwerk 3 · 90562 Musterstadt</p>
      <h2>Jahresrechnung Wasser / Abwasser</h2>
      <table>
        <tr><td>Rechnungsnummer</td><td>2025-004711</td></tr>
        <tr><td>Rechnungsdatum</td><td>14.03.2025</td></tr>
        <tr><td>Kundennummer</td><td>88 12 445</td></tr>
        <tr><td>Abrechnungszeitraum</td><td>01.01.2024 - 31.12.2024</td></tr>
      </table>
      <table class="posten">
        <tr><th>Position</th><th>Menge</th><th>Betrag</th></tr>
        <tr><td>Trinkwasser</td><td>142 m3</td><td>812,40</td></tr>
        <tr><td>Grundpreis Zaehler</td><td>12 Monate</td><td>87,60</td></tr>
        <tr><td>Zwischensumme</td><td></td><td>900,00</td></tr>
        <tr><td>Umsatzsteuer 19 %</td><td></td><td>171,00</td></tr>
        <tr class="summe"><td>Gesamtbetrag</td><td></td><td>1.071,00</td></tr>
      </table>
      <p>Bitte ueberweisen Sie den Betrag bis zum 28.03.2025.</p>`,
  },
  {
    name: 'heizung',
    erwartet: { betrag: 3428.55, jahr: 2024, monat: 11, kategorie: 'Nebenkosten' },
    html: `
      <h1>Waermedienst Nord GmbH</h1>
      <h2>Heizkostenabrechnung 2024</h2>
      <table>
        <tr><td>Datum</td><td>08.11.2024</td></tr>
        <tr><td>Liegenschaft</td><td>Musterstrasse 5</td></tr>
      </table>
      <table class="posten">
        <tr><td>Brennstoffkosten</td><td>2.880,00</td></tr>
        <tr><td>Wartung</td><td>240,00</td></tr>
        <tr><td>Messdienst</td><td>308,55</td></tr>
        <tr class="summe"><td>Rechnungsbetrag</td><td>3.428,55</td></tr>
      </table>`,
  },
  {
    name: 'grundsteuer',
    erwartet: { betrag: 486.20, jahr: 2025, monat: 1, kategorie: 'Steuer' },
    html: `
      <h1>Stadt Musterstadt — Steueramt</h1>
      <h2>Grundsteuerbescheid</h2>
      <table>
        <tr><td>Bescheiddatum</td><td>15.01.2025</td></tr>
        <tr><td>Aktenzeichen</td><td>GS/2025/0812</td></tr>
      </table>
      <table class="posten">
        <tr><td>Grundsteuer B, Jahresbetrag</td><td>486,20</td></tr>
        <tr><td>faellig je Quartal</td><td>121,55</td></tr>
        <tr class="summe"><td>Zu zahlen</td><td>486,20</td></tr>
      </table>`,
  },
];

const RUMPF = inhalt => `<!DOCTYPE html><html lang="de"><head><meta charset="utf-8">
<style>
  /* Bewusst eine gewoehnliche Serifenlose in normaler Groesse — so sehen
     echte Rechnungen aus, und genau daran muss sich die Erkennung messen. */
  body{font:15px/1.6 Arial,Helvetica,sans-serif;color:#000;background:#fff;
       padding:48px 56px;width:760px}
  h1{font-size:22px;margin:0 0 4px} h2{font-size:17px;margin:26px 0 10px}
  p{margin:4px 0}
  table{border-collapse:collapse;margin:14px 0;width:100%}
  td,th{padding:5px 8px;text-align:left}
  .posten td:last-child,.posten th:last-child{text-align:right}
  .posten tr.summe{font-weight:bold;border-top:2px solid #000}
</style></head><body>${inhalt}</body></html>`;

const browser = await chromium.launch();
const page = await (await browser.newContext({
  viewport: { width: 860, height: 1200 }, deviceScaleFactor: 2 })).newPage();

let fehler = 0;
for (const rechnung of RECHNUNGEN) {
  await page.setContent(RUMPF(rechnung.html));
  const bild = `tests/screenshots/ocr/${rechnung.name}.png`;
  await page.screenshot({ path: bild, fullPage: true });

  const paket = new FormData();
  paket.append('datei', new Blob([readFileSync(bild)], { type: 'image/png' }),
               `${rechnung.name}.png`);
  const antwort = await fetch(`${ziel}/api/dokumente/erkennen`,
                              { method: 'POST', body: paket });
  const erg = await antwort.json();

  const betragOk = erg.betrag === rechnung.erwartet.betrag;
  const datumOk = erg.datum
    && Number(erg.datum.slice(0, 4)) === rechnung.erwartet.jahr
    && Number(erg.datum.slice(5, 7)) === rechnung.erwartet.monat;
  // Die Kategorie kam erst später dazu — eine ältere Fassung der API kennt
  // sie noch nicht. Dann wird sie nicht bemängelt, sondern angemerkt.
  const kategorieBekannt = 'kategorie' in erg;
  const kategorieOk = !kategorieBekannt
    || erg.kategorie === rechnung.erwartet.kategorie;

  const gut = betragOk && datumOk && kategorieOk;
  console.log(`${gut ? '✓' : '✗'} ${rechnung.name.padEnd(12)}`
    + ` Betrag ${String(erg.betrag).padStart(9)} (soll ${rechnung.erwartet.betrag})`
    + ` · Datum ${erg.datum} (soll ${rechnung.erwartet.jahr}-`
    + `${String(rechnung.erwartet.monat).padStart(2, '0')})`
    + ` · Art ${kategorieBekannt ? (erg.kategorie || '—') : '(API zu alt)'}`
    + ` · ${erg.zeichen} Zeichen`);
  if (!gut) fehler++;
}

await browser.close();
console.log(fehler ? `\n${fehler} von ${RECHNUNGEN.length} nicht erkannt`
                   : `\nAlle ${RECHNUNGEN.length} Rechnungen richtig gelesen ✔`);
process.exit(fehler ? 1 : 0);
