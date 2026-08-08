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
                                labelBreite } = {}) {
  const eintraege = daten.filter(d => d.wert > 0);
  if (!eintraege.length) return leer('Keine Werte für diesen Zeitraum');

  const max = Math.max(...eintraege.map(d => d.wert));
  // 7 viewBox-Einheiten je Zeichen bei 12 px Inter 500 — bewusst grosszuegig,
  // damit breite Zeichen (W, M) die Spalte nicht in den Balken schieben.
  const zeichenBreite = 7;
  const luft = 12;                       // Luft zwischen Beschriftung und Balken
  // Die Beschriftungsspalte waechst mit dem laengsten Namen, aber gedeckelt:
  // breit genug, dass ein Name wie „Wohnung 1.OG · 2023" seinen unterscheidenden
  // Teil (das Jahr) behaelt, schmal genug, dass die Balken Platz haben (<=52 %).
  // Vorher stand die Spalte fest auf 28 % — auf dem iPhone verlor „Wohnung
  // 1.OG …" so genau das Jahr, an dem die Zeilen sich unterscheiden. Eine
  // ausdruecklich uebergebene labelBreite hat weiterhin Vorrang.
  const noetig = Math.max(...eintraege.map(d => (d.name || '').length))
                 * zeichenBreite + luft;
  const spalte = labelBreite != null ? labelBreite
    : Math.round(Math.min(breite * 0.52, Math.max(breite * 0.28, noetig)));
  const bahn = breite - spalte - 74;
  const h = eintraege.length * (hoehe + luecke);
  const maxZeichen = Math.max(6, Math.floor((spalte - luft) / zeichenBreite));
  const kurz = n => n.length > maxZeichen ? n.slice(0, maxZeichen - 1) + '…' : n;

  const zeilen = eintraege.map((d, i) => {
    const y = i * (hoehe + luecke);
    const w = Math.max(3, (d.wert / max) * bahn);
    return `
      <text x="0" y="${y + hoehe / 2 + 4}" class="lbl">${kurz(d.name)}<title>${
        d.name}</title></text>
      <rect x="${spalte}" y="${y}" width="${w}" height="${hoehe}"
            rx="7" fill="${d.farbe || farbe(i)}"/>
      <text x="${spalte + w + 8}" y="${y + hoehe / 2 + 4}" class="val">${d.text}</text>`;
  }).join('');

  return `<svg viewBox="0 0 ${breite} ${h}" class="chart" role="img">
      <style>
        .lbl{font:500 12px var(--body);fill:var(--soft)}
        .val{font:600 12px var(--mono);fill:var(--ink)}
      </style>${zeilen}
    </svg>`;
}

/** Ein langer kanonischer Titel wie „(Lauf am Holz) Klausner Winkel 12" passt
 *  nicht unter eine schmale Saeule. Statt ihn hart abzuschneiden — wobei genau
 *  der unterscheidende Strassenteil verlorenging und nur „(Lauf am Ho…" blieb —
 *  wird er in zwei Zeilen geteilt: Ortsteil (Klammer) oben, Strasse unten, jede
 *  fuer sich gekuerzt. Namen ohne Klammer bleiben einzeilig. */
function saeulenLabel(name, maxZeichen) {
  const kurz = t => t.length > maxZeichen ? t.slice(0, maxZeichen - 1) + '…' : t;
  const m = /^\(([^)]+)\)\s*(.+)$/.exec((name || '').trim());
  return m ? [kurz(m[1]), kurz(m[2])] : [kurz((name || '').trim())];
}

