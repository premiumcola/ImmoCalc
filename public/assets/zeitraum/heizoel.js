/* zeitraum/heizoel.js — der Öl-Manager: Lieferungen, FIFO-Bewertung,
   §9-Split Warmwasser/Heizung, HKV-Verteilung (N79/N81/N91/N118).

   Wird beim Aufklappen der jeweiligen Position (Heizöl / Warmwasser /
   Heizkörper-Wärmemenge) inline geladen. */

import { api, eur, esc, melde } from '../immo.js';
import * as state from './state.js';
import { wasserArt } from './modell.js';
import {
  zahl, _isoKurz, alleEinheiten, zaehlerEinheiten,
} from './helpers.js';

/* N79 — eine Öl-Lieferung erfassen. */
export async function heizoelHinzufuegen(btn) {
  const box = btn.closest('.ho-neu');
  const datum = box?.querySelector('[data-ho-datum]')?.value;
  const liter = parseFloat(String(box?.querySelector('[data-ho-liter]')?.value || '').replace(',', '.'));
  const wert = parseFloat(String(box?.querySelector('[data-ho-wert]')?.value || '').replace(',', '.'));
  const anf = !!box?.querySelector('[data-ho-anf]')?.checked;
  if (!datum || !(liter > 0)) { melde('Datum und Liter angeben', 'neg'); return; }
  try {
    await api(`/objekte/${encodeURIComponent(state.daten.objekt)}/heizoel`, {
      method: 'POST',
      body: { datum, liter, wert: Number.isFinite(wert) ? wert : 0, ist_anfangsbestand: anf },
    });
    melde('Öl-Lieferung erfasst', 'pos');
    const { zeichnen } = await import('./checkliste.js');
    await zeichnen();
  } catch (fehler) { melde(String(fehler.message || fehler), 'neg'); }
}

/* N79 — eine Öl-Lieferung wieder entfernen. */
export async function heizoelEntfernen(id) {
  try {
    await api(`/heizoel/${id}`, { method: 'DELETE' });
    melde('Lieferung entfernt', 'pos');
    const { zeichnen } = await import('./checkliste.js');
    await zeichnen();
  } catch (fehler) { melde(String(fehler.message || fehler), 'neg'); }
}

/* N81 — einen Heizkörper (HKV) erfassen. */
export async function hkvHinzufuegen(btn) {
  const box = btn.closest('.ho-neu');
  const q = s => box?.querySelector(s);
  const faktor = parseFloat(String(q('[data-hkv-faktor]')?.value || '').replace(',', '.'));
  const stand = parseFloat(String(q('[data-hkv-stand]')?.value || '').replace(',', '.'));
  if (!(faktor > 0)) { melde('Faktor angeben', 'neg'); return; }
  try {
    await api(`/objekte/${encodeURIComponent(state.daten.objekt)}/heizverteiler`, {
      method: 'POST',
      body: {
        einheit: q('[data-hkv-einheit]')?.value || '',
        nummer: q('[data-hkv-nummer]')?.value || '',
        raum: q('[data-hkv-raum]')?.value || '',
        faktor, einheiten_stand: Number.isFinite(stand) ? stand : 0,
      },
    });
    melde('Heizkörper erfasst', 'pos');
    const { zeichnen } = await import('./checkliste.js');
    await zeichnen();
  } catch (fehler) { melde(String(fehler.message || fehler), 'neg'); }
}

export async function hkvEntfernen(id) {
  try {
    await api(`/heizverteiler/${id}`, { method: 'DELETE' });
    melde('Heizkörper entfernt', 'pos');
    const { zeichnen } = await import('./checkliste.js');
    await zeichnen();
  } catch (fehler) { melde(String(fehler.message || fehler), 'neg'); }
}

/* N118 — Warmwassermenge je Einheit aus den Warmwasser-Unterzählern. */
function wwJeEinheit(wasserDetail) {
  const karte = {};
  for (const e of (wasserDetail?.einheiten || [])) {
    const wasserM3 = (e.zeilen || []).filter(z => z.art === 'Warmwasser')
      .reduce((su, z) => su + (z.m3 || 0), 0);
    if (wasserM3 > 0) karte[e.name] = wasserM3;
  }
  if (Object.keys(karte).length) return karte;
  for (const z of (state.ablesungMaske?.zaehler || [])) {
    if (wasserArt(z) !== 'Warmwasser' || !z.hauptzaehler_id) continue;
    const v = z.verbrauch || 0;
    if (!v) continue;
    const ein = zaehlerEinheiten(z).filter(e => alleEinheiten().includes(e));
    if (!ein.length) continue;
    for (const e of ein) karte[e] = (karte[e] || 0) + v / ein.length;
  }
  return karte;
}

