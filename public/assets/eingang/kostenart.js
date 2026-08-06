/* N216 — Die Kostenposition am Pruefblatt (CLXXI/CCLXXIV).

   Die Art sagt nur den Ordner. Welche Position der Abrechnung gemeint ist —
   Kaminkehrer, Wasser, Muellabfuhr —, steht im Kostenkatalog der Immobilie.
   Der Katalog wird je Immobilie gecacht; ein Vorschlag wird aus Dateiname und
   OCR erraten, ein KI-Vorschlag wandert in leere Felder. */

import { S } from './state.js';
import { api } from '../immo.js';
import { befund } from './helpers.js';
import { planZeichnen } from './plan.js';

export async function kostenartenFuer(slug) {
  if (!slug) return [];
  if (S.kostenartenJeObjekt.has(slug)) return S.kostenartenJeObjekt.get(slug);
  try {
    const katalog = await api(`/objekte/${encodeURIComponent(slug)}/kostenarten`);
    const namen = katalog.filter(k => k.aktiv !== false).map(k => k.name);
    S.kostenartenJeObjekt.set(slug, namen);
    return namen;
  } catch {
    return [];       // ohne Katalog bleibt das Feld eben leer
  }
}

/** Welche Position zu diesem Beleg passt — geraten aus Dateiname und
    Erkennung. Ein Vorschlag, den der Nutzer ueberschreiben kann. */
export function passendeKostenart(namen, d, b) {
  const gelesen = (S.erkanntJeBeleg.get(d.id) || {}).werte || {};
  const heu = [d.dateiname, b.sache, gelesen.sache]
    .filter(Boolean).join(' ').toLowerCase();
  return namen.find(n => n && heu.includes(n.toLowerCase())) || '';
}

export async function kostenartenFuellen(d) {
  const slug = (S.erfassung && S.erfassung.id === d.id ? S.erfassung.objekt.wert() : '')
    || d.objekt || '';
  const namen = await kostenartenFuer(slug);
  if (!S.erfassung || S.erfassung.id !== d.id) return;
  const b = befund(d);
  const gesetzt = S.erfassung.kostenart.wert();
  // Eine Position, die der Katalog nicht (mehr) fuehrt, bleibt trotzdem
  // stehen — sie ist eine Angabe des Nutzers, keine Auswahl der App. Nach
  // einem Wechsel der Immobilie gilt das aber nicht: „Kaminkehrer" gehoert
  // dann zu einem fremden Haus und muss neu gewaehlt werden.
  const eigenes = slug === (d.objekt || '');
  const behalten = Boolean(gesetzt)
    && (namen.includes(gesetzt) || (eigenes && gesetzt === b.kostenart));
  let wert = behalten ? gesetzt : '';
  if (!wert) {
    wert = passendeKostenart(namen, d, b);
    if (wert) S.erfassung.vorgeschlagen.add('kostenart');
  }
  // CCLXXIV: die KI hat eine Kostenposition erkannt — als Vorbelegung nehmen,
  // wo der Nutzer (noch) keine gewaehlt hat und der Beleg zu dieser Immobilie
  // gehoert. Steht sie nicht im Katalog, kommt sie als eigene Angabe dazu.
  if (!wert && eigenes) {
    const kiArt = String((d.ki_felder || {}).kostenart || '').trim();
    if (kiArt) { wert = kiArt; S.erfassung.vorgeschlagen.add('kostenart'); }
  }
  const alle = [...namen];
  if (behalten && !namen.includes(gesetzt)) alle.push(gesetzt);
  if (wert && !alle.includes(wert)) alle.push(wert);
  S.erfassung.kostenart.fuelle(
    [{ wert: '', text: namen.length ? 'ohne Position'
                                    : 'keine Kostenarten hinterlegt' },
     ...alle.map(n => ({ wert: n, text: n }))], wert);
  planZeichnen();
}
