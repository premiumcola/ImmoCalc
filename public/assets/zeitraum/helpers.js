/* zeitraum/helpers.js — Formatter, kleine Werkzeuge, Chip- & Beleg-Renderer,
   Zähler-Verbrauchs- und Fortschritts-Rechnungen.

   Alles, was mehr als ein Topic braucht (Wasser, Strom, Heizöl, Checkliste
   greifen alle darauf zurück) und keine eigene größere Einheit ergibt. */

import { eur, esc, fristKlasse, zahlAus } from '../immo.js';
import * as state from './state.js';
import { VKEY_IKON } from './icons.js';
import {
  normUml, wasserArt, zaehlerNameZuKostenart,
  istWasserSammel, istWasserKostenart, istStromPos, istStromKettePos,
  istHeizoelSammel, istWarmwasserPos, istHeizwaermePos,
  istImDetailPopup,
} from './modell.js';

/* ---------- Formatter --------------------------------------------------- */

/* Wasser als m³ (deutsch, bis 2 Nachkommastellen). */
export const m3 = n => `${(n ?? 0).toLocaleString('de-DE', { maximumFractionDigits: 2 })} m³`;

/* Zahlen mit bis zu 3 Nachkommastellen (Standard-Anzeige von Ständen). */
export const zahl = n => (n ?? 0).toLocaleString('de-DE', { maximumFractionDigits: 3 });

/* Kurzes deutsches Datum aus ISO (für die Öl-Lieferungsliste). */
export const _isoKurz = iso => iso ? new Date(iso).toLocaleDateString('de-DE') : '';

/* Der Verbrauch im Chip auf ganze Einheiten gerundet. */
export const chipZahl = n => Math.round(n || 0).toLocaleString('de-DE');
/* Liter kurz als „l"; m³/kWh bleiben, wie sie sind. */
export const chipEinheit = e => (e === 'Liter' ? 'l' : e);

export const prozentText = (wert, summe) =>
  summe > 0 ? `${(Number(wert || 0) / summe * 100).toFixed(1)} %` : '—';

/* N29 — Monatsangabe für die Aufteilung: ganze Zahl, wo es aufgeht (12),
   sonst eine Nachkommastelle mit Komma (6,5). */
export const monatText = n => {
  const r = Math.round(n);
  return Math.abs(n - r) < 0.05 ? String(r) : n.toFixed(1).replace('.', ',');
};

/* Der Dateiname als kurze Chip-Beschriftung. */
export const kurzBeleg = name => (name || '')
  .replace(/\.[^.]+$/, '')
  .replace(/^\d{4}(-\d{2})?[_-]/, '')
  .replace(/_-?\d[\d.,]*\s*€$/, '')
  .replace(/[_-]+/g, ' ')
  .trim() || (name || 'Beleg');

/* N288 — die EINE Weiche, durch die in diesem Ordner jede Zahl aus einem
 * Eingabefeld gelesen wird. Die deutsche Regel selbst steht ausschliesslich in
 * `zahlAus()` (immo.js) und wird hier nur durchgereicht.
 *
 * Zwei Arten von Feldern, zwei Leser — und beide Verwechslungen kosten den
 * Faktor 1000 in einer echten Abrechnung:
 *
 *   `<input type="number">`  Der Browser normalisiert selbst: Punkt ist immer
 *     das Dezimaltrennzeichen, Tausenderpunkte gibt es nie. Ein getipptes
 *     „8,205" steht als `"8.205"` in `.value` — `zahlAus` läse daraus 8205.
 *     Also liest hier `Number()`.
 *   Alles andere (`type="text"` mit `inputmode="decimal"`, rohe Texte)
 *     enthält, was der Nutzer wörtlich getippt hat: „1.250" sind 1250,
 *     „1.250,50" sind 1250,5. Das kann nur `zahlAus`.
 *
 * Bewusst über `el.value`, nie über `el.dataset.wert`: in diesem Ordner trägt
 * `data-wert` den ZULETZT GESPEICHERTEN Wert (Änderungsvergleich), nicht die
 * rohe Eingabe wie bei den Feldern aus `eingabe.js`.
 *
 * Leeres Feld und Unsinn ergeben `null`.
 */
export function feldZahl(el) {
  const roh = String((typeof el === 'string' ? el : el?.value) ?? '').trim();
  if (roh === '') return null;
  if (el && typeof el === 'object' && el.type === 'number') {
    const n = Number(roh);
    return Number.isFinite(n) ? n : null;
  }
  return zahlAus(roh);
}

