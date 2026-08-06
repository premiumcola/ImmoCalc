/* zeitraum/stromkette.js — die Stromkette in der aufgeklappten Strom-
   Position: kWh → Euro → E-Tankstelle → Einheiten (N142).

   Drei Schritte untereinander, jeder mit dem, was hineingeht und was
   herauskommt. Gerechnet wird im Backend (GET /zeitraeume/{zid}/stromkette);
   hier steht nur die Darstellung und die Eingabe der drei SolarEdge-Anteile. */

import { api, eur, esc, frage, melde } from '../immo.js';
import * as state from './state.js';
import { SK_BLOECKE, SK_FARBE } from './state.js';
import { zahl, belegDatumText, stromKetteVerteilt } from './helpers.js';
import { istStromPos } from './modell.js';
// Zirkulär mit checkliste.js (die importiert `fuelleStromketteInline` von
// hier) — unproblematisch, weil `deckungAktualisieren` erst innerhalb einer
// async Funktion aufgerufen wird, nie während der Modul-Auswertung selbst.
import { deckungAktualisieren } from './checkliste.js';

/* Prozent mit einer Nachkommastelle, ohne überflüssige Null. */
const skProz = n => (n ?? 0).toLocaleString('de-DE', { maximumFractionDigits: 1 });
/* Ein Preis als ct/kWh. */
const skCt = n => `${((n ?? 0) * 100).toLocaleString('de-DE',
  { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ct`;
/* Mengen in kWh — eine Nachkommastelle genügt. */
const skKwh = n => `${(n ?? 0).toLocaleString('de-DE',
  { maximumFractionDigits: 1 })} kWh`;

const skProzent = (s, k) => s[`${k === 'akku' ? 'speicher' : k}_prozent`] || 0;

export async function fuelleStromketteInline(el, frisch = false) {
  try {
    // N157 — was `laden()` schon geholt hat, wird nicht ein zweites Mal geholt.
    const d = (!frisch && state.stromketteDaten)
      || await api(`/zeitraeume/${state.zid}/stromkette`);
    state.setStromketteDaten(d);
    await stromBetragSichern();
    el.dataset.gesamtKwh = d.schritt1.gesamt_kwh || 0;
    el.innerHTML = stromketteInhalt(d);
  } catch (fehler) {
    el.innerHTML = `<div class="wd-lade">Stromkette nicht ladbar: ${
      esc(String(fehler.message || fehler))}</div>`;
  }
}

/* N222 — sobald die Kette vollständig berechnet UND verteilt ist, den
   Betrag auf die zugehörige Kostenposition schreiben. Ohne das zählt die
   tatsächliche Abrechnung ("Umgelegt") diesen Betrag nie mit: die
   Checkliste zeigte ihn grün, aber die echte Abrechnung sah ihn nie, weil
   sie nur persistierte, als "erledigt" markierte Positionen zählt (N222). */
async function stromBetragSichern() {
  if (!stromKetteVerteilt()) return;
  const pos = (state.daten?.checkliste || []).find(istStromPos);
  if (!pos) return;
  const betrag = Math.round((state.stromketteDaten.kontrolle.schritt1_betrag || 0) * 100) / 100;
  if (betrag <= 0.005) return;
  if (pos.erledigt && Math.abs((pos.betrag || 0) - betrag) < 0.005) return;
  try {
    // Ohne eigene Kostenposition (Strom entsteht rein aus der Stromkette,
    // nie aus einem Beleg) muss sie hier erst angelegt werden — derselbe Weg
    // wie bei einer Wasser-Position ohne `position_id` (`wasserPosBetragSchreiben`).
    if (pos.position_id) {
      await api(`/positionen/${pos.position_id}`, { method: 'PATCH', body: { betrag } });
    } else {
      const neu = await api(`/zeitraeume/${state.daten.id}/positionen`,
        { method: 'POST', body: { kostenart: pos.kostenart, betrag } });
      pos.position_id = neu.id;
    }
    // Lokal sofort konsistent — ohne auf den nächsten vollen `laden()` zu warten.
    pos.betrag = betrag;
    pos.erledigt = true;
    // Die „Umgelegt"-Karte hat ihren Stand schon VOR diesem Schreiben
    // geholt (Stromkette lädt erst beim Aufklappen/beim Nachrender) — ohne
    // diesen Refresh bliebe sie bis zum nächsten vollen Laden veraltet.
    await deckungAktualisieren();
  } catch { /* nächster Aufruf versucht es erneut — kein Fehlerbanner nötig */ }
}

