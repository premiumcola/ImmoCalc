/* N131/N155/N161 — den SolarEdge-Screenshot lesen lassen.

   Der Nutzer laedt seinen Screenshot hoch: `POST /api/solaredge/lesen` gibt
   die erkannten Werte zurueck und speichert nichts. Uebernommen wird trotzdem
   nichts von allein — dazwischen steht die Pruefansicht (erkannt neben
   gespeichert). Beim Uebernehmen wandert der Screenshot zusaetzlich in die
   Nextcloud (`seScreenshotAblegen`); die Vorschau bleibt als Beleg stehen
   (N155).

   Umzug ohne Verhaltensaenderung: dieselben Endpunkte, dieselbe drei-
   stufige Kette (lesen → pruefen → uebernehmen). */
import { esc, melde } from '../immo.js';
import { S, inhalt } from './state.js';
import { kwh, feldZahl } from './helpers.js';
import { angestossen } from './jahre.js';

/* Feld · Bezeichnung · Herkunft im Bild · Menge · Anteil. Aus derselben
   Liste entsteht die Pruefansicht und die Uebernahme. */
const SE_ZEILEN = [
  ['pv_produktion_kwh', 'PV-Produktion', 'Balken „Produktion"',
   d => d.produktion_kwh, () => null],
  ['einspeisung_kwh', 'Einspeisung', '„Ins Netz"',
   d => (d.produktion_kwh_je_anteil || {}).netz, d => d.produktion_netz_prozent],
  ['netz_kwh', 'Verbrauch Netz', '„Vom Netz"',
   d => (d.verbrauch_kwh_je_anteil || {}).netz, d => d.verbrauch_netz_prozent],
  ['solar_kwh', 'Verbrauch PV', '„Aus PV-Energie"',
   d => (d.verbrauch_kwh_je_anteil || {}).pv, d => d.verbrauch_pv_prozent],
  ['akku_kwh', 'Verbrauch Akku', '„Vom Speicher"',
   d => (d.verbrauch_kwh_je_anteil || {}).speicher,
   d => d.verbrauch_speicher_prozent],
];

const SE_HINWEIS = 'Bitte die Reihenfolge Netz · PV · Speicher mit dem Bild '
  + 'vergleichen: zwei vertauschte Anteile ergeben zusammen weiterhin 100 % '
  + 'und fallen keiner Pruefung auf. Erst mit „Übernehmen" wandern die Zahlen '
  + 'in die Felder.';

const seProzent = p => p == null ? ''
  : p.toLocaleString('de-DE', { maximumFractionDigits: 1 }) + ' %';

/* Der aktuelle Stand eines Feldes — das, wogegen der erkannte Wert steht. */
function seJetzt(feld) {
  return feldZahl(inhalt.querySelector(`input[data-feld="${feld}"]`));
}

function seZeile(feld, name, herkunft, wert, anteil) {
  const erkannt = wert != null;
  const rechts = erkannt
    ? `<span class="alt">${kwh(seJetzt(feld))}</span><span class="pf"
       aria-hidden="true">→</span><span class="neu">${kwh(wert)}</span>`
    : `<span class="neu leer">nicht erkannt</span>`;
  const sub = [herkunft, seProzent(anteil)].filter(Boolean).join(' · ');
  return `<div class="se-zeile">
    <span class="se-n">${esc(name)}</span>
    <span class="se-w">${rechts}</span>
    <span class="se-sub">${esc(sub)}</span>
  </div>`;
}

