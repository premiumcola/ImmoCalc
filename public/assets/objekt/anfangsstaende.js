/* N216 — Anfangszählerstände.

   Rubrik-Einstiegskarte (`erststandHtml`) unter den Abrechnungszeiträumen und
   der Erfassungs-Dialog (`anfangsstaendeDialog`). Der Anfangsstand hängt an
   KEINEM Zeitraum — er ist der Stand vor der ersten Abrechnung. */

import { api, esc, zahlAus, heuteIso } from '../immo.js';
import { datumwahl } from '../datumwahl.js';
import { kostenIcon } from '../kostenicons.js';
import { datum } from '../objekt-format.js?v=2';
import { HAKEN_ICON } from '../objekt-baum.js?v=2';
import { istGrundstueck, slug } from '../objekt-state.js?v=2';
import { GAUGE_ICON, daten, zaehlerListe, erststandZiel,
         setZaehlerListe, updateZaehler } from './state.js';

export function erststandHtml(zielId) {
  if (istGrundstueck()) return '';
  // Nur gemessene, aktive Zähler brauchen einen Anfangsstand.
  // N141b — `rest` errechnet sich, `direkt` traegt den fertigen Periodenverbrauch
  // statt eines Zaehlerstands (N120): beide brauchen keinen Anfangsstand. Vorher
  // mahnte die Zeile dauerhaft zwei Zaehler an, bei denen nie etwas zu tun ist.
  const OHNE_ANFANG = new Set(['rest', 'direkt']);
  const mess = (zaehlerListe || []).filter(
    z => z.aktiv !== false && !OHNE_ANFANG.has(z.typ));
  const ohne = mess.filter(z => !z.anfangsstand);
  // Zähler vorhanden, aber keiner misst (nur Rest/inaktiv) — kein Anfangsstand nötig.
  if (zaehlerListe.length && mess.length === 0) return '';

  // Alles hinterlegt — ruhige Bestätigung. N141: trotzdem anklickbar, damit die
  // Übersicht (und ein Ändern) erreichbar bleibt, statt in einer Sackgasse zu
  // enden. Kein Pfeil, kein Drängen — nur ein leiser Weg hinein.
  if (mess.length && !ohne.length) {
    return `<button class="erststand fertig" data-erststand="1">
        <span class="es-ik ok">${HAKEN_ICON}</span>
        <span class="es-tx">
          <span class="es-t">Anfangszählerstände hinterlegt</span>
          <span class="es-d">${mess.length === 1
            ? 'Für den Zähler ist ein Erststand'
            : `Für alle ${mess.length} Zähler ist ein Erststand`} vor der ersten
            Abrechnung erfasst — Übersicht ansehen.</span>
        </span></button>`;
  }

  const text = !zaehlerListe.length
    ? 'Noch keine Zähler angelegt — für verbrauchsabhängige Kosten die Zähler '
      + 'und ihren Anfangsstand vor der ersten Abrechnung einrichten.'
    : ohne.length === mess.length
      ? (mess.length === 1
          ? 'Dem Zähler fehlt noch der Anfangsstand vor der ersten Abrechnung.'
          : `Allen ${mess.length} Zählern fehlt noch der Anfangsstand vor der `
            + 'ersten Abrechnung.')
      : `${ohne.length} von ${mess.length} Zählern `
        + `${ohne.length === 1 ? 'hat' : 'haben'} noch keinen Anfangsstand.`;

  const zielAttr = zielId != null ? ` data-z="${esc(String(zielId))}"` : '';
  return `<button class="erststand offen" data-erststand="1"${zielAttr}>
      <span class="es-ik">${GAUGE_ICON}</span>
      <span class="es-tx">
        <span class="es-t">Anfangszählerstand erfassen</span>
        <span class="es-d">${esc(text)}</span>
      </span>
      <span class="es-arr" aria-hidden="true">›</span>
    </button>`;
}

/* Die Anfangsstand-Rubrik an Ort und Stelle neu zeichnen: nach dem Speichern
   soll der Zähler oben stimmen, ohne die ganze Seite neu zu laden. */
export function erststandAuffrischen() {
  const alt = document.querySelector('.erststand');
  if (!alt) return;
  const html = erststandHtml(erststandZiel);
  if (!html) return alt.remove();
  const halter = document.createElement('div');
  halter.innerHTML = html;
  const neu = halter.firstElementChild;
  if (neu) alt.replaceWith(neu);
}

