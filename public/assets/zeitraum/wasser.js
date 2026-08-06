/* zeitraum/wasser.js — Wasser-Detail (inline), Betragsfelder,
   Rechnungsmenge, wasser-spezifischer Beleg-Drop-Dialog, Position leeren.

   Die Wasser-Sammelposition ist eine Zusammenfassung dreier Bestandteile
   (Frisch-/Schmutz-/Niederschlagswasser). Beim Aufklappen lädt sie ihre
   Detailübersicht inline (N74). */

import { api, eur, esc, frage, melde } from '../immo.js';
import * as state from './state.js';
import { normUml, istWasserSammel } from './modell.js';
import { m3, zahl } from './helpers.js';

/* N57 — die Checklisten-Position hinter einem der drei Bestandteile. */
export function wasserPosFuer(art) {
  const treffer = {
    wasser: k => istWasserSammel(k),
    schmutz: k => {
      const n = normUml(k.kostenart);
      return n.includes('abwasser') || n.includes('schmutzwasser');
    },
    niederschlag: k => normUml(k.kostenart).includes('niederschlag'),
  }[art];
  return (state.daten?.checkliste || []).find(treffer) || null;
}

/* N78 — einen Bereichsbetrag auf seine Wasser-Position schreiben. */
export async function wasserPosBetragSchreiben(art, betrag) {
  if (!(betrag > 0)) return;
  const pos = wasserPosFuer(art);
  if (!pos) return;
  if (pos.position_id) {
    await api(`/positionen/${pos.position_id}`, { method: 'PATCH', body: { betrag } });
  } else {
    await api(`/zeitraeume/${state.daten.id}/positionen`,
      { method: 'POST', body: { kostenart: pos.kostenart, betrag } });
  }
}

/* N57 — Kostenbox im Popup als Eingabefeld oder lesbarer Wert. */
export function wdKostenBox(label, art, kostenWert) {
  const pos = wasserPosFuer(art);
  if (pos && state.daten.status === 'in Arbeit') {
    const val = pos.betrag != null ? pos.betrag : (kostenWert ?? '');
    const ziel = pos.position_id
      ? `data-wasser-pid="${pos.position_id}"`
      : `data-wasser-ka="${esc(pos.kostenart)}"`;
    return `<div class="wd-kbox wd-edit"><span class="wd-kl">${label}</span>
      <span class="wd-kin"><input type="number" step="0.01" inputmode="decimal"
        value="${val ?? ''}" ${ziel} data-wert="${val ?? ''}"
        aria-label="${label} Betrag"><span class="wd-kve">€</span></span></div>`;
  }
  return `<div class="wd-kbox"><span class="wd-kl">${label}</span>
    <span class="wd-kv">${eur(kostenWert)}</span></div>`;
}

/* N57 — einen der drei Bestandteil-Beträge speichern. */
export async function wasserBetragSpeichern(input) {
  const roh = String(input.value).trim().replace(',', '.');
  if (roh === '') return;
  const betrag = Number(roh);
  if (!Number.isFinite(betrag)) { melde('Ungültiger Betrag', 'neg'); return; }
  if (String(input.dataset.wert) === String(betrag)) return;
  input.dataset.wert = String(betrag);
  try {
    if (input.dataset.wasserPid) {
      await api(`/positionen/${input.dataset.wasserPid}`,
        { method: 'PATCH', body: { betrag } });
    } else {
      await api(`/zeitraeume/${state.zid}/positionen`,
        { method: 'POST', body: { kostenart: input.dataset.wasserKa, betrag } });
    }
    melde('✓ Betrag gespeichert', 'pos');
    const { laden } = await import('./checkliste.js');
    await laden();
  } catch (fehler) { melde(String(fehler.message || fehler), 'neg'); }
}

/* N116/N144 — abgerechnete Menge aus dem Bescheid am Zeitraum. */
export async function wasserRechnungsmengeSpeichern(feld) {
  const wert = (feld.value || '').trim();
  try {
    await api(`/zeitraeume/${state.zid}/wasser/rechnungsmenge`,
      { method: 'PUT', body: { rechnung_m3: wert === '' ? null : Number(wert) } });
    const box = feld.closest('[data-wasser-inline]');
    if (box) await fuelleWasserInline(box);
  } catch (fehler) { melde(String(fehler.message || fehler), 'neg'); }
}

