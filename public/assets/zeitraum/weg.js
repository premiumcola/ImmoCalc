/* zeitraum/weg.js — N280: die Vordertür zur WEG-Abrechnung.
 *
 * Liegt die vermietete Einheit in einer Wohnungseigentümergemeinschaft, rechnet
 * nicht der Vermieter ab, sondern die Messfirma. Er bekommt EINE fertige
 * Einzelabrechnung und reicht sie an den Mieter weiter. Damit fällt der ganze
 * übliche Weg weg: keine eigenen Rechnungen, keine Zähler, keine Belegjagd —
 * nur noch eine Dateiübernahme.
 *
 * Der Ablauf ist derselbe wie beim Belegscan und aus gutem Grund zweistufig:
 *
 *   aufnehmen (mehrseitig) → `/weg/lesen` (liest, speichert NICHTS)
 *   → Bestätigungsansicht → `/weg/uebernehmen` (erst jetzt entstehen Zeilen)
 *
 * Drei Regeln, die hier sichtbar werden müssen und nicht verhandelbar sind:
 *
 *   * **Nicht umlagefähig bleibt sichtbar, aber abgesetzt.** Anschaffungen,
 *     Reparatur und Schädlingsbekämpfung trägt die Eigentümergemeinschaft. Sie
 *     werden gezeigt, damit der Nutzer die Abrechnung wiedererkennt — und nie
 *     als Kostenposition angelegt.
 *   * **Die Einzelbeträge sind nicht editierbar.** Das hier ist die Kopie einer
 *     vorgegebenen Abrechnung; geändert wird am Papier, nicht an der Kopie.
 *     Erkennbar an `wertquelle == "WEG"`.
 *   * **Die Einheit geht IMMER mit.** Ohne sie verteilt der Server nach Fläche —
 *     die WEG-Abrechnung gilt aber für genau die eine Wohnung.
 */

import { api, eur, esc, melde, frage, baueDialog } from '../immo.js';
import { kamerascanStarten, istBildDatei } from '../kamerascan.js';
import { belegAblegen } from '../belegscan.js';
import * as state from './state.js';
import { WEG_ICON, BLATT_ICON } from './icons.js';
import { alleEinheiten, sonderEinheiten, kurzBeleg } from './helpers.js';

/* Woran die abgelegte Abrechnungsdatei später wiederzuerkennen ist. Sie trägt
   diesen Baustein im Namen (der Server benennt aus der Bezeichnung) — mehr
   braucht es nicht, um sie in `daten.dokumente` wiederzufinden. */
const BELEG_NAME = 'WEG-Abrechnung';

const geld = n => eur(Number(n) || 0);

/* Ein ISO-Datum als TT.MM.JJJJ — leer, wenn nichts Brauchbares dasteht. */
function datumText(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ''));
  return m ? `${m[3]}.${m[2]}.${m[1]}` : '';
}

/* Die Einheiten, auf die eine WEG-Abrechnung laufen kann. Bevorzugt die aus der
   Schlüssel-Vorschau (sie kennt auch die Partei), sonst die reinen
   Objekt-Einheiten. Nie hartkodiert — beides kommt aus der API. */
export function wegEinheiten() {
  const mitPartei = sonderEinheiten();
  if (mitPartei.length) return mitPartei;
  return alleEinheiten().map(einheit => ({ einheit, parteien: [] }));
}

/* Die zuletzt abgelegte Abrechnungsdatei dieses Zeitraums — der Nutzer soll
   sehen, wie sie heißt, und sie wieder ansehen können. */
function wegBeleg() {
  const treffer = (state.daten?.dokumente || [])
    .filter(d => (d.dateiname || '').includes(BELEG_NAME));
  return treffer.length ? treffer[treffer.length - 1] : null;
}

/* ------------------------------------------------------------------ */
/* Der Schalter                                                        */
/* ------------------------------------------------------------------ */

/** Die schmale Zeile ganz oben: ist die WEG-Abrechnung für diesen Zeitraum an?
 *  Sie steht auf jedem Zeitraum — sonst wäre der Modus nirgends zu finden. */
