/* zeitraum/ergebnis.js — der Ergebnis-Tab (N407): Belegungsübersicht
   (Einheiten, Zeitstrahl, Tabelle), Kosten×Einheiten-Matrix, Warnkarten.
   Ausgelagert aus checkliste.js, das mit den Kostenzeilen schon groß genug
   ist. Die Tabellen nutzen dieselbe Sprache wie die Wasser-Detailtabelle
   (.wd-tabelle/.wd-tab/.wd-rowh/.wd-summe, siehe wasser.js) statt eigener
   CSS-Klassen — eine Tabellenform für die ganze Seite. */

import { api, eur, esc } from '../immo.js';
import * as state from './state.js';
import { einmal } from './holen.js';
import { _isoKurz } from './helpers.js';

const { zid } = state;

const _zahl1 = n => (n ?? 0).toLocaleString('de-DE', { maximumFractionDigits: 1 });

// N33/N19 dieselbe Idee wie die Mietverhältnis-Zeitstrahlen der Objekt-Seite
// (objekt/helpers.js::mietFarbe), aber eine eigene Palette: Rot/Grün sind in
// dieser App fest Nachzahlung/Guthaben (--neg/--pos) — als beliebige Balken-
// farbe hier gelesen sie fälschlich als Warnung. Nur neutrale Akzente.
const FARBEN = ['#0F6E5C', '#916212', '#5B7CA6', '#8A5FA6', '#2E7DA6', '#4A8577'];

// N410 — Heatmap der Kosten×Einheiten-Matrix: rot (größter Posten) über
// orange/gelb bis neutral (kleinster) — dieselbe Idee wie die PDF-Heatmap
// (abrechnung_pdf.py), nur eigenständig für CSS-Farben statt PDF-Ops.
const HEAT_STOPS = [
  { t: 0.00, c: [244, 246, 245] },
  { t: 0.33, c: [242, 214, 130] },
  { t: 0.66, c: [224, 150, 96] },
  { t: 1.00, c: [196, 92, 78] },
];
function heatFarbe(ratio) {
  const r = Math.max(0, Math.min(1, ratio || 0));
  for (let i = 1; i < HEAT_STOPS.length; i++) {
    if (r <= HEAT_STOPS[i].t) {
      const a = HEAT_STOPS[i - 1], b = HEAT_STOPS[i];
      const t = (r - a.t) / (b.t - a.t || 1);
      const c = a.c.map((v, k) => Math.round(v + (b.c[k] - v) * t));
      return `rgb(${c[0]} ${c[1]} ${c[2]})`;
    }
  }
  return `rgb(${HEAT_STOPS.at(-1).c.join(' ')})`;
}

// N410 — Sortier-Zustand der Matrix, session-lokal wie `state.sortierung`.
// Erster Klick auf eine Spalte sortiert absteigend (größter Posten zuerst —
// „um sich einen Blick zu verschaffen"), erneuter Klick dreht um.
let mxSort = null;   // { spalte: Partei-Name | '__summe__', richtung: 'ab' | 'auf' }

export function matrixSortSetzen(spalte) {
  mxSort = mxSort?.spalte === spalte
    ? { spalte, richtung: mxSort.richtung === 'ab' ? 'auf' : 'ab' }
    : { spalte, richtung: 'ab' };
}

/* Wer eine Abrechnung bekommt — Mailadresse, oder bleibt sie beim Eigentümer.
   Kompakt als Tooltip-Text am PDF-Knopf der Matrix, statt einer eigenen Zeile
   je Partei wie früher (roter Faden #3 — jede Information genau einmal). */
function empfaengerKurz(p) {
  if (!p) return '';
  if (p.leerstand) return 'Bleibt beim Eigentümer — kein Versand.';
  if (p.adressen?.length) return `Geht an ${p.adressen.join(', ')}`;
  return 'Keine Mailadresse hinterlegt — ausdrucken und mit der Post schicken.';
}

