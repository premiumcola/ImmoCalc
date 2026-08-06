/* N216 — Fabrik für alle Bearbeiten-/Anlegen-Formulare.

   Baut aus einem Bereich und einer Feldliste den Inhalt des `<dialog id="dlg">`
   im Objekt-HTML: Titel, Formularfelder (auswahl, einheit, anteileinheit,
   turnus, select, ja_nein, schalter, text/number/date), optionale Zusatzblöcke
   (Bewohner, Gemeinschaftsflächen, Zusatz-Nutzflächen, Kredit-Stände) und den
   Speicher-Knopf. Feld-Formatierung (Tausenderpunkte, IBAN, Steuernummer) und
   Auswahlfelder werden hier verdrahtet und beim Schließen wieder gelöst. */

import { esc, api, installHilfe, belegSeitenLaden } from '../immo.js';
import { auswahlfeld } from '../auswahl.js';
import { datumwahl } from '../datumwahl.js';
import { felderFuer, uebernahmeAnbieten } from '../objekt-felder.js?v=2';
import { flaecheText } from '../objekt-format.js?v=2';
import { einheiten,
         setDialogFelder, setDialogUmbau, dialogUmbau,
         ZINSTEXT } from './state.js';
import { turnusOptionen } from './turnus.js';

/* Lesbare Eingabe (Tausenderpunkte, IBAN in Vierergruppen, Steuernummer).
   Bewusst dynamisch geladen: fehlt die Datei, bleiben es schlichte Felder —
   die Seite muss deswegen nicht ausfallen. */
let eingabe = null;
try {
  eingabe = await import('../eingabe.js');
} catch {
  eingabe = null;
}

/* CXLVII — welches Zeichen rechts im Eingabefeld steht. Geld ist immer Euro,
   alles andere sagt es selbst („m²", „%"). Leer heisst: schmuckloses Feld. */
export const feldEinheit = f => (f.geld ? '€' : f.einheit) || '';

/* Beschriftung eines Feldes — bei echten Fachbegriffen (`f.lex`) mit einem
   ?-Hilfe-Platzhalter. `installHilfe` macht nach dem Rendern ein anklickbares
   Icon daraus. Triviale Felder (Name, Betrag, Bank) tragen kein `lex`. */
export const feldLabel = f => `${esc(f.l)}${
  f.lex ? ` <span data-hilfe="${esc(f.lex)}"></span>` : ''}`;

