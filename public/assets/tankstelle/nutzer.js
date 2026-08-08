/* nutzer.js — die Nutzer-Karte: Liste, Anlegen ueber das „＋" oben rechts,
   Inline-Bearbeiten der Stammdaten (Anschrift, Bankverbindung, E-Auto) und
   Entfernen. Beliebig viele Nutzer, jederzeit ergaenzbar, nicht zwangslaeufig
   Eigentuemer der Immobilie (N132/N143).

   `eautoErmitteln` zieht den Durchschnittsverbrauch des eingegebenen
   E-Auto-Modells einmalig ueber die KI (defensive Fahrweise, N170) und schreibt
   ihn ins Verbrauchsfeld — klappt es nicht, kommt ein ehrlicher Hinweis. */
import { S, zahl, zeigeFehler, feldZahl } from './state.js';
import { api, esc, melde, frage } from '../immo.js';
import { abrechnungZeigen } from './abrechnung.js';

export async function nutzerZeigen() {
  const ziel = document.getElementById('nutzer');
  if (!ziel) return;
  // Fruehere Fassung schluckte den Fehler stumm: die Liste blieb leer, und
  // die Abrechnung darunter zeigte 0,00 € ohne einen Hinweis darauf, dass
  // ueberhaupt etwas schiefgegangen war.
  try {
    S.nutzerListe = (await api(`/tankstelle/${encodeURIComponent(S.objektSlug)}/nutzer`)).nutzer || [];
  } catch (fehler) {
    S.nutzerListe = [];
    zeigeFehler(ziel, 'Nutzerliste nicht verfügbar', fehler);
    return;
  }

  const anschrift = n => [n.plz, n.ort].filter(Boolean).join(' ');
  const zusatz = n => {
    const teile = [];
    if (n.strasse || anschrift(n)) teile.push([n.strasse, anschrift(n)].filter(Boolean).join(', '));
    if (n.iban) teile.push('IBAN hinterlegt');
    if (n.e_auto_modell) teile.push('🚗 ' + n.e_auto_modell
      + (n.verbrauch_kwh_100km ? ` · ${zahl(n.verbrauch_kwh_100km, 1)} kWh/100 km` : ''));
    return teile.join(' · ');
  };
  const zeilen = S.nutzerListe.map(n => `
    <div class="nz">
      <span class="nk" aria-hidden="true">${esc((n.name || '?').trim()[0] || '?')}</span>
      <span class="nt">
        <span class="nn">${esc(n.name)}</span>
        <span class="nm">${esc(n.email || 'keine E-Mail hinterlegt')}</span>
        ${zusatz(n) ? `<span class="nm">${esc(zusatz(n))}</span>` : ''}
      </span>
      <button class="nx" data-nutzer-edit="${n.id}"
              aria-label="${esc(n.name)} bearbeiten">✎</button>
      <button class="nx" data-nutzer-weg="${n.id}" data-name="${esc(n.name)}"
              aria-label="${esc(n.name)} entfernen">×</button>
    </div>
    <div class="nedit" data-edit="${n.id}"></div>`).join('');

  // Anlegen läuft über den „＋" oben (data-nutzer-add) — eine aufklappbare
  // Eingabe statt einer dauerhaft sichtbaren Spalte unten.
  const addForm = `
    <div class="efgrid nedit-form" style="margin-bottom:12px">
      <div class="field span"><label class="fl" for="nName">Name</label>
        <input class="inp" id="nName" type="text" autocomplete="name"
               placeholder="Name des Nutzers"></div>
      <div class="field span"><label class="fl" for="nMail">E-Mail</label>
        <input class="inp" id="nMail" type="email" autocomplete="email"
               placeholder="für die Quartalsabrechnung"></div>
      <div class="ef-save span"><button class="btn" data-nutzer-neu>Anlegen</button></div>
    </div>`;
  ziel.innerHTML = `
    ${S.addOffen ? addForm : ''}
    ${zeilen ? `<div class="nliste">${zeilen}</div>`
      : (S.addOffen ? '' : `<div class="leer" style="margin-bottom:4px">
          <b>Noch niemand angelegt</b>
          Tipp oben rechts auf ＋, um den ersten Nutzer anzulegen — Name und
          E-Mail genügen. Das muss kein Eigentümer sein.</div>`)}`;
  if (S.addOffen) document.getElementById('nName')?.focus();
  if (S.offeneBearbeitung) nutzerBearbeiten(S.offeneBearbeitung, true);
}

