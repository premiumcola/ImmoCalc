/* N200 — die Amortisation nach Kategorien: ein Ringdiagramm neben der Kurve
   und die Prozent-Aufteilung darunter.

   Der Ring zeigt die KILOWATTSTUNDEN je Kategorie (die Flaeche), seine
   Legende das €, das jede eingebracht hat. Genau darin sitzt die Aussage,
   um die es dem Nutzer geht: die Netz-Einspeisung ist ein groszer kWh-Kuchen
   mit kleinem €, Direktnutzung und E-Tanken sind kleinere Stuecke mit
   deutlich mehr € je kWh.

   Alles Inline-SVG, keine Bibliothek — wie der Rest der Seite. Umzug ohne
   Verhaltensaenderung. */
import { esc, eur } from '../immo.js';
import { kwh0, proz1, satzKwh } from './helpers.js';
import { C_DIREKT, C_EINSP, C_TANK } from './farben.js';

const KAT_FARBE = { pv_strom: C_DIREKT, einspeisung: 'url(#kringelSchraffur)',
                    tanken: C_TANK };

/* Ein Farbchip je Kategorie mit einer Basisklasse. Die Einspeisung traegt
   die Schraffur (wie in der Kurven-Legende), die beiden anderen ihren
   Vollton — `class` und Schraffur in EINEM Attribut, sonst schluckt der
   Browser das zweite. */
export function katChip(feld, basis) {
  if (feld === 'einspeisung') return `class="${basis} schraffur"`;
  return `class="${basis}" style="background:${
    feld === 'tanken' ? C_TANK : C_DIREKT}"`;
}

/* Ein Ringsegment als Pfad — Auszen- und Innenbogen, im Uhrzeigersinn. */
function ringSegment(cx, cy, ra, ri, a0, a1) {
  const pt = (r, a) => [cx + r * Math.cos(a), cy + r * Math.sin(a)];
  const gross = a1 - a0 > Math.PI ? 1 : 0;
  const [x0, y0] = pt(ra, a0), [x1, y1] = pt(ra, a1);
  const [x2, y2] = pt(ri, a1), [x3, y3] = pt(ri, a0);
  const f = n => n.toFixed(2);
  return `M${f(x0)} ${f(y0)} A${ra} ${ra} 0 ${gross} 1 ${f(x1)} ${f(y1)}`
    + ` L${f(x2)} ${f(y2)} A${ri} ${ri} 0 ${gross} 0 ${f(x3)} ${f(y3)} Z`;
}

/* Das Ringdiagramm: kWh-Anteile als Segmente, in der Mitte die
   Gesamtmenge. */
function kringelSvg(cats, gesamtKwh) {
  const B = 200, cx = 100, cy = 100, ra = 92, ri = 56;
  const total = cats.reduce((s, p) => s + p.kwh, 0);
  if (total <= 0) return '';
  const luecke = cats.length > 1 ? 0.045 : 0;   // kleiner Spalt je Segment
  let a = -Math.PI / 2, segmente = '';
  cats.forEach(p => {
    const spanne = (p.kwh / total) * (Math.PI * 2);
    const a0 = a + luecke / 2, a1 = a + spanne - luecke / 2;
    if (a1 > a0) {
      segmente += `<path d="${ringSegment(cx, cy, ra, ri, a0, a1)}"
        fill="${KAT_FARBE[p.feld]}" stroke="var(--sheet)" stroke-width="2"/>`;
    }
    a += spanne;
  });
  return `<svg viewBox="0 0 ${B} ${B}" class="kringel" role="img"
      aria-label="Geladene und erzeugte kWh je Kategorie">
    <defs><pattern id="kringelSchraffur" width="6" height="6"
        patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
      <rect width="6" height="6" fill="${C_EINSP}"/>
      <line x1="0" y1="0" x2="0" y2="6" stroke="#FFF" stroke-width="2.4"
            stroke-opacity=".8"/></pattern></defs>
    ${segmente}
    <text x="${cx}" y="${cy - 2}" class="km-z">${
      gesamtKwh == null ? '—' : Math.round(gesamtKwh).toLocaleString('de-DE')}</text>
    <text x="${cx}" y="${cy + 12}" class="km-l">KWH GESAMT</text>
  </svg>`;
}