/* Der Zählerstand braucht eine Unterscheidung mehr: `null` heisst „nichts
   eingetragen", `NaN` heisst „Unsinn eingetragen" — das eine wird still
   übergangen, das andere abgelehnt. Sonst dieselbe Weiche.
   (Die alte Fassung strich hier alle Punkte: aus dem Stand „12.5" wurde 125.) */
export function standAusFeld(el) {
  if (String(el?.value ?? '').trim() === '') return null;
  const n = feldZahl(el);
  return n == null ? NaN : n;
}

/* Die Zeile, zu der ein Eingabefeld gehört: die Karten-Zeile der
   Zählerstände (`.zu-zeile`) oder — in der Strommaske (N120) — der <tr>. */
export const zeilenBox = el => el?.closest('.zu-zeile, tr');

/* SHA-1 einer Datei als Hex — die Prüfsumme, mit der der Server erkennt,
   ob die exakt gleiche Datei schon in der Nextcloud liegt (CCCLXXXVI c). */
export async function sha1Hex(datei) {
  const hash = await crypto.subtle.digest('SHA-1', await datei.arrayBuffer());
  return [...new Uint8Array(hash)].map(b => b.toString(16).padStart(2, '0')).join('');
}

/* ---------- Rollen, Chooser, Metadaten ---------------------------------- */

export const schluesselMeta = wert =>
  (state.schluessel?.schluessel || []).find(s => s.wert === wert) || null;

/* N77b — nur echte, an der NK teilnehmende Immobilien-Einheiten. */
export function alleEinheiten() {
  return [...new Set((state.objektEinheiten || []).filter(Boolean))];
}

/* Die Einheiten des Objekts samt der Partei, die einen Sonderposten dort
   tragen würde — Grundlage: die Schlüssel-Vorschau. */
export function sonderEinheiten() {
  const map = new Map();
  for (const p of (state.schluessel?.parteien || [])) {
    if (!p.einheit) continue;
    if (!map.has(p.einheit)) map.set(p.einheit, new Set());
    map.get(p.einheit).add(p.partei);
  }
  return [...map.entries()].map(([einheit, parteien]) =>
    ({ einheit, parteien: [...parteien] }));
}

/* ---------- Zähler-Bloecke & Labels ------------------------------------- */

export function zaehlerEinheiten(z) {
  if (Array.isArray(z.einheiten) && z.einheiten.length) return z.einheiten;
  return z.einheit_bezug ? [z.einheit_bezug] : [];
}

/* Kostenblock aus Kostenart/Name — ohne Kontext. */
export function zaehlerBlockBasis(z) {
  if (z.kostenblock && state.KOSTENBLOCK_ORDER.includes(z.kostenblock)) return z.kostenblock;
  const n = normUml(z.kostenart || z.name || '');
  if (n.includes('wasser') || n.includes('niederschlag') || n.includes('entwaesser'))
    return 'Wasser';
  if (n.includes('heiz') || n.includes('waerme') || n.includes('gas')
      || n.includes('oel') || n.includes('brennstoff')) return 'Heizung';
  if (n.includes('strom') || n.includes('beleucht')) return 'Strom';
  return '';
}

/* Kostenblock je Zähler-id, kontextbewusst (Unterzähler erbt vom Hauptzähler). */
export function zaehlerBloecke(zaehler) {
  const byId = new Map(zaehler.map(z => [z.id, z]));
  const cache = new Map();
  const block = (z, tiefe = 0) => {
    if (cache.has(z.id)) return cache.get(z.id);
    cache.set(z.id, 'Sonstige');                       // Zyklus-Schutz
    let b = zaehlerBlockBasis(z);
    if (!b && z.hauptzaehler_id && byId.has(z.hauptzaehler_id) && tiefe < 8) {
      b = block(byId.get(z.hauptzaehler_id), tiefe + 1);
    }
    b = state.KOSTENBLOCK_ORDER.includes(b) ? b : 'Sonstige';
    cache.set(z.id, b);
    return b;
  };
  const map = new Map();
  for (const z of zaehler) map.set(z.id, block(z));
  return map;
}

