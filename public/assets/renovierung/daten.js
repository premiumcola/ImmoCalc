/* N270 — Renovierung: Zugriff auf die API und die kleinen Formathelfer der
   Seite. Eine Stelle fuer jeden Endpunkt, damit Liste, Detail und Formulare
   nicht jeweils ihren eigenen Pfad zusammenbauen. */

import { api } from '../immo.js';

const weg = s => encodeURIComponent(s);

/* ---- Lesen -------------------------------------------------------------- */

export const gewerkeHolen = async () => (await api('/renovierungen/gewerke')).gewerke || [];

export const listeHolen = slug => api(`/objekte/${weg(slug)}/renovierungen`);

export const detailHolen = rid => api(`/renovierungen/${rid}`);

export const einheitenHolen = slug => api(`/objekte/${weg(slug)}/einheiten`);

/** Der Objekttitel fuer die Kopfzeile — aus der Objektliste, die es ohnehin
 *  gibt. Ein eigener Detailabruf nur fuer einen Namen waere Verschwendung. */
export async function objektHolen(slug) {
  const alle = await api('/objekte');
  return (alle || []).find(o => o.slug === slug) || null;
}

/* ---- Schreiben ---------------------------------------------------------- */

export const renovierungAnlegen = (slug, werte) =>
  api(`/objekte/${weg(slug)}/renovierungen`, { method: 'POST', body: werte });

export const renovierungAendern = (rid, werte) =>
  api(`/renovierungen/${rid}`, { method: 'PATCH', body: werte });

export const renovierungLoeschen = rid =>
  api(`/renovierungen/${rid}`, { method: 'DELETE' });

export const postenAnlegen = (rid, werte) =>
  api(`/renovierungen/${rid}/posten`, { method: 'POST', body: werte });

export const postenAendern = (pid, werte) =>
  api(`/renovierungen/posten/${pid}`, { method: 'PATCH', body: werte });

export const postenLoeschen = pid =>
  api(`/renovierungen/posten/${pid}`, { method: 'DELETE' });

/* ---- Format ------------------------------------------------------------- */

/** ISO-Datum als „14.03.2026". Leer bleibt leer — kein „01.01.1970". */
export const tag = iso => {
  if (!iso) return '';
  const [j, m, t] = String(iso).slice(0, 10).split('-');
  return j && m && t ? `${t}.${m}.${j}` : '';
};

/** Zeitraum einer Renovierung als eine Zeile: „März 2026 – Juli 2026",
 *  „ab 03.03.2026", „bis 31.07.2026" oder leer. */
export function zeitraumText(von, bis) {
  if (von && bis) return `${tag(von)} – ${tag(bis)}`;
  if (von) return `ab ${tag(von)}`;
  if (bis) return `bis ${tag(bis)}`;
  return '';
}

/** Betroffene Einheiten in Worten. Leer heisst: das ganze Objekt. */
export const einheitenText = liste =>
  !liste || !liste.length ? 'ganzes Objekt' : liste.join(' · ');
