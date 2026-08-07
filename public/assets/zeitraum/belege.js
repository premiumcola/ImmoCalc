/* zeitraum/belege.js — Belege: Anhänger, Drop-Dialog, Ablage, Erkennung,
   Vorschlag übernehmen, Beleg lösen.

   Der Beleg-Weg zur NK-Zeile: ziehen/tippen → KI liest → Nutzer bestätigt →
   Datei in Nextcloud → Position bekommt ihre `position_id`. Der Wasser-
   Spezialfall ruft `belegWasserDialog` in wasser.js auf. */

import { api, eur, esc, frage, melde, belegAnsehen } from '../immo.js';
import { scanZuPdf, lesbareGroesse } from '../scan.js';
import { fotoAlsJpeg } from '../kamerascan.js';
import * as state from './state.js';
import { KEINE_KAMERA } from './state.js';
import {
  UPLOAD_ICON, FOTO_ICON, WOLKE_ICON, ANH_ICON,
} from './icons.js';
import { istWasserSammel, istWasserKostenart } from './modell.js';
import { sha1Hex, kurzBeleg } from './helpers.js';
import { belegWasserDialog, wasserPosBetragSchreiben } from './wasser.js';

/* Der Ablage-Bereich einer offenen Zeile (Drop-Fläche + Knöpfe). */
export function belegAblageHtml(k, bearbeitbar) {
  if (!bearbeitbar) return '';
  const art = esc(k.kostenart);
  const knoepfe = KEINE_KAMERA
    ? `<button type="button" class="ablg-knopf" data-scan="${art}"
        >${UPLOAD_ICON}<span>Datei wählen</span></button>`
    : `<button type="button" class="ablg-knopf" data-scan="${art}"
        >${FOTO_ICON}<span>Foto</span></button>
       <button type="button" class="ablg-knopf" data-ablage="${art}"
        >${WOLKE_ICON}<span>Aus der Ablage</span></button>`;
  return `<div class="ablg">
      <span class="ablg-ikon">${UPLOAD_ICON}</span>
      <span class="ablg-t">${KEINE_KAMERA
        ? 'Beleg hier ablegen' : 'Beleg erfassen'}</span>
      <span class="ablg-s">${KEINE_KAMERA
        ? 'Die PDF einfach auf diese Karte ziehen — daraus entstehen Betrag und Position.'
        : 'Aus dem Beleg entstehen Betrag und Position.'}</span>
      <span class="ablg-k">${knoepfe}</span>
    </div>`;
}

/* N96b — was mit dem Beleg geschehen soll: nur aus der Abrechnung nehmen
   oder auch aus der Ablage löschen. */
export function belegWegDialog(dok) {
  return new Promise(fertig => {
    const dlg = document.createElement('dialog');
    dlg.className = 'immo-dlg';
    document.body.appendChild(dlg);
    let wahl = null;
    dlg.addEventListener('close', () => { dlg.remove(); fertig(wahl); }, { once: true });
    dlg.innerHTML = `
      <button class="immo-dlg-zu" data-nein aria-label="Schließen">×</button>
      <div class="dt">Beleg herausnehmen</div>
      <p style="font:400 13px var(--body);color:var(--soft);line-height:1.5">
        <b style="color:var(--ink)">${esc(dok?.dateiname || 'Beleg')}</b><br>
        Er wird aus dieser Abrechnung genommen; sein Betrag zählt nicht mehr mit.</p>
      <div class="kartenfuss" style="display:flex;flex-direction:column;gap:9px">
        <button class="hauptaktion" data-wahl="raus">Nur herausnehmen — Datei bleibt</button>
        <button class="minilink gefahr" data-wahl="ablage">Doppelt: auch aus der Ablage löschen</button>
      </div>`;
    dlg.querySelectorAll('[data-wahl]').forEach(b => (b.onclick = () => {
      wahl = b.dataset.wahl; dlg.close();
    }));
    dlg.querySelector('[data-nein]').onclick = () => dlg.close();
    dlg.showModal();
  });
}

