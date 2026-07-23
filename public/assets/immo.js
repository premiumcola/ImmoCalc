/* ImmoCalc — gemeinsame Bausteine: Logo-Sprites, API-Zugriff, Formatierung.
   Wird von allen Seiten geladen; die Sprites werden einmal ins Dokument
   gehaengt, statt sie in jeder Datei zu wiederholen. */

// Das Grundstueck kam spaeter dazu und liegt bei den uebrigen Grundstuecks-
// Symbolen. Importiert statt kopiert — zwei Fassungen desselben Logos wuerden
// frueher oder later auseinanderlaufen.
import { GRUNDSTUECK_LOGO, GRUNDSTUECK_SPRITE } from './kostenicons.js';

const LOGO_SPRITES = `
<symbol id="lg-villa" viewBox="0 0 96 96"><rect x="2" y="2" width="92" height="92" rx="20" fill="#EDF1F0"/><circle cx="80" cy="54" r="8" fill="#2E7D4F"/><rect x="78.5" y="60" width="3" height="12" fill="#143038"/><polygon points="22,46 48,27 74,46" fill="#143038"/><rect x="57" y="31" width="5" height="11" fill="#143038"/><rect x="29" y="46" width="38" height="26" fill="#0F6E5C"/><rect x="44" y="57" width="8" height="15" fill="#143038"/><rect x="33" y="51" width="8" height="8" fill="#F4B740"/><rect x="55" y="51" width="8" height="8" fill="#F4B740"/></symbol>
<symbol id="lg-bauernhof" viewBox="0 0 96 96"><rect x="2" y="2" width="92" height="92" rx="20" fill="#EDF1F0"/><circle cx="16" cy="56" r="7" fill="#2E7D4F"/><rect x="14.5" y="61" width="3" height="11" fill="#143038"/><rect x="62" y="42" width="11" height="30" fill="#F4B740"/><path d="M62 42 a5.5 5.5 0 0 1 11 0 z" fill="#143038"/><polygon points="24,47 30,33 54,33 60,47" fill="#143038"/><rect x="26" y="47" width="32" height="25" fill="#0F6E5C"/><rect x="36" y="54" width="12" height="18" fill="#143038"/></symbol>
<symbol id="lg-wohnung" viewBox="0 0 96 96"><rect x="2" y="2" width="92" height="92" rx="20" fill="#EDF1F0"/><circle cx="72" cy="55" r="8" fill="#2E7D4F"/><rect x="70.5" y="61" width="3" height="11" fill="#143038"/><polygon points="30,47 48,32 66,47" fill="#143038"/><rect x="34" y="47" width="28" height="25" fill="#0F6E5C"/><rect x="44" y="58" width="9" height="14" fill="#143038"/><rect x="38" y="52" width="9" height="8" fill="#F4B740"/></symbol>
<symbol id="lg-mfhA" viewBox="0 0 96 96"><rect x="2" y="2" width="92" height="92" rx="20" fill="#EDF1F0"/><rect x="17" y="44" width="15" height="28" fill="#143038" opacity=".22"/><circle cx="19" cy="60" r="5" fill="#2E7D4F" opacity=".55"/><rect x="34" y="28" width="30" height="44" fill="#0F6E5C"/><rect x="32" y="26" width="34" height="4" fill="#143038"/><rect x="39" y="34" width="8" height="8" fill="#F4B740"/><rect x="53" y="34" width="8" height="8" fill="#F4B740"/><rect x="39" y="46" width="8" height="8" fill="#F4B740"/><rect x="53" y="46" width="8" height="8" fill="#F4B740"/><rect x="45" y="60" width="8" height="12" fill="#143038"/></symbol>
<symbol id="lg-mfhB" viewBox="0 0 96 96"><rect x="2" y="2" width="92" height="92" rx="20" fill="#EDF1F0"/><circle cx="80" cy="56" r="7" fill="#2E7D4F"/><rect x="78.5" y="61" width="3" height="11" fill="#143038"/><polygon points="16,48 30,34 44,48" fill="#143038"/><rect x="19" y="48" width="22" height="24" fill="#0F6E5C"/><rect x="26" y="60" width="8" height="12" fill="#143038"/><rect x="22" y="52" width="7" height="7" fill="#F4B740"/><polygon points="42,48 56,34 70,48" fill="#143038"/><rect x="45" y="48" width="22" height="24" fill="#0F6E5C"/><rect x="52" y="60" width="8" height="12" fill="#143038"/><rect x="57" y="52" width="7" height="7" fill="#F4B740"/></symbol>
<symbol id="lg-gewerbe" viewBox="0 0 96 96"><rect x="2" y="2" width="92" height="92" rx="20" fill="#EDF1F0"/><circle cx="79" cy="58" r="6" fill="#2E7D4F"/><rect x="77.5" y="63" width="3" height="9" fill="#143038"/><rect x="18" y="40" width="52" height="5" fill="#143038"/><rect x="20" y="45" width="48" height="27" fill="#0F6E5C"/><rect x="27" y="47" width="34" height="6" fill="#143038"/><circle cx="31" cy="50" r="1.6" fill="#F4B740"/><polygon points="24,57 64,57 60,63 28,63" fill="#F4B740"/><rect x="28" y="63" width="13" height="9" fill="#F4B740"/><rect x="47" y="63" width="13" height="9" fill="#F4B740"/><rect x="41" y="61" width="6" height="11" fill="#143038"/></symbol>
${GRUNDSTUECK_SPRITE}`;

