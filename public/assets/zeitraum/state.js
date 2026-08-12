/* zeitraum/state.js — geteilter Modul-State + statische Konstanten.

   Der ganze Zeitraum-Bildschirm läuft mit einem gemeinsamen Datenstand
   (Zeitraum, Schlüssel-Vorschau, Ablese-Maske, Stromkette …). Vor der
   Modularisierung waren das freie let-Variablen im großen `<script>`; jetzt
   liegen sie hier und werden über named exports als *live bindings* von den
   Modulen gelesen. Ändert sich ein Wert (z. B. `daten = neuerStand`), muss
   das über die Setter unten laufen — sonst sehen andere Module die
   Änderung nicht.

   Reine Konstanten (BEREICHE, KOSTENART_ALIAS, STROM_ROLLEN, SORTIERUNG,
   HAKEN, ABGELEITET, NUR_EINHEIT_WAHL, WEG_ART, SK_BLOECKE, SK_FARBE,
   MESSEINHEITEN, KOSTENBLOCK_ORDER, WASSER_GRUPPE, KEINE_KAMERA) stehen
   ebenfalls hier, damit jedes Modul dieselben Bezugswerte hat. */

/* ---------- DOM-Anker (aus zeitraum.html) --------------------------------- */
export const zid = new URLSearchParams(location.search).get('z');
export const inhalt = document.getElementById('inhalt');
export const titel = document.getElementById('titel');
export const sub = document.getElementById('sub');

/* ---------- mutabler State (Setter für Neuzuweisungen) ------------------- */

export let daten = null;
export function setDaten(v) { daten = v; }

/* Welche Verteilungsschlüssel für dieses Objekt taugen und welche Gewichte
   sie ergäben — die Vorschau, bevor man sich festlegt. */
export let schluessel = null;
export function setSchluessel(v) { schluessel = v; }

/* CCLV — kostenfreie Themen-Anhänger: was am Zeitraum hängt (nach Kostenart
   gruppiert) und welche kostenfreien Belege sich noch anhängen ließen. */
export let anhaenger = null;
export function setAnhaenger(v) { anhaenger = v; }

/* Welche Zeilen der Verteilung kein Mieter sind, sondern unbelegte Zeit. */
export let leerstaende = new Set();
export function setLeerstaende(v) { leerstaende = v; }

export let ansicht = 'pruef';
export function setAnsicht(v) { ansicht = v; }

export let sortierung = 'status';
export function setSortierung(v) { sortierung = v; }

/* Welche Zeilenindizes gerade aufgeklappt sind. In-place mutiert. */
export const offen = new Set();

/* N189 — der Konfig-Modus (Positionen ein-/ausblenden + Pflicht/optional). */
export let konfigModus = false;
export function setKonfigModus(v) { konfigModus = v; }
export let konfigArten = null;
export function setKonfigArten(v) { konfigArten = v; }

/* „Nur eine Einheit/Person" — für welche Position der Einheit-Auswähler
   offen ist, solange keine Einheit gesetzt wurde. */
export let einzelWahl = null;
export function setEinzelWahl(v) { einzelWahl = v; }

/* CCCLIX — offene Vorab-Panels je Position (Set von position_id). */
export const vorabOffen = new Set();

/* Welche Position gerade einen Beleg erwartet — gesetzt beim Klick auf den
   Scan-Knopf, gelesen wenn die Kamera zurückkommt. */
export let scanZiel = null;
export function setScanZiel(v) { scanZiel = v; }

/* NK-STRUKTUR — Ablese-Maske und daraus abgeleitete Chip-Karte. */
export let ablesungMaske = null;
export function setAblesungMaske(v) { ablesungMaske = v; }
export let chipMap = new Map();
export function setChipMap(v) { chipMap = v; }

/* N58 — die realen Einheiten-Bezeichnungen des Objekts. */
export let objektEinheiten = [];
export function setObjektEinheiten(v) { objektEinheiten = v; }

/* N157 — Ladeprotokoll-Zug der Wallbox. */
export let eautoZug = null;
export function setEautoZug(v) { eautoZug = v; }

