/* verlauf.js — die Verlaufs-Karte: Grafik ueber alle Monate, Legende, ein
   ruhiger Vermerk fuer unzugeordnete kWh, und eine paginierte Monatstabelle mit
   Heatmap in der Kosten-Spalte (N188).

   Der Verlauf laeuft ueber alle Monate, ueber Jahresgrenzen hinweg. Ein Monat
   ohne Ladung bleibt als leere Stelle stehen — eine Luecke im Verlauf waere
   kein Verlauf. Die paginierte Tabelle (~5 Zeilen je Seite, neueste voran)
   greift auf `S.verlaufMonate` zurueck; Blaettern zeichnet nur den Tabellen-
   Container neu, kein zweiter API-Aufruf. */
import { S, NETZ, PV, AKKU, EIGEN, OFFEN, MIN_PRO_MONAT, LABEL_BREITE,
         TAB_PRO_SEITE, kwh, proz, zahl, datum, zeigeFehler } from './state.js';
import { api, esc, eur } from '../immo.js';
import { legende } from '../charts.js';
import { jahreUebernehmen } from './matrix.js';

/* =======================================================================
   Grafik: je Monat ein Balken, gestapelt aus den drei Kostenbloecken —
   unten der Akku, darueber PV, oben der Netzbezug. Ein Monat ohne Ladung
   bleibt als leere Stelle stehen.

   Drei Vorkehrungen, damit die Grafik auch mit vielen Monaten lesbar
   bleibt: feste Breite je Monat (der Balken schrumpft nie zum Strich,
   notfalls scrollt die Grafik), Monatsbeschriftung ausgeduennt statt
   uebereinander, und jeder Jahreswechsel als Trennstrich mit Jahreszahl.
   ======================================================================= */
export function grafik(monate, platzHint) {
  const max = Math.max(1, ...monate.map(m => m.kwh || 0));
  // `platzHint` erlaubt es der Abrechnungs-Vorschau (N184), die Grafik auf die
  // schmalere Blattbreite zu setzen, statt die breitere Verlauf-Karte zu messen.
  const platz = Math.max(240,
    platzHint || document.getElementById('verlauf')?.clientWidth || 320);
  const proMonat = Math.max(MIN_PRO_MONAT, platz / monate.length);
  const breite = Math.round(proMonat * monate.length);
  const hoehe = 190, padO = 12, padU = 40;
  const nutz = hoehe - padO - padU;
  const bw = Math.min(22, Math.max(6, proMonat * 0.6));
  const grund = padO + nutz;
  // Beschriftung ausduennen statt uebereinanderlegen — je enger die Monate,
  // desto groesser der Schritt.
  const schritt = Math.max(1, Math.ceil(LABEL_BREITE / proMonat));

  const saeulen = monate.map((m, i) => {
    const mitte = i * proMonat + proMonat / 2;
    const h = (m.kwh || 0) / max * nutz;
    const x = mitte - bw / 2;
    const beschriftet = i % schritt === 0;
    const kuerzel = beschriftet
      ? `<text x="${mitte}" y="${hoehe - 20}" class="ax">${esc(m.kurz)}</text>` : '';
    const titel = `${m.label}: ${kwh(m.kwh)}` + (m.aufteilung
      ? ` · Netz ${proz(m.extern_prozent)}`
        + (m.dreiteilig
            ? ` · PV ${proz(m.pv_prozent)} · Akku ${proz(m.speicher_prozent)}`
            : ` · eigen ${proz(m.eigen_prozent)}`)
      : '');
    if (h <= 0) return kuerzel;

    const block = (menge, farbe, unten) => {
      const hh = Math.max(0, menge || 0) / max * nutz;
      return hh <= 0 ? ''
        : `<rect x="${x}" y="${grund - unten - hh}" width="${bw}" height="${hh}"
                 rx="3" fill="${farbe}"/>`;
    };
    // Negative Bloecke gibt es: die Box schreibt selten einen negativen
    // PV-Anteil. Gestapelt wird deshalb ueber die sichtbaren Anteile.
    const teile = !m.aufteilung ? [[m.kwh, OFFEN]]
      : m.dreiteilig
        ? [[m.speicher_kwh, AKKU], [m.pv_kwh, PV], [m.extern_kwh, NETZ]]
        : [[m.eigen_kwh, EIGEN], [m.extern_kwh, NETZ]];
    let unten = 0;
    const stapel = teile.map(([menge, farbe]) => {
      const stueck = block(menge, farbe, unten);
      unten += Math.max(0, menge || 0) / max * nutz;
      return stueck;
    }).join('');

    return `<rect x="${x}" y="${grund - h}" width="${bw}" height="${h}" rx="3"
                  fill="${OFFEN}"><title>${esc(titel)}</title></rect>
      ${stapel}${kuerzel}`;
  }).join('');

  // Jahreswechsel: ein feiner Strich vor dem Januar, die Jahreszahl darunter.
  const jahre = monate.map((m, i) => {
    if (i > 0 && m.monat !== 1) return '';
    const x = i * proMonat;
    return `${i > 0 ? `<line x1="${x}" y1="${padO}" x2="${x}" y2="${grund + 4}"
                             stroke="#D6DCDD" stroke-width="1"/>` : ''}
      <text x="${x + 3}" y="${hoehe - 6}" class="jz">${m.jahr}</text>`;
  }).join('');

  return `<div class="chartrahmen"><svg width="${breite}" height="${hoehe}"
               viewBox="0 0 ${breite} ${hoehe}" class="chart" role="img"
               aria-label="Geladene Energie je Monat">
      <style>.ax{font:500 9.5px var(--body);fill:var(--soft);text-anchor:middle}
             .jz{font:600 9px var(--mono);fill:var(--soft)}</style>
      <line x1="0" y1="${grund}" x2="${breite}" y2="${grund}"
            stroke="#D6DCDD" stroke-width="1"/>
      ${jahre}${saeulen}
    </svg></div>`;
}

