/* ladungen.js — das Erfassen und Loeschen einzelner Ladungen. Die Eingabe-Zeile
   (Person/Menge/Datum) selbst wird in zuordnen.js gerendert, weil sie in der
   Zuordnungs-Karte sitzt; die Aktion dahinter liegt hier.

   Nach jeder Änderung neu rechnen (Abrechnung) und Verlauf aktualisieren. */
import { S, kwh, datum, feldZahl } from './state.js';
import { api, melde, frage } from '../immo.js';
import { abrechnungZeigen } from './abrechnung.js';
import { verlaufZeigen } from './verlauf.js';
import { jahrWert } from './matrix.js';

export async function ladungBuchen() {
  const nid = S.buchungsWahl?.wert();
  const nutzer = S.nutzerListe.find(n => String(n.id) === String(nid));
  // N288 — `feldZahl` (state.js) statt eigener Fassung; die deutsche Regel
  // steht in `zahlAus` (immo.js) und wird hier nicht nachgebaut.
  const menge = feldZahl(document.getElementById('bKwh'), 0);
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

/* N288 — Loeschen war rueckfragelos: ein Fehlgriff auf das kleine × nahm eine
   erfasste Ladung aus der Abrechnung, ohne dass jemand danach gefragt hatte.
   Die Rueckfrage nennt, WAS weggeht — Datum, Menge, Person —, nicht nur
   „Wirklich loeschen?". */
export async function ladungEntfernen(id) {
  const l = S.ladungen.find(x => String(x.id) === String(id));
  const teile = [
    l?.datum ? datum(l.datum) : 'ohne Datum',
    l ? kwh(l.kwh) : null,
    l?.person || null,
  ].filter(Boolean);
  const ja = await frage('Ladung löschen?',
    `${teile.join(' · ')} wird aus der Abrechnung entfernt. `
    + 'Das lässt sich nicht rückgängig machen.',
    { knopf: 'Löschen', gefahr: true });
  if (!ja) return;
  try {
    await api(`/tankladungen/${id}`, { method: 'DELETE' });
    melde('Ladung gelöscht', 'pos');
    await abrechnungZeigen();
    await verlaufZeigen();
  } catch (fehler) { melde(String(fehler.message || fehler), 'neg'); }
}
