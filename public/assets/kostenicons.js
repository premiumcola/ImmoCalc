/* Einheitliche Symbole für Kostenarten — ein Raster, eine Strichstärke,
   alle in currentColor. So wirkt die Checkliste ruhig und die Farbe kann
   den Zustand tragen (grau = offen, grün = erledigt). */

const P = 'stroke="currentColor" stroke-width="1.7" fill="none" ' +
  'stroke-linecap="round" stroke-linejoin="round"';

const SYMBOLE = {
  wasser: `<path ${P} d="M12 3.5c3.2 3.6 5 6.2 5 8.6a5 5 0 0 1-10 0c0-2.4 1.8-5 5-8.6Z"/>`,
  heizung: `<rect ${P} x="4" y="7" width="16" height="12" rx="2"/>
            <path ${P} d="M9 7v12M15 7v12M8 4.5c0-1 1-1 1-2M12 4.5c0-1 1-1 1-2M16 4.5c0-1 1-1 1-2"/>`,
  flamme: `<path ${P} d="M12 3c.6 3-2 4-2 7a4 4 0 0 0 8 0c0-1.4-.6-2.6-1.4-3.6.2 1.6-.6 2.4-1.4 2.4.4-2.6-1.2-4.6-3.2-5.8Z"/>
           <path ${P} d="M8.5 12.5c-.6.9-1 2-1 3.1A5.5 5.5 0 0 0 13 21"/>`,
  muell: `<path ${P} d="M4.5 7h15M9.5 7V5.5a1 1 0 0 1 1-1h3a1 1 0 0 1 1 1V7"/>
          <path ${P} d="M6.5 7l.8 11.6a1.6 1.6 0 0 0 1.6 1.4h6.2a1.6 1.6 0 0 0 1.6-1.4L17.5 7"/>
          <path ${P} d="M10.5 11v5M13.5 11v5"/>`,
  strom: `<path ${P} d="M13.5 3 6 13.5h5L10.5 21 18 10.5h-5L13.5 3Z"/>`,
  haus: `<path ${P} d="M4 10.5 12 4l8 6.5"/><path ${P} d="M6 9.8V20h12V9.8"/>
         <path ${P} d="M10 20v-5h4v5"/>`,
  schild: `<path ${P} d="M12 3.5 5.5 6v6c0 4 2.8 6.9 6.5 8.5 3.7-1.6 6.5-4.5 6.5-8.5V6L12 3.5Z"/>`,
  paragraf: `<path ${P} d="M4.5 7.5h15M4.5 12h15M4.5 16.5h9"/>`,
  garten: `<path ${P} d="M12 21v-6"/>
           <path ${P} d="M12 15c-3.5 0-5.5-2-5.5-5 3.5 0 5.5 2 5.5 5Z"/>
           <path ${P} d="M12 15c3.5 0 5.5-2 5.5-5-3.5 0-5.5 2-5.5 5Z"/>`,
  werkzeug: `<path ${P} d="m14.5 6.5 3-3a4 4 0 0 1-5 5l-7 7a1.8 1.8 0 1 0 2.5 2.5l7-7a4 4 0 0 0 5-5l-3 3-2.5-2.5Z"/>`,
  aufzug: `<rect ${P} x="5" y="3.5" width="14" height="17" rx="2"/>
           <path ${P} d="M12 3.5v17M9 9l-1.5 2h3L9 9ZM15 15l1.5-2h-3l1.5 2Z"/>`,
  melder: `<circle ${P} cx="12" cy="12" r="3"/>
           <path ${P} d="M7.8 7.8a6 6 0 0 0 0 8.4M16.2 7.8a6 6 0 0 1 0 8.4"/>
           <path ${P} d="M5 5a10 10 0 0 0 0 14M19 5a10 10 0 0 1 0 14"/>`,
  zaehler: `<circle ${P} cx="12" cy="12" r="8"/><path ${P} d="M12 12l3.5-2.5M12 7v1"/>`,
  bank: `<path ${P} d="M4 9.5 12 4l8 5.5"/><path ${P} d="M6 9.5V19M10 9.5V19M14 9.5V19M18 9.5V19"/>
         <path ${P} d="M4 19h16"/>`,
  schnee: `<path ${P} d="M12 3v18M4.2 7.5l15.6 9M19.8 7.5l-15.6 9"/>`,
  brief: `<rect ${P} x="3.5" y="5.5" width="17" height="13" rx="2"/>
          <path ${P} d="m4.5 7 7.5 5.5L19.5 7"/>`,
  punkt: `<circle ${P} cx="12" cy="12" r="7.5"/><path ${P} d="M12 8.5v4M12 15.5h.01"/>`,
  schluessel: `<circle ${P} cx="8" cy="8" r="4"/>
               <path ${P} d="m11 11 8 8M16 16l-2 2M19 19l-2 2"/>`,
  person: `<circle ${P} cx="12" cy="8" r="3.5"/>
           <path ${P} d="M5.5 20a6.5 6.5 0 0 1 13 0"/>`,
  vertrag: `<path ${P} d="M6 3.5h8l4 4V20a.5.5 0 0 1-.5.5h-11A.5.5 0 0 1 6 20V4a.5.5 0 0 1 .5-.5Z"/>
            <path ${P} d="M14 3.5V8h4M9 12.5h6M9 16h4"/>`,
};

