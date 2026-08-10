/* N216 — Eintrags-Detailansicht (CCCXIII): Daten links, Beleg rechts.

   Klick auf einen Eintrag (z. B. Grundsteuer) öffnet nicht direkt das
   Bearbeiten-Formular, sondern eine geteilte Ansicht wie im Dokumentenmodus:
   links Felder + Belege (Hauptbeleg + eingerückt die Info-Belege), rechts das
   PDF. Ein Beleg antippen tauscht die Vorschau, „Bearbeiten" führt ins
   bewährte Formular. Auf dem Telefon stapelt sich alles. */

import { esc, api, installHilfe, melde, wahl, belegSeitenLaden, belegAnsehen,
         fokusAufDenDialog, belegUmbenennen, belegVerschieben, kiAusleseZeigen,
         werkzeugreiheHtml } from '../immo.js';
import { kostenIcon } from '../kostenicons.js';
import { cfgFuer, felderFuer, endpunktBereich,
         RUBRIK_FESTWERTE } from '../objekt-felder.js?v=2';
import { feldWertText } from '../objekt-format.js?v=2';
import { HAKEN_ICON, BELEG_ICON } from '../objekt-baum.js?v=2';
import { slug } from '../objekt-state.js?v=2';
import { belegVorbereiten, belegAblegen } from '../belegscan.js';
import { analyseDecke, belegBestaetigen } from '../belegbestaetigung.js';
import { AN_TYP, RUBRIKFARBE, SCAN_KATEGORIE, SCAN_TYPEN, SCAN_WORT,
         UMKLASS_ZIELE, KAMERA_ICON, kannUmklassifizieren } from './state.js';
import { scanJahr } from './helpers.js';

/* N264 — Drucker-Sprite im flachen Stil der uebrigen Symbole. */
const DRUCKER_ICON = `<svg viewBox="0 0 24 24" width="15" height="15" fill="none"
  stroke="currentColor" stroke-width="1.8" stroke-linecap="round"
  stroke-linejoin="round" aria-hidden="true">
  <path d="M6 9V3h12v6"/><rect x="3" y="9" width="18" height="8" rx="2"/>
  <path d="M6 14h12v7H6z"/></svg>`;

import { formular, feldLabel, feldHtml, ausFormular, formateSetzen,
         auswahlSetzen, datumwahlSetzen } from './formular.js';
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

/**
 * Die Detailansicht eines Eintrags.
 *
 * `zeigeDocId` (N280): welcher Beleg gleich in der Vorschau stehen soll. Nach
 * einem frischen Scan ist das der eben abgelegte — der Nutzer sieht sofort,
 * wie die Datei heisst und wo sie liegt, statt sie erst suchen zu müssen.
 */