export function wegSchalterHtml() {
  const an = !!state.wegDaten?.aktiv;
  const bearbeitbar = state.daten?.status === 'in Arbeit';
  return `<div class="weg-schalter${an ? ' an' : ''}">
      <span class="ws-ikon">${WEG_ICON}</span>
      <span class="ws-t">WEG-Abrechnung
        <span class="ws-s">${an
          ? 'Die Abrechnungsfirma rechnet ab — hier wird nur ihre Abrechnung übernommen.'
          : 'Rechnet eine Hausverwaltung oder Messfirma für diese Einheit ab?'}</span></span>
      <button type="button" class="ws-kipp" role="switch" aria-checked="${an}"
        aria-label="WEG-Abrechnung ${an ? 'ausschalten' : 'einschalten'}"
        ${bearbeitbar ? '' : 'disabled'}
        data-weg-schalter="${an ? '0' : '1'}"><i></i></button>
    </div>`;
}

/* ------------------------------------------------------------------ */
/* Die Ansicht im eingeschalteten Zustand                              */
/* ------------------------------------------------------------------ */

/* Eine Positionsliste als Balken: die Höhe der Zahl wird sichtbar, statt nur
   dazustehen. Der Balken ist relativ zur größten Position der Liste. */
function balkenListe(zeilen, klasse = '') {
  const max = Math.max(0.01, ...zeilen.map(z => Math.abs(z.betrag || 0)));
  return `<div class="weg-liste ${klasse}">${zeilen.map(z => `
      <div class="weg-zeile">
        <span class="wz-n">${esc(z.kostenart)}</span>
        <span class="wz-bahn"><i style="width:${
          Math.max(3, Math.round(Math.abs(z.betrag || 0) / max * 100))}%"></i></span>
        <span class="wz-v">${geld(z.betrag)}</span>
      </div>`).join('')}</div>`;
}

/* Der Kopf des Belegs: wer hat ihn geschrieben, für welche Liegenschaft, für
   welchen Zeitraum. Chips statt Fließtext. */
function belegChips(beleg) {
  const chips = [
    beleg.firma, beleg.liegenschaft,
    beleg.nutzer_nr ? `Nutzer ${beleg.nutzer_nr}` : '',
    (beleg.von && beleg.bis)
      ? `${datumText(beleg.von)} – ${datumText(beleg.bis)}` : '',
    beleg.datum ? `Abgerechnet ${datumText(beleg.datum)}` : '',
  ].filter(Boolean);
  if (!chips.length) return '';
  return `<div class="weg-chips">${chips
    .map(c => `<span class="weg-chip">${esc(c)}</span>`).join('')}</div>`;
}

function vorauszahlungHtml(liste, summe) {
  const bearbeitbar = state.daten?.status === 'in Arbeit';
  const zeilen = liste.length ? liste.map(v => `
      <div class="weg-vz">
        <span class="wv-n">${esc(v.einheit || 'Einheit offen')}
          <span class="wv-s">${(v.von || v.bis)
            ? `${datumText(v.von) || 'Beginn'} – ${datumText(v.bis) || 'Ende'}`
            : 'ganzer Zeitraum'}</span></span>
        <span class="wv-r">${geld(v.betrag_monat)} × ${
          String(v.monate).replace('.', ',')} Mon.</span>
        <span class="wv-v">${geld(v.summe)}</span>
        ${bearbeitbar ? `<span class="wv-k">
          <button type="button" class="wv-b" data-weg-vz-bearbeiten="${v.id}"
            aria-label="Abschnitt ändern">Ändern</button>
          <button type="button" class="wv-x" data-weg-vz-weg="${v.id}"
            aria-label="Abschnitt entfernen">×</button></span>` : ''}
      </div>`).join('')
    : `<div class="weg-leer">Noch kein Abschnitt erfasst — ohne ihn steht die
        Vorauszahlung des Mieters auf 0 € und der Saldo ist die volle Summe.</div>`;

  return `<div class="karte weg-karte">
      <div class="weg-kopf">
        <h3>Vorauszahlung des Mieters</h3>
        ${bearbeitbar ? `<button type="button" class="weg-plus" data-weg-vz-neu
          aria-label="Abschnitt hinzufügen" title="Abschnitt hinzufügen">+</button>` : ''}
      </div>
      <span class="erklaer">Ändert sich der Betrag im Jahr, bekommt jeder
        Abschnitt seine eigene Zeile — gerechnet wird monatsgenau.</span>
      ${zeilen}
      <div class="weg-vzsumme"><span>Zusammen vorausgezahlt</span>
        <span>${geld(summe)}</span></div>
    </div>`;
}

