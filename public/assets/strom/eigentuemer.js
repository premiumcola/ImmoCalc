/* N112c/N139/N149/N204 — die PV-Anteile je Person.

   Zugeordnet wird aus derselben Eigentuemer-Liste wie ueberall; gespeichert
   wird in den Stammdaten der Anlage ({Name: ‰}), nicht am Jahr — die Anlage
   kann anderen gehoeren als das Haus.

   N149 — in der Liste steht nur, wer wirklich einen Anteil haelt. Wer nichts
   haelt, steht in der Auswahl darunter. Die Anteile leben in `S.pvAnteile`,
   nicht im DOM: die Anzeige rundet auf eine Nachkommastelle, gespeichert
   wird der ungerundete Wert — sonst wanderte 833,333 bei jedem Oeffnen ein
   Stueck.

   N204 — jede Zeile traegt Investitions-€ und ‰; hinzugefuegt wird ueber
   das „＋" oben rechts, das ausgraut, sobald alle 1000 ‰ vergeben sind.

   Umzug ohne Verhaltensaenderung: dieselben API-Aufrufe und dieselbe
   Zeichenlogik wie zuvor inline in strom.html. */
import { api, esc, eur, frage, melde, promille } from '../immo.js';
import { auswahlfeld } from '../auswahl.js';
import { S, inhalt } from './state.js';
import { runde3 } from './helpers.js';
import { stammAngestossen } from './stammdaten.js';

/* Die Gesamt-Anschaffung aktualisieren und die Karte nachziehen. */
export function pvAnschaffungSetzen(betrag) {
  const neu = Number.isFinite(betrag) ? betrag : 0;
  if (neu === S.pvAnschaffung) return;
  S.pvAnschaffung = neu;
  if (S.pvGeladen) pvAnteileZeichnen();
}

const pvSumme = () => runde3(Object.values(S.pvAnteile).reduce((s, v) => s + v, 0));
const pvAnzahl = () => Object.keys(S.pvAnteile).filter(n => S.pvAnteile[n] > 0).length;

export async function pvAnteileLaden() {
  S.pvGeladen = false;
  S.pvPersonen = [];
  S.pvAnteile = {};
  if (!S.objektSlug) return;
  let d;
  try {
    d = await api(`/objekte/${encodeURIComponent(S.objektSlug)}/pv/eigentuemer`);
  } catch {
    const ziel = document.getElementById('pvAnteile');
    if (ziel) ziel.innerHTML = '<p class="hint">Personen nicht ladbar.</p>';
    return;
  }
  S.pvPersonen = d.personen || [];
  S.pvAnteile = { ...(d.pv_anteile || {}) };
  S.pvGeladen = true;
  pvAnteileZeichnen();
}

/* N204 — die Investitions-€ dieses Anteils: ‰/1000 × Gesamt-Anschaffung.
   Ist die Gesamt-Anschaffung nicht bekannt (z. B. vor dem naechsten Deploy),
   steht nur das ‰ — nie eine erfundene Zahl. */
function pvInvestChip(promilleWert) {
  if (!(S.pvAnschaffung > 0) || !(promilleWert > 0)) return '';
  return `<span class="pa-invest">${eur(promilleWert / 1000 * S.pvAnschaffung)}</span>`;
}

/* Das „＋" oben rechts: aktiv, solange noch etwas zu vergeben ist; sonst
   ausgegraut mit sprechendem Hinweis. Schlieszt ein offenes Formular, wenn
   nichts mehr hinzuzufuegen ist. */
function pvPlusStand() {
  const plus = document.getElementById('pvPlus');
  if (!plus) return;
  const frei = S.pvPersonen.filter(p => !(S.pvAnteile[p.name] > 0));
  const voll = pvSumme() >= 999.95;
  const gesperrt = !S.pvPersonen.length || voll || !frei.length;
  plus.disabled = gesperrt;
  plus.title = !S.pvPersonen.length ? 'Erst Personen als Eigentümer anlegen'
    : voll ? 'Alle 1000 ‰ vergeben'
    : !frei.length ? 'Alle Personen zugeordnet'
    : 'Anteil zuordnen';
  plus.setAttribute('aria-expanded', String(S.pvAddOffen && !gesperrt));
  if (gesperrt) S.pvAddOffen = false;
}

