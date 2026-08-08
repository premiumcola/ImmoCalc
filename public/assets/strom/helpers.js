/* N215 — kleine Formatierer, die mehrere Module brauchen.

   Umzug ohne inhaltliche Aenderung: dieselben Formeln wie zuvor inline in
   strom.html. `eur` und `promille` kommen weiter aus immo.js. */
import { zahlAus } from '../immo.js';

/* N288 — eine Zahl aus einem Eingabefeld, leeres Feld = 0.

   Die deutsche Lese-Regel steht an EINER Stelle: `zahlAus` in immo.js (Komma
   trennt Dezimalen, Punkte in Dreiergruppen sind Tausenderpunkte). Sie gilt
   fuer alles, was der Nutzer als Text tippt.

   Ein `<input type="number">` ist der eine Fall, in dem sie NICHT gilt: sein
   `value` kommt vom Browser bereits normiert heraus — Punkt als Dezimal-
   trenner, nie Tausenderpunkte. Dort haette die deutsche Regel aus einem
   getippten „8,205 kWp" (value „8.205") die Zahl 8205 gemacht. Deshalb hier
   nur die Weiche; nachgebaut wird die Regel nirgends. */
export function feldZahl(el, vorgabe = 0) {
  if (!el) return vorgabe;
  if (el.type === 'number') {
    const v = Number(el.value);
    return el.value === '' || !Number.isFinite(v) ? vorgabe : v;
  }
  const v = zahlAus(el);
  return v == null ? vorgabe : v;
}

export const kwh = n => (n ?? 0)
  .toLocaleString('de-DE', { maximumFractionDigits: 0 }) + ' kWh';

export const kwh0 = n => Math.round(n || 0).toLocaleString('de-DE') + ' kWh';

export const eur0 = n => Math.round(n || 0).toLocaleString('de-DE') + ' €';

export const negativ = t => t.replace('-', '−');

export const prozent = n => n == null ? '—'
  : n.toLocaleString('de-DE', { maximumFractionDigits: 1 }) + ' %';

export const ct = n => n.toLocaleString('de-DE',
  { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' ct';

/* Wie `prozent`, mit demselben Verhalten fuer `null`. Getrennter Name, weil
   das Ringdiagramm eine andere Bedeutung transportiert (Anteil an der
   Aufteilung, nicht Autarkie). */
export const proz1 = p => p == null ? '—'
  : p.toLocaleString('de-DE', { maximumFractionDigits: 1 }) + ' %';

export const satzKwh = s => s == null ? null
  : s.toLocaleString('de-DE',
    { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' €/kWh';

export const runde3 = w => Math.round(w * 1000) / 1000;

export const datumDe = d => d.toLocaleDateString('de-DE',
  { day: '2-digit', month: '2-digit', year: 'numeric' });

/* ISO-Datum → Date-Objekt; ungueltiges wird zu `null`, damit Aufrufer nicht
   auf NaN pruefen muessen. */
export function tag(iso) {
  if (!iso) return null;
  const d = new Date(`${iso}T00:00:00`);
  return Number.isNaN(d.getTime()) ? null : d;
}
