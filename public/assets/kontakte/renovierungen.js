/* N309f — die zweite Sicht des Kontaktbuchs: „Wer hat bei dieser Renovierung
   in welchem Gewerk gearbeitet?" Die Antwort kommt fertig sortiert aus
   `/api/kontakte/gewerke/{id}`; hier wird sie nur gezeichnet.

   Alle Balken teilen sich EINEN Maßstab (das größte Gewerk = volle Breite).
   Dadurch sind die Firmenbalken die sichtbaren Teile ihres Gewerkbalkens und
   lassen sich zugleich über Karten hinweg vergleichen. */

import { esc, eur } from '../immo.js';
import { gewerkIcon } from '../gewerkicons.js';

const datum = iso => {
  if (!iso) return '';
  const [j, m, t] = String(iso).split('-');
  return t ? `${t}.${m}.${j}` : String(iso);
};

const zeitraum = r => {
  const von = datum(r.von);
  const bis = datum(r.bis);
  if (von && bis) return `${von} – ${bis}`;
  return von || bis || '';
};

const anzahlText = (n, eins, viele) => `${n} ${n === 1 ? eins : viele}`;

/** Breite eines Balkens in Prozent — nie unter 2 %, damit „fast nichts" noch
 *  zu sehen ist; genau 0 € bleibt aber leer. */
const breite = (wert, groesstes) => {
  if (!wert || !groesstes) return 0;
  return Math.max(2, Math.round((wert / groesstes) * 100));
};

function firmaHtml(f, groesstes) {
  const b = breite(f.summe, groesstes);
  return `<li><button class="firma" type="button" data-kontakt="${f.kontakt_id}">
      <span class="fname">${esc(f.firma)}</span>
      <span class="fbalken">${b ? `<span style="width:${b}%"></span>` : ''}</span>
      <span class="fwert">${f.summe
        ? esc(eur(f.summe))
        : '<i class="ohne">ohne Betrag</i>'}
        <i>${esc(anzahlText(f.anzahl, 'Rechnung', 'Rechnungen'))}</i></span>
    </button></li>`;
}

function gewerkHtml(g, groesstes) {
  const b = breite(g.summe, groesstes);
  return `<section class="gwkarte">
      <div class="gwkopf">
        <span class="gwikon">${gewerkIcon(g.gewerk, 'gi', 22)}</span>
        <span class="gwname">${esc(g.gewerk || 'Ohne Gewerk')}</span>
        <span class="gwsumme">${esc(eur(g.summe))}</span>
      </div>
      <div class="gwbalken">${b ? `<span style="width:${b}%"></span>` : ''}</div>
      <ul class="fliste">${g.firmen.map(f => firmaHtml(f, groesstes)).join('')}</ul>
    </section>`;
}

/**
 * Kopf und Gewerke einer Renovierung.
 * @param {object} reno   Eintrag aus /objekte/{slug}/renovierungen
 * @param {object} sicht  Antwort von /kontakte/gewerke/{id}
 * @param {string} slug   Immobilie — für den Weg zur Renovierungsseite
 */
export function renoSichtHtml(reno, sicht, slug) {
  const gewerke = sicht?.gewerke || [];
  const groesstes = Math.max(0, ...gewerke.map(g => g.summe || 0));
  const firmen = new Set();
  for (const g of gewerke) for (const f of g.firmen) firmen.add(f.kontakt_id);

  // Die drei Zahlen als eigene Spannen: bricht die Zeile um, wandert der
  // Trenner nicht an den Anfang der nächsten (CSS setzt ihn hinter das Wort).
  const kopf = `<div class="rkopf">
      <div class="rzahl">
        <span class="rv">${esc(eur(reno.summe))}</span>
        <span class="rl">
          <span>${esc(anzahlText(firmen.size, 'Firma', 'Firmen'))}</span>
          <span>${esc(anzahlText(gewerke.length, 'Gewerk', 'Gewerke'))}</span>
          <span>${esc(anzahlText(reno.anzahl_posten || 0, 'Rechnung',
            'Rechnungen'))}</span>
        </span>
      </div>
      <a class="rlink" href="renovierung.html?o=${encodeURIComponent(slug)}&r=${
        reno.id}">${esc(zeitraum(reno) || 'Zur Renovierung')} ›</a>
    </div>`;

  if (!gewerke.length) {
    return `${kopf}<div class="leerfeld">
        <div class="big">Noch keine Rechnung erfasst</div>
        <p>Sobald Rechnungen zu „${esc(reno.name)}" erfasst sind, steht hier,
           welche Firma in welchem Gewerk gearbeitet hat.</p>
        <a class="btn" href="renovierung.html?o=${encodeURIComponent(slug)}&r=${
          reno.id}">Zur Renovierung</a>
      </div>`;
  }

  return `${kopf}<div class="gwraster">${
    gewerke.map(g => gewerkHtml(g, groesstes)).join('')}</div>`;
}
