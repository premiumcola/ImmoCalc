/* N216 / N479 — Ordner-Benennung (GET/POST /api/nextcloud/vorlage).

   Die Vorlage bestimmt, wie ImmoCalc die Objektordner in der Nextcloud
   benennt. Platzhalter (`{ort}`, `{strasse}`, `{name}`, `{plz}`).

   Seit N479 steht die Zeile dazu im Nextcloud-Dialog statt auf der
   Einstellungsseite — sie gehört zur Cloud, nicht neben sie. Und sie steht
   dort IMMER, nicht nur solange keine Vorlage gesetzt ist: im Dialog kostet
   sie keinen Platz auf der Seite, und wer sie ändern will, findet sie. */
import { api, esc } from '../immo.js';
import { feldmeldung, meldungWeg } from './state.js';

let vorlageDlg, vorlageFeld, vorlageMeldung;

export async function vorlageLaden() {
  try {
    const v = await api('/nextcloud/vorlage');
    vorlageFeld.value = v.vorlage;
    document.getElementById('vorlageStatus').textContent =
      v.vorlage || 'Standard';
    document.getElementById('vorlageVerboten').textContent =
      `Nicht erlaubt: ${v.verboten}`;
    beispieleZeigen(v.beispiele);
  } catch {
    document.getElementById('vorlageStatus').textContent = 'Standard';
  }
}

function beispieleZeigen(beispiele) {
  const feld = document.getElementById('vorlageBeispiele');
  feld.innerHTML = beispiele?.length
    ? beispiele.map(b => `▸ ${esc(b.ordner)}`).join('<br>')
    : 'Noch keine Immobilie zum Vorzeigen';
}

/* Bindet Zeile, Speichern und Live-Vorschau. Aufruf einmal beim Laden. */
export function vorlageInit() {
  vorlageDlg = document.getElementById('vorlageDlg');
  vorlageFeld = document.getElementById('vorlageFeld');
  vorlageMeldung = document.getElementById('vorlageMeldung');

  const zeile = document.getElementById('vorlageRow');
  zeile.addEventListener('click', () => {
    meldungWeg(vorlageMeldung);
    // Die Zeile steht IM Nextcloud-Dialog — der geht zu, bevor dieser aufgeht:
    // zwei gestapelte Modals übereinander sind auf dem Telefon nicht zu
    // durchschauen.
    zeile.closest('dialog')?.close();
    vorlageDlg.showModal();
    vorlageLaden();
  });

  document.getElementById('vorlageSpeichern').addEventListener('click', async () => {
    meldungWeg(vorlageMeldung);
    try {
      const antwort = await api('/nextcloud/vorlage', {
        method: 'POST', body: { vorlage: vorlageFeld.value },
      });
      if (antwort.hinweise?.length) {
        feldmeldung(vorlageMeldung, antwort.hinweise.join(' '), false);
      } else {
        // N479 — „Benennung nachziehen" gibt es nicht mehr: bereits angelegte
        // Ordner behalten ihren Namen, neue bekommen den neuen. Das steht
        // jetzt hier, statt auf eine Zeile zu verweisen, die weg ist.
        feldmeldung(vorlageMeldung,
          'Übernommen. Bereits angelegte Ordner behalten ihren Namen; '
          + 'neue Immobilien bekommen den neuen.', true);
      }
      await vorlageLaden();
    } catch (fehler) {
      feldmeldung(vorlageMeldung, String(fehler.message || fehler));
    }
  });

  /* Vorschau beim Tippen — zeigt sofort, was herauskommt */
  let vorschauZeit;
  vorlageFeld.addEventListener('input', () => {
    clearTimeout(vorschauZeit);
    vorschauZeit = setTimeout(async () => {
      try {
        const v = await api('/nextcloud/vorlage');
        beispieleZeigen(v.beispiele.map(b => ({
          ordner: vorlageFeld.value
            .replace(/\{ort\}|%ort/gi, b.objekt.split(' · ')[0] || '')
            .replace(/\{strasse\}|%strasse/gi, '')
            .replace(/\{name\}|%name/gi, b.objekt)
            .replace(/[<>:"/\\|?*]/g, '')
            .replace(/\(\s*\)/g, '').replace(/\s{2,}/g, ' ').trim(),
        })));
      } catch { /* Vorschau ist Beiwerk */ }
    }, 350);
  });
}
