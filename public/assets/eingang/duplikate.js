/* N301 — Duplikat-Assistent: gleiche Dateien nebeneinander, eine bleibt.

   Der Wachdienst nimmt auf, was in der Ablage liegt — und dieselbe Rechnung
   liegt dort schon mal zweimal: einmal aus dem Mailanhang, einmal
   abfotografiert. Gleicher SHA-1, gleiche Groesse, zwei Eintraege.

   Dieser Abschnitt haengt als Aufklapper unter der Dokumentenverwaltung
   (bewusst KEIN eigener Menuepunkt — die Leiste ist voll genug). Zugeklappt
   ist er eine Zeile und faellt nicht auf, solange nichts zu tun ist.
   Geladen wird erst beim Aufklappen: der Abruf geht ueber die ganze Ablage
   und soll nicht bei jedem Seitenaufruf mitlaufen.

   Entschieden wird je Gruppe: eine Kopie behalten, die uebrigen entfernen.
   Damit die Entscheidung tragfaehig ist, steht auf jeder Karte, was der
   Nutzer dafuer braucht — voller Pfad, Immobilie, Kostenart, Betrag, Datum
   und vor allem: woran der Beleg haengt. Ein Beleg ohne jede Verknuepfung
   ist der unverfaenglichste Kandidat zum Wegwerfen; das sagt die Karte
   selbst (gruene Marke). Vorausgewaehlt ist deshalb umgekehrt die Kopie mit
   den MEISTEN Verknuepfungen — sie muss am wenigsten umgehaengt werden. */

import { api, esc, eur, frage, melde } from '../immo.js';
import { tagText } from './helpers.js';

const box = document.getElementById('dupe');
const zahlEl = document.getElementById('dupeZahl');
const inhalt = document.getElementById('dupeInhalt');

/* Der Abruf laeuft genau einmal — beim ersten Aufklappen. */
let geladen = false;
let laufend = false;
let gruppen = [];

/* ---- Kleine Formatierer -------------------------------------------------- */

/** Dateigroesse in der Einheit, die man noch lesen mag. */
const groesseText = wert => {
  const z = Number(wert) || 0;
  if (z < 1024) return `${z} B`;
  if (z < 1048576) {
    return `${(z / 1024).toLocaleString('de-DE', { maximumFractionDigits: 0 })} kB`;
  }
  return `${(z / 1048576).toLocaleString('de-DE', { maximumFractionDigits: 1 })} MB`;
};

/* Der Pfad ist lang und darf die Seite nie waagerecht scrollen lassen. Er
   bricht deshalb an den Schraegstrichen (<wbr>); `overflow-wrap:anywhere` im
   Stylesheet faengt zusaetzlich einzelne ueberlange Namensteile ab. */
