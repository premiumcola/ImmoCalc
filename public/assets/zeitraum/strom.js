/* zeitraum/strom.js — der Strom-Zähler-Block im Zählerstände-Bereich.

   Gesamtverbrauch oben, Zwischenzähler als Abzug, Verbrauch Haus (Rest) am
   Ende. Rollen (STROM_ROLLEN) beschreiben, welche Position eine Zeile
   einnimmt (Gesamt · Zwischen · Jahreswert · Haus). Neue Strom-Zähler
   entstehen im Anlegen-Formular. */

import { api, esc, frage, melde } from '../immo.js';
import * as state from './state.js';
import { STROM_ROLLEN } from './state.js';
import { istStromPos } from './modell.js';
import { zahl, standAusFeld, baueChipMap, feldZahl } from './helpers.js';
import { meterZeileHtml } from './zaehler.js';

export const stromLabel = z => state.zLabels.get(z.id) || z.name;

export const stromRolle = (z, s) => z.typ === 'rest' ? 'rest'
  : (s.gesamt?.id === z.id ? (z.typ === 'direkt' ? 'gesamt' : 'gesamt_stand')
    : (z.typ === 'direkt' ? 'direkt' : 'gemessen'));

/* Was unter einer Strom-Zeile zusätzlich steht: Rolle + Entfernen. */
export function stromExtra(z, s) {
  if (state.daten.status !== 'in Arbeit') return '';
  const jetzt = stromRolle(z, s);
  const optionen = Object.entries(STROM_ROLLEN).map(([wert, r]) =>
    `<option value="${wert}"${wert === jetzt ? ' selected' : ''}>${r.titel}</option>`)
    .join('');
  return `<div class="zu-rolle"><span class="zu-ehl">Rolle</span>
      <select data-strom-rolle-set="${z.id}"
        aria-label="Rolle von ${esc(z.name)}">${optionen}</select>
      <button type="button" class="zu-weg" data-strom-weg="${z.id}"
        data-strom-titel="${esc(stromLabel(z))}">Entfernen</button></div>`;
}

/* Unter welcher Kostenart ein neuer Strom-Zähler hängt. */
export const stromKostenart = () =>
  (state.daten.checkliste || []).find(istStromPos)?.kostenart || 'Strom';

/* Ein neuer Zähler: Name und Rolle. */
export function stromNeuForm(s) {
  const rollen = Object.entries(STROM_ROLLEN)
    .filter(([w]) => !(w.startsWith('gesamt') && s.gesamt)
      && !(w === 'rest' && s.rest));
  return `<div class="ho-neu st-neu">
      <input type="text" data-strom-name placeholder="Name des Zählers"
        aria-label="Name des neuen Zählers">
      <select data-strom-rolle aria-label="Rolle des neuen Zählers">${rollen
        .map(([w, r]) => `<option value="${w}">${r.titel}</option>`).join('')}</select>
      <button class="btn" data-strom-add>Zähler anlegen</button>
    </div>`;
}

/* Die Strom-Zähler in fachlicher Ordnung. */
function stromStrukturLokal(zaehler = null) {
  const liste = (zaehler || state.ablesungMaske?.zaehler || [])
    .filter(z => (z.messeinheit || '') === 'kWh');
  const hauptIds = new Set(liste.filter(z => z.hauptzaehler_id)
    .map(z => z.hauptzaehler_id));
  const gesamt = liste.find(z => z.typ !== 'rest' && hauptIds.has(z.id))
    || liste.find(z => z.typ !== 'rest' && !z.hauptzaehler_id) || null;
  const unter = liste.filter(z => z.typ !== 'rest' && z.id !== gesamt?.id);
  const rest = liste.find(z => z.typ === 'rest') || null;
  return { liste, gesamt, unter, rest };
}

