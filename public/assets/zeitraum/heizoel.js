/* zeitraum/heizoel.js — der Öl-Manager: Lieferungen, FIFO-Bewertung,
   §9-Split Warmwasser/Heizung, HKV-Verteilung (N79/N81/N91/N118).

   Wird beim Aufklappen der jeweiligen Position (Heizöl / Warmwasser /
   Heizkörper-Wärmemenge) inline geladen. */

import { api, eur, esc, frage, melde } from '../immo.js';
import * as state from './state.js';
import { einmal, einmalPost } from './holen.js';
import { wasserArt } from './modell.js';
import {
  zahl, _isoKurz, alleEinheiten, zaehlerEinheiten, feldZahl,
} from './helpers.js';

/* N79 — eine Öl-Lieferung erfassen. */
export async function heizoelHinzufuegen(btn) {
  const box = btn.closest('.ho-neu');
  const datum = box?.querySelector('[data-ho-datum]')?.value;
  const liter = feldZahl(box?.querySelector('[data-ho-liter]'));
  const wert = feldZahl(box?.querySelector('[data-ho-wert]'));
  const anf = !!box?.querySelector('[data-ho-anf]')?.checked;
  if (!datum || !(liter > 0)) { melde('Datum und Liter angeben', 'neg'); return; }
  try {
    await api(`/objekte/${encodeURIComponent(state.daten.objekt)}/heizoel`, {
      method: 'POST',
      body: { datum, liter, wert: Number.isFinite(wert) ? wert : 0, ist_anfangsbestand: anf },
    });
    melde('Öl-Lieferung erfasst', 'pos');
    const { zeichnen } = await import('./checkliste.js');
    await zeichnen();
  } catch (fehler) { melde(String(fehler.message || fehler), 'neg'); }
}

/* N79 — eine Öl-Lieferung wieder entfernen. N288: nicht mehr auf einen
   Fingertipp hin. Die Rückfrage nennt Datum, Liter und Wert der Lieferung —
   „Wirklich löschen?" allein sagt nicht, welche Zeile es trifft. */
export async function heizoelEntfernen(id, beschreibung = '') {
  const ok = await frage('Öl-Lieferung löschen?',
    `${beschreibung ? `${beschreibung} — ` : ''}Die Lieferung wird aus der `
    + 'Bestandsrechnung genommen; Verbrauch und Heizkosten rechnen sich neu.',
    { knopf: 'Löschen', gefahr: true });
  if (!ok) return;
  try {
    await api(`/heizoel/${id}`, { method: 'DELETE' });
    melde('Lieferung entfernt', 'pos');
    const { zeichnen } = await import('./checkliste.js');
    await zeichnen();
  } catch (fehler) { melde(String(fehler.message || fehler), 'neg'); }
}

/* N118 — Warmwassermenge je Einheit aus den Warmwasser-Unterzählern. */
function wwJeEinheit(wasserDetail) {
  const karte = {};
  for (const e of (wasserDetail?.einheiten || [])) {
    const wasserM3 = (e.zeilen || []).filter(z => z.art === 'Warmwasser')
      .reduce((su, z) => su + (z.m3 || 0), 0);
    if (wasserM3 > 0) karte[e.name] = wasserM3;
  }
  if (Object.keys(karte).length) return karte;
  for (const z of (state.ablesungMaske?.zaehler || [])) {
    // N356 — auch ein EIGENSTÄNDIGER Warmwasserzähler zählt hier mit: die
    // Bedingung „nur Unterzähler" liess die Verteilung leer, sobald die
    // Zähler auf „Eigenständig / Gesamt" stehen (so ist die Laufer Str. 5
    // konfiguriert: Boiler auf die zwei WG-Wohnungen, Studio mit eigenem).
    // Entscheidend ist allein, dass er einer Einheit zugeordnet ist.
    if (wasserArt(z) !== 'Warmwasser') continue;
    const v = z.verbrauch || 0;
    if (!v) continue;
    const ein = zaehlerEinheiten(z).filter(e => alleEinheiten().includes(e));
    if (!ein.length) continue;
    for (const e of ein) karte[e] = (karte[e] || 0) + v / ein.length;
  }
  return karte;
}