/* Die Monatstabelle — paginiert (N178). Sie liest die geholten Monate aus dem
   Modul-Zustand, zeigt ~5 je Seite mit den NEUESTEN zuerst und laesst sich mit
   ◀ / ▶ durchblaettern; die Summe ueber alle Monate steht als tfoot immer
   sichtbar darunter. Kein Argument, kein API-Aufruf — `tabelleNeu` zeichnet nur
   diesen Container neu. */
export function verlaufTabelle() {
  const monate = S.verlaufMonate;
  const summe = S.verlaufSumme;
  // Ein Monat ohne Ladung bekommt einen Strich, keine 0,00 mit leerer
  // Prozentzeile darunter — es gibt schlicht nichts aufzuteilen.
  const zelle = (menge, prozent) => menge == null || prozent == null
    ? '<td class="leise">—</td>'
    : `<td>${zahl(menge)}<span class="pz">${proz(prozent)}</span></td>`;
  const drei = summe.dreiteilig;
  // N188 — Reichweite (km, wie weit die geladene Menge trägt) und Gesamtbetrag
  // (€) je Monat. Beide kommen aus dem Backend; fehlt die Grundlage (kein
  // Verbrauch bzw. kein Satz), bleibt die Zelle leer statt eine 0 zu behaupten.
  const kmZelle = m => m.km == null
    ? '<td class="leise">—</td>'
    : `<td>${zahl(m.km, 0)}<span class="pz">km</span></td>`;
  // Die Heatmap der Gesamtbeträge: je mehr in einem Monat geladen — und damit
  // gefahren — wurde, desto kräftiger die amberfarbene Tönung der €-Zelle.
  // Bezug ist die geladene Menge über ALLE Monate (nicht nur die Seite), damit
  // die Seiten untereinander vergleichbar bleiben. Die Summenzeile bleibt neutral.
  const maxKwh = Math.max(1, ...monate.map(m => m.kwh || 0));
  const heat = w => {
    const i = Math.min(1, (w || 0) / maxKwh);
    return i > 0.001 ? `background:rgba(145,98,18,${(0.05 + 0.30 * i).toFixed(3)})` : '';
  };
  const eurZelle = (m, summeRow) => m.kosten == null
    ? '<td class="leise">—</td>'
    : `<td class="kbtr" style="${summeRow ? '' : heat(m.kwh)}">${eur(m.kosten)}</td>`;
  const zeile = (m, summeRow = false) => `<tr>
    <td>${esc(m.label)}</td>
    <td class="${m.kwh ? '' : 'leise'}">${zahl(m.kwh)}</td>
    ${zelle(m.extern_kwh, m.extern_prozent)}
    ${drei ? zelle(m.pv_kwh, m.pv_prozent) + zelle(m.speicher_kwh, m.speicher_prozent)
           : zelle(m.eigen_kwh, m.eigen_prozent)}
    ${kmZelle(m)}
    ${eurZelle(m, summeRow)}</tr>`;

  // Neueste voran: die Grafik oben laeuft chronologisch, die Tabelle blaettert
  // das Juengste zuerst — bei einer Abrechnung ist das das Interessante.
  const umgekehrt = [...monate].reverse();
  const seiten = Math.max(1, Math.ceil(umgekehrt.length / TAB_PRO_SEITE));
  S.verlaufSeite = Math.min(Math.max(0, S.verlaufSeite), seiten - 1);
  const start = S.verlaufSeite * TAB_PRO_SEITE;
  const teil = umgekehrt.slice(start, start + TAB_PRO_SEITE);

  const pager = seiten > 1 ? `<div class="tabpager">
      <button class="tp" data-tabseite="${S.verlaufSeite - 1}"
        ${S.verlaufSeite === 0 ? 'disabled' : ''}
        aria-label="Neuere Monate">◀</button>
      <span class="tpz">Seite ${S.verlaufSeite + 1}/${seiten}</span>
      <button class="tp" data-tabseite="${S.verlaufSeite + 1}"
        ${S.verlaufSeite >= seiten - 1 ? 'disabled' : ''}
        aria-label="Ältere Monate">▶</button>
    </div>` : '';

  return `${pager}<div class="tabrahmen"><table class="mt">
      <thead><tr><th>Monat</th><th>Geladen</th><th>Netz</th>
        ${drei ? '<th>PV</th><th>Akku</th>' : '<th>Eigen</th>'}
        <th title="Reichweite des E-Autos">Reichw.</th><th>Kosten</th></tr></thead>
      <tbody>${teil.map(m => zeile(m)).join('')}</tbody>
      <tfoot>${zeile({ ...summe, label: 'Summe' }, true)}</tfoot>
    </table></div>`;
}

