/* Mehrseitige Belege: Rand erkennen, entzerren, zu einem PDF fügen.
 *
 * Jedes Foto kommt auf eine eigene Seite. Die Ecken werden zuerst automatisch
 * geschätzt (Kontrastschwelle + größtes helles Viereck), lassen sich aber an
 * vier großen Griffen von Hand nachziehen — das ist der Sicherheitsanker
 * gegen eine falsche Erkennung, kein Nice-to-have. Zwei Wächter warnen, wenn
 * die Schätzung offensichtlich daneben liegt, blockieren aber nicht: sie
 * verhindern nur, dass ein schlechter Zuschnitt stillschweigend durchgeht.
 *
 * Die Entzerrung nutzt den Zwei-Dreieck-Trick auf <canvas>: pro Dreieck eine
 * affine Abbildung von den (korrigierten) Bildecken auf ein sauberes
 * Rechteck, dann geclippt gezeichnet. Keine Bibliothek, keine Matrixklasse —
 * nur die Punkte, die für genau diesen Trick nötig sind.
 *
 * Das fertige PDF baut `bauePdf` aus scan.js — dieselbe Minimal-Implementierung,
 * die auch der unbearbeitete Scan-Weg verwendet (DCTDecode, ein Bild je Seite).
 */
import { bauePdf } from './scan.js';

// ---- Stellschrauben — benannt, damit sie sich leicht nachjustieren lassen ----
const DET_KANTE = 700;            // Kante für die Randerkennung (Downscale)
const VORSCHAU_KANTE = 1000;      // Kante für die Bildschirm-Vorschau
const MAX_KANTE = 1700;           // Kante des fertigen, entzerrten Bildes
const JPEG_GUETE = 0.72;
const MIN_HELL_ANTEIL = 0.04;     // zu wenig Kontrast -> Erkennung verworfen
const MIN_FLAECHE_ANTEIL = 0.55;  // Wächter a) zu viel abgeschnitten
const SEITENVERHAELTNIS_MIN = 0.7; // Wächter b) Längenverhältnis Gegenseiten
const SEITENVERHAELTNIS_MAX = 1.4;
const WINKEL_TOLERANZ_GRAD = 15;   // Wächter b) Winkeldifferenz Gegenseiten
const A4_VERHAELTNIS = Math.SQRT2; // 1,4142 — lange durch kurze Seite
const A4_TOLERANZ = 0.12;          // wie nah an A4, um dorthin zu runden

