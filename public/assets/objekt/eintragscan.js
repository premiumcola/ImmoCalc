/* N263 — einen Eintrag aus einem Foto anlegen.
 *
 * Bisher gab es zu jeder Eintragsart nur die leere Maske: Notarvertrag,
 * Versicherung, Kredit — alles abtippen. Dabei steht das meiste auf dem Papier,
 * das ohnehin eingescannt werden soll.
 *
 * Der Ablauf ist derselbe wie beim Nebenkosten-Beleg (N250/N254), nur endet er
 * nicht bei der Ablage, sondern im Formular:
 *
 *     fotografieren → zuschneiden → Decke drüber → auslesen
 *       → Maske GEFÜLLT öffnen (jedes Feld änderbar) → speichern
 *       → Eintrag anlegen UND die Datei daran hängen
 *
 * Übersetzt wird auf dem Server (`feldzuordnung.py`): die Maske bekommt fertige
 * Feldwerte, hier wird nichts geraten. Der vorbereitete Scan wartet so lange in
 * `offen` — erst wenn der Eintrag steht und seine id hat, wandert die Datei in
 * die Cloud. Bricht der Nutzer im Formular ab, wurde nichts abgelegt.
 */
import { melde } from '../immo.js';
import { belegVorbereiten, belegAblegen } from '../belegscan.js';
import { analyseDecke } from '../belegbestaetigung.js';
import { cfgFuer, felderFuer } from '../objekt-felder.js?v=2';
import { slug } from '../objekt-state.js?v=2';
import { formular } from './formular.js';

/* Welche Ablage-Kategorie zu welcher Eintragsart gehört — dieselben Werte, die
   `cloudkern.ZIELORDNER` kennt. Fehlt eine, landet der Beleg unter
   „Sonstiges"; das ist richtig, nicht bloss ein Rückfall. */
const KATEGORIE = {
  notarvertraege: 'Notarvertrag',
  versicherungen: 'Versicherung',
  kredite: 'Kredit',
  mieten: 'Mietvertrag',
  zahlungen: 'Steuer',
};

/* Der Rubrikname ist PLURAL („notarvertraege"), `an_typ` am Beleg SINGULAR
   („notarvertrag") — siehe `_AN_TYP_MODELLE` in `routers/dokumente.py`. Ohne
   diese Übersetzung nähme der Server den Anhang nicht an und die Datei hinge
   an nichts. */
const AN_TYP = {
  notarvertraege: 'notarvertrag',
  versicherungen: 'versicherung',
  kredite: 'kredit',
  mieten: 'miete',
  zahlungen: 'zahlung',
};

/* Bereiche, die die Server-Zuordnung kennt (`feldzuordnung.ZUORDNUNG`). Nur
   dort lohnt der Scan-Weg — anderswo käme eine leere Maske heraus, und der
   Knopf verspräche etwas, das er nicht hält. */
export const SCANBAR = new Set(Object.keys(KATEGORIE));

/* Der vorbereitete, noch NICHT abgelegte Scan. Er wartet, bis der Eintrag
   gespeichert ist — vorher gibt es keine id, an die er gehören könnte. */
let offen = null;

/** Wartet ein Scan auf den gerade gespeicherten Eintrag? */
export const scanWartet = () => Boolean(offen);

/** Vergisst den vorbereiteten Scan (Formular abgebrochen oder verworfen). */
export function scanVerwerfen() { offen = null; }

/**
 * Hängt den vorbereiteten Scan an den frisch angelegten Eintrag.
 *
 * Bewusst NACH dem Speichern: Der Eintrag ist das Wichtige — schlägt die Ablage
 * fehl (Cloud weg, Zeitüberschreitung), steht er trotzdem, und der Nutzer
 * bekommt eine Meldung statt eines verlorenen Formulars. Der Scan wird dabei
 * immer vergessen, damit er nicht beim nächsten Speichern erneut hochgeht.
 */
