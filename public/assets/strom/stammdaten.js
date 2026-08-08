/* N139/N153 — Stammdaten der PV-Anlage.

   Die Anlage wurde einmal gekauft, nicht jedes Jahr neu: `data-stamm`-Felder
   liegen unter /pv/stammdaten, jahresunabhaengig. Der Vorlauf beziffert, was
   die Anlage vor der ersten Nebenkostenabrechnung eingebracht hat — nach
   denselben Quellen aufgeteilt wie die Jahre danach (N153).

   Umzug ohne Verhaltensaenderung: dieselben Formeln, dasselbe PUT, dieselbe
   Vorrang-Regel wie zuvor inline in strom.html. */
import { api, eur, melde } from '../immo.js';
import { S, inhalt } from './state.js';
import { datumDe, tag, feldZahl } from './helpers.js';
import { feldHtml, datumHtml } from './felder.js';
import { pvAnteileJson } from './eigentuemer.js';
import { rechnen } from './jahre.js';

/* Die Stammdaten-Felder — Reihenfolge und Beschriftungen wie in der Maske. */
export const F_STAMM = [
  ['anschaffung_eur', 'Anschaffung', '€', 1],
  ['kwp', 'Anlagenleistung', 'kWp', 0.01],
];

/* N153 — der Startbetrag wird nach denselben Quellen eingetragen wie die
   Jahre danach. Ohne Einheit am Label: die drei stehen nebeneinander, die
   Waehrung sagt die Summe daneben einmal. */
export const F_VORLAUF = [
  ['vorlauf_pv_strom_eur', 'PV-Strom', '', 1],
  ['vorlauf_einspeisung_eur', 'Einspeisung', '', 1],
  ['vorlauf_tanken_eur', 'E-Tanken', '', 1],
];

/* Kein modulinterner Zeitgeber; `S.stammZeit` liegt zentral, damit `laden()`
   ihn beim Objektwechsel abraeumen kann. */

/* N139 — die STAMMDATEN der Anlage: Zahlen, Datum und die Eigentuemer-Anteile.
   Ein leeres Datum wird nicht mitgeschickt (nicht mitgeschickt = unveraendert),
   damit ein Tippfehler im Zahlenfeld nicht nebenbei das Datum loescht. */
export function stammAusForm() {
  const werte = {};
  // N288 — gelesen ueber `feldZahl` (helpers.js), das die deutsche Regel aus
  // immo.js benutzt, statt sie hier ein zweites Mal zu schreiben.
  inhalt.querySelectorAll('input[data-stamm]').forEach(el => {
    werte[el.dataset.stamm] = feldZahl(el);
  });
  const d = inhalt.querySelector('[data-stammdatum]');
  if (d && d.value) werte.inbetriebnahme = d.value;
  // Nur wenn die Zuordnung wirklich geladen ist — sonst schriebe ein Tippen
  // im Zahlenfeld eine leere Zuordnung ueber die gepflegte.
  if (S.pvGeladen) werte.anteile = pvAnteileJson();
  return werte;
}

export function stammFuellen(s) {
  inhalt.querySelectorAll('input[data-stamm]').forEach(el => {
    const v = s[el.dataset.stamm];
    el.value = (v == null || v === 0) ? '' : v;
  });
  const d = inhalt.querySelector('[data-stammdatum]');
  if (d) d.value = s.inbetriebnahme || '';
}

/* --------------------------------------------------------------------------
   N153 — der Startbetrag der Amortisation.

   Die Jahre nach der ersten Abrechnung zeigen im Verlauf schon, woher der
   Ertrag kam. Beim Startbetrag stand bisher nur eine Gesamtzahl — der Anfang
   des Verlaufs war damit die einzige Stelle ohne Herkunft.
   -------------------------------------------------------------------------- */

/* „2023 und 2024" / „2023, 2024 und 2025" — hoechstens eine Handvoll, sonst
   wird aus dem Hinweis eine Aufzaehlung. */
function jahreText(von, bis) {
  if (bis - von > 6) return '';
  const jahre = [];
  for (let j = von; j <= bis; j++) jahre.push(j);
  if (!jahre.length) return '';
  return jahre.length === 1 ? String(jahre[0])
    : `${jahre.slice(0, -1).join(', ')} und ${jahre[jahre.length - 1]}`;
}

/* Welcher Zeitraum gemeint ist, steht nirgends im Code: `vorlauf_bis` ist der
   Beginn des ersten Abrechnungszeitraums, die Inbetriebnahme der Anfang. */
