/* N216 — Die Dokumentenliste: Karten rendern, Karte waehlen, die Eingabefelder
   der offenen Karte beleben, das Pruefblatt und das Dokument daneben platzieren.

   Auch die Umschaltung Telefon/Schreibtisch fuer Kamera-Knopf und Dokument-
   Spalte wohnt hier — sie haengt am gleichen Layout wie die Liste. */

import { S, els, ALLE, ANLEGEN } from './state.js';
import { esc } from '../immo.js';
import { auswahlfeld } from '../auswahl.js';
import { lesbareGroesse } from '../scan.js';
import { befund, belegDatumText, betragText, titelVon, jahresliste,
         fertig, dok } from './helpers.js';
import { planZeichnen } from './plan.js';
import { vorschauLaden, vorschauLeeren } from './vorschau.js';
import { erkennungHolen } from './ki.js';
import { kiEinschaetzungZeigen, kiVorbelegungZeigen, kiFelderEinsetzen }
  from './ki.js';
import { posZeigen } from './position.js';
import { zeitraeumeFuellen } from './zeitraum.js';
import { kostenartenFuellen } from './kostenart.js';

/* ---- Eine Karte je Dokument --------------------------------------------- */
export function karte(d) {
  const b = befund(d);
  const gewahlt = S.gewaehlt === d.id;
  const datum = belegDatumText(b);
  const chips = [
    datum ? `<span class="chip"><span class="ci">▤</span>${esc(datum)}</span>`
          : '<span class="chip offen">Datum fehlt</span>',
    b.betrag ? `<span class="chip geld">${esc(betragText(b.betrag))}</span>`
             : '<span class="chip offen">Betrag fehlt</span>',
  ].join('');
  const meta = [d.objekt_name, b.kategorie, b.kostenart,
                d.groesse ? lesbareGroesse(d.groesse) : null]
    .filter(Boolean).join(' · ');
  const marke = d.vermisst
    ? '<span class="marke fehlt">Datei fehlt</span>'
    : d.status === 'neu' ? '<span class="marke">neu</span>' : '';
  // Nur die geschlossene Karte ist ein Knopf. Die offene traegt Eingabefelder —
  // ein Knopf mit Formular darin waere fuer die Sprachausgabe ein Widerspruch.
  return `<article class="beleg${gewahlt ? ' gewaehlt' : ''}" data-id="${d.id}"
        data-status="${esc(d.status)}"
        ${gewahlt ? '' : 'tabindex="0" role="button"'}>
      <div class="kopf">
        <span class="sym">${d.vermisst ? '!' : d.abgelegt ? 'PDF' : '—'}</span>
        <span class="wer">
          <span class="dn">${esc(titelVon(d))}</span>
          <span class="meta">${esc(meta)}</span>
        </span>
        ${gewahlt
          ? `<button type="button" class="kzu" aria-label="Karte schließen"
                     title="Schließen">×</button>`
          : marke}
      </div>
      ${gewahlt ? '' : `<div class="chips">${chips}</div>`}
      ${gewahlt && !d.vermisst ? felder(d, b) : ''}
      ${gewahlt ? '<div data-dokplatz></div>' : ''}
      ${gewahlt ? '<div data-blattplatz></div>' : ''}
    </article>`;
}

/* Die Felder der gewaehlten Karte.
   `data-fach` benennt das Fach, in dem ein Feld sitzt — daran haengen die
   gruene Kennzeichnung (CLXXV) und der Vermerk „Vorschlag" (CLXXVII).
   Das Belegdatum steht tagesgenau (CLXXII); das Jahr daneben ist nur fuer die
   Belege, bei denen der Tag nicht bekannt ist, und weicht dem Datum, sobald
   eines dasteht — dieselbe Angabe zweimal waere eine zu viel. */
export function felder(d, b) {
  return `<div class="felder" data-erfassung>
      <div class="fach" data-fach="objekt"><span class="fl">Immobilie</span>
        <div data-feld="objekt"></div></div>
      <div class="fach" data-fach="kategorie"><span class="fl">Art</span>
        <div data-feld="kategorie"></div></div>
      <div class="fach breit" data-fach="kostenart">
        <span class="fl">Kostenposition</span>
        <div data-feld="kostenart"></div></div>
      <div class="fach" data-fach="belegdatum">
        <span class="fl" id="fl${d.id}d">Datum</span>
        <input data-feld="belegdatum" type="date" aria-labelledby="fl${d.id}d"
               value="${esc(b.belegdatum)}">
      </div>
      <div class="fach" data-fach="jahr"${b.belegdatum ? ' hidden' : ''}>
        <span class="fl">Jahr</span><div data-feld="jahr"></div></div>
      <div class="fach" data-fach="betrag">
        <span class="fl" id="fl${d.id}b">Betrag</span>
        <input data-feld="betrag" inputmode="decimal" placeholder="—"
               aria-labelledby="fl${d.id}b"
               value="${esc(b.betrag ? b.betrag.toFixed(2).replace('.', ',') : '')}">
      </div>
      <div class="fach breit" data-fach="beschreibung">
        <span class="fl" id="fl${d.id}t">Bezeichnung</span>
        <input data-feld="beschreibung" maxlength="60" placeholder="Wofür?"
               aria-labelledby="fl${d.id}t" value="${esc(b.sache)}">
      </div>
    </div>`;
}

