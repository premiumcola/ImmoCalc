/* N139/N154/N160 — Jahreseingabe, Rechenanstoss und Ergebnis-Kacheln.

   Zwei Seiten, zwei Aufgaben (N160): die VERBRAUCHSSEITE ist massgeblich
   (Verteilung, Kosten, Autarkie), die ERZEUGERSEITE traegt allein die
   Einspeiseverguetung. Deshalb zwei Bloecke statt eines Rasters.

   Umzug ohne Verhaltensaenderung: dieselben PUT-, Rechnen- und Anzeige-
   Funktionen wie zuvor inline in strom.html. */
import { api, esc, eur, melde } from '../immo.js';
import { S, inhalt } from './state.js';
import { kwh, ct, prozent, feldZahl } from './helpers.js';
import { verlaufZeigen } from './verlauf.js';

export const F_JAHR_VERBRAUCH = [
  ['netz_kwh', 'Verbrauch Netz', 'kWh', 1],
  ['solar_kwh', 'Verbrauch PV', 'kWh', 1],
  ['akku_kwh', 'Verbrauch Akku', 'kWh', 1],
];

export const F_JAHR_ERZEUGUNG = [
  ['pv_produktion_kwh', 'PV-Produktion', 'kWh', 1],
  ['einspeisung_kwh', 'Einspeisung', 'kWh', 1],
  ['verguetung_eur', 'Vergütung', '€', 0.01],
];

/* Werte der JAHRESfelder als Objekt (leeres Feld = 0).

   N288 — gelesen wird ueber `feldZahl` (helpers.js), das die deutsche Regel
   aus immo.js benutzt, statt sie hier ein zweites Mal zu schreiben. */
export function werteAusForm() {
  const werte = {};
  inhalt.querySelectorAll('input[data-feld]').forEach(el => {
    werte[el.dataset.feld] = feldZahl(el);
  });
  return werte;
}

/* Eingaben in die Maske schreiben. 0 bleibt leer, damit die Maske nicht mit
   Nullen zugestellt ist und man gleich lostippen kann. */
export function formFuellen(werte) {
  inhalt.querySelectorAll('input[data-feld]').forEach(el => {
    const v = werte[el.dataset.feld];
    el.value = (v == null || v === 0) ? '' : v;
  });
}

/* N154/N160 — massgeblich ist die VERBRAUCHSSEITE: 10.800 kWh, davon
   24 % Netz, 50 % PV, 26 % Speicher. Daraus kommt die Autarkie
   (8.208 von 10.800 = 76 %). Die fruehere Kachel „Eigenverbrauch"
   (Produktion − Einspeisung, 8.375 kWh) ist ersatzlos weg. */
function autarkieKacheln(a) {
  if (!a) return '';
  return `
    <div class="k"><span class="kl">Autarkie <span class="kh">Anteil des
      Verbrauchs aus eigener Anlage</span></span>
      <span class="kv pos">${prozent(a.prozent)}</span>
      <span class="knote">${kwh(a.eigen_kwh)} von ${kwh(a.verbrauch_kwh)}</span></div>
    <div class="k"><span class="kl">Selbst gedeckt <span class="kh">PV +
      Speicher</span></span><span class="kv">${kwh(a.eigen_kwh)}</span>
      <span class="knote">${kwh(a.solar_kwh)} PV · ${kwh(a.akku_kwh)} Speicher</span></div>
    <div class="k"><span class="kl">Zugekauft <span class="kh">vom Netz</span></span>
      <span class="kv">${kwh(a.netz_kwh)}</span></div>`;
}

/* Das Engine-Ergebnis in die Karten schreiben (Inputs bleiben unberuehrt). */
function ergebnisZeigen(r) {
  const pv = r.pv;
  document.getElementById('pv').innerHTML = `
    ${autarkieKacheln(r.autarkie)}
    <div class="k"><span class="kl">Satz</span><span class="kv">${(pv.satz_ct ?? 0).toLocaleString('de-DE', { maximumFractionDigits: 2 })} ct</span></div>
    <div class="k"><span class="kl">Einspeisevergütung</span><span class="kv">${eur(pv.einspeiseverguetung)}</span></div>
    <div class="k"><span class="kl">Ersparnis Zukauf <span class="kh">rechnerisch,
      kein Ertrag</span></span><span class="kv">${eur(pv.eigenverbrauch_ersparnis)}</span></div>`;

  tippsZeigen(r);
  tankZeigen();

  const w = document.getElementById('warnungen');
  w.innerHTML = (r.warnungen || []).map(t =>
    `<div class="warnung"><span class="wi" aria-hidden="true">⚠</span><span>${esc(t)}</span></div>`).join('');
}

