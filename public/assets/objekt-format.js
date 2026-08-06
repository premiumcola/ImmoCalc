import { eur, eurVoll, esc } from './immo.js';
import { kostenIcon } from './kostenicons.js';

const proTurnus = { monatlich: '/ M', vierteljaehrlich: '/ Q', halbjaehrlich: '/ HJ',
                    jaehrlich: '/ J', einmalig: 'einm.' };
const kuerzel = t => proTurnus[t] || '/ J';
/* Wie oft im Jahr gezahlt wird — Grundlage für Monats- und Jahresgrößen. */
const proJahr = t => ({ monatlich: 12, vierteljaehrlich: 4,
                        halbjaehrlich: 2 }[t] || 1);

const istBausparer = art =>
  String(art || '').trim().toLowerCase().startsWith('bauspar');

/* Was ein Vertrag heute wert ist — als Schuld oder als Guthaben. */
function kreditStandText(e) {
  if (istBausparer(e.art)) {
    const gespart = e.guthaben_aktuell ?? e.angespart ?? 0;
    return e.bausparsumme
      ? `${eurVoll(gespart)} von ${eurVoll(e.bausparsumme)}`
      : (gespart ? `Guthaben ${eurVoll(gespart)}` : '');
  }
  return restText(e);
}

const datum = s => s ? new Date(s).toLocaleDateString('de-DE') : '';

/* Datum als ISO-Tag ohne Umweg über UTC — `toISOString` verschiebt in
   Mitteleuropa auf den Vortag und macht aus dem 1. den 31. */
