/* zeitraum/zaehler.js — die Zählerstände-Panels und Zeilen.

   Jede Kategorie (Wasser/Heizung/Strom) bekommt ein eigenes Einklapp-Panel
   (N67). Innerhalb Wasser laufen Kaltwasser und Rest als Subtraktion
   (kaltwasserBlockHtml), Heizung als schlichte Liste, Strom über
   `stromBlockHtml` (Modul strom.js). Die Meter-Zeile selbst rendert
   `meterZeileHtml` — Anfangs-/Endstand mit Datum, Einheiten-Chooser,
   Interpolations-Hinweisen und einem Umbenennen-Bleistift. */

import { api, esc, melde } from '../immo.js';
import * as state from './state.js';
import { ZAEHLER_ICON, CHEV_ICON, STIFT_ICON } from './icons.js';
import { wasserArt } from './modell.js';
import {
  zahl, _isoKurz, chipZahl, chipEinheit, baueChipMap,
  zaehlerEinheiten, alleEinheiten, standAusFeld, zeilenBox, heizBereich,
} from './helpers.js';
import { stromBlockHtml } from './strom.js';

/* N356 — wo die Zuordnung hier NICHT geändert wird (Heizung: das geschieht
   unter „Zähler konfigurieren"), soll sie wenigstens sichtbar sein: auf
   welche Einheit der Zähler zählt, so wie er konfiguriert ist. */
export function nurEinheitenHtml(z) {
  const ein = zaehlerEinheiten(z).filter(Boolean);
  if (!ein.length) return '';
  return `<div class="zu-ehfest"><span class="zu-ehl">Zählt auf</span>
    ${ein.map(e => `<span class="zu-ehtag">${esc(e)}</span>`).join('')}</div>`;
}

/* N58 — kompakter Mehrfach-Auswähler aller Einheiten für einen Zähler. */
export function einheitChooserHtml(z) {
  const alle = alleEinheiten();
  if (!alle.length) return '';
  const gewaehlt = new Set(zaehlerEinheiten(z));
  const chips = alle.map(e => `<button type="button"
      class="zu-eh${gewaehlt.has(e) ? ' an' : ''}"
      data-einheit-toggle="${z.id}" data-einheit="${esc(e)}"
      aria-pressed="${gewaehlt.has(e)}">${esc(e)}</button>`).join('');
  return `<div class="zu-ehwahl"><span class="zu-ehl">Zählt auf</span>
    <div class="zu-ehchips">${chips}</div></div>`;
}

/* N88 — die Umrechnung eines Zählers sichtbar machen. */
export function interpolationsHinweise(z, eh) {
  const start = state.ablesungMaske?.zeitraum?.start || state.daten.start || '';
  const ende = state.ablesungMaske?.zeitraum?.ende || state.daten.ende || '';
  const grenzenAnfang = [state.ablesungMaske?.vorheriges_ende, start].filter(Boolean);
  const saetze = [];
  if (z.vorwert?.datum && !grenzenAnfang.includes(z.vorwert.datum)) {
    saetze.push(`<b>Anfang</b> abgelesen am ${_isoKurz(z.vorwert.datum)} ·
      auf ${_isoKurz(start)} gerechnet
      <strong>${zahl(z.vorwert.stand)}&nbsp;${eh}</strong>`);
  }
  if (z.ablesung?.datum && z.ablesung.datum !== ende) {
    const gerechnet = (z.vorwert && z.verbrauch != null)
      ? z.vorwert.stand + z.verbrauch : null;
    saetze.push(`<b>Ende</b> abgelesen ${zahl(z.ablesung.stand)}&nbsp;${eh} am
      ${_isoKurz(z.ablesung.datum)}` + (gerechnet == null
        ? ` · Startablesung, noch keine Umrechnung`
        : ` · auf ${_isoKurz(ende)} gerechnet
            <strong>${zahl(Math.round(gerechnet * 1000) / 1000)}&nbsp;${eh}</strong>`));
  }
  return saetze;
}

/* N157 — Hauptzähler ohne eigenen Einheit-Chooser. */
export function istHauptzaehler(z) {
  if (z.hauptzaehler_id) return false;
  return (state.ablesungMaske?.zaehler || []).some(a => a.hauptzaehler_id === z.id);
}

