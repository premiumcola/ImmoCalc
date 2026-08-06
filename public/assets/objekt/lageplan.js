/* N216 — Lagepläne einer Einheit: höhenbegrenzte Vorschau als Kachel, kleine
   „✎"- und „×"-Aktionen oben rechts, Upload über ein verstecktes File-Feld.
   Fotos gehen durch dieselbe Aufbereitung wie Belege (kamerascan). Kamera-
   Rohdaten aus dem Objekt-Ordner gehen an die Nextcloud, die Datei bleibt
   auch beim „×" bestehen — hier verschwindet nur der Eintrag. */

import { api, melde, esc, frage, belegAnsehen } from '../immo.js';
import { RUBRIKFARBE } from './state.js';
import { sekopfHtml } from '../objekt-format.js?v=2';
import { kamerascanStarten } from '../kamerascan.js';

/* Der Anzeigename eines Plans, aufgeräumt für die Beschriftung: ohne Endung und
   ohne die Ablage-Vorsilben (ohne-Jahr_, Jahr_, Lageplan …). Frisch umbenannt
   ist er schon kurz („1.OG"); bei Alt-Uploads bleibt wenigstens der Kern übrig. */
export function planLabel(p) {
  return ((p.dateiname || 'Lageplan')
    .replace(/\.[a-z0-9]+$/i, '')
    .replace(/^ohne-jahr[ _-]+/i, '')
    .replace(/^(?:19|20)\d{2}[ _-]+/, '')
    .replace(/^lageplan[ _-]*/i, '')
    .trim()) || 'Lageplan';
}

/* Ein Plan als Karte: höhenbegrenzte Vorschau mit dem Namen sanft überlagert,
   dazu die zwei leisen Aktionen (umbenennen ✎, entfernen ×) oben rechts. Jeder
   Plan bekommt seine eigene Vorschau — so lassen sich 1.OG, DG … auseinander
   halten (CCCLXXXV). */
export function lageplanKarte(p, e) {
  const label = planLabel(p);
  return `<div class="lp-karte" data-lp-karte="${p.id}">
      <button class="lp-vorschau klick" data-lageplan="${p.id}"
        aria-label="Lageplan „${esc(label)}“ ansehen">
        <img data-lp-bild="${p.id}" alt="">
        <span class="lp-name">${esc(label)}</span>
      </button>
      <span class="lp-akte">
        <button class="lp-akt" data-lageplan-rename="${p.id}" data-e="${e.id}"
          data-name="${esc(label)}" title="Umbenennen"
          aria-label="Lageplan umbenennen">✎</button>
        <button class="lp-akt lp-weg" data-lageplan-weg="${p.id}" data-e="${e.id}"
          title="Entfernen" aria-label="Lageplan entfernen">×</button>
      </span>
    </div>`;
}

export function lageplanHtml(e) {
  const plaene = e.lageplaene || [];
  // N4 — Kopf über den gemeinsamen sekopfHtml-Helfer (bündig + gleiche
  // Icon-Ausrichtung/-Farbe wie die anderen Rubriken, kein Sonderweg mehr).
  const add = `<label class="seakt" title="Lageplan aufnehmen oder hochladen"
        aria-label="Lageplan aufnehmen oder hochladen">Hinzufügen
        <input type="file" accept="image/*,application/pdf" capture="environment"
               data-lageplan-neu="${e.id}" hidden></label>`;
  const kopf = sekopfHtml('Lageplan', 'Grundstück', add, RUBRIKFARBE.grundstueck);
  // N4 — Pläne als kompakte Elemente im Seitenverhältnis nebeneinander (Flex),
  // nicht als ganzseitige Kästen untereinander.
  const inhalt = plaene.length
    ? `<div class="lp-liste">${plaene.map(p => lageplanKarte(p, e)).join('')}</div>`
    : `<div class="liste"><div class="leerzeile">Noch kein Lageplan hinterlegt</div></div>`;
  return `${kopf}${inhalt}`;
}

/* Die Inline-Vorschau des ersten Plans: das Bild über denselben Weg holen, über
   den ein Lageplan angesehen wird (serverseitig gerendert, auch für PDF), als
   Object-URL setzen. Alte URLs werden beim erneuten Rendern freigegeben. */
let lageplanVorschauUrls = [];

