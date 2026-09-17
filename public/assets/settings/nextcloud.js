/* N216 / N479 — Nextcloud: Verbindung, Home-Ordner und Ordner-Benennung.

   Seit N479 hängt das alles an EINEM Knopf — der Dienst-Kachel. Vorher standen
   drei Zeilen auf der Einstellungsseite: Verbindung, Home-Ordner, Benennung.
   Zwei davon waren Einrichtungsschritte, die nach dem ersten Mal nur noch
   Platz gekostet haben; jetzt stehen sie im Dialog der Verbindung, wo sie
   hingehören.

   Der Ordnerbrowser blättert per WebDAV — angefasst wird beim Wählen nichts,
   nur der Home-Pfad in der Konfiguration wird gesetzt. */
import { api, esc, baueDialog, melde } from '../immo.js';
import { feldmeldung, meldungWeg, diensteAuffrischen } from './state.js';

let ncDlg, ordnerDlg;
let ncHome, ncMeldung, ordnerMeldung, pfadleiste, ordnerliste;

let ncZustand = { eingerichtet: false, struktur: [] };
let aktuellerPfad = '';

/* Zustand holen und in den Dialog schreiben: Adresse und Benutzer vorbelegen,
   die Einrichtungsschritte ein- oder ausblenden. Seit N482 wird auch das
   App-Passwort vorbelegt: als Punkte sichtbar, per Auge aufdeckbar. */
async function zustandLaden() {
  try {
    ncZustand = await api('/nextcloud/status');
  } catch {
    ncZustand = { eingerichtet: false, struktur: [] };
    return;
  }
  if (ncZustand.eingerichtet) {
    document.getElementById('ncUrl').value = ncZustand.url;
    document.getElementById('ncUser').value = ncZustand.benutzer;
  }
  // N482 — das App-Passwort vorbelegen: als Punkte sichtbar, per Auge
  // aufdeckbar. Vorher stand im Feld nur der Platzhalter
  // „xxxxx-xxxxx-xxxxx-xxxxx-xxxxx", der wie ein Inhalt aussah.
  document.getElementById('ncPass').value = ncZustand.passwort || '';
  ncHome.textContent = ncZustand.home || 'noch nicht gewählt';
  // Die Einrichtungsschritte gibt es erst, wenn die Verbindung steht —
  // ohne sie liesse sich kein Ordner blättern.
  document.getElementById('ncSchritte').hidden = !ncZustand.eingerichtet;
  document.getElementById('strukturliste').innerHTML =
    (ncZustand.struktur || []).map(o => `<span>${esc(o)}</span>`).join('');
}

/* Öffnet den Verbindungsdialog — der Kachel-Knopf landet hier. */
export async function nextcloudOeffnen() {
  meldungWeg(ncMeldung);
  ncDlg.showModal();
  await zustandLaden();
}