async function feldHtml(f, bereich, wert) {
  const id = `f_${f.k}`;
  if (f.typ === 'auswahl') {
    // Kein natives <select>: die aufgeklappte Liste zeichnete sonst das
    // Betriebssystem. Der wirkliche Wert steht im versteckten Feld, damit
    // `ausFormular` ihn wie bei jedem anderen Feld findet.
    // Beschriftung ohne `for`: den Knopf baut auswahl.js selbst und gibt ihm
    // eine eigene id — die Verknüpfung läuft über aria-label.
    // `ohneLeer`: eine Vertragsart gibt es immer — „nicht gewählt" wäre dort
    // keine mögliche Antwort, sondern eine Lücke im Datenmodell.
    const werte = f.ohneLeer ? f.werte : ['', ...f.werte];
    const gesetzt = wert ?? f.vorgabe ?? '';
    return `<div class="field"><label>${feldLabel(f)}</label>
      <input type="hidden" id="${id}" name="${f.k}" value="${esc(gesetzt)}">
      <div data-auswahl="${esc(f.k)}" data-label="${esc(f.l)}"
           ${f.umbau ? 'data-umbau="1"' : ''}
           data-optionen="${esc(JSON.stringify(werte))}"></div>
      ${f.note ? `<span class="feldnote">${esc(f.note)}</span>` : ''}</div>`;
  }
  if (f.typ === 'einheit') {
    // CLXIX — die Einheit wird angetippt, nicht getippt. Freitext liess einen
    // Tippfehler durch, und die Partei fiel stumm aus der Kostenverteilung
    // (Fund XCII). Ohne erfasste Einheiten bleibt es ein Textfeld: sonst
    // liesse sich an einem Bestandsobjekt gar kein Mietverhältnis anlegen.
    if (!einheiten.length) {
      return `<div class="field"><label for="${id}">${esc(f.l)}</label>
        <input class="inp" id="${id}" name="${f.k}" type="text"
               value="${esc(wert ?? '')}"></div>`;
    }
    const gewaehlt = wert ?? (einheiten.length === 1
      ? einheiten[0].bezeichnung : '');
    const blasen = einheiten.map(e => {
      const an = e.bezeichnung === gewaehlt;
      return `<button type="button" class="bubble${an ? ' gewaehlt' : ''}${
          e.vermietet ? '' : ' frei'}" data-wahl="${esc(e.bezeichnung)}"
          aria-pressed="${an}">
        <span class="bt">${esc(e.bezeichnung)}</span>
        ${e.flaeche ? `<span class="bf">${flaecheText(e.flaeche)}</span>` : ''}
        ${e.vermietet ? '' : '<span class="bfrei">frei</span>'}
      </button>`;
    }).join('');
    return `<div class="field"><label>${esc(f.l)}</label>
      <input type="hidden" id="${id}" name="${f.k}" value="${esc(gewaehlt)}">
      <div class="bubbles" data-wahlfeld="${esc(f.k)}" role="group"
           aria-label="${esc(f.l)}">${blasen}</div>
      <span class="feldnote">Antippen statt tippen — nur so findet die
        Kostenverteilung die Einheit wieder.</span></div>`;
  }
  if (f.typ === 'anteileinheit') {
    // CLXI — worauf ein Eigentümer-Anteil zeigt: das ganze Haus oder eine
    // Einheit. „Ganzes Haus" steht als erste Blase und ist vorgewählt — der
    // gewachsene Fall bleibt der Normalfall. Dieselbe Blasen-Verdrahtung wie
    // bei der Einheitenwahl der Miete (data-wahl/data-wahlfeld).
    const gewaehlt = wert ?? '';
    const blase = (w, text, extra) => {
      const an = w === gewaehlt;
      return `<button type="button" class="bubble${an ? ' gewaehlt' : ''}"
          data-wahl="${esc(w)}" aria-pressed="${an}">
        <span class="bt">${esc(text)}</span>${extra || ''}</button>`;
    };
    const blasen = blase('', 'Ganzes Haus')
      + einheiten.map(e => blase(e.bezeichnung, e.bezeichnung,
          e.flaeche ? `<span class="bf">${flaecheText(e.flaeche)}</span>` : '')).join('');
    return `<div class="field"><label>${esc(f.l)}</label>
      <input type="hidden" id="${id}" name="${f.k}" value="${esc(gewaehlt)}">
      <div class="bubbles" data-wahlfeld="${esc(f.k)}" role="group"
           aria-label="${esc(f.l)}">${blasen}</div>
      <span class="feldnote">Gehört dem Eigentümer nur eine Wohnung, hier die
        Einheit wählen — sonst „Ganzes Haus". Einheit-Anteile haben Vorrang für
        ihre Einheit, der Haus-Anteil deckt den Rest.</span></div>`;
  }
  // Turnus und Auswahllisten tragen dasselbe eigene Auswahlfeld wie `auswahl`
  // — ein natives <select> zeichnet sonst das Betriebssystem und fällt aus dem
  // Design der Seite (blaue Kästen, eckige Liste).
  if (f.typ === 'turnus') {
    const { optionen, vorgabe } = await turnusOptionen(bereich);
    const gewaehlt = wert ?? f.vorgabe ?? vorgabe;
    return `<div class="field"><label>${feldLabel(f)}</label>
      <input type="hidden" id="${id}" name="${f.k}" value="${esc(gewaehlt)}">
      <div data-auswahl="${esc(f.k)}" data-label="${esc(f.l)}"
           data-optionen="${esc(JSON.stringify(optionen))}"></div>
      ${f.note ? `<span class="feldnote">${esc(f.note)}</span>` : ''}</div>`;
  }
  if (f.typ === 'select') {
    return `<div class="field"><label>${feldLabel(f)}</label>
      <input type="hidden" id="${id}" name="${f.k}" value="${esc(wert ?? '')}">
      <div data-auswahl="${esc(f.k)}" data-label="${esc(f.l)}"
           data-optionen="${esc(JSON.stringify(f.werte))}"></div>
      ${f.note ? `<span class="feldnote">${esc(f.note)}</span>` : ''}</div>`;
  }
  if (f.typ === 'date') {
    // N226 — kein natives <input type="date">: der aufklappende Kalender
    // zeichnet sonst das Betriebssystem (blau, fremd) — genau wie beim
    // Auswahlfeld. Derselbe Aufbau: verstecktes Feld trägt den echten (ISO-)
    // Wert, `datumwahlSetzen` baut den eigenen Chooser hinein.
    const gesetzt = wert ?? f.vorgabe ?? '';
    return `<div class="field"><label>${feldLabel(f)}</label>
      <input type="hidden" id="${id}" name="${f.k}" value="${esc(gesetzt)}">
      <div data-datumwahl="${esc(f.k)}" data-label="${esc(f.l)}"></div>
      ${f.note ? `<span class="feldnote" id="n_${f.k}">${esc(f.note)}</span>` : ''}</div>`;
  }
  if (f.typ === 'ja_nein') {
    const ja = wert === undefined ? true : Boolean(wert);
    return `<div class="field"><label for="${id}">${esc(f.l)}</label>
      <select class="inp" id="${id}" name="${f.k}">
        <option value="ja" ${ja ? 'selected' : ''}>ja</option>
        <option value="nein" ${ja ? '' : 'selected'}>nein</option>
      </select></div>`;
  }
  if (f.typ === 'schalter') {
    // CXCIII — ein gedeckter Ja/Nein-Schalter im Stil der Seite, kein natives
    // Kästchen. Er borgt sich die Blasen-Verdrahtung (data-wahl/-wahlfeld): der
    // echte Wert steht im versteckten Feld, `ausFormular` liest ihn als bool.
    const ja = wert == null ? (f.vorgabe == null ? true : Boolean(f.vorgabe))
                            : Boolean(wert);
    const knopf = (w, an, text) => `<button type="button"
        class="schaltknopf${an ? ' an' : ''}" data-wahl="${w}"
        aria-pressed="${an}">${text}</button>`;
    return `<div class="field"><label>${feldLabel(f)}</label>
      <input type="hidden" id="${id}" name="${f.k}" value="${ja ? 'ja' : 'nein'}">
      <div class="schalter" data-wahlfeld="${esc(f.k)}" role="group"
           ${f.umbau ? 'data-umbau="1"' : ''} aria-label="${esc(f.l)}">
        ${knopf('ja', ja, 'Ja')}${knopf('nein', !ja, 'Nein')}
      </div>
      ${f.note ? `<span class="feldnote">${esc(f.note)}</span>` : ''}</div>`;
  }
  const v = wert == null ? (f.vorgabe != null ? f.vorgabe : '') : wert;
  // Felder mit Einheit sind Textfelder: ein <input type="number"> nimmt keine
  // Tausenderpunkte an und stellte seine Pfeilchen genau dorthin, wo das
  // Zeichen sitzt. Die Zifferntastatur bleibt über inputmode erhalten.
  const einheit = feldEinheit(f);
  const typ = einheit ? 'text' : f.typ;
  const zusatz = einheit ? 'inputmode="decimal"'
                         : (f.schritt ? `step="${f.schritt}"` : '');
  return `<div class="field"><label for="${id}">${feldLabel(f)}</label>
    <input class="inp" id="${id}" name="${f.k}" type="${typ}" ${zusatz}
           value="${esc(v)}" ${f.pflicht ? 'required' : ''}>
    ${f.note ? `<span class="feldnote" id="n_${f.k}">${esc(f.note)}</span>` : ''}</div>`;
}

