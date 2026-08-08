import { eur, eurVoll } from './immo.js';
import { kuerzel, datum, prozent, kontaktText, istBausparer, kreditStandText } from './objekt-format.js?v=2';
import { istGrundstueck, objekt, objektEigentuemer, alleEigentuemer } from './objekt-state.js?v=2';

/* ---- CXLIX: Darlehen oder Bausparvertrag --------------------------------
   Beide hängen an derselben Immobilie und kosten dieselbe Rate im Monat —
   gerechnet werden sie umgekehrt. Beim Darlehen sinkt die Restschuld, beim
   Bausparvertrag wächst das Guthaben. Deshalb entscheidet die Vertragsart
   ganz oben, wie die Maske darunter aussieht; die Regeln dazu stehen in
   `api/app/vermoegen.py`, hier wird nur gefragt und gezeigt. */
const VERTRAGSARTEN = ['Darlehen', 'Bausparvertrag'];

function kreditFelder(art, werte = {}) {
  const bauspar = istBausparer(art);
  return [
    { k: 'art', l: 'Vertragsart', typ: 'auswahl', werte: VERTRAGSARTEN,
      vorgabe: 'Darlehen', ohneLeer: true, umbau: true, lex: 'bausparvertrag',
      note: bauspar
        ? 'Beim Bausparvertrag wird gespart, nicht getilgt: eingetragen '
          + 'werden Bausparsumme und Guthaben.'
        : 'Beim Darlehen wird getilgt: eingetragen wird die Restschuld.' },
    { k: 'bezeichnung', l: 'Bezeichnung', typ: 'text', pflicht: true },
    { k: 'bank', l: bauspar ? 'Bausparkasse' : 'Bank', typ: 'text' },
    { k: 'darlehensnummer', l: bauspar ? 'Vertragsnummer' : 'Darlehensnummer',
      typ: 'text' },
    ...(bauspar ? [
      { k: 'bausparsumme', l: 'Bausparsumme', typ: 'number', schritt: '0.01',
        geld: true },
      { k: 'angespart', l: 'Bisher angespart', typ: 'number', schritt: '0.01',
        geld: true, note: (werte.uebernommen
          ? 'Aus der bisherigen Restschuld vorgeschlagen — prüfe den Betrag, '
            + 'bevor du speicherst. '
          : '')
          + 'Was noch zu sparen ist, ergibt sich als Differenz zur '
          + 'Bausparsumme.' },
    ] : [
      { k: 'urspruenglich', l: 'Ursprungsbetrag', typ: 'number', schritt: '0.01',
        geld: true },
      { k: 'restschuld', l: 'Restschuld bei Beginn', typ: 'number',
        schritt: '0.01', geld: true, lex: 'restschuld' },
      /* CXLVIII — zwei Wege zum selben Satz. Wer den Zinssatz nicht kennt,
         liest den monatlichen Zinsanteil aus dem Kontoauszug ab; die Kopplung
         rechnet ihn in den Satz um (und umgekehrt). Gespeichert wird nur der
         Zinssatz — ein zweites Feld am Modell wäre eine zweite Wahrheit,
         deshalb `hilfe: true`. Beim Bausparvertrag gibt es nichts
         umzurechnen: dort fällt kein Zins an, dort kommt welcher dazu. */
    ]),
    { k: 'zinssatz', l: bauspar ? 'Guthabenzins' : 'Zinssatz', typ: 'number',
      schritt: '0.01', einheit: '%', lex: bauspar ? null : 'sollzins' },
    ...(bauspar ? [] : [
      { k: 'zins_monat', l: 'Zinsanteil je Monat', typ: 'number',
        schritt: '0.01', geld: true, hilfe: true,
        note: 'Eines von beidem genügt — das andere ergibt sich aus der '
            + 'Restschuld.' },
    ]),
    { k: 'rate_monatlich', l: bauspar ? 'Sparbeitrag je Turnus'
                                      : 'Rate je Turnus',
      typ: 'number', schritt: '0.01', geld: true,
      lex: bauspar ? null : 'annuitaet' },
    { k: 'turnus', l: 'Zahlungsturnus', typ: 'turnus' },
    { k: 'beginn', l: 'Beginn', typ: 'date' },
    ...(bauspar ? [] : [
      { k: 'zinsbindung_bis', l: 'Zinsbindung bis', typ: 'date',
        lex: 'zinsbindung' },
      // CCXXX — der Satz, der ab Ende der Bindung gilt, wenn schon bekannt.
      // Optional: bleibt er leer, rechnet ImmoCalc wie bisher mit dem
      // gebundenen Zinssatz weiter.
      { k: 'zinssatz_variabel', l: 'Anschlusszins ab Bindungsende (variabel)',
        typ: 'number', schritt: '0.01', einheit: '%', lex: 'anschlusszins' },
    ]),
    { k: 'notiz', l: 'Notiz', typ: 'text' },
  ];
}

/* Welche Felder ein Formular zeigt. Kredite hängen von der Vertragsart ab, die
   Stammdaten vom Nießbrauch-Schalter (CCCI) — beide bauen sich beim Umschalten
   im Formular selbst um. */