export function lageplanVorschauAufraeumen() {
  lageplanVorschauUrls.forEach(u => URL.revokeObjectURL(u));
  lageplanVorschauUrls = [];
}

export async function lageplanVorschauFuellen(root) {
  const bilder = [...root.querySelectorAll('[data-lp-bild]')];
  await Promise.all(bilder.map(async bild => {
    try {
      const antwort = await fetch(`/api/dokumente/${bild.dataset.lpBild}/vorschau?seite=0`);
      if (!antwort.ok) throw new Error(String(antwort.status));
      const adr = URL.createObjectURL(await antwort.blob());
      lageplanVorschauUrls.push(adr);
      bild.src = adr;
    } catch {
      // Ohne Cloud-Anbindung (oder wenn sich der Plan nicht rendern lässt) bleibt
      // die Karte stehen — nur das Bild wird eingeklappt, Name und Aktionen
      // (umbenennen/entfernen) bleiben erreichbar.
      bild.closest('.lp-karte')?.classList.add('lp-ohne-bild');
    }
  }));
}

/* CCCLXXXI — kleiner Umbenennen-Dialog: nur der Anzeigename. Die Datei in der
   Nextcloud wird nicht berührt (das erledigt der Endpunkt), hier wird bloss der
   Name erfragt. Im Stil des Zuordnen-Dialogs, damit nichts Neues nötig ist. */
export function lageplanUmbenennen(einheitId, id, name, laden) {
  const dlg = document.createElement('dialog');
  dlg.className = 'immo-dlg zuord-dlg';
  document.body.appendChild(dlg);
  dlg.addEventListener('close', () => dlg.remove());
  dlg.innerHTML = `
    <div class="zd-kopf">
      <span class="zd-t">Lageplan umbenennen</span>
      <button class="zd-x" data-nein aria-label="Schließen">×</button>
    </div>
    <div class="zd-block">
      <span class="zd-l">Anzeigename</span>
      <input class="lp-eingabe" type="text" value="${esc(name || '')}"
             maxlength="120" aria-label="Anzeigename des Lageplans">
      <span class="zd-hint">Nur die Bezeichnung in der App ändert sich — die
        Datei in der Nextcloud bleibt, wo sie liegt.</span>
    </div>
    <div class="zd-fuss">
      <button class="zd-ab" data-nein>Abbrechen</button>
      <button class="zd-ok" data-ja>Speichern</button>
    </div>`;
  const feld = dlg.querySelector('.lp-eingabe');
  const speichern = async () => {
    const wert = feld.value.trim();
    if (!wert) return feld.focus();
    dlg.close();
    try {
      await api(`/einheiten/${einheitId}/lageplan/${id}`,
                { method: 'PATCH', body: { name: wert } });
    } catch (fehler) {
      return melde(String(fehler.message || 'Umbenennen ging nicht.'), 'neg');
    }
    return laden();
  };
  dlg.addEventListener('click', e => {
    if (e.target.closest('[data-nein]')) return dlg.close();
    if (e.target.closest('[data-ja]')) return speichern();
  });
  feld.addEventListener('keydown', e => { if (e.key === 'Enter') speichern(); });
  dlg.showModal();
  feld.focus();
  feld.select();
}

/* N9 — beim Anlegen direkt einen Zusatztitel (z. B. „Bad", „DG") vergeben; er
   fließt in Datei- und Anzeigenamen. Liefert den Titel (auch leer „") oder
   null (abgebrochen). */
export function lageplanTitelAbfragen() {
  return new Promise(fertig => {
    const dlg = document.createElement('dialog');
    dlg.className = 'immo-dlg zuord-dlg';
    document.body.appendChild(dlg);
    let ok = false;
    dlg.addEventListener('close', () => { dlg.remove(); if (!ok) fertig(null); });
    dlg.innerHTML = `
      <div class="zd-kopf">
        <span class="zd-t">Lageplan hinzufügen</span>
        <button class="zd-x" data-nein aria-label="Schließen">×</button>
      </div>
      <div class="zd-block">
        <span class="zd-l">Zusatztitel (optional)</span>
        <input class="lp-eingabe" type="text" placeholder="z. B. Bad, DG, Grundriss …"
               maxlength="80" aria-label="Zusatztitel des Lageplans">
        <span class="zd-hint">Kommt in den Datei- und Anzeigenamen. Leer lassen ist ok.</span>
      </div>
      <div class="zd-fuss">
        <button class="zd-ab" data-nein>Abbrechen</button>
        <button class="zd-ok" data-ja>Hochladen</button>
      </div>`;
    const feld = dlg.querySelector('.lp-eingabe');
    const weiter = () => { ok = true; const w = feld.value.trim(); dlg.close(); fertig(w); };
    dlg.addEventListener('click', e => {
      if (e.target.closest('[data-nein]')) return dlg.close();
      if (e.target.closest('[data-ja]')) return weiter();
    });
    feld.addEventListener('keydown', e => { if (e.key === 'Enter') weiter(); });
    dlg.showModal();
    feld.focus();
  });
}