function saldoHtml(stand) {
  const saldo = Number(stand.saldo) || 0;
  const nach = saldo < 0;
  return `<div class="weg-saldo ${nach ? 'neg' : 'pos'}">
      <div class="wsz"><span>Umlagefähig auf den Mieter</span>
        <span>${geld(stand.umlagefaehig_summe)}</span></div>
      <div class="wsz"><span>Vorausgezahlt</span>
        <span>${geld(stand.vorauszahlung_summe)}</span></div>
      <div class="wsz gross"><span>${nach ? 'Nachzahlung' : 'Guthaben'}</span>
        <span>${nach ? '−' : '+'} ${geld(Math.abs(saldo))}</span></div>
    </div>`;
}

/** Die ganze WEG-Ansicht — sie tritt an die Stelle der Checkliste. */
export function wegAnsichtHtml() {
  const d = state.wegDaten || {};
  const stand = d.stand || {};
  const positionen = stand.positionen || [];
  const nicht = stand.nicht_umlagefaehig || [];
  const beleg = stand.beleg || {};
  const bearbeitbar = state.daten?.status === 'in Arbeit';
  const datei = wegBeleg();
  const meldung = state.wegMeldung || {};

  const aufnahme = `<div class="karte weg-karte weg-aufnahme">
      <div class="weg-kopf"><h3>Abrechnung der Abrechnungsfirma</h3></div>
      ${belegChips(beleg)}
      ${datei ? `<div class="weg-datei">
          <a href="#" data-beleg="${datei.id}" data-name="${esc(datei.dateiname)}"
             data-pfad="${esc(datei.pfad || '')}"
             title="${esc(datei.pfad || datei.dateiname)}"
            >${BLATT_ICON}<span>${esc(kurzBeleg(datei.dateiname))}</span></a>
          <span class="wd-ort">${esc(datei.pfad || 'in der Ablage')}</span>
        </div>` : ''}
      ${bearbeitbar ? `<button type="button" class="weg-los" data-weg-scan>
          ${BLATT_ICON}<span>${positionen.length
            ? 'Neue Abrechnung aufnehmen' : 'Abrechnung aufnehmen'}</span>
        </button>
        <span class="erklaer">Alle Seiten nacheinander fotografieren (oder die
          PDF wählen). Was erkannt wurde, wird vor dem Übernehmen gezeigt.</span>`
        : ''}
    </div>`;

  const warnung = stand.warnung ? `<div class="weg-warn">
      <span class="ww-z">▲</span><span>${esc(stand.warnung)}</span></div>` : '';

  const uebersprungen = (meldung.uebersprungen || []).length
    ? `<div class="weg-warn leise"><span class="ww-z">≠</span><span>
        <b>${esc(meldung.uebersprungen.join(', '))}</b> ${
        meldung.uebersprungen.length === 1 ? 'wurde' : 'wurden'} nicht
        übernommen — hier steht schon eine von Hand gepflegte Position gleichen
        Namens, und die gewinnt.</span></div>` : '';
  const entfernt = (meldung.entfernt || []).length
    ? `<div class="weg-warn leise"><span class="ww-z">–</span><span>
        <b>${esc(meldung.entfernt.join(', '))}</b> ${
        meldung.entfernt.length === 1 ? 'stand' : 'standen'} in einer früheren
        Übernahme und ${meldung.entfernt.length === 1 ? 'kommt' : 'kommen'} in
        dieser Abrechnung nicht mehr vor — die Zeile ist entfallen.</span></div>`
    : '';

  const listen = positionen.length || nicht.length
    ? `<div class="karte weg-karte">
        <div class="weg-kopf"><h3>Übernommene Positionen</h3>
          <span class="weg-summe">${geld(stand.umlagefaehig_summe)}</span></div>
        <span class="erklaer">Kopie der vorgegebenen Abrechnung — die Beträge
          sind hier bewusst nicht änderbar.</span>
        ${warnung}${uebersprungen}${entfernt}
        ${positionen.length ? balkenListe(positionen)
          : '<div class="weg-leer">Noch keine Position übernommen.</div>'}
        ${nicht.length ? `<div class="weg-nicht">
            <div class="wn-kopf"><span>Nicht umlagefähig</span>
              <span class="wn-v">${geld(stand.nicht_umlagefaehig_summe)}</span></div>
            <p class="wn-s">Trägt die Eigentümergemeinschaft — geht nicht auf den
              Mieter und wird deshalb gar nicht erst zur Kostenposition.</p>
            ${balkenListe(nicht, 'aus')}
          </div>` : ''}
      </div>`
    : '';

  return wegSchalterHtml() + aufnahme + listen
    + vorauszahlungHtml(d.vorauszahlungen || [], stand.vorauszahlung_summe || 0)
    + saldoHtml(stand);
}

