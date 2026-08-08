/* zeitraum/belege.js — Belege: Anhänger, Ablage, Erkennung, Beleg lösen.

   Der Beleg-Weg zur NK-Zeile ist **einer**, ganz gleich ob er mit dem
   Foto-Knopf, der Dateiauswahl oder einem Drop auf die Karte beginnt (N280):

     `belegVorbereiten` (aufnehmen · zuschneiden · KI liest)
       → `belegBestaetigen` (Dateiname, Betrag, Vorschau)
       → `belegAbschluss` (Wasser-Rückfrage, Ablage, Verbuchung)

   Vorher entschied am Rechner die *Geste*, welchen Ablauf man bekam: der Knopf
   lief durch die gemeinsame Kette, der Drop auf dieselbe Karte durch einen
   Eigenbau mit eigenem `/erkennen`, eigenem `/scannen` und einem Dialog ohne
   Dateinamen-Vorschlag. Beides steht jetzt hier zusammen — `belegAbschluss` ist
   der gemeinsame Schwanz, den `checkliste.js` (Knopf) und `belegPerDrop`
   (Ziehen) gleichermaßen benutzen.

   Der Wasser-Sonderfall bleibt fachlich erhalten: ein Wasserbescheid trägt drei
   Bereichsgebühren, die auf drei Positionen gehören. Er fragt sie NACH der
   gemeinsamen Bestätigungsmaske ab (`wasserBetraegeDialog` in wasser.js), nicht
   an ihrer Stelle. */

import { api, esc, eur, melde, wahl, frage } from '../immo.js';
import { fotoAlsJpeg } from '../kamerascan.js';
import { belegVorbereiten, belegAblegen } from '../belegscan.js';
import * as state from './state.js';
import { KEINE_KAMERA } from './state.js';
import {
  UPLOAD_ICON, FOTO_ICON, WOLKE_ICON, ANH_ICON,
} from './icons.js';
import { istWasserSammel, istWasserKostenart } from './modell.js';
import { sha1Hex, kurzBeleg } from './helpers.js';
import { wasserBetraegeDialog, wasserPosBetragSchreiben } from './wasser.js';

/* Der Ablage-Bereich einer offenen Zeile (Drop-Fläche + Knöpfe). */
export function belegAblageHtml(k, bearbeitbar) {
  if (!bearbeitbar) return '';
  const art = esc(k.kostenart);
  const knoepfe = KEINE_KAMERA
    ? `<button type="button" class="ablg-knopf" data-scan="${art}"
        >${UPLOAD_ICON}<span>Datei wählen</span></button>`
    : `<button type="button" class="ablg-knopf" data-scan="${art}"
        >${FOTO_ICON}<span>Foto</span></button>
       <button type="button" class="ablg-knopf" data-ablage="${art}"
        >${WOLKE_ICON}<span>Aus der Ablage</span></button>`;
  return `<div class="ablg">
      <span class="ablg-ikon">${UPLOAD_ICON}</span>
      <span class="ablg-t">${KEINE_KAMERA
        ? 'Beleg hier ablegen' : 'Beleg erfassen'}</span>
      <span class="ablg-s">${KEINE_KAMERA
        ? 'Die PDF einfach auf diese Karte ziehen — daraus entstehen Betrag und Position.'
        : 'Aus dem Beleg entstehen Betrag und Position.'}</span>
      <span class="ablg-k">${knoepfe}</span>
    </div>`;
}

/* N96b — was mit dem Beleg geschehen soll: nur aus der Abrechnung nehmen
   oder auch aus der Ablage löschen. */
export function belegWegDialog(dok) {
  return new Promise(fertig => {
    const dlg = document.createElement('dialog');
    dlg.className = 'immo-dlg';
    document.body.appendChild(dlg);
    let wahl = null;
    dlg.addEventListener('close', () => { dlg.remove(); fertig(wahl); }, { once: true });
    dlg.innerHTML = `
      <button class="immo-dlg-zu" data-nein aria-label="Schließen">×</button>
      <div class="dt">Beleg herausnehmen</div>
      <p style="font:400 13px var(--body);color:var(--soft);line-height:1.5">
        <b style="color:var(--ink)">${esc(dok?.dateiname || 'Beleg')}</b><br>
        Er wird aus dieser Abrechnung genommen; sein Betrag zählt nicht mehr mit.</p>
      <div class="kartenfuss" style="display:flex;flex-direction:column;gap:9px">
        <button class="hauptaktion" data-wahl="raus">Nur herausnehmen — Datei bleibt</button>
        <button class="minilink gefahr" data-wahl="ablage">Doppelt: auch aus der Ablage löschen</button>
      </div>`;
    dlg.querySelectorAll('[data-wahl]').forEach(b => (b.onclick = () => {
      wahl = b.dataset.wahl; dlg.close();
    }));
    dlg.querySelector('[data-nein]').onclick = () => dlg.close();
    dlg.showModal();
  });
}

