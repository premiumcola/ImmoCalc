/* N340l — die Simulation: für ein Jahr aus der Zähler-Zuordnung eine
   Nutzerliste bauen, ans Backend schicken (`waermesim.rechne`), das Ergebnis
   je Einheit dem Vorjahr gegenüberstellen.

   Bewusst auf derselben Seite wie die Zähler-Konfiguration (nicht als
   eigenes Werkzeug): der Nutzer soll benennen, zuordnen und sofort sehen,
   wohin das führt — und beim Verifizieren immer den Vorjahreswert daneben
   haben, nicht nur den aktuellen. */

import { api, esc, eur } from '../immo.js';
import { ALLGEMEIN, GERAETE, faktorVon, lade as ladeZaehlerstand } from './zaehler.js';
import { JAHRE_ABSTEIGEND, JAHRESDATEN } from './jahre.js';

let stand = null;   // der Zähler-/Zuordnungsstand (dieselbe Quelle wie konfig.js)
let gewaehltesJahr = JAHRE_ABSTEIGEND[0];
let ergebnisJeJahr = {};   // Cache: Jahr -> Rechenergebnis (spart wiederholte Aufrufe)

/* Eine Lane (Einheit oder Allgemein) als "Nutzer" für `waermesim.rechne()`:
   Summe der EHKV-Einheiten (Faktor × Ablesewert) und der Wärmezähler-kWh
   aller Geräte, die auf dieser Lane liegen. */
function nutzerFuerJahr(laneId, jahr) {
  let ehkv = 0, kwh = 0, geraete = 0;
  for (const g of GERAETE) {
    if (stand.zuordnung[g.nr] !== laneId) continue;
    const wert = (g.staende || {})[jahr];
    if (wert === undefined) continue;
    geraete++;
    if (g.art === 'wmz') kwh += wert;
    else ehkv += wert * (faktorVon(stand, g) || 0);
  }
  return { ehkv: Math.round(ehkv * 1000) / 1000, kwh, geraete };
}

function laneName(laneId) {
  if (laneId === ALLGEMEIN) return 'Allgemein';
  const e = stand.einheiten.find(x => x.id === laneId);
  return e ? (e.name || `Einheit ${laneId}`) : laneId;
}

function laneFlaeche(laneId) {
  const e = stand.einheiten.find(x => x.id === laneId);
  return e ? (e.flaeche || 0) : 0;
}

async function rechneJahr(jahr) {
  if (ergebnisJeJahr[jahr]) return ergebnisJeJahr[jahr];
  const jd = JAHRESDATEN[jahr];
  if (!jd) return null;
  const lanes = [...stand.einheiten.map(e => e.id), ALLGEMEIN]
    .filter(id => GERAETE.some(g => stand.zuordnung[g.nr] === id));
  const nutzer = lanes.map(id => {
    const n = nutzerFuerJahr(id, jahr);
    return { name: laneName(id), flaeche: laneFlaeche(id),
             ehkv: n.ehkv, kwh: n.kwh, _geraete: n.geraete };
  }).filter(n => n._geraete > 0);
  const eingabe = { heizwert: 10.0, bestaende: jd.bestaende, rest: jd.rest,
                    ww_m3: jd.ww_m3, bloecke: jd.bloecke,
                    fest_anteil: jd.fest_anteil, nutzer };
  let erg;
  try {
    erg = await api('/waermesim/rechne', { method: 'POST', body: eingabe });
  } catch {
    return null;
  }
  erg._soll_gesamt = jd.soll_gesamt;
  erg._zeitraum = jd.zeitraum;
  ergebnisJeJahr[jahr] = erg;
  return erg;
}

/* N340m — Vorjahresvergleich: zu jeder Zeile das Ergebnis des vorherigen
   bekannten Jahres daneben, nicht nur eine blosse Zahl. Der Nutzer will beim
   Abschätzen und Prüfen nie nur den aktuellen Wert sehen. */
function vorjahrVon(jahr) {
  const kleinere = JAHRE_ABSTEIGEND.filter(j => j < jahr);
  return kleinere.length ? kleinere[0] : null;
}

function jahrWaehlerHtml() {
  return `<div class="wsim-jahre">${JAHRE_ABSTEIGEND.map(j =>
    `<button type="button" class="wsim-jahrknopf${j === gewaehltesJahr ? ' an' : ''}"
       data-jahr="${j}">${j - 1}/${String(j).slice(2)}</button>`).join('')}</div>`;
}

