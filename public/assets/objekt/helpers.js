/* N216 — kleine Werkzeuge und Ableitungen für die Objektseite. Reine
   Funktionen — sie lesen Zustand aus `state.js` per Live-Bindung, verändern
   ihn aber nicht. */

import { esc, eur } from '../immo.js';
import { flaecheText } from '../objekt-format.js?v=2';
import { bereicheDaten, einheiten, daten, MIET_PALETTE } from './state.js';
import { istGrundstueck } from '../objekt-state.js?v=2';

/* Auf welche Einheit ein Mietverhältnis zeigt. Spiegelt `verteilung.bezuege`:
   ohne Angabe gehört es bei genau einer Einheit zu dieser — sonst nirgendwohin. */
export const zuEinheit = m => (m.einheit || '').trim()
  || (einheiten.length === 1 ? einheiten[0].bezeichnung : '');

/* ---- Datums-/Dauer-Bausteine (N19) --------------------------------------- */

export const isoTag = iso =>
  iso ? `${iso.slice(8, 10)}.${iso.slice(5, 7)}.${iso.slice(0, 4)}` : '';

// Heute als ISO-Tag (lokal) — für laufende Mietdauer und den Vermietet-Status.
export const heuteIso = () => {
  const h = new Date();
  return `${h.getFullYear()}-${String(h.getMonth() + 1).padStart(2, '0')}-${
    String(h.getDate()).padStart(2, '0')}`;
};

export function tagPlus(iso, d) {
  const t = new Date(`${iso}T00:00:00Z`);
  t.setUTCDate(t.getUTCDate() + d);
  return t.toISOString().slice(0, 10);
}

export function dauerText(vonIso, bisIso) {
  const [vy, vm, vd] = vonIso.split('-').map(Number);
  const [by, bm, bd] = bisIso.split('-').map(Number);
  let monate = (by - vy) * 12 + (bm - vm) - (bd < vd ? 1 : 0);
  monate = Math.max(0, monate);
  const j = Math.floor(monate / 12), m = monate % 12;
  const teile = [];
  if (j) teile.push(`${j} Jahr${j > 1 ? 'e' : ''}`);
  if (m || !j) teile.push(`${m} Monat${m === 1 ? '' : 'e'}`);
  return teile.join(' ');
}

/* ---- Flächen einer Einheit (CCCXXVII/CCCXXVIII) -------------------------- */

// CCCXXVII/CCCXXVIII/N227 — die für Miete und Verteilung maßgebliche Fläche
// einer Einheit: die Wohn-/Nutzfläche, Terrasse/Balkon zu ihrem eingestellten
// Anteil (`terrasse_anteil_pct`, Vorgabe 50 %), Nebenfläche zur Hälfte, plus
// anteilig mitgenutzte Gemeinschaftsflächen (Fläche ÷ Zahl der Nutzer) und
// volle Zusatz-Nutzflächen. Dieselbe Formel wie `verteilung._gesamtflaeche`
// im Backend — sonst wichen Anzeige und echte Abrechnung voneinander ab.
export function effektiveFlaeche(e) {
  const wohn = Number(e.flaeche) || 0;
  const terrassePct = e.terrasse_anteil_pct != null ? Number(e.terrasse_anteil_pct) : 50;
  const terrasse = (Number(e.terrasse) || 0) * terrassePct / 100;
  const neben = (Number(e.nebenflaeche) || 0) * 0.5;
  // CCCXXIX — benannte Zusatz-Nutzflächen zählen voll (ungeteilt) mit.
  const nutz = (e.nutzflaechen || []).reduce((s, n) =>
    s + (Number(n.flaeche) || 0), 0);
  const gemein = (e.gemeinflaechen || []).reduce((s, g) => {
    const f = Number(g.flaeche) || 0;
    const p = Number(g.personen) || 0;
    return s + (p > 0 ? f / p : 0);
  }, 0);
  return wohn + terrasse + neben + nutz + gemein;
}

// Kaltmiete je m² (monatlich) — null, wenn Fläche oder Miete fehlen (CCCXXVIII).
export function qmMiete(e) {
  const f = effektiveFlaeche(e);
  return e.vermietet && e.kaltmiete && f > 0 ? e.kaltmiete / f : null;
}

