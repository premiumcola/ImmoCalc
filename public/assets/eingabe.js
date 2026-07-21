/* Eingabefelder, die sich beim Tippen selbst lesbar machen.
 *
 * Drei Felder, ein Prinzip: der Nutzer tippt Zeichen für Zeichen, die Anzeige
 * legt die üblichen Trenner dazwischen — Tausenderpunkte beim Betrag,
 * Vierergruppen bei der IBAN, Schrägstriche bei der Steuernummer. Der Cursor
 * bleibt dabei da, wo er hingehört: gemerkt wird nicht seine Position, sondern
 * wie viele echte Zeichen vor ihm stehen; die Trenner zählen nicht mit.
 *
 *     geldFeld(el) · ibanFeld(el) · steuernummerFeld(el)  →  { zerstoere() }
 *
 * WICHTIG FÜR DEN EINBINDENDEN CODE — der Wert bleibt unformatiert.
 * `el.value` liefert weiterhin den ROHEN Wert, nicht den angezeigten Text:
 *
 *     Betrag        1250.5   (Punkt als Dezimaltrenner, keine Tausenderpunkte)
 *     IBAN          DE12345678901234567890   (ohne Leerzeichen, Großbuchstaben)
 *     Steuernummer  12345678901              (nur Ziffern, ohne Schrägstriche)
 *
 * Dazu wird `value` genau auf diesem einen Element überschrieben; die Anzeige
 * liegt darunter im nativen Wert. Wer es lieber ausdrücklich liest, nimmt
 * `el.dataset.wert` — derselbe Inhalt. Schreiben geht genauso: `el.value =
 * '1250.5'` setzt den rohen Wert, die Formatierung macht das Feld selbst.
 * Bestehende Seiten müssen also nichts ändern, sie lesen und schreiben weiter
 * `el.value`. Ein Formular, das beim Absenden `el.value` einsammelt, bekommt
 * den unverfälschten Wert.
 *
 * AUCH ÜBER `new FormData(form)`. Der Weg geht am überschriebenen `value`
 * vorbei — er liest den nativen Wert, also die Anzeige. Damit auch er den
 * rohen Wert liefert, wandert beim Anhängen das `name`-Attribut vom
 * sichtbaren Feld auf ein verstecktes <input type="hidden"> direkt daneben;
 * dort steht immer der rohe Wert. Für einbindende Seiten heißt das:
 *
 *   new FormData(form).get('kaufpreis')  →  '1250000'   (roh)
 *   form.elements.kaufpreis              →  das VERSTECKTE Feld
 *   form.querySelector('#kaufpreis')     →  das sichtbare Feld
 *
 * Wer das sichtbare Feld braucht (Fokus, Prüfung, `dataset.wert`), sucht es
 * also über seine id, nicht über den Namen. `zerstoere()` gibt den Namen
 * zurück und räumt das versteckte Feld weg.
 *
 * `zerstoere()` nimmt die Überschreibung zurück und lässt den rohen Wert im
 * Feld stehen — danach ist es wieder ein ganz normales <input>.
 *
 * DIE EINHEIT STEHT IM FELD. `geldFeld(el)` legt ein leises „€“ an den rechten
 * Rand des Feldes, `geldFeld(el, 'm²')` das jeweils passende Zeichen. Es ist
 * reine Anzeige: es hängt in einer Hülle über dem Feld, nicht im Wert. Das
 * Feld bekommt rechts so viel Polster, dass auch eine lange Zahl nie darunter
 * läuft.
 */

/* Der native Zugriff auf `value`. Über ihn läuft alles, was die ANZEIGE
 * betrifft — die überschriebene Eigenschaft liefert ja den rohen Wert. */
const NATIV = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
const lies = el => NATIV.get.call(el);
const schreibe = (el, text) => NATIV.set.call(el, text);

const ZIFFER = /[0-9]/;
const MAX_STELLEN = 15;      // Vorkommastellen — mehr ist kein Betrag mehr
const MAX_NACHKOMMA = 2;
const MAX_IBAN = 34;         // längste IBAN weltweit
const MAX_STEUER = 13;       // bundeseinheitliches Schema

/* ---- Stil: nur das Nötigste, damit die Datei ohne Zutun in immo.css läuft.
   Wird einmal je Seite eingehängt und kommt nach immo.css, gewinnt also bei
   gleicher Spezifität. ---- */
