/* N216 — Benennung nachziehen (GET/POST /api/nextcloud/umzug).

   Ändert sich die Vorlage, heißen die bestehenden Ordner weiter wie früher.
   Hier steht der Weg, sie nachzuziehen: erst der Trockenlauf, dann eine
   ausdrückliche Rückfrage, dann das Ergebnis — samt dem, was misslang.
   Verhaltensgleich zum bisherigen Inline-Skript in settings.html. */
import { api, esc, frage } from '../immo.js';
import { belegText, feldmeldung, meldungWeg } from './state.js';

let umzugDlg, umzugMeldung, umzugPlan, umzugStart, umzugStatus;
let trockenlauf = null;

function schrittHtml(s) {
  return `<div class="uschritt">
      <div class="uk">
        <span class="uname">${esc(s.name)}</span>
        <span class="uart ${s.art === 'entschachteln' ? 'tief' : ''}">${
          esc(s.art)}</span>
      </div>
      <div class="upfad alt">${esc(s.von)}</div>
      <div class="upfad neu">↳ ${esc(s.nach)}</div>
      ${s.dokumente.length ? `<span class="ufuss">${
        belegText(s.dokumente.length)} ziehen mit</span>` : ''}
      ${s.art === 'entschachteln'
        ? `<span class="ufuss">${esc(s.hinweis)}</span>` : ''}
    </div>`;
}

/* Ordner ohne Immobilie und Immobilien ohne Ordner: beides bleibt, wie es
   ist — genannt wird es trotzdem, sonst sucht man später danach. */
function randnotizen(p) {
  const teile = [];
  if (p.verwaist?.length) {
    teile.push(`<div class="ulabel">Gehört zu keiner Immobilie</div>
      <div class="uruhig">
        ${p.verwaist.map(o => `<div class="upfad alt">${esc(o)}</div>`).join('')}
        <span class="ufuss">Bleibt unangetastet — ImmoCalc fasst nur die
          Ordner seiner Immobilien an.</span>
      </div>`);
  }
  if (p.ohne_ordner?.length) {
    teile.push(`<div class="ulabel">Noch ohne Ordner</div>
      <div class="uruhig">
        <div class="upfad alt">${p.ohne_ordner.map(o => esc(o.name)).join(' · ')}</div>
        <span class="ufuss">Diese Immobilien bekommen ihren Ordner beim
          nächsten Anlegen auf der Objektseite.</span>
      </div>`);
  }
  return teile.join('');
}

function planZeigen() {
  if (!trockenlauf) return;
  const kopf = trockenlauf.schritte.length
    ? `<div class="ulabel">${trockenlauf.schritte.length} ${trockenlauf.schritte.length === 1
        ? 'Ordner weicht ab' : 'Ordner weichen ab'} · ${
        belegText(trockenlauf.dokumente)}</div>`
    : `<div class="uruhig"><span class="ufuss" style="margin-top:0">Alles schon
         richtig benannt — die Ordner in der Nextcloud tragen bereits die
         Namen aus der aktuellen Vorlage.</span></div>`;
  umzugPlan.innerHTML = `<div class="uliste">${kopf}
    ${trockenlauf.schritte.map(schrittHtml).join('')}${randnotizen(trockenlauf)}</div>`;
  umzugStart.style.display = trockenlauf.schritte.length ? 'block' : 'none';
  umzugStart.disabled = false;
  umzugStart.textContent = 'Ordner nachziehen';
  if (trockenlauf.hinweise?.length) feldmeldung(umzugMeldung, trockenlauf.hinweise.join(' '));
}

/** Trockenlauf holen und die Zeile beschriften. `grund` bleibt gesetzt, wenn
    es noch nichts zu prüfen gibt — ohne Home-Ordner ist das der Normalfall. */
export async function umzugLaden() {
  let grund = '';
  try {
    trockenlauf = await api('/nextcloud/umzug');
    // Ohne verbundene Cloud antwortet der Trockenlauf ruhig mit `moeglich:
    // false` statt mit einem Fehler — dann gibt es nichts zu zeigen.
    if (trockenlauf && trockenlauf.moeglich === false) {
      grund = trockenlauf.grund || 'nicht prüfbar';
      trockenlauf = null;
    }
  } catch (fehler) {
    trockenlauf = null;
    grund = String(fehler.message || fehler).replace(/^\d+\s*/, '')
      || 'nicht prüfbar';
  }
  umzugStatus.textContent = !trockenlauf ? grund : trockenlauf.schritte.length
    ? `${trockenlauf.schritte.length} ${trockenlauf.schritte.length === 1 ? 'Ordner weicht'
        : 'Ordner weichen'} von der Vorlage ab`
    : 'alles schon richtig benannt';
  document.getElementById('umzugIkon').className =
    'ic' + (!trockenlauf ? '' : trockenlauf.schritte.length ? ' warte' : ' aktiv');
}

