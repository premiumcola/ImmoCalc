/* N216 — Nextcloud: Verbindung einrichten und Home-Ordner wählen.

   Zwei Zeilen auf der Seite („Nextcloud-Verbindung" und „Home-Ordner"), zwei
   Dialoge. Der Ordnerbrowser blättert per WebDAV — angefasst wird beim Wählen
   nichts, nur der Home-Pfad in der Konfiguration wird gesetzt. Verhaltensgleich
   zum bisherigen Inline-Skript in settings.html. */
import { api, esc } from '../immo.js';
import { feldmeldung, meldungWeg } from './state.js';

let ncDlg, ordnerDlg;
let ncStatus, ncHome, ncMeldung, ordnerMeldung, pfadleiste, ordnerliste;

let ncZustand = { eingerichtet: false, struktur: [] };
let aktuellerPfad = '';

/* Statuszeile befuellen: gruen (verbunden + Home), gelb (verbunden ohne Home),
   grau (nicht eingerichtet). Die Struktur-Vorschau zeigt die Objektunterordner
   an, die spaeter angelegt werden. */
export async function zustandLaden() {
  try {
    ncZustand = await api('/nextcloud/status');
  } catch {
    ncStatus.textContent = 'Status nicht abrufbar';
    return;
  }
  if (ncZustand.eingerichtet) {
    ncStatus.textContent = `${ncZustand.benutzer} · ${ncZustand.url}`;
    document.getElementById('ncUrl').value = ncZustand.url;
    document.getElementById('ncUser').value = ncZustand.benutzer;
    // Grün und leise atmend, sobald auch der Home-Ordner steht; bis dahin
    // gelb — verbunden, aber noch nicht einsatzbereit.
    document.getElementById('ncIkon').className =
      'ic ' + (ncZustand.home ? 'aktiv' : 'warte');
  } else {
    ncStatus.textContent = 'noch nicht eingerichtet';
    document.getElementById('ncIkon').className = 'ic';
  }
  ncHome.textContent = ncZustand.home || (ncZustand.eingerichtet
    ? 'noch nicht gewählt' : 'erst Verbindung einrichten');
  // N310 — der Home-Ordner ist der Schreibriegel der Anwendung: einmal gewählt,
  // nie wieder angefasst. Die Zeile steht deshalb nur da, solange er fehlt —
  // ohne ihn liesse sich die Anwendung sonst gar nicht einrichten.
  document.getElementById('ncHomeRow').hidden = Boolean(ncZustand.home);
  document.getElementById('strukturliste').innerHTML =
    (ncZustand.struktur || []).map(o => `<span>${esc(o)}</span>`).join('');
}

async function ordnerZeigen(pfad = '') {
  aktuellerPfad = pfad;
  pfadleiste.textContent = '/' + pfad.replace(/^\//, '');
  ordnerliste.innerHTML = '<div class="leer">wird geladen …</div>';
  try {
    const daten = await api('/nextcloud/ordner?pfad=' + encodeURIComponent(pfad));
    const hoch = daten.hoch !== null && pfad
      ? `<button data-pfad="${daten.hoch}"><span class="sym">↰</span>eine Ebene höher</button>`
      : '';
    const eintraege = daten.ordner.map(o =>
      `<button data-pfad="${o.pfad.replace(/^\//, '')}">
         <span class="sym">▸</span>${o.name}</button>`).join('');
    ordnerliste.innerHTML = hoch + (eintraege ||
      '<div class="leer">Keine Unterordner — dieser Ordner ist wählbar</div>');
  } catch (fehler) {
    ordnerliste.innerHTML = '<div class="leer">Ordner nicht lesbar</div>';
    feldmeldung(ordnerMeldung, String(fehler.message || fehler));
  }
}

function oeffneOrdnerwahl() {
  if (!ncZustand.eingerichtet) {
    meldungWeg(ncMeldung);
    ncDlg.showModal();
    return;
  }
  meldungWeg(ordnerMeldung);
  ordnerDlg.showModal();
  ordnerZeigen((ncZustand.home || '').replace(/^\//, ''));
}

/* Bindet die beiden Zeilen und Dialoge. Aufruf einmal beim Laden der Seite;
   das eigentliche Nachziehen des Zustands passiert danach ueber `zustandLaden`. */
export function nextcloudInit() {
  ncDlg = document.getElementById('ncDlg');
  ordnerDlg = document.getElementById('ordnerDlg');
  ncStatus = document.getElementById('ncStatus');
  ncHome = document.getElementById('ncHome');
  ncMeldung = document.getElementById('ncMeldung');
  ordnerMeldung = document.getElementById('ordnerMeldung');
  pfadleiste = document.getElementById('pfadleiste');
  ordnerliste = document.getElementById('ordnerliste');

  document.getElementById('ncRow').addEventListener('click', () => {
    meldungWeg(ncMeldung);
    ncDlg.showModal();
  });

  document.getElementById('ncForm').addEventListener('submit', async e => {
    e.preventDefault();
    const knopf = document.getElementById('ncSpeichern');
    knopf.disabled = true;
    knopf.textContent = 'Prüfe Verbindung …';
    meldungWeg(ncMeldung);
    try {
      await api('/nextcloud/verbindung', {
        method: 'POST',
        body: {
          url: document.getElementById('ncUrl').value.trim(),
          benutzer: document.getElementById('ncUser').value.trim(),
          passwort: document.getElementById('ncPass').value,
          tls_pruefen: false,
        },
      });
      feldmeldung(ncMeldung, 'Verbindung steht. Jetzt den Home-Ordner wählen.', true);
      await zustandLaden();
      setTimeout(() => { ncDlg.close(); oeffneOrdnerwahl(); }, 900);
    } catch (fehler) {
      feldmeldung(ncMeldung, String(fehler.message || fehler).replace(/^\d+\s*/, '')
        || 'Verbindung fehlgeschlagen');
    } finally {
      knopf.disabled = false;
      knopf.textContent = 'Verbinden und prüfen';
    }
  });

  document.getElementById('ncHomeRow').addEventListener('click', oeffneOrdnerwahl);
  ordnerliste.addEventListener('click', e => {
    const knopf = e.target.closest('[data-pfad]');
    if (knopf) ordnerZeigen(knopf.dataset.pfad);
  });

  document.getElementById('homeWaehlen').addEventListener('click', async () => {
    try {
      const antwort = await api('/nextcloud/home', {
        method: 'POST', body: { pfad: aktuellerPfad },
      });
      ncZustand.home = antwort.home;
      ncHome.textContent = antwort.home;
      document.getElementById('ncHomeRow').hidden = Boolean(antwort.home);
      ordnerDlg.close();
    } catch (fehler) {
      feldmeldung(ordnerMeldung, String(fehler.message || fehler));
    }
  });
}