/* N342 — innerhalb des Heizungs-Kostenblocks noch einmal nach Art: Heizöl
   (der Liter-Zähler bleibt bei der Öl-Rechnung), Warmwasser (Warmwasser-
   mengenzähler) und Heizkörper & Wärmemenge (Heizkostenverteiler +
   Wärmemengenzähler) — dieselbe Einteilung wie im Zähler-Konfigurator
   (`zaehler-konfig.js`), hier geteilt, damit beide Stellen nicht
   auseinanderlaufen. */
export function heizBereich(z) {
  const ka = normUml(z.kostenart || '');
  if (ka.includes('heizoel') || ka.includes('oel')) return 'Heizöl';
  if (ka.includes('warmwasser')) return 'Warmwasser';
  return 'Heizkörper & Wärmemenge';
}

/* N68 — generische Anzeigenamen je Zähler-id. */
export function generischeLabels(zaehler) {
  const map = new Map();
  // N101 — „WG" ist überholt: das Haupthaus sind zwei Wohnungen.
  for (const z of zaehler) {
    if (/\bWG\b/.test(z.name || '')) {
      map.set(z.id, (z.name || '').replace(/\bWG\b/g, 'Haupthaus'));
    }
  }
  let wm = 0;
  for (const z of zaehler) {
    if (!z.hauptzaehler_id || z.typ === 'rest') continue;
    const art = wasserArt(z);
    if (art === 'Waschmaschine') map.set(z.id, `Waschmaschine ${++wm}`);
    else if (art === 'Kaltwasser') map.set(z.id, 'Kaltwasserzähler');
    else if (art === 'Warmwasser') map.set(z.id, 'Warmwasserzähler');
    else if (art === 'Gartenwasser') map.set(z.id, 'Gartenwasser');
  }
  return map;
}

/* ---------- Chip-Karte (abgelesener Verbrauch je Kostenart) ------------ */

export function baueChipMap() {
  const map = new Map();
  const alle = state.ablesungMaske?.zaehler || [];
  // N101 — nur GESAMT-Zähler zählen (die ohne eigenen Hauptzähler).
  const hat = new Set(alle.filter(z => !z.hauptzaehler_id && z.verbrauch != null)
    .map(z => z.kostenart || zaehlerNameZuKostenart(z.name)).filter(Boolean));
  for (const z of alle) {
    if (z.verbrauch == null) continue;
    const ziel = z.kostenart || zaehlerNameZuKostenart(z.name);
    if (!ziel) continue;
    // N107 - Gartenwasser ist ein TEIL des Gesamtverbrauchs.
    if (wasserArt(z) === 'Gartenwasser') continue;
    if (hat.has(ziel) ? !!z.hauptzaehler_id : z.typ === 'rest') continue;
    const cur = map.get(ziel) || { verbrauch: 0, messeinheit: z.messeinheit };
    cur.verbrauch += z.verbrauch;
    map.set(ziel, cur);
  }
  return map;
}

/* ---------- Strom-Mengen (extern/eigen) --------------------------------- */

/* N122 — die Mengen der Strom-Positionen: extern (Netzbezug) + intern (PV). */
export function stromMengen() {
  let extern = 0;
  let eigen = 0;
  for (const k of (state.daten?.checkliste || [])) {
    if (!istStromPos(k) || !(k.menge > 0)) continue;
    if (k.herkunft === 'extern') extern += k.menge;
    else if (k.herkunft === 'eigen') eigen += k.menge;
  }
  const gesamt = extern + eigen;
  return { extern, eigen, gesamt, quote: gesamt > 0 ? eigen / gesamt : null };
}

/* N157 — die Aufschlüsselung für den Kopf: bevorzugt aus der Stromkette. */
export function stromAufteilung() {
  const s = state.stromketteDaten?.schritt1;
  if (s && s.gesamt_kwh > 0) {
    const extern = s.netz?.kwh || 0;
    const eigen = (s.pv?.kwh || 0) + (s.akku?.kwh || 0);
    return { gesamt: s.gesamt_kwh, extern, eigen,
             quote: s.gesamt_kwh > 0 ? eigen / s.gesamt_kwh : null };
  }
  return stromMengen();
}

