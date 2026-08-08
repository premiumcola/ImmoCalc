/* N309f — Kontaktbuch: alles, was mit der API spricht, und der Zustand der
   Seite. Die Ansichten (firmen.js, renovierungen.js) bekommen fertige Daten
   und geben HTML zurueck — sie rufen selbst nichts ab. */

import { api } from '../immo.js';

/** Zustand der Seite. Eine Stelle, damit die Ansichten nicht raten muessen. */
export const S = {
  sicht: 'firmen',              // 'firmen' | 'reno'
  filter: { objekt: '', art: '', gewerk: '', suche: '', nurLuecken: false },
  daten: null,                  // Antwort von /kontakte
  objekte: [],                  // alle Immobilien
  renovierungen: new Map(),     // slug -> [Renovierung]
  renoObjekt: '',               // gewaehlte Immobilie in der Renovierungssicht
  renoId: '',                   // gewaehlte Renovierung
  renoSicht: null,              // Antwort von /kontakte/gewerke/{id}
};

/** Die Filter als Abfragekette — leere Werte bleiben weg. */
function kette(filter) {
  const p = new URLSearchParams();
  if (filter.objekt) p.set('objekt', filter.objekt);
  if (filter.art) p.set('art', filter.art);
  if (filter.gewerk) p.set('gewerk', filter.gewerk);
  if (filter.suche) p.set('suche', filter.suche);
  const s = p.toString();
  return s ? `?${s}` : '';
}

export const kontakteHolen = filter => api(`/kontakte${kette(filter)}`);
export const kontaktHolen = id => api(`/kontakte/${id}`);
export const kontaktAendern = (id, werte) =>
  api(`/kontakte/${id}`, { method: 'PATCH', body: werte });
export const kontaktLoeschen = id =>
  api(`/kontakte/${id}`, { method: 'DELETE' });
export const nummerAnlegen = (id, werte) =>
  api(`/kontakte/${id}/nummer`, { method: 'POST', body: werte });
export const nummerLoeschen = nid =>
  api(`/kontakte/nummer/${nid}`, { method: 'DELETE' });
export const ernten = () => api('/kontakte/ernten', { method: 'POST' });

export const objekteHolen = () => api('/objekte');
export const renovierungenHolen = slug =>
  api(`/objekte/${encodeURIComponent(slug)}/renovierungen`);
export const gewerkeSichtHolen = rid => api(`/kontakte/gewerke/${rid}`);

/**
 * Renovierungen aller Immobilien einsammeln — nebenlaeufig, und ein Objekt
 * ohne Bauvorhaben faellt einfach weg. Ergebnis liegt in `S.renovierungen`.
 */
export async function renovierungenAllerObjekte() {
  const paare = await Promise.all(S.objekte.map(async o => {
    try { return [o.slug, await renovierungenHolen(o.slug)]; }
    catch { return [o.slug, []]; }
  }));
  S.renovierungen = new Map(paare.filter(([, liste]) => liste?.length));
  return S.renovierungen;
}

/** Die angezeigten Kontakte — der Lueckenfilter wirkt nur im Browser. */
export function sichtbareKontakte() {
  const alle = S.daten?.kontakte || [];
  return S.filter.nurLuecken ? alle.filter(k => k.fehlt?.length) : alle;
}

/** Wie viele Kundennummern stecken in der aktuellen Antwort? */
export const nummernAnzahl = () =>
  (S.daten?.kontakte || []).reduce((summe, k) => summe + (k.nummern?.length || 0), 0);

/** Ist irgendein Filter gesetzt? Steuert den Zuruecksetzen-Knopf. */
export const gefiltert = () => Boolean(S.filter.objekt || S.filter.art
  || S.filter.gewerk || S.filter.suche || S.filter.nurLuecken);