const felderFuer = (bereich, werte = {}, absicht = bereich) =>
  absicht === 'stamm' ? stammfelder(werte.niessbrauch_aktiv)
  : bereich === 'kredite' ? kreditFelder(werte.art, werte)
  : cfgFuer(bereich).felder;

/* Wird ein Vertrag von Darlehen auf Bausparvertrag umgestellt, ist der Betrag
   derselbe und seine Bedeutung eine andere: aus der Restschuld wird das
   Guthaben. Genau dieser Fall steht heute in der Datenbank — der „LBS
   Bausparer" lief als Kredit. Der Betrag wird deshalb angeboten, nicht
   ersetzt: er steht sichtbar im Feld und wird erst mit „Speichern" übernommen.
   Umgekehrt gibt es nichts anzubieten — ein Guthaben ist keine Schuld. */
function uebernahmeAnbieten(werte) {
  if (istBausparer(werte.art) && werte.angespart == null && werte.restschuld) {
    return { ...werte, angespart: werte.restschuld, uebernommen: true };
  }
  return werte;
}

/* Welche Felder hat welcher Bereich — steuert Liste, Formular und Symbol. */
const BEREICHE = {
  mieten: {
    titel: 'Mieten & Mieter', einzahl: 'Mietverhältnis', ikon: 'Miete',
    felder: [
      { k: 'einheit', l: 'Einheit', typ: 'einheit' },
      { k: 'partei', l: 'Mieter / Partei', typ: 'text' },
      { k: 'kaltmiete', l: 'Kaltmiete', typ: 'number', schritt: '0.01', geld: true,
        lex: 'kaltmiete' },
      { k: 'nebenkosten_vz', l: 'NK-Vorauszahlung', typ: 'number', schritt: '0.01',
        geld: true, lex: 'vorauszahlung' },
      { k: 'stellplatz', l: 'Stellplatzmiete', typ: 'number', schritt: '0.01',
        geld: true, lex: 'stellplatz' },
      { k: 'sonstige', l: 'Sonstige Einnahmen', typ: 'number', schritt: '0.01',
        geld: true },
      { k: 'turnus', l: 'Zahlungsturnus', typ: 'turnus' },
      { k: 'ab_datum', l: 'Gültig ab', typ: 'date', pflicht: true },
      { k: 'bis_datum', l: 'Beendet am', typ: 'date' },
      // CCLXVI — die Kontaktdaten (E-Mail, Telefon, Anschrift) werden nicht
      // mehr am Mietverhältnis abgefragt, sondern je Bewohner (siehe
      // bewohnerZeile). Die Spalten Miete.email/telefon/anschrift bleiben im
      // Modell bestehen — Altbestand bleibt gültig, es wird nur nicht mehr
      // hier eingegeben.
      { k: 'personen', l: 'Personen im Haushalt', typ: 'number', schritt: '1',
        lex: 'personen-im-haushalt' },
      { k: 'kaution', l: 'Kaution', typ: 'number', schritt: '0.01', geld: true,
        lex: 'kaution' },
      // N224 — vom Dokument (Kautionsunterlagen, Checkliste) getrennt: das ist
      // der tatsächliche Geldeingang auf dem Konto.
      { k: 'kaution_eingang', l: 'Kaution eingegangen am', typ: 'date' },
      { k: 'notiz', l: 'Notiz', typ: 'text' },
    ],
    name: e => e.partei || e.einheit || 'Mietverhältnis',
    /* Die Mailadresse steht nicht in der Zeile — sie bricht auf dem Handy
       mitten im Wort um. Ein Zeichen genügt als Auskunft, ob sie da ist.
       Bei mehreren Bewohnern zählt, wie viele erreichbar sind. */
    /* Im Fokus steht die Einheit schon in der Kopfzeile — sie ein zweites Mal
       in jede Zeile zu schreiben, sagt nichts Neues. */
    detail: (e, imFokus = false) => [
      imFokus ? '' : e.einheit,
      e.geplant ? `ab ${datum(e.ab_datum)}`
        : (e.bis_datum ? `bis ${datum(e.bis_datum)}`
                       : (e.ab_datum ? `seit ${datum(e.ab_datum)}` : '')),
      kontaktText(e),
    ].filter(Boolean).join(' · '),
    /* Was insgesamt hereinkommt — eine reine Stellplatzmiete stünde sonst
       mit 0,00 € in der Liste. */
    wert: e => `${eur((e.kaltmiete || 0) + (e.stellplatz || 0) + (e.sonstige || 0))
                } ${kuerzel(e.turnus)}`,
    /* Beendete Mietverhältnisse bleiben als Historie stehen, treten aber
       zurück. Ein Stand, der erst mit der nächsten Erhöhung endet, läuft
       heute noch — der darf nicht blass werden. */
    matt: e => Boolean(e.beendet),
    chip: e => e.geplant ? ['amber', 'geplant'] : null,
  },
  versicherungen: {
    titel: 'Zusätzliche Versicherungen', einzahl: 'Versicherung', ikon: 'Versicherung',
    felder: [
      { k: 'art', l: 'Art', typ: 'text', pflicht: true },
      { k: 'anbieter', l: 'Anbieter', typ: 'text' },
      { k: 'police_nr', l: 'Policen-Nr.', typ: 'text' },
      { k: 'jahresbeitrag', l: 'Beitrag je Turnus', typ: 'number', schritt: '0.01',
        geld: true },
      { k: 'turnus', l: 'Zahlungsturnus', typ: 'turnus' },
      { k: 'versicherungswert', l: 'Versicherungswert', typ: 'number',
        schritt: '0.01', geld: true },
      { k: 'beginn', l: 'Beginn', typ: 'date' },
      { k: 'ende', l: 'Ende', typ: 'date' },
      { k: 'umlagefaehig', l: 'Umlagefähig', typ: 'ja_nein', lex: 'umlagefaehigkeit' },
      { k: 'notiz', l: 'Notiz', typ: 'text' },
    ],
    name: e => e.art,
    detail: e => [e.anbieter, e.police_nr,
                  e.umlagefaehig ? 'umlagefähig' : ''].filter(Boolean).join(' · '),
    wert: e => `${eur(e.jahresbeitrag)} ${kuerzel(e.turnus)}`,
  },
  notarvertraege: {
    titel: 'Notarverträge', einzahl: 'Notarvertrag', ikon: 'Notarvertrag',
    felder: [
      { k: 'art', l: 'Art', typ: 'text', pflicht: true },
      { k: 'notar', l: 'Notar / Notariat', typ: 'text' },
      { k: 'urnr', l: 'URNr', typ: 'text' },
      { k: 'datum', l: 'Beurkundet am', typ: 'date' },
      { k: 'betrag', l: 'Betrag / Kaufpreis', typ: 'number', schritt: '0.01',
        geld: true },
      { k: 'beteiligte', l: 'Beteiligte', typ: 'text' },
      { k: 'notiz', l: 'Notiz', typ: 'text' },
    ],
    name: e => e.art || 'Notarvertrag',
    detail: e => [e.notar, e.urnr ? `URNr ${e.urnr}` : '',
                  e.datum ? datum(e.datum) : '',
                  e.beteiligte].filter(Boolean).join(' · '),
    wert: e => e.betrag ? eur(e.betrag) : '',
  },
  kredite: {
    titel: 'Kredite & Bausparen', einzahl: 'Vertrag', ikon: 'Kredit',
    // Die tatsächlich gezeigten Felder hängen an der Vertragsart und kommen
    // aus `kreditFelder`; dies hier ist die Ausgangslage für einen neuen
    // Vertrag.
    felder: kreditFelder('Darlehen'),
    name: e => e.bezeichnung,
    /* Gezeigt wird der fortgeschriebene Stand, nicht der eingetragene:
       eingegeben wird nur der Stand zum Jahresende, dazwischen rechnet die
       App aus Rate und Zinssatz weiter. */
    // Der Habenzins eines Bausparers steht bewusst nicht in der Zeile: bei
    // 0,25 % sagt er nichts, kostet aber die Breite, die der Name braucht.
    // Dass gespart und nicht getilgt wird, sagt „47.818 € von 140.000 €".
    detail: e => [e.bank, kreditStandText(e),
                  !istBausparer(e.art) && e.zinssatz ? `${prozent(e.zinssatz)} %` : '']
      .filter(Boolean).join(' · '),
    wert: e => `${eur(e.rate_monatlich)} ${kuerzel(e.turnus)}`,
    chip: e => istBausparer(e.art)
      ? (e.stand && e.stand.zuteilungsreif ? ['pos', 'zuteilungsreif'] : null)
      : (e.stand && e.stand.quelle === 'fortgeschrieben'
          ? ['teal', `Stand ${e.stand.stand_jahr}`] : null),
  },
  zahlungen: {
    titel: 'Steuer & Zahlungen', einzahl: 'Zahlung', ikon: 'Steuer',
    felder: [
      { k: 'art', l: 'Art', typ: 'text', pflicht: true },
      { k: 'kategorie', l: 'Kategorie', typ: 'select',
        werte: ['Steuer', 'Kredit', 'Instandhaltung', 'Sonstiges'] },
      { k: 'jahr', l: 'Jahr', typ: 'number', pflicht: true,
        vorgabe: new Date().getFullYear() },
      { k: 'betrag', l: 'Betrag je Turnus', typ: 'number', schritt: '0.01',
        geld: true },
      { k: 'turnus', l: 'Zahlungsturnus', typ: 'turnus' },
      { k: 'absetzbar', l: 'Steuerlich absetzbar', typ: 'ja_nein' },
      { k: 'notiz', l: 'Notiz', typ: 'text' },
    ],
    name: e => e.art,
    detail: e => [e.kategorie, e.jahr, e.absetzbar ? 'absetzbar' : ''].
      filter(Boolean).join(' · '),
    wert: e => `${eur(e.betrag)} ${kuerzel(e.turnus)}`,
  },
};