/**
 * N314(g) — eine Vorauszahlung, deren Partei zu keinem Bezug dieses Zeitraums
 * passt (Tippfehler, ausgezogener Mieter unter altem Namen). Sie steckt in
 * `gesamt.abschlaege`, taucht aber in keiner Partei-Zeile auf — ohne diesen
 * Hinweis unsichtbar. Der Betrag ist nicht Teil der API-Antwort und wird
 * daher aus der Differenz Gesamt-Abschläge ./. Summe der bekannten
 * Vorauszahlungen abgeleitet (bei genau einem unbekannten Namen exakt sein
 * Betrag).
 */
function vorauszahlungOhnePartei(a) {
  const namen = a.vorauszahlungen_ohne_partei;
  if (!namen?.length) return '';
  const bekannt = Object.values(a.parteien || {})
    .reduce((s, w) => s + (w.vorauszahlungen || 0), 0);
  const betrag = (a.gesamt?.abschlaege || 0) - bekannt;
  const satz = namen.length === 1
    ? `Der Name passt zu keiner Partei dieses Zeitraums.`
    : `Diese Namen passen zu keiner Partei dieses Zeitraums.`;
  return `<div class="karte">
      <h3>Vorauszahlung ohne Partei</h3>
      <div class="weg-warn"><span class="ww-z">${eur(betrag)}</span>
        <span><b>${esc(namen.join(', '))}</b> — ${satz} Sie fließen in die
        Gesamtsumme ein, aber in keine Partei-Zeile. Name in den
        Mieterstammdaten prüfen und richtigstellen.</span>
      </div>
    </div>`;
}

/* N402 — das Gegenstück: ein von Hand gesetztes Gewicht auf einem Namen, den
 * es als Partei nicht gibt. Anders als bei der Vorauszahlung geht hier Geld
 * an einen Empfänger, den es nicht gibt — die echte Partei bekommt dafür
 * nichts. Der Betrag steht in der Partei-Zeile des Phantoms, deshalb ist er
 * hier direkt ablesbar und muss nicht abgeleitet werden.
 * N407 — Verweis auf die Belegungstabelle: dort stehen alle echten Parteien
 * dieses Zeitraums, ein Abgleich zeigt auf einen Blick, dass der Name dort
 * fehlt.
 */
function anteilOhnePartei(a) {
  const treffer = a.anteile_ohne_partei;
  if (!treffer?.length) return '';
  const zeilen = treffer.map(t => {
    const betrag = t.parteien.reduce(
      (s, n) => s + (a.parteien?.[n]?.kosten || 0), 0);
    return `<div class="weg-warn"><span class="ww-z">${eur(betrag)}</span>
        <span><b>${esc(t.kostenart)}</b> verteilt an <b>${
        esc(t.parteien.join(', '))}</b> — diesen Namen gibt es in der
        Belegung oben nicht. Der Betrag geht damit an niemanden, und die
        Partei, die ihn tragen müsste, bekommt ihn nicht. Die Verteilung
        dieser Position richtigstellen.</span></div>`;
  }).join('');
  return `<div class="karte"><h3>Anteil ohne Partei</h3>${zeilen}</div>`;
}

/* N407 — welche Partei/welcher Leerstand wann in welcher Einheit zu
   verrechnen war: Zeitstrahl je Einheit (dieselbe Sprache wie die
   Mietverhältnis-Timeline der Objekt-Seite) + eine Tabelle mit Monaten,
   Personen und m². Datenquelle: `/schluessel`, dieselben Bezüge, aus denen
   auch die Verteilungsgewichte selbst kommen — hier nur vollständig statt
   auf partei/einheit/flaeche/personen zusammengekürzt. */
