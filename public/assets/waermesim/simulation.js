/* N340l — die Simulation: für ein Jahr aus der Zähler-Zuordnung eine
   Nutzerliste bauen, ans Backend schicken (`waermesim.rechne`), das Ergebnis
   je Einheit dem Vorjahr gegenüberstellen.

   Bewusst auf derselben Seite wie die Zähler-Konfiguration (nicht als
   eigenes Werkzeug): der Nutzer soll benennen, zuordnen und sofort sehen,
   wohin das führt — und beim Verifizieren immer den Vorjahreswert daneben
   haben, nicht nur den aktuellen. */

import { api, esc, eur } from '../immo.js';
import { ALLGEMEIN, GERAETE, faktorVon, lade as ladeZaehlerstand } from './zaehler.js';
import { JAHRE_ABSTEIGEND, JAHRESDATEN, QUELLEN } from './jahre.js';

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

/* N340o/N340r — Nachweis: der Link auf die echte(n) Delta-t-PDF(s), aus
   denen die Zahlen dieses Jahres stammen. Ohne diesen Link bliebe die
   Simulationsbasis eine Behauptung; mit ihm lässt sich jede Zahl gegen das
   Original halten. */
function quellenHtml(jahr) {
  const quellen = QUELLEN[jahr];
  if (!quellen || !quellen.length) return '';
  return `<p class="wsim-quelle">Quelle: ${quellen.map(q =>
    `<a href="/api/dokumente/${q.id}/inhalt" target="_blank" rel="noopener">${esc(q.label)}</a>`
  ).join(' · ')}</p>`;
}

