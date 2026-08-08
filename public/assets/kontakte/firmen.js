/* N309f — die Firmensicht des Kontaktbuchs: alle Kontakte, gruppiert nach Art
   (Handwerker, Versicherung, Bank, Versorger …). Reines HTML-Bauen; geklickt
   wird in kontakte.html, gespeichert in blatt.js. */

import { esc } from '../immo.js';
import { gewerkIcon, gewerkSymbol } from '../gewerkicons.js';

/* Wege zur Firma. Flache Strichzeichnungen im Projektstil, `currentColor` —
   die Farbe kommt vom Chip. Sie stehen hier und nicht in gewerkicons.js:
   dort wohnen die Gewerke, das hier sind Kontaktwege. */
const STRICH = 'fill="none" stroke="currentColor" stroke-width="1.7" '
  + 'stroke-linecap="round" stroke-linejoin="round"';

const WEG_SVG = {
  telefon: `<path ${STRICH} d="M6.5 3.5h3l1.3 3.4-1.9 1.4a11 11 0 0 0 4.8 4.8l1.4-1.9
            3.4 1.3v3a2 2 0 0 1-2.2 2A15.5 15.5 0 0 1 4.5 5.7a2 2 0 0 1 2-2.2Z"/>`,
  email: `<rect ${STRICH} x="3.2" y="5.4" width="17.6" height="13.2" rx="2.4"/>
          <path ${STRICH} d="m4.2 7 7.8 5.6L19.8 7"/>`,
  // Die Weltkugel: Kreis, Äquator, Meridian — drei getrennte Pfade, damit
  // kein Bogen mitten in einem `d`-Attribut untergeht.
  web: `<circle ${STRICH} cx="12" cy="12" r="8.4"/>
        <path ${STRICH} d="M3.6 12h16.8"/>
        <path ${STRICH} d="M12 3.6c2.4 2.6 3.6 5.4 3.6 8.4s-1.2 5.8-3.6 8.4
                           c-2.4-2.6-3.6-5.4-3.6-8.4S9.6 6.2 12 3.6Z"/>`,
};

const wegIcon = (art, groesse = 15) =>
  `<svg class="wi" width="${groesse}" height="${groesse}" viewBox="0 0 24 24"
        aria-hidden="true">${WEG_SVG[art] || ''}</svg>`;

/* Rechtsformen tragen nichts zum Kürzel bei — „WWK Allgemeine Versicherung AG"
   soll „WA" ergeben, nicht „WG". */
const FUELLWORT = new Set(['gmbh', 'ag', 'kg', 'co', 'mbh', 'ohg', 'gbr', 'ug',
  'e', 'k', 'und', 'the', 'se']);

/** Kürzel aus dem Firmennamen: „N. Liebel GmbH" → „NL", „Sparkasse" → „Sp". */
export function monogramm(firma) {
  const worte = String(firma || '').split(/[^\p{L}\p{N}]+/u)
    .filter(w => w && !FUELLWORT.has(w.toLowerCase()));
  if (!worte.length) return '?';
  if (worte.length === 1) return worte[0].slice(0, 2).toUpperCase();
  return (worte[0][0] + worte[1][0]).toUpperCase();
}

/**
 * Das Zeichen der Firma. Ein bekanntes Gewerk gibt sein Symbol; sonst wird der
 * Firmenname befragt („Fliesen-Neuner" ist erkennbar ein Fliesenleger), und
 * erst wenn auch das nichts hergibt, steht das Kürzel da. Ein Schrauben-
 * schlüssel über einer Bank wäre schlicht falsch.
 */
export function kontaktZeichen(k) {
  const symbol = gewerkSymbol(k.gewerk || k.firma);
  return symbol === 'sonstiges'
    ? `<span class="mono">${esc(monogramm(k.firma))}</span>`
    : gewerkIcon(k.gewerk || k.firma, 'gi', 22);
}

/* ---- Kontaktwege als Chips --------------------------------------------- */

const TELEFON_LINK = t => `tel:${String(t).replace(/[^\d+]/g, '')}`;
const WEB_LINK = w => (/^https?:/i.test(w) ? w : `https://${w}`);

