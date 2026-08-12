/* zeitraum/konfigmodus.js — Inline-Konfig (N189): Sichtbar/Verborgen +
   Pflicht/Optional je Kostenart. Die Zähler stehen als feste Pflicht-
   Zeilen unter ihrer Kategorie. */

import { api, esc, melde } from '../immo.js';
import { kostenIcon } from '../kostenicons.js';
import * as state from './state.js';
import { BEREICHE, BEREICH_IKON } from './state.js';
import { ZAEHLER_ICON } from './icons.js';
import {
  bereichIndex, normUml, istImDetailPopup, istHeizoelSammel,
  istWarmwasserPos, istHeizwaermePos, kostenartAnzeige,
} from './modell.js';

async function neuLaden() {
  const { laden } = await import('./checkliste.js');
  await laden();
}

async function neuZeichnen() {
  const { zeichnen } = await import('./checkliste.js');
  await zeichnen();
}

/* N189 — den Konfig-Modus betreten/verlassen. */
export async function konfigModusUmschalten() {
  if (state.konfigModus) {
    state.setKonfigModus(false);
    return neuLaden();
  }
  try {
    state.setKonfigArten(await api(`/objekte/${encodeURIComponent(state.daten.objekt)}/kostenarten`));
  } catch {
    return melde('Kostenarten nicht ladbar', 'neg');
  }
  state.setKonfigModus(true);
  return neuZeichnen();
}

/* Die Konfig-Ansicht: dieselben Kategorien wie live. */
export function konfigAnsichtHtml(zListe, zBlock) {
  const arten = state.konfigArten || [];
  const katalog = new Set(arten.map(a => a.name));
  const rows = arten.map(a => ({
    kostenart: a.name, kostenart_id: a.id,
    optional: !!a.optional, sichtbar: a.aktiv !== false, fest: false,
    s35: !!a.s35,
  }));
  // Waisen ohne Katalog-Eintrag: sichtbar, aber nicht konfigurierbar.
  const waise = (state.daten.checkliste || [])
    .filter(k => !katalog.has(k.kostenart))
    .map(k => ({ kostenart: k.kostenart, kostenart_id: null,
                 optional: false, sichtbar: true, fest: true }));
  const alle = [...rows, ...waise].filter(k => !istImDetailPopup(k));

  const bereiche = BEREICHE.map(() => []);
  for (const k of alle) bereiche[bereichIndex(k.kostenart)].push(k);
  const heizRang = k => istHeizoelSammel(k) ? 0
    : istWarmwasserPos(k) ? 1 : istHeizwaermePos(k) ? 2
    : normUml(k.kostenart).includes('wartung') ? 4 : 3;
  bereiche[1].sort((a, b) => heizRang(a) - heizRang(b));

  const blockName = ['Wasser', 'Heizung', 'Strom'];
  const abschnitte = bereiche.map((liste, bi) => {
    const meter = bi < 3 ? konfigZaehlerHtml(zListe, zBlock, blockName[bi]) : '';
    if (!liste.length && !meter) return '';
    return `<div class="kat-kopf"><span class="kat-ikon">${
        kostenIcon(BEREICH_IKON[bi])}</span><span class="kat-t">${
        esc(BEREICHE[bi].titel)}</span></div>`
      + liste.map(konfigZeileHtml).join('') + meter;
  }).join('');

  return `<div class="konf-leiste">
      <button class="konf-fertig" data-pos-konfig><svg viewBox="0 0 24 24" width="16"
        height="16" fill="none" stroke="currentColor" stroke-width="2.4"
        stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path
        d="m5 12 5 5 9-11"/></svg> Konfiguration verlassen</button>
    </div>
    <div class="konf-hinweis">Lege fest, welche Positionen in der Checkliste
      erscheinen — und ob eine fehlende Zahl als <b>Pflicht</b> rot mahnt.
      <b>Optionale</b> Positionen (z.&nbsp;B. eine Heizungswartung, die nicht
      jedes Jahr anfällt) bleiben sichtbar, ohne rot zu mahnen. Diese Einstellung
      gilt objektweit über alle Jahre.</div>
    ${abschnitte || '<div class="empty"><div class="big">Keine Positionen</div></div>'}`;
}