/* Die Strom-Zähler (alles in kWh) in fachlicher Ordnung. */
export function stromStruktur(zaehler = null) {
  const liste = (zaehler || state.ablesungMaske?.zaehler || [])
    .filter(z => (z.messeinheit || '') === 'kWh');
  const hauptIds = new Set(liste.filter(z => z.hauptzaehler_id)
    .map(z => z.hauptzaehler_id));
  const gesamt = liste.find(z => z.typ !== 'rest' && hauptIds.has(z.id))
    || liste.find(z => z.typ !== 'rest' && !z.hauptzaehler_id) || null;
  const unter = liste.filter(z => z.typ !== 'rest' && z.id !== gesamt?.id);
  const rest = liste.find(z => z.typ === 'rest') || null;
  return { liste, gesamt, unter, rest };
}

/* Die eigene Menge einer Strom-Position — extern gedeckt vs. intern. */
export function stromChipsHtml(k) {
  if (!(k.menge > 0)) return '';
  const eigen = k.herkunft === 'eigen';
  return `<span class="mchip ${eigen ? 'intern' : 'extern'}">${chipZahl(k.menge)}
    kWh ${eigen ? 'intern' : 'extern'}</span>`;
}

/* N157 — der Kopf der Strom-Position: Gesamtverbrauch + Aufteilung. */
export function stromKopfHtml(k) {
  if (!istStromKettePos(k)) return '';
  const m = stromAufteilung();
  if (!(m.gesamt > 0)) return '';
  // N258(e) — in der zugeklappten Übersicht nur noch Gesamtmenge und Autarkie.
  // „extern" und „eigen" sind die Aufschlüsselung derselben Zahl; sie stehen
  // eine Reihe tiefer in der Stromkette und machten die Zeile hier nur voll.
  const teile = [`<span class="mchip" title="Verbrauch der Periode">${
    chipZahl(m.gesamt)}&nbsp;kWh gesamt</span>`];
  if (m.quote != null && m.extern > 0 && m.eigen > 0) {
    teile.push(`<span class="mchip intern" title="Anteil aus der eigenen Anlage
      am Gesamtverbrauch">${Math.round(m.quote * 100)}&nbsp;% autark</span>`);
  }
  return `<span class="mchips">${teile.join('')}</span>`;
}

/* N122 — Verbrauch & Herkunft an einer Strom-Position (Netzbezug/eigene Anlage). */
export function stromPosFeldHtml(k) {
  if (!istStromPos(k) || !k.position_id) return '';
  const bearbeitbar = state.daten?.status === 'in Arbeit';
  const wert = k.menge > 0 ? zahl(k.menge) : '';
  const knopf = (h, text) => `<button type="button"
      class="wd-sb${k.herkunft === h ? ' an' : ''}" data-herkunft="${h}"
      data-herkunft-pid="${k.position_id}"
      aria-pressed="${k.herkunft === h}">${text}</button>`;
  const preis = k.preis_je_menge
    ? `<span class="sp-hint">Das sind ${(k.preis_je_menge * 100)
        .toLocaleString('de-DE', { maximumFractionDigits: 2 })} ct/kWh.</span>` : '';
  // Plausibilität gegen die Zähler.
  let abgleich = '';
  const gesamtZaehler = stromStruktur().gesamt?.verbrauch;
  if (k.herkunft === 'eigen' && k.menge > 0 && gesamtZaehler != null) {
    const erwartet = gesamtZaehler - stromMengen().extern;
    if (Math.abs(erwartet - k.menge) > Math.max(1, Math.abs(erwartet) * 0.05)) {
      abgleich = `<span class="sp-hint">Die Zähler weisen ${zahl(gesamtZaehler)} kWh
        aus; abzüglich des Netzbezugs wären ${zahl(Math.round(erwartet * 100) / 100)}
        kWh aus der eigenen Anlage zu erwarten.</span>`;
    }
  }
  const felder = bearbeitbar
    ? `<div class="sp-zeile">
        <input type="text" inputmode="decimal" data-strom-menge="${k.position_id}"
          value="${wert}" placeholder="kWh" aria-label="Verbrauch in kWh">
        <span class="sp-eh">kWh</span>
        ${knopf('extern', 'Netzbezug')}${knopf('eigen', 'eigene Anlage')}
      </div>`
    : `<div class="sp-zeile"><span class="sp-fest">${wert ? `${wert} kWh` : '—'}
        ${k.herkunft === 'eigen' ? '· eigene Anlage'
          : (k.herkunft === 'extern' ? '· Netzbezug' : '')}</span></div>`;
  return `<div class="strompos"><label>Verbrauch &amp; Herkunft</label>
    ${felder}${preis}${abgleich}</div>`;
}

