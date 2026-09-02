/* N216 — geteilter Zustand der Objektseite. Andere Module lesen `daten`,
   `einheiten`, `bereicheDaten` … als Live-Bindungen; geschrieben wird nur hier
   über die Setter, die `laden()` und die Handler aufrufen. So bleibt eine
   einzige Quelle der Wahrheit über alle Module hinweg erhalten
   (ES-Modul-Live-Bindings). */

/* Die aktuell geladene Objekt-Antwort (`/objekte/{slug}` — samt zeitraeume,
   nachpflege, einheiten). */
export let daten = null;
/* Die Einheiten des Hauses — gebraucht von der Hausebene, vom Fokus und von
   den Blasen im Mietformular. Ein Grundstück hat keine. */
export let einheiten = [];
/* Die Einheit, auf die gerade geschaut wird — null heisst: das ganze Haus. */
export let fokus = null;
/* CCXXIX — Grundschulden auf diesem Objekt. Nur am Haus gepflegt, nicht in
   der Einheiten-Ansicht — wie die Kredite auch. */
export let grundschulden = [];
/* CCCIX — die geladenen Bereiche, damit der Zuordnen-Dialog die vorhandenen
   Einträge einer Rubrik anbieten kann. */
export let bereicheDaten = {};
/* CCCLXXX (a) — die Zähler des Objekts (mit ihrem Anfangsstand-Zustand) für die
   Anfangszählerstand-Rubrik unter den Abrechnungszeiträumen. Nur gelesen. */
export let zaehlerListe = [];
/* N141 — der Zeitraum, über den die Zähler-Konfig erreichbar ist — für den Weg
   dorthin („Zähler verwalten") und für den Fall, dass es noch gar keine Zähler
   gibt. */
export let erststandZiel = null;

export function setDaten(v) { daten = v; }
export function setEinheiten(v) { einheiten = v; }
export function setFokus(v) { fokus = v; }
export function setGrundschulden(v) { grundschulden = v; }
export function setBereicheDaten(v) { bereicheDaten = v; }
export function setZaehlerListe(v) { zaehlerListe = v; }
export function setErststandZiel(v) { erststandZiel = v; }
/* ---- Dialog-Zustand — geteilt zwischen formular.js und handlers.js ---- */

/* Die Felder, die gerade im Dialog stehen. Beim Speichern wird genau das
   ausgelesen, was auch gezeigt wurde — bei den Verträgen hängt das an der
   Vertragsart und lässt sich nicht aus dem Bereich allein ableiten. */
export let dialogFelder = [];
/* Baut den offenen Dialog mit anderen Feldern neu auf, ohne das Eingetippte
   zu verlieren. Gesetzt von `formular`, gerufen vom Auswahlfeld mit `umbau`. */
export let dialogUmbau = null;

export function setDialogFelder(v) { dialogFelder = v; }
export function setDialogUmbau(v) { dialogUmbau = v; }

/* Beim Speichern zu entfernende Bewohner. Erst dann, nicht beim Antippen —
   ein versehentlicher Druck lässt sich so noch mit Abbrechen zurücknehmen. */
export let bewohnerWeg = [];
export function setBewohnerWeg(v) { bewohnerWeg = v; }
export function pushBewohnerWeg(bid) { bewohnerWeg.push(bid); }

/* Die Felderliste für den „Eigentümer zuordnen"-Dialog. Wird erst gefüllt,
   wenn die Eigentümer-Liste geladen ist (dort steht die Auswahl drin) — bis
   dahin leer. Der Submit-Handler liest sie beim Speichern aus. */
export let ANTEILFELDER = [];
export function setAnteilfelder(v) { ANTEILFELDER = v; }

/* ---- Katalog-Konstanten (unveränderlich) -------------------------------- */

/* CCCIV — jede Rubrik trägt ihr Symbol in der Überschrift, in der Farbe der
   Rubrik. Dieselbe Zuordnung nutzt der Dokumentenbaum, damit oben und unten
   dieselbe Sprache gesprochen wird. */
export const RUBRIKFARBE = {
  notarvertraege: 'var(--teal)', zahlungen: 'var(--amber)',
  mieten: 'var(--pos)', versicherungen: 'var(--soft)',
  kredite: 'var(--neg)', grundstueck: 'var(--teal-d)',
  erwerbskosten: 'var(--amber)',
  // N270 — Renovierungen stehen bewusst neben den einmaligen
  // Erwerbsnebenkosten und teilen deren Amber: beides ist Geld, das einmalig
  // ins Objekt fliesst, nicht laufender Betrieb.
  renovierungen: 'var(--amber)',
};

/* CCLXXVIII — welcher Bereich welchen Entwurfstyp am Backend hat. Nur diese
   Bereiche können vorläufige (orange) Einträge tragen; alles andere ignoriert
   `vorlaeufig` einfach. */
