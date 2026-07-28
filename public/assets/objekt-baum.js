import { api, esc } from './immo.js';
import { kostenIcon } from './kostenicons.js';
import { slug } from './objekt-state.js';

/* ---- CCXCIX — der Dokumentenbaum -----------------------------------------
   Die Ablage als Gliederung: je Kategorie ein Ast in seiner Farbe und mit dem
   Symbol der Rubrik, darunter „wie Früchte" die Dokumente. Grau = hängt noch an
   keinem Eintrag; von dort lässt es sich zuordnen. Oben Filter-Chips mit
   denselben Symbolen — sie zeigen nur, was es wirklich gibt. */
// Vorschlag der Zielrubrik beim Zuordnen, abgeleitet aus dem echten Ordner
// (CCCXVI). Der Dialog lässt sie ohnehin ändern.
const ORDNER_RUBRIK = {
  '60_Nebenkosten': 'nebenkosten', '70_Steuer_Finanzamt': 'zahlungen',
  '40_Kauf_Eigentum_Finanzierung': 'notarvertraege',
  '50_Pacht_und_Paechter': 'mieten', '20_Mietvertraege_Vermietung': 'mieten',
  '01_Allgemein_Hauskonto': 'versicherungen',
};
// Farbe/Symbol je Ordner — an der Zahl (10_/40_/60_ …) festgemacht.
const ORDNER_FARBE = {
  '10': '#5C6B70', '20': 'var(--pos)', '30': '#5C6B70',
  '40': 'var(--teal)', '50': 'var(--pos)', '55': '#5C6B70',
  '60': 'var(--teal-d)', '70': 'var(--amber)', '80': '#5C6B70',
  '98': '#8A9599', '99': '#8A9599', '01': 'var(--soft)', '': 'var(--neg)',
};
const ORDNER_IKON = {
  '10': 'Dokument', '20': 'Miete', '30': 'Korrespondenz',
  '40': 'Notarvertrag', '50': 'Miete', '60': 'Nebenkosten',
  '70': 'Finanzamt', '80': 'Haus', '99': 'Dokument', '01': 'Versicherung',
  '': 'Dokument',
};
// CCCXXXII-c — klarere Anzeige-Namen für Ordner, deren echter Name nicht sagt,
// was drin liegt (Cloud-Ordnername bleibt unangetastet). Grobe Ordner tragen
// die Rubriken, die sie bündeln, damit Filter und Rubrik zueinander passen.
const ORDNER_ANZEIGE = {
  '01_Allgemein_Hauskonto': 'Allgemein & Versicherungen',
  '40_Kauf_Eigentum_Finanzierung': 'Kauf · Notar · Kredite · Grundschuld',
  '50_Bauphase_Projekte': 'Bauphase & Instandhaltung',
};
const ordnerTitel = a => ORDNER_ANZEIGE[a.ordner] || a.titel;
const ordnerNr = o => (o || '').slice(0, 2).match(/^\d\d$/) ? o.slice(0, 2) : '';
const ordnerFarbe = o => ORDNER_FARBE[ordnerNr(o)] || 'var(--soft)';
const ordnerIkon = o => ORDNER_IKON[ordnerNr(o)] || 'Dokument';
// Statuszeichen im Baum (CCCXXI): der Haken für „einem Eintrag zugeordnet",
// ein kleines Belegblatt für „als Beleg angehängt" (statt des ⊙-Kreises).
const HAKEN_ICON = `<svg viewBox="0 0 24 24" width="15" height="15" fill="none"
  stroke="currentColor" stroke-width="2.4" stroke-linecap="round"
  stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4 4 10-10.5"/></svg>`;
const BELEG_ICON = `<svg viewBox="0 0 24 24" width="15" height="15" fill="none"
  stroke="currentColor" stroke-width="1.9" stroke-linecap="round"
  stroke-linejoin="round" aria-hidden="true">
  <path d="M7 3.5h6l4 4V19a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4.5a1 1 0 0 1 1-1Z"/>
  <path d="M13 3.5V8h4M8.5 12.5h7M8.5 15.5h5"/></svg>`;
