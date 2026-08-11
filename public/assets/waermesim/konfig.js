/* N340f — die Konfig-Oberfläche: benennen, Faktor prüfen, auf Einheiten legen.

   Zuweisen geht auf zwei Wegen, weil einer allein nicht reicht: am Schreib-
   tisch zieht man das Kärtchen (HTML5-Drag), am Telefon tippt man es an und
   dann die Zeile der Einheit. Reines Drag-and-Drop wäre auf dem iPhone eine
   Falle — der Browser deutet das Ziehen als Scrollen. */

import { api, esc, melde } from '../immo.js';
import { ALLGEMEIN, GERAETE, faktorVon, fortschritt, lade, sichere }
  from './zaehler.js';
import { simulationAktualisieren, simulationEinbauen } from './simulation.js';

const SLUG = 'eschenau-laufer-str-5';
let stand = null;
let aufgenommen = null;       // welches Kärtchen gerade „in der Hand" liegt

const ARTNAME = { hkv: 'Heizkörperzähler', wmz: 'Wärmemengenzähler' };
const RAUMNAME = { Z: 'Zimmer', K: 'Küche', W: 'Wohnen', B: 'Bad', S: 'Sonstige',
                   WK: 'Wohnküche', HZ: 'Heizung', 'B/1G': 'Bad 1. OG',
                   'B/DG': 'Bad DG', 'T/DG': 'Teil DG', '—': 'ohne Raum' };

function lanes() {
  return [...stand.einheiten.map(e => ({ id: e.id, titel: e.name || `Einheit ${e.id}`,
                                         zusatz: e.flaeche ? `${e.flaeche} m²` : '' })),
          { id: ALLGEMEIN, titel: 'Allgemein', zusatz: 'Flure, Küche & Bäder' }];
}

/* N340h — der Verlauf am Kärtchen. Fehlt einmal ein Ablesewert, ist die
   Frage sofort „was hatte der Heizkörper sonst?" — deshalb stehen die Jahre
   direkt dort, mit einem kleinen Balken je Wert. Ein Jahr ohne Zahl bleibt
   sichtbar leer, statt stillschweigend zu fehlen: abgebaute Heizkörper und
   Lücken in den Unterlagen sollen auffallen. */
const JAHRE = [2019, 2020, 2021, 2022, 2023, 2024];