export async function fuelleWasserInline(el) {
  try {
    const d = await api(`/zeitraeume/${el.dataset.wasserInline}/wasser`
      + `?schluessel=${state.wasserSchluessel}`);
    state.setWasserDetailCache(d);
    el.innerHTML = wasserDetailInhalt(d);
  } catch (fehler) {
    el.innerHTML = `<div class="wd-lade">Detailübersicht nicht ladbar: ${
      esc(String(fehler.message || fehler))}</div>`;
  }
}

/* N185 — die Wasser-Sammelposition bewusst leeren (für einen neuen Bescheid). */
export async function wasserPositionLeeren() {
  const ok = await frage('Wasser-Position leeren?',
    'Die drei Wasser-Beträge (Frisch-, Schmutz-, Niederschlagswasser) und die '
    + 'abgerechnete Rechnungsmenge werden auf 0 gesetzt — die Zähler darunter '
    + 'bleiben. Danach kannst du einen neuen Beleg fotografieren.',
    { knopf: 'Leeren', gefahr: true });
  if (!ok) return;
  try {
    await api(`/zeitraeume/${state.zid}/wasser/leeren?force=true`, { method: 'POST' });
    melde('Wasser-Position geleert — die Zähler bleiben.', 'pos');
    const wi = (state.daten.checkliste || []).findIndex(istWasserSammel);
    if (wi >= 0) state.offen.delete(wi);
    const { laden } = await import('./checkliste.js');
    await laden();
  } catch (fehler) { melde(String(fehler.message || fehler), 'neg'); }
}