function zeileHtml(name, jetzt, vorjahr) {
  const diff = vorjahr != null ? jetzt - vorjahr : null;
  const diffHtml = diff == null ? ''
    : `<span class="wsim-diff ${diff > 0 ? 'auf' : diff < 0 ? 'ab' : ''}">${
        diff === 0 ? '±0' : (diff > 0 ? '+' : '') + eur(diff)}</span>`;
  return `<div class="wsim-zeile">
      <span class="wsim-name">${esc(name)}</span>
      <span class="wsim-vorjahr">${vorjahr != null ? eur(vorjahr) : '—'}</span>
      <span class="wsim-jetzt">${eur(jetzt)}</span>
      ${diffHtml}
    </div>`;
}

async function zeichneSimulation() {
  const wurzel = document.getElementById('wsim-inhalt');
  if (!wurzel) return;
  wurzel.innerHTML = `<div class="wsim-lade">Wird gerechnet …</div>`;

  const erg = await rechneJahr(gewaehltesJahr);
  const vjJahr = vorjahrVon(gewaehltesJahr);
  const ergVorjahr = vjJahr ? await rechneJahr(vjJahr) : null;

  if (!erg) {
    wurzel.innerHTML = `<p class="wsim-leer">Für ${gewaehltesJahr} liegen noch keine
      Jahresdaten vor.</p>`;
    return;
  }
  const vjZeile = name => ergVorjahr?.nutzer.find(n => n.name === name);

  const zeilen = erg.nutzer.map(n => {
    const vj = vjZeile(n.name);
    return zeileHtml(n.name, n.heizkosten, vj ? vj.heizkosten : null);
  }).join('');

  const summeJetzt = erg.nutzer.reduce((s, n) => s + n.heizkosten, 0);
  const summeVorjahr = ergVorjahr
    ? ergVorjahr.nutzer.reduce((s, n) => s + n.heizkosten, 0) : null;

  const soll = erg._soll_gesamt?.heizkosten;
  const sollHtml = soll != null
    ? `<p class="wsim-soll">Delta-t weist für ${erg._zeitraum} <b>${eur(soll)}</b>
        Heizkosten aus (Gesamt-Vorprüfung, kein Nutzer-Abgleich, da die
        Zuordnung neu ist). Gerechnet: <b>${eur(summeJetzt)}</b>${
          Math.abs(summeJetzt - soll) > 1
            ? ` <span class="wsim-abw">(Abweichung ${eur(summeJetzt - soll)})</span>`
            : ' <span class="wsim-treffer">✓ trifft</span>'}</p>`
    : '';

  wurzel.innerHTML = `
    ${sollHtml}
    <div class="wsim-tabelle">
      <div class="wsim-kopf">
        <span></span><span>${vjJahr ? `${vjJahr - 1}/${String(vjJahr).slice(2)}` : 'Vorjahr'}</span>
        <span>${gewaehltesJahr - 1}/${String(gewaehltesJahr).slice(2)}</span><span></span>
      </div>
      ${zeilen || '<p class="wsim-leer">Noch keine Einheit hat einen Zähler mit Werten für dieses Jahr.</p>'}
      ${zeilen ? zeileHtml('Summe Heizkosten', summeJetzt, summeVorjahr) : ''}
    </div>`;
}

export function jahrWechseln(jahr) {
  gewaehltesJahr = jahr;
  zeichneSimulation();
}

export async function simulationEinbauen(aktuellerStand) {
  stand = aktuellerStand;
  const seite = document.getElementById('inhalt');
  if (!seite || document.getElementById('wsim-block')) return;
  const block = document.createElement('div');
  block.id = 'wsim-block';
  block.innerHTML = `
    <h2 class="wsim-titel">Simulation — Heizkosten je Einheit</h2>
    <p class="wsim-hinweis">Rechnet dieselbe Aufstellung wie Delta-t, aus den
      Zählerständen oben. ${jahrWaehlerHtml()}</p>
    <div id="wsim-inhalt"></div>`;
  seite.appendChild(block);
  block.querySelector('.wsim-jahre').addEventListener('click', e => {
    const knopf = e.target.closest('[data-jahr]');
    if (knopf) jahrWechseln(Number(knopf.dataset.jahr));
  });
  await zeichneSimulation();
}

export function simulationAktualisieren(aktuellerStand) {
  stand = aktuellerStand;
  ergebnisJeJahr = {};   // Zuordnung kann sich geändert haben — neu rechnen
  if (document.getElementById('wsim-block')) zeichneSimulation();
}
