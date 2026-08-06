/* N127 — der Amortisationsverlauf: Grafik, Legende, KPIs und Jahrestabelle.

   Die Grafik zeigt nicht die Ertraege nach oben, sondern die Anschaffung als
   negativen Betrag, der Jahr fuer Jahr aufgefressen wird. Je Jahr eine
   Saeule: der noch offene Rest haengt in Rot unter der Nulllinie, und was
   ihn in diesem Jahr kleiner gemacht hat, sitzt als Ertragsblock darunter —
   Direktnutzung voll, Einspeiseverguetung schraffiert (bleibt auch ohne
   Farbe lesbar), E-Tanken und der einmalige Vorlauf in eigenen Toenen.
   Durchstoeszt die Saeule die Nulllinie, ist die Anlage amortisiert und der
   Ueberschuss steht in Gruen darueber. Prognosejahre sind blass und
   gestrichelt umrandet, damit auf einen Blick klar ist, was gemessen und
   was gerechnet ist.

   Alles Inline-SVG von Hand — es gibt in diesem Projekt keine Chart-
   Bibliothek. Umzug ohne Verhaltensaenderung. */
import { api, esc, eur } from '../immo.js';
import { S } from './state.js';
import { eur0, negativ } from './helpers.js';
import { C_DIREKT, C_EINSP, C_TANK, C_VOR, C_OFFEN, C_PLUS } from './farben.js';
import { pvAnschaffungSetzen } from './eigentuemer.js';
import { kringel, katAnteil } from './kringel.js';

/* Die Ertragsquellen einer Saeule, von unten nach oben gestapelt. */
const V_QUELLEN = [
  ['pv_strom', C_DIREKT],
  ['einspeisung', 'url(#pvSchraffur)'],
  ['tanken', C_TANK],
];

/* Die Bloecke einer Saeule: erst der Vorlauf, dann das Jahr selbst.
   N153 — ist die Herkunft des Vorlaufs gepflegt (`vorlauf_teile`), wird er
   nach DENSELBEN Quellen aufgeteilt wie die Jahre danach, in denselben
   Farben und derselben Schraffur. Sonst bleibt er ein Block in seinem
   eigenen Ton. */
function saeulenBloecke(z) {
  const t = z.vorlauf_teile;
  const quellen = daten => V_QUELLEN.map(([feld, fuellung]) =>
    [daten[feld] || 0, fuellung]);
  return [t ? quellen(t) : [[z.vorlauf || 0, C_VOR]], quellen(z)];
}

const bloeckeSumme = liste => liste.reduce((s, [wert]) => s + wert, 0);