/* Warmwasser-Kosten cent-genau verteilen. */
function wwVerteilung(kosten, wasserDetail) {
  const mengen = wwJeEinheit(wasserDetail);
  const namen = Object.keys(mengen);
  const summe = namen.reduce((s, e) => s + mengen[e], 0);
  if (!summe || !kosten) return { mengen, anteile: {}, summe };
  const anteile = {};
  let rest = Math.round(kosten * 100);
  namen.forEach((e, i) => {
    const c = i === namen.length - 1 ? rest
      : Math.round(kosten * 100 * mengen[e] / summe);
    anteile[e] = c / 100;
    rest -= c;
  });
  return { mengen, anteile, summe };
}

/* N79 — Öl-Manager inline. */
export async function fuelleHeizoelInline(el) {
  const slug = encodeURIComponent(state.daten.objekt);
  try {
    // N369 — dieselben drei Auskünfte holt `checkliste.laden()` bereits. Ohne
    // Bündelung waren es bei drei offenen Öl-Panels vier identische GETs je
    // Zeichnung.
    const [best, bew] = await Promise.all([
      einmal(`/objekte/${slug}/heizoel`),
      einmal(`/objekte/${slug}/heizoel/bewertung?zeitraum_id=${state.zid}`)
        .catch(() => null),
    ]);
    // N80 — Warmwassermenge (m³) für den §9-Split.
    const zl = state.ablesungMaske?.zaehler || [];
    const wwHaupt = zl.find(z => wasserArt(z) === 'Warmwasser' && !z.hauptzaehler_id);
    const wwVol = wwHaupt?.verbrauch != null ? wwHaupt.verbrauch
      : zl.filter(z => wasserArt(z) === 'Warmwasser' && z.hauptzaehler_id)
          .reduce((s, z) => s + (z.verbrauch || 0), 0);
    let split = null;
    if (bew && bew.verbrauch_kosten > 0) {
      split = await einmal(
        `/objekte/${slug}/waerme/split?oel_kosten=${bew.verbrauch_kosten}`
        + `&oel_liter=${bew.verbrauch_liter}&ww_volumen_m3=${wwVol}`).catch(() => null);
    }
    // N118 — Warmwasser-Modus braucht die Wasser-Detailmengen.
    // N369 — `einmal()` statt Wert-Cache: der Guard `!wasserDetailCache` griff
    // nicht, weil `wasser.js` und dieses Modul im selben Tick starteten und
    // keiner awaited wurde — beide holten. Das gemerkte Promise deckt auch die
    // Zeit ab, in der die erste Anfrage noch läuft.
    if ((el.dataset.heizModus || 'oel') === 'warmwasser' && !state.wasserDetailCache) {
      state.setWasserDetailCache(await einmal(`/zeitraeume/${state.zid}/wasser`
        + `?schluessel=${state.wasserSchluessel}`).catch(() => null));
    }
    // N356 — die Verteilung der Heizkosten auf die Einheiten aus den ECHTEN
    // Zählern (`heizkosten.py`, N340w): Heizkörperzähler mit ihrem
    // Bewertungsfaktor, Wärmemengenzähler mit ihren kWh, Grundkosten nach
    // Fläche. Die alte `heizung/verteilung` liest die separate
    // `Heizverteiler`-Tabelle, die hier leer ist — deshalb blieb die Ansicht
    // ohne Tabelle. Übergeben wird der schon warmwasserbereinigte Betrag,
    // deshalb `ww_kwh: 0` (sonst zöge die Rechnung ein zweites Mal ab).
    let heizVerteilung = null;
    if (split && split.heizung_kosten > 0 && bew?.verbrauch_liter) {
      const literHeiz = bew.verbrauch_liter * (1 - (split.ww_anteil || 0));
      heizVerteilung = await einmalPost(
        `/zeitraeume/${state.zid}/heizkosten/rechnen`,
        { liter: literHeiz, eur: split.heizung_kosten, ww_kwh: 0,
          fest_anteil: 0.30, fest_schluessel: state.heizFestSchluessel }).catch(() => null);
    }
    el.innerHTML = heizoelInhalt(best, bew, wwVol, split,
                                 el.dataset.heizModus || 'oel', heizVerteilung,
                                 el.dataset.pid, el.dataset.schluessel,
                                 el.dataset.art || '');
  } catch (fehler) {
    el.innerHTML = `<div class="wd-lade">Heizöl nicht ladbar: ${
      esc(String(fehler.message || fehler))}</div>`;
  }
}

