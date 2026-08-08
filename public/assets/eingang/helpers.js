/* N216 — Reine Hilfsfunktionen und Konstanten.

   Nichts ausser das, was ohne Blick auf DOM oder API auskommt: Namen und
   Datum aus dem Dateinamen lesen, Datums-/Betragsformatter, Zeitraum-
   Vergleiche, KI-Label-Zuordnung, kleine Bausteine fuers Prueferblatt. */

import { S, jetzt, MONATE } from './state.js';
import { eur, zahlAus as deutscheZahl } from '../immo.js';

/* ---- Die Liste der Jahre fuer die Auswahlfelder ------------------------- */
export const jahresliste = () => {
  const aus_daten = S.daten.jahre || [];
  const spanne = Array.from({ length: 8 }, (_, i) => jetzt - i);
  return [...new Set([...spanne, ...aus_daten])].sort((a, b) => b - a);
};

/* ---- Dokument aus der Liste holen --------------------------------------- */
export const dok = id => S.daten.dokumente.find(d => d.id === id) || null;

/* ---- Aus dem Dateinamen lesen -------------------------------------------
   Der Name traegt Datum, Sache und Betrag an festen Plaetzen
   (JJJJ-MM_Sache_1234,56€.pdf). Was die API im `vorschlag` mitschickt, ist
   dieselbe Zerlegung — hier wird nur noch die Sache herausgeloest, damit die
   Karte einen Titel hat, der nicht Datum und Betrag ein zweites Mal zeigt. */
export const DATUM_IM_NAMEN =
  /\b(?:(?:0?[1-9]|1[0-2])[-.])?(?:19|20)\d{2}(?:[-.](?:0?[1-9]|1[0-2]))?\b/g;
export const BETRAG_IM_NAMEN = /\(?\b\d{1,3}(?:[.\s]?\d{3})*[,.]\d{2}\s*(?:€|EUR)\)?/gi;

/** Der Dateiname ohne das, was Datum und Betrag schon sagen.
    Der Unterstrich faellt zuerst — er ist ein Wortzeichen und hebelte sonst
    jede Wortgrenze in den beiden Mustern aus ("_1284,50€" fand kein \b). */
export function sacheAusNamen(name, kategorie) {
  const stamm = String(name || '').replace(/\.[^.]+$/, '').replace(/_+/g, ' ');
  let rest = stamm.replace(BETRAG_IM_NAMEN, ' ').replace(DATUM_IM_NAMEN, ' ');
  // Was der Ordner schon sagt, gehoert nicht in den Titel (CXXII/CXXVI).
  if (kategorie) {
    rest = rest.replace(new RegExp('\\b' + kategorie + '\\w{0,2}', 'gi'), ' ');
  }
  return rest.replace(/\s+/g, ' ').replace(/^[-·._\s]+|[-·._\s]+$/g, '').trim();
}

export const endungVon = name => {
  const teile = String(name || '').split('.');
  return teile.length > 1 ? '.' + teile.pop() : '';
};

/* ---- Datums- und Betrags-Formatter -------------------------------------- */
export const datumText = (jahr, monat) => (!jahr ? ''
  : monat ? `${MONATE[monat - 1]} ${jahr}` : String(jahr));

/** 'JJJJ-MM-TT' als echtes Datum — der Wert eines Datumsfeldes. */
export const alsDatum = iso => {
  const t = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(iso || ''));
  return t ? new Date(Number(t[1]), Number(t[2]) - 1, Number(t[3])) : null;
};

/** Ein Datum, wie es auf der Rechnung steht: 14.11.2025 (CLXXII). */
export const dmy = t => t.toLocaleDateString('de-DE',
  { day: '2-digit', month: '2-digit', year: 'numeric' });

export const tagText = iso => {
  const t = alsDatum(iso);
  return t ? dmy(t) : '';
};

export const betragText = betrag =>
  (betrag === null || betrag === undefined ? '' : eur(betrag));

/** Belegdatum und Betrag, wie die Ablage sie sieht (CXXIV). */
export function befund(d) {
  const v = d.vorschlag || {};
  const kategorie = d.kategorie || v.kategorie || '';
  // Steht ein tagesgenaues Belegdatum am Eintrag, ist es die feinere Wahrheit:
  // Jahr und Monat folgen ihm, statt daneben ein zweites Datum zu behaupten.
  const tag = d.belegdatum || '';
  return {
    sache: sacheAusNamen(d.dateiname, kategorie) || v.sache || '',
    belegdatum: tag,
    jahr: (tag ? Number(tag.slice(0, 4)) : d.jahr || v.jahr) || null,
    monat: (tag ? Number(tag.slice(5, 7)) : v.monat) || null,
    betrag: v.betrag === undefined ? null : v.betrag,
    kategorie,
    kostenart: d.kostenart || '',
  };
}

