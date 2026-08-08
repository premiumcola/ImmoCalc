/* N216 — Geteilter Zustand der Dokumenten-Eingang-Seite.

   Die Fach-Module (filter, liste, plan, zeitraum, kostenart, ki, position,
   vorschau, scan, aktionen) teilen sich ihren mutierten Zustand hier. Ein
   exportiertes Primitiv waere in jedem importierenden Modul eine eigene
   Kopie — deshalb liegen alle veraenderlichen Zustaende auf einem Objekt `S`,
   dessen Eigenschaften ueberall dieselben sind (`S.gewaehlt`, `S.filter`,
   `S.daten`, …).

   Verhaltensgleich zum bisherigen Inline-Skript in eingang.html — nur der
   Ort aendert sich. */

/* ---- Konstanten ---------------------------------------------------------- */
export const jetzt = new Date().getFullYear();
export const ALLE = '';
// CCLVIII: Wert der „…anlegen"-Option im Zeitraum-Feld. Kein echter Zeitraum,
// sondern der Auftrag, den vorgeschlagenen erst anzulegen — deshalb ein
// Sentinel, der nie als id durchgeht.
export const ANLEGEN = '__anlegen__';
export const MONATE = ['Januar', 'Februar', 'März', 'April', 'Mai', 'Juni',
                       'Juli', 'August', 'September', 'Oktober', 'November',
                       'Dezember'];

/* ---- DOM-Referenzen ----------------------------------------------------- */
/* Das Modul-Skript laeuft am Ende des <body> — beim Import sind die Elemente
   also schon da. Ein einziges Auslesen und Cachen spart pro Aufruf ein
   getElementById. */
export const els = {
  liste: document.getElementById('liste'),
  sub: document.getElementById('sub'),
  zahl: document.getElementById('zahl'),
  fussnote: document.getElementById('fussnote'),
  pruefKnopf: document.getElementById('pruef'),
  zuruecksetzen: document.getElementById('zuruecksetzen'),
  bilanz: document.getElementById('bilanz'),
  blatt: document.getElementById('blatt'),
  bDok: document.getElementById('bDok'),
  spalteDok: document.getElementById('spalteDok'),
  leerBlatt: document.getElementById('leerBlatt'),
  bSchau: document.getElementById('bSchau'),
  bPlan: document.getElementById('bPlan'),
  bLesen: document.getElementById('bLesen'),
  bEin: document.getElementById('bEin'),
  bEinTags: document.getElementById('bEinTags'),
  bEinText: document.getElementById('bEinText'),
  bKiMeldung: document.getElementById('bKiMeldung'),
  bKi: document.getElementById('bKi'),
  bKiNeu: document.getElementById('bKiNeu'),
  bZeitraum: document.getElementById('bZeitraum'),
  bZeitHinweis: document.getElementById('bZeitHinweis'),
  bZiel: document.getElementById('bZiel'),
  bPosFach: document.getElementById('bPosFach'),
  bPosPlan: document.getElementById('bPosPlan'),
  bPos: document.getElementById('bPos'),
  bPosLos: document.getElementById('bPosLos'),
  bPosHinweis: document.getElementById('bPosHinweis'),
  bOk: document.getElementById('bOk'),
  bNeu: document.getElementById('bNeu'),
  bWeg: document.getElementById('bWeg'),
  bMeldung: document.getElementById('bMeldung'),
  bilanzWrap: document.getElementById('bilanz'),
  suche: document.getElementById('suche'),
  fArt: document.getElementById('fArt'),
  fJahr: document.getElementById('fJahr'),
  fStatus: document.getElementById('fStatus'),
  fKostenart: document.getElementById('fKostenart'),
  fObjektBtns: document.getElementById('fObjektBtns'),
  kaTrigger: document.getElementById('kaTrigger'),
  kaLabel: document.getElementById('kaLabel'),
  warteArchiv: document.getElementById('warteArchiv'),
  kameraKnopf: document.getElementById('kamera'),
  kameraFeld: document.getElementById('kameraFeld'),
  erneutFeld: document.getElementById('erneutFeld'),
  nkKontext: document.getElementById('nkKontext'),
  zielDlg: document.getElementById('zielDlg'),
  zielInfo: document.getElementById('zielInfo'),
  zielObjekt: document.getElementById('zielObjekt'),
  zielArt: document.getElementById('zielArt'),
  zielJahr: document.getElementById('zielJahr'),
  zielOk: document.getElementById('zielOk'),
};

