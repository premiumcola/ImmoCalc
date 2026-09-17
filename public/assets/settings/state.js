/* N216 — Modul-Zustand fuer die Einstellungen-Seite.

   Die Fach-Module (verknuepfungen, nextcloud, ki, mail, vorlage, backup)
   teilen sich hier ihre gemeinsamen Helfer: die Meldungen an Ort und Stelle
   (`feldmeldung`/`meldungWeg`), den knapp befristeten Statusabruf fuer die
   Dienst-Kacheln (`vHole`, `vHoleGeteilt`, `vGeteiltReset`), die kleinen
   Formatierer (`vKurz`, `vModell`, `ortszeit`) und die Passwortabfrage
   (`passwortAbfrage`).

   Die Zeichen der Kacheln stehen seit N479 in `symbole.js`. Das Passwortfeld
   mit Auge (`passwortFeld`, `augenBinden`) ist in N482 nach `immo.js`
   gewandert: der Anmeldescreen braucht es genauso, und der soll dafür kein
   Einstellungsmodul importieren müssen. */
import { baueDialog, passwortFeld, augenBinden } from '../immo.js';

/* Frist fuer die Statusabrufe der Dienst-Kacheln (N133). */
const VZEITGRENZE = 6000;

/* Ein Abruf mit knapper Frist. Nie werfend — der Aufrufer bekommt immer
   einen Zustand zurueck:
     { da:false }            den Endpunkt gibt es (noch) nicht
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

/* N479 — „die Kacheln bitte neu befragen". Wer eine Verbindung frisch
   eingerichtet hat, will sie sofort grün sehen. Bewusst über ein Ereignis am
   Dokument statt über einen Import: sonst müsste jedes Fach-Modul die
   Kachel-Leiste kennen, und die Kachel-Leiste kennt schon jedes Fach-Modul —
   das wäre ein Ringschluss. */
export const diensteAuffrischen = () =>
  document.dispatchEvent(new Event('dienste:aendern'));

/* Meldungen im Dialog — an, weg, gut/schlecht. */
export function feldmeldung(feld, text, gut = false) {
  feld.textContent = text;
  feld.className = 'meldung an ' + (gut ? 'gut' : 'schlecht');
}
export const meldungWeg = feld => { feld.className = 'meldung'; };

/* Ein kleiner Dialog, der nur nach dem Passwort der Familie fragt — fuer
   Zwei-Faktor, Backup und alles Weitere dieselbe Form. Loest mit dem
   Passwort auf, oder mit `null`, wenn abgebrochen wurde. */
export function passwortAbfrage(titel, text, knopf) {
  return new Promise(resolve => {
    const dlg = baueDialog(`
      <div class="dt">${titel}</div>
      <p>${text}</p>
      <form id="pwaForm">
        ${passwortFeld('pwaFeld', 'Passwort der Familie',
          'autocomplete="current-password" required')}
        <button type="submit" class="btn${knopf.gefahr ? ' gefahr' : ''}">${
          knopf.text}</button>
      </form>`);
    augenBinden(dlg);
    let fertig = false;
    dlg.querySelector('#pwaForm').addEventListener('submit', e => {
      e.preventDefault();
      fertig = true;
      resolve(dlg.querySelector('#pwaFeld').value);
      dlg.close();
    });
    dlg.addEventListener('close', () => { if (!fertig) resolve(null); });
  });
}
