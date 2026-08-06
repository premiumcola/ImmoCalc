/* N216 — Unterordner je Dokumentart (GET/POST /api/nextcloud/unterordner).

   CXCI: dieselbe Mechanik wie die Objektordner-Vorlage, eine Ebene tiefer.
   Eine Vorlage je Art, Platzhalter, Beispiel — damit in „60_Nebenkosten"
   nicht alles flach nebeneinander liegt. Verhaltensgleich zum bisherigen
   Inline-Skript in settings.html. */
import { api, esc } from '../immo.js';
import { melde, meldungWeg } from './state.js';

let unterordnerDlg, unterordnerMeldung, unterordnerFelder;
let unterordnerStand = { jahr: new Date().getFullYear(), einheit: '' };

/* Dieselbe Rechnung wie `bezeichnung.unterordner_name` — nur zum Ansehen
   beim Tippen. Gespeichert wird immer, was der Server daraus macht. */
function unterordnerName(vorlage, art) {
  return (vorlage || '')
    .replace(/\{jahr\}|%jahr/gi, String(unterordnerStand.jahr))
    .replace(/\{einheit\}|%einheit/gi, unterordnerStand.einheit || '')
    .replace(/\{art\}|%art/gi, art)
    .replace(/[<>:"/\\|?*]/g, ' ')
    .replace(/\s{2,}/g, ' ')
    .replace(/^[\s\-_.·]+|[\s\-_.·]+$/g, '');
}

function unterordnerVorschau(karte) {
  const feld = karte.querySelector('input');
  const schau = karte.querySelector('.uovorschau');
  const name = unterordnerName(feld.value, feld.dataset.art);
  schau.textContent = name
    ? `▸ ${feld.dataset.ordner}/${name}`
    : `▸ ${feld.dataset.ordner} — ohne Unterordner`;
  schau.classList.toggle('flach', !name);
}

function unterordnerZeigen(stand) {
  unterordnerStand = stand;
  document.getElementById('unterordnerVerboten').textContent =
    `Nicht erlaubt: ${stand.verboten}`;
  unterordnerFelder.innerHTML = stand.arten.map(a => `
    <div class="uokarte">
      <div class="uokopf">
        <span class="uoart">${esc(a.art)}</span>
        <span class="uoordner">${esc(a.ordner)}</span>
      </div>
      <input class="inp" data-art="${esc(a.art)}" data-ordner="${esc(a.ordner)}"
             value="${esc(a.vorlage)}" placeholder="ohne Unterordner"
             aria-label="Vorlage für ${esc(a.art)}">
      <span class="uovorschau"></span>
    </div>`).join('');
  unterordnerFelder.querySelectorAll('.uokarte').forEach(unterordnerVorschau);
  const nk = stand.arten.find(a => a.art === 'Nebenkosten');
  document.getElementById('unterordnerStatus').textContent = nk
    ? (nk.beispiel ? `Nebenkosten → ${nk.beispiel}` : 'ohne Unterordner')
    : 'Standard';
}

export async function unterordnerLaden() {
  try {
    unterordnerZeigen(await api('/nextcloud/unterordner'));
  } catch {
    document.getElementById('unterordnerStatus').textContent = 'Standard';
  }
}

/* Bindet Zeile, Live-Vorschau und Speichern. Aufruf einmal beim Laden. */
export function unterordnerInit() {
  unterordnerDlg = document.getElementById('unterordnerDlg');
  unterordnerMeldung = document.getElementById('unterordnerMeldung');
  unterordnerFelder = document.getElementById('unterordnerFelder');

  unterordnerFelder.addEventListener('input', e => {
    const karte = e.target.closest('.uokarte');
    if (karte) unterordnerVorschau(karte);
  });

  document.getElementById('unterordnerRow').addEventListener('click', () => {
    meldungWeg(unterordnerMeldung);
    unterordnerDlg.showModal();
  });

  document.getElementById('unterordnerSpeichern').addEventListener('click', async () => {
    meldungWeg(unterordnerMeldung);
    const vorlagen = {};
    unterordnerFelder.querySelectorAll('input').forEach(f => {
      vorlagen[f.dataset.art] = f.value;
    });
    try {
      const antwort = await api('/nextcloud/unterordner',
                                { method: 'POST', body: { vorlagen } });
      unterordnerZeigen(antwort);
      melde(unterordnerMeldung, antwort.hinweise?.length
        ? antwort.hinweise.join(' ')
        : 'Übernommen. Bereits abgelegte Belege bleiben liegen — die neue '
          + 'Ordnung gilt für alles, was ab jetzt hereinkommt.',
        !antwort.hinweise?.length);
    } catch (fehler) {
      melde(unterordnerMeldung, String(fehler.message || fehler));
    }
  });
}
