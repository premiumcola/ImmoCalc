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
import { melde, esc } from '../immo.js';
import { belegVorbereiten, belegAblegen } from '../belegscan.js';
import { analyseDecke, namenHolen, ohneEndung } from '../belegbestaetigung.js';
import { cfgFuer, felderFuer } from '../objekt-felder.js?v=2';
import { slug } from '../objekt-state.js?v=2';
import { SCAN_KATEGORIE, AN_TYP } from './state.js';
import { formular } from './formular.js';

/* N280 — Ablageordner (`cloudkern.ZIELORDNER`) und `an_typ` standen hier ein
   zweites Mal, Wort für Wort gleich wie in `state.js`. Zwei Tabellen für
   dieselbe Frage laufen auseinander: die Detailansicht kannte
   `erwerbskosten` längst, dieser Weg nicht — und deshalb erschien am
   Erwerbsnebenkosten-Formular kein Scan-Knopf. Jetzt gilt überall dieselbe
   Zuordnung: `SCAN_KATEGORIE` sagt, wohin der Beleg wandert, `AN_TYP`
   übersetzt die Rubrik (Plural) in den Eintragstyp des Servers (Singular,
   siehe `_AN_TYP_MODELLE` in `routers/dokumente.py`). */

/* Bereiche, die die Server-Zuordnung kennt (`feldzuordnung.ZUORDNUNG`). Nur
   dort lohnt der Scan-Weg — anderswo käme eine leere Maske heraus, und der
   Knopf verspräche etwas, das er nicht hält. */
export const SCANBAR = new Set(['notarvertraege', 'versicherungen', 'kredite',
                                'mieten', 'zahlungen', 'erwerbskosten',
                                'grundschulden']);

/* Der vorbereitete, noch NICHT abgelegte Scan. Er wartet, bis der Eintrag
   gespeichert ist — vorher gibt es keine id, an die er gehören könnte.
   `name` ist der Dateiname-Vorschlag; der Nutzer sieht und ändert ihn im
   Formular (N280), bis dahin steht darin, was die Auslese vorschlägt. */
let offen = null;

/** Wartet ein Scan auf den gerade gespeicherten Eintrag? */
export const scanWartet = () => Boolean(offen);

/** Vergisst den vorbereiteten Scan (Formular abgebrochen oder verworfen). */
export function scanVerwerfen() { offen = null; vorschauAufraeumen(); }

/** N280 — der im Formular getippte Dateiname. Er geht beim Speichern als
    Bezeichnung an die Ablage (`belegAblegen`), die daraus mit Datum und Betrag
    den endgültigen Namen baut — dieselbe Regel wie in der Bestätigungsmaske. */
export function scanNameSetzen(name) {
  if (offen) offen.name = String(name || '').trim() || null;
}

/* N269 — solange eine Aufnahme läuft (Kamera offen, Zuschnitt, KI-Auslese),
 * blockt jeder weitere Tastendruck. Ohne diesen Riegel öffnete ein zweiter,
 * ungeduldiger Tipp auf den Scan-Knopf einen ZWEITEN, unabhängigen Zuschnitt
 * gleichzeitig — zwei Kamera-Sitzungen, zwei Fotos, keines davon zusammen als
 * ein mehrseitiges Dokument. Genau das hatte der Nutzer gemeldet: drei Ebenen
 * übereinander (die Eingabemaske plus zwei einzelne Seiten-Zuschnitte statt
 * eines gemeinsamen mit „+" für die zweite Seite).
 */
let inBearbeitung = false;

/* Die Vorschau der zuletzt aufgenommenen Seiten — Object-URLs, die beim
 * nächsten Scan oder Verwerfen wieder freigegeben werden. */
let vorschauUrls = [];
function vorschauAufraeumen() {
  vorschauUrls.forEach(u => URL.revokeObjectURL(u));
  vorschauUrls = [];
}

/**
 * N269 — der Beleg verschwand nach der Aufnahme sang- und klanglos aus dem
 * Blick: die Maske ging gefüllt auf, aber ohne jede sichtbare Spur des Fotos.
 * Diese kleine Vorschau zeigt genau, was gleich mit abgelegt wird, und macht
 * mit „Erneut aufnehmen" einen kompletten Neuversuch möglich — mehrseitig
 * hinzufügen läuft weiterhin über das „+" im Kamerafenster selbst
 * (`kamerascanStarten`), das erlaubt beliebig viele Seiten in EINER Sitzung.
 *
 * N280 — dazu der **Dateiname**. Beim Anlegen aus einem Scan gibt es keine
 * Bestätigungsmaske (das gefüllte Formular kommt ohnehin gleich danach — eine
 * zweite Maske davor wäre ein Klick zu viel), also steht der Name hier: sicht-
 * und änderbar, direkt neben den Seiten, zu denen er gehört. Er wird bei jedem
 * Tastendruck nach `offen.name` durchgereicht (`scanNameSetzen`) und geht beim
 * Speichern an die Ablage.
 *
 * Bewusst eine Funktion statt einer fertigen Zeichenkette: baut das Formular
 * sich um (Vertragsart gewechselt), wird sie erneut gerufen und zeigt den
 * Stand, den der Nutzer gerade getippt hat — nicht wieder den ersten Vorschlag.
 */