/* N95 — einen Beleg aus seiner Kostenposition herausnehmen. */
export async function belegLoesen(id) {
  const dok = (state.daten.dokumente || []).find(d => String(d.id) === String(id));
  const wahl = await belegWegDialog(dok);
  if (!wahl) return;
  try {
    await api(`/dokumente/${id}/position`, { method: 'DELETE' }).catch(() => {});
    await api(`/dokumente/${id}`, { method: 'PATCH', body: { zeitraum_id: null } });
    if (wahl === 'ablage') {
      // N97 — Gegenstück suchen.
      const gleich = d => String(d.id) !== String(id)
        && (d.betrag ?? null) === (dok?.betrag ?? null)
        && (d.kostenart || '') === (dok?.kostenart || '');
      const zwilling = (state.daten.dokumente || []).find(d => gleich(d) && d.groesse === dok?.groesse)
        || (state.daten.dokumente || []).find(gleich);
      if (!zwilling) {
        melde('Herausgenommen. Kein zweiter Beleg mit gleichem Betrag und '
          + 'gleicher Kostenart gefunden — die Datei bleibt in der Ablage.', 'neg');
      } else {
        const a = await api(`/dokumente/${id}/duplikat-entfernen`,
          { method: 'POST', body: { behalten_id: zwilling.id, bestaetigt: true } });
        melde(a?.verschoben
          ? 'Doppel bestätigt — Datei nach „99_Duplikate" verschoben'
          : 'Doppelter Beleg entfernt — auch aus der Ablage', 'pos');
      }
    } else {
      melde('Beleg herausgenommen — die Datei bleibt in der Ablage', 'pos');
    }
    // N185 — Wasser-Beleg: bei letztem Beleg räumt das Backend die drei Bestandteile ab.
    if (dok && istWasserKostenart(dok.kostenart)) {
      const r = await api(`/zeitraeume/${state.zid}/wasser/leeren`, { method: 'POST' })
        .catch(() => null);
      if (r?.geleert) {
        melde('Wasser-Position geleert — die Zähler bleiben. Neuen Beleg '
          + 'fotografieren, dann liest die Erkennung sie wieder ein.', 'pos');
      }
    }
    const { laden } = await import('./checkliste.js');
    await laden();
  } catch (fehler) { melde(String(fehler.message || fehler), 'neg'); }
}

/* CCLV — den kostenfreien Beleg aus dem Bestand wählen. */
function anhaengerWaehlen(kostenart) {
  const kandidaten = state.anhaenger?.kandidaten || [];
  const liste = kandidaten.length
    ? kandidaten.map(d => `
        <button class="ahz" data-pick="${d.id}">
          ${ANH_ICON}
          <span class="ahn">${esc(kurzBeleg(d.dateiname))}
            <span class="ahsub">${esc(d.kategorie || 'Ohne Art')}${
              d.jahr ? ` · ${d.jahr}` : ''}</span></span>
        </button>`).join('')
    : `<div class="ahleer">Kein kostenfreier Beleg im Bestand dieser Immobilie.
       Ein Beleg wird kostenfrei, wenn er im Eingang ohne Kostenposition bleibt —
       etwa ein Zählerstand oder ein SEPA-Mandat.</div>`;

  return new Promise(fertig => {
    const dlg = document.createElement('dialog');
    dlg.className = 'immo-dlg ahdlg';
    dlg.innerHTML = `
      <div class="dt">Beleg an „${esc(kostenart)}“ hängen</div>
      <p>Trägt der Beleg keinen Betrag, hängt er als Infobeleg am Thema — mit
        Betrag wird er zur Kostenposition.</p>
      <button type="button" class="ahscan" data-neu>
        ${KEINE_KAMERA ? UPLOAD_ICON : FOTO_ICON}
        <span class="ahn">${KEINE_KAMERA ? 'Datei wählen' : 'Abfotografieren'}</span>
      </button>
      <div class="ahtrenn">oder aus dem Bestand</div>
      <div class="ahliste">${liste}</div>
      <button class="btn leise" data-nein>Abbrechen</button>`;
    document.body.appendChild(dlg);
    dlg.addEventListener('close', () => dlg.remove());
    dlg.addEventListener('cancel', () => fertig(null));
    dlg.addEventListener('click', e => {
      const pick = e.target.closest('[data-pick]');
      // N268 — statt aus dem Bestand zu wählen, den Beleg gleich hier
      // aufnehmen. Der Rückgabewert sagt dem Aufrufer, welcher Weg gemeint war.
      if (e.target.closest('[data-neu]')) { fertig({ scan: true }); dlg.close(); }
      else if (pick) { fertig(Number(pick.dataset.pick)); dlg.close(); }
      else if (e.target.closest('[data-nein]')) { fertig(null); dlg.close(); }
    });
    dlg.showModal();
  });
}