/* ---- Der geteilte Zustand ----------------------------------------------- */
export const S = {
  /* Filter fuer die API-Abfrage. Leerer String = ALLE. */
  filter: { objekt: ALLE, kategorie: ALLE, kostenart: ALLE, jahr: ALLE,
            status: ALLE, suche: '' },
  /* Antwort der API: die Liste wird immer daraus neu gebaut. */
  daten: { dokumente: [], objekte: [], arten: [], jahre: [],
           kategorien: [], kostenarten: [] },
  /* id des Belegs, der im Pruefblatt liegt. */
  gewaehlt: null,
  /* Die Eingabefelder der gewaehlten Karte (leben nur, solange sie offen ist). */
  erfassung: null,
  /* Ob die Texterkennung serverseitig verfuegbar ist. */
  erkennungMoeglich: true,
  /* Auswahlfelder des Ablage-Dialogs (einmal gebaut, wiederverwendet). */
  zielFelder: null,
  /* Blob-Adresse der gezeigten Datei — beim Wechsel freigegeben. */
  vorschauAdresse: null,
  /* Laufnummer gegen ueberholende Ladevorgaenge (Preview + Kostenposition). */
  vorschauLauf: 0,
  posLauf: 0,
  /* Caches: die Zeitraeume und Kostenarten je Immobilie sowie die Ergebnisse
     der Texterkennung je Beleg. Letzterer spart die zweite Cloud-Abfrage. */
  zeitraeumeJeObjekt: new Map(),
  kostenartenJeObjekt: new Map(),
  erkanntJeBeleg: new Map(),
  /* Bleibt der Abschnitt „erledigt" ueber ein Neuzeichnen hinweg offen? */
  erledigtOffen: false,
  /* Zeitraum-Feld (auswahlfeld-Handle) + Liste + Vorschlag zum Anlegen. */
  zeitraumFeld: null,
  zeitraumListe: [],
  zeitraumVorschlag: null,
  /* Vorschau der Kostenposition-Buchung des gewaehlten Belegs (vom Server). */
  posPlan: null,
  /* Filter-Feld-Handles (auswahlfeld) — einmal gebaut, danach nachgefuellt. */
  fArt: null,
  fJahr: null,
  /* Kurzzeit-Timer: Tipp-Entprellung der Suche + „Wirklich?"-Rueckfrage. */
  tippuhr: 0,
  sicherUhr: 0,
};

/* ---- Die Beleg-Meldung ---------------------------------------------------
   Kurze Rueckmeldung am Fuss des Pruefblatts — kein globaler Toast, sondern
   an der gerade offenen Karte. Bewusst hier: sie ist der einzige direkte
   DOM-Zugriff, den mehrere Module teilen.

   N288 — sie hiess frueher `melde` und trug damit den Namen der projektweiten
   Toast-Funktion aus `immo.js`, bei voellig anderer Bedeutung der zweiten
   Angabe (dort 'pos'/'neg', hier 'gut'/'schlecht'). Wer aus Gewohnheit
   `melde('Gespeichert', 'pos')` schrieb, bekam eine stumm falsch eingefaerbte
   Zeile. Der eigene Name macht den Unterschied sichtbar. */
export const belegmeldung = (text, art) => {
  els.bMeldung.textContent = text;
  els.bMeldung.className = 'bmeldung ' + (art || '');
};