export const LOGOS = [
  ['lg-villa', 'Villa'],
  ['lg-bauernhof', 'Bauernhof'],
  ['lg-wohnung', 'Einzelne Wohnung'],
  ['lg-mfhA', 'Mehrfamilienhaus'],
  ['lg-mfhB', 'Zwei-/Doppelhaus'],
  ['lg-gewerbe', 'Gewerbe'],
  [GRUNDSTUECK_LOGO, 'Grundstück'],
];

/** Haengt die Logo-Symbole einmalig ins Dokument. */
export function installLogos() {
  if (document.getElementById('immo-sprites')) return;
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.id = 'immo-sprites';
  svg.setAttribute('width', '0');
  svg.setAttribute('height', '0');
  svg.setAttribute('aria-hidden', 'true');
  svg.style.position = 'absolute';
  svg.innerHTML = `<defs>${LOGO_SPRITES}</defs>`;
  document.body.prepend(svg);
}

export const logoSvg = (id, cls = '') =>
  `<svg class="${cls}" viewBox="0 0 96 96"><use href="#${id}"/></svg>`;

/** Bezeichnung eines Gebaeudetyps, mit Rueckfall auf Strich. */
export const logoLabel = id => (LOGOS.find(l => l[0] === id) || [, '—'])[1];

/* ---- API ---- */
export async function api(pfad, optionen = {}) {
  const antwort = await fetch('/api' + pfad, {
    headers: { 'Content-Type': 'application/json' },
    ...optionen,
    body: optionen.body ? JSON.stringify(optionen.body) : undefined,
  });
  if (!antwort.ok) {
    // FastAPI liefert die Ursache in `detail` — die ist fuer den Nutzer
    // deutlich hilfreicher als der blosse Statuscode.
    const grund = await antwort.json().then(k => k.detail).catch(() => null);
    throw new Error(grund || `${antwort.status} ${pfad}`);
  }
  return antwort.status === 204 ? null : antwort.json();
}

