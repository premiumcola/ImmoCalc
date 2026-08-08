/* N216 — Die Beleg-Vorschau (rechte Spalte auf Desktop, unter der Karte auf
   dem Telefon). Der Server liefert die erste Seite als Bild — ein Klick
   oeffnet die grosse Ansicht (belegAnsehen aus immo.js). */

import { S, els } from './state.js';
import { esc, belegAnsehen } from '../immo.js';
import { dok, sichtbareDokumente } from './helpers.js';

export function vorschauLeeren() {
  if (S.vorschauAdresse) {
    URL.revokeObjectURL(S.vorschauAdresse);
    S.vorschauAdresse = null;
  }
  els.bSchau.innerHTML = '';
}

export function vorschauText(text, schlecht) {
  vorschauLeeren();
  els.bSchau.classList.add('knapp');
  els.bSchau.innerHTML = `<div class="wart${schlecht ? ' leer' : ''}">${esc(text)}</div>`;
}

export async function vorschauLaden(d) {
  const lauf = ++S.vorschauLauf;
  if (!d.abgelegt) {
    vorschauText(d.vermisst
      ? 'Die Datei ist in der Nextcloud nicht mehr auffindbar.'
      : 'Zu diesem Eintrag liegt noch keine Datei in der Cloud.', true);
    return;
  }
  vorschauText('Beleg wird geholt …');
  try {
    // Die GANZE erste Seite als Bild (serverseitig gerendert): so fuellt die
    // Vorschau die Breite, statt dass ein PDF-Betrachter sie beschneidet.
    const antwort = await fetch(`/api/dokumente/${d.id}/vorschau`);
    // 415 = keine Bildvorschau (z. B. Tabelle) — dezent anbieten, im Tab zu
    // oeffnen, statt eine Fehlermeldung zu zeigen.
    if (antwort.status === 415) {
      if (lauf !== S.vorschauLauf) return;
      vorschauLeeren();
      els.bSchau.classList.add('knapp');
      els.bSchau.innerHTML = '<div class="wart">Keine Bildvorschau möglich.'
        + `<a href="/api/dokumente/${d.id}/inhalt" target="_blank"`
        + ' rel="noopener">Im neuen Tab öffnen ↗</a></div>';
      return;
    }
    if (!antwort.ok) {
      const grund = await antwort.json().then(k => k.detail).catch(() => null);
      throw new Error(grund || 'Der Beleg lässt sich gerade nicht öffnen.');
    }
    const blob = await antwort.blob();
    if (lauf !== S.vorschauLauf) return;    // ein neuerer Beleg ist schon dran
    vorschauLeeren();
    els.bSchau.classList.remove('knapp');
    S.vorschauAdresse = URL.createObjectURL(blob);
    const bild = document.createElement('img');
    bild.alt = `Vorschau ${d.dateiname}`;
    bild.src = S.vorschauAdresse;
    els.bSchau.appendChild(bild);
    els.bSchau.insertAdjacentHTML('beforeend', '<span class="lupe">größer ansehen</span>');
  } catch (fehler) {
    if (lauf === S.vorschauLauf) {
      vorschauText(String(fehler.message || fehler), true);
    }
  }
}

export const grossAnsehen = () => {
  const d = S.gewaehlt !== null ? dok(S.gewaehlt) : null;
  if (!d || !d.abgelegt) return;
  // N99 — Ablageort mitgeben, damit die Datei in der Cloud auffindbar ist.
  // N288 — dazu die ganze sichtbare Liste: hier stehen zwanzig Belege
  // untereinander, und wer den fünften ansieht, will meistens gleich den
  // sechsten. Mit den Geschwistern blättert das Beleg-Fenster selbst weiter,
  // statt jedes Mal zurück in die Liste zu zwingen.
  belegAnsehen(`/api/dokumente/${d.id}/inhalt`, d.dateiname, d.pfad || '',
               d.id, sichtbareDokumente());
};

els.bSchau.addEventListener('click', grossAnsehen);
els.bSchau.addEventListener('keydown', e => {
  if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); grossAnsehen(); }
});
