/* Datumsfeld im Design der App — ein eigener Kalender-Chooser statt des
 * nativen Browser-Pickers (blau, fremdes Betriebssystem-Design, per CSS nicht
 * stylebar — dieselbe Begründung wie beim Auswahlfeld in `auswahl.js`, an dem
 * sich dieses Modul auch strukturell orientiert: ein Knopf + ein Popover,
 * genau ein gemeinsamer Dokument-Lauscher, `zerstoere()` zum Abräumen).
 *
 * Bedienbar: Pfeiltasten bewegen tageweise, Bild-Auf/-Ab monatsweise, Enter
 * wählt, Escape schließt, ein Klick daneben schließt. Ohne Bibliothek.
 */

const esc = s => String(s ?? '')
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;');

const MONATE = ['Januar', 'Februar', 'März', 'April', 'Mai', 'Juni', 'Juli',
  'August', 'September', 'Oktober', 'November', 'Dezember'];
const WOCHENTAGE = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'];

const KAL_SVG = `<svg viewBox="0 0 16 16" width="15" height="15" fill="none"
    aria-hidden="true"><rect x="2" y="3" width="12" height="11" rx="2"
    stroke="currentColor" stroke-width="1.3"/><path d="M2 6h12M5 2v2M11 2v2"
    stroke="currentColor" stroke-width="1.3"/></svg>`;

/* Lokales Datum ohne UTC-Umweg — sonst rutscht der 1. in Mitteleuropa auf
   den 31. des Vormonats (dasselbe Problem wie `isoDatum` in objekt-format.js). */
