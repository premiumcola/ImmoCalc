/* N216 — Seiten-Orchestrierung des Dokumenten-Eingangs.

   `laden()` holt die gefilterte Liste vom Server und stoesst die Neuzeichnung
   an. `fussnoteZeigen` fuellt den Wachdienst-/OCR-Hinweis unter dem Kamera-
   Knopf. `nkKontextInit` uebernimmt Filter aus dem NK-Kontext-Sprung
   (CCLXXXIII/CCCLXXII). Die Handlungsknoepfe „Ordner einlesen" (CXXVII),
   „Uebernehmen" und „Entfernen" wohnen ebenfalls hier — sie sind die letzte
   Meile eines gewaehlten Belegs. */

import { S, els, belegmeldung } from './state.js';
import { api, esc } from '../immo.js';
import { filterFuellen } from './filter.js';
import { zeichne, stand } from './liste.js';

/* ---- Die Liste vom Server holen und die Seite frisch aufbauen ---------- */
export async function laden() {
  const abfrage = new URLSearchParams();
  for (const [schluessel, wert] of Object.entries(S.filter)) {
    if (wert) abfrage.set(schluessel, wert);
  }
  try {
    S.daten = await api('/dokumente?' + abfrage.toString());
    const { anzahl, gesamt, offen, vermisst } = S.daten;
    const stimmen = [];
    if (offen) stimmen.push(`${offen} ${offen === 1 ? 'wartet' : 'warten'}`);
    if (vermisst) stimmen.push(`${vermisst} vermisst`);
    els.sub.textContent = stimmen.length ? stimmen.join(' · ')
      : gesamt ? 'alles einsortiert' : 'noch nichts abgelegt';
    els.zahl.textContent = anzahl === gesamt
      ? `${gesamt} ${gesamt === 1 ? 'Dokument' : 'Dokumente'}`
      : `${anzahl} von ${gesamt}`;
    // Ein Beleg, der aus der gefilterten Liste gefallen ist, kann nicht
    // gewaehlt bleiben — sonst zeigte das Pruefblatt ins Leere.
    if (S.gewaehlt !== null
        && !S.daten.dokumente.find(d => d.id === S.gewaehlt)) S.gewaehlt = null;
    filterFuellen();
    zeichne();
    // Ohne Immobilie gibt es keinen Ort fuer einen Beleg — dann gleich sagen,
    // was fehlt, statt die Kamera ins Leere laufen zu lassen.
    const ohneObjekt = !S.daten.objekte.length;
    els.kameraKnopf.disabled = ohneObjekt;
    els.kameraKnopf.querySelector('.k2').textContent = ohneObjekt
      ? 'Erst eine Immobilie anlegen'
      : 'Mehrere Seiten möglich · wird als PDF abgelegt';
  } catch (fehler) {
    els.sub.textContent = 'nicht erreichbar';
    els.liste.innerHTML = `<div class="hinweisbox">
        <div class="big">Ablage nicht verfügbar</div>
        <p>${esc(String(fehler.message || fehler))}</p>
      </div>`;
  }
}

/* ---- Fussnote: Wachdienst und Texterkennung, jede Information einmal --- */
export async function fussnoteZeigen() {
  const teile = [];
  let warnung = false;
  try {
    const w = await api('/dokumente/wachdienst');
    const wann = w.letzter_lauf
      ? new Date(w.letzter_lauf).toLocaleTimeString('de-DE',
          { hour: '2-digit', minute: '2-digit' })
      : null;
    teile.push(w.letzter_fehler
      ? `Ordner werden alle ${w.takt_minuten} min geprüft · zuletzt fehlgeschlagen`
      : wann
      ? `Ordner geprüft alle ${w.takt_minuten} min · zuletzt ${wann} Uhr`
      : `Ordner werden alle ${w.takt_minuten} min geprüft`);
    // N290 — der zweite, schnelle Takt: er zieht die Verknüpfung nach, wenn
    // Dateien ausserhalb der App umbenannt oder verschoben wurden. Für den
    // Nutzer ist genau das die Frage „wie lange dauert es, bis es passt?".
    if (w.abgleich_takt_minuten) {
      teile.push(`Umzüge alle ${w.abgleich_takt_minuten} min nachgezogen`
        + (w.nachgezogen_gesamt ? ` (${w.nachgezogen_gesamt})` : ''));
    }
    warnung = Boolean(w.letzter_fehler);
  } catch { /* ohne API keine Fussnote */ }
  try {
    const e = await api('/dokumente/erkennung');
    S.erkennungMoeglich = Boolean(e.verfuegbar);
    if (!S.erkennungMoeglich) {
      teile.push('Texterkennung ist auf diesem Server nicht eingerichtet — '
                 + 'Datum, Art und Betrag bitte selbst eintragen');
      warnung = true;
    }
  } catch { /* Zustand unbekannt: dann eben ohne Hinweis */ }
  els.fussnote.textContent = teile.join(' · ');
  els.fussnote.classList.toggle('warn', warnung);
}