function verlaufGrafik(v) {
  const prog = (v.prognose && v.prognose.jahre) || [];
  const reihe = [
    ...v.jahre.map(z => ({ ...z, geschaetzt: false })),
    ...prog.map(z => ({ ...z, vorlauf: 0, pv_strom: 0, einspeisung: 0,
                        tanken: 0, geschaetzt: true })),
  ];
  const ansch = v.anschaffung;
  if (!reihe.length || !ansch) return '';

  const B = 380, H = 238;
  // Die Achsenspalte waechst mit der Beschriftung: „−36.000 €" braucht mehr
  // Platz als „−900 €" — sonst haengt die Zahl links aus der Zeichnung
  // heraus.
  const bodenText = negativ(eur0(-ansch));
  const achse = Math.max(46, Math.round(12 + bodenText.length * 5.8));
  const xl = achse, xr = B - 6, yo = 16, yu = H - 44;
  // Der „Stand" ist kumulierter Ertrag minus Anschaffung: er startet bei
  // −Anschaffung und wandert nach oben durch die Null.
  const stand = z => (z.kumuliert || 0) - ansch;
  const maxPlus = Math.max(...reihe.map(stand), ansch * 0.09);
  const spanne = ansch + maxPlus;
  const y = w => yu - ((w + ansch) / spanne) * (yu - yo);
  const yNull = y(0);
  const slot = (xr - xl) / reihe.length;
  const bw = Math.max(3, Math.min(42, slot * 0.62));
  const rx = Math.min(4, bw / 3).toFixed(1);
  const jederNte = Math.ceil(reihe.length / 9);

  let clips = '', saeulen = '', jahrLabels = '', vorher = -ansch;
  let letztesLabel = -Infinity;
  reihe.forEach((z, i) => {
    const x = xl + slot * i + (slot - bw) / 2;
    const nachher = stand(z);
    const yV = y(vorher), yN = y(nachher);        // yV liegt tiefer als yN
    const oben = Math.min(yN, yNull), unten = Math.max(yV, yNull);
    const blass = z.geschaetzt ? ' opacity=".24"' : '';
    let inhalt = '';
    // Noch offener Rest — haengt unter der Nulllinie.
    if (nachher < 0 && yN - yNull > 0.3) {
      inhalt += `<rect x="${x}" y="${yNull.toFixed(1)}" width="${bw}"
        height="${(yN - yNull).toFixed(1)}" fill="${C_OFFEN}"${blass}/>`;
    }
    // Ueberschuss aus den Vorjahren — steht ueber der Nulllinie.
    if (vorher > 0 && yNull - yV > 0.3) {
      inhalt += `<rect x="${x}" y="${yV.toFixed(1)}" width="${bw}"
        height="${(yNull - yV).toFixed(1)}" fill="${C_PLUS}"${blass}/>`;
    }
    // Was dieses Jahr eingebracht hat — der Bissen aus dem Balken.
    const block = yV - yN;
    if (block > 0.3) {
      if (z.geschaetzt) {
        inhalt += `<rect x="${x + .75}" y="${(yN + .75).toFixed(1)}"
          width="${Math.max(1, bw - 1.5)}" height="${Math.max(1, block - 1.5).toFixed(1)}"
          fill="${C_PLUS}" fill-opacity=".16" stroke="${C_OFFEN}"
          stroke-opacity=".5" stroke-width="1.2" stroke-dasharray="3 2.5"/>`;
      } else {
        const [vorBloecke, jahrBloecke] = saeulenBloecke(z);
        let boden = yV;
        const stapeln = ([wert, fuellung]) => {
          const h = z.summe > 0 ? block * (wert / z.summe) : 0;
          if (h < 0.3) return;
          boden -= h;
          inhalt += `<rect x="${x}" y="${boden.toFixed(1)}" width="${bw}"
            height="${h.toFixed(1)}" fill="${fuellung}"/>`;
        };
        vorBloecke.forEach(stapeln);
        const vorlaufKante = boden;       // Oberkante des Vorlaufs
        jahrBloecke.forEach(stapeln);
        // Ist der Vorlauf nach denselben Quellen aufgeteilt, haetten seine
        // Bloecke dieselbe Farbe wie die des Jahres — ein Haarstrich sagt,
        // wo der Vorsprung endet und das erste Abrechnungsjahr anfaengt.
        if (z.vorlauf_teile && bloeckeSumme(vorBloecke) > 0
            && bloeckeSumme(jahrBloecke) > 0 && yV - vorlaufKante > 1.5) {
          inhalt += `<line x1="${x}" y1="${vorlaufKante.toFixed(1)}"
            x2="${(x + bw).toFixed(1)}" y2="${vorlaufKante.toFixed(1)}" stroke="#FFF"
            stroke-opacity=".85" stroke-width="1.2"/>`;
        }
      }
    }
    clips += `<clipPath id="pvc${i}"><rect x="${x}" y="${oben.toFixed(1)}"
      width="${bw}" height="${Math.max(.5, unten - oben).toFixed(1)}"
      rx="${rx}"/></clipPath>`;
    saeulen += `<g clip-path="url(#pvc${i})">${inhalt}</g>`;
    // Jede n-te Jahreszahl, dazu die letzte — aber nur, wenn sie der
    // vorigen nicht auf die Pelle rueckt.
    const letzte = i === reihe.length - 1;
    if ((i % jederNte === 0 || letzte) && i - letztesLabel >= jederNte) {
      letztesLabel = i;
      jahrLabels += `<text x="${(x + bw / 2).toFixed(1)}" y="${yu + 17}"
        class="ax${z.geschaetzt ? ' blass' : ''}">${z.jahr}</text>`;
    }
    vorher = nachher;
  });

  // Trennstrich zwischen Erfasstem und Prognose.
  const grenze = prog.length ? `<line x1="${(xl + slot * v.jahre.length).toFixed(1)}"
    y1="${yo}" x2="${(xl + slot * v.jahre.length).toFixed(1)}" y2="${yu + 4}"
    stroke="#5C6B70" stroke-opacity=".35" stroke-width="1" stroke-dasharray="3 3"/>` : '';

  return `<svg viewBox="0 0 ${B} ${H}" class="chart" role="img"
      aria-label="Amortisationsverlauf der PV-Anlage">
    <defs>
      <pattern id="pvSchraffur" width="6" height="6" patternUnits="userSpaceOnUse"
               patternTransform="rotate(45)">
        <rect width="6" height="6" fill="${C_EINSP}"/>
        <line x1="0" y1="0" x2="0" y2="6" stroke="#FFF" stroke-width="2.4"
              stroke-opacity=".8"/>
      </pattern>
      ${clips}
    </defs>
    <style>
      .ax{font:500 10px var(--body);fill:var(--soft);text-anchor:middle}
      .ax.blass{fill-opacity:.6}
      .ay{font:500 9.5px var(--mono);fill:var(--soft);text-anchor:end}
    </style>
    <line x1="${xl}" y1="${yu}" x2="${xr}" y2="${yu}" stroke="${C_OFFEN}"
          stroke-opacity=".35" stroke-width="1" stroke-dasharray="4 3"/>
    ${grenze}
    ${saeulen}
    ${jahrLabels}
    <line x1="${achse - 4}" y1="${yNull.toFixed(1)}" x2="${xr}"
          y2="${yNull.toFixed(1)}" stroke="#16262C" stroke-width="1.2"/>
    <text x="${achse - 8}" y="${(yNull - 4).toFixed(1)}" class="ay">0 €</text>
    <text x="${achse - 8}" y="${yu + 4}" class="ay">${bodenText}</text>
  </svg>`;
}