/* Was unter der Ladestations-Zeile steht: Quelle + Nutzer + Vorab-Hinweis. */
export function eautoInfoHtml() {
  const d = state.eautoZug;
  const start = state.ablesungMaske?.zeitraum?.start || state.daten.start || '';
  const ende = state.ablesungMaske?.zeitraum?.ende || state.daten.ende || '';
  const spanne = `${_isoKurz(start)} – ${_isoKurz(ende)}`;
  const quelle = d?.ok
    ? `Aus dem Ladeprotokoll der Wallbox für ${spanne} —
       <b>${zahl(d.anzahl || 0)} Ladungen</b>. Von Hand wird hier nichts eingetragen.`
    : `Zuletzt aus dem Ladeprotokoll der Wallbox für ${spanne} gezogen.
       ${esc(d?.hinweis || 'Die Wallbox antwortet gerade nicht — der zuletzt '
         + 'gezogene Wert bleibt stehen.')}`;
  const nutzer = d?.nutzer || [];
  const vorab = 'Der Strom geht <b>vorab</b> ab und wird nicht auf die Einheiten '
    + 'verteilt — das Auto lädt für sich.';
  const wer = nutzer.length === 1
    ? `<b>${esc(nutzer[0])}</b> lädt hier. ${vorab}`
    : (nutzer.length
      ? `${nutzer.map(n => `<b>${esc(n)}</b>`).join(' · ')} laden hier. ${vorab}`
      : `Noch niemand als Nutzer angelegt — das steht im Bereich
         <a href="tankstelle.html?objekt=${encodeURIComponent(state.daten.objekt || '')}"
           >E-Tankstelle</a>. ${vorab}`);
  return `<div class="zu-eauto">
      <div class="zu-eq${d && !d.ok ? ' fehlt' : ''}">
        <span class="zu-ehl">Quelle</span><span class="zu-et">${quelle}</span></div>
      <div class="zu-eq${nutzer.length ? '' : ' fehlt'}">
        <span class="zu-ehl">Lädt</span><span class="zu-et">${wer}</span></div>
    </div>`;
}

/* N156 — umbenennen an Ort und Stelle in der Zeile. */
export function zaehlerUmbenennen(zid) {
  const feld = document.querySelector(`[data-zaehler-umbenennen="${zid}"]`);
  const halter = feld?.closest('.zu-name');
  if (!halter || halter.querySelector('.zu-name-inp')) return;   // schon offen
  const z = (state.ablesungMaske?.zaehler || []).find(x => String(x.id) === String(zid));
  const alt = z?.name || halter.textContent.trim();
  const vorher = halter.innerHTML;

  halter.innerHTML = `<input class="zu-name-inp" type="text" value="${esc(alt)}"
    aria-label="Name des Zählers" maxlength="80">`;
  const inp = halter.querySelector('.zu-name-inp');
  inp.focus();
  inp.select();

  let fertig = false;
  const zurueck = () => { if (!fertig) { fertig = true; halter.innerHTML = vorher; } };

  const speichern = async () => {
    if (fertig) return;
    const name = inp.value.trim();
    if (!name || name === alt) return zurueck();
    fertig = true;
    try {
      await api(`/zaehler/${zid}`, { method: 'PATCH', body: { name } });
      if (z) z.name = name;
      melde('Zähler umbenannt', 'pos');
      const { laden } = await import('./checkliste.js');
      await laden();
    } catch (fehler) {
      melde(String(fehler.message || fehler), 'neg');
      halter.innerHTML = vorher;
    }
  };

  inp.addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); speichern(); }
    if (e.key === 'Escape') { e.preventDefault(); zurueck(); }
  });
  inp.addEventListener('blur', speichern);
  inp.addEventListener('click', e => e.stopPropagation());
}