/* N191 — die drei SolarEdge-Anteile als Balken. */
function skBalken(s, breit = false) {
  const werte = SK_BLOECKE.map(([k]) => skProzent(s, k));
  const max = Math.max(1, ...werte);
  const hoch = breit ? 44 : 62;
  const saeulen = SK_BLOECKE.map(([k, titel], i) => {
    const p = werte[i];
    const px = Math.max(8, Math.round(p / max * hoch));
    return `<div class="sk-saeule">
        <span class="sk-saeule-wert">${skProz(p)}%</span>
        <span class="sk-saeule-bar" style="height:${px}px;background:${
          SK_FARBE[k]}"></span>
        <span class="sk-saeule-name">${esc(titel.split(' ')[0])}</span>
      </div>`;
  }).join('');
  return `<div class="sk-bars${breit ? ' breit' : ''}" role="img" aria-label="Aufteilung Netz ${
      skProz(werte[0])} Prozent, PV ${skProz(werte[1])} Prozent, Speicher ${
      skProz(werte[2])} Prozent">${saeulen}
    <span class="sk-bars-pfeil" aria-hidden="true">→</span></div>`;
}

/* N191 — drei knappe Bubbles: Fakten, was daraus wird, was weitergeht. */
function skBubbles(s) {
  const anteile = SK_BLOECKE.map(([k, titel]) =>
    `${esc(titel.split(' ')[0])} ${skProz(skProzent(s, k))}%`).join(' · ');
  const herkunft = SK_BLOECKE.map(([k, titel]) => {
    const h = (s[k] || {}).herkunft || {};
    if (!h.text) return '';
    return `<li><b>${esc(titel.split(' ')[0])}</b> ${esc(h.text)}</li>`;
  }).filter(Boolean).join('');
  const menge = s.quelle_menge
    ? `<li><b>Menge</b> ${esc(s.quelle_menge)}</li>` : '';
  const fehlt = s.vollstaendig === false
    ? `<span class="sk-bubble-warn">Für die mit „fehlt“ gezeichneten Blöcke
        liegt noch kein Betrag vor — die Summe ist nur das bisher Bekannte.</span>`
    : '';
  return `<div class="sk-bubbles">
      <div class="sk-bubble"><span class="sk-bubble-k">Aus der Tabelle</span>
        <b>${zahl(s.gesamt_kwh)} kWh</b> — ${anteile}.</div>
      <div class="sk-bubble"><span class="sk-bubble-k">Daraus wird</span>
        <b>${eur(s.betrag)}</b> Stromkosten. Netz nach Rechnung, PV &amp; Akku
        10 % unter dem Netzpreis.${fehlt}
        <details class="sk-info"><summary>Woher die Zahlen &amp; Euro kommen</summary>
          <ul class="sk-herk">${menge}${herkunft}</ul></details></div>
      <div class="sk-bubble"><span class="sk-bubble-k">Weiter unten</span>
        Davon geht die E-Tankstelle vorab ab (Schritt 2); der Rest verteilt sich
        nach Zählerwerten auf die Einheiten (Schritt 3).</div>
    </div>`;
}