/* Verpachtet statt vermietet: gespeichert wird derselbe Satz (ein Pachtzins
   ist eine Miete für Grund und Boden), gefragt wird in der Sprache der
   Landwirtschaft — und nur nach dem, was es dort gibt. Nebenkosten-
   vorauszahlung, Stellplatz und Personen im Haushalt fallen weg. */
const PACHT = {
  titel: 'Pacht & Erträge', einzahl: 'Pachtverhältnis', ikon: 'Miete',
  felder: [
    { k: 'partei', l: 'Pächter', typ: 'text' },
    { k: 'kaltmiete', l: 'Pacht', typ: 'number', schritt: '0.01', geld: true,
      note: 'Der Betrag je Zahlung — bei jährlicher Pacht also der Jahresbetrag.' },
    { k: 'turnus', l: 'Zahlungsturnus', typ: 'turnus', vorgabe: 'jaehrlich' },
    { k: 'ab_datum', l: 'Verpachtet ab', typ: 'date', pflicht: true },
    { k: 'bis_datum', l: 'Pacht endet am', typ: 'date' },
    { k: 'email', l: 'E-Mail', typ: 'email' },
    { k: 'telefon', l: 'Telefon', typ: 'tel' },
    { k: 'anschrift', l: 'Anschrift', typ: 'text' },
    // Kaution gibt es bei einer Landpacht nicht — das Feld kommt hier gar
    // nicht erst vor.
    { k: 'notiz', l: 'Notiz', typ: 'text' },
  ],
  name: e => e.partei || 'Pachtverhältnis',
  detail: e => [
    e.geplant ? `ab ${datum(e.ab_datum)}`
      : (e.bis_datum ? `bis ${datum(e.bis_datum)}`
                     : (e.ab_datum ? `seit ${datum(e.ab_datum)}` : '')),
    e.notiz,
  ].filter(Boolean).join(' · '),
  wert: e => `${eur(e.kaltmiete || 0)} ${kuerzel(e.turnus)}`,
};