function wegeHtml(k) {
  const chips = [];
  const vorhanden = (art, text, href) => chips.push(
    `<a class="weg an" href="${esc(href)}" ${art === 'web'
      ? 'target="_blank" rel="noopener"' : ''} data-halt
       title="${esc(text)}">${wegIcon(art)}<span>${esc(text)}</span></a>`);

  if (k.telefon) vorhanden('telefon', k.telefon, TELEFON_LINK(k.telefon));
  if (k.email) vorhanden('email', k.email, `mailto:${k.email}`);
  // Angezeigt wird die nackte Adresse (ohne https:// und www.) — verlinkt
  // bleibt die vollständige.
  if (k.web) {
    vorhanden('web', k.web.replace(/^https?:\/\//i, '').replace(/^www\./i, ''),
              WEB_LINK(k.web));
  }
  // Was fehlt, ist kein Warnhinweis, sondern der Weg zum Beheben: derselbe
  // Chip in leiser Umrisslinie öffnet das Kontaktblatt beim richtigen Feld.
  // Beschriftung bewusst kurz — das „＋" sagt schon, was passiert.
  for (const feld of (k.fehlt || [])) {
    chips.push(`<button class="weg fehlt" type="button" data-kontakt="${k.id}"
        data-feld="${esc(feld)}" title="${
        feld === 'telefon' ? 'Telefonnummer' : 'E-Mail-Adresse'} eintragen"
        >${wegIcon(feld)}<span>＋ ${
        feld === 'telefon' ? 'Telefon' : 'E-Mail'}</span></button>`);
  }
  return chips.join('');
}

/* Drei Darlehen derselben Bank zur selben Wohnung sind nicht dreimal
   „DARLEHENSNUMMER · Wohnung 1.OG": Art und Immobilie stehen einmal als
   Überschrift, darunter die Nummern (roter Faden 3). */
function nummernHtml(k) {
  if (!k.nummern?.length) return '';
  const gruppen = new Map();
  for (const n of k.nummern) {
    const art = n.art || 'Kundennummer';
    const objekt = n.objekt_name || '';
    const schluessel = `${art}|${objekt}`;
    if (!gruppen.has(schluessel)) gruppen.set(schluessel, { art, objekt, werte: [] });
    gruppen.get(schluessel).werte.push(n.nummer);
  }
  const bloecke = [...gruppen.values()].map(g => `<div class="knr">
      <span class="knrkopf"><i>${esc(g.art)}</i>${
        g.objekt ? `<em>${esc(g.objekt)}</em>` : ''}</span>
      <span class="knrwerte">${g.werte.map(w => `<b>${esc(w)}</b>`).join('')}</span>
    </div>`).join('');
  return `<div class="knrn">${bloecke}</div>`;
}

/** Eine Kontaktkarte. Der Kopf ist der Knopf ins Kontaktblatt. */
export function karteHtml(k) {
  return `<article class="kkarte">
      <button class="kkopf" type="button" data-kontakt="${k.id}">
        <span class="kikon">${kontaktZeichen(k)}</span>
        <span class="ktext">
          <span class="kname">${esc(k.firma)}</span>
          ${k.gewerk ? `<span class="kgw">${esc(k.gewerk)}</span>` : ''}
        </span>
        <span class="kpfeil" aria-hidden="true">›</span>
      </button>
      <div class="kwege">${wegeHtml(k)}</div>
      ${nummernHtml(k)}
    </article>`;
}

/* ---- Die ganze Sicht ---------------------------------------------------- */

/** „Sonstiges" ans Ende — es ist der Rest, nicht der Anfang. */
function artenReihenfolge(kontakte) {
  const gesehen = [];
  for (const k of kontakte) {
    const art = k.art || 'Sonstiges';
    if (!gesehen.includes(art)) gesehen.push(art);
  }
  return gesehen.sort((a, b) => (a === 'Sonstiges') - (b === 'Sonstiges'));
}

/** Alle Kontakte, nach Art gruppiert. */
export function firmenHtml(kontakte) {
  const teile = [];
  for (const art of artenReihenfolge(kontakte)) {
    const gruppe = kontakte.filter(k => (k.art || 'Sonstiges') === art);
    teile.push(`<h2 class="gruppe">${esc(art)}
        <span class="anzahl">${gruppe.length}</span></h2>
      <div class="kraster">${gruppe.map(karteHtml).join('')}</div>`);
  }
  return teile.join('');
}
