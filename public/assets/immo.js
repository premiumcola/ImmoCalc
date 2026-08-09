/* ImmoCalc — gemeinsame Bausteine: Logo-Sprites, API-Zugriff, Formatierung.
   Wird von allen Seiten geladen; die Sprites werden einmal ins Dokument
   gehaengt, statt sie in jeder Datei zu wiederholen. */

// Das Grundstueck kam spaeter dazu und liegt bei den uebrigen Grundstuecks-
// Symbolen. Importiert statt kopiert — zwei Fassungen desselben Logos wuerden
// frueher oder later auseinanderlaufen.
import { GRUNDSTUECK_LOGO, GRUNDSTUECK_SPRITE } from './kostenicons.js';
// N286 — der Ordner-Umzugs-Dialog im Beleg-Fenster braucht dasselbe
// Auswahlfeld wie der Rest der App statt eines nativen <select>.
import { auswahlfeld } from './auswahl.js';

// N18 — Datumsfelder: den Kalender öffnet der Klick aufs SYMBOL rechts (die
// klickbare, transparente Picker-Indicator-Fläche aus immo.css). Der Textteil
// bleibt frei zum Tippen: „01112026" springt nativ Tag→Monat→Jahr weiter. Es
// gibt bewusst KEINEN globalen showPicker()-auf-Klick-Handler mehr — der öffnete
// den Kalender bei jedem Klick und machte das Eintippen unmöglich (N18-b).

const LOGO_SPRITES = `
<symbol id="lg-villa" viewBox="0 0 96 96"><rect x="2" y="2" width="92" height="92" rx="20" fill="#EDF1F0"/><circle cx="80" cy="54" r="8" fill="#2E7D4F"/><rect x="78.5" y="60" width="3" height="12" fill="#143038"/><polygon points="22,46 48,27 74,46" fill="#143038"/><rect x="57" y="31" width="5" height="11" fill="#143038"/><rect x="29" y="46" width="38" height="26" fill="#0F6E5C"/><rect x="44" y="57" width="8" height="15" fill="#143038"/><rect x="33" y="51" width="8" height="8" fill="#F4B740"/><rect x="55" y="51" width="8" height="8" fill="#F4B740"/></symbol>
<symbol id="lg-bauernhof" viewBox="0 0 96 96"><rect x="2" y="2" width="92" height="92" rx="20" fill="#EDF1F0"/><circle cx="16" cy="56" r="7" fill="#2E7D4F"/><rect x="14.5" y="61" width="3" height="11" fill="#143038"/><rect x="62" y="42" width="11" height="30" fill="#F4B740"/><path d="M62 42 a5.5 5.5 0 0 1 11 0 z" fill="#143038"/><polygon points="24,47 30,33 54,33 60,47" fill="#143038"/><rect x="26" y="47" width="32" height="25" fill="#0F6E5C"/><rect x="36" y="54" width="12" height="18" fill="#143038"/></symbol>
<symbol id="lg-wohnung" viewBox="0 0 96 96"><rect x="2" y="2" width="92" height="92" rx="20" fill="#EDF1F0"/><circle cx="72" cy="55" r="8" fill="#2E7D4F"/><rect x="70.5" y="61" width="3" height="11" fill="#143038"/><polygon points="30,47 48,32 66,47" fill="#143038"/><rect x="34" y="47" width="28" height="25" fill="#0F6E5C"/><rect x="44" y="58" width="9" height="14" fill="#143038"/><rect x="38" y="52" width="9" height="8" fill="#F4B740"/></symbol>
<symbol id="lg-mfhA" viewBox="0 0 96 96"><rect x="2" y="2" width="92" height="92" rx="20" fill="#EDF1F0"/><rect x="17" y="44" width="15" height="28" fill="#143038" opacity=".22"/><circle cx="19" cy="60" r="5" fill="#2E7D4F" opacity=".55"/><rect x="34" y="28" width="30" height="44" fill="#0F6E5C"/><rect x="32" y="26" width="34" height="4" fill="#143038"/><rect x="39" y="34" width="8" height="8" fill="#F4B740"/><rect x="53" y="34" width="8" height="8" fill="#F4B740"/><rect x="39" y="46" width="8" height="8" fill="#F4B740"/><rect x="53" y="46" width="8" height="8" fill="#F4B740"/><rect x="45" y="60" width="8" height="12" fill="#143038"/></symbol>
<symbol id="lg-mfhB" viewBox="0 0 96 96"><rect x="2" y="2" width="92" height="92" rx="20" fill="#EDF1F0"/><circle cx="80" cy="56" r="7" fill="#2E7D4F"/><rect x="78.5" y="61" width="3" height="11" fill="#143038"/><polygon points="16,48 30,34 44,48" fill="#143038"/><rect x="19" y="48" width="22" height="24" fill="#0F6E5C"/><rect x="26" y="60" width="8" height="12" fill="#143038"/><rect x="22" y="52" width="7" height="7" fill="#F4B740"/><polygon points="42,48 56,34 70,48" fill="#143038"/><rect x="45" y="48" width="22" height="24" fill="#0F6E5C"/><rect x="52" y="60" width="8" height="12" fill="#143038"/><rect x="57" y="52" width="7" height="7" fill="#F4B740"/></symbol>
<symbol id="lg-gewerbe" viewBox="0 0 96 96"><rect x="2" y="2" width="92" height="92" rx="20" fill="#EDF1F0"/><circle cx="79" cy="58" r="6" fill="#2E7D4F"/><rect x="77.5" y="63" width="3" height="9" fill="#143038"/><rect x="18" y="40" width="52" height="5" fill="#143038"/><rect x="20" y="45" width="48" height="27" fill="#0F6E5C"/><rect x="27" y="47" width="34" height="6" fill="#143038"/><circle cx="31" cy="50" r="1.6" fill="#F4B740"/><polygon points="24,57 64,57 60,63 28,63" fill="#F4B740"/><rect x="28" y="63" width="13" height="9" fill="#F4B740"/><rect x="47" y="63" width="13" height="9" fill="#F4B740"/><rect x="41" y="61" width="6" height="11" fill="#143038"/></symbol>
${GRUNDSTUECK_SPRITE}`;

export const LOGOS = [
  ['lg-villa', 'Villa'],
  ['lg-bauernhof', 'Bauernhof'],
  ['lg-wohnung', 'Einzelne Wohnung'],
  ['lg-mfhA', 'Mehrfamilienhaus'],
  ['lg-mfhB', 'Zwei-/Doppelhaus'],
  ['lg-gewerbe', 'Gewerbe'],
  [GRUNDSTUECK_LOGO, 'Grundstück'],
];

/** Haengt die Logo-Symbole einmalig ins Dokument. */
export function installLogos() {
  if (document.getElementById('immo-sprites')) return;
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.id = 'immo-sprites';
  svg.setAttribute('width', '0');
  svg.setAttribute('height', '0');
  svg.setAttribute('aria-hidden', 'true');
  svg.style.position = 'absolute';
  svg.innerHTML = `<defs>${LOGO_SPRITES}</defs>`;
  document.body.prepend(svg);
}

export const logoSvg = (id, cls = '') =>
  `<svg class="${cls}" viewBox="0 0 96 96"><use href="#${id}"/></svg>`;

/** Bezeichnung eines Gebaeudetyps, mit Rueckfall auf Strich. */
export const logoLabel = id => (LOGOS.find(l => l[0] === id) || [, '—'])[1];

/* ---- API ---- */
export async function api(pfad, optionen = {}) {
  const antwort = await fetch('/api' + pfad, {
    headers: { 'Content-Type': 'application/json' },
    ...optionen,
    body: optionen.body ? JSON.stringify(optionen.body) : undefined,
  });
  if (!antwort.ok) {
    // FastAPI liefert die Ursache in `detail` — die ist fuer den Nutzer
    // deutlich hilfreicher als der blosse Statuscode.
    const grund = await antwort.json().then(k => k.detail).catch(() => null);
    throw new Error(grund || `${antwort.status} ${pfad}`);
  }
  return antwort.status === 204 ? null : antwort.json();
}