/* N288 — der Zählerstand steht als Text im Feld, nicht als `type="number"`:
   ein Gaszähler zeigt „12.345", und in einem Zahlenfeld ist der Punkt je nach
   Browser mal Tausender-, mal Dezimaltrenner. Geschrieben wird deutsch
   („12.345,678"), gelesen wird mit `zahlAus` — dieselbe Regel wie überall. */
const standText = n => n == null
  ? '' : Number(n).toLocaleString('de-DE', { maximumFractionDigits: 3 });

const azZahl = (n, einheit) =>
  `${(n ?? 0).toLocaleString('de-DE', { maximumFractionDigits: 3 })}`
  + (einheit ? ` ${einheit}` : '');

/* Zähler nach Kostenart bündeln — Wasser, Warmwasser, Strom und Heizöl stehen
   sonst bunt durcheinander. Die Messeinheit steht am Gruppentitel, nicht an
   jeder Zeile: sie ist innerhalb einer Kostenart ohnehin dieselbe. */
function azGruppen(liste) {
  const map = new Map();
  for (const z of liste) {
    const art = z.kostenart || 'Ohne Kostenart';
    const schluessel = `${art}|${z.messeinheit || ''}`;
    if (!map.has(schluessel)) {
      map.set(schluessel, { art, einheit: z.messeinheit || '', zaehler: [] });
    }
    map.get(schluessel).zaehler.push(z);
  }
  return [...map.values()];
}