/* Der Öl-Manager als HTML. */
/* N356 — eine Verteilungstabelle im Wasser-Stil (`.wd-tab`): Kopfzeile mit
   den Einheiten, je Zeile eine Herkunft (Menge klein, Betrag darunter),
   Summenzeile. Damit sehen Wasser, Warmwasser und Heizung gleich aus. */
function verteilTabelle(titel, spalten, zeilen, summe) {
  if (!spalten.length) return '';
  const zelle = w => w == null
    ? '<td class="wd-leerz">–</td>'
    : `<td><span class="wd-m3">${w.menge ?? ''}</span>
        <span class="wd-eur">${eur(w.eur || 0)}</span></td>`;
  return `<div class="wd-tabelle"><table class="wd-tab">
      <thead><tr><th class="wd-rowh">${esc(titel)}</th>${
        spalten.map(e => `<th>${esc(e)}</th>`).join('')}</tr></thead>
      <tbody>${zeilen.map(z => `<tr><td class="wd-rowh">${esc(z.name)}${
          z.herkunft ? `<small>${esc(z.herkunft)}</small>` : ''}</td>${
          spalten.map(e => zelle(z.werte[e])).join('')}</tr>`).join('')}
        <tr class="wd-summe"><td class="wd-rowh">Summe</td>${
          spalten.map(e => `<td><span class="wd-m3">${
            eur(summe[e] || 0)}</span></td>`).join('')}</tr>
      </tbody></table></div>`;
}

/* N358/N395 — Verteilerschlüssel wählen wie beim Wasser (`wd-schl`): der
   Rest, der nicht über Zähler läuft, geht nach Fläche, Personen oder
   Einheiten. Zwei GRUNDVERSCHIEDENE Verwendungen teilen sich diese Optik:
   beim Warmwasser (`ziel="position"`) ist es `Kostenposition.schluessel`,
   den der generische Verteilungsmotor liest; bei der Heizung
   (`ziel="grundkosten"`) ist es `waermesim.rechne`s `fest_schluessel` —
   ein reiner Session-Wert (`state.heizFestSchluessel`), weil die Heizkosten
   nicht über die Kostenposition, sondern live aus den Zählern gerechnet
   werden. Der Klick-Handler (`checkliste.js`) unterscheidet über `ziel`,
   welchen der beiden Wege er nimmt — vorher liefen beide auf denselben
   PATCH, der bei der Heizung nichts bewirkte. */
function schluesselWahlHtml(pid, jetzt, label, ziel) {
  if (!pid) return '';
  const knopf = (wert, text) => `<button type="button" class="wd-sb${
    (jetzt || 'flaeche') === wert ? ' an' : ''}"
    data-heiz-schluessel="${wert}" data-heiz-ziel="${ziel}"
    data-pid="${pid}">${text}</button>`;
  return `<div class="wd-schl"><span class="wd-schl-l">${esc(label)}</span>
    ${knopf('flaeche', 'Fläche')}${knopf('personen', 'Personen')}
    ${knopf('einheiten', 'Einheiten')}</div>`;
}

