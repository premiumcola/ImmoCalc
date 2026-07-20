/* Diagramme als reines SVG — bewusst ohne Bibliothek, passend zur
   Design-Sprache. Alle Funktionen liefern einen SVG-String zurueck. */

const PALETTE = ['#0F6E5C', '#916212', '#2E7D4F', '#B24229', '#5C6B70', '#7A9E94'];
export const farbe = i => PALETTE[i % PALETTE.length];

const runden = n => Math.round(n * 100) / 100;

/** Waagerechte Balken mit Beschriftung — fuer Kostenbloecke. */
export function balken(daten, { hoehe = 30, luecke = 10, breite = 380 } = {}) {
  const eintraege = daten.filter(d => d.wert > 0);
  if (!eintraege.length) return leer('Keine Werte für diesen Zeitraum');

  const max = Math.max(...eintraege.map(d => d.wert));
  const labelBreite = 104;
  const bahn = breite - labelBreite - 74;
  const h = eintraege.length * (hoehe + luecke);

  const zeilen = eintraege.map((d, i) => {
    const y = i * (hoehe + luecke);
    const w = Math.max(3, (d.wert / max) * bahn);
    return `
      <text x="0" y="${y + hoehe / 2 + 4}" class="lbl">${d.name}</text>
      <rect x="${labelBreite}" y="${y}" width="${w}" height="${hoehe}"
            rx="7" fill="${d.farbe || farbe(i)}"/>
      <text x="${labelBreite + w + 8}" y="${y + hoehe / 2 + 4}" class="val">${d.text}</text>`;
  }).join('');

  return `<svg viewBox="0 0 ${breite} ${h}" class="chart" role="img">
      <style>
        .lbl{font:500 12px var(--body);fill:var(--soft)}
        .val{font:600 12px var(--mono);fill:var(--ink)}
      </style>${zeilen}
    </svg>`;
}

/** Gruppierte Saeulen je Objekt: Einnahmen gegen Ausgaben. */
export function saeulen(gruppen, { breite = 380, hoehe = 170 } = {}) {
  if (!gruppen.length) return leer('Keine Objekte');

  const max = Math.max(1, ...gruppen.flatMap(g => [g.a, g.b]));
  const padUnten = 34, padOben = 6;
  const nutz = hoehe - padUnten - padOben;
  const proGruppe = breite / gruppen.length;
  const bw = Math.min(26, proGruppe / 3.2);

  const inhalt = gruppen.map((g, i) => {
    const mitte = i * proGruppe + proGruppe / 2;
    const ha = (g.a / max) * nutz, hb = (g.b / max) * nutz;
    const kurz = g.name.length > 12 ? g.name.slice(0, 11) + '…' : g.name;
    return `
      <rect x="${mitte - bw - 3}" y="${padOben + nutz - ha}" width="${bw}" height="${ha}"
            rx="5" fill="#2E7D4F"/>
      <rect x="${mitte + 3}" y="${padOben + nutz - hb}" width="${bw}" height="${hb}"
            rx="5" fill="#B24229"/>
      <text x="${mitte}" y="${hoehe - 16}" class="ax">${kurz}</text>`;
  }).join('');

  return `<svg viewBox="0 0 ${breite} ${hoehe}" class="chart" role="img">
      <style>.ax{font:500 10.5px var(--body);fill:var(--soft);text-anchor:middle}</style>
      <line x1="0" y1="${padOben + nutz}" x2="${breite}" y2="${padOben + nutz}"
            stroke="#D6DCDD" stroke-width="1"/>
      ${inhalt}
    </svg>`;
}

/** Linienverlauf ueber Jahre — fuer den Mietverlauf. */
export function linie(jahre, reihen, { breite = 380, hoehe = 165 } = {}) {
  if (!reihen.length) return leer('Noch keine Mietdaten erfasst');

  const max = Math.max(1, ...reihen.flatMap(r => r.werte));
  const padL = 6, padUnten = 26, padOben = 8;
  const nutzB = breite - padL * 2;
  const nutzH = hoehe - padUnten - padOben;
  const x = i => padL + (jahre.length === 1 ? nutzB / 2 : (i / (jahre.length - 1)) * nutzB);
  const y = v => padOben + nutzH - (v / max) * nutzH;

  const pfade = reihen.map((r, i) => {
    const d = r.werte.map((v, j) => `${j ? 'L' : 'M'}${runden(x(j))},${runden(y(v))}`).join(' ');
    const punkte = r.werte.map((v, j) =>
      `<circle cx="${runden(x(j))}" cy="${runden(y(v))}" r="3" fill="${farbe(i)}"/>`).join('');
    return `<path d="${d}" fill="none" stroke="${farbe(i)}" stroke-width="2.5"
                  stroke-linejoin="round" stroke-linecap="round"/>${punkte}`;
  }).join('');

  const achse = jahre.map((j, i) =>
    `<text x="${runden(x(i))}" y="${hoehe - 8}" class="ax">${String(j).slice(2)}</text>`).join('');

  return `<svg viewBox="0 0 ${breite} ${hoehe}" class="chart" role="img">
      <style>.ax{font:500 10px var(--mono);fill:var(--soft);text-anchor:middle}</style>
      <line x1="0" y1="${padOben + nutzH}" x2="${breite}" y2="${padOben + nutzH}"
            stroke="#D6DCDD" stroke-width="1"/>
      ${pfade}${achse}
    </svg>`;
}

export function legende(eintraege) {
  return `<div class="legende">` + eintraege.map((e, i) =>
    `<span class="le"><i style="background:${e.farbe || farbe(i)}"></i>${e.name}</span>`
  ).join('') + `</div>`;
}

const leer = text =>
  `<div class="chartleer">${text}</div>`;