/** Die Eingabefelder der gewaehlten Karte — sie leben nur, solange sie offen ist. */
export function erfassungBeleben(karteEl, d, b) {
  const bau = (feld, label, optionen, wert, aenderung) => auswahlfeld(
    karteEl.querySelector(`[data-feld="${feld}"]`),
    { optionen, wert, label, aenderung: aenderung || (() => planZeichnen()) });
  const eingabe = feld => karteEl.querySelector(`input[data-feld="${feld}"]`);
  S.erfassung = {
    id: d.id,
    karte: karteEl,
    // Welche Faecher die Texterkennung gefuellt hat — nur zum Kennzeichnen.
    vorgeschlagen: new Set(),
    // Eine andere Immobilie hat andere Abrechnungszeitraeume und einen anderen
    // Kostenkatalog — beides muss mitkommen, sonst zeigte das Feld daneben auf
    // eine fremde Abrechnung.
    objekt: bau('objekt', 'Immobilie',
                S.daten.objekte.map(o => ({ wert: o.slug, text: o.name })),
                d.objekt || S.daten.objekte[0]?.slug || '',
                () => { kostenartenFuellen(d); zeitraeumeFuellen(d); }),
    kategorie: bau('kategorie', 'Art',
                   S.daten.arten.map(a => ({ wert: a, text: a })),
                   b.kategorie || 'Sonstiges'),
    // Der Katalog kommt aus der API und trifft gleich darauf ein; bis dahin
    // steht wenigstens da, was am Beleg schon vermerkt ist.
    kostenart: bau('kostenart', 'Kostenposition',
                   [{ wert: '', text: 'ohne Position' },
                    ...(b.kostenart
                      ? [{ wert: b.kostenart, text: b.kostenart }] : [])],
                   b.kostenart),
    jahr: bau('jahr', 'Jahr', [{ wert: '', text: 'ohne Jahr' },
      ...jahresliste().map(j => ({ wert: String(j), text: String(j) }))],
      b.jahr ? String(b.jahr) : ''),
    datumFeld: eingabe('belegdatum'),
    betragFeld: eingabe('betrag'),
    textFeld: eingabe('beschreibung'),
  };
  for (const feld of [S.erfassung.betragFeld, S.erfassung.textFeld]) {
    feld.addEventListener('input', planZeichnen);
  }
  // Das Belegdatum ist die genauere Angabe: steht eines da, tritt das
  // Jahresfeld zurueck, und der Abrechnungszeitraum wird neu vorgeschlagen.
  S.erfassung.datumFeld.addEventListener('change', () => {
    jahresfachZeigen();
    zeitraeumeFuellen(d);
  });
  kostenartenFuellen(d);
}

/** Jahr fragen wir nur, solange kein Belegdatum dasteht — sonst stuende
    dieselbe Angabe zweimal auf dem Blatt. */
export function jahresfachZeigen() {
  const fach = S.erfassung && S.erfassung.karte.querySelector('[data-fach="jahr"]');
  if (fach) fach.hidden = Boolean(S.erfassung.datumFeld.value);
}

/** Was der Nutzer gerade eingestellt hat — die Grundlage fuer Vorschau und PATCH. */
export function stand() {
  if (!S.erfassung) return null;
  const zahlText = (S.erfassung.betragFeld.value || '').trim()
    .replace(/[€\s]/g, '').replace(/\.(?=\d{3}\b)/g, '').replace(',', '.');
  const betrag = zahlText ? Number(zahlText) : null;
  const datum = (S.erfassung.datumFeld.value || '').trim();
  return {
    objekt: S.erfassung.objekt.wert(),
    kategorie: S.erfassung.kategorie.wert(),
    kostenart: S.erfassung.kostenart.wert(),
    belegdatum: datum || null,
    jahr: datum ? Number(datum.slice(0, 4))
        : S.erfassung.jahr.wert() ? Number(S.erfassung.jahr.wert()) : null,
    // Ohne Belegdatum bleibt der Monat, den der Dateiname traegt: `undefined`
    // wird beim Uebernehmen nicht mitgeschickt, und was nicht mitkommt, laesst
    // die API stehen.
    monat: datum ? Number(datum.slice(5, 7)) : undefined,
    betrag: Number.isFinite(betrag) && betrag > 0 ? Math.round(betrag * 100) / 100
                                                  : null,
    beschreibung: (S.erfassung.textFeld.value || '').trim(),
    // Der Sentinel „…anlegen" ist keine id — er loest das Anlegen aus und wird
    // gleich durch die echte id ersetzt; bis dahin gilt „ohne Abrechnung".
    zeitraum_id: S.zeitraumFeld && S.zeitraumFeld.wert()
      && S.zeitraumFeld.wert() !== ANLEGEN ? Number(S.zeitraumFeld.wert()) : null,
  };
}