export async function anhaengen(kostenart) {
  const wahl = await anhaengerWaehlen(kostenart);
  if (!wahl) return;
  // N268 — der Foto-Weg läuft durch dieselbe Scan-Kette wie die Kostenart-Karte
  // (Zuschnitt, Auslese, Bestätigungsmaske). Was danach passiert, entscheidet
  // der Betrag: mit Betrag wird es eine Kostenposition, ohne ein Anhänger.
  // `anhaengerFuer` ist das einzige Unterscheidungsmerkmal, das die Kette
  // dafür braucht — siehe `checkliste.js`.
  if (wahl.scan) {
    state.setScanZiel({ kostenart, anhaengerFuer: kostenart });
    document.getElementById('scanFeld').click();
    return;
  }
  const id = wahl;
  try {
    await api(`/dokumente/${id}/anhaenger`,
      { method: 'POST', body: { zeitraum_id: Number(state.zid), kostenart } });
    melde(`Anhänger an „${kostenart}“ gesetzt`, 'pos');
    const { laden } = await import('./checkliste.js');
    await laden();
  } catch (fehler) {
    melde(String(fehler.message || fehler), 'neg');
  }
}

/* N237 — einen Zusatzbeleg wieder vom Thema lösen (Datei bleibt in der Ablage).
   N288: mit Rückfrage, die den Beleg beim Namen nennt — das × sitzt dicht
   neben dem Link, mit dem man ihn nur ansehen wollte. */
export async function anhaengerEntfernen(id, name = '') {
  const ok = await frage('Beleg herausnehmen?',
    `${name ? `„${name}“ ` : 'Der Beleg '}wird von dieser Kostenart gelöst. `
    + 'Die Datei bleibt in der Ablage und lässt sich erneut anhängen.',
    { knopf: 'Herausnehmen', gefahr: true });
  if (!ok) return;
  try {
    await api(`/dokumente/${id}/anhaenger`, { method: 'DELETE' });
    melde('Anhänger gelöst — die Datei bleibt in der Ablage', 'pos');
    const { laden } = await import('./checkliste.js');
    await laden();
  } catch (fehler) {
    melde(String(fehler.message || fehler), 'neg');
  }
}

/* Ladeanzeige in genau der NK-Zeile. */
function zeileVerarbeitet(kostenart, text) {
  const zeile = state.inhalt.querySelector(`.pruef[data-kostenart="${CSS.escape(kostenart)}"]`);
  if (!zeile) return;
  zeile.classList.add('verarbeitet');
  const kopf = zeile.querySelector('.kopf');
  let badge = kopf.querySelector('.zeile-lade');
  if (!badge) {
    badge = document.createElement('span');
    badge.className = 'zeile-lade';
    badge.innerHTML = '<span class="kringel"></span><span class="zl-txt"></span>';
    kopf.appendChild(badge);
  }
  badge.querySelector('.zl-txt').textContent = text;
}

/** N78/N207 — Texterkennung. */
export async function erkennen(bild, kostenart = '') {
  if (!bild) return null;
  try {
    const lesbar = await fotoAlsJpeg(bild);
    const paket = new FormData();
    paket.append('datei', lesbar, lesbar.name || 'seite.jpg');
    if (kostenart) paket.append('kostenart', kostenart);
    const antwort = await fetch('/api/dokumente/erkennen',
                                { method: 'POST', body: paket });
    return antwort.ok ? await antwort.json() : null;
  } catch {
    return null;
  }
}

export function erkennungHatWert(vorschlag) {
  if (!vorschlag) return false;
  const w = vorschlag.wasser;
  if (w && (w.wasser > 0 || w.schmutz > 0 || w.niederschlag > 0)) return true;
  return vorschlag.betrag > 0;
}

