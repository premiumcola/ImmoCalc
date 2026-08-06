/* N216 — Zuordnen-Dialog (CCCIX/CCCX/CCCXI):

   Drei Fragen in einem Blatt: Wohin gehört das Dokument (Rubrik)? Wird daraus
   eine Kostenposition oder ist es nur ein Info-Beleg? Und hängt es an einem
   bestehenden Eintrag (z. B. die Bestätigung an ihrem Kaufvertrag)? */

import { esc } from '../immo.js';
import { kostenIcon } from '../kostenicons.js';
import { cfgFuer, ERWERB_KATEGORIE } from '../objekt-felder.js?v=2';
import { istGrundstueck } from '../objekt-state.js?v=2';
import { RUBRIK_WAHL, bereicheDaten } from './state.js';

export function zuordnenDialog(dok, vorgabe, umhaengen = false) {
  const wahlen = RUBRIK_WAHL.filter(r => !(r.nurHaus && istGrundstueck()));
  let rubrik = vorgabe && wahlen.some(r => r.wert === vorgabe) ? vorgabe
    : (wahlen[0] && wahlen[0].wert);
  let art = 'position';
  let anId = '';

  return new Promise(fertig => {
    const dlg = document.createElement('dialog');
    dlg.className = 'immo-dlg zuord-dlg';
    document.body.appendChild(dlg);
    dlg.addEventListener('close', () => dlg.remove());
    dlg.addEventListener('cancel', () => fertig(null));

    const male = () => {
      const cfg = wahlen.find(r => r.wert === rubrik) || wahlen[0];
      // Bestehende Einträge derselben Rubrik — daran lässt sich anhängen.
      // Erwerbsnebenkosten und Finanzamt teilen sich die Zahlungen und werden
      // über die Kategorie auseinandergehalten (CCCXIX).
      const roh = cfg.wert === 'erwerbskosten'
        ? (bereicheDaten.zahlungen || []).filter(z => z.kategorie === ERWERB_KATEGORIE)
        : cfg.wert === 'zahlungen'
          ? (bereicheDaten.zahlungen || []).filter(z => z.kategorie !== ERWERB_KATEGORIE)
          : (bereicheDaten[cfg.wert] || []);
      const eintraege = roh.map(e => ({
        id: e.id,
        text: (cfgFuer(cfg.wert)?.name?.(e)) || e.art || e.bezeichnung || `#${e.id}`,
      }));
      dlg.innerHTML = `
        <div class="zd-kopf">
          <span class="zd-t">${umhaengen ? 'Umhängen' : 'Zuordnen'}</span>
          <button class="zd-x" data-nein aria-label="Schließen">×</button>
        </div>
        <p class="zd-datei">${esc(dok.dateiname)}</p>
        ${umhaengen ? `<button class="zd-loesen" data-entfernen>Zuordnung ganz lösen
          — Beleg wieder offen</button>` : ''}

        <div class="zd-block"><span class="zd-l">Wohin gehört es?</span>
          <div class="zd-chips">${wahlen.map(r => `
            <button class="zd-chip${r.wert === rubrik ? ' an' : ''}" data-rubrik="${r.wert}">
              <span class="zi">${kostenIcon(r.ikon)}</span>${esc(r.titel)}</button>`).join('')}
          </div></div>

        <div class="zd-block"><span class="zd-l">Was ist es?</span>
          <div class="zd-chips">
            <button class="zd-chip${art === 'position' ? ' an' : ''}" data-art="position"
              ${cfg.wiederkehrend ? '' : ''}>Kostenposition (mit Betrag)</button>
            <button class="zd-chip${art === 'beleg' ? ' an' : ''}" data-art="beleg"
              >Nur Beleg (Information)</button>
          </div>
          <span class="zd-hint">${art === 'position'
            ? (cfg.wiederkehrend
                ? 'Wiederkehrend — trägt einen Betrag je Jahr/Turnus.'
                : 'Einmalig — trägt einen Betrag (z. B. Kaufpreis).')
            : 'Hängt ohne Betrag als Information am Eintrag, z. B. eine Bestätigung.'}</span>
        </div>

        ${eintraege.length ? `<div class="zd-block">
          <span class="zd-l">An einen bestehenden Eintrag hängen?</span>
          <div class="zd-chips">
            <button class="zd-chip${!anId ? ' an' : ''}" data-an="">neuer Eintrag</button>
            ${eintraege.map(e => `<button class="zd-chip${String(anId) === String(e.id)
              ? ' an' : ''}" data-an="${e.id}">${esc(e.text)}</button>`).join('')}
          </div></div>` : ''}

        <div class="zd-fuss">
          <button class="zd-ab" data-nein>Abbrechen</button>
          <button class="zd-ok" data-ja>Zuordnen</button>
        </div>`;
    };

    dlg.addEventListener('click', e => {
      const r = e.target.closest('[data-rubrik]');
      if (r) { rubrik = r.dataset.rubrik; anId = ''; male(); return; }
      const a = e.target.closest('[data-art]');
      if (a) { art = a.dataset.art; male(); return; }
      const an = e.target.closest('[data-an]');
      if (an) { anId = an.dataset.an; male(); return; }
      if (e.target.closest('[data-entfernen]')) { fertig({ entfernen: true }); dlg.close(); return; }
      if (e.target.closest('[data-nein]')) { fertig(null); dlg.close(); return; }
      if (e.target.closest('[data-ja]')) {
        const cfg = wahlen.find(x => x.wert === rubrik) || wahlen[0];
        fertig({ ziel: rubrik, art,
                 an_typ: anId ? cfg.typ : null, an_id: anId ? Number(anId) : null });
        dlg.close();
      }
    });
    male();
    dlg.showModal();
  });
}
