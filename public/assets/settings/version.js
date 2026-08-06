/* N216 — Version + die letzten fünf Änderungen.

   Bevorzugt `version.json` (vom Auto-Updater bei JEDEM neuen Stand geschrieben,
   auch reinen Frontend-Deploys — zeigt den echten Live-Stand mit Commit-Zeit
   und Release-Notes). Fällt sie aus, wird der gebackene Build aus der API
   gezogen. Verhaltensgleich zum bisherigen Inline-Skript in settings.html. */
import { api } from '../immo.js';
import { ortszeit } from './state.js';

// Die letzten fünf Änderungen als einzelne Zeilen (textContent → keine
// Interpretation von Sonderzeichen aus den Commit-Titeln).
function zeigeNotizen(rnotes, notes) {
  if (!Array.isArray(notes) || !notes.length) return;
  rnotes.textContent = '';
  const titel = document.createElement('span');
  titel.className = 'rn-titel';
  titel.textContent = 'Zuletzt geändert';
  rnotes.appendChild(titel);
  for (const n of notes.slice(0, 5)) {
    const z = document.createElement('span');
    z.className = 'rn-zeile';
    z.textContent = n;
    rnotes.appendChild(z);
  }
  rnotes.hidden = false;
}

/* Zeigt Version + Kopfzeile („API verbunden") und ggf. die Release-Notes.
   Läuft einmal beim Laden — async, weil es die Version aus version.json oder
   /health zieht. */
export async function versionZeigen() {
  const build = document.getElementById('build');
  const rnotes = document.getElementById('rnotes');
  const sub = document.getElementById('sub');

  try {
    const v = await fetch('/version.json', { cache: 'no-store' })
      .then(r => (r.ok ? r.json() : null)).catch(() => null);
    if (v && v.sha) {
      const wann = ortszeit(v.zeit);
      build.textContent = `ImmoCalc · ${v.sha}` + (wann ? ` · ${wann} Uhr` : '');
      zeigeNotizen(rnotes, v.notes);
      sub.textContent = 'API verbunden';
    } else {
      const g = await api('/health');
      const wann = ortszeit(g.build_zeit);
      build.textContent =
        `ImmoCalc ${g.version ?? '–'} · Build ${g.build ?? 'unbekannt'}`
        + (wann ? ` · ${wann} Uhr` : '');
      sub.textContent = 'API verbunden';
    }
  } catch {
    build.textContent = 'API nicht erreichbar';
    sub.textContent = 'API nicht erreichbar';
  }
}