/* --------------------------------------------------------------------------
   N154 — wo noch etwas zu holen ist.

   Jeder Hinweis steht auf ERFASSTEN Zahlen dieses Jahres und nennt sie. Fehlt
   die Grundlage, faellt der Hinweis weg — ein Tipp auf einer erfundenen
   Annahme ist schlechter als kein Tipp.
   -------------------------------------------------------------------------- */
const round1 = n => Math.round(n * 10) / 10;

function tippIcon(pfad) {
  return `<svg class="ti" viewBox="0 0 24 24" width="19" height="19" fill="none"
    stroke="currentColor" stroke-width="1.6" stroke-linecap="round"
    stroke-linejoin="round" aria-hidden="true">${pfad}</svg>`;
}

const I_BLITZ = '<path d="M13 3 5.5 13.5H11l-.5 7.5L18.5 10.5H12.5L13 3Z"/>';
const I_STECKER = '<path d="M9 3v5M15 3v5"/><path d="M6 8h12v2.5a6 6 0 0 1-12 0V8Z"/><path d="M12 16.5V21"/>';
const I_AKKU = '<rect x="3" y="7.5" width="15.5" height="9" rx="2.5"/><path d="M21 11v2"/><path d="M8 12h5.5"/>';

function tippListe(r) {
  const q = r.quellen || {};
  const netzPreis = (q.netz || {}).preis || 0;
  const solarPreis = (q.solar || {}).preis || 0;
  const akku = (q.akku || {}).kwh || 0;
  const a = r.autarkie || {};
  const pv = r.pv || {};
  const tipps = [];

  // 1) Der staerkste Hebel: eine selbst verbrauchte kWh ist mehr wert als
  //    eine eingespeiste. Nur mit beiden Preisen und tatsaechlicher
  //    Einspeisung.
  const satz = pv.satz_ct || 0;
  if (pv.einspeisung_kwh > 0 && satz > 0 && netzPreis > 0
      && netzPreis * 100 > satz) {
    const unterschied = netzPreis * 100 - satz;
    tipps.push([I_BLITZ,
      `<b>Selbst verbrauchen schlägt einspeisen.</b> Eingespeist bringt
       ${ct(satz)} je kWh, zugekauft kostet ${ct(netzPreis * 100)} — jede kWh,
       die im Haus bleibt, ist ${ct(unterschied)} mehr wert. Bei
       ${kwh(pv.einspeisung_kwh)} Einspeisung sind das rechnerisch bis zu
       ${eur(pv.einspeisung_kwh * unterschied / 100)} im Jahr.`]);
  }

  // 2) Was das E-Auto aus dem Netz gezogen hat — die Zahl traegt der Nutzer
  //    selbst ein (`eauto_extern_kwh`), sie steht nicht in der Wallbox-Wolke.
  const extern = S.jahresSatz.eauto_extern_kwh || 0;
  if (extern > 0 && netzPreis > solarPreis && solarPreis > 0) {
    tipps.push([I_STECKER,
      `<b>Das E-Auto lud ${kwh(extern)} aus dem Netz.</b> Zum Satz des eigenen
       Stroms (${ct(solarPreis * 100)} statt ${ct(netzPreis * 100)}) wären das
       ${eur(extern * (netzPreis - solarPreis))} weniger — tagsüber laden
       verschiebt genau diese Menge.`]);
  }

  // 3) Was der Speicher in die Nacht rettet. Ohne ihn kaeme dieselbe Menge
  //    aus dem Netz — deshalb steht die Quote ohne Speicher daneben.
  if (akku > 0 && a.verbrauch_kwh > 0) {
    const ohne = round1((a.eigen_kwh - akku) / a.verbrauch_kwh * 100);
    tipps.push([I_AKKU,
      `<b>Der Speicher rettet ${kwh(akku)} in die Nacht.</b> Ohne ihn läge die
       Autarkie bei ${prozent(ohne)} statt ${prozent(a.prozent)} — je mehr
       Verbrauch in die Sonnenstunden wandert, desto weniger muss er leisten.`]);
  }
  return tipps;
}

