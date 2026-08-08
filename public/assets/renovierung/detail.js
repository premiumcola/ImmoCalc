/* N270 — eine einzelne Renovierung: Budgetstand, Gewerk-Verteilung als Donut,
   Zeitstrahl der Rechnungen und die Rechnungsliste.

   Die Diagramme kommen fertig aus `assets/charts.js` — hier wird nur
   eingesetzt, was die API liefert. */

import { esc, eur, eurVoll } from '../immo.js';
import { donut, zeitstrahl, farbe } from '../charts.js';
import { tag, zeitraumText, einheitenText } from './daten.js';

/* N279 — der gescannte Beleg gehoert sichtbar an seine Rechnung. Ohne ihn
   liegt die Datei zwar in der Cloud, ist von hier aus aber nicht auffindbar —
   und der Nutzer will (wie ueberall) Name UND Ablagepfad sehen. Flaches
   Blatt-Symbol im Stil der uebrigen Sprites, keine Icon-Bibliothek. */
const BELEG_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
  stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"
  aria-hidden="true" width="17" height="17">
  <path d="M14 3H7a1.5 1.5 0 0 0-1.5 1.5v15A1.5 1.5 0 0 0 7 21h10a1.5 1.5 0 0
           0 1.5-1.5V7.5z"/><path d="M14 3v4.5h4.5"/>
  <path d="M9 12.5h6M9 16h4"/></svg>`;

/** Farbe je Gewerk — dieselbe Reihenfolge wie im Donut, damit Ring, Legende
 *  und die Punkte in der Rechnungsliste dieselbe Sprache sprechen. */
export function gewerkFarben(gewerke) {
  const karte = new Map();
  (gewerke || []).forEach((g, i) => karte.set(g.gewerk, farbe(i)));
  return karte;
}

/* ---- Kopf: Budgetstand + Donut ------------------------------------------ */

function budgetHtml(stand) {
  if (stand.budget == null) {
    return `<div class="bstand ohne">
        <span class="bl">Ohne Budget</span>
        <p class="bhinweis">Ein Budget zeigt dir laufend, was noch übrig ist.</p>
        <button class="btn leise" type="button" data-bearbeiten>Budget festlegen</button>
      </div>`;
  }
  const pct = Math.max(2, Math.min(100, Math.round(stand.anteil_pct || 0)));
  const ueber = stand.ueberzogen;
  // Solange nichts ausgegeben ist, sind Rest und Budget dieselbe Zahl — dann
  // steht sie einmal da und heisst, was sie ist: das Budget.
  const leer = !stand.ausgegeben;
  return `<div class="bstand">
      <span class="bl">${leer ? 'Budget' : ueber ? 'Überzogen' : 'Restbudget'}</span>
      <b class="bv ${leer ? '' : ueber ? 'neg' : 'pos'}">${
        eurVoll(Math.abs(leer ? stand.budget : stand.rest))}</b>
      <div class="bbar${ueber ? ' ueber' : ''}"><span style="width:${pct}%"></span></div>
      <div class="bfuss">${leer ? 'noch nichts ausgegeben'
        : `${Math.round(stand.anteil_pct || 0)} % von ${eurVoll(stand.budget)} Budget`}</div>
    </div>`;
}

/* N284 — die Gewerk-Legende ist entfallen. Anteil und Summe stehen jetzt
   rechts an ihrer Spur im Zeitstrahl (`charts.zeitstrahl`), wo sie zu genau
   der Zeile gehoeren, die sie meinen. Als eigener Block ueber dem Zeitstrahl
   sagten sie dasselbe wie der Ring daneben — dieselbe Angabe zweimal. */

const leerfeldHtml = `<div class="leerfeld">
    <div class="big">Noch keine Rechnung</div>
    <p>Trag die erste Rechnung ein — Verteilung nach Gewerk und Zeitstrahl
       bauen sich daraus von selbst auf.</p>
    <button class="btn" type="button" data-posten-neu>Rechnung hinzufügen</button>
  </div>`;

function kopfHtml(d) {
  const anzahl = d.posten.length;
  const meta = [zeitraumText(d.von, d.bis), einheitenText(d.einheiten)]
    .filter(Boolean).join(' · ');

  // Ohne Rechnungen gibt es nichts zu verteilen — dann steht hier der Weg zur
  // ersten Rechnung. Ein gesetztes Budget wird trotzdem gezeigt: es ist der
  // Rahmen, in dem gearbeitet wird, auch bevor die erste Rechnung da ist.
  if (!anzahl) {
    return `<div class="karte">
        ${metaZeileHtml(meta, d)}
        ${d.budget_stand.budget == null ? '' : budgetHtml(d.budget_stand)}
        ${leerfeldHtml}
      </div>`;
  }

  const ring = donut(d.gewerke.map(g => ({ name: g.gewerk, wert: g.summe })), {
    groesse: 200, dicke: 30,
    mitte: eurVoll(d.summe),
    mitteSub: `${anzahl} ${anzahl === 1 ? 'Rechnung' : 'Rechnungen'}`,
  });

  // Die Gewerkliste steht UNTER dem Zweispalter, nicht in seiner rechten
  // Spalte: sie ist die laengste Zeile der Karte und liess auf dem Desktop
  // sonst neben dem Budgetblock eine halbe Bildschirmhoehe leer stehen.
  return `<div class="karte">
      ${metaZeileHtml(meta, d)}
      <div class="kopfgrid">
        ${budgetHtml(d.budget_stand)}
        <div class="ringfeld">${ring}</div>
      </div>
    </div>`;
}

function metaZeileHtml(meta, d) {
  return `<div class="hh">
      <div class="metatxt">
        <span class="rmeta">${d.abgeschlossen
          ? '<span class="chip pos">fertig</span>'
          : '<span class="chip teal">läuft</span>'} ${esc(meta)}</span>
        ${d.notiz ? `<span class="rnotiz">${esc(d.notiz)}</span>` : ''}
      </div>
      <button class="seakt" type="button" data-bearbeiten>Bearbeiten</button>
    </div>`;
}

/* ---- Rechnungen --------------------------------------------------------- */

function postenZeileHtml(p, farben) {
  const punkt = farben.get((p.gewerk || '').trim() || 'Sonstiges') || 'var(--soft)';
  const zweite = [tag(p.datum) || 'ohne Datum', p.gewerk, p.notiz]
    .filter(Boolean).join(' · ');
  return `<div class="prow">
      <button class="pklick" type="button" data-posten="${p.id}"
              aria-label="Rechnung bearbeiten">
        <span class="pdot" style="background:${punkt}"></span>
        <span class="pt">
          <span class="pn">${esc(p.firma || 'Ohne Firma')}</span>
          <span class="pd">${esc(zweite)}</span>
        </span>
        <span class="pw${p.betrag ? '' : ' ohne'}">${
          p.betrag ? eur(p.betrag) : 'ohne Kosten'}</span>
      </button>
      ${p.quelle_dokument_id ? `<button class="pbeleg" type="button"
              data-posten-beleg="${p.quelle_dokument_id}"
              aria-label="Beleg ansehen" title="Beleg ansehen">${BELEG_ICON}</button>` : ''}
      <button class="del" type="button" data-posten-weg="${p.id}"
              aria-label="Rechnung löschen">×</button>
    </div>`;
}

function postenHtml(d, farben) {
  if (!d.posten.length) return '';
  return `<div class="hh">
      <h2 class="sec">Rechnungen</h2>
      <button class="plus" type="button" data-posten-neu
              aria-label="Rechnung hinzufügen" title="Rechnung hinzufügen">＋</button>
    </div>
    <div class="ablagezeile" data-ablage-hinweis></div>
    <div class="pliste">${d.posten.map(p => postenZeileHtml(p, farben)).join('')}</div>`;
}

/* ---- Zeitstrahl --------------------------------------------------------- */

/** Zeichnet den Zeitstrahl in der Breite, die der Behaelter gerade hat. Wird
 *  bei jeder Groessenaenderung erneut gerufen (siehe renovierung.html), damit
 *  Punktabstaende und Achsenmarken auf jedem Geraet passen. */
export function zeitstrahlZeichnen(feld, d) {
  if (!feld) return;
  const breite = Math.max(260, Math.round(feld.clientWidth || 320));
  // N279 — je Gewerk eine eigene Spur, in der Farbe der Legende. Die Hoehe
  // ergibt sich aus der Zahl der Spuren und wird im Diagramm gerechnet; eine
  // vorgegebene Hoehe waere hier falsch.
  const farben = gewerkFarben(d.gewerke);
  // N284 — Anteil und Summe wandern an die Spur. Sie standen als eigener
  // Legendenblock über dem Zeitstrahl und sagten dasselbe wie der Ring
  // daneben; an der Zeile gehören sie zu dem, was sie meinen.
  const spuren = d.gewerke
    .filter(g => g.summe > 0)
    .map(g => ({ name: g.gewerk, farbe: farben.get(g.gewerk),
                 anteil: g.anteil_pct, summe: g.summe }));
  feld.innerHTML = zeitstrahl(
    d.posten.map(p => ({ datum: p.datum, wert: p.betrag,
                         // Ohne Gewerk laeuft der Posten in der „Sonstiges"-
                         // Spur mit — dieselbe Regel wie in der Verteilung.
                         name: (p.gewerk || '').trim() || 'Sonstiges',
                         firma: p.firma })),
    { breite, von: d.von || '', bis: d.bis || '', spuren });
}

/* ---- Ganze Ansicht ------------------------------------------------------ */

export function detailHtml(d) {
  const farben = gewerkFarben(d.gewerke);
  const mitZeitstrahl = d.posten.some(p => p.datum && p.betrag > 0);
  return `${kopfHtml(d)}
    ${mitZeitstrahl ? `<div class="karte">
      <h3>Rechnungen im Verlauf</h3>
      <div id="zeitstrahl"></div>
    </div>` : ''}
    ${postenHtml(d, farben)}
    <div class="gefahr-block">
      <button class="btn gefahr" type="button" data-reno-weg>Renovierung löschen</button>
    </div>`;
}