/* N142/N157 — Stromkette einmal je Laden holen. */
export let stromketteDaten = null;
export function setStromketteDaten(v) { stromketteDaten = v; }

/* N60/N67 — Auf-/Zu-Zustand der Zählerstände-Panels (Block-Namen). */
export const zaehlerOffen = new Set();
/* N361 — welche Einheiten-Gruppe in der Jahreswert-Tabelle ZU ist
   (Vorgabe: alle offen, damit man der Reihe nach eintragen kann). */
export const zaehlerEinheitZu = new Set();

/* N68 — generische Anzeigenamen je Zähler-id. */
export let zLabels = new Map();
export function setZLabels(v) { zLabels = v; }

/* N114/N118/N198a — Heizkosten & HKV-Bestand. */
export let heizoelKosten = 0;
export function setHeizoelKosten(v) { heizoelKosten = v; }
export let wwKosten = 0;
export function setWwKosten(v) { wwKosten = v; }
export let heizverteiler = [];
export function setHeizverteiler(v) { heizverteiler = v; }

/* N118 — Cache der Wasser-Verteilung (Warmwasser-Split greift darauf zu). */
export let wasserDetailCache = null;
export function setWasserDetailCache(v) { wasserDetailCache = v; }

/* N82b — Deckung aus den NK-Vorauszahlungen. */
export let deckungAbschlaege = null;
export function setDeckungAbschlaege(v) { deckungAbschlaege = v; }
export let deckungUmgelegt = null;
export function setDeckungUmgelegt(v) { deckungUmgelegt = v; }

/* N113 — Umschalter Personen/Fläche für den Haupthaus-Rest. */
export let wasserSchluessel = 'personen';
export function setWasserSchluessel(v) { wasserSchluessel = v; }

/* N280 — der WEG-Stand dieses Zeitraums: `{aktiv, stand, vorauszahlungen}`
   aus `GET /zeitraeume/{id}/weg`. Ist er `aktiv`, tritt die Dateiübernahme an
   die Stelle der Belegjagd. `null`, solange nichts geladen wurde. */
export let wegDaten = null;
export function setWegDaten(v) { wegDaten = v; }

/* N280 — was die letzte Übernahme gemeldet hat: `uebersprungen` (eine
   Handeingabe gleichen Namens hat gewonnen) und `entfernt` (eine WEG-Zeile aus
   einem früheren Lauf kommt im neuen Beleg nicht mehr vor). Beides steht NUR
   in der Antwort von `/weg/uebernehmen`, nicht im gelesenen Stand — ohne diese
   Merkstelle fehlte ein Betrag ohne sichtbaren Grund. */
export let wegMeldung = null;
export function setWegMeldung(v) { wegMeldung = v; }

/* ---------- Konstanten (nie neu zugewiesen) ------------------------------ */

/* Geräte ohne Kamera (Schreibtisch, Maus): dort genügt EIN neutraler Knopf,
   der den lokalen Datei-Dialog öffnet. */
export const KEINE_KAMERA = window.matchMedia('(pointer: fine)').matches;

export const SORTIERUNG = {
  status: (a, b) => Number(a.erledigt) - Number(b.erledigt) ||
                    (b.betrag || 0) - (a.betrag || 0),
  betrag: (a, b) => (b.betrag || 0) - (a.betrag || 0),
  name: (a, b) => a.kostenart.localeCompare(b.kostenart, 'de'),
};

export const HAKEN = {
  erledigt: ['gruen', '✓'],
  offen: ['rot', '!'],
  fehlt: ['grau', '–'],
  // N198a — bernsteinfarbene Warnung: berechnet, aber noch nicht verteilt.
  warnung: ['amber', '▲'],
};

/* Fünf Bereiche in fester Anzeige-Reihenfolge. Geprüft wird Bereich 2
   (Heizung/Warmwasser) VOR Bereich 1, damit „Warmwasser" zu 2 fällt. */