const STIL = `
.eingabe-feld{font-variant-numeric:tabular-nums}
.eingabe-huelle{position:relative; display:block}
/* Body-Schrift, nicht Mono: eine Mono-Schrift stellt jedes Zeichen in ein
   eigenes Fach, und „m²" fiele auseinander. */
.eingabe-einheit{
  position:absolute; right:13px; top:50%; transform:translateY(-50%);
  font:500 13.5px var(--body,system-ui,sans-serif); line-height:1;
  color:var(--soft,#5C6B70); pointer-events:none; white-space:nowrap;
}
`;

function stellStilBereit() {
  if (document.getElementById('eingabe-stil')) return;
  const stil = document.createElement('style');
  stil.id = 'eingabe-stil';
  stil.textContent = STIL;
  document.head.append(stil);
}

/* ==========================================================================
   Betrag
   ========================================================================== */

/**
 * Wo steht der Dezimaltrenner?
 *
 * Beim Tippen ist die Sache eindeutig: das Komma trennt, die Punkte in der
 * Anzeige haben wir selbst gesetzt. Beim Einfügen aus der Zwischenablage ist
 * sie es nicht — „1.250“ sind zwölfhundertfünfzig, „1.25“ ist eine Mark und
 * fünfundzwanzig. Deshalb dort die übliche Faustregel: ein einzelner Punkt mit
 * genau drei Ziffern dahinter ist ein Tausenderpunkt, sonst ein Dezimalpunkt.
 * @param {string} text
 * @param {boolean} locker  Punkte dürfen Dezimaltrenner sein (Einfügen)
 * @returns {number} Index im Text oder -1
 */
function geldTrenner(text, locker) {
  const komma = text.lastIndexOf(',');
  if (komma >= 0) return komma;
  if (!locker) return -1;
  const punkt = text.indexOf('.');
  if (punkt < 0 || punkt !== text.lastIndexOf('.')) return -1;
  const nach = text.slice(punkt + 1).replace(/\D/g, '').length;
  return nach === 3 ? -1 : punkt;
}

/**
 * Zieht aus dem Getippten die Zeichen heraus, die der Nutzer wirklich meint:
 * Ziffern, ein führendes Minus, höchstens ein Komma, höchstens zwei Stellen
 * dahinter. Zählt nebenbei, wie viele davon vor dem Cursor stehen.
 * @returns {{kern:string, vor:number}}
 */
function geldKern(text, caret, locker) {
  const trenner = geldTrenner(text, locker);
  let kern = '';
  let vor = 0;
  let nachkomma = -1;
  let stellen = 0;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    let zeichen = '';
    if (ZIFFER.test(c)) zeichen = c;
    else if (c === '-' && kern === '') zeichen = '-';
    else if (i === trenner && !kern.includes(',')) zeichen = ',';
    if (!zeichen) continue;
    if (zeichen === ',') nachkomma = 0;
    else if (ZIFFER.test(zeichen)) {
      if (nachkomma >= 0) {
        if (nachkomma >= MAX_NACHKOMMA) continue;
        nachkomma++;
      } else {
        if (stellen >= MAX_STELLEN) continue;
        stellen++;
      }
    }
    kern += zeichen;
    if (i < caret) vor++;
  }
  return { kern, vor };
}

/** Kern → Anzeige: „-1234567,5“ wird zu „-1.234.567,5“. */
function geldAnzeige(kern) {
  if (!kern) return '';
  const minus = kern[0] === '-';
  const rest = minus ? kern.slice(1) : kern;
  const k = rest.indexOf(',');
  const ganz = k < 0 ? rest : rest.slice(0, k);
  const dez = k < 0 ? null : rest.slice(k + 1);
  const gruppiert = ganz.replace(/\B(?=(\d{3})+(?!\d))/g, '.');
  return (minus ? '-' : '') + gruppiert + (dez === null ? '' : ',' + dez);
}

/** Kern → roher Wert für die API: „1.234,50“ wird zu „1234.50“. */
function geldRoh(kern) {
  const minus = kern[0] === '-';
  const rest = minus ? kern.slice(1) : kern;
  const k = rest.indexOf(',');
  const ganz = (k < 0 ? rest : rest.slice(0, k)).replace(/^0+(?=\d)/, '');
  const dez = k < 0 ? '' : rest.slice(k + 1);
  if (!ganz && !dez) return '';
  return (minus ? '-' : '') + (ganz || '0') + (dez ? '.' + dez : '');
}

