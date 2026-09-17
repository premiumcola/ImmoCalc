/* N474 / N478 / N479 — Sicherung dieser Familie.

   Der Dialog erklärt zuerst, WIE gesichert wird (Nutzer: „der Nutzer soll die
   Sicherheit haben zu wissen, wie die Backups gemacht werden"), dann kommen
   Einstellungen, Aktionen und die Liste der bisherigen Stände.

   Seit N479 steht das hier als eigenes Modul statt inline in settings.html —
   die Sicherung ist ein Dienst wie Nextcloud oder Mail und hängt an derselben
   Kachel-Reihe. Und: kein „leer = beibehalten" mehr. Passwortfelder zeigen
   Punkte mit einem Auge daneben; wo ein Geheimnis gar nicht zurückgelesen
   werden KANN (das Backup-Passwort ist nur als abgeleiteter Schlüssel
   gespeichert), sagt das Feld das ausdrücklich statt es zu verschweigen. */
import { api, esc, melde, baueDialog, passwortFeld,
         augenBinden } from '../immo.js';
import { feldmeldung, meldungWeg, passwortAbfrage,
         diensteAuffrischen } from './state.js';

const KOOFR_DAV = 'https://app.koofr.net/dav/Koofr';
const RHYTHMUS_TEXT = { '': 'Aus', taeglich: 'Täglich', woechentlich: 'Wöchentlich' };
const ZIEL_TEXT = { '': 'kein Ziel', nextcloud: 'Nextcloud', webdav: 'WebDAV-Speicher',
                    download: 'heruntergeladen', ordner: 'Server-Ordner' };

let backupDatei;

const groesseText = b => b >= 1048576 ? `${(b / 1048576).toFixed(1)} MB`
  : b >= 1024 ? `${Math.round(b / 1024)} KB` : `${b} B`;