/* CCCXXVI / CCCLXIX — ein aufgenommener oder gewählter Lageplan wird abgelegt.
   Ein Foto läuft durch dieselbe Aufbereitung wie die Belege (kamerascan:
   Kanten erkennen, drehen, zuschneiden, klein als PDF); ein bereits fertiges
   PDF geht unverändert durch. Das Ergebnis wandert als multipart (Feld „datei")
   an den Lageplan-Endpunkt. Danach neu laden, damit der frische Plan — mitsamt
   Inline-Vorschau — in der Liste steht. Fehler dezent über melde. */
export async function lageplanHochladen(feld, laden) {
  if (!feld || !feld.files || !feld.files.length) return;
  const dateien = [...feld.files];
  feld.value = '';        // damit dieselbe Datei danach erneut wählbar bleibt

  const bilder = dateien.filter(d => (d.type || '').startsWith('image/'));
  const pdf = dateien.find(d => (d.type || '') === 'application/pdf');
  let datei, name;
  if (bilder.length) {
    let ergebnis;
    try {
      ergebnis = await kamerascanStarten(bilder, { titel: 'Lageplan' });
    } catch (fehler) {
      return melde(String(fehler.message
        || 'Der Lageplan konnte nicht aufbereitet werden.'), 'neg');
    }
    if (!ergebnis) return;            // Zuschnitt abgebrochen
    datei = ergebnis.pdf; name = 'lageplan.pdf';
  } else if (pdf) {
    datei = pdf; name = pdf.name;
  } else {
    return;
  }

  // N9 — Zusatztitel direkt beim Erstellen erfragen; fließt in den Dateinamen.
  const tag = await lageplanTitelAbfragen();
  if (tag === null) return;               // abgebrochen
  const fd = new FormData();
  fd.append('datei', datei, name);
  if (tag) fd.append('bezeichnung', tag);
  melde('Lageplan wird hochgeladen …');
  try {
    const antwort = await fetch(
      `/api/einheiten/${feld.dataset.lageplanNeu}/lageplan`,
      { method: 'POST', body: fd });
    if (!antwort.ok) {
      const grund = await antwort.json().then(k => k.detail).catch(() => null);
      throw new Error(grund || `${antwort.status}`);
    }
  } catch (fehler) {
    return melde(String(fehler.message
      || 'Lageplan konnte nicht hochgeladen werden.'), 'neg');
  }
  melde('Lageplan gespeichert.', 'pos');
  return laden();
}

/* Kleiner Handler für „Lageplan entfernen" — der Klick-Delegator ruft ihn auf. */
export async function lageplanEntfernen(einheitId, planId, laden) {
  const ja = await frage('Lageplan entfernen?',
    'Der Eintrag wird aus der App genommen. Die Datei in der Nextcloud '
    + 'bleibt unberührt — dort wird nichts gelöscht.',
    { knopf: 'Entfernen', gefahr: true });
  if (!ja) return;
  try {
    await api(`/einheiten/${einheitId}/lageplan/${planId}`, { method: 'DELETE' });
  } catch (fehler) {
    return melde(String(fehler.message || 'Konnte nicht entfernt werden.'), 'neg');
  }
  return laden();
}

/* Einen hinterlegten Lageplan als Bild-Vorschau öffnen (dieselbe Ansicht wie
   ein Beleg, über den Dokument-Inhalt). */
export function lageplanAnsehen(planId) {
  belegAnsehen(`/api/dokumente/${planId}/inhalt`, 'Lageplan');
}
