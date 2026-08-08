/* N270 — die Eingabedialoge der Renovierungsseite: die Renovierung selbst
   (Name, Zeitraum, Budget, betroffene Einheiten) und eine einzelne Rechnung
   (Datum, Betrag, Firma, Gewerk).

   Beide bauen auf `baueDialog()` aus immo.js auf und benutzen die vorhandenen
   Formularklassen `.field` / `.inp` / `.btn` — kein eigenes Formularsystem. */

import { baueDialog, esc } from '../immo.js';

/** Zahl aus einem Eingabefeld: leer bleibt `null`, Komma zaehlt als Komma. */
function zahl(el) {
  const roh = String(el.value ?? '').trim().replace(',', '.');
  if (roh === '') return null;
  const n = Number(roh);
  return Number.isFinite(n) ? n : null;
}

/** Gemeinsamer Rahmen: Titel, Felder, Speichern/Abbrechen. `fuellen` bekommt
 *  das <form> und darf Lauscher anhaengen; `lesen` liefert den Datensatz oder
 *  `null`, wenn etwas fehlt (dann bleibt der Dialog offen). */
function formularDialog({ titel, felder, fuellen = () => {}, lesen }) {
  return new Promise(fertig => {
    const dlg = baueDialog(`
      <div class="dt">${esc(titel)}</div>
      <form novalidate>
        ${felder}
        <button class="btn" type="submit">Speichern</button>
        <button class="btn leise" type="button" data-abbruch
                style="margin-top:8px">Abbrechen</button>
      </form>`);
    const form = dlg.querySelector('form');
    fuellen(form, dlg);
    form.querySelector('[data-abbruch]')
        .addEventListener('click', () => { fertig(null); dlg.close(); });
    form.addEventListener('submit', e => {
      e.preventDefault();
      const werte = lesen(form, dlg);
      if (werte === null) return;
      fertig(werte);
      dlg.close();
    });
    dlg.addEventListener('cancel', () => fertig(null));
    // Der Name ist das erste Feld — direkt hineinspringen spart einen Tipp.
    setTimeout(() => form.querySelector('.inp')?.focus(), 30);
  });
}

/* ---- Einheiten-Blasen (Mehrfachauswahl) --------------------------------- */

function einheitenFeldHtml(alle, gewaehlt) {
  if (!alle.length) return '';
  const an = new Set(gewaehlt || []);
  const blasen = alle.map(e => {
    const aktiv = an.has(e.bezeichnung);
    return `<button type="button" class="bubble${aktiv ? ' gewaehlt' : ''}"
        data-einheit="${esc(e.bezeichnung)}" aria-pressed="${aktiv}">
      <span class="bt">${esc(e.bezeichnung)}</span></button>`;
  }).join('');
  return `<div class="field">
      <label>Betroffene Einheiten</label>
      <div class="bubbles" data-einheiten role="group"
           aria-label="Betroffene Einheiten">${blasen}</div>
      <div class="feldnote" data-einheitennote></div>
    </div>`;
}

/** Haelt die Blasen und ihren Hinweistext in Gang. Nichts gewaehlt heisst:
 *  die Renovierung betrifft das ganze Objekt — das steht auch so da, statt
 *  den Nutzer raten zu lassen. */
function einheitenVerdrahten(form) {
  const feld = form.querySelector('[data-einheiten]');
  if (!feld) return () => [];
  const note = form.querySelector('[data-einheitennote]');
  const gewaehlte = () => [...feld.querySelectorAll('[aria-pressed=true]')]
    .map(b => b.dataset.einheit);
  const auffrischen = () => {
    const n = gewaehlte().length;
    note.textContent = n
      ? `${n} von ${feld.children.length} Einheiten betroffen`
      : 'Nichts gewählt — die Renovierung betrifft das ganze Objekt.';
  };
  feld.addEventListener('click', e => {
    const knopf = e.target.closest('[data-einheit]');
    if (!knopf) return;
    const an = knopf.getAttribute('aria-pressed') === 'true';
    knopf.setAttribute('aria-pressed', String(!an));
    knopf.classList.toggle('gewaehlt', !an);
    auffrischen();
  });
  auffrischen();
  return gewaehlte;
}

/* ---- Renovierung anlegen / bearbeiten ----------------------------------- */

/**
 * @param {object|null} vorhanden  bestehende Renovierung oder null (neu)
 * @param {Array}       einheiten  Einheiten des Objekts [{bezeichnung}]
 * @returns {Promise<object|null>} Datensatz fuers Backend oder null
 */