function heizoelInhalt(best, bew, wwVol, split, modus = 'oel',
                       heizVerteilung = null, pid = '', schluessel = '',
                       art = '') {
  const bearbeitbar = state.daten.status === 'in Arbeit';
  const liefer = (best?.lieferungen || []);
  const kopf = bew && bew.verbrauch_liter != null
    ? `<div class="ho-kpi">
        ${bew.anfang_liter != null ? `<div class="ho-kbox">
          <span class="ho-kl">Bestand zu Periodenbeginn</span>
          <span class="ho-kv">${zahl(bew.anfang_liter)} L · ${eur(bew.anfang_wert)}</span></div>` : ''}
        <div class="ho-kbox"><span class="ho-kl">Verbrauch Periode</span>
          <span class="ho-kv">${zahl(bew.verbrauch_liter)} L</span></div>
        <div class="ho-kbox teal"><span class="ho-kl">Heizkosten (FIFO)</span>
          <span class="ho-kv">${eur(bew.verbrauch_kosten)}</span></div>
        <div class="ho-kbox"><span class="ho-kl">Restbestand am Ende</span>
          <span class="ho-kv">${zahl(bew.rest_liter)} L · ${eur(bew.rest_wert)}</span></div>
      </div>${bew.warnung ? `<div class="ho-warn">▲ ${esc(bew.warnung)}</div>` : ''}`
    : `<div class="ho-warn">Noch keine Öl-Lieferung erfasst — unten anlegen. Der
        Perioden-Verbrauch kommt aus dem Öl-Zähler.</div>`;
  const inPeriode = bew?.lieferungen_periode;
  const sichtbar = Array.isArray(inPeriode)
    ? liefer.filter(l => inPeriode.includes(l.id) || l.ist_anfangsbestand) : liefer;
  const zeilen = sichtbar.length ? sichtbar.map(l => `
    <div class="ho-zeile">
      <span class="ho-dt">${_isoKurz(l.datum)}${l.ist_anfangsbestand
        ? ' <span class="ho-anf">Anfangsbestand — zählt vor der Periode</span>'
        : ''}</span>
      <span class="ho-lit">${zahl(l.liter)} L</span>
      <span class="ho-wert">${eur(l.wert)}</span>
      <span class="ho-pl">${eur(l.preis_liter ?? (l.liter ? l.wert / l.liter : 0))}/L</span>
      ${bearbeitbar ? `<button class="ho-x" data-heizoel-weg="${l.id}"
        data-was="${esc(`${_isoKurz(l.datum)} · ${zahl(l.liter)} L · ${eur(l.wert)}`)}"
        aria-label="Lieferung entfernen">×</button>` : ''}
    </div>`).join('') : '';
  const nurPeriode = sichtbar.filter(l => !l.ist_anfangsbestand
    || !Array.isArray(inPeriode) || inPeriode.includes(l.id));
  const bestZeile = sichtbar.length
    ? `<div class="ho-summe">In dieser Periode getankt: <b>${
        zahl(nurPeriode.reduce((s, l) => s + (l.liter || 0), 0))} L</b> · <b>${
        eur(nurPeriode.reduce((s, l) => s + (l.wert || 0), 0))}</b>${
        liefer.length > sichtbar.length
          ? ` · insgesamt erfasst: ${zahl(best.bestand_liter)} L` : ''}</div>` : '';
  const form = bearbeitbar ? `
    <div class="ho-neu">
      <input type="date" data-ho-datum aria-label="Datum" value="${state.daten.ende || ''}">
      <input type="number" step="0.1" data-ho-liter placeholder="Liter" aria-label="Liter">
      <input type="number" step="0.01" data-ho-wert placeholder="€ gesamt" aria-label="Wert €">
      <label class="ho-anfw"><input type="checkbox" data-ho-anf> Anfangsbestand</label>
      <button class="btn" data-heizoel-add>Lieferung hinzufügen</button>
    </div>` : '';
  // N80 — §9-Split Warmwasser vs. Heizung.
  const splitHtml = split ? `<div class="ho-sekt">
      <div class="ho-st">Warmwasser & Heizung <span class="ho-sh">§9: 2,5·V·(t−10)</span></div>
      <div class="ho-kpi">
        <div class="ho-kbox"><span class="ho-kl">Warmwasser-Menge</span>
          <span class="ho-kv">${zahl(wwVol)} m³ · ${zahl(split.ww_kwh)} kWh</span></div>
        <div class="ho-kbox"><span class="ho-kl">Warmwasser-Kosten</span>
          <span class="ho-kv">${eur(split.ww_kosten)}</span></div>
        <div class="ho-kbox teal"><span class="ho-kl">Heizungs-Kosten</span>
          <span class="ho-kv">${eur(split.heizung_kosten)}</span></div>
      </div>${split.warnung ? `<div class="ho-warn">▲ ${esc(split.warnung)}</div>` : ''}
    </div>` : '';
  // N369 — der HKV-Block ist ersatzlos raus. N356 hat die Heizkörper auf
  // echte `Zaehler` umgestellt und die Anzeige auf `heizkosten/rechnen`; das
  // hier gebaute `hkvHtml` wurde seither von keinem Zweig mehr ausgegeben,
  // holte aber weiter `heizung/verteilung` (sechsmal je Seitenaufbau) aus der
  // leeren Legacy-Tabelle. Mit ihm gehen `hkvHinzufuegen`/`hkvEntfernen`.
  // N91 — je Stufe nur ihren Teil zeigen.
  if (modus === 'warmwasser') {
    // N118 — Verteilung der Warmwasser-Kosten auf die Einheiten.
    const wv = wwVerteilung(split?.ww_kosten || 0, state.wasserDetailCache);
    const sp = Object.keys(wv.mengen);
    // N356 — dieselbe Tabellenform wie beim Wasser.
    const wwTab = verteilTabelle('Warmwasser', sp, [{
      name: 'Warmwasser', herkunft: 'nach Zähler',
      werte: Object.fromEntries(sp.map(e => [e, {
        menge: `${zahl(wv.mengen[e])} m³`, eur: wv.anteile[e] || 0 }])),
    }], Object.fromEntries(sp.map(e => [e, wv.anteile[e] || 0])));
    return `<div class="ho-box">${splitHtml
      || '<div class="ho-warn">Noch keine Öl-Kosten erfasst — erst Lieferungen und den Zähler-Endstand bei „Heizöl & Lieferungen" eintragen.</div>'}${
      schluesselWahlHtml(pid, schluessel, 'Ohne eigenen Zähler verteilen nach', 'position')}${wwTab}</div>`;
  }
  if (modus === 'waerme') {
    const kopfW = split ? `<div class="ho-kpi"><div class="ho-kbox teal">
        <span class="ho-kl">Heizungs-Kosten (nach Warmwasser-Abzug)</span>
        <span class="ho-kv">${eur(split.heizung_kosten)}</span></div></div>` : '';
    // N356 — Verteilung auf die Einheiten aus den echten Zählern, in
    // derselben Tabellenform wie beim Wasser: Wärme nach Zählern (Heizkörper
    // mit Faktor + Wärmemengenzähler), Grundkosten nach Fläche.
    const nutzer = (heizVerteilung?.nutzer || []).filter(n => n.summe || n.heizkosten);
    const sp = nutzer.map(n => n.name);
    const wert = (n, betrag, menge) => [n.name, { menge, eur: betrag }];
    const waerme = n => (n.verbrauch_h1 || 0) + (n.verbrauch_h2 || 0);
    // Steht noch kein Ablesewert, ist der Verbrauchsanteil nicht verteilbar —
    // eine 0,00-€-Zeile würde das verschleiern.
    const hatVerbrauch = nutzer.some(n => waerme(n) > 0.005);
    const zeilen = [];
    if (hatVerbrauch) {
      zeilen.push({ name: 'Wärme', herkunft: 'nach Zählern',
        werte: Object.fromEntries(nutzer.map(n => wert(n, waerme(n),
          n.kwh ? `${zahl(n.kwh)} kWh` : ''))) });
    }
    // N395 — die Herkunft zeigt jetzt den TATSÄCHLICH gewählten Schlüssel,
    // vorher stand hier immer „nach Fläche", auch wenn Personen oder
    // Einheiten gewählt war — der Text hätte sonst gelogen, sobald der
    // (jetzt endlich wirksame) Umschalter etwas anderes als Fläche wählt.
    const festHerkunft = { flaeche: 'nach Fläche', personen: 'nach Personen',
      einheiten: 'nach Einheiten' }[state.heizFestSchluessel] || 'nach Fläche';
    zeilen.push({ name: 'Grundkosten', herkunft: festHerkunft,
      werte: Object.fromEntries(nutzer.map(n => wert(n, n.festkosten || 0, ''))) });
    const heizTab = verteilTabelle('Heizung', sp, zeilen,
      Object.fromEntries(nutzer.map(n => [n.name, n.heizkosten || 0])));
    const verteilt = nutzer.reduce((s, n) => s + (n.heizkosten || 0), 0);
    const rest = (split?.heizung_kosten || 0) - verteilt;
    // N395 — der Nutzer wollte die Summe aller Weiterverrechnungen sehen UND
    // auf einen Blick wissen, ob alles verteilt wurde: die Kopf-Kachel zeigt
    // nur die Heizungskosten VOR Verteilung, die Tabelle nur je Einheit —
    // die Gesamtsumme über alle Einheiten stand nirgends. `rest` war schon
    // berechnet, wurde bisher aber nur in einem Spezialfall (fehlender
    // Verbrauch) erwähnt, nie als allgemeiner Abgleich.
    const vollstaendig = Math.abs(rest) < 0.01;
    // Fehlt noch der Verbrauchsanteil (kein Zähler abgelesen), erklärt der
    // spezifische Hinweis unten schon, WAS fehlt und WARUM — die allgemeine
    // Summenzeile hier nur für den Regelfall, sonst stünde dieselbe Lücke
    // zweimal da (einmal generisch, einmal mit Begründung).
    const summeCheck = (split?.heizung_kosten || 0) > 0 && hatVerbrauch
      ? `<div class="ho-summe-check${vollstaendig ? ' ok' : ''}">
          <span class="ho-sc-ik">${vollstaendig ? '✓' : '▲'}</span>
          <span>${vollstaendig
            ? `Vollständig weiterverrechnet: <b>${eur(verteilt)}</b>`
            : `<b>${eur(verteilt)}</b> von ${eur(split.heizung_kosten)} weiterverrechnet
               — <b>${eur(Math.abs(rest))}</b> ${rest > 0 ? 'noch offen' : 'zu viel verteilt'}`}
          </span></div>` : '';
    const hinweise = [];
    if (!hatVerbrauch && (split?.heizung_kosten || 0) > 0) {
      hinweise.push(`Für diesen Zeitraum ist noch kein Heizkörper- oder
        Wärmemengenzähler abgelesen — verteilt sind bisher nur die
        Grundkosten nach Fläche. Die restlichen <b>${eur(Math.max(0, rest))}</b>
        (Verbrauchsanteil) folgen, sobald die Zählerstände unter
        „Zählerstände · Heizkörper &amp; Wärmemenge" eingetragen sind.`);
    }
    for (const name of (heizVerteilung?.unzugeordnet || [])) {
      hinweise.push(`<b>${esc(name)}</b> ist keiner Einheit zugeordnet und
        zählt deshalb nicht mit — die Zuordnung steht in „Zähler konfigurieren".`);
    }
    const hinweis = hinweise.map(t => `<div class="ho-warn">▲ ${t}</div>`).join('');
    // N356 — der alte „Heizungswärme · Heizkostenverteiler"-Block (eigene
    // `Heizverteiler`-Tabelle mit HKV-Nr./Raum/Faktor-Formular) ist raus: die
    // Heizkörper sind echte Zähler und werden unter „Zähler konfigurieren"
    // gepflegt, ihre Stände unter „Zählerstände". Zwei Wege für dieselbe
    // Sache waren genau die Verwirrung, die die leere Tabelle erzeugt hat.
    return `<div class="ho-box">${kopfW}${
      schluesselWahlHtml(pid, state.heizFestSchluessel, 'Grundkosten verteilen nach', 'grundkosten')}${
      heizTab}${summeCheck}${hinweis}</div>`;
  }
  return `<div class="ho-box">${kopf}
    ${zeilen ? `<div class="ho-liste">${zeilen}</div>${bestZeile}` : ''}
    ${form}${abschlussHtml(pid, art, bew, bearbeitbar)}</div>`;
}

