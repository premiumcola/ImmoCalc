/* N216 — Modul-Zustand fuer die Einstellungen-Seite.

   Die Fach-Module (verknuepfungen, nextcloud, ki, mail, vorlage, backup)
   teilen sich hier ihre gemeinsamen Helfer: die Meldungen an Ort und Stelle
   (`feldmeldung`/`meldungWeg`), den knapp befristeten Statusabruf fuer die
   Dienst-Kacheln (`vHole`, `vHoleGeteilt`, `vGeteiltReset`), die kleinen
   Formatierer (`vKurz`, `vModell`, `ortszeit`) und — seit N479 — das
   Passwortfeld mit Auge (`passwortFeld`, `augenBinden`, `passwortAbfrage`).

   Die Zeichen der Kacheln stehen seit N479 in `symbole.js`. */
import { baueDialog } from '../immo.js';

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

/* ---- Passwortfeld mit Auge (N479) ------------------------------------
   Nutzer: „leer = beibehalten ist sehr verwirrend, das ist nicht der
   Standard." Deshalb gibt es genau ein Muster fuer alle Passwortfelder der
   App: Punkte plus ein Auge, das sie sichtbar macht. Wer sehen kann, was
   im Feld steht, braucht keine Erklaerung daneben. */

const A_STRICH = 'stroke="currentColor" stroke-width="1.7" fill="none" '
  + 'stroke-linecap="round" stroke-linejoin="round"';

/* Zwei symmetrische Quadratbögen als Lidbogen, dazu die Pupille. Symmetrisch
   gesetzt, damit das Auge bei 19 px nicht schief wirkt. */
const AUGE = `<path ${A_STRICH} d="M2.4 12Q12 3.6 21.6 12 12 20.4 2.4 12Z"/>
  <circle ${A_STRICH} cx="12" cy="12" r="2.7"/>`;

const AUGE_AUF = AUGE;

/* Zugedeckt: dasselbe Auge mit einem Strich darüber. Bewusst dieselbe Form —
   wer den Knopf zweimal drückt, soll denselben Gegenstand sehen und nicht
   zwei verschiedene Bilder vergleichen müssen. */
const AUGE_ZU = `${AUGE}<path ${A_STRICH} d="M4.3 4.3 19.7 19.7"/>`;

/* Baut ein Passwortfeld samt Beschriftung und Auge.
   `label` und `zusatz` sind immer eigene Literale aus dem Code (nie Eingaben
   des Nutzers) — deshalb wandern sie unmaskiert ins Markup. */
export function passwortFeld(id, label, zusatz = '') {
  return `<div class="field">
      <label for="${id}">${label}</label>
      <div class="pwfeld">
        <input class="inp" type="password" id="${id}" ${zusatz}>
        <button type="button" class="pwauge" data-auge aria-pressed="false"
                aria-label="Passwort anzeigen" title="Passwort anzeigen">
          <svg class="auf" viewBox="0 0 24 24" aria-hidden="true">${AUGE_AUF}</svg>
          <svg class="zu" viewBox="0 0 24 24" aria-hidden="true">${AUGE_ZU}</svg>
        </button>
      </div>
    </div>`;
}

/* Verdrahtet alle Augen unterhalb von `wurzel`. Mehrfach aufrufbar: einmal
   verdrahtete Knoepfe werden uebersprungen. */
export function augenBinden(wurzel = document) {
  wurzel.querySelectorAll('[data-auge]').forEach(knopf => {
    if (knopf.dataset.auge === 'bereit') return;
    knopf.dataset.auge = 'bereit';
    // Der Knopf darf den Fokus NICHT an sich ziehen: sonst springt beim
    // Aufdecken die Schreibmarke aus dem Feld und die Eingabe reisst ab.
    knopf.addEventListener('mousedown', e => e.preventDefault());
    knopf.addEventListener('click', () => {
      const feld = knopf.parentElement.querySelector('input');
      if (!feld) return;
      const zeigen = feld.type === 'password';
      feld.type = zeigen ? 'text' : 'password';
      knopf.setAttribute('aria-pressed', String(zeigen));
      const text = zeigen ? 'Passwort verbergen' : 'Passwort anzeigen';
      knopf.setAttribute('aria-label', text);
      knopf.title = text;
    });
  });
}

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