/* Das Panel, in das `fuelleStromketteInline` die drei Schritte lädt. */
export const stromKetteHtml = k => istStromKettePos(k)
  ? `<div class="sk-inline" data-strom-kette="${state.zid}">
      <div class="wd-lade">Stromkette wird geladen …</div></div>` : '';

/* Der runde Zähler-Chip vor dem Namen. */
export function chipHtml(k) {
  // N122 — an Strom-Positionen die erfasste Menge (extern/intern).
  if (istStromPos(k)) {
    // N157 — Kettenzeile hat volle Aufschlüsselung eine Reihe tiefer.
    if (istStromKettePos(k) && stromAufteilung().gesamt > 0) return '';
    const strom = stromChipsHtml(k);
    if (strom) return strom;
  }
  const c = state.chipMap.get(k.kostenart);
  if (!c) return '';
  return `<span class="mchip" title="Zählerstand · abgelesener Verbrauch im ` +
    `Zeitraum — nicht die Verteilungsgewichte">${chipZahl(c.verbrauch)}&nbsp;${
      esc(chipEinheit(c.messeinheit))}</span>`;
}

/* Verteilungsschlüssel als ruhiges Wort. */
export function schluesselWort(k) {
  if (!k.position_id) return '';
  if (k.nur_einheit) return '1 Einheit';
  if (!k.schluessel) return '';
  return schluesselMeta(k.schluessel)?.titel || k.schluessel;
}

/* Verteilungsschlüssel-Chip an der Zeile. */
export function vkeyChip(k) {
  if (istWasserSammel(k) || istStromPos(k)) {
    return `<span class="vkey">${VKEY_IKON.verbrauch || VKEY_IKON.punkt}<span>nach Zählern</span></span>`;
  }
  const wort = schluesselWort(k);
  if (!wort) return '';
  const key = k.nur_einheit ? 'einheiten' : (k.schluessel || '');
  const ikon = VKEY_IKON[key] || VKEY_IKON.punkt;
  const text = k.nur_einheit ? wort : `nach ${wort}`;
  return `<span class="vkey">${ikon}<span>${esc(text)}</span></span>`;
}

/* ---------- Belege ------------------------------------------------------ */

/* Welche Belege zu einer Position gehören (CLXXXIII). */
export function belegeZu(k) {
  if (k.belege?.length) return k.belege;
  const gruppe = (state.daten?.belege_je_art || {})[k.kostenart];
  if (gruppe?.length) return gruppe;
  const stamm = k.kostenart.toLowerCase().split(/[ /]/)[0];
  return (state.daten?.dokumente || []).filter(d =>
    (d.dateiname || '').toLowerCase().includes(stamm));
}

/* N8 — das genaue Belegdatum als DD.MM.YYYY. */
export const belegDatumText = iso => {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || '');
  return m ? `${m[3]}.${m[2]}.${m[1]}` : '';
};

/* `data-name` statt der Beschriftung. */
export const belegLinks = (liste, extra = '', loesbar = false) => `<div class="belege">${liste.map(d => {
  const datum = belegDatumText(d.belegdatum);
  const weg = loesbar
    ? `<button class="beleg-weg" data-beleg-loesen="${d.id}"
        title="Beleg aus dieser Position herausnehmen (Datei bleibt)"
        aria-label="Beleg herausnehmen">×</button>` : '';
  return `<span class="beleg-zeile"><a href="#" data-beleg="${d.id}" data-name="${esc(d.dateiname)}"
      title="${esc(d.pfad)}">PDF · ${esc(d.dateiname)}${
    d.betrag ? ` · ${eur(d.betrag)}` : ''}${
    datum ? `<span class="beleg-datum">${datum}</span>` : ''}</a>${weg}</span>`;
}).join('')}${extra}</div>`;

/* N288 — die Belege, die mit diesem im selben Kasten stehen. Das Beleg-Fenster
   blättert damit zwischen ihnen (fünfter Parameter von `belegAnsehen`), statt
   für jeden Beleg zurück in die Liste zu zwingen. Gesucht wird der Kasten, in
   dem der Link sitzt; steht er dort allein, gibt es nichts zu blättern. */
export function belegGeschwister(link) {
  const kasten = link?.closest(
    '.belege, .zusatzbelege, .sk-belege, .weg-datei, .anh-gruppe');
  const links = [...(kasten?.querySelectorAll('[data-beleg]') || [])];
  if (links.length < 2) return null;
  return links.map(a => ({
    id: Number(a.dataset.beleg),
    dateiname: a.dataset.name || a.textContent.replace(/^PDF · /, '').trim(),
    pfad: a.dataset.pfad || a.getAttribute('title') || '',
  }));
}