/* Die Pruefansicht bauen — und dabei merken, was uebernommen werden darf. */
function sePruefung(d) {
  S.seWerte = {};
  const zeilen = SE_ZEILEN.map(([feld, name, herkunft, menge, anteil]) => {
    const roh = menge(d);
    const wert = roh == null ? null : Math.round(roh);
    if (wert != null) S.seWerte[feld] = wert;
    return seZeile(feld, name, herkunft, wert, anteil(d));
  }).join('');

  const etwas = Object.keys(S.seWerte).length > 0;
  // Kam gar nichts durch, sagen Hinweis und Warnungen alle dasselbe — dann
  // steht der Satz genau einmal da. Erst wenn etwas erkannt wurde, tragen
  // die Warnungen eigene Information (Anteile ≠ 100 %, fehlende Einheit).
  const erklaerung = etwas ? esc(SE_HINWEIS)
    : esc(d.hinweis || 'Aus dem Bild kam nichts Übernehmbares — bitte die Werte '
          + 'unten von Hand eintragen.');
  const warnungen = etwas ? (d.warnungen || []).map(t =>
    `<div class="warnung"><span class="wi" aria-hidden="true">⚠</span>
      <span>${esc(t)}</span></div>`).join('') : '';
  const zusatz = (etwas && d.hinweis) ? `<p class="seh">${esc(d.hinweis)}</p>` : '';
  const gesamt = d.verbrauch_kwh != null
    ? `<p class="se-fuss">Verbrauch laut Screenshot: <b>${kwh(d.verbrauch_kwh)}</b>
       — daraus kommen die drei Anteile.</p>` : '';

  return `<div class="se-pruef">
    <span class="set">${etwas ? 'Erkannte Werte prüfen' : 'Nichts erkannt'}</span>
    ${zusatz}
    <p class="seh">${erklaerung}</p>
    ${warnungen}
    ${zeilen}
    ${gesamt}
    <div class="se-knoepfe">
      ${etwas ? '<button type="button" class="btn" data-se-ok>Übernehmen</button>'
        : ''}
      <button type="button" class="btn leise" data-se-weg>${
        etwas ? 'Verwerfen' : 'Schließen'}</button>
    </div>
  </div>`;
}

/* Eine ruhige Aussage, wenn das Lesen gar nicht erst zustande kam. Die
   Handeingabe darunter bleibt unberuehrt — sie ist der Weg, der immer geht. */
function seFehler(text) {
  S.seWerte = {};
  return `<div class="se-pruef">
    <span class="set">Screenshot nicht gelesen</span>
    <p class="seh">${esc(text)} Die Werte lassen sich unten von Hand eintragen.</p>
    <div class="se-knoepfe">
      <button type="button" class="btn leise" data-se-weg>Schließen</button>
    </div>
  </div>`;
}

/* Das Bild hochladen. `api()` schickt JSON — hier geht ein multipart-Paket
   direkt an `fetch`, wie ueberall, wo eine Datei hochgeladen wird. */
async function seLesen(datei) {
  const box = document.getElementById('seBox');
  const knopf = inhalt.querySelector('[data-se-waehlen]');
  if (!box) return;
  // Das Bild bleibt stehen, egal wie das Lesen ausgeht: klappt es nicht,
  // traegt der Nutzer von Hand ein — der Beleg gehoert dann erst recht dazu.
  seBildMerken(datei);
  box.innerHTML = '<div class="se-pruef"><span class="set">Der Screenshot '
    + 'wird gelesen …</span><p class="seh">Das dauert ein paar Sekunden.</p></div>';
  if (knopf) knopf.disabled = true;
  try {
    const paket = new FormData();
    paket.append('datei', datei, datei.name || 'solaredge.png');
    const antwort = await fetch('/api/solaredge/lesen',
                                { method: 'POST', body: paket });
    if (!antwort.ok) {
      const grund = await antwort.json().then(k => k.detail).catch(() => null);
      box.innerHTML = seFehler(grund || `Fehler ${antwort.status}.`);
      return;
    }
    box.innerHTML = sePruefung(await antwort.json());
  } catch (fehler) {
    box.innerHTML = seFehler(String(fehler.message || fehler));
  } finally {
    if (knopf) knopf.disabled = false;
  }
}

/* Bestaetigt: die erkannten Werte in die Felder schreiben und speichern
   lassen. Nur, was erkannt wurde — ein nicht gelesener Wert behaelt seinen
   Stand.

   N161 — beim Übernehmen wandert der Screenshot zusaetzlich als Beleg in die
   Nextcloud (`seScreenshotAblegen`). Das ist eine Zugabe: klappt es nicht
   (keine Cloud), bleibt die Uebernahme der Zahlen davon unberuehrt. */
function seUebernehmen() {
  const felder = Object.keys(S.seWerte);
  if (!felder.length) return;
  felder.forEach(feld => {
    const el = inhalt.querySelector(`input[data-feld="${feld}"]`);
    if (el) el.value = S.seWerte[feld] === 0 ? '' : S.seWerte[feld];
  });
  seSchliessen();
  angestossen();
  melde(`${felder.length} ${felder.length === 1 ? 'Wert' : 'Werte'} übernommen`,
        'pos');
  seScreenshotAblegen();       // der Beleg wandert in die Nextcloud (Zugabe)
}