export const ENTWURF_TYP = {
  mieten: 'miete', versicherungen: 'versicherung', kredite: 'kredit',
  notarvertraege: 'notarvertrag', zahlungen: 'zahlung', erwerbskosten: 'zahlung',
};
// Rubrik (Frontend) → Eintragstyp (Backend `an_typ`), inkl. Nebenkosten. Die
// Detailansicht (CCCXIII) holt darüber die Belege eines Eintrags.
// Erwerbsnebenkosten sind Zahlungen — dieselbe Typkennung wie „zahlungen".
// N331c — Grundschulden sind keine BEREICHE-Rubrik (eigene Endpunkte, siehe
// GRUNDSCHULDFELDER unten) und kennen deshalb kein `vorlaeufig` — direkt
// hier gesetzt statt über `ENTWURF_TYP`.
export const AN_TYP = { ...ENTWURF_TYP, nebenkosten: 'kostenposition',
                        erwerbskosten: 'zahlung', grundschulden: 'grundschuld' };
/* CCCLXVII — welche Dokumentart ein direkt am Eintrag abfotografierter Beleg
   bekommt. Sie entscheidet über Ablageordner und Dateinamen (`ZIELORDNER`,
   `ARTKUERZEL` im Backend); die Rubrik allein sagt das nicht. Was hier fehlt,
   landet unter „Sonstiges" — nie geraten. */
export const SCAN_KATEGORIE = {
  mieten: 'Mietvertrag', versicherungen: 'Versicherung', kredite: 'Kredit',
  notarvertraege: 'Notarvertrag', nebenkosten: 'Nebenkosten',
  zahlungen: 'Steuer',
  // N331b — Fund: stand hier fälschlich auch 'Steuer'. Das Backend kennt
  // `ZIELORDNER["Erwerbsnebenkosten"] = "40_Kauf_Eigentum_Finanzierung"`
  // schon seit N283d, aber ohne diesen Wert schickte das Frontend weiterhin
  // 'Steuer' — jeder Erwerbsnebenkosten-Scan landete trotz des Backend-Fixes
  // weiter unter 70_Steuer_Finanzamt statt beim Kauf.
  erwerbskosten: 'Erwerbsnebenkosten',
  // N331c — der KI-Scan für Grundschulden (Eintragungsbekanntmachung des
  // Grundbuchamts) landet bei denselben Kauf-/Finanzierungsunterlagen wie
  // Notarvertrag und Kredit.
  grundschulden: 'Grundschuld',
};
/* Wie der Beleg an dieser Stelle heisst. „Mietvertrag abfotografieren" sagt
   mehr als „Beleg abfotografieren", wo es nur einen geben kann. */
export const SCAN_WORT = { mieten: 'Mietvertrag', notarvertraege: 'Notarvertrag' };
// CCCLXXXII — am Mietverhältnis mehr als nur der Vertrag: Übergabeprotokolle
// und Kautionsunterlagen. Der Typ steckt in Bezeichnung/Dateiname; abgelegt
// wird wie der Mietvertrag (SCAN_KATEGORIE.mieten).
// Jeder Eintrag ist [voll, kurz] oder [voll, kurz, auchErkennenAls] — `voll`
// ist der Name, unter dem neu abfotografiert wird; `auchErkennenAls` (N223)
// erkennt zusätzlich schon vorhandene Dokumente mit anderem Namen als
// dieselbe Zeile — z. B. eine bereits hochgeladene Lohnsteuerbescheinigung
// zählt als Mieterselbstauskunft, statt als eigene Zeile zu fehlen.
export const SCAN_TYPEN = { mieten: [
  ['Mietvertrag', 'Mietvertrag'],
  ['Übergabeprotokoll Einzug', 'Übergabe Einzug'],
  ['Mietkautionskonto', 'Kautionsunterlagen'],
  ['Mieterselbstauskunft', 'Selbstauskunft', ['Lohnsteuerbescheinigung']],
  ['Abnahmeprotokoll Rauchwarnmelder', 'Rauchwarnmelder'],
  ['Übergabeprotokoll Auszug', 'Übergabe Auszug'],
] };

export const KAMERA_ICON = `<svg viewBox="0 0 24 24" width="15" height="15" fill="none"
  stroke="currentColor" stroke-width="1.9" stroke-linecap="round"
  stroke-linejoin="round" aria-hidden="true">
  <path d="M4 8.5h3.2L9 6h6l1.8 2.5H20a1 1 0 0 1 1 1V18a1 1 0 0 1-1 1H4a1 1 0
    0 1-1-1V9.5a1 1 0 0 1 1-1Z"/><circle cx="12" cy="13.5" r="3.2"/></svg>`;

