// Erzeugt die App-Icons aus public/icons/icon.svg — gerendert mit Chromium,
// damit kein zusaetzliches Bildwerkzeug noetig ist.
//
//   node tools/make-icons.mjs
//
// apple-touch-icon bekommt bewusst KEINE runden Ecken: iOS maskiert selbst,
// sonst entstehen doppelte Ecken mit dunklem Rand.
import { chromium } from 'playwright';
import { readFileSync, writeFileSync } from 'fs';

const svg = readFileSync('public/icons/icon.svg', 'utf8');
const eckig = svg.replace(/rx="112"/, 'rx="0"');

const VARIANTEN = [
  { datei: 'public/icons/apple-touch-icon.png', groesse: 180, quelle: eckig },
  { datei: 'public/icons/icon-192.png', groesse: 192, quelle: svg },
  { datei: 'public/icons/icon-512.png', groesse: 512, quelle: svg },
  { datei: 'public/icons/icon-maskable-512.png', groesse: 512, quelle: eckig },
];

const browser = await chromium.launch();
for (const { datei, groesse, quelle } of VARIANTEN) {
  const page = await browser.newPage({
    viewport: { width: groesse, height: groesse },
    deviceScaleFactor: 1,
  });
  await page.setContent(
    `<body style="margin:0;width:${groesse}px;height:${groesse}px">
       <div style="width:${groesse}px;height:${groesse}px">${
         quelle.replace(/width="512" height="512"/, `width="${groesse}" height="${groesse}"`)
       }</div></body>`);
  writeFileSync(datei, await page.screenshot({ omitBackground: true }));
  await page.close();
  console.log(`${datei}  ${groesse}×${groesse}`);
}
await browser.close();