/* Lesbare Eingabe anhängen — und beim Schliessen wieder lösen, sonst häufen
   sich die Beobachter mit jedem geöffneten Dialog. */
let formate = [];

export function formateLoesen() {
  for (const f of formate) {
    try { f.zerstoere(); } catch { /* schon weg */ }
  }
  formate = [];
}

function formateSetzen(form, felder) {
  formateLoesen();
  if (!eingabe) return;
  for (const f of felder) {
    const el = form.elements[f.k];
    if (!el || el.tagName !== 'INPUT') continue;
    const einheit = feldEinheit(f);
    const bauer = einheit ? feld => eingabe.geldFeld(feld, einheit)
                : f.iban ? eingabe.ibanFeld
                : f.steuer ? eingabe.steuernummerFeld : null;
    if (typeof bauer !== 'function') continue;
    try {
      const griff = bauer(el);
      if (griff && typeof griff.zerstoere === 'function') formate.push(griff);
    } catch { /* eine Formatierung ist kein Muss */ }
  }
}

/* Auswahlfelder im eigenen Design — je Dialog neu gebaut und beim Schliessen
   wieder abgeräumt, wie die Formatierungen darüber. */
let auswahlen = [];

export function auswahlLoesen() {
  for (const a of auswahlen) {
    try { a.zerstoere(); } catch { /* schon weg */ }
  }
  auswahlen = [];
}

