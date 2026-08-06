/* N216 — der Stammdaten-Block am Kopf des Hauses (bzw. beim Grundstück
   im grundstueck-Modul) und der WEG-Block darunter. */

import { esc, eurVoll } from '../immo.js';
import { kostenIcon } from '../kostenicons.js';
import { stammfelder, WEGFELDER } from '../objekt-felder.js?v=2';
import { stammwert, ibanSchoen, feldLeer, paarZeile, cellZeile } from '../objekt-format.js?v=2';
import { objekt, istGrundstueck } from '../objekt-state.js?v=2';
import { einheiten } from './state.js';
import { flaechenSummen, wohnflaecheCells, flaecheWarnung } from './helpers.js';
import { istEinheitswert } from '../objekt-felder.js?v=2';

export function stammHtml(o) {
  const s = flaechenSummen();
  const felder = stammfelder();
  const def = k => felder.find(f => f.k === k);
  const hat = k => Boolean(def(k));
  const erbe = o.erwerbsart === 'Erbschaft';
  // Eine Zelle aus einem Stammfeld — Label, formatierter Wert, Hilfe-Lexikon.
  const feldZelle = (k, extra = {}) => {
    const f = def(k);
    return { label: f.l, wert: stammwert(f, o), lex: f.lex, lang: f.lang, ...extra };
  };
  const zeilen = [];
  // CCCXXX (korrigiert) — wieder EINSPALTIG: jede Angabe eine Zeile. Nur wo der
  // Wert kurz ist, werden zwei Angaben in EINER Zeile zusammengezogen (IBAN mit
  // Bank in Klammern, Rücklagen-Stand neben der Monatsrate). Kein Zwei-Spalten-
  // Raster (das war unübersichtlich).
  // CCCXLII — leere Felder nicht als „nicht erfasst"-Zeile führen. Die
  // gerechneten Zellen (Wohnfläche, Adresse) laufen über cellZeile direkt und
  // behalten ihren Herkunfts-/Leerhinweis.
  const zeile = (k, extra = {}) => {
    if (feldLeer(def(k), o[k])) return;
    zeilen.push(cellZeile(feldZelle(k, extra)));
  };

  // Kopf: Objektart, Erwerbsart.
  if (hat('objektart')) zeile('objektart');
  if (hat('erwerbsart')) zeile('erwerbsart');

  // Adresse einzeilig: Straße · PLZ Ort. Beim Grundstück fehlt die Straße.
  const strasse = hat('strasse') ? o.strasse : '';
  const plzOrt = [hat('plz') && o.plz, hat('ort') && o.ort].filter(Boolean).join(' ');
  const adresse = [strasse, plzOrt].filter(Boolean).join(' · ');
  zeilen.push(cellZeile({ label: 'Adresse', wert: adresse || null }));

  // Flächen: Wohnfläche (mit Herkunft „aus N Einheiten") und Stellplätze,
  // dazu die Grundstücksfläche — jede in ihrer eigenen Zeile.
  if (hat('flaeche')) for (const c of wohnflaecheCells(o, s)) zeilen.push(cellZeile(c));
  if (hat('grundstueck_flaeche')) zeile('grundstueck_flaeche');

  // Erwerb & Wert: Kaufpreis (bei Erbschaft ohne Sinn → ausgeblendet),
  // Kauf-/Erbschaftsdatum bzw. Baudatum, Verkehrswert.
  if (hat('kaufpreis') && !erbe) zeile('kaufpreis');
  if (erbe) { if (hat('baudatum')) zeile('baudatum', { label: 'Baudatum' }); }
  else { if (hat('kaufdatum')) zeile('kaufdatum'); if (hat('baudatum')) zeile('baudatum'); }
  // CCCLVI — Verkehrswert je Modus: „ganzes Objekt" zeigt den Objektwert; „je
  // Einheit" die Summe der Einheiten-Verkehrswerte — aber nur, wenn mindestens
  // eine Einheit bewertet ist (sonst bleibt die Zeile schlicht weg).
  if (hat('verkehrswert')) {
    if (istEinheitswert(o)) {
      const bewertet = einheiten.filter(e => e.verkehrswert != null && e.verkehrswert !== '');
      if (bewertet.length) {
        const summe = bewertet.reduce((s, e) => s + Number(e.verkehrswert), 0);
        // Kurzes Label, damit der Betrag rechts einzeilig passt; die Herkunft
        // (Summe aus N Einheiten) steht als Herkunftshinweis darunter.
        zeilen.push(cellZeile({
          label: 'Verkehrswert (Summe)',
          wert: stammwert(def('verkehrswert'), { verkehrswert: summe }),
          quelle: `aus ${bewertet.length} Einheit${bewertet.length === 1 ? '' : 'en'}`,
          lex: 'verkehrswert' }));
      }
    } else {
      zeile('verkehrswert');
    }
  }

  // Konto & Rücklage — abgesetzter Block. Kontoinhaber eigene Zeile, dann IBAN
  // mit der Bank in Klammern, dann Rücklagenstand und Monatsrate zusammen.
  const iban = o.iban ? ibanSchoen(o.iban) : '';
  const bank = (o.bank || '').trim();
  const ibanBank = iban ? (bank ? `${iban} (${bank})` : iban) : (bank || null);
  const saldo = (hat('ruecklage_saldo') && o.ruecklage_saldo != null)
    ? stammwert(def('ruecklage_saldo'), o) : '';
  const rate = (hat('ruecklage_monatlich') && o.ruecklage_monatlich != null)
    ? stammwert(def('ruecklage_monatlich'), o) : '';
  const ruecklageWert = [saldo && `Stand ${saldo}`, rate && `mtl. ${rate}`]
    .filter(Boolean).join(' · ');
  const hatKonto = hat('kontoinhaber') || hat('iban') || hat('bank');
  if (hatKonto || saldo || rate) {
    zeilen.push('<div class="paar-trenn"><span>Konto &amp; Rücklage</span></div>');
    if (hat('kontoinhaber')) zeile('kontoinhaber');
    if (hat('iban') || hat('bank')) {
      zeilen.push(cellZeile({ label: 'IBAN', wert: ibanBank }));
    }
    if (saldo || rate) {
      zeilen.push(cellZeile({ label: 'Rücklage', wert: ruecklageWert || null,
                              lex: 'ruecklage' }));
    }
  }

  // Nießbrauch: ist er eingetragen, ein eigener abgesetzter Block; sonst die
  // eine ruhige „Nein"-Zeile.
  if (o.niessbrauch_aktiv) {
    zeilen.push('<div class="paar-trenn"><span>Nießbrauch</span></div>');
    for (const k of ['niessbrauch_aktiv', 'niessbrauch_berechtigt', 'niessbrauch_bis']) {
      if (hat(k)) zeile(k);
    }
  } else if (hat('niessbrauch_aktiv')) {
    zeile('niessbrauch_aktiv');
  }

  // N210 — Titel + Objektname als Spalte (setxt), damit der Name UNTER
  // „Stammdaten" steht und die Kopfzeile nicht mehr umbricht.
  return `<div class="sekopf"><span class="seikon">${kostenIcon('Haus')}</span>
      <div class="setxt"><h2 class="sec">Stammdaten</h2>${(objekt?.titel || objekt?.name)
        ? `<span class="secsub">${esc(objekt.titel || objekt.name)}</span>` : ''}</div>
      <button data-stamm="1">Bearbeiten</button></div>
    <div class="paare">${zeilen.join('')}</div>
    ${flaecheWarnung(o.flaeche, s)}`;
}