/* Der Rumpf des Wasser-Popups aus der /wasser-Antwort. */
export function wasserDetailInhalt(d) {
  const k = d.kosten || {};
  const kbox = (label, wert, extra = '') =>
    `<div class="wd-kbox${extra}"><span class="wd-kl">${label}</span>
      <span class="wd-kv">${wert}</span></div>`;
  // N113 - Umschalter Personen/Fläche.
  const schl = d.schluessel || 'personen';
  const umschalter = `<div class="wd-schl">
      <span class="wd-schl-l">Rest verteilen nach</span>
      <button type="button" class="wd-sb${schl === 'personen' ? ' an' : ''}"
        data-wasser-schluessel="personen">Personen</button>
      <button type="button" class="wd-sb${schl === 'flaeche' ? ' an' : ''}"
        data-wasser-schluessel="flaeche">Fläche</button>
      <span class="wd-schl-l" style="margin-left:auto">Laut Rechnung</span>
      <input class="wd-rm" type="number" step="0.1" data-wasser-rechnung
        value="${d.rechnung_m3 ?? ''}" placeholder="m³"
        aria-label="Abgerechnete Menge laut Bescheid in m³">
    </div>${(d.abweichung_m3 != null && Math.abs(d.abweichung_m3) > 0.05)
      ? `<div class="ho-warn">Zwei Zahlen, beide bleiben stehen: der
          <b>Zählerwert</b> ${m3(d.abgelesen_m3)} (eigener Hauptzähler) und die
          <b>abgerechnete Menge</b> ${m3(d.rechnung_m3)} (Bescheid des
          Versorgers). Verteilt wird auf die abgerechnete Menge. Die Abweichung
          von ${m3(d.abweichung_m3)} bleibt damit unverteilt — sie ist ein
          offener Punkt zwischen Ablesung und Abrechnung, den die nächsten
          Jahre klären.</div>` : ''}`;
  const kosten = umschalter + `<div class="wd-kosten">
    ${wdKostenBox('Frischwasser', 'wasser', k.wasser)}
    ${wdKostenBox('Schmutzwasser', 'schmutz', k.schmutz)}
    ${wdKostenBox('Niederschlag', 'niederschlag', k.niederschlag)}
    ${kbox('Gesamt', eur(k.gesamt), ' gesamt')}
    ${kbox('Preis / m³', `${(k.preis_m3 ?? 0).toLocaleString('de-DE',
      { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`, ' preis')}
  </div>`;

  const warn = (d.warnungen || []).map(t =>
    `<div class="ho-warn">▲ ${esc(t)}</div>`).join('');
  const einheiten = d.einheiten || [];
  if (!einheiten.length) {
    return (d.bereit === false
      ? `<div class="wd-hinweis">${esc(d.hinweis
          || 'Für die Verrechnung fehlen noch Angaben.')}</div>` : '')
      + kosten + warn;
  }

  const zelle = z => z
    ? `<td><span class="wd-m3">${m3(z.m3)}</span>
        <span class="wd-eur">${eur(z.kosten)}</span>
        </td>`
    : '<td class="wd-leerz">–</td>';

  const arten = [];
  for (const e of einheiten) for (const z of (e.zeilen || []))
    if (!arten.includes(z.art)) arten.push(z.art);

  const zusammen = (e, art) => {
    const treffer = (e.zeilen || []).filter(z => z.art === art);
    if (!treffer.length) return null;
    if (treffer.length === 1) return treffer[0];
    return {
      art,
      m3: treffer.reduce((s, z) => s + (z.m3 || 0), 0),
      kosten: treffer.reduce((s, z) => s + (z.kosten || 0), 0),
      quelle: treffer.every(z => z.quelle === 'gemessen') ? 'gemessen'
        : (treffer.find(z => z.quelle) ? 'berechnet' : ''),
    };
  };

  const zeileMit = (kopfZelle, klasse, zellen) =>
    `<tr${klasse ? ` class="${klasse}"` : ''}>
      <td class="wd-rowh">${kopfZelle}</td>${zellen.join('')}</tr>`;

  const kopf = `<tr><th class="wd-rowh">Verbrauch</th>${
    einheiten.map(e => `<th>${esc(e.name)}</th>`).join('')}</tr>`;

  const herkunft = a => /waschmaschine|kaltwasser|warmwasser/i.test(a)
    ? 'nach Zähler' : /haupthaus|anteil/i.test(a) ? 'errechnet' : '';
  const artZeilen = arten.map(art => zeileMit(
    `${esc(art)}${herkunft(art) ? `<small>${herkunft(art)}</small>` : ''}`, '',
    einheiten.map(e => zelle(zusammen(e, art))))).join('');

  const g = d.garten;
  const gartenZeile = g ? zeileMit('Gartenwasser <small>manuell · Eigentümer</small>',
    'wd-garten', einheiten.map(e => e.name === g.einheit
      ? `<td><span class="wd-m3">${m3(g.m3)}</span>
          <span class="wd-eur">${eur(g.kosten)}</span></td>`
      : '<td class="wd-leerz">–</td>')) : '';

  const summeZeile = zeileMit('Summe', 'wd-summe',
    einheiten.map(e => `<td><span class="wd-m3">${eur(e.summe)}</span></td>`));

  const tabelle = `<div class="wd-tabelle"><table class="wd-tab">
      <thead>${kopf}</thead>
      <tbody>${artZeilen}${gartenZeile}${summeZeile}</tbody>
    </table></div>`;

  const stimmt = Math.abs((d.kontrolle ?? 0) - (k.gesamt ?? 0)) < 0.02;
  const fuss = `<div class="wd-fuss">
      <span>Gesamtverbrauch <b>${m3(d.gesamt_m3)}</b></span>
      ${d.rest_m3 != null ? `<span>Rest Haupthaus <b>${m3(d.rest_m3)}</b> ·
        ${eur(d.rest_kosten)}</span>` : ''}
      <span class="wd-kontroll${stimmt ? '' : ' neg'}">Kontrolle ${
        eur(d.kontrolle ?? k.gesamt)}${stimmt ? '' : ` ≠ ${eur(k.gesamt)}`}</span>
    </div>`;

  return (d.bereit === false
    ? `<div class="wd-hinweis">${esc(d.hinweis
        || 'Für die Verrechnung fehlen noch Angaben.')}</div>` : '')
    + kosten + warn + tabelle + fuss;
}

/* N78 — der wasser-spezifische Drop-Dialog: drei Betragsfelder. Wird von
   belege.js aufgerufen; `erkennen` und `lesbareGroesse` werden dort
   herausgereicht (kein Import über Kreuz zu belege.js). */
export function belegWasserDialog({ kostenart, vorschlag, dup, jahr, groesse, datei,
                                    anbieter, erkennen, lesbareGroesse }) {
  return new Promise(fertig => {
    const dlg = document.createElement('dialog');
    dlg.className = 'immo-dlg beleg-drop-dlg';
    document.body.appendChild(dlg);
    let entschieden = false;
    const blobUrl = datei ? URL.createObjectURL(datei) : '';
    dlg.addEventListener('close', () => {
      if (blobUrl) URL.revokeObjectURL(blobUrl);
      dlg.remove();
      if (!entschieden) fertig(null);
    }, { once: true });
    const kiZeile = v => {
      const t = [];
      if (v?.sache) t.push(esc(v.sache));
      if (v?.absender) t.push(esc(v.absender));
      if (v?.datum) t.push(new Date(v.datum).toLocaleDateString('de-DE'));
      const w = v?.wasser;
      if (w && (w.wasser || w.schmutz || w.niederschlag)) {
        const s = w.wasser + (w.schmutz || 0) + (w.niederschlag || 0);
        t.push(eur(s) + ' gesamt');
      } else if (v?.betrag) {
        t.push(eur(Math.abs(v.betrag)));
      }
      return t.length ? `erkannt: ${t.join(' · ')}` : 'keine automatische Erkennung';
    };
    const dupHtml = dup?.gefunden ? `<div class="dup-hinweis">
        <strong>Diese Datei liegt schon in der Ablage.</strong>
        ${dup.im_ziel_ordner ? 'Im richtigen Ordner ✓' : 'Aber in einem anderen Ordner.'}
        ${dup.pfad ? `<span class="pfad">${esc(dup.pfad)}</span>` : ''}
        Statt sie erneut hochzuladen, wird der vorhandene Beleg verknüpft.</div>` : '';
    const istPdf = (datei?.type || '') === 'application/pdf' || /\.pdf$/i.test(datei?.name || '');
    const vorschau = !blobUrl ? '<div class="bdd-leer">Keine Vorschau</div>'
      : istPdf ? `<embed class="bdd-embed" src="${blobUrl}#toolbar=0&navpanes=0&view=Fit" type="application/pdf">`
      : `<img class="bdd-img" src="${blobUrl}" alt="Beleg-Vorschau">`;
    const eyebrow = [state.daten.objekt_name, 'Nebenkosten'].filter(Boolean).map(esc).join(' · ');
    const wv = v => (v != null && v !== '') ? Math.abs(v) : '';
    const w0 = vorschlag?.wasser || {};
    dlg.innerHTML = `
      <button class="immo-dlg-zu" data-nein aria-label="Schließen">×</button>
      ${eyebrow ? `<span class="bdd-eyebrow">${eyebrow}</span>` : ''}
      <div class="dt">Wasser-Beleg zuordnen</div>
      <div class="bdd-body">
        <div class="bdd-links">
          <p class="zinfo">→ <strong>${esc(kostenart)}</strong> · ${lesbareGroesse(groesse)}
            <br><span class="bdd-ki" data-ki-zeile>${kiZeile(vorschlag)}</span></p>
          <button class="bdd-kibtn" data-ki-neu type="button"
            title="Beleg noch einmal von der KI lesen lassen">
            <span class="funke">✦</span><span class="lbl">KI neu lesen</span></button>
          <div class="bdd-zus" data-zus${vorschlag?.zusammenfassung ? '' : ' hidden'}
            >${esc(vorschlag?.zusammenfassung || '')}</div>
          ${dupHtml}
          <p class="bdd-wasser-hint">Die drei Bereichs-Gebühren des Bescheids —
            von der KI vorausgelesen, bitte prüfen. Sie werden auf die Positionen
            Wasser, Abwasser und Niederschlagswasser gebucht.</p>
          <div class="field"><label>Bezeichnung</label>
            <input class="inp" data-f="beschreibung" value="${esc(vorschlag?.sache || kostenart)}"></div>
          <div class="field"><label>Firma / Gemeinde / Zweckverband</label>
            <input class="inp" data-f="firma" value="${esc(vorschlag?.absender || anbieter || '')}"
              placeholder="z. B. Zweckverband, Versicherer …"></div>
          <div class="field drei">
            <div><label>Frischwasser (€)</label>
              <input class="inp" type="number" step="0.01" data-f="w_wasser"
                value="${wv(w0.wasser)}" placeholder="0,00"></div>
            <div><label>Schmutzwasser (€)</label>
              <input class="inp" type="number" step="0.01" data-f="w_schmutz"
                value="${wv(w0.schmutz)}" placeholder="0,00"></div>
            <div><label>Niederschlag (€)</label>
              <input class="inp" type="number" step="0.01" data-f="w_niederschlag"
                value="${wv(w0.niederschlag)}" placeholder="0,00"></div>
          </div>
          <div class="field"><label>Jahr</label>
            <input class="inp" type="number" data-f="jahr" value="${jahr}"></div>
          <div class="bdd-err" data-err hidden></div>
          <div class="bdd-fuss">
            <button class="btn" data-ok>${dup?.gefunden ? 'Verknüpfen' : 'Ablegen'}</button>
          </div>
        </div>
        <div class="bdd-rechts">${vorschau}</div>
      </div>`;
    const kibtn = dlg.querySelector('[data-ki-neu]');
    async function neuErkennen() {
      if (!datei || kibtn.classList.contains('laedt')) return;
      kibtn.classList.add('laedt'); kibtn.disabled = true;
      kibtn.querySelector('.lbl').textContent = 'KI liest …';
      try {
        const v = await erkennen(datei, kostenart);
        if (!v) throw new Error('keine Antwort');
        const setF = (s, val) => {
          const el = dlg.querySelector(`[data-f="${s}"]`);
          if (el && val != null && val !== '') el.value = val;
        };
        if (v.sache) setF('beschreibung', v.sache);
        if (v.absender) setF('firma', v.absender);
        if (v.jahr) setF('jahr', v.jahr);
        const w = v.wasser || {};
        if (w.wasser != null) setF('w_wasser', Math.abs(w.wasser));
        if (w.schmutz != null) setF('w_schmutz', Math.abs(w.schmutz));
        if (w.niederschlag != null) setF('w_niederschlag', Math.abs(w.niederschlag));
        dlg.querySelector('[data-ki-zeile]').textContent = kiZeile(v);
        const zus = dlg.querySelector('[data-zus]');
        if (v.zusammenfassung) { zus.textContent = v.zusammenfassung; zus.hidden = false; }
        if (!v.ki) {
          melde('KI nicht aktiv (kein Schlüssel/Guthaben) — es gilt die einfache '
            + 'Erkennung. In den Einstellungen den Anthropic-Schlüssel hinterlegen.', 'neg');
        } else if (!w.wasser && !w.schmutz && !w.niederschlag) {
          melde('✦ KI gelesen — aber keine Wasser-Bereiche erkannt; bitte von Hand '
            + 'eintragen.', 'neg');
        } else {
          melde('✦ KI-Erkennung aktualisiert', 'pos');
        }
      } catch (fehler) {
        melde('KI-Erkennung nicht möglich: ' + String(fehler.message || fehler), 'neg');
      } finally {
        kibtn.classList.remove('laedt'); kibtn.disabled = false;
        kibtn.querySelector('.lbl').textContent = 'KI neu lesen';
      }
    }
    kibtn.onclick = neuErkennen;
    dlg.querySelector('[data-nein]').onclick = () => dlg.close();
    dlg.querySelector('[data-ok]').onclick = () => {
      const f = s => dlg.querySelector(`[data-f="${s}"]`).value;
      const zn = s => parseFloat(String(f(s)).replace(',', '.')) || 0;
      const wasser = zn('w_wasser'), schmutz = zn('w_schmutz'),
            niederschlag = zn('w_niederschlag');
      if (!(wasser > 0 || schmutz > 0 || niederschlag > 0)) {
        const err = dlg.querySelector('[data-err]');
        err.textContent = 'Bitte mindestens einen Bereichsbetrag eintragen — '
          + 'sonst bleibt die Zeile leer.';
        err.hidden = false;
        const bf = dlg.querySelector('[data-f="w_wasser"]');
        bf.focus(); bf.select?.();
        return;
      }
      entschieden = true;
      fertig({
        aktion: dup?.gefunden ? 'verknuepfen' : 'ablegen',
        beschreibung: f('beschreibung').trim(),
        firma: f('firma').trim(),
        jahr: Number(f('jahr')) || jahr,
        betrag: wasser,
        wasser: { wasser, schmutz, niederschlag },
      });
      dlg.close();
    };
    dlg.showModal();
  });
}
