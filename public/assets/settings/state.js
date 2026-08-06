/* N216 — Modul-Zustand fuer die Einstellungen-Seite.

   Die Fach-Module (verknuepfungen, nextcloud, ki, mail, vorlage, unterordner,
   umzug, einsortieren, import, version, rechenlogik) teilen sich hier ihre
   gemeinsamen Helfer: die Meldungen an Ort und Stelle (`melde`/`meldungWeg`),
   den knapp befristeten Statusabruf fuer die Live-Kacheln (`vHole`,
   `vHoleGeteilt`, `vGeteiltReset`) und die kleinen Formatierer (`vKurz`,
   `vModell`, `ortszeit`, `belegText`). Alles verhaltensgleich zum bisherigen
   Inline-Skript in settings.html — nur der Ort aendert sich. */

/* Frist fuer die Statusabrufe der Live-Kacheln (N133). */
export const VZEITGRENZE = 6000;

/* Gemeinsame SVG-Attribute fuer die kleinen Kachel-Symbole. */
export const VSTRICH = 'stroke="currentColor" stroke-width="1.7" fill="none" '
  + 'stroke-linecap="round" stroke-linejoin="round"';

/* Die fuenf Live-Kachel-Symbole als reine Pfade — der umgebende <svg> steht
   im HTML-Renderer. */
export const VSYMBOLE = {
  wolke: `<path ${VSTRICH} d="M7.6 18.5h9a3.9 3.9 0 0 0 .5-7.8 5.4 5.4 0 0
          0-10.4 1.1 3.5 3.5 0 0 0 .9 6.7Z"/>`,
  wallbox: `<rect ${VSTRICH} x="4.5" y="3.5" width="10.5" height="17" rx="2.5"/>
            <path ${VSTRICH} d="M10.8 7.5 8.5 11.6h3.1l-2.3 4.4"/>
            <path ${VSTRICH} d="M15 9.5h2.6a1.9 1.9 0 0 1 1.9 1.9V16a1.75 1.75
            0 0 1-3.5 0v-2.2"/>`,
  solar: `<path ${VSTRICH} d="M4 17.5h16l-2.4-7.5H6.4L4 17.5Z"/>
          <path ${VSTRICH} d="M12 10v7.5M5.7 13.7h12.6"/>
          <path ${VSTRICH} d="M12 3v2.4M7.4 4.6l1.2 1.8M16.6 4.6l-1.2 1.8"/>`,
  funke: `<path ${VSTRICH} d="M11 3.5c.9 3.6 2.1 4.8 5.7 5.7-3.6.9-4.8
          2.1-5.7 5.7-.9-3.6-2.1-4.8-5.7-5.7 3.6-.9 4.8-2.1 5.7-5.7Z"/>
          <path ${VSTRICH} d="M17.2 14.4c.45 1.8 1.05 2.35 2.8 2.8-1.75.45-2.35
          1-2.8 2.8-.45-1.8-1.05-2.35-2.8-2.8 1.75-.45 2.35-1 2.8-2.8Z"/>`,
  brief: `<rect ${VSTRICH} x="3.5" y="5.5" width="17" height="13" rx="2"/>
          <path ${VSTRICH} d="m4.6 7.2 7.4 5.4 7.4-5.4"/>`,
};

/* Ein Abruf mit knapper Frist. Nie werfend — der Aufrufer bekommt immer
   einen Zustand zurueck:
     { da:false }            der Endpunkt gibt es (noch) nicht
     { fehler:'…' }          keine oder eine kaputte Antwort
     { da:true, daten:{…} }  alles gut */
export async function vHole(pfad, frist = VZEITGRENZE) {
  const abbruch = new AbortController();
  const uhr = setTimeout(() => abbruch.abort(), frist);
  try {
    const antwort = await fetch('/api' + pfad,
      { signal: abbruch.signal, cache: 'no-store' });
    if (antwort.status === 404) return { da: false };
    if (!antwort.ok) return { fehler: `Antwort ${antwort.status}` };
    return { da: true, daten: await antwort.json() };
  } catch {
    return { fehler: abbruch.signal.aborted ? 'keine Antwort in 6 s'
                                            : 'nicht erreichbar' };
  } finally {
    clearTimeout(uhr);
  }
}

/* Zwei Kacheln haengen am selben Schluessel (Belegerkennung und SolarEdge).
   Der Statusabruf pingt echt bei Anthropic — also je Durchlauf nur einmal.
   `vGeteiltReset` startet den Cache neu, sobald der Nutzer „Erneut pruefen"
   drueckt oder eine Verbindung frisch eingerichtet wurde. */
let vGeteilt = new Map();
export function vHoleGeteilt(pfad) {
  if (!vGeteilt.has(pfad)) vGeteilt.set(pfad, vHole(pfad));
  return vGeteilt.get(pfad);
}
export function vGeteiltReset() {
  vGeteilt = new Map();
}

/* Adresse kurz halten: Schema und Schluss-Slash weg — sonst frisst die
   Kachel schon das www vom Rest. */
export const vKurz = (adresse) => String(adresse || '')
  .replace(/^https?:\/\//, '').replace(/\/+$/, '');

/* Modellnamen tragen ein Datum am Ende — in der Kachel nur Ballast. */
export const vModell = (name) => String(name || '').replace(/-\d{8}$/, '');

/* Version + Uhrzeit ins Deutsche uebersetzen. */
export const ortszeit = (iso) => iso
  ? new Date(iso).toLocaleString('de-DE',
      { day: '2-digit', month: '2-digit', year: 'numeric',
        hour: '2-digit', minute: '2-digit' })
  : null;

/* Meldungen im Dialog — an, weg, gut/schlecht. Verhaltensgleich zum bisherigen
   `melde`/`meldungWeg` in settings.html. */
export function melde(feld, text, gut = false) {
  feld.textContent = text;
  feld.className = 'meldung an ' + (gut ? 'gut' : 'schlecht');
}
export const meldungWeg = feld => { feld.className = 'meldung'; };

/* Einheitliche Ein-/Mehrzahl fuer Belege — mehrfach benutzt in umzug/einsortieren. */
export const belegText = n => `${n} ${n === 1 ? 'Beleg' : 'Belege'}`;