function vorlaufZeitraum() {
  const bis = tag(S.stammStand.vorlauf_bis);
  if (!bis) return 'Gemeint ist alles, was die Anlage eingebracht hat, bevor '
    + 'die erste Nebenkostenabrechnung begann.';
  const vortag = new Date(bis);
  vortag.setDate(bis.getDate() - 1);
  const feld = inhalt.querySelector('[data-stammdatum]');
  const start = tag((feld && feld.value) || S.stammStand.inbetriebnahme);
  const jahre = start && start <= vortag
    ? jahreText(start.getFullYear(), vortag.getFullYear()) : '';
  return 'Gemeint ist die Zeit vor dem ersten Abrechnungszeitraum: '
    + (start ? `von der Inbetriebnahme am ${datumDe(start)} ` : 'alles ')
    + `bis zum ${datumDe(vortag)}${jahre ? ` — also ${jahre}` : ''}.`;
}

/* „Es passiert nichts" darf es hier nicht geben: kam der Startbetrag nicht so
   an, wie er abgeschickt wurde, wird das gesagt — ein stumm verschluckter
   Fehler ist schlimmer als ein sichtbarer. */
function vorlaufPruefen(gesendet, antwort) {
  const summe = F_VORLAUF.reduce((s, [name]) => s + (gesendet[name] || 0), 0);
  if (!summe) return;
  if (antwort.vorlauf_summe == null
      || Math.abs(antwort.vorlauf_summe - summe) > 0.005) {
    melde('Der Startbetrag kam nicht an — bitte die Seite neu laden', 'neg');
  }
}

function vorlaufWerte() {
  return F_VORLAUF.map(([name]) => {
    return feldZahl(inhalt.querySelector(`input[data-stamm="${name}"]`));
  });
}

/* Die Vorrang-Regel — dieselbe wie im Backend (`_vorlauf`): steht in einem der
   drei Felder etwas, gilt IHRE Summe als Vorlauf. Sonst gilt weiterhin der
   frueher eingetragene Gesamtwert. So bleibt der bestehende Wert gueltig, bis
   die Aufteilung dasteht — und es entstehen keine zwei Wahrheiten. */
export function vorlaufZeigen() {
  const summeZiel = document.getElementById('vorlaufSumme');
  if (!summeZiel) return;
  const werte = vorlaufWerte();
  const aufgeteilt = werte.some(w => w !== 0);
  const gesamt = S.stammStand.vorlauf_ertrag_eur || 0;
  const gilt = aufgeteilt ? werte.reduce((s, w) => s + w, 0) : gesamt;
  summeZiel.textContent = gilt ? eur(gilt) : '—';
  document.getElementById('vorlaufZeit').textContent = vorlaufZeitraum();
  document.getElementById('vorlaufFuss').textContent = aufgeteilt
    ? 'Diese Summe steht im Verlauf als eigener Balken VOR dem ersten '
      + 'Abrechnungsjahr — nach denselben Quellen aufgeteilt wie die Jahre '
      + 'danach, und voll in der Amortisation.'
    : (gesamt
      ? `Bisher steht hier nur der Gesamtwert ${eur(gesamt)}. Er gilt weiter, `
        + 'solange die Aufteilung leer ist — im Verlauf dann als ein Balken '
        + 'ohne Herkunft.'
      : 'Leer lassen, wenn die Anlage vor der ersten Abrechnung noch nichts '
        + 'eingebracht hat.');
}

/* N139 — nach jeder Eingabe: kurz warten, dann speichern und neu rechnen.
   Wechselt der Nutzer waehrend der 550 ms das Objekt, wird der eingefrorene
   Stand beim Feuern gegen die aktuelle Auswahl gepruet — und lieber nichts
   geschrieben. */
export function stammAngestossen() {
  vorlaufZeigen();              // die Summe steht sofort da, nicht erst nach
                                // dem Speichern
  const werte = stammAusForm();
  const stempel = JSON.stringify(werte);
  if (stempel === S.letzteStamm) return;
  const slug = S.objektSlug;
  clearTimeout(S.stammZeit);
  S.stammZeit = setTimeout(async () => {
    S.stammZeit = null;
    if (slug !== S.objektSlug) return;
    S.letzteStamm = stempel;
    try {
      const antwort = await api(
        `/objekte/${encodeURIComponent(slug)}/pv/stammdaten`,
        { method: 'PUT', body: werte });
      if (slug !== S.objektSlug) return;
      S.stammStand = antwort;         // Server ist die Wahrheit, nicht die Maske
      vorlaufPruefen(werte, antwort);
      // Anschaffung, Anteile UND der Vorlauf gehen mit ein: `rechnen` holt
      // den Verlauf neu, damit Grafik und Tabelle oben sofort mitgehen.
      await rechnen();
    } catch (fehler) {
      melde(String(fehler.message || fehler), 'neg');
    }
  }, 550);
}