async function positionBetragSchreiben(zeile, kostenart, betrag) {
  if (!(betrag > 0)) return;
  if (zeile?.position_id) {
    await api(`/positionen/${zeile.position_id}`,
      { method: 'PATCH', body: { betrag, wertquelle: 'Scan' } });
  } else {
    await api(`/zeitraeume/${state.zid}/positionen`,
      { method: 'POST', body: { kostenart, betrag, wertquelle: 'Scan' } });
  }
}

/* N280 — der gemeinsame Abschluss NACH der Bestätigungsmaske.
 *
 * Alles, was zwischen „Ablegen" und einer fertigen Zeile passiert, steht genau
 * einmal hier: der Wasser-Sonderfall, die Ablage (oder die Verknüpfung einer
 * schon vorhandenen Datei), der gelernte Anbieter und die Verbuchung. Der
 * Foto-Knopf (`checkliste.js`) und der Drop auf die Karte rufen dieselbe
 * Funktion — vorher liefen dafür zwei Fassungen nebeneinander, die sich in
 * jedem Punkt unterschieden.
 *
 * `dup` ist das Ergebnis von `/dokumente/duplikat-pruefen` (oder `null`). Ist
 * die Datei schon in der Cloud, wird der vorhandene Beleg verknüpft statt
 * ein zweites Mal hochgeladen.
 *
 * Gibt `null` zurück, wenn der Nutzer im Wasser-Dialog abgebrochen hat — dann
 * wurde nichts abgelegt. Sonst `{ id, dateiname, seiten, groesse, betrag }`.
 */
export async function belegAbschluss({ kostenart, vorbereitet, entscheidung,
                                       dup = null }) {
  const zeile = (state.daten.checkliste || []).find(k => k.kostenart === kostenart);

  // N78 — ein Wasserbescheid trägt DREI Bereichsgebühren. Die eine Zahl aus der
  // Bestätigungsmaske kann das nicht abbilden, deshalb hier die Rückfrage —
  // nach der gemeinsamen Maske, nicht an ihrer Stelle.
  //
  // Gefragt wird nur, wenn überhaupt Geld im Spiel ist: ein Infobeleg an der
  // Wasserzeile (Zählerkarte, Anschreiben) hat keine drei Beträge, und ein
  // Pflichtfeld dafür würde ihn schlicht nicht ablegen lassen.
  const w = vorbereitet.ki?.wasser;
  const wasserGeld = (entscheidung.betrag > 0)
    || !!(w && ((w.wasser > 0) || (w.schmutz > 0) || (w.niederschlag > 0)));
  let wasser = null;
  if (istWasserSammel({ kostenart }) && wasserGeld) {
    wasser = await wasserBetraegeDialog({
      kostenart, vorschlag: vorbereitet.ki,
      datei: vorbereitet.aufnahme?.datei, erkennen,
      vorgabe: entscheidung.betrag,
    });
    if (!wasser) return null;                    // abgebrochen — nichts abgelegt
  }
  const betrag = wasser ? wasser.wasser : entscheidung.betrag;

  zeileVerarbeitet(kostenart, 'Beleg wird abgelegt …');
  let ergebnis;
  if (dup?.gefunden && dup.pfad) {
    const res = await api('/dokumente/vorhandenen-zuordnen', { method: 'POST', body: {
      objekt: state.daten.objekt, pfad: dup.pfad, kategorie: 'Nebenkosten',
      kostenart,
      beschreibung: entscheidung.beschreibung
        || vorbereitet.ziel?.beschreibung || kostenart,
      betrag: betrag > 0 ? betrag : null,
      jahr: vorbereitet.ziel?.jahr, zeitraum_id: state.daten.id } });
    if (!res?.id) throw new Error('Der vorhandene Beleg ließ sich nicht zuordnen.');
    ergebnis = { id: res.id, dateiname: res.dateiname || dup.dateiname || '',
                 seiten: 0, groesse: vorbereitet.aufnahme?.datei?.size || 0 };
    melde('Diese Datei lag schon in der Ablage — der vorhandene Beleg wurde '
      + 'verknüpft statt erneut hochgeladen.', 'pos');
  } else {
    ergebnis = await belegAblegen(vorbereitet, entscheidung.beschreibung, betrag);
  }
  if (!ergebnis?.id) throw new Error('Der Beleg wurde nicht abgelegt.');

  // CCCXCV — die erkannte Firma als Anbieter der Kostenart merken. Rein
  // additiv: ein schon gepflegter Anbieter wird nie überschrieben.
  const absender = String(vorbereitet.ki?.absender || '').trim();
  if (absender && !(zeile?.anbieter || '').trim() && zeile?.kostenart_id) {
    await api(`/kostenarten/${zeile.kostenart_id}`,
      { method: 'PATCH', body: { lieferant: absender } }).catch(() => {});
  }

  // Der Beleg wird in seine Kostenposition eingerechnet — dadurch bekommt er
  // seine `position_id` und ist an der Karte wieder auffindbar. Scheitert das
  // (kein Zeitraum, keine Kostenart), darf der Betrag trotzdem nicht verloren
  // gehen: dann wird er direkt geschrieben.
  if (betrag > 0) {
    zeileVerarbeitet(kostenart, 'wird verbucht …');
    try {
      const buchung = await api(`/dokumente/${ergebnis.id}/position`,
                                { method: 'POST' });
      await handanteilKlaeren(zeile, kostenart, buchung);
    } catch {
      await positionBetragSchreiben(zeile, kostenart, betrag);
    }
  }
  if (wasser) {
    zeileVerarbeitet(kostenart, 'Bereiche werden gebucht …');
    await wasserPosBetragSchreiben('schmutz', wasser.schmutz);
    await wasserPosBetragSchreiben('niederschlag', wasser.niederschlag);
  }
  return { ...ergebnis, betrag: betrag > 0 ? betrag : null };
}

