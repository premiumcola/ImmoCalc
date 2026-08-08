/* N216/N280 — Beleg abfotografieren und ersetzen, auf der gemeinsamen Kette.

   Der Dokumenteneingang ist der Ort, an dem Belege ankommen — er darf als
   letzter einen eigenen Ablauf haben. Aufnehmen, Zuschneiden, Auslesen und
   Ablegen kommen deshalb aus `belegscan.js`, die Bestätigungsmaske mit
   Dateinamen und Betrag aus `belegbestaetigung.js`. Hier bleibt nur, was
   diese Seite von den anderen unterscheidet: Immobilie, Art und Jahr stehen
   beim Eingang oft noch nicht fest.

   Deshalb die Zielwahl. Sie ERSETZT die Bestätigungsmaske nicht, sie geht ihr
   voraus — und nur dann, wenn die Kette Immobilie oder Art nicht selbst
   füllen konnte. Was Filter und Erkennung schon wissen, steht darin vorbelegt;
   im Regelfall bleibt ein Tippen. Steht beides fest, entfällt sie ganz und der
   Nutzer sieht direkt die Maske mit dem vorgeschlagenen Dateinamen. Korrigieren
   lassen sich Immobilie und Art danach jederzeit an der Karte in der Liste. */

import { S, els, jetzt, melde } from './state.js';
import { auswahlfeld } from '../auswahl.js';
import { api } from '../immo.js';
import { lesbareGroesse } from '../scan.js';
import { belegVorbereiten, belegAblegen } from '../belegscan.js';
import { belegBestaetigen, analyseDecke } from '../belegbestaetigung.js';
import { jahresliste, dok, titelVon } from './helpers.js';
import { laden } from './aktionen.js';

/* N263/N280 — welche Eingabemaske zu einer Art gehört. Steht die Art schon
   fest (Filter gesetzt oder Beleg vorhanden), kommt die Auslese gleich auf
   deren Feldnamen übersetzt zurück. Rein additiv: kennt der Server den Bereich
   nicht, bleibt die Antwort wie zuvor. Die Zuordnung steht bewusst hier und
   nicht im Import aus `objekt/eintragscan.js` — die dortige Tabelle geht in
   die andere Richtung und hinge die ganze Objektseite mit an diese hier. */
const BEREICH_ZU_ART = {
  Nebenkosten: 'nebenkosten',
  Notarvertrag: 'notarvertraege',
  Kaufvertrag: 'notarvertraege',
  Versicherung: 'versicherungen',
  Kredit: 'kredite',
  Mietvertrag: 'mieten',
  Steuer: 'zahlungen',
  Renovierung: 'renovierungsposten',
};

const bereichFuer = kategorie => BEREICH_ZU_ART[kategorie] || '';

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

  // N254 — Griff auf die Wartedecke. Das `finally` nimmt sie in JEDEM Fall
  // wieder weg; eine hängende Vollbild-Sperre wäre schlimmer als die Lücke.
  let deckeWeg = null;
  try {
    // Eindeutig ist die Immobilie, wenn es nur eine gibt — oder wenn gerade
    // nach einer gefiltert wird. Dasselbe gilt für die Art: wer den Filter auf
    // „Versicherung" gestellt hat, scannt eine Versicherung.
    const einzige = S.daten.objekte.length === 1 ? S.daten.objekte[0].slug : '';
    const kategorie = S.filter.kategorie || '';
    const vorbereitet = await belegVorbereiten(dateien, {
      objekt: S.filter.objekt || einzige,
      kategorie,
      bereich: bereichFuer(kategorie),
      titel: kategorie || 'Beleg',
    }, () => { deckeWeg = analyseDecke(); });
    if (!vorbereitet) throw new Error('abgebrochen');

    // Konnte die Kette Immobilie oder Art nicht füllen, fragt die Zielwahl —
    // vorbelegt mit dem, was die Erkennung gelesen hat.
    if (!vorbereitet.ziel.objekt || !vorbereitet.ziel.kategorie) {
      if (deckeWeg) { deckeWeg(); deckeWeg = null; }
      const wahl = await zielAbfragen(vorbereitet);
      if (!wahl) throw new Error('abgebrochen');
      Object.assign(vorbereitet.ziel, wahl);
    }

    // N250 — der Nutzer sieht, was erkannt wurde, und vor allem den
    // vorgeschlagenen Dateinamen; N267 — dazu den Betrag.
    const entscheidung = await belegBestaetigen(vorbereitet, deckeWeg);
    if (!entscheidung) throw new Error('abgebrochen');

    const ergebnis = await belegAblegen(vorbereitet, entscheidung.beschreibung,
                                        entscheidung.betrag);
    // Erst neu laden, dann melden: `laden()` setzt die Unterzeile des Knopfes
    // selbst zurück und hätte den Namen sonst gleich wieder weggewischt — der
    // Nutzer soll aber genau ihn sehen.
    await laden();
    beschriftung.textContent = '✓ Abgelegt';
    unterzeile.textContent =
      `${ergebnis.dateiname} · ${lesbareGroesse(ergebnis.groesse)}`;
  } catch (fehler) {
    const text = String(fehler.message || fehler);
    beschriftung.textContent = text === 'abgebrochen' ? 'Abgebrochen' : 'Fehlgeschlagen';
    unterzeile.textContent = text === 'abgebrochen' ? 'Nichts hochgeladen' : text;
  } finally {
    if (deckeWeg) { try { deckeWeg(); } catch { /* schon zu */ } }
    setTimeout(() => {
      els.kameraKnopf.disabled = false;
      beschriftung.textContent = 'Beleg abfotografieren';
      unterzeile.textContent = 'Mehrere Seiten möglich · wird als PDF abgelegt';
    }, 3400);
  }
});

