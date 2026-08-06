/* zeitraum/modell.js — Modell-Gates (Standard vs. Laufer, N213) und
   Bereichs-/Positions-Klassifikation. Reine Filter, keine DOM-Berührung.

   Klassifikatoren wie `istStromPos`, `istHeizoelSammel` etc. entscheiden,
   welches UI-Verhalten (Öl-Manager, HKV, Stromkette, Wasser-Sammelposition)
   greift. Sie werden von allen Render-Modulen genutzt. */

import { BEREICHE, BEREICH_PRUEF, KOSTENART_ALIAS, LAUFER_ALIAS_KEYS } from './state.js';
import * as state from './state.js';

/* Umlaut-tolerant + case-insensitiv: für den Wortvergleich der Bereiche
   und der Zähler-Zuordnung. */
export const normUml = s => (s || '').toLowerCase()
  .replace(/ä/g, 'ae').replace(/ö/g, 'oe').replace(/ü/g, 'ue').replace(/ß/g, 'ss');

/* Welcher der sechs Bereiche eine Kostenart bekommt. */
export function bereichIndex(kostenart) {
  const n = normUml(kostenart);
  for (const i of BEREICH_PRUEF) {
    if (BEREICHE[i].muster.some(m => n.includes(m))) return i;
  }
  return BEREICHE.length - 1;   // „Verwaltung & Sonstiges" als Auffangbereich
}

/* Zähler-Zuordnung über den Namen, wenn am Zähler keine Kostenart hängt. */
export function zaehlerNameZuKostenart(name) {
  const n = normUml(name);
  if (n.includes('warmwasser')) return 'Warmwasser';
  if (n.includes('wasser')) return 'Wasser';
  if (n.includes('oel')) return 'Heizkosten';
  if (n.includes('strom')) return 'Allgemeinstrom';
  return '';
}

/* Zu welcher Wasser-Art ein Zähler zählt — bevorzugt aus `art`, sonst aus
   dem Namen. Waschmaschine/Garten VOR Warm-/Kaltwasser prüfen. */
export function wasserArt(z) {
  for (const feld of [normUml(z.art || ''), normUml(z.name || '')]) {
    if (!feld) continue;
    if (feld.includes('waschmaschine')) return 'Waschmaschine';
    if (feld.includes('garten')) return 'Gartenwasser';
    if (feld.includes('warmwasser')) return 'Warmwasser';
    if (feld.includes('kaltwasser')) return 'Kaltwasser';
  }
  return '';
}

/* N213 — Objektmodell: `laufer_spezial` schaltet die Laufer-Maschinerie
   (Stromkette, HKV, Öl-FIFO) ein; `standard` blendet sie aus. Fallback ist
   bewusst `laufer_spezial`, damit vor dem Backend-Deploy nichts fehlt. */
export const istLaufer = () => (state.daten?.modell || 'laufer_spezial') === 'laufer_spezial';

/* Anzeige-Alias je Kostenart. Für Laufer-Aliasse gilt: nur wenn das Objekt
   im Laufer-Modell ist — sonst trägt die Kostenart ihren normalen Namen. */
export const kostenartAnzeige = k => (LAUFER_ALIAS_KEYS.has(k) && !istLaufer())
  ? k : (KOSTENART_ALIAS[k] || k);

/* N89 — die Strom-Position: der Strombetrag entsteht in der PV-/Strom-
   Rechnung und fließt hier in die NK zurück. */
export function istStromPos(k) {
  const n = normUml(k.kostenart);
  if (n.includes('zaehler')) return false;
  return n.includes('strom') || n.includes('beleucht');
}

/* N142 — die Stromkette hängt an genau EINER Zeile: der obersten Strom-
   Position der Checkliste. N213 — nur im Laufer-Modell. */
export function istStromKettePos(k) {
  if (!istLaufer()) return false;
  return istStromPos(k)
    && (state.daten?.checkliste || []).find(istStromPos) === k;
}

/* N47 — die Wasser-Sammelposition. */
export function istWasserSammel(k) {
  const n = normUml(k.kostenart);
  if (n.includes('zaehler') || n.includes('abwasser') || n.includes('schmutz')
      || n.includes('niederschlag') || n.includes('entwaesser')
      || n.includes('kaltwasser') || n.includes('warmwasser')) return false;
  return n === 'wasser' || n === 'frischwasser' || n === 'trinkwasser';
}

/* N185 — ob eine Kostenart zu den drei Wasser-Bestandteilen gehört. */
export function istWasserKostenart(name) {
  const n = normUml(name);
  if (n.includes('zaehler') || n.includes('warmwasser')) return false;
  return n.includes('wasser') || n.includes('abwasser')
    || n.includes('schmutz') || n.includes('niederschlag')
    || n.includes('entwaess');
}

/* N79/N91/N213 — die Heizöl-Sammelposition (nur Laufer). */
export function istHeizoelSammel(k) {
  if (!istLaufer()) return false;
  const n = normUml(k.kostenart);
  if (n.includes('wartung') || n.includes('warmwasser')) return false;
  return n === 'heizkosten' || n.includes('heizoel') || n.includes('heizol');
}

/* N91/N213 — Warmwasser-Position: §9-Split (nur Laufer). */
export function istWarmwasserPos(k) {
  if (!istLaufer()) return false;
  const n = normUml(k.kostenart);
  return n === 'warmwasser' || n.includes('warmwassererzeug');
}

/* N91/N213 — Heizungs-Position: Heizkörper-Wärmemenge über HKV (nur Laufer). */
export function istHeizwaermePos(k) {
  if (!istLaufer()) return false;
  const n = normUml(k.kostenart);
  if (n.includes('wartung') || n.includes('warmwasser')) return false;
  return n === 'heizung' || n.includes('heizkoerper') || n.includes('waermemenge');
}

/* N57 — die drei Wasser-Bestandteile leben nur im Detail-Popup. */
export function istImDetailPopup(k) {
  if (istWasserSammel(k)) return false;
  const n = normUml(k.kostenart);
  if (n.includes('abwasser') || n.includes('schmutzwasser')) return true;
  if (n.includes('niederschlag') || n.includes('entwaesser')) return true;
  if (n.includes('kaltwasser') && n.includes('zaehler')) return true;
  return false;
}
