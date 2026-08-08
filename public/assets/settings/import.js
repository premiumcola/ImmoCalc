/* N216 — Sicherung einlesen (POST /api/objekte/import).

   Herunterladen ging schon, einlesen nirgends. Der Endpunkt legt immer ein
   neues Objekt an — das steht im Dialog, damit niemand ein Zusammenführen
   erwartet. Verhaltensgleich zum bisherigen Inline-Skript in settings.html. */
import { api } from '../immo.js';
import { feldmeldung, meldungWeg } from './state.js';

const KEINE_DATEI = 'Noch keine Datei gewählt';

/* Bindet Zeile, Datei-Auswahl und Start-Knopf. Aufruf einmal beim Laden. */
export function importInit() {
  const importDlg = document.getElementById('importDlg');
  const importMeldung = document.getElementById('importMeldung');
  const importDatei = document.getElementById('importDatei');
  const zumObjekt = document.getElementById('importZumObjekt');
  const importName = document.getElementById('importName');

  document.getElementById('importRow').addEventListener('click', () => {
    meldungWeg(importMeldung);
    zumObjekt.style.display = 'none';
    importDatei.value = '';
    importName.textContent = KEINE_DATEI;
    importDlg.showModal();
  });

  document.getElementById('importWahl').addEventListener('click', () => importDatei.click());
  importDatei.addEventListener('change', () => {
    importName.textContent = importDatei.files?.[0]?.name || KEINE_DATEI;
  });

  document.getElementById('importStart').addEventListener('click', async () => {
    const knopf = document.getElementById('importStart');
    const datei = importDatei.files?.[0];
    meldungWeg(importMeldung);
    zumObjekt.style.display = 'none';
    if (!datei) return feldmeldung(importMeldung, 'Bitte eine Sicherungsdatei wählen.');

    knopf.disabled = true;
    knopf.textContent = 'Lese ein …';
    try {
      const daten = JSON.parse(await datei.text());
      const neu = await api('/objekte/import', { method: 'POST', body: daten });
      feldmeldung(importMeldung, `„${neu.name}“ wurde als neue Immobilie angelegt.`, true);
      zumObjekt.href = `objekt.html?o=${encodeURIComponent(neu.slug)}`;
      zumObjekt.style.display = 'block';
    } catch (fehler) {
      feldmeldung(importMeldung, fehler instanceof SyntaxError
        ? 'Das ist keine lesbare JSON-Datei.'
        : String(fehler.message || fehler));
    } finally {
      knopf.disabled = false;
      knopf.textContent = 'Einlesen';
    }
  });
}