/* N161 — den gemerkten Screenshot als Beleg ablegen lassen. Ein multipart-
   Paket direkt an `fetch` (wie beim Lesen), weil `api()` JSON schickt. Der
   Ausgang steht ehrlich in der Vorschau: „abgelegt" oder der ruhige Grund,
   warum nicht. Nie ein roter Fehler — die Zahlen sind laengst gespeichert. */
async function seScreenshotAblegen() {
  const schluessel = seSchluessel();
  const bild = S.seBilder.get(schluessel);
  if (!bild || !bild.datei || bild.abgelegt) return;
  const slug = S.objektSlug, jahr = S.jahrWahl.wert();
  try {
    const paket = new FormData();
    paket.append('datei', bild.datei, bild.name || 'solaredge.png');
    const antwort = await fetch(
      `/api/solaredge/objekte/${encodeURIComponent(slug)}/${jahr}/screenshot`,
      { method: 'POST', body: paket });
    const d = await antwort.json().catch(() => ({}));
    if (schluessel !== seSchluessel()) return;   // Objekt/Jahr inzwischen gewechselt
    if (antwort.ok && d.abgelegt) {
      bild.abgelegt = true;
      bild.pfad = d.pfad || '';
      bild.grund = '';
      melde('Screenshot in der Nextcloud abgelegt', 'pos');
    } else {
      bild.grund = d.grund || d.detail || `Ablage fehlgeschlagen (${antwort.status})`;
    }
  } catch (fehler) {
    if (schluessel !== seSchluessel()) return;
    bild.grund = String(fehler.message || fehler);
  }
  seBildZeigen();
}

function seSchliessen() {
  S.seWerte = {};
  const box = document.getElementById('seBox');
  if (box) box.innerHTML = '';
}

/* Ein Lauscher am Behaelter: die Karte wird bei jedem Jahreswechsel neu
   gezeichnet, ein Lauscher je Knopf ginge dabei verloren. */
inhalt.addEventListener('click', e => {
  if (e.target.closest('[data-se-waehlen]')) {
    const datei = inhalt.querySelector('[data-se-datei]');
    if (datei) datei.click();
  } else if (e.target.closest('[data-se-ok]')) {
    seUebernehmen();
  } else if (e.target.closest('[data-se-weg]')) {
    seSchliessen();
  }
});

inhalt.addEventListener('change', e => {
  const feld = e.target.closest('[data-se-datei]');
  if (!feld || !feld.files || !feld.files.length) return;
  const datei = feld.files[0];
  feld.value = '';            // damit dasselbe Bild erneut gewaehlt werden kann
  seLesen(datei);
});

/* --------------------------------------------------------------------------
   N155 — das gelesene Bild bleibt stehen.

   Der Screenshot ist der Beleg der eingetragenen Zahlen; verschwindet er
   nach dem Auslesen, steht spaeter niemand mehr die Herkunft. Er bleibt
   deshalb als Vorschau sichtbar, ein neues Bild ersetzt ihn.

   N161 — beim Uebernehmen wird der Screenshot zusaetzlich dauerhaft in der
   Nextcloud abgelegt (`seScreenshotAblegen`, `routers/solaredge.py`). Die
   Vorschau sagt ehrlich, in welchem Zustand er ist: noch nicht abgelegt
   (vor dem Uebernehmen), abgelegt (mit Pfad) oder — ohne eingerichtete
   Cloud — der ruhige Grund, warum die Ablage entfiel.
   -------------------------------------------------------------------------- */
export const seSchluessel = () => `${S.objektSlug}|${S.jahrWahl.wert()}`;

function seBildMerken(datei) {
  const schluessel = seSchluessel();
  const alt = S.seBilder.get(schluessel);
  if (alt) URL.revokeObjectURL(alt.url);     // das ersetzte Bild freigeben
  // Die Datei bleibt gemerkt: beim Uebernehmen wird sie in die Nextcloud
  // gelegt.
  S.seBilder.set(schluessel, { url: URL.createObjectURL(datei),
                               name: datei.name || 'Screenshot', datei,
                               abgelegt: false, pfad: '', grund: '' });
  seBildZeigen();
}