let stilEingefuegt = false;
function stilSicherstellen() {
  if (stilEingefuegt) return;
  stilEingefuegt = true;
  const stil = document.createElement('style');
  stil.textContent = `
.kscan-overlay{position:fixed;inset:0;z-index:9000;background:rgba(15,20,22,.94);
  display:flex;flex-direction:column;height:100dvh;font-family:var(--body,sans-serif);
  color:#fff}
.kscan-kopf{flex:none;display:flex;align-items:center;gap:10px;padding:12px 12px;
  padding-top:max(12px,env(safe-area-inset-top))}
.kscan-x{flex:none;width:44px;height:44px;border:none;border-radius:12px;
  background:rgba(255,255,255,.12);color:#fff;font:400 20px var(--body,sans-serif);
  cursor:pointer;display:flex;align-items:center;justify-content:center}
.kscan-x:hover{background:rgba(255,255,255,.22)}
.kscan-titel{flex:1;text-align:center;font:600 13.5px var(--disp,sans-serif);
  letter-spacing:-.01em}
.kscan-platz{flex:none;width:44px}
.kscan-mitte{flex:1;min-height:0;display:flex;flex-direction:column;
  align-items:center;justify-content:center;padding:6px 14px;gap:10px}
.kscan-bildwrap{position:relative;max-width:100%;max-height:100%;line-height:0;
  touch-action:none;user-select:none}
.kscan-bild{display:block;max-width:100%;max-height:calc(100dvh - 300px);
  width:auto;height:auto;border-radius:10px;background:#000}
.kscan-umriss{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}
.kscan-umriss polygon{fill:rgba(15,110,92,.16);stroke:var(--teal,#0F6E5C);
  stroke-width:.006;vector-effect:non-scaling-stroke}
.kscan-overlay.kscan-warnt .kscan-umriss polygon{fill:rgba(145,98,18,.18);
  stroke:var(--amber,#916212)}
.kscan-griff{position:absolute;width:44px;height:44px;margin:-22px 0 0 -22px;
  border-radius:50%;border:3px solid #fff;background:rgba(15,110,92,.85);
  cursor:grab;touch-action:none;box-shadow:0 2px 8px rgba(0,0,0,.4)}
.kscan-griff::after{content:'';position:absolute;inset:14px;border-radius:50%;
  background:#fff}
.kscan-overlay.kscan-warnt .kscan-griff{background:rgba(145,98,18,.9)}
.kscan-griff:active{cursor:grabbing}
.kscan-hinweis{flex:none;max-width:440px;text-align:center;font:500 12px var(--mono,monospace);
  color:rgba(255,255,255,.68);line-height:1.55;padding:0 8px}
.kscan-hinweis.kscan-warn{color:#F2C879}
.kscan-leer{text-align:center;color:rgba(255,255,255,.75);font:500 13.5px var(--body,sans-serif);
  padding:30px 20px;line-height:1.6}
.kscan-fuss{flex:none;padding:10px 12px;padding-bottom:max(12px,env(safe-area-inset-bottom));
  background:rgba(0,0,0,.28)}
.kscan-thumbs{display:flex;gap:8px;overflow-x:auto;padding:2px 2px 10px;
  scrollbar-width:none}
.kscan-thumbs::-webkit-scrollbar{display:none}
.kscan-thumb{position:relative;flex:none;width:52px;height:70px;border-radius:9px;
  overflow:hidden;border:2px solid transparent;background:#222;cursor:pointer;padding:0}
.kscan-thumb img{width:100%;height:100%;object-fit:cover;display:block}
.kscan-thumb.kscan-aktiv{border-color:var(--teal,#0F6E5C)}
.kscan-thumb.kscan-thumbwarn::before{content:'!';position:absolute;top:2px;left:3px;
  width:15px;height:15px;border-radius:50%;background:var(--amber,#916212);color:#fff;
  font:700 10px var(--mono,monospace);display:flex;align-items:center;justify-content:center}
.kscan-plus{flex:none;width:52px;height:70px;border-radius:9px;border:2px dashed rgba(255,255,255,.4);
  background:none;color:#fff;font:400 22px var(--body,sans-serif);cursor:pointer}
.kscan-werkzeuge{display:flex;align-items:center;justify-content:center;gap:6px;flex-wrap:wrap}
.kscan-reset,.kscan-entfernen{background:none;border:none;color:rgba(255,255,255,.65);
  font:500 11.5px var(--mono,monospace);text-decoration:underline;cursor:pointer;
  padding:8px 12px;min-height:44px;min-width:44px}
.kscan-entfernen{color:#F2A98D}
.kscan-aktionen{display:flex;gap:8px}
.kscan-aktionen button{flex:1;border:none;border-radius:12px;min-height:48px;
  font:600 14px var(--disp,sans-serif);cursor:pointer}
.kscan-ab{background:rgba(255,255,255,.1);color:#fff;flex:none;padding:0 18px}
.kscan-ab:hover{background:rgba(255,255,255,.18)}
.kscan-primaer{background:var(--teal,#0F6E5C);color:#fff}
.kscan-primaer:hover{background:var(--teal-d,#0B5548)}
.kscan-primaer[disabled]{opacity:.5;cursor:default}
@media (min-width:900px){
  .kscan-mitte{padding:20px}
  .kscan-bild{max-height:calc(100dvh - 260px)}
}
`;
  document.head.appendChild(stil);
}

// ---------------------------------------------------------------------------
// Erkennung: größtes helles Viereck vor dunklerem Untergrund.
// ---------------------------------------------------------------------------

/** Otsu-Schwelle aus einem 256er-Histogramm — trennt hell von dunkel. */
function otsuSchwelle(hist, gesamt) {
  let summeGesamt = 0;
  for (let i = 0; i < 256; i++) summeGesamt += i * hist[i];
  let summeHinten = 0, gewichtHinten = 0, beste = 128, besterWert = -1;
  for (let t = 0; t < 256; t++) {
    gewichtHinten += hist[t];
    if (gewichtHinten === 0) continue;
    const gewichtVorn = gesamt - gewichtHinten;
    if (gewichtVorn === 0) break;
    summeHinten += t * hist[t];
    const mittelHinten = summeHinten / gewichtHinten;
    const mittelVorn = (summeGesamt - summeHinten) / gewichtVorn;
    const varianz = gewichtHinten * gewichtVorn * (mittelHinten - mittelVorn) ** 2;
    if (varianz > besterWert) { besterWert = varianz; beste = t; }
  }
  return beste;
}