/** Bauart „Betrag“. */
function artGeld() {
  return {
    inputmode: 'decimal',
    /* Auf dem Zehnerblock und auf mancher Tastatur liegt der Punkt da, wo im
       Deutschen das Komma hingehört — also wird er stumm dazu gemacht. */
    punktIstKomma: true,
    kern: (text, caret, { locker }) => geldKern(text, caret, locker),
    anzeige: geldAnzeige,
    roh: geldRoh,
    istKern: c => ZIFFER.test(c) || c === ',' || c === '-',
    // Ein roher Wert kommt mit Punkt als Dezimaltrenner — also locker lesen.
    vonRoh: text => geldKern(text, text.length, true).kern,
    // Beim Verlassen des Feldes das angefangene Komma wegräumen.
    schluss: kern => (kern.endsWith(',') ? kern.slice(0, -1) : kern),
  };
}

/* ==========================================================================
   IBAN
   ========================================================================== */

function ibanKern(text, caret) {
  let kern = '';
  let vor = 0;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (!/[0-9a-zA-Z]/.test(c)) continue;
    if (kern.length >= MAX_IBAN) continue;
    kern += c.toUpperCase();
    if (i < caret) vor++;
  }
  return { kern, vor };
}

/** Bauart „IBAN“: Vierergruppen, Großbuchstaben. */
function artIban() {
  return {
    // 'text': die IBAN beginnt mit zwei Buchstaben, eine Zifferntastatur
    // führte in die Sackgasse.
    inputmode: 'text',
    zusatz: { autocomplete: 'off', autocapitalize: 'characters',
              autocorrect: 'off', spellcheck: 'false' },
    kern: (text, caret) => ibanKern(text, caret),
    // Leerzeichen nur zwischen die Gruppen, nie hinter die letzte —
    // sonst steht der Cursor beim Tippen hinter einer Lücke ins Nichts.
    anzeige: kern => kern.replace(/(.{4})(?=.)/g, '$1 '),
    roh: kern => kern,
    istKern: c => /[0-9A-Z]/.test(c),
    vonRoh: text => ibanKern(text, 0).kern,
  };
}

/* ==========================================================================
   Steuernummer
   ========================================================================== */

/**
 * Welcher Abschnitt von `neu` ist beim letzten Schritt dazugekommen?
 *
 * Ein Tastendruck, ein Einfügen, ein Löschen — jedes davon ändert genau ein
 * zusammenhängendes Stück in der Mitte; Anfang und Ende bleiben stehen. Der
 * gemeinsame Anfang und das gemeinsame Ende grenzen es ein.
 * @returns {[number, number]} Halboffener Bereich [von, bis) in `neu`
 */
function neuerTeil(alt, neu) {
  let vorn = 0;
  while (vorn < alt.length && vorn < neu.length && alt[vorn] === neu[vorn]) vorn++;
  const rest = Math.min(alt.length, neu.length) - vorn;
  let hinten = 0;
  while (hinten < rest &&
         alt[alt.length - 1 - hinten] === neu[neu.length - 1 - hinten]) hinten++;
  return [vorn, neu.length - hinten];
}

/** Bauart „Steuernummer“.
 *
 * Länge und Schnitt hängen am Bundesland: 123/456/78901 in Bayern,
 * 93815/08152 in Baden-Württemberg, 133/8150/8159 in Nordrhein-Westfalen. Eine
 * feste Maske wäre für die meisten falsch. Deshalb führen zwei Wege zum Ziel:
 *
 *   nur Ziffern      Das Feld schlägt den verbreiteten Schnitt 3/3/Rest vor.
 *                    Der Vorschlag ist reine Anzeige.
 *   eigene Trenner   Sobald der Nutzer selbst einen „/“ setzt oder einfügt,
 *                    gilt seiner — und der Vorschlag löst sich rückstandsfrei
 *                    auf.
 *
 * Damit das zweite ohne Reste geht, muss das Feld die eigenen Vorschläge von
 * den Trennern des Nutzers unterscheiden. Es merkt sich dazu die zuletzt
 * ausgegebene Anzeige: Trenner, die schon darin standen, sind die eigenen;
 * neu dazugekommene gehören dem Nutzer. Aus „938/15“ plus einem getippten
 * „/“ wird so „93815/“ statt „938/15/“.
 */
