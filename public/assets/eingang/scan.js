/* N216 — Beleg abfotografieren und ersetzen (CCCLXXI).

   <input capture> oeffnet auf iOS direkt die Kamera. Die Aufnahmen werden im
   Browser verkleinert und zu einem PDF zusammengesetzt; die Texterkennung
   liest die erste Seite und schlaegt Sache, Datum und Betrag vor. Steht die
   Immobilie fest und ist die Art erkannt, wird ohne Rueckfrage abgelegt —
   sonst kommt der Ziel-Dialog. */

import { S, els, jetzt, melde } from './state.js';
import { auswahlfeld } from '../auswahl.js';
import { lesbareGroesse } from '../scan.js';
import { kamerascanStarten, istBildDatei } from '../kamerascan.js';
import { datumText, betragText, jahresliste } from './helpers.js';
import { laden } from './aktionen.js';

/* Bilder gehen durch den Zuschnitt (Kanten erkennen, entzerren, PDF bauen); ein
   schon fertiges PDF (aus der Dateiauswahl am PC statt aus der Kamera) laeuft
   ohne Zuschnitt direkt durch — dieselbe Aufteilung wie in `belegscan.js`.
   `null` = der Nutzer hat den Zuschnitt abgebrochen. */
async function belegPdf(dateien) {
  // N42 — dieselbe robuste Aufteilung wie in belegscan.js: iOS-Fotos mit leerem
  // `type` gelten als Bild (sonst fielen sie durch und der Zuschnitt bliebe aus).
  const bilder = dateien.filter(istBildDatei);
  const pdf = dateien.find(d => (d.type || '') === 'application/pdf'
                             || /\.pdf$/i.test(d.name || ''));
  if (bilder.length) {
    const s = await kamerascanStarten(bilder);
    return s ? { pdf: s.pdf, name: 'scan.pdf', seiten: s.seiten, quelle: bilder[0] } : null;
  }
  if (pdf) return { pdf, name: pdf.name, seiten: 0, quelle: pdf };
  return null;
}

async function erkenne(bild) {
  if (!S.erkennungMoeglich || !bild) return null;
  try {
    const paket = new FormData();
    // Mit echtem Namen — so erkennt der Server ein PDF an der Endung.
    paket.append('datei', bild, bild.name || 'seite.jpg');
    const antwort = await fetch('/api/dokumente/erkennen',
                                { method: 'POST', body: paket });
    return antwort.ok ? await antwort.json() : null;
  } catch {
    return null;
  }
}

/* ---- Beleg abfotografieren --------------------------------------------- */
els.kameraKnopf.addEventListener('click', () => els.kameraFeld.click());

els.kameraFeld.addEventListener('change', async () => {
  const dateien = [...els.kameraFeld.files];
  els.kameraFeld.value = '';
  if (!dateien.length) return;

  const beschriftung = els.kameraKnopf.querySelector('.k1');
  const unterzeile = els.kameraKnopf.querySelector('.k2');
  els.kameraKnopf.disabled = true;
  beschriftung.textContent = 'Verarbeite …';
  unterzeile.textContent = `${dateien.length} Aufnahme${dateien.length > 1 ? 'n' : ''}`;

  try {
    // Bilder werden zugeschnitten, ein gewaehltes PDF geht direkt durch.
    const aufnahme = await belegPdf(dateien);
    if (!aufnahme) throw new Error('abgebrochen');
    const { pdf, seiten, name } = aufnahme;
    const erkannt = await erkenne(aufnahme.quelle);
    // Eindeutig ist die Immobilie, wenn es nur eine gibt — oder wenn gerade
    // nach einer gefiltert wird.
    const einzige = S.daten.objekte.length === 1 ? S.daten.objekte[0].slug : '';
    const objekt = S.filter.objekt || einzige;
    const kategorie = erkannt?.kategorie || '';
    const vorgabe = { objekt, kategorie, jahr: erkannt?.jahr || jetzt,
                      beschreibung: erkannt?.sache || '' };

    const auswahl = (objekt && kategorie) ? vorgabe
      : await zielAbfragen(seiten, pdf.size, vorgabe, erkannt);
    if (!auswahl) throw new Error('abgebrochen');

    const paket = new FormData();
    paket.append('objekt', auswahl.objekt);
    paket.append('kategorie', auswahl.kategorie);
    paket.append('jahr', String(auswahl.jahr));
    paket.append('beschreibung', auswahl.beschreibung);
    // Datum und Betrag der Texterkennung wandern mit — sie gehoeren an den
    // Anfang und an das Ende des Dateinamens (CXXIII, CXXX).
    if (erkannt?.datum) paket.append('datum', erkannt.datum);
    if (erkannt?.monat) paket.append('monat', String(erkannt.monat));
    if (erkannt?.betrag) paket.append('betrag', String(erkannt.betrag));
    paket.append('datei', pdf, name);

    const antwort = await fetch('/api/dokumente/scannen',
      { method: 'POST', body: paket });
    if (!antwort.ok) {
      const grund = await antwort.json().then(k => k.detail).catch(() => null);
      throw new Error(grund || `Fehler ${antwort.status}`);
    }
    const ergebnis = await antwort.json();
    beschriftung.textContent = '✓ Abgelegt';
    unterzeile.textContent = `${ergebnis.dateiname} · ${lesbareGroesse(pdf.size)}`;
    await laden();
  } catch (fehler) {
    const text = String(fehler.message || fehler);
    beschriftung.textContent = text === 'abgebrochen' ? 'Abgebrochen' : 'Fehlgeschlagen';
    unterzeile.textContent = text === 'abgebrochen' ? 'Nichts hochgeladen' : text;
  } finally {
    setTimeout(() => {
      els.kameraKnopf.disabled = false;
      beschriftung.textContent = 'Beleg abfotografieren';
      unterzeile.textContent = 'Mehrere Seiten möglich · wird als PDF abgelegt';
    }, 3400);
  }
});