/**
 * Schätzt die vier Ecken des Dokuments, normiert auf 0..1 relativ zur
 * Bildgröße. Verfahren: graustufen, per Otsu in hell/dunkel trennen, dann
 * unter den hellen Pixeln die Extrempunkte entlang der vier Diagonalen
 * (x+y, x−y, −x+y, −x−y) nehmen — die Stützpunkte eines konvexen Vierecks in
 * vier Richtungen. Schlägt das fehl (zu wenig Kontrast), bleibt ein knapper
 * Rand als Ausgangspunkt; der Wächter für „zu viel abgeschnitten" greift dann
 * ohnehin nicht, der Nutzer zieht die Ecken selbst auf die echten Kanten.
 */
function eckenSchaetzen(bitmap) {
  const w = bitmap.width, h = bitmap.height;
  const faktor = Math.min(1, DET_KANTE / Math.max(w, h));
  const dw = Math.max(1, Math.round(w * faktor));
  const dh = Math.max(1, Math.round(h * faktor));
  const c = document.createElement('canvas');
  c.width = dw; c.height = dh;
  const ctx = c.getContext('2d', { willReadFrequently: true });
  ctx.drawImage(bitmap, 0, 0, dw, dh);
  const { data } = ctx.getImageData(0, 0, dw, dh);

  const grau = new Uint8ClampedArray(dw * dh);
  const hist = new Array(256).fill(0);
  for (let i = 0, p = 0; i < data.length; i += 4, p++) {
    const g = (data[i] * 0.299 + data[i + 1] * 0.587 + data[i + 2] * 0.114) | 0;
    grau[p] = g;
    hist[g]++;
  }
  const schwelle = otsuSchwelle(hist, dw * dh);

  let minSumme = Infinity, maxSumme = -Infinity, minDiff = Infinity, maxDiff = -Infinity;
  let ptTL = null, ptTR = null, ptBR = null, ptBL = null, anzahlHell = 0;
  for (let y = 0; y < dh; y++) {
    for (let x = 0; x < dw; x++) {
      if (grau[y * dw + x] <= schwelle) continue;
      anzahlHell++;
      const summe = x + y, diff = x - y;
      if (summe < minSumme) { minSumme = summe; ptTL = { x, y }; }
      if (summe > maxSumme) { maxSumme = summe; ptBR = { x, y }; }
      if (diff > maxDiff) { maxDiff = diff; ptTR = { x, y }; }
      if (diff < minDiff) { minDiff = diff; ptBL = { x, y }; }
    }
  }

  if (!ptTL || anzahlHell / (dw * dh) < MIN_HELL_ANTEIL) {
    const rand = 0.03;
    return [{ x: rand, y: rand }, { x: 1 - rand, y: rand },
            { x: 1 - rand, y: 1 - rand }, { x: rand, y: 1 - rand }];
  }
  return [ptTL, ptTR, ptBR, ptBL].map(p => ({ x: p.x / dw, y: p.y / dh }));
}

// ---------------------------------------------------------------------------
// Wächter: verhindern nur die stille Übernahme, nichts wird hart blockiert.
// ---------------------------------------------------------------------------

/** Erwartet die Ecken in Pixeln der jeweiligen Seite, Reihenfolge TL,TR,BR,BL. */
function guards([tl, tr, br, bl], breite, hoehe) {
  const flaeche = Math.abs(
    (tl.x * tr.y - tr.x * tl.y) + (tr.x * br.y - br.x * tr.y) +
    (br.x * bl.y - bl.x * br.y) + (bl.x * tl.y - tl.x * bl.y)) / 2;
  const flaecheAnteil = flaeche / (breite * hoehe);

  const dist = (a, b) => Math.hypot(b.x - a.x, b.y - a.y);
  const richtung = (a, b) => Math.atan2(b.y - a.y, b.x - a.x) * 180 / Math.PI;
  const winkelAbstand = (a, b) => {
    const d = Math.abs(a - b) % 180;
    return d > 90 ? 180 - d : d;
  };

  const oben = dist(tl, tr), unten = dist(bl, br);
  const links = dist(tl, bl), rechts = dist(tr, br);
  const verhaeltnisOK = v => v >= SEITENVERHAELTNIS_MIN && v <= SEITENVERHAELTNIS_MAX;
  const seitenSchlecht = !verhaeltnisOK(oben / unten) || !verhaeltnisOK(links / rechts);

  const winkelSchlecht =
    winkelAbstand(richtung(tl, tr), richtung(bl, br)) > WINKEL_TOLERANZ_GRAD ||
    winkelAbstand(richtung(tl, bl), richtung(tr, br)) > WINKEL_TOLERANZ_GRAD;

  return {
    flaecheZuKlein: flaecheAnteil < MIN_FLAECHE_ANTEIL,
    schief: seitenSchlecht || winkelSchlecht,
    flaecheAnteil,
  };
}