/* ---- Formatierung ---- */
export const eur = n =>
  (n ?? 0).toLocaleString('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' €';

export const eurKurz = n => {
  const v = n ?? 0;
  if (Math.abs(v) >= 10000) return Math.round(v / 1000).toLocaleString('de-DE') + 'k €';
  return Math.round(v).toLocaleString('de-DE') + ' €';
};

/**
 * Voller Betrag ohne Cent: „315.000 €“.
 *
 * Fuer Werte, bei denen die Groessenordnung nicht reicht und der Cent nur
 * stoert — Verkehrswert, Restschuld, Eigenkapital. Bei einem Hauswert sind
 * zwei Nachkommastellen eine Genauigkeit, die es gar nicht gibt.
 */
export const eurVoll = n =>
  (n == null ? 0 : Math.round(n)).toLocaleString('de-DE') + ' €';

/**
 * Miteigentumsanteil lesbar: „500 ‰", „333,3 ‰" — nie 333,29999999. Bewusst
 * ohne Tausenderpunkt: „1.000 ‰" liest sich sonst wie eintausend Komma null.
 */
export const promille = n => (n ?? 0).toLocaleString('de-DE',
  { maximumFractionDigits: 1, useGrouping: false }) + ' ‰';

export const esc = s => String(s ?? '')
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

/**
 * N287 — eine deutsche Zahleneingabe zu einer Zahl. `null`, wenn nichts
 * Brauchbares drinsteht.
 *
 * Es gab davon zwanzig Fassungen in fünf Ausbaustufen, und die häufigste war
 * schlicht `Number(text.replace(',', '.'))`. Die verliert genau einen Fall,
 * aber den teuersten: **`Number("1.250")` ist 1.25.** Wer im Ölbeleg, beim
 * Zählerstand oder in einem Wasserbetrag „1.250" tippt — für einen deutschen
 * Nutzer die naheliegende Schreibweise —, speicherte einen Tausendstel des
 * gemeinten Werts, ohne Hinweis.
 *
 * Die Regel ist dieselbe, die `kiauslese._zahl_de` auf dem Server anwendet:
 *
 *   * Ein Komma ist IMMER der Dezimaltrenner; Punkte davor sind Tausender.
 *     „1.234,56" → 1234.56
 *   * Ohne Komma entscheidet die Gruppierung: stehen hinter jedem Punkt genau
 *     drei Ziffern, sind es Tausenderpunkte. „1.250" → 1250, „1.234.567" →
 *     1234567
 *   * Sonst ist der Punkt dezimal. „12.5" → 12.5 — so kommen Werte aus der
 *     API zurück, und „12,5 m³" schreibt niemand als „12.500".
 *
 * `el` darf ein Element oder ein String sein.
 *
 * N294 — `data-wert` gilt NUR an einem Feld von `eingabe.js` (erkennbar an
 * `.eingabe-feld`). Dort steht der rohe Wert, während im Feld die formatierte
 * Fassung mit Tausenderpunkten sichtbar ist. Überall sonst bedeutet dasselbe
 * Attribut etwas anderes: in `zeitraum/` trägt es den ZULETZT GESPEICHERTEN
 * Wert für den Änderungsvergleich. Ohne diese Unterscheidung hätte `zahlAus`
 * dort den alten statt des getippten Werts gelesen und eine Eingabe stillschweigend
 * verworfen — dieselbe Falle wie die gleichnamigen `melde()` (N288).
 */
export function zahlAus(el) {
  const roh = (el && typeof el === 'object')
    ? (el.classList?.contains('eingabe-feld')
        && el.dataset?.wert != null && el.dataset.wert !== ''
        ? el.dataset.wert : el.value)
    : el;
  const text = String(roh ?? '').replace(/[^\d,.-]/g, '').trim();
  if (!text) return null;
  let zahl;
  if (text.includes(',')) {
    zahl = Number(text.replace(/\./g, '').replace(',', '.'));
  } else {
    const teile = text.split('.');
    // Dreiergruppen hinter jedem Punkt = Tausendergliederung, sonst dezimal.
    const tausender = teile.length > 1
      && teile.slice(1).every(t => t.length === 3);
    zahl = Number(tausender ? teile.join('') : text);
  }
  return Number.isFinite(zahl) ? zahl : null;
}

/**
 * N287 — heute als ISO-Datum, in LOKALER Zeit.
 *
 * `new Date().toISOString()` rechnet nach UTC um: zwischen Mitternacht und
 * 2 Uhr morgens (Sommerzeit) liefert es in Mitteleuropa den Vortag. Genau
 * darauf lief eine Zukunftsprüfung schon auf — und genau davor warnen zwei
 * Kommentare im Projekt, während drei Stellen es trotzdem taten.
 */
export function heuteIso() {
  const d = new Date();
  const p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/**
 * N295 — der leere Zustand einer Seite: eine Aussage, ein Weg heraus.
 *
 * Es gab ihn ein Dutzend Mal einzeln gebaut, und mehrere Fassungen endeten in
 * einer Sackgasse: eine weisse Karte mit „… nicht gefunden", darunter eine
 * Bildschirmhöhe leere Fläche und kein Knopf (roter Faden 4 und 7). Manche
 * wiederholten die Meldung zusätzlich in der Kopfzeile (roter Faden 3), weil
 * der Server denselben Satz zurückgibt, der schon als Überschrift dasteht.
 *
 * `dazu` erscheint deshalb NUR, wenn es etwas anderes sagt als `gross` — und
 * „anders" heisst hier nicht bloss „nicht wortgleich": „Nicht gefunden" über
 * „Renovierung nicht gefunden" ist dieselbe Auskunft zweimal. Steckt eines im
 * anderen, gewinnt der genauere Satz und wird zur Überschrift.
 *
 * `weg` ist der Ausweg — Vorgabe ist die Objektübersicht; `null` unterdrückt
 * ihn für die Fälle, in denen es wirklich nirgendwohin geht.
 */
export function leerHtml(gross, dazu = '',
                         weg = { text: 'Zur Übersicht', href: 'index.html' }) {
  const a = String(gross || '').trim();
  const b = String(dazu || '').trim();
  const ak = a.toLowerCase(), bk = b.toLowerCase();
  const deckungsgleich = Boolean(b) && (ak.includes(bk) || bk.includes(ak));
  const titel = deckungsgleich && b.length > a.length ? b : a;
  const rest = !b || deckungsgleich ? '' : b;
  return `<div class="empty">
      <div class="big">${esc(titel)}</div>
      ${rest ? `<p>${esc(rest)}</p>` : ''}
      ${weg ? `<a class="btn" href="${esc(weg.href)}">${esc(weg.text)}</a>` : ''}
    </div>`;
}

/** Fristklasse fuer die Ampel-Chips: rot ab 30, gelb ab 90 Tagen. */
export const fristKlasse = tage =>
  tage == null ? '' : tage < 0 ? 'neg' : tage <= 30 ? 'neg' : tage <= 90 ? 'amber' : 'pos';

/* ---- Navigation (CCXVI) -------------------------------------------------
   Die Leiste stand wortgleich in acht Seiten. Jetzt liegt sie einmal hier:
   `installNav()` baut sie aus `NAV` und haengt sie anstelle eines
   Platzhalter-Elements `[data-nav]` ein. */

// N203 — die Leiste ist gestaffelt: die objektbezogenen Wege stehen als
// eingerueckte Untergruppe unter „Objekte" (auf dem Desktop aufklappbar), der
// Rest bleibt oberste Ebene. Ein Eintrag mit viertem Feld (Kinder) ist ein
// Gruppenkopf; er ist selbst ein Link auf die Objektliste.
// N325 — bislang schlichte Unicode-Zeichen (▤ ▦ ≡ ▣ …), unterschiedliche
// Strichstärken, teils kryptisch (☗ für „Eigentümer"). Jetzt ein
// durchgehender Satz einstrichiger Liniensymbole (24×24, Strichstärke 1.7–1.9)
// im flachen Stil der App, wie schon `kostenicons.js`/`gewerkicons.js`.
const MENU_SPRITES = `
<symbol id="mi-objekte" viewBox="0 0 24 24"><path d="M4 11 12 4l8 7" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/><path d="M6 10v9h12v-9" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M10 19v-5h4v5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/></symbol>
<symbol id="mi-vermietung" viewBox="0 0 24 24"><rect x="4" y="10" width="6" height="10" rx="1" fill="none" stroke="currentColor" stroke-width="1.8"/><rect x="14" y="6" width="6" height="14" rx="1" fill="none" stroke="currentColor" stroke-width="1.8"/></symbol>
<symbol id="mi-nebenkosten" viewBox="0 0 24 24"><rect x="5" y="3.5" width="14" height="17" rx="2" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M8.5 8.5h7M8.5 12h7M8.5 15.5h4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></symbol>
<symbol id="mi-dokumente" viewBox="0 0 24 24"><path d="M6.5 4h7l4 4v12h-11z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M13.5 4v4h4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/></symbol>
<symbol id="mi-wert" viewBox="0 0 24 24"><path d="M4 16 9.5 10 13 13.5 20 6" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/><path d="M14.5 6h5.5v5.5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></symbol>
<symbol id="mi-pv" viewBox="0 0 24 24"><circle cx="12" cy="12" r="3.6" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M12 3v2.6M12 18.4V21M4.4 12H7M17 12h2.6M6.3 6.3l1.8 1.8M15.9 15.9l1.8 1.8M17.7 6.3l-1.8 1.8M8.1 15.9l-1.8 1.8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></symbol>
<symbol id="mi-tankstelle" viewBox="0 0 24 24"><rect x="5" y="4" width="9" height="16" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M14 9h2a2 2 0 0 1 2 2v4a1.6 1.6 0 0 0 3.2 0V8.5L19 6.3" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/><path d="M8 8h3M9.5 12 8 15h3l-1.5 3" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></symbol>
<symbol id="mi-eigentuemer" viewBox="0 0 24 24"><path d="M12 3.5 19 6.5v5.5c0 4.2-3 7-7 8.5-4-1.5-7-4.3-7-8.5V6.5z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M9 12l2 2 4-4.5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></symbol>
<symbol id="mi-kontakte" viewBox="0 0 24 24"><rect x="6" y="3" width="12" height="18" rx="2.5" fill="none" stroke="currentColor" stroke-width="1.8"/><circle cx="12" cy="10" r="2.4" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M8.3 16.5c.7-1.6 2-2.4 3.7-2.4s3 .8 3.7 2.4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></symbol>
<symbol id="mi-vorlagen" viewBox="0 0 24 24"><path d="M7 8h8l3 3v9H7z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><path d="M4.5 5h11l2.5 2.5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/><path d="M10.5 14.5h4M10.5 17.5h4" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></symbol>
<symbol id="mi-lexikon" viewBox="0 0 24 24"><path d="M12 6.5c-1.4-1.2-3.4-1.7-5.5-1.5v12.5c2.1-.2 4.1.3 5.5 1.5 1.4-1.2 3.4-1.7 5.5-1.5V5c-2.1-.2-4.1.3-5.5 1.5Z" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/><path d="M12 6.5v12.5" stroke="currentColor" stroke-width="1.7"/></symbol>
<symbol id="mi-einstellungen" viewBox="0 0 24 24"><circle cx="12" cy="12" r="6" fill="none" stroke="currentColor" stroke-width="1.8"/><circle cx="12" cy="12" r="2" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M12 2.3v2.5M12 19.2v2.5M21.7 12h-2.5M4.8 12H2.3M18.7 5.3l-1.8 1.8M7.1 16.9l-1.8 1.8M18.7 18.7l-1.8-1.8M7.1 7.1 5.3 5.3" stroke="currentColor" stroke-width="2.1" stroke-linecap="round"/></symbol>
<symbol id="mi-mehr" viewBox="0 0 24 24"><circle cx="6" cy="12" r="1.7" fill="currentColor"/><circle cx="12" cy="12" r="1.7" fill="currentColor"/><circle cx="18" cy="12" r="1.7" fill="currentColor"/></symbol>
<symbol id="mi-suche" viewBox="0 0 24 24"><circle cx="10.5" cy="10.5" r="6.5" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M19 19l-4-4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></symbol>
<symbol id="mi-scan-plus" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="2.3" stroke-linecap="round"/></symbol>`;

/** Haengt die Menue-Symbole einmalig ins Dokument (analog `installLogos`). */
function installMenuIcons() {
  if (document.getElementById('menu-sprites')) return;
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.id = 'menu-sprites';
  svg.setAttribute('width', '0');
  svg.setAttribute('height', '0');
  svg.setAttribute('aria-hidden', 'true');
  svg.style.position = 'absolute';
  svg.innerHTML = `<defs>${MENU_SPRITES}</defs>`;
  document.body.prepend(svg);
}

const navIcon = id =>
  `<svg viewBox="0 0 24 24" aria-hidden="true"><use href="#${id}"/></svg>`;

// N327-b — die Dokumente-Kachel in der unteren Leiste ist wieder der runde,
// erhöhte Knopf in der Mitte (Nutzer-Korrektur: „Dokument-Icon in der Mitte
// fehlt" — die reine Vier-Link-Fassung hatte ihn faelschlich ganz entfernt).
// Steht man schon auf `eingang.html`, waere ein Klick auf „Dokumente"
// sinnlos (dieselbe Seite) — das Symbol wechselt dann auf ein eigens
// gestaltetes „+" und der Klick loest „Beleg abfotografieren" aus (siehe
// `installNav`). Zwei Icons uebereinander, CSS blendet je nach
// `aria-current` das passende ein.
const dokumenteIcon = `<span class="ni-doc">${navIcon('mi-dokumente')}</span>`
  + `<span class="ni-plus">${navIcon('mi-scan-plus')}</span>`;

export const NAV = [
  ['Objekte', 'index.html', navIcon('mi-objekte'), [
    // N23 — Vermietungsstatistik: Miete + Nebenkosten, Durchschnitte,
    // Mieterhöhungen über die eigenen Objekte und Einheiten.
    ['Vermietung', 'vermietungen.html', navIcon('mi-vermietung')],
    ['Nebenkosten', 'nebenkosten.html', navIcon('mi-nebenkosten')],
    ['Dokumente', 'eingang.html', dokumenteIcon],
    // N327-b — Nutzer: „Shorten to Wert" — „Wertentwicklung" lief in der
    // unteren Leiste zu „Wertentwickl…" zusammen.
    ['Wert', 'wertentwicklung.html', navIcon('mi-wert')],
    // N83/N87 — Strom/PV-Subsystem je Objekt/Jahr, samt Amortisation des
    // PV-Investments (die Amortisation ist Inhalt der PV-Seite, kein Menuepunkt).
    ['PV Anlagen', 'strom.html', navIcon('mi-pv')],
  ]],
  // N132 — die E-Tankstelle ist ein eigener Bereich, keine Karte auf der
  // PV-Seite: eigene Nutzer, eigener Verlauf, eigene Abrechnung.
  ['E-Tankstelle', 'tankstelle.html', navIcon('mi-tankstelle')],
  ['Eigentümer', 'eigentuemer.html', navIcon('mi-eigentuemer')],
  // N246 — das Belegarchiv (N84, die interne Wissens-Datenbank der KI-
  // ausgelesenen Belege) hat KEINEN Menuepunkt mehr: es laeuft im Hintergrund
  // mit und wird selten geoeffnet. Der Einstieg steht in den Einstellungen
  // unter „Dokumente"; die Seite bleibt unter `belegarchiv.html` erreichbar.
  // N240 — leere Formulare zum Ausfüllen (Übergabeprotokoll, Selbstauskunft,
  // Rauchwarnmelder-Abnahme, Wohnungsgeberbestätigung …), objektübergreifend.
  ['Vorlagen', 'vorlagenarchiv.html', navIcon('mi-vorlagen')],
  ['Lexikon', 'lexikon.html', navIcon('mi-lexikon')],
  // N327-b — „Kontakte" und „Einstellungen" stehen hier NICHT mehr als eigene
  // Zeile: sie sind jetzt eigene Symbole an jeder Kopfzeile, gleichrangig
  // neben der Suche (`KOPF_EIGEN` unten), statt hinter einem Sammel-Knopf zu
  // verschwinden — derselbe Weg soll nicht doppelt existieren.
];

// N327-b — Einstellungen und Kontakte: eigene Symbole in der Kopfzeile, genau
// wie die Suche (nicht mehr hinter „…" versteckt, siehe Nutzer-Feedback).
const KOPF_EIGEN = [
  ['Einstellungen', 'settings.html', navIcon('mi-einstellungen')],
  ['Kontakte', 'kontakte.html', navIcon('mi-kontakte')],
];

// N327-b — die unteren festen Ziele: links Objekte/Nebenkosten, rechts PV
// Anlagen/Wertentwicklung (Nutzer-Auswahl: „die wichtigsten"), Dokumente
// bleibt der runde, erhöhte Knopf in der Mitte. Alles andere aus `NAV`
// (Vermietung, E-Tankstelle, Eigentümer, Vorlagen, Lexikon) wandert in die
// Kopfzeilen-„…" (`kopfMehrOeffnen`) — kein unteres „Mehr" mehr.
const NAV_UNTEN_FEST = ['index.html', 'nebenkosten.html', 'eingang.html',
                        'strom.html', 'wertentwicklung.html'];

// Alle NAV-Ziele flach (Gruppenkopf + Kinder in einer Liste) — Grundlage für
// die Kopfzeilen-„…", die alles zeigt, was nicht unten fest steht.
function navFlach() {
  const flach = [];
  for (const [label, href, icon, kinder] of NAV) {
    flach.push([label, href, icon]);
    if (kinder) flach.push(...kinder);
  }
  return flach;
}

// Kleiner Chevron im flachen Stil der App — dreht sich beim Einklappen.
const CARET_SVG = '<svg viewBox="0 0 16 16" width="14" height="14" '
  + 'aria-hidden="true"><path d="M4 6l4 4 4-4" fill="none" stroke="currentColor" '
  + 'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>';

// Merkt sich, ob die Objektgruppe eingeklappt ist (nur Desktop-Belang).
const GRUPPE_ZU = 'immocalc-objekte-zu';

// objekt.html, zeitraum.html und renovierung.html stehen selbst nicht in der
// Leiste — sie sind Detailansichten der Objektliste und zaehlen fuer die
// Markierung als "Objekte". N277: renovierung.html fehlte hier und setzte
// `aria-current` nach `installNav()` von Hand nach; die Markierung gehoert an
// diese eine Stelle, sonst muss sie jede neue Detailseite neu erfinden.
const NAV_ALIAS = {
  'objekt.html': 'index.html',
  'zeitraum.html': 'index.html',
  'renovierung.html': 'index.html',
};

/** Haengt die Navigationsleiste anstelle von `[data-nav]` ins Dokument. */
export function installNav() {
  const platz = document.querySelector('[data-nav]');
  if (!platz) return;
  const datei = location.pathname.split('/').pop() || 'index.html';
  const aktiv = NAV_ALIAS[datei] || datei;

  // Ein Eintrag wird zum flachen Link. `extra` haengt hinter das Label (Chevron
  // beim Gruppenkopf); `klasse` markiert Gruppenkopf bzw. Kind.
  const link = (label, href, icon, extra = '', klasse = '') =>
    `<a${klasse ? ` class="${klasse}"` : ''} href="${href}"${
      href === aktiv ? ' aria-current="page"' : ''
    }><span class="ni">${icon}</span><span class="nl">${label}</span>${extra}</a>`;

  let html = `<a class="brand" href="index.html">ImmoCalc</a>`;
  let kindAktiv = false;
  for (const [label, href, icon, kinder] of NAV) {
    if (kinder) {
      // Alle Ziele bleiben flache <a> in der Leiste (`navFlach` zaehlt sie
      // fuer die Kopfzeilen-„…" einzeln auf); die Staffelung ist reine Optik.
      kindAktiv = kinder.some(([, khref]) => khref === aktiv);
      const caret = `<span class="kappe" role="button" tabindex="0"`
        + ` aria-label="Objektmenü ein- oder ausklappen" aria-expanded="true">`
        + `${CARET_SVG}</span>`;
      html += link(label, href, icon, caret, 'gruppenkopf');
      html += kinder.map(([kl, kh, ki]) => link(kl, kh, ki, '', 'kind')).join('');
    } else {
      html += link(label, href, icon);
    }
  }

  installMenuIcons();
  const nav = document.createElement('nav');
  nav.className = 'nav';
  nav.innerHTML = html;
  platz.replaceWith(nav);
  gruppeVerdrahten(nav, kindAktiv);
  dokumenteKnopfVerdrahten(nav, aktiv);
  installKopfAktionen(aktiv);
}

/* N327 — steht man schon auf `eingang.html`, macht ein Klick auf den runden
   Dokumente-Knopf (dort jetzt ein „+", siehe CSS) nichts Sinnvolles mehr: die
   Seite ist ja schon offen. Er loest stattdessen denselben Weg aus wie der
   Kamera-Knopf oben auf der Seite selbst — ohne den erst suchen zu muessen. */
function dokumenteKnopfVerdrahten(nav, aktiv) {
  if (aktiv !== 'eingang.html') return;
  const knopf = nav.querySelector('a[href="eingang.html"]');
  if (!knopf) return;
  knopf.setAttribute('aria-label', 'Beleg abfotografieren');
  knopf.addEventListener('click', e => {
    const kamera = document.getElementById('kamera');
    if (!kamera) return;
    e.preventDefault();
    kamera.click();
  });
}

/* Klappt die Objektgruppe auf dem Desktop auf/zu. Standard: aufgeklappt, damit
   die Staffelung sichtbar ist. Ist ein Kind die aktive Seite, wird immer
   aufgeklappt, sonst waere der aktive Eintrag verborgen. Der Chevron toggelt,
   der Rest des Kopfes bleibt ein Link auf die Objektliste. */
function gruppeVerdrahten(nav, kindAktiv) {
  const kappe = nav.querySelector('.gruppenkopf .kappe');
  if (!kappe) return;
  let zu = localStorage.getItem(GRUPPE_ZU) === '1';
  if (kindAktiv) zu = false;
  const anwenden = () => {
    nav.classList.toggle('objekte-zu', zu);
    kappe.setAttribute('aria-expanded', String(!zu));
  };
  anwenden();
  const um = e => {
    e.preventDefault();
    e.stopPropagation();
    zu = !zu;
    localStorage.setItem(GRUPPE_ZU, zu ? '1' : '0');
    anwenden();
  };
  kappe.addEventListener('click', um);
  kappe.addEventListener('keydown', e => {
    if (e.key === 'Enter' || e.key === ' ') um(e);
  });
}

/* N327-b — Kopfzeilen-Aktionsgruppe: Einstellungen, Kontakte, „…" (der Rest)
   und Suche — gleichrangig, keine hinter einem Sammel-Knopf versteckt (ausser
   dem bewusst gesammelten Rest). Haengt sich an JEDE `.bar` — eine Stelle
   statt ~19 Seiten einzeln anzufassen. Steht keine `.bar` auf der Seite
   (sollte nicht vorkommen), passiert nichts.

   Die untere Leiste zeigt auf dem Handy nur noch die vier festen Ziele aus
   `NAV_UNTEN_FEST` (reines CSS, siehe immo.css) — kein JS-„Mehr" mehr dort.
   Alles andere (Vermietung, Dokumente, E-Tankstelle, Eigentümer, Vorlagen,
   Lexikon) zeigt die Kopfzeilen-„…". */
function installKopfAktionen(aktiv) {
  const bar = document.querySelector('.bar');
  if (!bar || bar.querySelector('.kopfakt')) return;
  const rest = navFlach().filter(([, href]) => !NAV_UNTEN_FEST.includes(href));
  const gruppe = document.createElement('div');
  gruppe.className = 'kopfakt';
  gruppe.innerHTML = `
    <button type="button" class="ka-mehr" aria-haspopup="dialog"
            aria-label="Weitere Bereiche" title="Weitere Bereiche"
            ${rest.some(([, href]) => href === aktiv) ? 'aria-current="page"' : ''}
      >${navIcon('mi-mehr')}</button>
    ${KOPF_EIGEN.map(([label, href, icon]) => `
      <a class="ka-ziel" href="${href}" aria-label="${label}" title="${label}"
         ${href === aktiv ? 'aria-current="page"' : ''}>${icon}</a>`).join('')}
    <button type="button" class="ka-suche" aria-label="Suchen"
            title="Suchen">${navIcon('mi-suche')}</button>`;
  bar.appendChild(gruppe);
  installMenuIcons();
  gruppe.querySelector('.ka-mehr').addEventListener('click', () => kopfMehrOeffnen(rest, aktiv));
  // N328 — die neue Suchseite lebt fuer sich (leer bis zur ersten Eingabe,
  // live Ergebnisse, nach Objekte/Einheiten/Dokumente unterschieden) statt in
  // der ohnehin schon vollen Dokumente-Ansicht mitzulaufen.
  gruppe.querySelector('.ka-suche').addEventListener('click', () => {
    location.href = 'suche.html';
  });
}

/** Das "…"-Blatt der Kopfzeile: alles aus `NAV`, das nicht unten fest steht. */
function kopfMehrOeffnen(rest, aktiv) {
  const dlg = baueDialog(`
    <div class="dt">Weitere Bereiche</div>
    <div class="mehrliste">${rest.map(([label, href, icon]) => `
      <a href="${href}" ${href === aktiv ? 'aria-current="page"' : ''}>
        <span class="ni">${icon}</span>${label}
      </a>`).join('')}</div>`);
  dlg.classList.add('mehr-dlg');
  dlg.addEventListener('click', e => { if (e.target === dlg) dlg.close(); });
}

/* ---- Meldungen und Rückfragen im Design der App -------------------------
   `alert` und `confirm` zeichnet der Browser: graue Systemkästen, die mit der
   Seite nichts zu tun haben. Beides hier selbst gebaut — und die Rückfrage vor
   dem Löschen als Schiebe-Regler, damit ein zweiter Klick nicht aus Versehen
   passieren kann. */

/** Kurze Rückmeldung am unteren Rand. Verschwindet von selbst. */
export function melde(text, art = '') {
  let feld = document.getElementById('immo-melder');
  if (!feld) {
    feld = document.createElement('div');
    feld.id = 'immo-melder';
    feld.className = 'melder';
    feld.setAttribute('role', 'status');
    feld.setAttribute('aria-live', 'polite');
    document.body.appendChild(feld);
  }
  feld.className = `melder an ${art}`;
  feld.textContent = text;
  clearTimeout(feld._zeit);
  feld._zeit = setTimeout(() => { feld.className = 'melder'; }, 5200);
}

// Woran ein Dialog erkennt, dass er schon ein eigenes Schließen-Element hat —
// dann wird keins nachgerüstet. Deckt beide Welten ab: die per baueDialog
// erzeugten (data-zu / .immo-dlg-zu) und die statisch im HTML stehenden
// (.close/data-schliessen in settings & eigentuemer, .bzu/.bx in eingang).
// `data-nein` gehört dazu: ein Dialog mit unterem Abbrechen/Schließen-Knopf
// braucht kein zweites × oben — sonst „doppelt gemoppelt". Wer nur das ×
// will, lässt den unteren Knopf weg (siehe „Mehr"-Menü).
const SCHLIESS_MARKER =
  '[data-schliessen],[data-zu],[data-nein],.immo-dlg-zu,.close,.bzu,.bx';

// Sichtbares Schließen-Kreuz oben rechts anbringen, falls der Dialog noch
// keins hat. Bewusst gut sichtbar (heller Kreis mit Tiefe), nicht grau-
// unscheinbar — sonst muss man zum Abbrechen erst nach unten scrollen.
export function kreuzAnbringen(dlg) {
  if (!dlg || dlg.querySelector(SCHLIESS_MARKER)) return;
  const zu = document.createElement('button');
  zu.type = 'button';
  zu.className = 'immo-dlg-zu';
  zu.setAttribute('aria-label', 'Schließen');
  zu.textContent = '✕';
  zu.addEventListener('click', () => dlg.close());
  dlg.appendChild(zu);
}

// Statische <dialog>-Elemente (Mietverhältnis, Einheit …) bekommen dasselbe
// Kreuz wie die dynamischen. Läuft einmal, wenn das Modul geladen ist.
function dialogeNachruesten() {
  document.querySelectorAll('dialog').forEach(kreuzAnbringen);
}
if (typeof document !== 'undefined') {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', dialogeNachruesten);
  } else {
    dialogeNachruesten();
  }
}

export function baueDialog(inhalt) {
  const dlg = document.createElement('dialog');
  dlg.className = 'immo-dlg';
  dlg.innerHTML = inhalt;
  kreuzAnbringen(dlg);
  document.body.appendChild(dlg);
  dlg.addEventListener('close', () => dlg.remove());
  dlg.showModal();
  return dlg;
}

/**
 * Beleg ansehen, ohne die App zu verlassen.
 *
 * Vorher lief das ueber `window.open`: auf dem Telefon oeffnet die
 * Startbildschirm-App damit einen Betrachter ohne Leiste — man sieht das PDF
 * und kommt nicht mehr heraus. Deshalb bleibt der Beleg jetzt im Dialog, mit
 * drei Wegen zurueck: Kreuz, Escape und Tippen neben das Blatt.
 */
/* N257(d) — mehrere Belege gehören oft zusammen (fünf an einer Kostenart).
   `geschwister` ist die Liste, in der dieser Beleg steht: `[{id, dateiname,
   pfad}]`. Steht mehr als einer darin, erscheinen ← und → im Kopf und man
   blättert, ohne jedes Mal in die Liste zurückzumüssen. Freiwillig — alle
   bisherigen Aufrufer übergeben nichts und sehen keinen Unterschied. */
// N286 — flaches Ordner-Symbol im selben Stil wie die übrigen Inline-SVGs der
// App (keine Icon-Bibliothek, `currentColor` folgt dem Hover wie beim
// Umbenennen-Knopf daneben).
const ORDNER_ICON = `<svg viewBox="0 0 24 24" width="19" height="19"
  style="vertical-align:-4px" aria-hidden="true">
  <path d="M3 6.5A1.5 1.5 0 0 1 4.5 5h4.6l1.6 1.8h8.8A1.5 1.5 0 0 1 21 8.3v9.2a1.5
    1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 17.5z"
    fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>
</svg>`;

export function belegAnsehen(url, titel = 'Beleg', pfad = '', dokumentId = null,
                             geschwister = null) {
  // Die GANZE Seite als serverseitig gerendertes Bild, breitenfüllend statt
  // beschnitten — das ist die alleinige große Ansicht. Kein zusätzliches ↗ in
  // einen zweiten Tab: auf dem iPhone lässt sich der native PDF-Betrachter dort
  // nicht mehr schließen. Zurück geht es allein über das × oben (oder Tippen
  // daneben, oder Escape). Das ↗ erscheint nur, wenn es gar keine Bildvorschau
  // gibt (xlsx/docx) — dann ist der neue Tab der einzige Weg zum Inhalt.
  // Alle Seiten des PDFs untereinander, jede als serverseitig gerendertes Bild
  // (`/seiten` sagt wie viele, `/vorschau?seite=i` liefert Blatt i, 0-basiert).
  // Fällt der Seiten-Endpunkt aus (alter Stand), bleibt es bei einer Seite.
  const basis = url.replace('/inhalt', '');
  // Wo stehen wir in der Reihe? Nur mit mindestens zwei Geschwistern blättern.
  const reihe = Array.isArray(geschwister) && geschwister.length > 1
    ? geschwister : null;
  const platz = reihe
    ? reihe.findIndex(d => String(d.id) === String(dokumentId ?? dokumentIdAus(url)))
    : -1;
  const blaettern = reihe && platz >= 0
    ? `<span class="bnav">
         <button class="bnb" data-vor title="Vorheriger Beleg"
           aria-label="Vorheriger Beleg">‹</button>
         <span class="bnz">${platz + 1}/${reihe.length}</span>
         <button class="bnb" data-zurueck title="Nächster Beleg"
           aria-label="Nächster Beleg">›</button>
       </span>` : '';
  // N261 — der Name lässt sich hier korrigieren. Der Knopf sitzt EINMAL in
  // diesem Fenster und erscheint dadurch überall, wo ein Beleg geöffnet wird.
  // Nur bei echten Belegen: Vorlagen (`/api/dokumentvorlagen/…`) kennen den
  // Endpunkt nicht, dort wäre der Knopf ein Versprechen ins Leere.
  const belegId = dokumentId ?? dokumentIdAus(url);
  const umbenennbar = Boolean(belegId) && /\/api\/dokumente\//.test(String(url));
  const dlg = baueDialog(
    `<div class="beleg-kopf">
       <span class="bt">${belegKopf(titel, pfad)}</span>
       ${blaettern}
       ${umbenennbar
         ? `<button class="bx" data-um title="Namen ändern"
              aria-label="Namen ändern">✎</button>
            <button class="bx" data-ordner title="Ordner ändern"
              aria-label="Ordner ändern">${ORDNER_ICON}</button>` : ''}
       <button class="bx" data-zu title="Schließen" aria-label="Schließen">✕</button>
     </div>
     <div class="beleg-ki" hidden></div>
     <div class="beleg-flaeche"><div class="beleg-blatt lade">Beleg wird geholt …</div></div>`);
  dlg.classList.add('beleg-dlg');
  dlg.querySelector('[data-zu]').addEventListener('click', () => dlg.close());
  // Tippen neben die Fläche schliesst ebenfalls.
  dlg.addEventListener('click', e => { if (e.target === dlg) dlg.close(); });

  // N102 — was zu diesem Beleg schon ausgelesen wurde, steht über der Vorschau.
  kiAusleseZeigen(dokumentId ?? dokumentIdAus(url), dlg.querySelector('.beleg-ki'));

  const flaeche = dlg.querySelector('.beleg-flaeche');
  const adressen = belegSeitenLaden(basis, flaeche, titel, url);

  dlg.addEventListener('close', () => adressen.forEach(adr => URL.revokeObjectURL(adr)));

  // N261 — Umbenennen ohne das Fenster zu verlassen: nach dem Speichern stehen
  // neuer Name und neuer Pfad sofort im Kopf, die Seite wird nicht neu geladen.
  dlg.querySelector('[data-um]')?.addEventListener('click', async () => {
    const gewuenscht = await namenErfragen(titel);
    if (gewuenscht === null) return;
    try {
      const erg = await api(`/dokumente/${belegId}/name`,
                            { method: 'PATCH', body: { beschreibung: gewuenscht } });
      titel = erg.dateiname || titel;
      pfad = erg.pfad || pfad;
      dlg.querySelector('.bt').innerHTML = belegKopf(titel, pfad);
      // Beim Weiterblättern soll der Nachbar-Eintrag den neuen Namen tragen.
      if (reihe && platz >= 0) Object.assign(reihe[platz], { dateiname: titel, pfad });
      melde(erg.geaendert === false
        ? 'Der Name war schon so — nichts geändert'
        : `Umbenannt in „${titel}“`, 'pos');
    } catch (fehler) {
      melde(String(fehler.message || fehler), 'neg');
    }
  });

  // N286 — Ablageordner von Hand ändern: erst die möglichen Ziele holen, dann
  // wählen lassen, dann verschieben. Cloud zuerst, Datenbank danach
  // (`_beleg_umziehen`) — kippt die Cloud, bleibt hier bewusst nichts sichtbar
  // geändert, der Nutzer bekommt nur die Fehlermeldung.
  dlg.querySelector('[data-ordner]')?.addEventListener('click', async () => {
    let ziele;
    try {
      ziele = await api(`/dokumente/${belegId}/ablageziele`);
    } catch (fehler) {
      melde(String(fehler.message || fehler), 'neg');
      return;
    }
    const gewaehlt = await ordnerWaehlen(ziele);
    if (gewaehlt === null) return;
    try {
      const erg = await api(`/dokumente/${belegId}/verschieben`,
                            { method: 'POST', body: { ordner: gewaehlt } });
      if (erg.verschoben === false) {
        melde(erg.hinweis || 'Der Beleg liegt bereits dort.');
        return;
      }
      titel = erg.dateiname || titel;
      pfad = erg.pfad || pfad;
      dlg.querySelector('.bt').innerHTML = belegKopf(titel, pfad);
      if (reihe && platz >= 0) Object.assign(reihe[platz], { dateiname: titel, pfad });
      melde(`In „${erg.pfad}“ verschoben`, 'pos');
    } catch (fehler) {
      melde(String(fehler.message || fehler), 'neg');
    }
  });

  // Blättern: dasselbe Fenster für den Nachbarn neu aufbauen. Die Reihe wandert
  // mit, sodass man beliebig weiterblättern kann; am Rand wird umgebrochen.
  if (reihe && platz >= 0) {
    const springe = (schritt) => {
      const n = reihe[(platz + schritt + reihe.length) % reihe.length];
      dlg.close();
      belegAnsehen(`/api/dokumente/${n.id}/inhalt`, n.dateiname || 'Beleg',
                   n.pfad || '', n.id, reihe);
    };
    dlg.querySelector('[data-vor]').addEventListener('click', () => springe(-1));
    dlg.querySelector('[data-zurueck]').addEventListener('click', () => springe(1));
    dlg.addEventListener('keydown', e => {
      if (e.key === 'ArrowLeft') { e.preventDefault(); springe(-1); }
      if (e.key === 'ArrowRight') { e.preventDefault(); springe(1); }
    });
  }
  return dlg;
}

/* ---- N261: den Namen eines abgelegten Belegs korrigieren ----------------
   Vorher gab es dafür keinen Weg. Der Versuch, einen Namen zu ändern, landete
   in der Betrags-Korrektur und stand danach als „_348_" im Dateinamen statt
   im Betrag. Jetzt: ein Stift im Beleg-Kopf, eine Zeile, fertig. */

/** Kopfzeile des Beleg-Fensters: Name und darunter der Ablageort.
    Steht einmal hier, weil das Umbenennen sie neu setzt. */
const belegKopf = (titel, pfad) => `${sicher(titel)}${pfad
  ? `<span class="bpfad" title="Ablageort in der Nextcloud"><bdi dir="ltr">${
      sicher(pfad)}</bdi></span>` : ''}`;

/**
 * Fragt nach dem neuen Namen. Liefert den Text — oder `null` bei Abbruch.
 *
 * Vorbelegt mit dem heutigen Namen ohne Endung: der Nutzer korrigiert, was er
 * sieht. Datum und Betrag setzt der Server an ihren festen Platz (dieselbe
 * Regel wie beim Scannen), deshalb macht auch ein mitgetippter Betrag den
 * Namen nicht kaputt.
 */
function namenErfragen(aktuellerName) {
  const stamm = String(aktuellerName ?? '').replace(/\.[A-Za-z0-9]{1,5}$/, '');
  return new Promise(erfuellen => {
    const dlg = baueDialog(
      `<div class="dt">Beleg umbenennen</div>
       <div class="sb-name">
         <label for="umName">Name</label>
         <input id="umName" type="text" value="${esc(stamm)}"
                placeholder="Bezeichnung des Belegs" spellcheck="false"
                autocapitalize="off" autocomplete="off">
         <p class="sb-hinweis">Datum und Betrag setzt ImmoCalc selbst — hier
           steht die Sache. Die Datei bleibt in ihrem Ordner.</p>
       </div>
       <div class="sb-fuss" style="margin-top:14px">
         <button type="button" class="sb-weiter" data-ok>Umbenennen</button>
       </div>`);
    dlg.classList.add('scanbest-dlg');

    let entschieden = false;
    const schliessen = (wert) => {
      if (entschieden) return;
      entschieden = true;
      dlg.close();
      erfuellen(wert);
    };
    const feld = dlg.querySelector('#umName');
    const speichern = () => {
      const neu = (feld.value || '').trim();
      // Ein leeres Feld ist kein Abbruch, sondern ein Versehen: die Maske
      // bleibt stehen und sagt, was fehlt.
      if (!neu) {
        melde('Bitte einen Namen für den Beleg angeben', 'neg');
        feld.focus();
        return;
      }
      // Unverändert: gar nicht erst zum Server — es gäbe nichts zu tun.
      schliessen(neu === stamm ? null : neu);
    };
    dlg.querySelector('[data-ok]').addEventListener('click', speichern);
    feld.addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); speichern(); }
    });
    dlg.addEventListener('close', () => schliessen(null));
    feld.focus();
    feld.select();
  });
}