/* Woraus der Betrag besteht. Vier Abschlagsrechnungen ergeben eine Position. */
export function zusammensetzungHtml(k) {
  if (!k.beleg_summe) return '';
  const anzahl = (k.belege || []).length;
  const teile = [`${anzahl} ${anzahl === 1 ? 'Beleg' : 'Belegen'} · ${eur(k.beleg_summe)}`];
  if (k.handanteil) teile.push(`${eur(k.handanteil)} von Hand`);
  return `<div class="zsumme">Summe aus ${teile.join(' · ')}</div>`;
}

export function belegeHtml(k, extra = '') {
  const alle = belegeZu(k);
  if (!alle.length) {
    return `<div class="belege"><span class="kein">Kein Beleg hinterlegt —
      im Eingang lässt sich einer übernehmen.</span>${extra}</div>`;
  }
  // N95 — in einer bearbeitbaren Abrechnung lässt sich jeder Beleg wieder lösen.
  return zusammensetzungHtml(k) + belegLinks(alle, extra, state.daten?.status === 'in Arbeit');
}

/* ---------- Vorab-Teilbetrag ------------------------------------------- */

export const vorabAktiv = k => (k.vorab_betrag || 0) > 0 && !!(k.vorab_einheit || '');
export const vorabBrutto = netto => Math.round((Number(netto) || 0) * 1.19 * 100) / 100;
export const bruttoAnzeige = netto => (Number(netto) || 0) > 0
  ? `= ${eur(vorabBrutto(netto))} brutto (19 %)`
  : 'netto eingeben — Brutto rechnet 19 % dazu';

/* ---------- Wasser/Heizöl-Betragsermittlung ---------------------------- */

/* N101 — Summe der drei Wasser-Bestandteile. */
export function wasserGesamtBetrag() {
  return (state.daten?.checkliste || []).reduce((s, k) => {
    const n = normUml(k.kostenart);
    const dazu = istWasserSammel(k) || n.includes('abwasser')
      || n.includes('schmutzwasser') || n.includes('niederschlag');
    return dazu ? s + (k.betrag || 0) : s;
  }, 0);
}

/* N74/N185 — die Wasser-Sammelposition trägt erst eine Rechnung, wenn ein
   Beleg mit Betrag hochgeladen wurde. */
export function wasserHatRechnung(k) {
  return !!(wasserGesamtBetrag() > 0.005 || (k.belege && k.belege.length));
}

/* N208 — die Strom-Kette-Position ist FERTIG, sobald die Kette vollständig
   berechnet UND verteilt ist. */
export function stromKetteVerteilt() {
  const d = state.stromketteDaten;
  if (!d) return false;
  const kon = d.kontrolle || {};
  return kon.stimmt === true && (kon.schritt1_betrag || 0) > 0.005
    && d.schritt1?.vollstaendig !== false;
}

/* N198a — HKV mindestens einer erfasst → Heizkörper-Wärmemenge verteilt. */
export function heizwaermeVerteilt() {
  return (state.heizverteiler || []).length > 0;
}

/* N114/N118/N190 — der WIRKSAME Betrag einer Position. */
export function positionsBetrag(k) {
  if (istWasserSammel(k)) return wasserGesamtBetrag();
  if (k.betrag) return k.betrag;
  if (istHeizoelSammel(k)) return state.heizoelKosten;
  if (istWarmwasserPos(k)) return state.wwKosten;
  if (istHeizwaermePos(k)) return Math.round((state.heizoelKosten - state.wwKosten) * 100) / 100;
  if (istStromKettePos(k) && stromKetteVerteilt())
    return state.stromketteDaten.kontrolle.schritt1_betrag || 0;
  return 0;
}