/* Der kurze Cloud-Pfad fuer die Bestaetigung — Objektordner weg, nur der Ort
   darunter („60_Nebenkosten/2025/…"), sonst laeuft die Zeile in die Breite. */
function seKurzpfad(pfad) {
  const teile = (pfad || '').split('/').filter(Boolean);
  return teile.slice(-3).join('/');
}

export function seBildZeigen() {
  const ziel = document.getElementById('seBild');
  if (!ziel) return;
  const bild = S.seBilder.get(seSchluessel());
  if (!bild) { ziel.innerHTML = ''; return; }
  let stand;
  if (bild.abgelegt) {
    const wo = bild.pfad ? ` · ${esc(seKurzpfad(bild.pfad))}` : '';
    stand = `<span class="se-abgelegt"><span class="hk" aria-hidden="true">✓</span>
      In der Nextcloud abgelegt${wo}</span>`;
  } else if (bild.grund) {
    stand = `<span>Beleg der eingetragenen Zahlen. Nicht abgelegt: ${esc(bild.grund)}</span>`;
  } else {
    stand = `<span>Beleg der eingetragenen Zahlen. Ein neues Bild auf die Fläche
      darüber ersetzt dieses. Beim Übernehmen wird er dauerhaft in der Nextcloud
      abgelegt.</span>`;
  }
  ziel.innerHTML = `<div class="sebild">
    <img src="${bild.url}" alt="Gelesener Screenshot: ${esc(bild.name)}">
    <div class="sebt"><b>${esc(bild.name)}</b>${stand}</div>
  </div>`;
}

/* --------------------------------------------------------------------------
   N153b — den Screenshot hineinziehen.

   Der Knopf bleibt (auf dem Handy fuehrt kein anderer Weg zum Ziel); am
   Rechner ist Ziehen der kuerzere. Am Ablauf aendert das nichts: hochladen
   → erkannte Werte ZUR PRUEFUNG zeigen → erst „Übernehmen" schreibt. Diese
   Bestaetigung ist das Einzige, was ein vertauschtes Netz/Speicher-Paar
   abfaengt.

   Ohne `preventDefault` im `dragover` oeffnet der Browser das
   fallengelassene Bild einfach im Tab — die Seite waere samt getippter
   Eingaben weg. Deshalb wird auch NEBEN der Flaeche abgefangen und dort
   schlicht nichts getan.
   -------------------------------------------------------------------------- */
const seZielTreffer = e => e.target instanceof Element
  && !!e.target.closest('[data-se-zone]');

function seZielAn(an) {
  const zone = inhalt.querySelector('[data-se-zone]');
  if (zone) zone.classList.toggle('dran', an);
}

/* Angenommen wird genau ein Bild. Alles andere wird gesagt, nicht
   geschluckt. */
function seAusAblage(dt) {
  const dateien = Array.from((dt && dt.files) || []);
  if (!dateien.length) return melde('Da war keine Datei dabei', 'neg');
  if (dateien.length > 1) return melde('Bitte nur ein Bild auf einmal', 'neg');
  if (!/^image\//.test(dateien[0].type || '')) {
    return melde('Nur Bilder — ein Screenshot der SolarEdge-Ansicht', 'neg');
  }
  seLesen(dateien[0]);
}

['dragenter', 'dragover'].forEach(art => document.addEventListener(art, e => {
  e.preventDefault();
  const treffer = seZielTreffer(e);
  if (e.dataTransfer) e.dataTransfer.dropEffect = treffer ? 'copy' : 'none';
  seZielAn(treffer);
}));

// Beim Wechsel zwischen Kindelementen feuert `dragleave` staendig — die
// Flaeche darf erst dunkeln, wenn der Zeiger sie wirklich verlassen hat.
document.addEventListener('dragleave', e => {
  const bleibt = e.relatedTarget instanceof Element
    && !!e.relatedTarget.closest('[data-se-zone]');
  if (!bleibt) seZielAn(false);
});

document.addEventListener('drop', e => {
  e.preventDefault();
  const treffer = seZielTreffer(e);
  seZielAn(false);
  if (treffer) seAusAblage(e.dataTransfer);
});