/* Nur zeigen, was in der Zeichnung auch vorkommt — eine Legende mit Farben
   ohne Balken waere eine Behauptung. */
function verlaufLegende(v) {
  // N153 — der aufgeschluesselte Vorlauf zaehlt fuer die Legende wie ein
  // Jahr: er erscheint in denselben Farben und braucht deshalb dieselben
  // Eintraege.
  const teile = v.vorlauf_teile || {};
  const hat = feld => v.jahre.some(z => (z[feld] || 0) > 0)
    || (teile[feld] || 0) > 0;
  const eintraege = [
    [hat('pv_strom'), `style="background:${C_DIREKT}"`, 'Direktnutzung'],
    [hat('einspeisung'), 'class="schraffur"', 'Einspeisevergütung'],
    [hat('tanken'), `style="background:${C_TANK}"`, 'E-Tanken'],
    [(v.vorlauf || 0) > 0 && !v.vorlauf_aufgeschluesselt,
     `style="background:${C_VOR}"`, 'Vorlauf — Herkunft nicht aufgeschlüsselt'],
    [hat('offen'), `style="background:${C_OFFEN}"`, 'noch offen'],
    [hat('ueberschuss'), `style="background:${C_PLUS}"`, 'amortisiert'],
    [!!v.prognose, 'class="prognose"', 'Prognose'],
  ].filter(([zeigen]) => zeigen);
  // Der Vorlaufbalken steht in denselben Farben da wie die Abrechnungsjahre
  // — ohne einen Satz dazu waere nicht zu sehen, dass er aus der Zeit
  // davor kommt.
  const note = (v.vorlauf || 0) > 0 && v.vorlauf_jahr != null
    ? `<p class="legendennote">Der Balken ${v.vorlauf_jahr} ist der Vorlauf
       (${eur(v.vorlauf)}): die Zeit vor der ersten Abrechnung${
        v.vorlauf_aufgeschluesselt
          ? ', nach denselben Quellen aufgeteilt wie die Jahre danach'
          : ' — die Herkunft ist dort nicht aufgeschlüsselt'}.</p>` : '';
  return `<div class="legende">${eintraege.map(([, attr, text]) =>
    `<span><i ${attr}></i>${text}</span>`).join('')}</div>${note}`;
}