// ---------------------------------------------------------------------------
// Entzerren: Zwei-Dreieck-Trick — je Dreieck eine affine Abbildung + Clip.
// ---------------------------------------------------------------------------

/** Affine Abbildung (a,b,c,d,e,f für setTransform), die drei Quellpunkte auf
    drei Zielpunkte legt. Cramersche Regel auf dem 3x3-Koeffizientensystem. */
function affinAusDreieck([[x0, y0], [x1, y1], [x2, y2]],
                          [[X0, Y0], [X1, Y1], [X2, Y2]]) {
  const det = x0 * (y1 - y2) - y0 * (x1 - x2) + (x1 * y2 - y1 * x2);
  const loese = (V0, V1, V2) => {
    const dA = V0 * (y1 - y2) - y0 * (V1 - V2) + (V1 * y2 - y1 * V2);
    const dC = x0 * (V1 - V2) - V0 * (x1 - x2) + (x1 * V2 - V1 * x2);
    const dE = x0 * (y1 * V2 - V1 * y2) - y0 * (x1 * V2 - V1 * x2) + V0 * (x1 * y2 - y1 * x2);
    return [dA / det, dC / det, dE / det];
  };
  const [a, c, e] = loese(X0, X1, X2);
  const [b, d, f] = loese(Y0, Y1, Y2);
  return { a, b, c, d, e, f };
}

/** Zeichnet das Quellbild anhand der vier (Pixel-)Ecken rechtwinklig entzerrt
    in ein neues Canvas der Zielgröße — zwei Dreiecke, je eigene Abbildung. */
function entzerren(bild, [tl, tr, br, bl], breite, hoehe) {
  const canvas = document.createElement('canvas');
  canvas.width = breite;
  canvas.height = hoehe;
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#fff';
  ctx.fillRect(0, 0, breite, hoehe);

  const dTL = [0, 0], dTR = [breite, 0], dBR = [breite, hoehe], dBL = [0, hoehe];
  const dreieck = (quelle, ziel) => {
    ctx.save();
    ctx.beginPath();
    ctx.moveTo(ziel[0][0], ziel[0][1]);
    ctx.lineTo(ziel[1][0], ziel[1][1]);
    ctx.lineTo(ziel[2][0], ziel[2][1]);
    ctx.closePath();
    ctx.clip();
    const { a, b, c, d, e, f } = affinAusDreieck(quelle, ziel);
    ctx.setTransform(a, b, c, d, e, f);
    ctx.drawImage(bild, 0, 0);
    ctx.restore();
  };
  dreieck([[tl.x, tl.y], [tr.x, tr.y], [bl.x, bl.y]], [dTL, dTR, dBL]);
  dreieck([[tr.x, tr.y], [br.x, br.y], [bl.x, bl.y]], [dTR, dBR, dBL]);
  return canvas;
}

/** Zielgröße aus den erkannten Kantenlängen — tendiert Richtung A4, ohne es
    zu erzwingen, und bleibt innerhalb von MAX_KANTE. */
function zielGroesse([tl, tr, br, bl]) {
  const dist = (a, b) => Math.hypot(b.x - a.x, b.y - a.y);
  let breite = Math.round((dist(tl, tr) + dist(bl, br)) / 2) || 1;
  let hoehe = Math.round((dist(tl, bl) + dist(tr, br)) / 2) || 1;

  const lang = Math.max(breite, hoehe), kurz = Math.min(breite, hoehe);
  if (Math.abs(lang / kurz - A4_VERHAELTNIS) < A4_VERHAELTNIS * A4_TOLERANZ) {
    if (breite >= hoehe) hoehe = Math.round(breite / A4_VERHAELTNIS);
    else breite = Math.round(hoehe / A4_VERHAELTNIS);
  }
  const faktor = Math.min(1, MAX_KANTE / Math.max(breite, hoehe));
  return { breite: Math.max(1, Math.round(breite * faktor)),
           hoehe: Math.max(1, Math.round(hoehe * faktor)) };
}

