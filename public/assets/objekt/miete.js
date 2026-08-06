/* N216 — Mieten-Rubrik: Timeline über die Mietverhältnisse einer Einheit
   (bzw. Ohne-Einheit-Sammlung am Haus), farbige Zeilen, Leerstände als
   eigene Zeilen, und die einheitliche `abschnitt()`-Fabrik, die aus einer
   Bereichs-Liste einen Titel + Timeline + Liste macht. */

import { esc, eur } from '../immo.js';
import { kostenIcon } from '../kostenicons.js';
import { cfgFuer, ERWERB_KATEGORIE } from '../objekt-felder.js?v=2';
import { sekopfHtml } from '../objekt-format.js?v=2';
import { isoTag, heuteIso, tagPlus, dauerText, mietFarbe } from './helpers.js';
import { ENTWURF_TYP, RUBRIKFARBE } from './state.js';

/* ---- Modell + Timeline (N19) -------------------------------------------- */

export function mietModell(eintraege) {
  const heute = heuteIso();
  const roh = (eintraege || []).filter(m => m && m.ab_datum && m.vorlaeufig !== true);
  if (!roh.length) return null;
  const mieten = roh.map(m => ({ ...m })).sort((a, b) => a.ab_datum.localeCompare(b.ab_datum));
  const ende = m => m.bis_datum || heute;
  mieten.forEach((m, i) => {
    m.farbe = mietFarbe(i);
    m.laufend = !m.bis_datum && !m.geplant;
    m.dauer = dauerText(m.ab_datum, ende(m));
  });
  const minIso = mieten[0].ab_datum;
  const maxIso = mieten.reduce((a, m) => ende(m) > a ? ende(m) : a, ende(mieten[0]));
  const t0 = Date.parse(`${minIso}T00:00:00Z`);
  const spanne = Math.max(1, Date.parse(`${maxIso}T00:00:00Z`) - t0);
  const pct = iso => Math.min(100, Math.max(0,
    (Date.parse(`${iso}T00:00:00Z`) - t0) / spanne * 100));
  // Leerstände: chronologisch durchlaufen, jede Lücke zur bisherigen Deckung.
  const leerstaende = [];
  let deckung = minIso;
  for (const m of mieten) {
    if (m.ab_datum > deckung) {
      const von = tagPlus(deckung, 1), bis = tagPlus(m.ab_datum, -1);
      if (bis >= von) leerstaende.push({ von, bis, ab: deckung, endeIso: m.ab_datum,
        dauer: dauerText(deckung, m.ab_datum) });
    }
    if (ende(m) > deckung) deckung = ende(m);
  }
  const jahre = [];
  for (let j = Number(minIso.slice(0, 4)); j <= Number(maxIso.slice(0, 4)); j++) jahre.push(j);
  return { mieten, leerstaende, pct, minIso, maxIso, heute, jahre };
}

export function mietTimelineHtml(mo, mini = false) {
  const seg = (l, w, farbe, titel, leer) =>
    `<span class="tl-seg${leer ? ' leer' : ''}" title="${esc(titel)}"
       style="left:${l}%;width:${w}%;${leer ? '' : `background:${farbe}`}"></span>`;
  const balken = mo.mieten.map(m => {
    const l = mo.pct(m.ab_datum), r = mo.pct(m.bis_datum || mo.heute);
    return seg(l, Math.max(2, r - l), m.farbe,
      `${m.partei}: ${isoTag(m.ab_datum)} – ${m.bis_datum ? isoTag(m.bis_datum) : 'heute'} · ${m.dauer}`);
  }).join('');
  const leer = mo.leerstaende.map(x => {
    const l = mo.pct(x.ab), r = mo.pct(x.endeIso);
    return seg(l, Math.max(1.5, r - l), '',
      `Leerstand: ${isoTag(x.von)} – ${isoTag(x.bis)} · ${x.dauer}`, true);
  }).join('');
  // N39 — Jahres-Achse ausdünnen: bei langer Historie (17 Jahre bei „seit 17
  // Jahren") kleben sonst alle Jahreszahlen zu „200920102011…" zusammen. Wir
  // wählen einen runden Schritt (1/2/5/10 …), sodass höchstens ~5 (mini) bzw.
  // ~8 (voll) Marken bleiben, und beschriften nur Jahre, die durch ihn teilbar
  // sind — die Balken decken weiterhin die volle Spanne ab.
  const maxMarken = mini ? 5 : 8;
  const roh = Math.ceil(mo.jahre.length / maxMarken);
  const schritt = [1, 2, 5, 10, 20, 25, 50].find(s => s >= roh)
    || Math.ceil(roh / 50) * 50;
  const ticks = mo.jahre.filter(j => j % schritt === 0).map(j =>
    `<span class="tl-tick" style="left:${mo.pct(`${j}-01-01`)}%">${j}</span>`).join('');
  return `<div class="miet-timeline${mini ? ' mini' : ''}">
      <div class="tl-track">${leer}${balken}</div>
      <div class="tl-achse">${ticks}</div>
    </div>`;
}

