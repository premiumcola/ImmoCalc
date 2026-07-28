import { eur, esc } from './immo.js';
import { kostenIcon } from './kostenicons.js';
import { flaecheText, cellZeile, sekopfHtml, paarZeile, stammwert } from './objekt-format.js?v=2';
import { stammfelder, feldAus, GRUNDFELDER } from './objekt-felder.js?v=2';

/* ---- CCCXXXVI — das Grundstück in drei Blöcken ---------------------------
   Preis je m² und Grundsteuer werden gerechnet, nicht gepflegt: sie stünden
   sonst irgendwann im Widerspruch zu den Zahlen, aus denen sie stammen. Bearbeitet
   wird alles über EIN Stammdaten-Formular (data-stamm, GRUND_STAMMFELDER). */

/* Der Grundstückswert: geschätzter m²-Preis × Fläche, sonst der Verkehrswert. */
function grundstueckswert(o) {
  if (o.grundstueck_m2_preis && o.grundstueck_flaeche) {
    return { betrag: o.grundstueck_m2_preis * o.grundstueck_flaeche,
             quelle: `aus ${eur(o.grundstueck_m2_preis)} / m² × ${
               flaecheText(o.grundstueck_flaeche)}` };
  }
  if (o.verkehrswert) return { betrag: o.verkehrswert, quelle: 'Verkehrswert' };
  return null;
}

/* Grundsteuer im Jahr: Steuermessbetrag × Hebesatz. */
const grundsteuerJahrVon = o => (o.grundsteuer_messbetrag && o.grundsteuer_hebesatz)
  ? o.grundsteuer_messbetrag * o.grundsteuer_hebesatz / 100 : 0;

/* Block A — Stammdaten: was das Grundstück ist. Objektart, Adresse inkl.
   Flurnummer (Ort · Gemarkung · Flurstück), Fläche, Nutzungsart, Grundstückswert;
   ist ein Nießbrauch eingetragen, klingt er als abgesetzter Block mit aus. */
function grundStammHtml(o) {
  const felder = stammfelder();
  const def = k => felder.find(f => f.k === k);
  const zeilen = [];
  const zeile = c => zeilen.push(cellZeile(c));
  if (def('objektart')) {
    zeile({ label: 'Objektart', wert: stammwert(def('objektart'), o) });
  }
  const plzOrt = [o.plz, o.ort].filter(Boolean).join(' ');
  const adresse = [plzOrt, o.gemarkung && `Gemarkung ${o.gemarkung}`,
                   o.flurstueck && `Flur ${o.flurstueck}`].filter(Boolean).join(' · ');
  zeile({ label: 'Adresse', wert: adresse || null });
  if (def('grundstueck_flaeche')) {
    zeile({ label: 'Grundstücksfläche',
            wert: stammwert(def('grundstueck_flaeche'), o) });
  }
  if (def('grundstueck_nutzungsart')) {
    zeile({ label: 'Nutzungsart',
            wert: stammwert(def('grundstueck_nutzungsart'), o) });
  }
  const gw = grundstueckswert(o);
  zeile({ label: 'Grundstückswert', wert: gw ? eur(gw.betrag) : null,
          quelle: gw ? gw.quelle : null, abgeleitet: Boolean(gw) });
  if (o.niessbrauch_aktiv) {
    zeilen.push('<div class="paar-trenn"><span>Nießbrauch</span></div>');
    for (const k of ['niessbrauch_berechtigt', 'niessbrauch_bis']) {
      const f = def(k);
      if (f) zeile({ label: f.l, wert: stammwert(f, o) });
    }
  }
  return `<div class="sekopf"><span class="seikon" style="color:var(--teal-d)"
        >${kostenIcon('Grundstück')}</span>
      <h2 class="sec">Stammdaten${o.name
        ? ` <span class="secsub">· ${esc(o.name)}</span>` : ''}</h2>
      <button data-stamm="1">Bearbeiten</button></div>
    <div class="paare">${zeilen.join('')}</div>`;
}

/* Block B, Kopf — Erwerb & Kosten: wie erworben wurde. Erwerbsart, Kaufpreis,
   Kauf-/Erbschaftsdatum. Die Rubriken (Notar, Erwerbsnebenkosten, Finanzamt)
   und die Grundsteuer-Kette folgen im Aufbau darunter (laden). */