/* Blaettern zeichnet nur den Tabellen-Container neu — kein API-Aufruf, keine
   neu geholten Daten, die Grafik bleibt stehen. */
export function tabelleNeu() {
  const box = document.getElementById('verlauftabelle');
  if (box) box.innerHTML = verlaufTabelle();
}

/* Ein ruhiger Vermerk statt eines Warnbalkens: kWh, die die Wallbox keinem
   Anteil zuordnet, zaehlen zum eigenen Strom (PV). Das ist eine Festlegung,
   keine Stoerung — sie gehoert an die Zahl, nicht in einen gelben Kasten. */
function restVermerk(s) {
  if (!(s.rest_kwh > 0.05)) return '';
  return `<span class="vermerk">Davon ordnet die Wallbox
    ${zahl(s.rest_kwh)} kWh (${proz(s.rest_prozent)}) keinem Anteil zu; diese
    Menge zählt zum eigenen Strom aus der PV.</span>`;
}

export async function verlaufZeigen() {
  const ziel = document.getElementById('verlauf');
  if (!ziel) return;
  ziel.innerHTML = '<div class="leer">Verlauf wird geholt …</div>';
  let d;
  try {
    d = await api(`/tankstelle/${encodeURIComponent(S.objektSlug)}/verlauf?alles=1`);
  } catch (fehler) {
    zeigeFehler(ziel, 'Verlauf nicht verfügbar', fehler);
    return;
  }
  jahreUebernehmen(d.jahre || []);

  const s = d.summe || {};
  // N178 — die Monate fuer die paginierte Tabelle festhalten; frische Daten
  // starten wieder auf der ersten Seite (die neuesten Monate).
  S.verlaufMonate = d.monate || [];
  S.verlaufSumme = s;
  S.verlaufSeite = 0;
  const nichts = !(s.kwh > 0);
  const drei = s.dreiteilig;
  ziel.innerHTML = `
    ${d.hinweis ? `<div class="notiz"><span class="wi">◔</span>
       <span>${esc(d.hinweis)}</span></div>` : ''}
    <div class="kpi vier">
      <div class="k"><span class="kl">Geladen</span>
        <span class="kv">${kwh(s.kwh, 0)}</span></div>
      <div class="k"><span class="kl">Aus dem Netz</span>
        <span class="kv amber">${s.extern_prozent == null ? '—' : proz(s.extern_prozent)}</span></div>
      <div class="k"><span class="kl">Eigener Strom</span>
        <span class="kv teal">${s.eigen_prozent == null ? '—' : proz(s.eigen_prozent)}</span></div>
      <div class="k"><span class="kl">Ladungen</span>
        <span class="kv">${(s.anzahl ?? 0).toLocaleString('de-DE')}</span></div>
    </div>
    ${nichts ? `<div class="leer" style="margin-top:14px"><b>Noch nichts geladen</b>
        An dieser Station ist bisher keine Ladung angekommen. Sobald die
        Wallbox Daten liefert — oder unten eine Ladung erfasst wird — steht
        hier der Verlauf.</div>`
      : `<span class="zrzeile" style="margin-top:14px">${datum(d.von)} –
           ${datum(d.bis)} · ${(d.monate || []).length} Monate</span>
         ${grafik(d.monate || [])}
         ${legende(drei
            ? [{ name: 'Netz', farbe: NETZ },
               { name: 'PV direkt', farbe: PV },
               { name: 'Akku', farbe: AKKU }]
            : [{ name: 'Netz', farbe: NETZ },
               { name: 'Eigener Strom (PV + Akku)', farbe: EIGEN }])}
         ${restVermerk(s)}
         <div id="verlauftabelle">${verlaufTabelle()}</div>`}`;
}