/* ---- Listenzeilen ------------------------------------------------------- */

/* Die schlichte Listenzeile — der gemeinsame Kern von normaler und
   vorläufiger Darstellung. */
export function eintragZeile(cfg, bereich, e, imFokus, { mitDel = true } = {}) {
  const marke = cfg.chip ? cfg.chip(e) : null;
  const beschreibung = cfg.detail(e, imFokus);
  return `<div class="eintrag klick" data-edit="${bereich}:${e.id}"
      ${cfg.matt && cfg.matt(e) ? 'style="opacity:.62"' : ''}>
    <span class="sym">${kostenIcon(cfg.ikon)}</span>
    <span class="et">
      <span class="en">${esc(cfg.name(e))}${marke
        ? ` <span class="chip ${marke[0]}">${esc(marke[1])}</span>` : ''}</span>
      ${beschreibung ? `<span class="ed">${esc(beschreibung)}</span>` : ''}
    </span>
    <span class="ew">${cfg.wert(e)}</span>
    ${mitDel
      ? `<button class="del" data-del="${bereich}:${e.id}" aria-label="löschen">×</button>`
      : ''}
  </div>`;
}

/* Ein vorläufiger Datensatz: derselbe Kern, aber in Amber gerahmt und mit
   Fußleiste — „Entwurf aus Beleg", optional der Belegblick, und die zwei
   Entscheidungen Bestätigen / Zurück zum Prüfen. */
export function entwurfZeile(cfg, bereich, e, imFokus) {
  const typ = ENTWURF_TYP[bereich];
  const beleg = e.quelle_dokument_id
    ? `<button class="beleg" data-beleg="${e.quelle_dokument_id}">aus Beleg</button>`
    : '';
  return `<div class="entwurf">
    ${eintragZeile(cfg, bereich, e, imFokus, { mitDel: false })}
    <div class="entfuss">
      <span class="marke"><span class="pt"></span>Entwurf aus Beleg</span>
      ${beleg}
      <span class="luecke"></span>
      <button class="ea ok" data-ok="${typ}:${e.id}">✓ Bestätigen</button>
      <button class="ea zurueck" data-zurueck="${typ}:${e.id}">↩ Zurück zum Prüfen</button>
    </div>
  </div>`;
}

/* CCCXII — Wiederkehrendes staffeln statt stapeln: zehn Grundsteuerbescheide
   sind zehn Jahre derselben Sache, nicht zehn Sachen. Sie stehen deshalb als
   EINE Zeile mit einer Jahresstaffel darunter; jedes Jahr bleibt einzeln
   anklickbar. Entwürfe (orange) bleiben eigenständig — sie wollen erst
   bestätigt werden. */
export function staffelHtml(cfg, bereich, art, gruppe) {
  const nachJahr = [...gruppe].sort((a, b) => (b.jahr || 0) - (a.jahr || 0));
  const neuestes = nachJahr[0];
  const jahre = nachJahr.map(e => `
    <button class="stjahr" data-edit="${bereich}:${e.id}"
            title="${esc(cfg.name(e))} ${e.jahr || ''} öffnen">
      <span class="sj">${e.jahr || '—'}</span>
      <span class="sb">${eur(e.betrag || 0)}</span></button>`).join('');
  return `<div class="eintrag staffel">
      <span class="sym">${kostenIcon(art)}</span>
      <span class="et">
        <span class="en">${esc(art)}
          <span class="stz">${gruppe.length} Jahre</span></span>
        <span class="ed">zuletzt ${neuestes.jahr || '—'} · ${
          esc(cfg.detail ? cfg.detail(neuestes) : '')}</span>
        <span class="staffel-jahre">${jahre}</span>
      </span>
      <span class="ew">${cfg.wert ? cfg.wert(neuestes) : eur(neuestes.betrag || 0)}</span>
    </div>`;
}