/* Was der Umzug wirklich getan hat — und was nicht. Fehler stehen oben und
   in Rot: ein übersprungener Ordner ist die eine Sache, die man sehen muss. */
function ergebnisZeigen(a, namen) {
  const fehler = a.fehler?.length
    ? `<div class="ulabel">Nicht verschoben</div>` + a.fehler.map(f =>
        `<div class="uschritt">
           <div class="uk"><span class="uname">${
             esc(namen.get(f.objekt) || f.objekt)}</span>
             <span class="uart schlecht">Fehler</span></div>
           <div class="upfad alt">${esc(f.von)}</div>
           <span class="ufuss">${esc(f.fehler)}</span>
         </div>`).join('')
    : '';
  const geschafft = a.verschoben.map(v => `<div class="uschritt">
      <div class="uk"><span class="uname">${esc(v.name)}</span>
        <span class="uart">${esc(v.art)}</span></div>
      <div class="upfad alt">${esc(v.von)}</div>
      <div class="upfad neu">↳ ${esc(v.nach)}</div>
      ${v.dokumente ? `<span class="ufuss">${belegText(v.dokumente)}
        mitgezogen</span>` : ''}
      ${v.geblieben?.length ? `<span class="ufuss">Liegen geblieben, weil am
        Ziel schon vorhanden: ${v.geblieben.map(esc).join(', ')}</span>` : ''}
    </div>`).join('');
  umzugPlan.innerHTML = `<div class="uliste">${fehler}
    ${geschafft ? `<div class="ulabel">Nachgezogen</div>${geschafft}` : ''}
    ${randnotizen(a)}</div>`;
}

/* Bindet Zeile und Start-Knopf. Aufruf einmal beim Laden; der eigentliche
   Trockenlauf laeuft ueber `umzugLaden`. */
export function umzugInit() {
  umzugDlg = document.getElementById('umzugDlg');
  umzugMeldung = document.getElementById('umzugMeldung');
  umzugPlan = document.getElementById('umzugPlan');
  umzugStart = document.getElementById('umzugStart');
  umzugStatus = document.getElementById('umzugStatus');

  document.getElementById('umzugRow').addEventListener('click', async () => {
    meldungWeg(umzugMeldung);
    umzugPlan.innerHTML = '';
    umzugStart.style.display = 'none';
    umzugDlg.showModal();
    await umzugLaden();
    if (trockenlauf) planZeigen();
    else umzugPlan.innerHTML = `<div class="uruhig"><span class="ufuss"
        style="margin-top:0">Erst Nextcloud verbinden und einen Home-Ordner
        wählen — vorher gibt es nichts nachzuziehen.</span></div>`;
  });

  umzugStart.addEventListener('click', async () => {
    if (!trockenlauf?.schritte.length) return;
    const ja = await frage('Ordner jetzt nachziehen?',
      `${trockenlauf.schritte.length} Ordner werden in der Nextcloud verschoben, `
      + `${belegText(trockenlauf.dokumente)} ziehen mit. Gelöscht oder überschrieben `
      + 'wird dabei nichts.', { knopf: 'Nachziehen' });
    if (!ja) return;

    // Die Antwort nennt bei einem Fehler nur den Kürzel des Objekts; der
    // Klarname steht im Plan, den wir gerade noch in Händen halten.
    const namen = new Map(trockenlauf.schritte.map(s => [s.objekt, s.name]));
    meldungWeg(umzugMeldung);
    umzugStart.disabled = true;
    umzugStart.textContent = 'Ziehe nach …';
    try {
      const a = await api('/nextcloud/umzug', { method: 'POST' });
      umzugStart.style.display = 'none';
      ergebnisZeigen(a, namen);
      feldmeldung(umzugMeldung, a.fehler.length
        ? `${a.anzahl} von ${a.anzahl + a.fehler.length} Ordnern nachgezogen — `
          + `${a.fehler.length} blieben stehen.`
        : `${a.anzahl} Ordner nachgezogen · ${belegText(a.dokumente)} umgehängt.`,
        !a.fehler.length);
      // Die Zeile im Hintergrund erzählt danach den neuen Stand; das Ergebnis
      // bleibt im Dialog stehen, bis er geschlossen wird.
      await umzugLaden();
    } catch (fehler) {
      umzugStart.disabled = false;
      umzugStart.textContent = 'Ordner nachziehen';
      feldmeldung(umzugMeldung, String(fehler.message || fehler));
    }
  });
}