export const GAUGE_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
  stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"
  aria-hidden="true"><path d="M5 16.5a7 7 0 0 1 14 0"/>
  <path d="M12 16.5l3.6-3.1"/><path d="M12 6.5V8M5.7 9.7l1 1M18.3 9.7l-1 1"/>
  <circle cx="12" cy="16.5" r="1.15" fill="currentColor" stroke="none"/></svg>`;

// CCCXXIV — zwischen welchen Rubriken sich ein Eintrag umklassifizieren lässt
// (der „Erwerb/Steuer"-Cluster). Der Wert ist zugleich der Bereich und das
// Backend-Ziel.
export const UMKLASS_ZIELE = [
  { wert: 'erwerbskosten', titel: 'Einmalige Erwerbsnebenkosten' },
  { wert: 'zahlungen', titel: 'Finanzamt' },
  { wert: 'notarvertraege', titel: 'Notarverträge' },
];
export const kannUmklassifizieren = b => UMKLASS_ZIELE.some(z => z.wert === b);

/* ---- Zuordnen-Dialog: welche Rubriken es überhaupt gibt ------------------ */
export const RUBRIK_WAHL = [
  { wert: 'notarvertraege', titel: 'Notarverträge', ikon: 'Notarvertrag',
    typ: 'notarvertrag', wiederkehrend: false },
  { wert: 'zahlungen', titel: 'Finanzamt', ikon: 'Finanzamt',
    typ: 'zahlung', wiederkehrend: true },
  { wert: 'nebenkosten', titel: 'Nebenkosten', ikon: 'Nebenkosten',
    typ: 'kostenposition', wiederkehrend: true },
  // CCCXIX — dritte Belegart: einmalige Erwerbsnebenkosten (Notar, Makler …).
  { wert: 'erwerbskosten', titel: 'Erwerbsnebenkosten', ikon: 'Erwerbsnebenkosten',
    typ: 'zahlung', wiederkehrend: false },
  { wert: 'mieten', titel: 'Pacht & Erträge', ikon: 'Miete',
    typ: 'miete', wiederkehrend: true, nurHaus: false },
  { wert: 'versicherungen', titel: 'Versicherungen', ikon: 'Versicherung',
    typ: 'versicherung', wiederkehrend: true, nurHaus: true },
  { wert: 'kredite', titel: 'Kredite', ikon: 'Kredit',
    typ: 'kredit', wiederkehrend: true, nurHaus: true },
];

/* ---- Feste Feldsätze ---------------------------------------------------- */

export const ZEITRAUMFELDER = [
  { k: 'jahr', l: 'Abrechnungsjahr', typ: 'number', pflicht: true,
    vorgabe: new Date().getFullYear() - 1 },
];

/* CCXXIX: Grundschulden ---------------------------------------------------
   Eine eigene Liste, kein Eintrag in BEREICHE: die Endpunkte liegen anders
   (`/objekte/{slug}/grundschulden`, `/grundschulden/{id}`, nicht der
   generische `/stammdaten/{bereich}/{id}`-Weg) — wie bei den Einheiten. */
export const GRUNDSCHULDFELDER = [
  { k: 'betrag', l: 'Betrag', typ: 'number', schritt: '0.01', geld: true,
    voll: true, pflicht: true },
  // N331c — Nutzer: „Die Eingabe buggt eine Zeile drunter rum" — `rang` war
  // das einzige Zahlenfeld dieser Maske ohne `geld`/`einheit` und entging
  // damit dem in `formular.js` dokumentierten Umweg über `type="text"`
  // (ein natives `type="number"` setzt seine Pfeilchen genau dort hin, wo
  // sonst der Cursor steht). Ausserdem ist ein Rang oft gar keine reine
  // Zahl: „vor Abt. II/1", „nach Abt. III/1" — echte Werte aus der
  // Grundbuch-Praxis, die ein Zahlenfeld ohnehin nie hätte fassen können.
  { k: 'rang', l: 'Rang', typ: 'text', lex: 'rang' },
  { k: 'grundbuch_blatt', l: 'Grundbuchblatt', typ: 'text', lex: 'grundbuch' },
  { k: 'glaeubiger', l: 'Gläubiger', typ: 'text' },
  { k: 'brief', l: 'Briefgrundschuld', typ: 'schalter', vorgabe: false,
    lex: 'brief-buchgrundschuld',
    note: 'Aus: Buchgrundschuld — kein Grundschuldbrief ausgestellt.' },
  { k: 'notiz', l: 'Notiz', typ: 'text' },
];

/* ---- Palette und Textbausteine ------------------------------------------ */

/* N19: eine Farbe je Mietverhältnis (nach Startdatum). */
export const MIET_PALETTE = ['#0F6E5C', '#916212', '#B24229', '#5B3E8F',
                             '#1F6F8B', '#2E7D4F', '#8A6D1E'];

export const MONATS_KURZ = ['Jan', 'Feb', 'Mär', 'Apr', 'Mai', 'Jun',
                            'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dez'];

/* CXLVIII — Kopplungstext für Zinssatz und Zinsanteil je Monat. */
export const ZINSTEXT = {
  ja: 'Eines von beidem genügt — das andere ergibt sich aus der Restschuld.',
  nein: 'Ohne Restschuld lässt sich das nicht umrechnen — trag sie oben ein.',
};
