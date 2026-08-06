/* N216 — die Einheiten-Liste am Haus und der Stammdaten-Block einer einzelnen
   Einheit im Fokus. Enthält auch die Objekt-Summen (Monat/Jahr) und den
   Vermietet-Stempel. Bringt selbst keine Handler mit — die klickbaren Zeilen
   tragen data-Attribute, die zentral in handlers.js abgefangen werden. */

import { esc, eur, eurVoll } from '../immo.js';
import { kostenIcon } from '../kostenicons.js';
import { proJahr, flaecheText, paarZeile, stammwert, feldLeer } from '../objekt-format.js?v=2';
import { EINHEITFELDER, istEinheitswert } from '../objekt-felder.js?v=2';
import { objekt, istGrundstueck } from '../objekt-state.js?v=2';
import { einheiten, bereicheDaten } from './state.js';
import { effektiveFlaeche, qmMiete, hergeleiteteKaltmiete, laufendeMiete,
         mietzeitBeginn, heuteIso, dauerText, zuEinheit } from './helpers.js';
import { mietModell, mietTimelineHtml } from './miete.js';
import { lageplanHtml } from './lageplan.js';

export function einheitDetail(e) {
  const flaeche = effektiveFlaeche(e);
  return [e.nutzungsart,
          flaeche ? flaecheText(flaeche) : '',
          e.stellplaetze ? (e.stellplaetze > 1 ? `${e.stellplaetze} Stellplätze`
                                               : '1 Stellplatz') : '',
          e.mieter].filter(Boolean).join(' · ');
}

/* N31 — angeschrägter Gummistempel „VERMIETET": zwei gerundete Rahmen und der
   Schriftzug, leicht gedreht und transparent im Pos-Grün. Reines Inline-SVG. */
export function vermietetStempel() {
  // N36 — die viewBox muss die -7°-Drehung fassen (gedrehte Höhe ~47 statt 32),
  // sonst ragen die Rahmen-Ecken aus dem Kasten und der Text darunter überlappt.
  return `<svg class="stempel-svg" viewBox="0 0 134 52" width="116" height="45"
       role="img" aria-label="Vermietet">
      <g transform="rotate(-7 67 26)" fill="none" style="stroke:var(--pos)">
        <rect x="4" y="10" width="126" height="32" rx="7" style="stroke-width:2.2"/>
        <rect x="8.5" y="14.5" width="117" height="23" rx="4.5" style="stroke-width:1"/>
        <text x="67" y="31" text-anchor="middle"
          style="fill:var(--pos);stroke:none;font:800 14px var(--disp);letter-spacing:1.4px">VERMIETET</text>
      </g>
    </svg>`;
}

/* N33 — kompakte Vermietungs-Timeline EINER Einheit (Balken + Leerstand-Lücken),
   dieselbe Sprache wie N19, nur schlanker. Ohne Mietverhältnisse: nichts. */
export function miniMietTimelineHtml(eintraege) {
  const mo = mietModell(eintraege);
  if (!mo) return '';
  return `<div class="einheit-tl">${mietTimelineHtml(mo, true)}</div>`;
}

/* N32 — die vier Objekt-Kennzahlen rechts neben dem Diagramm: Miete/Monat und
   NK/Monat (Summe der laufenden Verhältnisse, jeder Turnus auf Monat normiert),
   daraus Ertrag/Jahr und NK-Pauschale/Jahr. */
export function objektSummenHtml() {
  let mMonat = 0, nkMonat = 0;
  for (const e of einheiten) {
    const lm = laufendeMiete(e);
    if (!lm) continue;
    const f = proJahr(lm.turnus) / 12;   // Turnus → Monatsbetrag
    mMonat += (lm.kaltmiete || 0) * f;
    nkMonat += (lm.nebenkosten_vz || 0) * f;
  }
  const zeile = (l, w) =>
    `<div class="os-zeile"><span class="os-l">${l}</span><span class="os-w">${eur(w)}</span></div>`;
  return `<div class="objekt-summen">
      <div class="os-grp monat">
        ${zeile('Miete / Monat', mMonat)}
        ${zeile('Nebenkosten / Monat', nkMonat)}
      </div>
      <div class="os-grp jahr">
        ${zeile('Ertrag / Jahr', mMonat * 12)}
        ${zeile('NK-Pauschale / Jahr', nkMonat * 12)}
      </div>
    </div>`;
}

