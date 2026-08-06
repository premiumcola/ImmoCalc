/* matrix.js — der kompakte Quartal×Monat-Chooser (N193) samt Auswahl-Logik.
   Jahr-Pills oben, darunter vier Spalten Q1–Q4 mit je drei Monaten, darunter
   die klare Aktion („als abgerechnet setzen"). Ein Klick auf einen Monat nimmt
   ihn in die Abrechnung oder heraus, ein Klick auf den Quartalskopf das ganze
   Quartal. ✓ zeigt Abgerechnetes (N182/N193).

   Hier liegen zusaetzlich die abgerechnet-Marker-Helfer (`markerDeckt`,
   `monatAbgerechnet`, `quartalAbgerechnet`, `jahrAbgerechnet`,
   `periodeAbgerechnet`, `nutzerPeriodeAbgerechnet`) sowie die
   Zeitraum-Helfer (`monateDerQuartale`, `aktiveMonate`, `zeitraumParams`,
   `jahrWert`) — sie gehoeren logisch zur Matrix und werden von ihr wie von
   der Abrechnung gelesen. */
import { S, MONKURZ, QMON } from './state.js';
import { melde } from '../immo.js';
import { abrechnungZeigen } from './abrechnung.js';

export const jahrWert = () => S.jahrGewaehlt || new Date().getFullYear();

export function jahreUebernehmen(jahre) {
  S.jahreListe = jahre || [];
  // Ist das gewaehlte Jahr nicht (mehr) dabei, auf das juengste springen —
  // sonst zeigte die Abrechnung ein Jahr ohne jede Ladung.
  if (!S.jahreListe.includes(S.jahrGewaehlt)) {
    S.jahrGewaehlt = S.jahreListe.length ? S.jahreListe[S.jahreListe.length - 1] : 0;
  }
}

/* Die Monate der aktuell gewaehlten Quartale (ganzes Jahr = alle zwoelf). */
export function monateDerQuartale() {
  if (S.quartaleGewaehlt.includes(0)) return [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12];
  const s = new Set();
  for (const q of S.quartaleGewaehlt) (QMON[q] || []).forEach(m => s.add(m));
  return [...s].sort((a, b) => a - b);
}

/* Die Zeitraum-Parameter fuer jede Abfrage — Jahr, Quartalsauswahl und die
   abgewaehlten Monate. So sehen Liste, Vorschau, PDF und Versand denselben
   Ausschnitt. */
export function zeitraumParams() {
  const q = S.quartaleGewaehlt.includes(0) ? '0' : S.quartaleGewaehlt.join(',');
  const aus = [...S.ausMonate].sort((a, b) => a - b).join(',');
  return `jahr=${jahrWert()}&quartale=${q}&aus=${aus}`;
}

/* Ist ein Monat aktuell in der Abrechnung (im Zeitraum & nicht abgewählt)? */
export const monatAktiv = m => aktiveMonate().includes(m);
export const quartalAktiv = q => (QMON[q] || []).every(monatAktiv);

/* Die aktuell WIRKSAMEN Monate: die Monate der gewählten Quartale ohne die von
   Hand abgewählten. Sie sind der Bezug für „abgerechnet" (N187). */
export const aktiveMonate = () => monateDerQuartale().filter(m => !S.ausMonate.has(m));

/* N202 — ein kompaktes Label der gewählten Periode für den Sende-Button
   („Mai, Jun 2026" bzw. „2026" fürs ganze Jahr). */
export function periodeKurz() {
  const mo = aktiveMonate();
  if (mo.length === 12) return `${jahrWert()}`;
  return `${mo.map(m => MONKURZ[m - 1]).join(', ')} ${jahrWert()}`;
}

/* N187 — ein Marker „deckt" einen Monat, wenn er entweder monatsgenau auf ihn
   zeigt oder als Quartalsmarker das Quartal dieses Monats trägt. */
export const QUARTAL_VON = m => Math.floor((m - 1) / 3) + 1;
export const markerDeckt = (mk, j, m) => mk.jahr === j
  && (mk.monat === m || (mk.monat == null && mk.quartal === QUARTAL_VON(m)));

/* N214 — ein Monat gilt als „noch offen", wenn sein Ende in der Zukunft liegt.
   Solche Monate dürfen nicht als abgerechnet markiert werden. */
