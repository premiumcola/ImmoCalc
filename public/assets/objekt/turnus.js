/* N216 — Zahlungsturnus kommt aus der API — die Bereiche haben unterschiedliche
   sinnvolle Auswahlen, und die soll nicht doppelt gepflegt werden. Kleiner
   Cache, damit Nachfragen innerhalb eines Aufrufs keinen zweiten Roundtrip
   auslösen. */

import { api } from '../immo.js';

const turnusCache = new Map();

export async function turnusOptionen(bereich) {
  if (!turnusCache.has(bereich)) {
    try {
      turnusCache.set(bereich, await api(`/turnus/${bereich}`));
    } catch {
      turnusCache.set(bereich, { optionen: [], vorgabe: '' });
    }
  }
  return turnusCache.get(bereich);
}