/** Gruppierte Saeulen je Objekt: Einnahmen gegen Ausgaben. */
export function saeulen(gruppen, { breite = 380, hoehe = 170 } = {}) {
  if (!gruppen.length) return leer('Keine Objekte');
  // Alles null: leere Achsen sind nutzlos, ein Hinweis ist ehrlicher.
  if (!gruppen.some(g => g.a > 0 || g.b > 0))
    return leer('Noch keine Einnahmen oder Ausgaben erfasst');

  const max = Math.max(1, ...gruppen.flatMap(g => [g.a, g.b]));
  const proGruppe = breite / gruppen.length;
  const bw = Math.min(26, proGruppe / 3.2);
  // Wie viele Zeichen je Zeile in eine Spalte passen (10.5 px Inter, ~6 Einheiten
  // je Zeichen mit Sicherheitsabstand, damit Nachbarlabels sich nicht beruehren).
  const maxZeichen = Math.max(5, Math.floor(proGruppe / 6));
  const labels = gruppen.map(g => saeulenLabel(g.name, maxZeichen));
  const zweizeilig = labels.some(l => l.length > 1);
  // Zweizeilige Labels brauchen unten mehr Platz — sonst schneidet der
  // viewBox-Rand die zweite Zeile ab.
  const padUnten = zweizeilig ? 48 : 34, padOben = 6;
  const nutz = hoehe - padUnten - padOben;

  const inhalt = gruppen.map((g, i) => {
    const mitte = i * proGruppe + proGruppe / 2;
    const ha = (g.a / max) * nutz, hb = (g.b / max) * nutz;
    const [z1, z2] = labels[i];
    const beschriftung = z2
      ? `<text x="${mitte}" y="${hoehe - 21}" class="ax">${z1}<title>${g.name}</title></text>
         <text x="${mitte}" y="${hoehe - 8}" class="ax">${z2}</text>`
      : `<text x="${mitte}" y="${hoehe - 16}" class="ax">${z1}<title>${g.name}</title></text>`;
    return `
      <rect x="${mitte - bw - 3}" y="${padOben + nutz - ha}" width="${bw}" height="${ha}"
            rx="5" fill="#2E7D4F"/>
      <rect x="${mitte + 3}" y="${padOben + nutz - hb}" width="${bw}" height="${hb}"
            rx="5" fill="#B24229"/>
      ${beschriftung}`;
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
    // N82 — Farbe nur LINKS (Kostenart → Sammelknoten): dort sagt sie, welche
    // Kostenart fließt. Bänder in die rechte Spalte (Sammelknoten → Einheit)
    // bleiben neutral grau: sonst sähe es aus, als ginge „Heizung" gezielt in
    // eine bestimmte Wohnung — verteilt wird aber die ganze Abrechnung.
    const nachRechts = lage.get(f.nach).spalte === spalten[spalten.length - 1];
    const bandFarbe = nachRechts ? '#8A989D'
      : knotenFarbe(lage.get(f.von).spalte === spalten[0] ? f.von : f.nach);
    return `<path d="${d}" fill="${bandFarbe}" fill-opacity="${nachRechts ? '.26' : '.3'}"><title>${
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

  // N82 — die rechte Spalte (Einheiten) trägt Grau-Abstufungen statt der
  // Kostenart-Farben: gleiche Farbe links/rechts würde sonst eine Beziehung
  // suggerieren („Heizung" ↔ „Wohnung 1.OG"), die es nicht gibt. Die Bänder
  // behalten die Kostenart-Farbe (Quelle), so bleibt die Herkunft ablesbar.
  const GRAU = ['#4A575C', '#5C6B70', '#728287', '#8A989D', '#A2AEB2', '#BAC4C7'];
  const rechteIds = [...lage.entries()]
    .filter(([, l]) => l.spalte === spalten[spalten.length - 1]).map(([i]) => i);
  const grauFuer = i => GRAU[Math.max(0, rechteIds.indexOf(i)) % GRAU.length];

  const kaesten = [...lage.entries()].map(([i, l]) => {
    const rechts = l.spalte === spalten[spalten.length - 1];
    const mittig = !rechts && l.spalte !== spalten[0];

    // Mittelspalten beschriften wir ueber dem Kasten — seitlich wuerde die
    // Schrift in die Beschriftung der Nachbarspalte laufen.
    if (mittig) {
      const ly = einzelneMitte.has(l.spalte) ? -obenPlatz + 15 : l.y - 14;
      // N82 — der Sammelknoten in der Mitte ist neutral (dunkel), nicht teal:
      // er ist die Summe, keine eigene Kostenart.
      return `<rect x="${l.x}" y="${l.y}" width="${knotenBreite}" height="${l.h}"
                    rx="3" fill="${ROLLENFARBE[knoten[i].rolle] || '#16262C'}"/>
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
                  rx="3" fill="${rechts ? grauFuer(i) : knotenFarbe(i)}"/>
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

  const padR = hatQm ? 34 : 6;
  const n = punkte.length;
  // N229 — lange kanonische Namen ("(Eschenau) Tauchersreuther Str. 5")
  // passen nicht einzeilig unter eine schmale Säule und überlappten sich.
  // Derselbe Zweizeiler wie bei `saeulen()`: Ortsteil oben, Strasse unten,
  // je nach verfügbarer Spaltenbreite gekürzt.
  const padL = 6;
  const nutzB = breite - padL - padR;
  const step = nutzB / n;
  const maxZeichen = Math.max(5, Math.floor(step / 6));
  const labels = punkte.map(p => saeulenLabel(p.label, maxZeichen));
  const zweizeilig = labels.some(l => l.length > 1);
  const padOben = 16, padUnten = zweizeilig ? 44 : 30;
  const nutzH = hoehe - padOben - padUnten;
  const baseY = padOben + nutzH;
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

  // Bei vielen Punkten wird jeder n-te ausgelassen — sonst drängen sich auch
  // gekürzte Labels noch zusammen (Mietverlauf über viele Monate/Jahre).
  const schritt = Math.max(1, Math.ceil(n / 8));
  const achse = punkte.map((p, i) => {
    if (i % schritt !== 0) return '';
    const [z1, z2] = labels[i];
    return z2
      ? `<text x="${runden(cx(i))}" y="${hoehe - 17}" class="ax">${z1}<title>${
          p.label}</title></text>
         <text x="${runden(cx(i))}" y="${hoehe - 6}" class="ax">${z2}</text>`
      : `<text x="${runden(cx(i))}" y="${hoehe - 9}" class="ax">${z1}<title>${
          p.label}</title></text>`;
  }).join('');

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

const euroKurz = v => `${Math.round(v).toLocaleString('de-DE')} €`;

/** Schriftgroesse, die einen Text in eine gegebene Breite quetscht — gleiches
 *  Prinzip wie die Spaltenrechnung in `balken()`, nur umgekehrt: dort steht
 *  die Breite fest und der Text wird gekuerzt, hier steht der Text fest
 *  (eine Summe soll nicht abgeschnitten werden) und die Schrift schrumpft. */
const passendeSchrift = (text, verfuegbar, { max = 22, min = 9, breiteJeZeichen = 0.58 } = {}) =>
  !text ? 0 : Math.max(min, Math.min(max, verfuegbar / (text.length * breiteJeZeichen)));

/** Donut/Ring — z. B. Kostenanteile je Gewerk.
 *
 *  Ring aus stroke-dasharray auf konzentrischen <circle>-Elementen statt aus
 *  <path>-Kreisboegen: bei einem einzigen Segment (Anteil 100 %) haben Start-
 *  und Endpunkt eines Bogens denselben Punkt, der Bogen hat also keine
 *  wohldefinierte Richtung mehr und kollabiert je nach Renderer zu einem
 *  0°-Schlitz — der klassische Arc-Fehler. Ein Kreis, dessen Dash-Laenge dem
 *  Umfang entspricht, hat dieses Problem nicht: er malt immer einmal
 *  komplett herum, unabhaengig vom Anteil.
 *
 *  `teile`: [{ name, wert, farbe? }], bereits absteigend sortiert erwartet
 *  (bestimmt nur die Zeichenreihenfolge/Farbzuordnung, nicht die Berechnung). */
export function donut(teile, { groesse = 220, dicke = 34, mitte = '',
                               mitteSub = '', format = euroKurz } = {}) {
  const eintraege = (teile || []).filter(t => t.wert > 0);
  if (!eintraege.length) return leer('Keine Werte für diesen Zeitraum');

  const gesamt = eintraege.reduce((s, t) => s + t.wert, 0);
  const mittelpunkt = groesse / 2;
  const radius = (groesse - dicke) / 2;
  const umfang = 2 * Math.PI * radius;

  let bisher = 0;
  const ring = eintraege.map((t, i) => {
    const laenge = (t.wert / gesamt) * umfang;
    // Luecke nie exakt 0 — sonst rundet mancher Renderer den Dash/Gap-
    // Uebergang am Segmentende sichtbar an (feiner Spalt im Ring).
    const luecke = Math.max(umfang - laenge, 0.001);
    const versatz = -bisher;
    bisher += laenge;
    return `<circle cx="${mittelpunkt}" cy="${mittelpunkt}" r="${runden(radius)}"
              fill="none" stroke="${t.farbe || farbe(i)}" stroke-width="${dicke}"
              stroke-dasharray="${runden(laenge)} ${runden(luecke)}"
              stroke-dashoffset="${runden(versatz)}"
              ><title>${t.name}: ${format(t.wert)}</title></circle>`;
  }).join('');

  // Lochdurchmesser = groesse - 2×dicke. Beide Mitte-Zeilen muessen mit Luft
  // zum Ring hineinpassen — die Schrift schrumpft dafuer statt zu ueberlaufen.
  const lochDurchmesser = groesse - dicke * 2;
  const verfuegbar = Math.max(0, lochDurchmesser * 0.82);
  const schriftMitte = passendeSchrift(mitte, verfuegbar, { max: 22, min: 10, breiteJeZeichen: 0.6 });
  const schriftSub = passendeSchrift(mitteSub, verfuegbar, { max: 12, min: 8, breiteJeZeichen: 0.56 });

  let mitteHtml = '';
  if (mitte && mitteSub) {
    mitteHtml = `
      <text x="${mittelpunkt}" y="${mittelpunkt - schriftMitte * 0.32}" class="dm"
            style="font-size:${runden(schriftMitte)}px">${mitte}</text>
      <text x="${mittelpunkt}" y="${mittelpunkt + schriftSub + 2}" class="ds"
            style="font-size:${runden(schriftSub)}px">${mitteSub}</text>`;
  } else if (mitte) {
    mitteHtml = `<text x="${mittelpunkt}" y="${mittelpunkt}" class="dm"
                   style="font-size:${runden(schriftMitte)}px">${mitte}</text>`;
  } else if (mitteSub) {
    mitteHtml = `<text x="${mittelpunkt}" y="${mittelpunkt}" class="ds"
                   style="font-size:${runden(schriftSub)}px">${mitteSub}</text>`;
  }

  // Der Ring bekommt eine Hoechstbreite. Die uebrigen Diagramme duerfen mit
  // der Spalte wachsen — bei einem Balken bringt Breite Ablesbarkeit. Ein
  // Donut gewinnt dadurch nichts: auf dem iPad fuellte er sonst 560 px Hoehe
  // fuer eine einzige Zahl in der Mitte.
  return `<svg viewBox="0 0 ${groesse} ${groesse}" class="chart chart-donut"
      role="img" style="max-width:${groesse}px;display:block;margin:0 auto">
      <style>
        .dm{font:700 16px var(--disp);fill:var(--ink);text-anchor:middle;dominant-baseline:middle}
        .ds{font:500 11px var(--body);fill:var(--soft);text-anchor:middle;dominant-baseline:middle}
      </style>
      <g transform="rotate(-90 ${mittelpunkt} ${mittelpunkt})">${ring}</g>
      ${mitteHtml}
    </svg>`;
}

const MONATSKURZ = ['Jan', 'Feb', 'Mrz', 'Apr', 'Mai', 'Jun',
                     'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dez'];
const pad2 = n => String(n).padStart(2, '0');
const datumMs = s => { const [j, m, t] = s.split('-').map(Number); return Date.UTC(j, m - 1, t); };
const datumVoll = ms => { const d = new Date(ms);
  return `${pad2(d.getUTCDate())}.${pad2(d.getUTCMonth() + 1)}.${d.getUTCFullYear()}`; };

/** Zeitstrahl — Rechnungen einer Renovierung ueber die Zeit, Punktflaeche
 *  proportional zum Betrag. Bewusst Flaeche statt Radius: waechst der Radius
 *  linear mit dem Betrag, wirkt ein doppelt so teurer Posten viermal so
 *  gross (Flaeche waechst quadratisch mit dem Radius) — optisch eine Luege
 *  ueber die Groessenordnung. Bei Flaechen-Proportionalitaet stimmt der
 *  visuelle Eindruck mit dem Zahlenverhaeltnis ueberein.
 *
 *  `punkte`: [{ datum: 'YYYY-MM-DD', wert, name, firma }, …]
 *  `von`/`bis`: 'YYYY-MM-DD', Zeitraum der Renovierung — fehlen sie, wird er
 *  aus den Punkten abgeleitet. */
export function zeitstrahl(punkte, { breite = 380, hoehe = 190,
                                     von = '', bis = '' } = {}) {
  const eintraege = (punkte || []).filter(p => p.datum && p.wert > 0);
  if (!eintraege.length) return leer('Keine Rechnungen für diesen Zeitraum');

  const zeiten = eintraege.map(p => datumMs(p.datum));
  const vonMs = von ? datumMs(von) : Math.min(...zeiten);
  const bisMs = bis ? datumMs(bis) : Math.max(...zeiten);
  const spanne = Math.max(0, bisMs - vonMs);

  const minR = 4, maxR = 13;
  const werte = eintraege.map(p => p.wert);
  const wertMin = Math.min(...werte), wertMax = Math.max(...werte);
  const flaeche = v => wertMax === wertMin ? (Math.PI * minR * minR + Math.PI * maxR * maxR) / 2
    : Math.PI * minR * minR + (v - wertMin) / (wertMax - wertMin)
      * (Math.PI * maxR * maxR - Math.PI * minR * minR);
  const radiusVon = v => Math.sqrt(flaeche(v) / Math.PI);

  const padL = maxR + 8, padR = maxR + 8;
  const padOben = 26, achsenY = hoehe - 24, tickY = hoehe - 8;
  const nutzB = breite - padL - padR;
  const centerY = (padOben + (achsenY - 16)) / 2;
  const x = ms => spanne === 0 ? padL + nutzB / 2 : padL + ((ms - vonMs) / spanne) * nutzB;

  // Nahe beieinanderliegende Punkte (bis hin zu „alle am selben Tag") faechern
  // sich senkrecht um die Mittellinie auf, statt sich deckungsgleich zu
  // ueberlagern — sortiert nach Zeit, dann nach x-Naehe gruppiert.
  const roh = eintraege.map((p, i) => ({ p, i, ms: zeiten[i], cx: x(zeiten[i]), r: radiusVon(p.wert) }))
    .sort((a, b) => a.cx - b.cx || a.ms - b.ms);
  // Verglichen wird mit dem ANFANG der Gruppe, nicht mit ihrem letzten Punkt.
  // Andernfalls haengt sich jeder Punkt an seinen knapp benachbarten Vorgaenger
  // und die ganze Reihe wird zu EINER Kette: bei 40 Rechnungen auf 338 px
  // liegen die Punkte rund 8 px auseinander, also unter der Schwelle — sie
  // landeten alle in einer Gruppe und wanderten als Diagonale nach unten aus
  // dem Diagramm heraus, statt der Zeitachse zu folgen.
  const naehe = Math.max(minR * 2, 9);
  const gruppen = [];
  for (const punkt of roh) {
    const letzte = gruppen[gruppen.length - 1];
    if (letzte && punkt.cx - letzte[0].cx < naehe) letzte.push(punkt);
    else gruppen.push([punkt]);
  }
  // Die Faecherung bleibt im Diagramm: passt eine Gruppe mit dem Wunschabstand
  // nicht mehr zwischen Oberkante und Achse, ruecken ihre Punkte enger
  // zusammen, statt oben und unten hinauszulaufen.
  const halbeHoehe = Math.max(0, (achsenY - 16 - padOben) / 2 - maxR);
  for (const gruppe of gruppen) {
    const spannweite = gruppe.length - 1;
    const abstand = spannweite === 0 ? 0
      : Math.min(15, (halbeHoehe * 2) / spannweite);
    gruppe.forEach((punkt, k) => {
      punkt.cy = centerY + (k - spannweite / 2) * abstand;
    });
  }

  const punkteHtml = roh.map(({ p, cx, cy, r }) =>
    `<circle cx="${runden(cx)}" cy="${runden(cy)}" r="${runden(r)}"
             fill="${farbe(0)}" fill-opacity=".82" stroke="var(--sheet)" stroke-width="1.4"
             ><title>${datumVoll(datumMs(p.datum))} · ${p.firma || ''}${p.firma && p.name ? ' · ' : ''}${
             p.name || ''} · ${euroKurz(p.wert)}</title></circle>`).join('');

  // Beschriftung: abwechselnd oben/unten, aber nur wenn zur letzten
  // Beschriftung auf DERSELBEN Seite genug Abstand ist — sonst lieber
  // auslassen als Buchstabensalat uebereinander zu schreiben. Innerhalb
  // einer gefaecherten Gruppe (siehe oben) traegt zusaetzlich nur der
  // groesste Posten ein Label: sonst kreuzen sich die Zeilen der uebrigen
  // Gruppenmitglieder, weil deren Fluchtpunkt (cy) senkrecht versetzt ist,
  // ihr Label-Text aber trotzdem auf gleicher Zeile mit dem Nachbarpunkt
  // landen kann.
  const beschriftbar = new Set(
    gruppen.map(g => g.reduce((a, b) => a.p.wert >= b.p.wert ? a : b)));
  // Gemessen wird die RECHTE KANTE der zuletzt gesetzten Beschriftung, nicht
  // ihr Mittelpunkt: ein fester Mindestabstand reichte nicht, weil die Namen
  // verschieden breit sind — „Fenster & T…" ist doppelt so breit wie
  // „Elektro", und so schrieben sich „Sonstiges" und „Fliesen" ineinander.
  // 5 Einheiten je Zeichen bei 9.5 px var(--body), grosszuegig gerechnet.
  const zeichenBreite = 5;
  const textLuft = 7;
  const letzteRechts = { oben: -Infinity, unten: -Infinity };
  let seitenZaehler = 0;
  const beschriftungHtml = roh.filter(pt => beschriftbar.has(pt)).map(({ p, cx, cy, r }) => {
    // Bei einer gefaecherten Gruppe zeigt das Label vom Zentrum weg, in die
    // Richtung, in die der Punkt ohnehin schon versetzt ist — sonst zeigt es
    // haeufig genau auf einen benachbarten, ebenfalls versetzten Punkt.
    // Nur bei exakt zentrierten Punkten (kein Versatz) wechselt es reihum.
    const seite = cy < centerY - 0.5 ? 'oben' : cy > centerY + 0.5 ? 'unten'
      : (seitenZaehler++ % 2 === 0 ? 'oben' : 'unten');
    const name = (p.name || '').length > 12 ? p.name.slice(0, 11) + '…' : (p.name || '');
    if (!name) return '';
    const anker = cx < padL + 24 ? 'start' : cx > breite - padR - 24 ? 'end' : 'middle';
    const textB = name.length * zeichenBreite;
    const links = anker === 'start' ? cx : anker === 'end' ? cx - textB : cx - textB / 2;
    // Ueberlappt die Beschriftung ihre linke Nachbarin, wird sie ausgelassen —
    // eine fehlende Beschriftung ist lesbar, zwei uebereinander sind es nicht.
    if (links - letzteRechts[seite] < textLuft) return '';
    letzteRechts[seite] = links + textB;
    const ly = seite === 'oben' ? cy - r - 6 : cy + r + 13;
    return `<text x="${runden(cx)}" y="${runden(ly)}" class="zl" text-anchor="${anker}">${name}</text>`;
  }).join('');

  // Anzahl und Format der Datumsmarken richten sich nach der verfuegbaren
  // Breite bzw. der Zeitspanne — auf dem iPhone 3 grobe Marken, auf dem
  // Desktop 5–6 feinere; unter drei Monaten reicht Tag.Monat, ueber einem
  // Jahr reicht Monat + Jahr (sonst waeren die Marken laenger als ihr Abstand).
  const tageSpanne = spanne / 86400000;
  const format = tageSpanne > 365
    ? ms => { const d = new Date(ms); return `${MONATSKURZ[d.getUTCMonth()]} ${String(d.getUTCFullYear()).slice(2)}`; }
    : tageSpanne < 90
    ? ms => { const d = new Date(ms); return `${pad2(d.getUTCDate())}.${pad2(d.getUTCMonth() + 1)}.`; }
    : ms => { const d = new Date(ms); return `${pad2(d.getUTCDate())}. ${MONATSKURZ[d.getUTCMonth()]}`; };
  const anzahl = spanne === 0 ? 1 : breite < 420 ? 3 : breite < 900 ? 5 : 6;
  const marken = Array.from({ length: anzahl }, (_, i) => {
    const ms = anzahl === 1 ? vonMs : vonMs + (i / (anzahl - 1)) * spanne;
    const mx = x(ms);
    // Erste/letzte Marke duerfen nicht ueber den Rand hinausragen: start/end
    // statt middle, sonst haengt die Haelfte des Textes ins Leere.
    const anker = anzahl === 1 ? 'middle' : i === 0 ? 'start' : i === anzahl - 1 ? 'end' : 'middle';
    return `<text x="${runden(mx)}" y="${tickY}" class="ax" text-anchor="${anker}">${format(ms)}</text>`;
  }).join('');

  return `<svg viewBox="0 0 ${breite} ${hoehe}" class="chart" role="img">
      <style>
        .ax{font:500 10px var(--mono);fill:var(--soft)}
        .zl{font:500 9.5px var(--body);fill:var(--soft)}
      </style>
      <line x1="${padL}" y1="${achsenY}" x2="${breite - padR}" y2="${achsenY}"
            stroke="#D6DCDD" stroke-width="1"/>
      ${punkteHtml}${beschriftungHtml}${marken}
    </svg>`;
}