/* Warmwasser-Kosten cent-genau verteilen. */
function wwVerteilung(kosten, wasserDetail) {
  const mengen = wwJeEinheit(wasserDetail);
  const namen = Object.keys(mengen);
  const summe = namen.reduce((s, e) => s + mengen[e], 0);
  if (!summe || !kosten) return { mengen, anteile: {}, summe };
  const anteile = {};
  let rest = Math.round(kosten * 100);
  namen.forEach((e, i) => {
    const c = i === namen.length - 1 ? rest
      : Math.round(kosten * 100 * mengen[e] / summe);
    anteile[e] = c / 100;
    rest -= c;
  });
  return { mengen, anteile, summe };
}

/* N79 — Öl-Manager inline. */
export async function fuelleHeizoelInline(el) {
  const slug = encodeURIComponent(state.daten.objekt);
  try {
    const [best, bew, hkv] = await Promise.all([
      api(`/objekte/${slug}/heizoel`),
      api(`/objekte/${slug}/heizoel/bewertung?zeitraum_id=${state.zid}`).catch(() => null),
      api(`/objekte/${slug}/heizverteiler`).catch(() => ({ heizverteiler: [] })),
    ]);
    // N80 — Warmwassermenge (m³) für den §9-Split.
    const zl = state.ablesungMaske?.zaehler || [];
    const wwHaupt = zl.find(z => wasserArt(z) === 'Warmwasser' && !z.hauptzaehler_id);
    const wwVol = wwHaupt?.verbrauch != null ? wwHaupt.verbrauch
      : zl.filter(z => wasserArt(z) === 'Warmwasser' && z.hauptzaehler_id)
          .reduce((s, z) => s + (z.verbrauch || 0), 0);
    let split = null;
    if (bew && bew.verbrauch_kosten > 0) {
      split = await api(`/objekte/${slug}/waerme/split?oel_kosten=${bew.verbrauch_kosten}`
        + `&oel_liter=${bew.verbrauch_liter}&ww_volumen_m3=${wwVol}`).catch(() => null);
    }
    // N118 — Warmwasser-Modus braucht die Wasser-Detailmengen.
    if ((el.dataset.heizModus || 'oel') === 'warmwasser' && !state.wasserDetailCache) {
      state.setWasserDetailCache(await api(`/zeitraeume/${state.zid}/wasser`
        + `?schluessel=${state.wasserSchluessel}`).catch(() => null));
    }
    let verteilung = null;
    if (split && split.heizung_kosten > 0) {
      verteilung = await api(`/objekte/${slug}/heizung/verteilung?kosten=${split.heizung_kosten}`)
        .catch(() => null);
    }
    el.innerHTML = heizoelInhalt(best, bew, hkv, wwVol, split, verteilung,
                                 el.dataset.heizModus || 'oel');
  } catch (fehler) {
    el.innerHTML = `<div class="wd-lade">Heizöl nicht ladbar: ${
      esc(String(fehler.message || fehler))}</div>`;
  }
}