const isoZuDatum = iso => iso ? new Date(`${iso}T12:00:00`) : null;
const datumZuIso = d => `${d.getFullYear()}-${String(d.getMonth() + 1)
  .padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const heuteIso = () => datumZuIso(new Date());
const anzeige = iso => {
  const d = isoZuDatum(iso);
  return d ? `${String(d.getDate()).padStart(2, '0')}.${
    String(d.getMonth() + 1).padStart(2, '0')}.${d.getFullYear()}` : '';
};

let laufendeNummer = 0;
const instanzen = new Set();
let lauscherHaengt = false;

function kehreAus(ersetzt = null) {
  for (const feld of instanzen) {
    if (!feld.ziel.isConnected || feld.ziel === ersetzt) feld.zerstoere();
  }
}

function haengeLauscherAn() {
  if (lauscherHaengt) return;
  lauscherHaengt = true;
  document.addEventListener('pointerdown', e => {
    kehreAus();
    for (const feld of instanzen) feld.klickDaneben(e.target);
  });
}

/**
 * Baut einen Datums-Chooser in `ziel`.
 * @param {HTMLElement} ziel
 * @param {object}      einst
 * @param {string}      einst.wert       ISO-Datum ("2028-03-01") oder leer
 * @param {string}      einst.label      Beschriftung für Screenreader
 * @param {Function}    einst.aenderung  wird mit dem neuen ISO-Wert (oder '') gerufen
 * @returns {{wert:Function, setze:Function, zerstoere:Function}}
 */
export function datumwahl(ziel, { wert = '', label = '', aenderung = () => {} } = {}) {
  kehreAus(ziel);

  const id = `datumwahl${++laufendeNummer}`;
  const wache = new AbortController();
  const { signal } = wache;
  let gewaehlt = wert || '';
  // Der Monat, den das Popover gerade zeigt — startet beim gewählten Datum,
  // sonst bei heute.
  let sicht = isoZuDatum(gewaehlt) || new Date();
  let offen = false;

  ziel.classList.add('datumwahl');
  ziel.innerHTML = `
    <button type="button" class="datumwahl-knopf" id="${id}"
            aria-haspopup="dialog" aria-expanded="false"
            ${label ? `aria-label="${esc(label)}"` : ''}>
      <span class="datumwahl-text"></span>
      <span class="datumwahl-ikon">${KAL_SVG}</span>
    </button>
    <div class="datumwahl-pop" hidden role="dialog" aria-label="Datum wählen">
      <div class="dw-kopf">
        <button type="button" class="dw-nav" data-nav="-jahr" aria-label="Vorheriges Jahr">«</button>
        <button type="button" class="dw-nav" data-nav="-monat" aria-label="Vorheriger Monat">‹</button>
        <span class="dw-titel"></span>
        <button type="button" class="dw-nav" data-nav="+monat" aria-label="Nächster Monat">›</button>
        <button type="button" class="dw-nav" data-nav="+jahr" aria-label="Nächstes Jahr">»</button>
      </div>
      <div class="dw-wochentage">${WOCHENTAGE.map(w => `<span>${w}</span>`).join('')}</div>
      <div class="dw-tage"></div>
      <div class="dw-fuss">
        <button type="button" class="dw-fussknopf" data-heute>Heute</button>
        <button type="button" class="dw-fussknopf leer" data-loeschen>Löschen</button>
      </div>
    </div>`;

  const knopf = ziel.querySelector('.datumwahl-knopf');
  const text = ziel.querySelector('.datumwahl-text');
  const pop = ziel.querySelector('.datumwahl-pop');
  const titel = ziel.querySelector('.dw-titel');
  const tage = ziel.querySelector('.dw-tage');

  function zeichneKnopf() {
    text.textContent = anzeige(gewaehlt);
    text.classList.toggle('leer', !gewaehlt);
    if (!text.textContent) text.textContent = 'tt.mm.jjjj';
  }

  function zeichneKalender() {
    titel.textContent = `${MONATE[sicht.getMonth()]} ${sicht.getFullYear()}`;
    const jahr = sicht.getFullYear(), monat = sicht.getMonth();
    // Montag als Wochenanfang: JS zählt So=0 … Sa=6, hier auf Mo=0 … So=6 drehen.
    const ersterTagWochentag = (new Date(jahr, monat, 1).getDay() + 6) % 7;
    const tageImMonat = new Date(jahr, monat + 1, 0).getDate();
    const heute = heuteIso();
    const zellen = [];
    for (let i = 0; i < ersterTagWochentag; i++) zellen.push('<span class="dw-leer"></span>');
    for (let t = 1; t <= tageImMonat; t++) {
      const iso = datumZuIso(new Date(jahr, monat, t));
      const an = iso === gewaehlt, heutiger = iso === heute;
      zellen.push(`<button type="button" class="dw-tag${an ? ' gewaehlt' : ''}${
          heutiger ? ' heute' : ''}" data-tag="${iso}" aria-pressed="${an}">${t}</button>`);
    }
    tage.innerHTML = zellen.join('');
  }

  function oeffne() {
    if (offen) return;
    offen = true;
    sicht = isoZuDatum(gewaehlt) || sicht || new Date();
    zeichneKalender();
    pop.hidden = false;
    knopf.setAttribute('aria-expanded', 'true');
    const platz = window.innerHeight - knopf.getBoundingClientRect().bottom;
    ziel.classList.toggle('nach-oben', platz < 360);
    pop.querySelector('.dw-tag.gewaehlt')?.focus();
  }

  function schliesse({ zurueck = true } = {}) {
    if (!offen) return;
    offen = false;
    pop.hidden = true;
    knopf.setAttribute('aria-expanded', 'false');
    ziel.classList.remove('nach-oben');
    if (zurueck) knopf.focus();
  }

  function waehle(iso) {
    const vorher = gewaehlt;
    gewaehlt = iso;
    zeichneKnopf();
    schliesse();
    if (vorher !== gewaehlt) aenderung(gewaehlt);
  }

  function blaettere(schritt) {
    const n = new Date(sicht);
    n.setDate(1);            // erst auf den 1., sonst überspringt setMonth() bei Monaten mit 31 Tagen manchmal einen
    n.setMonth(n.getMonth() + schritt);
    sicht = n;
    zeichneKalender();
    pop.querySelector('.dw-tag.gewaehlt, .dw-tag.heute')?.focus();
  }

  knopf.addEventListener('click', () => (offen ? schliesse() : oeffne()), { signal });
  knopf.addEventListener('keydown', e => {
    if (e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ') {
      e.preventDefault(); oeffne();
    }
  }, { signal });

  pop.addEventListener('click', e => {
    const nav = e.target.closest('[data-nav]');
    if (nav) {
      const richtung = nav.dataset.nav;
      blaettere(richtung.includes('jahr') ? (richtung[0] === '+' ? 12 : -12)
                                          : (richtung[0] === '+' ? 1 : -1));
      return;
    }
    const tagKnopf = e.target.closest('[data-tag]');
    if (tagKnopf) { waehle(tagKnopf.dataset.tag); return; }
    if (e.target.closest('[data-heute]')) { waehle(heuteIso()); return; }
    if (e.target.closest('[data-loeschen]')) { waehle(''); return; }
  }, { signal });

  pop.addEventListener('keydown', e => {
    const im = ziel.querySelectorAll('.dw-tag');
    const aktIdx = [...im].findIndex(b => b === document.activeElement);
    const springe = delta => {
      e.preventDefault();
      const neu = im[aktIdx + delta];
      if (neu) neu.focus();
      else blaettere(delta > 0 ? 1 : -1);   // über den Monatsrand hinaus
    };
    if (e.key === 'ArrowRight') springe(1);
    else if (e.key === 'ArrowLeft') springe(-1);
    else if (e.key === 'ArrowDown') springe(7);
    else if (e.key === 'ArrowUp') springe(-7);
    else if (e.key === 'Enter' && aktIdx >= 0) { e.preventDefault(); waehle(im[aktIdx].dataset.tag); }
    else if (e.key === 'Escape') { e.preventDefault(); schliesse(); }
  }, { signal });

  zeichneKnopf();

  function zerstoere() {
    offen = false;
    wache.abort();
    instanzen.delete(eintragImRegister);
  }

  const eintragImRegister = {
    ziel,
    zerstoere,
    klickDaneben(el) {
      if (offen && !ziel.contains(el)) schliesse({ zurueck: false });
    },
  };
  instanzen.add(eintragImRegister);
  haengeLauscherAn();

  return {
    wert: () => gewaehlt,
    setze(neu) { gewaehlt = neu || ''; zeichneKnopf(); },
    zerstoere,
  };
}
