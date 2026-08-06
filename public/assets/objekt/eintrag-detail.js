/* N216 — Eintrags-Detailansicht (CCCXIII): Daten links, Beleg rechts.

   Klick auf einen Eintrag (z. B. Grundsteuer) öffnet nicht direkt das
   Bearbeiten-Formular, sondern eine geteilte Ansicht wie im Dokumentenmodus:
   links Felder + Belege (Hauptbeleg + eingerückt die Info-Belege), rechts das
   PDF. Ein Beleg antippen tauscht die Vorschau, „Bearbeiten" führt ins
   bewährte Formular. Auf dem Telefon stapelt sich alles. */

import { esc, api, installHilfe, melde, wahl, belegSeitenLaden } from '../immo.js';
import { kostenIcon } from '../kostenicons.js';
import { cfgFuer, felderFuer, endpunktBereich } from '../objekt-felder.js?v=2';
import { feldWertText } from '../objekt-format.js?v=2';
import { HAKEN_ICON, BELEG_ICON } from '../objekt-baum.js?v=2';
import { slug } from '../objekt-state.js?v=2';
import { belegScannen } from '../belegscan.js';
import { AN_TYP, RUBRIKFARBE, SCAN_KATEGORIE, SCAN_TYPEN, SCAN_WORT,
         UMKLASS_ZIELE, KAMERA_ICON, kannUmklassifizieren } from './state.js';
import { scanJahr } from './helpers.js';
import { formular, feldLabel } from './formular.js';
import { mietExtra } from './miete-extras.js';
import { kreditExtra } from './kredit-extras.js';

/* Das bewährte Bearbeiten-Formular — aus der Detailansicht heraus erreichbar
   und weiterhin der direkte Weg für Rubriken ohne Belegbezug. */
export function oeffneEintragFormular(bereich, eintrag, beleg = null) {
  const extra = bereich === 'mieten' ? mietExtra(eintrag)
              : bereich === 'kredite' ? kreditExtra(eintrag) : '';
  const cfg = cfgFuer(bereich);
  // CCCXXIII — hat der Eintrag einen Beleg, steht er beim Bearbeiten daneben.
  const dok = beleg && beleg.id ? beleg
    : (eintrag.quelle_dokument_id
        ? { id: eintrag.quelle_dokument_id, dateiname: eintrag.beleg_dateiname }
        : null);
  return formular({ titel: `${cfg.einzahl} bearbeiten`,
                    felder: felderFuer(bereich, eintrag), bereich,
                    werte: eintrag, absicht: 'eintrag', extra, beleg: dok });
}