/* Der Öl-Manager als HTML. */
function heizoelInhalt(best, bew, hkv, wwVol, split, verteilung, modus = 'oel') {
  const bearbeitbar = state.daten.status === 'in Arbeit';
  const liefer = (best?.lieferungen || []);
  const kopf = bew && bew.verbrauch_liter != null
    ? `<div class="ho-kpi">
        ${bew.anfang_liter != null ? `<div class="ho-kbox">
          <span class="ho-kl">Bestand zu Periodenbeginn</span>
          <span class="ho-kv">${zahl(bew.anfang_liter)} L · ${eur(bew.anfang_wert)}</span></div>` : ''}
        <div class="ho-kbox"><span class="ho-kl">Verbrauch Periode</span>
          <span class="ho-kv">${zahl(bew.verbrauch_liter)} L</span></div>
        <div class="ho-kbox teal"><span class="ho-kl">Heizkosten (FIFO)</span>
          <span class="ho-kv">${eur(bew.verbrauch_kosten)}</span></div>
        <div class="ho-kbox"><span class="ho-kl">Restbestand am Ende</span>
          <span class="ho-kv">${zahl(bew.rest_liter)} L · ${eur(bew.rest_wert)}</span></div>
      </div>${bew.warnung ? `<div class="ho-warn">▲ ${esc(bew.warnung)}</div>` : ''}`
    : `<div class="ho-warn">Noch keine Öl-Lieferung erfasst — unten anlegen. Der
        Perioden-Verbrauch kommt aus dem Öl-Zähler.</div>`;
  const inPeriode = bew?.lieferungen_periode;
  const sichtbar = Array.isArray(inPeriode)
    ? liefer.filter(l => inPeriode.includes(l.id) || l.ist_anfangsbestand) : liefer;
  const zeilen = sichtbar.length ? sichtbar.map(l => `
    <div class="ho-zeile">
      <span class="ho-dt">${_isoKurz(l.datum)}${l.ist_anfangsbestand
        ? ' <span class="ho-anf">Anfangsbestand — zählt vor der Periode</span>'
        : ''}</span>
      <span class="ho-lit">${zahl(l.liter)} L</span>
      <span class="ho-wert">${eur(l.wert)}</span>
      <span class="ho-pl">${eur(l.preis_liter ?? (l.liter ? l.wert / l.liter : 0))}/L</span>
      ${bearbeitbar ? `<button class="ho-x" data-heizoel-weg="${l.id}"
        aria-label="Lieferung entfernen">×</button>` : ''}
    </div>`).join('') : '';
  const nurPeriode = sichtbar.filter(l => !l.ist_anfangsbestand
    || !Array.isArray(inPeriode) || inPeriode.includes(l.id));
  const bestZeile = sichtbar.length
    ? `<div class="ho-summe">In dieser Periode getankt: <b>${
        zahl(nurPeriode.reduce((s, l) => s + (l.liter || 0), 0))} L</b> · <b>${
        eur(nurPeriode.reduce((s, l) => s + (l.wert || 0), 0))}</b>${
        liefer.length > sichtbar.length
          ? ` · insgesamt erfasst: ${zahl(best.bestand_liter)} L` : ''}</div>` : '';
  const form = bearbeitbar ? `
    <div class="ho-neu">
      <input type="date" data-ho-datum aria-label="Datum" value="${state.daten.ende || ''}">
      <input type="number" step="0.1" data-ho-liter placeholder="Liter" aria-label="Liter">
      <input type="number" step="0.01" data-ho-wert placeholder="€ gesamt" aria-label="Wert €">
      <label class="ho-anfw"><input type="checkbox" data-ho-anf> Anfangsbestand</label>
      <button class="btn" data-heizoel-add>Lieferung hinzufügen</button>
    </div>` : '';
  // N80 — §9-Split Warmwasser vs. Heizung.
  const splitHtml = split ? `<div class="ho-sekt">
      <div class="ho-st">Warmwasser & Heizung <span class="ho-sh">§9: 2,5·V·(t−10)</span></div>
      <div class="ho-kpi">
        <div class="ho-kbox"><span class="ho-kl">Warmwasser-Menge</span>
          <span class="ho-kv">${zahl(wwVol)} m³ · ${zahl(split.ww_kwh)} kWh</span></div>
        <div class="ho-kbox"><span class="ho-kl">Warmwasser-Kosten</span>
          <span class="ho-kv">${eur(split.ww_kosten)}</span></div>
        <div class="ho-kbox teal"><span class="ho-kl">Heizungs-Kosten</span>
          <span class="ho-kv">${eur(split.heizung_kosten)}</span></div>
      </div>${split.warnung ? `<div class="ho-warn">▲ ${esc(split.warnung)}</div>` : ''}
    </div>` : '';
  // N81 — HKV → Heizungs-Anteil je Einheit.
  const hkvListe = (hkv?.heizverteiler || []);
  const vt = verteilung || {};
  const hkvZeilen = hkvListe.length ? hkvListe.map(h => `
    <div class="ho-zeile">
      <span class="ho-dt">${esc(h.nummer || '—')}${h.raum ? ` · ${esc(h.raum)}` : ''}
        ${h.einheit ? `<span class="ho-anf">${esc(h.einheit)}</span>` : ''}</span>
      <span class="ho-lit">Faktor ${zahl(h.faktor)}</span>
      <span class="ho-wert">${zahl(h.einheiten_stand)} Einh.</span>
      ${bearbeitbar ? `<button class="ho-x" data-hkv-weg="${h.id}"
        aria-label="HKV entfernen">×</button>` : ''}
    </div>`).join('') : '';
  const vtZeilen = Object.keys(vt).length ? `<div class="ho-summe">Heizung je Einheit: ${
    Object.entries(vt).map(([e, w]) => `${esc(e)} <b>${eur(w)}</b>`).join(' · ')}</div>` : '';
  const einOpt = alleEinheiten().map(e => `<option value="${esc(e)}">${esc(e)}</option>`).join('');
  const hkvForm = bearbeitbar ? `
    <div class="ho-neu">
      <select data-hkv-einheit aria-label="Einheit"><option value="">Einheit …</option>${einOpt}</select>
      <input type="text" data-hkv-nummer placeholder="HKV-Nr." aria-label="Nummer">
      <input type="text" data-hkv-raum placeholder="Raum" aria-label="Raum">
      <input type="number" step="0.001" data-hkv-faktor placeholder="Faktor" aria-label="Faktor">
      <input type="number" step="0.1" data-hkv-stand placeholder="Einheiten" aria-label="Abgelesene Einheiten">
      <button class="btn" data-hkv-add>Heizkörper hinzufügen</button>
    </div>` : '';
  const hkvHtml = `<div class="ho-sekt">
      <div class="ho-st">Heizungswärme · Heizkostenverteiler</div>
      ${hkvZeilen ? `<div class="ho-liste">${hkvZeilen}</div>${vtZeilen}`
        : '<div class="ho-warn">Noch keine Heizkörper erfasst — je Heizkörper Nummer, Raum, Faktor und die abgelesenen Einheiten anlegen.</div>'}
      ${hkvForm}</div>`;
  // N91 — je Stufe nur ihren Teil zeigen.
  if (modus === 'warmwasser') {
    // N118 — Verteilung der Warmwasser-Kosten auf die Einheiten.
    const wv = wwVerteilung(split?.ww_kosten || 0, state.wasserDetailCache);
    const sp = Object.keys(wv.mengen);
    const wwTab = sp.length ? `<div class="ho-sekt">
        <div class="ho-st">Verteilung auf die Einheiten
          <span class="ho-sh">nach Warmwasser-Zähler</span></div>
        <div class="wd-scroll"><table class="wd-tab"><thead><tr>
          <th>Warmwasser</th>${sp.map(e => `<th>${esc(e)}</th>`).join('')}</tr></thead>
          <tbody>
            <tr><td class="wd-rowh">Menge<small>nach Zähler</small></td>
              ${sp.map(e => `<td>${zahl(wv.mengen[e])} m³</td>`).join('')}</tr>
            <tr><td class="wd-rowh">Kosten<small>anteilig</small></td>
              ${sp.map(e => `<td><b>${eur(wv.anteile[e] || 0)}</b></td>`).join('')}</tr>
          </tbody>
          <tfoot><tr><td class="wd-rowh">Summe</td>
            <td colspan="${sp.length}">${zahl(wv.summe)} m³ · <b>${
              eur(split?.ww_kosten || 0)}</b></td></tr></tfoot>
        </table></div></div>` : '';
    return `<div class="ho-box">${splitHtml
      || '<div class="ho-warn">Noch keine Öl-Kosten erfasst — erst Lieferungen und den Zähler-Endstand bei „Heizöl & Lieferungen" eintragen.</div>'}${wwTab}</div>`;
  }
  if (modus === 'waerme') {
    const kopfW = split ? `<div class="ho-kpi"><div class="ho-kbox teal">
        <span class="ho-kl">Heizungs-Kosten (nach Warmwasser-Abzug)</span>
        <span class="ho-kv">${eur(split.heizung_kosten)}</span></div></div>` : '';
    return `<div class="ho-box">${kopfW}${hkvHtml}</div>`;
  }
  return `<div class="ho-box">${kopf}
    ${zeilen ? `<div class="ho-liste">${zeilen}</div>${bestZeile}` : ''}
    ${form}</div>`;
}
