/* N270 — die Eingabedialoge der Renovierungsseite: die Renovierung selbst
   (Name, Zeitraum, Budget, betroffene Einheiten) und eine einzelne Rechnung
   (Datum, Betrag, Firma, Gewerk).

   Beide bauen auf `baueDialog()` aus immo.js auf und benutzen die vorhandenen
   Formularklassen `.field` / `.inp` / `.btn` — kein eigenes Formularsystem. */

import { baueDialog, esc, melde, heuteIso, zahlAus } from '../immo.js';
import { auswahlfeld } from '../auswahl.js';
import { datumwahl } from '../datumwahl.js';
import { belegVorbereiten, belegAblegen } from '../belegscan.js';
import { analyseDecke } from '../belegbestaetigung.js';

/* N278 — dieselbe Kamera-/Dateiweiche wie auf den Kostenart-Karten: am Telefon
   direkt die Kamera, am Rechner die Dateiauswahl. */
const KEINE_KAMERA = !(navigator.mediaDevices || window.matchMedia?.(
  '(pointer:coarse)').matches);

const KAMERA_SVG = `<svg class="sv-i" viewBox="0 0 24 24" fill="none"
  stroke="currentColor" stroke-width="1.7" stroke-linecap="round"
  stroke-linejoin="round" aria-hidden="true">
  <path d="M3 8.5A1.5 1.5 0 0 1 4.5 7h2.2l1.1-1.8A1 1 0 0 1 8.7 4.7h6.6
           a1 1 0 0 1 .9.5L17.3 7h2.2A1.5 1.5 0 0 1 21 8.5v9A1.5 1.5 0 0 1
           19.5 19h-15A1.5 1.5 0 0 1 3 17.5z"/>
  <circle cx="12" cy="13" r="3.4"/></svg>`;

/* N287 — `zahl()` hiess frueher hier und rechnete `Number(text.replace(',','.'))`.
   Damit wurde aus getippten „1.250" ein Betrag von 1,25 €. Jetzt gilt ueberall
   dieselbe Regel aus `immo.js`. */