function auswahlSetzen(form) {
  auswahlLoesen();
  for (const halter of form.querySelectorAll('[data-auswahl]')) {
    const feld = form.elements[halter.dataset.auswahl];
    if (!feld) continue;
    // Reine Zeichenketten (Nutzungsart, Erwerbsart …) oder Wert/Text-Paare
    // (Turnus: „jaehrlich" heisst „jährlich").
    const optionen = JSON.parse(halter.dataset.optionen)
      .map(w => (w && typeof w === 'object')
        ? { wert: w.wert, text: w.text }
        : { wert: w, text: w || 'nicht gewählt' });
    auswahlen.push(auswahlfeld(halter, {
      optionen, wert: feld.value, label: halter.dataset.label,
      aenderung: neu => {
        feld.value = neu;
        // Ein Feld, das die Maske umstellt (die Vertragsart), baut das
        // Formular neu — aber erst im nächsten Anlauf: sonst zöge sich das
        // Auswahlfeld sein eigenes DOM unter den Füssen weg.
        if (halter.dataset.umbau && dialogUmbau) setTimeout(dialogUmbau, 0);
      },
    }));
  }
}

/* N226 — Datumsfelder im eigenen Design, wie `auswahlSetzen` für die
   Auswahlfelder. Eigene Liste zum Abräumen, damit ein neu gebautes Formular
   keine toten Chooser vom vorigen mitschleppt. */
let datumfelder = [];

export function datumwahlLoesen() {
  for (const d of datumfelder) {
    try { d.zerstoere(); } catch { /* schon weg */ }
  }
  datumfelder = [];
}

function datumwahlSetzen(form) {
  datumwahlLoesen();
  for (const halter of form.querySelectorAll('[data-datumwahl]')) {
    const feld = form.elements[halter.dataset.datumwahl];
    if (!feld) continue;
    datumfelder.push(datumwahl(halter, {
      wert: feld.value, label: halter.dataset.label,
      aenderung: neu => {
        feld.value = neu;
        // Bestehende Lauscher (Kappungsgrenze, Zins-Kopplung, …) hören auf
        // 'input'/'change' am Feld selbst — die müssen weiter feuern, auch
        // wenn der Wert jetzt vom eigenen Chooser statt vom Browser kommt.
        feld.dispatchEvent(new Event('input', { bubbles: true }));
        feld.dispatchEvent(new Event('change', { bubbles: true }));
      },
    }));
  }
}

/* CXLVIII — Zinssatz und Zinsanteil je Monat halten sich gegenseitig aktuell.
   Wer den Satz kennt, tippt ihn; wer nur den Zinsanteil aus dem Kontoauszug
   hat, tippt den — beides führt zum selben Ergebnis. Gespeichert wird der
   Zinssatz.

   Die Regel dahinter steht in `api/app/vermoegen.py` (`monatszins` und
   `zinssatz_aus_monatszins`) und ist dort geprüft; hier wird sie nur
   angezeigt, damit die Zahl schon während des Tippens dasteht. Wer sie ändert,
   ändert sie an beiden Stellen. */
