/* N216 — Das Pruefblatt: Gegenueberstellung „erkannt → wird eingetragen"
   (CXXV) und die Ziel-Zeile mit dem Dateinamen, den die Ablage vergeben wird.

   Ruft die Feldstand-Anzeige (gruene Kennzeichnung) an, laesst die
   Zeitraum-Warnung nachziehen und triggert bei jedem Neuzeichnen den
   Kostenposition-Plan, wenn sein Fach offen ist. */

import { S, els } from './state.js';
import { esc } from '../immo.js';
import { befund, belegDatumText, betragText, endungVon, dok } from './helpers.js';
import { stand, feldstandZeigen } from './liste.js';
import { zeitraumHinweisZeigen } from './zeitraum.js';
import { posPlanZeichnen } from './position.js';

/* Gegenueberstellung: was steht am Beleg, was wird daraus (CXXV). */
export function planZeichnen() {
  const d = S.gewaehlt !== null ? dok(S.gewaehlt) : null;
  if (!d) return;
  const b = befund(d);
  // Ohne Eingabefelder (vermisster Beleg) bleibt es beim Erkannten — dann
  // stuende sonst hinter jeder Zeile ein Pfeil auf „nichts".
  const eingestellt = stand();
  const s = eingestellt || { objekt: d.objekt, kategorie: b.kategorie,
                             kostenart: b.kostenart, belegdatum: b.belegdatum,
                             jahr: b.jahr, monat: b.monat, betrag: b.betrag,
                             beschreibung: b.sache };
  feldstandZeigen(eingestellt);
  const objektName = slug => (S.daten.objekte.find(o => o.slug === slug) || {}).name;
  // Ohne Belegdatum bleibt der Monat, den der Dateiname traegt.
  const neuesDatum = { belegdatum: s.belegdatum, jahr: s.jahr,
                       monat: s.monat === undefined ? b.monat : s.monat };
  const zeilen = [
    ['Sache', b.sache, s.beschreibung],
    ['Datum', belegDatumText(b), belegDatumText(neuesDatum)],
    ['Betrag', betragText(b.betrag), betragText(s.betrag)],
    ['Immobilie', d.objekt_name || '', objektName(s.objekt) || ''],
    ['Art', b.kategorie, s.kategorie],
    ['Position', b.kostenart, s.kostenart],
  ];
  els.bPlan.innerHTML = zeilen.map(([label, alt, neu]) => {
    const gleich = (alt || '') === (neu || '');
    const wert = gleich
      ? (alt ? `<span class="pw da">${esc(alt)}</span>`
             : '<span class="pw leer">offen</span>')
      : `<span class="pw alt">${esc(alt || 'nichts')}</span>`
        + '<span class="pfeil">→</span>'
        + `<span class="pw${neu ? ' da' : ''}">${esc(neu || 'nichts')}</span>`;
    return `<div class="pzeile"><span class="pl">${label}</span>${wert}</div>`;
  }).join('');
  zeitraumHinweisZeigen();

  if (d.vermisst) {
    els.bZiel.className = 'bziel gesperrt';
    els.bZiel.textContent = 'Diese Datei liegt nicht mehr in der Nextcloud. '
      + 'Neu einscannen oder den Eintrag entfernen.';
    els.bOk.disabled = true;
    els.bOk.textContent = 'Nicht möglich';
    return;
  }
  els.bZiel.className = 'bziel';
  const zeitraum = S.zeitraumFeld && S.zeitraumFeld.wert()
    ? (S.zeitraumListe.find(z => String(z.id) === S.zeitraumFeld.wert()) || {}).label
    : null;
  els.bZiel.textContent = 'Wird abgelegt als ' + zielName(d, s)
    + (zeitraum ? ` · Abrechnung ${zeitraum}` : ' · ohne Abrechnung');
  els.bOk.disabled = false;
  els.bOk.textContent = d.status === 'neu' ? 'Zuordnen und einsortieren'
                                           : 'Übernehmen';
  // Der Kostenpositions-Schritt rechnet mit dem gespeicherten Stand — beim
  // Tippen muss deshalb mitkommen, ob das Formular davon abweicht.
  if (!els.bPosFach.hidden) posPlanZeichnen(d);
}

/** Der Name, den die Ablage vergeben wird: Datum_Sache_Betrag.
    Das letzte Wort hat die API — hier steht die Vorschau dazu. */
export function zielName(d, s) {
  const datum = s.jahr
    ? (s.monat ? `${s.jahr}-${String(s.monat).padStart(2, '0')}` : String(s.jahr))
    : 'ohne-Jahr';
  // Was der Ordner schon sagt, steht nicht noch einmal im Namen (CXXII).
  const ohneArt = (s.beschreibung || '')
    .replace(new RegExp('\\b' + (s.kategorie || '\\u0000'), 'gi'), ' ');
  const sache = ohneArt.replace(/[^\wäöüÄÖÜß.\- ]+/g, '-').trim()
    .replace(/\s+/g, '-').replace(/[-_.]{2,}/g, '-').replace(/^[-_.]+|[-_.]+$/g, '');
  const betrag = s.betrag
    ? s.betrag.toFixed(2).replace('.', ',') + '€' : '';
  return [datum, sache || 'Beleg', betrag].filter(Boolean).join('_')
    + endungVon(d.dateiname);
}