/* ---- Formatierung ---- */
export const eur = n =>
  (n ?? 0).toLocaleString('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' €';

export const eurKurz = n => {
  const v = n ?? 0;
  if (Math.abs(v) >= 10000) return Math.round(v / 1000).toLocaleString('de-DE') + 'k €';
  return Math.round(v).toLocaleString('de-DE') + ' €';
};

/**
 * Voller Betrag ohne Cent: „315.000 €“.
 *
 * Fuer Werte, bei denen die Groessenordnung nicht reicht und der Cent nur
 * stoert — Verkehrswert, Restschuld, Eigenkapital. Bei einem Hauswert sind
 * zwei Nachkommastellen eine Genauigkeit, die es gar nicht gibt.
 */
export const eurVoll = n =>
  (n == null ? 0 : Math.round(n)).toLocaleString('de-DE') + ' €';

/**
 * Miteigentumsanteil lesbar: „500 ‰", „333,3 ‰" — nie 333,29999999. Bewusst
 * ohne Tausenderpunkt: „1.000 ‰" liest sich sonst wie eintausend Komma null.
 */
export const promille = n => (n ?? 0).toLocaleString('de-DE',
  { maximumFractionDigits: 1, useGrouping: false }) + ' ‰';

export const esc = s => String(s ?? '')
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

/** Fristklasse fuer die Ampel-Chips: rot ab 30, gelb ab 90 Tagen. */
export const fristKlasse = tage =>
  tage == null ? '' : tage < 0 ? 'neg' : tage <= 30 ? 'neg' : tage <= 90 ? 'amber' : 'pos';

/* ---- Navigation (CCXVI) -------------------------------------------------
   Die Leiste stand wortgleich in acht Seiten. Jetzt liegt sie einmal hier:
   `installNav()` baut sie aus `NAV` und haengt sie anstelle eines
   Platzhalter-Elements `[data-nav]` ein. */

export const NAV = [
  ['Objekte', 'index.html', '▤'],
  ['Dokumente', 'eingang.html', '▣'],
  ['Wert', 'wertentwicklung.html', '◔'],
  ['Nebenkosten', 'nebenkosten.html', '≡'],
  ['Eigentümer', 'eigentuemer.html', '☗'],
  // CCXL — das Immobilien-Lexikon. Steht bewusst vor „Einstellungen", damit die
  // Einstellungen der letzte Eintrag bleiben; auf dem Handy wandert es dadurch
  // von selbst hinter „Mehr" (Index ≥ SICHTBAR).
  ['Lexikon', 'lexikon.html', '?'],
  ['Einstellungen', 'settings.html', '⚙'],
];

// objekt.html und zeitraum.html stehen selbst nicht in der Leiste — sie
// sind Detailansichten der Objektliste und zaehlen fuer die Markierung als
// "Objekte".
const NAV_ALIAS = { 'objekt.html': 'index.html', 'zeitraum.html': 'index.html' };

/** Haengt die Navigationsleiste anstelle von `[data-nav]` ins Dokument. */
export function installNav() {
  const platz = document.querySelector('[data-nav]');
  if (!platz) return;
  const datei = location.pathname.split('/').pop() || 'index.html';
  const aktiv = NAV_ALIAS[datei] || datei;
  const nav = document.createElement('nav');
  nav.className = 'nav';
  nav.innerHTML = `<a class="brand" href="index.html">ImmoCalc</a>`
    + NAV.map(([label, href, icon]) => `<a href="${href}"${
        href === aktiv ? ' aria-current="page"' : ''
      }><span class="ni">${icon}</span>${label}</a>`).join('');
  platz.replaceWith(nav);
  navAufraeumen();
}

/* ---- Navigation auf dem Handy ------------------------------------------
   Sechs Einträge nebeneinander sind auf einem iPhone zu eng: die
   Beschriftungen schrumpfen auf 8,5 px und die Ziele werden schmaler als der
   Daumen. Auf schmalen Schirmen bleiben deshalb die vier täglichen Wege
   stehen, der Rest wandert hinter „Mehr" — ein Fingertipp mehr für zwei
   Seiten, die man selten braucht.

   Das passiert hier und nicht in den Seiten, damit die Leiste an einer
   einzigen Stelle gepflegt wird. */

const SICHTBAR = 4;                    // so viele Einträge bleiben stehen
const ENG = window.matchMedia('(max-width: 700px)');

function navAufraeumen() {
  const nav = document.querySelector('nav.nav');
  if (!nav) return;
  const eintraege = [...nav.querySelectorAll('a:not(.brand)')];
  if (eintraege.length <= SICHTBAR + 1) return;   // nichts zu verstecken

  let mehr = nav.querySelector('.mehr');
  if (!mehr) {
    mehr = document.createElement('button');
    mehr.type = 'button';
    mehr.className = 'mehr';
    mehr.setAttribute('aria-haspopup', 'dialog');
    mehr.innerHTML = '<span class="ni">⋯</span>Mehr';
    mehr.addEventListener('click', () => mehrOeffnen(eintraege.slice(SICHTBAR)));
    nav.appendChild(mehr);
  }

  const versteckt = eintraege.slice(SICHTBAR);
  for (const [i, a] of eintraege.entries()) {
    a.classList.toggle('weg', ENG.matches && i >= SICHTBAR);
  }
  mehr.classList.toggle('an', ENG.matches);
  // Steckt die aktuelle Seite hinter „Mehr", muss man das sehen
  mehr.classList.toggle('hier',
    versteckt.some(a => a.getAttribute('aria-current') === 'page'));
}

function mehrOeffnen(eintraege) {
  const dlg = baueDialog(`
    <div class="dt">Mehr</div>
    <div class="mehrliste">${eintraege.map(a => `
      <a href="${a.getAttribute('href')}"
         ${a.getAttribute('aria-current') ? 'aria-current="page"' : ''}>
        <span class="ni">${a.querySelector('.ni')?.textContent ?? ''}</span>
        ${a.lastChild?.textContent?.trim() ?? ''}
      </a>`).join('')}</div>
    <button class="btn leise" data-nein>Schließen</button>`);
  dlg.querySelector('[data-nein]').addEventListener('click', () => dlg.close());
}

// Auch bei Drehung und beim Wechsel auf ein breiteres Fenster nachziehen
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', navAufraeumen);
} else {
  navAufraeumen();
}
ENG.addEventListener('change', navAufraeumen);