export function monatIstOffen(jahr, monat) {
  const heute = new Date();
  const monatsEnde = new Date(jahr, monat, 0);   // Tag 0 des Folgemonats
  return monatsEnde >= new Date(heute.getFullYear(), heute.getMonth(), heute.getDate());
}
export const monatAbgerechnet = (j, m) => S.abgerechnet.some(mk => markerDeckt(mk, j, m));

/* Ein Jahr gilt als abgerechnet, wenn alle zwölf Monate abgerechnet sind
   (je Monat genügt irgendein Nutzer — es ist nur das Signal am Jahres-Chip). */
export function jahrAbgerechnet(j) {
  for (let m = 1; m <= 12; m++) if (!monatAbgerechnet(j, m)) return false;
  return true;
}

/* Ist ein Quartal (des gewählten Jahres) abgerechnet? Für den Chip-Haken: ein
   Quartal gilt als abgerechnet, sobald mindestens ein Nutzer es ist; „Ganzes
   Jahr" (0) nur, wenn alle vier Quartale abgerechnet sind. */
export function quartalAbgerechnet(q) {
  const j = jahrWert();
  const monate = q === 0 ? [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12] : (QMON[q] || []);
  return monate.length > 0 && monate.every(m => monatAbgerechnet(j, m));
}

/* Ist die aktuell gewählte Periode für diesen Nutzer bereits abgerechnet? Sperrt
   dann seinen Versand-Knopf — derselbe Riegel wie im Backend (jedes gewählte
   Quartal zählt; „Ganzes Jahr" prüft alle vier). */
export function nutzerPeriodeAbgerechnet(nid) {
  if (!nid) return false;
  const j = jahrWert();
  const mo = aktiveMonate();
  // Gesperrt wird erst, wenn JEDER wirksame Monat für diesen Nutzer abgerechnet
  // ist — sonst gäbe es noch Neues zu verschicken (N187, feiner als quartalsweit).
  return mo.length > 0 && mo.every(m => S.abgerechnet.some(
    mk => mk.nutzer_id === nid && markerDeckt(mk, j, m)));
}

/* Gilt die ganze gewählte Periode als abgerechnet (für die Steuerung: dann bietet
   sie „entfernen" statt „markieren")? */
export function periodeAbgerechnet() {
  const mo = aktiveMonate();
  const j = jahrWert();
  return mo.length > 0 && mo.every(m => monatAbgerechnet(j, m));
}

/* N193 — der Zeitraum-Chooser als kompakte Quartal×Monat-Matrix: Jahr-Pills
   oben, darunter vier Spalten Q1–Q4 mit je drei Monaten, darunter die klare
   Aktion. Ein Klick auf einen Monat nimmt ihn in die Abrechnung oder heraus, ein
   Klick auf den Quartalskopf das ganze Quartal. ✓ zeigt Abgerechnetes. */
export function zeitraumWahl() {
  const jahre = S.jahreListe.length ? S.jahreListe : [jahrWert()];
  const jahrPill = j => {
    const ab = jahrAbgerechnet(j);
    return `<button type="button" data-jahr="${j}" aria-pressed="${jahrWert() === j}"
      ${ab ? 'title="Jahr abgerechnet"' : ''}>${j}${
      ab ? ' <span class="hk" aria-hidden="true">✓</span>' : ''}</button>`;
  };
  const qKopf = q => {
    const an = quartalAktiv(q), ab = quartalAbgerechnet(q);
    return `<button type="button" class="fm-q${an ? ' an' : ''}${ab ? ' fertig' : ''}"
      data-quartal="${q}" aria-pressed="${an}"
      title="ganzes Quartal Q${q}${ab ? ' — abgerechnet' : ''}">Q${q}${
      ab ? '<span class="hk" aria-hidden="true">✓</span>' : ''}</button>`;
  };
  const mZelle = m => {
    const an = monatAktiv(m), ab = monatAbgerechnet(jahrWert(), m);
    // N214 — noch nicht abgeschlossene Monate (Ende in der Zukunft) sind für die
    // „abgerechnet"-Markierung tabu; bereits abgerechnete bleiben klickbar,
    // damit man sie zur Korrektur wieder entfernen kann.
    const offen = !ab && monatIstOffen(jahrWert(), m);
    return `<button type="button" class="fm-m${an ? ' an' : ''}${ab ? ' fertig' : ''}${
        offen ? ' offen' : ''}" data-monat="${m}" aria-pressed="${an}"
      ${offen ? 'disabled' : ''}
      title="${ab ? 'bereits abgerechnet — anklicken, wählen, dann unten „abgerechnet-Status entfernen"'
              : (offen ? 'Noch nicht abgeschlossen — kann nicht abgerechnet werden' : '')}"
      >${MONKURZ[m - 1]}${ab ? '<span class="hk" aria-hidden="true">✓</span>' : ''}</button>`;
  };
  // Zeilenweise (row-major) füllen: erst die vier Quartalsköpfe, dann je
  // Monatszeile die vier Quartalsspalten — so steht Jan/Feb/Mär unter Q1 usw.
  const gitter = [1, 2, 3, 4].map(qKopf).join('')
    + [0, 1, 2].map(i => [1, 2, 3, 4].map(q => mZelle(QMON[q][i])).join('')).join('');
  const ab = periodeAbgerechnet();
  const abBtn = `<button type="button" class="fm-abbtn${ab ? ' an' : ''}"
      data-abger-toggle aria-pressed="${ab}">${
      ab ? 'abgerechnet-Status entfernen' : 'als abgerechnet setzen'}</button>`;
  return `<div class="filter-matrix">
    <div class="fm-jahre">${jahre.map(jahrPill).join('')}
      <button type="button" class="fm-alle" data-quartal="0">ganzes Jahr</button></div>
    <div class="fm-grid">${gitter}</div>
    ${abBtn}</div>`;
}