/* Der Ring plus seine Legende: je Kategorie das €, darunter kWh und €/kWh. */
export function kringel(kat) {
  const cats = (kat.posten || []).filter(p => p.kwh && p.kwh > 0);
  if (!cats.length) return '';
  const legende = cats.map(p => `
    <div class="kz">
      <div class="kzt"><i ${katChip(p.feld, 'ki')}></i>
        <span class="kn">${esc(p.label)}</span>
        <b class="kv">${eur(p.eur)}</b></div>
      <span class="ksub">${kwh0(p.kwh)}${
        p.eur_pro_kwh != null ? ` · ${satzKwh(p.eur_pro_kwh)}` : ''}</span>
    </div>`).join('');
  return `<div class="vk-ring">
    <span class="rt">kWh je Kategorie · was jede einbrachte</span>
    ${kringelSvg(cats, kat.gesamt_kwh)}
    <div class="kleg">${legende}</div>
  </div>`;
}

/* Point 2 — woraus sich die Amortisation zusammensetzt: der €-Anteil je
   Kategorie in Prozent, mit kWh und € darunter. Der Balken ist der
   €-Anteil. */
export function katAnteil(kat) {
  const posten = (kat.posten || []).filter(p => p.eur > 0 || (p.kwh && p.kwh > 0));
  if (!posten.length || !(kat.gesamt_eur > 0)) return '';
  const zeilen = posten.map(p => {
    const breite = kat.gesamt_eur > 0
      ? Math.max(0, Math.min(100, p.eur / kat.gesamt_eur * 100)) : 0;
    const fuell = p.feld === 'einspeisung'
      ? `background:repeating-linear-gradient(45deg,${C_EINSP} 0 3px,#FFF 3px 5px)`
      : `background:${p.feld === 'tanken' ? C_TANK : C_DIREKT}`;
    const meta = [p.kwh ? `<b>${kwh0(p.kwh)}</b>` : null,
                  `<b>${eur(p.eur)}</b>`,
                  p.eur_pro_kwh != null ? satzKwh(p.eur_pro_kwh) : null]
      .filter(Boolean).join(' · ');
    return `<div class="katzeile">
      <div class="kk">
        <span class="kl"><i ${katChip(p.feld, '')}></i>${esc(p.label)}</span>
        <span class="kp">${proz1(p.prozent)}</span>
      </div>
      <div class="kbar"><i style="width:${breite.toFixed(1)}%;${fuell}"></i></div>
      <div class="kmeta">${meta}</div>
    </div>`;
  }).join('');
  // Der eine Satz, der die Aussage benennt — nur, wenn die Einspeisung
  // wirklich viele kWh zu wenig € beisteuert (sonst behauptet er etwas
  // Ungeprueftes).
  const einsp = posten.find(p => p.feld === 'einspeisung');
  const tank = posten.find(p => p.feld === 'tanken');
  const note = (einsp && tank && einsp.eur_pro_kwh != null
    && tank.eur_pro_kwh != null && einsp.eur_pro_kwh < tank.eur_pro_kwh)
    ? `<p class="katnote">Die Netz-Einspeisung bringt viele Kilowattstunden zu
       wenigen Cent (${satzKwh(einsp.eur_pro_kwh)}); Direktnutzung und E-Tanken
       tragen weniger kWh, aber deutlich mehr € je kWh
       (E-Tanken ${satzKwh(tank.eur_pro_kwh)}).</p>` : '';
  return `<div class="katanteil">
    <span class="kt">Woraus sich die Amortisation zusammensetzt</span>
    ${zeilen}${note}</div>`;
}