/* ---- N286: Ablageordner eines Belegs von Hand ändern --------------------
   Die Ziele kommen aus `GET …/ablageziele` — derselben Kategorie-Struktur,
   die auch beim automatischen Ablegen benutzt wird (`cloudkern.ZIELORDNER`).
   Ausgewählt wird über das App-eigene Auswahlfeld, kein natives <select>. */

/**
 * Zeigt die möglichen Ablageordner als Auswahlfeld und liefert den gewählten
 * Ordner zurück — oder `null` bei Abbruch bzw. wenn der Nutzer den Ordner
 * bestätigt, in dem der Beleg schon liegt (dann gäbe es nichts zu tun).
 */
function ordnerWaehlen(daten) {
  const ziele = daten?.ziele || [];
  if (!ziele.length) {
    melde('Für diese Immobilie sind keine Ablageordner bekannt.', 'neg');
    return Promise.resolve(null);
  }
  const aktuell = ziele.find(z => z.aktuell)?.ordner ?? ziele[0].ordner;
  return new Promise(erfuellen => {
    const dlg = baueDialog(
      `<div class="dt">Ablageordner ändern</div>
       <div class="sb-name">
         <label>Ordner</label>
         <div id="umOrdner"></div>
         <p class="sb-hinweis">Die Datei wandert in der Nextcloud mit —
           nichts wird überschrieben, nichts gelöscht.</p>
       </div>
       <div class="sb-fuss" style="margin-top:14px">
         <button type="button" class="sb-weiter" data-ok>Verschieben</button>
       </div>`);
    dlg.classList.add('scanbest-dlg');

    let entschieden = false;
    const schliessen = (wert) => {
      if (entschieden) return;
      entschieden = true;
      dlg.close();
      erfuellen(wert);
    };
    const feld = auswahlfeld(dlg.querySelector('#umOrdner'), {
      optionen: ziele.map(z => ({ wert: z.ordner, text: z.name })),
      wert: aktuell,
      label: 'Ablageordner',
    });
    dlg.querySelector('[data-ok]').addEventListener('click', () => {
      const gewuenscht = feld.wert();
      // Derselbe Ordner wie jetzt: kein Aufruf, der nichts zu tun hätte.
      schliessen(gewuenscht === aktuell ? null : gewuenscht);
    });
    dlg.addEventListener('close', () => schliessen(null));
  });
}

