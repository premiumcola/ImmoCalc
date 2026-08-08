/* N270 — der Einstieg auf der Objektseite: die Rubrik „Renovierungen".
   Sie zeigt Anzahl und Summe und führt auf `renovierung.html?o={slug}`, wo
   Zeitraum, Budget und die Rechnungen gepflegt werden.

   Bewusst nur Links (`<a>`), keine `data-…`-Knöpfe: die Rubrik hängt nicht am
   Stammdaten-Weg der Objektseite (eigene Endpunkte, eigene Seite) — wie schon
   die Grundschulden. Sie benutzt aber deren Klassen (.sekopf/.liste/.eintrag),
   damit sie sich nahtlos zwischen die übrigen Rubriken einfügt. */

import { esc, eurVoll } from '../immo.js';
import { RENOVIERUNG_RUBRIK } from '../objekt-felder.js?v=2';
import { RUBRIKFARBE } from '../objekt/state.js';
import { zeitraumText, einheitenText } from './daten.js';

/* Werkzeug-Symbol im flachen Stil der übrigen Rubriksymbole (assets/
   kostenicons.js). Es steht hier, weil die Zuordnungstabelle dort nach
   Kostenarten geht — „Renovierung" ist eine Rubrik, keine Kostenart. */
const WERKZEUG = `<svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true"
  ><path stroke="currentColor" stroke-width="1.7" fill="none" stroke-linecap="round"
    stroke-linejoin="round" d="m14.5 6.5 3-3a4 4 0 0 1-5 5l-7 7a1.8 1.8 0 1 0 2.5
    2.5l7-7a4 4 0 0 0 5-5l-3 3-2.5-2.5Z"/></svg>`;

const seite = slug => `renovierung.html?o=${encodeURIComponent(slug)}`;

function zeileHtml(slug, r) {
  const meta = [zeitraumText(r.von, r.bis), einheitenText(r.einheiten)]
    .filter(Boolean).join(' · ');
  const chip = r.budget == null ? ''
    : r.ueberzogen
      ? `<span class="chip neg">${eurVoll(-r.rest)} über</span>`
      : `<span class="chip pos">${eurVoll(r.rest)} übrig</span>`;
  return `<a class="eintrag klick" style="text-decoration:none;color:inherit"
      href="${seite(slug)}&r=${r.id}">
      <span class="et">
        <span class="en">${esc(r.name)}</span>
        <span class="ed">${esc(meta)} · ${r.anzahl_posten}
          ${r.anzahl_posten === 1 ? 'Rechnung' : 'Rechnungen'}</span>
      </span>
      ${chip}
      <span class="ew">${eurVoll(r.summe)}</span>
    </a>`;
}

/** Der ganze Abschnitt für objekt.html. */
export function renovierungenHtml(slug, liste) {
  const eintraege = Array.isArray(liste) ? liste : [];
  const gesamt = eintraege.reduce((s, r) => s + (r.summe || 0), 0);
  const kopfLink = `<a class="seakt" style="text-decoration:none"
      href="${seite(slug)}">${eintraege.length ? 'Alle ansehen' : 'Anlegen'}</a>`;
  const zeilen = eintraege.length
    ? eintraege.map(r => zeileHtml(slug, r)).join('')
      + (eintraege.length > 1
        ? `<div class="eintrag" style="background:#F5F8F7">
             <span class="et"><span class="en">${eintraege.length} Renovierungen
               gesamt</span></span>
             <span class="ew">${eurVoll(gesamt)}</span></div>`
        : '')
    : `<div class="leerzeile">Noch keine Renovierung erfasst</div>`;

  return `<div class="sekopf">
      <span class="seikon" style="color:${RUBRIKFARBE.renovierungen}">${WERKZEUG}</span>
      <h2 class="sec">${esc(RENOVIERUNG_RUBRIK.titel)}</h2>
      ${kopfLink}
    </div>
    <div class="liste">${zeilen}</div>`;
}