/* CCCXIX — Einmalige Kauferwerbsnebenkosten: bei jeder Immobilie die Kosten,
   die beim Erwerb einmalig anfallen (Notar, Grunderwerbsteuer, Grundbuch,
   Makler …). Technisch eine Zahlung mit fester Kategorie „Erwerbsnebenkosten"
   und Turnus „einmalig" — deshalb ein eigenes Kürzel, keine /Jahr-Angabe. Die
   Rubrik teilt sich den Zahlungs-Endpunkt (siehe RUBRIK_ENDPUNKT). */
const ERWERB_ARTEN = ['Notar', 'Grunderwerbsteuer', 'Grundbuch / Grundschuld',
                      'Makler', 'Gutachter', 'Sonstiges'];
const ERWERB = {
  titel: 'Einmalige Erwerbsnebenkosten', einzahl: 'Erwerbsnebenkosten',
  ikon: 'Erwerbsnebenkosten',
  felder: [
    // ohneLeer + Vorgabe: eine Erwerbsnebenkosten-Art gibt es immer — sonst
    // liesse sich (ohne Auswahl) ein Posten ohne Art speichern (auswahl.js
    // meldet den Wert erst bei Nutzer-Auswahl zurück).
    { k: 'art', l: 'Art', typ: 'auswahl', werte: ERWERB_ARTEN, ohneLeer: true,
      vorgabe: ERWERB_ARTEN[0], pflicht: true, lex: 'kaufnebenkosten' },
    { k: 'betrag', l: 'Betrag', typ: 'number', schritt: '0.01', geld: true,
      voll: true, pflicht: true },
    { k: 'jahr', l: 'Jahr', typ: 'number', vorgabe: new Date().getFullYear() },
    { k: 'notiz', l: 'Notiz', typ: 'text' },
  ],
  name: e => e.art || 'Erwerbsnebenkosten',
  detail: e => [e.jahr, e.notiz].filter(Boolean).join(' · '),
  wert: e => eurVoll(e.betrag || 0),
};

// Rubriken, die keinen eigenen Endpunkt haben, sondern auf einem anderen
// aufsetzen (Erwerbsnebenkosten sind Zahlungen einer festen Kategorie).
const RUBRIK_ENDPUNKT = { erwerbskosten: 'zahlungen' };
const endpunktBereich = b => RUBRIK_ENDPUNKT[b] || b;
// Feste Feldwerte, die eine Pseudo-Rubrik beim Speichern immer mitschickt.
const RUBRIK_FESTWERTE = {
  erwerbskosten: { kategorie: 'Erwerbsnebenkosten', turnus: 'einmalig',
                   absetzbar: false },
};
const ERWERB_KATEGORIE = 'Erwerbsnebenkosten';

/* N270 — Renovierungen sind KEIN Eintrag in BEREICHE: sie haben eigene
   Endpunkte (`/objekte/{slug}/renovierungen`, `/renovierungen/{rid}`) und eine
   eigene Seite, genau wie die Grundschulden. Beschrieben werden sie trotzdem
   hier, damit Titel und Einzahl an EINER Stelle stehen — die Objektseite und
   renovierung.html lesen beide von hier. */
const RENOVIERUNG_RUBRIK = {
  titel: 'Renovierungen', einzahl: 'Renovierung', seite: 'renovierung.html',
};

/** Die Beschreibung eines Bereichs — beim Grundstück in seiner Sprache.
    „Steuer & Zahlungen" heisst dort schlicht „Finanzamt" (CCCIV). */