/* Schritt 1 — aus den drei Anteilen und der Rechnung werden Euro. */
function skSchritt1(d) {
  const s = d.schritt1;
  const bearbeitbar = state.daten.status === 'in Arbeit';
  const feld = (schluessel, label, wert) => bearbeitbar
    ? `<div class="sk-feld"><label>${label}</label>
        <input type="text" inputmode="decimal" data-sk-anteil="${schluessel}"
          value="${wert ? skProz(wert) : ''}" placeholder="%"
          aria-label="${label} in Prozent"></div>`
    : `<div class="sk-feld fest"><label>${label}</label>
        <span>${wert ? `${skProz(wert)} %` : '—'}</span></div>`;
  const zeilen = SK_BLOECKE.map(([k, titel, sub]) => {
    const b = s[k] || {};
    const kosten = b.betrag == null
      ? `<span class="wd-m3 sk-offen">—</span>
         <span class="wd-eur sk-offen">fehlt</span>`
      : `<span class="wd-m3">${eur(b.betrag)}</span>
         <span class="wd-eur">${b.preis == null ? '—' : `${skCt(b.preis)}/kWh`}</span>`;
    return `<tr>
      <td class="wd-rowh sk-rh-${k}">${titel}<small>${sub}</small></td>
      <td><span class="wd-m3">${skKwh(b.kwh)}</span></td>
      <td>${kosten}</td></tr>`;
  }).join('');
  const chip = (s.netz_preis != null && s.netz_preis_geeicht != null
    && Math.abs(s.netz_preis - s.netz_preis_geeicht) < 1e-6)
    ? `<span class="sk-satzchip" title="Durchschnittspreis Netzbezug inkl. Grundgebühr">Netz ${skCt(s.netz_preis)}/kWh</span>` : '';
  const anteileKomplett = Math.abs((s.erfasst_summe ?? 0) - 100) < 1.5;
  const tabelle = `<div class="wd-scroll sk-splittab"><table class="wd-tab sk-tab"><thead><tr>
          <th class="wd-rowh">Quelle</th><th>Menge</th><th>Kosten</th>
        </tr></thead><tbody>${zeilen}</tbody>
        <tfoot><tr class="wd-summe"><td class="wd-rowh">Summe</td>
          <td><span class="wd-m3">${skKwh(s.gesamt_kwh)}</span></td>
          <td><span class="wd-m3">${eur(s.betrag)}</span></td>
        </tr></tfoot>
        </table></div>`;
  const felderHtml = anteileKomplett ? ''
    : `<div class="sk-felder">${feld('netz', 'Netz', s.netz_erfasst)}${
        feld('pv', 'PV direkt', s.pv_erfasst)}${
        feld('akku', 'Speicher', s.speicher_erfasst)}</div>`;
  const splitHtml = anteileKomplett
    ? `${skBalken(s, true)}${tabelle}`
    : `<div class="sk-split">${skBalken(s)}${tabelle}</div>`;
  return `<div class="sk-schritt">
      <div class="sk-kopf"><span class="sk-nr">1</span><span class="sk-t">Gesamtverbrauch
        im Zeitraum</span><span class="sk-h">${esc(d.zeitraum?.label || '')}</span>${chip}</div>
      ${felderHtml}
      ${splitHtml}
      ${skNetzsaetze(s)}
      ${skBubbles(s)}
      ${skNetzBelege(s)}
      ${skGeeichteMenge(s, bearbeitbar)}</div>`;
}

/* N173 — Verteilungssatz + geeichter Satz. */
function skNetzsaetze(s) {
  const vert = s.netz_preis, geeicht = s.netz_preis_geeicht;
  if (vert == null || geeicht == null) return '';
  if (Math.abs(vert - geeicht) < 1e-6) return '';
  const menge = s.geeichte_menge
    ? ` (${zahl(s.geeichte_menge)} kWh laut Rechnung)` : '';
  return `<div class="sk-saetze">
      <span class="sk-satz"><b>${skCt(vert)}/kWh</b>
        <small>Mieter · Verteilung (SolarEdge-Menge)</small></span>
      <span class="sk-satz"><b>${skCt(geeicht)}/kWh</b>
        <small>E-Auto · geeicht${menge}</small></span>
      <span class="sk-satz-hinweis">Zwei Sätze, ein Netzbetrag: die Mieter tragen
        ihn auf die SolarEdge-gemessene Menge, das E-Auto auf die geeichte
        Rechnungsmenge. Die Differenz wird mit dem Versorger geklärt.</span>
    </div>`;
}