const pfadHtml = pfad => esc(pfad).replace(/\//g, '/<wbr>');

/** Die kleinen Marken einer Kopie — jede Angabe genau einmal. */
function chipsHtml(k) {
  const chips = [];
  const objekt = k.objekt_name || k.objekt;
  if (objekt) chips.push(`<span class="chip">${esc(objekt)}</span>`);
  const sache = [k.kategorie, k.kostenart].filter(Boolean).join(' · ');
  if (sache) chips.push(`<span class="chip">${esc(sache)}</span>`);
  if (k.betrag != null) chips.push(`<span class="chip geld">${esc(eur(k.betrag))}</span>`);
  const wann = k.belegdatum ? tagText(k.belegdatum) : (k.jahr ? String(k.jahr) : '');
  if (wann) chips.push(`<span class="chip">${esc(wann)}</span>`);
  if (k.status && k.status !== 'zugeordnet') {
    chips.push(`<span class="chip offen">${esc(k.status)}</span>`);
  }
  return chips.length ? `<div class="chips">${chips.join('')}</div>` : '';
}

/** Woran haengt die Datei? Das ist die eigentliche Entscheidungsgrundlage. */
function verknuepfungHtml(k) {
  const links = k.verknuepfungen || [];
  if (!links.length) {
    return '<span class="dfrei">✓ nichts hängt daran</span>';
  }
  const zeilen = links.map(v => `<li>${esc(v.text || v.typ || '')}</li>`).join('');
  return `<div class="dlink">
      <span class="dlt">hängt an ${links.length} ${links.length === 1
        ? 'Stelle' : 'Stellen'}</span>
      <ul>${zeilen}</ul>
    </div>`;
}

/* ---- Eine Gruppe zeichnen ------------------------------------------------ */

/** Die Kopie, die am meisten haelt — sie ist der sinnvollste Vorschlag. */
function vorschlag(kopien) {
  let beste = kopien[0];
  for (const k of kopien) {
    const a = (k.verknuepfungen || []).length;
    const b = (beste.verknuepfungen || []).length;
    if (a > b || (a === b && k.id < beste.id)) beste = k;
  }
  return beste;
}

function kopieHtml(k, name, gewaehlt) {
  return `<label class="dkopie${k.id === gewaehlt ? ' an' : ''}">
      <span class="dkw">
        <input type="radio" name="${esc(name)}" value="${k.id}"
               ${k.id === gewaehlt ? 'checked' : ''}
               aria-label="${esc(k.dateiname)} behalten">
        <span class="dn">${esc(k.dateiname)}</span>
      </span>
      <span class="dpfad" title="${esc(k.pfad)}">${pfadHtml(k.pfad)}</span>
      ${chipsHtml(k)}
      ${verknuepfungHtml(k)}
    </label>`;
}

function gruppeHtml(g, i) {
  const name = `dupe-${i}`;
  const gewaehlt = vorschlag(g.kopien).id;
  const weg = g.kopien.length - 1;
  const kurz = String(g.sha1 || '').slice(0, 10);
  return `<article class="dgruppe" data-i="${i}">
      <div class="dgkopf">
        <span class="dgt">${g.anzahl}× dieselbe Datei</span>
        <span class="dgm">${esc(groesseText(g.groesse))} · ${esc(kurz)}</span>
      </div>
      <div class="dkopien">
        ${g.kopien.map(k => kopieHtml(k, name, gewaehlt)).join('')}
      </div>
      <div class="dfuss">
        <label class="dopt">
          <input type="checkbox" class="dloe" checked>
          Dateien in der Cloud mitlöschen
        </label>
        <button class="dtat" type="button">Diese behalten ·
          ${weg === 1 ? 'die andere' : `${weg} andere`} entfernen</button>
      </div>
    </article>`;
}

/* ---- Zeichnen und zaehlen ------------------------------------------------ */

function zahlZeigen() {
  if (!geladen) { zahlEl.hidden = true; return; }
  const n = gruppen.length;
  zahlEl.hidden = false;
  zahlEl.textContent = n ? `${n} ${n === 1 ? 'Gruppe' : 'Gruppen'}` : 'keine';
  zahlEl.classList.toggle('an', n > 0);
}

function zeichne() {
  zahlZeigen();
  inhalt.innerHTML = gruppen.length
    ? gruppen.map(gruppeHtml).join('')
    : `<span class="dleer">Keine doppelten Dateien — jede Datei liegt genau
         einmal in der Ablage.</span>`;
}

/* ---- Laden: erst beim Aufklappen ---------------------------------------- */

async function laden() {
  if (laufend) return;
  laufend = true;
  inhalt.innerHTML = '<span class="dwarte">Die Ablage wird auf gleiche '
    + 'Dateien geprüft …</span>';
  try {
    const antwort = await api('/dokumente/duplikate');
    gruppen = (antwort && antwort.gruppen) || [];
    geladen = true;
    zeichne();
  } catch (fehler) {
    /* Solange der Endpunkt noch fehlt, bleibt der Abschnitt still: er
       verschwindet, statt ein Fehlerbanner aufzuspannen (roter Faden 7). */
    const text = String((fehler && fehler.message) || fehler);
    if (/not found|404/i.test(text)) box.hidden = true;
    else {
      inhalt.innerHTML = '<span class="dwarte">Die Prüfung ist gerade nicht '
        + 'möglich.</span>';
    }
  } finally {
    laufend = false;
  }
}

/* ---- Zusammenfuehren: erst fragen, dann tun ----------------------------- */

async function zusammenfuehren(artikel) {
  const g = gruppen[Number(artikel.dataset.i)];
  const gewaehlt = artikel.querySelector('input[type=radio]:checked');
  if (!g || !gewaehlt) return;
  const behaltenId = Number(gewaehlt.value);
  const behalten = g.kopien.find(k => k.id === behaltenId);
  const weg = g.kopien.filter(k => k.id !== behaltenId);
  const dateiLoeschen = artikel.querySelector('.dloe').checked;
  const knopf = artikel.querySelector('.dtat');

  const namen = weg.map(k => k.dateiname).join(' · ');
  const ok = await frage(
    `${weg.length} ${weg.length === 1 ? 'Kopie' : 'Kopien'} entfernen?`,
    `Es verschwindet: ${namen}. Behalten wird „${behalten.dateiname}". `
    + (dateiLoeschen
      ? 'Die Dateien werden auch in der Cloud gelöscht.'
      : 'Die Dateien bleiben in der Cloud liegen, nur die Einträge gehen weg.'),
    { knopf: `${weg.length} entfernen`, gefahr: true });
  if (!ok) return;

  knopf.disabled = true;
  const vorher = knopf.textContent;
  knopf.textContent = 'Wird zusammengeführt …';
  try {
    const antwort = await api(`/dokumente/${behaltenId}/zusammenfuehren`, {
      method: 'POST',
      body: { weg_ids: weg.map(k => k.id), datei_loeschen: dateiLoeschen },
    });
    gruppen = gruppen.filter(x => x !== g);
    zeichne();
    const teile = [`✓ ${behalten.dateiname} behalten`];
    if (antwort.verweise_umgehaengt) {
      teile.push(`${antwort.verweise_umgehaengt} ${antwort.verweise_umgehaengt === 1
        ? 'Verweis' : 'Verweise'} umgehängt`);
    }
    if (antwort.eintraege_entfernt) teile.push(`${antwort.eintraege_entfernt} entfernt`);
    if (antwort.dateien_geloescht) {
      teile.push(`${antwort.dateien_geloescht} Datei${antwort.dateien_geloescht === 1
        ? '' : 'en'} gelöscht`);
    }
    const fehler = antwort.fehler || [];
    melde(teile.join(' · ') + (fehler.length ? ` · ${fehler[0]}` : ''),
          fehler.length ? '' : 'pos');
  } catch (fehler) {
    knopf.disabled = false;
    knopf.textContent = vorher;
    melde('⚠ ' + String((fehler && fehler.message) || fehler), 'neg');
  }
}

/* ---- Verdrahtung --------------------------------------------------------- */

if (box && zahlEl && inhalt) {
  box.addEventListener('toggle', () => {
    if (box.open && !geladen) laden();
  });

  /* Die gewaehlte Karte hebt sich ab — ein Radio allein sieht man auf einer
     breiten Karte kaum. */
  inhalt.addEventListener('change', e => {
    const radio = e.target.closest('input[type=radio]');
    if (!radio) return;
    const gruppe = radio.closest('.dgruppe');
    gruppe.querySelectorAll('.dkopie').forEach(karte => {
      karte.classList.toggle('an', karte.contains(radio));
    });
  });

  inhalt.addEventListener('click', e => {
    const knopf = e.target.closest('.dtat');
    if (knopf) zusammenfuehren(knopf.closest('.dgruppe'));
  });
}