/* ---- Ordner einlesen -----------------------------------------------------
   Ein Knopf, nicht zwei: der Abgleich (CXXVII) nimmt neue Dateien auf wie der
   alte Scanlauf und zieht zusaetzlich die vorhandenen Eintraege nach — zwei
   Knoepfe nebeneinander, von denen einer alles kann, waeren nur eine Frage
   mehr. Was er getan hat, steht danach in einer ruhigen Zeile darunter. */
els.pruefKnopf.addEventListener('click', async () => {
  els.pruefKnopf.disabled = true;
  els.pruefKnopf.textContent = 'Lese ein …';
  els.bilanz.hidden = false;
  els.bilanz.className = 'bilanz';
  els.bilanz.textContent = 'Die Ordner werden gelesen …';
  try {
    const e = await api('/dokumente/abgleich', { method: 'POST' });
    const umgezogen = e.verschoben.length + e.umbenannt.length;
    const teile = [`${e.geprueft} geprüft`];
    if (e.neu) teile.push(`${e.neu} neu` + (e.automatisch
      ? ` · ${e.automatisch} davon einsortiert` : ''));
    if (umgezogen) teile.push(`${umgezogen} nachgezogen`);
    if (e.vermisst.length) teile.push(`${e.vermisst.length} vermisst`);
    if (e.wiederda.length) teile.push(`${e.wiederda.length} wieder da`);
    if (teile.length === 1) teile.push('alles unverändert');
    const zeilen = [teile.join(' · '), ...e.hinweise.slice(0, 3)];
    els.bilanz.innerHTML = zeilen
      .map(z => `<span class="zeile">${esc(z)}</span>`).join('');
    els.bilanz.classList.toggle('warn',
      Boolean(e.vermisst.length || e.hinweise.length));
    await laden();
  } catch (fehler) {
    const text = String(fehler.message || fehler);
    els.bilanz.className = 'bilanz warn';
    els.bilanz.innerHTML = `<span class="zeile">${esc(text)}</span>`
      + (/nextcloud|cloud|zugangsdaten/i.test(text)
        ? '<span class="zeile"><a href="settings.html">Zu den Einstellungen</a></span>'
        : '');
  } finally {
    els.pruefKnopf.disabled = false;
    els.pruefKnopf.textContent = 'Ordner einlesen';
  }
});

/* ---- Uebernehmen: Ablage und Zeitraum in einem Schritt ---------------- */
els.bOk.addEventListener('click', async () => {
  const d = S.gewaehlt !== null
    ? S.daten.dokumente.find(x => x.id === S.gewaehlt) : null;
  const s = stand();
  if (!d || !s) return;
  els.bOk.disabled = true;
  const vorher = els.bOk.textContent;
  els.bOk.textContent = 'Wird einsortiert …';
  try {
    const antwort = await api(`/dokumente/${d.id}`, { method: 'PATCH', body: s });
    // Der Beleg ist eingeordnet — dann gehoert das Pruefblatt dem naechsten, der
    // noch wartet. Bleibt er stehen, sieht es aus, als waere nichts passiert.
    const naechster = S.daten.dokumente.find(
      x => x.id !== d.id && (x.status === 'neu' || x.vermisst));
    S.gewaehlt = naechster ? naechster.id : null;
    await laden();
    belegmeldung((antwort.verschoben ? '✓ ' : '✓ unverändert · ') + antwort.pfad
          + (naechster ? ' · weiter mit dem nächsten' : ''), 'gut');
  } catch (fehler) {
    els.bOk.disabled = false;
    els.bOk.textContent = vorher;
    belegmeldung('⚠ ' + String(fehler.message || fehler), 'schlecht');
  }
});

