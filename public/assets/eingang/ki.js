/* N216 — Texterkennung und KI-Auslese am gewaehlten Beleg (CLXXVII, CCLXXIII,
   CCLXXIV, CCCLXVII).

   `/dokumente/{id}/erkennen` liest Betrag, Datum, Art und Sache aus der Datei
   in der Cloud — auch aus einem Text-PDF. Gefragt wird fuer den einen Beleg,
   den der Nutzer gerade offen hat, und nur einmal je Beleg (Cache in S).

   Die KI-Einschaetzung (Kosten? / Nebenkosten? / Zeitraum) und die
   KI-Vorbelegung (Mieter/Kaltmiete, Police/Beitrag, Darlehen/Restschuld,
   Grundsteuer …) sind dezente Bloecke unter den Feldern — nur da, wenn die KI
   etwas geliefert hat. „KI-Analyse neu starten" laesst den Beleg erneut lesen,
   nachdem etwa der API-Schluessel hinterlegt wurde. */

import { S, els } from './state.js';
import { api, esc } from '../immo.js';
import { KI_UEBERNAHME, kiLabel, kiWert, zahlAus, dok } from './helpers.js';
import { planZeichnen } from './plan.js';
import { jahresfachZeigen } from './liste.js';
import { kostenartenFuellen } from './kostenart.js';
import { zeitraeumeFuellen } from './zeitraum.js';

/* Hilfs-Bausteine — bewusst hier, weil ausschliesslich dieses Modul sie nutzt. */
const jaNeinMarke = (label, ja) =>
  `<span class="kitag ${ja ? 'ja' : 'nein'}">${esc(label)}: ${ja ? 'ja' : 'nein'}</span>`;
const infoMarke = (label, wert) =>
  `<span class="kitag">${esc(label)}: ${esc(wert)}</span>`;
const kiZeile = (label, wert) =>
  `<div class="bkizeile"><span class="bkik">${esc(label)}</span>` +
  `<span class="bkiv">${esc(wert)}</span></div>`;

/* ---- Anzeige der reinen Lese-Meldung ------------------------------------ */
export function erkennungZeigen(d) {
  const eintrag = S.erkanntJeBeleg.get(d.id) || {};
  els.bLesen.textContent = eintrag.zustand === 'laeuft'
    ? 'Der Beleg wird gelesen …' : (eintrag.grund || '');
  els.bLesen.classList.toggle('warn',
    eintrag.zustand !== 'laeuft' && Boolean(eintrag.grund));
}

/* CCLXXIII/CCCLXVII: die KI-Einschaetzung dezent unter den Feldern zeigen —
   Marken (Kosten? · Nebenkosten? · Zeitraum) und der zusammenfassende Satz.
   Die Marken kommen aus der frischen Analyse; die Zusammenfassung notfalls aus
   dem am Beleg gespeicherten Text (`ki_einordnung`). Fehlt alles, bleibt der
   Block aus. */
export function kiEinschaetzungZeigen(d) {
  const w = ((S.erkanntJeBeleg.get(d.id) || {}).werte) || {};
  const text = (((w.zusammenfassung || w.einordnung) || d.ki_einordnung) || '').trim();
  const marken = [];
  if (w.kosten_relevant === true || w.kosten_relevant === false)
    marken.push(jaNeinMarke('Kosten', w.kosten_relevant));
  if (w.nebenkosten === true || w.nebenkosten === false)
    marken.push(jaNeinMarke('Nebenkosten', w.nebenkosten));
  if (w.zeitraum_hinweis) marken.push(infoMarke('Zeitraum', w.zeitraum_hinweis));
  els.bEinTags.innerHTML = marken.join('');
  els.bEinText.textContent = text;
  els.bEin.hidden = !(text || marken.length);
}