function verlaufHtml(g) {
  const s = g.staende || {};
  const werte = JAHRE.map(j => s[j]).filter(w => w !== undefined);
  if (!werte.length) return '';
  const hoch = Math.max(...werte, 1);
  return `<span class="wz-verlauf" role="img"
      aria-label="Verlauf ${JAHRE.map(j => `${j}: ${s[j] ?? 'kein Wert'}`).join(', ')}">
    ${JAHRE.map(j => {
      const w = s[j];
      const h = w === undefined ? 0 : Math.max(2, Math.round(w / hoch * 22));
      return `<span class="wz-vj${w === undefined ? ' leer' : ''}">
          <i style="height:${h}px"></i><b>${w === undefined ? '·' : w}</b>
          <em>'${String(j).slice(2)}</em></span>`;
    }).join('')}
  </span>`;
}

function karte(g) {
  const name = stand.namen[g.nr] || '';
  const faktor = faktorVon(stand, g);
  const offenerFaktor = g.art === 'hkv' && !faktor;
  return `<div class="wz-karte${aufgenommen === g.nr ? ' auf' : ''}
       ${offenerFaktor ? ' mahnt' : ''}" draggable="true" data-nr="${g.nr}">
      <button type="button" class="wz-nr" data-griff="${g.nr}"
        aria-label="${g.nr} aufnehmen">${g.nr}</button>
      <span class="wz-mitte">
        <input class="wz-name" data-name="${g.nr}" value="${esc(name)}"
               placeholder="Heizkörper benennen — z. B. Wohnzimmer links">
        <span class="wz-meta">${ARTNAME[g.art]} · ${esc(RAUMNAME[g.raum] || g.raum)}
          · früher ${esc(g.war)}${g.belegt
            ? ` · Faktor belegt (${esc(g.belegt)})` : ''}</span>
        ${verlaufHtml(g)}
      </span>
      ${g.art === 'hkv'
        ? `<span class="wz-faktor"><label>Faktor</label>
             <input data-faktor="${g.nr}" inputmode="decimal"
                    value="${faktor ?? ''}" placeholder="?"></span>`
        : '<span class="wz-faktor kwh">misst kWh</span>'}
    </div>`;
}

function zeichne() {
  const wurzel = document.getElementById('inhalt');
  const frei = GERAETE.filter(g => !stand.zuordnung[g.nr]);
  const f = fortschritt(stand);
  wurzel.innerHTML = `
    <div class="wz-kopf">
      <h2>Zähler benennen und zuordnen</h2>
      <p>${f.gesamt - f.offen} von ${f.gesamt} Zählern liegen auf einer Einheit.
         ${f.ohneName ? `${f.ohneName} ohne Namen.` : 'Alle benannt.'}
         ${f.ohneFaktor ? `<b>${f.ohneFaktor} ohne Faktor</b> — der steht auf der
           Abrechnung hinter dem Ablesewert.` : ''}</p>
      <p class="wz-hinweis">Kärtchen antippen, dann die Einheit antippen —
         oder am Rechner hinüberziehen.</p>
    </div>
    <div class="wz-frei" data-lane="">
      <h3>Noch nicht zugeordnet <span>${frei.length}</span></h3>
      <div class="wz-liste">${frei.map(karte).join('') ||
        '<p class="wz-leer">Alle Zähler liegen auf einer Einheit.</p>'}</div>
    </div>
    <div class="wz-lanes">${lanes().map(l => {
      const drin = GERAETE.filter(g => stand.zuordnung[g.nr] === l.id);
      const hkv = drin.filter(g => g.art === 'hkv').length;
      const wmz = drin.filter(g => g.art === 'wmz').length;
      return `<div class="wz-lane${aufgenommen ? ' bereit' : ''}" data-lane="${l.id}">
        <h3>${esc(l.titel)}<span>${l.zusatz}</span>
          <span class="wz-zahl">${hkv ? `${hkv} Heizkörper` : ''}${
            hkv && wmz ? ' · ' : ''}${wmz ? `${wmz} Wärmemengenzähler` : ''}${
            drin.length ? '' : 'leer'}</span></h3>
        <div class="wz-liste">${drin.map(karte).join('')}</div>
      </div>`;
    }).join('')}</div>`;
}

function ablegen(nr, lane) {
  stand.zuordnung[nr] = lane || '';
  aufgenommen = null;
  sichere(stand);
  zeichne();
  simulationAktualisieren(stand);
}

function verdrahte() {
  const wurzel = document.getElementById('inhalt');

  wurzel.addEventListener('click', e => {
    // Der Griff ist die Nummer. Das Namensfeld füllt die Mitte des Kärtchens
    // aus — würde ein Klick irgendwo darauf schon „aufnehmen" bedeuten, käme
    // man nie zum Tippen. Deshalb ein eigener, grosser Knopf.
    const griff = e.target.closest('[data-griff]');
    const laneEl = e.target.closest('[data-lane]');
    if (griff) {
      const nr = griff.dataset.griff;
      aufgenommen = aufgenommen === nr ? null : nr;
      zeichne();
      return;
    }
    if (e.target.matches('input')) return;              // tippen, nicht greifen
    if (laneEl && aufgenommen) ablegen(aufgenommen, laneEl.dataset.lane);
  });

  // Namen und Faktoren schreiben sich beim Tippen mit — kein Speichern-Knopf,
  // der vergessen werden könnte.
  wurzel.addEventListener('input', e => {
    const nr = e.target.dataset.name || e.target.dataset.faktor;
    if (!nr) return;
    if (e.target.dataset.name) stand.namen[nr] = e.target.value;
    else stand.faktoren[nr] = e.target.value.replace(',', '.');
    sichere(stand);
  });
  // Ein geänderter Faktor wirkt sich auf die Rechnung aus — aber erst nach
  // dem Feld verlassen, nicht bei jedem Tastendruck (sonst rechnet die
  // Simulation bei jeder Ziffer neu und die Eingabe stockt).
  wurzel.addEventListener('change', e => {
    if (e.target.dataset.faktor) simulationAktualisieren(stand);
  });

  wurzel.addEventListener('dragstart', e => {
    const k = e.target.closest('.wz-karte');
    if (!k) return;
    e.dataTransfer.setData('text/plain', k.dataset.nr);
    e.dataTransfer.effectAllowed = 'move';
  });
  wurzel.addEventListener('dragover', e => {
    if (e.target.closest('[data-lane]')) e.preventDefault();
  });
  wurzel.addEventListener('drop', e => {
    const lane = e.target.closest('[data-lane]');
    if (!lane) return;
    e.preventDefault();
    ablegen(e.dataTransfer.getData('text/plain'), lane.dataset.lane);
  });
}

export async function start() {
  let einheiten = [];
  try {
    einheiten = (await api(`/objekte/${SLUG}`)).einheiten || [];
  } catch {
    melde('Die Einheiten konnten nicht geladen werden.', 'neg');
  }
  // Die Garage heizt nicht — sie als Lane anzubieten hiesse, einen Fehler
  // einzuladen.
  stand = lade(einheiten.filter(e => !/garage/i.test(e.bezeichnung || '')));
  zeichne();
  verdrahte();
  await simulationEinbauen(stand);
}