export const BEREICHE = [
  { titel: 'Wasser & Abwasser',
    muster: ['wasser', 'abwasser', 'kanal', 'niederschlag', 'entwaesser'] },
  { titel: 'Heizung & Warmwasser',
    muster: ['heiz', 'oel', 'gas', 'fernwaerme', 'warmwasser', 'brennstoff'] },
  { titel: 'Strom & Beleuchtung',
    muster: ['strom', 'beleucht'] },
  { titel: 'Reinigung & Außenanlagen',
    muster: ['reinig', 'winterdienst', 'streu', 'garten', 'gruenpflege', 'muell',
             'entsorg', 'hausmeist', 'hauswart', 'schornstein', 'kamin', 'aufzug',
             'fahrstuhl'] },
  { titel: 'Versicherung & Steuer',
    muster: ['versicher', 'haftpflicht', 'grundsteuer', 'steuer', 'police'] },
  { titel: 'Verwaltung & Sonstiges', muster: [] },
];
export const BEREICH_IKON = ['Wasser', 'Heizung', 'Strom', 'Müll',
                             'Versicherung', 'Hausverwaltung'];
// Prüf-Reihenfolge: Heizung zuerst, dann Wasser/Strom/Reinigung/Versicherung.
export const BEREICH_PRUEF = [1, 0, 2, 3, 4];

export const KOSTENART_ALIAS = { 'Müll': 'Abfallwirtschaft',
  'Heizkosten': 'Heizöl & Lieferungen', 'Warmwasser': 'Warmwassererzeugung',
  'Heizung': 'Heizkörper Wärmemenge',
  'Strom': 'Stromverbrauch und Kosten' };
// N213 — die Aliasse für Heiz-/Strom-Zeilen erklären Laufer-spezifische Stufen.
export const LAUFER_ALIAS_KEYS = new Set(['Heizkosten', 'Warmwasser',
                                          'Heizung', 'Strom']);

/* Anzeige-Titel je Wasser-Art in der Zählerübersicht. */
export const WASSER_GRUPPE = { Kaltwasser: 'Kaltwasser', Warmwasser: 'Warmwasser',
  Waschmaschine: 'Waschmaschinen', Gartenwasser: 'Gartenwasser' };

export const KOSTENBLOCK_ORDER = ['Wasser', 'Heizung', 'Strom', 'Sonstige'];

/* Welche Schlüssel sich aus den Stammdaten ergeben (verteilung.py: ableitbar). */
export const ABGELEITET = new Set(['flaeche', 'personen', 'einheiten', 'bewohnermonate']);
/* Der Sonder-Eintrag am Ende der „Verteilen nach"-Auswahl. */
export const NUR_EINHEIT_WAHL = '__nur_einheit__';

/* CCVIII — Kostenart-Muster für den WEG-Direkteintrag. */
export const WEG_ART = einheit => `Nebenkosten (WEG) · ${einheit}`;

/* N120 — die vier Rollen einer Strom-Zeile. */
export const STROM_ROLLEN = {
  gesamt: { titel: 'Gesamtverbrauch (absolut)', typ: 'direkt',
            haupt: false, reihenfolge: 1 },
  gesamt_stand: { titel: 'Gesamtverbrauch (2 Stände)', typ: 'gemessen',
                  haupt: false, reihenfolge: 1 },
  gemessen: { titel: 'Zwischenzähler (2 Stände)', typ: 'gemessen',
              haupt: true, reihenfolge: 5 },
  direkt: { titel: 'Jahreswert ohne Zähler', typ: 'direkt',
            haupt: true, reihenfolge: 6 },
  rest: { titel: 'Verbrauch Haus (Rest)', typ: 'rest',
          haupt: true, reihenfolge: 9 },
};

/* Die drei Stromkette-Blöcke in fester Reihenfolge — teuer nach günstig. */
export const SK_BLOECKE = [['netz', 'Netz', 'zugekauft'], ['pv', 'PV direkt', 'vom Dach'],
  ['akku', 'Akku', 'aus dem Speicher']];
export const SK_FARBE = { netz: 'var(--amber)', pv: 'var(--teal)', akku: 'var(--pos)' };

export const MESSEINHEITEN = ['m³', 'kWh', 'Liter', 'Einheiten'];
