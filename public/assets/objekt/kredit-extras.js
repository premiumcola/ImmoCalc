/* N216 — Zusatzblöcke am Kredit-Formular: „Restschuld / Sparstand"-Kachel und
   das Stand-Formular für Jahresstände (CCXXXI: Ist-Zinsen aus dem Kontoauszug
   neben der kalkulierten Zahl). */

import { esc, eur, api, melde } from '../immo.js';
import { istBausparer } from '../objekt-format.js?v=2';
import { formular } from './formular.js';

/* Das Feld heisst weiter `restschuld` — so heisst die Spalte, und beim
   Bausparvertrag steht dort der Sparstand (siehe `models.Kreditstand`).
   Gefragt wird trotzdem nach dem, was auf dem Auszug steht. */
export const standFelder = bauspar => [
  { k: 'jahr', l: 'Jahr', typ: 'number', pflicht: true,
    vorgabe: new Date().getFullYear() - 1 },
  { k: 'restschuld', l: bauspar ? 'Sparstand am 31.12.'
                                : 'Restschuld am 31.12.',
    typ: 'number', schritt: '0.01', geld: true, pflicht: true },
  // CCXXXI — was laut Kontoauszug tatsächlich an Zinsen floss, neben der
  // Kalkulation aus Rate und Zinssatz. Optional: ohne Angabe zeigt der
  // Verlauf weiter nur die gerechnete Zahl.
  { k: 'zinsen_ist', l: bauspar ? 'Erhaltene Zinsen lt. Kontoauszug'
                                : 'Gezahlte Zinsen lt. Kontoauszug',
    typ: 'number', schritt: '0.01', geld: true },
];

/* CCXXXI — Zinsen je Jahr: was laut Kontoauszug wirklich anfiel (`zinsen_ist`)
   neben dem, was aus Rate und Zinssatz gerechnet ist (`zinsen_kalk`). Fehlt
   der Ist-Wert, bleibt nur die Kalkulation stehen; fehlen beide, bleibt die
   Zeile ganz weg — eine leere Zinszeile wäre nur Rauschen. */
function zinsZeile(j) {
  if (j.zinsen_ist == null && j.zinsen_kalk == null) return '';
  const teile = [];
  if (j.zinsen_ist != null) teile.push(`ist ${eur(j.zinsen_ist)}`);
  if (j.zinsen_kalk != null) teile.push(`kalk ${eur(j.zinsen_kalk)}`);
  return `<div class="jz">Zinsen: ${teile.join(' · ')}</div>`;
}

function verlaufBlock(s) {
  const bauspar = istBausparer(s.art);
  const zeilen = (s.verlauf || []).map(j => `<div class="jahr${
      j.eingetragen ? ' gemessen' : ''}">
      <div class="jzeile">
        <span class="jj">${j.jahr}</span>
        <span class="jw">${eur(j.restschuld)}</span>
        <span class="jq">${j.eingetragen ? 'eingetragen' : 'gerechnet'}</span>
        ${j.eingetragen ? `<button type="button" class="weg"
            data-stand-weg="${(s.staende.find(x => x.jahr === j.jahr) || {}).id}"
            data-jahr="${j.jahr}" data-betrag="${esc(eur(j.restschuld))}"
            data-was="${bauspar ? 'Sparstand' : 'Restschuld'}"
            aria-label="Stand entfernen">×</button>`
          : '<span class="weg" aria-hidden="true"></span>'}
      </div>
      ${zinsZeile(j)}
    </div>`).join('');
  return `<div class="block">
    <span class="bt">Verlauf</span>
    <span class="bd">Grün hinterlegt ist, was du eingetragen hast. Die Jahre
      dazwischen rechnet die App aus ${bauspar ? 'Sparbeitrag und Guthabenzins'
                                              : 'Rate und Zinssatz'}.</span>
    ${zeilen ? `<div class="jahre">${zeilen}</div>`
             : '<div class="bd">Noch kein Stand eingetragen.</div>'}
  </div>`;
}

export function kreditExtra(eintrag) {
  if (!eintrag) return '';
  const s = eintrag.stand || {};
  const bauspar = istBausparer(eintrag.art);
  const gemessen = s.stand_jahr
    ? `Zuletzt eingetragen zum 31.12.${s.stand_jahr}: ${eur(s.stand_wert)} —
       heute fortgeschrieben ${eur(s.stand)}.`
    : (bauspar
        ? `Trage den Sparstand zum 31.12. ein, wie er auf dem Kontoauszug
           steht. Dazwischen rechnet ImmoCalc aus Sparbeitrag und
           Guthabenzins weiter.`
        : `Trage die Restschuld zum 31.12. ein, wie sie im Kontoauszug steht.
           Dazwischen rechnet ImmoCalc aus Rate und Zinssatz weiter.`);
  // Beim Bausparvertrag zählt, was noch fehlt — das ist die Zahl, die der
  // Nutzer im Kopf hat: 140.000 Bausparsumme, 45.000 gespart, Rest offen.
  const rest = bauspar && s.noch_zu_sparen != null
    ? (s.zuteilungsreif
        ? ` Die Bausparsumme ist erreicht — der Vertrag ist zuteilungsreif.`
        : ` Bis zur Bausparsumme fehlen noch ${eur(s.noch_zu_sparen)}.`)
    : '';
  const zins = bauspar
    ? (s.habenzins_monat ? ` Das Guthaben bringt zurzeit
        ${eur(s.habenzins_monat)} im Monat an Zinsen.` : '')
    : (s.zins_monat ? ` Davon gehen zurzeit ${eur(s.zins_monat)} im Monat
        an Zinsen weg.` : '');
  return `<div class="block">
    <span class="bt">${bauspar ? 'Sparstand' : 'Restschuld'}</span>
    <span class="bd">${gemessen}${rest}${zins}</span>
    <button type="button" class="zusatz"
            data-staende="${eintrag.id}">Jahresstände pflegen</button>
  </div>`;
}

export async function standFormular(kid) {
  let s;
  try {
    s = await api(`/kredite/${kid}/staende`);
  } catch (fehler) {
    return melde(String(fehler.message || fehler), 'neg');
  }
  const bauspar = istBausparer(s.art);
  await formular({
    titel: bauspar ? 'Sparstand zum Jahresende' : 'Restschuld zum Jahresende',
    hinweis: bauspar
      ? 'Die Bausparkasse weist das Guthaben zum 31.12. aus — trage es ein wie '
        + 'einen Zählerstand. Dazwischen schreibt ImmoCalc monatlich fort: '
        + 'Sparbeitrag plus Guthabenzins. Jeder neue Stand korrigiert die '
        + 'Rechnung.'
      : 'Die Bank weist die Restschuld zum 31.12. aus — trage sie ein wie '
        + 'einen Zählerstand. Dazwischen schreibt ImmoCalc monatlich fort: Rate '
        + 'minus Zinsanteil ist Tilgung. Jeder neue Stand korrigiert die Rechnung.',
    felder: standFelder(bauspar), werte: { id: kid }, absicht: 'stand',
    extra: verlaufBlock(s), knopf: 'Stand eintragen',
  });
}