/* ------------------------------------------------------------------ */
/* Laden und Schalten                                                  */
/* ------------------------------------------------------------------ */

/** Den WEG-Stand holen. Fällt der Endpunkt aus, bleibt alles wie ohne WEG. */
export async function wegLaden() {
  try {
    state.setWegDaten(await api(`/zeitraeume/${state.zid}/weg`));
  } catch {
    state.setWegDaten(null);
  }
}

/* Die Antwort von PATCH/uebernehmen übernimmt den ganzen Stand — sie hat
   dieselbe Form wie das GET. `uebersprungen`/`entfernt` stehen nur dort und
   werden getrennt gemerkt, sonst wären sie beim nächsten Zeichnen weg. */
function standUebernehmen(antwort) {
  if (!antwort) return;
  state.setWegDaten({ aktiv: !!antwort.aktiv, stand: antwort.stand || {},
                      vorauszahlungen: antwort.vorauszahlungen || [] });
  const s = antwort.stand || {};
  if (s.uebersprungen || s.entfernt) {
    state.setWegMeldung({ uebersprungen: s.uebersprungen || [],
                          entfernt: s.entfernt || [] });
  }
}

export async function wegSchalten(an) {
  if (!an) {
    const ok = await frage('WEG-Abrechnung ausschalten?',
      'Die übernommenen Positionen bleiben stehen — nur die Ansicht wechselt '
      + 'zurück auf die gewohnte Checkliste.', { knopf: 'Ausschalten' });
    if (!ok) return;
  }
  try {
    standUebernehmen(await api(`/zeitraeume/${state.zid}/weg`,
      { method: 'PATCH', body: { aktiv: !!an } }));
    const { laden } = await import('./checkliste.js');
    await laden();
  } catch (fehler) { melde(String(fehler.message || fehler), 'neg'); }
}

/* ------------------------------------------------------------------ */
/* Aufnehmen → lesen → bestätigen → übernehmen                          */
/* ------------------------------------------------------------------ */

/* Aus Fotos wird EIN mehrseitiges PDF (die Abrechnung hat drei Seiten); eine
   fertig gewählte PDF geht unverändert durch. Derselbe Zuschnitt wie überall
   sonst — `kamerascanStarten` ist die eine Choreografie dafür. */
async function aufnahme(dateien) {
  const liste = Array.from(dateien || []);
  const bilder = liste.filter(istBildDatei);
  if (bilder.length) {
    const e = await kamerascanStarten(bilder, { titel: 'WEG-Abrechnung' });
    if (!e) return null;                                  // abgebrochen
    return { datei: e.pdf, name: 'weg-abrechnung.pdf', seiten: e.seiten,
             blaetter: e.bilder || [] };
  }
  const pdf = liste.find(d => (d.type || '') === 'application/pdf'
                           || /\.pdf$/i.test(d.name || ''));
  return pdf ? { datei: pdf, name: pdf.name, seiten: 0, blaetter: [] } : null;
}

/* Die Bestätigungsansicht: alles, was gelesen wurde — umlagefähig zuerst, der
   nicht umlagefähige Block klar abgesetzt darunter. Nichts ist editierbar
   außer der Einheit; geändert wird am Papier, nicht an der Kopie. */