/* Schlüsselwort -> Symbol. Erster Treffer gewinnt, deshalb stehen
   spezifische Begriffe vor allgemeinen. */
const ZUORDNUNG = [
  ['warmwasser', 'heizung'], ['heizkosten', 'heizung'], ['heizöl', 'flamme'],
  ['heizung', 'heizung'], ['kaminkehrer', 'flamme'], ['kamin', 'flamme'],
  ['niederschlagswasser', 'wasser'], ['abwasser', 'wasser'],
  ['gartenwasser', 'garten'], ['kaltwasserzähler', 'zaehler'],
  ['wasserzähler', 'zaehler'], ['zähler', 'zaehler'], ['wasser', 'wasser'],
  ['müll', 'muell'], ['abfall', 'muell'],
  ['allgemeinstrom', 'strom'], ['strom', 'strom'],
  ['grundsteuer', 'paragraf'], ['steuer', 'paragraf'],
  ['versicherung', 'schild'], ['haftpflicht', 'schild'],
  ['hausmeister', 'werkzeug'], ['hausverwaltung', 'haus'],
  ['gartenpflege', 'garten'], ['garten', 'garten'],
  ['aufzug', 'aufzug'], ['rauchwarnmelder', 'melder'], ['rauchmelder', 'melder'],
  ['winterdienst', 'schnee'], ['straßenreinigung', 'schnee'],
  ['bankspesen', 'bank'], ['kredit', 'bank'], ['darlehen', 'bank'],
  ['korrespondenz', 'brief'], ['nebenkosten', 'haus'],
  ['mietvertrag', 'vertrag'], ['miete', 'schluessel'], ['mieter', 'person'],
  ['eigentümer', 'person'], ['zahlung', 'paragraf'],
];

/** Symbolname zu einer Kostenart — mit Rückfall auf einen neutralen Punkt. */
export function symbolFuer(kostenart) {
  const name = String(kostenart || '').toLowerCase();
  for (const [wort, symbol] of ZUORDNUNG) {
    if (name.includes(wort)) return symbol;
  }
  return 'punkt';
}

/** Fertiges SVG für eine Kostenart. */
export function kostenIcon(kostenart, klasse = '') {
  const symbol = SYMBOLE[symbolFuer(kostenart)] || SYMBOLE.punkt;
  return `<svg class="${klasse}" viewBox="0 0 24 24" width="24" height="24"
               aria-hidden="true">${symbol}</svg>`;
}