const cfgFuer = (bereich) => {
  if (bereich === 'erwerbskosten') return ERWERB;
  if (!istGrundstueck()) return BEREICHE[bereich];
  if (bereich === 'mieten') return { ...BEREICHE.mieten, ...PACHT };
  if (bereich === 'zahlungen') {
    return { ...BEREICHE.zahlungen, titel: 'Finanzamt', ikon: 'Finanzamt' };
  }
  return BEREICHE[bereich];
};

/* CCCLVI — die zwei Modi, wie der Verkehrswert/Marktwert erfasst wird. Der Wert
   wird als lesbarer Text gespeichert (wie objektart/erwerbsart). */
const VERKEHRSWERT_GESAMT = 'Für das ganze Objekt';
const VERKEHRSWERT_EINHEIT = 'Je Einheit einzeln';
const istEinheitswert = (o) => o?.verkehrswert_modus === VERKEHRSWERT_EINHEIT;

/* Stammdaten des Objekts: dieselbe Feldbeschreibung für Anzeige und Formular. */
const STAMMFELDER = [
  { k: 'name', l: 'Name', typ: 'text', pflicht: true },
  // CCCXXX — die Objektart bestimmt, wie das Haus gedacht ist. Weit oben, weil
  // sie den Charakter des Objekts festlegt.
  { k: 'objektart', l: 'Objektart', typ: 'auswahl', ohneLeer: true,
    vorgabe: 'Mehrfamilienhaus',
    werte: ['Einfamilienhaus', 'Reihenhaus', 'Mehrfamilienhaus', 'Villa',
            'Zwei-/Doppelhaus', 'Einzelne Wohnung', 'Bauernhof', 'Gewerbe',
            'Grundstück'] },
  { k: 'strasse', l: 'Straße', typ: 'text' },
  { k: 'plz', l: 'PLZ', typ: 'text' },
  { k: 'ort', l: 'Ort', typ: 'text' },
  { k: 'flaeche', l: 'Wohnfläche (manuell)', typ: 'number', schritt: '0.01',
    einheit: 'm²', lex: 'wohnflaeche',
    note: 'Optional. Die Wohnfläche summiert ImmoCalc aus den Einheiten. Hier '
        + 'nur eintragen, wenn du sie unabhängig führen willst — weicht sie von '
        + 'den Einheiten ab, weist ImmoCalc darauf hin. Maßgeblich bleibt die '
        + 'aus den Einheiten berechnete Fläche.' },
  // CCLIV — die Grundstücksfläche (Grund und Boden) lässt sich für jede
  // Immobilie eintragen, nicht nur für den Grundstückstyp: auch zu einem
  // normalen Haus will man oft wissen, wie viel Grund dazugehört. Beim
  // Grundstückstyp steht dasselbe Feld im Grundstück-Block (siehe GRUNDFELDER),
  // deshalb hier für diesen Typ ausgeblendet.
  { k: 'grundstueck_flaeche', l: 'Grundstücksfläche / Grund', typ: 'number',
    schritt: '0.01', einheit: 'm²' },
  // CCXXXV — wie die Immobilie ins Eigentum kam. Bei Kauf zählt der Kaufpreis
  // als AfA-Basis; bei Schenkung, Erbschaft oder Überlassung übernimmt man
  // stattdessen die AfA-Basis des Vorbesitzers.
  { k: 'erwerbsart', l: 'Erwerbsart', typ: 'auswahl', ohneLeer: true,
    vorgabe: 'Kauf', werte: ['Kauf', 'Schenkung', 'Erbschaft', 'Überlassung'],
    lex: 'erwerbsart' },
  { k: 'kaufpreis', l: 'Kaufpreis', typ: 'number', schritt: '0.01', geld: true, voll: true },
  { k: 'kaufdatum', l: 'Kauf-/Erbschaftsdatum', typ: 'date' },
  // CCCXXX — das Baujahr/Baudatum getrennt vom Kaufdatum: bei einer Erbschaft
  // gibt es kein sinnvolles Kaufdatum, wohl aber ein Baujahr.
  { k: 'baudatum', l: 'Baujahr / Baudatum', typ: 'date' },
  // CCCLVI — der Modus entscheidet, wie der Verkehrswert erfasst wird. Steht er
  // vor dem Wert, damit klar ist, worauf sich der folgende Wert bezieht.
  { k: 'verkehrswert_modus', l: 'Verkehrswert erfassen', typ: 'auswahl',
    ohneLeer: true, vorgabe: VERKEHRSWERT_GESAMT,
    werte: [VERKEHRSWERT_GESAMT, VERKEHRSWERT_EINHEIT], lex: 'verkehrswert',
    note: 'Für das ganze Objekt: ein Wert in den Stammdaten. Je Einheit einzeln: '
        + 'jede Einheit trägt ihren Verkehrswert, das Objekt zeigt die Summe.' },
  { k: 'verkehrswert', l: 'Verkehrswert', typ: 'number', schritt: '0.01', geld: true, voll: true,
    lex: 'verkehrswert' },
  // CCCXXX — Konto & Rücklage bilden einen eigenen Block: erst wer und wo
  // (Kontoinhaber, IBAN, Bank), dann was zurückgelegt ist (Stand, Sparrate).
  { k: 'kontoinhaber', l: 'Kontoinhaber', typ: 'text' },
  { k: 'iban', l: 'IBAN', typ: 'text', iban: true },
  { k: 'bank', l: 'Bank', typ: 'text' },
  // CCIX — Rücklagenkonto: zurückgelegtes Geld für die Immobilie und die
  // laufende Sparrate. Beides optional, jederzeit nachtragbar.
  { k: 'ruecklage_saldo', l: 'Rücklagenkonto (Stand)', typ: 'number',
    schritt: '0.01', geld: true, voll: true, lex: 'ruecklage',
    note: 'Zurückgelegtes Eigentümergeld für Instandhaltung und Sanierung — '
        + 'steht in der Wertentwicklung als eigene Zeile.' },
  { k: 'ruecklage_monatlich', l: 'Monatliche Rücklage', typ: 'number',
    schritt: '0.01', geld: true, lex: 'ruecklage' },
  // CCCI — Nießbrauch als aktivierbarer Block. Der Schalter trägt den Umbau
  // (`umbau: true`): geht er aus, verschwinden Berechtigter und Frist. Der
  // Berechtigte ist einer der Eigentümer (Auswahl, kein Freitext) — die Werte
  // füllt `stammfelder()` beim Öffnen aus der Eigentümerliste des Objekts.
  { k: 'niessbrauch_aktiv', l: 'Nießbrauch eingetragen', typ: 'schalter',
    vorgabe: false, umbau: true, lex: 'niessbrauch' },
  { k: 'niessbrauch_berechtigt', l: 'Nießbrauch: Berechtigter', typ: 'auswahl',
    werte: [], nurWennNiessbrauch: true },
  { k: 'niessbrauch_bis', l: 'Nießbrauch bis', typ: 'date',
    nurWennNiessbrauch: true },
];

