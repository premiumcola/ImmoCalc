/* N216 / N479 — die Dienst-Kacheln der Einstellungen.

   Seit N479 sind sie nicht mehr eine Übersicht ÜBER die Zeilen darunter,
   sondern der Weg selbst: eine Kachel je Dienst, ein Knopf, der direkt in
   dessen Einstellungen führt. Vorher gab es beides — eine Kachel, die zur
   Zeile rollte, und die Zeile, die den Dialog öffnete. Zwei Knöpfe für
   dieselbe Sache.

   Drei Zustände — verbunden (grün), noch nicht eingerichtet (ruhig grau,
   ausdrücklich kein Fehler) und gestört (rot). Jede Kachel fragt für sich und
   nebenläufig; eine tote Verbindung hält die anderen nicht auf. */
import { api, esc, baueDialog, frage, melde } from '../immo.js';
import { VSYMBOLE } from './symbole.js';
import { vHole, vHoleGeteilt, vGeteiltReset, vKurz, vModell } from './state.js';
import { nextcloudOeffnen } from './nextcloud.js';
import { kiOeffnen } from './ki.js';
import { mailOeffnen } from './mail.js';
import { druckerOeffnen, druckerStand } from './drucker.js';
import { backupOeffnen, backupStand } from './backup.js';

async function vNextcloud() {
  const a = await vHole('/nextcloud/status');
  if (a.fehler) return { stand: 'weg', text: a.fehler };
  if (!a.da || !a.daten.eingerichtet)
    return { stand: 'aus', text: 'noch nicht eingerichtet' };
  if (!a.daten.home) return { stand: 'warte', text: 'Home-Ordner fehlt noch' };
  return { stand: 'gut', text: `${a.daten.benutzer} · ${vKurz(a.daten.url)}` };
}

/* N288 — die Adresse im Design der App abfragen. Frueher stand hier ein
   nacktes `prompt()`: der graue Systemkasten des Browsers, der mit der Seite
   nichts zu tun hat und sich auf dem Telefon nicht bedienen laesst wie der
   Rest. Liefert den getippten Text oder `null` beim Abbrechen. */
function adresseFragen(jetzt) {
  return new Promise(fertig => {
    const dlg = baueDialog(`
      <div class="dt">openWB-Wallbox</div>
      <form novalidate>
        <div class="field">
          <label for="wbUrl">Adresse im Heimnetz</label>
          <input class="inp" id="wbUrl" maxlength="120" autocomplete="off"
                 placeholder="192.168.178.61" value="${esc(jetzt)}">
        </div>
        <p class="hinweis">
          Hostname oder IP genügt — Schema und Pfad ergänzt der Server selbst.
          Leer lassen entfernt die Verbindung.</p>
        <button class="btn" type="submit">Übernehmen</button>
        <button class="btn leise" type="button" data-nein
                style="margin-top:8px">Abbrechen</button>
      </form>`);
    const form = dlg.querySelector('form');
    form.addEventListener('submit', e => {
      e.preventDefault();
      fertig(form.querySelector('#wbUrl').value.trim());
      dlg.close();
    });
    form.querySelector('[data-nein]')
        .addEventListener('click', () => { fertig(null); dlg.close(); });
    dlg.addEventListener('cancel', () => fertig(null));
    setTimeout(() => form.querySelector('#wbUrl')?.focus(), 30);
  });
}

/* N138 — die Adresse der Wallbox im Heimnetz. Nur Hostname oder IP (der Server
   ergaenzt Schema und Pfad selbst). Leer eingeben loest die Verbindung wieder. */
async function wallboxEinrichten() {
  let jetzt = '';
  try {
    const a = await vHole('/openwb/status');
    jetzt = a.daten?.url || '';
  } catch { /* noch nicht eingerichtet */ }
  const eingabe = await adresseFragen(jetzt);
  if (eingabe === null) return;
  // Leeres Feld bei bestehender Verbindung heisst: Verbindung entfernen. Das
  // ist ein Loeschen — also nachfragen, und dabei sagen, was verschwindet.
  if (!eingabe && jetzt) {
    const ok = await frage('Verbindung zur Wallbox entfernen',
      `Die openWB unter „${jetzt}" wird nicht mehr abgefragt. `
      + 'Bereits gespeicherte Ladungen bleiben erhalten.',
      { knopf: 'Entfernen', gefahr: true });
    if (!ok) return;
  }
  try {
    await api('/openwb/adresse', { method: 'POST', body: { url: eingabe } });
    vAlleLaden();
  } catch (fehler) {
    melde('Konnte nicht gespeichert werden: '
      + (fehler.message || fehler), 'neg');
  }
}

async function vWallbox() {
  const a = await vHole('/openwb/status');
  if (a.fehler) return { stand: 'weg', text: a.fehler };
  if (!a.da || !a.daten.eingerichtet)
    return { stand: 'aus', text: 'noch nicht eingerichtet' };
  if (!a.daten.erreichbar) return { stand: 'weg', text: 'Box antwortet nicht' };
  return { stand: 'gut', text: vKurz(a.daten.url) };
}

async function vSolaredge() {
  const a = await vHoleGeteilt('/ki/status');
  if (a.fehler) return { stand: 'weg', text: a.fehler };
  if (!a.da || !a.daten.eingerichtet)
    return { stand: 'aus', text: 'braucht den KI-Schlüssel' };
  if (a.daten.erreichbar === false)
    return { stand: 'weg', text: 'Bildauslese nicht erreichbar' };
  return { stand: 'gut', text: 'Screenshot-Auslese bereit' };
}