export async function scanAnhaengen(bereich, id) {
  const paket = offen;
  offen = null;
  if (!paket || !id) return;
  try {
    await belegAblegen({
      ...paket,
      ziel: { ...paket.ziel, anTyp: AN_TYP[bereich], anId: id },
    }, paket.name || null);
  } catch (fehler) {
    melde(`${cfgFuer(bereich).einzahl} gespeichert — die Datei konnte aber `
      + `nicht abgelegt werden: ${fehler.message || fehler}`, 'neg');
  }
}

/** Die Kamera/Dateiauswahl öffnen und auf die Wahl warten. */
function dateienWaehlen() {
  return new Promise(fertig => {
    const feld = document.createElement('input');
    feld.type = 'file';
    feld.accept = 'image/*,application/pdf';
    feld.multiple = true;
    // Am Telefon direkt die Kamera — genau das will der Nutzer hier.
    feld.capture = 'environment';
    feld.hidden = true;
    document.body.appendChild(feld);
    feld.addEventListener('change', () => {
      const dateien = Array.from(feld.files || []);
      feld.remove();
      fertig(dateien.length ? dateien : null);
    }, { once: true });
    // Bricht der Nutzer den Dateidialog ab, kommt gar kein `change` — das
    // Feld bliebe für immer im DOM stehen. Beim nächsten Fokus aufräumen.
    window.addEventListener('focus', () => {
      setTimeout(() => { if (feld.isConnected && !feld.files?.length) {
        feld.remove(); fertig(null);
      } }, 800);
    }, { once: true });
  });
}

/**
 * Der ganze Weg: fotografieren, auslesen, die Maske gefüllt öffnen.
 *
 * `werte` sind die Vorgaben, die schon feststehen (z. B. die Einheit im Fokus).
 * Sie haben Vorrang vor der Auslese — was der Nutzer im Kontext entschieden
 * hat, überschreibt kein Automatismus.
 */
export async function eintragScannen(bereich, werte = {}, extra = '') {
  const cfg = cfgFuer(bereich);
  const dateien = await dateienWaehlen();
  if (!dateien) return;

  let deckeWeg = null;
  let vorbereitet = null;
  try {
    vorbereitet = await belegVorbereiten(dateien, {
      objekt: slug,
      kategorie: KATEGORIE[bereich] || 'Sonstiges',
      bereich,
      titel: `${cfg.einzahl} abfotografieren`,
    }, () => { deckeWeg = analyseDecke(`${cfg.einzahl} wird gelesen …`); });
  } catch (fehler) {
    melde(String(fehler.message || 'Der Scan hat nicht geklappt.'), 'neg');
    return;
  } finally {
    // Die Decke geht IMMER weg — auch wenn das Auslesen scheitert. Eine
    // hängende Vollbild-Sperre wäre schlimmer als gar keine.
    if (deckeWeg) { try { deckeWeg(); } catch { /* egal */ } }
  }
  if (!vorbereitet) return;                      // Zuschnitt abgebrochen

  const ki = vorbereitet.ki || {};
  // Der Kontext gewinnt: `werte` steht hinten und überschreibt die Auslese.
  const gefuellt = { ...(ki.formwerte || {}), ...werte };
  const erkannt = Object.keys(ki.formwerte || {}).length;

  // Der Scan wartet jetzt auf den gespeicherten Eintrag (siehe `scanAnhaengen`).
  offen = { ...vorbereitet, name: ki.formname || null };

  await formular({
    titel: `${cfg.einzahl} aus Scan`,
    felder: felderFuer(bereich, gefuellt),
    bereich,
    werte: gefuellt,
    absicht: 'eintrag',
    hinweis: erkannt
      ? `${erkannt} ${erkannt === 1 ? 'Angabe' : 'Angaben'} erkannt — bitte `
        + 'prüfen und ergänzen. Die Datei wird beim Speichern mit abgelegt.'
      : 'Aus dem Foto liess sich nichts Sicheres lesen — bitte von Hand '
        + 'ausfüllen. Die Datei wird beim Speichern mit abgelegt.',
    extra,
  });
}
