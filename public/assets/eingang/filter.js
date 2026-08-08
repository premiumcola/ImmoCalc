/* N216 — Die Filterleiste des Dokumenten-Eingangs.

   Immobilien-Buttons (Kurzcodes „lau 5"), Art-/Jahr-/Zustand-Auswahl und das
   aufklappbare Kostenart-Dropdown mit Bubbles. Die Aktionen „Angezeigte ins
   Warten" (CCLXXXII) und der Filter-Reset gehoeren ebenfalls hierher, weil
   sie den Filterzustand betreffen. Bei jeder Aenderung laeuft `laden()`. */

import { S, els, ALLE } from './state.js';
import { esc, api, frage, melde } from '../immo.js';
import { auswahlfeld } from '../auswahl.js';
import { jahresliste, kurzObjekt } from './helpers.js';
import { laden } from './aktionen.js';

/* ---- Filterfelder: einmal gebaut, danach nur noch nachgefuellt --------- */
const filterFeld = (id, label, schluessel) => auswahlfeld(
  document.getElementById(id), {
    optionen: [{ wert: ALLE, text: label }], wert: ALLE, label,
    aenderung: wert => { S.filter[schluessel] = wert; laden(); },
  });

S.fArt = filterFeld('fArt', 'Alle Arten', 'kategorie');
S.fJahr = filterFeld('fJahr', 'Alle Jahre', 'jahr');
// Der Zustandsfilter hat feste Werte — er wird nie nachgefuellt und braucht
// deshalb auch keinen Namen.
auswahlfeld(els.fStatus, {
  optionen: [{ wert: ALLE, text: 'Alle Zustände' },
             { wert: 'neu', text: 'Wartet auf Zuordnung' },
             { wert: 'zugeordnet', text: 'Einsortiert' },
             { wert: 'vermisst', text: 'Datei vermisst' }],
  wert: ALLE, label: 'Zustand',
  aenderung: wert => { S.filter.status = wert; laden(); },
});

/* ---- Immobilien-Filter als Buttons -------------------------------------- */
function objektButtons() {
  const alle = !S.filter.objekt;
  const knoepfe = [`<button class="imbtn${alle ? ' an' : ''}" type="button"
      data-slug="" aria-pressed="${alle}">Alle</button>`];
  for (const o of S.daten.objekte) {
    const an = S.filter.objekt === o.slug;
    knoepfe.push(`<button class="imbtn${an ? ' an' : ''}" type="button"
      data-slug="${esc(o.slug)}" title="${esc(o.name)}" aria-label="${esc(o.name)}"
      aria-pressed="${an}">${esc(kurzObjekt(o.name))}</button>`);
  }
  els.fObjektBtns.innerHTML = knoepfe.join('');
}

els.fObjektBtns.addEventListener('click', e => {
  const b = e.target.closest('[data-slug]');
  if (!b) return;
  const slug = b.dataset.slug;
  S.filter.objekt = (S.filter.objekt === slug) ? ALLE : slug;
  laden();
});

/* ---- Kostenart-Filter: Dropdown, die Bubbles stehen aufgeklappt darin.
   Zahlen aus `daten.kostenarten` (serverseitig ueber die uebrigen Filter
   gezaehlt) ziehen bei Objekt-/Jahrwechsel mit. Klick schaltet an/aus. ---- */
function kaAufklappen(auf) {
  els.fKostenart.hidden = !auf;
  els.kaTrigger.setAttribute('aria-expanded', String(auf));
}

function kostenartenLeiste() {
  const arten = S.daten.kostenarten || [];
  els.kaTrigger.hidden = !arten.length && !S.filter.kostenart;
  const aktiv = Boolean(S.filter.kostenart);
  els.kaTrigger.classList.toggle('an', aktiv);
  els.kaLabel.textContent = aktiv ? S.filter.kostenart : 'Kostenart';
  const alleAn = !S.filter.kostenart;
  const chips = [`<button class="kabtn alle${alleAn ? ' an' : ''}" type="button"
      data-ka="" aria-pressed="${alleAn}">Alle</button>`];
  for (const a of arten) {
    const an = S.filter.kostenart === a.name;
    chips.push(`<button class="kabtn${an ? ' an' : ''}" type="button"
      data-ka="${esc(a.name)}" aria-pressed="${an}">${esc(a.name)}<span class="n">${a.anzahl}</span></button>`);
  }
  els.fKostenart.innerHTML = chips.join('');
}