const wannText = iso => {
  const d = new Date(iso);
  return `${String(d.getDate()).padStart(2, '0')}.${String(d.getMonth() + 1).padStart(2, '0')}. `
    + `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
};

const dazuText = dazu => Object.entries(dazu || {})
  .map(([k, v]) => `${v > 0 ? '+' : ''}${v} ${{ objekte: 'Obj.', zeitraeume: 'Zeitr.',
    belege: 'Belege', kontakte: 'Kont.' }[k] || k}`).join(' · ');

/* N478 — was an DATEIEN dazukam. Steht getrennt, weil es die Größe erklärt:
   „+12 Dateien · 8,4 MB" sagt mehr als eine gewachsene Archivzahl. */
const dateienText = z => z && z.dateien_neu
  ? `+${z.dateien_neu} Dateien · ${groesseText(z.dateien_bytes || 0)}` : '';

/* Datei-Uploads gehen nicht über `api()` (das setzt JSON) — hier mit FormData,
   der Browser setzt den Multipart-Rahmen selbst. */
async function apiForm(pfad, form) {
  const antwort = await fetch('/api' + pfad, { method: 'POST', body: form });
  if (antwort.status === 401) { location.href = 'anmeldung.html'; return new Promise(() => {}); }
  if (!antwort.ok) {
    const grund = await antwort.json().then(k => k.detail).catch(() => null);
    throw new Error(grund || `${antwort.status} ${pfad}`);
  }
  return antwort.status === 204 ? null : antwort.json();
}

/* N479 — der Stand für die Dienst-Kachel. Vier Fälle, und der mittlere ist
   der wichtige: eingerichtet, aber noch nie gelaufen ist kein Fehler und
   auch kein „alles gut" — das ist gelb. */
export async function backupStand() {
  let s;
  try {
    s = await api('/backup/einstellungen');
  } catch {
    return { stand: 'weg', text: 'Stand nicht abrufbar' };
  }
  if (!s.hat_passwort) return { stand: 'aus', text: 'noch nicht eingerichtet' };
  const letzte = s.backups[0];
  if (!letzte) return { stand: 'warte', text: 'noch keine Sicherung gelaufen' };
  return { stand: 'gut',
           text: `${ZIEL_TEXT[s.ziel]} · zuletzt ${wannText(letzte.zeitpunkt)}` };
}

function listeHtml(backups) {
  if (!backups.length) return '<div class="bk-leer">Noch keine Sicherung.</div>';
  return `<div class="bk-liste">${backups.map(b => `
    <div class="bk-zeile">
      <span class="wann">${esc(wannText(b.zeitpunkt))}</span>
      <span class="was">${esc(ZIEL_TEXT[b.ziel] || b.ziel)} · ${esc(groesseText(b.groesse))}
        · ${b.zusammenfassung.objekte ?? 0} Obj. · ${b.zusammenfassung.belege ?? 0} Belege
        ${dateienText(b.zusammenfassung) ? '· ' + esc(dateienText(b.zusammenfassung)) : ''}
        ${b.ausloeser === 'hand' ? '· von Hand' : ''}</span>
      ${Object.keys(b.dazu || {}).length ? `<span class="dazu">${esc(dazuText(b.dazu))}</span>` : ''}
    </div>`).join('')}</div>`;
}

function instanzHtml(i) {
  if (!i.eingerichtet) {
    return `<div class="bk-instanz">Zusätzlich zur Familien-Sicherung legt der Betreiber
      nachts einen Schnappschuss der ganzen Installation ab — <b>auf diesem Server noch
      nicht eingerichtet</b> (BACKUP_PASSWORT fehlt).</div>`;
  }
  return `<div class="bk-instanz">Zusätzlich sichert der Betreiber jede Nacht die ganze
    Installation (alle Familien, Konten, Einstellungen) verschlüsselt auf den Server:
    <b>${i.anzahl} Stände</b>${i.letzte ? `, zuletzt <b>${esc(wannText(i.letzte.zeitpunkt))}</b>
    (${esc(groesseText(i.letzte.groesse))})` : ''}. 30 Tage lückenlos, danach je Monat
    ein Stand für ein Jahr.</div>`;
}

/* Das Backup-Passwort liegt nur als abgeleiteter Schlüssel in der Datenbank —
   es lässt sich grundsätzlich nicht anzeigen. Genau das steht im Feld, statt
   ein „leer = beibehalten" zu verlangen, das niemand von selbst versteht. */
function passwortBlock(s) {
  if (!s.hat_passwort) {
    return passwortFeld('bkPw',
      'Backup-Passwort (mind. 12 Zeichen)',
      'autocomplete="new-password" minlength="12" required')
      + `<p class="hinweis" style="margin-top:-6px">Gut aufheben: ImmoCalc
         speichert davon nur einen abgeleiteten Schlüssel, nie das Passwort
         selbst. Ohne dein Passwort ist das Archiv wertlos — auch für uns.</p>`;
  }
  return `<div class="bk-gesetzt">
      <span class="bk-hak">✓</span>
      <span>Backup-Passwort ist gesetzt. Anzeigen lässt es sich nicht — davon
        liegt nur ein abgeleiteter Schlüssel hier, nicht das Passwort.</span>
    </div>
    <button type="button" class="btn leise" id="bkPwTauschen"
            style="margin:0 0 14px">Backup-Passwort ersetzen</button>
    <div id="bkPwNeu" hidden>${passwortFeld('bkPw',
      'Neues Backup-Passwort (mind. 12 Zeichen)',
      'autocomplete="new-password" minlength="12"')}
      <p class="hinweis" style="margin-top:-6px">Ältere Sicherungen bleiben mit
         dem <b>alten</b> Passwort verschlüsselt — hebe es auf, solange du sie
         noch einspielen willst.</p>
    </div>`;
}

function backupDialog(s) {
  const dlg = baueDialog(`
    <div class="dt">Sicherung dieser Familie</div>
    <p>Jede Nacht zwischen ${s.nacht_von} und ${s.nacht_bis} Uhr prüft ImmoCalc, ob sich seit
       der letzten Sicherung etwas geändert hat — nur dann wird gesichert. Wer tagsüber
       arbeitet, ist um diese Zeit fertig. Das Archiv wird <b>vor</b> dem Ablegen mit deinem
       Backup-Passwort verschlüsselt: wer die Datei findet, kann sie ohne das Passwort
       nicht öffnen. Es enthält alles, was dieser Familie gehört — Immobilien, Zeiträume,
       Kontakte, Einstellungen — und <b>die Belege selbst</b>: jede Datei wandert genau
       einmal hinüber, erkannt an ihrer Prüfsumme. Beim nächsten Mal kommen nur die neuen
       dazu.</p>
    <div class="meldung" id="bkMeldung"></div>
    <form id="bkForm">
      ${passwortBlock(s)}
      <div class="field">
        <label for="bkRhythmus">Rhythmus</label>
        <select class="inp" id="bkRhythmus">
          <option value="" ${!s.rhythmus ? 'selected' : ''}>Aus — nur von Hand</option>
          <option value="taeglich" ${s.rhythmus === 'taeglich' ? 'selected' : ''}>Täglich (nachts, nur bei Änderung)</option>
          <option value="woechentlich" ${s.rhythmus === 'woechentlich' ? 'selected' : ''}>Wöchentlich (Sonntagnacht, nur bei Änderung)</option>
        </select>
      </div>
      <div class="field">
        <label for="bkZiel">Ablegen in</label>
        <select class="inp" id="bkZiel">
          <option value="" ${!s.ziel ? 'selected' : ''}>Kein Ziel — nur Herunterladen</option>
          <option value="nextcloud" ${s.ziel === 'nextcloud' ? 'selected' : ''}
            ${s.nextcloud_moeglich ? '' : 'disabled'}>Eigene Nextcloud (Home-Ordner/_Backups)</option>
          <option value="webdav" ${s.ziel === 'webdav' ? 'selected' : ''}>WebDAV-Speicher (z. B. Koofr, 10 GB gratis)</option>
        </select>
      </div>
      <div id="bkWebdav" ${s.ziel === 'webdav' ? '' : 'hidden'}>
        <p class="hinweis">Empfehlung: <b>Koofr</b> — 10 GB kostenlos, EU-Anbieter. Konto anlegen,
          dann unter Einstellungen → Passwort → „App-Passwort" eines erzeugen und hier
          eintragen. Die Adresse ist schon vorausgefüllt. Andere WebDAV-Speicher (kDrive,
          Hetzner, eine fremde Nextcloud) gehen genauso.</p>
        <div class="field">
          <label for="bkUrl">WebDAV-Adresse</label>
          <input class="inp" type="url" id="bkUrl" value="${esc(s.webdav_url || KOOFR_DAV)}"
            autocapitalize="off" spellcheck="false">
        </div>
        <div class="field">
          <label for="bkBenutzer">Benutzer (bei Koofr die E-Mail)</label>
          <input class="inp" type="text" id="bkBenutzer" value="${esc(s.webdav_benutzer)}"
            autocomplete="off" autocapitalize="off" spellcheck="false">
        </div>
        ${passwortFeld('bkDavPw', 'App-Passwort des Speichers',
          `autocomplete="off" value="${esc(s.webdav_passwort || '')}"`)}
      </div>
      ${passwortFeld('bkLogin', 'Zum Speichern: Passwort der Familie',
        'autocomplete="current-password" required')}
      <button type="submit" class="btn">Einstellungen speichern</button>
    </form>
    <h3 class="dt" style="font-size:14px;margin:18px 0 8px">Jetzt</h3>
    <div class="bk-knoepfe">
      <button type="button" class="btn" id="bkJetzt" ${s.hat_passwort && s.ziel ? '' : 'disabled'}>Jetzt sichern</button>
      <a class="btn" id="bkDownload" href="/api/backup/herunterladen" download
        ${s.hat_passwort ? '' : 'aria-disabled="true" style="pointer-events:none;opacity:.5"'}>Herunterladen</a>
      <button type="button" class="btn" id="bkEinspielen">Aus Datei einspielen</button>
      <button type="button" class="btn" id="bkAusSpeicher" ${s.ziel ? '' : 'disabled'}>Aus dem Speicher einspielen</button>
      <button type="button" class="btn" id="bkDateienZurueck" ${s.ziel ? '' : 'disabled'}>Belege zurückholen</button>
    </div>
    <h3 class="dt" style="font-size:14px;margin:0 0 8px">Bisherige Sicherungen</h3>
    ${listeHtml(s.backups)}
    ${instanzHtml(s.instanz)}`);

  augenBinden(dlg);
  const meldung = dlg.querySelector('#bkMeldung');
  const ziel = dlg.querySelector('#bkZiel');
  ziel.addEventListener('change', () => {
    dlg.querySelector('#bkWebdav').hidden = ziel.value !== 'webdav';
  });

  // Das Ersetzen des Backup-Passworts ist ein bewusster Schritt, kein
  // beiläufig leer gelassenes Feld — deshalb erst auf Knopfdruck.
  dlg.querySelector('#bkPwTauschen')?.addEventListener('click', e => {
    e.target.hidden = true;
    dlg.querySelector('#bkPwNeu').hidden = false;
    dlg.querySelector('#bkPw').focus();
  });

  dlg.querySelector('#bkForm').addEventListener('submit', async e => {
    e.preventDefault();
    meldungWeg(meldung);
    const pw = dlg.querySelector('#bkPw')?.value || '';
    const davPw = dlg.querySelector('#bkDavPw').value;
    try {
      const neu = await api('/backup/einstellungen', { method: 'PUT', body: {
        login_passwort: dlg.querySelector('#bkLogin').value,
        backup_passwort: pw || null,
        rhythmus: dlg.querySelector('#bkRhythmus').value,
        ziel: ziel.value,
        webdav_url: dlg.querySelector('#bkUrl').value,
        webdav_benutzer: dlg.querySelector('#bkBenutzer').value,
        webdav_passwort: davPw || null,
      } });
      dlg.close();
      melde('Backup-Einstellungen gespeichert', 'pos');
      diensteAuffrischen();
      backupDialog(neu);
    } catch (f) { feldmeldung(meldung, f.message || 'Speichern fehlgeschlagen'); }
  });

  dlg.querySelector('#bkJetzt').addEventListener('click', async () => {
    meldungWeg(meldung);
    const knopf = dlg.querySelector('#bkJetzt');
    knopf.disabled = true; knopf.textContent = 'Sichert …';
    try {
      const eintrag = await api('/backup/jetzt', { method: 'POST' });
      dlg.close();
      melde(`Gesichert: ${eintrag.dateiname} (${groesseText(eintrag.groesse)})`, 'pos');
      diensteAuffrischen();
      backupOeffnen();
    } catch (f) {
      feldmeldung(meldung, f.message || 'Sichern fehlgeschlagen');
      knopf.disabled = false; knopf.textContent = 'Jetzt sichern';
    }
  });

  dlg.querySelector('#bkEinspielen').addEventListener('click', () => {
    dlg.close();
    backupDatei.click();
  });

  /* N478 — nach dem Einspielen einer Sicherung stehen die Belegverweise da,
     die Dateien aber noch nicht. Der Knopf legt sie unter denselben Pfaden
     in der Nextcloud ab; was schon da ist, bleibt unangetastet. */
  dlg.querySelector('#bkDateienZurueck').addEventListener('click', async () => {
    dlg.close();
    const passwort = await passwortAbfrage('Belege zurückholen',
      'Holt die gesicherten Belege aus dem Speicher und legt sie wieder in der '
      + 'Nextcloud ab — unter denselben Pfaden, damit die Verknüpfungen greifen. '
      + 'Vorhandene Dateien werden nicht überschrieben.',
      { text: 'Zurückholen' });
    if (passwort === null) return;
    try {
      const st = await api('/backup/dateien-zurueckholen', { method: 'POST',
        body: { pfad: '', passwort } });
      melde(`${st.zurueck} von ${st.geprueft} Belegen zurückgeholt`
        + (st.fehlt ? ` · ${st.fehlt} nicht im Speicher` : ''), 'pos');
    } catch (f) { melde(f.message || 'Zurückholen fehlgeschlagen', 'neg'); }
  });

  dlg.querySelector('#bkAusSpeicher').addEventListener('click', async () => {
    dlg.close();
    let dateien = [];
    try { dateien = await api('/backup/im-speicher'); }
    catch (f) { melde(f.message || 'Speicher nicht erreichbar', 'neg'); return; }
    if (!dateien.length) { melde('Im Speicher liegt noch keine Sicherung', 'neg'); return; }
    einspielenDialog('Aus dem Speicher einspielen', dateien.map(d =>
      ({ wert: d.pfad, text: `${d.dateiname} · ${groesseText(d.groesse)}` })),
      async (pfad, passwort) => api('/backup/aus-speicher',
        { method: 'POST', body: { pfad, passwort } }));
  });
}

/* Einspielen — aus Datei oder aus dem Speicher — braucht nur das
   Backup-Passwort. Geht nur in eine leere Familie, der Server prüft das. */
function einspielenDialog(titel, auswahl, ausfuehren) {
  const dlg = baueDialog(`
    <div class="dt">${titel}</div>
    <p>Nur in eine leere Familie: bestehende Immobilien werden nie überschrieben.</p>
    <form id="bkEinForm">
      <div class="meldung" id="bkEinMeldung"></div>
      ${auswahl ? `
      <div class="field">
        <label for="bkEinWahl">Sicherung</label>
        <select class="inp" id="bkEinWahl">
          ${auswahl.map(a => `<option value="${esc(a.wert)}">${esc(a.text)}</option>`).join('')}
        </select>
      </div>` : ''}
      ${passwortFeld('bkEinPw', 'Backup-Passwort dieser Sicherung',
        'autocomplete="off" required autofocus')}
      <button type="submit" class="btn">Einspielen</button>
    </form>`);
  augenBinden(dlg);
  const meldung = dlg.querySelector('#bkEinMeldung');
  dlg.querySelector('#bkEinForm').addEventListener('submit', async e => {
    e.preventDefault();
    meldungWeg(meldung);
    const wahl = dlg.querySelector('#bkEinWahl');
    try {
      const ergebnis = await ausfuehren(wahl ? wahl.value : null,
                                        dlg.querySelector('#bkEinPw').value);
      dlg.close();
      melde(`Eingespielt: ${(ergebnis.objekte || []).length} Immobilie(n)`, 'pos');
      setTimeout(() => { location.href = 'index.html'; }, 900);
    } catch (f) { feldmeldung(meldung, f.message || 'Einspielen fehlgeschlagen'); }
  });
}

/* Öffnet den Dialog — der Kachel-Knopf landet hier. */
export async function backupOeffnen() {
  try {
    backupDialog(await api('/backup/einstellungen'));
  } catch (f) {
    melde(f.message || 'Backup-Stand nicht abrufbar', 'neg');
  }
}

/* Bindet die Dateiauswahl fürs Einspielen. Aufruf einmal beim Laden. */
export function backupInit() {
  backupDatei = document.getElementById('backupDatei');
  backupDatei.addEventListener('change', () => {
    const datei = backupDatei.files && backupDatei.files[0];
    backupDatei.value = '';
    if (!datei) return;
    einspielenDialog(`Einspielen: ${datei.name}`, null, (_wahl, passwort) => {
      const form = new FormData();
      form.append('passwort', passwort);
      form.append('datei', datei);
      return apiForm('/backup/einspielen', form);
    });
  });
}