async function ordnerZeigen(pfad = '') {
  aktuellerPfad = pfad;
  pfadleiste.textContent = '/' + pfad.replace(/^\//, '');
  ordnerliste.innerHTML = '<div class="leer">wird geladen …</div>';
  try {
    const daten = await api('/nextcloud/ordner?pfad=' + encodeURIComponent(pfad));
    const hoch = daten.hoch !== null && pfad
      ? `<button data-pfad="${esc(daten.hoch)}"><span class="sym">↰</span>eine Ebene höher</button>`
      : '';
    const eintraege = daten.ordner.map(o =>
      `<button data-pfad="${esc(o.pfad.replace(/^\//, ''))}">
         <span class="sym">▸</span>${esc(o.name)}</button>`).join('');
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

/* Bindet Dialoge und Formulare. Aufruf einmal beim Laden der Seite; der
   Zustand wird erst geholt, wenn der Dialog aufgeht. */
export function nextcloudInit() {
  ncDlg = document.getElementById('ncDlg');
  ordnerDlg = document.getElementById('ordnerDlg');
  ncHome = document.getElementById('ncHome');
  ncMeldung = document.getElementById('ncMeldung');
  ordnerMeldung = document.getElementById('ordnerMeldung');
  pfadleiste = document.getElementById('pfadleiste');
  ordnerliste = document.getElementById('ordnerliste');

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
      diensteAuffrischen();
      setTimeout(() => { ncDlg.close(); oeffneOrdnerwahl(); }, 900);
    } catch (fehler) {
      feldmeldung(ncMeldung, String(fehler.message || fehler).replace(/^\d+\s*/, '')
        || 'Verbindung fehlgeschlagen');
    } finally {
      knopf.disabled = false;
      knopf.textContent = 'Verbinden und prüfen';
    }
  });

  // Der Verbindungsdialog geht zu, bevor der nächste aufgeht: zwei gestapelte
  // Modals übereinander sind auf dem Telefon nicht zu durchschauen.
  document.getElementById('ncHomeRow').addEventListener('click', () => {
    ncDlg.close();
    oeffneOrdnerwahl();
  });
  ordnerliste.addEventListener('click', e => {
    const knopf = e.target.closest('[data-pfad]');
    if (knopf) ordnerZeigen(knopf.dataset.pfad);
  });

  /* N483 — Dateinamen richten. Immer erst der Trockenlauf: der Nutzer sieht,
     was passieren würde, und entscheidet dann. Ein Lauf, der ohne Rückfrage
     Dateien in der Cloud anfasst, wäre an dieser Stelle falsch. */
  document.getElementById('namenRow').addEventListener('click', async () => {
    ncDlg.close();
    let plan;
    try {
      plan = await api('/dokumente/namen-richten', { method: 'POST' });
    } catch (f) {
      melde(f.message || 'Prüfung fehlgeschlagen', 'neg');
      return;
    }
    if (!plan.anzahl) {
      melde('Alle Belege heißen bereits nach der aktuellen Regel', 'pos');
      return;
    }
    const proben = plan.plan.slice(0, 6).map(p =>
      `<div class="nr-zeile"><span class="alt">${esc(p.alt)}</span>
       <span class="neu">${esc(p.neu)}</span></div>`).join('');
    const dlg = baueDialog(`
      <div class="dt">${plan.anzahl} ${plan.anzahl === 1 ? 'Beleg' : 'Belege'}
        ${plan.anzahl === 1 ? 'heißt' : 'heißen'} anders als heute vorgesehen</div>
      <p>Umbenannt wird <b>im selben Ordner</b> — verschoben, gelöscht oder
         überschrieben wird nichts. Die Belege bleiben verknüpft.</p>
      <div class="nr-liste">${proben}</div>
      ${plan.anzahl > 6 ? `<p class="hinweis">… und ${plan.anzahl - 6} weitere.</p>` : ''}
      <button type="button" class="btn" id="nrLos">Namen richten</button>`);
    dlg.querySelector('#nrLos').addEventListener('click', async e => {
      e.target.disabled = true;
      e.target.textContent = 'Benennt um …';
      try {
        const a = await api('/dokumente/namen-richten?trocken=false',
                            { method: 'POST' });
        dlg.close();
        melde(`${a.umbenannt.length} umbenannt`
          + (a.fehler.length ? ` · ${a.fehler.length} nicht möglich` : ''),
          a.fehler.length ? 'neg' : 'pos');
      } catch (f) {
        dlg.close();
        melde(f.message || 'Umbenennen fehlgeschlagen', 'neg');
      }
    });
  });

  document.getElementById('homeWaehlen').addEventListener('click', async () => {
    try {
      const antwort = await api('/nextcloud/home', {
        method: 'POST', body: { pfad: aktuellerPfad },
      });
      ncZustand.home = antwort.home;
      ncHome.textContent = antwort.home;
      ordnerDlg.close();
      diensteAuffrischen();
    } catch (fehler) {
      feldmeldung(ordnerMeldung, String(fehler.message || fehler));
    }
  });
}