function scanBlockHtml(bereich) {
  if (!offen) return '';
  vorschauAufraeumen();
  const blaetter = offen.aufnahme?.blaetter || [];
  const anzahl = offen.aufnahme?.seiten || blaetter.length || 0;
  const bilder = blaetter.map(b => {
    const url = URL.createObjectURL(b);
    vorschauUrls.push(url);
    return `<img class="sv-blatt" src="${url}" alt="">`;
  }).join('');
  return `<div class="sv-vorschau">
      ${bilder ? `<div class="sv-blaetter">${bilder}</div>` : ''}
      <label class="sv-nlabel" for="svName">Dateiname</label>
      <input class="sv-namefeld" id="svName" type="text" data-scanname
             value="${esc(offen.name || '')}"
             placeholder="Bezeichnung des Belegs"
             spellcheck="false" autocapitalize="off" autocomplete="off">
      <span class="sv-nhinweis">So wird die Datei in der Nextcloud abgelegt —
        Datum und Betrag stehen schon darin. Stimmt etwas nicht, hier ändern.</span>
      <div class="sv-vzeile">
        <span class="sv-vanzahl">${anzahl
          ? `${anzahl} Seite${anzahl === 1 ? '' : 'n'} aufgenommen`
          : 'Datei ausgewählt'}</span>
        <button type="button" class="sv-vneu" data-eintrag-scan="${esc(bereich)}"
          >Erneut aufnehmen</button>
      </div>
    </div>`;
}

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
      // N283(c) — im Feld steht jetzt der volle Name samt Endung. Als
      // Bezeichnung geht sie nicht mit: `dateiname()` hängt sie ohnehin selbst
      // an und liesse sie sonst mitten im Namen stehen. Dieselbe Regel wie in
      // der Bestätigungsmaske, deshalb dieselbe Funktion.
    }, paket.name ? ohneEndung(paket.name) : null);
  } catch (fehler) {
    melde(`${cfgFuer(bereich).einzahl} gespeichert — die Datei konnte aber `
      + `nicht abgelegt werden: ${fehler.message || fehler}`, 'neg');
  }
}

/** Die Kamera/Dateiauswahl öffnen und auf die Wahl warten.
 *
 * Das `feld.click()` ist der ganze Punkt dieser Funktion: ein Dateifeld öffnet
 * sich NIE von selbst, nur weil es im DOM steht. Es fehlte — der Knopf legte
 * das Feld an und wartete dann auf eine Kamera, die niemand aufgerufen hatte.
 *
 * Der Klick muss im selben Durchlauf wie die Nutzerberührung passieren, sonst
 * verweigert Safari ihn. Deshalb steht hier vor `click()` kein `await` und
 * darf auch keines dazwischen geraten. */
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

    let erledigt = false;
    const abschliessen = dateien => {
      if (erledigt) return;
      erledigt = true;
      feld.remove();
      fertig(dateien);
    };

    feld.addEventListener('change', () => {
      const dateien = Array.from(feld.files || []);
      abschliessen(dateien.length ? dateien : null);
    }, { once: true });

    feld.click();

    // Bricht der Nutzer die Auswahl ab, kommt gar kein `change` — das Feld
    // bliebe für immer im DOM stehen. Beim nächsten Fokus aufräumen, aber mit
    // reichlich Nachlauf: nach einer Aufnahme kann der Fokus VOR dem `change`
    // eintreffen, und ein zu strammer Zeitgeber würfe das Foto weg.
    window.addEventListener('focus', () => {
      setTimeout(() => { if (!feld.files?.length) abschliessen(null); }, 2000);
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
  // N269 — ein zweiter Tipp während Kamera/Zuschnitt/Auslese laufen wird
  // stillschweigend ignoriert statt eine zweite, unabhängige Sitzung zu
  // starten (siehe die Erklärung bei `inBearbeitung` oben).
  if (inBearbeitung) return;
  inBearbeitung = true;
  try {
    const cfg = cfgFuer(bereich);
    const dateien = await dateienWaehlen();
    if (!dateien) return;

    let deckeWeg = null;
    let vorbereitet = null;
    // N283(c) — der endgültige Dateiname, wie ihn auch die Bestätigungsmaske
    // zeigt. Er wird NOCH UNTER DER DECKE geholt: der Namensvorschlag ist eine
    // kurze Wartezeit, und ein Formular, dessen Namensfeld eine Sekunde später
    // von selbst umspringt, sieht nach einem Fehler aus.
    let namensvorschlag = '';
    try {
      vorbereitet = await belegVorbereiten(dateien, {
        objekt: slug,
        kategorie: SCAN_KATEGORIE[bereich] || 'Sonstiges',
        bereich,
        titel: `${cfg.einzahl} abfotografieren`,
      }, () => { deckeWeg = analyseDecke(`${cfg.einzahl} wird gelesen …`); });
      if (vorbereitet) {
        const formname = vorbereitet.ki?.formname || '';
        namensvorschlag = await namenHolen(
          formname ? { ...vorbereitet.ziel, beschreibung: formname }
                   : vorbereitet.ziel,
          vorbereitet.aufnahme, vorbereitet.jahrHinweis);
      }
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
    // N283(c) — im Feld steht der ENDGÜLTIGE Name (mit Datum und Betrag), nicht
    // mehr nur die Bezeichnung aus der Auslese. Bleibt der Vorschlag aus
    // (Server nicht erreichbar), ist die Bezeichnung weiterhin der Rückfall.
    offen = { ...vorbereitet, name: namensvorschlag || ki.formname || null };

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
      // Als Funktion: ein Umbau des Formulars (Vertragsart) baut den Block neu
      // und zeigt dabei den zuletzt getippten Dateinamen (siehe scanBlockHtml).
      extra: () => scanBlockHtml(bereich) + extra,
    });
  } finally {
    inBearbeitung = false;
  }
}