/* ---- KI-Auslese im Beleg-Fenster (N102) ----
   Beim Ansehen eines verknüpften Belegs soll gleich oben stehen, was zu dieser
   Datei schon erkannt wurde. Bewusst OHNE `?neu=true`: `GET …/erkennen` gibt
   seit N98 die in der Datenbank festgehaltene Auslese zurück (`aus_db`), es
   wird von hier aus nie eine neue KI-Anfrage ausgelöst. */

/** Dokument-Id aus einer Beleg-URL wie `/api/dokumente/605/inhalt`. */
const dokumentIdAus = url => {
  const treffer = /\/dokumente\/(\d+)(?:\/|\?|$)/.exec(String(url ?? ''));
  return treffer ? treffer[1] : null;
};

const datumDe = wert => {
  const t = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(wert ?? ''));
  return t ? `${t[3]}.${t[2]}.${t[1]}` : String(wert ?? '').trim();
};

/** Feldname aus dem KI-Raster als Beschriftung: `abrechnungs_zeitraum` → „Abrechnungs zeitraum". */
const feldLabel = name => {
  const t = String(name ?? '').replace(/[_-]+/g, ' ').trim();
  return t ? t[0].toUpperCase() + t.slice(1) : '';
};

/** Ein Wert aus dem KI-Raster als Text. Verschachteltes wird ausgelassen. */
function feldWert(name, wert) {
  if (wert === null || wert === undefined || wert === '') return '';
  if (Array.isArray(wert)) return wert.map(w => feldWert(name, w)).filter(Boolean).join(', ');
  if (typeof wert === 'object') return '';
  if (typeof wert === 'boolean') return wert ? 'ja' : 'nein';
  if (typeof wert === 'number') {
    return /betrag|summe|preis|kosten|brutto|netto/i.test(name)
      ? eur(wert) : wert.toLocaleString('de-DE');
  }
  return String(wert).trim();
}