/**
 * N280 — der Beleg wird in die Position EINGERECHNET, nicht daraufgesetzt:
 * `betrag = Handanteil + Belegsumme` (`belegposten._rechne`). Das ist richtig,
 * wenn ein Teil der Kosten belegt ist und ein Teil von Hand nachgetragen —
 * aber falsch in dem einen Fall, der im Alltag am häufigsten vorkommt: der
 * Betrag wurde von Hand eingetippt, und JETZT kommt der Beleg dazu, der genau
 * diesen Betrag erklärt. Dann stünden plötzlich 200 € statt 100 €.
 *
 * Stillschweigend das eine oder das andere zu tun wäre beides falsch. Also
 * fragen — aber nur, wenn es überhaupt etwas zu entscheiden gibt, und mit
 * beiden Zahlen im Text (roter Faden: Hinweise bedienbar machen, Kontext in
 * die Aktion). Der Vorgabeweg ist „ersetzen": der Beleg ist die Quelle, die
 * Handeingabe war der Platzhalter.
 */
async function handanteilKlaeren(zeile, kostenart, buchung) {
  const hand = Number(buchung?.handanteil) || 0;
  const belegSumme = Number(buchung?.beleg_summe) || 0;
  if (hand <= 0.005 || belegSumme <= 0.005) return;
  const antwort = await wahl(
    'Betrag war schon eingetragen',
    `Für „${kostenart}" standen ${eur(hand)} von Hand. Zusammen mit dem Beleg `
    + `(${eur(belegSumme)}) ergäbe das ${eur(hand + belegSumme)}.`,
    [{ wert: 'ersetzen', text: `Beleg ersetzt den Betrag — ${eur(belegSumme)}` },
     { wert: 'addieren', text: `Kosten kommen dazu — ${eur(hand + belegSumme)}` }]);
  // Weggeklickt heisst „nichts ändern": die Summe steht schon so da.
  if (antwort !== 'ersetzen') return;
  // Nur den Handanteil streichen: die Belegsumme bleibt, wie sie ist.
  await api(`/positionen/${buchung.position_id}`,
    { method: 'PATCH', body: { betrag: belegSumme } }).catch(() => {});
}

/* Liegt genau diese Datei schon in der Cloud? Nur für eine einzelne PDF
   beantwortbar (die Prüfsumme gilt der Datei, nicht einem Bilderstapel). */
async function duplikatPruefen(dateien, jahr) {
  const leer = { gefunden: false };
  if (dateien.length !== 1) return leer;
  const datei = dateien[0];
  const istPdf = (datei.type || '') === 'application/pdf'
    || /\.pdf$/i.test(datei.name || '');
  if (!istPdf) return leer;
  const sha1 = await sha1Hex(datei).catch(() => null);
  if (!sha1) return leer;
  try {
    return await api('/dokumente/duplikat-pruefen', { method: 'POST', body: {
      objekt: state.daten.objekt, sha1, name: datei.name || '', jahr } }) || leer;
  } catch {
    return leer;                 // Endpunkt/Cloud nicht da → normal ablegen
  }
}