/** Das Datum eines Belegs in seiner feinsten bekannten Genauigkeit. */
export const belegDatumText = b =>
  (b.belegdatum ? tagText(b.belegdatum) : datumText(b.jahr, b.monat));

/** Was in der Kachel oben steht: die Sache, nicht der ganze Dateiname. */
export const titelVon = d => befund(d).sache || 'Beleg';

/* ---- Kurzcodes fuer den Immobilien-Filter (CCLXXXVIII) ------------------
   „(Eschenau) Laufer Str. 5" → „lau 5": erste 3 Buchstaben der Strasse +
   Hausnummer; ein Grundstueck ohne Nummer bekommt die ersten Buchstaben des
   Namens. Der volle Name steht im title/aria — so bleibt die Leiste einzeilig. */
export function kurzObjekt(name) {
  const ohneOrt = String(name || '').replace(/^\([^)]*\)\s*/, '').trim();
  const num = (ohneOrt.match(/(\d+\s*[a-zA-Z]?)\s*$/) || [, ''])[1].replace(/\s+/g, '');
  const wort = (ohneOrt.match(/[A-Za-zÄÖÜäöüß]{2,}/) || [ohneOrt])[0];
  const kurz = wort.slice(0, 3).toLowerCase();
  return (num ? `${kurz} ${num}` : kurz) || String(name || '').slice(0, 4);
}

/* ---- Zeitraum-Vergleiche ------------------------------------------------ */
export const zumDatum = text => {
  const t = /(\d{2})\.(\d{2})\.(\d{4})/.exec(text || '');
  return t ? new Date(Number(t[3]), Number(t[2]) - 1, Number(t[1])) : null;
};

/** Enthaelt dieser Zeitraum den Tag? */
export const umfasst = (z, tag) =>
  Boolean(z && tag && z.von && z.bis && z.von <= tag && tag <= z.bis);

/** Welcher Zeitraum das Belegdatum enthaelt — vorgeschlagen, nicht gesetzt.
    Tagesgenau (CLXXII): Abrechnungen laufen nicht immer von Januar bis
    Dezember, sondern zum Beispiel vom 1. Oktober bis zum 30. September. */
export const passenderZeitraum = (zs, tag) =>
  (tag ? zs.find(z => umfasst(z, tag)) || null : null);

/** Der Tag, an dem der Beleg haengt. `genau` sagt, ob er auf der Rechnung
    steht oder nur aus Jahr und Monat geschaetzt ist — das ist ein Unterschied,
    wenn ein Zeitraum mitten im Jahr endet. */
export function belegTag(s) {
  const genau = alsDatum(s.belegdatum);
  if (genau) return { tag: genau, genau: true };
  if (!s.jahr) return { tag: null, genau: false };
  return { tag: new Date(s.jahr, (s.monat || 6) - 1, 15), genau: false };
}

/** Ein JS-Datum als 'JJJJ-MM-TT' fuer die Abfrage — lokal, ohne Zeitzonen-
    versatz (toISOString gaebe UTC und koennte auf den Vortag rutschen). */
export const isoTag = t => `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, '0')}`
  + `-${String(t.getDate()).padStart(2, '0')}`;

/* ---- Was zaehlt als „fertig"? ------------------------------------------
   Zugeordnet allein genuegt nicht: ein Nebenkostenbeleg ohne Kostenposition
   liegt zwar richtig, steht aber in keiner Abrechnung. Ein Mietvertrag dagegen
   gehoert in keine Abrechnung und ist mit dem Einsortieren fertig. */
export const BRAUCHT_POSITION = new Set(['Nebenkosten']);
export const fertig = d => d.status === 'zugeordnet' && !d.vermisst
  && (!BRAUCHT_POSITION.has(d.kategorie) || Boolean(d.position_id));

/** N288 — die Belege in genau der Reihenfolge, in der die Liste sie zeigt:
    nur PDFs (CCCLXXXIII), offene zuerst, Erledigtes darunter. Das grosse
    Beleg-Fenster blaettert damit durch dieselbe Reihe, die auf dem Schirm
    steht — sonst spraenge das „›" in eine andere Ordnung als die Karten. */
