/* zeitraum/zaehler-konfig.js — Zähler-Konfig-Dialog (Zahnrad-Knopf,
   CCCLXXX): Zähler je Immobilie anlegen, entfernen, verschieben, Messeinheit /
   Bezug / Kostenart einstellen, Verrechnung setzen (Rest = Hauptzähler −
   Unterzähler), Anfangsstand vor der ersten Abrechnung erfassen.

   Zusätzlich: der ablesungWizard (CCXCIII), der von N211 zwar aus der UI
   ausgekoppelt wurde, aber weiter existiert. Er wird derzeit nicht mehr
   aufgerufen — der Öffnungsknopf ist raus, siehe `ablesenKnopfHtml`. */

import { api, esc, frage, melde } from '../immo.js';
import * as state from './state.js';
import { MESSEINHEITEN } from './state.js';
import { GEAR_ICON, MUELL_ICON } from './icons.js';
import { zahl, feldZahl } from './helpers.js';

/* CCCLXXX — der Zahnrad-Knopf über der Checkliste. */
export function ablesenKnopfHtml() {
  return `<div class="ablese-leiste nur-konfig">
    <button class="zk-gear breit" id="zaehlerKonfig" type="button"
      aria-label="Zähler konfigurieren">${GEAR_ICON}<span>Zähler konfigurieren</span></button>
  </div>`;
}

/* Frühester Periodenbeginn (ISO). */
function fruehesterStartISO(objektDaten) {
  const daten2 = (objektDaten?.zeitraeume || [])
    .map(z => (z.label || '').match(/(\d{2})\.(\d{2})\.(\d{4})/))
    .filter(Boolean).map(m => `${m[3]}-${m[2]}-${m[1]}`).sort();
  return daten2[0] || null;
}

async function neuLaden() {
  const { laden } = await import('./checkliste.js');
  await laden();
}

