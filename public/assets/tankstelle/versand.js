/* versand.js — die Sende-Orchestrierung fuer die Quartalsabrechnung. Der Knopf
   dazu sitzt an jeder Nutzer-Zeile in der Abrechnungs-Karte (N202: er traegt
   Zeitraum + Betrag). Vor dem Versand kommt eine Rueckfrage; ausgefuehrt wird
   ueber `/versand`, das die Mail mit PDF-Anhang zusammenbaut. */
import { S } from './state.js';
import { api, melde, frage } from '../immo.js';
import { jahrWert } from './matrix.js';

export async function versenden(nid) {
  const nutzer = S.nutzerListe.find(n => n.id === Number(nid));
  const ja = await frage('Abrechnung verschicken?',
    `Die Abrechnung geht als Mail an ${nutzer?.email || 'die hinterlegte Adresse'}.`,
    { knopf: 'Senden' });
  if (!ja) return;
  try {
    const d = await api(`/tankstelle/${encodeURIComponent(S.objektSlug)}/versand`, {
      method: 'POST',
      body: { nutzer_id: Number(nid), jahr: jahrWert(),
              quartale: S.quartaleGewaehlt, aus: [...S.ausMonate] } });
    melde(`Abrechnung an ${d.an} verschickt`, 'pos');
  } catch (fehler) { melde(String(fehler.message || fehler), 'neg'); }
}