function bestaetigungsDialog(gelesen, einheiten) {
  const pos = (gelesen.positionen || []).filter(p => p && p.bezeichnung);
  const uml = pos.filter(p => p.umlagefaehig !== false);
  const nicht = pos.filter(p => p.umlagefaehig === false);
  const zusatz = [
    ['Heizkosten', gelesen.heizkosten],
    ['Warmwasser', gelesen.warmwasserkosten],
  ].filter(([, b]) => Number(b) > 0);
  const summeUml = uml.reduce((s, p) => s + (Number(p.ihre_kosten) || 0), 0)
    + zusatz.reduce((s, [, b]) => s + Number(b), 0);
  const summeNicht = nicht.reduce((s, p) => s + (Number(p.ihre_kosten) || 0), 0);

  const zeile = p => `<div class="wb-z">
      <span class="wb-n">${esc(p.bezeichnung)}${p.schluessel
        ? `<span class="wb-s">${esc(p.schluessel)}</span>` : ''}</span>
      <span class="wb-g">${p.gesamtkosten ? geld(p.gesamtkosten) : ''}</span>
      <span class="wb-v">${geld(p.ihre_kosten)}</span>
    </div>`;

  const wahlEinheit = einheiten.length > 1
    ? `<select class="wb-einheit" data-einheit>${einheiten.map((e, i) =>
        `<option value="${esc(e.einheit)}"${i === 0 ? ' selected' : ''}
          >${esc(e.einheit)}${e.parteien.length
            ? ` · ${esc(e.parteien.join(', '))}` : ''}</option>`).join('')}</select>`
    : einheiten.length === 1
      ? `<span class="wb-eintext" data-einheit-fest="${esc(einheiten[0].einheit)}"
          >${esc(einheiten[0].einheit)}</span>`
      : `<span class="wb-eintext warn" data-einheit-fest=""
          >Keine Einheit gefunden — ohne sie verteilt der Server nach Fläche.</span>`;

  return new Promise(fertig => {
    let entschieden = false;
    const dlg = baueDialog(`
      <div class="beleg-kopf"><span class="bt">Gelesene Abrechnung prüfen</span></div>
      ${belegChips(gelesen)}
      ${gelesen.warnung ? `<div class="weg-warn"><span class="ww-z">▲</span>
        <span>${esc(gelesen.warnung)}</span></div>` : ''}
      <div class="wb-fuer"><span>Geht auf</span>${wahlEinheit}</div>
      <div class="wb-rolle">
        <div class="wb-liste">
          <div class="wb-kopfz"><span>Position</span><span class="wb-g">Gesamt</span>
            <span class="wb-v">Anteil</span></div>
          ${uml.map(zeile).join('')}
          ${zusatz.map(([n, b]) => zeile({ bezeichnung: n, ihre_kosten: b })).join('')}
          <div class="wb-z summe"><span class="wb-n">Umlagefähig zusammen</span>
            <span class="wb-g"></span><span class="wb-v">${geld(summeUml)}</span></div>
        </div>
        ${nicht.length ? `<div class="wb-nicht">
            <div class="wb-nkopf">Nicht umlagefähig — bleibt bei der Gemeinschaft
              <span>${geld(summeNicht)}</span></div>
            <p class="wb-ns">Instandhaltung, Anschaffungen und Schädlingsbekämpfung
              trägt die Eigentümergemeinschaft. Diese Zeilen werden gezeigt, aber
              nie zur Kostenposition.</p>
            <div class="wb-liste aus">${nicht.map(zeile).join('')}</div>
          </div>` : ''}
      </div>
      <div class="sb-fuss">
        <button type="button" class="sb-weiter" data-ok>${
          uml.length + zusatz.length} Positionen übernehmen · ${geld(summeUml)}</button>
      </div>`);
    dlg.classList.add('beleg-dlg', 'weg-best-dlg');
    const schliessen = wert => {
      if (entschieden) return;
      entschieden = true;
      dlg.close();
      fertig(wert);
    };
    dlg.querySelector('[data-ok]').addEventListener('click', () => {
      const sel = dlg.querySelector('[data-einheit]');
      const fest = dlg.querySelector('[data-einheit-fest]');
      schliessen({ einheit: sel ? sel.value : (fest?.dataset.einheitFest || '') });
    });
    dlg.addEventListener('click', e => { if (e.target === dlg) schliessen(null); });
    dlg.addEventListener('close', () => schliessen(null));
  });
}