/* N192 — die Belege hinter dem Netzbetrag: ansehen und ggf. herausnehmen. */
function skNetzBelege(s) {
  const belege = s.netz_belege || [];
  if (!belege.length) return '';
  const bearbeitbar = state.daten.status === 'in Arbeit';
  const zeilen = belege.map(b => {
    const datum = belegDatumText(b.belegdatum);
    const weg = bearbeitbar
      ? `<button class="beleg-weg" data-strom-beleg-weg="${b.id}"
          data-strom-beleg-name="${esc(b.dateiname)}"
          title="Beleg herausnehmen (Datei bleibt in der Cloud)"
          aria-label="Beleg „${esc(b.dateiname)}“ herausnehmen">×</button>` : '';
    return `<span class="beleg-zeile"><a href="#" data-beleg="${b.id}"
        data-name="${esc(b.dateiname)}" title="${esc(b.pfad)}">PDF · ${
        esc(b.dateiname)}${b.betrag ? ` · ${eur(b.betrag)}` : ''}${
        datum ? `<span class="beleg-datum">${datum}</span>` : ''}</a>${weg}</span>`;
  }).join('');
  const mehr = belege.length > 1
    ? ` Trägt einer davon nur Abschläge oder ist doppelt, nimm ihn heraus —
        der Netzbetrag rechnet sich dann neu.` : '';
  return `<div class="sk-belege"><span class="sk-belege-k">Netz-Beleg${
      belege.length === 1 ? '' : `e (${belege.length})`}</span>
      <span class="sk-belege-txt">Der Netzbetrag stammt aus ${
        belege.length === 1 ? 'diesem Beleg' : 'diesen Belegen'}.${mehr}</span>
      <div class="belege">${zeilen}</div></div>`;
}

/* N192 — geeichte Rechnungsmenge: erklären und eintragbar machen. */
function skGeeichteMenge(s, bearbeitbar) {
  if (s.netz_preis == null || s.geeichte_menge > 0) return '';
  const eingabe = bearbeitbar
    ? `<div class="sk-geeicht-eingabe">
        <input type="text" inputmode="decimal" data-geeichte-menge
          placeholder="kWh laut Rechnung" aria-label="Geeichte Rechnungsmenge in kWh">
        <button type="button" data-geeichte-menge-speichern>Eintragen</button>
      </div>` : '';
  return `<details class="sk-geeicht">
      <summary><span class="sk-geeicht-i">i</span>Geeichte Rechnungsmenge fehlt
        — E-Auto rechnet ersatzweise auf die SolarEdge-Menge</summary>
      <p>Der Netzbezug wird auf der Versorgerrechnung nach dem <b>geeichten
        Zähler</b> abgerechnet; SolarEdge misst am Wechselrichter und weicht davon
        ab. Für den E-Auto-Satz zählt die geeichte Menge. Trag sie ein, dann
        rechnet das E-Auto genau auf die abgerechneten kWh und dieser Hinweis
        verschwindet.</p>${eingabe}</details>`;
}