/* ---- Meldungen und Rückfragen im Design der App -------------------------
   `alert` und `confirm` zeichnet der Browser: graue Systemkästen, die mit der
   Seite nichts zu tun haben. Beides hier selbst gebaut — und die Rückfrage vor
   dem Löschen als Schiebe-Regler, damit ein zweiter Klick nicht aus Versehen
   passieren kann. */

/** Kurze Rückmeldung am unteren Rand. Verschwindet von selbst. */
export function melde(text, art = '') {
  let feld = document.getElementById('immo-melder');
  if (!feld) {
    feld = document.createElement('div');
    feld.id = 'immo-melder';
    feld.className = 'melder';
    feld.setAttribute('role', 'status');
    feld.setAttribute('aria-live', 'polite');
    document.body.appendChild(feld);
  }
  feld.className = `melder an ${art}`;
  feld.textContent = text;
  clearTimeout(feld._zeit);
  feld._zeit = setTimeout(() => { feld.className = 'melder'; }, 5200);
}

function baueDialog(inhalt) {
  const dlg = document.createElement('dialog');
  dlg.className = 'immo-dlg';
  dlg.innerHTML = inhalt;
  // Sichtbares Schließen-Kreuz oben rechts — überall, wo der Dialog nicht schon
  // selbst eines mitbringt. Sonst muss man zum Abbrechen erst nach unten
  // scrollen. Bewusst gut sichtbar (heller Kreis), nicht grau-unscheinbar.
  if (!dlg.querySelector('[data-zu]')) {
    const zu = document.createElement('button');
    zu.type = 'button';
    zu.className = 'immo-dlg-zu';
    zu.setAttribute('aria-label', 'Schließen');
    zu.textContent = '✕';
    zu.addEventListener('click', () => dlg.close());
    dlg.appendChild(zu);
  }
  document.body.appendChild(dlg);
  dlg.addEventListener('close', () => dlg.remove());
  dlg.showModal();
  return dlg;
}

