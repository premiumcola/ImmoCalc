/* N317 — Baustellen-Banner: solange eine Renovierung läuft, ganz oben auf der
   Objektseite sichtbar, auffälliger als die ruhige Rubrik weiter unten. Genau
   dann wird am häufigsten gescannt (Rechnungen der laufenden Baustelle) —
   deshalb der Alarmton, nicht die sonst übliche Zurückhaltung. */

import { esc } from '../immo.js';
import { zeitraumText, einheitenText } from './daten.js';

const WARNDREIECK = `<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"
  ><path stroke="currentColor" stroke-width="1.7" fill="none" stroke-linecap="round"
    stroke-linejoin="round" d="M12 3.6 21.3 20H2.7L12 3.6Z"/>
  <path stroke="currentColor" stroke-width="1.9" stroke-linecap="round" d="M12 9.7v4.6"/>
  <circle cx="12" cy="17" r="1" fill="currentColor"/></svg>`;

/** Läuft `r` gerade — heute zwischen `von` (oder immer) und `bis` (oder
 *  offen) und nicht als abgeschlossen markiert? */
function laeuft(r, heute) {
  if (r.abgeschlossen) return false;
  if (r.von && r.von > heute) return false;
  if (r.bis && r.bis < heute) return false;
  return true;
}

/** Das Banner für objekt.html — leer, wenn keine Renovierung gerade läuft. */
export function baustellenBannerHtml(slug, liste) {
  const heute = new Date().toISOString().slice(0, 10);
  const aktiv = (Array.isArray(liste) ? liste : []).filter(r => laeuft(r, heute));
  if (!aktiv.length) return '';

  const erste = aktiv[0];
  const titel = aktiv.length === 1
    ? `Baustelle: ${esc(erste.name)}`
    : `${aktiv.length} Baustellen aktiv`;
  const sub = aktiv.length === 1
    ? [zeitraumText(erste.von, erste.bis), einheitenText(erste.einheiten)]
        .filter(Boolean).join(' · ')
    : aktiv.map(r => r.name).join(' · ');
  const ziel = aktiv.length === 1
    ? `renovierung.html?o=${encodeURIComponent(slug)}&r=${erste.id}`
    : `renovierung.html?o=${encodeURIComponent(slug)}`;

  return `<a class="baustelle-banner" href="${ziel}">
      <span class="bb-ikon">${WARNDREIECK}</span>
      <span class="bb-text">
        <span class="bb-titel">${titel}</span>
        <span class="bb-sub">${esc(sub)}</span>
      </span>
      <span class="bb-pfeil">›</span>
    </a>`;
}