function tippsZeigen(r) {
  const ziel = document.getElementById('tipps');
  if (!ziel) return;
  const tipps = tippListe(r);
  ziel.innerHTML = !tipps.length ? '' : `<div class="tipps">
    <span class="tt">Wo noch etwas zu holen ist</span>
    ${tipps.map(([icon, text]) =>
      `<div class="tz">${tippIcon(icon)}<span>${text}</span></div>`).join('')}
  </div>`;
}

/* Was der Anlage aus der E-Tankstelle zuflieszt: die erfassten Ladungen des
   gewaehlten Jahres. Nutzer und Abrechnungen werden auf `tankstelle.html`
   verwaltet — hier steht nur die Summe (N132/N139). */
export async function tankZeigen() {
  const ziel = document.getElementById('tank');
  if (!ziel || !S.objektSlug) return;
  let d = {};
  try {
    d = await api(`/objekte/${encodeURIComponent(S.objektSlug)}/tankstelle/${S.jahrWahl.wert()}`);
  } catch {
    d = {};                       // keine Ladungen erfasst — dann eben Null
  }
  // Der Satz steht schon im Eingabefeld darueber und wird hier nicht
  // wiederholt.
  ziel.innerHTML = `
    <div class="k"><span class="kl">Ladungen</span><span class="kv">${(d.ladungen || []).length}</span></div>
    <div class="k"><span class="kl">Geladen</span><span class="kv">${kwh(d.kwh_gesamt || 0)}</span></div>
    <div class="k"><span class="kl">Zufluss</span><span class="kv pos">${eur(d.betrag_gesamt || 0)}</span></div>`;
}

/* --------------------------------------------------------------------------
   Der Rechen-Anstoss.

   `rechnen` holt das aktuelle Ergebnis und zieht den Verlauf nach; die
   Debounce-Kette dahinter (`angestossen`) friert Objekt und Jahr ein, damit
   wer waehrend der 550 ms wechselt, nicht die Zahlen der einen Anlage in den
   Datensatz der anderen schreibt.
   -------------------------------------------------------------------------- */
export async function rechnen() {
  if (!S.objektSlug) return;
  try {
    const r = await api(
      `/objekte/${encodeURIComponent(S.objektSlug)}/strom/${S.jahrWahl.wert()}/rechnung`);
    ergebnisZeigen(r);
    verlaufZeigen();              // N127 — laeuft ueber alle Jahre, nebenher
  } catch (fehler) {
    melde(String(fehler.message || fehler), 'neg');
  }
}

/* Der PUT nimmt IMMER den ganzen Satz: seine Felder haben den Vorgabewert 0,
   ein Teil-PUT setzte alles, was diese Maske nicht zeigt (Zaehlerstaende,
   Preise, E-Auto-Aufteilung), still auf 0. Deshalb liegt der zuletzt
   gelesene Satz darunter und nur die Felder der Maske werden darueber
   gelegt. `jahr` steht im Pfad; die Einheiten-Zuordnung wird gar nicht erst
   mitgeschickt — nicht mitgeschickt heiszt beim Server unveraendert. */
function basisSatz() {
  const satz = { ...S.jahresSatz };
  delete satz.jahr;
  delete satz.wg_einheiten;
  delete satz.buero_einheiten;
  return satz;
}

export function angestossen() {
  const werte = werteAusForm();
  const stempel = JSON.stringify(werte);
  if (stempel === S.letzteWerte) return;
  const slug = S.objektSlug;
  const jahr = S.jahrWahl.wert();
  clearTimeout(S.speicherZeit);
  S.speicherZeit = setTimeout(async () => {
    S.speicherZeit = null;
    if (slug !== S.objektSlug || jahr !== S.jahrWahl.wert()) return;
    S.letzteWerte = stempel;
    try {
      const satz = await api(
        `/objekte/${encodeURIComponent(slug)}/strom/${jahr}`,
        { method: 'PUT', body: { ...basisSatz(), ...werte } });
      if (slug !== S.objektSlug || jahr !== S.jahrWahl.wert()) return;
      S.jahresSatz = satz;
      await rechnen();
    } catch (fehler) {
      melde(String(fehler.message || fehler), 'neg');
    }
  }, 550);
}
