/* N216 — Dokumentenablage / Nextcloud-Status. Zeigt je nach Zustand einen
   Hinweis (Nextcloud nicht verbunden, kein Home-Ordner, Ordner anlegen) oder
   nach dem Anlegen den Baum. Fehlt ein Unterordner, wird er still
   nachgezogen. */

import { api, esc } from '../immo.js';
import { slug } from '../objekt-state.js?v=2';
import { baumZeigen } from '../objekt-baum.js?v=2';

/* N321 — dieselbe Wolken-Silhouette für beide Zustände: ladend (mit ruhig
   pulsierendem Punkt, animiert per `.sym.laedt` in objekt.html) und
   gescheitert (mit Ausrufezeichen statt Punkt) — im Stil einer Nextcloud-
   Dateiablage, nicht im generischen Sechseck-„⬡" von vorher. */
export const WOLKE_LADE_SVG = `<svg viewBox="0 0 24 24" width="22" height="22"
  fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"
  stroke-linejoin="round" aria-hidden="true">
  <path d="M7.5 17.5a4 4 0 0 1-.5-7.96A5 5 0 0 1 16.4 8.2 4.4 4.4 0 0 1
           17.5 17.5H7.5Z"/>
  <circle class="wlk-funke" cx="12" cy="13" r="1.1" fill="currentColor" stroke="none"/>
</svg>`;

export const WOLKE_FEHLER_SVG = `<svg viewBox="0 0 24 24" width="22" height="22"
  fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"
  stroke-linejoin="round" aria-hidden="true">
  <path d="M7.5 17.5a4 4 0 0 1-.5-7.96A5 5 0 0 1 16.4 8.2 4.4 4.4 0 0 1
           17.5 17.5H7.5Z"/>
  <path d="M12 10.8v3" stroke-width="1.9"/>
  <circle cx="12" cy="15.3" r="0.9" fill="currentColor" stroke="none"/>
</svg>`;

/* Die Ordnerstruktur lässt sich jederzeit nachträglich anlegen — auch wenn
   das Objekt längst existiert und Nextcloud erst später verbunden wurde. */
export async function cloudZeigen() {
  const ziel = document.getElementById('cloudbereich');
  if (!ziel) return;
  let s;
  try {
    s = await api(`/nextcloud/objekte/${encodeURIComponent(slug)}/status`);
  } catch (fehler) {
    // Frueher verschwand der ganze Block hier kommentarlos — dann sah es aus,
    // als gaebe es die Dokumentenablage gar nicht.
    ziel.innerHTML = `<div class="cloudbox"><div class="zeile">
        <span class="sym fehler">${WOLKE_FEHLER_SVG}</span>
        <span class="txt">
          <span class="t">Ablage gerade nicht erreichbar</span>
          <span class="d">${esc(String(fehler.message || fehler))}</span>
        </span></div>
        <div class="tat nebensache"><button data-cloud="status">Nochmal prüfen</button></div>
      </div>`;
    return;
  }

  if (s.angelegt) {
    // CCCXVI — schlank: nur „Ordner verknüpft", darunter die Filter und die
    // Dateiübersicht. Fehlende Unterordner legt ImmoCalc still selbst an; die
    // Ordner-Chipliste und der Knopf sind weg (wenig gewinnbringend).
    // CCCXXXI — der verknüpfte Pfad steht klein/kursiv direkt unter dem
    // Dokumentenablage-Header; die frühere „Ordner verknüpft"-Box entfällt.
    const pfadEl = document.getElementById('ablagePfad');
    if (pfadEl) pfadEl.textContent = s.ordner || '';
    ziel.innerHTML = `<div id="dokbaum"></div>`;
    // Fehlt ein Unterordner der Vorlage, wird er im Hintergrund angelegt —
    // ohne Knopf. Erst prüfen (fehlend?), dann nur bei Bedarf anlegen.
    ordnerAutoAnlegen();
    baumZeigen();
    return;
  }

  if (!s.cloud_verbunden) {
    ziel.innerHTML = `<div class="cloudbox"><div class="zeile">
        <span class="sym offen">⬡</span>
        <span class="txt">
          <span class="t">Nextcloud ist noch nicht verbunden</span>
          <span class="d">Das Objekt ist gespeichert. Sobald du die Verbindung
            einrichtest, kannst du die Ordnerstruktur hier nachträglich anlegen.</span>
        </span></div>
        <div class="tat"><a href="settings.html">Verbindung einrichten</a></div>
      </div>`;
    return;
  }

  if (!s.home) {
    ziel.innerHTML = `<div class="cloudbox"><div class="zeile">
        <span class="sym offen">▣</span>
        <span class="txt">
          <span class="t">Kein Home-Ordner gewählt</span>
          <span class="d">Wähle den Ordner, unter dem die Immobilien liegen.</span>
        </span></div>
        <div class="tat"><a href="settings.html">Home-Ordner wählen</a></div>
      </div>`;
    return;
  }

  ziel.innerHTML = `<div class="cloudbox"><div class="zeile">
      <span class="sym offen">＋</span>
      <span class="txt">
        <span class="t">Ordnerstruktur noch nicht angelegt</span>
        <span class="d">Wird angelegt unter <b>${esc(s.vorschlag)}</b> —
          vorhandene Ordner und Dateien bleiben unberührt.</span>
      </span></div>
      <div class="tat"><button data-cloud="struktur">Ordnerstruktur anlegen</button></div>
    </div>`;
}

/* CCCXVI — fehlt ein Unterordner der Vorlage, legt ImmoCalc ihn still an
   (kein Knopf). Nur wenn wirklich etwas fehlt, geht eine Anfrage raus; danach
   frischt sich der Baum auf, damit neue Ordner sofort sichtbar sind. */
async function ordnerAutoAnlegen() {
  try {
    const s = await api(`/nextcloud/objekte/${encodeURIComponent(slug)}/ordner`);
    if ((s.fehlend || []).length) {
      await api(`/nextcloud/objekte/${encodeURIComponent(slug)}/struktur`,
                { method: 'POST' });
      baumZeigen();
    }
  } catch { /* Ordner nicht lesbar — der Baum zeigt trotzdem, was da ist */ }
}