async function vKi() {
  const a = await vHoleGeteilt('/ki/status');
  if (a.fehler) return { stand: 'weg', text: a.fehler };
  if (!a.da || !a.daten.eingerichtet)
    return { stand: 'aus', text: 'kein Schlüssel hinterlegt' };
  if (a.daten.erreichbar === false)
    return { stand: 'weg', text: a.daten.fehler || 'nicht erreichbar' };
  return { stand: 'gut', text: vModell(a.daten.modell) || 'erreichbar' };
}

async function vMail() {
  const a = await vHole('/mail/status');
  if (a.fehler) return { stand: 'weg', text: a.fehler };
  if (!a.da || !a.daten.verbunden)
    return { stand: 'aus', text: 'noch kein Postfach' };
  return { stand: 'gut', text: a.daten.absender || vKurz(a.daten.server) };
}

/* Die Kacheln stehen in der Reihenfolge, in der sie im Alltag gebraucht
   werden: erst wohin die Belege gehen, dann was sie liest, dann was sie
   verschickt und druckt, dann die Sicherung. Die zwei Energie-Kacheln
   stehen am Ende — sie gehören zu einem anderen Teil der App. */
const VERKNUEPFUNGEN = [
  { id: 'nextcloud', name: 'Nextcloud', ikon: 'wolke', tun: nextcloudOeffnen,
    was: 'Belege und Unterlagen liegen in deiner eigenen Cloud.',
    pruefe: vNextcloud },
  { id: 'ki', name: 'Belegerkennung', ikon: 'beleg', tun: kiOeffnen,
    was: 'Holt Datum, Betrag und Kostenart aus hochgeladenen Belegen.',
    pruefe: vKi },
  { id: 'mail', name: 'Mailversand', ikon: 'brief', tun: mailOeffnen,
    was: 'Verschickt Abrechnungen über dein eigenes Postfach.',
    pruefe: vMail },
  // N479 — Drucker war bisher nur eine Zeile weiter unten. Den Stand liefert
  // das Drucker-Modul selbst: es kennt den Unterschied zwischen eigenen
  // Geräten und einem Druckdienst, und es hält dabei seine Liste aktuell.
  { id: 'drucker', name: 'Drucker', ikon: 'drucker', tun: druckerOeffnen,
    was: 'Druckt Abrechnungen direkt auf ein Gerät im Haus.',
    pruefe: druckerStand },
  { id: 'backup', name: 'Sicherung', ikon: 'tresor', tun: backupOeffnen,
    was: 'Verschlüsselte Kopie aller Daten und Belege, jede Nacht.',
    pruefe: backupStand },
  { id: 'solaredge', name: 'SolarEdge', ikon: 'solar', tun: kiOeffnen,
    was: 'Liest die Verbrauchsaufteilung aus dem Screenshot ab.',
    pruefe: vSolaredge },
  // N138 — die Wallbox wird HIER eingerichtet. Der Verweis auf die Tankstellen-
  // seite lief ins Leere: dort gibt es (noch) kein Adressfeld, die Kachel war
  // damit nicht einzurichten.
  { id: 'wallbox', name: 'openWB-Wallbox', ikon: 'wallbox',
    tun: wallboxEinrichten,
    was: 'Ladeprotokoll des E-Autos — je Ladung Netz, Speicher und PV.',
    pruefe: vWallbox },
];

let vGitter, vPruef;

function vZeige(id, ergebnis) {
  document.getElementById(`vk-${id}`).className = 'vk ' + ergebnis.stand;
  document.getElementById(`vs-${id}`).textContent = ergebnis.text;
}

/* Alle Kacheln neu befragen. Wird auch von aussen gebraucht: wer eine
   Verbindung frisch eingerichtet hat, will sie sofort grün sehen. */
export function vAlleLaden() {
  vGeteiltReset();
  vPruef.classList.add('laeuft');
  const laeufe = VERKNUEPFUNGEN.map(v => {
    document.getElementById(`vk-${v.id}`).className = 'vk laedt';
    document.getElementById(`vs-${v.id}`).textContent = 'wird geprüft …';
    // Jede Kachel fuer sich: eine langsame Verbindung haelt keine andere auf.
    return v.pruefe().then(e => vZeige(v.id, e))
      .catch(() => vZeige(v.id, { stand: 'weg', text: 'nicht abrufbar' }));
  });
  Promise.allSettled(laeufe).then(() => vPruef.classList.remove('laeuft'));
}

/* Baut die Kachel-Reihe, verdrahtet den „Erneut pruefen"-Knopf und startet
   den ersten Statusabruf. Aufruf einmal beim Laden der Seite. */
export function verknuepfungenInit() {
  vGitter = document.getElementById('vGitter');
  vPruef = document.getElementById('vPruef');

  vGitter.innerHTML = VERKNUEPFUNGEN.map(v => `
    <button class="vk laedt" id="vk-${v.id}" data-tun="${v.id}">
      <span class="vk-kopf">
        <span class="vk-ic"><svg viewBox="0 0 24 24" aria-hidden="true">${
          VSYMBOLE[v.ikon]}</svg></span>
        <span class="vk-punkt" aria-hidden="true"></span>
      </span>
      <span class="vk-name">${esc(v.name)}</span>
      <span class="vk-was">${esc(v.was)}</span>
      <span class="vk-stand" id="vs-${v.id}">wird geprüft …</span>
    </button>`).join('');

  vPruef.addEventListener('click', vAlleLaden);
  vGitter.addEventListener('click', e => {
    const kachel = e.target.closest('[data-tun]');
    if (!kachel) return;
    VERKNUEPFUNGEN.find(v => v.id === kachel.dataset.tun)?.tun();
  });

  vAlleLaden();
}
