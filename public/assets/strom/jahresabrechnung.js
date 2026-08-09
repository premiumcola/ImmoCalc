/* jahresabrechnung.js — N308: die jaehrliche PV-Eigentuemer-Abrechnung statt
   eines nur kumulierten Standes, mit Versand nach demselben Muster wie die
   E-Tankstelle (Rueckfrage vor dem Senden, Versendet-Marker gegen Dopplung).
   Anders als dort: ein Informationsschreiben unter Mit-Eigentuemern, keine
   Rechnung — deshalb ohne PDF-Anhang.

   Zeigt denselben Jahrgang wie die uebrigen Karten der Seite (`S.jahrWahl`) —
   keine zweite Jahresauswahl fuer dieselbe Information. */
import { api, esc, eur, frage, melde, promille } from '../immo.js';
import { S, inhalt } from './state.js';

function pjZeile(e, jahr) {
  const gesperrt = !e.eigentuemer_id
    ? 'Keine Person hinterlegt — oben zuordnen'
    : !e.email ? `Für ${e.name} ist keine E-Mail-Adresse hinterlegt`
    : !(e.betrag > 0) ? `Für ${jahr} ist kein Ertrag zu verteilen` : '';
  return `<div class="pj-row">
    <div class="pj-kopf">
      <span class="pj-name">${esc(e.name)}${e.promille != null
        ? `<span class="pa-obj">${promille(e.promille)}</span>` : ''}</span>
      <span class="pj-betrag">${eur(e.betrag)}</span>
    </div>
    <span class="pj-kum">kumuliert seit Beginn ${eur(e.kumuliert_anteil)}</span>
    ${e.versendet
      ? `<span class="chip teal pj-chip">✓ ${jahr} verschickt</span>`
      : `<button type="button" class="btn pj-send" data-pj-send="${esc(e.name)}"
           data-pj-jahr="${jahr}"${gesperrt
             ? ` disabled aria-disabled="true" title="${esc(gesperrt)}"` : ''}>
           <span class="bs-t">${jahr} · per Mail senden</span>
           <span class="bs-e">${eur(e.betrag)}</span>
         </button>`}
  </div>`;
}

export async function pvJahresabrechnungZeigen() {
  const ziel = document.getElementById('pvJahresabrechnung');
  if (!ziel || !S.objektSlug || !S.jahrWahl) return;
  const jahr = S.jahrWahl.wert();
  let d;
  try {
    d = await api(`/objekte/${encodeURIComponent(S.objektSlug)}`
                  + `/pv/jahresabrechnung?jahr=${encodeURIComponent(jahr)}`);
  } catch {
    ziel.innerHTML = '<p class="hint">Jahresabrechnung nicht ladbar.</p>';
    return;
  }
  if (d.ertrag == null) {
    ziel.innerHTML = `<div class="pa-leer">${esc(d.hinweis
      || 'Für dieses Jahr gibt es noch nichts zu verteilen.')}</div>`;
    return;
  }
  if (!d.eigentuemer.length) {
    ziel.innerHTML = '<div class="pa-leer">Noch niemandem zugeordnet — die '
      + 'Vorgabe 5/6 + 1/6 greift, sobald oben Personen zugeordnet sind.</div>';
    return;
  }
  ziel.innerHTML = d.eigentuemer.map(e => pjZeile(e, jahr)).join('');
}

async function senden(name, jahr) {
  const ja = await frage('Jahresabrechnung verschicken?',
    `${name} bekommt eine Mail mit dem Anteil für ${jahr}.`, { knopf: 'Senden' });
  if (!ja) return;
  try {
    const d = await api(`/objekte/${encodeURIComponent(S.objektSlug)}`
                        + '/pv/jahresabrechnung/versand', {
      method: 'POST', body: { jahr: Number(jahr), name } });
    melde(`Abrechnung an ${d.an} verschickt`, 'pos');
    await pvJahresabrechnungZeigen();
  } catch (fehler) { melde(String(fehler.message || fehler), 'neg'); }
}

// Ein Lauscher am bestehenden Behaelter, wie bei den PV-Anteilen selbst —
// die Karte wird bei jeder Aenderung neu gezeichnet, ein Lauscher je Knopf
// ginge dabei jedes Mal verloren.
inhalt.addEventListener('click', e => {
  const btn = e.target.closest('[data-pj-send]');
  if (btn && !btn.disabled) senden(btn.dataset.pjSend, btn.dataset.pjJahr);
});