els.kaTrigger.addEventListener('click', () => kaAufklappen(els.fKostenart.hidden));
els.fKostenart.addEventListener('click', e => {
  const b = e.target.closest('[data-ka]');
  if (!b) return;
  const ka = b.dataset.ka;
  S.filter.kostenart = (S.filter.kostenart === ka) ? ALLE : ka;
  kaAufklappen(false);
  laden();
});
// Tap ausserhalb schliesst das aufgeklappte Kostenart-Dropdown wieder.
document.addEventListener('click', e => {
  if (els.fKostenart.hidden) return;
  if (e.target.closest('#fKostenart') || e.target.closest('#kaTrigger')) return;
  kaAufklappen(false);
});

/* ---- Angezeigte Belege gesammelt zurueck ins Warten (CCLXXXII) ---------- */
els.warteArchiv.addEventListener('click', async () => {
  const n = S.daten.anzahl || 0;
  if (!n) return;
  const ok = await frage('Zurück ins Warten',
    `${n} angezeigte ${n === 1 ? 'Beleg wird' : 'Belege werden'} zurück ins Warten `
    + 'gestellt: Zuordnungen und vorläufige (orange) Entwürfe werden entfernt. '
    + 'Die Dateien in der Nextcloud bleiben unangetastet.',
    { knopf: 'Ins Warten', gefahr: true });
  if (!ok) return;
  const frageStr = new URLSearchParams();
  for (const [k, v] of Object.entries(S.filter)) if (v) frageStr.set(k, v);
  try {
    const r = await api('/dokumente/warte-archiv?' + frageStr.toString(),
                        { method: 'POST' });
    melde(`${r.belege} zurück ins Warten`
      + (r.zeitraeume_entfernt ? ` · ${r.zeitraeume_entfernt} leere Zeiträume weg` : ''));
    await laden();
  } catch (e) { melde(e.message || 'Fehlgeschlagen', 'neg'); }
});

/* ---- Suche: tippen filtert, ohne bei jedem Zeichen zu fragen ------------ */
els.suche.addEventListener('input', e => {
  clearTimeout(S.tippuhr);
  S.filter.suche = e.target.value.trim();
  S.tippuhr = setTimeout(laden, 250);
});

els.zuruecksetzen.addEventListener('click', () => {
  Object.assign(S.filter, { objekt: ALLE, kategorie: ALLE, kostenart: ALLE,
                            jahr: ALLE, status: ALLE, suche: '' });
  els.suche.value = '';
  laden();
});

/* ---- Alle Filter frisch beschriften (aus S.daten) ----------------------- */
export function filterFuellen() {
  objektButtons();
  S.fArt.fuelle([{ wert: ALLE, text: 'Alle Arten' },
    ...(S.daten.kategorien.length ? S.daten.kategorien : S.daten.arten)
      .map(a => ({ wert: a, text: a }))], S.filter.kategorie);
  S.fJahr.fuelle([{ wert: ALLE, text: 'Alle Jahre' },
    ...jahresliste().map(j => ({ wert: String(j), text: String(j) }))], S.filter.jahr);
  kostenartenLeiste();
  const gefiltert = Boolean(S.filter.objekt || S.filter.kategorie || S.filter.kostenart
                            || S.filter.jahr || S.filter.status || S.filter.suche);
  els.zuruecksetzen.hidden = !gefiltert;
  // „Angezeigte ins Warten" nur, wenn ein Filter aktiv ist und etwas uebrig
  // bleibt — so schickt man bewusst einen Ausschnitt zurueck, nie versehentlich
  // den ganzen Bestand.
  els.warteArchiv.hidden = !(gefiltert && S.daten.anzahl > 0);
}