export async function zaehlerKonfig() {
  const slug = state.daten.objekt;
  let meters, objektDaten;
  try {
    [meters, objektDaten] = await Promise.all([
      api(`/objekte/${slug}/zaehler`), api(`/objekte/${slug}`)]);
  } catch (fehler) { melde(fehler.message || 'Zähler nicht ladbar', 'neg'); return; }

  const startISO = fruehesterStartISO(objektDaten) || state.daten.start;
  const kostenarten = [...new Set((state.daten.checkliste || []).map(k => k.kostenart))];
  const bezuege = [...new Set((state.schluessel?.parteien || []).map(p => p.partei))];

  const dlg = document.createElement('dialog');
  // N340v — eigene Klasse, damit die Weite NUR diese Maske betrifft (39
  // Zähler mit Grid brauchen am PC mehr Platz), nicht den Ablese-Wizard.
  dlg.className = 'ablese-dlg zk-dlg';
  document.body.appendChild(dlg);
  dlg.addEventListener('close', () => { dlg.remove(); neuLaden(); });

  async function neuLadenIntern() {
    try { meters = await api(`/objekte/${slug}/zaehler`); } catch { /* Ansicht bleibt */ }
    render();
  }

  const opt = (wert, text, sel) =>
    `<option value="${esc(String(wert))}"${sel ? ' selected' : ''}>${esc(text)}</option>`;

  // N231 — „fertig eingerichtet" heißt: Messeinheit und Kostenart sind gesetzt,
  // und (falls nötig) ein Anfangsstand liegt vor. Ein Rest-Zähler braucht
  // keinen eigenen Anfangsstand — sein Stand ergibt sich rechnerisch, und ein
  // „direkt"-Zähler (N340u — Wärmemengenzähler: immer ein fertiger Jahreswert
  // pro Turnus, kein kumulierter Stand) bekommt seinen Wert erst beim Ablesen
  // des jeweiligen Zeitraums, nicht hier.
  function vollstaendig(z) {
    if (!z.messeinheit || !z.kostenart) return false;
    return z.typ === 'rest' || z.typ === 'direkt' || !!z.anfangsstand;
  }

  // N340u — bei 39 Zählern ist die volle Karte für jeden zu viel auf einmal;
  // offen bleibt nur, was der Nutzer selbst antippt. Übersteht ein `render()`
  // (Verrechnung ändern, Zähler hinzufügen), weil es ausserhalb davon lebt.
  const offen = new Set();

  // N340u — Bewertungsfaktor ergibt nur bei Heizkostenverteilern (Verdunstungs-
  // röhrchen: Messeinheit „Einheiten") einen Sinn — ein Wärmemengenzähler
  // misst kWh direkt, ein Wasserzähler m³, keiner von beiden braucht ihn.
  function istHkv(z) {
    return z.messeinheit === 'Einheiten';
  }

  function karte(z, i) {
    const rest = z.typ === 'rest';
    const messSel = MESSEINHEITEN.map(m => opt(m, m, m === z.messeinheit)).join('')
      + (MESSEINHEITEN.includes(z.messeinheit) ? '' : opt(z.messeinheit, z.messeinheit, true));
    const bezugSel = opt('', 'Haus / Gesamt', !z.einheit_bezug)
      + bezuege.map(b => opt(b, b, b === z.einheit_bezug)).join('')
      + (z.einheit_bezug && !bezuege.includes(z.einheit_bezug)
         ? opt(z.einheit_bezug, z.einheit_bezug, true) : '');
    const kaSel = opt('', '— keine —', !z.kostenart)
      + kostenarten.map(k => opt(k, k, k === z.kostenart)).join('')
      + (z.kostenart && !kostenarten.includes(z.kostenart)
         ? opt(z.kostenart, z.kostenart, true) : '');
    const modus = rest ? 'rest' : z.typ === 'direkt' ? 'direkt' : (z.hauptzaehler_id ? 'unter' : 'frei');
    const verrSel = opt('frei', 'Eigenständig / Gesamt', modus === 'frei')
      + opt('unter', 'Unterzähler von …', modus === 'unter')
      + opt('rest', 'Rest von …', modus === 'rest')
      // N340u — Wärmemengenzähler u.ä.: kein Stand zum Interpolieren, jeder
      // Zeitraum bekommt beim Ablesen direkt seinen fertigen Jahreswert.
      + opt('direkt', 'Jahreswert direkt (kein Zählerstand)', modus === 'direkt');
    // N231 — nur Zähler derselben Messeinheit lassen sich gegeneinander
    // verrechnen (Rest = Hauptzähler − Unterzähler ergibt zwischen kWh und m³
    // keinen Sinn).
    const gleicheEinheit = meters.filter(m => m.id !== z.id && m.messeinheit === z.messeinheit);
    const hauptSel = gleicheEinheit.length
      ? gleicheEinheit.map(m => opt(m.id, m.name, m.id === z.hauptzaehler_id)).join('')
      : opt('', `kein anderer ${z.messeinheit}-Zähler`, true);
    let restInfo = '';
    if (rest && z.hauptzaehler_id) {
      const haupt = meters.find(m => m.id === z.hauptzaehler_id);
      const unter = meters.filter(m => m.typ === 'gemessen'
        && m.hauptzaehler_id === z.hauptzaehler_id);
      restInfo = `<div class="zk-rest">Rest = ${esc(haupt?.name || '?')}${
        unter.length ? unter.map(u => ` − ${esc(u.name)}`).join('')
                     : ' − (noch keine Unterzähler)'}</div>`;
    }
    const anf = z.anfangsstand;
    const anfBlock = rest ? '' : modus === 'direkt'
      ? `<div class="zk-rest">Kein Anfangsstand nötig — der Jahreswert wird
          beim Ablesen des jeweiligen Zeitraums eingetragen, nicht hier.</div>`
      : `<div class="zk-anfang">
        <div class="zk-feld"><label>Anfangsstand</label>
          <input type="number" step="0.001" inputmode="decimal" placeholder="—"
            value="${anf ? anf.stand : ''}" data-zk-anf-stand="${z.id}"
            aria-label="Anfangsstand ${esc(z.name)}"></div>
        <div class="zk-feld"><label>am</label>
          <input type="date" value="${anf ? anf.datum : startISO}"
            data-zk-anf-datum="${z.id}" aria-label="Datum Anfangsstand"></div>
      </div>`;

    const fertig = vollstaendig(z);
    const aufgeklappt = offen.has(z.id);
    // N340u — die Kopfzeile bleibt immer sichtbar (Name, Nummer, Status); der
    // Rest klappt erst auf Antippen auf. Bei 39 Zählern ist die volle Karte
    // für jeden zu viel auf einmal.
    return `<div class="zk-karte${aufgeklappt ? '' : ' zu'}" data-zid="${z.id}">
      <div class="zk-kopf" data-zk-toggle="${z.id}">
        <span class="zk-status ${fertig ? 'ok' : 'warn'}"
          title="${fertig ? 'Vollständig eingerichtet' : 'Noch nicht vollständig eingerichtet'}"
          aria-hidden="true">${fertig ? '✓' : '!'}</span>
        <span class="zk-kopftxt">
          <input class="zk-name" value="${esc(z.name)}" data-zk-f="name" data-zid="${z.id}"
            aria-label="Zählername">
          ${z.zaehlernummer ? `<span class="zk-nr">Nr. ${esc(z.zaehlernummer)}</span>` : ''}
        </span>
        <span class="zk-chevron" aria-hidden="true">${aufgeklappt ? '▾' : '▸'}</span>
        <div class="zk-tools">
          <button class="zk-ic" data-zk-up="${z.id}" ${i === 0 ? 'disabled' : ''}
            aria-label="nach oben">↑</button>
          <button class="zk-ic" data-zk-down="${z.id}"
            ${i === meters.length - 1 ? 'disabled' : ''} aria-label="nach unten">↓</button>
          <button class="zk-ic gefahr" data-zk-del="${z.id}"
            aria-label="Zähler entfernen">${MUELL_ICON}</button>
        </div>
      </div>
      ${aufgeklappt ? `
      <div class="zk-grid">
        <div class="zk-feld"><label>Zählernummer</label>
          <input value="${esc(z.zaehlernummer || '')}" data-zk-f="zaehlernummer"
            data-zid="${z.id}" placeholder="z. B. 5057" aria-label="Zählernummer"></div>
        <div class="zk-feld"><label>Einheit</label>
          <select data-zk-f="messeinheit" data-zid="${z.id}">${messSel}</select></div>
        <div class="zk-feld"><label>Bezug</label>
          <select data-zk-f="einheit_bezug" data-zid="${z.id}">${bezugSel}</select></div>
        <div class="zk-feld"><label>Kostenart</label>
          <select data-zk-f="kostenart" data-zid="${z.id}">${kaSel}</select></div>
        ${istHkv(z) ? `<div class="zk-feld"><label>Bewertungsfaktor</label>
          <input type="number" step="0.001" inputmode="decimal" placeholder="—"
            value="${z.bewertungsfaktor ?? ''}" data-zk-f="bewertungsfaktor"
            data-zid="${z.id}" aria-label="Bewertungsfaktor"></div>` : ''}
        <div class="zk-feld"><label>Verrechnung</label>
          <select data-zk-verr="${z.id}">${verrSel}</select></div>
        ${modus !== 'frei' && modus !== 'direkt' ? `<div class="zk-feld voll"><label>Hauptzähler</label>
          <select data-zk-f="hauptzaehler_id" data-zid="${z.id}">${hauptSel}</select></div>` : ''}
      </div>
      ${restInfo}
      ${anfBlock}` : ''}
    </div>`;
  }

  function render() {
    // N231 — jedes `render()` ersetzt das komplette innerHTML; ohne das hier
    // sprang die lange Liste bei jeder Änderung (Verrechnung, Zähler
    // hinzufügen/entfernen/verschieben) zurück an den Anfang.
    const vorherigerBody = dlg.querySelector('.zk-body');
    const scrollY = vorherigerBody?.scrollTop || 0;
    const liste = meters.length
      ? meters.map((z, i) => karte(z, i)).join('')
      : `<div class="zk-leer">Noch keine Zähler für diese Immobilie. Lege den
          ersten an — Gesamtzähler, Unterzähler je Einheit und, wenn nötig, einen
          berechneten Rest.</div>`;
    dlg.innerHTML = `
      <div class="aw-kopf">
        <span class="t">Zähler · ${esc(state.daten.objekt_name)}</span>
        <button class="aw-x" data-zk-schliessen aria-label="Schließen">×</button>
      </div>
      <div class="aw-body zk-body">
        <p class="zk-intro">Zähler dieser Immobilie: Messeinheit, Bezug und
          Kostenart einstellen, die Verrechnung festlegen (Rest = Hauptzähler −
          Unterzähler) und den Anfangsstand vor der ersten Abrechnung setzen.</p>
        ${meters.length ? `<div class="zk-fort">
            <div class="zk-balken"><i style="width:${
              Math.round(meters.filter(vollstaendig).length / meters.length * 100)}%"></i></div>
            <span class="zk-fz">${meters.filter(vollstaendig).length} von
              ${meters.length} eingerichtet</span>
          </div>` : ''}
        <div class="zk-liste">${liste}</div>
        <button class="zk-add" data-zk-add>＋ Zähler hinzufügen</button>
      </div>
      <div class="aw-fuss">
        <button class="aw-weiter" data-zk-schliessen style="flex:1">Fertig</button>
      </div>`;
    const neuerBody = dlg.querySelector('.zk-body');
    if (neuerBody) neuerBody.scrollTop = scrollY;
  }

  dlg.addEventListener('change', async e => {
    const f = e.target.closest('[data-zk-f]');
    if (f) {
      const id = f.dataset.zid;
      let wert = f.value;
      if (f.dataset.zkF === 'hauptzaehler_id') wert = wert ? Number(wert) : null;
      else if (f.dataset.zkF === 'bewertungsfaktor') wert = feldZahl(f);
      const z = meters.find(m => String(m.id) === String(id));
      if (z) z[f.dataset.zkF] = wert;
      try { await api(`/zaehler/${id}`, { method: 'PATCH', body: { [f.dataset.zkF]: wert } }); }
      catch (fehler) { melde(fehler.message || 'Speichern fehlgeschlagen', 'neg'); }
      return;
    }
    const verr = e.target.closest('[data-zk-verr]');
    if (verr) return verrechnungSetzen(Number(verr.dataset.zkVerr), verr.value);
    const anf = e.target.closest('[data-zk-anf-stand],[data-zk-anf-datum]');
    if (anf) return anfangsstandSpeichern(
      Number(anf.dataset.zkAnfStand || anf.dataset.zkAnfDatum));
  });

  async function verrechnungSetzen(id, modus) {
    const z = meters.find(m => m.id === id);
    // N231 — nur ein Zähler derselben Messeinheit taugt als Hauptzähler; ein
    // vorhandener, aber nicht mehr passender hauptzaehler_id-Wert wird verworfen.
    const gleiche = meters.filter(m => m.id !== id && m.messeinheit === z?.messeinheit);
    const haupt = (z?.hauptzaehler_id && gleiche.some(m => m.id === z.hauptzaehler_id))
      ? z.hauptzaehler_id : (gleiche[0]?.id || null);
    const body = modus === 'frei' || modus === 'direkt'
      ? { typ: modus === 'direkt' ? 'direkt' : 'gemessen', hauptzaehler_id: null }
      : { typ: modus === 'rest' ? 'rest' : 'gemessen', hauptzaehler_id: haupt };
    try { await api(`/zaehler/${id}`, { method: 'PATCH', body }); await neuLadenIntern(); }
    catch (fehler) { melde(fehler.message || 'Speichern fehlgeschlagen', 'neg'); }
  }

  async function anfangsstandSpeichern(id) {
    const s = dlg.querySelector(`[data-zk-anf-stand="${id}"]`);
    const d = dlg.querySelector(`[data-zk-anf-datum="${id}"]`);
    if (String(s?.value ?? '').trim() === '') return;
    const stand = feldZahl(s);
    if (stand == null) return;
    const datum = d?.value || startISO;
    try {
      await api(`/zaehler/${id}/ablesungen`,
        { method: 'POST', body: { stand, datum, notiz: 'Anfangsstand' } });
      const z = meters.find(m => m.id === id);
      if (z) z.anfangsstand = { stand, datum };
      // N230 — still speichern: bei zügiger Eingabe mehrerer Zähler
      // hintereinander störte die Erfolgsmeldung bei jedem einzelnen Feld.
      // Ein Fehler bleibt weiterhin sichtbar (siehe catch).
    } catch (fehler) { melde(fehler.message || 'Speichern fehlgeschlagen', 'neg'); }
  }

  dlg.addEventListener('click', async e => {
    if (e.target.closest('[data-zk-schliessen]')) { dlg.close(); return; }
    if (e.target.closest('[data-zk-add]')) {
      try {
        await api(`/objekte/${slug}/zaehler`, { method: 'POST',
          body: { name: 'Neuer Zähler', messeinheit: 'm³', reihenfolge: meters.length } });
        await neuLadenIntern();
      } catch (fehler) { melde(fehler.message || 'Anlegen fehlgeschlagen', 'neg'); }
      return;
    }
    const del = e.target.closest('[data-zk-del]');
    if (del) {
      const z = meters.find(m => m.id === Number(del.dataset.zkDel));
      const ja = await frage(`„${z?.name || 'Zähler'}" entfernen?`,
        'Der Zähler und seine Ablesungen werden gelöscht. Kostenpositionen und '
        + 'Belege bleiben unangetastet.', { knopf: 'Entfernen', gefahr: true });
      if (!ja) return;
      try { await api(`/zaehler/${del.dataset.zkDel}`, { method: 'DELETE' }); await neuLadenIntern(); }
      catch (fehler) { melde(fehler.message || 'Löschen fehlgeschlagen', 'neg'); }
      return;
    }
    const bewegung = e.target.closest('[data-zk-up],[data-zk-down]');
    if (bewegung) return verschieben(
      Number(bewegung.dataset.zkUp || bewegung.dataset.zkDown),
      bewegung.dataset.zkUp ? -1 : 1);
    // N340u — Kopfzeile antippen klappt die Karte auf/zu. Kommt nach den
    // spezifischeren Zielen oben, sonst schlucken deren Buttons nie das
    // Toggle (sie liegen alle INNERHALB der Kopfzeile). Der Name bleibt
    // tippbar, ohne die Karte gleich wieder zuzuklappen.
    if (e.target.matches('input')) return;
    const toggle = e.target.closest('[data-zk-toggle]');
    if (toggle) {
      const id = Number(toggle.dataset.zkToggle);
      offen.has(id) ? offen.delete(id) : offen.add(id);
      render();
    }
  });

  async function verschieben(id, richtung) {
    const i = meters.findIndex(m => m.id === id);
    const j = i + richtung;
    if (i < 0 || j < 0 || j >= meters.length) return;
    const neu = [...meters];
    [neu[i], neu[j]] = [neu[j], neu[i]];
    meters = neu;
    render();
    try {
      await Promise.all(neu.map((m, k) => m.reihenfolge === k ? null
        : api(`/zaehler/${m.id}`, { method: 'PATCH', body: { reihenfolge: k } })));
      neu.forEach((m, k) => { m.reihenfolge = k; });
    } catch (fehler) { melde(fehler.message || 'Speichern fehlgeschlagen', 'neg'); }
  }

  render();
  dlg.showModal();
}