function belegungHtml() {
  const bez = state.schluessel?.parteien || [];
  const start = state.daten?.start, ende = state.daten?.ende;
  if (!bez.length || !start || !ende) return '';
  const t0 = Date.parse(start), t1 = Date.parse(ende);
  const spanne = Math.max(1, t1 - t0);
  const pct = iso => Math.min(100, Math.max(0, (Date.parse(iso) - t0) / spanne * 100));

  const jeEinheit = new Map();
  for (const b of bez) {
    const key = b.einheit || 'Ohne Einheit';
    if (!jeEinheit.has(key)) jeEinheit.set(key, []);
    jeEinheit.get(key).push(b);
  }

  let farbI = 0;
  const bloecke = [...jeEinheit.entries()].map(([einheit, liste]) => {
    liste.sort((x, y) => (x.ab || '').localeCompare(y.ab || ''));
    const segs = liste.map(b => {
      if (!b.ab || !b.bis) return '';
      const l = pct(b.ab), r = pct(b.bis);
      const breite = Math.max(1.5, r - l);
      const farbe = b.leerstand ? '' : FARBEN[farbI++ % FARBEN.length];
      const titel = `${b.leerstand ? 'Leerstand' : b.partei}: ${
        _isoKurz(b.ab)} – ${_isoKurz(b.bis)} · ${_zahl1(b.monate)} Monate`;
      return `<span class="tl-seg${b.leerstand ? ' leer' : ''}" title="${esc(titel)}"
          style="left:${l}%;width:${breite}%;${b.leerstand ? '' : `background:${farbe}`}"></span>`;
    }).join('');
    const flaeche = liste.find(b => b.flaeche != null)?.flaeche;
    return `<div class="beleg-einheit">
        <div class="be-kopf"><span class="be-name">${esc(einheit)}</span>${
          flaeche != null ? `<span class="be-flaeche">${_zahl1(flaeche)} m²</span>` : ''}</div>
        <div class="miet-timeline mini"><div class="tl-track">${segs}</div></div>
      </div>`;
  }).join('');

  const zeilen = bez.slice()
    .sort((x, y) => (x.einheit || '').localeCompare(y.einheit || '')
      || (x.ab || '').localeCompare(y.ab || ''))
    .map(b => `<tr${b.leerstand ? ' class="wd-garten"' : ''}>
        <td class="wd-rowh">${esc(b.einheit || '–')}</td>
        <td>${b.leerstand ? '<span style="color:var(--soft)">Leerstand</span>'
          : esc(b.partei)}</td>
        <td style="white-space:nowrap">${_isoKurz(b.ab)} – ${_isoKurz(b.bis)}</td>
        <td>${_zahl1(b.monate)}</td>
        <td>${b.personen ?? '–'}</td>
        <td>${b.flaeche != null ? `${_zahl1(b.flaeche)} m²` : '–'}</td>
      </tr>`).join('');

  return `<div class="karte">
      <h3>Belegung im Zeitraum</h3>
      ${bloecke}
      <div class="wd-tabelle"><table class="wd-tab">
        <thead><tr><th class="wd-rowh">Einheit</th><th>Partei</th><th>Zeitraum</th>
          <th>Monate</th><th>Personen</th><th>m²</th></tr></thead>
        <tbody>${zeilen}</tbody>
      </table></div>
    </div>`;
}

/* N407 — ersetzt die vorherigen einfachen Personen-Karten: Kostenarten
   untereinander, Einheiten/Parteien nebeneinander — dieselbe Form wie die
   Wasser-Detailtabelle. `a.positionen[i].verteilung` ist der von der Engine
   selbst gerechnete Euro-Betrag je Partei (N125-Filter, CCCLIX-Vorab-Split
   und Rundung schon berücksichtigt) — keine Neuberechnung im Frontend. */