/**
 * Beleg ansehen, ohne die App zu verlassen.
 *
 * Vorher lief das ueber `window.open`: auf dem Telefon oeffnet die
 * Startbildschirm-App damit einen Betrachter ohne Leiste — man sieht das PDF
 * und kommt nicht mehr heraus. Deshalb bleibt der Beleg jetzt im Dialog, mit
 * drei Wegen zurueck: Kreuz, Escape und Tippen neben das Blatt.
 */
export function belegAnsehen(url, titel = 'Beleg') {
  // Vorschau der GANZEN ersten Seite als Bild (serverseitig gerendert), damit
  // sie breitenfüllend in der Seite steht statt beschnitten. Das ↗ öffnet das
  // vollständige Dokument im neuen Tab. Eine Ansicht, kein Zoom-Ärger.
  const vorschauUrl = url.replace('/inhalt', '/vorschau');
  const dlg = baueDialog(
    `<div class="beleg-kopf">
       <span class="bt">${sicher(titel)}</span>
       <a class="bx auf" href="${sicher(url)}" target="_blank" rel="noopener"
          title="Ganzes Dokument im neuen Tab">↗</a>
       <button class="bx" data-zu title="Schließen" aria-label="Schließen">✕</button>
     </div>
     <div class="beleg-flaeche"><div class="beleg-blatt lade">Beleg wird geholt …</div></div>`);
  dlg.classList.add('beleg-dlg');
  dlg.querySelector('[data-zu]').addEventListener('click', () => dlg.close());
  // Tippen neben die Fläche schliesst ebenfalls.
  dlg.addEventListener('click', e => { if (e.target === dlg) dlg.close(); });

  const flaeche = dlg.querySelector('.beleg-flaeche');
  let adresse = null;
  fetch(vorschauUrl)
    .then(antwort => {
      if (!antwort.ok) throw new Error('keine-vorschau');
      return antwort.blob();
    })
    .then(blob => {
      adresse = URL.createObjectURL(blob);
      const bild = document.createElement('img');
      bild.className = 'beleg-bild';
      bild.alt = titel;
      bild.src = adresse;
      flaeche.innerHTML = '';
      flaeche.appendChild(bild);
    })
    .catch(() => {
      flaeche.innerHTML = '<div class="beleg-blatt leer">Für diese Datei gibt '
        + 'es keine Bildvorschau — mit ↗ im neuen Tab öffnen.</div>';
    });

  dlg.addEventListener('close', () => { if (adresse) URL.revokeObjectURL(adresse); });
  return dlg;
}

const sicher = s => String(s ?? '')
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

/**
 * Rückfrage mit mehreren Wegen. `optionen` ist [{wert, text, gefahr, leise}];
 * der erste Eintrag ist der Hauptweg. Liefert den `wert` des Gewählten oder
 * `null` beim Abbrechen.
 */
export function wahl(titel, text, optionen) {
  return new Promise(fertig => {
    const knoepfe = optionen.map((o, i) => `
      <button class="btn ${o.gefahr ? 'gefahr' : (i > 0 || o.leise ? 'leise' : '')}"
              data-wahl="${sicher(o.wert)}"
              ${i > 0 ? 'style="margin-top:8px"' : ''}>${sicher(o.text)}</button>`);
    const dlg = baueDialog(`
      <div class="dt">${sicher(titel)}</div>
      <p>${sicher(text)}</p>
      ${knoepfe.join('')}
      <button class="btn leise" style="margin-top:8px" data-nein>Abbrechen</button>`);

    dlg.addEventListener('click', e => {
      const knopf = e.target.closest('[data-wahl]');
      if (knopf) { fertig(knopf.dataset.wahl); dlg.close(); }
      else if (e.target.closest('[data-nein]')) { fertig(null); dlg.close(); }
    });
    dlg.addEventListener('cancel', () => fertig(null));
  });
}