// CCCXXXIII — die aus Flächen × €/m² hergeleitete Kaltmiete (monatlich). Je
// Flächenart zählt nur der Term, dessen €/m²-Ansatz gesetzt ist:
//   (flaeche + Σnutz) × miete_qm_wohn      Wohn-/Nutzfläche inkl. voller Zusatz
// + nebenflaeche       × miete_qm_neben     Nebenfläche
// + Σ(gemein ÷ Pers.)  × miete_qm_gemein    anteilige Gemeinschaftsfläche
// Null, wenn kein Ansatz gesetzt ist — dann gibt es nichts vorzuschlagen. Der
// Wert ist ein überschreibbarer Vorschlag; gespeichert wird die tatsächliche
// Kaltmiete am Mietverhältnis, nicht an der Einheit.
export function hergeleiteteKaltmiete(e) {
  const gesetzt = v => v != null && v !== '';
  const wohn = (Number(e.flaeche) || 0)
    + (e.nutzflaechen || []).reduce((s, n) => s + (Number(n.flaeche) || 0), 0);
  const neben = Number(e.nebenflaeche) || 0;
  const gemein = (e.gemeinflaechen || []).reduce((s, g) => {
    const f = Number(g.flaeche) || 0;
    const p = Number(g.personen) || 0;
    return s + (p > 0 ? f / p : 0);
  }, 0);
  let summe = 0, hat = false;
  if (gesetzt(e.miete_qm_wohn)) { summe += wohn * Number(e.miete_qm_wohn); hat = true; }
  if (gesetzt(e.miete_qm_neben)) { summe += neben * Number(e.miete_qm_neben); hat = true; }
  if (gesetzt(e.miete_qm_gemein)) { summe += gemein * Number(e.miete_qm_gemein); hat = true; }
  return hat ? Math.round(summe * 100) / 100 : null;
}

/* ---- Laufende Miete und Beginn der Mietzeit ----------------------------- */

/* N31 — das aktuell laufende Mietverhältnis einer Einheit: ab_datum ≤ heute,
   kein Enddatum oder Enddatum ≥ heute, nicht geplant. Bei mehreren das jüngste.
   Grundlage für Vermietet-Status, laufende Mietdauer und die Objekt-Summen. */
export function laufendeMiete(e) {
  const heute = heuteIso();
  return (bereicheDaten.mieten || [])
    .filter(m => m && m.ab_datum && !m.geplant && zuEinheit(m) === e.bezeichnung
      && m.ab_datum <= heute && (!m.bis_datum || m.bis_datum >= heute))
    .sort((a, b) => b.ab_datum.localeCompare(a.ab_datum))[0] || null;
}

/* N53 — Beginn der DURCHGEHENDEN Mietzeit desselben Mieters. Eine Mieterhöhung
   (auch eine geplante) ist ein eigener Vertrag, der nahtlos an den vorigen
   anschließt (altes Ende = neuer Beginn − 1 Tag). Für „seit X" zählt nicht der
   jüngste Vertrag, sondern der erste einer solchen Kette gleicher Partei ohne
   Leerstands-Lücke. Bei echter Lücke (Auszug, später wieder eingezogen) bricht
   die Kette — das ist dann keine bloße Erhöhung mehr. */
export function mietzeitBeginn(e, lm) {
  const mieten = (bereicheDaten.mieten || [])
    .filter(m => m && m.ab_datum && zuEinheit(m) === e.bezeichnung
      && m.partei === lm.partei)
    .sort((a, b) => a.ab_datum.localeCompare(b.ab_datum));
  let beginn = lm.ab_datum;
  for (let weiter = true; weiter;) {
    weiter = false;
    // Vertrag, dessen Ende nahtlos vor `beginn` liegt (bis == beginn−1 oder
    // beginn, also keine Lücke). Von mehreren Anschlüssen den frühesten nehmen.
    const grenze = tagPlus(beginn, -1);
    const vor = mieten.filter(m => m.bis_datum && m.ab_datum < beginn
      && m.bis_datum >= grenze);
    if (vor.length) { beginn = vor[0].ab_datum; weiter = true; }
  }
  return beginn;
}

/* ---- Objekt-Flächensummen und -Kennzahlen ------------------------------- */

/* CCLIV — Wohnfläche und Stellplätze eines Objekts kommen aus den Einheiten,
   nicht mehr aus einer eigenen Objektangabe. Bevorzugt die vom Backend
   gelieferten Summen (Single Source of Truth); fehlen sie (noch nicht
   deployt), summiert es die geladenen Einheiten selbst. */
export function flaechenSummen() {
  if (daten && daten.wohnflaeche_summe != null) {
    return { wohn: daten.wohnflaeche_summe,
             stell: daten.stellplaetze_summe || 0,
             mit: daten.einheiten_mit_flaeche || 0 };
  }
  const mitFlaeche = einheiten.filter(e => e.flaeche);
  return {
    wohn: mitFlaeche.reduce((sum, e) => sum + (e.flaeche || 0), 0),
    stell: einheiten.reduce((sum, e) => sum + (e.stellplaetze || 0), 0),
    mit: mitFlaeche.length,
  };
}

/* Die gerechneten Flächenzellen, die im Stammdatenblock die Stelle der
   früheren manuellen „Gesamtfläche" einnehmen — als Zell-Daten, damit sie
   kompakt neben den Stellplätzen stehen können. */