/* N95 — einen Beleg aus seiner Kostenposition herausnehmen. */
export async function belegLoesen(id) {
  const dok = (state.daten.dokumente || []).find(d => String(d.id) === String(id));
  const wahl = await belegWegDialog(dok);
  if (!wahl) return;
  try {
    await api(`/dokumente/${id}/position`, { method: 'DELETE' }).catch(() => {});
    await api(`/dokumente/${id}`, { method: 'PATCH', body: { zeitraum_id: null } });
    if (wahl === 'ablage') {
      // N97 — Gegenstück suchen.
      const gleich = d => String(d.id) !== String(id)
        && (d.betrag ?? null) === (dok?.betrag ?? null)
        && (d.kostenart || '') === (dok?.kostenart || '');
      const zwilling = (state.daten.dokumente || []).find(d => gleich(d) && d.groesse === dok?.groesse)
        || (state.daten.dokumente || []).find(gleich);
      if (!zwilling) {
        melde('Herausgenommen. Kein zweiter Beleg mit gleichem Betrag und '
          + 'gleicher Kostenart gefunden — die Datei bleibt in der Ablage.', 'neg');
      } else {
        const a = await api(`/dokumente/${id}/duplikat-entfernen`,
          { method: 'POST', body: { behalten_id: zwilling.id, bestaetigt: true } });
        melde(a?.verschoben
          ? 'Doppel bestätigt — Datei nach „99_Duplikate" verschoben'
          : 'Doppelter Beleg entfernt — auch aus der Ablage', 'pos');
      }
    } else {
      melde('Beleg herausgenommen — die Datei bleibt in der Ablage', 'pos');
    }
    // N185 — Wasser-Beleg: bei letztem Beleg räumt das Backend die drei Bestandteile ab.
    if (dok && istWasserKostenart(dok.kostenart)) {
      const r = await api(`/zeitraeume/${state.zid}/wasser/leeren`, { method: 'POST' })
        .catch(() => null);
      if (r?.geleert) {
        melde('Wasser-Position geleert — die Zähler bleiben. Neuen Beleg '
          + 'fotografieren, dann liest die Erkennung sie wieder ein.', 'pos');
      }
    }
    const { laden } = await import('./checkliste.js');
    await laden();
  } catch (fehler) { melde(String(fehler.message || fehler), 'neg'); }
}

/* CCLV — den kostenfreien Beleg aus dem Bestand wählen. */
function anhaengerWaehlen(kostenart) {
  const kandidaten = state.anhaenger?.kandidaten || [];
  const liste = kandidaten.length
    ? kandidaten.map(d => `
        <button class="ahz" data-pick="${d.id}">
          ${ANH_ICON}
          <span class="ahn">${esc(kurzBeleg(d.dateiname))}
            <span class="ahsub">${esc(d.kategorie || 'Ohne Art')}${
              d.jahr ? ` · ${d.jahr}` : ''}</span></span>
        </button>`).join('')
    : `<div class="ahleer">Kein kostenfreier Beleg im Bestand dieser Immobilie.
       Ein Beleg wird kostenfrei, wenn er im Eingang ohne Kostenposition bleibt —
       etwa ein Zählerstand oder ein SEPA-Mandat.</div>`;

  return new Promise(fertig => {
    const dlg = document.createElement('dialog');
    dlg.className = 'immo-dlg ahdlg';
    dlg.innerHTML = `
      <div class="dt">Beleg an „${esc(kostenart)}“ hängen</div>
      <p>Ein Zusatzbeleg ohne Kostenanteil — er erscheint als kleiner Anhänger
        am Thema, ohne Betrag.</p>
      <div class="ahliste">${liste}</div>
      <button class="btn leise" data-nein>Abbrechen</button>`;
    document.body.appendChild(dlg);
    dlg.addEventListener('close', () => dlg.remove());
    dlg.addEventListener('cancel', () => fertig(null));
    dlg.addEventListener('click', e => {
      const pick = e.target.closest('[data-pick]');
      if (pick) { fertig(Number(pick.dataset.pick)); dlg.close(); }
      else if (e.target.closest('[data-nein]')) { fertig(null); dlg.close(); }
    });
    dlg.showModal();
  });
}

