/* Symbole für die 15 Gewerke — ein Raster (24×24), eine Strichstärke,
   alles in currentColor. Damit trägt die Farbe die Bedeutung (Tinte für
   ruhig, Teal für aktiv) und der Satz bleibt so still wie der Rest der
   Oberfläche. Gezeichnet für 20 px: lieber drei Striche, die sitzen, als
   ein Ziegeldach mit zwölf Ziegeln.

   Die Symbole liegen als <symbol>-Sprite im Dokument, weil dasselbe Gewerk
   im Kontaktbuch vielfach vorkommt (je Handwerker eine Reihe von Chips) —
   ein <use> je Chip ist billiger als ein eigener Pfad. */

const P = 'stroke="currentColor" stroke-width="1.7" fill="none" ' +
  'stroke-linecap="round" stroke-linejoin="round"';

/* Die Zeichnungen. Reihenfolge wie in `renovierung.GEWERKE`, damit sich
   Datei und Fachliste nebeneinander lesen lassen. */
const ZEICHNUNGEN = {
  /* Rohbau — Mauerwerk im Verband: zwei Lagerfugen, versetzte Stoßfugen. */
  rohbau: `<rect ${P} x="3.6" y="6.2" width="16.8" height="11.6" rx="1.4"/>
           <path ${P} d="M3.6 10.1h16.8M3.6 13.9h16.8"/>
           <path ${P} d="M12 6.2v3.9M8 10.1v3.8M16 10.1v3.8M12 13.9v3.9"/>`,

  /* Dach — die Dachfläche über der Traufe, zwei kurze Wandstummel darunter.
     Der Überstand und der Schornstein machen aus dem Dreieck ein Dach und
     keinen Berg; ganze Wände machten daraus ein Haus. */
  dach: `<path ${P} d="M3.8 15.2 12 6.2l8.2 9"/>
         <path ${P} d="M2.2 15.2h19.6"/>
         <path ${P} d="M4.8 15.2v3.6M19.2 15.2v3.6"/>
         <path ${P} d="M15.2 9.7V6.6h2.4v4.8"/>`,

  /* Fassade & Dämmung — die Aussenhaut des Hauses, schraffiert wie eine
     Dämmschicht im Schnitt. Als Wandaufbau aus zwei Platten glich das
     Symbol bei 20 px dem Fenster-und-Tür-Paar; die Hauskontur macht den
     Unterschied auf einen Blick. */
  fassade: `<path ${P} d="M3.6 11.4 12 4.8l8.4 6.6v8H3.6z"/>
            <path ${P} d="M7 16.6 11 12.6M11.8 17.2l3.8-3.8"/>`,

  /* Fenster & Türen — links die Tür mit Drücker, rechts das Kreuzfenster. */
  fenster: `<rect ${P} x="3.4" y="4.4" width="7.2" height="15.2" rx="1.3"/>
            <path ${P} d="M8.6 12.4h.01"/>
            <rect ${P} x="13.4" y="7" width="7.2" height="10" rx="1.3"/>
            <path ${P} d="M17 7v10M13.4 12h7.2"/>`,

  /* Elektro — derselbe Blitz wie bei den Stromkosten, damit Strom im
     ganzen Produkt gleich aussieht. */
  elektro: `<path ${P} d="M13.5 3 6 13.5h5L10.5 21 18 10.5h-5L13.5 3Z"/>`,

  /* Sanitär — Waschbecken mit Armatur; der Rand liegt waagrecht, damit die
     Schale auch bei 20 px als Becken und nicht als Napf gelesen wird. */
  sanitaer: `<path ${P} d="M3.4 12.2h17.2"/>
             <path ${P} d="M5.4 12.2v1.8a4.8 4.8 0 0 0 4.8 4.8h3.6a4.8 4.8 0 0 0 4.8-4.8v-1.8"/>
             <path ${P} d="M10.6 12.2V7.6a1.8 1.8 0 0 1 1.8-1.8h2.2a1.8 1.8 0 0 1 1.8 1.8v1.6"/>`,

  /* Heizung — Gliederheizkörper mit aufsteigender Wärme, Zeichnung wie bei
     den Heizkosten: dieselbe Sache, dasselbe Bild. */
  heizung: `<rect ${P} x="4" y="7" width="16" height="12" rx="2"/>
            <path ${P} d="M9 7v12M15 7v12"/>
            <path ${P} d="M8 4.5c0-1 1-1 1-2M12 4.5c0-1 1-1 1-2M16 4.5c0-1 1-1 1-2"/>`,

  /* Trockenbau — die Platte liegt vor dem Ständerwerk: vom Rahmen ist nur
     zu sehen, was sie nicht verdeckt. Der Versatz nach hinten oben macht
     aus zwei Rechtecken eine Wand mit Tiefe. */
  trockenbau: `<path ${P} d="M7.6 8.6V4.4h12.8v12.4h-5.6"/>
               <path ${P} d="M11.8 4.4v4.2M16.4 4.4v12.4"/>
               <rect ${P} x="3.6" y="8.6" width="11.2" height="11" rx="1"/>`,

  /* Estrich & Böden — die Fläche in der Flucht; flach gehalten, damit sie
     liegt und nicht steht. Zwei Fugen genügen, mehr verklebt bei 20 px. */
  estrich: `<path ${P} d="M6.8 12.4h10.4l3.8 7.2H3l3.8-7.2Z"/>
            <path ${P} d="M10.4 12.4 8.6 19.6M13.6 12.4l1.8 7.2"/>`,

  /* Fliesen — diagonal verlegt: vier Platten in der Raute. Das ist der
     Verband, den man mit Fliesen verbindet, und es ähnelt keinem anderen
     Symbol im Satz. */
  fliesen: `<path ${P} d="M12 3.8 20.2 12 12 20.2 3.8 12Z"/>
            <path ${P} d="M7.9 7.9 16.1 16.1M16.1 7.9 7.9 16.1"/>`,

  /* Maler — Farbrolle mit Bügel und Griff. */
  maler: `<rect ${P} x="3.6" y="4" width="12" height="5" rx="1.4"/>
          <path ${P} d="M15.6 6.5h3.2a1.4 1.4 0 0 1 1.4 1.4v2.3a1.4 1.4 0 0 1-1.4 1.4h-6.6a1.4 1.4 0 0 0-1.4 1.4v.6"/>
          <rect ${P} x="9.1" y="13.6" width="3.6" height="6.4" rx="1.4"/>`,

  /* Küche — Topf mit zwei Griffen und aufsteigendem Dampf; ein Herd mit
     Kochfeld wäre bei 20 px nur ein Kasten mit vier Punkten. */
  kueche: `<path ${P} d="M4.6 10.4h14.8v4.9a4.1 4.1 0 0 1-4.1 4.1H8.7a4.1 4.1 0 0 1-4.1-4.1v-4.9Z"/>
           <path ${P} d="M19.4 11.8h1.2a1.3 1.3 0 0 1 0 2.6h-1.2M4.6 11.8H3.4a1.3 1.3 0 0 0 0 2.6h1.2"/>
           <path ${P} d="M9.6 7.6c0-1.2 1.2-1.2 1.2-2.4M14 7.6c0-1.2 1.2-1.2 1.2-2.4"/>`,

  /* Außenanlagen — Baum über dem Gelände, wie das Gartensymbol der
     Betriebskosten, nur auf den Boden gestellt. */
  aussen: `<path ${P} d="M12 19.6v-4.2"/>
           <path ${P} d="M12 15.4c-3.4 0-5.4-2-5.4-4.9 3.4 0 5.4 2 5.4 4.9Z"/>
           <path ${P} d="M12 15.4c3.4 0 5.4-2 5.4-4.9-3.4 0-5.4 2-5.4 4.9Z"/>
           <path ${P} d="M3.4 19.6h17.2"/>`,

  /* Planung & Gebühren — der Bescheid: Blatt mit Eselsohr und Stempel.
     Ein Grundriss im Rahmen sah aus wie ein Bilderrahmen; was dieses Gewerk
     wirklich hinterlässt, sind Genehmigungen und Rechnungen. */
  planung: `<path ${P} d="M6.4 4.2h6.8l4.4 4.4v11.2H6.4z"/>
            <path ${P} d="M13.2 4.2v4.4h4.4"/>
            <path ${P} d="M8.8 11.4h4"/>
            <circle ${P} cx="11.9" cy="15.4" r="2.4"/>`,

  /* Sonstiges — der Schraubenschlüssel; zugleich der Rückfall für alles,
     was nicht zugeordnet werden kann. */
  sonstiges: `<path ${P} d="m14.5 6.5 3-3a4 4 0 0 1-5 5l-7 7a1.8 1.8 0 1 0 2.5 2.5l7-7a4 4 0 0 0 5-5l-3 3-2.5-2.5Z"/>`,
};