/* CCVIII — die WEG-Ebene. Nur bei einem Objekt sichtbar, das Teil einer
   Wohnungseigentümergemeinschaft ist. Das Hausgeld ist Eigentümerkosten (an die
   WEG gezahlt), die Rücklagenzuführung der Sparanteil darin; der Verwalter ist
   die Hausverwaltung/Abrechnungsfirma, die die Nebenkosten für die Mieter
   verteilt. Der Schalter selbst schaltet die Ebene an oder aus. */
const WEGFELDER = [
  { k: 'weg', l: 'Teil einer Wohnungseigentümergemeinschaft', typ: 'schalter',
    vorgabe: false, lex: 'weg',
    note: 'An: die Hausverwaltung verteilt die Nebenkosten, du trägst die '
        + 'fertigen Werte je Mieter direkt in die Abrechnung ein. '
        + 'Aus: ImmoCalc verteilt selbst über einen Schlüssel.' },
  { k: 'hausgeld_monatlich', l: 'Hausgeld (monatlich)', typ: 'number',
    schritt: '0.01', geld: true, voll: true, lex: 'hausgeld',
    note: 'Was du monatlich an die WEG zahlst — ein Eigentümerkosten.' },
  { k: 'weg_ruecklage_zufuehrung', l: 'davon Rücklagenzuführung (mtl.)',
    typ: 'number', schritt: '0.01', geld: true, lex: 'ruecklage',
    note: 'Der Sparanteil im Hausgeld, der in die gemeinschaftliche Rücklage '
        + 'der WEG fliesst.' },
  { k: 'weg_verwalter', l: 'Hausverwaltung / Abrechnungsfirma', typ: 'text' },
];

/* Grundstücksangaben. `grundstueck_flaeche` steht bewusst neben `flaeche`:
   letzteres ist Wohn-/Nutzfläche und geht in den Verteilungsschlüssel
   „Fläche" ein — eine Ackerfläche dort verfälschte jede Abrechnung.

   Der Grundstückswert ist der Verkehrswert des Objekts: beim Grund und Boden
   ist das derselbe Wert, und so rechnet die Vermögensübersicht das Grundstück
   ohne Zutun mit. */