function verlaufTabelle(v) {
  // N174 — keine eigene Vorlauf-Spalte mehr. Der Vorlauf des ersten Jahres
  // wird in dieselben Quellenspalten aufgeschluesselt wie die Jahre danach:
  // sein PV-Strom-Anteil in die PV-Strom-Spalte, seine Einspeisung in die
  // Einspeisung-Spalte, sein E-Tanken in die E-Tanken-Spalte. Ist er nur
  // als Gesamtbetrag gepflegt, steht er in PV-Strom mit dem Hinweis, dass
  // er nicht aufgeschluesselt ist — statt eine Spalte wieder einzufuehren.
  const kopf = ['Jahr', 'PV-Strom', 'Einspeisung', 'E-Tanken',
                'Summe', 'kumuliert', 'noch offen'];
  const roherVorlauf = z => z.jahr === v.vorlauf_jahr && (z.vorlauf || 0) > 0
    && !z.vorlauf_teile;
  const zelle = (z, feld) => {
    let wert = z[feld] || 0;
    if (z.jahr === v.vorlauf_jahr) {
      if (z.vorlauf_teile) wert += z.vorlauf_teile[feld] || 0;
      else if (feld === 'pv_strom') wert += z.vorlauf || 0;
    }
    return wert;
  };
  const geld = (z, feld) => {
    const w = zelle(z, feld);
    const hinweis = feld === 'pv_strom' && roherVorlauf(z)
      ? '<span class="unauf">nicht aufgeschlüsselt</span>' : '';
    return (w ? eur(w) : '—') + hinweis;
  };
  const summe = feld => v.jahre.reduce((s, z) => s + zelle(z, feld), 0);
  const zeilen = v.jahre.map(z => `<tr>
      <td>${z.jahr}${z.jahr === v.vorlauf_jahr
        ? '<span class="vorab">vor der Abrechnung</span>' : ''}</td>
      <td class="leise">${geld(z, 'pv_strom')}</td>
      <td class="leise">${geld(z, 'einspeisung')}</td>
      <td class="leise">${geld(z, 'tanken')}</td>
      <td class="summe">${eur(z.summe)}</td>
      <td>${eur(z.kumuliert)}</td>
      <td>${z.offen ? eur(z.offen)
        : (z.ueberschuss ? `<span class="plus">+ ${eur(z.ueberschuss)}</span>`
          : eur(0))}</td>
    </tr>`).join('');
  return `<div class="tabrahmen"><table class="jt">
    <thead><tr>${kopf.map(t => `<th>${t}</th>`).join('')}</tr></thead>
    <tbody>${zeilen}</tbody>
    <tfoot><tr>
      <td>Σ</td>
      <td>${eur(summe('pv_strom'))}</td>
      <td>${eur(summe('einspeisung'))}</td>
      <td>${eur(summe('tanken'))}</td>
      <td class="summe">${eur(v.kumuliert)}</td>
      <td>${eur(v.kumuliert)}</td>
      <td>${eur(v.rest)}</td>
    </tr></tfoot>
  </table></div>
  <p class="scrollhinweis">Seitlich wischen für alle Spalten.</p>`;
}

