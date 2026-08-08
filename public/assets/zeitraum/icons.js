/* zeitraum/icons.js — inline-SVG-Icons. Flacher Strich-Stil wie kostenicons.js.
   Wird von den Render-Modulen importiert; nichts hier ist reaktiv. */

/* CCLV — der kleine Anhänger („Kleideranhänger"): ein flaches Etikett. */
export const ANH_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
  stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
  aria-hidden="true"><path d="M20.6 13.4 13.4 20.6a2 2 0 0 1-2.8 0l-7.4-7.4A2 2
  0 0 1 2.6 11.8V4.8a2 2 0 0 1 2-2h7a2 2 0 0 1 1.4.6l7.4 7.4a2 2 0 0 1 0
  2.8Z"/><circle cx="7.8" cy="7.8" r="1.4"/></svg>`;

/* Chevron für den Zählerstände-Einklapper (N60). */
export const CHEV_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
  stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"
  aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>`;

/* N143 — Zählerscheibe mit Zeiger. */
export const ZAEHLER_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
  stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"
  aria-hidden="true"><rect x="3.2" y="4.2" width="17.6" height="15.6" rx="3.2"/>
  <circle cx="12" cy="12" r="4.3"/><path d="M12 12 14.4 9.9"/>
  <path d="M7.2 12h-.9"/><path d="M17.7 12h-.9"/></svg>`;

/* Kleine Symbole für den Verteilungsschlüssel-Chip an der Zeile. */
const VST = 'stroke="currentColor" stroke-width="2" fill="none" ' +
  'stroke-linecap="round" stroke-linejoin="round"';
const vsvg = inner => `<svg viewBox="0 0 24 24" width="12" height="12"
  aria-hidden="true">${inner}</svg>`;
export const VKEY_IKON = {
  flaeche: vsvg(`<rect ${VST} x="4" y="4" width="16" height="16" rx="2"/>
    <path ${VST} d="M9 4v16M4 9h16" opacity=".45"/>`),
  personen: vsvg(`<circle ${VST} cx="9" cy="8" r="3"/>
    <path ${VST} d="M3.5 20a5.5 5.5 0 0 1 11 0"/>
    <path ${VST} d="M16 5.4a3 3 0 0 1 0 5.9M15 15.3a5.5 5.5 0 0 1 3.5 4.7"/>`),
  bewohnermonate: vsvg(`<circle ${VST} cx="12" cy="8" r="3.2"/>
    <path ${VST} d="M5.5 20a6.5 6.5 0 0 1 13 0"/>`),
  einheiten: vsvg(`<path ${VST} d="M4 10.5 12 4l8 6.5"/>
    <path ${VST} d="M6 9.8V20h12V9.8"/>`),
  verbrauch: vsvg(`<circle ${VST} cx="12" cy="12" r="8"/>
    <path ${VST} d="M12 12l3.5-2.5M12 7v1"/>`),
  prozent: vsvg(`<path ${VST} d="M6 18 18 6"/>
    <circle ${VST} cx="7.5" cy="7.5" r="1.7"/><circle ${VST} cx="16.5" cy="16.5" r="1.7"/>`),
  individuell: vsvg(`<circle ${VST} cx="12" cy="12" r="3"/>
    <path ${VST} d="M12 3.5v3M12 17.5v3M3.5 12h3M17.5 12h3"/>`),
  punkt: vsvg(`<circle ${VST} cx="12" cy="12" r="7.5"/>`),
};

/* N135 — Bleistift zum Umbenennen. */
export const STIFT_ICON = `<svg viewBox="0 0 16 16" aria-hidden="true" width="13" height="13">
  <path d="M11.2 1.8a1.4 1.4 0 0 1 2 2l-.8.8-2-2 .8-.8Z" fill="currentColor"/>
  <path d="M9.7 3.3l2 2-6.3 6.3-2.6.6.6-2.6 6.3-6.3Z" fill="currentColor"/>
</svg>`;

/* CCCLXXXVII — Zahnrad; der viewBox bekommt Rand, damit die äußeren
   Zähne nicht von der Strichbreite beschnitten werden. */
export const GEAR_ICON = `<svg viewBox="-2 -2 28 28" fill="none" stroke="currentColor"
  stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
  <circle cx="12" cy="12" r="3.2"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2
  2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0
  0 1-4 0v-.09A1.65 1.65 0 0 0 8.6 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1
  1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H2a2 2 0 0
  1 0-4h.09A1.65 1.65 0 0 0 3.6 8.6a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1
  2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H8a1.65 1.65 0 0 0 1-1.51V2a2 2 0 0 1
  4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83
  2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9c.2.63.77 1.06 1.43 1.09H22a2 2 0 0 1 0
  4h-.09a1.65 1.65 0 0 0-1.51 1Z"/></svg>`;
export const MUELL_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
  stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
  <path d="M3 6h18M8 6V4h8v2m-9 0 1 14h8l1-14"/></svg>`;
/* CCCLXXXVII — klare Beleg-Icons: Kamera, Upload, Wolke. */
export const FOTO_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
  stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
  <path d="M4 8.5A1.5 1.5 0 0 1 5.5 7h1.7l1-1.6A1 1 0 0 1 9.9 5h4.2a1 1 0 0 1 .84.45L15.8 7h1.7A1.5 1.5 0 0 1 19 8.5v8A1.5 1.5 0 0 1 17.5 18h-11A1.5 1.5 0 0 1 5 16.5Z"/>
  <circle cx="12" cy="12.5" r="3.1"/></svg>`;
export const UPLOAD_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
  stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
  <path d="M12 15V4.5"/><path d="M8 8l4-4 4 4"/>
  <path d="M5 15v3a1.5 1.5 0 0 0 1.5 1.5h11A1.5 1.5 0 0 0 19 18v-3"/></svg>`;
export const WOLKE_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
  stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
  <path d="M7 18a4 4 0 0 1-.4-7.98A5 5 0 0 1 16.3 9.2 3.9 3.9 0 0 1 17 18Z"/>
  <path d="M12 15.5V10m0 0-2 2m2-2 2 2"/></svg>`;

/* N280 — die WEG: ein Haus mit mehreren Parteien, davor das Blatt der
   Abrechnung, das die Verwaltung fertig herausgibt. */
export const WEG_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
  stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
  <path d="M3.4 10.2 10 4.8l6.6 5.4"/><path d="M5.2 9.4V19h9.6V9.4"/>
  <path d="M8 19v-3.4h3.6V19"/><path d="M8 12.2h3.6"/>
  <path d="M16.2 12.6h4.4v7.6h-4.4z"/><path d="M17.5 15h1.8M17.5 17.4h1.8"/></svg>`;

/* N280 — das Blatt mit Zeilen: „Abrechnung aufnehmen". */
export const BLATT_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
  stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
  <path d="M6.5 3.2h7.2L18.5 8v12.8h-12z"/><path d="M13.4 3.4V8h4.9"/>
  <path d="M9 12h6M9 15.2h6M9 18h3.6"/></svg>`;