/* ---- CCLXXIV: KI-Vorbelegung -------------------------------------------
   Die KI-Auslese legt am Beleg `ki_immobilie`, `ki_einheit` und `ki_felder`
   ab (typspezifisch). Hier werden sie kompakt gezeigt — der Nutzer bestaetigt
   nur noch. Fuer Versicherung/Kredit/Mietvertrag/Steuer, wo der eigentliche
   Datensatz-Weg noch aussteht, heisst der Block „bereit zum Uebernehmen". */
export function kiVorbelegungZeigen(d) {
  const felder = d.ki_felder || {};
  const eintraege = Object.entries(felder).filter(([, v]) =>
    v !== null && v !== undefined && typeof v !== 'object'
    && String(v).trim() !== '');
  const ort = [d.ki_immobilie, d.ki_einheit].filter(Boolean).join(' · ');
  if (!eintraege.length && !ort) {
    els.bKi.hidden = true; els.bKi.innerHTML = ''; return;
  }
  const art = d.kategorie || (d.vorschlag || {}).kategorie || '';
  const titel = KI_UEBERNAHME.has(art) ? 'Bereit zum Übernehmen' : 'KI-Vorbelegung';
  const zeilen = [];
  if (ort) zeilen.push(kiZeile('Immobilie', ort));
  for (const [k, v] of eintraege) zeilen.push(kiZeile(kiLabel(k), kiWert(k, v)));
  els.bKi.innerHTML =
    `<div class="bkikopf"><span class="bkisym" aria-hidden="true">✦</span>` +
    `<span class="bkitit">${esc(titel)}</span></div>` +
    `<div class="bkiliste">${zeilen.join('')}</div>`;
  els.bKi.hidden = false;
}

/** CCLXXIV: die KI-Felder belegen leere Eingaben vor — der Betrag hier, die
    Kostenposition in `kostenartenFuellen`. Getipptes bleibt unangetastet. */
export function kiFelderEinsetzen(d) {
  if (!S.erfassung || S.erfassung.id !== d.id) return;
  const betrag = zahlAus((d.ki_felder || {}).betrag);
  if (betrag && !S.erfassung.betragFeld.value.trim()) {
    S.erfassung.betragFeld.value = betrag.toFixed(2).replace('.', ',');
    S.erfassung.vorgeschlagen.add('betrag');
    planZeichnen();
  }
}

/** Die frischen KI-Angaben in die Kopie des Dokuments uebernehmen — damit
    Raster (Vorbelegung) und Einschaetzung mit dem Gelesenen uebereinstimmen,
    ohne auf ein volles Neuladen zu warten. Nur, was die KI wirklich lieferte. */
export function kiWerteUebernehmen(d, w) {
  if (!w) return;
  if (w.felder) d.ki_felder = w.felder;
  if (w.immobilie) d.ki_immobilie = w.immobilie;
  if (w.einheit) d.ki_einheit = w.einheit;
  const satz = (w.zusammenfassung || w.einordnung || '').trim();
  if (satz) d.ki_einordnung = satz;
}

export async function erkennungHolen(d) {
  if (!S.erkennungMoeglich || !d.abgelegt || d.vermisst) return;
  if (!S.erkanntJeBeleg.has(d.id)) {
    S.erkanntJeBeleg.set(d.id, { zustand: 'laeuft' });
    erkennungZeigen(d);
    try {
      const werte = await api(`/dokumente/${d.id}/erkennen`);
      S.erkanntJeBeleg.set(d.id,
        { zustand: 'fertig', werte, grund: werte.hinweis || '' });
      kiWerteUebernehmen(dok(d.id) || d, werte);
    } catch (fehler) {
      S.erkanntJeBeleg.set(d.id,
        { zustand: 'fertig', grund: String(fehler.message || fehler) });
    }
  }
  if (S.gewaehlt !== d.id) return;          // inzwischen etwas anderes gewaehlt
  erkennungZeigen(d);
  kiEinschaetzungZeigen(d);                 // die KI-Einschaetzung kann jetzt da sein
  kiVorbelegungZeigen(d);                   // das Raster ggf. mit frischen Werten
  vorschlagEinsetzen(d);
}

