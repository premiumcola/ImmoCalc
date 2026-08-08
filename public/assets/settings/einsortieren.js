/* N216 — Belege in Jahresordner einsortieren
   (GET/POST /api/nextcloud/unterordner-umzug).

   CXCII: Was vor der Unterordner-Ablage schon da lag, liegt noch flach im
   Sachordner. Hier zieht es nach — erst Trockenlauf, dann Rückfrage, dann das
   Ergebnis samt dem, was misslang. Selbe Mechanik wie „Benennung nachziehen",
   nur eine Ebene tiefer: es wandern Belege, keine Ordner. Verhaltensgleich
   zum bisherigen Inline-Skript in settings.html. */
import { api, esc, frage } from '../immo.js';
import { belegText, feldmeldung, meldungWeg } from './state.js';

let einsortierenDlg, einsortierenMeldung, einsortierenPlan,
    einsortierenStart, einsortierenStatus;
let einsortierenTrocken = null;

/* Je Immobilie ein Kärtchen: der Name, wie viele Belege ziehen, dann alt → neu
   je Datei. */
function einsortierenKarte(s) {
  return `<div class="uschritt">
      <div class="uk">
        <span class="uname">${esc(s.name)}</span>
        <span class="uart">${belegText(s.dokumente.length)}</span>
      </div>
      ${s.dokumente.map(d => `<div class="upfad alt">${esc(d.von)}</div>
        <div class="upfad neu">↳ ${esc(d.nach)}</div>`).join('')}
    </div>`;
}

/* Belege ohne erkennbares Jahr bleiben liegen — genannt wird das trotzdem,
   sonst sucht man später danach. */
function einsortierenRest(p) {
  if (!p.ohne_jahr?.length) return '';
  return `<div class="ulabel">Ohne Jahr — bleibt liegen</div>
    <div class="uruhig">
      ${p.ohne_jahr.map(d => `<div class="upfad alt">${esc(d.pfad)}</div>`).join('')}
      <span class="ufuss">Ein Ordner „ohne-Jahr" hülfe beim Wiederfinden nicht
        — diese Belege bleiben im Sachordner.</span>
    </div>`;
}

function einsortierenPlanZeigen() {
  if (!einsortierenTrocken) return;
  const p = einsortierenTrocken;
  const kopf = p.schritte.length
    ? `<div class="ulabel">${belegText(p.dokumente)} in ${p.schritte.length} ${
        p.schritte.length === 1 ? 'Immobilie' : 'Immobilien'}</div>`
    : `<div class="uruhig"><span class="ufuss" style="margin-top:0">Alles schon
         einsortiert — es liegt nichts mehr flach im Sachordner, was einen
         Jahresordner bekommen könnte.</span></div>`;
  einsortierenPlan.innerHTML = `<div class="uliste">${kopf}
    ${p.schritte.map(einsortierenKarte).join('')}${einsortierenRest(p)}</div>`;
  einsortierenStart.style.display = p.schritte.length ? 'block' : 'none';
  einsortierenStart.disabled = false;
  einsortierenStart.textContent = 'Belege einsortieren';
}

export async function einsortierenLaden() {
  let grund = '';
  try {
    einsortierenTrocken = await api('/nextcloud/unterordner-umzug');
    if (einsortierenTrocken && einsortierenTrocken.moeglich === false) {
      grund = einsortierenTrocken.grund || 'nicht prüfbar';
      einsortierenTrocken = null;
    }
  } catch (fehler) {
    einsortierenTrocken = null;
    grund = String(fehler.message || fehler).replace(/^\d+\s*/, '')
      || 'nicht prüfbar';
  }
  einsortierenStatus.textContent = !einsortierenTrocken ? grund
    : einsortierenTrocken.dokumente
      ? `${belegText(einsortierenTrocken.dokumente)} liegen noch flach`
      : 'alles schon in Jahresordnern';
  document.getElementById('einsortierenIkon').className = 'ic' + (
    !einsortierenTrocken ? '' : einsortierenTrocken.dokumente ? ' warte' : ' aktiv');
}

