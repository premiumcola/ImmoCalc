/* N216 — Werkzeug „Zeiträume umstellen" (N35): Grenzen verschieben, teilen,
   neuen Zeitraum anlegen und Belege nach Datum neu zuordnen. Reine GUI über
   die Zeitraum-Endpunkte (PATCH /zeitraeume, /teilen, /belege-abgleichen). */

import { api, esc, melde } from '../immo.js';
import { datumwahl } from '../datumwahl.js';
import { slug } from '../objekt-state.js?v=2';

/* N288 — kein natives `<input type="date">`: auf dem iPhone legt der Browser
   dafür einen Systemkalender ÜBER die ganze Maske, und dieser Dialog besteht
   fast nur aus Datumsfeldern. Der echte (ISO-)Wert steht wie überall im
   versteckten Feld, den Kalender baut `datumwahl.js`. */
const datumFeld = (schluessel, label, wert = '') =>
  `<input type="hidden" data-${esc(schluessel)} value="${esc(wert)}">
   <div style="flex:1 1 110px;min-width:0" data-datumwahl="${esc(schluessel)}"
        data-label="${esc(label)}"></div>`;

export async function zeitraumWerkzeug(laden) {
  const dlg = document.createElement('dialog');
  dlg.className = 'immo-dlg zuord-dlg zw-breit';
  document.body.appendChild(dlg);
  dlg.addEventListener('close', () => dlg.remove());
  let veraendert = false;   // ob die Seite dahinter neu geladen werden muss

  const rowHtml = z => {
    const offen = z.status === 'in Arbeit';
    return `<div class="zw-row">
        <div class="zw-lbl">${esc(z.label)}
          <span class="zw-typ">${esc(z.typ)}</span>
          ${offen ? '' : '<span class="zw-zu">abgeschlossen</span>'}</div>
        ${offen ? `<div class="zw-felder">
          ${datumFeld('zw-start', `Start ${z.label}`, z.start || '')}
          ${datumFeld('zw-ende', `Ende ${z.label}`, z.ende || '')}
          <button class="zw-b" data-zw-save="${z.id}">Speichern</button></div>
        <div class="zw-teil"><label>teilen ab</label>
          ${datumFeld('zw-teildatum', `Teilungsdatum ${z.label}`)}
          <button class="zw-b teil" data-zw-teilen="${z.id}">Teilen</button></div>`
        : ''}
      </div>`;
  };

  async function rendern() {
    const det = await api(`/objekte/${encodeURIComponent(slug)}`);
    const alle = (det.zeitraeume || []).slice()
      .sort((a, b) => (a.start || '').localeCompare(b.start || ''));
    // Nur bestückte Zeiträume zeigen — die vielen leeren, automatisch
    // angelegten Alt-Jahre gehören nicht in dieses Werkzeug.
    const zs = alle.filter(z => (z.positionen || 0) > 0);
    const versteckt = alle.length - zs.length;
    const verstecktText = versteckt === 1
      ? '1 leerer Zeitraum ausgeblendet'
      : `${versteckt} leere Zeiträume ausgeblendet`;
    dlg.innerHTML = `
      <div class="zd-kopf"><span class="zd-t">Zeiträume umstellen</span>
        <button class="zd-x" data-nein aria-label="Schließen">×</button></div>
      <p class="zw-intro">Jeder Beleg gehört in <b>genau einen</b> Zeitraum — den,
        in dessen Datumsfenster er fällt. Grenzen ändern oder teilen, dann
        <b>Belege neu zuordnen</b>: die App schiebt jeden Beleg ins richtige
        Fenster und markiert Grenzfälle (z. B. Jahresrechnungen, die anteilig in
        zwei Zeiträume gehören — die teilst du danach per Teilbetrag auf).</p>
      <div class="zw-body">
        <div class="zw-links">
          ${zs.map(rowHtml).join('') || '<p class="zw-intro">Noch kein bestückter Zeitraum.</p>'}
          ${versteckt ? `<div class="zw-leer">${verstecktText}</div>` : ''}
        </div>
        <div class="zw-rechts">
          <div class="zw-neu"><span class="zd-l">Neuer Zeitraum</span>
            <div class="zw-felder">
              ${datumFeld('zw-neu-start', 'Start neuer Zeitraum')}
              ${datumFeld('zw-neu-ende', 'Ende neuer Zeitraum')}
              <button class="zw-b" data-zw-neu>Anlegen</button></div></div>
          <div class="zw-abgl">
            <button class="zd-ok" data-zw-abgleich>Belege nach Datum neu zuordnen</button></div>
          <div class="zw-erg" id="zwErg"></div>
        </div>
      </div>
      <div class="zd-fuss"><button class="zd-ab" data-nein>Schließen</button></div>`;
    datumwahlBauen();
  }

  /* Die Datumsfelder im eigenen Design. `rendern()` baut den Dialog jedes Mal
     neu — deshalb werden die alten Chooser zuerst gelöst, sonst häufen sich
     tote Lauscher an (Muster aus `renovierung/formulare.js`). Das versteckte
     Feld steht unmittelbar vor seinem Halter, siehe `datumFeld`. */
  let chooser = [];
  const datumwahlLoesen = () => {
    for (const c of chooser) {
      try { c.zerstoere(); } catch { /* schon weg */ }
    }
    chooser = [];
  };
  const datumwahlBauen = () => {
    datumwahlLoesen();
    for (const halter of dlg.querySelectorAll('[data-datumwahl]')) {
      const feld = halter.previousElementSibling;
      if (!feld || feld.tagName !== 'INPUT') continue;
      chooser.push(datumwahl(halter, {
        wert: feld.value, label: halter.dataset.label,
        aenderung: neu => { feld.value = neu; },
      }));
      // Das engere Mass dieses Dialogs steht als Regel `.zw-felder
      // .datumwahl-knopf` in objekt.html — nicht hier als `style=`.
    }
  };
  dlg.addEventListener('close', datumwahlLoesen);

  const erg = () => dlg.querySelector('#zwErg');
  const fehlerText = f => String(f?.message || f || 'Das ging nicht.');
  // N52 — Meldungen IM Dialog zeigen: ein modaler <dialog> liegt in der obersten
  // Browser-Ebene, ein normaler Toast (`melde`) läge dahinter (unlesbar). Erfolg
  // grün, Fehler rot, direkt im Ergebnis-Bereich.
  const zeigeErg = (text, art = 'fehler') => {
    const e = erg();
    if (e) e.innerHTML = `<div class="zw-${art}">${esc(text)}</div>`;
  };

  async function speichern(id, row) {
    const start = row.querySelector('[data-zw-start]').value;
    const ende = row.querySelector('[data-zw-ende]').value;
    if (!start || !ende) return zeigeErg('Start und Ende angeben.');
    try {
      await api(`/zeitraeume/${id}`, { method: 'PATCH', body: { start, ende } });
    } catch (f) { return zeigeErg(fehlerText(f)); }
    veraendert = true; await rendern(); zeigeErg('Grenzen gespeichert.', 'ok');
  }

  async function teilen(id, row) {
    const datum = row.querySelector('[data-zw-teildatum]').value;
    if (!datum) return zeigeErg('Teilungsdatum angeben.');
    try {
      await api(`/zeitraeume/${id}/teilen`, { method: 'POST', body: { datum } });
    } catch (f) { return zeigeErg(fehlerText(f)); }
    veraendert = true; await rendern(); zeigeErg('Zeitraum geteilt.', 'ok');
  }

  async function neuAnlegen() {
    const start = dlg.querySelector('[data-zw-neu-start]').value;
    const ende = dlg.querySelector('[data-zw-neu-ende]').value;
    if (!start || !ende) return zeigeErg('Start und Ende angeben.');
    try {
      await api(`/objekte/${encodeURIComponent(slug)}/zeitraeume`,
                { method: 'POST', body: { start, ende } });
    } catch (f) { return zeigeErg(fehlerText(f)); }
    veraendert = true; await rendern(); zeigeErg('Zeitraum angelegt.', 'ok');
  }

  function abgleichBericht(v, angewandt) {
    const moves = (v.moves || []).map(m =>
      `<div class="zw-move">• <b>${esc(m.name)}</b>: ${esc(m.von)} → ${esc(m.nach)}</div>`).join('');
    const GF = { kein_datum: 'kein Belegdatum', kein_zeitraum: 'Datum in keinem Zeitraum',
                 randnah: 'randnah — evtl. zeitanteilig prüfen' };
    const gf = (v.grenzfaelle || []).map(g =>
      `<div class="zw-gf">▲ <b>${esc(g.name)}</b>: ${esc(GF[g.typ] || g.typ)}</div>`).join('');
    const kopf = angewandt
      ? `<b>${v.verschoben} Beleg(e) verschoben.</b>`
      : `<b>${v.wandern} Beleg(e) würden wandern.</b>`;
    const knopf = (!angewandt && v.wandern)
      ? `<div class="zw-abgl" style="margin-top:10px"><button class="zd-ok"
           data-zw-anwenden>Übernehmen — ${v.wandern} Beleg(e) verschieben</button></div>`
      : '';
    erg().innerHTML = kopf
      + (moves ? `<div style="margin-top:6px">${moves}</div>` : '')
      + (gf ? `<div style="margin-top:8px"><b>Grenzfälle (${(v.grenzfaelle || []).length}):</b>${gf}</div>` : '')
      + knopf;
  }

  async function abgleichVorschau() {
    erg().textContent = 'Prüfe …';
    try {
      const v = await api(`/objekte/${encodeURIComponent(slug)}/zeitraeume/belege-abgleichen`,
                          { method: 'POST' });
      abgleichBericht(v, false);
    } catch (f) { zeigeErg(fehlerText(f)); }
  }

  // N323 — der Knopf blieb waehrend des Verschiebens klickbar, ein zweiter
  // Tipp haette dieselben Belege doppelt bewegt.
  async function abgleichAnwenden(knopf) {
    if (knopf) { knopf.disabled = true; knopf.textContent = 'Verschiebe …'; }
    try {
      const v = await api(`/objekte/${encodeURIComponent(slug)}/zeitraeume/`
                          + 'belege-abgleichen?vorschau=false', { method: 'POST' });
      veraendert = true;
      abgleichBericht(v, true);
    } catch (f) { zeigeErg(fehlerText(f)); }
  }

  dlg.addEventListener('click', async e => {
    if (e.target.closest('[data-nein]')) { dlg.close(); if (veraendert) laden(); return; }
    const save = e.target.closest('[data-zw-save]');
    if (save) return speichern(save.dataset.zwSave, save.closest('.zw-row'));
    const teil = e.target.closest('[data-zw-teilen]');
    if (teil) return teilen(teil.dataset.zwTeilen, teil.closest('.zw-row'));
    if (e.target.closest('[data-zw-neu]')) return neuAnlegen();
    if (e.target.closest('[data-zw-abgleich]')) return abgleichVorschau();
    const anwenden = e.target.closest('[data-zw-anwenden]');
    if (anwenden) return abgleichAnwenden(anwenden);
  });

  // N369 — `rendern()` holt Daten und wirft bei jedem Non-2xx. Stand der Wurf
  // vor `showModal()` und fing ihn niemand ab, tat der Klick auf „Umstellen"
  // sichtbar gar nichts: kein Dialog, keine Meldung, nur eine unbehandelte
  // Promise. Jetzt öffnet der Dialog immer — und sagt, was schiefging.
  try {
    await rendern();
  } catch (fehler) {
    melde(String(fehler.message || fehler), 'neg');
    dlg.remove();
    return;
  }
  dlg.showModal();
}