/** Was gelesen wurde, wandert in die leeren Felder. Was der Beleg selbst
    schon hergibt — aus seinem Namen oder aus frueherer Zuordnung —, bleibt
    unangetastet: die Erkennung schlaegt vor, sie korrigiert nicht. */
export function vorschlagEinsetzen(d) {
  const w = (S.erkanntJeBeleg.get(d.id) || {}).werte;
  if (!w || !S.erfassung || S.erfassung.id !== d.id) return;
  const merke = fach => S.erfassung.vorgeschlagen.add(fach);
  if (w.betrag && !S.erfassung.betragFeld.value.trim()) {
    S.erfassung.betragFeld.value = w.betrag.toFixed(2).replace('.', ',');
    merke('betrag');
  }
  if (w.datum && !S.erfassung.datumFeld.value) {
    S.erfassung.datumSetzen(w.datum);
    jahresfachZeigen();
    merke('belegdatum');
  }
  if (w.sache && !S.erfassung.textFeld.value.trim()) {
    S.erfassung.textFeld.value = w.sache;
    merke('beschreibung');
  }
  if (w.kategorie && !d.kategorie) {
    S.erfassung.kategorie.setze(w.kategorie);
    merke('kategorie');
  }
  kostenartenFuellen(d);      // die Sache kann eine Position nahelegen
  zeitraeumeFuellen(d);       // das Datum kann den Zeitraum aendern
}

/* ---- KI-Analyse neu starten (CCCLXVII) ------------------------------------
   Liest den Beleg erneut ueber die KI ein — z. B. nachdem der API-Schluessel
   hinterlegt wurde. Ohne Schluessel/Guthaben sagt der Server ehrlich, dass
   keine KI-Einschaetzung kam; die Seite bricht nicht, es entstehen keine Daten. */
els.bKiNeu.addEventListener('click', async () => {
  const d = S.gewaehlt !== null ? dok(S.gewaehlt) : null;
  if (!d || !d.abgelegt || d.vermisst) return;
  const vorher = els.bKiNeu.innerHTML;
  els.bKiNeu.disabled = true;
  els.bKiNeu.textContent = 'KI liest den Beleg …';
  els.bKiMeldung.textContent = '';
  els.bKiMeldung.classList.remove('warn');
  try {
    const w = await api(`/dokumente/${d.id}/neu-analysieren`, { method: 'POST' });
    S.erkanntJeBeleg.set(d.id, { zustand: 'fertig', werte: w, grund: w.hinweis || '' });
    kiWerteUebernehmen(d, w);
    // Sagt die frische Analyse, dass keine echten Kosten entstanden sind, darf
    // ein nur vorgeschlagener Betrag nicht stehen bleiben (die Geraete-Kennung).
    if (w.ki_gelaufen && w.kosten_relevant === false && S.erfassung
        && S.erfassung.id === d.id && S.erfassung.vorgeschlagen.has('betrag')) {
      S.erfassung.betragFeld.value = '';
      S.erfassung.vorgeschlagen.delete('betrag');
    }
    els.bKiMeldung.textContent = w.meldung || '';
    els.bKiMeldung.classList.toggle('warn', !w.ki_gelaufen);
    if (S.gewaehlt === d.id) {
      erkennungZeigen(d);
      kiEinschaetzungZeigen(d);
      kiVorbelegungZeigen(d);
      vorschlagEinsetzen(d);
      kiFelderEinsetzen(d);
      planZeichnen();
    }
  } catch (fehler) {
    els.bKiMeldung.textContent = '⚠ ' + String(fehler.message || fehler);
    els.bKiMeldung.classList.add('warn');
  } finally {
    els.bKiNeu.disabled = false;
    els.bKiNeu.innerHTML = vorher;
  }
});