/* N190 — erledigt heißt: ein Betrag liegt vor (Beleg ODER Berechnung).
   Zwei Ausnahmen, weil ein angezeigter Betrag hier NICHT automatisch heißt,
   dass er auch in der echten Abrechnung zählt (N222 — die Abrechnung zählt
   nur, was als `Kostenposition.status=='erledigt'` persistiert ist):
   - Heizöl & Lieferungen + Heizkörper-Wärmemenge (N198a) sind erst fertig,
     wenn die Wärmemenge wirklich auf Einheiten verteilt ist (HKV erfasst) —
     vorher ist ihr Geld noch nicht auf Einheiten umgelegt, nur als Topf da.
   - Stromkette + Warmwasser werden vollautomatisch berechnet, aber erst beim
     Berechnen auf die Kostenposition zurückgeschrieben (`stromBetragSichern`/
     `warmwasserBetragSichern`) — bis das passiert ist, zeigt `k.erledigt`
     ehrlich „noch nicht wirklich umgelegt" statt eines nur angezeigten Werts. */
export function effektivErledigt(k) {
  if (istHeizwaermePos(k) || istHeizoelSammel(k)) {
    return positionsBetrag(k) > 0.005 && heizwaermeVerteilt();
  }
  if (istStromKettePos(k) || istWarmwasserPos(k)) {
    return !!k.erledigt;
  }
  // N256 — allein der Betrag entscheidet, nicht das gespeicherte Kennzeichen.
  // N238 leitet `Kostenposition.status` beim Schreiben aus dem Betrag ab
  // („erledigt" bei > 0, sonst „offen"), doch Zeilen aus der Zeit davor tragen
  // weiter `status='erledigt'` bei `betrag=0` — die Karte stand grün mit einem
  // Haken und „0 €" da, obwohl nur ein Infobeleg (SEPA-Mandat) daranhing. Der
  // gespeicherte Wert wird deshalb hier nicht mehr geglaubt; `positionsBetrag`
  // deckt auch die berechneten Fälle ab (Wasser-Summe, Heizöl, Warmwasser …).
  return positionsBetrag(k) > 0.005;
}

/* N189 — Fortschritt zählt, was die Checkliste WIRKLICH zeigt. */
export function fortschrittRechnen() {
  let gesamt = 0, fertig = 0;
  for (const k of (state.daten?.checkliste || [])) {
    if (istImDetailPopup(k)) continue;
    const erl = effektivErledigt(k);
    if (k.optional && !erl) continue;
    gesamt++;
    if (erl) fertig++;
  }
  return { fertig, gesamt, summe: state.daten?.fortschritt?.summe || 0 };
}

/* ---------- Kopfzeile & Scrollhilfe ------------------------------------ */

/* N36b — die Frist steht kompakt als Chip oben rechts in der Kopfzeile. */
export function fristChipSetzen() {
  const chip = document.getElementById('fristchip');
  if (!chip) return;
  if (state.daten.status !== 'in Arbeit') {
    chip.className = 'frist-chip an fertig';
    chip.innerHTML = '<span class="d"></span><span>Abgeschlossen</span>';
    return;
  }
  const k = fristKlasse(state.daten.frist_tage);
  const tage = state.daten.frist_tage < 0
    ? `${Math.abs(state.daten.frist_tage)} Tage über` : `noch ${state.daten.frist_tage} Tage`;
  chip.className = `frist-chip an ${k}`;
  chip.innerHTML = `<span class="d"></span><span><span class="flabel">Frist § 556 · </span>${tage}</span>`;
}

/* Rollt `el` auf `oben` px unter den oberen Rand — im richtigen Rollbereich. */
export function rolleUnterDieKopfzeile(el, oben) {
  const delta = el.getBoundingClientRect().top - oben;
  let bereich = el.parentElement;
  while (bereich && bereich !== document.body) {
    const stil = getComputedStyle(bereich);
    if (/(auto|scroll)/.test(stil.overflowY) &&
        bereich.scrollHeight > bereich.clientHeight) break;
    bereich = bereich.parentElement;
  }
  if (bereich && bereich !== document.body) bereich.scrollTop += delta;
  else window.scrollBy(0, delta);
}

/* ---------- Kostenart-Auswahl -------------------------------------------- */

/* CCCLXII — Optionen für den Umhäng-Wähler. */
export function artOptionen(aktuell) {
  const namen = new Set();
  for (const k of (state.daten?.checkliste || [])) if (k.kostenart_id) namen.add(k.kostenart);
  namen.add(aktuell);
  const opts = [...namen].sort((a, b) => a.localeCompare(b, 'de'))
    .map(n => `<option value="${esc(n)}"${n === aktuell ? ' selected' : ''}>${esc(n)}</option>`)
    .join('');
  return opts + '<option value="__neu__">＋ Neue Kostenart …</option>';
}
