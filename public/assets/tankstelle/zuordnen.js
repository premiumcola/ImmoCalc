/* zuordnen.js — die Karte „Ladungen zuordnen" (N165/2).

   Die Wallbox weiss, WIE VIEL geladen wurde, aber nicht von WEM. Deshalb hier
   die Zuordnung: je Nutzer ein Zeitraum „laedt vom … bis …". Jede Ladung geht
   an den, dessen Zeitraum ihren Tag enthaelt — statt jede Ladung einzeln
   zuzuordnen. Einzelne Ladungen lassen sich unten in der Liste ausschliessen
   (Korrekturweg).

   Diese Karte erscheint erst ab zwei Nutzern (bei einem gehen alle Ladungen
   ohnehin automatisch auf ihn); das <div id="kartezuordnen"> im Skelett bleibt
   sonst `hidden`. Die neue-Ladung-Eingabe unten (Person/Menge/Datum) wird hier
   mit gerendert, weil sie im selben Bereich sitzt; ihre Aktion sitzt in
   ladungen.js. */
import { S, kwh, datum, zeigeFehler } from './state.js';
import { api, esc, melde } from '../immo.js';
import { auswahlfeld } from '../auswahl.js';
import { abrechnungZeigen } from './abrechnung.js';
import { jahrWert } from './matrix.js';

/* N165/2 — die Mehrnutzer-Zuordnung ueber einen Zeitraum. Statt jede Ladung
   einzeln anzuklicken (der ausdrueckliche Kritikpunkt): je Nutzer ein „laedt
   vom … bis …". Jede Ladung geht an den, dessen Zeitraum ihren Tag enthaelt. */
function zuordnungBlock() {
  const regel = id => (S.einst.regeln || []).find(r => r.nutzer_id === id) || {};
  const zeilen = S.nutzerListe.map(n => {
    const r = regel(n.id);
    return `<div class="zregel">
      <span class="zn">${esc(n.name)}</span>
      <div class="zf">
        <div class="field"><span class="fl">Lädt ab</span>
          <input class="inp" type="date" data-regel-von="${n.id}"
                 value="${esc(r.von || '')}"></div>
        <div class="field"><span class="fl">Lädt bis</span>
          <input class="inp" type="date" data-regel-bis="${n.id}"
                 value="${esc(r.bis || '')}"></div>
      </div>
    </div>`;
  }).join('');
  // Der frühere Erklär-Absatz steht jetzt im i-Popup am Karten-Titel „Ladungen
  // zuordnen" (N181) — hier bleiben nur die Regel-Felder selbst.
  return `${zeilen}
    <button class="btn" data-zuordnung-speichern
            style="margin:0 0 16px">Zuordnung speichern</button>`;
}

/* N165/2 — die Mehrnutzer-Zuordnung: ganz ersetzend gespeichert. Regeln auf
   inzwischen geloeschte Nutzer werden vorher aussortiert, damit ein PUT nicht
   an einer verwaisten Regel scheitert. */
async function speichereZuordnung(regeln, ausschluss) {
  const gueltig = (regeln || []).filter(
    r => S.nutzerListe.some(n => n.id === r.nutzer_id));
  try {
    const d = await api(`/tankstelle/${encodeURIComponent(S.objektSlug)}/zuordnung`,
                        { method: 'PUT',
                          body: { regeln: gueltig, ausschluss: ausschluss || [] } });
    S.einst.regeln = d.regeln || [];
    S.einst.ausschluss = d.ausschluss || [];
    melde('Zuordnung gespeichert', 'pos');
    await abrechnungZeigen();               // rechnet neu und zeichnet Ladungen
  } catch (fehler) { melde(String(fehler.message || fehler), 'neg'); }
}

export async function zuordnungSpeichern() {
  const regeln = [];
  for (const n of S.nutzerListe) {
    const von = document.querySelector(`[data-regel-von="${n.id}"]`)?.value || '';
    const bis = document.querySelector(`[data-regel-bis="${n.id}"]`)?.value || '';
    if (von && bis) regeln.push({ nutzer_id: n.id, von, bis });
    else if (von || bis) {
      melde(`Bei ${n.name} fehlt ein Datum des Zeitraums`, 'neg');
      return;
    }
  }
  await speichereZuordnung(regeln, S.einst.ausschluss);
}