export async function eintragDetail(bereich, id, laden, zeigeDocId = null) {
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

  // N240 — welche Checklisten-Typen eine Vorlage im Vorlagenarchiv haben
  // (Übergabeprotokoll, Selbstauskunft, Rauchwarnmelder-Abnahme …). Nur für
  // Mietverhältnisse angefragt, ein Fehlschlag lässt die Checkliste einfach
  // ohne Vorlagen-Links weiterlaufen.
  let vorlagenNachTyp = new Map();
  let drucker = [];
  if (bereich === 'mieten') {
    try {
      const d = await api('/dokumentvorlagen?verwendungszweck=Vermietung');
      vorlagenNachTyp = new Map((d.vorlagen || []).map(v => [v.typ, v]));
      // N264 — die Drucker des Hauses. Ohne Druckdienst bleibt die Liste leer
      // und es erscheint kein Druckknopf, statt einer, der ins Leere laeuft.
      try { drucker = (await api('/drucker')).drucker || []; } catch { drucker = []; }
    } catch { /* Vorlagenarchiv optional — Checkliste bleibt nutzbar */ }
  }

  // Felder als ruhige Zusammenfassung — dieselbe Beschreibung wie das Formular.
  const felder = felderFuer(bereich, eintrag).filter(f => !f.hilfe && f.typ !== 'block');
  const datenHtml = felder.map(f => {
    const t = feldWertText(f, eintrag[f.k]);
    return `<div class="dd-zeile"><span class="dd-l">${feldLabel(f)}</span>
      <span class="dd-v">${esc(t)}</span></div>`;
  }).join('');

  const belegItem = (d, unter) => `<button class="dd-beleg${unter ? ' unter' : ''}"
      data-doc="${d.id}" data-name="${esc(d.dateiname)}" data-pfad="${esc(d.pfad || '')}">
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
  /* `knapp`: steht der Knopf neben Vorlage und Druckern, trägt er nur noch die
     Kamera. Mit Beschriftung passten die vier Knöpfe nicht in eine Zeile und
     die Reihe wuchs auf drei — das Symbol sagt hier dasselbe. */
  const aufnehmenKnopf = (voll, kurz, knapp = false) => `<button
       class="dd-cadd${knapp ? ' nurikon' : ''}" data-scan data-wort="${esc(voll)}"
       title="${esc(kurz)} aufnehmen" aria-label="${esc(kurz)} aufnehmen"
       >${KAMERA_ICON}${knapp ? '' : '<span>aufnehmen</span>'}</button>`;
  /* Name oben, Aktionen darunter — für jede Zeile, in der mehr als ein Knopf
     steht. Nebeneinander bliebe vom Namen nichts übrig (siehe objekt.html). */
  const zweizeilig = (kurz, aktionen) => `<div class="dd-check fehlt zweizeilig">
       <span class="dd-ci"></span>
       <div class="dd-zspalte">
         <span class="dd-cn leer">${esc(kurz)}</span>
         <div class="dd-zaktionen">${aktionen}</div>
       </div>
     </div>`;
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
    // N224 — die Kaution hat zwei Wege: ein eigenes Kautionskonto (Dokument-
    // Nachweis, wie jede andere Zeile) ODER eine Überweisung auf das normale
    // Objektkonto (kein Dokument — dafür dieser Vermerk am Mietverhältnis).
    const istKaution = voll => voll === 'Mietkautionskonto';
    return `<div class="dd-checkliste">${typen.map(([voll, kurz]) => {
      const da = alle.find(d => typVon(d) === voll);
      if (!da && istKaution(voll) && eintrag.kaution_objektkonto) {
        return `<div class="dd-check da">
             <span class="dd-ci ok">${HAKEN_ICON}</span>
             <span class="dd-cn" style="cursor:default">Kaution auf Objektkonto</span>
             <button class="dd-cx" data-kaution-objektkonto="0"
               title="Doch ein eigenes Kautionskonto?"
               aria-label="Doch ein eigenes Kautionskonto?">Ändern</button>
           </div>`;
      }
      return da
        ? `<div class="dd-check da">
             <span class="dd-ci ok">${HAKEN_ICON}</span>
             <button class="dd-cn" data-doc="${da.id}" data-name="${esc(da.dateiname)}"
               data-pfad="${esc(da.pfad || '')}"
               >${esc(kurz)}${da.jahr ? `<span class="dd-cj">${da.jahr}</span>` : ''}</button>
             <button class="dd-cx" data-scan data-wort="${esc(voll)}"
               title="${esc(kurz)} ersetzen" aria-label="${esc(kurz)} ersetzen">Ersetzen</button>
           </div>`
        : istKaution(voll)
          // N224 — zwei Aktionen (Auf Objektkonto / aufnehmen) passen nicht
          // mehr in eine Zeile neben dem Namen, ohne ihn abzuschneiden —
          // eigenes zweizeiliges Layout: Name oben, Aktionen darunter.
          ? zweizeilig(kurz, `<button class="dd-cx" data-kaution-objektkonto="1"
                     title="Auf das normale Objektkonto überwiesen — kein Dokument nötig"
                     aria-label="Kaution auf Objektkonto vermerken">Auf Objektkonto</button>
                   ${aufnehmenKnopf(voll, kurz)}`)
          : (() => {
              const vorlage = vorlagenNachTyp.get(voll);
              // Ohne Vorlage bleibt es einzeilig: Name und ein Knopf passen
              // nebeneinander. Mit Vorlage kommen Ansehen + je ein Drucker
              // dazu — dann derselbe zweizeilige Aufbau wie bei der Kaution.
              if (!vorlage) {
                return `<div class="dd-check fehlt">
             <span class="dd-ci"></span>
             <span class="dd-cn leer">${esc(kurz)}</span>
             ${aufnehmenKnopf(voll, kurz)}
           </div>`;
              }
              return zweizeilig(kurz, `<button class="dd-vorlage" data-vorlage="${vorlage.id}"
               data-vorlage-name="${esc(vorlage.name)}"
               title="Leere Vorlage ansehen/herunterladen">Vorlage</button>
             ${drucker.map(dr => `<button class="dd-vdruck"
               data-vorlage-drucken="${vorlage.id}" data-drucker="${esc(dr.name)}"
               title="Vorlage an ${esc(dr.standort || dr.name)} schicken"
               aria-label="Vorlage an ${esc(dr.standort || dr.name)} schicken"
               >${DRUCKER_ICON}</button>`).join('')}
             ${aufnehmenKnopf(voll, kurz, true)}`);
            })();
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
        <div class="dd-vorschau-kopf" hidden></div>
        <div class="beleg-flaeche"><div class="beleg-blatt leer">${alle.length
          ? 'Tippe ein Dokument an, um es anzusehen.'
          : 'Kein Dokument zum Anzeigen.'}</div></div>
      </div>
    </div>`;
  // Fachbegriffe in der Zusammenfassung bekommen dasselbe ?-Icon wie im Formular.
  installHilfe(dlg);

  const flaeche = dlg.querySelector('.beleg-flaeche');
  const vorschauKopf = dlg.querySelector('.dd-vorschau-kopf');
  // Der gerade gezeigte Beleg — er wandert beim „Bearbeiten" mit in die Maske.
  let aktuellerBeleg = null;
  const zeigeDoc = (docId, name, pfad) => {
    aktuellerBeleg = { id: Number(docId), dateiname: name };
    dlg.querySelectorAll('.dd-beleg').forEach(b =>
      b.classList.toggle('an', b.dataset.doc === String(docId)));
    if (vorschauKopf) {
      // N334 — die Handgriffe am Beleg stehen HIER, nicht in einem zweiten
      // Fenster. Vorher trug diese Zeile den Text „Umbenennen · verschieben ·
      // Auslese" — das las sich wie drei winzige Verweise, war aber ein
      // einziger Knopf, der bloss eine weitere Ansicht öffnete. Jetzt: Name
      // und Ablageort als ruhige Beschriftung, darunter drei echte Knöpfe mit
      // voller Grösse. Die Auslese klappt an Ort und Stelle auf, statt die
      // halbe Vorschau zu verdrängen.
      vorschauKopf.innerHTML = `
        <div class="dd-vn">${esc(name || 'Beleg')}</div>${pfad
        ? `<div class="dd-vp" title="Ablageort in der Nextcloud"><bdi dir="ltr">${
            esc(pfad)}</bdi></div>` : ''}
        ${werkzeugreiheHtml()}
        <div class="dd-vki beleg-ki" hidden></div>`;
      vorschauKopf.hidden = false;
    }
    flaeche.classList.add('klickbar');
    adressListen.push(belegSeitenLaden(`/api/dokumente/${docId}`, flaeche,
      name || 'Beleg', `/api/dokumente/${docId}/inhalt`));
  };
  // N331e — CCCLXXXIX liess das PDF bewusst erst nach einem Antippen laden
  // ("Ansicht ruhig halten"); Nutzer-Fund: in ~90-95 % der Fälle gibt es
  // ohnehin nur den einen (richtigen) Beleg — der Antipp-Zwang war für die
  // meisten Aufrufe nur ein unnötiger Extra-Klick. Jetzt lädt automatisch:
  // der eben angehängte Beleg (N280, falls gerade einer dazukam), sonst der
  // erste der Liste. Umwählen bleibt jederzeit möglich (Klick auf einen
  // anderen Beleg in der Liste, siehe `.dd-beleg`-Handler unten).
  const zeigeStart = (zeigeDocId
    ? alle.find(d => String(d.id) === String(zeigeDocId)) : null) || alle[0] || null;
  if (zeigeStart) zeigeDoc(zeigeStart.id, zeigeStart.dateiname, zeigeStart.pfad);

  /* N280 — das gemeinsame Beleg-Fenster. Es liegt als eigener `showModal`-
     Dialog über dieser Ansicht (beide in der obersten Browser-Ebene, das
     zuletzt geöffnete gewinnt) — die Detailansicht muss dafür nicht zu.
     Beim Schliessen wird sie neu aufgebaut: ein dort geänderter Name steht
     dann auch hier. Wurde weitergeblättert, ist schon das nächste Fenster
     offen — dann bleibt alles stehen, bis auch das zu ist. */
  const grossAnsehen = () => {
    if (!aktuellerBeleg) return;
    const dok = alle.find(d => String(d.id) === String(aktuellerBeleg.id));
    const fenster = belegAnsehen(`/api/dokumente/${aktuellerBeleg.id}/inhalt`,
      dok?.dateiname || aktuellerBeleg.dateiname || 'Beleg', dok?.pfad || '',
      aktuellerBeleg.id, alle);
    const zurueck = aktuellerBeleg.id;
    fenster.addEventListener('close', () => setTimeout(() => {
      if (document.querySelector('dialog.beleg-dlg[open]')) return;
      dlg.close();
      eintragDetail(bereich, id, laden, zurueck);
    }, 0));
  };

  /* CCCLXVII — die Aufnahmen laufen durch die gemeinsame Choreografie
     (`belegscan.js`): zuschneiden, mehrseitig als PDF ablegen, Textschicht
     nachtragen.

     Die Detailansicht schliesst dafür zuerst. Sie steht als `showModal()` in
     der obersten Ebene des Browsers — die Scanner-Oberfläche läge sonst
     dahinter und liesse sich nicht bedienen (kein z-index hilft dagegen).
     Danach wird sie mit dem frischen Beleg neu aufgebaut; der Nutzer landet
     wieder genau dort, wo er losgegangen ist. */
  /* N280 — und zwar in ZWEI Schritten, wie überall sonst: aufnehmen und
     auslesen, dann den vorgeschlagenen **Dateinamen zeigen** (änderbar), dann
     ablegen. Hier gibt es kein Formular, das den Namen tragen könnte — also
     gehört die Bestätigungsmaske genau hierher. Vorher lief das über den
     Ein-Schritt-Weg: die Datei war benannt in der Cloud, bevor der Nutzer den
     Namen auch nur gesehen hatte. */
  const scanFeld = dlg.querySelector('[data-scanfeld]');
  if (scanFeld) scanFeld.addEventListener('change', async () => {
    const dateien = [...scanFeld.files];
    scanFeld.value = '';
    if (!dateien.length) return;
    dlg.close();
    // Die Decke über der Wartezeit zwischen Zuschnitt und Maske (N254). Sie
    // geht IMMER wieder weg — `belegBestaetigen` nimmt sie, sonst das `finally`.
    let deckeWeg = null;
    let ergebnis;
    try {
      const vorbereitet = await belegVorbereiten(dateien, {
        objekt: slug, kategorie: SCAN_KATEGORIE[bereich] || 'Sonstiges',
        jahr: scanJahr(eintrag), beschreibung: gewaehltWort,
        anTyp: typ, anId: id, titel: `${gewaehltWort} · ${cfg.name(eintrag)}`,
      }, () => { deckeWeg = analyseDecke(`${gewaehltWort} wird gelesen …`); });
      if (!vorbereitet) return eintragDetail(bereich, id, laden);  // abgebrochen
      const entscheidung = await belegBestaetigen(vorbereitet, deckeWeg);
      deckeWeg = null;
      if (!entscheidung) return eintragDetail(bereich, id, laden);  // abgebrochen
      ergebnis = await belegAblegen(vorbereitet, entscheidung.beschreibung,
                                    entscheidung.betrag);
    } catch (fehler) {
      // Die Ansicht bleibt bewusst zu: der Melder sitzt unter einem modalen
      // Dialog (oberste Browser-Ebene schlägt jeden z-index) und wäre sonst
      // nicht zu lesen. Der Eintrag ist einen Tipp entfernt.
      return melde(String(fehler.message || 'Der Beleg wurde nicht abgelegt.'),
                   'neg');
    } finally {
      if (deckeWeg) { try { deckeWeg(); } catch { /* egal */ } }
    }
    // Kein Erfolgs-Toast: der frische Beleg steht gleich in der Liste und
    // sagt dasselbe — nur sichtbar und dauerhaft. Und er steht offen in der
    // Vorschau, mit Namen und Ablageort (N280).
    await laden();
    return eintragDetail(bereich, id, laden, ergebnis?.id || null);
  });

  /* ------------------------------------------------------------------
     N334e — Bearbeiten an Ort und Stelle.

     Bisher führte „Bearbeiten" in ein zweites Fenster: dieselben Werte, nur
     woanders und in einem anderen Rahmen — der Beleg, wegen dem man die
     Ansicht überhaupt geöffnet hat, war dabei weg. Jetzt werden die
     angezeigten Zeilen selbst zu Feldern; „Fertig" speichert und legt sie
     wieder still. Es sind buchstäblich dieselben Felder wie im Formular
     (`feldHtml`, `ausFormular` aus formular.js) — kein zweiter Satz, der
     auseinanderlaufen könnte.

     Nicht für Mietverhältnis und Kredit: dort hängen Zusatzblöcke am Formular
     (Bewohner, Kreditstände, Zinskopplung), die eigene Speicherwege haben.
     Die behalten das grosse Formular — mit dem Rückweg aus N333.
  ------------------------------------------------------------------ */
  const inlineMoeglich = !['mieten', 'kredite'].includes(bereich);
  const datenKasten = dlg.querySelector('.dd-daten');
  let inlineAktiv = false;

  const inlineAus = (frisch = null) => {
    inlineAktiv = false;
    const stand = frisch || eintrag;
    datenKasten.innerHTML = felder.map(f =>
      `<div class="dd-zeile"><span class="dd-l">${feldLabel(f)}</span>
       <span class="dd-v">${esc(feldWertText(f, stand[f.k]))}</span></div>`).join('');
    dlg.querySelector('.dd-aktionen').hidden = false;
    installHilfe(datenKasten);
  };

  const inlineAn = async () => {
    if (inlineAktiv) return;
    inlineAktiv = true;
    dlg.querySelector('.dd-aktionen').hidden = true;
    const stuecke = await Promise.all(
      felder.map(f => feldHtml(f, bereich, eintrag[f.k])));
    datenKasten.innerHTML = `<form class="dd-form" data-inline>
        ${stuecke.join('')}
        <div class="dd-formknoepfe">
          <button class="btn" value="ok">Fertig</button>
          <button class="btn leise" type="button" data-inline-ab>Abbrechen</button>
        </div>
      </form>`;
    const form = datenKasten.querySelector('form');
    formateSetzen(form, felder);
    auswahlSetzen(form);
    datumwahlSetzen(form);
    installHilfe(form);
    form.querySelector('input,select,textarea')?.focus({ preventScroll: true });
  };

  datenKasten.addEventListener('submit', async e => {
    e.preventDefault();
    const form = e.target;
    const knopf = form.querySelector('button[value="ok"]');
    if (knopf) { knopf.disabled = true; knopf.textContent = 'Wird gespeichert …'; }
    const werte = { ...ausFormular(form, felder),
                    ...(RUBRIK_FESTWERTE[bereich] || {}) };
    try {
      await api(`/stammdaten/${endpunktBereich(bereich)}/${id}`,
                { method: 'PATCH', body: werte });
    } catch (fehler) {
      if (knopf) { knopf.disabled = false; knopf.textContent = 'Fertig'; }
      return melde(String(fehler.message || 'Konnte nicht gespeichert werden.'), 'neg');
    }
    Object.assign(eintrag, werte);
    inlineAus(eintrag);
    // Die Liste dahinter trägt denselben Wert — sie zieht mit, ohne dass
    // diese Ansicht dafür zugehen müsste.
    laden();
  });

  dlg.addEventListener('click', async e => {
    if (e.target === dlg || e.target.closest('[data-zu]')) { dlg.close(); return; }
    if (e.target.closest('[data-inline-ab]')) { inlineAus(); return; }
    // N334 — Umbenennen, Verschieben und die Auslese laufen HIER, ohne ein
    // zweites Fenster. Nur das Blättern zum Nachbarbeleg blieb dem gemeinsamen
    // Beleg-Fenster vorbehalten (`grossAnsehen`, s. u.) — dafür gibt es in
    // dieser Ansicht die Belegliste links.
    if (e.target.closest('[data-um]') && aktuellerBeleg) {
      const erg = await belegUmbenennen(aktuellerBeleg.id, aktuellerBeleg.dateiname);
      if (erg) {
        aktuellerBeleg.dateiname = erg.dateiname || aktuellerBeleg.dateiname;
        dlg.querySelector('.dd-vn').textContent = aktuellerBeleg.dateiname;
        const pfadEl = dlg.querySelector('.dd-vp bdi');
        if (pfadEl && erg.pfad) pfadEl.textContent = erg.pfad;
        const eintragEl = dlg.querySelector(`.dd-beleg[data-doc="${aktuellerBeleg.id}"] .dd-bn`);
        if (eintragEl) eintragEl.textContent = aktuellerBeleg.dateiname;
      }
      return;
    }
    if (e.target.closest('[data-ordner]') && aktuellerBeleg) {
      const erg = await belegVerschieben(aktuellerBeleg.id);
      const pfadEl = dlg.querySelector('.dd-vp bdi');
      if (erg && pfadEl && erg.pfad) pfadEl.textContent = erg.pfad;
      return;
    }
    // Die Auslese klappt auf und wieder zu — sie ist Hintergrundwissen, nicht
    // das, weswegen man die Ansicht öffnet. Geladen wird sie erst beim ersten
    // Aufklappen, danach bleibt sie stehen.
    const kiKnopf = e.target.closest('[data-kiauf]');
    if (kiKnopf && aktuellerBeleg) {
      const kasten = dlg.querySelector('.dd-vki');
      const auf = kasten.hidden;
      kasten.hidden = !auf;
      kiKnopf.setAttribute('aria-expanded', auf ? 'true' : 'false');
      kiKnopf.classList.toggle('an', auf);
      if (auf && !kasten.dataset.geladen) {
        kasten.dataset.geladen = '1';
        kiAusleseZeigen(aktuellerBeleg.id, kasten);
      }
      return;
    }
    if (e.target.closest('[data-gross]')) { grossAnsehen(); return; }
    // N333 — die Vorschau selbst antippen zoomt dagegen HIER auf: die Felder
    // treten zur Seite, der Beleg füllt das Blatt und scrollt durch. Nochmal
    // antippen holt die Felder zurück. Kein drittes Fenster mehr für den
    // häufigsten Wunsch („einmal genauer hinsehen").
    if (aktuellerBeleg && e.target.closest('.dd-rechts .beleg-flaeche')) {
      dlg.querySelector('.dd-body')?.classList.toggle('zoom');
      return;
    }
    const scanBtn = e.target.closest('[data-scan]');
    if (scanBtn) { gewaehltWort = scanBtn.dataset.wort || gewaehltWort; scanFeld.click(); return; }
    // N240 — die leere Vorlage ansehen/herunterladen, ohne den „aufnehmen"-Weg
    // zu berühren: reine Lesehilfe, kein Ersatz für den echten Beleg.
    // N264 — dieselbe Vorlage direkt auf einen Drucker im Haus.
    const vdruck = e.target.closest('[data-vorlage-drucken]');
    if (vdruck) {
      vdruck.disabled = true;
      try {
        const antwort = await api(
          `/dokumentvorlagen/${vdruck.dataset.vorlageDrucken}/drucken`
          + `?drucker=${encodeURIComponent(vdruck.dataset.drucker)}`,
          { method: 'POST' });
        melde(antwort.meldung || 'An den Drucker geschickt', 'pos');
      } catch (fehler) {
        melde(fehler?.message || 'Der Druckauftrag hat nicht geklappt', 'neg');
      } finally {
        vdruck.disabled = false;
      }
      return;
    }
    const vorlageBtn = e.target.closest('[data-vorlage]');
    if (vorlageBtn) {
      belegAnsehen(`/api/dokumentvorlagen/${vorlageBtn.dataset.vorlage}/inhalt`,
        vorlageBtn.dataset.vorlageName || 'Vorlage', '', null);
      return;
    }
    // N224 — Kaution auf das normale Objektkonto vermerken (oder zurücknehmen),
    // ohne dass dafür ein Dokument nötig ist.
    const kontoBtn = e.target.closest('[data-kaution-objektkonto]');
    if (kontoBtn) {
      const auf = kontoBtn.dataset.kautionObjektkonto === '1';
      (async () => {
        try {
          await api(`/stammdaten/mieten/${id}`,
            { method: 'PATCH', body: { kaution_objektkonto: auf } });
        } catch (fehler) {
          return melde(String(fehler.message || 'Konnte nicht gespeichert werden.'), 'neg');
        }
        dlg.close();
        await laden();
        return eintragDetail(bereich, id, laden);
      })();
      return;
    }
    const b = e.target.closest('[data-doc]');
    if (b) { zeigeDoc(b.dataset.doc, b.dataset.name, b.dataset.pfad); return; }
    if (e.target.closest('[data-bearbeiten]')) {
      // N334e — der Regelfall: die angezeigten Werte werden an Ort und Stelle
      // bedienbar. Kein Fensterwechsel, der Beleg bleibt daneben stehen.
      if (inlineMoeglich) { await inlineAn(); return; }
      // N333 — der Rückweg für die Rubriken, die weiterhin das grosse
      // Formular brauchen (Mietverhältnis mit Bewohnern, Kredit mit Ständen
      // und Zinskopplung — dort hängen Zusatzblöcke am Formular, die sich
      // nicht sinnvoll in die schmale Spalte falten lassen). Das Formular lebt
      // in einem einzigen, global wiederverwendeten <dialog id="dlg">; wer
      // bisher „Bearbeiten" antippte, war nach dem Speichern ODER Abbrechen
      // ganz aus dem Beleg heraus — den Vorgänger merkte sich niemand.
      const zurueck = aktuellerBeleg?.id || null;
      dlg.close();
      await oeffneEintragFormular(bereich, eintrag, aktuellerBeleg);
      const formDlg = document.getElementById('dlg');
      if (!formDlg?.open) return;
      formDlg.addEventListener('close', () => setTimeout(() => {
        // Hat der Weg von hier in ein weiteres Fenster geführt (Kamera,
        // Rückfrage), gehört die Bühne dem — dann bleibt alles stehen.
        if (document.querySelector('dialog[open]')) return;
        eintragDetail(bereich, id, laden, zurueck);
      }, 0), { once: true });
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
  fokusAufDenDialog(dlg);
}