/* Die Versand-Stammdaten (Anschrift, Bankverbindung) werden inline gepflegt —
   ein Klick auf ✎ klappt das Formular unter der Zeile auf. Zweiter Klick
   schliesst wieder. `bleiben` haelt es nach einem Neu-Rendern offen. */
export function nutzerBearbeiten(id, bleiben = false) {
  const feld = document.querySelector(`[data-edit="${id}"]`);
  if (!feld) return;
  if (!bleiben && S.offeneBearbeitung === Number(id)) {
    feld.innerHTML = '';
    S.offeneBearbeitung = 0;
    return;
  }
  document.querySelectorAll('[data-edit]').forEach(f => { f.innerHTML = ''; });
  S.offeneBearbeitung = Number(id);
  const n = S.nutzerListe.find(x => x.id === Number(id)) || {};
  // `span` gibt einem Feld die volle Breite — E-Mail, Anschrift und IBAN sind
  // sonst zu schmal und schneiden die Adresse ab (BIC entfällt, N170-Wunsch).
  const feldChen = (schl, beschr, wert, typ = 'text', span = false) => `
    <div class="field${span ? ' span' : ''}"><span class="fl">${beschr}</span>
      <input class="inp" id="e-${schl}-${id}" type="${typ}"
             value="${esc(wert || '')}"></div>`;
  feld.innerHTML = `<div class="efgrid">
    ${feldChen('name', 'Name', n.name, 'text', true)}
    ${feldChen('email', 'E-Mail', n.email, 'email', true)}
    ${feldChen('strasse', 'Straße', n.strasse, 'text', true)}
    ${feldChen('plz', 'PLZ', n.plz)}
    ${feldChen('ort', 'Ort', n.ort)}
    ${feldChen('kontoinhaber', 'Kontoinhaber', n.kontoinhaber, 'text', true)}
    ${feldChen('iban', 'IBAN', n.iban, 'text', true)}
    ${feldChen('e_auto_modell', 'E-Auto-Modell', n.e_auto_modell, 'text', true)}
    <div class="field span"><span class="fl">Verbrauch (kWh/100 km)</span>
      <div class="verbrauchzeile">
        <input class="inp" id="e-verbrauch_kwh_100km-${id}" type="number"
               inputmode="decimal" step="0.1" min="0"
               value="${n.verbrauch_kwh_100km ? n.verbrauch_kwh_100km : ''}"
               placeholder="z. B. 16,5">
        <button class="btn-ki" data-eauto-ermitteln="${id}">per KI ermitteln</button>
      </div></div>
    <div class="ef-save span"><button class="btn"
      data-nutzer-save="${id}">Speichern</button></div>
  </div>`;
}