/* ---- Neu einscannen: ersetzt den Beleg eines vorhandenen Eintrags ------
   Auch hier die gemeinsame Kette: der Nutzer sieht vorher, was ankommt, was
   erkannt wurde und wie die Datei heissen wird. Abgelegt wird über
   `POST /dokumente/{id}/neu` — der Endpunkt tauscht die Datei und behält den
   Eintrag. Name und Betrag aus der Maske reicht danach ein PATCH nach; ohne
   Änderung bleibt alles, wie es war. */
els.bNeu.addEventListener('click', () => {
  if (S.gewaehlt === null) return;
  els.erneutFeld.click();
});

els.erneutFeld.addEventListener('change', async e => {
  const dateien = [...e.target.files];
  e.target.value = '';
  const id = S.gewaehlt;
  if (!dateien.length || id === null) return;
  const d = dok(id);

  let deckeWeg = null;
  try {
    const kategorie = d?.kategorie || '';
    const vorbereitet = await belegVorbereiten(dateien, {
      objekt: d?.objekt || '',
      kategorie,
      kostenart: d?.kostenart || '',
      jahr: d?.jahr || undefined,
      bereich: bereichFuer(kategorie),
      titel: d ? titelVon(d) : 'Beleg',
    }, () => { deckeWeg = analyseDecke('Die neue Aufnahme wird gelesen …'); });
    if (!vorbereitet) { melde('Abgebrochen'); return; }

    const entscheidung = await belegBestaetigen(vorbereitet, deckeWeg);
    if (!entscheidung) { melde('Abgebrochen'); return; }

    melde('Neue Aufnahme wird abgelegt …');
    const paket = new FormData();
    paket.append('datei', vorbereitet.aufnahme.datei, vorbereitet.aufnahme.name);
    const antwort = await fetch(`/api/dokumente/${id}/neu`,
                                { method: 'POST', body: paket });
    if (!antwort.ok) {
      const grund = await antwort.json().then(k => k.detail).catch(() => null);
      throw new Error(grund || `Fehler ${antwort.status}`);
    }
    let name = (await antwort.json()).dateiname || d?.dateiname || '';

    // Nur was der Nutzer wirklich geändert hat, wandert nach. `beschreibung`
    // ist ohnehin `null`, solange der Vorschlag unangetastet blieb. Der Betrag
    // steht dagegen vorbelegt in der Maske — er zählt als Entscheidung, wenn
    // der Nutzer ihn angefasst hat, sonst füllt er nur eine Lücke. Ein
    // bestehender Betrag wird nie überschrieben, bloss weil eine neue Aufnahme
    // etwas anderes gelesen hat.
    const kiBetrag = typeof vorbereitet.ki?.betrag === 'number'
      ? vorbereitet.ki.betrag : null;
    const nach = {};
    if (entscheidung.beschreibung) nach.beschreibung = entscheidung.beschreibung;
    if (typeof entscheidung.betrag === 'number'
        && (entscheidung.betrag !== kiBetrag || !d?.betrag)) {
      nach.betrag = entscheidung.betrag;
    }
    if (Object.keys(nach).length) {
      const erg = await api(`/dokumente/${id}`, { method: 'PATCH', body: nach });
      name = erg?.dateiname || name;
    }

    await laden();
    melde(`✓ ${name}`, 'gut');
  } catch (fehler) {
    melde('⚠ ' + String(fehler.message || fehler), 'schlecht');
  } finally {
    if (deckeWeg) { try { deckeWeg(); } catch { /* schon zu */ } }
  }
});

/** Wohin gehört der Beleg? Nur Immobilie, Art und Jahr — der Dateiname und der
    Betrag stehen in der Bestätigungsmaske, die gleich danach kommt, und hätten
    hier nur ein zweites Mal gestanden. */
function zielAbfragen({ aufnahme, ziel }) {
  return new Promise(fertig => {
    const dlg = els.zielDlg;
    // Ein direkt gewaehltes PDF traegt keine gezaehlten Seiten (seiten = 0) —
    // dann steht schlicht „PDF" statt „0 Seite".
    const seiten = aufnahme.seiten;
    const mengeText = seiten > 0 ? `${seiten} Seite${seiten > 1 ? 'n' : ''}` : 'PDF';
    els.zielInfo.textContent = `${mengeText} · ${lesbareGroesse(aufnahme.datei.size)}`
      + (S.erkennungMoeglich ? '' : ' · Texterkennung nicht eingerichtet');

    if (!S.zielFelder) {
      S.zielFelder = {
        objekt: auswahlfeld(els.zielObjekt, { label: 'Immobilie' }),
        art: auswahlfeld(els.zielArt, { label: 'Art' }),
        jahr: auswahlfeld(els.zielJahr, { label: 'Jahr' }),
      };
    }
    const { objekt: objektWahl, art: artWahl, jahr: jahrWahl } = S.zielFelder;
    objektWahl.fuelle(S.daten.objekte.map(o => ({ wert: o.slug, text: o.name })),
                      ziel.objekt || S.daten.objekte[0]?.slug || '');
    artWahl.fuelle(S.daten.arten.map(a => ({ wert: a, text: a })),
                   ziel.kategorie || 'Sonstiges');
    jahrWahl.fuelle(jahresliste().map(j => ({ wert: String(j), text: String(j) })),
                    String(ziel.jahr || jetzt));

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
      });
    };
    dlg.showModal();
  });
}