/* N364 — der Abschluss-Haken für „Heizöl & Lieferungen". Öl ist der eine
   Posten, den keine Regel automatisch für fertig erklären kann: es gibt keinen
   Beleg, der die Periode abschließt, und der Verbrauch stimmt erst, wenn alle
   Lieferungen und der Zähler-Endstand drin sind. Das weiß nur der Nutzer —
   also bestätigt er es hier, und die Position wird grün.

   Der Haken bestätigt die ERFASSUNG, er legt kein Geld um: das Öl-Geld
   erreicht die Einheiten über die Positionen „Heizkörper Wärmemenge" und
   „Warmwassererzeugung" (§9-Split). Die Sammelposition trägt deshalb bewusst
   `betrag: 0` — stünde hier der volle Öl-Betrag, käme er ein zweites Mal auf
   die Mieter. Angezeigt wird trotzdem der echte Betrag, den
   `positionsBetrag()` aus der FIFO-Bewertung holt. */
function abschlussHtml(pid, art, bew, bearbeitbar) {
  if (!bearbeitbar || !(pid || art)) return '';
  const kosten = bew?.verbrauch_kosten || 0;
  const liter = bew?.verbrauch_liter || 0;
  if (kosten <= 0.005) return '';
  const pos = pid && (state.daten?.checkliste || [])
    .find(k => String(k.position_id) === String(pid));
  const an = !!pos?.bestaetigt;
  return `<label class="ho-fertig${an ? ' an' : ''}">
    <input type="checkbox" data-heizoel-fertig data-pid="${esc(String(pid || ''))}"
      data-art="${esc(art)}"${an ? ' checked' : ''}>
    <span class="ho-ft">Alle Lieferungen und der Zählerstand sind eingetragen</span>
    <span class="ho-fw">${zahl(liter)} L · ${eur(kosten)}</span></label>`;
}
