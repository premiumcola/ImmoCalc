/* N215 — Modul-Zustand fuer die Tankstelle-Seite.

   Die Fach-Module (matrix, abrechnung, verlauf, blatt, nutzer, zuordnen,
   ladungen, versand, infos) teilen sich hier ihre mutierten Werte. Ein
   exportiertes Primitiv waere in jedem importierenden Modul eine eigene
   Kopie — deshalb liegen alle veraenderlichen Zustaende auf einem Objekt `S`,
   dessen Eigenschaften ueberall dieselben sind (`S.objektSlug`,
   `S.quartaleGewaehlt` etc.).

   Verhaltensgleich zum bisherigen Inline-Skript in tankstelle.html — nur der
   Ort aendert sich. */
import { esc, melde } from '../immo.js';

export const S = {
  /* Die aktuell gewaehlte Immobilie. */
  objektSlug: '',
  /* Die geladenen Nutzer der Ladestation. */
  nutzerListe: [],
  /* Der geholte Gesamtverlauf, aus dem die paginierte Tabelle blaettert und
     die Abrechnungs-Vorschau (N184) ihre Monate zieht — kein zweiter
     API-Aufruf noetig. */
  verlaufMonate: [],
  verlaufSumme: {},
  verlaufSeite: 0,
  /* N169 — mehrere Quartale zusammen waehlbar, einzelne Monate abwaehlbar.
     `[0]` ist die Abkuerzung fuer „ganzes Jahr", sonst eine Teilmenge aus
     1..4; `ausMonate` haelt die abgewaehlten Monatsnummern. */
  quartaleGewaehlt: [0],
  ausMonate: new Set(),
  /* 0 = noch nicht gesetzt → dann gilt das laufende Jahr. */
  jahrGewaehlt: 0,
  /* Jahre mit Verbrauch (aus dem Verlauf). */
  jahreListe: [],
  /* N165/2 — Autoversand-Schalter und Mehrnutzer-Zuordnung des Objekts. */
  einst: { autoversand: false, regeln: [], ausschluss: [] },
  /* N182 — die abgerechnet-Marker: [{jahr, quartal, monat, nutzer_id}]. Sie
     tragen den Haken an den Quartals-Chips und sperren den Versand bereits
     abgerechneter Perioden. */
  abgerechnet: [],
  /* N179 — die zuletzt geholte Abrechnung; die HTML-Vorschau liest Satz,
     Herkunft und die Nutzerzeile daraus, statt ein A4-PDF zu laden. */
  letzteAbrechnung: null,
  /* Nutzer, dessen Vorschau gerade aufgeklappt ist; der Timer entprellt das
     Neuladen der Vorschau bei rascher Monatsauswahl. */
  offeneVorschau: 0,
  vorschauTimer: 0,
  /* Nutzer, dessen Stammdaten gerade offen sind. */
  offeneBearbeitung: 0,
  /* Ist die „Nutzer anlegen"-Eingabe aufgeklappt? */
  addOffen: false,
  /* Die Person-Auswahl fuer neue Ladungen (auswahlfeld-Handle). */
  buchungsWahl: null,
};

/* ---- Farben ---------------------------------------------------------
   Drei Kostenbloecke, drei Farben — der Nutzer rechnet Strom ueber genau
   diese drei (N143). PV und Akku sind Geschwister im Ton, weil beide eigener
   Strom sind; Netz steht dagegen. */
export const NETZ = '#916212';        /* --amber: zugekaufter Strom */
export const PV = '#0F6E5C';          /* --teal: direkt vom Dach */
export const AKKU = '#6BA697';        /* heller Teal-Ton: aus dem Speicher */
export const EIGEN = '#0F6E5C';       /* PV + Akku, wenn beide nicht trennbar sind */
export const OFFEN = '#B7C2C4';       /* Herkunft unbekannt — nie als 0 zeigen */

/* ---- Kalender ------------------------------------------------------- */
export const MONKURZ = ['Jan', 'Feb', 'Mär', 'Apr', 'Mai', 'Jun',
                        'Jul', 'Aug', 'Sep', 'Okt', 'Nov', 'Dez'];
export const QMON = { 1: [1, 2, 3], 2: [4, 5, 6], 3: [7, 8, 9], 4: [10, 11, 12] };

/* ---- Grafik-/Tabellen-Parameter ------------------------------------ */
export const TAB_PRO_SEITE = 5;      /* ~5 Zeilen je Seite (N188) — lieber
                                        mehr Seiten als eine lange Tabelle */
export const MIN_PRO_MONAT = 16.5;   /* schmalster Monat in der Grafik */
export const LABEL_BREITE = 26;      /* Platzbedarf eines Monatskuerzels */

/* ---- Zahlenformatter ------------------------------------------------ */
export const kwh = (n, stellen = 2) => (n ?? 0).toLocaleString('de-DE',
  { minimumFractionDigits: stellen, maximumFractionDigits: stellen }) + ' kWh';
export const proz = n => n == null ? '—'
  : n.toLocaleString('de-DE', { maximumFractionDigits: 1 }) + ' %';
export const zahl = (n, stellen = 2) => n == null ? '—'
  : n.toLocaleString('de-DE', { minimumFractionDigits: stellen,
                                maximumFractionDigits: stellen });
/* Vier Nachkommastellen wie in der Mail: bei einem Preis je kWh macht das
   vierte Zehntel-Cent den Unterschied zwischen „gerechnet" und „gerundet". */
export const satzText = s => s == null ? '—' : zahl(s, 4) + ' € je kWh';
/* Zweistellig — „18.01.2026" steht in einer Spalte ruhiger als „18.1.2026"
   und deckt sich mit der Schreibweise in der Mail. */
export const datum = iso => new Date(iso).toLocaleDateString('de-DE',
  { day: '2-digit', month: '2-digit', year: 'numeric' });

/* Jede gescheiterte Abfrage wird sichtbar — an Ort und Stelle und als kurze
   Meldung. „Nichts passiert" ist nie eine zulaessige Antwort. */
export function zeigeFehler(ziel, titel, fehler) {
  const text = String(fehler?.message || fehler || 'Unbekannter Fehler');
  ziel.innerHTML = `<div class="leer"><b>${esc(titel)}</b>${esc(text)}</div>`;
  melde(`${titel}: ${text}`, 'neg');
}