/* Die aufgenommene Abrechnung zusätzlich in die Ablage legen — über genau
   dieselbe Funktion wie jeder andere Beleg (`belegAblegen`). Ohne KI-Auslese:
   gelesen wurde sie schon von `/weg/lesen`, ein zweiter Durchlauf kostete den
   Nutzer Tokens für nichts. Schlägt es fehl, ist das kein Grund, die Übernahme
   zu verwerfen — die Zahlen stehen längst. */
async function belegAblegenStill(auf, gelesen, jahr) {
  try {
    const teile = [BELEG_NAME, gelesen.firma || ''].filter(Boolean);
    await belegAblegen({
      aufnahme: auf, jahrHinweis: null, ki: null,
      ziel: { objekt: state.daten.objekt, kategorie: 'Nebenkosten', jahr,
              beschreibung: teile.join(' '), zeitraumId: state.daten.id },
    });
  } catch { /* die Datei fehlt in der Ablage — die Abrechnung steht trotzdem */ }
}

/** Der ganze Weg: Aufnahme → `/weg/lesen` → Bestätigung → `/weg/uebernehmen`. */
export async function wegAufnehmen(dateien) {
  const auf = await aufnahme(dateien);
  if (!auf) return;                                        // abgebrochen
  const { analyseDecke } = await import('../belegbestaetigung.js');
  const deckeWeg = analyseDecke('Die Abrechnung wird gelesen …');
  let gelesen = null, hinweis = '';
  try {
    const paket = new FormData();
    paket.append('datei', auf.datei, auf.name);
    const antwort = await fetch(`/api/zeitraeume/${state.zid}/weg/lesen`,
                                { method: 'POST', body: paket });
    if (!antwort.ok) {
      const grund = await antwort.json().then(k => k.detail).catch(() => null);
      throw new Error(grund || `Fehler ${antwort.status}`);
    }
    const r = await antwort.json();
    gelesen = r.gelesen;
    hinweis = r.hinweis || '';
  } catch (fehler) {
    melde(String(fehler.message || fehler), 'neg');
    return;
  } finally {
    deckeWeg();
  }
  if (!gelesen) {
    melde(hinweis || 'Die Abrechnung konnte nicht gelesen werden.', 'neg');
    return;
  }

  const wahl = await bestaetigungsDialog(gelesen, wegEinheiten());
  if (!wahl) return;                                       // nichts übernommen

  const jahr = Number((state.daten.ende || '').slice(0, 4))
    || new Date().getFullYear();
  try {
    standUebernehmen(await api(`/zeitraeume/${state.zid}/weg/uebernehmen`,
      { method: 'POST', body: { ...gelesen, einheit: wahl.einheit } }));
    await belegAblegenStill(auf, gelesen, jahr);
    melde('✓ WEG-Abrechnung übernommen', 'pos');
    const { laden } = await import('./checkliste.js');
    await laden();
  } catch (fehler) {
    melde('Nicht übernommen: ' + String(fehler.message || fehler), 'neg');
  }
}

/* ------------------------------------------------------------------ */
/* Vorauszahlung — Abschnitte anlegen, ändern, entfernen               */
/* ------------------------------------------------------------------ */

/* Ein Abschnitt: für wen, ab wann, bis wann, wie viel im Monat. Ohne Daten gilt
   er für den ganzen Zeitraum — der häufige Fall braucht dann keine Eingabe. */