/* Die Karte neu zeichnen: zugeordnete Personen als Zeilen, darunter die
   Summe und — sobald das „＋" gedrueckt ist — der Weg zum Hinzufuegen. */
function pvAnteileZeichnen() {
  const ziel = document.getElementById('pvAnteile');
  if (!ziel) return;
  if (!S.pvPersonen.length) {
    ziel.innerHTML = '<p class="hint">Noch keine Personen angelegt — lege sie '
      + 'unter Eigentümer an, dann lassen sie sich hier zuordnen.</p>';
    pvPlusStand();
    return;
  }
  const amObjekt = new Map(S.pvPersonen.map(p => [p.name, p.am_objekt]));
  const zugeordnet = S.pvPersonen.filter(p => S.pvAnteile[p.name] > 0);
  const zeilen = zugeordnet.map(p => `
    <div class="pa-zeile">
      <span class="pa-name">${esc(p.name)}${p.am_objekt != null
        ? `<span class="pa-obj">am Objekt ${promille(p.am_objekt)}</span>` : ''}</span>
      ${pvInvestChip(S.pvAnteile[p.name])}
      <span class="pa-wert">${promille(S.pvAnteile[p.name])}</span>
      <button type="button" class="pa-weg" data-pv-weg="${esc(p.name)}"
              aria-label="${esc(p.name)} entfernen">×</button>
    </div>`).join('');

  // Namen, die in der Datenbank stehen, deren Person es aber nicht mehr
  // gibt — sie bleiben sichtbar, sonst verschwaende ein Anteil lautlos aus
  // der Summe.
  const verwaist = Object.keys(S.pvAnteile)
    .filter(n => S.pvAnteile[n] > 0 && !amObjekt.has(n))
    .map(n => `
    <div class="pa-zeile">
      <span class="pa-name">${esc(n)}<span class="pa-obj">nicht mehr als
        Eigentümer angelegt</span></span>
      ${pvInvestChip(S.pvAnteile[n])}
      <span class="pa-wert">${promille(S.pvAnteile[n])}</span>
      <button type="button" class="pa-weg" data-pv-weg="${esc(n)}"
              aria-label="${esc(n)} entfernen">×</button>
    </div>`).join('');

  const liste = zeilen + verwaist;
  const frei = S.pvPersonen.filter(p => !(S.pvAnteile[p.name] > 0));
  const formOffen = S.pvAddOffen && frei.length && pvSumme() < 999.95;
  ziel.innerHTML = (liste
      ? `${liste}<div class="pa-summe"><span>Vergeben</span>
          <b>${promille(pvSumme())}</b></div>`
      : `<div class="pa-leer">Noch niemandem zugeordnet — solange hier nichts
          steht, gilt die Vorgabe 5/6 + 1/6.</div>`)
    + '<div id="paHinweis"></div>'
    + (formOffen
      ? `<div class="pa-neu">
           <div class="pa-person" id="paPerson"></div>
           <!-- Bewusst kein type=number: die deutsche Zifferntastatur liefert
                ein Komma, und ein Zahlenfeld verwirft es samt Eingabe. -->
           <input class="inp pa-neuwert" id="paWert" type="text"
                  inputmode="decimal" autocomplete="off" maxlength="9"
                  aria-label="Anteil in Tausendsteln">
           <span class="pa-einheit" aria-hidden="true">‰</span>
           <button type="button" class="btn pa-add" id="paAdd">Zuordnen</button>
         </div>` : '');

  pvHinweisZeigen();
  pvPlusStand();
  if (!formOffen) { S.pvNeuWahl = null; return; }
  S.pvNeuWahl = auswahlfeld(document.getElementById('paPerson'), {
    label: 'Person zuordnen',
    optionen: frei.map(p => ({ wert: p.name, text: p.name })),
    wert: frei[0].name,
    aenderung: pvVorschlagSetzen,
  });
  pvVorschlagSetzen(frei[0].name);
  document.getElementById('paAdd').addEventListener('click', pvZuordnen);
  document.getElementById('paWert').addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); pvZuordnen(); }
  });
}

