/* N216 — Postfach für den Versand der Abrechnungen.

   Ein Anbieter aus einer festen Liste (GMX, Web.de, Custom …) — der Server
   ergänzt Host und Port automatisch, „custom" gibt die beiden Felder frei.
   Nach dem Verbinden lässt sich eine Testmail an die eigene Adresse schicken.
   Verhaltensgleich zum bisherigen Inline-Skript in settings.html. */
import { api } from '../immo.js';
import { auswahlfeld } from '../auswahl.js';
import { feldmeldung, meldungWeg } from './state.js';

let mailDlg, mailStatus, mailMeldung, serverZeile;
let anbieterListe = [];
let anbieterWahl;

function anbieterUebernehmen() {
  const a = anbieterListe.find(x => x.id === anbieterWahl.wert());
  if (!a) return;
  // Nur beim freien Anbieter muss der Server von Hand eingetragen werden
  serverZeile.style.display = a.id === 'custom' ? 'flex' : 'none';
  document.getElementById('mailServer').value = a.server;
  document.getElementById('mailPort').value = a.port;
}

export async function mailZustand() {
  try {
    const [{ anbieter }, status] = await Promise.all([
      api('/mail/anbieter'), api('/mail/status'),
    ]);
    anbieterListe = anbieter;
    anbieterWahl.fuelle(anbieter.map(a => ({ wert: a.id, text: a.name })),
                        status.anbieter);
    anbieterUebernehmen();

    if (status.verbunden) {
      mailStatus.textContent = `${status.absender} · ${status.server}`;
      document.getElementById('mailBenutzer').value = status.benutzer;
      document.getElementById('mailName').value = status.absender_name || '';
      document.getElementById('mailTestbereich').style.display = 'block';
      document.getElementById('mailTestAn').value = status.absender;
    } else {
      mailStatus.textContent = 'noch nicht verbunden';
    }
    document.getElementById('mailIkon').className =
      'ic' + (status.verbunden ? ' aktiv' : '');
  } catch {
    mailStatus.textContent = 'Status nicht abrufbar';
  }
}

/* Bindet Zeile, Anbieter-Chooser, Formular und Testmail. Aufruf einmal
   beim Laden — der Zustand wird danach über `mailZustand` nachgezogen. */
export function mailInit() {
  mailDlg = document.getElementById('mailDlg');
  mailStatus = document.getElementById('mailStatus');
  mailMeldung = document.getElementById('mailMeldung');
  serverZeile = document.getElementById('mailServerZeile');

  anbieterWahl = auswahlfeld(document.getElementById('mailAnbieter'), {
    label: 'Anbieter',
    aenderung: anbieterUebernehmen,
  });

  document.getElementById('mailRow').addEventListener('click', () => {
    meldungWeg(mailMeldung);
    mailDlg.showModal();
  });

  document.getElementById('mailForm').addEventListener('submit', async e => {
    e.preventDefault();
    const knopf = document.getElementById('mailSpeichern');
    knopf.disabled = true;
    knopf.textContent = 'Melde an …';
    meldungWeg(mailMeldung);
    try {
      await api('/mail/verbindung', {
        method: 'POST',
        body: {
          anbieter: anbieterWahl.wert(),
          server: document.getElementById('mailServer').value.trim(),
          port: Number(document.getElementById('mailPort').value) || 587,
          benutzer: document.getElementById('mailBenutzer').value.trim(),
          passwort: document.getElementById('mailPass').value,
          absender: document.getElementById('mailBenutzer').value.trim(),
          absender_name: document.getElementById('mailName').value.trim(),
        },
      });
      feldmeldung(mailMeldung, 'Postfach verbunden. Jetzt eine Testmail schicken.', true);
      await mailZustand();
    } catch (fehler) {
      feldmeldung(mailMeldung, String(fehler.message || fehler));
    } finally {
      knopf.disabled = false;
      knopf.textContent = 'Verbinden und prüfen';
    }
  });

  document.getElementById('mailTest').addEventListener('click', async () => {
    const an = document.getElementById('mailTestAn').value.trim();
    if (!an) return feldmeldung(mailMeldung, 'Bitte eine Empfängeradresse angeben');
    const knopf = document.getElementById('mailTest');
    knopf.disabled = true;
    knopf.textContent = 'Sende …';
    try {
      await api('/mail/test', { method: 'POST', body: { an } });
      feldmeldung(mailMeldung, `Testmail an ${an} verschickt.`, true);
    } catch (fehler) {
      feldmeldung(mailMeldung, String(fehler.message || fehler));
    } finally {
      knopf.disabled = false;
      knopf.textContent = 'Testmail senden';
    }
  });
}