/** Die anzeigbaren Angaben einer Auslese als [Beschriftung, Wert]-Paare. */
function kiZeilen(w) {
  const zeilen = [];
  const gesehen = new Set();
  const dazu = (label, wert) => {
    const text = String(wert ?? '').trim();
    const schluessel = label.toLowerCase();
    if (!text || !label || gesehen.has(schluessel)) return;
    gesehen.add(schluessel);
    zeilen.push([label, text]);
  };
  if (typeof w.betrag === 'number') dazu('Betrag', eur(w.betrag));
  // N262 — steht der Betrag nicht auf dem Beleg, sondern ist aus Teilzahlungen
  // gerechnet, gehört das dazu. Ein Jahreswert, den niemand herleiten kann,
  // wäre in der Abrechnung nicht nachvollziehbar.
  if (typeof w.teilbetrag === 'number' && w.teilzahlungen > 1) {
    dazu('Hochgerechnet', `${eur(w.teilbetrag)} × ${w.teilzahlungen}`);
  }
  if (w.datum) dazu('Datum', datumDe(w.datum));
  else if (w.jahr) dazu('Jahr', w.jahr);
  dazu('Kategorie', w.kategorie);
  dazu('Kostenart', w.kostenart);
  dazu('Sache', w.sache);
  dazu('Immobilie', w.immobilie);
  dazu('Einheit', w.einheit);
  const felder = (w.felder && typeof w.felder === 'object') ? w.felder : {};
  Object.entries(felder).forEach(([name, wert]) =>
    dazu(feldLabel(name), feldWert(name, wert)));
  return zeilen;
}

