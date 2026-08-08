/* N216 — Zusatzblöcke fürs Mietformular:
   - Bewohner (mehrere Kontakte je Mietverhältnis),
   - Gemeinschaftsflächen (anteilig, CCCXXVII),
   - Zusatz-Nutzflächen (voll, CCCXXIX).

   Speichern der Bewohner separat gegen `/mieten/{id}/bewohner` bzw.
   `/bewohner/{id}`. */

import { esc, api, zahlAus } from '../immo.js';
import { bewohnerWeg, setBewohnerWeg } from './state.js';

/* ---- Bewohner ----------------------------------------------------------- */

export function bewohnerZeile(b) {
  return `<div class="bwzeile" ${b.id ? `data-bid="${b.id}"` : ''}>
    <button type="button" class="weg" data-bw-weg aria-label="Bewohner entfernen">×</button>
    <input class="nm" name="bw_name" type="text" placeholder="Name"
           value="${esc(b.name || '')}">
    <input name="bw_email" type="email" placeholder="E-Mail"
           value="${esc(b.email || '')}">
    <input name="bw_telefon" type="tel" placeholder="Handy"
           value="${esc(b.telefon || '')}">
    <input name="bw_anschrift" type="text" placeholder="Anschrift"
           value="${esc(b.anschrift || '')}">
  </div>`;
}

export function bewohnerBlock(liste) {
  setBewohnerWeg([]);
  return `<div class="block" id="bewohnerblock">
    <span class="bt">Bewohner &amp; Kontakt</span>
    <span class="bd">Der Kontakt gehört zu den Bewohnern: jede Person bekommt
      hier ihre eigene E-Mail, Handynummer und Anschrift. Die
      Nebenkostenabrechnung geht an alle Bewohner mit hinterlegter Mailadresse.</span>
    ${(liste || []).map(bewohnerZeile).join('')}
    <button type="button" class="zusatz" data-bw-neu>＋ Bewohner</button>
  </div>`;
}

/* Was im Dialog steht, mit dem Bestand abgleichen: geändert, neu, entfernt. */
export async function bewohnerSpeichern(form, miete_id) {
  const block = form.querySelector('#bewohnerblock');
  if (!block || !miete_id) return;
  for (const bid of bewohnerWeg) {
    await api(`/bewohner/${bid}`, { method: 'DELETE' });
  }
  setBewohnerWeg([]);
  for (const zeile of block.querySelectorAll('.bwzeile')) {
    const daten = {
      name: zeile.querySelector('[name=bw_name]').value.trim(),
      email: zeile.querySelector('[name=bw_email]').value.trim(),
      telefon: zeile.querySelector('[name=bw_telefon]').value.trim(),
      anschrift: zeile.querySelector('[name=bw_anschrift]').value.trim(),
    };
    if (zeile.dataset.bid) {
      await api(`/bewohner/${zeile.dataset.bid}`, { method: 'PATCH', body: daten });
    } else if (daten.name || daten.email || daten.telefon || daten.anschrift) {
      await api(`/mieten/${miete_id}/bewohner`, { method: 'POST', body: daten });
    }
  }
}

/* ---- Flächenfelder ------------------------------------------------------
   N288 — Flächen stehen als Text im Feld, nicht als `type="number"`: ein
   Zahlenfeld deutet den Punkt je nach Browser mal als Tausender-, mal als
   Dezimaltrenner. Geschrieben wird deutsch („1.250,5"), gelesen wird mit
   `zahlAus` aus `immo.js` — dieselbe Regel wie überall. Vorher stand hier
   `Number(text.replace(',', '.'))`: aus getippten „1.250" wurden 1,25 m². */
const flaecheWert = n => (n == null || n === '')
  ? '' : Number(n).toLocaleString('de-DE', { maximumFractionDigits: 2 });
const flaecheAus = el => zahlAus(el) ?? 0;

/* ---- Gemeinschaftsflächen (anteilig) ------------------------------------ */