function matrixHtml(a, wer) {
  // CCCLIX — ein Vorab-Anteil splittet EINE Kostenposition in zwei Engine-
  // Positionen (Vorab-Betrag direkt auf eine Einheit, Rest über den Schlüssel)
  // mit demselben `kostenart`-Namen. Ungruppiert stünde „Schornsteinfeger"
  // zweimal in der Matrix — verwirrend, wo die Checkliste nur eine Zeile
  // kennt. Zusammengefasst zu genau einer Zeile je Kostenart.
  const jeKostenart = new Map();
  for (const pos of a.positionen || []) {
    const bisher = jeKostenart.get(pos.kostenart);
    if (!bisher) {
      jeKostenart.set(pos.kostenart, { kostenart: pos.kostenart,
        kosten: pos.kosten || 0, verteilung: { ...(pos.verteilung || {}) } });
      continue;
    }
    bisher.kosten += pos.kosten || 0;
    for (const [p, betrag] of Object.entries(pos.verteilung || {})) {
      bisher.verteilung[p] = (bisher.verteilung[p] || 0) + betrag;
    }
  }
  const positionen = [...jeKostenart.values()];
  // N410 — auf Wunsch sortiert: erste Klick auf eine Spalte zeigt den
  // größten Posten dort zuerst.
  if (mxSort) {
    const wert = pos => mxSort.spalte === '__summe__' ? pos.kosten
      : (pos.verteilung?.[mxSort.spalte] || 0);
    const dir = mxSort.richtung === 'ab' ? -1 : 1;
    positionen.sort((x, y) => (wert(x) - wert(y)) * dir);
  }
  const einheitVon = new Map((state.schluessel?.parteien || [])
    .map(p => [p.partei, p.einheit]));
  const parteien = [...new Map((state.schluessel?.parteien || [])
    .map(p => [p.partei, p.einheit])).entries()]
    .sort((x, y) => (x[1] || '').localeCompare(y[1] || '') || x[0].localeCompare(y[0]))
    .map(([partei]) => partei);
  if (!positionen.length || !parteien.length) return '';

  const istLeer = p => !!(wer.get(p)?.leerstand || state.leerstaende.has(p));
  const spaltenKopf = p => istLeer(p)
    ? `<span class="mx-einheit">${esc(einheitVon.get(p) || '')}</span>
       <span class="mx-partei leer">Leerstand</span>`
    : `<span class="mx-einheit">${esc(einheitVon.get(p) || '')}</span>
       <span class="mx-partei">${esc(p)}</span>`;
  // N410 — kleiner Sortierpfeil je Spalte: neutral (⇅) solange sie nicht die
  // aktive ist, sonst die tatsächliche Richtung.
  const pfeil = spalte => mxSort?.spalte === spalte
    ? `<span class="mx-pfeil aktiv">${mxSort.richtung === 'ab' ? '▼' : '▲'}</span>`
    : '<span class="mx-pfeil">⇅</span>';

  const kopf = `<tr><th class="wd-rowh">Kostenart</th>${
    parteien.map(p => `<th class="mx-sortbar" data-mx-sort="${esc(p)}"
        >${spaltenKopf(p)}${pfeil(p)}</th>`).join('')
    }<th class="mx-sortbar" data-mx-sort="__summe__">Summe${pfeil('__summe__')}</th></tr>`;

  const zeileMit = (label, klasse, zellenHtml) =>
    `<tr${klasse ? ` class="${klasse}"` : ''}><td class="wd-rowh">${label}</td>${zellenHtml}</tr>`;

  // N410 — Heatmap INNERHALB der Zeile: eine einheitliche Zeilenfarbe zeigte
  // nur, welche Kostenart insgesamt groß ist — die Verteilung auf die
  // Einheiten in genau dieser Zeile blieb unsichtbar (alle Zellen gleich
  // eingefärbt). Jetzt bezieht sich die Farbe jeder Partei-Zelle auf das
  // Maximum IHRER EIGENEN Zeile: wer bei „Heizung" am meisten trägt, sticht
  // rot heraus, unabhängig davon, wie groß „Heizung" gegenüber „Strom" ist.
  // Die Summe-Spalte bleibt separat nach der Gesamtkostenart eingefärbt —
  // dort lässt sich weiterhin ablesen, welche Kostenart insgesamt am meisten
  // ausmacht. Die Kostenart-Spalte selbst bleibt neutral (sie trägt keinen
  // Betrag, nur den Namen).
  const maxKosten = Math.max(0.01, ...positionen.map(p => p.kosten));
  const posZeilen = positionen.map(pos => {
    const zeilenMax = Math.max(0.01,
      ...parteien.map(p => pos.verteilung?.[p] || 0));
    return `<tr><td class="wd-rowh">${esc(pos.kostenart)}</td>${
      parteien.map(p => {
        const betrag = pos.verteilung?.[p] || 0;
        return `<td style="background:${heatFarbe(betrag / zeilenMax)}"
            >${eur(betrag)}</td>`;
      }).join('')
      }<td style="background:${heatFarbe(pos.kosten / maxKosten)}"
          ><b>${eur(pos.kosten)}</b></td></tr>`;
  }).join('');

  const gesamtKosten = positionen.reduce((s, p) => s + (p.kosten || 0), 0);
  const summeZeile = zeileMit('Umlagefähige Kosten', 'wd-summe',
    parteien.map(p => `<td><b>${eur(a.parteien?.[p]?.kosten || 0)}</b></td>`).join('')
    + `<td><b>${eur(gesamtKosten)}</b></td>`);
  // Nur zeigen, wenn irgendwo wirklich ein § 35a-Anteil steckt — eine leere
  // Zeile für alle wäre reine Luft (roter Faden #4).
  const hatS35 = parteien.some(p => (a.parteien?.[p]?.s35 || 0) > 0);
  const s35Zeile = hatS35 ? zeileMit('davon § 35a', '',
    parteien.map(p => `<td>${eur(a.parteien?.[p]?.s35 || 0)}</td>`).join('')
    + '<td></td>') : '';
  const vzZeile = zeileMit('Vorauszahlungen', '',
    parteien.map(p => `<td>${eur(a.parteien?.[p]?.vorauszahlungen || 0)}</td>`).join('')
    + '<td></td>');
  const saldoZeile = zeileMit('Saldo', 'wd-summe',
    parteien.map(p => {
      const s = a.parteien?.[p]?.saldo || 0;
      return `<td><b style="color:${s >= 0 ? 'var(--pos)' : 'var(--neg)'}">${eur(s)}</b></td>`;
    }).join('') + '<td></td>');
  // N407/Folgemeldung — kein `<a target="_blank">` mehr: auf dem
  // Startbildschirm (installierte PWA) öffnete das den Systembetrachter ohne
  // jede Leiste, ohne Weg zurück in die App außer dem App-Wechsler. Jetzt
  // ein Knopf, der `pdfAnsehen()` (immo.js) im eigenen Dialog öffnet.
  const pdfZeile = zeileMit('Abrechnung', '',
    parteien.map(p => `<td><button type="button" class="mx-pdf"
        title="${esc(empfaengerKurz(wer.get(p)) || 'Abrechnung als PDF ansehen')}"
        data-pdf-ansehen="/api/zeitraeume/${zid}/abrechnung.pdf?partei=${encodeURIComponent(p)}"
        data-pdf-titel="${esc(`Abrechnung ${p}`)}"
        >▤ PDF</button></td>`).join('') + '<td></td>');

  return `<div class="karte">
      <h3>Kosten je Einheit</h3>
      <div class="wd-tabelle"><table class="wd-tab mx-tab">
        <thead>${kopf}</thead>
        <tbody>${posZeilen}${summeZeile}${s35Zeile}${vzZeile}${saldoZeile}${pdfZeile}</tbody>
      </table></div>
    </div>`;
}