/* Ein Vorschlag, kein Zwang: erst der Anteil am Objekt, sonst der noch
   freie Rest. Getipptes wird nie ueberschrieben. */
function pvVorschlagSetzen(name) {
  const feld = document.getElementById('paWert');
  if (!feld || feld.value) return;
  const p = S.pvPersonen.find(x => x.name === name);
  const rest = runde3(1000 - pvSumme());
  const vorschlag = p?.am_objekt ?? (rest > 0.05 ? rest : null);
  if (vorschlag != null) feld.value = String(runde3(vorschlag)).replace('.', ',');
}

/* Die gewaehlte Person mit dem eingetippten Anteil in die Liste aufnehmen. */
function pvZuordnen() {
  const name = S.pvNeuWahl?.wert();
  const feld = document.getElementById('paWert');
  const v = parseFloat(String(feld?.value || '').replace(',', '.'));
  if (!name) return melde('Bitte eine Person wählen', 'neg');
  if (!Number.isFinite(v) || v <= 0) return melde('Bitte einen Anteil in ‰ angeben', 'neg');
  // Bewusst ungerundet: die Anzeige rundet auf eine Nachkommastelle,
  // gespeichert wird, was dasteht — sonst wuerde 833,3333 bei jedem Oeffnen
  // kuerzer.
  S.pvAnteile[name] = v;
  // Nach dem Zuordnen das Formular wieder einklappen — die Karte bleibt
  // kompakt, ein weiterer Anteil geht erneut ueber das „＋".
  S.pvAddOffen = false;
  pvAnteileZeichnen();
  melde(`${promille(S.pvAnteile[name])} an ${name} zugeordnet`, 'pos');
  stammAngestossen();
}

/* Eine Zuordnung loesen — mit Rueckfrage, wie ueberall, wo ein Anteil
   weggeht. */
async function pvEntfernen(name) {
  const ja = await frage('Zuordnung entfernen?',
    `${name} hält dann keinen Anteil mehr an der Anlage. Die Person selbst `
    + 'bleibt erhalten.', { knopf: 'Entfernen', gefahr: true });
  if (!ja) return;
  delete S.pvAnteile[name];
  pvAnteileZeichnen();
  stammAngestossen();
}

/* Ein ruhiger Hinweis, wenn die vergebenen Tausendstel nicht 1000 ‰ ergeben.
   Ein Hinweis, keine Sperre: gespeichert wird trotzdem. */
function pvHinweisZeigen() {
  const hinweis = document.getElementById('paHinweis');
  if (!hinweis) return;
  const summe = pvSumme();
  const offen = Math.round((1000 - summe) * 10) / 10;
  const fehlt = offen > 0 ? `${promille(offen)} fehlen noch`
    : `${promille(-offen)} zu viel`;
  hinweis.innerHTML = (!summe || Math.abs(offen) <= 0.5) ? ''
    : `<div class="pa-hinweis">Vergeben sind ${promille(summe)} statt 1000 ‰`
      + ` — ${fehlt}.</div>`;
}

export function pvAnteileJson() {
  return pvAnzahl() ? JSON.stringify(S.pvAnteile) : '';
}

// Ein Lauscher am bestehenden Behaelter: die Karte wird bei jeder Aenderung
// neu gezeichnet, ein Lauscher je Knopf ginge dabei jedes Mal verloren.
inhalt.addEventListener('click', e => {
  const weg = e.target.closest('[data-pv-weg]');
  if (weg) return pvEntfernen(weg.dataset.pvWeg);
  const add = e.target.closest('[data-pv-add]');
  if (add) {
    if (add.disabled) return;             // ausgegraut: alle 1000 ‰ vergeben
    S.pvAddOffen = !S.pvAddOffen;
    pvAnteileZeichnen();
  }
});
