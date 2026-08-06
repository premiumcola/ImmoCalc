/* N216 — Live-Verknuepfungen (N133): eine Kachel je angebundenem System.
   Drei Zustaende — verbunden (gruen), noch nicht eingerichtet (ruhig grau,
   ausdruecklich kein Fehler) und gestoert (rot). Jede Kachel fragt fuer sich
   und nebenlaeufig; eine tote Verbindung haelt die anderen nicht auf.

   Der ganze Block war frueher inline in settings.html — Verhalten unveraendert. */
import { api, esc } from '../immo.js';
import { VSYMBOLE, vHole, vHoleGeteilt, vGeteiltReset,
         vKurz, vModell } from './state.js';

async function vNextcloud() {
  const a = await vHole('/nextcloud/status');
  if (a.fehler) return { stand: 'weg', text: a.fehler };
  if (!a.da || !a.daten.eingerichtet)
    return { stand: 'aus', text: 'noch nicht eingerichtet' };
  if (!a.daten.home) return { stand: 'aus', text: 'Home-Ordner fehlt noch' };
  return { stand: 'gut', text: `${a.daten.benutzer} · ${vKurz(a.daten.url)}` };
}

/* N138 — die Adresse der Wallbox im Heimnetz. Nur Hostname oder IP (der Server
   ergaenzt Schema und Pfad selbst). Leer eingeben loest die Verbindung wieder. */
async function wallboxEinrichten() {
  let jetzt = '';
  try {
    const a = await vHole('/openwb/status');
    jetzt = a.daten?.url || '';
  } catch { /* noch nicht eingerichtet */ }
  const eingabe = prompt(
    'Adresse der openWB im Heimnetz (Hostname oder IP, z. B. 192.168.178.61).\n'
    + 'Leer lassen entfernt die Verbindung.', jetzt);
  if (eingabe === null) return;
  try {
    await api('/openwb/adresse', { method: 'POST', body: { url: eingabe.trim() } });
    vAlleLaden();
  } catch (fehler) {
    alert('Konnte nicht gespeichert werden: ' + (fehler.message || fehler));
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

/* `zeile` fuehrt zu den Feldern weiter unten auf dieser Seite, `seite` zu der
   Seite, auf der die Verknuepfung eingerichtet und genutzt wird. */
const VERKNUEPFUNGEN = [
  { id: 'nextcloud', name: 'Nextcloud', ikon: 'wolke', zeile: 'ncRow',
    was: 'Belege und Unterlagen liegen in deiner eigenen Cloud.',
    pruefe: vNextcloud },
  // N138 — die Wallbox wird HIER eingerichtet. Der Verweis auf die Tankstellen-
  // seite lief ins Leere: dort gibt es (noch) kein Adressfeld, die Kachel war
  // damit nicht einzurichten.
  { id: 'wallbox', name: 'openWB-Wallbox', ikon: 'wallbox',
    tun: wallboxEinrichten,
    was: 'Ladeprotokoll des E-Autos — je Ladung Netz, Speicher und PV.',
    pruefe: vWallbox },
  { id: 'solaredge', name: 'SolarEdge', ikon: 'solar', zeile: 'kiRow',
    was: 'Liest die Verbrauchsaufteilung aus dem Screenshot ab.',
    pruefe: vSolaredge },
  { id: 'ki', name: 'Belegerkennung', ikon: 'funke', zeile: 'kiRow',
    was: 'Holt Datum, Betrag und Kostenart aus hochgeladenen Belegen.',
    pruefe: vKi },
  { id: 'mail', name: 'Mailversand', ikon: 'brief', zeile: 'mailRow',
    was: 'Verschickt Abrechnungen über dein eigenes Postfach.',
    pruefe: vMail },
];

let vGitter, vPruef;

function vZeige(id, ergebnis) {
  document.getElementById(`vk-${id}`).className = 'vk ' + ergebnis.stand;
  document.getElementById(`vs-${id}`).textContent = ergebnis.text;
}

function vAlleLaden() {
  vGeteiltReset();
  vPruef.classList.add('laeuft');
  const laeufe = VERKNUEPFUNGEN.map(v => {
    document.getElementById(`vk-${v.id}`).className = 'vk laedt';
    document.getElementById(`vs-${v.id}`).textContent = 'wird geprüft …';
    // Jede Kachel fuer sich: eine langsame Verbindung haelt keine andere auf.
    return v.pruefe().then(e => vZeige(v.id, e));
  });
  Promise.allSettled(laeufe).then(() => vPruef.classList.remove('laeuft'));
}

/* Von der Kachel zu den Feldern: hinrollen und die Zeile kurz aufblinken
   lassen, damit klar ist, welche gemeint war. */
function klickHandler(e) {
  const tun = e.target.closest('[data-tun]');
  if (tun) {
    const v = VERKNUEPFUNGEN.find(x => x.id === tun.dataset.tun);
    if (v?.tun) { e.preventDefault(); return v.tun(); }
  }
  const kachel = e.target.closest('[data-zeile]');
  if (!kachel) return;
  const zeile = document.getElementById(kachel.dataset.zeile);
  if (!zeile) return;
  zeile.scrollIntoView({ behavior: 'smooth', block: 'center' });
  zeile.classList.remove('gezeigt');
  void zeile.offsetWidth;          // erzwingt den Neustart der Animation
  zeile.classList.add('gezeigt');
  setTimeout(() => zeile.classList.remove('gezeigt'), 3200);
}

/* Baut die Kachel-Reihe, verdrahtet den „Erneut pruefen"-Knopf und startet
   den ersten Statusabruf. Aufruf einmal beim Laden der Seite. */
export function verknuepfungenInit() {
  vGitter = document.getElementById('vGitter');
  vPruef = document.getElementById('vPruef');

  vGitter.innerHTML = VERKNUEPFUNGEN.map(v => {
    const inhalt = `<span class="vk-kopf">
          <span class="vk-ic"><svg viewBox="0 0 24 24" aria-hidden="true">${
            VSYMBOLE[v.ikon]}</svg></span>
          <span class="vk-punkt" aria-hidden="true"></span>
        </span>
        <span class="vk-name">${esc(v.name)}</span>
        <span class="vk-was">${esc(v.was)}</span>
        <span class="vk-stand" id="vs-${v.id}">wird geprüft …</span>`;
    if (v.seite)
      return `<a class="vk laedt" id="vk-${v.id}" href="${v.seite}">${inhalt}</a>`;
    // N138 — `tun` richtet die Verknuepfung an Ort und Stelle ein, statt auf eine
    // Seite zu verweisen, die das Feld gar nicht hat.
    return `<button class="vk laedt" id="vk-${v.id}"${v.tun
      ? ` data-tun="${v.id}"` : ` data-zeile="${v.zeile}"`}>${inhalt}</button>`;
  }).join('');

  vPruef.addEventListener('click', vAlleLaden);
  vGitter.addEventListener('click', klickHandler);

  vAlleLaden();
}