/* Schritt 2 — die Ladungen der Periode gehen vorab ab. */
function skSchritt2(d) {
  const s = d.schritt2;
  if (!s.eauto_kwh) {
    return `<div class="sk-schritt">
      <div class="sk-kopf"><span class="sk-nr">2</span><span class="sk-t">Abzug
        E-Tankstelle</span></div>
      <div class="zu-kein">Im Zeitraum wurde nichts geladen — es geht nichts ab.${
        s.quelle_text ? ` ${esc(s.quelle_text.replace(/\.$/, ''))}.` : ''}</div>
    </div>`;
  }
  const zeilen = SK_BLOECKE.map(([k, titel, sub]) => `<tr>
      <td class="wd-rowh">${titel}<small>${sub}</small></td>
      <td><span class="wd-m3">${skKwh(s[`${k}_kwh`])}</span></td></tr>`).join('');
  const gegen = s.zaehler
    ? ` Der Zähler „${esc(s.zaehler)}“ weist dieselbe Menge aus (${
        skKwh(s.zaehler_kwh)}) — er braucht deshalb keine Einheit.` : '';
  return `<div class="sk-schritt">
      <div class="sk-kopf"><span class="sk-nr">2</span><span class="sk-t">Abzug
        ${esc(s.einheit)}</span><span class="sk-h">${esc(s.quelle_text)}</span></div>
      <div class="wd-scroll"><table class="wd-tab sk-tab"><thead><tr>
        <th class="wd-rowh">Quelle</th><th>Geladen</th>
      </tr></thead><tbody>${zeilen}</tbody>
      <tfoot><tr class="wd-summe"><td class="wd-rowh">Summe</td>
        <td><span class="wd-m3">${skKwh(s.eauto_kwh)}</span>
          <span class="wd-eur">${eur(s.betrag)}</span></td></tr></tfoot>
      </table></div>
      <span class="sk-quelle">Diese Menge geht <b>vorab</b> ab und wird
        <b>nicht</b> auf die Bewohner der Einheiten verteilt — das Auto lädt für
        sich. Wer geladen hat, spielt hier keine Rolle; das steht im Bereich
        E-Tankstelle.${gegen}</span></div>`;
}

/* Schritt 3 — der Rest nach den Zählerwerten. */
function skSchritt3(d) {
  const s = d.schritt3;
  const namen = Object.keys(s.je_einheit);
  if (!namen.length) {
    return `<div class="sk-schritt">
      <div class="sk-kopf"><span class="sk-nr">3</span><span class="sk-t">Verteilung
        auf die Einheiten</span></div>
      <div class="zu-kein">Noch keine Einheit mit Zählerwert — die Zuordnung
        bitte an den Stromzählern nachtragen.</div></div>`;
  }
  const zeile = (titel, sub, zellen) => `<tr>
    <td class="wd-rowh">${titel}${sub ? `<small>${sub}</small>` : ''}</td>${zellen}</tr>`;
  const menge = k => namen.map(n =>
    `<td><span class="wd-m3">${skKwh(s.je_einheit[n][k])}</span></td>`).join('');
  const rest = `<div class="sk-rest">
      <span class="sk-rest-label">was übrig ist</span>
      <span class="sk-rest-zahl"><b>${zahl(s.rest_kwh)}</b> kWh<small>nach Abzug
        der E-Tankstelle — diese verteilen sich nach Zählerwerten</small></span>
    </div>`;
  return `<div class="sk-schritt">
      <div class="sk-kopf"><span class="sk-nr">3</span><span class="sk-t">Verteilung
        auf die Einheiten</span><span class="sk-h">nach Zählerwerten</span></div>
      ${rest}
      <div class="wd-scroll"><table class="wd-tab sk-tab"><thead><tr>
        <th class="wd-rowh">Verbrauch</th>${namen.map(n =>
          `<th>${esc(n)}</th>`).join('')}</tr></thead>
      <tbody>
        ${zeile('Menge', 'nach Zähler', menge('kwh'))}
        ${zeile('davon Netz', '', menge('netz_kwh'))}
        ${zeile('davon PV', '', menge('pv_kwh'))}
        ${zeile('davon Akku', '', menge('akku_kwh'))}
        <tr class="wd-summe"><td class="wd-rowh">Kosten</td>${namen.map(n =>
          `<td><span class="wd-m3">${eur(s.je_einheit[n].betrag)}</span></td>`).join('')}</tr>
      </tbody></table></div>
      ${(s.ohne_einheit || []).length ? `<span class="sk-quelle">Noch keiner
        Einheit zugeordnet: ${s.ohne_einheit.map(o =>
          `<b>${esc(o.zaehler)}</b> ${skKwh(o.kwh)}`).join(' · ')}</span>` : ''}</div>`;
}

