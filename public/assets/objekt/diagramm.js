/* N216 — Miet-/NK-Diagramm über der Übersicht: Säulen für Kalt und NK, Linie
   für €/m² (bei Bedarf). N20/N21 — grafischer Einstieg statt Kennzahlen-
   Kacheln. Bei 30+ Monaten Historie wird auf Quartale verdichtet. */

import { esc, eur } from '../immo.js';
import { kostenIcon } from '../kostenicons.js';
import { proJahr } from '../objekt-format.js?v=2';
import { mietChart, legende } from '../charts.js';
import { MONATS_KURZ } from './state.js';

/* N20/N21 — grafischer Einstieg statt Kennzahlen-Kacheln: der Miet- und
   Nebenkostenverlauf aus den Mietverhältnissen. Ein Mietverhältnis steuert
   seinen Monatsbetrag (Turnus normalisiert) zu jedem Monat bei, den es abdeckt
   (ab_datum … bis_datum ||heute). Ein Monat ohne aktives Verhältnis bleibt leer
   — das ist der Leerstand und wird als solcher gezeigt.

   `flaeche` ist der Teiler für die €/m²-Linie: im Fokus die effektive Fläche
   der Einheit, am Haus die Summe über alle Einheiten (Ø €/m²). Ist sie 0,
   entfällt die Linie.

   Bis ~24 Monate monatlich; wird die Historie länger als 30 Monate, wird auf
   Quartale verdichtet (Ø Monatsbetrag je Quartal) und auf die letzten drei
   Jahre begrenzt — sonst quetschen sich zu viele Säulen ins Bild. */

export function mietVerlauf(mieten, flaeche) {
  // Geplante zählen noch nicht; beendete gehören zur Historie und bleiben drin.
  const aktive = (mieten || []).filter(m => !m.geplant && m.ab_datum);
  if (!aktive.length) return [];

  const idx = s => { const d = new Date(s); return d.getFullYear() * 12 + d.getMonth(); };
  const heute = new Date();
  const endM = heute.getFullYear() * 12 + heute.getMonth();
  let startM = Math.min(...aktive.map(m => idx(m.ab_datum)));
  if (startM > endM) startM = endM;

  const faktor = m => proJahr(m.turnus) / 12;  // Turnus auf Monatsbetrag
  const monate = [];
  for (let mm = startM; mm <= endM; mm++) {
    let miete = 0, nk = 0;
    for (const m of aktive) {
      const a = idx(m.ab_datum);
      const b = m.bis_datum ? idx(m.bis_datum) : endM;
      if (mm >= a && mm <= b) {
        const f = faktor(m);
        miete += (m.kaltmiete || 0) * f;
        nk += (m.nebenkosten_vz || 0) * f;
      }
    }
    monate.push({ m: mm, miete, nk });
  }

  const punkt = (miete, nk, label) => ({
    miete, nk, label,
    qm: flaeche > 0 ? miete / flaeche : null,
  });

  if (monate.length > 30) {
    // Auf Quartale verdichten: Ø Monatsbetrag je Quartal, letzte 12 Quartale.
    const eimer = new Map();
    for (const b of monate) {
      const y = Math.floor(b.m / 12), q = Math.floor((b.m % 12) / 3);
      const key = y * 4 + q;
      const e = eimer.get(key) || { y, q, miete: 0, nk: 0, n: 0 };
      e.miete += b.miete; e.nk += b.nk; e.n++;
      eimer.set(key, e);
    }
    const quartale = [...eimer.values()].sort((a, b) => (a.y * 4 + a.q) - (b.y * 4 + b.q))
      .slice(-12);
    return quartale.map(e =>
      punkt(e.miete / e.n, e.nk / e.n, `Q${e.q + 1}/${String(e.y).slice(2)}`));
  }

  // Monatlich, höchstens die letzten 24 Monate.
  return monate.slice(-24).map(b => {
    const y = Math.floor(b.m / 12), mo = b.m % 12;
    const label = mo === 0 ? `${MONATS_KURZ[mo]} ${String(y).slice(2)}` : MONATS_KURZ[mo];
    return punkt(b.miete, b.nk, label);
  });
}

/* Der Diagramm-Block: Überschrift, Säulen+Linie, Legende. Bei fehlenden Daten
   zeigt mietChart selbst einen ruhigen Leer-Hinweis; dann entfällt die Legende. */
export function mietDiagrammHtml(mieten, flaeche, uebersicht = '') {
  const punkte = mietVerlauf(mieten, flaeche);
  const svg = mietChart(punkte, { format: eur });
  const hatWerte = punkte.some(p => (p.miete || 0) + (p.nk || 0) > 0);
  const leg = hatWerte ? legende([
    { name: 'Kaltmiete', farbe: '#0F6E5C' },
    { name: 'Nebenkosten', farbe: '#916212' },
    { name: '€ / m²', farbe: '#16262C' },
  ]) : '';
  const karte = `<div class="diagramm-karte">${svg}${leg}</div>`;
  // N32 — auf der Hausebene stehen die vier Objekt-Summen rechts daneben.
  const koerper = uebersicht
    ? `<div class="diagramm-wrap">${karte}${uebersicht}</div>`
    : karte;
  return `<div class="sekopf"><span class="seikon">${kostenIcon('Miete')}</span>
      <h2 class="sec">Miete &amp; Nebenkosten</h2></div>
    ${koerper}`;
}