function zinsKopplung(form) {
  const satz = form.querySelector('#f_zinssatz');
  const monat = form.querySelector('#f_zins_monat');
  const rest = form.querySelector('#f_restschuld');
  const note = form.querySelector('#n_zins_monat');
  if (!satz || !monat || !rest) return;
  // Das Nachtragen im anderen Feld ist keine Eingabe des Nutzers.
  let rechnet = false;

  /* Die Restschuld, auf die sich beide Felder beziehen — null, solange keine
     eingetragen ist. */
  const basis = () => {
    const r = zahlAus(rest);
    return r && r > 0 ? r : null;
  };

  const setze = (feld, wert) => {
    rechnet = true;
    feld.value = wert == null ? '' : String(wert);
    rechnet = false;
  };
  const auf2 = n => Math.round(n * 100) / 100;

  function ausSatz() {
    const r = basis();
    const s = zahlAus(satz);
    setze(monat, r == null || s == null ? null : auf2(r * s / 100 / 12));
  }

  /* Umgekehrt nur, wenn wirklich etwas dasteht: ein geleertes Hilfsfeld soll
     keinen eingetragenen Zinssatz mitnehmen. */
  function ausMonat() {
    const r = basis();
    const m = zahlAus(monat);
    if (r == null || m == null) return;
    setze(satz, auf2(m * 12 / r * 100));
  }

  /* Die fehlende Restschuld wird erst zum Thema, wenn wirklich etwas
     umzurechnen wäre — ein frisch geöffnetes Formular wird nicht gleich
     ermahnt. */
  function melde() {
    if (!note) return;
    const angefangen = zahlAus(satz) != null || zahlAus(monat) != null;
    note.textContent = !basis() && angefangen ? ZINSTEXT.nein : ZINSTEXT.ja;
  }

  const beiEingabe = rechnung => () => {
    if (rechnet) return;
    rechnung();
    melde();
  };

  satz.addEventListener('input', beiEingabe(ausSatz));
  monat.addEventListener('input', beiEingabe(ausMonat));
  // Ändert sich die Restschuld, gilt weiter der Zinssatz — er ist das
  // Gespeicherte, der Zinsanteil folgt ihm.
  rest.addEventListener('input', beiEingabe(ausSatz));

  melde();
  ausSatz();
}

/* Was wirklich im Feld steht — auch wenn es "1.250.000" anzeigt.
   `data-wert` hat Vorrang: dort legt die Formatierung den rohen Wert ab. */
export function zahlAus(el) {
  const roh = el.dataset.wert != null && el.dataset.wert !== ''
    ? el.dataset.wert : el.value;
  const text = String(roh ?? '').replace(/[^\d,.-]/g, '');
  if (text === '') return null;
  const komma = text.lastIndexOf(',');
  const sauber = komma >= 0
    ? `${text.slice(0, komma).replace(/\./g, '')}.${text.slice(komma + 1).replace(/\D/g, '')}`
    // Ein einzelner Punkt mit ein bis zwei Stellen dahinter ist ein
    // Dezimalpunkt (so kommt der Wert aus der API), sonst Tausendertrennung.
    : (/^-?\d+\.\d{1,2}$/.test(text) ? text : text.replace(/\./g, ''));
  const zahl = Number(sauber);
  return Number.isFinite(zahl) ? zahl : null;
}

export function ausFormular(form, felder) {
  const werte = {};
  for (const f of felder) {
    // Hilfsfelder helfen beim Ausfüllen und werden nicht gespeichert — der
    // Zinsanteil je Monat steckt schon im Zinssatz.
    if (f.hilfe) continue;
    const el = form.elements[f.k];
    if (!el) continue;
    if (f.typ === 'ja_nein' || f.typ === 'schalter') {
      werte[f.k] = el.value === 'ja'; continue;
    }
    // Leeren heisst hier wirklich leeren — sonst liesse sich ein einmal
    // gesetztes Enddatum nie wieder entfernen.
    if (f.typ === 'number') { werte[f.k] = zahlAus(el); continue; }
    if (el.value === '') { werte[f.k] = f.typ === 'date' ? null : ''; continue; }
    werte[f.k] = el.value;
  }
  return werte;
}