function artSteuernummer() {
  // Die zuletzt ausgegebene Anzeige — der Vergleichsstand für `neuerTeil`.
  let zuletzt = '';
  // Trennt der Nutzer selbst? Ergibt sich aus dem zuletzt gelesenen Kern.
  let eigen = false;

  const kern = (text, caret) => {
    const [von, bis] = neuerTeil(zuletzt, text);
    let aus = '';
    let vor = 0;
    let ziffern = 0;
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      if (c === '/') {
        // Führende und doppelte Trenner schluckt das Feld …
        if (!aus || aus.endsWith('/')) continue;
        // … und den eigenen Vorschlag ebenso: er stand schon in der letzten
        // Anzeige, während der Trenner des Nutzers gerade erst dazukam.
        // Im eigenen Schnitt gibt es keine Vorschläge, dort zählt jeder.
        if (!eigen && (i < von || i >= bis)) continue;
      } else if (!ZIFFER.test(c) || ziffern >= MAX_STEUER) {
        continue;
      } else {
        ziffern++;
      }
      aus += c;
      if (i < caret) vor++;
    }
    eigen = aus.includes('/');
    return { kern: aus, vor };
  };

  const anzeige = k => {
    let aus;
    if (k.includes('/')) {
      aus = k;                                  // eigener Schnitt des Nutzers
    } else {
      aus = k.slice(0, 3);
      if (k.length > 3) aus += '/' + k.slice(3, 6);
      if (k.length > 6) aus += '/' + k.slice(6);
    }
    zuletzt = aus;
    return aus;
  };

  return {
    // 'numeric': die Steuernummer ist eine Ziffernkette; die Schrägstriche
    // setzt das Feld selbst, dafür muss niemand die Tastatur umschalten.
    inputmode: 'numeric',
    zusatz: { autocomplete: 'off', spellcheck: 'false' },
    kern,
    anzeige,
    roh: k => k.replace(/\D/g, ''),
    istKern: c => ZIFFER.test(c) || (eigen && c === '/'),
    // Ein von aussen gesetzter Wert ist ganz und gar der des Nutzers —
    // ohne Vergleichsstand zählt jeder Trenner darin als seiner.
    vonRoh: text => { zuletzt = ''; return kern(text, 0).kern; },
  };
}

/* ==========================================================================
   Gemeinsamer Unterbau
   ========================================================================== */

/* Alle lebenden Felder. Ein einziger Lauscher am Dokument bedient sie alle —
 * kämen pro Feld eigene dazu, sammelten sich bei jedem Neuaufbau der Seite
 * hunderte an. Der Lauscher hängt bewusst in der ABFANGPHASE: so ist
 * `el.value` schon aktualisiert, wenn die Seite ihren eigenen input-Lauscher
 * am Feld ausführt. */
const felder = new Map();
let lauscherHaengt = false;

function haengeLauscherAn() {
  if (lauscherHaengt) return;
  lauscherHaengt = true;
  const an = (name, ruf) =>
    document.addEventListener(name, e => {
      const feld = felder.get(e.target);
      if (feld) ruf(feld, e);
    }, true);
  an('input', (feld, e) => feld.beiEingabe(e));
  an('keydown', (feld, e) => feld.beiTaste(e));
  an('blur', feld => feld.beiVerlassen());
}

/** Wirft alle Felder weg, deren Element nicht mehr im Dokument hängt. */
function kehreAus() {
  for (const [el, feld] of felder) if (!el.isConnected) feld.zerstoere();
}

/** Stelle in der Anzeige, vor der genau `anzahl` echte Zeichen stehen. */
function stelleNach(anzeige, anzahl, istKern) {
  let gesehen = 0;
  for (let i = 0; i < anzeige.length; i++) {
    if (gesehen === anzahl) return i;
    if (istKern(anzeige[i])) gesehen++;
  }
  return anzeige.length;
}

let laufendeNummer = 0;

/**
 * Hängt eine Bauart an ein Feld.
 * @param {HTMLInputElement} el
 * @param {object} art
 * @param {{einheit?:string}} opt  Zeichen, das rechts im Feld stehen soll
 * @returns {{wert:Function, setze:Function, zerstoere:Function}}
 */
