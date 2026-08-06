/* N216 — Zusatzblöcke am Miet-Formular:
   - Vorschlagsblock „Kaltmiete aus Flächen × €/m²" (CCCXXXIII)
   - Bewohnerblock (siehe bewohner.js)
   - Miet-/Pachterhöhung planen (eigenes Formular mit Kappungsgrenze)
   - Kappungsgrenzen-Wächter (§ 558 Abs. 3 BGB) */

import { esc, eur, api, melde } from '../immo.js';
import { cfgFuer } from '../objekt-felder.js?v=2';
import { ersterNaechsterMonat, tagDanach } from '../objekt-format.js?v=2';
import { slug, istGrundstueck } from '../objekt-state.js?v=2';
import { einheiten, fokus } from './state.js';
import { hergeleiteteKaltmiete } from './helpers.js';
import { formular, zahlAus } from './formular.js';
import { bewohnerBlock } from './bewohner.js';

/* CCCXXXIII — hat die Einheit €/m²-Ansätze, ergibt sich daraus eine Kaltmiete.
   Sie wird als überschreibbarer Vorschlag angeboten: ein Knopf trägt sie ins
   Kaltmiete-Feld, gespeichert wird nur, was dann dort steht. Beim Anlegen im
   Fokus ist die Einheit die fokussierte, beim Bearbeiten die am Mietverhältnis
   genannte. Ohne Ansatz (kein Vorschlag) bleibt der Block ganz weg. */
function mietVorschlagBlock(eintrag) {
  if (istGrundstueck()) return '';           // eine Pacht kennt keine €/m²-Ansätze
  const bez = (eintrag && eintrag.einheit) || (fokus && fokus.bezeichnung) || '';
  const e = (bez && einheiten.find(x => x.bezeichnung === bez)) || fokus || null;
  if (!e) return '';
  const wert = hergeleiteteKaltmiete(e);
  if (wert == null) return '';
  return `<div class="block">
    <span class="bt">Kaltmiete aus Flächen</span>
    <span class="bd">Aus den €/m²-Ansätzen dieser Einheit ergeben sich
      ${eur(wert)} / Monat. Übernimm den Wert als Ausgangspunkt und passe ihn
      im Feld „Kaltmiete" bei Bedarf an.</span>
    <button type="button" class="zusatz" data-miete-vorschlag="${wert}"
      >aus Flächen × €/m² (${eur(wert)}) übernehmen</button>
  </div>`;
}

export function mietExtra(eintrag) {
  // Ein Acker hat keine Bewohner. Die Staffelung des Pachtzinses schon —
  // die läuft über denselben Weg wie eine Mieterhöhung.
  const pacht = istGrundstueck();
  const kopf = pacht ? 'Pachterhöhung' : 'Mieterhöhung';
  const kopien = (eintrag ? eintrag.bewohner : []) || [];
  return mietVorschlagBlock(eintrag)
    + (pacht ? '' : bewohnerBlock(kopien)) + (eintrag ? `<div class="block">
      <span class="bt">${kopf}</span>
      <span class="bd">Eine beschlossene Erhöhung lässt sich schon jetzt
        eintragen. Sie steht als „geplant" in der Liste, bis sie wirksam wird;
        der heutige Stand endet automatisch am Tag davor.</span>
      <button type="button" class="zusatz"
              data-erhoehung="${eintrag.id}">＋ ${kopf} planen</button>
    </div>` : '');
}

/* CLXXVI: Kappungsgrenze nach § 558 Abs. 3 BGB -----------------------
   Wie viel eine Erhöhung binnen drei Jahren zulegen darf, hängt an der
   Gemeinde: 20 %, in Gebieten mit angespanntem Wohnungsmarkt 15 %. Welche
   Gemeinden das sind und wie gerechnet wird, steht in
   `api/app/kappungsgrenze.py` — hier wird nur gefragt und gezeigt.

   Gewarnt, nicht verboten: eine Erhöhung nach Modernisierung (§ 559 BGB)
   fällt gar nicht unter die Grenze, und über Ausnahmen entscheidet nicht
   diese Seite. Gespeichert wird deshalb in jedem Fall. */
