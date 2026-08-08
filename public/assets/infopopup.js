/* infopopup.js — das kleine i und sein Popup, einmal fuer alle.

   N288 — dieselbe Mechanik stand zweimal im Haus (`strom/info.js`,
   `tankstelle/infos.js`), Zeile fuer Zeile gleich: Karte unter dem Icon auf
   dem Desktop, Blatt von unten auf dem iPhone, Escape/Klick daneben/
   „Verstanden" schliesst. Jetzt liegt sie hier; die beiden Ordner halten nur
   noch ihre Texte.

   Und sie behebt dabei einen echten Fehler: beide Fassungen haengten das
   Popup an `document.body`. Ein per `showModal()` geoeffneter <dialog> liegt
   in der Top-Layer — DARUEBER kommt kein z-index, das Popup war innerhalb
   eines Dialogs schlicht unsichtbar. Deshalb sucht `wirt()` den naechsten
   offenen Dialog und haengt das Popup dort hinein; gibt es keinen, bleibt es
   am Body. Ein `position:fixed`-Kind wird von einem Dialog nicht beschnitten,
   die Optik aendert sich also nicht.

   Die Optik selbst (`.tinfo`, `.tinfo-overlay`, `.tinfo-card`, `.tinfo-ok`)
   steht weiter in der jeweiligen Seite. */
import { esc } from './immo.js';

export const INFO_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
    stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
    aria-hidden="true"><circle cx="12" cy="12" r="10"/>
    <line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>`;

/* Nur ein Popup zur Zeit — modulweit, damit sich zwei Info-Verzeichnisse auf
   derselben Seite nicht gegenseitig ueberdecken. */
let offen = null;

function beiEscape(e) {
  if (e.key !== 'Escape' || !offen) return;
  e.preventDefault();
  e.stopPropagation();
  infoSchliessen();
}

export function infoSchliessen() {
  if (!offen) return;
  document.removeEventListener('keydown', beiEscape, true);
  offen.remove();
  offen = null;
}

/* Wohin das Popup gehaengt wird: in den naechsten offenen Dialog, sonst an den
   Body. `closest` faengt den Fall mit, dass der Knopf tief im Dialog sitzt. */
function wirt(anker) {
  const dlg = anker && anker.closest ? anker.closest('dialog[open]') : null;
  return dlg || document.body;
}

/* Ein Eintrag ist `{ titel, text }` — woher er kommt, entscheidet der
   Aufrufer. */
function oeffnen(anker, eintrag) {
  if (!eintrag || !eintrag.text) return;
  infoSchliessen();
  const sheet = window.matchMedia('(max-width:700px)').matches;
  const overlay = document.createElement('div');
  overlay.className = 'tinfo-overlay' + (sheet ? ' sheet' : '');
  const karte = document.createElement('div');
  karte.className = 'tinfo-card' + (sheet ? ' sheet' : '');
  karte.setAttribute('role', 'dialog');
  karte.setAttribute('aria-label', eintrag.titel || 'Erklärung');
  karte.innerHTML = `<div class="tinfo-titel">${esc(eintrag.titel || '')}</div>
    <p class="tinfo-text">${esc(eintrag.text)}</p>
    <button type="button" class="tinfo-ok" data-info-zu>Verstanden</button>`;
  overlay.appendChild(karte);
  wirt(anker).appendChild(overlay);
  // Auf dem Desktop dockt die Karte unter dem Icon an — und klappt darueber,
  // wenn unten kein Platz ist; am Rand wird sie ins Fenster gezogen.
  if (!sheet && anker) {
    const r = anker.getBoundingClientRect();
    const kb = karte.offsetWidth, kh = karte.offsetHeight;
    const links = Math.max(12, Math.min(r.left, window.innerWidth - kb - 12));
    let oben = r.bottom + 8;
    if (oben + kh > window.innerHeight - 12) oben = Math.max(12, r.top - kh - 8);
    karte.style.left = `${links}px`;
    karte.style.top = `${oben}px`;
  }
  overlay.addEventListener('click', e => {
    if (e.target === overlay) infoSchliessen();
  });
  document.addEventListener('keydown', beiEscape, true);
  offen = overlay;
  karte.querySelector('.tinfo-ok').focus();
}

/* Das i als String — ein echter <button> mit aria-label, 44 px Touch-Ziel,
   per Tastatur bedienbar. */
function knopfHtml(titel, attribute) {
  return `<button type="button" class="tinfo" ${attribute}
    aria-label="${esc(titel)}: Erklärung anzeigen"
    title="Erklärung anzeigen">${INFO_ICON}</button>`;
}

/**
 * Ein Info-Modul fuer ein Text-Verzeichnis `{ schluessel: {titel, text} }`.
 *
 * Liefert die vier Bausteine, die eine Seite braucht — und `faengerAnhaengen`
 * fuer Seiten, die den Klick-Faenger nicht selbst mitbringen. Der Faenger
 * sitzt am Dokument, weil die i-Knoepfe in Titeln stehen, die bei jedem
 * Neuzeichnen ersetzt werden; ein Lauscher je Knopf ginge dabei verloren.
 */
export function infoModul(INFOS = {}) {
  /* Ein dynamischer Knopf traegt seinen Text am Element (`data-info-text`),
     sonst kommt er aus dem Verzeichnis. */
  const eintragVon = (anker, key) => anker && anker.dataset
    && anker.dataset.infoText != null
    ? { titel: anker.dataset.infoTitel || '', text: anker.dataset.infoText }
    : INFOS[key];

  const infoKnopf = key => {
    const i = INFOS[key];
    return i ? knopfHtml(i.titel, `data-info="${esc(key)}"`) : '';
  };

  /* Ein Info-Knopf mit dynamischem Text (Satz-Herkunft, Benzin-Annahme):
     dieselbe Mechanik, der Inhalt kommt aber aus den Daten. */
  const infoKnopfText = (titel, text) => text
    ? knopfHtml(titel, `data-info="" data-info-titel="${esc(titel)}"`
        + ` data-info-text="${esc(text)}"`)
    : '';

  const infoOeffnen = (anker, key) => oeffnen(anker, eintragVon(anker, key));

  function faengerAnhaengen() {
    document.addEventListener('click', e => {
      const inf = e.target.closest('[data-info]');
      if (inf) {
        e.preventDefault();
        e.stopPropagation();
        return infoOeffnen(inf, inf.dataset.info);
      }
      if (e.target.closest('[data-info-zu]')) infoSchliessen();
    });
  }

  return { infoKnopf, infoKnopfText, infoOeffnen, infoSchliessen,
           faengerAnhaengen };
}
