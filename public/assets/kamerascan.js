/* Mehrseitige Belege: Rand erkennen, entzerren, zu einem PDF fügen.
 *
 * Jedes Foto kommt auf eine eigene Seite. Die Ecken werden zuerst automatisch
 * geschätzt und lassen sich an vier großen Griffen von Hand nachziehen — das
 * ist der Sicherheitsanker gegen eine falsche Erkennung, kein Nice-to-have.
 * Zwei Wächter warnen, wenn die Schätzung offensichtlich daneben liegt,
 * blockieren aber nicht: sie verhindern nur, dass ein schlechter Zuschnitt
 * stillschweigend durchgeht.
 *
 * Die Erkennung zielt auf den Normalfall „helles Blatt auf dunklem Untergrund":
 * herunterskalieren, Graustufen, Otsu-Schwelle, dunkle Einschlüsse (Text,
 * Heftklammer) auffüllen, größte zusammenhängende helle Fläche nehmen, deren
 * konvexe Hülle in vier Seiten zerlegen und die vier Kantengeraden schneiden.
 * Über die Hülle stört eine Heftklammer nicht, über die Geraden trifft es auch
 * bei leicht schiefem Blatt genau. Nur wenn das Ergebnis unplausibel ist,
 * bleibt der eingerückte Standardrahmen als ehrlicher Rückfall.
 *
 * Beim Ziehen einer Ecke blendet sich eine Lupe ein — der Finger verdeckt
 * genau die Stelle, die getroffen werden muss. Sie sitzt in der vom Finger
 * am weitesten entfernten Bildecke und weicht aus, wenn er dorthin wandert.
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
const DET_KANTE = 640;            // Kante für die Randerkennung (Downscale)
const VORSCHAU_KANTE = 1000;      // Kante für die Bildschirm-Vorschau
const MAX_KANTE = 1700;           // Kante des fertigen, entzerrten Bildes
const ERKENN_KANTE = 2200;        // Kante des JPEG für die Text-/KI-Auslese (N207)
const JPEG_GUETE = 0.72;
const MIN_HELL_ANTEIL = 0.04;     // zu wenig Kontrast -> Erkennung verworfen
const RUECKFALL_RAND = 0.04;      // eingerückter Standardrahmen
const SEITE_MIN_ANTEIL = 0.04;    // Seite ohne genug Hüllenlänge -> unsicher
const KANTE_MAX_ABWEICHUNG = 32;  // Grad: Hüllenkante zählt noch zu der Seite
const NACHZIEH_PUNKTE = 21;       // Abtastpunkte entlang jeder Seite
const NACHZIEH_RAND = 0.08;       // Anteil je Seitenende, der ausgespart bleibt (Ecken)
const NACHZIEH_SUCHE = 0.22;      // Suchradius für die Grobkorrektur, Anteil der langen Bildkante
const NACHZIEH_FENSTER = 10;      // Feinsuche quer zur Kante (Detektions-Pixel)
const NACHZIEH_SAUM = 4;          // Pixel je Seite für den „bleibt hell/dunkel"-Test
const NACHZIEH_MIN_STUFE = 10;    // Mindest-Helligkeitsstufe innen gegen außen
const QUAD_ANTEIL_MIN = 0.75;     // Viereck vs. erkannte Fläche — Plausibilität
const QUAD_ANTEIL_MAX = 1.6;
const MIN_FLAECHE_ANTEIL = 0.40;  // Wächter a) Abdeckung (N11): 51% bleibt grün, ruhiger Hinweis erst unter 40%
const SEITENVERHAELTNIS_MIN = 0.7; // Wächter b) Längenverhältnis Gegenseiten
const SEITENVERHAELTNIS_MAX = 1.4;
const WINKEL_TOLERANZ_GRAD = 15;   // Wächter b) Winkeldifferenz Gegenseiten
const A4_VERHAELTNIS = Math.SQRT2; // 1,4142 — lange durch kurze Seite
const A4_TOLERANZ = 0.12;          // wie nah an A4, um dorthin zu runden
const LUPE_KANTE = 132;            // Durchmesser der Lupe in CSS-Pixeln
const LUPE_ZOOM = 2.8;             // Vergrößerung gegenüber der Anzeige
const LUPE_RAND = 10;              // Abstand der Lupe zum Bildrand

let stilEingefuegt = false;
function stilSicherstellen() {
  if (stilEingefuegt) return;
  stilEingefuegt = true;
  const stil = document.createElement('style');
  stil.textContent = `
.kscan-overlay{position:fixed;inset:0;z-index:9000;background:rgba(15,20,22,.94);
  display:flex;flex-direction:column;height:100dvh;font-family:var(--body,sans-serif);
  color:#fff;
  /* CCCLXXXVIII — beim langsamen Ziehen einer Ecke fing iOS sonst an, Text im
     Hintergrund zu markieren (Kopieren/Nachschlagen-Menü). Im ganzen Scanner
     ist nichts zu markieren, also Auswahl und Langdruck-Menü komplett aus. */
  -webkit-user-select:none;user-select:none;-webkit-touch-callout:none}