const GRUNDFELDER = [
  { k: 'grundstueck_flaeche', l: 'Grundstücksfläche', typ: 'number',
    schritt: '0.01', einheit: 'm²' },
  { k: 'grundstueck_nutzungsart', l: 'Nutzungsart', typ: 'auswahl',
    werte: ['Ackerland', 'Grünland', 'Wald', 'Bauerwartungsland', 'Gemischt',
            'Sonstiges'] },
  // CCCXXX — die Wirtschaftsart (grundstueck_wirtschaftsart) wird nicht mehr
  // gezeigt; das Modellfeld bleibt bestehen, nur ohne Formular- und Anzeigezeile.
  { k: 'gemarkung', l: 'Gemarkung', typ: 'text', lex: 'flurstueck' },
  { k: 'flurstueck', l: 'Flurstück', typ: 'text', lex: 'flurstueck' },
  { k: 'grundstueck_m2_preis', l: 'Wert je m² (geschätzt)', typ: 'number',
    schritt: '0.01', geld: true,
    note: 'Dein geschätzter Marktwert je m². ImmoCalc errechnet daraus den '
        + 'Grundstückswert (× Grundstücksfläche). Steht NICHT auf dem '
        + 'Finanzamts-Bescheid und ist etwas anderes als der Grundsteuerwert.' },
  // Die drei folgenden bilden die Rechenkette der Grundsteuer, in der
  // Reihenfolge, in der sie entsteht (CCXCVI).
  { k: 'grundsteuerwert', l: 'Grundsteuerwert', typ: 'number', schritt: '0.01',
    geld: true, voll: true, lex: 'grundsteuerwert',
    note: '① Vom Finanzamt — „Bescheid über den Grundsteuerwert". Bei Land-/'
        + 'Forstwirtschaft: Summe der Reinerträge × Kapitalisierungsfaktor (18,6), '
        + 'abgerundet auf volle 100 € (Eckenhaid: 144,60 € × 18,6 ≈ 2.689 € → '
        + '2.600 €).' },
  { k: 'grundsteuer_messbetrag', l: 'Steuermessbetrag', typ: 'number',
    schritt: '0.01', geld: true, lex: 'steuermessbetrag',
    note: '② Vom Finanzamt — „Bescheid über den Grundsteuermessbetrag" = '
        + 'Grundsteuerwert × Steuermesszahl (bei Land-/Forstwirtschaft 0,55 ‰; '
        + 'Eckenhaid: 2.600 € × 0,55 ‰ = 1,43 €).' },
  { k: 'grundsteuer_hebesatz', l: 'Hebesatz', typ: 'number', schritt: '1',
    einheit: '%', lex: 'hebesatz',
    note: '③ Von der GEMEINDE (Eckental), nicht vom Finanzamt — steht auf dem '
        + 'Grundsteuerbescheid der Stadt (Hebesatz Grundsteuer A). '
        + 'Steuermessbetrag × Hebesatz = Grundsteuer im Jahr.' },
];

/* CXLI — was eine Einheit ausmacht. Dieselbe Beschreibung trägt die Anzeige
   im Fokus und das Formular; die Feldnamen sind die des Modells. */
const EINHEITFELDER = [
  { k: 'bezeichnung', l: 'Bezeichnung', typ: 'text', pflicht: true },
  { k: 'nutzungsart', l: 'Nutzungsart', typ: 'auswahl', vorgabe: 'Wohnen',
    werte: ['Wohnen', 'WG', 'Büro', 'Gewerbe', 'Praxis', 'Laden', 'Lager',
            'Stellplatz', 'Garage', 'Sonstiges'], lex: 'nutzungsart' },
  { k: 'flaeche', l: 'Wohn-/Nutzfläche', typ: 'number', schritt: '0.01',
    einheit: 'm²', lex: 'wohnflaeche' },
  { k: 'terrasse', l: 'Terrasse / Balkon', typ: 'number', schritt: '0.01',
    einheit: 'm²', lex: 'terrassenflaeche' },
  // N227 — wie viel Prozent der Terrasse/Balkon-Fläche zur Wohn-/Nutzfläche
  // zählt (Wohnflächenverordnung: üblich 25–50 %). Vorgabe 50, wie der
  // bisherige feste Wert in der Verteilung.
  { k: 'terrasse_anteil_pct', l: 'davon zur Wohnfläche', typ: 'number',
    schritt: '1', einheit: '%', vorgabe: 50 },
  { k: 'nebenflaeche', l: 'Nebenfläche', typ: 'number', schritt: '0.01',
    einheit: 'm²', lex: 'nebenflaeche' },
  { k: 'stellplaetze', l: 'Stellplätze', typ: 'number', schritt: '1',
    lex: 'stellplatz' },
  // CCCXXXIII — €/m²-Ansätze je Flächenart. Aus ihnen leitet ImmoCalc eine
  // Kaltmiete her, die das Miet-Formular als überschreibbaren Vorschlag anbietet.
  // Der Mietpreis selbst gehört ans Mietverhältnis, nicht an die Einheit —
  // hier steht nur der Ansatz je Quadratmeter. Alle optional.
  { k: 'miete_qm_wohn', l: 'Miete je m² Wohn-/Nutzfläche', typ: 'number',
    schritt: '0.01', geld: true,
    note: 'Optional. Kaltmiete je m² Wohn-/Nutzfläche (inkl. voller '
        + 'Zusatz-Nutzflächen). Dient nur zum Herleiten eines Mietvorschlags — '
        + 'die tatsächliche Kaltmiete steht am Mietverhältnis.' },
  { k: 'miete_qm_neben', l: 'Miete je m² Nebenfläche', typ: 'number',
    schritt: '0.01', geld: true,
    note: 'Optional. Kaltmiete je m² Nebenfläche (Keller, Abstellraum).' },
  { k: 'miete_qm_gemein', l: 'Miete je m² Gemeinschaftsfläche', typ: 'number',
    schritt: '0.01', geld: true,
    note: 'Optional. Kaltmiete je m² anteiliger Gemeinschaftsfläche.' },
  // CLXXXVI — ein Verkehrswert je Einheit. Nur pflegen, wo er bekannt ist;
  // sonst bleibt der Wert am Haus maßgeblich. Er gewichtet die Zurechnung des
  // Objektwerts auf die Eigentümer.
  { k: 'verkehrswert', l: 'Verkehrswert', typ: 'number', schritt: '0.01',
    geld: true, voll: true, lex: 'verkehrswert',
    note: 'Optional. Ist er gesetzt, zählt diese Einheit mit ihm in der '
        + 'Vermögenssicht je Eigentümer; sonst gilt der Wert am Haus.' },
  // CXCIII — eine Einheit ganz aus der Nebenkostenabrechnung nehmen.
  { k: 'nk_abrechnung', l: 'Nimmt an der Nebenkostenabrechnung teil',
    typ: 'schalter', vorgabe: true,
    note: 'Aus: selbstgenutzt, separat abgerechnet oder gewerblich mit '
        + 'eigenem Zähler. Die Einheit zählt dann in keinem '
        + 'Verteilungsschlüssel mehr mit.' },
];