/** Rückfrage mit zwei Knöpfen. Liefert true, wenn bestätigt wurde. */
export async function frage(titel, text,
                            { knopf = 'Weiter', gefahr = false } = {}) {
  return await wahl(titel, text, [{ wert: 'ja', text: knopf, gefahr }]) === 'ja';
}

/**
 * Rückfrage, die man nicht wegklicken kann: der Griff muss ganz nach rechts
 * geschoben werden. Ein versehentlicher Doppelklick löst nichts aus.
 */
export function schiebeFrage(titel, text, label = 'Zum Löschen schieben') {
  return new Promise(fertig => {
    const dlg = baueDialog(`
      <div class="dt">${sicher(titel)}</div>
      <p>${sicher(text)}</p>
      <div class="schieber" role="button" tabindex="0"
           aria-label="${sicher(label)} — mit den Pfeiltasten nach rechts oder
                        mit der Eingabetaste bestätigen">
        <span class="sl">${sicher(label)}</span>
        <span class="griff" aria-hidden="true">›</span>
      </div>
      <button class="btn leise" data-nein>Abbrechen</button>`);

    const bahn = dlg.querySelector('.schieber');
    const griff = dlg.querySelector('.griff');
    let zieht = false;
    let weg = 0;

    const strecke = () => bahn.clientWidth - griff.offsetWidth - 8;
    const setze = px => {
      weg = Math.max(0, Math.min(strecke(), px));
      griff.style.transform = `translateX(${weg}px)`;
      bahn.style.setProperty('--anteil', (weg / strecke()).toFixed(3));
    };
    const zurueck = () => { griff.style.transition = 'transform .2s'; setze(0);
                            setTimeout(() => { griff.style.transition = ''; }, 220); };

    const ausloesen = () => {
      bahn.classList.add('fertig');
      fertig(true);
      setTimeout(() => dlg.close(), 220);
    };

    // Bewusst ohne setPointerCapture: beim zweiten Zug hintereinander
    // verliert der Griff die Erfassung, und der Regler bleibt auf halbem Weg
    // stehen. Am Fenster zu lauschen ist verlaesslich — auch auf dem iPhone.
    let anfang = 0;

    const bewegt = e => setze(e.clientX - anfang);
    const losgelassen = () => {
      if (!zieht) return;
      zieht = false;
      window.removeEventListener('pointermove', bewegt);
      window.removeEventListener('pointerup', losgelassen);
      window.removeEventListener('pointercancel', losgelassen);
      // Knapp vor dem Ende zählt auch — sonst wird es zur Geduldsprobe.
      if (weg >= strecke() - 4) ausloesen(); else zurueck();
    };

    griff.addEventListener('pointerdown', e => {
      e.preventDefault();
      zieht = true;
      anfang = e.clientX - weg;
      window.addEventListener('pointermove', bewegt);
      window.addEventListener('pointerup', losgelassen);
      window.addEventListener('pointercancel', losgelassen);
    });

    // Ohne Zeigegerät: Pfeiltaste nach rechts oder Eingabetaste
    bahn.addEventListener('keydown', e => {
      if (e.key === 'ArrowRight') { e.preventDefault(); setze(weg + strecke() / 4); }
      else if (e.key === 'ArrowLeft') { e.preventDefault(); setze(weg - strecke() / 4); }
      else if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); ausloesen(); }
      if (weg >= strecke() - 4) ausloesen();
    });

    dlg.querySelector('[data-nein]').addEventListener('click', () => {
      fertig(false); dlg.close();
    });
    dlg.addEventListener('cancel', () => fertig(false));
  });
}

export const fristText = tage =>
  tage == null ? null : tage < 0 ? `${Math.abs(tage)} T über Frist` : `Frist in ${tage} T`;