/** CLXXV: was beisammen ist, traegt gruen — was fehlt, bleibt ruhig offen.
    Sind alle Faecher gruen, ist der Beleg fertig zum Einsortieren; das sagt die
    Farbe, ein Satz darueber waere einer zu viel. */
export function feldstandZeigen(s) {
  els.bZeitraum.classList.toggle('gefuellt',
    Boolean(S.zeitraumFeld && S.zeitraumFeld.wert()));
  if (!S.erfassung || !s) return;
  const gefuellt = {
    objekt: s.objekt, kategorie: s.kategorie, kostenart: s.kostenart,
    belegdatum: s.belegdatum, jahr: s.jahr, betrag: s.betrag,
    beschreibung: s.beschreibung,
  };
  for (const [name, wert] of Object.entries(gefuellt)) {
    const fach = S.erfassung.karte.querySelector(`[data-fach="${name}"]`);
    if (!fach) continue;
    fach.classList.toggle('gefuellt', Boolean(wert));
    fach.classList.toggle('vorschlag', S.erfassung.vorgeschlagen.has(name));
  }
}

/* ---- Die Liste neu zeichnen -------------------------------------------- */
export function zeichne() {
  // Pruefblatt und Dokument zuerst in Sicherheit bringen: gleich wird die Liste
  // neu gebaut und alles darin (auch die Blattplaetze) verworfen.
  els.spalteDok.appendChild(els.bDok);
  els.spalteDok.appendChild(els.blatt);
  S.erfassung = null;
  // CCCLXXXIII — nur PDFs zeigen. Alles wird zu PDF gewandelt und erkannt;
  // Fremdformate (Excel, Bilder, …) gehoeren nicht in die Beleg-Uebersicht.
  const dokumente = (S.daten.dokumente || [])
    .filter(d => /\.pdf$/i.test(d.dateiname || ''));
  // Der Kopf-Zaehler zaehlt die tatsaechlich gezeigten PDF-Belege, nicht die
  // Fremdformate, die aus der Liste fallen (CCCLXXXIII).
  els.zahl.textContent = `${dokumente.length} ${dokumente.length === 1 ? 'Beleg' : 'Belege'}`;
  if (!dokumente.length) {
    els.liste.innerHTML = S.daten.gesamt
      ? `<div class="hinweisbox">
           <div class="big">Nichts gefunden</div>
           <p>Zu diesen Filtern liegt kein Dokument vor.</p>
         </div>`
      : `<div class="hinweisbox">
           <div class="big">Noch keine Dokumente</div>
           <p>Fotografiere einen Beleg ab, oder lege Dateien in den Hauptordner
              einer Immobilie — beim nächsten Blick in den Ordner erscheinen
              sie hier.</p>
         </div>`;
    blattZeigen();
    return;
  }
  // Erledigtes tritt zurueck: was zugeordnet ist und — wo es in eine
  // Abrechnung gehoert — seine Kostenposition hat, verstellt oben nur den
  // Blick. Es verschwindet nicht, es klappt zu.
  const offenNoch = dokumente.filter(x => !fertig(x));
  const erledigt = dokumente.filter(fertig);
  // CCCLXX — bleibt oben nichts uebrig, darf das Erledigte nicht zugeklappt
  // bleiben: die Seite sah sonst leer aus, obwohl Treffer da waren.
  const erledigtAuf = S.erledigtOffen || !offenNoch.length;
  els.liste.innerHTML = offenNoch.map(karte).join('')
    + (erledigt.length ? `
      <details class="erledigt" ${erledigtAuf ? 'open' : ''}>
        <summary>${erledigt.length} erledigt</summary>
        <div class="ebox">${erledigt.map(karte).join('')}</div>
      </details>` : '');
  const zeiger = els.liste.querySelector('details.erledigt');
  if (zeiger) zeiger.addEventListener('toggle',
    () => { S.erledigtOffen = zeiger.open; });
  const d = S.gewaehlt !== null ? dok(S.gewaehlt) : null;
  const karteEl = d ? els.liste.querySelector(`[data-id="${d.id}"]`) : null;
  // Ein vermisster Beleg bekommt keine Felder — geaendert werden kann an ihm
  // nichts, solange seine Datei nicht wieder da ist.
  if (karteEl && karteEl.querySelector('[data-erfassung]')) {
    erfassungBeleben(karteEl, d, befund(d));
  }
  blattZeigen();
}