/* Die Zeile führt eine Ebene tiefer — angetippt wird sie ganz, nicht ein
   Pfeilchen am Rand. N31 setzt den Vermietet-Stempel und die grüne Tönung,
   N33 hängt die Mini-Timeline unter jede Zeile. */
export function einheitenHtml() {
  if (istGrundstueck()) return '';
  const alleMieten = bereicheDaten.mieten || [];
  const zeilen = einheiten.length
    ? einheiten.map(e => {
        const lm = laufendeMiete(e);
        const vermietet = !!(e.vermietet || lm);
        const seit = lm ? dauerText(mietzeitBeginn(e, lm), heuteIso()) : '';
        // N217 — „seit X" wandert IN eine Zeile HINTER den Stempel: kein zweiter
        // Zeilenumbruch mehr, spart ~30 % Karten-Höhe.
        const stempel = vermietet
          ? `<span class="e-stempel">${vermietetStempel()}${seit
              ? ` <span class="e-seit">seit ${esc(seit)}</span>` : ''}</span>`
          : '';
        const detail = einheitDetail(e);
        // Der Trenner „·" gehört IN die ed-seit-Spanne — auf dem Desktop ist die
        // Dauer dort verborgen (sie steht im Stempel), sonst bliebe ein loser „·".
        const seitSpan = seit
          ? `<span class="ed-seit">${detail ? ' · ' : ''}seit ${esc(seit)}</span>` : '';
        const detailZeile = (detail || seit)
          ? `<span class="ed">${esc(detail)}${seitSpan}</span>`
          : '';
        const wert = e.vermietet && e.kaltmiete
          ? `${eur(e.kaltmiete)} / M${qmMiete(e)
              ? `<span class="ew-sub">${eur(qmMiete(e))} / m²</span>` : ''}`
          : '';
        const chips = `${vermietet ? '' : ' <span class="chip amber">frei</span>'}${
          e.nk_abrechnung === false ? ' <span class="chip">nicht in NK</span>' : ''}`;
        const tl = miniMietTimelineHtml(alleMieten.filter(m => zuEinheit(m) === e.bezeichnung));
        return `<div class="einheit-block">
          <div class="eintrag klick${vermietet ? ' vermietet' : ''}" data-einheit="${e.id}">
            <span class="sym">${kostenIcon('Miete')}</span>
            <span class="et">
              <span class="en">${esc(e.bezeichnung)}${chips}</span>
              ${detailZeile}
            </span>
            ${stempel}
            <span class="ewwrap">
              <span class="ew">${wert}</span>
              <button class="del" data-einheit-weg="${e.id}" aria-label="löschen">×</button>
            </span>
          </div>
          ${tl}
        </div>`;
      }).join('')
    : `<div class="leerzeile">Noch keine Einheit erfasst</div>`;

  // N217 — der Erklärtext wandert ins Info-i oben (kein Dauer-Fließtext mehr),
  // „Hinzufügen" wird zum kompakten „+" rechts oben — dem etablierten Muster.
  const info = 'Eine Einheit antippen: dort stehen Mieter, Kontakt und '
    + 'Nebenkosten dieser Wohnung. Alles Übergeordnete — Stammdaten, '
    + 'Eigentümer, Kredite, Versicherungen, Steuer und Ablage — bleibt hier '
    + 'am Haus.';
  return `<div class="sekopf einheiten-kopf">
      <h2 class="sec">Einheiten</h2>
      <button class="einheit-i" type="button" data-info="${esc(info)}"
        aria-label="Info Einheiten" title="Info"><span aria-hidden="true">ⓘ</span></button>
      <button class="plus" data-einheit-neu="1" aria-label="Einheit hinzufügen"
        title="Einheit hinzufügen">＋</button></div>
    <div class="liste">${zeilen}</div>`;
}