const PRO_AST = 10;                     // so viele Früchte je Ast, dann „mehr"
let baumDaten = null;
let baumFilter = '';                    // '' = alle Äste
let baumMehr = new Set();               // Äste, die alles zeigen
// CCCXXXI — Ordner sind standardmäßig eingeklappt; `baumOffen` merkt die
// aufgeklappten. `baumJahr` filtert die Nebenkosten-Belege auf ein Jahr.
let baumOffen = new Set();
let baumJahr = '';

async function baumZeigen() {
  const ziel = document.getElementById('dokbaum');
  if (!ziel) return;
  try {
    baumDaten = await api(`/dokumente/objekt/${encodeURIComponent(slug)}/baum`);
  } catch { ziel.innerHTML = ''; return; }
  baumMalen();
}

function baumMalen() {
  const ziel = document.getElementById('dokbaum');
  if (!ziel || !baumDaten) return;
  const aeste = baumDaten.aeste || [];
  if (!aeste.length) {
    ziel.innerHTML = `<div class="baumleer">Noch keine Dokumente in der Ablage
      dieser Immobilie.</div>`;
    return;
  }
  const chip = (wert, text, ikon, farbe, zahl) => `
    <button class="bfilter${baumFilter === wert ? ' an' : ''}" data-bfilter="${esc(wert)}"
            ${farbe ? `style="--bf:${farbe}"` : ''}>
      ${ikon ? `<span class="bi">${kostenIcon(ikon)}</span>` : ''}${esc(text)}
      <span class="bz">${zahl}</span></button>`;

  const filter = [chip('', 'Alle', 'Dokument', 'var(--ink)', baumDaten.gesamt)]
    .concat(aeste.map(a => chip(a.ordner, ordnerTitel(a), ordnerIkon(a.ordner),
                                ordnerFarbe(a.ordner), a.anzahl))).join('');

  // Eine Frucht (Dokument) — optional eingerückt als Kind einer Hauptdatei.
  // Ist es zugeordnet, ist das Statuszeichen ein Knopf: antippen zum Umhängen.
  const frucht = (d, farbe, kind = false) => `
      <div class="frucht${d.zugeordnet ? '' : ' offen'}${kind ? ' kind' : ''}"
           data-dok="${d.id}">
        <span class="fp" style="background:${d.zugeordnet ? farbe : 'transparent'};
              border-color:${farbe}"></span>
        <span class="fn" data-beleg="${d.id}"
              data-name="${esc(d.dateiname)}">${esc(d.dateiname)}</span>
        ${d.zugeordnet
          ? `<button class="fstatus${d.info ? ' info' : ' pos'}"
               data-umhaengen="${d.id}" data-rubrik="${esc(ORDNER_RUBRIK[a_ordner] || '')}"
               title="${d.info ? 'Als Beleg angehängt' : 'Einem Eintrag zugeordnet'}
 — antippen zum Umhängen">${d.info ? BELEG_ICON : HAKEN_ICON}</button>`
          : `<button class="fzu" data-zuordnen="${d.id}"
               data-rubrik="${esc(ORDNER_RUBRIK[a_ordner] || '')}"
               title="Diesem Beleg einen Eintrag anlegen">zuordnen</button>`}
      </div>`;

  let a_ordner = '';
  const gezeigt = baumFilter ? aeste.filter(a => a.ordner === baumFilter) : aeste;
  const zweige = gezeigt.map(a => {
    a_ordner = a.ordner;
    const farbe = ordnerFarbe(a.ordner);
    // CCCXXXI — standardmäßig eingeklappt; ein gesetzter Filter klappt den
    // betroffenen Ordner auf. (Leerer Filter darf den Hauptordner-Ast mit
    // ordner==='' nicht versehentlich öffnen.)
    const offen = baumOffen.has(a.ordner) || (!!baumFilter && baumFilter === a.ordner);
    // CCCXVII — Kinder (Info-Belege) unter ihre Hauptdatei einrücken, aber nur,
    // wenn die Hauptdatei im selben Ordner liegt. Liegt sie woanders, steht das
    // Kind eigenständig hier (sonst verschwände es aus dem Baum).
    const idsHier = new Set(a.dokumente.map(d => d.id));
    const kinderVon = new Map();
    for (const d of a.dokumente) if (d.unter && idsHier.has(d.unter)) {
      if (!kinderVon.has(d.unter)) kinderVon.set(d.unter, []);
      kinderVon.get(d.unter).push(d);
    }
    let oberste = a.dokumente.filter(d => !d.unter || !idsHier.has(d.unter));
    // CCCXXXI — neueste oben: nach Jahr, dann Dateiname absteigend.
    oberste = oberste.slice().sort((x, y) => (y.jahr || 0) - (x.jahr || 0)
      || String(y.dateiname).localeCompare(String(x.dateiname), 'de'));
    const kopf = `<button class="zkopf" data-bast="${esc(a.ordner)}"
        aria-expanded="${offen}">
        <span class="zi">${kostenIcon(ordnerIkon(a.ordner))}</span>
        <span class="zt"><span class="zn">${esc(ordnerTitel(a))}</span>
          <span class="zo">${esc(a.ordner || 'im Hauptordner')}</span></span>
        <span class="zz">${a.offen ? `${a.offen} offen` : 'alles zugeordnet'}</span>
        <span class="zpfeil${offen ? ' auf' : ''}" aria-hidden="true">›</span>
      </button>`;
    if (!offen) {
      return `<section class="zweig zu" style="--zw:${farbe}">${kopf}</section>`;
    }
    // CCCXXXI — Jahres-Filter nur im Nebenkosten-Ordner (60_…), viele Belege.
    const istNK = ordnerNr(a.ordner) === '60';
    let jahre = [];
    if (istNK) {
      jahre = [...new Set(oberste.map(d => d.jahr).filter(Boolean))]
        .sort((p, q) => q - p);
      if (baumJahr) oberste = oberste.filter(d => String(d.jahr) === String(baumJahr));
    }
    const alle = baumMehr.has(a.ordner);
    const docs = alle ? oberste : oberste.slice(0, PRO_AST);
    const fruechte = docs.map(d =>
      frucht(d, farbe) + (kinderVon.get(d.id) || [])
        .map(k => frucht(k, farbe, true)).join('')).join('');
    const rest = oberste.length - docs.length;
    const jahrLeiste = istNK && jahre.length > 1 ? `<div class="jahr-leiste">
        <button class="jchip${!baumJahr ? ' an' : ''}" data-bjahr="">Alle</button>
        ${jahre.map(j => `<button class="jchip${String(baumJahr) === String(j)
          ? ' an' : ''}" data-bjahr="${j}">${j}</button>`).join('')}</div>` : '';
    return `<section class="zweig" style="--zw:${farbe}">${kopf}
      ${jahrLeiste}
      <div class="fruechte">${fruechte}</div>
      ${rest > 0 ? `<button class="mehrbtn" data-bmehr="${esc(a.ordner)}"
          >… ${rest} weitere zeigen</button>` : ''}
    </section>`;
  }).join('');

  ziel.innerHTML = `<div class="bfilter-leiste">${filter}</div>
    <div class="baum-legende">
      <span class="bl-hak">${HAKEN_ICON}</span> einem Eintrag zugeordnet
      <span class="bl-bel">${BELEG_ICON}</span> als Beleg angehängt
      <span class="bl-off">○</span> noch offen — antippen zum Zuordnen
    </div>
    <div class="baum">${zweige}</div>`;
}

/* Aktionen des Baums nach aussen — der Zustand bleibt privat in diesem Modul.
   Die Klick-Handler der Seite rufen sie statt die Variablen direkt zu setzen. */
export function baumFilterUmschalten(wert) {
  baumFilter = (baumFilter === wert) ? '' : wert;
  baumMalen();
}
export function baumMehrZeigen(ordner) { baumMehr.add(ordner); baumMalen(); }
export function baumAstUmschalten(ordner) {
  if (baumOffen.has(ordner)) baumOffen.delete(ordner); else baumOffen.add(ordner);
  baumMalen();
}
export function baumJahrSetzen(jahr) { baumJahr = jahr; baumMalen(); }
export function getBaumDaten() { return baumDaten; }

export { baumZeigen, baumMalen, HAKEN_ICON, BELEG_ICON };