/* Miet-Zeile: farbiger Punkt statt Symbol, Dauer als „seit X" oder „X gesamt". */
function mietZeile(cfg, e, imFokus) {
  const besch = cfg.detail(e, imFokus);
  const dauer = e.dauer ? (e.laufend ? `seit ${e.dauer}` : `${e.dauer} gesamt`) : '';
  return `<div class="eintrag klick" data-edit="mieten:${e.id}">
      <span class="miet-dot" style="background:${e.farbe}"></span>
      <span class="et">
        <span class="en">${esc(e.partei || cfg.name(e))}</span>
        <span class="ed">${esc(besch)}${dauer ? ` · ${esc(dauer)}` : ''}</span>
      </span>
      <span class="ew">${cfg.wert(e)}</span>
      <button class="del" data-del="mieten:${e.id}" aria-label="löschen">×</button>
    </div>`;
}

function leerstandZeile(x) {
  return `<div class="eintrag leerstand">
      <span class="miet-dot leer"></span>
      <span class="et">
        <span class="en">Leerstand</span>
        <span class="ed">${isoTag(x.von)} – ${isoTag(x.bis)} · ${x.dauer}</span>
      </span>
      <span class="ew">—</span>
    </div>`;
}

/* ---- Ein Rubrik-Abschnitt (Kopf + Timeline + Liste) --------------------- */

export function abschnitt(bereich, eintraege, { imFokus = false, kopf = '',
                                                vorspann = '' } = {}) {
  const cfg = cfgFuer(bereich);
  const istEntwurf = e => e && e.vorlaeufig === true && ENTWURF_TYP[bereich];
  let zeilen;
  let timelineHtml = '';
  if (!eintraege.length) {
    zeilen = `<div class="leerzeile">Noch nichts erfasst</div>`;
  } else if (bereich === 'mieten') {
    // N19 — Timeline + farbige Zeilen + erkannte Leerstände als eigene Zeilen.
    const mo = mietModell(eintraege);
    if (mo) {
      timelineHtml = mietTimelineHtml(mo);
      const gemischt = [
        ...mo.mieten.map(m => ({ t: m.ab_datum, html: mietZeile(cfg, m, imFokus) })),
        ...mo.leerstaende.map(x => ({ t: x.von, html: leerstandZeile(x) })),
      ].sort((a, b) => a.t.localeCompare(b.t));       // chronologisch …
      const entwuerfe = eintraege.filter(istEntwurf)
        .map(e => entwurfZeile(cfg, bereich, e, imFokus)).join('');
      zeilen = entwuerfe + gemischt.reverse().map(x => x.html).join('');  // … neueste oben
    } else {
      zeilen = eintraege.map(e => istEntwurf(e)
        ? entwurfZeile(cfg, bereich, e, imFokus)
        : eintragZeile(cfg, bereich, e, imFokus)).join('');
    }
  } else if (bereich === 'zahlungen') {
    // Nach Art gruppieren; nur was mehrfach vorkommt, wird gestaffelt.
    const gruppen = new Map();
    const einzeln = [];
    for (const e of eintraege) {
      if (istEntwurf(e)) { einzeln.push(e); continue; }
      const art = (e.art || 'Zahlung').trim();
      if (!gruppen.has(art)) gruppen.set(art, []);
      gruppen.get(art).push(e);
    }
    const teile = [];
    for (const [art, gruppe] of gruppen) {
      teile.push(gruppe.length > 1
        ? staffelHtml(cfg, bereich, art, gruppe)
        : eintragZeile(cfg, bereich, gruppe[0], imFokus));
    }
    for (const e of einzeln) teile.push(entwurfZeile(cfg, bereich, e, imFokus));
    zeilen = teile.join('');
  } else {
    zeilen = eintraege.map(e => istEntwurf(e)
      ? entwurfZeile(cfg, bereich, e, imFokus)
      : eintragZeile(cfg, bereich, e, imFokus)).join('');
  }

  // N3 — Mietverhältnisse (auch Vormietverhältnisse) lassen sich JEDERZEIT
  // hinzufügen; ein laufendes muss dafür nicht beendet werden. Rücknahme der
  // CCCLXXXIX-Sperre — der „＋" oben rechts im Titel bleibt immer aktiv (CCCXC).
  // N22 — der „hinzufügen"-Zugang ist ein Textlink im selben Stil wie
  // „Anlegen"/„Bearbeiten" der übrigen Rubriken, kein eigener „＋"-Kasten.
  const kopfAdd = `<button class="seakt" data-add="${bereich}"
       aria-label="${esc(cfg.einzahl)} hinzufügen"
       title="${esc(cfg.einzahl)} hinzufügen">Hinzufügen</button>`;
  return `${sekopfHtml(kopf || cfg.titel, cfg.ikon, kopfAdd, RUBRIKFARBE[bereich])}
    ${timelineHtml}${vorspann}
    <div class="liste">${zeilen}</div>`;
}