.kscan-leer{max-width:340px;margin:auto;padding:24px;text-align:center;
  font:500 14px var(--body,sans-serif);line-height:1.6;color:#fff}
.kscan-leer b{font-weight:700}
.kscan-kopf{flex:none;display:flex;align-items:center;gap:10px;padding:12px 12px;
  padding-top:max(12px,env(safe-area-inset-top))}
.kscan-x{flex:none;width:44px;height:44px;border:none;border-radius:12px;
  background:rgba(255,255,255,.12);color:#fff;font:400 20px var(--body,sans-serif);
  cursor:pointer;display:flex;align-items:center;justify-content:center}
.kscan-x:hover{background:rgba(255,255,255,.22)}
.kscan-titel{flex:1;text-align:center;font:600 13.5px var(--disp,sans-serif);
  letter-spacing:-.01em}
.kscan-platz{flex:none;width:44px}
/* Mittiger Block, der aber nie unter die Fußzeile rutscht: die Auto-Ränder
   zentrieren bei Platz und weichen beim Überlauf dem Scrollen. */
.kscan-mitte{flex:1;min-height:0;display:flex;flex-direction:column;
  align-items:center;justify-content:flex-start;overflow-y:auto;
  padding:6px 14px;gap:10px}
.kscan-mitte>:first-child{margin-top:auto}
.kscan-mitte>:last-child{margin-bottom:auto}
.kscan-bildwrap{position:relative;max-width:100%;max-height:100%;line-height:0;
  touch-action:none;user-select:none;flex:none}
.kscan-bild{display:block;max-width:100%;max-height:calc(100dvh - 356px);
  width:auto;height:auto;border-radius:10px;background:#000}
.kscan-umriss{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}
/* Alles ausserhalb des Vierecks abdunkeln — die Kanten treten hervor, das
   Blatt selbst bleibt unangetastet hell. */
.kscan-schatten{fill:rgba(6,10,12,.66)}
.kscan-halo,.kscan-kante{fill:none;vector-effect:non-scaling-stroke;
  stroke-linejoin:round}
.kscan-halo{stroke:rgba(255,255,255,.85);stroke-width:7}
.kscan-kante{stroke:var(--teal,#0F6E5C);stroke-width:3.5}
.kscan-overlay.kscan-warnt .kscan-kante{stroke:var(--amber,#916212)}
.kscan-griff{position:absolute;width:44px;height:44px;margin:-22px 0 0 -22px;
  border:none;background:none;padding:0;cursor:grab;touch-action:none}
.kscan-griff::before,.kscan-griff::after{content:'';position:absolute;left:50%;
  top:50%;border-radius:50%;transform:translate(-50%,-50%)}
.kscan-griff::before{width:26px;height:26px;background:var(--teal,#0F6E5C);
  box-shadow:0 0 0 3px #fff,0 2px 8px rgba(0,0,0,.55)}
.kscan-griff::after{width:7px;height:7px;background:#fff}
.kscan-overlay.kscan-warnt .kscan-griff::before{background:var(--amber,#916212)}
.kscan-griff:active{cursor:grabbing}
.kscan-griff:active::before{width:30px;height:30px}
.kscan-lupe{position:absolute;left:0;top:0;width:132px;height:132px;
  border-radius:50%;background:#0B1012;pointer-events:none;display:none;z-index:2;
  box-shadow:0 0 0 2px rgba(255,255,255,.9),0 8px 22px rgba(0,0,0,.6)}
.kscan-lupe.kscan-sichtbar{display:block}
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
/* CCCLXXXVIII — Drehen links/rechts, falls das Foto quer aufgenommen wurde. */
.kscan-dreh{background:rgba(255,255,255,.12);border:none;border-radius:11px;
  color:#fff;cursor:pointer;padding:0;min-height:44px;min-width:44px;
  display:flex;align-items:center;justify-content:center}
.kscan-dreh:hover{background:rgba(255,255,255,.22)}
.kscan-dreh svg{width:22px;height:22px;display:block}
.kscan-aktionen{display:flex;gap:8px}
.kscan-aktionen button{flex:1;border:none;border-radius:12px;min-height:48px;
  font:600 14px var(--disp,sans-serif);cursor:pointer}
.kscan-ab{background:rgba(255,255,255,.1);color:#fff;flex:none;padding:0 18px}
.kscan-ab:hover{background:rgba(255,255,255,.18)}
.kscan-primaer{background:var(--teal,#0F6E5C);color:#fff}
.kscan-primaer:hover{background:var(--teal-d,#0B5548)}
.kscan-primaer[disabled]{opacity:.5;cursor:default}
@media (min-width:900px){
  .kscan-mitte{padding:14px 20px}
  .kscan-bild{max-height:calc(100dvh - 372px)}
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

/** Verkleinerte Graustufen-Maske: 1 = hell (Blatt), 0 = dunkel (Untergrund). */
function hellMaske(bitmap) {
  const faktor = Math.min(1, DET_KANTE / Math.max(bitmap.width, bitmap.height));
  const dw = Math.max(8, Math.round(bitmap.width * faktor));
  const dh = Math.max(8, Math.round(bitmap.height * faktor));
  const c = document.createElement('canvas');
  c.width = dw; c.height = dh;
  const ctx = c.getContext('2d', { willReadFrequently: true });
  ctx.drawImage(bitmap, 0, 0, dw, dh);
  const { data } = ctx.getImageData(0, 0, dw, dh);

  const grau = new Uint8Array(dw * dh);
  const hist = new Uint32Array(256);
  for (let i = 0, p = 0; i < data.length; i += 4, p++) {
    const g = (data[i] * 0.299 + data[i + 1] * 0.587 + data[i + 2] * 0.114) | 0;
    grau[p] = g;
    hist[g]++;
  }
  const schwelle = otsuSchwelle(hist, dw * dh);
  const maske = new Uint8Array(dw * dh);
  for (let p = 0; p < maske.length; p++) maske[p] = grau[p] > schwelle ? 1 : 0;
  return { maske, grau, dw, dh };
}

/** Dunkle Einschlüsse auffüllen: Text und Heftklammer liegen mitten im Blatt
    und sind vom Bildrand aus nicht erreichbar — sie gehören zur Fläche. */
function loecherFuellen(maske, dw, dh) {
  const gesehen = new Uint8Array(dw * dh);
  const stapel = new Int32Array(dw * dh);
  let oben = 0;
  const merken = p => { if (!maske[p] && !gesehen[p]) { gesehen[p] = 1; stapel[oben++] = p; } };
  for (let x = 0; x < dw; x++) { merken(x); merken((dh - 1) * dw + x); }
  for (let y = 0; y < dh; y++) { merken(y * dw); merken(y * dw + dw - 1); }
  while (oben > 0) {
    const p = stapel[--oben];
    const x = p % dw, y = (p / dw) | 0;
    if (x > 0) merken(p - 1);
    if (x < dw - 1) merken(p + 1);
    if (y > 0) merken(p - dw);
    if (y < dh - 1) merken(p + dw);
  }
  for (let p = 0; p < maske.length; p++) if (!maske[p] && !gesehen[p]) maske[p] = 1;
}

/** Zusammenhängende helle Flächen (4er-Nachbarschaft) durchnummerieren und
    die größte benennen — ein heller Fleck neben dem Blatt zählt so nicht mit. */
function groessteFlaeche(maske, dw, dh) {
  const marke = new Int32Array(dw * dh).fill(-1);
  const stapel = new Int32Array(dw * dh);
  let naechste = 0, besteMarke = -1, besteGroesse = 0;
  for (let start = 0; start < maske.length; start++) {
    if (!maske[start] || marke[start] >= 0) continue;
    let oben = 0, groesse = 0;
    marke[start] = naechste; stapel[oben++] = start;
    while (oben > 0) {
      const p = stapel[--oben];
      groesse++;
      const x = p % dw, y = (p / dw) | 0;
      if (x > 0 && maske[p - 1] && marke[p - 1] < 0) { marke[p - 1] = naechste; stapel[oben++] = p - 1; }
      if (x < dw - 1 && maske[p + 1] && marke[p + 1] < 0) { marke[p + 1] = naechste; stapel[oben++] = p + 1; }
      if (y > 0 && maske[p - dw] && marke[p - dw] < 0) { marke[p - dw] = naechste; stapel[oben++] = p - dw; }
      if (y < dh - 1 && maske[p + dw] && marke[p + dw] < 0) { marke[p + dw] = naechste; stapel[oben++] = p + dw; }
    }
    if (groesse > besteGroesse) { besteGroesse = groesse; besteMarke = naechste; }
    naechste++;
  }
  return { marke, besteMarke, besteGroesse };
}

/** Randpixel der größten Fläche — Stützpunkte für die konvexe Hülle. */
function randPunkte(marke, besteMarke, dw, dh) {
  const punkte = [];
  for (let y = 0; y < dh; y++) {
    for (let x = 0; x < dw; x++) {
      const p = y * dw + x;
      if (marke[p] !== besteMarke) continue;
      if (x === 0 || y === 0 || x === dw - 1 || y === dh - 1
        || marke[p - 1] !== besteMarke || marke[p + 1] !== besteMarke
        || marke[p - dw] !== besteMarke || marke[p + dw] !== besteMarke) {
        punkte.push([x, y]);
      }
    }
  }
  return punkte;
}

/** Konvexe Hülle (Andrew's monotone chain). Eine Heftklammer kerbt die Fläche
    ein — die Hülle überbrückt die Kerbe und stört damit nicht. */
function konvexeHuelle(punkte) {
  const p = punkte.slice().sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  if (p.length < 3) return p;
  const kreuz = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const halb = folge => {
    const aus = [];
    for (const pt of folge) {
      while (aus.length >= 2 && kreuz(aus[aus.length - 2], aus[aus.length - 1], pt) <= 0) aus.pop();
      aus.push(pt);
    }
    aus.pop();
    return aus;
  };
  return halb(p).concat(halb(p.slice().reverse()));
}

/** Lage des flächenkleinsten umschließenden Rechtecks (rotierende
    Auflagekanten) — die Bezugsrichtung, nach der die vier Seiten sortiert
    werden. Damit stimmt die Zuordnung auch bei schiefem Blatt. */
function hauptwinkel(huelle) {
  let besteFlaeche = Infinity, bester = 0;
  for (let i = 0; i < huelle.length; i++) {
    const a = huelle[i], b = huelle[(i + 1) % huelle.length];
    const w = Math.atan2(b[1] - a[1], b[0] - a[0]);
    const cos = Math.cos(w), sin = Math.sin(w);
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (const q of huelle) {
      const x = q[0] * cos + q[1] * sin, y = -q[0] * sin + q[1] * cos;
      if (x < minX) minX = x;
      if (x > maxX) maxX = x;
      if (y < minY) minY = y;
      if (y > maxY) maxY = y;
    }
    const f = (maxX - minX) * (maxY - minY);
    if (f < besteFlaeche) { besteFlaeche = f; bester = w; }
  }
  return bester;
}

/** Ausgleichsgerade durch die Hüllenkanten einer Seite. Gewichtet mit der
    Kantenlänge (Momente über das Segment), damit kurze Eckabschrägungen die
    Gerade nicht kippen. */
function seitenGeraden(huelle, winkel) {
  const rechter = Math.PI / 2;
  const grenze = KANTE_MAX_ABWEICHUNG * Math.PI / 180;
  const m = Array.from({ length: 4 },
    () => ({ l: 0, x: 0, y: 0, xx: 0, yy: 0, xy: 0 }));
  let gesamt = 0;
  for (let i = 0; i < huelle.length; i++) {
    const a = huelle[i], b = huelle[(i + 1) % huelle.length];
    const dx = b[0] - a[0], dy = b[1] - a[1];
    const laenge = Math.hypot(dx, dy);
    if (laenge < 1e-6) continue;
    gesamt += laenge;
    const roh = Math.atan2(dy, dx) - winkel;
    const viertel = Math.round(roh / rechter);
    // Kanten, die zu schräg zu ihrer Seite stehen (abgerundete Ecken), fallen raus.
    if (Math.abs(roh - viertel * rechter) > grenze) continue;
    const k = ((viertel % 4) + 4) % 4;
    const s = m[k];
    s.l += laenge;
    s.x += laenge * (a[0] + dx / 2);
    s.y += laenge * (a[1] + dy / 2);
    s.xx += laenge * (a[0] * a[0] + a[0] * dx + dx * dx / 3);
    s.yy += laenge * (a[1] * a[1] + a[1] * dy + dy * dy / 3);
    s.xy += laenge * (a[0] * a[1] + (a[0] * dy + a[1] * dx) / 2 + dx * dy / 3);
  }
  return m.map(s => {
    if (s.l <= 0 || s.l < gesamt * SEITE_MIN_ANTEIL) return null;
    const cx = s.x / s.l, cy = s.y / s.l;
    const sxx = s.xx / s.l - cx * cx, syy = s.yy / s.l - cy * cy, sxy = s.xy / s.l - cx * cy;
    const richtung = 0.5 * Math.atan2(2 * sxy, sxx - syy);
    return { px: cx, py: cy, dx: Math.cos(richtung), dy: Math.sin(richtung) };
  });
}

/** Bilinear interpolierter Grauwert — Unterpixel-Abtastung fürs Gradientenprofil. */
function grauWert(grau, dw, dh, x, y) {
  const xi = Math.min(dw - 1, Math.max(0, x));
  const yi = Math.min(dh - 1, Math.max(0, y));
  const x0 = Math.floor(xi), y0 = Math.floor(yi);
  const x1 = Math.min(dw - 1, x0 + 1), y1 = Math.min(dh - 1, y0 + 1);
  const fx = xi - x0, fy = yi - y0;
  const g00 = grau[y0 * dw + x0], g10 = grau[y0 * dw + x1];
  const g01 = grau[y1 * dw + x0], g11 = grau[y1 * dw + x1];
  return g00 * (1 - fx) * (1 - fy) + g10 * fx * (1 - fy)
       + g01 * (1 - fx) * fy + g11 * fx * fy;
}

/** Schwerpunkt der Hülle — Bezug, um bei jeder Seite "nach außen" zu wissen. */
function huellenMitte(huelle) {
  let sx = 0, sy = 0;
  for (const [x, y] of huelle) { sx += x; sy += y; }
  return [sx / huelle.length, sy / huelle.length];
}

/** Median einer Zahlenliste (verändert die Liste). Leere Liste -> null. */
function median(werte) {
  if (!werte.length) return null;
  werte.sort((a, b) => a - b);
  return werte[werte.length >> 1];
}

/** N241 — die vier Seiten robust auf den echten Blattrand nachziehen.
 *
 * Warum überhaupt: die grobe Seitengerade stammt aus der konvexen Hülle über
 * der binären Otsu-Maske. Beides ist ausreißer-empfindlich:
 *
 *  a) Liegt neben dem Blatt ein HELLERER Untergrundfleck (heller Holzstreifen,
 *     Lichtreflex) und berührt er das Blatt auch nur in wenigen Zeilen, zählt
 *     ihn Otsu als „hell" und `groessteFlaeche` schluckt ihn mit. Die konvexe
 *     Hülle beult dann auf genau dieser Seite weit nach AUSSEN aus — gemessen
 *     am echten Scan: linke Kante bis zu ~107 px zu weit außen, Ecke sogar
 *     außerhalb des Bildes.
 *  b) Läuft eine Kante im weichen Schatten aus, liegt die globale Schwelle
 *     mitten in der Rampe und die Seite rutscht nach INNEN.
 *
 * Beides trifft typischerweise nur EINE Seite — genau das gemeldete Bild.
 *
 * Gegenmittel in zwei Stufen, beide Male über den MEDIAN vieler Abtastpunkte
 * statt über Extremwerte (eine Handvoll verseuchter Zeilen kippt den Median
 * nicht, die Hülle dagegen schon):
 *
 *  1. Grob: je Abtastpunkt quer zur Seite die äußerste Stelle suchen, die noch
 *     zur erkannten Fläche gehört. Der Median dieser Randlagen ist die Kante,
 *     die die MEHRHEIT der Abtastpunkte sieht — der helle Fleck aus (a) bleibt
 *     Minderheit und fliegt raus.
 *  2. Fein: im echten Grauwertverlauf (nicht der Maske) auf die Stelle
 *     einrasten, an der es von innen nach außen HELL -> DUNKEL springt und
 *     auch dabei bleibt (`NACHZIEH_SAUM` Pixel Mittelwert je Seite). Der
 *     „bleibt dabei"-Teil ist entscheidend: eine dunkle Holzmaserung ist auf
 *     BEIDEN Seiten dunkel und erzeugt so keine Stufe, während der alte
 *     Ansatz (stärkster Einzelsprung, Betrag ohne Vorzeichen) genau darauf
 *     hereinfiel und die Kante auf die Maserung zog.
 *
 * Ist eine Stufe zu schwach oder uneindeutig, bleibt es bei Stufe 1 bzw. bei
 * der Original-Geraden — lieber grob und ehrlich als scharf und falsch.
 */
function seitenNachziehen(marke, besteMarke, grau, dw, dh, geraden, mitte, huelle) {
  const inFlaeche = (x, y) => {
    const xi = Math.round(x), yi = Math.round(y);
    if (xi < 0 || yi < 0 || xi >= dw || yi >= dh) return false;
    return marke[yi * dw + xi] === besteMarke;
  };
  const suchweite = Math.round(Math.max(dw, dh) * NACHZIEH_SUCHE);

  return geraden.map(g => {
    if (!g) return g;
    let nx = -g.dy, ny = g.dx;
    const norm = Math.hypot(nx, ny) || 1;
    nx /= norm; ny /= norm;
    // Normale nach außen drehen (weg vom Hüllenschwerpunkt) — sonst wäre
    // „außen" je nach Seite zufällig die falsche Richtung.
    if ((g.px - mitte[0]) * nx + (g.py - mitte[1]) * ny < 0) { nx = -nx; ny = -ny; }

    // Abtastpunkte nur über die tatsächliche Ausdehnung der Fläche entlang
    // dieser Seite legen — und die Enden aussparen, weil dort schon die
    // Nachbarseite quert. (Vorher spannte das Raster starr über die lange
    // Bildkante hinaus; die Hälfte der Punkte lag außerhalb des Bildes oder
    // hinter den Ecken und wurde entweder verworfen oder maß die falsche Kante.)
    let tMin = Infinity, tMax = -Infinity;
    for (const [hx, hy] of huelle) {
      const t = (hx - g.px) * g.dx + (hy - g.py) * g.dy;
      if (t < tMin) tMin = t;
      if (t > tMax) tMax = t;
    }
    if (!Number.isFinite(tMin) || tMax - tMin < 4) return g;
    const saum = (tMax - tMin) * NACHZIEH_RAND;
    tMin += saum; tMax -= saum;

    const basis = [];
    for (let i = 0; i < NACHZIEH_PUNKTE; i++) {
      const t = tMin + (tMax - tMin) * (i / (NACHZIEH_PUNKTE - 1));
      basis.push([g.px + g.dx * t, g.py + g.dy * t]);
    }

    // --- Stufe 1: je Abtastpunkt die stärkste GEHALTENE Hell/Dunkel-Stufe --
    // Nicht die Maskengrenze: die zieht ein heller Untergrundfleck mit nach
    // außen (gemessen: in ~40 % der Zeilen, damit ist auch ihr Median nicht
    // mehr zu retten). Der Grauwertverlauf dagegen zeigt am ECHTEN Blattrand
    // die mit Abstand kräftigste Stufe — Blatt gegen Tisch ist ein viel
    // größerer Sprung als heller Tisch gegen dunklen Tisch. Gemittelt über
    // `NACHZIEH_SAUM` Pixel je Seite, damit weder eine dünne Holzmaserung noch
    // eine Textzeile im Blatt als Kante durchgeht.
    const stufeBei = (bx, by, o) => {
      let innen = 0, aussen = 0;
      for (let s = 1; s <= NACHZIEH_SAUM; s++) {
        innen += grauWert(grau, dw, dh, bx + nx * (o - s + 1), by + ny * (o - s + 1));
        aussen += grauWert(grau, dw, dh, bx + nx * (o + s), by + ny * (o + s));
      }
      return (innen - aussen) / NACHZIEH_SAUM;
    };
    const grobe = [];
    for (const [bx, by] of basis) {
      let bester = null, beste = NACHZIEH_MIN_STUFE;
      for (let o = -suchweite; o <= suchweite; o++) {
        const s = stufeBei(bx, by, o);
        if (s > beste) { beste = s; bester = o + 0.5; }
      }
      if (bester !== null) grobe.push({ o: bester, x: bx + nx * bester, y: by + ny * bester });
    }
    // Reißt der Grauwert nichts her (flaues Bild), lieber die Maskengrenze als
    // gar nichts — sie ist grob, aber nie völlig aus der Luft gegriffen.
    if (grobe.length < Math.ceil(NACHZIEH_PUNKTE / 3)) {
      for (const [bx, by] of basis) {
        for (let o = suchweite; o >= -suchweite; o--) {
          if (inFlaeche(bx + nx * o, by + ny * o)) {
            grobe.push({ o, x: bx + nx * o, y: by + ny * o });
            break;
          }
        }
      }
    }
    if (grobe.length < Math.ceil(NACHZIEH_PUNKTE / 3)) return g;
    const grob = median(grobe.map(v => v.o));

    // Auch die RICHTUNG neu bestimmen, nicht nur den Abstand: eine von einem
    // hellen Fleck verbogene Hülle liefert eine schräge Seitengerade, die ein
    // reines Parallelverschieben nicht geraderücken kann (gemessen: linke
    // Kante lief 122 -> 36 px statt senkrecht bei ~107). Dafür die Randlagen,
    // die weit vom Median abweichen, per MAD aussortieren und durch den Rest
    // eine Ausgleichsgerade legen.
    const mad = median(grobe.map(v => Math.abs(v.o - grob))) || 1;
    const behalten = grobe.filter(v => Math.abs(v.o - grob) <= Math.max(3, mad * 3));
    let rx = g.dx, ry = g.dy;
    if (behalten.length >= Math.ceil(NACHZIEH_PUNKTE / 3)) {
      let sx = 0, sy = 0;
      for (const v of behalten) { sx += v.x; sy += v.y; }
      const cx = sx / behalten.length, cy = sy / behalten.length;
      let sxx = 0, syy = 0, sxy = 0;
      for (const v of behalten) {
        const ax = v.x - cx, ay = v.y - cy;
        sxx += ax * ax; syy += ay * ay; sxy += ax * ay;
      }
      const richtung = 0.5 * Math.atan2(2 * sxy, sxx - syy);
      rx = Math.cos(richtung); ry = Math.sin(richtung);
      // Laufrichtung der Seite beibehalten, sonst kippt die Seitenzuordnung.
      if (rx * g.dx + ry * g.dy < 0) { rx = -rx; ry = -ry; }
    }
    // Normale zur neuen Richtung, wieder nach außen zeigend.
    let mx = -ry, my = rx;
    if (mx * nx + my * ny < 0) { mx = -mx; my = -my; }
    nx = mx; ny = my;

    // Basispunkte auf die nachgezogene Gerade umlegen.
    const stuetze = behalten.length
      ? [behalten.reduce((s, v) => s + v.x, 0) / behalten.length,
         behalten.reduce((s, v) => s + v.y, 0) / behalten.length]
      : [g.px + nx * grob, g.py + ny * grob];
    const basis2 = basis.map(([bx, by]) => {
      const t = (bx - stuetze[0]) * rx + (by - stuetze[1]) * ry;
      return [stuetze[0] + rx * t, stuetze[1] + ry * t];
    });

    // --- Stufe 2: um die nachgezogene Gerade herum sauber einrasten --------
    // Enges Fenster: die Lage stimmt jetzt, gesucht ist nur noch das
    // Unterpixel-Feintuning entlang der bereits gefundenen Kante.
    const feine = [];
    for (const [px0, py0] of basis2) {
      let besterVersatz = null, besteStufe = NACHZIEH_MIN_STUFE;
      for (let o = -NACHZIEH_FENSTER; o <= NACHZIEH_FENSTER; o++) {
        let innen = 0, aussen = 0;
        for (let s = 1; s <= NACHZIEH_SAUM; s++) {
          innen += grauWert(grau, dw, dh, px0 + nx * (o - s + 1), py0 + ny * (o - s + 1));
          aussen += grauWert(grau, dw, dh, px0 + nx * (o + s), py0 + ny * (o + s));
        }
        const stufe = (innen - aussen) / NACHZIEH_SAUM;
        if (stufe > besteStufe) { besteStufe = stufe; besterVersatz = o + 0.5; }
      }
      if (besterVersatz !== null) feine.push(besterVersatz);
    }
    const fein = feine.length >= Math.ceil(NACHZIEH_PUNKTE / 2) ? median(feine) : 0;

    return { px: stuetze[0] + nx * fein, py: stuetze[1] + ny * fein, dx: rx, dy: ry };
  });
}

/** Schnittpunkt zweier Geraden in Punkt-Richtungs-Form. */
function geradenSchnitt(g1, g2) {
  if (!g1 || !g2) return null;
  const nenner = g1.dx * g2.dy - g1.dy * g2.dx;
  if (Math.abs(nenner) < 1e-9) return null;
  const t = ((g2.px - g1.px) * g2.dy - (g2.py - g1.py) * g2.dx) / nenner;
  const x = g1.px + t * g1.dx, y = g1.py + t * g1.dy;
  return Number.isFinite(x) && Number.isFinite(y) ? { x, y } : null;
}

/** Vier Punkte nach oben-links, oben-rechts, unten-rechts, unten-links ordnen. */
function eckenOrdnen(ecken) {
  const mx = (ecken[0].x + ecken[1].x + ecken[2].x + ecken[3].x) / 4;
  const my = (ecken[0].y + ecken[1].y + ecken[2].y + ecken[3].y) / 4;
  const reihe = ecken.slice().sort(
    (a, b) => Math.atan2(a.y - my, a.x - mx) - Math.atan2(b.y - my, b.x - mx));
  let start = 0;
  reihe.forEach((p, i) => { if (p.x + p.y < reihe[start].x + reihe[start].y) start = i; });
  return [0, 1, 2, 3].map(i => reihe[(start + i) % 4]);
}

/** Fläche eines Vierecks (Gaußsche Trapezformel). */
function vierecksFlaeche([a, b, c, d]) {
  return Math.abs((a.x * b.y - b.x * a.y) + (b.x * c.y - c.x * b.y)
    + (c.x * d.y - d.x * c.y) + (d.x * a.y - a.x * d.y)) / 2;
}

/** Konvex und nicht entartet? Sonst ist der Schnitt der Geraden misslungen. */
function istKonvex(ecken) {
  let vorzeichen = 0;
  for (let i = 0; i < 4; i++) {
    const a = ecken[i], b = ecken[(i + 1) % 4], c = ecken[(i + 2) % 4];
    const kreuz = (b.x - a.x) * (c.y - b.y) - (b.y - a.y) * (c.x - b.x);
    if (Math.abs(kreuz) < 1e-6) return false;
    const v = Math.sign(kreuz);
    if (vorzeichen === 0) vorzeichen = v;
    else if (v !== vorzeichen) return false;
  }
  return true;
}

/** Stützpunkte der Hülle in den vier Diagonalrichtungen — gröber als der
    Geradenschnitt, aber immer definiert. */
function eckenAusHuelle(huelle, winkel) {
  return eckenOrdnen([0, 1, 2, 3].map(k => {
    const r = winkel + Math.PI / 4 + k * Math.PI / 2;
    const cos = Math.cos(r), sin = Math.sin(r);
    let bester = huelle[0], wert = -Infinity;
    for (const p of huelle) {
      const s = p[0] * cos + p[1] * sin;
      if (s > wert) { wert = s; bester = p; }
    }
    return { x: bester[0], y: bester[1] };
  }));
}

const RUECKFALL_ECKEN = [
  { x: RUECKFALL_RAND, y: RUECKFALL_RAND }, { x: 1 - RUECKFALL_RAND, y: RUECKFALL_RAND },
  { x: 1 - RUECKFALL_RAND, y: 1 - RUECKFALL_RAND }, { x: RUECKFALL_RAND, y: 1 - RUECKFALL_RAND },
];

/**
 * Schätzt die vier Ecken des Dokuments, normiert auf 0..1 relativ zur
 * Bildgröße, in der Reihenfolge TL, TR, BR, BL. Bleibt die Erkennung
 * unsicher, kommt der eingerückte Standardrahmen zurück — der Nutzer zieht
 * die Ecken dann selbst auf die echten Kanten.
 */
function eckenSchaetzen(bitmap) {
  const { maske, grau, dw, dh } = hellMaske(bitmap);
  loecherFuellen(maske, dw, dh);
  const { marke, besteMarke, besteGroesse } = groessteFlaeche(maske, dw, dh);
  if (besteGroesse / (dw * dh) < MIN_HELL_ANTEIL) return RUECKFALL_ECKEN.map(e => ({ ...e }));

  const huelle = konvexeHuelle(randPunkte(marke, besteMarke, dw, dh));
  if (huelle.length < 4) return RUECKFALL_ECKEN.map(e => ({ ...e }));

  const winkel = hauptwinkel(huelle);
  const geradenRoh = seitenGeraden(huelle, winkel);
  // N241 — Seiten robust nachziehen: die konvexe Hülle folgt jedem hellen
  // Fleck neben dem Blatt, der Median vieler Abtastpunkte nicht (siehe
  // Funktionskommentar oben).
  const geraden = seitenNachziehen(marke, besteMarke, grau, dw, dh,
                                   geradenRoh, huellenMitte(huelle), huelle);
  const geschnitten = [0, 1, 2, 3].map(k => geradenSchnitt(geraden[k], geraden[(k + 1) % 4]));

  let ecken = null;
  if (geschnitten.every(Boolean)) {
    const geordnet = eckenOrdnen(geschnitten);
    const anteil = vierecksFlaeche(geordnet) / besteGroesse;
    if (istKonvex(geordnet) && anteil >= QUAD_ANTEIL_MIN && anteil <= QUAD_ANTEIL_MAX) {
      ecken = geordnet;
    }
  }
  if (!ecken) ecken = eckenAusHuelle(huelle, winkel);
  if (!istKonvex(ecken)) return RUECKFALL_ECKEN.map(e => ({ ...e }));

  const klemm = v => Math.min(1, Math.max(0, v));
  return ecken.map(p => ({ x: klemm(p.x / dw), y: klemm(p.y / dh) }));
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

/* Ein Foto in etwas Zeichenbares verwandeln — robust über die Browser hinweg.
 *
 * `createImageBitmap` ist der schnelle Weg (mit EXIF-Ausrichtung), aber iOS-
 * Safari kann die Options-Angabe `{imageOrientation}` nicht und dekodiert HEIC
 * darüber gar nicht — dann warf der Scanner still und das Overlay blieb leer.
 * Deshalb: erst mit Option, dann ohne, und als sicherer Rückfall über ein
 * <img> (das Safari inkl. HEIC lädt und EXIF-korrekt ausrichtet) auf ein
 * Canvas. Das Canvas ist überall via `drawImage` nutzbar — dieselbe Rolle wie
 * ein ImageBitmap (Breite/Höhe, zeichenbar; `.close?.()` greift ins Leere). */
export async function zuBitmap(datei) {
  if (typeof createImageBitmap === 'function') {
    try {
      return await createImageBitmap(datei, { imageOrientation: 'from-image' });
    } catch { /* Option nicht unterstützt — ohne Option weiter */ }
    try {
      return await createImageBitmap(datei);
    } catch { /* HEIC o. ä. — der <img>-Weg unten fängt es */ }
  }
  const url = URL.createObjectURL(datei);
  try {
    const img = new Image();
    img.decoding = 'async';
    await new Promise((ok, fail) => {
      img.onload = () => ok();
      img.onerror = () => fail(new Error('Das Foto ließ sich nicht laden.'));
      img.src = url;
    });
    if (img.decode) { try { await img.decode(); } catch { /* onload genügt */ } }
    const c = document.createElement('canvas');
    c.width = img.naturalWidth || img.width;
    c.height = img.naturalHeight || img.height;
    if (!c.width || !c.height) throw new Error('Das Foto ist leer.');
    c.getContext('2d').drawImage(img, 0, 0);
    return c;
  } finally {
    URL.revokeObjectURL(url);
  }
}

/* Ist die Datei ein Foto? iOS liefert manchmal einen leeren `type`; dann darf
 * die Datei nicht durchs Raster fallen. Alles außer einem PDF gilt als Bild —
 * ein PDF läuft ohne Zuschnitt durch (siehe belegscan.js). */
export function istBildDatei(datei) {
  const typ = (datei && datei.type) || '';
  if (typ === 'application/pdf') return false;
  if (typ.startsWith('image/')) return true;
  return !/\.pdf$/i.test((datei && datei.name) || '');
}

/* N207 — ein Kamerafoto in ein Format bringen, das der Server auch LESEN kann.
 *
 * iOS liefert für Kamerafotos oft HEIC oder einen leeren `type`. Die
 * serverseitige Texterkennung (tesseract/leptonica) kann HEIC nicht dekodieren,
 * und die KI-Auslese arbeitet auf diesem OCR-Text — also blieb bei einem HEIC
 * beides stumm: kein Text, kein Betrag, und die Erkennungs-/Bestätigungs-Maske
 * ging gar nicht erst auf. Das Overlay dekodiert dasselbe Foto längst iOS-fest
 * (`zuBitmap`, inkl. <img>-Rückfall für HEIC); die Erkennung umging das bisher
 * und schickte die Rohdatei.
 *
 * Deshalb hier: über denselben iOS-festen Weg dekodieren, auf ein Canvas zeichnen
 * (auf `ERKENN_KANTE` begrenzt, damit der Upload schlank bleibt und die OCR noch
 * genug Auflösung hat) und als JPEG neu kodieren. Ein PDF und alles, was kein
 * Bild ist, bleibt unangetastet — dort gibt es nichts umzuwandeln. Schlägt die
 * Umwandlung fehl, kommt die Originaldatei zurück: die Erkennung darf nie einen
 * Beleg aufhalten. */
export async function fotoAlsJpeg(datei) {
  if (!datei || !istBildDatei(datei)) return datei;      // PDF/kein Bild: unverändert
  try {
    const bitmap = await zuBitmap(datei);
    const faktor = Math.min(1, ERKENN_KANTE / Math.max(bitmap.width, bitmap.height));
    const c = document.createElement('canvas');
    c.width = Math.max(1, Math.round(bitmap.width * faktor));
    c.height = Math.max(1, Math.round(bitmap.height * faktor));
    c.getContext('2d').drawImage(bitmap, 0, 0, c.width, c.height);
    bitmap.close?.();
    const blob = await new Promise(r => c.toBlob(r, 'image/jpeg', 0.92));
    if (!blob) return datei;
    const stamm = (datei.name || 'foto').replace(/\.[^.]*$/, '') || 'foto';
    return new File([blob], `${stamm}.jpg`, {
      type: 'image/jpeg', lastModified: datei.lastModified || Date.now() });
  } catch {
    return datei;                                        // lieber das Original als nichts
  }
}

/**
 * Öffnet die Bearbeitung für eine Reihe frisch aufgenommener Fotos.
 * Löst mit `{ pdf, seiten }` auf (gleiche Form wie `scanZuPdf`), oder mit
 * `null`, wenn abgebrochen wurde.
 */
export function kamerascanStarten(dateien, optionen = {}) {
  stilSicherstellen();
  const bilder = Array.from(dateien).filter(istBildDatei);
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
      const bitmap = await zuBitmap(datei);
      const ecken = eckenSchaetzen(bitmap);
      const vorschau = await vorschauCanvas(bitmap);
      const thumbBlob = await new Promise(r => vorschau.toBlob(r, 'image/jpeg', 0.6));
      return {
        bitmap, ecken, eckenErkannt: ecken.map(e => ({ ...e })), vorschau,
        thumbUrl: URL.createObjectURL(thumbBlob),
      };
    }

    /* CCCLXXXVIII — die Aufnahme um 90° drehen (quer gehaltenes Handy). Die
       EXIF-Orientierung greift schon beim Laden; das hier ist der manuelle Weg,
       wenn kein Tag da ist oder das Blatt quer liegt. */
    async function bitmapDrehen(bitmap, gegenUhrzeiger) {
      const c = document.createElement('canvas');
      c.width = bitmap.height;
      c.height = bitmap.width;
      const x = c.getContext('2d');
      if (gegenUhrzeiger) { x.translate(0, c.height); x.rotate(-Math.PI / 2); }
      else { x.translate(c.width, 0); x.rotate(Math.PI / 2); }
      x.drawImage(bitmap, 0, 0);
      // Das Canvas direkt zurückgeben — überall via drawImage nutzbar und ohne
      // Abhängigkeit von createImageBitmap (das iOS-Safari nicht immer kann).
      return c;
    }

    // CD — die vier Ecken (normalisiert, Reihenfolge TL,TR,BR,BL) 90° mitdrehen,
    // damit eine Drehung die schon korrigierten Ecken NICHT verwirft. Im/Gegen den
    // Uhrzeigersinn dreht jede Rolle um eine Position weiter, darum wird das Array
    // passend rotiert.
    const eckenMitdrehen = (ecken, gegen) => {
      const t = gegen
        ? e => ({ x: e.y, y: 1 - e.x })       // gegen den Uhrzeigersinn
        : e => ({ x: 1 - e.y, y: e.x });      // im Uhrzeigersinn
      const g = ecken.map(t);
      return gegen ? [g[1], g[2], g[3], g[0]] : [g[3], g[0], g[1], g[2]];
    };

    async function dreheSeite(gegenUhrzeiger) {
      const s = seiten[aktiv];
      if (!s) return;
      const neu = await bitmapDrehen(s.bitmap, gegenUhrzeiger);
      s.bitmap.close?.();
      URL.revokeObjectURL(s.thumbUrl);
      s.bitmap = neu;
      // Korrigierte Ecken bleiben erhalten — mitgedreht statt neu geschätzt.
      s.ecken = eckenMitdrehen(s.ecken, gegenUhrzeiger);
      s.eckenErkannt = eckenMitdrehen(s.eckenErkannt, gegenUhrzeiger);
      s.vorschau = await vorschauCanvas(neu);
      const thumbBlob = await new Promise(r => s.vorschau.toBlob(r, 'image/jpeg', 0.6));
      s.thumbUrl = URL.createObjectURL(thumbBlob);
      zeichneAktuelleSeite();
      thumbsZeichnen();
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
      // Drei Lagen: abgedunkelter Aussenbereich, weisser Saum, farbige Kante.
      const schatten = document.createElementNS(svgNS, 'path');
      schatten.setAttribute('class', 'kscan-schatten');
      schatten.setAttribute('fill-rule', 'evenodd');
      const halo = document.createElementNS(svgNS, 'polygon');
      halo.setAttribute('class', 'kscan-halo');
      const kante = document.createElementNS(svgNS, 'polygon');
      kante.setAttribute('class', 'kscan-kante');
      svg.append(schatten, halo, kante);
      wrap.appendChild(svg);

      const griffe = s.ecken.map((e, i) => {
        const g = document.createElement('button');
        g.className = 'kscan-griff';
        g.type = 'button';
        g.setAttribute('aria-label', ECKEN_LABEL[i]);
        wrap.appendChild(g);
        return g;
      });

      const lupe = document.createElement('canvas');
      lupe.className = 'kscan-lupe';
      lupe.setAttribute('aria-hidden', 'true');
      const lupeDicht = Math.min(3, window.devicePixelRatio || 1);
      const lupeSeite = Math.round(LUPE_KANTE * lupeDicht);
      lupe.width = lupeSeite;
      lupe.height = lupeSeite;
      const lupeCtx = lupe.getContext('2d');
      wrap.appendChild(lupe);
      let lupePlatz = null;

      const positionieren = () => {
        const punkte = s.ecken.map(e => `${e.x},${e.y}`).join(' ');
        halo.setAttribute('points', punkte);
        kante.setAttribute('points', punkte);
        schatten.setAttribute('d', `M0,0 H1 V1 H0 Z M${s.ecken.map(e => `${e.x},${e.y}`).join(' L')} Z`);
        griffe.forEach((g, i) => {
          g.style.left = (s.ecken[i].x * 100) + '%';
          g.style.top = (s.ecken[i].y * 100) + '%';
        });
        const g = guardsVon(s);
        overlay.classList.toggle('kscan-warnt', g.flaecheZuKlein || g.schief);
        let hinweis;
        if (g.flaecheZuKlein) {
          hinweis = 'Foto bitte näher aufnehmen für bessere Qualität '
            + `(nur ${Math.round(g.flaecheAnteil * 100)}% der Aufnahme erkannt).`;
        } else if (g.schief) {
          hinweis = 'Die erkannten Ecken wirken schief oder ungleich — bitte auf die '
            + 'vier echten Blattecken ziehen.';
        } else {
          hinweis = 'Ecken stimmen? Zum Anpassen an einem Punkt ziehen.';
        }
        hinweisEl.textContent = hinweis;
        hinweisEl.classList.toggle('kscan-warn', g.flaecheZuKlein || g.schief);
      };

      // Die Lupe zeigt den Bildausschnitt unter dem Finger vergrößert, mit
      // Fadenkreuz auf dem Eckpunkt und den beiden anliegenden Kanten.
      const lupeZeichnen = (i, rect) => {
        const g = lupeSeite, m = g / 2;
        const zoom = LUPE_ZOOM * lupeDicht;
        const ziel = s.ecken[i];
        const proAnzeige = s.bitmap.width / rect.width;   // Bitmap- je Anzeige-Pixel
        const halb = (m / zoom) * proAnzeige;
        // CCCXCIX — den Quell-Ausschnitt INS Bitmap klemmen: liegt die Ecke am
        // Bildrand, ragte er sonst hinaus und die Lupe wurde großflächig schwarz.
        // Jetzt „pant" die Lupe am Rand (zeigt weiter Bild), das Fadenkreuz sitzt
        // trotzdem auf der echten Ecke (cx/cy statt fix Mitte).
        const bw = s.bitmap.width, bh = s.bitmap.height;
        const sw = Math.min(halb * 2, bw), sh = Math.min(halb * 2, bh);
        const sx = Math.max(0, Math.min(ziel.x * bw - halb, bw - sw));
        const sy = Math.max(0, Math.min(ziel.y * bh - halb, bh - sh));
        lupeCtx.setTransform(1, 0, 0, 1, 0, 0);
        lupeCtx.fillStyle = '#0B1012';
        lupeCtx.fillRect(0, 0, g, g);
        lupeCtx.drawImage(s.bitmap, sx, sy, sw, sh, 0, 0, g, g);
        const skalaX = g / sw, skalaY = g / sh;
        const cx = (ziel.x * bw - sx) * skalaX;   // Position der Ecke in der Lupe
        const cy = (ziel.y * bh - sy) * skalaY;

        const zuLupe = p => ({
          x: cx + (p.x - ziel.x) * bw * skalaX,
          y: cy + (p.y - ziel.y) * bh * skalaY,
        });
        const davor = zuLupe(s.ecken[(i + 3) % 4]);
        const danach = zuLupe(s.ecken[(i + 1) % 4]);
        lupeCtx.lineJoin = 'round';
        lupeCtx.lineCap = 'round';
        for (const [farbe, breite] of [['rgba(255,255,255,.85)', 7], [getComputedStyle(kante).stroke, 3.5]]) {
          lupeCtx.strokeStyle = farbe;
          lupeCtx.lineWidth = breite * lupeDicht;
          lupeCtx.beginPath();
          lupeCtx.moveTo(davor.x, davor.y);
          lupeCtx.lineTo(cx, cy);
          lupeCtx.lineTo(danach.x, danach.y);
          lupeCtx.stroke();
        }

        // Fadenkreuz doppelt: dunkel unterlegt, damit es auch auf dem hellen
        // Blatt steht.
        const luecke = 6 * lupeDicht, arm = 22 * lupeDicht;
        const kreuz = () => {
          lupeCtx.beginPath();
          for (const [dx, dy] of [[-1, 0], [1, 0], [0, -1], [0, 1]]) {
            lupeCtx.moveTo(cx + dx * luecke, cy + dy * luecke);
            lupeCtx.lineTo(cx + dx * arm, cy + dy * arm);
          }
          lupeCtx.moveTo(cx + luecke, cy);
          lupeCtx.arc(cx, cy, luecke, 0, Math.PI * 2);
          lupeCtx.stroke();
        };
        lupeCtx.strokeStyle = 'rgba(10,14,16,.55)';
        lupeCtx.lineWidth = 4 * lupeDicht;
        kreuz();
        lupeCtx.strokeStyle = '#fff';
        lupeCtx.lineWidth = 1.6 * lupeDicht;
        kreuz();
      };

      // Die Lupe darf nie unter dem Finger sitzen: sie geht in die entfernteste
      // Bildecke und wechselt erst, wenn der Finger ihr zu nahe kommt.
      const lupeSetzen = (fx, fy, rect) => {
        const links = Math.max(0, rect.width - LUPE_KANTE - LUPE_RAND);
        const unten = Math.max(0, rect.height - LUPE_KANTE - LUPE_RAND);
        const plaetze = [[LUPE_RAND, LUPE_RAND], [links, LUPE_RAND], [links, unten], [LUPE_RAND, unten]];
        const abstand = ([px, py]) => Math.hypot(fx - (px + LUPE_KANTE / 2), fy - (py + LUPE_KANTE / 2));
        if (lupePlatz === null || abstand(plaetze[lupePlatz]) < LUPE_KANTE * 0.9) {
          let beste = 0;
          plaetze.forEach((p, k) => { if (abstand(p) > abstand(plaetze[beste])) beste = k; });
          lupePlatz = beste;
        }
        lupe.style.left = plaetze[lupePlatz][0] + 'px';
        lupe.style.top = plaetze[lupePlatz][1] + 'px';
      };

      griffe.forEach((g, i) => {
        g.addEventListener('pointerdown', ev => {
          ev.preventDefault();
          try { g.setPointerCapture(ev.pointerId); } catch { /* ohne Capture weiter */ }
          const start = wrap.getBoundingClientRect();
          lupePlatz = null;
          lupe.classList.add('kscan-sichtbar');
          lupeSetzen(ev.clientX - start.left, ev.clientY - start.top, start);
          lupeZeichnen(i, start);
          const bewegen = evb => {
            const rect = wrap.getBoundingClientRect();
            const fx = evb.clientX - rect.left, fy = evb.clientY - rect.top;
            s.ecken[i] = {
              x: Math.min(1, Math.max(0, fx / rect.width)),
              y: Math.min(1, Math.max(0, fy / rect.height)),
            };
            positionieren();
            lupeSetzen(fx, fy, rect);
            lupeZeichnen(i, rect);
          };
          const loslassen = () => {
            g.removeEventListener('pointermove', bewegen);
            g.removeEventListener('pointerup', loslassen);
            g.removeEventListener('pointercancel', loslassen);
            lupe.classList.remove('kscan-sichtbar');
            thumbsZeichnen();
          };
          g.addEventListener('pointermove', bewegen);
          g.addEventListener('pointerup', loslassen);
          g.addEventListener('pointercancel', loslassen);
        });
      });

      mitte.appendChild(wrap);
      const hinweisEl = document.createElement('div');
      hinweisEl.className = 'kscan-hinweis';
      mitte.appendChild(hinweisEl);

      const werkzeuge = document.createElement('div');
      werkzeuge.className = 'kscan-werkzeuge';
      // CCCLXXXVIII — links/rechts drehen, wenn die Aufnahme quer liegt.
      const drehIcon = pfad => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
        stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${pfad}</svg>`;
      const drehL = document.createElement('button');
      drehL.className = 'kscan-dreh';
      drehL.setAttribute('aria-label', 'Nach links drehen');
      drehL.title = 'Nach links drehen';
      drehL.innerHTML = drehIcon('<polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/>');
      drehL.addEventListener('click', () => dreheSeite(true));
      werkzeuge.appendChild(drehL);
      const drehR = document.createElement('button');
      drehR.className = 'kscan-dreh';
      drehR.setAttribute('aria-label', 'Nach rechts drehen');
      drehR.title = 'Nach rechts drehen';
      drehR.innerHTML = drehIcon('<polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>');
      drehR.addEventListener('click', () => dreheSeite(false));
      werkzeuge.appendChild(drehR);
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
      const bilderNeu = Array.from(liste).filter(istBildDatei);
      let fehlgeschlagen = 0;
      for (const datei of bilderNeu) {
        try {
          seiten.push(await seiteAnlegen(datei));
        } catch {
          fehlgeschlagen++;         // ein kaputtes Foto blockiert nicht den Rest
        }
      }
      if (!seiten.length) {
        // Nichts ließ sich laden — statt eines leeren, „kaputten" Overlays ein
        // klarer Hinweis (statt stillem Nichts wie bisher auf iOS).
        mitte.innerHTML = `<div class="kscan-leer">Das Foto ließ sich nicht
          öffnen.<br>Bitte erneut aufnehmen. Falls es weiter klemmt: am iPhone
          unter <b>Einstellungen → Kamera → Formate</b> „Maximale Kompatibilität"
          wählen (JPEG statt HEIC).</div>`;
        primaer.disabled = true;
        return;
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
        // N250 — die entzerrten Seiten zusätzlich als Bilder herausgeben. Die
        // Bestätigungsmaske zeigt damit genau das, was gleich abgelegt wird,
        // ohne das PDF im Browser rendern zu müssen (dafür gäbe es hier keine
        // Bibliothek). Rein additiv: wer nur `pdf`/`seiten` liest, merkt nichts.
        const bilder = ausgabe.map(a =>
          new Blob([a.bytes], { type: 'image/jpeg' }));
        fertigMit({ pdf, seiten: ausgabe.length, bilder });
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