/* Was wirklich getan wurde — und was nicht. Fehler stehen oben und in Rot. */
function einsortierenErgebnis(a, namen) {
  const fehler = a.fehler?.length
    ? `<div class="ulabel">Nicht einsortiert</div>` + a.fehler.map(f =>
        `<div class="uschritt">
           <div class="uk"><span class="uname">${esc(f.dateiname)}</span>
             <span class="uart schlecht">Fehler</span></div>
           <div class="upfad alt">${esc(f.von)}</div>
           <span class="ufuss">${esc(f.fehler)}</span>
         </div>`).join('')
    : '';
  // Nach Immobilie gruppieren, damit die Liste dieselbe Form hat wie der Plan.
  const jeObjekt = new Map();
  for (const v of a.verschoben) {
    if (!jeObjekt.has(v.objekt)) jeObjekt.set(v.objekt, []);
    jeObjekt.get(v.objekt).push(v);
  }
  const geschafft = [...jeObjekt.entries()].map(([slug, vs]) =>
    `<div class="uschritt">
       <div class="uk"><span class="uname">${esc(namen.get(slug) || slug)}</span>
         <span class="uart">${belegText(vs.length)}</span></div>
       ${vs.map(v => `<div class="upfad alt">${esc(v.von)}</div>
         <div class="upfad neu">↳ ${esc(v.nach)}</div>`).join('')}
     </div>`).join('');
  einsortierenPlan.innerHTML = `<div class="uliste">${fehler}
    ${geschafft ? `<div class="ulabel">Einsortiert</div>${geschafft}` : ''}</div>`;
}

/* Bindet Zeile und Start-Knopf. Aufruf einmal beim Laden. */
export function einsortierenInit() {
  einsortierenDlg = document.getElementById('einsortierenDlg');
  einsortierenMeldung = document.getElementById('einsortierenMeldung');
  einsortierenPlan = document.getElementById('einsortierenPlan');
  einsortierenStart = document.getElementById('einsortierenStart');
  einsortierenStatus = document.getElementById('einsortierenStatus');

  document.getElementById('einsortierenRow').addEventListener('click', async () => {
    meldungWeg(einsortierenMeldung);
    einsortierenPlan.innerHTML = '';
    einsortierenStart.style.display = 'none';
    einsortierenDlg.showModal();
    await einsortierenLaden();
    if (einsortierenTrocken) einsortierenPlanZeigen();
    else einsortierenPlan.innerHTML = `<div class="uruhig"><span class="ufuss"
        style="margin-top:0">Erst Nextcloud verbinden und einen Home-Ordner
        wählen — vorher gibt es nichts einzusortieren.</span></div>`;
  });

  einsortierenStart.addEventListener('click', async () => {
    if (!einsortierenTrocken?.dokumente) return;
    const ja = await frage('Belege jetzt einsortieren?',
      `${belegText(einsortierenTrocken.dokumente)} werden in ihre Jahresordner `
      + 'verschoben. Gelöscht oder überschrieben wird dabei nichts.',
      { knopf: 'Einsortieren' });
    if (!ja) return;

    const namen = new Map(einsortierenTrocken.schritte.map(s => [s.objekt, s.name]));
    meldungWeg(einsortierenMeldung);
    einsortierenStart.disabled = true;
    einsortierenStart.textContent = 'Sortiere ein …';
    try {
      const a = await api('/nextcloud/unterordner-umzug', { method: 'POST' });
      einsortierenStart.style.display = 'none';
      einsortierenErgebnis(a, namen);
      feldmeldung(einsortierenMeldung, a.fehler.length
        ? `${a.anzahl} von ${a.anzahl + a.fehler.length} Belegen einsortiert — `
          + `${a.fehler.length} blieben liegen.`
        : `${belegText(a.anzahl)} einsortiert.`,
        !a.fehler.length);
      await einsortierenLaden();
    } catch (fehler) {
      einsortierenStart.disabled = false;
      einsortierenStart.textContent = 'Belege einsortieren';
      feldmeldung(einsortierenMeldung, String(fehler.message || fehler));
    }
  });
}