/* CCCXXIII — die PDF-Spalte des Bearbeiten-Dialogs sauber wieder abräumen,
   sobald er schliesst: Klasse weg (nächste schmale Maske bleibt schmal),
   Object-URLs freigeben, Inhalt leeren. */
function pdfSchliessverdrahtung(dlg) {
  if (dlg._pdfWired) return;
  dlg._pdfWired = true;
  dlg.addEventListener('close', () => {
    (dlg._pdfUrls || []).forEach(u => URL.revokeObjectURL(u));
    dlg._pdfUrls = [];
    dlg.classList.remove('mit-pdf');
    const p = document.getElementById('dlgPdf');
    if (p) { p.innerHTML = ''; delete p.dataset.docId; }
  });
}

export async function formular(einst) {
  const { titel: dtitel, felder, bereich, werte = {}, absicht,
          hinweis = '', extra = '', knopf = 'Speichern', beleg = null } = einst;
  const dlg = document.getElementById('dlg');
  const form = document.getElementById('dlgForm');
  pdfSchliessverdrahtung(dlg);
  // Beleg daneben (CCCXXIII): nur laden, wenn sich das Dokument ändert — sonst
  // flackerte die Vorschau bei jedem reaktiven Umbau des Formulars.
  const pdf = document.getElementById('dlgPdf');
  if (beleg && beleg.id) {
    dlg.classList.add('mit-pdf');
    if (pdf.dataset.docId !== String(beleg.id)) {
      (dlg._pdfUrls || []).forEach(u => URL.revokeObjectURL(u));
      pdf.innerHTML = '<div class="beleg-flaeche"></div>';
      dlg._pdfUrls = belegSeitenLaden(`/api/dokumente/${beleg.id}`,
        pdf.querySelector('.beleg-flaeche'), beleg.dateiname || 'Beleg',
        `/api/dokumente/${beleg.id}/inhalt`);
      pdf.dataset.docId = String(beleg.id);
    }
  } else {
    dlg.classList.remove('mit-pdf');
    (dlg._pdfUrls || []).forEach(u => URL.revokeObjectURL(u));
    dlg._pdfUrls = [];
    pdf.innerHTML = '';
    delete pdf.dataset.docId;
  }
  const html = await Promise.all(
    felder.map(f => feldHtml(f, bereich, werte[f.k])));
  document.getElementById('dlgTitel').textContent = dtitel;
  // Abbrechen ist bewusst type="button": als Submit-Knopf loeste es den
  // submit-Handler aus und speicherte. Die Abfrage darauf lief ins Leere,
  // weil returnValue am <dialog> haengt, nicht am <form>.
  form.innerHTML = (hinweis ? `<p class="dlgnote">${esc(hinweis)}</p>` : '')
    + html.join('') + extra +
    `<button class="btn" value="ok">${esc(knopf)}</button>
     <button class="btn leise" type="button" data-abbruch
             style="margin-top:8px">Abbrechen</button>`;
  form.dataset.absicht = absicht;
  form.dataset.bereich = bereich || '';
  form.dataset.id = werte.id || '';
  delete form.dataset.vorgaenger;   // sonst endet beim nächsten Mal ein fremder Stand
  setDialogFelder(felder);
  setDialogUmbau(async () => {
    // Das schon Eingetippte überlebt den Umbau — nur die Felder wechseln.
    const stand = bereich === 'kredite'
      ? uebernahmeAnbieten({ ...werte, ...ausFormular(form, felder) })
      : { ...werte, ...ausFormular(form, felder) };
    await formular({ ...einst, felder: felderFuer(bereich, stand, absicht),
                     werte: stand });
  });
  formateSetzen(form, felder);
  auswahlSetzen(form);
  datumwahlSetzen(form);
  zinsKopplung(form);
  installHilfe(form);
  // Ein zweiter showModal-Aufruf auf einem offenen Dialog wirft — der Wechsel
  // von der Miete zur Erhöhung tauscht nur den Inhalt aus.
  if (!dlg.open) dlg.showModal();
  form.scrollTop = 0;
}
