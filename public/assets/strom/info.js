/* N183 — Erklaertexte in Info-Popups.

   Statt einer Textwand am Kartenanfang sitzt ein kleines i im Titel; ein Tap
   zeigt den Text als Popover. Dieselbe Mechanik wie auf tankstelle.html
   (N181): Karte unter dem Icon auf dem Desktop, Blatt von unten auf dem
   iPhone, Escape/Klick daneben/„Verstanden" schliesst.

   Die Texte sind unveraendert aus der frueheren Inline-Fassung uebernommen —
   nur ihr Ort aendert sich. */
import { esc } from '../immo.js';

const INFO_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
    stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
    aria-hidden="true"><circle cx="12" cy="12" r="10"/>
    <line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>`;

const INFOS = {
  verlauf: { titel: 'Verlauf', text:
    'Die Anschaffung steht als negativer Betrag da und wird Jahr für Jahr '
    + 'aufgefressen: von der Direktnutzung (PV-Strom, den die Mieter bezahlt '
    + 'haben), der Einspeisevergütung und dem E-Tanken. Diese Werte kommen live '
    + 'aus den Nebenkostenjahren; der Balken davor ist der Vorlauf aus den '
    + 'Stammdaten — die Zeit vor der ersten Abrechnung. Durchstößt der Balken '
    + 'die Nulllinie, ist die Anlage amortisiert.' },
  verbrauchsseite: { titel: 'Verbrauchsseite', text:
    'Woher der im Haus verbrauchte Strom kam. Aus diesen drei Mengen zieht die '
    + 'Stromkette im Nebenkostenzeitraum ihre Anteile, und aus ihnen kommt die '
    + 'Autarkiequote.' },
  erzeugerseite: { titel: 'Erzeugerseite', text:
    'Was die Anlage produziert hat und wie viel davon wirklich ins Netz ging — '
    + 'dafür zahlt der Netzbetreiber. In Verbrauch und Autarkie geht diese Seite '
    + 'nicht ein. Ohne eigenen Betrag folgt die Vergütung den EEG-Stufen '
    + '(0–10 kWp 8,2 ct, 10–40 kWp 7,1 ct) auf Basis der Anlagenleistung aus '
    + 'den Stammdaten.' },
  tankstelle: { titel: 'E-Tankstelle', text:
    'Der E-Auto-Strom gehört der PV-Anlage: er wird der ladenden Person '
    + 'berechnet und zahlt auf die Amortisation ein. Der Satz je kWh wird aus '
    + 'den Stromkosten des Abrechnungszeitraums abgeleitet — Netzstrom zum '
    + 'Durchschnittspreis des Netzbezugs, eigener Strom 10 % darunter. Er steht '
    + 'bei der E-Tankstelle.' },
  eigentuemer: { titel: 'PV-Eigentümer', text:
    'Die PV-Anlage ist ein eigenes Investment: sie kann anderen gehören als das '
    + 'Haus. Zugeordnet wird aus den vorhandenen Eigentümern, die Anteile werden '
    + 'in Tausendsteln (‰) vergeben. Ohne Zuordnung gilt die Vorgabe 5/6 + 1/6.' },
};

/* Das i-Icon als String — ein echter <button> mit aria-label, 44 px Touch-
   Ziel, per Tastatur bedienbar. */
export function infoKnopf(key) {
  const i = INFOS[key];
  if (!i) return '';
  return `<button type="button" class="tinfo" data-info="${key}"
    aria-label="${esc(i.titel)}: Erklärung anzeigen"
    title="Erklärung anzeigen">${INFO_ICON}</button>`;
}

let infoOffen = null;

function infoEsc(e) {
  if (e.key !== 'Escape' || !infoOffen) return;
  e.preventDefault();
  e.stopPropagation();
  infoSchliessen();
}

function infoSchliessen() {
  if (!infoOffen) return;
  document.removeEventListener('keydown', infoEsc, true);
  infoOffen.remove();
  infoOffen = null;
}

function infoOeffnen(anker, key) {
  const eintrag = INFOS[key];
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
  // Auf dem Desktop dockt die Karte unter dem Icon an — und klappt darueber,
  // wenn unten kein Platz ist; am Rand wird sie ins Fenster gezogen (wie
  // tankstelle).
  if (!sheet) {
    const r = anker.getBoundingClientRect();
    const cw = card.offsetWidth, ch = card.offsetHeight;
    const left = Math.max(12, Math.min(r.left, window.innerWidth - cw - 12));
    let top = r.bottom + 8;
    if (top + ch > window.innerHeight - 12) top = Math.max(12, r.top - ch - 8);
    card.style.left = `${left}px`;
    card.style.top = `${top}px`;
  }
  overlay.addEventListener('click', e => {
    if (e.target === overlay) infoSchliessen();
  });
  document.addEventListener('keydown', infoEsc, true);
  infoOffen = overlay;
  card.querySelector('.tinfo-ok').focus();
}

/* Ein Faenger am Dokument — das i sitzt in den Titeln, die bei jedem
   Neuzeichnen ersetzt werden; ein Lauscher je Knopf ginge dabei verloren. */
document.addEventListener('click', e => {
  const inf = e.target.closest('[data-info]');
  if (inf) {
    e.preventDefault();
    e.stopPropagation();
    return infoOeffnen(inf, inf.dataset.info);
  }
  const infZu = e.target.closest('[data-info-zu]');
  if (infZu) return infoSchliessen();
});