const zahl = zahlAus;

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
    form.addEventListener('submit', async e => {
      e.preventDefault();
      // `lesen` darf warten (der Rechnungsdialog legt beim Speichern erst die
      // fotografierte Datei ab). Solange sperrt der Knopf, sonst löst ein
      // zweiter Tipp denselben Vorgang ein zweites Mal aus.
      const knopf = form.querySelector('button[type=submit]');
      knopf.disabled = true;
      let werte = null;
      try {
        werte = await lesen(form, dlg);
      } finally {
        knopf.disabled = false;
      }
      if (werte === null) return;
      fertig(werte);
      dlg.close();
    });
    dlg.addEventListener('cancel', () => fertig(null));
    // Der Name ist das erste Feld — direkt hineinspringen spart einen Tipp.
    // N278 — NICHT, wenn oben ein Foto-Knopf steht: auf dem Telefon risse der
    // Fokus sofort die Tastatur hoch und legte sie über die halbe Maske,
    // obwohl der erste Griff dort meist die Kamera ist.
    if (!form.querySelector('[data-posten-scan]')) {
      setTimeout(() => form.querySelector('.inp')?.focus(), 30);
    }
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
      <div class="field"><label>Beginn</label>
        <input type="hidden" id="rvon" value="${esc(r.von || '')}">
        <div data-vonwahl data-label="Beginn"></div></div>
      <div class="field"><label>Ende</label>
        <input type="hidden" id="rbis" value="${esc(r.bis || '')}">
        <div data-biswahl data-label="Ende"></div></div>
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
  const chooser = [];
  return formularDialog({
    titel: neu ? 'Neue Renovierung' : 'Renovierung bearbeiten',
    felder,
    fuellen(form, dlg) {
      // N277 — Beginn und Ende liefen hier noch über `type="date"`: den Kalender
      // dazu zeichnet das Betriebssystem und legt ihn auf iOS über die ganze
      // Maske. Der Rechnungsdialog hatte das mit N278 schon abgelegt, dieser
      // nicht. Jetzt dieselbe `datumwahl` wie dort — samt `zerstoere()`, sonst
      // bleiben Popover-Lauscher am Dokument hängen, wenn der Dialog zugeht.
      for (const [platz, feld, label] of [['[data-vonwahl]', '#rvon', 'Beginn'],
                                          ['[data-biswahl]', '#rbis', 'Ende']]) {
        const versteckt = form.querySelector(feld);
        chooser.push(datumwahl(form.querySelector(platz), {
          wert: versteckt.value, label,
          aenderung: neuWert => { versteckt.value = neuWert; },
        }));
      }
      dlg.addEventListener('close', () => {
        for (const c of chooser) { try { c.zerstoere(); } catch { /* schon weg */ } }
      }, { once: true });
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
/* N279 — heute als ISO, für den Vergleich „liegt das Datum in der Zukunft?".
   N287: `heuteIso` kommt jetzt aus `immo.js` und rechnet in LOKALER Zeit. Die
   Fassung hier nahm `toISOString()` — das rechnet nach UTC um und liefert
   zwischen Mitternacht und 2 Uhr morgens den Vortag. Wer nachts eine Rechnung
   von heute erfasste, bekam „liegt in der Zukunft" und das Datum flog raus. */

/**
 * N279 — ein Rechnungsdatum in der Zukunft ist immer ein Lesefehler.
 *
 * Die Auslese griff auf einer Handwerkerrechnung schon einmal das Fälligkeits-
 * oder ein Angebotsdatum ab und trug den 21.08.2026 ein. Bewusst NUR hier und
 * nicht in der Auslese selbst: eine Abbuchungsvorankündigung nennt sehr wohl
 * künftige Termine (N262), dort wäre dieselbe Regel falsch.
 */
const inDerZukunft = iso => Boolean(iso) && iso > heuteIso();

export function postenDialog(vorhanden, gewerke, vorgabeDatum = '',
                             objekt = '', renovierungId = null) {
  const p = vorhanden || {};
  const neu = !vorhanden;
  // N278 — der Weg übers Foto steht VOR den Feldern, wie in jeder anderen
  // Eingabemaske: er erspart im Regelfall das Abtippen, und danach steht
  // dieselbe Maske gefüllt da. Nur beim Anlegen — eine bestehende Rechnung
  // wird korrigiert, nicht neu fotografiert.
  const scanHtml = (neu && objekt) ? `
    <button type="button" class="scan-vorschlag" data-posten-scan>
      ${KAMERA_SVG}
      <span class="sv-t">${KEINE_KAMERA
        ? 'Rechnung als Datei wählen' : 'Rechnung abfotografieren'}</span>
      <span class="sv-u">Datum, Betrag, Firma und Gewerk werden erkannt und
        hier eingetragen. Mehrere Seiten? Im Kamerafenster unten „+".</span>
    </button>` : '';
  const felder = `${scanHtml}
    <div class="feldpaar">
      <div class="field"><label>Datum</label>
        <input type="hidden" id="pdatum" value="${esc(p.datum || '')}">
        <div data-datumwahl data-label="Datum"></div></div>
      <div class="field"><label for="pbetrag">Betrag (€)</label>
        <input class="inp" id="pbetrag" type="text" inputmode="decimal"
               placeholder="0,00"
               value="${p.betrag == null ? '' : esc(p.betrag)}"></div>
    </div>
    <div class="field"><label for="pfirma">Firma</label>
      <input class="inp" id="pfirma" type="text" placeholder="z. B. Elektro Meier"
             value="${esc(p.firma || '')}"></div>
    <div class="field"><label>Gewerk</label>
      <input type="hidden" id="pgewerk" value="${esc(p.gewerk || '')}">
      <div data-gewerkwahl data-label="Gewerk"></div></div>
    <div class="field"><label for="pnotiz">Notiz</label>
      <input class="inp" id="pnotiz" type="text" value="${esc(p.notiz || '')}"></div>
    <p class="feldnote">Ein Beleg ohne Kosten ist erlaubt — Betrag einfach
       leer lassen.</p>`;

  // Der vorbereitete, noch NICHT abgelegte Scan. Er wartet auf „Speichern" —
  // bricht der Nutzer ab, wurde nichts in die Cloud geschrieben.
  let offen = null;
  const chooser = [];

  return formularDialog({
    titel: neu ? 'Rechnung hinzufügen' : 'Rechnung bearbeiten',
    felder,
    fuellen(form, dlg) {
      const datumFeld = form.querySelector('#pdatum');
      const gewerkFeld = form.querySelector('#pgewerk');
      // N278 — die eigenen Chooser statt `type="date"` und `<select>`: das
      // native Datumsfeld legt auf iOS einen Systemkalender ÜBER die ganze
      // Maske, und die aufgeklappte Select-Liste zeichnet ebenfalls das
      // Betriebssystem. Genau deshalb gibt es `datumwahl.js`/`auswahl.js`
      // (siehe objekt/formular.js) — sie fehlten hier schlicht.
      chooser.push(datumwahl(form.querySelector('[data-datumwahl]'), {
        wert: datumFeld.value, label: 'Datum',
        aenderung: neuWert => { datumFeld.value = neuWert; },
      }));
      chooser.push(auswahlfeld(form.querySelector('[data-gewerkwahl]'), {
        optionen: [{ wert: '', text: '— ohne Gewerk —' },
                   ...gewerke.map(g => ({ wert: g, text: g }))],
        wert: gewerkFeld.value, label: 'Gewerk',
        aenderung: neuWert => { gewerkFeld.value = neuWert; },
      }));
      dlg.addEventListener('close', () => {
        for (const c of chooser) { try { c.zerstoere(); } catch { /* schon weg */ } }
      }, { once: true });

      form.querySelector('[data-posten-scan]')?.addEventListener('click', async e => {
        const knopf = e.currentTarget;
        if (knopf.disabled) return;
        knopf.disabled = true;
        const paket = await rechnungScannen(objekt, renovierungId);
        knopf.disabled = false;
        if (!paket) return;
        offen = paket.vorbereitet;
        const w = paket.werte;
        // Ein gelesenes Datum in der Zukunft wird verworfen, nicht übernommen —
        // dann bleibt das Feld leer und fällt auf, statt still falsch zu sein.
        if (w.datum && inDerZukunft(w.datum)) {
          delete w.datum;
          melde('Das gelesene Rechnungsdatum lag in der Zukunft — bitte von '
            + 'Hand eintragen.', '');
        }
        if (w.datum) { datumFeld.value = w.datum; chooser[0].setze?.(w.datum); }
        if (w.betrag != null) {
          form.querySelector('#pbetrag').value =
            String(w.betrag).replace('.', ',');
        }
        if (w.firma) form.querySelector('#pfirma').value = w.firma;
        if (w.gewerk) { gewerkFeld.value = w.gewerk; chooser[1].setze?.(w.gewerk); }
        if (w.notiz && !form.querySelector('#pnotiz').value) {
          form.querySelector('#pnotiz').value = w.notiz;
        }
        const anzahl = Object.keys(w).length;
        melde(anzahl
          ? `${anzahl} ${anzahl === 1 ? 'Angabe' : 'Angaben'} erkannt — bitte prüfen`
          : 'Aus dem Foto liess sich nichts Sicheres lesen', anzahl ? 'pos' : '');
      });
    },
    async lesen(form) {
      const werte = {
        datum: form.querySelector('#pdatum').value || null,
        betrag: zahl(form.querySelector('#pbetrag')) ?? 0,
        firma: form.querySelector('#pfirma').value.trim(),
        gewerk: form.querySelector('#pgewerk').value,
        notiz: form.querySelector('#pnotiz').value.trim(),
      };
      // N279 — eine Rechnung ohne jede Angabe ist keine Rechnung. Der Dialog
      // bleibt offen (`null`), statt eine leere Zeile in die Liste zu legen,
      // die niemand mehr zuordnen kann. Ein Beleg OHNE Betrag bleibt erlaubt —
      // dafür genügt eine Firma, ein Datum oder eine Notiz.
      if (!werte.datum && !werte.betrag && !werte.firma && !werte.gewerk
          && !werte.notiz && !offen) {
        melde('Bitte wenigstens eine Angabe machen — oder abbrechen.', 'neg');
        return null;
      }
      if (inDerZukunft(werte.datum)) {
        melde('Das Rechnungsdatum liegt in der Zukunft — bitte prüfen.', 'neg');
        return null;
      }
      // Erst jetzt wandert die Datei in die Cloud — und wenn das scheitert,
      // steht die Rechnung trotzdem. Der Beleg ist Beiwerk, die Zahl nicht.
      if (offen) {
        try {
          const abgelegt = await belegAblegen(offen);
          werte.quelle_dokument_id = abgelegt?.id ?? null;
        } catch (fehler) {
          melde(`Rechnung gespeichert — die Datei konnte aber nicht abgelegt `
            + `werden: ${fehler.message || fehler}`, 'neg');
        }
        offen = null;
      }
      return werte;
    },
  });
}

/**
 * N278 — fotografieren, zuschneiden, auslesen. Gibt `{vorbereitet, werte}`
 * zurück oder `null`, wenn abgebrochen wurde bzw. nichts zu holen war.
 *
 * Übersetzt wird auf dem Server: `bereich=renovierungsposten` liefert die
 * Auslese schon auf die Feldnamen dieser Maske gemünzt (`feldzuordnung.py`).
 * Hier wird nichts geraten.
 */
async function rechnungScannen(objekt, renovierungId = null) {
  const dateien = await dateienWaehlen();
  if (!dateien) return null;
  let deckeWeg = null;
  let vorbereitet = null;
  try {
    vorbereitet = await belegVorbereiten(dateien, {
      objekt, kategorie: 'Renovierung', bereich: 'renovierungsposten',
      // N289 — der Projektordner des Bauvorhabens; ohne ihn lag die Rechnung
      // vorher unter „99_Sonstiges".
      renovierungId,
      titel: 'Rechnung abfotografieren',
    }, () => { deckeWeg = analyseDecke('Rechnung wird gelesen …'); });
  } catch (fehler) {
    melde(String(fehler.message || 'Der Scan hat nicht geklappt.'), 'neg');
    return null;
  } finally {
    // Die Decke geht IMMER weg — auch wenn das Auslesen scheitert.
    if (deckeWeg) { try { deckeWeg(); } catch { /* egal */ } }
  }
  if (!vorbereitet) return null;                 // Zuschnitt abgebrochen
  return { vorbereitet, werte: vorbereitet.ki?.formwerte || {} };
}

/** Kamera bzw. Dateiauswahl öffnen und auf die Wahl warten. Das `click()` ist
    der Punkt: ein Dateifeld öffnet sich nicht von selbst, nur weil es im DOM
    steht (N263). Es muss im selben Durchlauf wie die Berührung fallen. */
function dateienWaehlen() {
  return new Promise(fertig => {
    const feld = document.createElement('input');
    feld.type = 'file';
    feld.accept = 'image/*,application/pdf';
    feld.multiple = true;
    if (!KEINE_KAMERA) feld.capture = 'environment';
    feld.hidden = true;
    document.body.appendChild(feld);
    let erledigt = false;
    const abschliessen = dateien => {
      if (erledigt) return;
      erledigt = true;
      feld.remove();
      fertig(dateien);
    };
    feld.addEventListener('change', () => {
      const dateien = Array.from(feld.files || []);
      abschliessen(dateien.length ? dateien : null);
    }, { once: true });
    feld.click();
    window.addEventListener('focus', () => {
      setTimeout(() => { if (!feld.files?.length) abschliessen(null); }, 2000);
    }, { once: true });
  });
}