function stromketteInhalt(d) {
  const k = d.kontrolle || {};
  const erledigt = t => t.includes('angehängten Beleg')
    || t.includes('geeichte Rechnungsmenge');
  const warn = (d.warnungen || []).filter(t => !erledigt(t)).map(t =>
    `<div class="ho-warn">▲ ${esc(t)}</div>`).join('');
  return `<div class="sk-box">${skSchritt1(d)}${skSchritt2(d)}${skSchritt3(d)}
    <div class="sk-kontrolle">
      <span>Verteilt <b>${eur(k.verteilt)}</b> von <b>${eur(k.schritt1_betrag)}</b></span>
      <span class="${k.stimmt ? 'ok' : 'fehl'}">${k.stimmt
        ? '✓ Kontrollsumme stimmt'
        : `▲ Abweichung ${eur(k.differenz)}`}</span>
    </div>${warn}</div>`;
}

/* Einen der drei SolarEdge-Anteile speichern. */
export async function stromAnteilSpeichern(feld) {
  const wert = parseFloat(String(feld.value || '').replace(',', '.'));
  const box = feld.closest('[data-strom-kette]');
  if (!box || Number.isNaN(wert) || wert < 0) return;
  const gesamt = Number(box.dataset.gesamtKwh) || 0;
  if (!gesamt) {
    return melde('Ohne Gesamtverbrauch lässt sich der Anteil nicht umrechnen — '
      + 'bitte zuerst den Stromzähler ablesen.', 'neg');
  }
  const SPALTE = { netz: 'netz_kwh', pv: 'solar_kwh', akku: 'akku_kwh' };
  const mengen = {};
  box.querySelectorAll('[data-sk-anteil]').forEach(f => {
    const p = parseFloat(String(f.value || '').replace(',', '.'));
    mengen[SPALTE[f.dataset.skAnteil]] = Number.isNaN(p) || p < 0 ? 0
      : Math.round(gesamt * p / 100 * 1000) / 1000;
  });
  const pfad = `/objekte/${encodeURIComponent(state.daten.objekt)}/strom/${state.daten.jahr}`;
  try {
    const jetzt = await api(pfad);
    delete jetzt.jahr;
    await api(pfad, { method: 'PUT', body: { ...jetzt, ...mengen } });
    await fuelleStromketteInline(box, true);
  } catch (fehler) { melde(String(fehler.message || fehler), 'neg'); }
}

/* N192 — einen Netz-Beleg der Stromkette herausnehmen. */
export async function stromBelegLoesen(id, name) {
  const ok = await frage(`Beleg „${name || 'Beleg'}“ aus dem Netzbetrag `
    + 'herausnehmen? Die Datei bleibt in der Cloud — nur die Zuordnung zu diesem '
    + 'Zeitraum wird gelöst.');
  if (!ok) return;
  try {
    await api(`/dokumente/${id}/position`, { method: 'DELETE' }).catch(() => {});
    await api(`/dokumente/${id}`, { method: 'PATCH', body: { zeitraum_id: null } });
    melde('Beleg herausgenommen — die Datei bleibt in der Cloud', 'pos');
    const { laden } = await import('./checkliste.js');
    await laden();
  } catch (fehler) { melde(String(fehler.message || fehler), 'neg'); }
}

/* N192 — die geeichte Rechnungsmenge speichern. */
export async function geeichteMengeSpeichern(btn) {
  const input = btn.closest('.sk-geeicht-eingabe')?.querySelector('[data-geeichte-menge]');
  const wert = parseFloat(String(input?.value || '').replace(/\./g, '').replace(',', '.'));
  if (Number.isNaN(wert) || wert <= 0) {
    return melde('Bitte eine Menge in kWh eintragen', 'neg');
  }
  try {
    await api(`/zeitraeume/${state.zid}/strom/rechnungsmenge`, { method: 'PUT',
      body: { rechnung_kwh: wert } });
    melde('Geeichte Rechnungsmenge gespeichert', 'pos');
    const { laden } = await import('./checkliste.js');
    await laden();
  } catch (fehler) { melde(String(fehler.message || fehler), 'neg'); }
}
