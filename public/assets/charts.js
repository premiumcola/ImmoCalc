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
 *  also genügt eine Höhenaufteilung je Spalte statt eines Layout-Algorithmus.
 *
 *  `mindestHoehe` (Standard 190) ist der Boden der Zeichenfläche: wer den
 *  Fluss grösser und lesbarer haben will, hebt ihn an — die Bänder wachsen
 *  massstabsgetreu mit. Additiv, bestehende Aufrufer bleiben bei 190. */
export function sankey(knoten, fluss, { breite = 560, zeilenhoehe = 30,
                                        luecke = 12, format = v => String(v),
                                        mindestHoehe = 190 } = {}) {
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

  // Der Massstab der Baender richtet sich nach der dichtesten Spalte: so hoch,
  // dass der groesste Fluss ansehnlich breit wird. Bei wenigen grossen Posten
  // bleibt damit alles wie bisher.
  const spaltenKnoten = s => knoten.map((k, i) => ({ k, i }))
    .filter(({ k, i }) => k.spalte === s && benutzt.has(i));
  const proSpalte = Math.max(...spalten.map(s => spaltenKnoten(s).length));
  const bandHoehe = Math.max(mindestHoehe, proSpalte * (zeilenhoehe + luecke));
  const skala = (bandHoehe - luecke * (proSpalte - 1)) / gesamt;

  // Jeder Knoten bekommt einen sichtbaren Marker — auch bei Winzbetraegen —
  // und vor allem genug senkrechten Abstand fuer sein zweizeiliges Label. Das
  // Band selbst bleibt duenn und massstabsgetreu; nur Marker und Schrift
  // erhalten diese Mindestluft. Ohne sie fielen bei einem grossen und mehreren
  // winzigen Posten die untersten Beschriftungen ineinander und aus dem Bild.
  const MIN_MARKER = 6;
  const MIN_ABSTAND = schmal ? 33 : 29;
  const markHoehe = i => Math.max(MIN_MARKER, gewicht(i) * skala);
  const abstand = i => Math.max(markHoehe(i) + luecke, MIN_ABSTAND);
  const bandPad = i => Math.max(0, (markHoehe(i) - gewicht(i) * skala) / 2);

  // Tatsaechliche Spaltenhoehe = Summe der Knotenabstaende. Die viewBox waechst
  // im Eng-Fall mit, statt die untersten Labels aus dem Bild zu draengen.
  const stapelHoehe = s =>
    spaltenKnoten(s).reduce((sum, { i }) => sum + abstand(i), 0) - luecke;
  const hoehe = Math.max(mindestHoehe, ...spalten.map(stapelHoehe));

  // Knoten je Spalte mittig stapeln — jeder in seinem Abstands-Slot zentriert,
  // damit Marker (l.h) und Label (l.mitte) gleichmaessig Luft haben. Das Band
  // sitzt zentriert im Marker (bandPad), auch wenn der Marker hoeher ist.
  const lage = new Map();
  for (const s of spalten) {
    let y = (hoehe - stapelHoehe(s)) / 2;
    for (const { i } of spaltenKnoten(s)) {
      const slot = abstand(i) - luecke;
      const h = markHoehe(i);
      lage.set(i, { x: spaltenX(s), y: y + (slot - h) / 2, h, spalte: s,
                    mitte: y + slot / 2 });
      y += abstand(i);
    }
  }

  // Anschlusspunkte je Knoten fortlaufend vergeben
  const ausOffset = new Map(), einOffset = new Map();
  const baender = aktiv.map(f => {
    const a = lage.get(f.von), b = lage.get(f.nach);
    if (!a || !b) return '';
    const ha = f.wert * skala, hb = f.wert * skala;
    const y0 = a.y + bandPad(f.von) + (ausOffset.get(f.von) || 0);
    const y1 = b.y + bandPad(f.nach) + (einOffset.get(f.nach) || 0);
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

    // Label sitzt auf der Knotenmitte — der Mindestabstand der Knoten (abstand)
    // haelt Name und Betrag benachbarter Posten schon auseinander, deshalb
    // braucht es weder Ausweich-Stapeln noch Fuehrungslinien.
    const tx = rechts ? l.x - 8 : l.x + knotenBreite + 8;
    const anker = rechts ? 'end' : 'start';
    const ly = l.mitte;
    return `<rect x="${l.x}" y="${l.y}" width="${knotenBreite}" height="${l.h}"
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

/** Miete-Diagramm: gestapelte Säulen (Kaltmiete + Nebenkosten-Vorauszahlung)
 *  je Monat oder Quartal, darüber eine Linie für die Kaltmiete je m².
 *
 *  `punkte`: [{ label, miete, nk, qm }] — miete/nk sind Monatsbeträge (€),
 *  qm ist Kaltmiete ÷ effektive Fläche (€/m², null wenn keine Fläche bekannt).
 *  Die beiden Größen tragen unterschiedliche Maßstäbe, deshalb bekommt die
 *  €/m²-Linie eine eigene, dezent angedeutete Achse rechts. */
export function mietChart(punkte, { breite = 380, hoehe = 205,
                                    format = v => `${Math.round(v)} €` } = {}) {
  if (!punkte || !punkte.length)
    return leer('Noch keine Mietdaten für ein Diagramm');

  const summen = punkte.map(p => (p.miete || 0) + (p.nk || 0));
  const echtMax = Math.max(0, ...summen);
  const qmWerte = punkte.map(p => p.qm).filter(v => v != null && isFinite(v) && v > 0);
  const hatQm = qmWerte.length > 0;
  // Alles null (z. B. eine Einheit ganz ohne Miet-/NK-Betrag): ein ruhiger
  // Hinweis ist ehrlicher als ein leeres Achsenkreuz.
  if (echtMax <= 0 && !hatQm)
    return leer('Keine Miet- oder Nebenkostenbeträge hinterlegt');

  const rohMax = Math.max(1, echtMax);
  // Runde € Achse auf einen glatten Wert und lass Luft nach oben, damit die
  // €/m²-Linie frei über den Säulen liegt, statt in den Balkenköpfen zu kleben.
  const stufe = rohMax > 2000 ? 500 : rohMax > 500 ? 200 : 100;
  const maxE = Math.ceil(rohMax * 1.18 / stufe) * stufe;

  const qmMax = hatQm ? Math.max(...qmWerte) : 1;
  const maxQ = qmMax * 1.05;
  const fmtQm = v => (Math.round(v * 10) / 10).toLocaleString('de-DE');

  const padL = 6, padR = hatQm ? 34 : 6, padOben = 16, padUnten = 30;
  const nutzB = breite - padL - padR;
  const nutzH = hoehe - padOben - padUnten;
  const baseY = padOben + nutzH;
  const n = punkte.length;
  const step = nutzB / n;
  const bw = Math.min(30, step * 0.62);
  const eH = v => (v / maxE) * nutzH;
  const qY = v => baseY - (v / maxQ) * nutzH;
  const cx = i => padL + i * step + step / 2;

  // Waagerechte Hilfslinien (nur € Maßstab) — ruhig, ohne Zahlenflut.
  const gitter = [0.5, 1].map(f =>
    `<line x1="${padL}" y1="${runden(baseY - nutzH * f)}" x2="${breite - padR}"
           y2="${runden(baseY - nutzH * f)}" stroke="#EDF0F0" stroke-width="1"/>`).join('');

  const saeulen = punkte.map((p, i) => {
    const x = runden(cx(i) - bw / 2);
    const mH = eH(p.miete || 0), nH = eH(p.nk || 0);
    const gap = mH > 0.5 && nH > 0.5 ? 2 : 0;
    let s = '';
    if (mH > 0.5)
      s += `<rect x="${x}" y="${runden(baseY - mH)}" width="${runden(bw)}"
              height="${runden(mH)}" rx="3" fill="#0F6E5C"/>`;
    if (nH > 0.5)
      s += `<rect x="${x}" y="${runden(baseY - mH - gap - nH)}" width="${runden(bw)}"
              height="${runden(nH)}" rx="3" fill="#916212"/>`;
    return `<g><title>${p.label}: ${format(p.miete || 0)} Miete + ${
      format(p.nk || 0)} NK${p.qm != null && p.qm > 0
        ? ` · ${fmtQm(p.qm)} €/m²` : ''}</title>${s || `<rect x="${x}" y="${
        runden(baseY - 2)}" width="${runden(bw)}" height="2" rx="1" fill="#D6DCDD"/>`}</g>`;
  }).join('');

  let linie = '', qmAchse = '';
  if (hatQm) {
    const pkt = punkte.map((p, i) => p.qm != null && p.qm > 0 ? [cx(i), qY(p.qm)] : null);
    const d = pkt.filter(Boolean)
      .map((pt, k) => `${k ? 'L' : 'M'}${runden(pt[0])},${runden(pt[1])}`).join(' ');
    const dots = n <= 14 ? pkt.filter(Boolean).map(pt =>
      `<circle cx="${runden(pt[0])}" cy="${runden(pt[1])}" r="3.4"
               fill="#16262C" stroke="#FFF" stroke-width="1.6"/>`).join('') : '';
    linie = `<path d="${d}" fill="none" stroke="#16262C" stroke-width="2"
                   stroke-linejoin="round" stroke-linecap="round"/>${dots}`;
    // Angedeutete €/m² Achse rechts: Höchstwert oben, Einheit als Hinweis.
    const top = qY(qmMax);
    qmAchse = `<text x="${breite - padR + 5}" y="${runden(top) + 4}" class="qax">${
      fmtQm(qmMax)}</text>
      <text x="${breite - padR + 5}" y="${runden(top) + 16}" class="qax qu">€/m²</text>`;
  }

  const schritt = Math.max(1, Math.ceil(n / 8));
  const achse = punkte.map((p, i) => i % schritt === 0
    ? `<text x="${runden(cx(i))}" y="${hoehe - 9}" class="ax">${p.label}</text>` : '')
    .join('');

  return `<svg viewBox="0 0 ${breite} ${hoehe}" class="chart" role="img">
      <style>
        .ax{font:500 9.5px var(--mono);fill:var(--soft);text-anchor:middle}
        .qax{font:600 10px var(--mono);fill:var(--ink);text-anchor:start}
        .qax.qu{font-weight:500;fill:var(--soft)}
      </style>
      ${gitter}
      <line x1="${padL}" y1="${baseY}" x2="${breite - padR}" y2="${baseY}"
            stroke="#D6DCDD" stroke-width="1"/>
      ${saeulen}${linie}${qmAchse}${achse}
    </svg>`;
}

export function legende(eintraege) {
  return `<div class="legende">` + eintraege.map((e, i) =>
    `<span class="le"><i style="background:${e.farbe || farbe(i)}"></i>${e.name}</span>`
  ).join('') + `</div>`;
}

const leer = text =>
  `<div class="chartleer">${text}</div>`;