export async function eintragDetail(bereich, id, laden) {
  const cfg = cfgFuer(bereich);
  const typ = AN_TYP[bereich];
  let eintrag;
  try {
    eintrag = (await api(`/objekte/${encodeURIComponent(slug)}/${endpunktBereich(bereich)}`))
      .find(x => String(x.id) === String(id));
  } catch { eintrag = null; }
  if (!eintrag) return;

  // Belege des Eintrags (nur für Typen, die das Backend kennt). Fällt der
  // Endpunkt aus (z. B. API noch nicht neu gebaut), bleibt wenigstens der
  // Quell-Beleg des Eintrags — sein `quelle_dokument_id` liegt schon vor.
  let belege = { haupt: null, unter: [] };
  if (typ) {
    try {
      belege = await api(`/dokumente/objekt/${encodeURIComponent(slug)}/eintrag/${typ}/${id}/belege`);
    } catch {
      if (eintrag.quelle_dokument_id) {
        belege = { haupt: { id: eintrag.quelle_dokument_id,
          dateiname: eintrag.beleg_dateiname || 'Beleg', jahr: eintrag.jahr },
          unter: [] };
      }
    }
  }
  const alle = [belege.haupt, ...(belege.unter || [])].filter(Boolean);

  // Felder als ruhige Zusammenfassung — dieselbe Beschreibung wie das Formular.
  const felder = felderFuer(bereich, eintrag).filter(f => !f.hilfe && f.typ !== 'block');
  const datenHtml = felder.map(f => {
    const t = feldWertText(f, eintrag[f.k]);
    return `<div class="dd-zeile"><span class="dd-l">${feldLabel(f)}</span>
      <span class="dd-v">${esc(t)}</span></div>`;
  }).join('');

  const belegItem = (d, unter) => `<button class="dd-beleg${unter ? ' unter' : ''}"
      data-doc="${d.id}" data-name="${esc(d.dateiname)}">
      <span class="dd-bi">${unter ? BELEG_ICON : HAKEN_ICON}</span>
      <span class="dd-bn">${esc(d.dateiname)}</span>
      ${d.jahr ? `<span class="dd-bj">${d.jahr}</span>` : ''}</button>`;
  // CCCLXVII — den Beleg gleich hier abfotografieren. Fehlt er, steht der Weg
  // als Knopf unter dem Hinweis; ist schon einer da, bleibt nur eine leise
  // Zeile für den nächsten. Nur für Rubriken, die das Backend als Ziel kennt.
  const scanWort = SCAN_WORT[bereich] || 'Beleg';
  // CCCLXXXIX — beim Mietverhältnis sind es Dokumente (Mietvertrag, Übergaben,
  // Kaution), keine „Belege".
  const dokLabel = bereich === 'mieten' ? 'Zugehörige Dokumente' : 'Belege';
  const typen = SCAN_TYPEN[bereich];
  // Welcher Belegtyp abfotografiert wird — bei mehreren Typen setzt ihn der Klick.
  let gewaehltWort = typen ? typen[0][0] : scanWort;
  const scanFeldHtml = `<input type="file" accept="image/*,application/pdf"
       capture="environment" multiple hidden data-scanfeld>`;
  const scanText = alle.length ? `Weiteren ${scanWort} abfotografieren`
                               : `${scanWort} abfotografieren`;
  const scanKnopf = (voll, kurz, leise) => `<button type="button" data-scan
       data-wort="${esc(voll)}" class="dd-scan${leise ? ' leise' : ''}"
       ><span class="dd-si">${KAMERA_ICON}</span
       ><span class="dd-st">${esc(kurz)}</span></button>`;
  const scanHtml = !typ ? ''
    : typen
      ? `<div class="dd-scanwahl"><span class="dd-scanlabel">Abfotografieren</span>${
          typen.map(([voll, kurz]) => scanKnopf(voll, kurz, true)).join('')
        }</div>${scanFeldHtml}`
      : scanKnopf(scanWort, scanText, alle.length) + scanFeldHtml;
  // CCCLXXXIX — beim Mietverhältnis eine Checkliste je Dokumentart in logischer
  // Reihenfolge: grüner Haken + Name (antippen zeigt es, „Ersetzen" tauscht) wo
  // vorhanden, sonst „fehlt" mit Aufnehmen-Knopf. So bleibt es EIN Dokument je Art.
  const mietChecklistHtml = () => {
    // Trennzeichen-blind vergleichen: der Dateiname trägt „Übergabeprotokoll
    // Einzug" als „…Miete-Übergabeprotokoll-Einzug" (Leerzeichen → Bindestrich,
    // vorangestelltes Kürzel), der Wahlname hat Leerzeichen. Ohne das Entfernen
    // aller Nicht-Buchstaben fiele jedes Übergabeprotokoll auf „Mietvertrag"
    // zurück und verschwände aus seiner Zeile.
    const norm = s => (s || '').toLowerCase().replace(/[^0-9a-zäöüß]+/g, '');
    // N223 — eine Zeile erkennt zusätzlich zu ihrem eigenen Namen auch die in
    // `auchErkennenAs` genannten Alternativnamen (z. B. Lohnsteuerbescheinigung
    // zählt als Mieterselbstauskunft) — EIN Dokument, EINE Zeile, kein Doppel.
    const passt = (d, voll, auch) => {
      const n = norm(d.dateiname);
      return n.includes(norm(voll)) || (auch || []).some(a => n.includes(norm(a)));
    };
    // Unerkanntes (z. B. Alt-„Miete") gilt als Mietvertrag (das Hauptdokument).
    const typVon = d =>
      (typen.find(([voll, , auch]) => passt(d, voll, auch)) || [])[0] || 'Mietvertrag';
    return `<div class="dd-checkliste">${typen.map(([voll, kurz]) => {
      const da = alle.find(d => typVon(d) === voll);
      return da
        ? `<div class="dd-check da">
             <span class="dd-ci ok">${HAKEN_ICON}</span>
             <button class="dd-cn" data-doc="${da.id}" data-name="${esc(da.dateiname)}"
               >${esc(kurz)}${da.jahr ? `<span class="dd-cj">${da.jahr}</span>` : ''}</button>
             <button class="dd-cx" data-scan data-wort="${esc(voll)}"
               title="${esc(kurz)} ersetzen" aria-label="${esc(kurz)} ersetzen">Ersetzen</button>
           </div>`
        : `<div class="dd-check fehlt">
             <span class="dd-ci"></span>
             <span class="dd-cn leer">${esc(kurz)}</span>
             <button class="dd-cadd" data-scan data-wort="${esc(voll)}"
               aria-label="${esc(kurz)} aufnehmen">${KAMERA_ICON}<span>aufnehmen</span></button>
           </div>`;
    }).join('')}</div>${scanFeldHtml}`;
  };
  const belegeHtml = (bereich === 'mieten' && typen)
    ? mietChecklistHtml()
    : (alle.length
        ? (belege.haupt ? belegItem(belege.haupt, false) : '')
          + (belege.unter || []).map(d => belegItem(d, true)).join('')
        : `<div class="dd-keinbeleg">Noch kein Beleg
            hinterlegt — hier abfotografieren oder über den Dokumentenbaum oben anhängen.</div>`)
      + scanHtml;

  const dlg = document.createElement('dialog');
  dlg.className = 'immo-dlg detail-dlg';
  document.body.appendChild(dlg);
  // Jeder Beleg-Wechsel liefert ein eigenes Array von Object-URLs (es füllt
  // sich asynchron). Wir merken die Arrays und geben beim Schließen alles frei.
  const adressListen = [];
  dlg.addEventListener('close', () => {
    for (const liste of adressListen) liste.forEach(a => URL.revokeObjectURL(a));
    dlg.remove();
  });

  dlg.innerHTML = `
    <div class="dd-kopf">
      <span class="dd-ikon" style="color:${RUBRIKFARBE[bereich] || 'var(--teal)'}"
        >${kostenIcon(cfg.ikon)}</span>
      <span class="dd-t">${esc(cfg.name(eintrag))}</span>
      <button class="dd-x" data-zu aria-label="Schließen">×</button>
    </div>
    <div class="dd-body">
      <div class="dd-links">
        <div class="dd-daten">${datenHtml}</div>
        <div class="dd-aktionen">
          <button class="dd-edit" data-bearbeiten>✎ Bearbeiten</button>
          ${kannUmklassifizieren(bereich)
            ? `<button class="dd-edit" data-umklass>⇄ Rubrik ändern</button>` : ''}
        </div>
        <div class="dd-belege"><span class="dd-sub">${esc(dokLabel)}</span>${belegeHtml}</div>
      </div>
      <div class="dd-rechts">
        <div class="beleg-flaeche"><div class="beleg-blatt leer">${alle.length
          ? 'Tippe ein Dokument an, um es anzusehen.'
          : 'Kein Dokument zum Anzeigen.'}</div></div>
      </div>
    </div>`;
  // Fachbegriffe in der Zusammenfassung bekommen dasselbe ?-Icon wie im Formular.
  installHilfe(dlg);

  const flaeche = dlg.querySelector('.beleg-flaeche');
  // Der gerade gezeigte Beleg — er wandert beim „Bearbeiten" mit in die Maske.
  let aktuellerBeleg = null;
  const zeigeDoc = (docId, name) => {
    aktuellerBeleg = { id: Number(docId), dateiname: name };
    dlg.querySelectorAll('.dd-beleg').forEach(b =>
      b.classList.toggle('an', b.dataset.doc === String(docId)));
    adressListen.push(belegSeitenLaden(`/api/dokumente/${docId}`, flaeche,
      name || 'Beleg', `/api/dokumente/${docId}/inhalt`));
  };
  // CCCLXXXIX — das PDF wird NICHT mehr automatisch geladen; es erscheint erst,
  // wenn man ein Dokument antippt (zeigeDoc). Das hielt die Ansicht ruhig, statt
  // gleich das ganze Blatt einzublenden.

  /* CCCLXVII — die Aufnahmen laufen durch die gemeinsame Choreografie
     (`belegscan.js`): zuschneiden, mehrseitig als PDF ablegen, Textschicht
     nachtragen.

     Die Detailansicht schliesst dafür zuerst. Sie steht als `showModal()` in
     der obersten Ebene des Browsers — die Scanner-Oberfläche läge sonst
     dahinter und liesse sich nicht bedienen (kein z-index hilft dagegen).
     Danach wird sie mit dem frischen Beleg neu aufgebaut; der Nutzer landet
     wieder genau dort, wo er losgegangen ist. */
  const scanFeld = dlg.querySelector('[data-scanfeld]');
  if (scanFeld) scanFeld.addEventListener('change', async () => {
    const dateien = [...scanFeld.files];
    scanFeld.value = '';
    if (!dateien.length) return;
    dlg.close();
    let ergebnis;
    try {
      ergebnis = await belegScannen(dateien, {
        objekt: slug, kategorie: SCAN_KATEGORIE[bereich] || 'Sonstiges',
        jahr: scanJahr(eintrag), beschreibung: gewaehltWort,
        anTyp: typ, anId: id, titel: `${gewaehltWort} · ${cfg.name(eintrag)}`,
      });
    } catch (fehler) {
      // Die Ansicht bleibt bewusst zu: der Melder sitzt unter einem modalen
      // Dialog (oberste Browser-Ebene schlägt jeden z-index) und wäre sonst
      // nicht zu lesen. Der Eintrag ist einen Tipp entfernt.
      return melde(String(fehler.message || 'Der Beleg wurde nicht abgelegt.'),
                   'neg');
    }
    if (!ergebnis) return eintragDetail(bereich, id, laden);   // abgebrochen
    // Kein Erfolgs-Toast: der frische Beleg steht gleich in der Liste und
    // sagt dasselbe — nur sichtbar und dauerhaft.
    await laden();
    return eintragDetail(bereich, id, laden);
  });

  dlg.addEventListener('click', e => {
    if (e.target === dlg || e.target.closest('[data-zu]')) { dlg.close(); return; }
    const scanBtn = e.target.closest('[data-scan]');
    if (scanBtn) { gewaehltWort = scanBtn.dataset.wort || gewaehltWort; scanFeld.click(); return; }
    const b = e.target.closest('[data-doc]');
    if (b) { zeigeDoc(b.dataset.doc, b.dataset.name); return; }
    if (e.target.closest('[data-bearbeiten]')) {
      dlg.close();
      oeffneEintragFormular(bereich, eintrag, aktuellerBeleg);
      return;
    }
    if (e.target.closest('[data-umklass]')) {
      const ziele = UMKLASS_ZIELE.filter(z => z.wert !== bereich);
      wahl('Rubrik ändern', `„${cfg.name(eintrag)}" gehört eigentlich zu …`,
           ziele.map(z => ({ wert: z.wert, text: z.titel }))).then(async gewaehlt => {
        if (!gewaehlt) return;
        try {
          await api(`/dokumente/eintrag/${AN_TYP[bereich]}/${id}/umklassifizieren`,
                    { method: 'POST', body: { ziel: gewaehlt } });
        } catch (fehler) {
          return melde(String(fehler.message || 'Konnte nicht geändert werden.'), 'neg');
        }
        dlg.close();
        const titel = (UMKLASS_ZIELE.find(z => z.wert === gewaehlt) || {}).titel;
        melde(`Eintrag nach „${titel}" verschoben`, 'pos');
        await laden();
      });
    }
  });
  dlg.showModal();
}