/** Der ruhige Block über der Vorschau — leer, wenn nichts gespeichert ist. */
export function kiAusleseHtml(w) {
  const satz = String(w.zusammenfassung || w.einordnung || '').trim();
  const zeilen = kiZeilen(w);
  if (!satz && !zeilen.length) return '';
  // N103 - „Dokumentenerkennung" statt „KI-Auslese": der Nutzer soll die
  // ausgelesenen Angaben sehen, nicht die Technik dahinter.
  return `<div class="ki-kopf"><span class="kt">Dokumentenerkennung</span>${
      w.aus_db ? '<span class="kq">gespeichert</span>' : ''}</div>`
    + (satz ? `<p class="ki-satz">${sicher(satz)}</p>` : '')
    + (zeilen.length
        ? `<div class="ki-chips">${zeilen.map(([l, v]) =>
            `<span class="ki-chip"><span class="kl">${sicher(l)}</span>`
            + `<span class="kw">${sicher(v)}</span></span>`).join('')}</div>`
        : '');
}

/**
 * Holt die gespeicherte Auslese und setzt sie in `kasten`. Still bei jedem
 * Fehler (404, kein Schlüssel, altes Backend): die Vorschau darf nie brechen,
 * dann bleibt der Kasten schlicht weg.
 */
function kiAusleseZeigen(id, kasten) {
  if (!id || !kasten) return;
  fetch(`/api/dokumente/${id}/erkennen`)
    .then(a => (a.ok ? a.json() : Promise.reject(new Error('erkennen'))))
    .then(w => {
      if (!w || !kasten.isConnected) return;
      const html = kiAusleseHtml(w);
      if (!html) return;
      kasten.innerHTML = html;
      kasten.hidden = false;
    })
    .catch(() => {});
}