/* Eine konfigurierbare Zeile: Anzeige-Schalter + Pflicht/optional-Wahl. */
export function konfigZeileHtml(k) {
  if (k.fest) {
    return `<div class="pruef konf-zeile fest">
      <div class="kopf">
        <span class="ikon warte">${kostenIcon(k.kostenart)}</span>
        <span class="name">${esc(kostenartAnzeige(k.kostenart))}
          <span class="unter">Aus einem Beleg entstanden — bleibt sichtbar</span></span>
        <span class="konf-fest-tag">fest</span>
      </div></div>`;
  }
  const an = k.sichtbar;
  return `<div class="pruef konf-zeile${an ? '' : ' verborgen'}"
      data-kostenart="${esc(k.kostenart)}">
    <div class="kopf">
      <span class="ikon ${an ? 'fertig' : 'warte'}">${kostenIcon(k.kostenart)}</span>
      <span class="name">${esc(kostenartAnzeige(k.kostenart))}</span>
      <div class="konf-steuer">
        <label class="konf-sw" title="In der Checkliste anzeigen">
          <input type="checkbox" data-konf-sicht="${k.kostenart_id}"${an ? ' checked' : ''}
            aria-label="Position anzeigen">
          <span class="pk-sw" aria-hidden="true"></span>
          <span class="konf-swl">${an ? 'Sichtbar' : 'Verborgen'}</span>
        </label>
        <div class="konf-seg" role="group" aria-label="Pflicht oder optional">
          <button type="button" class="konf-opt${!k.optional ? ' an' : ''}"
            data-konf-opt="${k.kostenart_id}" data-optional="0"
            ${an ? '' : 'disabled'}>Pflicht</button>
          <button type="button" class="konf-opt${k.optional ? ' an' : ''}"
            data-konf-opt="${k.kostenart_id}" data-optional="1"
            ${an ? '' : 'disabled'}>Optional</button>
        </div>
        <button type="button" class="konf-s35${k.s35 ? ' an' : ''}"
          data-konf-s35="${k.kostenart_id}" data-s35="${k.s35 ? '0' : '1'}"
          title="Haushaltsnahe Dienstleistung/Handwerkerleistung nach § 35a EStG —
wird in der Mieterabrechnung separat ausgewiesen (Steuererklärung)"
          aria-pressed="${k.s35}">§ 35a</button>
      </div>
    </div></div>`;
}

/* Die Zähler einer Kategorie als feste Pflicht-Zeilen. */
function konfigZaehlerHtml(zListe, zBlock, block) {
  const meter = zListe.filter(z => (zBlock.get(z.id) || '') === block);
  if (!meter.length) return '';
  return meter.map(z => `<div class="pruef konf-zeile fest">
    <div class="kopf">
      <span class="ikon warte">${ZAEHLER_ICON}</span>
      <span class="name">${esc(state.zLabels.get(z.id) || z.name || 'Zähler')}
        <span class="unter">Zählerstand — immer Pflicht</span></span>
      <span class="konf-fest-tag">fest · Pflicht</span>
    </div></div>`).join('');
}

/* N189 — Anzeige (sichtbar/verborgen) einer Kostenart setzen. */
export async function konfSichtSetzen(cb) {
  const id = Number(cb.dataset.konfSicht);
  const an = cb.checked;
  try {
    await api(`/kostenarten/${id}`, { method: 'PATCH', body: { aktiv: an } });
  } catch (fehler) {
    melde(String(fehler.message || fehler), 'neg');
    cb.checked = !an;
    return;
  }
  const a = (state.konfigArten || []).find(x => x.id === id);
  if (a) a.aktiv = an;
  return neuZeichnen();
}

/* N351 — § 35a (haushaltsnah/Handwerker) an der Kostenart setzen; das
   Backend zieht den Vermerk in alle bestehenden Positionen dieser Art nach. */
export async function konfS35Setzen(btn) {
  const id = Number(btn.dataset.konfS35);
  const s35 = btn.dataset.s35 === '1';
  try {
    await api(`/kostenarten/${id}`, { method: 'PATCH', body: { s35 } });
  } catch (fehler) {
    melde(String(fehler.message || fehler), 'neg');
    return;
  }
  const a = (state.konfigArten || []).find(x => x.id === id);
  if (a) a.s35 = s35;
  return neuZeichnen();
}

/* N189 — Pflicht/Optional setzen. */
export async function konfOptSetzen(btn) {
  if (btn.disabled) return;
  const id = Number(btn.dataset.konfOpt);
  const optional = btn.dataset.optional === '1';
  try {
    await api(`/kostenarten/${id}`, { method: 'PATCH', body: { optional } });
  } catch (fehler) {
    melde(String(fehler.message || fehler), 'neg');
    return;
  }
  const a = (state.konfigArten || []).find(x => x.id === id);
  if (a) a.optional = optional;
  const k = (state.daten.checkliste || []).find(x => x.kostenart_id === id);
  if (k) k.optional = optional;
  return neuZeichnen();
}