// ---------------------------------------------------------------------------
// Überlagerung: Aufnahme prüfen, Ecken nachziehen, Seiten verwalten.
// ---------------------------------------------------------------------------

const ECKEN_LABEL = ['Ecke oben links', 'Ecke oben rechts',
                     'Ecke unten rechts', 'Ecke unten links'];

/** Baut die statische Vorschau-Canvas einer Seite (einmalig, gecacht). */
async function vorschauCanvas(bitmap) {
  const faktor = Math.min(1, VORSCHAU_KANTE / Math.max(bitmap.width, bitmap.height));
  const c = document.createElement('canvas');
  c.width = Math.max(1, Math.round(bitmap.width * faktor));
  c.height = Math.max(1, Math.round(bitmap.height * faktor));
  c.getContext('2d').drawImage(bitmap, 0, 0, c.width, c.height);
  return c;
}

/**
 * Öffnet die Bearbeitung für eine Reihe frisch aufgenommener Fotos.
 * Löst mit `{ pdf, seiten }` auf (gleiche Form wie `scanZuPdf`), oder mit
 * `null`, wenn abgebrochen wurde.
 */
export function kamerascanStarten(dateien, optionen = {}) {
  stilSicherstellen();
  const bilder = Array.from(dateien).filter(d => d.type.startsWith('image/'));
  if (!bilder.length) return Promise.reject(new Error('Keine Bilder erhalten'));

  return new Promise(fertigMit => {
    const seiten = [];       // { bitmap, ecken, eckenErkannt, vorschau, thumbUrl }
    let aktiv = 0;
    let abgeschlossen = false;

    const overlay = document.createElement('div');
    overlay.className = 'kscan-overlay';
    overlay.innerHTML = `
      <div class="kscan-kopf">
        <button class="kscan-x" aria-label="Abbrechen" data-kscan="ab">×</button>
        <div class="kscan-titel" data-kscan="titel"></div>
        <div class="kscan-platz"></div>
      </div>
      <div class="kscan-mitte" data-kscan="mitte"></div>
      <div class="kscan-fuss">
        <div class="kscan-thumbs" data-kscan="thumbs"></div>
        <div class="kscan-aktionen">
          <button class="kscan-ab" data-kscan="abbrechen">Abbrechen</button>
          <button class="kscan-primaer" data-kscan="primaer" disabled>Seiten übernehmen</button>
        </div>
      </div>`;
    document.body.appendChild(overlay);
    const vormalsUeberlauf = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    const titelEl = overlay.querySelector('[data-kscan="titel"]');
    const mitte = overlay.querySelector('[data-kscan="mitte"]');
    const thumbs = overlay.querySelector('[data-kscan="thumbs"]');
    const primaer = overlay.querySelector('[data-kscan="primaer"]');

    const dateiEingabe = document.createElement('input');
    dateiEingabe.type = 'file';
    dateiEingabe.accept = 'image/*';
    dateiEingabe.capture = 'environment';
    dateiEingabe.multiple = true;
    dateiEingabe.hidden = true;
    overlay.appendChild(dateiEingabe);

    function aufraeumen() {
      document.body.style.overflow = vormalsUeberlauf;
      for (const s of seiten) {
        URL.revokeObjectURL(s.thumbUrl);
        s.bitmap.close?.();
      }
      overlay.remove();
    }

    function abbrechen() {
      if (abgeschlossen) return;
      abgeschlossen = true;
      aufraeumen();
      fertigMit(null);
    }

    async function seiteAnlegen(datei) {
      const bitmap = await createImageBitmap(datei, { imageOrientation: 'from-image' });
      const ecken = eckenSchaetzen(bitmap);
      const vorschau = await vorschauCanvas(bitmap);
      const thumbBlob = await new Promise(r => vorschau.toBlob(r, 'image/jpeg', 0.6));
      return {
        bitmap, ecken, eckenErkannt: ecken.map(e => ({ ...e })), vorschau,
        thumbUrl: URL.createObjectURL(thumbBlob),
      };
    }

    function guardsVon(seite) {
      const px = seite.ecken.map(e => ({ x: e.x * seite.bitmap.width, y: e.y * seite.bitmap.height }));
      return guards(px, seite.bitmap.width, seite.bitmap.height);
    }

    function thumbsZeichnen() {
      thumbs.innerHTML = '';
      seiten.forEach((s, i) => {
        const knopf = document.createElement('button');
        knopf.className = 'kscan-thumb' + (i === aktiv ? ' kscan-aktiv' : '')
          + (guardsVon(s).flaecheZuKlein || guardsVon(s).schief ? ' kscan-thumbwarn' : '');
        knopf.setAttribute('aria-label', `Seite ${i + 1} von ${seiten.length}`);
        knopf.innerHTML = `<img src="${s.thumbUrl}" alt="">`;
        knopf.addEventListener('click', () => { aktiv = i; zeichneAktuelleSeite(); thumbsZeichnen(); });
        thumbs.appendChild(knopf);
      });
      const plus = document.createElement('button');
      plus.className = 'kscan-plus';
      plus.setAttribute('aria-label', 'Weitere Seite fotografieren');
      plus.textContent = '+';
      plus.addEventListener('click', () => dateiEingabe.click());
      thumbs.appendChild(plus);
      primaer.disabled = !seiten.length;
      primaer.textContent = seiten.length
        ? `${seiten.length} Seite${seiten.length > 1 ? 'n' : ''} als PDF übernehmen` : 'Seiten übernehmen';
    }

    function zeichneAktuelleSeite() {
      mitte.innerHTML = '';
      if (!seiten.length) {
        titelEl.textContent = '';
        mitte.innerHTML = `<div class="kscan-leer">Keine Seite mehr vorhanden.<br>
          Über „+" unten eine Aufnahme hinzufügen.</div>`;
        overlay.classList.remove('kscan-warnt');
        return;
      }
      const s = seiten[aktiv];
      titelEl.textContent = `Seite ${aktiv + 1} von ${seiten.length}`;

      const wrap = document.createElement('div');
      wrap.className = 'kscan-bildwrap';
      const bild = document.createElement('canvas');
      bild.className = 'kscan-bild';
      bild.width = s.vorschau.width;
      bild.height = s.vorschau.height;
      bild.getContext('2d').drawImage(s.vorschau, 0, 0);
      wrap.appendChild(bild);

      const svgNS = 'http://www.w3.org/2000/svg';
      const svg = document.createElementNS(svgNS, 'svg');
      svg.setAttribute('class', 'kscan-umriss');
      svg.setAttribute('viewBox', '0 0 1 1');
      svg.setAttribute('preserveAspectRatio', 'none');
      const polygon = document.createElementNS(svgNS, 'polygon');
      svg.appendChild(polygon);
      wrap.appendChild(svg);

      const griffe = s.ecken.map((e, i) => {
        const g = document.createElement('button');
        g.className = 'kscan-griff';
        g.type = 'button';
        g.setAttribute('aria-label', ECKEN_LABEL[i]);
        wrap.appendChild(g);
        return g;
      });

      const positionieren = () => {
        polygon.setAttribute('points', s.ecken.map(e => `${e.x},${e.y}`).join(' '));
        griffe.forEach((g, i) => {
          g.style.left = (s.ecken[i].x * 100) + '%';
          g.style.top = (s.ecken[i].y * 100) + '%';
        });
        const g = guardsVon(s);
        overlay.classList.toggle('kscan-warnt', g.flaecheZuKlein || g.schief);
        let hinweis;
        if (g.flaecheZuKlein) {
          hinweis = `Nur ${Math.round(g.flaecheAnteil * 100)}% der Aufnahme erkannt — `
            + 'Ecken bitte prüfen und auf die echten Blattkanten ziehen.';
        } else if (g.schief) {
          hinweis = 'Die erkannten Ecken wirken schief oder ungleich — bitte auf die '
            + 'vier echten Blattecken ziehen.';
        } else {
          hinweis = 'Ecken stimmen? Zum Anpassen an einem Punkt ziehen.';
        }
        hinweisEl.textContent = hinweis;
        hinweisEl.classList.toggle('kscan-warn', g.flaecheZuKlein || g.schief);
      };

      griffe.forEach((g, i) => {
        g.addEventListener('pointerdown', ev => {
          ev.preventDefault();
          g.setPointerCapture(ev.pointerId);
          const bewegen = evb => {
            const rect = wrap.getBoundingClientRect();
            const x = Math.min(1, Math.max(0, (evb.clientX - rect.left) / rect.width));
            const y = Math.min(1, Math.max(0, (evb.clientY - rect.top) / rect.height));
            s.ecken[i] = { x, y };
            positionieren();
          };
          const loslassen = () => {
            g.removeEventListener('pointermove', bewegen);
            g.removeEventListener('pointerup', loslassen);
            thumbsZeichnen();
          };
          g.addEventListener('pointermove', bewegen);
          g.addEventListener('pointerup', loslassen);
        });
      });

      mitte.appendChild(wrap);
      const hinweisEl = document.createElement('div');
      hinweisEl.className = 'kscan-hinweis';
      mitte.appendChild(hinweisEl);

      const werkzeuge = document.createElement('div');
      werkzeuge.className = 'kscan-werkzeuge';
      const reset = document.createElement('button');
      reset.className = 'kscan-reset';
      reset.textContent = 'Ecken zurücksetzen';
      reset.addEventListener('click', () => {
        s.ecken = s.eckenErkannt.map(e => ({ ...e }));
        positionieren();
        thumbsZeichnen();
      });
      werkzeuge.appendChild(reset);

      // Eigener, ordentlich großer Knopf statt eines winzigen Kreuzes auf dem
      // Vorschaubildchen — ein Touch-Ziel unter 44px wäre dort unvermeidlich.
      const entfernen = document.createElement('button');
      entfernen.className = 'kscan-entfernen';
      entfernen.textContent = 'Seite entfernen';
      entfernen.addEventListener('click', () => {
        URL.revokeObjectURL(s.thumbUrl);
        s.bitmap.close?.();
        seiten.splice(aktiv, 1);
        if (aktiv >= seiten.length) aktiv = seiten.length - 1;
        zeichneAktuelleSeite();
        thumbsZeichnen();
      });
      werkzeuge.appendChild(entfernen);
      mitte.appendChild(werkzeuge);
      positionieren();
    }

    async function dateienHinzufuegen(liste) {
      const bilderNeu = Array.from(liste).filter(d => d.type.startsWith('image/'));
      for (const datei of bilderNeu) {
        seiten.push(await seiteAnlegen(datei));
      }
      aktiv = seiten.length - 1;
      zeichneAktuelleSeite();
      thumbsZeichnen();
    }

    async function fertigstellen() {
      if (!seiten.length || abgeschlossen) return;
      primaer.disabled = true;
      primaer.textContent = 'Verarbeite …';
      try {
        const ausgabe = [];
        for (const s of seiten) {
          const px = s.ecken.map(e => ({ x: e.x * s.bitmap.width, y: e.y * s.bitmap.height }));
          const { breite, hoehe } = zielGroesse(px);
          const canvas = entzerren(s.bitmap, px, breite, hoehe);
          const blob = await new Promise(r => canvas.toBlob(r, 'image/jpeg', JPEG_GUETE));
          const bytes = new Uint8Array(await blob.arrayBuffer());
          ausgabe.push({ bytes, breite, hoehe });
        }
        const pdf = bauePdf(ausgabe, optionen);
        abgeschlossen = true;
        aufraeumen();
        fertigMit({ pdf, seiten: ausgabe.length });
      } catch {
        primaer.disabled = false;
        primaer.textContent = 'Erneut versuchen';
      }
    }

    overlay.querySelector('[data-kscan="ab"]').addEventListener('click', abbrechen);
    overlay.querySelector('[data-kscan="abbrechen"]').addEventListener('click', abbrechen);
    primaer.addEventListener('click', fertigstellen);
    dateiEingabe.addEventListener('change', () => {
      // Erst kopieren, dann leeren: `.value = ''` macht sonst auch die noch
      // referenzierte (lebende) FileList leer, bevor sie gelesen wird.
      const liste = [...dateiEingabe.files];
      dateiEingabe.value = '';
      if (liste.length) dateienHinzufuegen(liste);
    });
    document.addEventListener('keydown', function escHandler(ev) {
      if (ev.key === 'Escape') { abbrechen(); }
      if (abgeschlossen) document.removeEventListener('keydown', escHandler);
    });

    dateienHinzufuegen(bilder);
  });
}