function alleQuellenHtml() {
  const jahre = Object.keys(QUELLEN).map(Number).sort((a, b) => b - a);
  return `<details class="wsim-alleq">
      <summary>Alle Delta-t-Gesamtabrechnungen in der Ablage (${
        jahre.reduce((n, j) => n + QUELLEN[j].length, 0)} Dokumente, ${jahre.length} Zeiträume)</summary>
      <ul>${jahre.map(j => `<li><b>${j}</b> — ${
          QUELLEN[j].map(q => `<a href="/api/dokumente/${q.id}/inhalt"
            target="_blank" rel="noopener">${esc(q.label)}</a>`).join(' · ')}
          ${JAHRESDATEN[j] ? '' : ' <span class="wsim-nochoffen">(Zahlen noch nicht erfasst)</span>'}</li>`).join('')}
        <li class="wsim-luecke">2019/20 und 2021/22 — keine vollständige
          Gesamtabrechnung in der Ablage gefunden.</li>
      </ul>
    </details>`;
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
    ${quellenHtml(gewaehltesJahr)}
    <div class="wsim-tabelle">
      <div class="wsim-kopf">
        <span></span><span>${vjJahr ? `${vjJahr - 1}/${String(vjJahr).slice(2)}` : 'Vorjahr'}</span>
        <span>${gewaehltesJahr - 1}/${String(gewaehltesJahr).slice(2)}</span><span></span>
      </div>
      ${zeilen || '<p class="wsim-leer">Noch keine Einheit hat einen Zähler mit Werten für dieses Jahr.</p>'}
      ${zeilen ? zeileHtml('Summe Heizkosten', summeJetzt, summeVorjahr) : ''}
    </div>`;
}

/* N340n — Warmwasser: Verhältnis zu den Heizkosten über alle bekannten
   Jahre, dazu die Warmwasser-Zähler, die bisher gefunden wurden — damit sich
   auf einen Blick prüfen lässt, ob vor Ort noch einer fehlt. Reine
   Bestandsaufnahme, keine eigene Rechnung: die Zahlen kommen unverändert aus
   `JAHRESDATEN` (Delta-t) und aus den Gerätestammdaten (`zaehler.js`). */
function warmwasserZaehlerHtml() {
  const ww = GERAETE.filter(g => g.art === 'wmz' || /^(WWZ|BZL)$/.test(g.war || ''));
  // Die zwei Boilerzulauf-/Warmwasserzähler-Nummern, die in den Ablese-
  // formularen auftauchten, ohne dass sie als eigenes Gerät in GERAETE
  // stehen (sie messen die ganze Liegenschaft, nicht eine Einheit — für die
  // Heizkörper-Zuordnung oben irrelevant, für die Vollständigkeit hier schon).
  const liegenschaft = [
    { nr: '8716 → 7592', bez: 'Boilerzulauf Liegenschaft (Nummer wechselte)' },
    { nr: '3274 → 6363', bez: 'Warmwasserzähler Anbau (Nummer wechselte)' },
  ];
  return `<ul class="wsim-wwliste">
      ${liegenschaft.map(z => `<li><b>${esc(z.nr)}</b> — ${esc(z.bez)}</li>`).join('')}
    </ul>
    <p class="wsim-wwhinweis">Nur diese zwei Warmwasser-/Boilerzulaufzähler
      sind bisher belegt — beide auf Liegenschaftsebene, keiner je Einheit.
      Die Heizkörperzähler oben liefern kein Warmwasser. Wenn vor Ort weitere
      Warmwasserzähler an einzelnen Wohnungen hängen, stehen sie noch nicht
      in dieser Liste.</p>`;
}

async function zeichneWarmwasser() {
  const wurzel = document.getElementById('wsim-ww');
  if (!wurzel) return;
  wurzel.innerHTML = `<p class="wsim-lade">Wird gerechnet …</p>`;

  // Zwei Blickwinkel je Jahr: der Kosten-Anteil laut Delta-t (direkt von der
  // Abrechnung) UND der Energie-Anteil nach §9 HeizkostenV (aus Liter/m³
  // gerechnet, unabhängig von den Zählern). Weichen beide stark voneinander
  // ab, ist das ein Hinweis auf eine falsche Eingabe — genau die Prüfung, die
  // der Nutzer sucht.
  const zeilen = (await Promise.all(JAHRE_ABSTEIGEND.map(async jahr => {
    const jd = JAHRESDATEN[jahr];
    if (!jd?.soll_gesamt) return null;
    const { heizkosten, warmwasser } = jd.soll_gesamt;
    const gesamt = heizkosten + warmwasser;
    const kostenAnteil = gesamt > 0 ? (warmwasser / gesamt) * 100 : 0;
    const erg = await rechneJahr(jahr);
    const energieAnteil = erg ? erg.anteile.warmwasser * 100 : null;
    return { jahr, warmwasser, heizkosten, kostenAnteil, energieAnteil,
             wwKwh: erg?.energie.ww_kwh, heizKwh: erg?.energie.heiz_kwh };
  }))).filter(Boolean);

  const hoechster = Math.max(...zeilen.map(z => z.kostenAnteil), 1);
  wurzel.innerHTML = `
    <h3 class="wsim-wwtitel">Warmwasser im Verhältnis zu den Heizkosten</h3>
    <p class="wsim-hinweis">Zwei unabhängige Rechnungen nebeneinander: der
      Kosten-Anteil steht direkt so auf der Delta-t-Abrechnung, der
      Energie-Anteil ergibt sich aus Litern Öl und m³ Warmwasser (§9
      HeizkostenV) — ohne die Zähler zu kennen. Laufen beide weit
      auseinander, lohnt ein zweiter Blick auf die Eingabe.</p>
    <div class="wsim-wwbalken">
      ${zeilen.map(z => `
        <div class="wsim-wwzeile">
          <span class="wsim-wwjahr">${z.jahr - 1}/${String(z.jahr).slice(2)}</span>
          <span class="wsim-wwspur"><span class="wsim-wwfuellung"
            style="width:${Math.max(4, z.kostenAnteil / hoechster * 100)}%"></span></span>
          <span class="wsim-wwproz">${z.kostenAnteil.toFixed(1).replace('.', ',')} %
            <span class="wsim-wwenergie">${z.energieAnteil != null
              ? `(Energie ${z.energieAnteil.toFixed(1).replace('.', ',')} %)` : ''}</span></span>
          <span class="wsim-wwbetrag">${eur(z.warmwasser)} WW / ${eur(z.heizkosten)} Heiz.
            ${z.wwKwh != null
              ? `<br>${Math.round(z.wwKwh).toLocaleString('de-DE')} kWh WW /
                 ${Math.round(z.heizKwh).toLocaleString('de-DE')} kWh Heiz.` : ''}</span>
        </div>`).join('')}
    </div>
    <h3 class="wsim-wwtitel">Gefundene Warmwasser-Zähler</h3>
    ${warmwasserZaehlerHtml()}`;
}

export function jahrWechseln(jahr) {
  gewaehltesJahr = jahr;
  // N340y — die Jahresknöpfe leben in `simulationEinbauen()` ausserhalb von
  // `#wsim-inhalt` und werden nur EINMAL gebaut; `zeichneSimulation()`
  // ersetzt allein `#wsim-inhalt`, die aktive Markierung oben blieb dadurch
  // am zuerst gewählten Jahr hängen, obwohl die Tabelle unten schon
  // umgesprungen war.
  document.querySelectorAll('.wsim-jahrknopf').forEach(b => {
    b.classList.toggle('an', Number(b.dataset.jahr) === jahr);
  });
  zeichneSimulation();
}

export async function simulationEinbauen(aktuellerStand) {
  stand = aktuellerStand;
  // N340n — ausserhalb von #inhalt: dort steht die fixierte Vorratsspalte
  // („Noch nicht zugeordnet"), und ein gemeinsames Grid liess deren
  // Sticky-Panel die Tabelle hier überlappen.
  const seite = document.getElementById('wsim-wrap');
  if (!seite || document.getElementById('wsim-block')) return;
  const block = document.createElement('div');
  block.id = 'wsim-block';
  block.innerHTML = `
    <h2 class="wsim-titel">Simulation — Heizkosten je Einheit</h2>
    <p class="wsim-hinweis">Rechnet dieselbe Aufstellung wie Delta-t, aus den
      Zählerständen oben. ${jahrWaehlerHtml()}</p>
    <div id="wsim-inhalt"></div>
    <div id="wsim-ww"></div>
    ${alleQuellenHtml()}`;
  seite.appendChild(block);
  block.querySelector('.wsim-jahre').addEventListener('click', e => {
    const knopf = e.target.closest('[data-jahr]');
    if (knopf) jahrWechseln(Number(knopf.dataset.jahr));
  });
  await zeichneSimulation();
  await zeichneWarmwasser();
}

export function simulationAktualisieren(aktuellerStand) {
  stand = aktuellerStand;
  ergebnisJeJahr = {};   // Zuordnung kann sich geändert haben — neu rechnen
  if (document.getElementById('wsim-block')) zeichneSimulation();
}