/**
 * Füllt ein Element mit allen Seiten eines Belegs als serverseitig gerenderten
 * Bildern (`/seiten` sagt wie viele, `/vorschau?seite=i` liefert Blatt i,
 * 0-basiert). `basis` ist die Dokument-URL OHNE `/inhalt`. Gibt das Array der
 * erzeugten Object-URLs zurück — der Aufrufer gibt sie beim Schließen frei.
 * Wiederverwendbar: die Beleg-Ansicht wie auch die Eintrags-Detailansicht
 * (objekt.html, CCCXIII) zeigen darüber dasselbe PDF.
 */
export function belegSeitenLaden(basis, flaeche, titel = 'Beleg', tabUrl = '') {
  const adressen = [];
  flaeche.innerHTML = '<div class="beleg-blatt lade">Beleg wird geholt …</div>';

  const seiteBild = (i) => fetch(`${basis}/vorschau?seite=${i}`)
    .then(a => { if (!a.ok) throw new Error('seite'); return a.blob(); })
    .then(blob => {
      const adr = URL.createObjectURL(blob);
      adressen.push(adr);
      const bild = document.createElement('img');
      bild.className = 'beleg-bild';
      bild.alt = `${titel} – Seite ${i + 1}`;
      bild.src = adr;
      return bild;
    });

  fetch(`${basis}/seiten`)
    .then(r => (r.ok ? r.json() : { seiten: 1 }))
    .then(d => (d && typeof d.seiten === 'number') ? d.seiten : 1)
    .catch(() => 1)
    .then(async (anzahl) => {
      if (anzahl === 0) throw new Error('keine-vorschau');   // xlsx/docx u. Ä.
      // Erste Seite zuerst — klappt die nicht, greift der Fallback. Danach die
      // weiteren Blätter in Reihenfolge nachladen (Platz sofort, Bild folgt).
      const erste = await seiteBild(0);
      flaeche.innerHTML = '';
      flaeche.appendChild(erste);
      for (let i = 1; i < anzahl; i++) {
        const platz = document.createElement('img');
        platz.className = 'beleg-bild';
        platz.alt = `${titel} – Seite ${i + 1}`;
        flaeche.appendChild(platz);
        fetch(`${basis}/vorschau?seite=${i}`)
          .then(a => (a.ok ? a.blob() : Promise.reject(a)))
          .then(blob => { const adr = URL.createObjectURL(blob); adressen.push(adr); platz.src = adr; })
          .catch(() => platz.remove());
      }
    })
    .catch(() => {
      flaeche.innerHTML = '<div class="beleg-blatt leer">Für diese Datei gibt '
        + 'es keine Bildvorschau.'
        + (tabUrl ? '<br><a class="beleg-tab" href="' + sicher(tabUrl)
            + '" target="_blank" rel="noopener">Im neuen Tab öffnen ↗</a>' : '')
        + '</div>';
    });

  return adressen;
}

const sicher = s => String(s ?? '')
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

/**
 * Rückfrage mit mehreren Wegen. `optionen` ist [{wert, text, gefahr, leise}];
 * der erste Eintrag ist der Hauptweg. Liefert den `wert` des Gewählten oder
 * `null` beim Abbrechen.
 */
export function wahl(titel, text, optionen) {
  return new Promise(fertig => {
    const knoepfe = optionen.map((o, i) => `
      <button class="btn ${o.gefahr ? 'gefahr' : (i > 0 || o.leise ? 'leise' : '')}"
              data-wahl="${sicher(o.wert)}"
              ${i > 0 ? 'style="margin-top:8px"' : ''}>${sicher(o.text)}</button>`);
    const dlg = baueDialog(`
      <div class="dt">${sicher(titel)}</div>
      <p>${sicher(text)}</p>
      ${knoepfe.join('')}
      <button class="btn leise" style="margin-top:8px" data-nein>Abbrechen</button>`);

    dlg.addEventListener('click', e => {
      const knopf = e.target.closest('[data-wahl]');
      if (knopf) { fertig(knopf.dataset.wahl); dlg.close(); }
      else if (e.target.closest('[data-nein]')) { fertig(null); dlg.close(); }
    });
    dlg.addEventListener('cancel', () => fertig(null));
  });
}

/** Rückfrage mit zwei Knöpfen. Liefert true, wenn bestätigt wurde. */
export async function frage(titel, text,
                            { knopf = 'Weiter', gefahr = false } = {}) {
  return await wahl(titel, text, [{ wert: 'ja', text: knopf, gefahr }]) === 'ja';
}

/**
 * Rückfrage, die man nicht wegklicken kann: der Griff muss ganz nach rechts
 * geschoben werden. Ein versehentlicher Doppelklick löst nichts aus.
 */
export function schiebeFrage(titel, text, label = 'Zum Löschen schieben') {
  return new Promise(fertig => {
    const dlg = baueDialog(`
      <div class="dt">${sicher(titel)}</div>
      <p>${sicher(text)}</p>
      <div class="schieber" role="button" tabindex="0"
           aria-label="${sicher(label)} — mit den Pfeiltasten nach rechts oder
                        mit der Eingabetaste bestätigen">
        <span class="sl">${sicher(label)}</span>
        <span class="griff" aria-hidden="true">›</span>
      </div>
      <button class="btn leise" data-nein>Abbrechen</button>`);

    const bahn = dlg.querySelector('.schieber');
    const griff = dlg.querySelector('.griff');
    let zieht = false;
    let weg = 0;

    const strecke = () => bahn.clientWidth - griff.offsetWidth - 8;
    const setze = px => {
      weg = Math.max(0, Math.min(strecke(), px));
      griff.style.transform = `translateX(${weg}px)`;
      bahn.style.setProperty('--anteil', (weg / strecke()).toFixed(3));
    };
    const zurueck = () => { griff.style.transition = 'transform .2s'; setze(0);
                            setTimeout(() => { griff.style.transition = ''; }, 220); };

    const ausloesen = () => {
      bahn.classList.add('fertig');
      fertig(true);
      setTimeout(() => dlg.close(), 220);
    };

    // Bewusst ohne setPointerCapture: beim zweiten Zug hintereinander
    // verliert der Griff die Erfassung, und der Regler bleibt auf halbem Weg
    // stehen. Am Fenster zu lauschen ist verlaesslich — auch auf dem iPhone.
    let anfang = 0;

    const bewegt = e => setze(e.clientX - anfang);
    const losgelassen = () => {
      if (!zieht) return;
      zieht = false;
      window.removeEventListener('pointermove', bewegt);
      window.removeEventListener('pointerup', losgelassen);
      window.removeEventListener('pointercancel', losgelassen);
      // Knapp vor dem Ende zählt auch — sonst wird es zur Geduldsprobe.
      if (weg >= strecke() - 4) ausloesen(); else zurueck();
    };

    griff.addEventListener('pointerdown', e => {
      e.preventDefault();
      zieht = true;
      anfang = e.clientX - weg;
      window.addEventListener('pointermove', bewegt);
      window.addEventListener('pointerup', losgelassen);
      window.addEventListener('pointercancel', losgelassen);
    });

    // Ohne Zeigegerät: Pfeiltaste nach rechts oder Eingabetaste
    bahn.addEventListener('keydown', e => {
      if (e.key === 'ArrowRight') { e.preventDefault(); setze(weg + strecke() / 4); }
      else if (e.key === 'ArrowLeft') { e.preventDefault(); setze(weg - strecke() / 4); }
      else if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); ausloesen(); }
      if (weg >= strecke() - 4) ausloesen();
    });

    dlg.querySelector('[data-nein]').addEventListener('click', () => {
      fertig(false); dlg.close();
    });
    dlg.addEventListener('cancel', () => fertig(false));
  });
}