/* ---- Neu einscannen: ersetzt den Beleg eines vorhandenen Eintrags ------ */
els.bNeu.addEventListener('click', () => {
  if (S.gewaehlt === null) return;
  els.erneutFeld.click();
});

els.erneutFeld.addEventListener('change', async e => {
  const dateien = [...e.target.files];
  e.target.value = '';
  const id = S.gewaehlt;
  if (!dateien.length || id === null) return;
  try {
    // Bilder zuschneiden, ein gewaehltes PDF direkt uebernehmen.
    const aufnahme = await belegPdf(dateien);
    if (!aufnahme) { melde('Abgebrochen'); return; }
    melde('Neue Aufnahme wird abgelegt …');
    const paket = new FormData();
    paket.append('datei', aufnahme.pdf, aufnahme.name);
    const antwort = await fetch(`/api/dokumente/${id}/neu`,
                                { method: 'POST', body: paket });
    if (!antwort.ok) {
      const grund = await antwort.json().then(k => k.detail).catch(() => null);
      throw new Error(grund || `Fehler ${antwort.status}`);
    }
    const ergebnis = await antwort.json();
    await laden();
    melde('✓ ' + ergebnis.hinweis, 'gut');
  } catch (fehler) {
    melde('⚠ ' + String(fehler.message || fehler), 'schlecht');
  }
});

/** Ein Schritt, nicht drei: alles Noetige in einem Dialog, vorbelegt mit dem,
    was die Texterkennung gelesen hat. */
function zielAbfragen(seiten, groesse, vorgabe, erkannt) {
  return new Promise(fertig => {
    const dlg = els.zielDlg;
    const gelesen = erkannt?.kategorie || erkannt?.betrag
      ? ` · erkannt: ${[erkannt.sache, datumText(erkannt.jahr, erkannt.monat),
          betragText(erkannt.betrag)].filter(Boolean).join(' · ')}`
      : S.erkennungMoeglich ? '' : ' · Texterkennung nicht eingerichtet';
    // Ein direkt gewaehltes PDF traegt keine gezaehlten Seiten (seiten = 0) — dann
    // steht schlicht „PDF" statt „0 Seite".
    const mengeText = seiten > 0 ? `${seiten} Seite${seiten > 1 ? 'n' : ''}` : 'PDF';
    els.zielInfo.textContent =
      `${mengeText} · ${lesbareGroesse(groesse)}${gelesen}`;

    if (!S.zielFelder) {
      S.zielFelder = {
        objekt: auswahlfeld(els.zielObjekt, { label: 'Immobilie' }),
        art: auswahlfeld(els.zielArt, { label: 'Art' }),
        jahr: auswahlfeld(els.zielJahr, { label: 'Jahr' }),
      };
    }
    const { objekt: objektWahl, art: artWahl, jahr: jahrWahl } = S.zielFelder;
    objektWahl.fuelle(S.daten.objekte.map(o => ({ wert: o.slug, text: o.name })),
                      vorgabe.objekt || S.daten.objekte[0]?.slug || '');
    artWahl.fuelle(S.daten.arten.map(a => ({ wert: a, text: a })),
                   vorgabe.kategorie || 'Sonstiges');
    jahrWahl.fuelle(jahresliste().map(j => ({ wert: String(j), text: String(j) })),
                    String(vorgabe.jahr));
    els.zielText.value = vorgabe.beschreibung || '';

    let entschieden = false;
    const abbruch = () => { if (!entschieden) fertig(null); };
    dlg.addEventListener('close', abbruch, { once: true });
    els.zielOk.onclick = () => {
      entschieden = true;
      dlg.close();
      fertig({
        objekt: objektWahl.wert(),
        kategorie: artWahl.wert(),
        jahr: Number(jahrWahl.wert()),
        beschreibung: els.zielText.value.trim(),
      });
    };
    dlg.showModal();
  });
}