export function renovierungDialog(vorhanden, einheiten) {
  const r = vorhanden || {};
  const neu = !vorhanden;
  const felder = `
    <div class="field"><label for="rname">Name der Renovierung</label>
      <input class="inp" id="rname" type="text" required
             placeholder="z. B. Bad und Elektrik 1. OG"
             value="${esc(r.name || '')}"></div>
    <div class="feldpaar">
      <div class="field"><label for="rvon">Beginn</label>
        <input class="inp" id="rvon" type="date" value="${esc(r.von || '')}"></div>
      <div class="field"><label for="rbis">Ende</label>
        <input class="inp" id="rbis" type="date" value="${esc(r.bis || '')}"></div>
    </div>
    <div class="field"><label for="rbudget">Budget (€, freiwillig)</label>
      <input class="inp" id="rbudget" type="number" step="0.01" inputmode="decimal"
             placeholder="ohne Budget leer lassen"
             value="${r.budget == null ? '' : esc(r.budget)}"></div>
    ${einheitenFeldHtml(einheiten, r.einheiten)}
    <div class="field"><label for="rnotiz">Notiz</label>
      <input class="inp" id="rnotiz" type="text" value="${esc(r.notiz || '')}"></div>
    <div class="field"><label>Stand</label>
      <div class="bubbles">
        <button type="button" class="bubble${r.abgeschlossen ? ' gewaehlt' : ''}"
                data-fertig aria-pressed="${Boolean(r.abgeschlossen)}">
          <span class="bt">Abgeschlossen</span></button>
      </div></div>`;

  let gewaehlte = () => [];
  return formularDialog({
    titel: neu ? 'Neue Renovierung' : 'Renovierung bearbeiten',
    felder,
    fuellen(form) {
      gewaehlte = einheitenVerdrahten(form);
      const fertigKnopf = form.querySelector('[data-fertig]');
      fertigKnopf.addEventListener('click', () => {
        const an = fertigKnopf.getAttribute('aria-pressed') === 'true';
        fertigKnopf.setAttribute('aria-pressed', String(!an));
        fertigKnopf.classList.toggle('gewaehlt', !an);
      });
    },
    lesen(form) {
      const name = form.querySelector('#rname').value.trim();
      if (!name) {
        form.querySelector('#rname').focus();
        return null;
      }
      return {
        name,
        von: form.querySelector('#rvon').value || null,
        bis: form.querySelector('#rbis').value || null,
        budget: zahl(form.querySelector('#rbudget')),
        einheiten: gewaehlte(),
        notiz: form.querySelector('#rnotiz').value.trim(),
        abgeschlossen:
          form.querySelector('[data-fertig]').getAttribute('aria-pressed') === 'true',
      };
    },
  });
}

/* ---- Rechnung anlegen / bearbeiten -------------------------------------- */

/**
 * @param {object|null} vorhanden  bestehender Posten oder null (neu)
 * @param {string[]}    gewerke    Gewerke-Liste aus der API
 * @param {string}      vorgabeDatum  Startdatum der Renovierung als Vorschlag
 */
export function postenDialog(vorhanden, gewerke, vorgabeDatum = '') {
  const p = vorhanden || {};
  const neu = !vorhanden;
  const auswahl = gewerke.map(g =>
    `<option value="${esc(g)}"${p.gewerk === g ? ' selected' : ''}>${esc(g)}</option>`).join('');
  const felder = `
    <div class="feldpaar">
      <div class="field"><label for="pdatum">Datum</label>
        <input class="inp" id="pdatum" type="date"
               value="${esc(p.datum || (neu ? vorgabeDatum : ''))}"></div>
      <div class="field"><label for="pbetrag">Betrag (€)</label>
        <input class="inp" id="pbetrag" type="number" step="0.01" inputmode="decimal"
               placeholder="0,00"
               value="${p.betrag == null ? '' : esc(p.betrag)}"></div>
    </div>
    <div class="field"><label for="pfirma">Firma</label>
      <input class="inp" id="pfirma" type="text" placeholder="z. B. Elektro Meier"
             value="${esc(p.firma || '')}"></div>
    <div class="field"><label for="pgewerk">Gewerk</label>
      <select class="inp" id="pgewerk"><option value="">— ohne Gewerk —</option>
        ${auswahl}</select></div>
    <div class="field"><label for="pnotiz">Notiz</label>
      <input class="inp" id="pnotiz" type="text" value="${esc(p.notiz || '')}"></div>
    <p class="feldnote">Ein Beleg ohne Kosten ist erlaubt — Betrag einfach
       leer lassen.</p>`;

  return formularDialog({
    titel: neu ? 'Rechnung hinzufügen' : 'Rechnung bearbeiten',
    felder,
    lesen(form) {
      return {
        datum: form.querySelector('#pdatum').value || null,
        betrag: zahl(form.querySelector('#pbetrag')) ?? 0,
        firma: form.querySelector('#pfirma').value.trim(),
        gewerk: form.querySelector('#pgewerk').value,
        notiz: form.querySelector('#pnotiz').value.trim(),
      };
    },
  });
}