export const fristText = tage =>
  tage == null ? null : tage < 0 ? `${Math.abs(tage)} T über Frist` : `Frist in ${tage} T`;

/* ---- CCXL: kontextsensitive Hilfe (?-Icon + Lexikon-Popover) -------------
   Ein kleines, unauffälliges ?-Icon neben echten Fachbegriff-Feldern. Beim
   Antippen öffnet ein Popover mit der Kurzerklärung aus dem Lexikon und einem
   Link in den vollen Eintrag.

   Die Wissensbasis (`lexikon-daten.js`) wird bewusst erst beim ersten Öffnen
   dynamisch geladen — sonst zöge jede Seite, die nur ein Formular zeigt, die
   ganze Datei mit. Das Icon selbst entsteht ohne die Daten; gebraucht werden
   sie erst, wenn wirklich jemand fragt. */

let lexikonDaten = null;            // Cache des dynamischen Imports (Promise)
function ladeLexikon() {
  if (!lexikonDaten) lexikonDaten = import('./lexikon-daten.js');
  return lexikonDaten;
}

// feather „help-circle" — flacher Strich-Stil wie die übrigen Icons.
const HILFE_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
    stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
    aria-hidden="true"><circle cx="12" cy="12" r="10"/>
    <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/>
    <line x1="12" y1="17" x2="12.01" y2="17"/></svg>`;

const HILFE_STIL = `
  .immo-hilfe{display:inline-flex;align-items:center;justify-content:center;
    width:44px;height:44px;margin:-12px -8px -12px 0;padding:0;border:none;
    background:none;color:var(--soft,#5A6B70);cursor:pointer;vertical-align:middle;
    border-radius:50%;-webkit-tap-highlight-color:transparent;flex:none}
  .immo-hilfe svg{width:16px;height:16px;display:block}
  .immo-hilfe:hover{color:var(--teal,#0F6E5C)}
  .immo-hilfe:focus-visible{outline:2px solid var(--teal,#0F6E5C);outline-offset:2px}
  .immo-lx-overlay{position:fixed;inset:0;z-index:1200;background:transparent}
  .immo-lx-card{position:fixed;z-index:1201;background:var(--sheet,#fff);
    border-radius:14px;box-shadow:0 22px 55px -14px rgba(22,38,44,.45);
    padding:16px 18px;width:300px;max-width:calc(100vw - 24px);
    font-family:var(--body,system-ui);color:var(--ink,#16262C)}
  .immo-lx-titel{font:700 15px var(--disp,var(--body));letter-spacing:-.01em;
    margin-bottom:6px}
  .immo-lx-kurz{font:400 13px/1.5 var(--body,system-ui);
    color:var(--ink,#16262C);margin:0 0 12px}
  .immo-lx-mehr{display:inline-block;min-height:36px;line-height:36px;
    font:600 12.5px var(--disp,var(--body));color:var(--teal-d,#0B5648);
    text-decoration:none}
  .immo-lx-mehr:hover{text-decoration:underline}
  @media (max-width:700px){
    .immo-lx-overlay.sheet{background:rgba(22,38,44,.35)}
    .immo-lx-card.sheet{left:0;right:0;bottom:0;top:auto;width:auto;
      max-width:none;border-radius:18px 18px 0 0;
      padding:20px 20px calc(20px + env(safe-area-inset-bottom));
      animation:immo-lx-auf .18s ease-out}
    .immo-lx-mehr{min-height:44px;line-height:44px}
  }
  @keyframes immo-lx-auf{from{transform:translateY(100%)}to{transform:translateY(0)}}`;

function installHilfeStil() {
  if (document.getElementById('immo-hilfe-stil')) return;
  const s = document.createElement('style');
  s.id = 'immo-hilfe-stil';
  s.textContent = HILFE_STIL;
  document.head.appendChild(s);
}

let hilfeOffen = null;
// Escape schliesst zuerst nur das Popover — und nicht gleich den Dialog
// darunter mit. Deshalb in der Capture-Phase abgefangen und die
// Standardaktion (Dialog schliessen) unterbunden, solange ein Popover offen ist.
function hilfeEsc(e) {
  if (e.key !== 'Escape' || !hilfeOffen) return;
  e.preventDefault();
  e.stopPropagation();
  hilfeSchliessen();
}
function hilfeSchliessen() {
  if (!hilfeOffen) return;
  document.removeEventListener('keydown', hilfeEsc, true);
  hilfeOffen.remove();
  hilfeOffen = null;
}

function zeigePopover(anker, eintrag) {
  hilfeSchliessen();
  const sheet = window.matchMedia('(max-width:700px)').matches;
  const overlay = document.createElement('div');
  overlay.className = 'immo-lx-overlay' + (sheet ? ' sheet' : '');
  const card = document.createElement('div');
  card.className = 'immo-lx-card' + (sheet ? ' sheet' : '');
  card.innerHTML = `
    <div class="immo-lx-titel">${sicher(eintrag.begriff)}</div>
    <p class="immo-lx-kurz">${sicher(eintrag.kurz)}</p>
    <a class="immo-lx-mehr" href="lexikon.html#${encodeURIComponent(eintrag.id)}"
       >Mehr im Lexikon →</a>`;
  overlay.appendChild(card);
  // Sitzt das Icon in einem modalen <dialog>, liegt der ganze Dialog in der
  // Top-Layer — ein an <body> gehängtes Popover verschwände dahinter. Deshalb
  // wird es in den offenen Dialog gehängt, sonst an <body>.
  (anker.closest('dialog[open]') || document.body).appendChild(overlay);

  // Auf dem Desktop dockt die Karte unter dem Icon an — und klappt darüber,
  // wenn unten kein Platz ist. Am Rand wird sie ins Fenster gezogen.
  if (!sheet) {
    const r = anker.getBoundingClientRect();
    const cw = card.offsetWidth, ch = card.offsetHeight;
    let left = Math.max(12, Math.min(r.left, window.innerWidth - cw - 12));
    let top = r.bottom + 8;
    if (top + ch > window.innerHeight - 12) top = Math.max(12, r.top - ch - 8);
    card.style.left = `${left}px`;
    card.style.top = `${top}px`;
  }

  overlay.addEventListener('click', e => { if (e.target === overlay) hilfeSchliessen(); });
  document.addEventListener('keydown', hilfeEsc, true);
  hilfeOffen = overlay;
  card.querySelector('.immo-lx-mehr').focus();
}

/**
 * Ein ?-Icon-Element zu einem Lexikon-Begriff. Klick öffnet das Popover.
 * Robust: Fehlt der Begriff in der Wissensbasis, verschwindet das Icon beim
 * ersten Antippen lautlos, statt einen Fehler zu werfen.
 */
export function hilfe(begriffId) {
  installHilfeStil();
  const b = document.createElement('button');
  b.type = 'button';
  b.className = 'immo-hilfe';
  b.dataset.begriff = begriffId;
  b.setAttribute('aria-label', 'Erklärung anzeigen');
  b.innerHTML = HILFE_ICON;
  b.addEventListener('click', e => {
    e.preventDefault();
    e.stopPropagation();
    ladeLexikon()
      .then(mod => {
        const eintrag = (mod.BEGRIFFE || []).find(x => x.id === begriffId);
        if (!eintrag) { b.remove(); return; }   // (noch) kein Eintrag → Icon weg
        zeigePopover(b, eintrag);
      })
      .catch(() => { /* Wissensbasis nicht ladbar — dann eben still */ });
  });
  return b;
}

/**
 * Ersetzt alle Platzhalter `[data-hilfe="<id>"]` unterhalb von `root` durch
 * ein ?-Icon. So bleibt das Markup der Seiten schlicht — sie setzen nur den
 * Platzhalter, das Icon baut diese Stelle.
 */
export function installHilfe(root = document) {
  root.querySelectorAll('[data-hilfe]').forEach(halter => {
    const id = halter.getAttribute('data-hilfe');
    if (id) halter.replaceWith(hilfe(id));
  });
}