/* Der Strom-Block: Gesamtverbrauch, Zwischenzähler als Abzug, Rest. */
export function stromBlockHtml(liste) {
  const bearbeitbar = state.daten.status === 'in Arbeit';
  const s = stromStrukturLokal(liste);
  const form = bearbeitbar ? stromNeuForm(s) : '';
  if (!s.liste.length) {
    return `<div class="zu-kein">Noch kein Stromzähler erfasst. Erwartet werden
      der <b>Gesamtverbrauch</b> der Periode als Absolutwert, darunter die
      <b>Zwischenzähler</b> mit ihren Ständen, Verbräuche <b>ohne Zähler</b> als
      Jahreswert (etwa das Elektroauto) und zuletzt der <b>Verbrauch Haus</b>,
      der sich daraus errechnet.</div>${form}`;
  }

  const zeile = (z, o) => meterZeileHtml(z, { ...o, extra: stromExtra(z, s) });
  const subZeilen = s.unter.map(z => zeile(z, { minus: true })).join('');
  const summeUnter = s.unter.reduce((sum, z) => sum + (z.verbrauch || 0), 0);
  const gesamtV = s.gesamt?.verbrauch ?? null;
  const restNegativ = !!(s.rest && s.rest.verbrauch != null && s.rest.verbrauch < 0);
  const restZeile = s.rest
    ? zeile(s.rest, { rest: true, verbText: restNegativ ? 'nicht plausibel' : '' })
    : '';

  const rechnung = s.gesamt ? `<div class="ho-summe">Gesamt <b>${gesamtV != null
      ? `${zahl(gesamtV)} kWh` : '—'}</b> − Zwischenzähler <b>${
      zahl(summeUnter)} kWh</b> = Haus <b>${gesamtV != null
      ? `${zahl(Math.round((gesamtV - summeUnter) * 1000) / 1000)} kWh` : '—'}</b></div>` : '';

  const warnungen = [];
  if (restNegativ) {
    warnungen.push(`Die Zwischenzähler ergeben zusammen <b>${zahl(summeUnter)} kWh</b>
      und damit mehr, als der Gesamtverbrauch mit <b>${zahl(gesamtV)} kWh</b>
      hergibt. Für das Haus bliebe nichts übrig — bitte die Stände prüfen.`);
  }
  const fremd = s.unter.filter(z => s.gesamt && z.hauptzaehler_id !== s.gesamt.id);
  if (fremd.length) {
    warnungen.push(`${fremd.map(z => `<b>${esc(stromLabel(z))}</b>`).join(', ')}
      ${fremd.length === 1 ? 'gehört' : 'gehören'} noch zu keinem Gesamtverbrauch und
      ${fremd.length === 1 ? 'wird' : 'werden'} beim Verbrauch Haus nicht abgezogen —
      die Rolle unten an der Zeile setzen.`);
  }
  const hinweise = [];
  if (!s.rest) {
    hinweise.push('Für den Verbrauch Haus fehlt noch die errechnete Zeile.');
  }
  if (s.gesamt && gesamtV == null) {
    hinweise.push(`Für „${esc(stromLabel(s.gesamt))}“ ist in dieser Periode noch
      kein Wert erfasst.`);
  }

  return `${s.gesamt ? zeile(s.gesamt, {}) : ''}
    <div class="zu-abzug">${subZeilen || `<div class="zu-kein">Noch keine
      Zwischenzähler.</div>`}${restZeile}</div>
    ${rechnung}
    ${hinweise.map(h => `<div class="zu-kein">${h}</div>`).join('')}
    ${warnungen.map(w => `<div class="ho-warn">▲ ${w}</div>`).join('')}
    ${form}`;
}

/* ---------- Aktionen ---------------------------------------------------- */

async function neuZeichnen() {
  const { zeichnen } = await import('./checkliste.js');
  await zeichnen();
}

async function neuLaden() {
  const { laden } = await import('./checkliste.js');
  await laden();
}

/* N122 — die Menge einer Strom-Position speichern. */
export async function stromMengeSpeichern(input) {
  const menge = standAusFeld(input);
  if (menge === null) return;
  if (Number.isNaN(menge)) { melde('Ungültige Menge', 'neg'); return; }
  try {
    await api(`/positionen/${input.dataset.stromMenge}`, { method: 'PATCH',
      body: { menge, menge_einheit: 'kWh' } });
    melde('Verbrauch gespeichert', 'pos');
    await neuLaden();
  } catch (fehler) { melde(String(fehler.message || fehler), 'neg'); }
}

/* N122 — Herkunft einer Strom-Position setzen (zweiter Klick nimmt zurück). */
export async function stromHerkunftSetzen(btn) {
  const k = (state.daten.checkliste || []).find(p =>
    String(p.position_id) === btn.dataset.herkunftPid);
  const neu = k?.herkunft === btn.dataset.herkunft ? '' : btn.dataset.herkunft;
  try {
    await api(`/positionen/${btn.dataset.herkunftPid}`, { method: 'PATCH',
      body: { herkunft: neu } });
    await neuLaden();
  } catch (fehler) { melde(String(fehler.message || fehler), 'neg'); }
}

/* Nach jeder Änderung an den Strom-Zählern. */
export async function stromFrisch(text) {
  state.setAblesungMaske(await api(`/zeitraeume/${state.zid}/ablesung`));
  state.setChipMap(baueChipMap());
  melde(text, 'pos');
  await neuZeichnen();
}