/* Eine Zähler-Zeile: Anfang + Ende mit Stand UND eigenem Ablesedatum. */
export function meterZeileHtml(z, { rest = false, minus = false, label = null,
                                    keinChooser = false, extra = '', verbText = '' } = {}) {
  const bearbeitbar = state.daten.status === 'in Arbeit';
  const eh = esc(z.messeinheit || 'm³');
  // N120 — `direkt`: fertiger Wert der Periode.
  const direkt = !rest && z.typ === 'direkt';
  // N157 — Ladestation: Jahreswert wird gezogen.
  const eauto = !rest && !!z.eauto;
  const fertig = z.verbrauch != null
    && (rest || direkt || (z.vorwert != null && z.ablesung != null));
  const startStand = z.vorwert ? zahl(z.vorwert.stand) : '';
  const endStand = z.ablesung ? zahl(z.ablesung.stand) : '';
  const anfangDatum = z.vorwert?.datum
    || state.ablesungMaske?.zeitraum?.start || state.daten.start || '';
  const endeDatum = z.ablesung?.datum
    || state.ablesungMaske?.zeitraum?.ende || state.daten.ende || '';
  const ausVorperiode = !!(z.vorwert && state.ablesungMaske?.vorheriges_ende);

  const feld = (kind, wert, standAttr, datumAttr, datum) => bearbeitbar
    ? `<div class="zu-feld"><label>${kind}</label>
        <div class="zu-paar">
          <input type="text" inputmode="decimal" ${standAttr}="${z.id}"
            value="${wert}" placeholder="Stand" aria-label="${kind}sstand ${esc(z.name)}">
          <input type="date" ${datumAttr}="${z.id}" value="${datum}"
            aria-label="Ablesedatum ${kind} ${esc(z.name)}">
        </div></div>`
    : `<div class="zu-feld"><label>${kind}</label>
        <div class="zu-paar"><span class="zu-anf">${wert ? `${wert}&nbsp;${eh}` : '—'}</span>
          <span class="zu-dat">${_isoKurz(datum)}</span></div></div>`;

  // N345 — nur Anzeige (Anfang aus der Vorperiode): eine schmale Zeile statt
  // eines vollen Feld-Blocks — der Anfang ist keine Eingabe, er braucht
  // keine Feldhöhe. Spart je Karte rund 50 px auf dem iPhone.
  const nurAnzeige = (kind, wert, datum, note) => `<span class="zu-anfchip"
      title="Endstand der Vorperiode, abgelesen am ${_isoKurz(datum)}">${kind}
      <b>${wert ? `${wert}&nbsp;${eh}` : '—'}</b> · ${note}</span>`;

  // N120 — Jahreswert: ein Feld, kein Datum.
  // N341 — kompakt: ohne eigene Label-Zeile und ohne „kein Zählerstand"-Text,
  // damit Name, Nummer, Stift und Eingabe in EINE Zeile passen. Auf dem
  // iPhone kostete jede Karte sonst über 100 px Höhe, bei 24 Zählern eine
  // endlose Liste.
  const jahresFeld = bearbeitbar
    ? `<input class="zu-jahr" type="text" inputmode="decimal" data-strom-jahr="${z.id}"
        value="${endStand}" placeholder="${eh}"
        aria-label="Jahresverbrauch ${esc(z.name)} in ${eh}">`
    : `<span class="zu-anf">${endStand ? `${endStand}&nbsp;${eh}` : '—'}</span>`;

  const startFeld = (rest || direkt) ? ''
    : (ausVorperiode
      ? nurAnzeige('Anfang', startStand, anfangDatum, 'aus Vorperiode')
      : feld('Anfang', startStand, 'data-anfangstand', 'data-anfangdatum', anfangDatum));
  const endFeld = (rest || eauto) ? ''
    : (direkt ? jahresFeld
      : feld('Ende', endStand, 'data-endstand', 'data-enddatum', endeDatum));

  const hinweise = (rest || direkt) ? [] : interpolationsHinweise(z, eh);
  const rechnung = hinweise.length
    ? `<div class="zu-rechnung">${hinweise.map(s => `<span class="zu-rz">${s}</span>`)
        .join('')}</div>` : '';
  const datumKnopf = bearbeitbar && !rest && !direkt
    ? `<button type="button" class="zu-dok" data-datum-uebernehmen="${z.id}"
        hidden>Geändertes Datum mit dem Stand speichern</button>` : '';

  const verb = verbText
    || (z.verbrauch != null ? `${zahl(z.verbrauch)}&nbsp;${eh}` : '—');
  // N345 — die Verrechnungsweise steht als Zeichen VOR jedem Zähler, ohne
  // dass man etwas aufklappen muss: „−" = wird vom Hauptzähler abgezogen,
  // „=" = errechneter Rest, „+" = zählt eigenständig. Dieselbe Sprache wie
  // im Zähler-Konfigurator.
  const zeichen = rest ? '=' : (minus || z.hauptzaehler_id) ? '−' : '+';
  return `<div class="zu-zeile${fertig && !verbText ? ' fertig' : ''}${
      minus ? ' minus' : ''}${rest ? ' rest' : ''}${
      direkt ? ' knapp' : ''}${
      verbText ? ' unplausibel' : ''}" data-zid="${z.id}">
    <div class="zu-haupt">
      <span class="zu-name"><span class="zu-op vz-${
        rest ? 'gleich' : zeichen === '−' ? 'minus' : 'plus'}"
        aria-hidden="true">${zeichen}</span><span class="zu-nametxt">${
        esc(label || state.zLabels.get(z.id) || z.name)}</span>${
        z.zaehlernummer ? `<span class="zu-nr">Nr. ${esc(z.zaehlernummer)}</span>` : ''}${
        bearbeitbar ? `<button class="zu-um" data-zaehler-umbenennen="${z.id}"
          title="Zähler umbenennen" aria-label="Zähler „${esc(z.name)}“ umbenennen"
          >${STIFT_ICON}</button>` : ''}</span>
      ${startFeld}${endFeld}
      ${direkt ? '' : `<span class="zu-verb">${rest ? '<small>berechnet</small> '
        : (eauto ? '<small>gezogen</small> ' : '')}${verb}</span>`}
    </div>
    ${rechnung}${datumKnopf}
    ${eauto ? eautoInfoHtml()
      : ((keinChooser || istHauptzaehler(z)) ? nurEinheitenHtml(z)
                                             : einheitChooserHtml(z))}${extra}
    ${verlaufHtml(z)}
  </div>`;
}

