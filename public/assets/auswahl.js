/* Auswahlfeld im Design der App.
 *
 * Ein natives <select> lässt sich zwar am Rahmen gestalten, die aufgeklappte
 * Liste zeichnet aber das Betriebssystem — eckig, systemblau, fremd. Deshalb
 * hier ein eigenes Listenfeld aus Knopf und <ul role="listbox">.
 *
 * Bedienbar bleibt es wie ein echtes Auswahlfeld: Pfeiltasten bewegen,
 * Enter wählt, Escape schließt, Home/End springen, ein Klick daneben schließt.
 * Ohne Bibliothek, ohne Build-Schritt.
 */

const esc = s => String(s ?? '')
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;');

let laufendeNummer = 0;

/**
 * Baut ein Auswahlfeld in `ziel`.
 * @param {HTMLElement} ziel      Behälter, dessen Inhalt ersetzt wird
 * @param {object}      einst
 * @param {Array}       einst.optionen  [{wert, text}, …]
 * @param {string}      einst.wert      vorausgewählter Wert
 * @param {string}      einst.label     Beschriftung für Screenreader
 * @param {Function}    einst.aenderung  wird mit dem neuen Wert gerufen
 * @returns {{wert:Function, setze:Function, fuelle:Function}}
 */
export function auswahlfeld(ziel, { optionen = [], wert = '', label = '',
                                    aenderung = () => {} } = {}) {
  const id = `auswahl${++laufendeNummer}`;
  let liste = optionen;
  let gewaehlt = wert;
  let offen = false;
  let markiert = 0;

  ziel.classList.add('auswahl');
  ziel.innerHTML = `
    <button type="button" class="auswahl-knopf" id="${id}"
            aria-haspopup="listbox" aria-expanded="false"
            ${label ? `aria-label="${esc(label)}"` : ''}>
      <span class="auswahl-text"></span>
      <svg class="auswahl-pfeil" viewBox="0 0 12 8" width="12" height="8"
           aria-hidden="true">
        <path d="M1 1l5 5 5-5" stroke="currentColor" stroke-width="1.6"
              fill="none" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    </button>
    <ul class="auswahl-liste" role="listbox" tabindex="-1" hidden
        aria-labelledby="${id}"></ul>`;

  const knopf = ziel.querySelector('.auswahl-knopf');
  const text = ziel.querySelector('.auswahl-text');
  const feld = ziel.querySelector('.auswahl-liste');

  const eintrag = () => liste.find(o => String(o.wert) === String(gewaehlt));

  function zeichne() {
    const treffer = eintrag();
    text.textContent = treffer ? treffer.text : (liste[0]?.text ?? '');
    feld.innerHTML = liste.map((o, i) => `
      <li role="option" data-i="${i}"
          aria-selected="${String(o.wert) === String(gewaehlt)}"
          class="${i === markiert ? 'markiert' : ''}">${esc(o.text)}</li>`).join('');
  }

  function oeffne() {
    if (offen) return;
    offen = true;
    markiert = Math.max(0, liste.findIndex(o => String(o.wert) === String(gewaehlt)));
    zeichne();
    feld.hidden = false;
    knopf.setAttribute('aria-expanded', 'true');
    // Nach oben aufklappen, wenn unten kein Platz mehr ist — sonst steht die
    // Liste halb unter dem Rand des Fensters.
    const platz = window.innerHeight - knopf.getBoundingClientRect().bottom;
    ziel.classList.toggle('nach-oben', platz < Math.min(260, liste.length * 44 + 16));
    feld.querySelector('.markiert')?.scrollIntoView({ block: 'nearest' });
  }

  function schliesse({ zurueck = true } = {}) {
    if (!offen) return;
    offen = false;
    feld.hidden = true;
    knopf.setAttribute('aria-expanded', 'false');
    ziel.classList.remove('nach-oben');
    if (zurueck) knopf.focus();
  }

  function waehle(i) {
    const o = liste[i];
    if (!o) return;
    const vorher = gewaehlt;
    gewaehlt = o.wert;
    zeichne();
    schliesse();
    if (String(vorher) !== String(gewaehlt)) aenderung(gewaehlt);
  }

  function bewege(schritt) {
    if (!offen) return oeffne();
    markiert = Math.min(liste.length - 1, Math.max(0, markiert + schritt));
    zeichne();
    feld.querySelector('.markiert')?.scrollIntoView({ block: 'nearest' });
  }

  knopf.addEventListener('click', () => (offen ? schliesse() : oeffne()));

  knopf.addEventListener('keydown', e => {
    if (e.key === 'ArrowDown') { e.preventDefault(); bewege(1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); bewege(-1); }
    else if (e.key === 'Home') { e.preventDefault(); markiert = 0; zeichne(); }
    else if (e.key === 'End') { e.preventDefault(); markiert = liste.length - 1; zeichne(); }
    else if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      offen ? waehle(markiert) : oeffne();
    } else if (e.key === 'Escape') schliesse();
  });

  feld.addEventListener('click', e => {
    const zeile = e.target.closest('[data-i]');
    if (zeile) waehle(Number(zeile.dataset.i));
  });

  // pointerdown statt click: sonst schliesst der eigene Klick das Feld,
  // bevor die Auswahl ankommt.
  document.addEventListener('pointerdown', e => {
    if (offen && !ziel.contains(e.target)) schliesse({ zurueck: false });
  });

  zeichne();

  return {
    wert: () => gewaehlt,
    setze(neu) { gewaehlt = neu; zeichne(); },
    fuelle(neueOptionen, neuerWert = gewaehlt) {
      liste = neueOptionen;
      gewaehlt = neuerWert;
      zeichne();
    },
  };
}