/* ---- Entfernen: erst fragen, dann tun --------------------------------- */
function sicherZuruecksetzen() {
  clearTimeout(S.sicherUhr);
  delete els.bWeg.dataset.sicher;
  els.bWeg.classList.remove('frage');
  els.bWeg.textContent = '⌫';
}

els.bWeg.addEventListener('click', async () => {
  const d = S.gewaehlt !== null
    ? S.daten.dokumente.find(x => x.id === S.gewaehlt) : null;
  if (!d) return;
  if (els.bWeg.dataset.sicher !== 'ja') {
    els.bWeg.dataset.sicher = 'ja';
    els.bWeg.textContent = 'Wirklich?';
    els.bWeg.classList.add('frage');
    belegmeldung('Der Eintrag verschwindet aus der App — '
          + 'die Datei bleibt in der Nextcloud.');
    clearTimeout(S.sicherUhr);
    S.sicherUhr = setTimeout(sicherZuruecksetzen, 4000);
    return;
  }
  sicherZuruecksetzen();
  els.bWeg.disabled = true;
  try {
    await api(`/dokumente/${d.id}`, { method: 'DELETE' });
    S.gewaehlt = null;
    await laden();
  } catch (fehler) {
    belegmeldung('⚠ ' + String(fehler.message || fehler), 'schlecht');
  } finally {
    els.bWeg.disabled = false;
  }
});

/* CCLXXXIII/CCCLXXII — aus einer NK-Abrechnung hierher gesprungen: Objekt +
   Jahr vorfiltern, Warte-Belege zeigen, Rueckweg anbieten. Das Pruefblatt
   ordnet den gewaehlten Beleg dann wie im Dokumentenmodus zu (mit Zeitraum-
   Vorschlag). */
export function nkKontextInit() {
  const p = new URLSearchParams(location.search);
  const objekt = p.get('objekt') || '';
  const kostenart = p.get('kostenart') || '';
  const ziel = p.get('zuordnenZeitraum') || '';
  const jahr = p.get('jahr') || '';
  if (!objekt && !kostenart && !ziel) return;
  // Auf Objekt + Jahr vorfiltern, NICHT auf die Kostenart: die NK-Checkliste
  // nutzt einen anderen Katalog (Heizkosten/Warmwasser) als die normalisierten
  // Dokument-Kostenarten (Heizung/Heizoel) — ein Kostenart-Filter traefe hier oft
  // nichts. Die Ziel-Kostenart nennt stattdessen der Banner.
  if (objekt) S.filter.objekt = objekt;
  // CCCLXXII — mit dem Abrechnungsjahr landet die Auswahl gleich am richtigen
  // Ordner (…/60_Nebenkosten/<Jahr>). Der Status bleibt offen (alle), damit auch
  // bereits abgelegte Belege des Ordners waehlbar sind, nicht nur wartende.
  if (jahr) S.filter.jahr = jahr;
  let zurueck = p.get('zurueck') || '';
  if (!/^\/?zeitraum\.html\?/.test(zurueck)) zurueck = 'nebenkosten.html';
  const el = els.nkKontext;
  el.innerHTML = `<span class="kx">☁</span>
    <span>Beleg für die Abrechnung wählen${kostenart
      ? ` — <strong>${esc(kostenart)}</strong>` : ''}${jahr
      ? ` · Ordner <strong>${esc(jahr)}</strong>` : ''}. Antippen öffnet das
      Prüfblatt wie bei einem neuen Beleg.</span>
    <a class="zur" href="${esc(zurueck)}">← zurück zur Abrechnung</a>`;
  el.hidden = false;
}