export async function anfangsstaendeDialog() {
  const dlg = document.createElement('dialog');
  dlg.className = 'immo-dlg az-dlg';
  document.body.appendChild(dlg);
  dlg.addEventListener('close', () => dlg.remove());

  // Frisch holen: der Stand kann inzwischen in der Zähler-Konfig geändert
  // worden sein. Scheitert es, wird mit dem geladenen Stand gearbeitet.
  try {
    const frisch = await api(`/objekte/${encodeURIComponent(slug)}/zaehler`);
    if (Array.isArray(frisch)) setZaehlerListe(frisch);
  } catch { /* Beiwerk — der geladene Stand tut es auch */ }

  // Der Anfangsstand gehört vor die erste Abrechnung: frühester Periodenbeginn.
  const starts = ((daten && daten.zeitraeume) || [])
    .map(z => z.start).filter(Boolean).sort();
  // N288 — `toISOString()` rechnet nach UTC: wer nachts um eins einen Zähler
  // erfasst, bekäme als Vorgabe den Vortag. `heuteIso()` rechnet lokal.
  const vorgabeDatum = starts[0] || heuteIso();

  const inArbeit = new Set();   // Zähler, deren vorhandener Stand ersetzt wird
  let meldung = null;           // { text, art } — im Dialog, nie als Toast

  /* Die Datumsfelder im eigenen Design. `male()` baut den Dialog jedes Mal neu,
     deshalb werden die alten Chooser vorher gelöst — sonst häufen sich mit
     jedem Neuzeichnen tote Lauscher an (dasselbe Muster wie in
     `renovierung/formulare.js` und `objekt/formular.js`). */
  let datumChooser = [];
  const datumwahlLoesen = () => {
    for (const d of datumChooser) {
      try { d.zerstoere(); } catch { /* schon weg */ }
    }
    datumChooser = [];
  };
  const datumwahlBauen = () => {
    datumwahlLoesen();
    for (const halter of dlg.querySelectorAll('[data-az-datumwahl]')) {
      const zid = halter.dataset.azDatumwahl;
      const feld = dlg.querySelector(`input[data-az-datum="${zid}"]`);
      if (!feld) continue;
      datumChooser.push(datumwahl(halter, {
        wert: feld.value,
        label: `Datum des Anfangsstands für ${halter.dataset.name || 'den Zähler'}`,
        aenderung: neu => { feld.value = neu; },
      }));
    }
  };
  dlg.addEventListener('close', datumwahlLoesen);

  const zeileHtml = z => {
    const anf = z.anfangsstand;
    const ersetzen = inArbeit.has(z.id);
    // Erledigt und nicht in Bearbeitung: nur zeigen. Ein Ändern ist möglich,
    // aber nie beiläufig — es braucht den bewussten Griff zu „Ändern".
    if (anf && !ersetzen) {
      return `<div class="az-zeile" data-az-zeile="${z.id}">
          <div class="az-kopfz">
            <span class="az-hak">${HAKEN_ICON}</span>
            <span class="az-n">${esc(z.name)}</span>
            <button class="az-aend" data-az-aend="${z.id}">Ändern</button>
          </div>
          <span class="az-stand">${esc(azZahl(anf.stand, z.messeinheit))}
            · am ${esc(datum(anf.datum))}</span>
        </div>`;
    }
    // N120 — `direkt` heisst: der eingetragene Wert IST der Jahresverbrauch,
    // es gibt keine Zählerstände. Ein Anfangsstand bleibt dort rechnerisch
    // wirkungslos; das steht dran, statt den Nutzer suchen zu lassen.
    const hinweis = ersetzen
      ? `<span class="az-hinw">Ersetzt den bisherigen Anfangsstand
           ${esc(azZahl(anf.stand, z.messeinheit))} vom ${esc(datum(anf.datum))}.</span>`
      : z.typ === 'direkt'
        ? `<span class="az-hinw leise">Hier wird der fertige Verbrauch je
             Abrechnung eingetragen, kein Zählerstand — ein Anfangsstand ist
             deshalb nicht nötig.</span>`
        : '';
    return `<div class="az-zeile ${ersetzen ? 'aend' : 'offen'}" data-az-zeile="${z.id}">
        <div class="az-kopfz">
          <span class="${ersetzen ? 'az-hak' : 'az-punkt'}">${ersetzen ? HAKEN_ICON : ''}</span>
          <span class="az-n">${esc(z.name)}</span>
        </div>
        ${hinweis}
        <div class="az-felder">
          <div class="az-f"><label for="azs${z.id}">Stand</label>
            <input id="azs${z.id}" type="text" inputmode="decimal"
              value="${esc(standText(anf ? anf.stand : null))}"
              data-az-stand="${z.id}" aria-label="Anfangsstand ${esc(z.name)}">
            ${z.messeinheit ? `<span class="az-eh">${esc(z.messeinheit)}</span>` : ''}
          </div>
          <!-- N288 — kein natives Datumsfeld: auf dem iPhone legt es einen
               Systemkalender ÜBER die ganze Maske. Der echte (ISO-)Wert steht
               im versteckten Feld, den Kalender baut datumwahl.js. -->
          <div class="az-dat" style="flex:1 1 175px;min-width:0"
               data-az-datumwahl="${z.id}"
               data-name="${esc(z.name)}"></div>
          <input type="hidden" value="${esc(anf ? anf.datum : vorgabeDatum)}"
                 data-az-datum="${z.id}">
          <div class="az-knoepfe">
            ${ersetzen ? `<button class="az-ab" data-az-ab="${z.id}">Abbrechen</button>` : ''}
            <button class="az-sp" data-az-save="${z.id}">${ersetzen ? 'Ersetzen' : 'Speichern'}</button>
          </div>
        </div>
      </div>`;
  };

  const abschnittHtml = (titel, liste, klasse = '') => {
    if (!liste.length) return '';
    return `<div class="az-abschnitt">
        <span class="az-at ${klasse}">${esc(titel)} (${liste.length})</span>
        ${azGruppen(liste).map(g => `<div class="az-gruppe">
          <div class="az-gt"><span class="zi">${kostenIcon(g.art)}</span>
            <span class="az-gn">${esc(g.art)}</span>
            ${g.einheit ? `<span class="az-me">${esc(g.einheit)}</span>` : ''}</div>
          ${g.zaehler.map(zeileHtml).join('')}</div>`).join('')}
      </div>`;
  };

  const male = () => {
    const halter = dlg.querySelector('.az-body');
    const scroll = halter ? halter.scrollTop : 0;
    const aktiv = zaehlerListe.filter(z => z.aktiv !== false);
    const mess = aktiv.filter(z => !['rest', 'direkt'].includes(z.typ));
    const rest = aktiv.filter(z => z.typ === 'rest');
    // Ein Zähler, dessen Stand gerade ersetzt wird, bleibt unter „bereits
    // erfasst" — er fehlt ja nicht, er wird nur geändert.
    const offen = mess.filter(z => !z.anfangsstand);
    const fertig = mess.filter(z => z.anfangsstand);
    const anteil = mess.length ? Math.round(fertig.length / mess.length * 100) : 0;

    dlg.innerHTML = `
      <div class="zd-kopf"><span class="zd-t">Anfangszählerstände</span>
        <button class="zd-x" data-nein aria-label="Schließen">×</button></div>
      <div class="az-body">
        <p class="az-intro">Der Anfangsstand ist der Zählerstand <b>vor der
          ersten Abrechnung</b>. Er gehört zu keinem Abrechnungszeitraum — von
          ihm aus rechnet jede spätere Periode ihren Verbrauch.</p>
        <div class="az-fort">
          <div class="az-balken"><i style="width:${anteil}%"></i></div>
          <span class="az-fz">${fertig.length} von ${mess.length} erfasst</span>
        </div>
        ${!mess.length ? `<div class="az-leer">Für dieses Objekt ist noch kein
          messender Zähler angelegt.</div>` : ''}
        ${(mess.length && !offen.length) ? `<div class="az-leer">Alle
          ${mess.length} Zähler haben einen Anfangsstand — hier steht, welcher.</div>` : ''}
        ${abschnittHtml('Fehlt noch', offen, 'offen')}
        ${abschnittHtml('Bereits erfasst', fertig)}
        ${rest.length ? `<p class="az-fuss-note">${rest.length === 1
            ? 'Ein Rest-Zähler'
            : `${rest.length} Rest-Zähler`} (${rest.map(z => esc(z.name)).join(', ')})
          ${rest.length === 1 ? 'braucht' : 'brauchen'} keinen Anfangsstand —
          ${rest.length === 1 ? 'sein' : 'ihr'} Stand ergibt sich rechnerisch aus
          Gesamtzähler minus Unterzähler.</p>` : ''}
      </div>
      ${meldung ? `<div class="az-meld ${meldung.art}">${esc(meldung.text)}</div>` : ''}
      <div class="zd-fuss">
        ${erststandZiel != null
          ? '<button class="az-konfig" data-az-konfig>Zähler verwalten</button>' : ''}
        <button class="zd-ok" data-nein>Fertig</button>
      </div>`;
    const neu = dlg.querySelector('.az-body');
    if (neu) neu.scrollTop = scroll;
    datumwahlBauen();
  };

  async function speichern(id) {
    const zid = Number(id);
    const zeile = dlg.querySelector(`[data-az-zeile="${zid}"]`);
    if (!zeile) return;
    const standEl = zeile.querySelector('[data-az-stand]');
    const datumEl = zeile.querySelector('[data-az-datum]');
    const stand = zahlAus(standEl);
    if (stand == null) {
      meldung = { text: 'Bitte einen Zählerstand eintragen.', art: 'fehler' };
      return male();
    }
    if (!datumEl.value) {
      meldung = { text: 'Bitte das Datum des Anfangsstands angeben.', art: 'fehler' };
      return male();
    }
    const knopf = zeile.querySelector('[data-az-save]');
    if (knopf) { knopf.disabled = true; knopf.textContent = 'Speichere …'; }
    let neu;
    try {
      // N96 — bewusst OHNE `zeitraum_id`: der Anfangsstand hängt an keiner Periode.
      neu = await api(`/zaehler/${zid}/anfangsstand`,
                      { method: 'POST', body: { stand, datum: datumEl.value } });
    } catch (fehler) {
      meldung = { text: String(fehler?.message || 'Speichern ging nicht.'), art: 'fehler' };
      return male();
    }
    const i = zaehlerListe.findIndex(z => Number(z.id) === zid);
    const ersatz = (neu && neu.id != null)
      ? neu
      : (i >= 0 ? { ...zaehlerListe[i], anfangsstand: { stand, datum: datumEl.value } }
                : { id: zid, anfangsstand: { stand, datum: datumEl.value } });
    if (i >= 0) updateZaehler(zid, ersatz);
    inArbeit.delete(zid);
    meldung = { text: `✓ Anfangsstand gespeichert: ${azZahl(stand,
      (i >= 0 ? zaehlerListe[i].messeinheit : ''))}.`, art: 'ok' };
    male();
    erststandAuffrischen();
  }

  dlg.addEventListener('click', e => {
    if (e.target.closest('[data-nein]')) return dlg.close();
    const aend = e.target.closest('[data-az-aend]');
    if (aend) {
      inArbeit.add(Number(aend.dataset.azAend));
      meldung = null;
      male();
      dlg.querySelector(`#azs${aend.dataset.azAend}`)?.focus();
      return;
    }
    const ab = e.target.closest('[data-az-ab]');
    if (ab) { inArbeit.delete(Number(ab.dataset.azAb)); meldung = null; return male(); }
    const sp = e.target.closest('[data-az-save]');
    if (sp) return speichern(sp.dataset.azSave);
    if (e.target.closest('[data-az-konfig]') && erststandZiel != null) {
      dlg.close();
      location.href = `zeitraum.html?z=${encodeURIComponent(erststandZiel)}`;
    }
  });

  // Enter im Feld speichert die Zeile — sonst müsste man für 14 Zähler
  // vierzehnmal zum Knopf greifen.
  dlg.addEventListener('keydown', e => {
    if (e.key !== 'Enter') return;
    const feld = e.target.closest('[data-az-stand],[data-az-datum]');
    if (!feld) return;
    e.preventDefault();
    speichern(feld.dataset.azStand || feld.dataset.azDatum);
  });

  male();
  dlg.showModal();
}
