/* N309f — das Kontaktblatt: ein Dialog, in dem alles zu einer Firma steht und
   gepflegt wird. Kontaktdaten werden beim Speichern geschickt, Kundennummern
   sofort (sie sind eigene Datensätze und sollen nicht an einem „Speichern"
   hängen, das man vergisst).

   Gesendet wird nur, was WIRKLICH geändert wurde: jedes gesetzte Feld gilt dem
   Backend danach als handgepflegt und ist vor der nächsten Ernte geschützt —
   ein blindes PATCH aller Felder würde also den ganzen Kontakt einfrieren. */

import { baueDialog, esc, frage, melde } from '../immo.js';
import { auswahlfeld } from '../auswahl.js';
import { kontaktZeichen } from './firmen.js';
import * as Daten from './daten.js';

const FELDER = [
  ['firma', 'Firma', 'text'],
  ['telefon', 'Telefon', 'tel'],
  ['email', 'E-Mail', 'email'],
  ['web', 'Website', 'text'],
  ['adresse', 'Adresse', 'text'],
  ['notiz', 'Notiz', 'text'],
];

/* Übliche Nummernarten. Was im Bestand schon vorkommt, steht vorn — der Rest
   sind die Fälle, die es noch nicht gibt (sonst müsste man sie tippen). */
const NUMMERNARTEN = ['Kundennummer', 'Vertragsnummer', 'Police',
  'Darlehensnummer', 'Zählernummer', 'Mitgliedsnummer', 'Rechnungskonto'];

const hand = (k, feld) => (k.handgepflegt || []).includes(feld)
  ? '<i class="hand" title="Von Hand gepflegt — die Ernte aus Belegen'
    + ' überschreibt diesen Wert nicht.">gepflegt</i>' : '';

function feldHtml(k, [name, label, typ]) {
  return `<div class="field" data-feldbox="${name}">
      <label for="kb-${name}">${esc(label)}${hand(k, name)}</label>
      <input class="inp" id="kb-${name}" type="${typ}" name="${name}"
             value="${esc(k[name] || '')}"
             placeholder="${name === 'telefon' ? '0911 123456'
               : name === 'email' ? 'kontakt@firma.de'
               : name === 'web' ? 'firma.de' : ''}"></div>`;
}

function nummernHtml(k) {
  if (!k.nummern?.length) {
    return `<p class="feldnote" data-nrleer>Noch keine Kundennummer —
      mit „＋" eintragen.</p>`;
  }
  // Zwei feste Zeilen statt eines Flatterumbruchs: die Nummer oben, Art und
  // Immobilie klein darunter. Das „×" bleibt daneben stehen.
  return `<ul class="nrliste">${k.nummern.map(n => `<li>
      <span class="nrtext">
        <span class="nrwert">${esc(n.nummer)}</span>
        <span class="nrmeta"><i>${esc(n.art || 'Kundennummer')}</i>${
          n.objekt_name ? `<em>${esc(n.objekt_name)}</em>` : ''}</span>
      </span>
      <button class="del" type="button" data-nr-weg="${n.id}"
              aria-label="Nummer entfernen" title="Nummer entfernen">×</button>
    </li>`).join('')}</ul>`;
}

/**
 * Öffnet das Kontaktblatt.
 * @param {object} k          Kontakt (wie ihn die API liefert)
 * @param {object} umgebung   {arten, gewerke, objekte}
 * @param {string} fokusFeld  Feld, in das gesprungen wird („telefon" …)
 * @returns {Promise<boolean>} true, wenn sich etwas geändert hat
 */