/** Der Sprite — alle Gewerke als <symbol> mit eigenem viewBox. */
export const GEWERK_SPRITE = Object.entries(ZEICHNUNGEN)
  .map(([name, d]) => `<symbol id="gw-${name}" viewBox="0 0 24 24">${d}</symbol>`)
  .join('');

/** Hängt den Sprite einmalig ins Dokument (idempotent). */
export function installGewerkIcons() {
  if (typeof document === 'undefined') return;
  if (document.getElementById('immo-sprite-gewerke')) return;
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.id = 'immo-sprite-gewerke';
  svg.setAttribute('width', '0');
  svg.setAttribute('height', '0');
  svg.setAttribute('aria-hidden', 'true');
  svg.style.position = 'absolute';
  svg.innerHTML = `<defs>${GEWERK_SPRITE}</defs>`;
  document.body.prepend(svg);
}

/* Schlüsselwort -> Symbol. Erster Treffer gewinnt, deshalb stehen
   spezifische Begriffe vor allgemeinen: „Dachdämmung" ist Dach, nicht
   Fassade. Umlaute jeweils auch in der ae/oe/ue-Schreibweise, damit ein
   Gewerk aus einem Import ebenfalls trifft. */
const ZUORDNUNG = [
  ['rohbau', 'rohbau'], ['mauer', 'rohbau'], ['beton', 'rohbau'],
  ['keller', 'rohbau'], ['abbruch', 'rohbau'],
  ['dach', 'dach'], ['spengler', 'dach'], ['klempner', 'dach'],
  ['fassade', 'fassade'], ['dämmung', 'fassade'], ['daemmung', 'fassade'],
  ['putz', 'fassade'], ['gerüst', 'fassade'], ['geruest', 'fassade'],
  ['fenster', 'fenster'], ['tür', 'fenster'], ['tuer', 'fenster'],
  ['schreiner', 'fenster'], ['tischler', 'fenster'],
  ['elektro', 'elektro'], ['strom', 'elektro'], ['photovolta', 'elektro'],
  ['sanitär', 'sanitaer'], ['sanitaer', 'sanitaer'], ['bad', 'sanitaer'],
  ['wasser', 'sanitaer'],
  ['heiz', 'heizung'], ['lüftung', 'heizung'], ['lueftung', 'heizung'],
  ['trockenbau', 'trockenbau'], ['gipskarton', 'trockenbau'],
  ['estrich', 'estrich'], ['böden', 'estrich'], ['boeden', 'estrich'],
  ['boden', 'estrich'], ['parkett', 'estrich'], ['teppich', 'estrich'],
  ['fliese', 'fliesen'], ['naturstein', 'fliesen'],
  ['maler', 'maler'], ['anstrich', 'maler'], ['lack', 'maler'],
  ['tapez', 'maler'],
  ['küche', 'kueche'], ['kueche', 'kueche'],
  ['außen', 'aussen'], ['aussen', 'aussen'], ['garten', 'aussen'],
  ['pflaster', 'aussen'], ['zaun', 'aussen'], ['terrasse', 'aussen'],
  ['planung', 'planung'], ['gebühr', 'planung'], ['gebuehr', 'planung'],
  ['architekt', 'planung'], ['statik', 'planung'], ['genehmig', 'planung'],
];

/** Symbolname zu einem Gewerk — mit Rückfall auf „Sonstiges". */
export function gewerkSymbol(gewerk) {
  const name = String(gewerk || '').toLowerCase();
  for (const [wort, symbol] of ZUORDNUNG) {
    if (name.includes(wort)) return symbol;
  }
  return 'sonstiges';
}

/** Fertiges SVG für ein Gewerk. Der Sprite wird bei Bedarf installiert. */
export function gewerkIcon(gewerk, klasse = '', groesse = 24) {
  installGewerkIcons();
  const symbol = gewerkSymbol(gewerk);
  return `<svg class="${klasse}" width="${groesse}" height="${groesse}"
               viewBox="0 0 24 24" aria-hidden="true"
          ><use href="#gw-${symbol}"/></svg>`;
}
