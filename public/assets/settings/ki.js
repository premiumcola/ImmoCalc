/* N216 — KI-Beleg-Auslese (GET/POST/DELETE /api/ki/…).

   Anthropic-Schluessel eintragen (wie die Nextcloud-Zugangsdaten) und sehen,
   dass das KI-Tool online und erreichbar ist. Der Schluessel wird NIE im
   Klartext angezeigt — nur „gespeichert" oder leer. Verhaltensgleich zum
   bisherigen Inline-Skript in settings.html. */
import { api, frage } from '../immo.js';
import { feldmeldung, meldungWeg, augenBinden, diensteAuffrischen } from './state.js';

let kiDlg, kiMeldung, kiKey, kiModell, kiEntfernen;
let kiZustand = { eingerichtet: false };

/* N479 — den Stand holen und in den Dialog schreiben. Die Statuszeile auf der
   Seite gibt es nicht mehr; was der Nutzer sieht, steht in der Dienst-Kachel
   (siehe `vKi` in verknuepfungen.js). Hier bleibt nur, was der Dialog
   braucht. */
export async function kiZustandLaden() {
  try {
    kiZustand = await api('/ki/status') || { eingerichtet: false };
  } catch {
    kiZustand = { eingerichtet: false };
  }
  // Ein gespeicherter Schlüssel lässt sich entfernen; ein env-Schlüssel nicht.
  kiEntfernen.style.display = kiZustand.gespeichert ? 'block' : 'none';
  // Den Schlüssel nie vorbelegen — nur das Modell, das kein Geheimnis ist.
  kiKey.value = '';
  kiModell.value = kiZustand.gespeichert && kiZustand.modell ? kiZustand.modell : '';
}

/* Öffnet den Dialog — der Kachel-Knopf landet hier. */
export async function kiOeffnen() {
  meldungWeg(kiMeldung);
  kiDlg.showModal();
  await kiZustandLaden();
}

/* Bindet Formular und Entfernen-Knopf. Aufruf einmal beim Laden. */
export function kiInit() {
  kiDlg = document.getElementById('kiDlg');
  kiMeldung = document.getElementById('kiMeldung');
  kiKey = document.getElementById('kiKey');
  kiModell = document.getElementById('kiModell');
  kiEntfernen = document.getElementById('kiEntfernen');
  augenBinden(kiDlg);

  document.getElementById('kiForm').addEventListener('submit', async e => {
    e.preventDefault();
    const knopf = document.getElementById('kiSpeichern');
    const key = kiKey.value.trim();
    if (!key) return feldmeldung(kiMeldung, 'Bitte einen Schlüssel eingeben.');
    knopf.disabled = true;
    knopf.textContent = 'Speichere und prüfe …';
    meldungWeg(kiMeldung);
    try {
      const a = await api('/ki/schluessel', {
        method: 'POST', body: { key, modell: kiModell.value.trim() },
      });
      feldmeldung(kiMeldung, a.erreichbar
        ? 'Gespeichert. Das KI-Tool ist online und erreichbar.'
        : `Gespeichert, aber nicht erreichbar${a.fehler ? ` — ${a.fehler}` : ''}.`,
        !!a.erreichbar);
      kiKey.value = '';
      await kiZustandLaden();
      diensteAuffrischen();
    } catch (fehler) {
      feldmeldung(kiMeldung, String(fehler.message || fehler).replace(/^\d+\s*/, '')
        || 'Speichern fehlgeschlagen');
    } finally {
      knopf.disabled = false;
      knopf.textContent = 'Speichern und prüfen';
    }
  });

  kiEntfernen.addEventListener('click', async () => {
    const ja = await frage('Schlüssel entfernen?',
      'Die KI-Auslese wird danach nicht mehr genutzt; Belege werden wieder rein '
      + 'über die Mustererkennung gelesen.', { knopf: 'Entfernen' });
    if (!ja) return;
    meldungWeg(kiMeldung);
    try {
      await api('/ki/schluessel', { method: 'DELETE' });
      feldmeldung(kiMeldung, 'Schlüssel entfernt.', true);
      await kiZustandLaden();
      diensteAuffrischen();
    } catch (fehler) {
      feldmeldung(kiMeldung, String(fehler.message || fehler));
    }
  });
}