export function sichtbareDokumente() {
  const pdfs = (S.daten.dokumente || [])
    .filter(d => /\.pdf$/i.test(d.dateiname || ''));
  return [...pdfs.filter(d => !fertig(d)), ...pdfs.filter(fertig)]
    .map(d => ({ id: d.id, dateiname: d.dateiname, pfad: d.pfad || '' }));
}

/* ---- KI-Labels und Wertformatierung ------------------------------------- */
export const KI_LABELS = {
  mieter: 'Mieter', vermieter: 'Vermieter', kaltmiete: 'Kaltmiete',
  warmmiete: 'Warmmiete', nettomiete: 'Nettomiete', kaution: 'Kaution',
  nebenkosten: 'Nebenkosten', betrag: 'Betrag', kostenart: 'Kostenposition',
  police_nr: 'Policennummer', policennummer: 'Policennummer',
  versicherer: 'Versicherer', versicherung: 'Versicherung',
  jahresbeitrag: 'Jahresbeitrag', beitrag: 'Beitrag', rate: 'Rate',
  darlehensnummer: 'Darlehensnummer', darlehen: 'Darlehen', bank: 'Bank',
  restschuld: 'Restschuld', zinssatz: 'Zinssatz', tilgung: 'Tilgung',
  messbetrag: 'Messbetrag', hebesatz: 'Hebesatz', grundsteuer: 'Grundsteuer',
  steuernummer: 'Steuernummer', aktenzeichen: 'Aktenzeichen',
  flaeche: 'Fläche', wohnflaeche: 'Wohnfläche', einheit: 'Einheit',
  sache: 'Sache', datum: 'Datum', zeitraum: 'Zeitraum',
  // N162 — Strombeleg. Auf einer Jahresabrechnung stehen drei Betraege
  // nebeneinander; sie brauchen Namen, sonst rechnet man mit dem falschen.
  verbrauch_kwh: 'Verbrauch', verbrauch: 'Verbrauch',
  betrag_art: 'Betrag ist', nachzahlung: 'Nachzahlung',
  abschlag_monat: 'Abschlag je Monat', preis_kwh: 'Preis je kWh',
  bruttobetrag: 'Bruttobetrag', zeitraum_von: 'Zeitraum von',
  zeitraum_bis: 'Zeitraum bis',
};

/** Welche Rasterfelder eine Einheit tragen — sonst stuende „2416" da, und
    niemand wuesste, ob das Kilowattstunden oder Euro sind (N162). */
export const KI_EINHEITEN = { verbrauch_kwh: 'kWh', verbrauch: 'kWh' };

/** Fuer diese Arten steht der Datensatz-Weg noch aus — die Vorbelegung dient
    dann dem haendischen Uebertragen der Werte. */
export const KI_UEBERNAHME = new Set(['Versicherung', 'Kredit', 'Mietvertrag', 'Steuer']);

export const kiLabel = schluessel => KI_LABELS[schluessel]
  || KI_LABELS[String(schluessel).toLowerCase()]
  || String(schluessel).charAt(0).toUpperCase()
     + String(schluessel).slice(1).replace(/_/g, ' ');

/** Wie ein KI-Wert dasteht: Geldbetraege huebsch, Mengen mit Einheit, sonst roh. */
export function kiWert(schluessel, wert) {
  if (typeof wert === 'number') {
    const name = String(schluessel).toLowerCase();
    // N162 — der Preis je kWh hat drei Nachkommastellen (0,357 €/kWh); mit
    // zwei stuende dort 0,36 € und der Abgleich mit der Rechnung ginge nicht auf.
    if (name === 'preis_kwh') {
      return wert.toLocaleString('de-DE', { minimumFractionDigits: 3,
                                            maximumFractionDigits: 3 }) + ' €/kWh';
    }
    const einheit = KI_EINHEITEN[name];
    if (einheit) return wert.toLocaleString('de-DE') + ' ' + einheit;
    const geld = /miete|beitrag|schuld|kaution|betrag|rate|kosten|messbetrag|zahlung|abschlag/
      .test(name);
    return geld ? eur(wert) : String(wert);
  }
  return String(wert);
}

/** Eine Zahl aus einem KI-Feld — Zahl oder deutscher Betragstext („1.234,56 €").
    N288 — die deutsche Leseregel selbst steht in `immo.js`; hier bleibt nur die
    zusaetzliche Eigenschaft dieser Fassung: ein Betrag muss positiv sein, sonst
    gilt er als „nichts erkannt". */
export function zahlAus(x) {
  if (typeof x === 'number') return Number.isFinite(x) && x > 0 ? x : null;
  const n = deutscheZahl(x);
  return n != null && n > 0 ? n : null;
}