export async function ergebnisHtml() {
  const [rechnung, versand] = await Promise.allSettled([
    einmal(`/zeitraeume/${zid}/abrechnung`),
    api(`/zeitraeume/${zid}/versand`),
  ]);
  if (rechnung.status !== 'fulfilled') {
    return '<div class="empty"><div class="big">Ergebnis nicht verfügbar</div></div>';
  }
  const a = rechnung.value;
  const wer = new Map((versand.value?.parteien || []).map(p => [p.partei, p]));

  const g = a.gesamt || {};
  const gesamtKarte = `<div class="karte">
      <h3>Gesamt</h3>
      <div class="summe"><span>Auslagen</span><b>${eur(g.auslagen)}</b></div>
      <div class="summe"><span>Abschläge</span><b>${eur(g.abschlaege)}</b></div>
      <div class="summe gesamt"><span>Saldo</span>
        <b class="${(g.saldo ?? 0) >= 0 ? 'pos' : 'neg'}">${eur(g.saldo)}</b></div>
    </div>`;

  return `${belegungHtml()}
    ${gesamtKarte}
    ${matrixHtml(a, wer)}
    ${vorauszahlungOhnePartei(a)}
    ${anteilOhnePartei(a)}
    ${a.offen?.length ? `<div class="karte"><h3>Noch offen</h3>
      ${a.ohne_betrag?.length ? `<div class="summe">
        <span>Ohne Betrag</span><b>${a.ohne_betrag.map(esc).join(', ')}</b></div>` : ''}
      ${a.ohne_verteilung?.length ? `<div class="summe">
        <span>Ohne Verteilung</span>
        <b class="neg">${a.ohne_verteilung.map(esc).join(', ')}</b></div>` : ''}
      </div>` : ''}`;
}