export async function ausschlussUmschalten(id) {
  id = Number(id);
  const menge = new Set(S.einst.ausschluss || []);
  menge.has(id) ? menge.delete(id) : menge.add(id);
  await speichereZuordnung(S.einst.regeln, [...menge]);
}

export async function ladungenZeigen() {
  const ziel = document.getElementById('ladungen');
  if (!ziel) return;
  // N169 — bei genau einem (oder keinem) Nutzer gehoeren ihm ohnehin alle
  // Ladungen automatisch; die Zuordnung waere leer und verwirrend. Erst ab zwei
  // Nutzern gibt es etwas zuzuordnen, dann erscheint der Bereich.
  const karte = document.getElementById('kartezuordnen');
  if (karte) karte.hidden = S.nutzerListe.length < 2;
  if (S.nutzerListe.length < 2) return;
  let d;
  try {
    d = await api(`/objekte/${encodeURIComponent(S.objektSlug)}/tankstelle/${jahrWert()}`);
  } catch (fehler) {
    zeigeFehler(ziel, 'Erfasste Ladungen nicht verfügbar', fehler);
    return;
  }
  /* Bewusst ohne Geldspalte (N148): der Betrag je Ladung kaeme aus
     `Tankladung.preis` — dem stillgelegten Handwert. Er stand hier als
     „0,00 €" und widersprach dem abgeleiteten Satz eine Karte weiter oben.
     Was eine Ladung kostet, sagt die Abrechnung; hier geht es allein um die
     Zuordnung: wer, wann, wie viel. */
  // Solange nur eine Person angelegt ist, gibt es nichts zu entscheiden —
  // jede Ladung geht auf sie. Sobald es zwei sind, wird zugeordnet.
  const einer = S.nutzerListe.length === 1 ? S.nutzerListe[0] : null;
  const mehr = S.nutzerListe.length > 1;
  const ausg = new Set(S.einst.ausschluss || []);

  const zeilen = (d.ladungen || []).map(l => `
    <div class="lz ${mehr && ausg.has(l.id) ? 'aus' : ''}">
      <span class="ld">${esc(l.person || '—')}
        <span class="ldt">${l.datum ? datum(l.datum) : 'ohne Datum'}</span></span>
      <span class="lk">${kwh(l.kwh)}</span>
      ${mehr ? `<button class="lex" data-ausschluss="${l.id}">${
        ausg.has(l.id) ? 'einbeziehen' : 'ausschließen'}</button>` : ''}
      <button class="lx" data-ladung-weg="${l.id}" aria-label="Ladung entfernen">×</button>
    </div>`).join('');

  ziel.innerHTML = `
    ${einer ? `<span class="vermerk">Angelegt ist bisher nur
        <b>${esc(einer.name)}</b> — jede Ladung geht damit auf ihn.</span>` : ''}
    ${mehr ? zuordnungBlock() : ''}
    ${zeilen ? `<div class="lliste">${zeilen}</div>`
      : `<div class="leer" style="margin-bottom:14px"><b>Keine Ladung erfasst</b>
          In ${esc(String(jahrWert()))} ist noch keine Ladung einer Person
          zugeordnet.</div>`}
    <div class="neu">
      <div class="field"><span class="fl">Wer hat geladen</span>
        <div id="bPerson"></div></div>
      <div class="field"><label for="bKwh">Menge (kWh)</label>
        <input class="inp" id="bKwh" type="number" inputmode="decimal" step="0.1" min="0"></div>
      <div class="field"><label for="bDatum">Datum</label>
        <input class="inp" id="bDatum" type="date"></div>
      <button class="btn" data-ladung-neu>Ladung buchen</button>
    </div>`;

  S.buchungsWahl = auswahlfeld(document.getElementById('bPerson'), {
    label: 'Wer hat geladen',
    optionen: S.nutzerListe.length
      ? S.nutzerListe.map(n => ({ wert: String(n.id), text: n.name }))
      : [{ wert: '', text: 'Nutzer anlegen' }],
    wert: S.nutzerListe.length ? String(S.nutzerListe[0].id) : '',
  });
}