/* CCCXXVII — Gemeinschaftsflächen einer Einheit: eine mitgenutzte Fläche und
   von wie vielen sie genutzt wird. Sie zählt geteilt durch die Nutzerzahl zur
   Einheitsfläche (Verteilung + €/m²). Seltener Fall — deshalb eingeklappt bis
   zum ersten Eintrag. */
export function gemeinZeile(g = {}) {
  return `<div class="gfzeile">
    <button type="button" class="weg" data-gf-weg aria-label="Fläche entfernen">×</button>
    <input class="nm" name="gf_bezeichnung" type="text" placeholder="z. B. Treppenhaus"
           value="${esc(g.bezeichnung || '')}">
    <input name="gf_flaeche" type="text" inputmode="decimal"
           placeholder="m²" value="${esc(flaecheWert(g.flaeche))}">
    <input name="gf_personen" type="number" step="1" inputmode="numeric"
           placeholder="Nutzer" value="${g.personen ?? ''}">
  </div>`;
}

export function gemeinBlock(liste) {
  return `<div class="block" id="gemeinblock">
    <span class="bt">Gemeinschaftsflächen (anteilig)</span>
    <span class="bd">Selten nötig: eine mitgenutzte Fläche (z. B. Treppenhaus,
      Waschküche) und von wie vielen Personen sie genutzt wird. Sie zählt geteilt
      durch die Nutzerzahl zur Wohnfläche dieser Einheit — für die Verteilung und
      die Quadratmetermiete.</span>
    ${(liste || []).map(gemeinZeile).join('')}
    <button type="button" class="zusatz" data-gf-neu>＋ Gemeinschaftsfläche</button>
  </div>`;
}

/** Die Gemeinschaftsflächen-Zeilen als Liste — leere (ohne Fläche) fallen weg. */
export function gemeinAusFormular(form) {
  return [...form.querySelectorAll('.gfzeile')].map(z => ({
    bezeichnung: z.querySelector('[name=gf_bezeichnung]').value.trim(),
    flaeche: flaecheAus(z.querySelector('[name=gf_flaeche]')),
    personen: Number(z.querySelector('[name=gf_personen]').value) || 0,
  })).filter(g => g.flaeche > 0);
}

/* ---- Zusatz-Nutzflächen (voll) ------------------------------------------ */

/* CCCXXIX — Zusätzliche Nutzflächen einer Einheit: benannte Teile der
   Wohnfläche (z. B. ein separates Bad), die VOLL — ungeteilt — zur Wohnfläche
   zählen. Analog zu den Gemeinschaftsflächen, nur ohne Nutzerzahl. Eingeklappt
   bis zum ersten Eintrag. */
export function nutzZeile(n = {}) {
  return `<div class="nfzeile">
    <button type="button" class="weg" data-nf-weg aria-label="Fläche entfernen">×</button>
    <input class="nm" name="nf_bezeichnung" type="text" placeholder="z. B. Bad"
           value="${esc(n.bezeichnung || '')}">
    <input name="nf_flaeche" type="text" inputmode="decimal"
           placeholder="m²" value="${esc(flaecheWert(n.flaeche))}">
  </div>`;
}

export function nutzBlock(liste) {
  return `<div class="block" id="nutzblock">
    <span class="bt">Zusätzliche Nutzflächen (voll)</span>
    <span class="bd">Wohnfläche in benannte Teile aufteilen — z. B. ein separates
      Bad. Zählt voll zur Wohnfläche dieser Einheit.</span>
    ${(liste || []).map(nutzZeile).join('')}
    <button type="button" class="zusatz" data-nf-neu>＋ Zusatzfläche</button>
  </div>`;
}

/** Die Zusatz-Nutzflächen als Liste — leere (ohne Fläche) fallen weg. */
export function nutzAusFormular(form) {
  return [...form.querySelectorAll('.nfzeile')].map(z => ({
    bezeichnung: z.querySelector('[name=nf_bezeichnung]').value.trim(),
    flaeche: flaecheAus(z.querySelector('[name=nf_flaeche]')),
  })).filter(n => n.flaeche > 0);
}
