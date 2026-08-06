/* N216 — Grundschulden am Haus: eigene Liste (nicht Teil von BEREICHE, eigene
   Endpunkte). Die Zuordnung zu Krediten ist eine objektübergreifende
   Mehrfachauswahl (jede Blase trägt ihren Zustand selbst — anders als bei den
   Einheiten-Blasen mit data-wahl/-wahlfeld). */

import { esc, eurVoll, api } from '../immo.js';
import { kostenIcon } from '../kostenicons.js';
import { grundschulden, GRUNDSCHULDFELDER } from './state.js';
import { formular } from './formular.js';

export const grundschuldName = g =>
  g.glaeubiger || (g.grundbuch_blatt ? `Blatt ${g.grundbuch_blatt}` : 'Grundschuld');

export const grundschuldDetail = g => [
  g.rang != null && g.rang !== '' ? `Rang ${g.rang}` : '',
  g.grundbuch_blatt ? `Blatt ${g.grundbuch_blatt}` : '',
  g.brief ? 'Brief' : 'Buch',
  (g.kredit_ids || []).length
    ? `sichert ${g.kredit_ids.length} Kredit${g.kredit_ids.length === 1 ? '' : 'e'}`
    : 'sichert keinen Kredit',
].filter(Boolean).join(' · ');

/** Alle Kredite über alle Objekte — eine Grundschuld kann anderswo sichern. */
async function grundschuldKrediteListe() {
  try { return await api('/grundschulden/kredit-auswahl'); }
  catch { return []; }
}

function grundschuldKreditBlock(kreditListe, ausgewaehlt) {
  if (!kreditListe.length) {
    return `<div class="block">
      <span class="bt">Gesicherte Kredite</span>
      <span class="bd">Noch kein Kredit angelegt — lege zuerst einen an, um
        ihn hier zu verknüpfen.</span>
    </div>`;
  }
  const gewaehlt = new Set(ausgewaehlt.map(String));
  const blasen = kreditListe.map(k => {
    const an = gewaehlt.has(String(k.id));
    return `<button type="button" class="bubble${an ? ' gewaehlt' : ''}"
        data-gs-kredit="${k.id}" aria-pressed="${an}">
      <span class="bt">${esc(k.bezeichnung)}</span>
      <span class="bf">${esc(k.objekt)}</span>
    </button>`;
  }).join('');
  return `<div class="block">
    <span class="bt">Gesicherte Kredite</span>
    <span class="bd">Eine Grundschuld kann auch einen Kredit an einem anderen
      Objekt sichern — deshalb stehen hier alle Kredite, objektübergreifend.
      Mehrfachauswahl möglich.</span>
    <div class="bubbles" role="group"
         aria-label="Gesicherte Kredite">${blasen}</div>
  </div>`;
}

export async function grundschuldFormular(g = null) {
  const kreditListe = await grundschuldKrediteListe();
  await formular({
    titel: g ? 'Grundschuld bearbeiten' : 'Grundschuld hinzufügen',
    hinweis: 'Rang und Grundbuchblatt stehen im Grundbuchauszug. Eine '
      + 'Grundschuld sichert einen oder mehrere Kredite ab — auch an einem '
      + 'anderen Objekt.',
    felder: GRUNDSCHULDFELDER, werte: g || {}, absicht: 'grundschuld',
    extra: grundschuldKreditBlock(kreditListe, g ? (g.kredit_ids || []) : []),
    knopf: g ? 'Speichern' : 'Anlegen',
  });
}

export function grundschuldenHtml() {
  const zeilen = grundschulden.length
    ? grundschulden.map(g => `<div class="eintrag klick" data-gs-edit="${g.id}">
        <span class="sym">${kostenIcon('Kredit')}</span>
        <span class="et">
          <span class="en">${esc(grundschuldName(g))}</span>
          <span class="ed">${esc(grundschuldDetail(g))}</span>
        </span>
        <span class="ew">${eurVoll(g.betrag)}</span>
        <button class="del" data-gs-weg="${g.id}" aria-label="löschen">×</button>
      </div>`).join('')
    : `<div class="leerzeile">Noch keine Grundschuld hinterlegt</div>`;
  // CCCXXXII — Grundschulden bekommen ein Symbol (Finanzierungs-Cluster wie
  // Kredite) und die Hilfe hängt daneben, nicht am nackten Titel.
  return `<div class="sekopf"><span class="seikon"
        style="color:var(--neg)">${kostenIcon('Grundschuld')}</span>
      <h2 class="sec">Grundschulden</h2><span data-hilfe="grundschuld"></span>
      <button class="seakt" data-gs-neu="1" aria-label="Grundschuld hinzufügen"
        title="Grundschuld hinzufügen">Hinzufügen</button></div>
    <div class="liste">${zeilen}</div>`;
}