function abschnittDialog(vorhanden, einheiten) {
  const v = vorhanden || {};
  const optionen = einheiten.map(e =>
    `<option value="${esc(e.einheit)}"${e.einheit === v.einheit ? ' selected' : ''}
      >${esc(e.einheit)}${e.parteien.length
        ? ` · ${esc(e.parteien.join(', '))}` : ''}</option>`).join('');
  return new Promise(fertig => {
    let entschieden = false;
    const dlg = baueDialog(`
      <div class="dt">${vorhanden ? 'Abschnitt ändern' : 'Abschnitt hinzufügen'}</div>
      <p class="weg-dp">Der Monatsbetrag der Vorauszahlung. Leere Daten heißen
        „gilt für den ganzen Abrechnungszeitraum".</p>
      <div class="field"><label for="wvEin">Einheit</label>
        ${einheiten.length
          ? `<select class="inp" id="wvEin">${optionen}</select>`
          : `<input class="inp" id="wvEin" value="${esc(v.einheit || '')}"
               placeholder="Bezeichnung der Einheit">`}</div>
      <div class="field zwei">
        <div><label for="wvVon">Von</label>
          <input class="inp" id="wvVon" type="date" value="${esc(v.von || '')}"></div>
        <div><label for="wvBis">Bis</label>
          <input class="inp" id="wvBis" type="date" value="${esc(v.bis || '')}"></div>
      </div>
      <div class="field"><label for="wvBet">Vorauszahlung je Monat (€)</label>
        <input class="inp" id="wvBet" type="number" step="0.01" inputmode="decimal"
          value="${v.betrag_monat != null ? v.betrag_monat : ''}" placeholder="0,00"></div>
      <div class="bdd-err" data-err hidden></div>
      <div class="sb-fuss"><button type="button" class="sb-weiter" data-ok
        >${vorhanden ? 'Ändern' : 'Hinzufügen'}</button></div>`);
    dlg.classList.add('weg-vz-dlg');
    const schliessen = wert => {
      if (entschieden) return;
      entschieden = true;
      dlg.close();
      fertig(wert);
    };
    dlg.querySelector('[data-ok]').addEventListener('click', () => {
      const betrag = parseFloat(String(dlg.querySelector('#wvBet').value)
        .replace(',', '.'));
      if (!(betrag > 0)) {
        const err = dlg.querySelector('[data-err]');
        err.textContent = 'Bitte den Monatsbetrag eintragen.';
        err.hidden = false;
        dlg.querySelector('#wvBet').focus();
        return;
      }
      schliessen({
        einheit: dlg.querySelector('#wvEin').value || '',
        von: dlg.querySelector('#wvVon').value || null,
        bis: dlg.querySelector('#wvBis').value || null,
        betrag_monat: Math.round(betrag * 100) / 100,
      });
    });
    dlg.addEventListener('click', e => { if (e.target === dlg) schliessen(null); });
    dlg.addEventListener('close', () => schliessen(null));
  });
}

/* Nach jeder Änderung an einem Abschnitt sind Summe UND Saldo neu — deshalb
   den ganzen Stand nachholen statt nur die Liste zu tauschen. */
async function vzNachladen() {
  await wegLaden();
  const { zeichnen } = await import('./checkliste.js');
  await zeichnen();
}

export async function vorauszahlungNeu() {
  const wahl = await abschnittDialog(null, wegEinheiten());
  if (!wahl) return;
  try {
    await api(`/zeitraeume/${state.zid}/weg/vorauszahlung`,
              { method: 'POST', body: wahl });
    await vzNachladen();
  } catch (fehler) { melde(String(fehler.message || fehler), 'neg'); }
}

export async function vorauszahlungBearbeiten(vid) {
  const vorhanden = (state.wegDaten?.vorauszahlungen || [])
    .find(v => String(v.id) === String(vid));
  const wahl = await abschnittDialog(vorhanden, wegEinheiten());
  if (!wahl) return;
  try {
    await api(`/zeitraeume/${state.zid}/weg/vorauszahlung/${vid}`,
              { method: 'PATCH', body: wahl });
    await vzNachladen();
  } catch (fehler) { melde(String(fehler.message || fehler), 'neg'); }
}

export async function vorauszahlungEntfernen(vid) {
  const v = (state.wegDaten?.vorauszahlungen || [])
    .find(x => String(x.id) === String(vid));
  const ok = await frage('Abschnitt entfernen?',
    `${v ? `${geld(v.betrag_monat)} je Monat · ${geld(v.summe)} im Zeitraum. ` : ''}`
    + 'Die Vorauszahlung sinkt entsprechend, der Saldo wächst.',
    { knopf: 'Entfernen', gefahr: true });
  if (!ok) return;
  try {
    await api(`/zeitraeume/${state.zid}/weg/vorauszahlung/${vid}`,
              { method: 'DELETE' });
    await vzNachladen();
  } catch (fehler) { melde(String(fehler.message || fehler), 'neg'); }
}
