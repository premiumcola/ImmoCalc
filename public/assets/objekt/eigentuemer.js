/* N216 — Eigentümer-Block am Haus: Liste der Anteile, Warnung wenn die
   Summe nicht 1000 ‰ ergibt, Weg zum Zuordnen-Formular. Das Formular
   selbst nutzt `formular()` — importiert von handlers.js. */

import { esc, api, promille, frage } from '../immo.js';
import { kostenIcon } from '../kostenicons.js';
import { einheiten, setAnteilfelder } from './state.js';
import { formular } from './formular.js';

export function eigentuemerHtml(stand) {
  if (!stand) return '';
  // CLXI — ein Anteil zeigt aufs ganze Haus oder auf eine Einheit. Die Einheit
  // steht als Auszeichnung am Namen, damit „mir gehört Wohnung 2" sichtbar ist.
  // Bestandszeilen kennen nur `tausendstel`; neue tragen `promille`.
  const zeilen = stand.anteile.length
    ? stand.anteile.map(a => `<div class="eintrag">
        <span class="sym">${kostenIcon('Eigentümer')}</span>
        <span class="et"><span class="en">${esc(a.name)}${a.einheit
            ? ` <span class="chip teal">${esc(a.einheit)}</span>` : ''}</span>
          <span class="ed">${esc([a.einheit ? '' : a.rolle, a.notiz]
            .filter(Boolean).join(' · '))}</span>
        </span>
        <span class="ew">${promille(a.promille ?? a.tausendstel ?? 0)}</span>
        <button class="del" data-anteil="${a.id}" aria-label="entfernen">×</button>
      </div>`).join('')
    : `<div class="leerzeile">Noch kein Eigentümer zugeordnet</div>`;

  // Warnung analog zu `parteien_ohne_einheit`: erst das Haus (der „Rest"),
  // dann jede Einheit, deren Anteile nicht aufgehen.
  const probleme = [];
  if (stand.objekt_noetig && stand.frei !== 0) {
    probleme.push(stand.frei > 0
      ? `Am Haus fehlen noch ${promille(stand.frei)}`
      : `Am Haus sind ${promille(-stand.frei)} zu viel verteilt`);
  } else if (!stand.objekt_noetig && stand.vergeben > 0) {
    probleme.push(`${promille(stand.vergeben)} am Haus, obwohl schon jede Einheit `
      + `einzeln zugeordnet ist`);
  }
  for (const es of (stand.einheiten_stand || [])) {
    if (es.stimmig) continue;
    probleme.push(es.unbekannt
      ? `„${es.einheit}" gibt es als Einheit nicht (mehr)`
      : (es.frei > 0
          ? `In „${es.einheit}" fehlen noch ${promille(es.frei)}`
          : `In „${es.einheit}" sind ${promille(-es.frei)} zu viel verteilt`));
  }
  const rest = !stand.stimmig
    ? `<div class="merker"><span class="hi">!</span><span class="ht">
         <span class="t">Zurechnung geht noch nicht auf</span>
         <span class="d">${probleme.length
            ? esc(probleme.join(' · ')) + '. '
            : ''}Je Haus und je Einheit sollten 1000 ‰ verteilt sein. Eine
           Nachkommastelle genügt — 333,3 dreimal gilt als vollständig.
           Einheit-Anteile haben Vorrang für ihre Einheit, der Haus-Anteil
           deckt den Rest.</span>
       </span></div>` : '';

  // CCCXXII — „Zuordnen" nur, wenn es überhaupt noch freie ‰ gibt. Ist alles
  // verteilt, wäre der Knopf eine Sackgasse (jede Zuweisung überbucht) —
  // stattdessen ein ruhiger Hinweis. Wird später etwas frei, kommt er zurück.
  const freiObjekt = stand.objekt_noetig === false ? 0 : (stand.frei || 0);
  const freiEinheit = (stand.einheiten_stand || [])
    .reduce((m, es) => Math.max(m, es.frei || 0), 0);
  const platz = Math.max(freiObjekt, freiEinheit) > 0.05;
  const kopfKnopf = platz
    ? `<button data-anteil-neu="1">Zuordnen</button>`
    : `<span class="voll-hinweis" title="Erst einen Anteil verkleinern oder entfernen, dann wird wieder etwas frei">Alle 1000 ‰ verteilt</span>`;

  return `<div class="sekopf"><span class="seikon">${kostenIcon('Eigentümer')}</span><h2 class="sec">Eigentümer</h2>
      ${kopfKnopf}</div>
    <div class="liste">${zeilen}</div>${rest}`;
}

export async function anteilFormular() {
  let eigner = [];
  try { eigner = await api('/eigentuemer'); } catch { /* leer behandeln */ }
  if (!eigner.length) {
    const hin = await frage('Noch kein Eigentümer angelegt',
      'Eigentümer werden einmal zentral gepflegt und dann den Immobilien '
      + 'zugeordnet. Jetzt in den Einstellungen anlegen?',
      { knopf: 'Zu den Einstellungen' });
    if (hin) location.href = 'settings.html#eigentuemer';
    return;
  }
  const felder = [
    { k: 'eigentuemer_id', l: 'Eigentümer', typ: 'select',
      werte: eigner.map(e => e.name) },
    // Die Einheitenwahl nur, wenn es überhaupt Einheiten gibt — ein
    // Grundstück oder ein Objekt ohne erfasste Einheiten kennt nur den
    // Haus-Anteil.
    ...(einheiten.length
      ? [{ k: 'einheit', l: 'Gehört dem Eigentümer', typ: 'anteileinheit' }]
      : []),
    { k: 'promille', l: 'Anteil in Tausendstel (‰)', typ: 'number', schritt: '0.1',
      vorgabe: 1000, pflicht: true },
    { k: 'notiz', l: 'Notiz', typ: 'text' },
  ];
  setAnteilfelder(felder);
  await formular({ titel: 'Eigentümer zuordnen', felder, absicht: 'anteil' });
  // Der Name im Auswahlfeld muss zur ID werden — die Reihenfolge ist dieselbe.
  const feld = document.getElementById('f_eigentuemer_id');
  eigner.forEach((e, i) => { feld.options[i].value = e.id; });
}
