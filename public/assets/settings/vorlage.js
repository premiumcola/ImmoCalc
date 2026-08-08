/* N216 — Ordner-Benennung (GET/POST /api/nextcloud/vorlage).

   Die Vorlage bestimmt, wie ImmoCalc die Objektordner in der Nextcloud
   benennt. Platzhalter (`{ort}`, `{strasse}`, `{name}`, `{plz}`). Nach dem
   Speichern zieht die Zeile „Benennung nachziehen" mit — daher der Import
   aus `umzug.js`. Verhaltensgleich zum bisherigen Inline-Skript. */
import { api, esc } from '../immo.js';
import { feldmeldung, meldungWeg } from './state.js';
import { umzugLaden } from './umzug.js';

let vorlageDlg, vorlageFeld, vorlageMeldung;

export async function vorlageLaden() {
  try {
    const v = await api('/nextcloud/vorlage');
    vorlageFeld.value = v.vorlage;
    document.getElementById('vorlageStatus').textContent =
      v.vorlage || 'noch nicht festgelegt';
    document.getElementById('vorlageVerboten').textContent =
      `Nicht erlaubt: ${v.verboten}`;
    // N310 — es gibt eine gute Vorgabe: die Zeile erscheint nur, wenn gar keine
    // Vorlage da ist. Sonst bleibt sie weg — Einstellungen, die man nie anfasst,
    // gehoeren nicht in die Liste. Der Dialog bleibt erreichbar, sobald sie da ist.
    document.getElementById('vorlageRow').hidden = Boolean(v.vorlage);
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

  document.getElementById('vorlageRow').addEventListener('click', () => {
    meldungWeg(vorlageMeldung);
    vorlageDlg.showModal();
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
        feldmeldung(vorlageMeldung, antwort.umzug_noetig
          ? `Übernommen. ${antwort.umzug_noetig} bereits angelegte Ordner `
            + `${antwort.umzug_noetig === 1 ? 'heißt' : 'heißen'} noch wie zuvor `
            + '— „Benennung nachziehen" holt sie nach.'
          : 'Übernommen. Bereits angelegte Ordner bleiben unverändert.', true);
      }
      await vorlageLaden();
      await umzugLaden();
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