/* N340y — der Verlauf am Kärtchen, wie im Wärme-Simulator: letzter Stand je
   Jahr, damit man beim Eingeben einordnen kann, ob der aktuelle Wert hoch
   oder niedrig ist. Nur die letzten fünf Jahre — mehr wäre nur Rauschen
   (dieselbe Grenze wie im Simulator). Gehört bewusst NUR hierhin, in die
   Ablese-Eingabe — im Zähler-Konfigurator (Zuordnung/Benennung) lenkt er nur
   ab, da geht es nicht um den Wert, sondern um die Einheit. */
function verlaufHtml(z) {
  const eintraege = Object.entries(z.verlauf || {}).map(([j, w]) => [Number(j), w])
    .sort((a, b) => a[0] - b[0]).slice(-5);
  if (!eintraege.length) return '';
  const hoch = Math.max(...eintraege.map(([, w]) => w), 1);
  return `<span class="zu-verlauf" role="img"
      aria-label="Verlauf ${eintraege.map(([j, w]) => `${j}: ${w}`).join(', ')}">
    ${eintraege.map(([j, w]) => `<span class="zu-vj">
        <i style="height:${Math.max(2, Math.round(w / hoch * 22))}px"></i><b>${zahl(w)}</b>
        <em>'${String(j).slice(2)}</em></span>`).join('')}
  </span>`;
}

/* Die Kaltwasser-Struktur (Hauptzähler + Unterzähler + Rest). */
export function kaltwasserStruktur(liste) {
  const istWarm = z => wasserArt(z) === 'Warmwasser'
    || (z.name || '').toLowerCase().includes('warmwasser');
  const hauptIds = new Set(liste.filter(z => z.hauptzaehler_id).map(z => z.hauptzaehler_id));
  const kandidaten = liste.filter(z => hauptIds.has(z.id) && z.typ !== 'rest' && !istWarm(z));
  const nameLower = z => (z.name || '').toLowerCase();
  const haupt = kandidaten.find(z => nameLower(z).includes('kaltwasser')
      || nameLower(z).includes('gesamt'))
    || kandidaten[0]
    || liste.find(z => nameLower(z).includes('gesamt') && !istWarm(z));
  if (!haupt) return null;
  const subs = liste.filter(z => z.id !== haupt.id && z.typ !== 'rest'
    && z.hauptzaehler_id === haupt.id);
  const rest = liste.find(z => z.typ === 'rest' && z.hauptzaehler_id === haupt.id)
    || liste.find(z => z.typ === 'rest' && !istWarm(z));
  if (!subs.length && !rest) return null;
  return { haupt, subs, rest };
}

/* N59 — der Kaltwasser-Block mit Abzugskette und Rest Haupthaus. */
export function kaltwasserBlockHtml(s) {
  const sortiert = [...s.subs].sort((a, b) =>
    (wasserArt(a) === 'Waschmaschine' ? 1 : 0) - (wasserArt(b) === 'Waschmaschine' ? 1 : 0));
  const subZeilen = sortiert.map(z => meterZeileHtml(z, { minus: true })).join('');
  const restZeile = s.rest ? meterZeileHtml(s.rest, { rest: true, label: 'Rest Haupthaus' }) : '';
  return `<div class="zu-art zu-kalt"><div class="zu-at">Kaltwasser</div>
    ${meterZeileHtml(s.haupt, { keinChooser: true })}
    <div class="zu-kalt-abzug">${subZeilen || `<div class="zu-kein">Noch keine
      Unterzähler zugeordnet.</div>`}${restZeile}</div>
  </div>`;
}

/* Der Wasser-Block: Kaltwasser zuerst, dann Warm/Waschmaschinen/Garten/Rest. */
export function wasserBlockHtml(liste) {
  const teile = [];
  const verbraucht = new Set();
  const s = kaltwasserStruktur(liste);
  if (s) {
    for (const z of [s.haupt, ...s.subs, s.rest]) if (z) verbraucht.add(z.id);
    teile.push(kaltwasserBlockHtml(s));
  }
  const rest = liste.filter(z => !verbraucht.has(z.id));
  const nachArt = [['Warmwasser', 'Warmwasser'], ['Waschmaschine', 'Waschmaschinen'],
    ['Gartenwasser', 'Gartenwasser']];
  for (const [art, titel] of nachArt) {
    const grp = rest.filter(z => wasserArt(z) === art);
    // N94 — Gartenwasser oft ohne Zähler: manuelle Zeile.
    if (art === 'Gartenwasser' && !grp.length) {
      if (state.daten.status !== 'in Arbeit') continue;
      teile.push(`<div class="zu-art"><div class="zu-at">Gartenwasser</div>
        <div class="zu-kein">Ohne Zähler — die verbrauchten m³ hier eintragen.
          Sie werden vom Rest Haupthaus abgezogen und nur mit dem
          Frischwasser-Anteil berechnet.</div>
        <div class="ho-neu">
          <input type="number" step="0.1" data-garten-m3 placeholder="m³"
            aria-label="Gartenwasser in m³">
          <button class="btn" data-garten-anlegen>Gartenwasser eintragen</button>
        </div></div>`);
      continue;
    }
    if (grp.length) teile.push(`<div class="zu-art"><div class="zu-at">${esc(titel)}</div>
      ${grp.map(z => meterZeileHtml(z, { rest: z.typ === 'rest' })).join('')}</div>`);
  }
  const uebrig = rest.filter(z =>
    !['Warmwasser', 'Waschmaschine', 'Gartenwasser'].includes(wasserArt(z)));
  if (uebrig.length) teile.push(`<div class="zu-art"><div class="zu-at">Weitere</div>
    ${uebrig.map(z => meterZeileHtml(z, { rest: z.typ === 'rest' })).join('')}</div>`);
  return teile.join('');
}

/* N347 — die Verrechnung des Blocks in ein, zwei Sätzen, dynamisch aus der
   tatsächlichen Struktur — kein gepflegter Text, der veralten könnte. */
function verrechnungsSatz(teil) {
  const haupt = teil.filter(z => teil.some(m => m.hauptzaehler_id === z.id));
  const rest = teil.filter(z => z.typ === 'rest');
  const unter = teil.filter(z => z.hauptzaehler_id && z.typ !== 'rest');
  const solo = teil.filter(z => !z.hauptzaehler_id && z.typ !== 'rest'
    && !haupt.includes(z));
  const garten = teil.filter(z => wasserArt(z) === 'Gartenwasser');
  const saetze = [];
  const unterTxt = unter.length === 1
    ? 'wird der Unterzähler (−)' : `werden die ${unter.length} Unterzähler (−)`;
  if (haupt.length && rest.length) {
    saetze.push(`Vom Gesamtzähler <b>${esc(haupt[0].name)}</b> ${unterTxt}
      abgezogen; <b>${esc(rest[0].name)}</b> (=) ist der errechnete Rest für
      alle ohne eigenen Zähler.`);
  } else if (haupt.length) {
    saetze.push(`Vom Gesamtzähler <b>${esc(haupt[0].name)}</b> ${unterTxt}
      abgezogen.`);
  }
  if (garten.length) {
    saetze.push(`<b>${esc(garten[0].name)}</b> wird vorab herausgenommen
      (kein Abwasser).`);
  }
  const eigen = solo.length - garten.length;
  if (solo.length && !haupt.length) {
    saetze.push(`Jeder Zähler zählt eigenständig (+) auf die Einheiten,
      denen er zugeordnet ist.`);
  } else if (eigen === 1) {
    saetze.push(`Einer zählt eigenständig (+).`);
  } else if (eigen > 1) {
    saetze.push(`${eigen} weitere zählen eigenständig (+).`);
  }
  return saetze.length ? `<p class="zu-erkl">${saetze.join(' ')}</p>` : '';
}

/* N67/N342 — Zählerstände-Panel EINER Kategorie als Einklapper. Bei
   `block==='Heizung'` optional weiter nach `unter` (Heizöl/Warmwasser/
   Heizkörper & Wärmemenge, siehe `heizBereich`) einschränken — sonst lag
   der Heizöl-Zähler in derselben Liste wie 21 Heizkörperzähler und ein
   Warmwassermengenzähler, alle unter „Heizöl & Lieferungen" eingehängt. */
export function zaehlerPanelHtml(block, zaehler, blockVon, unter = null) {
  const teil = zaehler.filter(z => blockVon.get(z.id) === block
    && (!unter || heizBereich(z) === unter));
  // N120 — Strom-Bereich zeigt sich auch ohne Zähler (Leerzustand + Anlegen).
  const stromLeer = block === 'Strom' && state.daten.status === 'in Arbeit';
  if (!teil.length && !stromLeer) return '';
  const basisOhneChooser = block === 'Heizung';
  const inner = block === 'Wasser' ? wasserBlockHtml(teil)
    : block === 'Strom' ? stromBlockHtml(teil)
    : teil.map(z => meterZeileHtml(z, {
        rest: z.typ === 'rest',
        keinChooser: basisOhneChooser && !z.hauptzaehler_id })).join('');
  const schluessel = unter ? `${block}:${unter}` : block;
  const offen = state.zaehlerOffen.has(schluessel);
  const abweichend = teil.filter(z => interpolationsHinweise(z, '').length).length;
  return `<div class="zu-panel${offen ? ' offen' : ''}" data-zu-block="${esc(schluessel)}">
    <button type="button" class="zu-sum" data-zu-toggle aria-expanded="${offen}">
      <span class="zu-ikon">${ZAEHLER_ICON}</span>
      <span class="zu-st">Zählerstände${unter ? ` · ${esc(unter)}` : ''}</span>
      <span class="zu-meta">${teil.length
        ? `${teil.length} Zähler${abweichend ? ` · ${abweichend} umgerechnet` : ''}`
        : 'noch keine'}</span>
      <span class="zu-chev">${CHEV_ICON}</span>
    </button>
    <div class="zu-inhalt">${verrechnungsSatz(teil)}${inner}</div>
  </div>`;
}

/* ---------- Aktionen an der Meter-Zeile -------------------------------- */

/* N47/N60 — Endstand eines Zählers aus der Übersicht speichern. */
export async function endstandSpeichern(input) {
  const id = input.dataset.endstand;
  const stand = standAusFeld(input);
  if (stand === null) return;
  if (Number.isNaN(stand)) { melde('Ungültiger Zählerstand', 'neg'); return; }
  const datumEl = zeilenBox(input)?.querySelector('[data-enddatum]');
  const datum = datumEl?.value || state.ablesungMaske?.zeitraum?.ende || state.daten.ende;
  try {
    await api(`/zaehler/${id}/ablesungen`,
      { method: 'POST', body: { stand, datum, zeitraum_id: Number(state.zid) } });
    state.setAblesungMaske(await api(`/zeitraeume/${state.zid}/ablesung`));
    state.setChipMap(baueChipMap());
    melde('Zählerstand gespeichert', 'pos');
    const { zeichnen } = await import('./checkliste.js');
    await zeichnen();
  } catch (fehler) {
    melde(fehler.message || 'Speichern fehlgeschlagen', 'neg');
  }
}

/* N60 — Anfangsstand eines Zählers aus der Übersicht speichern. */
export async function anfangstandSpeichern(input) {
  const id = input.dataset.anfangstand;
  const stand = standAusFeld(input);
  if (stand === null) return;
  if (Number.isNaN(stand)) { melde('Ungültiger Anfangsstand', 'neg'); return; }
  const datumEl = zeilenBox(input)?.querySelector('[data-anfangdatum]');
  const datum = datumEl?.value || state.ablesungMaske?.zeitraum?.start || state.daten.start;
  try {
    // N96 — Anfangsstand hängt an KEINEM Zeitraum.
    await api(`/zaehler/${id}/anfangsstand`, { method: 'POST', body: { stand, datum } });
    state.setAblesungMaske(await api(`/zeitraeume/${state.zid}/ablesung`));
    state.setChipMap(baueChipMap());
    melde('Anfangsstand gespeichert', 'pos');
    const { zeichnen } = await import('./checkliste.js');
    await zeichnen();
  } catch (fehler) {
    melde(fehler.message || 'Speichern fehlgeschlagen', 'neg');
  }
}

/* N88 — ein von Hand geändertes Ablesedatum vormerken (oder direkt speichern). */
/* N353 — ein `<input type=date>` feuert `change` schon, sobald die halb
   getippte Jahreszahl ein gültiges Datum ergibt: aus „30.09.2___" wird
   zwischendurch der 30.09.0002. Sofort zu speichern riss den Fokus aus dem
   Feld und schrieb einen Stand auf ein Jahr, das der Nutzer nie gemeint hat
   (beobachtet: ein Balken auf '26 und −0,005 m³ Verbrauch). Deshalb wird ein
   offensichtlich unfertiges Jahr nicht gespeichert — und ein plausibles erst
   nach kurzer Ruhe, damit das Tippen nicht mitten im Jahr abbricht. */
const DATUM_WARTEN = new WeakMap();

function jahrPlausibel(wert) {
  const jahr = Number(String(wert || '').slice(0, 4));
  return Number.isFinite(jahr) && jahr >= 1990 && jahr <= 2100;
}

export function datumGeaendert(el) {
  el.classList.add('geaendert');
  const zeile = zeilenBox(el);
  const ende = el.matches('[data-enddatum]');
  const standEl = zeile?.querySelector(ende ? '[data-endstand]' : '[data-anfangstand]');
  const knopf = zeile?.querySelector('[data-datum-uebernehmen]');

  clearTimeout(DATUM_WARTEN.get(el));
  // Unfertige Jahreszahl (0002, 20, 202…): nichts speichern, nichts anbieten —
  // der Nutzer tippt noch.
  if (el.value && !jahrPlausibel(el.value)) return;

  const speichern = () => {
    if (el.value && standEl && standAusFeld(standEl) != null
        && !Number.isNaN(standAusFeld(standEl))) {
      return ende ? endstandSpeichern(standEl) : anfangstandSpeichern(standEl);
    }
    if (knopf) knopf.hidden = false;
  };
  // Der Kalender-Picker setzt den Wert in einem Rutsch — dort darf es sofort
  // gehen; getippt wird er zeichenweise, deshalb die kurze Ruhe.
  DATUM_WARTEN.set(el, setTimeout(speichern, 700));
}

/* N88 — das geänderte Datum zusammen mit dem Stand dieser Zeile speichern. */
export async function datumUebernehmen(knopf) {
  const zeile = zeilenBox(knopf);
  const datumEl = zeile?.querySelector('input[type=date].geaendert');
  const ende = datumEl?.matches('[data-enddatum]');
  const standEl = zeile?.querySelector(ende ? '[data-endstand]' : '[data-anfangstand]');
  if (!standEl || standAusFeld(standEl) === null) {
    melde('Erst den Zählerstand eintragen — das Datum gehört zu einem Stand', 'neg');
    return;
  }
  return ende ? endstandSpeichern(standEl) : anfangstandSpeichern(standEl);
}

/* N58 — die Einheiten-Zuordnung eines Zählers umschalten und sofort speichern. */
export async function einheitToggle(btn) {
  const id = Number(btn.dataset.einheitToggle);
  const einheit = btn.dataset.einheit;
  const z = (state.ablesungMaske?.zaehler || []).find(m => m.id === id);
  if (!z) return;
  const set = new Set(zaehlerEinheiten(z));
  if (set.has(einheit)) set.delete(einheit); else set.add(einheit);
  const neu = [...set];
  z.einheiten = neu;                                   // lokal nachziehen
  const an = set.has(einheit);
  btn.classList.toggle('an', an);
  btn.setAttribute('aria-pressed', String(an));
  try {
    await api(`/zaehler/${id}`, { method: 'PATCH', body: { einheiten: neu } });
  } catch (fehler) {
    melde(fehler.message || 'Zuordnung nicht gespeichert', 'neg');
  }
}
