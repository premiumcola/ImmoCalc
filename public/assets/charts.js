/* Diagramme als reines SVG — bewusst ohne Bibliothek, passend zur
   Design-Sprache. Alle Funktionen liefern einen SVG-String zurueck. */

const PALETTE = ['#0F6E5C', '#916212', '#2E7D4F', '#B24229', '#5C6B70', '#7A9E94'];
export const farbe = i => PALETTE[i % PALETTE.length];

const runden = n => Math.round(n * 100) / 100;

/** Waagerechte Balken mit Beschriftung — fuer Kostenbloecke.
 *
 *  Die Beschriftungsspalte waechst mit der viewBox mit, und wie viele Zeichen
 *  hineinpassen, rechnet das Diagramm selbst aus. Vorher kuerzte die aufrufende
 *  Seite pauschal auf 15 Zeichen — auf dem iPhone stimmte das, auf dem Desktop
 *  stand „Niederschlagswa…" neben einer halb leeren Spalte. Der volle Name
 *  bleibt als <title> am Balken. */
export function balken(daten, { hoehe = 30, luecke = 10, breite = 380,
                                labelBreite = Math.round(breite * 0.28) } = {}) {
  const eintraege = daten.filter(d => d.wert > 0);
  if (!eintraege.length) return leer('Keine Werte für diesen Zeitraum');

  const max = Math.max(...eintraege.map(d => d.wert));
  const bahn = breite - labelBreite - 74;
  const h = eintraege.length * (hoehe + luecke);
  // 6.6 viewBox-Einheiten je Zeichen bei 12 px Inter — reicht als Faustmass,
  // die Spalte hat noch 8 Einheiten Luft bis zum Balken.
  const maxZeichen = Math.max(8, Math.floor((labelBreite - 8) / 6.6));
  const kurz = n => n.length > maxZeichen ? n.slice(0, maxZeichen - 1) + '…' : n;

  const zeilen = eintraege.map((d, i) => {
    const y = i * (hoehe + luecke);
    const w = Math.max(3, (d.wert / max) * bahn);
    return `
      <text x="0" y="${y + hoehe / 2 + 4}" class="lbl">${kurz(d.name)}<title>${
        d.name}</title></text>
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
  // Alles null: leere Achsen sind nutzlos, ein Hinweis ist ehrlicher.
  if (!gruppen.some(g => g.a > 0 || g.b > 0))
    return leer('Noch keine Einnahmen oder Ausgaben erfasst');

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

/** Sankey: Bandbreite entspricht dem Betrag. Knoten tragen eine Spaltennummer,
 *  Flüsse verbinden sie. Bewusst ohne Bibliothek — die Ebenen sind vorgegeben,
 *  also genügt eine Höhenaufteilung je Spalte statt eines Layout-Algorithmus. */
export function sankey(knoten, fluss, { breite = 560, zeilenhoehe = 30,
                                        luecke = 12, format = v => String(v) } = {}) {
  const aktiv = fluss.filter(f => f.wert > 0);
  if (!aktiv.length) return leer('Noch keine Zahlen für diesen Zeitraum');

  const spalten = [...new Set(knoten.map(k => k.spalte))].sort((a, b) => a - b);
  const summeAus = i => aktiv.filter(f => f.von === i).reduce((s, f) => s + f.wert, 0);
  const summeEin = i => aktiv.filter(f => f.nach === i).reduce((s, f) => s + f.wert, 0);
  const gewicht = i => Math.max(summeAus(i), summeEin(i));

  const benutzt = new Set(aktiv.flatMap(f => [f.von, f.nach]));
  const gesamt = Math.max(...spalten.map(s =>
    knoten.reduce((sum, k, i) => sum + (k.spalte === s && benutzt.has(i) ? gewicht(i) : 0), 0)));
  if (!gesamt) return leer('Keine Beträge');

  // Höhe so wählen, dass auch der kleinste Block sichtbar ist UND jede
  // Beschriftung Platz hat — sonst rutschen die untersten aus dem Bild.
  const proSpalte = Math.max(...spalten.map(s =>
    knoten.filter((k, i) => k.spalte === s && benutzt.has(i)).length));
  const MINDEST_ABSTAND = 27;
  const hoehe = Math.max(190, proSpalte * Math.max(zeilenhoehe + luecke,
                                                   MINDEST_ABSTAND));
  const skala = (hoehe - luecke * (proSpalte - 1)) / gesamt;

  const knotenBreite = 13;
  const spaltenX = s => spalten.length === 1 ? 0
    : (s / (spalten.length - 1)) * (breite - knotenBreite);

  // Auf schmalen Schirmen wird das SVG stark verkleinert — dort brauchen
  // Rand und Schrift im viewBox mehr Mass, damit die Beschriftung lesbar bleibt.
  const schmal = breite < 400;
  const rand = schmal ? 66 : 96;
  const schrift = schmal ? 13 : 11;

  // Überschuss und Fehlbetrag sind keine Kostenart, sondern das Ergebnis —
  // sie tragen deshalb nicht die naechste Palettenfarbe, sondern das Vorzeichen.
  const ROLLENFARBE = { plus: '#2E7D4F', minus: '#B24229' };
  const knotenFarbe = i => ROLLENFARBE[knoten[i].rolle] || farbe(i);

  // Knoten je Spalte stapeln
  const lage = new Map();
  for (const s of spalten) {
    const drin = knoten.map((k, i) => ({ k, i }))
      .filter(({ k, i }) => k.spalte === s && benutzt.has(i));
    const gesamtHoehe = drin.reduce((sum, { i }) => sum + gewicht(i) * skala, 0)
      + luecke * (drin.length - 1);
    let y = (hoehe - gesamtHoehe) / 2;
    for (const { i } of drin) {
      const h = Math.max(2, gewicht(i) * skala);
      lage.set(i, { x: spaltenX(s), y, h, spalte: s });
      y += h + luecke;
    }
  }

  // Anschlusspunkte je Knoten fortlaufend vergeben
  const ausOffset = new Map(), einOffset = new Map();
  const baender = aktiv.map(f => {
    const a = lage.get(f.von), b = lage.get(f.nach);
    if (!a || !b) return '';
    const ha = f.wert * skala, hb = f.wert * skala;
    const y0 = a.y + (ausOffset.get(f.von) || 0);
    const y1 = b.y + (einOffset.get(f.nach) || 0);
    ausOffset.set(f.von, (ausOffset.get(f.von) || 0) + ha);
    einOffset.set(f.nach, (einOffset.get(f.nach) || 0) + hb);

    const x0 = a.x + knotenBreite, x1 = b.x;
    const mitte = (x0 + x1) / 2;
    const d = `M${x0},${y0} C${mitte},${y0} ${mitte},${y1} ${x1},${y1}
               L${x1},${y1 + hb} C${mitte},${y1 + hb} ${mitte},${y0 + ha} ${x0},${y0 + ha} Z`;
    // Das Band trägt die Farbe seiner Quelle, nur blasser — so gehört sichtbar
    // zusammen, was zusammengehört, statt bunt durcheinanderzulaufen.
    const quelle = lage.get(f.von).spalte === spalten[0] ? f.von : f.nach;
    return `<path d="${d}" fill="${knotenFarbe(quelle)}" fill-opacity=".3"><title>${
      knoten[f.von].name} → ${knoten[f.nach].name}: ${format(f.wert)}</title></path>`;
  }).join('');

  // Beschriftungen je Spalte kollisionsfrei stapeln: dünne Baender liegen sonst
  // so dicht, dass Name und Betrag uebereinanderfallen. Die Baender selbst
  // bleiben massstabsgetreu — nur die Schrift rueckt aus.
  const labelY = new Map();
  for (const s of spalten) {
    const drin = [...lage.entries()]
      .filter(([, l]) => l.spalte === s)
      .sort((a, b) => a[1].y - b[1].y);
    let letzte = -Infinity;
    for (const [i, l] of drin) {
      const y = Math.max(l.y + l.h / 2, letzte + MINDEST_ABSTAND);
      labelY.set(i, y);
      letzte = y;
    }
  }

  // Ist eine Mittelspalte mit einem einzigen Knoten besetzt — der Regelfall:
  // „Einnahmen" bzw. „Vorauszahlungen" —, gehoert ihre Beschriftung ueber das
  // ganze Bild. Direkt ueber dem Kasten lag sie auf 390 px genau auf Hoehe der
  // obersten rechten Beschriftung und schob sich mit ihr ineinander.
  const einzelneMitte = new Set(spalten.slice(1, -1)
    .filter(s => knoten.filter((k, i) => k.spalte === s && benutzt.has(i)).length === 1));
  const obenPlatz = 40;

  // Die Beschriftung der Aussenspalten zeigt nach innen, ueber die Baender —
  // seitlich waere auf dem iPhone kein Platz. Damit die beiden Seiten sich in
  // der Mitte nicht begegnen, bekommt jede genau die Strecke bis zur
  // Nachbarspalte; was laenger ist, wird gekuerzt und steht voll im <title>.
  // Auf iPad und Desktop reicht diese Strecke fuer jeden vorkommenden Namen.
  const letzteSpalte = spalten[spalten.length - 1];
  const platz = rechts => {
    if (spalten.length < 2) return breite;
    return rechts
      ? (spaltenX(letzteSpalte) - 8) - (spaltenX(spalten[spalten.length - 2])
                                        + knotenBreite) - 8
      : spaltenX(spalten[1]) - (spaltenX(spalten[0]) + knotenBreite + 8) - 8;
  };
  const kuerze = (name, rechts) => {
    const max = Math.max(6, Math.floor(platz(rechts) / (schrift * 0.55)));
    return name.length > max ? name.slice(0, max - 1) + '…' : name;
  };

  const kaesten = [...lage.entries()].map(([i, l]) => {
    const rechts = l.spalte === spalten[spalten.length - 1];
    const mittig = !rechts && l.spalte !== spalten[0];

    // Mittelspalten beschriften wir ueber dem Kasten — seitlich wuerde die
    // Schrift in die Beschriftung der Nachbarspalte laufen.
    if (mittig) {
      const ly = einzelneMitte.has(l.spalte) ? -obenPlatz + 15 : l.y - 14;
      return `<rect x="${l.x}" y="${l.y}" width="${knotenBreite}" height="${l.h}"
                    rx="3" fill="${knotenFarbe(i)}"/>
        <text x="${l.x + knotenBreite / 2}" y="${ly}" class="kn"
              text-anchor="middle">${knoten[i].name}</text>
        <text x="${l.x + knotenBreite / 2}" y="${ly + 11}" class="kw"
              text-anchor="middle">${format(gewicht(i))}</text>`;
    }

    const tx = rechts ? l.x - 8 : l.x + knotenBreite + 8;
    const anker = rechts ? 'end' : 'start';
    const ly = labelY.get(i);
    // Fuehrungslinie, wenn die Schrift vom Kasten wegrutschen musste
    const versatz = Math.abs(ly - (l.y + l.h / 2)) > 3
      ? `<line x1="${rechts ? l.x : l.x + knotenBreite}" y1="${l.y + l.h / 2}"
               x2="${rechts ? l.x - 5 : l.x + knotenBreite + 5}" y2="${ly - 3}"
               stroke="#B9C4C5" stroke-width="1"/>` : '';
    return `${versatz}<rect x="${l.x}" y="${l.y}" width="${knotenBreite}" height="${l.h}"
                  rx="3" fill="${knotenFarbe(i)}"/>
      <text x="${tx}" y="${ly - 3}" class="kn" text-anchor="${anker}">${
        kuerze(knoten[i].name, rechts)}<title>${knoten[i].name}</title></text>
      <text x="${tx}" y="${ly + 10}" class="kw" text-anchor="${anker}">${
        format(gewicht(i))}</text>`;
  }).join('');

  // oben Platz fuer die Beschriftung der Mittelspalte
  return `<svg viewBox="${-rand} ${-obenPlatz} ${breite + rand * 2} ${hoehe + obenPlatz + 14}"
               class="chart sankey" role="img">
      <style>
        .kn{font:600 ${schrift}px var(--disp);fill:var(--ink)}
        .kw{font:500 ${schmal ? 12 : 10}px var(--mono);fill:var(--soft)}
      </style>${baender}${kaesten}
    </svg>`;
}

export function legende(eintraege) {
  return `<div class="legende">` + eintraege.map((e, i) =>
    `<span class="le"><i style="background:${e.farbe || farbe(i)}"></i>${e.name}</span>`
  ).join('') + `</div>`;
}

const leer = text =>
  `<div class="chartleer">${text}</div>`;