/* CCVIII — die WEG-Ebene. Beim Grundstück gibt es sie nicht (keine Mieter, keine
   Hausverwaltung). Ist das Objekt keine WEG, steht hier nur der Hinweis, wie man
   es einschaltet; ist es eine, stehen Hausgeld, Rücklagenzuführung und
   Verwalter. Der Wirtschaftsplan hat vorerst keinen eigenen Datensatz — Platz
   dafür schafft die Notiz am Verwalter und die Fussnote. */
export function wegHtml(o) {
  if (istGrundstueck()) return '';
  if (!o.weg) {
    return `<div class="sekopf"><h2 class="sec">WEG-Ebene</h2>
        <button data-weg="1">Einrichten</button></div>
      <div class="fussnote">Ist diese Wohnung Teil einer
        Wohnungseigentümergemeinschaft, verteilt die Hausverwaltung die
        Nebenkosten. Schalte die WEG-Ebene ein: du trägst dann die fertigen
        Werte je Mieter direkt ein und pflegst hier Hausgeld und
        Wirtschaftsplan.</div>`;
  }
  const zeilen = WEGFELDER
    .filter(f => f.k !== 'weg')
    // Der Verwaltername ist oft lang — als eigene Zeilenbreite statt eines
    // Bruchs mitten im Wort in der schmalen rechten Spalte.
    .map(f => paarZeile(f.l, stammwert(f, o),
                        { lang: f.k === 'weg_verwalter', lex: f.lex })).join('');
  const jahr = o.hausgeld_monatlich
    ? paarZeile('Hausgeld im Jahr', eurVoll(o.hausgeld_monatlich * 12),
                { abgeleitet: true })
    : '';
  return `<div class="sekopf"><h2 class="sec">WEG-Ebene</h2>
      <button data-weg="1">Bearbeiten</button></div>
    <div class="paare">${zeilen}${jahr}</div>
    <div class="fussnote">Die Hausverwaltung verteilt die Nebenkosten auf die
      Mieter — in der Abrechnung trägst du die Werte vom Zettel je Mieter direkt
      ein, ImmoCalc verteilt sie nicht selbst. Das Hausgeld zählt zu deinen
      Eigentümerkosten und steht in der Wertentwicklung.</div>`;
}