function binde(el, art, opt = {}) {
  if (!(el instanceof HTMLInputElement)) throw new TypeError('kein <input>');
  felder.get(el)?.zerstoere();
  kehreAus();
  stellStilBereit();

  // type=number verträgt keine Trennzeichen — der Browser wirft den Wert weg
  // und `selectionStart` gibt es dort auch nicht.
  const alterTyp = el.type;
  if (el.type !== 'text') el.type = 'text';
  if (!el.hasAttribute('inputmode')) el.inputMode = art.inputmode;
  for (const [name, wert] of Object.entries(art.zusatz || {})) {
    if (!el.hasAttribute(name)) el.setAttribute(name, wert);
  }
  el.classList.add('eingabe-feld');

  /* Die Einheit gehört ins Feld, nicht darunter: eine Hülle legt das Zeichen
     über den rechten Rand des Feldes, und das Feld bekommt dort genau so viel
     Polster, dass die Zahl nie darunter läuft — der Text eines <input> wird an
     der Innenkante abgeschnitten, das Zeichen liegt hinter ihr. */
  const zeichen = opt.einheit || '';
  const altesPolster = el.style.paddingRight;
  let huelle = null;
  let einheitEl = null;
  if (zeichen && el.parentNode) {
    huelle = document.createElement('span');
    huelle.className = 'eingabe-huelle';
    el.before(huelle);
    huelle.append(el);
    einheitEl = document.createElement('span');
    einheitEl.className = 'eingabe-einheit';
    einheitEl.id = `eingabe-einheit-${++laufendeNummer}`;
    einheitEl.textContent = zeichen;
    huelle.append(einheitEl);
    el.style.paddingRight = `${26 + 8 * zeichen.length}px`;
  }

  // Ein Formular sammelt seine Werte über `new FormData(form)` — und das liest
  // den NATIVEN Wert, also die Anzeige, an der überschriebenen Eigenschaft
  // vorbei. Deshalb wandert der Name auf ein verstecktes Feld daneben, das
  // immer den rohen Wert trägt; das sichtbare Feld trägt keinen mehr.
  const name = el.getAttribute('name');
  let spiegel = null;
  if (name) {
    spiegel = document.createElement('input');
    spiegel.type = 'hidden';
    spiegel.name = name;
    el.removeAttribute('name');
    el.after(spiegel);
  }

  /** Legt den rohen Wert dort ab, wo ihn alle Wege wiederfinden. */
  function merkeWert(roh) {
    el.dataset.wert = roh;
    if (spiegel) spiegel.value = roh;
  }

  // Das Zeichen wird mit vorgelesen — „Restschuld, Euro“ —, sonst bliebe es
  // eine rein optische Auskunft.
  const beschrieben = el.getAttribute('aria-describedby');
  if (einheitEl) {
    el.setAttribute('aria-describedby',
      beschrieben ? `${beschrieben} ${einheitEl.id}` : einheitEl.id);
  }

  /**
   * Formatiert die Anzeige neu und setzt den Cursor dorthin zurück, wo er
   * gemessen an den echten Zeichen stand.
   */
  function zeichne({ locker = false, schluss = false } = {}) {
    const text = lies(el);
    const caret = el.selectionStart ?? text.length;
    let { kern, vor } = art.kern(text, caret, { locker });
    if (schluss && art.schluss) kern = art.schluss(kern);
    vor = Math.min(vor, kern.length);

    const anzeige = art.anzeige(kern);
    if (anzeige !== text) schreibe(el, anzeige);
    const roh = art.roh(kern);
    merkeWert(roh);

    if (document.activeElement === el) {
      const pos = stelleNach(anzeige, vor, art.istKern);
      el.setSelectionRange(pos, pos);
    }
  }

  const steuerung = {
    beiEingabe(e) {
      const caret = el.selectionStart ?? 0;
      // Getippter Punkt wird zum Komma — noch bevor irgendwer den Wert liest.
      if (art.punktIstKomma && e.data === '.' && lies(el)[caret - 1] === '.') {
        const text = lies(el);
        schreibe(el, text.slice(0, caret - 1) + ',' + text.slice(caret));
        el.setSelectionRange(caret, caret);
      }
      const typ = String(e.inputType || '');
      zeichne({ locker: typ.includes('Paste') || typ.includes('Drop') });
    },

    /**
     * Löschen soll sich anfühlen wie in einem Feld ohne Trenner: steht der
     * Cursor hinter einem Trennzeichen, wird das echte Zeichen davor gelöscht
     * — nicht der Trenner, den das Feld gleich wieder setzen würde. Bei Entf
     * entsprechend das echte Zeichen dahinter.
     */
    beiTaste(e) {
      if (e.key !== 'Backspace' && e.key !== 'Delete') return;
      if (e.altKey || e.ctrlKey || e.metaKey) return;
      if (el.selectionStart !== el.selectionEnd) return;   // Auswahl: wie üblich
      const text = lies(el);
      let a = el.selectionStart;
      let b = a;
      if (e.key === 'Backspace') {
        while (a > 0 && !art.istKern(text[a - 1])) a--;
        if (a === 0) { e.preventDefault(); return; }
        a--;
      } else {
        while (b < text.length && !art.istKern(text[b])) b++;
        if (b === text.length) { e.preventDefault(); return; }
        b++;
      }
      e.preventDefault();
      schreibe(el, text.slice(0, a) + text.slice(b));
      el.setSelectionRange(a, a);
      zeichne();
      el.dispatchEvent(new Event('input', { bubbles: true }));
    },

    beiVerlassen() { zeichne({ schluss: true }); },

    /** Setzt einen rohen Wert von aussen. */
    setze(neu) {
      const kern = art.vonRoh(neu == null ? '' : String(neu));
      schreibe(el, art.anzeige(kern));
      merkeWert(art.roh(kern));
    },

    zerstoere() {
      if (!felder.has(el)) return;
      felder.delete(el);
      const roh = el.dataset.wert || '';
      delete el.value;                 // die eigene Eigenschaft fällt weg
      delete el.dataset.wert;
      schreibe(el, roh);
      if (spiegel) { spiegel.remove(); el.setAttribute('name', name); }
      el.classList.remove('eingabe-feld');
      if (el.type !== alterTyp) el.type = alterTyp;
      if (huelle) {
        huelle.before(el);            // das Feld tritt an die Stelle der Hülle
        huelle.remove();
        el.style.paddingRight = altesPolster;
        if (beschrieben) el.setAttribute('aria-describedby', beschrieben);
        else el.removeAttribute('aria-describedby');
      }
    },
  };

  felder.set(el, steuerung);
  haengeLauscherAn();

  // Der Wert, der schon im Feld steht, ist ein roher Wert (siehe Kopf).
  steuerung.setze(lies(el));

  // Ab hier liefert `el.value` den rohen Wert und nimmt ihn auch entgegen.
  Object.defineProperty(el, 'value', {
    configurable: true,
    enumerable: true,
    get: () => el.dataset.wert ?? '',
    set: neu => steuerung.setze(neu),
  });

  return {
    wert: () => el.dataset.wert ?? '',
    setze: neu => steuerung.setze(neu),
    zerstoere: () => steuerung.zerstoere(),
  };
}

/* ==========================================================================
   Schnittstelle
   ========================================================================== */

/**
 * Betrag mit Tausenderpunkten und einem leisen Zeichen rechts im Feld.
 * `el.value` bleibt die nackte Zahl („1250000“).
 * @param {HTMLInputElement} el
 * @param {string} einheit  „€“, „%“, „m²“ … — leer lässt das Feld schmucklos
 * @returns {{wert:Function, setze:Function, zerstoere:Function}}
 */
export function geldFeld(el, einheit = '€') {
  return binde(el, artGeld(), { einheit });
}

/**
 * IBAN in Vierergruppen. `el.value` bleibt die IBAN ohne Leerzeichen.
 * @param {HTMLInputElement} el
 * @returns {{wert:Function, setze:Function, zerstoere:Function}}
 */
export function ibanFeld(el) { return binde(el, artIban()); }

/**
 * Steuernummer im üblichen Schnitt. `el.value` bleibt die Ziffernkette.
 * @param {HTMLInputElement} el
 * @returns {{wert:Function, setze:Function, zerstoere:Function}}
 */
export function steuernummerFeld(el) { return binde(el, artSteuernummer()); }