export function kontaktBlatt(k, umgebung, fokusFeld = '') {
  const { arten = [], gewerke = [], objekte = [] } = umgebung;
  const nrArten = [...new Set([...(k.nummern || []).map(n => n.art)
    .filter(Boolean), ...NUMMERNARTEN])];

  return new Promise(fertig => {
    const dlg = baueDialog(`
      <div class="blattkopf">
        <span class="kikon gross">${kontaktZeichen(k)}</span>
        <span class="dt">${esc(k.firma)}</span>
      </div>
      <form novalidate class="blatt">
        <div class="feldpaar">
          <div class="field"><label>Art${hand(k, 'art')}</label>
            <div data-artwahl></div></div>
          <div class="field"><label>Gewerk${hand(k, 'gewerk')}</label>
            <div data-gewerkwahl></div></div>
        </div>
        ${FELDER.map(f => feldHtml(k, f)).join('')}

        <div class="hh"><h2 class="sec">Kundennummern</h2>
          <button class="plus" type="button" data-nr-auf
                  aria-label="Kundennummer hinzufügen"
                  title="Kundennummer hinzufügen">＋</button></div>
        <div class="nrform" data-nrform hidden>
          <div class="field"><label for="kb-nr">Nummer</label>
            <input class="inp" id="kb-nr" type="text" inputmode="numeric"
                   placeholder="z. B. 644685800"></div>
          <div class="feldpaar">
            <div class="field"><label>Art</label><div data-nrartwahl></div></div>
            <div class="field"><label>Immobilie</label>
              <div data-nrobjektwahl></div></div>
          </div>
          <button class="btn leise" type="button" data-nr-neu>Nummer
            hinzufügen</button>
        </div>
        <div data-nrliste>${nummernHtml(k)}</div>

        <button class="btn" type="submit">Speichern</button>
        <button class="btn leise" type="button" data-abbruch>Abbrechen</button>
        <button class="btn gefahr" type="button" data-weg
                style="margin-top:18px">Kontakt löschen</button>
      </form>`);

    const form = dlg.querySelector('form');
    const chooser = [];
    let geaendert = false;
    let stand = { ...k };                 // Stand nach dem letzten Speichern

    /* ---- Art und Gewerk ------------------------------------------------- */
    const wahl = { art: stand.art || '', gewerk: stand.gewerk || '' };
    chooser.push(auswahlfeld(form.querySelector('[data-artwahl]'), {
      optionen: [...new Set([...arten, stand.art].filter(Boolean))]
        .map(a => ({ wert: a, text: a })),
      wert: wahl.art, label: 'Art',
      aenderung: neu => { wahl.art = neu; },
    }));
    chooser.push(auswahlfeld(form.querySelector('[data-gewerkwahl]'), {
      optionen: [{ wert: '', text: 'ohne Gewerk' },
        ...[...new Set([...gewerke, stand.gewerk].filter(Boolean))]
          .map(g => ({ wert: g, text: g }))],
      wert: wahl.gewerk, label: 'Gewerk',
      aenderung: neu => { wahl.gewerk = neu; },
    }));

    /* ---- Kundennummer hinzufügen ---------------------------------------- */
    const neueNr = { art: nrArten[0] || 'Kundennummer', objekt: '' };
    chooser.push(auswahlfeld(form.querySelector('[data-nrartwahl]'), {
      optionen: nrArten.map(a => ({ wert: a, text: a })),
      wert: neueNr.art, label: 'Art der Nummer',
      aenderung: neu => { neueNr.art = neu; },
    }));
    chooser.push(auswahlfeld(form.querySelector('[data-nrobjektwahl]'), {
      optionen: [{ wert: '', text: 'ohne Immobilie' },
        ...objekte.map(o => ({ wert: o.slug, text: o.titel || o.name }))],
      wert: '', label: 'Immobilie',
      aenderung: neu => { neueNr.objekt = neu; },
    }));

    const nrForm = form.querySelector('[data-nrform]');
    form.querySelector('[data-nr-auf]').addEventListener('click', () => {
      nrForm.hidden = !nrForm.hidden;
      // „Noch keine Kundennummer — mit ＋ eintragen" wäre über dem offenen
      // Formular ein Hinweis auf das, was man gerade tut.
      const leer = form.querySelector('[data-nrleer]');
      if (leer) leer.hidden = !nrForm.hidden;
      if (!nrForm.hidden) form.querySelector('#kb-nr').focus();
    });

    /** Die Liste neu zeichnen — nach jedem Hinzufügen oder Entfernen. */
    async function nummernFrisch() {
      try { stand = await Daten.kontaktHolen(k.id); }
      catch { return; }
      form.querySelector('[data-nrliste]').innerHTML = nummernHtml(stand);
    }

    async function nummerAnlegen() {
      const feld = form.querySelector('#kb-nr');
      const nummer = feld.value.trim();
      if (!nummer) { feld.focus(); return; }
      try {
        await Daten.nummerAnlegen(k.id, { nummer, art: neueNr.art,
                                          objekt: neueNr.objekt || null });
        geaendert = true;
        feld.value = '';
        nrForm.hidden = true;
        await nummernFrisch();
        melde('Kundennummer gespeichert', 'pos');
      } catch (fehler) { melde(String(fehler.message || fehler), 'neg'); }
    }

    form.querySelector('[data-nr-neu]').addEventListener('click', nummerAnlegen);
    // Enter im Nummernfeld legt die Nummer an, statt das ganze Blatt zu speichern.
    form.querySelector('#kb-nr').addEventListener('keydown', e => {
      if (e.key !== 'Enter') return;
      e.preventDefault();
      nummerAnlegen();
    });

    form.addEventListener('click', async e => {
      const weg = e.target.closest('[data-nr-weg]');
      if (!weg) return;
      const ok = await frage('Kundennummer entfernen',
        'Die Nummer wird aus dem Kontaktbuch gelöscht.',
        { knopf: 'Entfernen', gefahr: true });
      if (!ok) return;
      try {
        await Daten.nummerLoeschen(weg.dataset.nrWeg);
        geaendert = true;
        await nummernFrisch();
      } catch (fehler) { melde(String(fehler.message || fehler), 'neg'); }
    });

    /* ---- Kontakt löschen ------------------------------------------------- */
    form.querySelector('[data-weg]').addEventListener('click', async () => {
      const ok = await frage('Kontakt löschen',
        `„${stand.firma}" wird mit allen Kundennummern aus dem Kontaktbuch `
        + 'entfernt. Belege und Rechnungen bleiben unangetastet.',
        { knopf: 'Löschen', gefahr: true });
      if (!ok) return;
      try {
        await Daten.kontaktLoeschen(k.id);
        fertig(true);
        dlg.close();
      } catch (fehler) { melde(String(fehler.message || fehler), 'neg'); }
    });

    /* ---- Speichern ------------------------------------------------------- */
    form.querySelector('[data-abbruch]').addEventListener('click', () => {
      fertig(geaendert);
      dlg.close();
    });

    form.addEventListener('submit', async e => {
      e.preventDefault();
      const neu = {};
      for (const [name] of FELDER) {
        const wert = form.querySelector(`#kb-${name}`).value.trim();
        if (wert !== String(stand[name] || '')) neu[name] = wert;
      }
      if (wahl.art !== (stand.art || '')) neu.art = wahl.art;
      if (wahl.gewerk !== (stand.gewerk || '')) neu.gewerk = wahl.gewerk;
      if (!Object.keys(neu).length) { fertig(geaendert); dlg.close(); return; }
      const knopf = form.querySelector('button[type=submit]');
      knopf.disabled = true;
      try {
        await Daten.kontaktAendern(k.id, neu);
        melde('Kontakt gespeichert', 'pos');
        fertig(true);
        dlg.close();
      } catch (fehler) {
        knopf.disabled = false;
        melde(String(fehler.message || fehler), 'neg');
      }
    });

    dlg.addEventListener('cancel', () => fertig(geaendert));
    dlg.addEventListener('close', () => {
      for (const c of chooser) { try { c.zerstoere(); } catch { /* schon weg */ } }
    }, { once: true });

    // Wer über „Telefon eintragen" hereinkommt, steht sofort im richtigen Feld.
    if (fokusFeld) {
      setTimeout(() => form.querySelector(`#kb-${fokusFeld}`)?.focus(), 40);
    }
  });
}
