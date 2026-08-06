/* ladungen.js — das Erfassen und Loeschen einzelner Ladungen. Die Eingabe-Zeile
   (Person/Menge/Datum) selbst wird in zuordnen.js gerendert, weil sie in der
   Zuordnungs-Karte sitzt; die Aktion dahinter liegt hier.

   Nach jeder Änderung neu rechnen (Abrechnung) und Verlauf aktualisieren. */
import { S } from './state.js';
import { api, melde } from '../immo.js';
import { abrechnungZeigen } from './abrechnung.js';
import { verlaufZeigen } from './verlauf.js';
import { jahrWert } from './matrix.js';

export async function ladungBuchen() {
  const nid = S.buchungsWahl?.wert();
  const nutzer = S.nutzerListe.find(n => String(n.id) === String(nid));
  const menge = parseFloat(String(document.getElementById('bKwh')?.value || '')
    .replace(',', '.'));
  if (!nutzer) { melde('Erst einen Nutzer anlegen', 'neg'); return; }
  if (!(menge > 0)) { melde('Bitte die geladene Menge angeben', 'neg'); return; }
  try {
    await api(`/objekte/${encodeURIComponent(S.objektSlug)}/tankstelle/${jahrWert()}`, {
      method: 'POST',
      body: { name: nutzer.name, email: nutzer.email || '', kwh: menge,
              datum: document.getElementById('bDatum')?.value || null } });
    melde('Ladung gebucht', 'pos');
    await abrechnungZeigen();
    await verlaufZeigen();
  } catch (fehler) { melde(String(fehler.message || fehler), 'neg'); }
}

export async function ladungEntfernen(id) {
  try {
    await api(`/tankladungen/${id}`, { method: 'DELETE' });
    await abrechnungZeigen();
    await verlaufZeigen();
  } catch (fehler) { melde(String(fehler.message || fehler), 'neg'); }
}
