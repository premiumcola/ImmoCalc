/* N270 — Liste aller Renovierungen eines Objekts. Eine Karte je Renovierung:
   Name, Zeitraum, betroffene Einheiten, Summe und — falls ein Budget gesetzt
   ist — der Rest samt Balken. Ohne Budget bleibt der Balken weg statt leer
   dazustehen. */

import { esc, eurVoll } from '../immo.js';
import { zeitraumText, einheitenText } from './daten.js';

/** Balkenbreite in Prozent — ueber 100 % wird gekappt, damit der Balken im
 *  Rahmen bleibt; dass ueberzogen wurde, sagt die Farbe und der Text. */
const anteilBreite = r => {
  if (!r.budget) return 0;
  return Math.max(2, Math.min(100, Math.round(r.summe / r.budget * 100)));
};

function budgetZeileHtml(r) {
  if (r.budget == null) return '';
  const pct = anteilBreite(r);
  return `<div class="bbar${r.ueberzogen ? ' ueber' : ''}">
      <span style="width:${pct}%"></span>
    </div>
    <div class="bfuss">
      <span>${r.budget ? Math.round(r.summe / r.budget * 100) : 0} % von
        ${eurVoll(r.budget)}</span>
      <b class="${r.ueberzogen ? 'neg' : 'pos'}">${
        r.ueberzogen ? `${eurVoll(-r.rest)} überzogen` : `${eurVoll(r.rest)} übrig`}</b>
    </div>`;
}

function karteHtml(r) {
  const meta = [zeitraumText(r.von, r.bis), einheitenText(r.einheiten)]
    .filter(Boolean).join(' · ');
  const zahl = `${r.anzahl_posten} ${r.anzahl_posten === 1 ? 'Rechnung' : 'Rechnungen'}`;
  return `<button class="rkarte" type="button" data-reno="${r.id}">
    <div class="rkopf">
      <span class="rname">${esc(r.name)}</span>
      ${r.abgeschlossen
        ? '<span class="chip pos">fertig</span>'
        : '<span class="chip teal">läuft</span>'}
    </div>
    <div class="rmeta">${esc(meta)}</div>
    <div class="rsumme">
      <b>${eurVoll(r.summe)}</b>
      <span>${zahl}</span>
    </div>
    ${budgetZeileHtml(r)}
  </button>`;
}

/** Die ganze Listenansicht. `anlegenKnopf` ist das „＋" im Abschnittskopf. */
export function listeHtml(renovierungen) {
  if (!renovierungen.length) {
    return `<div class="empty">
        <div class="big">Noch keine Renovierung</div>
        <p>Zeitraum, Budget und die Rechnungen dazu — Verteilung nach Gewerk
           und Restbudget rechnen sich daraus von selbst.</p>
        <button class="btn" type="button" data-neu style="margin-top:16px">
          Renovierung anlegen</button>
      </div>`;
  }
  const gesamt = renovierungen.reduce((s, r) => s + (r.summe || 0), 0);
  return `<div class="hh">
      <h2 class="sec">${renovierungen.length}
        ${renovierungen.length === 1 ? 'Renovierung' : 'Renovierungen'}
        <span class="secsum">${eurVoll(gesamt)}</span></h2>
      <button class="plus" type="button" data-neu
              aria-label="Renovierung anlegen" title="Renovierung anlegen">＋</button>
    </div>
    <div class="rkarten">${renovierungen.map(karteHtml).join('')}</div>`;
}