export async function anhaengen(kostenart) {
  const id = await anhaengerWaehlen(kostenart);
  if (!id) return;
  try {
    await api(`/dokumente/${id}/anhaenger`,
      { method: 'POST', body: { zeitraum_id: Number(state.zid), kostenart } });
    melde(`Anhänger an „${kostenart}“ gesetzt`, 'pos');
    const { laden } = await import('./checkliste.js');
    await laden();
  } catch (fehler) {
    melde(String(fehler.message || fehler), 'neg');
  }
}

/* N237 — einen Zusatzbeleg wieder vom Thema lösen (Datei bleibt in der Ablage). */
export async function anhaengerEntfernen(id) {
  try {
    await api(`/dokumente/${id}/anhaenger`, { method: 'DELETE' });
    melde('Anhänger gelöst — die Datei bleibt in der Ablage', 'pos');
    const { laden } = await import('./checkliste.js');
    await laden();
  } catch (fehler) {
    melde(String(fehler.message || fehler), 'neg');
  }
}

/* Ein erkannter Beleg-Vorschlag: was ist das, welcher Betrag. */
function belegDropDialog({ kostenart, vorschlag, dup, jahr, groesse, datei, anbieter }) {
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
      if (v?.betrag) t.push(eur(Math.abs(v.betrag)));
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
    dlg.innerHTML = `
      <button class="immo-dlg-zu" data-nein aria-label="Schließen">×</button>
      ${eyebrow ? `<span class="bdd-eyebrow">${eyebrow}</span>` : ''}
      <div class="dt">Beleg zuordnen</div>
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
          <div class="field"><label>Bezeichnung</label>
            <input class="inp" data-f="beschreibung" value="${esc(vorschlag?.sache || kostenart)}"></div>
          <div class="field"><label>Firma / Gemeinde / Zweckverband</label>
            <input class="inp" data-f="firma" value="${esc(vorschlag?.absender || anbieter || '')}"
              placeholder="z. B. Zweckverband, Versicherer …"></div>
          <div class="field zwei">
            <div><label>Jahr</label>
              <input class="inp" type="number" data-f="jahr" value="${jahr}"></div>
            <div><label>Betrag (€)</label>
              <input class="inp" type="number" step="0.01" data-f="betrag"
                value="${vorschlag?.betrag != null ? Math.abs(vorschlag.betrag) : ''}"
                placeholder="Rechnungsbetrag"></div>
          </div>
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
        const fd = new FormData();
        fd.append('datei', datei, datei.name || 'beleg.pdf');
        const r = await fetch('/api/dokumente/erkennen', { method: 'POST', body: fd });
        if (!r.ok) throw new Error(`Fehler ${r.status}`);
        const v = await r.json();
        const setF = (s, val) => {
          const el = dlg.querySelector(`[data-f="${s}"]`);
          if (el && val != null && val !== '') el.value = val;
        };
        if (v.sache) setF('beschreibung', v.sache);
        if (v.absender) setF('firma', v.absender);
        if (v.betrag) setF('betrag', Math.abs(v.betrag));
        if (v.jahr) setF('jahr', v.jahr);
        dlg.querySelector('[data-ki-zeile]').textContent = kiZeile(v);
        const zus = dlg.querySelector('[data-zus]');
        if (v.zusammenfassung) { zus.textContent = v.zusammenfassung; zus.hidden = false; }
        if (!v.ki) {
          melde('KI nicht aktiv (kein Schlüssel/Guthaben) — es gilt die einfache '
            + 'Erkennung. In den Einstellungen den Anthropic-Schlüssel hinterlegen.', 'neg');
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
      const betrag = parseFloat(String(f('betrag')).replace(',', '.')) || 0;
      if (!(betrag > 0)) {
        const err = dlg.querySelector('[data-err]');
        err.textContent = 'Bitte den Rechnungsbetrag eintragen — ohne ihn '
          + 'bleibt die Zeile leer.';
        err.hidden = false;
        const bf = dlg.querySelector('[data-f="betrag"]');
        bf.focus(); bf.select?.();
        return;
      }
      entschieden = true;
      fertig({
        aktion: dup?.gefunden ? 'verknuepfen' : 'ablegen',
        beschreibung: f('beschreibung').trim(),
        firma: f('firma').trim(),
        jahr: Number(f('jahr')) || jahr,
        betrag,
      });
      dlg.close();
    };
    dlg.showModal();
  });
}

/* Ladeanzeige in genau der NK-Zeile. */
function zeileVerarbeitet(kostenart, text) {
  const zeile = state.inhalt.querySelector(`.pruef[data-kostenart="${CSS.escape(kostenart)}"]`);
  if (!zeile) return;
  zeile.classList.add('verarbeitet');
  const kopf = zeile.querySelector('.kopf');
  let badge = kopf.querySelector('.zeile-lade');
  if (!badge) {
    badge = document.createElement('span');
    badge.className = 'zeile-lade';
    badge.innerHTML = '<span class="kringel"></span><span class="zl-txt"></span>';
    kopf.appendChild(badge);
  }
  badge.querySelector('.zl-txt').textContent = text;
}

/** N78/N207 — Texterkennung. */
export async function erkennen(bild, kostenart = '') {
  if (!bild) return null;
  try {
    const lesbar = await fotoAlsJpeg(bild);
    const paket = new FormData();
    paket.append('datei', lesbar, lesbar.name || 'seite.jpg');
    if (kostenart) paket.append('kostenart', kostenart);
    const antwort = await fetch('/api/dokumente/erkennen',
                                { method: 'POST', body: paket });
    return antwort.ok ? await antwort.json() : null;
  } catch {
    return null;
  }
}

export function erkennungHatWert(vorschlag) {
  if (!vorschlag) return false;
  const w = vorschlag.wasser;
  if (w && (w.wasser > 0 || w.schmutz > 0 || w.niederschlag > 0)) return true;
  return vorschlag.betrag > 0;
}

async function positionBetragSchreiben(zeile, kostenart, betrag) {
  if (!(betrag > 0)) return;
  if (zeile?.position_id) {
    await api(`/positionen/${zeile.position_id}`,
      { method: 'PATCH', body: { betrag, wertquelle: 'Scan' } });
  } else {
    await api(`/zeitraeume/${state.zid}/positionen`,
      { method: 'POST', body: { kostenart, betrag, wertquelle: 'Scan' } });
  }
}

/* Bietet erkannte Werte zur Übernahme an. */
export async function betragVorschlagen(kostenart, vorschlag) {
  const zeile = state.daten.checkliste.find(k => k.kostenart === kostenart);
  if (!zeile) return false;

  const w = vorschlag?.wasser;
  if (istWasserSammel({ kostenart })
      && w && (w.wasser > 0 || w.schmutz > 0 || w.niederschlag > 0)) {
    const teile = [];
    if (w.wasser)       teile.push(`Frischwasser ${eur(w.wasser)}`);
    if (w.schmutz)      teile.push(`Schmutzwasser ${eur(w.schmutz)}`);
    if (w.niederschlag) teile.push(`Niederschlag ${eur(w.niederschlag)}`);
    const summe = (w.wasser || 0) + (w.schmutz || 0) + (w.niederschlag || 0);
    const ja = await frage('Wasser-Beträge aus dem Beleg übernehmen?',
      `Erkannt: ${teile.join(' · ')} — zusammen ${eur(summe)}. `
      + 'Auf die Positionen Wasser, Abwasser und Niederschlag eintragen?',
      { knopf: 'Übernehmen' });
    if (!ja) return false;
    await positionBetragSchreiben(zeile, kostenart, w.wasser);   // Frischwasser
    await wasserPosBetragSchreiben('schmutz', w.schmutz);
    await wasserPosBetragSchreiben('niederschlag', w.niederschlag);
    return true;
  }

  if (!vorschlag?.betrag) return false;
  const ja = await frage('Betrag aus dem Beleg übernehmen?',
    `Erkannt wurden ${eur(vorschlag.betrag)}`
    + (vorschlag.datum
      ? ` vom ${new Date(vorschlag.datum).toLocaleDateString('de-DE')}`
      : '')
    + `. Als Betrag für „${kostenart}“ eintragen?`,
    { knopf: 'Übernehmen' });
  if (!ja) return false;
  await positionBetragSchreiben(zeile, kostenart, vorschlag.betrag);
  return true;
}

/* CCCLXXXVI — eine oder mehrere Dateien einer NK-Zeile zuordnen. */
export async function belegPerDrop(kostenart, dateien) {
  const istPdf = d => d.type === 'application/pdf' || /\.pdf$/i.test(d.name || '');
  const pdfs = dateien.filter(istPdf);
  const bilder = dateien.filter(d => !istPdf(d) && (d.type || '').startsWith('image/'));
  if (!pdfs.length && !bilder.length) {
    melde('Nur PDF- oder Bilddateien lassen sich hier ablegen.', 'neg');
    return;
  }
  const jahr = Number((state.daten.ende || '').slice(0, 4)) || new Date().getFullYear();
  const erste = pdfs[0] || bilder[0];
  // N78 — Wasser-Sammelposition? Dann drei-Beträge-Dialog + Wasser-Kontext.
  const istWasser = istWasserSammel({ kostenart });

  // CD — Ladeschleier zeigen.
  const schleier = document.createElement('div');
  schleier.className = 'drop-lade';
  schleier.innerHTML = '<div class="kringel"></div><div class="txt">Beleg wird gelesen …</div>';
  document.body.appendChild(schleier);

  const zeile = (state.daten.checkliste || []).find(k => k.kostenart === kostenart);
  let wahl, dup = { gefunden: false };
  try {
    const [sha1, vorschlag] = await Promise.all([
      (pdfs.length === 1 && !bilder.length) ? sha1Hex(erste).catch(() => null) : Promise.resolve(null),
      erkennen(erste, istWasser ? kostenart : ''),
    ]);
    if (sha1) {
      try {
        dup = await api('/dokumente/duplikat-pruefen',
          { method: 'POST', body: { objekt: state.daten.objekt, sha1, name: erste.name || '', jahr } }) || dup;
      } catch { /* Endpunkt/Cloud nicht da → einfach normal ablegen */ }
    }

    const groesse = dateien.reduce((s, d) => s + (d.size || 0), 0);
    schleier.remove();
    const dialogArgs = { kostenart, vorschlag, dup, jahr, groesse,
      datei: erste, anbieter: zeile?.anbieter || '' };
    wahl = istWasser
      ? await belegWasserDialog({ ...dialogArgs, erkennen, lesbareGroesse })
      : await belegDropDialog(dialogArgs);
  } finally {
    schleier.remove();
  }
  if (!wahl) return;
  // CCCXCV — die eingetragene Firma als Anbieter der Kostenart merken.
  if (wahl.firma && wahl.firma !== (zeile?.anbieter || '') && zeile?.kostenart_id) {
    await api(`/kostenarten/${zeile.kostenart_id}`,
      { method: 'PATCH', body: { lieferant: wahl.firma } }).catch(() => {});
  }

  zeileVerarbeitet(kostenart, 'Beleg wird abgelegt …');
  const { laden } = await import('./checkliste.js');
  try {
    const dokIds = [];
    if (wahl.aktion === 'verknuepfen' && dup.pfad) {
      const res = await api('/dokumente/vorhandenen-zuordnen', { method: 'POST', body: {
        objekt: state.daten.objekt, pfad: dup.pfad, kategorie: 'Nebenkosten',
        kostenart, beschreibung: wahl.beschreibung || kostenart,
        betrag: wahl.betrag > 0 ? wahl.betrag : null, jahr: wahl.jahr, zeitraum_id: state.daten.id } });
      if (res?.id) dokIds.push(res.id);
    } else {
      const sendungen = [];
      if (bilder.length) {
        const { pdf } = await scanZuPdf(bilder);
        sendungen.push({ datei: pdf, name: 'scan.pdf' });
      }
      for (const p of pdfs) sendungen.push({ datei: p, name: p.name });
      for (let i = 0; i < sendungen.length; i++) {
        const { datei, name } = sendungen[i];
        const paket = new FormData();
        paket.append('objekt', state.daten.objekt);
        paket.append('kategorie', 'Nebenkosten');
        paket.append('kostenart', kostenart);
        paket.append('jahr', String(wahl.jahr));
        paket.append('beschreibung', wahl.beschreibung || kostenart);
        paket.append('zeitraum_id', String(state.daten.id));
        if (i === 0 && wahl.betrag > 0) paket.append('betrag', String(wahl.betrag));
        paket.append('datei', datei, name);
        const antwort = await fetch('/api/dokumente/scannen', { method: 'POST', body: paket });
        if (!antwort.ok) {
          const grund = await antwort.json().then(k => k.detail).catch(() => null);
          throw new Error(grund || `Fehler ${antwort.status}`);
        }
        const res = await antwort.json();
        if (res?.id) dokIds.push(res.id);
      }
    }
    if (!dokIds.length) throw new Error('Der Beleg wurde nicht abgelegt.');
    zeileVerarbeitet(kostenart, 'wird verbucht …');
    for (const id of dokIds) {
      await api(`/dokumente/${id}/position`, { method: 'POST' });
    }
    // N78 — Schmutz + Niederschlag auf ihre eigenen Positionen buchen.
    if (istWasser && wahl.wasser) {
      zeileVerarbeitet(kostenart, 'Bereiche werden gebucht …');
      await wasserPosBetragSchreiben('schmutz', wahl.wasser.schmutz);
      await wasserPosBetragSchreiben('niederschlag', wahl.wasser.niederschlag);
    }
    melde(`✓ Beleg „${kostenart}“ zugeordnet`, 'pos');
    await laden();
  } catch (fehler) {
    melde('Beleg nicht zugeordnet: ' + String(fehler.message || fehler), 'neg');
    await laden();
  }
}

/* Drag&Drop nur am Zeiger-Gerät (PC) — Overlay auf `.pruef`. */
export function initBelegDrop() {
  if (!KEINE_KAMERA) return;
  const istDateiZug = e => [...(e.dataTransfer?.types || [])].includes('Files');
  let dropZeile = null;
  const markiere = z => {
    if (z === dropZeile) return;
    dropZeile?.classList.remove('dropziel');
    dropZeile = z || null;
    dropZeile?.classList.add('dropziel');
  };
  state.inhalt.addEventListener('dragover', e => {
    if (!istDateiZug(e)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
    markiere(e.target.closest('.pruef[data-kostenart]'));
  });
  state.inhalt.addEventListener('dragleave', e => {
    if (e.relatedTarget && state.inhalt.contains(e.relatedTarget)) return;
    markiere(null);
  });
  state.inhalt.addEventListener('drop', e => {
    if (!istDateiZug(e)) return;
    e.preventDefault();
    const zeile = e.target.closest('.pruef[data-kostenart]');
    const dateien = [...(e.dataTransfer.files || [])];
    markiere(null);
    if (zeile && dateien.length) belegPerDrop(zeile.dataset.kostenart, dateien);
  });
  document.addEventListener('dragover', e => { if (istDateiZug(e)) e.preventDefault(); });
  document.addEventListener('drop', e => {
    if (istDateiZug(e) && !e.target.closest('.pruef[data-kostenart]')) {
      e.preventDefault();
      markiere(null);
    }
  });
}

/* Ein Beleg-Link im Dialog ansehen (via /api/dokumente/{id}/inhalt). */
export function belegLinkAnsehen(link) {
  belegAnsehen(`/api/dokumente/${link.dataset.beleg}/inhalt`,
               link.dataset.name
               || link.textContent.replace(/^PDF · /, '').trim(),
               link.getAttribute('title') || '');
}
