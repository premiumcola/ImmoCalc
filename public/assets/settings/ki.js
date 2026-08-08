/* N216 — KI-Beleg-Auslese (GET/POST/DELETE /api/ki/…).

   Anthropic-Schluessel eintragen (wie die Nextcloud-Zugangsdaten) und sehen,
   dass das KI-Tool online und erreichbar ist. Der Schluessel wird NIE im
   Klartext angezeigt — nur „gespeichert" oder leer. Verhaltensgleich zum
   bisherigen Inline-Skript in settings.html. */
import { api, frage } from '../immo.js';
import { feldmeldung, meldungWeg } from './state.js';

let kiDlg, kiStatus, kiIkon, kiMeldung, kiKey, kiModell, kiEntfernen;
let kiZustand = { eingerichtet: false };

/* Aus dem Status eine Zeile und eine Kachelfarbe machen:
   grün = online, rot = eingerichtet aber nicht erreichbar,
   grau = nicht eingerichtet. */
function kiZeigen(z) {
  kiZustand = z || { eingerichtet: false };
  const modell = z && z.modell ? ` · ${z.modell}` : '';
  let text, ikon;
  if (!z || !z.eingerichtet) {
    text = 'nicht eingerichtet';
    ikon = '';
  } else if (z.erreichbar === true) {
    const quelle = z.gespeichert ? '' : (z.aus_umgebung ? ' · aus Umgebung' : '');
    text = `online · erreichbar${quelle}${modell}`;
    ikon = ' aktiv';
  } else if (z.erreichbar === false) {
    text = 'eingerichtet, aber nicht erreichbar'
      + (z.fehler ? ` — ${z.fehler}` : '');
    ikon = ' fehler';
  } else {
    text = `eingerichtet${modell}`;
    ikon = ' warte';
  }
  kiStatus.textContent = text;
  kiIkon.className = 'ic' + ikon;
  // Ein gespeicherter Schlüssel lässt sich entfernen; ein env-Schlüssel nicht.
  kiEntfernen.style.display = z && z.gespeichert ? 'block' : 'none';
}

export async function kiZustandLaden() {
  try {
    kiZeigen(await api('/ki/status'));
  } catch {
    kiStatus.textContent = 'Status nicht abrufbar';
    kiIkon.className = 'ic';
  }
}

/* Bindet Zeile, Formular und Entfernen-Knopf. Aufruf einmal beim Laden. */
export function kiInit() {
  kiDlg = document.getElementById('kiDlg');
  kiStatus = document.getElementById('kiStatus');
  kiIkon = document.getElementById('kiIkon');
  kiMeldung = document.getElementById('kiMeldung');
  kiKey = document.getElementById('kiKey');
  kiModell = document.getElementById('kiModell');
  kiEntfernen = document.getElementById('kiEntfernen');

  document.getElementById('kiRow').addEventListener('click', () => {
    meldungWeg(kiMeldung);
    // Den Schlüssel nie vorbelegen — nur das Modell, das kein Geheimnis ist.
    kiKey.value = '';
    kiModell.value = kiZustand.gespeichert && kiZustand.modell ? kiZustand.modell : '';
    kiDlg.showModal();
  });

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
    } catch (fehler) {
      feldmeldung(kiMeldung, String(fehler.message || fehler));
    }
  });
}