export async function nutzerSpeichern(id) {
  const holen = schl => document.getElementById(`e-${schl}-${id}`)?.value ?? '';
  const koerper = {};
  // BIC wird nicht mehr angezeigt (N170) und darum auch NICHT mitgeschickt —
  // sonst würde der gespeicherte Wert (Modellfeld bleibt, CLAUDE.md) geleert.
  for (const schl of ['name', 'email', 'strasse', 'plz', 'ort',
                      'kontoinhaber', 'iban', 'e_auto_modell']) {
    koerper[schl] = holen(schl).trim();
  }
  // Der Verbrauch von Hand: nur ein positiver Wert wird gesetzt, 0/leer laesst
  // den gespeicherten (KI-ermittelten) Wert stehen.
  // N288 — `feldZahl` (state.js) statt eigener Fassung; die deutsche Regel
  // steht in `zahlAus` (immo.js) und wird hier nicht nachgebaut.
  const verb = feldZahl(document.getElementById(`e-verbrauch_kwh_100km-${id}`), 0);
  if (verb > 0) koerper.verbrauch_kwh_100km = verb;
  if (!koerper.name) { melde('Bitte einen Namen angeben', 'neg'); return; }
  try {
    await api(`/tankstelle/${encodeURIComponent(S.objektSlug)}/nutzer/${id}`, {
      method: 'PUT', body: koerper });
    melde('Stammdaten gespeichert', 'pos');
    S.offeneBearbeitung = 0;
    await nutzerZeigen();
    await abrechnungZeigen();
  } catch (fehler) { melde(String(fehler.message || fehler), 'neg'); }
}

/* N170 — den Durchschnittsverbrauch des eingegebenen E-Auto-Modells einmalig
   ueber die KI ziehen (defensive Fahrweise) und ins Verbrauchsfeld schreiben.
   Klappt es nicht, kommt ein ehrlicher Hinweis — der Handeintrag bleibt der
   Rueckfallweg. */
export async function eautoErmitteln(id) {
  const modell = (document.getElementById(`e-e_auto_modell-${id}`)?.value || '').trim();
  if (!modell) { melde('Bitte zuerst das E-Auto-Modell eintragen', 'neg'); return; }
  const btn = document.querySelector(`[data-eauto-ermitteln="${id}"]`);
  if (btn) { btn.disabled = true; btn.textContent = 'wird ermittelt …'; }
  try {
    const d = await api(
      `/tankstelle/${encodeURIComponent(S.objektSlug)}/nutzer/${id}/eauto`,
      { method: 'POST', body: { modell } });
    const feld = document.getElementById(`e-verbrauch_kwh_100km-${id}`);
    if (d.verbrauch_kwh_100km > 0 && feld) feld.value = d.verbrauch_kwh_100km;
    if (d.hinweis) melde(d.hinweis, 'neg');
    else melde(`Verbrauch: ${zahl(d.verbrauch_kwh_100km, 1)} kWh/100 km`, 'pos');
    S.nutzerListe = S.nutzerListe.map(x => x.id === Number(id) ? { ...x, ...d } : x);
    await abrechnungZeigen();
  } catch (fehler) { melde(String(fehler.message || fehler), 'neg'); }
  finally {
    if (btn) { btn.disabled = false; btn.textContent = 'per KI ermitteln'; }
  }
}

export async function nutzerAnlegen() {
  const name = document.getElementById('nName');
  const mail = document.getElementById('nMail');
  if (!name?.value.trim()) { melde('Bitte einen Namen angeben', 'neg'); return; }
  try {
    await api(`/tankstelle/${encodeURIComponent(S.objektSlug)}/nutzer`, {
      method: 'POST', body: { name: name.value, email: mail?.value || '' } });
    melde('Nutzer angelegt', 'pos');
    S.addOffen = false;
    await nutzerZeigen();
    await abrechnungZeigen();
  } catch (fehler) { melde(String(fehler.message || fehler), 'neg'); }
}

export async function nutzerEntfernen(id, name) {
  const ja = await frage('Nutzer entfernen?',
    `„${name}“ verschwindet aus der Liste. Erfasste Ladungen bleiben erhalten `
    + 'und tauchen in der Abrechnung weiter auf.',
    { knopf: 'Entfernen', gefahr: true });
  if (!ja) return;
  try {
    await api(`/tankstelle/${encodeURIComponent(S.objektSlug)}/nutzer/${id}`,
              { method: 'DELETE' });
    await nutzerZeigen();
    await abrechnungZeigen();
  } catch (fehler) { melde(String(fehler.message || fehler), 'neg'); }
}