/* Ein Jahreswert als Ablesung dieses Zeitraums. */
export async function stromJahreswertSpeichern(input) {
  const wert = standAusFeld(input);
  if (wert === null) return;
  if (Number.isNaN(wert)) { melde('Ungültiger Wert', 'neg'); return; }
  try {
    await api(`/zaehler/${input.dataset.stromJahr}/ablesungen`, {
      method: 'POST',
      body: { stand: wert, zeitraum_id: Number(state.zid),
              datum: state.ablesungMaske?.zeitraum?.ende || state.daten.ende },
    });
    await stromFrisch('Jahreswert gespeichert');
  } catch (fehler) { melde(String(fehler.message || fehler), 'neg'); }
}

export async function stromZaehlerAnlegen(btn) {
  const box = btn.closest('.ho-neu');
  const feld = box?.querySelector('[data-strom-name]');
  const name = (feld?.value || '').trim();
  const rolle = box?.querySelector('[data-strom-rolle]')?.value || 'gemessen';
  const r = STROM_ROLLEN[rolle];
  if (!name) { melde('Name des Zählers eintragen', 'neg'); feld?.focus(); return; }
  const s = stromStrukturLokal();
  if (r.haupt && !s.gesamt) {
    melde('Erst den Gesamtverbrauch anlegen — die übrigen hängen daran', 'neg');
    return;
  }
  try {
    await api(`/objekte/${encodeURIComponent(state.daten.objekt)}/zaehler`, {
      method: 'POST',
      body: { name, kostenart: stromKostenart(), art: 'Strom',
              messeinheit: 'kWh', typ: r.typ, reihenfolge: r.reihenfolge,
              hauptzaehler_id: r.haupt ? s.gesamt.id : null },
    });
    await stromFrisch('Zähler angelegt');
  } catch (fehler) { melde(String(fehler.message || fehler), 'neg'); }
}

/* Die Rolle einer bestehenden Zeile umstellen. */
export async function stromRolleSetzen(sel) {
  const id = Number(sel.dataset.stromRolleSet);
  const r = STROM_ROLLEN[sel.value];
  if (!r) return;
  const s = stromStrukturLokal();
  const gesamt = s.gesamt && s.gesamt.id !== id ? s.gesamt : null;
  if (r.haupt && !gesamt) {
    melde('Erst einen anderen Zähler zum Gesamtverbrauch machen', 'neg');
    return neuZeichnen();
  }
  try {
    await api(`/zaehler/${id}`, { method: 'PATCH',
      body: { typ: r.typ, reihenfolge: r.reihenfolge,
              hauptzaehler_id: r.haupt ? gesamt.id : null } });
    await stromFrisch('Rolle geändert');
  } catch (fehler) { melde(String(fehler.message || fehler), 'neg'); }
}

export async function stromZaehlerEntfernen(btn) {
  const name = btn.dataset.stromTitel || 'Zähler';
  const ja = await frage(`„${name}“ entfernen?`,
    'Der Zähler und seine Ablesungen werden gelöscht. Kostenposition und Belege '
    + 'bleiben unangetastet. Hängen Unterzähler an ihm, verlieren sie ihren Bezug.',
    { knopf: 'Entfernen', gefahr: true });
  if (!ja) return;
  try {
    await api(`/zaehler/${btn.dataset.stromWeg}`, { method: 'DELETE' });
    await stromFrisch('Zähler entfernt');
  } catch (fehler) { melde(String(fehler.message || fehler), 'neg'); }
}

/* N94 — Gartenwasser ohne Zähler: als Zähler mit Anfangsstand 0 und
   Endstand = Wert ablegen. */
export async function gartenAnlegen(btn) {
  const feld = btn.closest('.ho-neu')?.querySelector('[data-garten-m3]');
  const m3wert = feldZahl(feld);
  if (!(m3wert > 0)) { melde('m³ eintragen', 'neg'); return; }
  try {
    const neu = await api(`/objekte/${encodeURIComponent(state.daten.objekt)}/zaehler`, {
      method: 'POST',
      body: { name: 'Gartenwasser', art: 'Gartenwasser', kostenart: 'Wasser',
              messeinheit: 'm³', typ: 'gemessen' },
    });
    const id = neu?.id;
    if (id) {
      await api(`/zaehler/${id}/anfangsstand`,
        { method: 'POST', body: { stand: 0, datum: state.daten.start } });
      await api(`/zaehler/${id}/ablesungen`, { method: 'POST',
        body: { stand: m3wert, datum: state.daten.ende, zeitraum_id: Number(state.zid) } });
    }
    melde('Gartenwasser erfasst — jetzt die Einheit wählen', 'pos');
    await neuLaden();
  } catch (fehler) { melde(String(fehler.message || fehler), 'neg'); }
}