function erwerbKopfHtml(o) {
  const felder = stammfelder();
  const def = k => felder.find(f => f.k === k);
  const zeilen = [];
  for (const k of ['erwerbsart', 'kaufpreis', 'kaufdatum']) {
    const f = def(k);
    if (f) zeilen.push(cellZeile({ label: f.l, wert: stammwert(f, o), lex: f.lex }));
  }
  return `<div class="sekopf"><span class="seikon" style="color:var(--amber)"
        >${kostenIcon('Erwerb')}</span>
      <h2 class="sec">Erwerb &amp; Kosten</h2>
      <button data-stamm="1">Bearbeiten</button></div>
    <div class="paare">${zeilen.join('')}</div>`;
}

/* Block B, Finanzamt/Grundsteuer — die Rechenkette, in der Reihenfolge, in der
   sie entsteht (CCXCVI): Grundsteuerwert × Steuermesszahl = Steuermessbetrag
   × Hebesatz = Grundsteuer im Jahr. Steht direkt über der Finanzamt-Rubrik. */
function grundsteuerHtml(o) {
  const g = k => feldAus(GRUNDFELDER, k);
  const zeilen = [];
  for (const k of ['grundsteuerwert', 'grundsteuer_messbetrag']) {
    const f = g(k);
    const w = stammwert(f, o);
    if (w) zeilen.push(cellZeile({ label: f.l, wert: w, lex: f.lex }));
  }
  if (o.grundsteuerwert && o.grundsteuer_messbetrag) {
    const promille = o.grundsteuer_messbetrag / o.grundsteuerwert * 1000;
    zeilen.push(cellZeile({ label: 'Steuermesszahl (rechnerisch)', abgeleitet: true,
      wert: `${promille.toLocaleString('de-DE', { maximumFractionDigits: 2 })} ‰` }));
  }
  const hebe = g('grundsteuer_hebesatz');
  if (stammwert(hebe, o)) {
    zeilen.push(cellZeile({ label: hebe.l, wert: stammwert(hebe, o), lex: hebe.lex }));
  }
  const jahr = grundsteuerJahrVon(o);
  if (jahr) {
    zeilen.push(cellZeile({ label: 'Grundsteuer im Jahr', wert: eur(jahr),
      quelle: `Steuermessbetrag × Hebesatz ${o.grundsteuer_hebesatz} %`,
      abgeleitet: true }));
  }
  if (!zeilen.length) return '';
  const kette = `<div class="fussnote">So entsteht die Grundsteuer:
       <strong>Grundsteuerwert</strong> (vom Finanzamt) × Steuermesszahl =
       <strong>Steuermessbetrag</strong> (vom Finanzamt) × <strong>Hebesatz</strong>
       (von der Gemeinde) = Grundsteuer&nbsp;im&nbsp;Jahr. Der Hebesatz steht nicht
       auf dem Finanzamts-Bescheid, sondern auf dem Grundsteuerbescheid der
       Stadt.</div>`;
  return `${sekopfHtml('Grundsteuer', 'Finanzamt', '', 'var(--amber)')}
    <div class="paare">${zeilen.join('')}</div>${kette}`;
}

/* Block C, Abschluss — die kleine Ertragsrechnung: Pacht/Jahr − Grundsteuer/Jahr
   (CCCIII). Die Grundsteuer ist beim verpachteten Grundstück die einzige
   Nebenkostenposition. Steht unter der Pacht-Rubrik. */
function pachtErtragHtml(o, pachtJahr = 0) {
  const jahr = grundsteuerJahrVon(o);
  const ertrag = [];
  if (pachtJahr) ertrag.push(['Pacht im Jahr', eur(pachtJahr)]);
  if (jahr) ertrag.push(['Nebenkosten im Jahr (Grundsteuer)', eur(jahr)]);
  if (pachtJahr) ertrag.push(['Ertrag im Jahr', eur(pachtJahr - jahr)]);
  if (!ertrag.length) return '';
  return `${sekopfHtml('Ertrag', 'Miete', '', 'var(--pos)')}
    <div class="paare">${ertrag.map(([l, w], i) =>
      paarZeile(l, w, { abgeleitet: i < ertrag.length - 1 })).join('')}</div>
    <div class="fussnote">Beim verpachteten Grundstück ist die Grundsteuer die
      einzige Nebenkostenposition — sie wird auf den Pächter umgelegt. Der Ertrag
      ist die Pacht abzüglich der Grundsteuer.</div>`;
}

export { grundstueckswert, grundsteuerJahrVon, grundStammHtml, erwerbKopfHtml, grundsteuerHtml, pachtErtragHtml };