/* Beim Grundstück gibt es keine Wohnfläche und kein Hauskonto — die Zeilen
   stehen dort nicht ausgegraut herum, sie kommen gar nicht erst vor. Der
   Verkehrswert wandert in den Grundstücksblock. */
// CCXCVII — ein landwirtschaftliches Grundstück braucht vieles nicht: keine
// Straße (es ist ein Flurstück), keine AfA (Grund und Boden wird nicht
// abgeschrieben), kein Rücklagenkonto und kein Hauskonto. Diese Zeilen kommen
// dort gar nicht erst vor — der Verkehrswert wandert in den Grundstücksblock.
const OHNE_BEIM_GRUNDSTUECK = new Set([
  'flaeche', 'verkehrswert', 'grundstueck_flaeche',
  'strasse', 'baudatum',
  'ruecklage_saldo', 'ruecklage_monatlich',
  'bank', 'iban', 'kontoinhaber']);

/* CCCXXXVI — beim Grundstück bilden Stammdaten und Grundstücksangaben EINE
   Feldbeschreibung, von grob nach fein geordnet: was es ist (Objektart, Adresse
   inkl. Flurnummer, Fläche, Nutzungsart, geschätzter m²-Preis), wie es erworben
   wurde (Erwerbsart, Kaufpreis/-datum), die Grundsteuer-Kette und zuletzt der
   Nießbrauch. Ein einziges Formular bearbeitet alles (alle Felder gehören zum
   Objekt und werden an dieselbe Route gePATCHt); die Anzeige teilt es in die
   drei Blöcke Stammdaten / Erwerb & Kosten / Nutzung & Pacht. */
const feldAus = (pool, k) => pool.find(f => f.k === k);
const GRUND_STAMMFELDER = () => {
  const s = k => feldAus(STAMMFELDER, k);
  const g = k => feldAus(GRUNDFELDER, k);
  return [
    s('name'), s('objektart'),
    s('plz'), s('ort'),
    g('gemarkung'), g('flurstueck'),
    g('grundstueck_flaeche'), g('grundstueck_nutzungsart'),
    g('grundstueck_m2_preis'),
    s('erwerbsart'), s('kaufpreis'), s('kaufdatum'),
    g('grundsteuerwert'), g('grundsteuer_messbetrag'), g('grundsteuer_hebesatz'),
    s('niessbrauch_aktiv'), s('niessbrauch_berechtigt'), s('niessbrauch_bis'),
  ].filter(Boolean);
};

/* Die Stammfelder — typ- und zustandsabhängig (CCCI). `aktiv` ist der aktuelle
   Nießbrauch-Zustand: er entscheidet, ob Berechtigter und Frist mitkommen. Für
   das Formular übergibt der Aufrufer den Stand aus dem Schalter; für die Ansicht
   den gespeicherten Wert. Der Berechtigte bekommt ALLE app-weit geführten
   Eigentümer als Auswahl (CCCXXXV) — der Nießbraucher ist meist nicht Eigentümer
   dieses Objekts; Fallback bleibt die Eigentümerliste des Objekts. */
function stammfelder(aktiv = objekt?.niessbrauch_aktiv) {
  let felder = istGrundstueck() ? GRUND_STAMMFELDER() : STAMMFELDER;
  const berechtigte = alleEigentuemer.length ? alleEigentuemer : objektEigentuemer;
  felder = felder
    .filter(f => !(f.nurWennNiessbrauch && !aktiv))
    .map(f => f.k === 'niessbrauch_berechtigt'
      ? { ...f, werte: berechtigte } : f);
  return felder;
}

export { VERTRAGSARTEN, kreditFelder, felderFuer, uebernahmeAnbieten, BEREICHE, PACHT, ERWERB_ARTEN, ERWERB, RUBRIK_ENDPUNKT, endpunktBereich, RUBRIK_FESTWERTE, ERWERB_KATEGORIE, RENOVIERUNG_RUBRIK, cfgFuer, STAMMFELDER, WEGFELDER, GRUNDFELDER, EINHEITFELDER, OHNE_BEIM_GRUNDSTUECK, feldAus, GRUND_STAMMFELDER, stammfelder, istEinheitswert, VERKEHRSWERT_GESAMT, VERKEHRSWERT_EINHEIT };