/* ---- CCXL: kontextsensitive Hilfe (?-Icon + Lexikon-Popover) -------------
   Ein kleines, unauffälliges ?-Icon neben echten Fachbegriff-Feldern. Beim
   Antippen öffnet ein Popover mit der Kurzerklärung aus dem Lexikon und einem
   Link in den vollen Eintrag.

   Die Wissensbasis (`lexikon-daten.js`) wird bewusst erst beim ersten Öffnen
   dynamisch geladen — sonst zöge jede Seite, die nur ein Formular zeigt, die
   ganze Datei mit. Das Icon selbst entsteht ohne die Daten; gebraucht werden
   sie erst, wenn wirklich jemand fragt. */

let lexikonDaten = null;            // Cache des dynamischen Imports (Promise)
function ladeLexikon() {
  if (!lexikonDaten) lexikonDaten = import('./lexikon-daten.js');
  return lexikonDaten;
}

// feather „help-circle" — flacher Strich-Stil wie die übrigen Icons.
const HILFE_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
    stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
    aria-hidden="true"><circle cx="12" cy="12" r="10"/>
    <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/>
    <line x1="12" y1="17" x2="12.01" y2="17"/></svg>`;

const HILFE_STIL = `
  .immo-hilfe{display:inline-flex;align-items:center;justify-content:center;
    width:44px;height:44px;margin:-12px -8px -12px 0;padding:0;border:none;
    background:none;color:var(--soft,#5A6B70);cursor:pointer;vertical-align:middle;
    border-radius:50%;-webkit-tap-highlight-color:transparent;flex:none}
  .immo-hilfe svg{width:16px;height:16px;display:block}
  .immo-hilfe:hover{color:var(--teal,#0F6E5C)}
  .immo-hilfe:focus-visible{outline:2px solid var(--teal,#0F6E5C);outline-offset:2px}
  .immo-lx-overlay{position:fixed;inset:0;z-index:1200;background:transparent}
  .immo-lx-card{position:fixed;z-index:1201;background:var(--sheet,#fff);
    border-radius:14px;box-shadow:0 22px 55px -14px rgba(22,38,44,.45);
    padding:16px 18px;width:300px;max-width:calc(100vw - 24px);
    font-family:var(--body,system-ui);color:var(--ink,#16262C)}
  .immo-lx-titel{font:700 15px var(--disp,var(--body));letter-spacing:-.01em;
    margin-bottom:6px}
  .immo-lx-kurz{font:400 13px/1.5 var(--body,system-ui);
    color:var(--ink,#16262C);margin:0 0 12px}
  .immo-lx-mehr{display:inline-block;min-height:36px;line-height:36px;
    font:600 12.5px var(--disp,var(--body));color:var(--teal-d,#0B5648);
    text-decoration:none}
  .immo-lx-mehr:hover{text-decoration:underline}
  @media (max-width:700px){
    .immo-lx-overlay.sheet{background:rgba(22,38,44,.35)}
    .immo-lx-card.sheet{left:0;right:0;bottom:0;top:auto;width:auto;
      max-width:none;border-radius:18px 18px 0 0;
      padding:20px 20px calc(20px + env(safe-area-inset-bottom));
      animation:immo-lx-auf .18s ease-out}
    .immo-lx-mehr{min-height:44px;line-height:44px}
  }
  @keyframes immo-lx-auf{from{transform:translateY(100%)}to{transform:translateY(0)}}`;

function installHilfeStil() {
  if (document.getElementById('immo-hilfe-stil')) return;
  const s = document.createElement('style');
  s.id = 'immo-hilfe-stil';
  s.textContent = HILFE_STIL;
  document.head.appendChild(s);
}

let hilfeOffen = null;
// Escape schliesst zuerst nur das Popover — und nicht gleich den Dialog
// darunter mit. Deshalb in der Capture-Phase abgefangen und die
// Standardaktion (Dialog schliessen) unterbunden, solange ein Popover offen ist.
function hilfeEsc(e) {
  if (e.key !== 'Escape' || !hilfeOffen) return;
  e.preventDefault();
  e.stopPropagation();
  hilfeSchliessen();
}
function hilfeSchliessen() {
  if (!hilfeOffen) return;
  document.removeEventListener('keydown', hilfeEsc, true);
  hilfeOffen.remove();
  hilfeOffen = null;
}

function zeigePopover(anker, eintrag) {
  hilfeSchliessen();
  const sheet = window.matchMedia('(max-width:700px)').matches;
  const overlay = document.createElement('div');
  overlay.className = 'immo-lx-overlay' + (sheet ? ' sheet' : '');
  const card = document.createElement('div');
  card.className = 'immo-lx-card' + (sheet ? ' sheet' : '');
  card.innerHTML = `
    <div class="immo-lx-titel">${sicher(eintrag.begriff)}</div>
    <p class="immo-lx-kurz">${sicher(eintrag.kurz)}</p>
    <a class="immo-lx-mehr" href="lexikon.html#${encodeURIComponent(eintrag.id)}"
       >Mehr im Lexikon →</a>`;
  overlay.appendChild(card);
  // Sitzt das Icon in einem modalen <dialog>, liegt der ganze Dialog in der
  // Top-Layer — ein an <body> gehängtes Popover verschwände dahinter. Deshalb
  // wird es in den offenen Dialog gehängt, sonst an <body>.
  (anker.closest('dialog[open]') || document.body).appendChild(overlay);

  // Auf dem Desktop dockt die Karte unter dem Icon an — und klappt darüber,
  // wenn unten kein Platz ist. Am Rand wird sie ins Fenster gezogen.
  if (!sheet) {
    const r = anker.getBoundingClientRect();
    const cw = card.offsetWidth, ch = card.offsetHeight;
    let left = Math.max(12, Math.min(r.left, window.innerWidth - cw - 12));
    let top = r.bottom + 8;
    if (top + ch > window.innerHeight - 12) top = Math.max(12, r.top - ch - 8);
    card.style.left = `${left}px`;
    card.style.top = `${top}px`;
  }

  overlay.addEventListener('click', e => { if (e.target === overlay) hilfeSchliessen(); });
  document.addEventListener('keydown', hilfeEsc, true);
  hilfeOffen = overlay;
  card.querySelector('.immo-lx-mehr').focus();
}

/**
 * Ein ?-Icon-Element zu einem Lexikon-Begriff. Klick öffnet das Popover.
 * Robust: Fehlt der Begriff in der Wissensbasis, verschwindet das Icon beim
 * ersten Antippen lautlos, statt einen Fehler zu werfen.
 */
export function hilfe(begriffId) {
  installHilfeStil();
  const b = document.createElement('button');
  b.type = 'button';
  b.className = 'immo-hilfe';
  b.dataset.begriff = begriffId;
  b.setAttribute('aria-label', 'Erklärung anzeigen');
  b.innerHTML = HILFE_ICON;
  b.addEventListener('click', e => {
    e.preventDefault();
    e.stopPropagation();
    ladeLexikon()
      .then(mod => {
        const eintrag = (mod.BEGRIFFE || []).find(x => x.id === begriffId);
        if (!eintrag) { b.remove(); return; }   // (noch) kein Eintrag → Icon weg
        zeigePopover(b, eintrag);
      })
      .catch(() => { /* Wissensbasis nicht ladbar — dann eben still */ });
  });
  return b;
}

/**
 * Ersetzt alle Platzhalter `[data-hilfe="<id>"]` unterhalb von `root` durch
 * ein ?-Icon. So bleibt das Markup der Seiten schlicht — sie setzen nur den
 * Platzhalter, das Icon baut diese Stelle.
 */
export function installHilfe(root = document) {
  root.querySelectorAll('[data-hilfe]').forEach(halter => {
    const id = halter.getAttribute('data-hilfe');
    if (id) halter.replaceWith(hilfe(id));
  });
}
