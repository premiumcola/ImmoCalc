/* N181 — Erklärtexte in Info-Popups. Die langen Fließtexte am Kartenanfang
   wandern hinter ein kleines i am jeweiligen Titel; ein Tap zeigt den Text als
   Popover. Dieselbe Mechanik und Optik wie die Lexikon-Hilfe in immo.js (nur
   gelesen): Karte unter dem Icon auf dem Desktop, Blatt von unten auf dem
   iPhone, Escape/Klick daneben schließt. Die Texte sind unverändert — nur ihr
   Ort ändert sich; die Ansicht bleibt ruhig ohne die Wand. */
import { esc } from '../immo.js';

const INFO_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
    stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
    aria-hidden="true"><circle cx="12" cy="12" r="10"/>
    <line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>`;

export const INFOS = {
  verlauf: { titel: 'Verlauf', text:
    'Wie viel je Monat geladen wurde — und woher der Strom kam: zugekaufter '
    + 'Netzstrom, eigener Strom direkt vom Dach und aus dem Akku. Über alle '
    + 'Monate hinweg, nicht nur über ein Jahr. Die Zahlen holt die Wallbox '
    + 'selbst; fehlt sie, treten die erfassten Ladungen an ihre Stelle.' },
  abrechnung: { titel: 'Abrechnung', text:
    'Was jeder Nutzer geladen hat, zu welchem Satz und was er zahlt. Der Satz '
    + 'wird nicht eingegeben, sondern aus den Stromkosten des Zeitraums '
    + 'gerechnet: Netzstrom zu seinem Durchschnittspreis — Rechnungsbetrag '
    + 'geteilt durch die bezogenen kWh, Grundgebühr inbegriffen — und eigener '
    + 'Strom aus PV und Akku etwas darunter. Vor dem Versand zeigt die Vorschau, '
    + 'was ankommt.' },
  zuordnen: { titel: 'Ladungen zuordnen', text:
    'Die Wallbox weiß, wie viel geladen wurde — aber nicht, von wem. Diese '
    + 'Zuordnung ist die Grundlage der Abrechnung. Bei mehreren Nutzern: leg je '
    + 'Person einen Zeitraum fest, statt jede Ladung einzeln zuzuordnen. Jede '
    + 'Ladung geht an den, in dessen Zeitraum ihr Datum fällt. Einzelne Ladungen '
    + 'schließt du unten aus.' },
  nutzer: { titel: 'Nutzer', text:
    'Wer an dieser Ladestation lädt. Beliebig viele, jederzeit ergänzbar — und '
    + 'nicht zwangsläufig Eigentümer der Immobilie. Die E-Mail-Adresse braucht '
    + 'es für die Quartalsabrechnung.' },
  autoversand: { titel: 'Automatisch verschicken', text:
    'Einen Tag nach Quartalsende geht die Abrechnung automatisch an jeden '
    + 'Nutzer mit Adresse, Ladung und Satz — als Mail mit PDF im Anhang.' },
};

/* Das i-Icon als String — für die statischen Titel (Skelett) wie für die im JS
   gebauten (Autoversand-Schalter). Ein echter <button> mit aria-label, 44 px
   Touch-Ziel, per Tastatur bedienbar. */
export function infoKnopf(key) {
  const i = INFOS[key];
  if (!i) return '';
  return `<button type="button" class="tinfo" data-info="${key}"
    aria-label="${esc(i.titel)}: Erklärung anzeigen"
    title="Erklärung anzeigen">${INFO_ICON}</button>`;
}

/* N186 — ein Info-Knopf mit dynamischem Text (Satz-Herkunft, Benzin-Annahme):
   dieselbe Popup-Mechanik, der Inhalt kommt aber aus den Daten des Zeitraums,
   nicht aus dem statischen INFOS-Verzeichnis. Kein neuer Text — nur ein Ort. */
export function infoKnopfText(titel, text) {
  if (!text) return '';
  return `<button type="button" class="tinfo" data-info=""
    data-info-titel="${esc(titel)}" data-info-text="${esc(text)}"
    aria-label="${esc(titel)}: Erklärung anzeigen"
    title="Erklärung anzeigen">${INFO_ICON}</button>`;
}

let infoOffen = null;
function infoEsc(e) {
  if (e.key !== 'Escape' || !infoOffen) return;
  e.preventDefault();
  e.stopPropagation();
  infoSchliessen();
}
export function infoSchliessen() {
  if (!infoOffen) return;
  document.removeEventListener('keydown', infoEsc, true);
  infoOffen.remove();
  infoOffen = null;
}
export function infoOeffnen(anker, key) {
  // N186 — ein dynamischer Knopf traegt seinen Text am Element (data-info-text);
  // sonst kommt er aus dem statischen INFOS-Verzeichnis.
  const eintrag = anker.dataset.infoText != null
    ? { titel: anker.dataset.infoTitel || '', text: anker.dataset.infoText }
    : INFOS[key];
  if (!eintrag) return;
  infoSchliessen();
  const sheet = window.matchMedia('(max-width:700px)').matches;
  const overlay = document.createElement('div');
  overlay.className = 'tinfo-overlay' + (sheet ? ' sheet' : '');
  const card = document.createElement('div');
  card.className = 'tinfo-card' + (sheet ? ' sheet' : '');
  card.setAttribute('role', 'dialog');
  card.setAttribute('aria-label', eintrag.titel);
  card.innerHTML = `<div class="tinfo-titel">${esc(eintrag.titel)}</div>
    <p class="tinfo-text">${esc(eintrag.text)}</p>
    <button type="button" class="tinfo-ok" data-info-zu>Verstanden</button>`;
  overlay.appendChild(card);
  document.body.appendChild(overlay);
  // Auf dem Desktop dockt die Karte unter dem Icon an — und klappt darüber, wenn
  // unten kein Platz ist; am Rand wird sie ins Fenster gezogen (wie immo.js).
  if (!sheet) {
    const r = anker.getBoundingClientRect();
    const cw = card.offsetWidth, ch = card.offsetHeight;
    const left = Math.max(12, Math.min(r.left, window.innerWidth - cw - 12));
    let top = r.bottom + 8;
    if (top + ch > window.innerHeight - 12) top = Math.max(12, r.top - ch - 8);
    card.style.left = `${left}px`;
    card.style.top = `${top}px`;
  }
  overlay.addEventListener('click', e => { if (e.target === overlay) infoSchliessen(); });
  document.addEventListener('keydown', infoEsc, true);
  infoOffen = overlay;
  card.querySelector('.tinfo-ok').focus();
}