export function wohnflaecheCells(o, s) {
  const anzahl = einheiten.length;
  const einheitWort = n => `${n} Einheit${n === 1 ? '' : 'en'}`;
  const cells = [];
  if (s.mit) {
    const quelle = s.mit === anzahl ? `aus ${einheitWort(anzahl)}`
                                    : `aus ${s.mit} von ${einheitWort(anzahl)}`;
    cells.push({ label: 'Wohnfläche', wert: flaecheText(s.wohn), quelle,
                 lex: 'wohnflaeche', abgeleitet: true });
  } else if (o.flaeche) {
    // Noch keine Einheitenfläche erfasst — dann ist die manuelle Angabe alles,
    // was es gibt, und steht schlicht als Wohnfläche da.
    cells.push({ label: 'Wohnfläche', wert: flaecheText(o.flaeche),
                 quelle: 'manuell — noch keine Einheitenfläche erfasst',
                 lex: 'wohnflaeche', abgeleitet: true });
  } else {
    cells.push({ label: 'Wohnfläche', wert: null, abgeleitet: true,
      quelle: anzahl ? 'in den Einheiten noch keine Fläche erfasst'
                     : 'noch keine Einheit erfasst', lex: 'wohnflaeche' });
  }
  if (s.stell) {
    cells.push({ label: 'Stellplätze', wert: String(s.stell),
                 quelle: `aus ${einheitWort(anzahl)}`, lex: 'stellplatz',
                 abgeleitet: true });
  }
  return cells;
}

/* Dezenter Hinweis, wenn die manuell geführte Wohnfläche von der aus den
   Einheiten berechneten abweicht. */
export function flaecheWarnung(manuell, s) {
  if (!manuell || !s.mit || Math.abs(manuell - s.wohn) < 0.05) return '';
  return `<div class="fussnote warn">Manuell eingetragene Wohnfläche
    ${esc(flaecheText(manuell))} weicht von der Summe der Einheiten
    (${esc(flaecheText(s.wohn))}) ab. Maßgeblich ist die aus den Einheiten
    berechnete Fläche.</div>`;
}

/* Was nach einem Update noch nachzutragen wäre — ruhig, nie als Fehler. */
export function nachpflegeHtml(n) {
  if (!n || !n.anzahl) return '';
  return `<div class="merker"><span class="hi">!</span><span class="ht">
      <span class="t">${n.anzahl === 1 ? 'Eine Angabe fehlt noch'
                                        : `${n.anzahl} Angaben fehlen noch`}</span>
      <span class="d">${esc(n.text)}. Nichts davon ist dringend — die
        Abrechnung läuft auch ohne. Ergänzen kannst du es jederzeit.</span>
    </span></div>`;
}

/* Die vier Objekt-Kennzahl-Kacheln am Kopf des Hauses (Wert, Restschuld,
   Bausparguthaben, Eigenkapital, Jahresmiete/Pacht). Am Grundstück heisst
   „Wert" schlicht „Grundstückswert" und die Miete wird zur Pacht. */
export function kennzahlenHtml(v, jahresmiete, restschuld, guthaben) {
  if (!v) return '';
  // Die Restschuld kommt aus den fortgeschriebenen Krediten dieser Seite.
  // Stünde hier der eingetragene Stand, widerspräche die Kennzahl oben der
  // Kreditzeile weiter unten.
  const rest = restschuld != null ? Math.round(restschuld * 100) / 100
                                  : v.restschuld;
  // CXLIX — ein Bausparguthaben ist Guthaben, keine Schuld: es kommt zum
  // Eigenkapital hinzu, statt es zu drücken.
  const gespart = guthaben != null ? Math.round(guthaben * 100) / 100
                                   : (v.bauspar_guthaben || 0);
  const eigen = v.wert != null
    ? Math.round((v.wert - rest + gespart) * 100) / 100 : null;
  const zellen = [];
  if (v.wert != null)
    zellen.push(['kv', eur(v.wert), istGrundstueck() ? 'Grundstückswert'
                                                     : (v.wertquelle || 'Wert')]);
  if (rest) zellen.push(['kv neg', eur(rest), 'Restschuld']);
  if (gespart) zellen.push(['kv pos', eur(gespart), 'Bausparguthaben']);
  if (eigen != null)
    zellen.push([`kv ${eigen >= 0 ? 'pos' : 'neg'}`, eur(eigen), 'Eigenkapital']);
  if (jahresmiete) zellen.push(['kv', eur(jahresmiete),
    istGrundstueck() ? 'Pacht pro Jahr' : 'Miete pro Jahr']);
  if (!zellen.length) return '';
  return `<div class="kennzahlen">${zellen.map(([k, w, l]) =>
    `<div class="kennzahl"><span class="${k}">${w}</span>
       <span class="kl">${esc(l)}</span></div>`).join('')}</div>`;
}

/* Unter welchem Jahr ein frischer Beleg abgelegt wird: was der Eintrag selbst
   sagt — `jahr` (Zahlung), `ab_datum` (Miete), `beginn` (Versicherung,
   Kredit), `datum` (Notarvertrag). Findet sich nichts, bleibt es ohne Jahr:
   der Beleg liegt dann im Sachordner, statt in einem erfundenen Jahrgang. */
export function scanJahr(eintrag) {
  for (const k of ['jahr', 'ab_datum', 'beginn', 'datum']) {
    const jahr = parseInt(String(eintrag[k] ?? '').slice(0, 4), 10);
    if (jahr > 1900) return jahr;
  }
  return null;
}

/* Palette-Farbe nach Index (für die Miet-Timeline). */
export const mietFarbe = i => MIET_PALETTE[i % MIET_PALETTE.length];