/* Nach jeder Änderung die interne Darstellung (S.quartaleGewaehlt + S.ausMonate)
   glattziehen: abgewählte Monate müssen im Zeitraum liegen, ein leergeräumtes
   Quartal fällt aus der Liste, und nie ist alles leer — dann zurück aufs Jahr. */
export function normalisiereAuswahl() {
  const gueltig = new Set(monateDerQuartale());
  S.ausMonate = new Set([...S.ausMonate].filter(m => gueltig.has(m)));
  if (!S.quartaleGewaehlt.includes(0)) {
    S.quartaleGewaehlt = S.quartaleGewaehlt.filter(
      q => (QMON[q] || []).some(m => !S.ausMonate.has(m)));
  }
  if (!aktiveMonate().length) { S.quartaleGewaehlt = [0]; S.ausMonate = new Set(); }
}

/* N193 — ein ganzes Quartal an- oder abwaehlen (Matrix-Kopf). `wert===0` ist die
   „ganzes Jahr"-Abkürzung. Nie alles abwaehlen — mindestens ein Monat bleibt. */
export function quartalUmschalten(wert) {
  if (wert === 0) {
    S.quartaleGewaehlt = [0]; S.ausMonate = new Set(); return abrechnungZeigen();
  }
  if (quartalAktiv(wert)) {
    if (!aktiveMonate().some(m => QUARTAL_VON(m) !== wert)) {
      return melde('Mindestens ein Monat muss gewählt bleiben', 'neg');
    }
    for (const m of QMON[wert]) S.ausMonate.add(m);
  } else {
    if (!S.quartaleGewaehlt.includes(0) && !S.quartaleGewaehlt.includes(wert)) {
      S.quartaleGewaehlt = [...new Set([...S.quartaleGewaehlt.filter(x => x !== 0), wert])]
        .sort((a, b) => a - b);
    }
    for (const m of QMON[wert]) S.ausMonate.delete(m);
  }
  normalisiereAuswahl();
  abrechnungZeigen();
}

/* N193 — einen einzelnen Monat in die Abrechnung nehmen oder heraus (Matrix-
   Zelle). Der letzte verbleibende Monat laesst sich nicht auch noch abwaehlen. */
export function monatUmschalten(monat) {
  const q = QUARTAL_VON(monat);
  if (monatAktiv(monat)) {
    if (aktiveMonate().length <= 1) {
      return melde('Mindestens ein Monat muss gewählt bleiben', 'neg');
    }
    S.ausMonate.add(monat);
  } else if (S.quartaleGewaehlt.includes(0) || S.quartaleGewaehlt.includes(q)) {
    S.ausMonate.delete(monat);
  } else {
    // Das Quartal war nicht gewählt: dazunehmen, aber nur diesen Monat aktiv
    // lassen (die beiden Geschwistermonate bleiben zunächst abgewählt).
    S.quartaleGewaehlt = [...new Set([...S.quartaleGewaehlt.filter(x => x !== 0), q])]
      .sort((a, b) => a - b);
    for (const mm of QMON[q]) if (mm !== monat) S.ausMonate.add(mm);
    S.ausMonate.delete(monat);
  }
  normalisiereAuswahl();
  abrechnungZeigen();
}