export async function kappungWachen(mid) {
  const form = document.getElementById('dlgForm');
  const feld = form.querySelector('#f_kaltmiete');
  const abFeld = form.querySelector('#f_ab_datum');
  if (!feld || !feld.closest('.field')) return;

  const halter = document.createElement('div');
  // Eigener Abstand nach unten: sonst klebt die Fundstelle an der
  // Beschriftung des nächsten Feldes.
  halter.style.margin = '-4px 0 18px';
  feld.closest('.field').insertAdjacentElement('afterend', halter);

  let lauf = 0;
  async function zeigen() {
    const frage = new URLSearchParams();
    const neu = zahlAus(feld);
    if (neu != null && neu > 0) frage.set('neu', String(neu));
    if (abFeld && abFeld.value) frage.set('ab', abFeld.value);
    const nummer = ++lauf;
    let s;
    try {
      s = await api(`/mieten/${mid}/kappungsgrenze?${frage}`);
    } catch {
      return;                    // ohne Auskunft lieber nichts behaupten
    }
    // Eine ältere Antwort darf eine neuere nicht überschreiben, und ein
    // umgebautes Formular hat den Platz gar nicht mehr.
    if (nummer !== lauf || !halter.isConnected) return;
    // Die Fundstelle steht immer, aber leise: sie gehört zur Auskunft, ist
    // aber nicht die Nachricht. Die Warnung selbst bleibt kurz.
    const quelle = `<span class="feldnote">Grundlage: ${esc(s.fundstelle)}.
      ${s.ueberschritten ? 'Eine Erhöhung nach Modernisierung (§ 559 BGB) '
        + 'fällt nicht darunter — eintragen lässt sie sich trotzdem.' : ''}</span>`;
    halter.innerHTML = (s.ueberschritten
      ? `<div class="merker" style="margin-top:10px">
           <span class="hi">!</span><span class="ht">
           <span class="t">${esc(s.titel)}</span>
           <span class="d">${esc(s.text)}</span></span></div>`
      : `<span class="feldnote">${esc(s.text)}</span>`) + quelle;
  }

  let warten = null;
  const spaeter = () => {
    clearTimeout(warten);
    warten = setTimeout(zeigen, 350);
  };
  feld.addEventListener('input', spaeter);
  if (abFeld) abFeld.addEventListener('change', spaeter);
  await zeigen();
}

/* Eine geplante Erhöhung ist ein neuer Mietstand derselben Partei — nicht ein
   geänderter alter. So bleibt nachvollziehbar, was wann galt. */
export async function erhoehungFormular(mid) {
  let alt;
  try {
    alt = (await api(`/objekte/${encodeURIComponent(slug)}/mieten`))
      .find(x => String(x.id) === String(mid));
  } catch (fehler) {
    return melde(String(fehler.message || fehler), 'neg');
  }
  if (!alt) return;
  const pacht = istGrundstueck();
  const bewohner = (alt.bewohner || []).map(b => ({ ...b, id: null }));
  // N225 — plant man eine weitere Erhöhung auf einem bereits (befristet)
  // geplanten Stand, muss das Anfangsdatum an dessen Ende anschließen, nicht
  // an „nächster Monat ab heute" — sonst läge der neue Stand vor dem, den er
  // fortsetzen soll, sobald `alt` selbst schon in der Zukunft liegt.
  const abNeu = alt.bis_datum ? tagDanach(alt.bis_datum) : ersterNaechsterMonat();
  await formular({
    titel: pacht ? 'Pachterhöhung planen' : 'Mieterhöhung planen',
    hinweis: `Trage ${pacht ? 'den neuen Pachtzins' : 'die neue Miete'} und `
      + 'den Tag ein, ab dem er gilt. Der bisherige Stand läuft bis zum Tag '
      + 'davor weiter und bleibt als Historie erhalten.',
    felder: cfgFuer('mieten').felder, bereich: 'mieten', absicht: 'eintrag',
    werte: { ...alt, id: '', ab_datum: abNeu, bis_datum: null },
    extra: pacht ? '' : bewohnerBlock(bewohner), knopf: 'Erhöhung planen',
  });
  document.getElementById('dlgForm').dataset.vorgaenger = mid;
  // Beim Pachtzins gibt es keine Kappungsgrenze — § 558 BGB gilt für
  // Wohnraum, nicht für Grund und Boden.
  if (!pacht) await kappungWachen(mid);
}