/* CCCXXVII/CCCXXIX — die erfassten Zusatz- und Gemeinschaftsflächen als Zeilen,
   gefolgt von der effektiven Gesamtfläche. Ohne erfasste Flächen bleibt es leer,
   dann steht nur die Basis-Wohnfläche wie bisher. */
function flaechenZeilenHtml(e) {
  const num = n => Number(n).toLocaleString('de-DE', { maximumFractionDigits: 2 });
  const nutz = (e.nutzflaechen || []).filter(n => Number(n.flaeche) > 0);
  const gemein = (e.gemeinflaechen || []).filter(g => Number(g.flaeche) > 0);
  if (!nutz.length && !gemein.length) return '';
  let out = '';
  for (const n of nutz) {
    out += paarZeile(n.bezeichnung || 'Zusatzfläche',
      `${num(n.flaeche)} m² · voll`, {});
  }
  for (const g of gemein) {
    const f = Number(g.flaeche) || 0;
    const p = Number(g.personen) || 0;
    const anteil = p > 0 ? f / p : 0;
    out += paarZeile(g.bezeichnung || 'Gemeinschaftsfläche',
      `${num(f)} m² ÷ ${p || '?'} = ${num(anteil)} m²`, {});
  }
  out += paarZeile('Effektive Fläche', `${num(effektiveFlaeche(e))} m²`,
    { abgeleitet: true });
  return out;
}

/* Die Einheit selbst — ohne ihre Bezeichnung: die steht schon in der Kopfzeile. */
export function einheitStammHtml(e) {
  // Der NK-Schalter (CXCIII) ist ein bool — als „true"-Zeile stünde er nur im
  // Weg. Die Teilnahme ist der Normalfall und bleibt still; nur der Ausschluss
  // wird als eigener Hinweis gezeigt.
  // CCCXXIX — direkt unter der Basis-Wohnfläche folgen die Zusatz- und
  // Gemeinschaftsflächen und die effektive Gesamtfläche.
  const flaechen = flaechenZeilenHtml(e);
  // CCCXLII — leere Felder (Verkehrswert, Terrasse, Nebenfläche, Stellplätze=0)
  // erscheinen nicht mehr als „nicht erfasst"-Zeile, sondern werden schlicht
  // weggelassen. Die Flächenaufstellung bleibt an der Wohnfläche hängen.
  const zeilen = EINHEITFELDER
    .filter(f => f.k !== 'bezeichnung' && f.k !== 'nk_abrechnung'
      // CCCLVI — der Einheiten-Verkehrswert erscheint nur im Modus „je Einheit";
      // erfasst man den Wert für das ganze Objekt, entfällt die Zeile hier.
      && !(f.k === 'verkehrswert' && !istEinheitswert(objekt)))
    .map(f => (feldLeer(f, e[f.k]) ? '' : paarZeile(f.l, stammwert(f, e), { lex: f.lex }))
      + (f.k === 'flaeche' ? flaechen : '')).join('');
  // CCCXXXIII — sind €/m²-Ansätze gesetzt, folgt die daraus hergeleitete
  // Kaltmiete als klar als „Vorschlag" markierte, abgeleitete Zeile. Sie steht
  // hier nur zur Auskunft; übernommen wird sie erst im Miet-Formular.
  const vorschlag = hergeleiteteKaltmiete(e);
  const mietZeile = vorschlag != null
    ? paarZeile('Hergeleitete Kaltmiete (Vorschlag)', `${eur(vorschlag)} / M`,
        { abgeleitet: true, lang: true })
    : '';
  const aus = e.nk_abrechnung === false
    ? `<div class="merker"><span class="hi">i</span><span class="ht">
         <span class="t">Nicht Teil der Nebenkostenabrechnung</span>
         <span class="d">Diese Einheit zählt in keinem Verteilungsschlüssel mit
           — selbstgenutzt, separat abgerechnet oder mit eigenem Zähler.
           „Bearbeiten" schaltet die Teilnahme wieder ein.</span>
       </span></div>` : '';
  return `<div class="sekopf"><h2 class="sec">Einheit</h2>
      <button data-einheit-edit="${e.id}">Bearbeiten</button></div>
    <div class="paare">${zeilen}${mietZeile}</div>${aus}
    ${lageplanHtml(e)}`;
}