function verlaufKpi(v) {
  // Die Jahreszahl bleibt der grosze Wert; „geschaetzt, noch 25 Jahre" steht
  // als eigene Zeile darunter — sonst sprengt der Zusatz die Kachel.
  const zusatz = v.break_even_geschaetzt
    ? `<span class="knote">geschätzt · noch ${v.break_even_in_jahren} Jahre</span>`
    : `<span class="knote">${v.break_even_jahr ? 'erreicht'
        : 'Prognose ab dem zweiten Ertragsjahr'}</span>`;
  return `
    <div class="k"><span class="kl">Anschaffung</span><span class="kv">${eur(v.anschaffung)}</span></div>
    <div class="k"><span class="kl">Bisher abgetragen</span><span class="kv pos">${eur(v.kumuliert)}</span></div>
    <div class="k"><span class="kl">Noch offen</span><span class="kv">${eur(v.rest)}</span></div>
    <div class="k"><span class="kl">Amortisiert</span><span class="kv">${
      v.amortisiert_prozent == null ? '—'
        : v.amortisiert_prozent.toLocaleString('de-DE', { maximumFractionDigits: 1 }) + ' %'}</span></div>
    <div class="k"><span class="kl">Break-even</span><span class="kv">${
      v.break_even_jahr || '—'}</span>${zusatz}</div>`;
}

export async function verlaufZeigen() {
  const kpi = document.getElementById('vKpi');
  if (!kpi || !S.objektSlug) return;
  const grafik = document.getElementById('vGrafik');
  const tabelle = document.getElementById('vTabelle');
  let v;
  try {
    v = await api(`/objekte/${encodeURIComponent(S.objektSlug)}/pv/verlauf`);
  } catch {
    kpi.innerHTML = '';
    grafik.innerHTML = '<div class="verlaufleer"><p>Der Verlauf ist nach dem '
      + 'nächsten Deploy verfügbar.</p></div>';
    tabelle.innerHTML = '';
    pvAnschaffungSetzen(0);
    return;
  }
  // N204 — die Gesamt-Anschaffung speist die Investitions-€ je
  // Eigentuemerzeile.
  pvAnschaffungSetzen(v.anschaffung || 0);
  const hinweise = (v.warnungen || []).map(t => `<p>${esc(t)}</p>`).join('');
  kpi.innerHTML = v.anschaffung ? verlaufKpi(v) : '';
  if (!v.anschaffung || !v.kumuliert) {
    // Ruhige Aussage statt einer leeren Flaeche.
    grafik.innerHTML = `<div class="verlaufleer">${hinweise
      || '<p>Für diese Anlage ist noch nichts zu zeigen.</p>'}</div>`;
    tabelle.innerHTML = '';
    return;
  }
  // N200 — Kurve und Ringdiagramm nebeneinander, darunter die Prozent-
  // Aufteilung. `kategorien` fehlt vor dem naechsten Deploy — dann bleibt
  // es bei Kurve und Tabelle, ohne Bruch.
  const kat = v.kategorien;
  grafik.innerHTML = `<div class="verlaufkopf">
      <div class="vk-kurve">${verlaufGrafik(v)}${verlaufLegende(v)}</div>
      ${kat ? kringel(kat) : ''}
    </div>`
    + (kat ? katAnteil(kat) : '')
    + (hinweise ? `<div class="verlaufleer">${hinweise}</div>` : '');
  tabelle.innerHTML = verlaufTabelle(v);
  const rahmen = tabelle.querySelector('.tabrahmen');
  const hinweis = tabelle.querySelector('.scrollhinweis');
  if (rahmen && hinweis) {
    hinweis.classList.toggle('zeigen',
      rahmen.scrollWidth - rahmen.clientWidth > 2);
  }
}
