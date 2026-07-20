/* ImmoCalc — gemeinsame Bausteine: Logo-Sprites, API-Zugriff, Formatierung.
   Wird von allen Seiten geladen; die Sprites werden einmal ins Dokument
   gehaengt, statt sie in jeder Datei zu wiederholen. */

const LOGO_SPRITES = `
<symbol id="lg-villa" viewBox="0 0 96 96"><rect x="2" y="2" width="92" height="92" rx="20" fill="#EDF1F0"/><circle cx="80" cy="54" r="8" fill="#2E7D4F"/><rect x="78.5" y="60" width="3" height="12" fill="#143038"/><polygon points="22,46 48,27 74,46" fill="#143038"/><rect x="57" y="31" width="5" height="11" fill="#143038"/><rect x="29" y="46" width="38" height="26" fill="#0F6E5C"/><rect x="44" y="57" width="8" height="15" fill="#143038"/><rect x="33" y="51" width="8" height="8" fill="#F4B740"/><rect x="55" y="51" width="8" height="8" fill="#F4B740"/></symbol>
<symbol id="lg-bauernhof" viewBox="0 0 96 96"><rect x="2" y="2" width="92" height="92" rx="20" fill="#EDF1F0"/><circle cx="16" cy="56" r="7" fill="#2E7D4F"/><rect x="14.5" y="61" width="3" height="11" fill="#143038"/><rect x="62" y="42" width="11" height="30" fill="#F4B740"/><path d="M62 42 a5.5 5.5 0 0 1 11 0 z" fill="#143038"/><polygon points="24,47 30,33 54,33 60,47" fill="#143038"/><rect x="26" y="47" width="32" height="25" fill="#0F6E5C"/><rect x="36" y="54" width="12" height="18" fill="#143038"/></symbol>
<symbol id="lg-wohnung" viewBox="0 0 96 96"><rect x="2" y="2" width="92" height="92" rx="20" fill="#EDF1F0"/><circle cx="72" cy="55" r="8" fill="#2E7D4F"/><rect x="70.5" y="61" width="3" height="11" fill="#143038"/><polygon points="30,47 48,32 66,47" fill="#143038"/><rect x="34" y="47" width="28" height="25" fill="#0F6E5C"/><rect x="44" y="58" width="9" height="14" fill="#143038"/><rect x="38" y="52" width="9" height="8" fill="#F4B740"/></symbol>
<symbol id="lg-mfhA" viewBox="0 0 96 96"><rect x="2" y="2" width="92" height="92" rx="20" fill="#EDF1F0"/><rect x="17" y="44" width="15" height="28" fill="#143038" opacity=".22"/><circle cx="19" cy="60" r="5" fill="#2E7D4F" opacity=".55"/><rect x="34" y="28" width="30" height="44" fill="#0F6E5C"/><rect x="32" y="26" width="34" height="4" fill="#143038"/><rect x="39" y="34" width="8" height="8" fill="#F4B740"/><rect x="53" y="34" width="8" height="8" fill="#F4B740"/><rect x="39" y="46" width="8" height="8" fill="#F4B740"/><rect x="53" y="46" width="8" height="8" fill="#F4B740"/><rect x="45" y="60" width="8" height="12" fill="#143038"/></symbol>
<symbol id="lg-mfhB" viewBox="0 0 96 96"><rect x="2" y="2" width="92" height="92" rx="20" fill="#EDF1F0"/><circle cx="80" cy="56" r="7" fill="#2E7D4F"/><rect x="78.5" y="61" width="3" height="11" fill="#143038"/><polygon points="16,48 30,34 44,48" fill="#143038"/><rect x="19" y="48" width="22" height="24" fill="#0F6E5C"/><rect x="26" y="60" width="8" height="12" fill="#143038"/><rect x="22" y="52" width="7" height="7" fill="#F4B740"/><polygon points="42,48 56,34 70,48" fill="#143038"/><rect x="45" y="48" width="22" height="24" fill="#0F6E5C"/><rect x="52" y="60" width="8" height="12" fill="#143038"/><rect x="57" y="52" width="7" height="7" fill="#F4B740"/></symbol>
<symbol id="lg-gewerbe" viewBox="0 0 96 96"><rect x="2" y="2" width="92" height="92" rx="20" fill="#EDF1F0"/><circle cx="79" cy="58" r="6" fill="#2E7D4F"/><rect x="77.5" y="63" width="3" height="9" fill="#143038"/><rect x="18" y="40" width="52" height="5" fill="#143038"/><rect x="20" y="45" width="48" height="27" fill="#0F6E5C"/><rect x="27" y="47" width="34" height="6" fill="#143038"/><circle cx="31" cy="50" r="1.6" fill="#F4B740"/><polygon points="24,57 64,57 60,63 28,63" fill="#F4B740"/><rect x="28" y="63" width="13" height="9" fill="#F4B740"/><rect x="47" y="63" width="13" height="9" fill="#F4B740"/><rect x="41" y="61" width="6" height="11" fill="#143038"/></symbol>`;

export const LOGOS = [
  ['lg-villa', 'Villa'],
  ['lg-bauernhof', 'Bauernhof'],
  ['lg-wohnung', 'Einzelne Wohnung'],
  ['lg-mfhA', 'Mehrfamilienhaus'],
  ['lg-mfhB', 'Zwei-/Doppelhaus'],
  ['lg-gewerbe', 'Gewerbe'],
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

export const esc = s => String(s ?? '')
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

/** Fristklasse fuer die Ampel-Chips: rot ab 30, gelb ab 90 Tagen. */
export const fristKlasse = tage =>
  tage == null ? '' : tage < 0 ? 'neg' : tage <= 30 ? 'neg' : tage <= 90 ? 'amber' : 'pos';

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
  document.body.appendChild(dlg);
  dlg.addEventListener('close', () => dlg.remove());
  dlg.showModal();
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