/* Ein Bündel (eine PDF oder ein Stapel Bilder) durch die gemeinsame Kette.
   `false` heisst „abgebrochen" — dann werden weitere Bündel nicht mehr
   angefangen. */
async function belegBuendel(kostenart, dateien) {
  const jahr = Number((state.daten.ende || '').slice(0, 4)) || new Date().getFullYear();
  const dup = await duplikatPruefen(dateien, jahr);
  let deckeWeg = null;
  try {
    const { analyseDecke, belegBestaetigen } = await import('../belegbestaetigung.js');
    const vorbereitet = await belegVorbereiten(dateien, {
      objekt: state.daten.objekt, kategorie: 'Nebenkosten', kostenart, jahr,
      zeitraumId: state.daten.id, titel: kostenart,
      // N263/N280 — die gemeinte Eingabemaske nennen. Gibt es für „nebenkosten"
      // noch keine Feldzuordnung, kommt schlicht nichts zurück und alles bleibt
      // wie zuvor — rein additiv.
      bereich: 'nebenkosten',
    }, () => { deckeWeg = analyseDecke(); });
    if (!vorbereitet) return false;                    // Zuschnitt abgebrochen
    const entscheidung = await belegBestaetigen(vorbereitet, deckeWeg);
    if (!entscheidung) return false;                   // nichts abgelegt
    const ergebnis = await belegAbschluss({ kostenart, vorbereitet,
                                            entscheidung, dup });
    if (!ergebnis) return false;
    melde(`✓ Beleg „${kostenart}“ zugeordnet`, 'pos');
    return true;
  } catch (fehler) {
    melde('Beleg nicht zugeordnet: ' + String(fehler.message || fehler), 'neg');
    return false;
  } finally {
    if (deckeWeg) deckeWeg();
  }
}

/* CCCLXXXVI/N280 — eine oder mehrere Dateien einer NK-Zeile zuordnen.
   Der Drop läuft durch **dieselbe** Kette wie der Foto-/Datei-Knopf. Fotos
   werden zu EINEM mehrseitigen Beleg zusammengefasst, jede PDF bekommt ihre
   eigene Bestätigung — sonst trüge die zweite den Namen und den Betrag der
   ersten. */
export async function belegPerDrop(kostenart, dateien) {
  const istPdf = d => (d.type || '') === 'application/pdf'
    || /\.pdf$/i.test(d.name || '');
  const liste = Array.from(dateien || []);
  const pdfs = liste.filter(istPdf);
  const bilder = liste.filter(d => !istPdf(d) && (d.type || '').startsWith('image/'));
  if (!pdfs.length && !bilder.length) {
    melde('Nur PDF- oder Bilddateien lassen sich hier ablegen.', 'neg');
    return;
  }
  const buendel = bilder.length ? [bilder] : [];
  for (const p of pdfs) buendel.push([p]);
  for (const b of buendel) {
    if (!await belegBuendel(kostenart, b)) break;
  }
  const { laden } = await import('./checkliste.js');
  await laden();
}

/* Drag&Drop nur am Zeiger-Gerät (PC) — Overlay auf `.pruef`. */
export function initBelegDrop() {
  if (!KEINE_KAMERA) return;
  const istDateiZug = e => [...(e.dataTransfer?.types || [])].includes('Files');
  let dropZeile = null;
  const markiere = z => {
    if (z === dropZeile) return;
    dropZeile?.classList.remove('dropziel');
    dropZeile = z || null;
    dropZeile?.classList.add('dropziel');
  };
  state.inhalt.addEventListener('dragover', e => {
    if (!istDateiZug(e)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
    markiere(e.target.closest('.pruef[data-kostenart]'));
  });
  state.inhalt.addEventListener('dragleave', e => {
    if (e.relatedTarget && state.inhalt.contains(e.relatedTarget)) return;
    markiere(null);
  });
  state.inhalt.addEventListener('drop', e => {
    if (!istDateiZug(e)) return;
    e.preventDefault();
    const zeile = e.target.closest('.pruef[data-kostenart]');
    const dateien = [...(e.dataTransfer.files || [])];
    markiere(null);
    if (zeile && dateien.length) belegPerDrop(zeile.dataset.kostenart, dateien);
  });
  document.addEventListener('dragover', e => { if (istDateiZug(e)) e.preventDefault(); });
  document.addEventListener('drop', e => {
    if (istDateiZug(e) && !e.target.closest('.pruef[data-kostenart]')) {
      e.preventDefault();
      markiere(null);
    }
  });
}
