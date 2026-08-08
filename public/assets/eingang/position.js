/* N216 — Aus dem Beleg wird eine Kostenposition (CLXXX/CLXXXII).

   Bewusst ein eigener, sichtbarer Schritt und keine Automatik beim
   „Uebernehmen": einsortieren und abrechnen sind zwei Entscheidungen. Ein
   Beleg darf am richtigen Platz liegen, ohne schon in der Abrechnung zu stehen
   — ein Doppel, eine Rechnung, die noch geprueft wird, ein Beleg fuers Archiv.

   Und weil ein zweiter Beleg den Betrag der vorhandenen Position erhoeht
   (CLXXXII), steht die Rechnung vorher da: „bisher 300,00 € + 150,50 € =
   450,50 €". Der Server rechnet sie, damit Vorschau und Ergebnis nicht
   auseinanderlaufen. */

import { S, els, belegmeldung } from './state.js';
import { api, esc } from '../immo.js';
import { betragText, dok } from './helpers.js';
import { stand } from './liste.js';
import { laden } from './aktionen.js';

/** Steht im Formular etwas anderes als gespeichert? Dann gilt fuer die
    Kostenposition noch der gespeicherte Stand — das muss dastehen, sonst
    verbucht der Knopf scheinbar etwas anderes, als das Blatt zeigt. */
export function posUngespeichert(d) {
  const s = stand();
  if (!s) return false;
  const gleich = (a, b) => (a || null) === (b || null);
  return !(gleich(s.kostenart, d.kostenart)
           && gleich(s.zeitraum_id, d.zeitraum_id)
           && gleich(s.betrag, d.betrag));
}

const posZeile = (label, wert, klasse) =>
  `<div class="pr${klasse ? ' ' + klasse : ''}"><span>${esc(label)}</span>` +
  `<span>${esc(wert)}</span></div>`;

export function posPlanZeichnen(d) {
  const p = S.posPlan;
  els.bPosLos.hidden = !(p && p.moeglich && p.schon_verbucht);
  if (!p) {
    els.bPosPlan.innerHTML = posZeile('wird geprüft …', '');
    els.bPos.disabled = true;
    return;
  }
  // Steht im Formular schon, was noch fehlt, ist das die eigentliche Antwort:
  // erst speichern, dann rechnet die Kostenposition damit.
  const wartet = posUngespeichert(d);
  // Hoechstens eine knappe Zeile: der Hinweis steht in der Aufstellung selbst,
  // eine zweite Erklaerung darueber waere eine zu viel.
  els.bPosHinweis.textContent = '';
  els.bPosHinweis.classList.remove('warn');
  if (!p.moeglich) {
    // Der Grund vom Server beschreibt den GESPEICHERTEN Stand. Steht die
    // fehlende Angabe laengst im Formular, waere „fehlt der Betrag" schlicht
    // falsch — dann fehlt nur das Uebernehmen.
    els.bPosPlan.innerHTML = `<div class="pr fehlt"><span>${esc(wartet
      ? 'Erst übernehmen — dann entsteht die Position.'
      : p.grund)}</span></div>`;
    els.bPos.disabled = true;
    els.bPos.className = 'posknopf';
    els.bPos.textContent = 'Als Kostenposition übernehmen';
    return;
  }
  // Eine neue Position aus einem einzigen Beleg braucht keine Aufstellung —
  // dann stuende dieselbe Zahl zweimal da. Erst wo etwas dazukommt, wird
  // gerechnet: bisher + dieser Beleg = danach.
  const einzeln = p.neu && p.belege.length === 1;
  const zeilen = [posZeile('Position', p.kostenart)];
  if (!einzeln) {
    if (p.schon_verbucht) {
      zeilen.push(posZeile('Dieser Beleg', betragText(
        (p.belege.find(b => b.id === d.id) || {}).betrag), 'fertig'));
    } else {
      if (!p.neu) zeilen.push(posZeile('Bisher', betragText(p.vorher)));
      zeilen.push(posZeile('Dieser Beleg', betragText(d.betrag)));
    }
    // Aufgeschluesselt wird nur, was „Bisher + dieser Beleg" nicht schon sagt:
    // liegt an der Position erst ein Beleg, ist „Bisher" bereits der
    // Handeintrag, und die Aufstellung stuende zweimal da.
    if (p.handanteil && p.belege.length > 1) {
      zeilen.push(posZeile(`Alle ${p.belege.length} Belege`,
                           betragText(p.beleg_summe)));
      zeilen.push(posZeile('Von Hand', betragText(p.handanteil)));
    }
  }
  zeilen.push(posZeile(
    einzeln ? 'Neue Position' : p.schon_verbucht ? 'Position gesamt' : 'Danach',
    betragText(p.betrag), 'summe'));
  els.bPosPlan.innerHTML = zeilen.join('');

  els.bPos.disabled = p.schon_verbucht || wartet;
  els.bPos.className = 'posknopf' + (p.schon_verbucht ? ' fertig' : '');
  els.bPos.textContent = p.schon_verbucht ? '✓ Steht in der Abrechnung'
    : p.neu ? 'Position anlegen und übernehmen'
            : 'Betrag zur Position addieren';
}

export async function posZeigen(d) {
  const lauf = ++S.posLauf;
  S.posPlan = null;
  els.bPosHinweis.textContent = '';
  els.bPosHinweis.classList.remove('warn');
  if (!d || d.vermisst) { els.bPosFach.hidden = true; return; }
  els.bPosFach.hidden = false;
  posPlanZeichnen(d);
  try {
    const plan = await api(`/dokumente/${d.id}/position`);
    if (lauf !== S.posLauf || S.gewaehlt !== d.id) return;
    S.posPlan = plan;
  } catch (fehler) {
    if (lauf !== S.posLauf) return;
    S.posPlan = { moeglich: false, grund: String(fehler.message || fehler) };
  }
  posPlanZeichnen(d);
}

els.bPos.addEventListener('click', async () => {
  const d = S.gewaehlt !== null ? dok(S.gewaehlt) : null;
  if (!d || !S.posPlan || !S.posPlan.moeglich) return;
  els.bPos.disabled = true;
  els.bPos.textContent = 'Wird übernommen …';
  try {
    const ergebnis = await api(`/dokumente/${d.id}/position`, { method: 'POST' });
    belegmeldung(`✓ ${ergebnis.kostenart} · ${betragText(ergebnis.betrag)}`
          + (ergebnis.belege.length > 1
            ? ` aus ${ergebnis.belege.length} Belegen` : ''), 'gut');
    await laden();
  } catch (fehler) {
    belegmeldung('⚠ ' + String(fehler.message || fehler), 'schlecht');
    posZeigen(d);
  }
});

els.bPosLos.addEventListener('click', async () => {
  const d = S.gewaehlt !== null ? dok(S.gewaehlt) : null;
  if (!d) return;
  els.bPosLos.disabled = true;
  try {
    const ergebnis = await api(`/dokumente/${d.id}/position`, { method: 'DELETE' });
    belegmeldung(`Aus „${ergebnis.kostenart}“ herausgerechnet · jetzt `
          + betragText(ergebnis.betrag));
    await laden();
  } catch (fehler) {
    belegmeldung('⚠ ' + String(fehler.message || fehler), 'schlecht');
  } finally {
    els.bPosLos.disabled = false;
  }
});
