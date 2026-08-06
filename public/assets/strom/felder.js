/* N215 — Bausteine fuer ein Eingabefeld mit Label.

   Stammdatenkarte und Jahreskarte nutzen dieselbe Form: `feldHtml` fuer eine
   Zahl mit optionaler Einheit, `datumHtml` fuer ein Datum. Bei einem `art`-
   Wechsel steht das `data-Attribut` dann automatisch richtig
   (`data-feld` oder `data-stamm`). */
import { esc } from '../immo.js';

export function feldHtml(name, label, einheit, step, art = 'feld') {
  const zusatz = einheit
    ? ` <span class="einheit">(${esc(einheit)})</span>` : '';
  return `<div class="field">
    <label for="f_${name}">${esc(label)}${zusatz}</label>
    <input class="inp" type="number" inputmode="decimal" step="${step}" min="0"
           id="f_${name}" data-${art}="${name}">
  </div>`;
}

/* Ein Datumsfeld — dasselbe Aussehen, nur ohne Einheit und ohne step. */
export function datumHtml(name, label) {
  return `<div class="field">
    <label for="f_${name}">${esc(label)}</label>
    <input class="inp" type="date" id="f_${name}" data-stammdatum="${name}">
  </div>`;
}