/** Waehlt einen Beleg aus oder gibt ihn frei. */
export function waehle(id) {
  if (S.gewaehlt === id) return;
  S.gewaehlt = id;
  zeichne();
}

/* ---- Pruefblatt & Dokument platzieren --------------------------------
   CCCLXVII: Das Ergebnis-Pruefblatt (#blatt) liegt IMMER unter der gewaehlten
   Karte — so stehen Eingabefelder und Ergebnis links beisammen. Das Dokument
   (#bDok) steht auf breiten Schirmen rechts daneben (sticky), auf schmalen
   rueckt es unter die Karte ueber das Pruefblatt. Ohne Auswahl kehren beide in
   die rechte Spalte zurueck (dort sind sie ausgeblendet). */
const breit = window.matchMedia('(min-width:1180px)');
// Am Schreibtisch wandert „Beleg abfotografieren" in die Werkzeugleiste (siehe
// die Regel dazu im Stilblock): dort bleibt die Handlung erreichbar, ohne eine
// ganze Zeile Hoehe ueber der Arbeitsflaeche zu belegen.
const schreibtisch = window.matchMedia('(min-width:1000px)');

export function blattPlatzieren() {
  const karteEl = S.gewaehlt !== null
    ? els.liste.querySelector(`[data-id="${S.gewaehlt}"]`) : null;
  const platzBlatt = karteEl && karteEl.querySelector('[data-blattplatz]');
  (platzBlatt || els.spalteDok).appendChild(els.blatt);
  // Das Dokument: breit → rechte Spalte, schmal → unter die Karte.
  const platzDok = karteEl && !breit.matches
    && karteEl.querySelector('[data-dokplatz]');
  (platzDok || els.spalteDok).appendChild(els.bDok);
}

export function kameraPlatzieren() {
  const knopf = els.kameraKnopf;
  const leiste = document.querySelector('.werkzeuge');
  if (!knopf || !leiste) return;
  if (schreibtisch.matches) leiste.appendChild(knopf);
  else leiste.parentNode.insertBefore(knopf, leiste.parentNode.firstChild);
}

breit.addEventListener('change', () => { blattPlatzieren(); });
schreibtisch.addEventListener('change', () => { kameraPlatzieren(); });
kameraPlatzieren();

export function blattZeigen() {
  const d = S.gewaehlt !== null ? dok(S.gewaehlt) : null;
  els.blatt.hidden = !d;
  els.bDok.hidden = !d;
  // Ohne Belege in der Liste ist auch die Einladung, einen zu waehlen, keine —
  // dann steht links schon, was zu tun ist.
  els.leerBlatt.hidden = Boolean(d) || !S.daten.dokumente.length;
  blattPlatzieren();
  if (!d) { vorschauLeeren(); els.bLesen.textContent = ''; return; }
  els.bMeldung.textContent = '';
  els.bMeldung.className = 'bmeldung';
  els.bLesen.textContent = '';
  els.bKiMeldung.textContent = '';
  els.bKiMeldung.classList.remove('warn');
  zeitraeumeFuellen(d);
  planZeichnen();
  vorschauLaden(d);
  erkennungHolen(d);
  kiEinschaetzungZeigen(d);
  kiVorbelegungZeigen(d);
  kiFelderEinsetzen(d);
  posZeigen(d);
}

/* ---- Einen Beleg waehlen ---------------------------------------------- */
els.liste.addEventListener('click', e => {
  // Klicks im Pruefblatt oder in den Eingabefeldern waehlen keine Karte.
  if (e.target.closest('.blatt') || e.target.closest('[data-erfassung]')) return;
  const karteEl = e.target.closest('[data-id]');
  if (!karteEl) return;
  const id = Number(karteEl.dataset.id);
  // Die offene Karte am Kopf antippen — oder ihr × — klappt sie wieder zu,
  // damit die naechste darunter in den Blick rueckt (CCLX). Der uebrige Karten-
  // koerper (Felder, Blatt) bleibt vom Zuklappen unberuehrt.
  if (id === S.gewaehlt) {
    if (e.target.closest('.kopf')) waehle(null);
    return;
  }
  waehle(id);
});

els.liste.addEventListener('keydown', e => {
  if (e.key !== 'Enter' && e.key !== ' ') return;
  const karteEl = e.target.closest('.beleg');
  if (!karteEl || e.target !== karteEl) return;
  e.preventDefault();
  waehle(Number(karteEl.dataset.id));
});