const isoDatum = d => `${d.getFullYear()}-${String(d.getMonth() + 1)
  .padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const tagDavor = iso => {
  const d = new Date(`${iso}T12:00:00`);
  d.setDate(d.getDate() - 1);
  return isoDatum(d);
};
const tagDanach = iso => {
  const d = new Date(`${iso}T12:00:00`);
  d.setDate(d.getDate() + 1);
  return isoDatum(d);
};
const ersterNaechsterMonat = () => {
  const d = new Date();
  d.setDate(1);
  d.setMonth(d.getMonth() + 1);
  return isoDatum(d);
};

/* Zinssatz deutsch: 2,75 statt 2.75 — zwei Nachkommastellen, mehr nie. */
const prozent = n => Number(n).toLocaleString('de-DE', { maximumFractionDigits: 2 });

/* Wer ist erreichbar: der Hauptkontakt am Mietverhältnis und die Bewohner,
   die eine eigene Mailadresse haben. */
function kontaktText(e) {
  const extra = (e.bewohner || []).filter(b => b.email).length;
  if (!e.email && !extra) return '✉ fehlt';
  const zahl = (e.email ? 1 : 0) + extra;
  return zahl === 1 ? '✉ hinterlegt' : `✉ ${zahl} Adressen`;
}

/* Die Restschuld, die heute gilt. Ohne Cent: zwischen zwei Jahresständen ist
   sie gerechnet, da wäre eine Angabe auf den Cent nur vorgetäuschte Schärfe. */
function restText(e) {
  const rest = e.restschuld_aktuell ?? e.restschuld;
  return rest ? `Rest ${eurVoll(rest)}` : '';
}

/* IBAN in Vierergruppen, egal wie sie gespeichert wurde: „DE42 7635 0000 …".
   Die letzte Gruppe darf kürzer sein. */
const ibanSchoen = s => String(s || '').replace(/\s+/g, '').toUpperCase()
  .replace(/(.{4})/g, '$1 ').trim();

function stammwert(f, o) {
  const v = o[f.k];
  if (f.typ === 'schalter' || f.typ === 'ja_nein') return v ? 'Ja' : 'Nein';
  if (v == null || v === '') return null;
  if (f.typ === 'date') return datum(v);
  if (f.iban) return ibanSchoen(v);
  // `voll`: ein Kaufpreis oder Verkehrswert ist ein runder Betrag — die zwei
  // Nachkommastellen sind dort nur Rauschen. Der Grundsteuer-Messbetrag (1,43 €)
  // trägt sie dagegen bewusst.
  if (f.geld) return f.voll ? eurVoll(v) : eur(v);
  if (f.einheit) return `${Number(v).toLocaleString('de-DE')} ${f.einheit}`;
  return String(v);
}

/* CCCXLII — ein Feld gilt als leer, wenn kein Wert erfasst ist; bei den
   optionalen Zahlenfeldern (Verkehrswert, Terrasse, Nebenfläche, Stellplätze)
   zählt auch die 0 als „nicht erfasst". Solche Felder werden dann gar nicht
   erst als Zeile gezeigt, statt eine Reihe leerer „nicht erfasst" aufzuziehen.
   Schalter/Ja-Nein-Felder sind nie leer — sie tragen bewusst „Ja"/„Nein". */
function feldLeer(f, v) {
  if (f.typ === 'schalter' || f.typ === 'ja_nein') return false;
  if (v == null || v === '') return true;
  return f.typ === 'number' && Number(v) === 0;
}

const flaecheText = f => `${Number(f).toLocaleString('de-DE',
  { maximumFractionDigits: 1 })} m²`;

/* CCLXVII — ein fachliches Label in der Übersicht trägt denselben ?-Platzhalter
   wie im Formular. `installHilfe(inhalt)` macht nach dem Rendern ein Icon
   daraus. Triviale Zeilen bekommen kein `lex` und bleiben schmucklos. */
const paarLabel = (label, lex) => `${esc(label)}${
  lex ? ` <span data-hilfe="${esc(lex)}"></span>` : ''}`;

function paarZeile(label, wert, { abgeleitet = false, lang = false,
                                  lex = null } = {}) {
  // `lang` gilt für die Beschriftung, nicht nur den Wert — ein langes Label
  // wie „Übernommene AfA-Bemessung (vom Vorbesitzer)" drückt die Wertspalte
  // sonst auf null Breite, und „nicht erfasst" bricht Buchstabe für
  // Buchstabe um (Fund bei CCXXXV). Deshalb gilt die gestapelte Form auch,
  // wenn noch kein Wert erfasst ist.
  return `<div class="paar${lang ? ' lang' : ''}">
    <span class="pl">${paarLabel(label, lex)}</span>
    <span class="pv${wert ? (abgeleitet ? ' abgeleitet' : '') : ' leer'}"
      >${wert ? esc(wert) : 'nicht erfasst'}</span></div>`;
}

/* Eine gerechnete Zeile mit Herkunftsangabe — „Wohnfläche · 205 m² · aus 5
   Einheiten". Die Herkunft steht ruhig unter dem Wert. */
/* CCCXXX — eine Zelle (Label + Wert, optional mit Herkunft) als gemeinsamer
   Baustein für ganze Zeilen und für die kompakten Zweiergruppen. */
function zelleInner({ label, wert, quelle = null, lex = null, abgeleitet = false }) {
  return `<span class="pl">${paarLabel(label, lex)}</span>
    <span class="pv${wert ? (abgeleitet ? ' abgeleitet' : '') : ' leer'}"
      >${wert ? esc(wert) : 'nicht erfasst'}${quelle
        ? `<span class="pq">${esc(quelle)}</span>` : ''}</span>`;
}

/* CCCXXX (korrigiert) — eine Zelle als eigene, EINSPALTIGE Zeile. Das
   Zwei-Spalten-Raster war unübersichtlich; kurze Werte werden stattdessen
   gezielt im Wert selbst zusammengezogen (IBAN (Bank), Stand · mtl.). */
function cellZeile(c) {
  return `<div class="paar${c.lang ? ' lang' : ''}">${zelleInner(c)}</div>`;
}

const sekopfHtml = (titel, ikon = '', knopf = '', farbe = '') =>
  `<div class="sekopf">${ikon
      ? `<span class="seikon"${farbe ? ` style="color:${farbe}"` : ''}
         >${kostenIcon(ikon)}</span>` : ''}
    <h2 class="sec">${esc(titel)}</h2>${knopf}</div>`;

function feldWertText(f, wert) {
  if (wert == null || wert === '') return '—';
  if (f.typ === 'ja_nein' || f.typ === 'schalter') return wert ? 'Ja' : 'Nein';
  if (f.typ === 'number') {
    if (f.geld) return f.voll ? eurVoll(wert) : eur(wert);
    // Jahreszahlen ohne Tausenderpunkt (2025, nicht 2.025).
    if (/jahr/i.test(f.k)) return String(wert);
    const zahl = Number(wert);
    const txt = Number.isFinite(zahl) ? zahl.toLocaleString('de-DE') : String(wert);
    return f.einheit ? `${txt} ${f.einheit}` : txt;
  }
  if (f.typ === 'date') {
    const d = new Date(wert);
    return isNaN(d) ? String(wert) : d.toLocaleDateString('de-DE');
  }
  return String(wert);
}

export { proTurnus, kuerzel, proJahr, istBausparer, kreditStandText, datum, isoDatum, tagDavor, tagDanach, ersterNaechsterMonat, prozent, kontaktText, restText, ibanSchoen, stammwert, feldLeer, flaecheText, paarLabel, paarZeile, zelleInner, cellZeile, sekopfHtml, feldWertText };
