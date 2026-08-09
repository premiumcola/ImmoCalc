/* N250 — die Bestätigungsmaske nach dem Scan.
 *
 * Zwischen „aufgenommen und ausgelesen" und „abgelegt" tritt der Nutzer noch
 * einmal dazwischen: er sieht, was die Erkennung verstanden hat, sieht die
 * Seite, und sieht vor allem den **vorgeschlagenen Dateinamen** — änderbar,
 * falls die Erkennung danebenlag. Auf dem Telefon ist das die einzige
 * Gelegenheit dafür; danach ist die Datei benannt in der Cloud.
 *
 * Der Name wird NICHT hier gebaut. Er kommt von `/api/dokumente/namensvorschlag`
 * — derselben Funktion, die auch `/scannen` benutzt. Sonst stünden zwei
 * Namensregeln nebeneinander und liefen mit der Zeit auseinander.
 */
import { baueDialog, kiAusleseHtml, esc } from './immo.js';
import { auswahlfeld } from './auswahl.js';
// N267 — DAS eine Betragsfeld der App (Tausenderpunkte, Komma, das Zeichen im
// Feld) statt einer zweiten, eigenen Parser-Logik hier. `geldEingabe`, damit
// der Name nicht mit der lokalen Variable `geldFeld` (dem Element selbst)
// kollidiert.
import { geldFeld as geldEingabe } from './eingabe.js';

/* N254 — die Wartezeit zwischen Zuschnitt und dieser Maske.
 *
 * Dazwischen liegt die KI-Auslese; auf dem Telefon sind das spürbare Sekunden,
 * in denen die Seite noch aussieht wie vorher. Der Nutzer tippt weiter und
 * stört damit den Bildschirm, der gerade kommt. Also eine Decke darüber, die
 * Eingaben WIRKLICH abfängt (ein `dialog` per `showModal` tut genau das) und
 * ruhig sagt, was passiert.
 *
 * Zwei Regeln, die wichtiger sind als das Aussehen:
 *   * Sie geht IMMER wieder weg — im Erfolg wie im Fehler (`finally` beim
 *     Aufrufer). Eine hängende Vollbild-Sperre wäre schlimmer als die Lücke.
 *   * Escape und ein Tippen daneben schliessen sie ebenfalls. Selbst wenn
 *     etwas ganz schiefgeht, sitzt niemand fest.
 */
const GEHIRN_SVG = `
<svg class="ldn-hirn" viewBox="0 0 64 64" fill="none" stroke="currentColor"
     stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"
     aria-hidden="true">
  <path d="M32 13v38"/>
  <path d="M32 17c-2.5-4-7-5-10.5-3S17 21 18 24c-3.5 1-5.5 4-4.5 7.5S18 36 18 36
           c-2 2.5-1.5 6 1 8s6 1.5 7.5-.5c1 3 3.5 4.5 5.5 4"/>
  <path d="M32 17c2.5-4 7-5 10.5-3S47 21 46 24c3.5 1 5.5 4 4.5 7.5S46 36 46 36
           c2 2.5 1.5 6-1 8s-6 1.5-7.5-.5c-1 3-3.5 4.5-5.5 4"/>
  <path class="ldn-ast" d="M32 24h-7M32 33h8M32 42h-6"/>
  <circle class="ldn-punkt" cx="25" cy="24" r="2.4"/>
  <circle class="ldn-punkt" cx="40" cy="33" r="2.4"/>
  <circle class="ldn-punkt" cx="26" cy="42" r="2.4"/>
</svg>`;

/** Legt die Decke über die Seite. Gibt eine Funktion zum Wegnehmen zurück. */
export function analyseDecke(text = 'Der Beleg wird gelesen …') {
  const dlg = baueDialog(
    `<div class="ldn">
       ${GEHIRN_SVG}
       <p class="ldn-text">${esc(text)}</p>
       <p class="ldn-klein">Betrag, Datum und Art werden erkannt.</p>
     </div>`);
  dlg.classList.add('lade-dlg');
  // Tippen daneben nimmt sie weg — Notausgang, falls doch etwas hängt.
  dlg.addEventListener('click', e => { if (e.target === dlg) dlg.close(); });
  let weg = false;
  return () => {
    if (weg) return;
    weg = true;
    try { dlg.close(); } catch { /* schon zu */ }
    dlg.remove();
  };
}

/** Der Dateiname ohne Endung — was als Bezeichnung zurückgeschickt wird.
    `dateiname()` auf dem Server zieht Datum und Betrag ohnehin wieder ab und
    setzt sie neu; die Endung würde dort aber als Teil der Sache hängenbleiben.
    N283(c) — auch der Scan-Weg am Objekt-Formular gibt seinen Namen so ab;
    deshalb exportiert statt ein zweites Mal geschrieben. */
export const ohneEndung = name => String(name || '').replace(/\.[^.\s]+$/, '');

/* N267 — der Betrag aus dem canonical Feld (`eingabe.js::geldFeld`). Dessen
   `.value` liefert schon den rohen, deutschsprachig-getippt aber
   punktgetrennten Wert („87.00", „1234.5") — hier bleibt nur noch runden und
   auf „nichts Brauchbares" prüfen. `null`, wenn das Feld leer ist oder nur
   Unsinn drinsteht — dann bleibt der Beleg ohne Kostenposition. */
function betragVon(el) {
  const zahl = Number(el?.value);
  return Number.isFinite(zahl) && zahl > 0 ? Math.round(zahl * 100) / 100 : null;
}

const betragZeigen = zahl => Number(zahl).toFixed(2).replace('.', ',');

/**
 * N267 — der Kostenposition-Block der Maske.
 *
 * Zwei Fälle, ein Feld:
 *   * Die Erkennung hat einen Betrag → er steht drin und ist änderbar.
 *   * Sie hat keinen → das Feld ist erst zu, ein Knopf macht es auf. Der Nutzer
 *     kann also widersprechen („doch, das ist eine Kostenposition"), ohne dass
 *     ein leeres Pflichtfeld jeden Info-Beleg anmeckert.
 *
 * `teilbetrag`/`teilzahlungen` kommen aus der Auslese (N262): eine
 * Abbuchungsvorankündigung nennt Raten, nicht die Jahressumme. Die Herleitung
 * steht sichtbar daneben — der Nutzer soll sehen, dass 348 € gerechnet und
 * nicht abgelesen sind.
 */
function geldBlock(ki) {
  const betrag = typeof ki?.betrag === 'number' && ki.betrag > 0 ? ki.betrag : null;
  const teil = typeof ki?.teilbetrag === 'number' && ki.teilbetrag > 0
    ? ki.teilbetrag : null;
  const anzahl = Number.isInteger(ki?.teilzahlungen) && ki.teilzahlungen > 1
    ? ki.teilzahlungen : null;
  const herleitung = betrag && teil && anzahl
    ? `${betragZeigen(teil)} € × ${anzahl} = ${betragZeigen(betrag)} €` : '';
  return `
    <div class="sb-name sb-geld"${betrag ? '' : ' data-zu'}>
      <label for="sbBetrag">Kostenposition</label>
      <div class="sb-eur"${betrag ? '' : ' hidden'}>
        <input id="sbBetrag" type="text"
               value="${betrag ? esc(betrag.toFixed(2)) : ''}"
               placeholder="0,00" spellcheck="false" autocomplete="off">
      </div>
      ${herleitung
        ? `<p class="sb-herleitung"><span class="sb-rechnung">${esc(herleitung)}</span>
             hochgerechnet aus den Teilbeträgen — bitte prüfen.</p>` : ''}
      <button type="button" class="sb-doch" data-doch${betrag ? ' hidden' : ''}>
        Betrag eintragen
      </button>
      <p class="sb-hinweis" data-ohne${betrag ? ' hidden' : ''}>Auf dem Beleg
        wurde kein Betrag erkannt — er wird ohne Kostenposition abgelegt.</p>
    </div>`;
}

/**
 * Fragt den Server, wie der Beleg heissen würde. Bei jedem Fehler `''` —
 * die Maske zeigt dann ein leeres Feld statt gar nicht zu erscheinen.
 *
 * N283(c) — exportiert. Nicht jeder Weg endet in dieser Maske: der Scan am
 * Objekt-Formular (`objekt/eintragscan.js`) zeigt sein Dateinamensfeld im
 * Formular selbst und stand deshalb ohne den Vorschlag da — dort stand nur die
 * Bezeichnung aus der Auslese, ohne Datum und Betrag, während die Datei nachher
 * anders hiess. Eine zweite Namensregel im Frontend wäre die falsche Antwort;
 * es ist dieselbe Frage an denselben Endpunkt.
 */
export async function namenHolen(ziel, aufnahme, jahrHinweis) {
  const paket = new FormData();
  paket.append('kategorie', ziel.kategorie || 'Sonstiges');
  if (ziel.kostenart) paket.append('kostenart', ziel.kostenart);
  if (ziel.jahr) paket.append('jahr', String(ziel.jahr));
  if (ziel.beschreibung) paket.append('beschreibung', ziel.beschreibung);
  if (ziel.betrag) paket.append('betrag', String(ziel.betrag));
  if (ziel.datum) paket.append('datum', ziel.datum);
  if (jahrHinweis) paket.append('datei_jahr', String(jahrHinweis));
  paket.append('dateiname_roh', aufnahme?.name || 'scan.pdf');
  try {
    const antwort = await fetch('/api/dokumente/namensvorschlag',
                                { method: 'POST', body: paket });
    if (!antwort.ok) return '';
    return (await antwort.json()).name || '';
  } catch {
    return '';
  }
}

/* N283(b) — der Steckplatz.
 *
 * Bis hierher klickte sich der Nutzer für EINEN Beleg durch bis zu drei
 * Fenster: eine Zielwahl davor (Immobilie/Art/Jahr), diese Maske, und danach
 * einen Toast, der noch etwas nachreichte. Das ist dreimal dieselbe Sache.
 *
 * Deshalb hat die Maske jetzt einen Platz, in den der Aufrufer eigene Felder
 * hängt — sie stehen zwischen Auslese und Dateiname, in derselben Optik wie
 * das Betrags- und das Namensfeld, und ihre Werte kommen in `zusatz` zurück.
 *
 * Ein Feld ist `{ name, label, typ, wert }`:
 *   * `typ: 'wahl'`  — Auswahlfeld (`optionen: [{wert, text}]`), im Design der
 *     App statt eines nativen `<select>`.
 *   * sonst          — Textfeld (`platzhalter` optional).
 *   * `imNamen: true` — die Angabe geht in den Dateinamen ein (Art, Jahr,
 *     Kostenart). Ändert sie sich, holt die Maske den Vorschlag neu; das Feld
 *     bleibt unangetastet, sobald der Nutzer selbst darin getippt hat.
 *
 * `name` ist bewusst der Schlüssel im `ziel` (`kategorie`, `jahr`, `objekt` …):
 * so lässt sich der geänderte Stand ohne Übersetzungstabelle an den
 * Namensvorschlag weiterreichen.
 */
function zusatzFelderHtml(felder) {
  return felder.map((f, i) => `
    <div class="sb-name">
      <label${f.typ === 'wahl' ? '' : ` for="sbz${i}"`}>${esc(f.label)}</label>
      ${f.typ === 'wahl'
        ? `<div data-zwahl="${i}"></div>`
        : `<input id="sbz${i}" type="text" value="${esc(f.wert ?? '')}"
             data-zfeld="${i}" placeholder="${esc(f.platzhalter || '')}"
             spellcheck="false" autocomplete="off">`}
      ${f.hinweis ? `<p class="sb-hinweis">${esc(f.hinweis)}</p>` : ''}
    </div>`).join('');
}

/* Ein Hinweis, der zur Entscheidung gehört (Duplikat, Anhänger) — im Fenster
   statt als Toast hinterher. Ruhig gesetzt, farbig nur wenn er etwas ändert. */
function hinweisHtml(h) {
  if (!h?.text) return '';
  const farbe = h.ton === 'warn' ? 'var(--amber)'
    : h.ton === 'gut' ? 'var(--pos)' : 'var(--soft)';
  return `<p class="sb-hinweis" style="color:${farbe}">${esc(h.text)}</p>`;
}

/* N283(b) — die Vorschau einer gezogenen PDF.
 *
 * Die Maske zeigte nur `blaetter` — die entzerrten Bilder aus dem Kamerascan.
 * Wer am Rechner eine PDF auf die Zeile zieht (der Hauptweg dort), sah gar
 * nichts und sollte trotzdem bestätigen, dass „der Beleg" richtig benannt ist.
 * Die Datei liegt als Blob vor; der Browser zeichnet sie selbst. */
const istPdf = datei => (datei?.type || '') === 'application/pdf'
  || /\.pdf$/i.test(datei?.name || '');

/**
 * Zeigt die Maske und wartet auf die Entscheidung.
 *
 * `vorbereitet` ist das Paket aus `belegVorbereiten`. `optionen` (N283 b):
 *   * `titel`   — Überschrift, Vorgabe „Beleg prüfen und ablegen".
 *   * `knopf`   — Beschriftung der Bestätigung, Vorgabe „Ablegen". Beim
 *     Neueinscannen steht dort „Ersetzen", bei einer schon vorhandenen Datei
 *     „Verknüpfen": der Knopf sagt, was passiert.
 *   * `hinweis` — `{ text, ton }`, gehört zur Entscheidung (Duplikat …).
 *   * `felder`  — der Steckplatz, siehe `zusatzFelderHtml`.
 *
 * Gibt zurück:
 *   * `{ beschreibung, betrag, zusatz }` — ablegen; `beschreibung` ist `null`,
 *     wenn der Nutzer den Vorschlag unverändert gelassen hat (dann benennt der
 *     Server wie eh), sonst der geänderte Name. `zusatz` trägt die Werte der
 *     eingehängten Felder.
 *   * `null` — abgebrochen, es wird nichts abgelegt.
 */
export async function belegBestaetigen(vorbereitet, deckeWeg = null,
                                       optionen = {}) {
  const { aufnahme, ziel, jahrHinweis, ki } = vorbereitet;
  const felder = optionen.felder || [];
  // Der Stand der eingehängten Felder — von Anfang an vollständig, damit der
  // Aufrufer auch dann etwas zurückbekommt, wenn nichts angefasst wurde.
  const zusatz = {};
  for (const f of felder) zusatz[f.name] = f.wert ?? '';
  const zielJetzt = () => ({ ...ziel, ...zusatz });
  const vorschlag = await namenHolen(zielJetzt(), aufnahme, jahrHinweis);
  // N254 — die Decke bleibt bis hierhin liegen (auch der Namensvorschlag ist
  // eine kurze Wartezeit) und geht erst weg, wenn die Maske wirklich kommt.
  if (deckeWeg) { try { deckeWeg(); } catch { /* egal */ } }

  // Dieselbe Darstellung wie im Beleg-Fenster (immo.js) — der Nutzer erkennt
  // den Block wieder. `aus_db` bleibt weg: das hier ist frisch gelesen.
  const kiHtml = ki ? kiAusleseHtml(ki) : '';
  const blaetter = aufnahme?.blaetter || [];
  // Das Feld steht IMMER da und ist immer benutzbar. Fällt der Vorschlag aus
  // (Server älter als N250 oder nicht erreichbar) oder hat die Erkennung nichts
  // Genaues gefunden, kommt wenigstens die Kostenart hinein — sonst stünde der
  // Nutzer vor einem leeren Feld genau dann, wenn er es am ehesten braucht.
  // Was hier steht, geht als Bezeichnung zurück; benannt wird auf dem Server.
  const startwert = vorschlag || ziel.beschreibung || ziel.kostenart || '';

  // Etwas zu sehen gibt es immer, wenn eine Datei da ist: die Blätter aus dem
  // Kamerascan — oder die gezogene PDF selbst (N283 b).
  const pdfVorschau = !blaetter.length && istPdf(aufnahme?.datei);
  const zeigeFlaeche = blaetter.length > 0 || pdfVorschau;

  const dlg = baueDialog(
    `<div class="beleg-kopf">
       <span class="bt">${esc(optionen.titel || 'Beleg prüfen und ablegen')}${
         ziel.kostenart
           ? `<span class="bpfad">${esc(ziel.kostenart)}</span>` : ''}</span>
       <button class="bx" data-ab title="Abbrechen" aria-label="Abbrechen">✕</button>
     </div>
     <div class="beleg-ki"${kiHtml ? '' : ' hidden'}>${kiHtml}</div>
     ${hinweisHtml(optionen.hinweis)}
     ${zusatzFelderHtml(felder)}
     ${geldBlock(ki)}
     <div class="sb-name">
       <label for="sbName">Dateiname</label>
       <input id="sbName" type="text" value="${esc(startwert)}"
              placeholder="Bezeichnung des Belegs"
              spellcheck="false" autocapitalize="off" autocomplete="off">
       <p class="sb-hinweis">${vorschlag
         ? 'Wird so in der Nextcloud abgelegt. Stimmt die Erkennung, einfach ablegen.'
         : 'Die Erkennung hat nichts Genaues gefunden — hier lässt sich der Name '
           + 'ergänzen, damit der Beleg später wiederzufinden ist.'}</p>
     </div>
     ${zeigeFlaeche ? '<div class="beleg-flaeche" data-blaetter></div>' : ''}
     <div class="sb-fuss">
       <button type="button" class="sb-weiter" data-ok>${
         esc(optionen.knopf || 'Ablegen')}</button>
     </div>`);
  dlg.classList.add('beleg-dlg', 'scanbest-dlg');
  // Mit eingehängten Feldern wird das Fenster länger als der Schirm. Ohne
  // eigenen Überlauf klemmte der Knopf unten ausserhalb — auf dem Telefon
  // wäre die Maske dann nicht mehr abschliessbar.
  if (felder.length || optionen.hinweis) {
    dlg.style.overflowY = 'auto';
    // Scrollt das Fenster, muss die Entscheidung trotzdem in Reichweite
    // bleiben — sonst sucht man auf dem Telefon den Knopf, den man drücken soll.
    const fuss = dlg.querySelector('.sb-fuss');
    if (fuss) {
      fuss.style.position = 'sticky';
      fuss.style.bottom = '0';
      fuss.style.background = 'var(--sheet)';
      fuss.style.paddingTop = '8px';
      // Der Innenrand des Fensters gehört beim Scrollen zur Fläche: ohne diese
      // Verlängerung schöbe sich der Beleg unter dem Knopf hindurch ins Bild.
      fuss.style.paddingBottom = 'calc(12px + env(safe-area-inset-bottom))';
      fuss.style.marginBottom = 'calc(-12px - env(safe-area-inset-bottom))';
    }
  }

  // Die Seiten als Bilder — genau das, was gleich hochgeladen wird.
  const adressen = [];
  const flaeche = dlg.querySelector('[data-blaetter]');
  if (flaeche && pdfVorschau) {
    const adr = URL.createObjectURL(aufnahme.datei);
    adressen.push(adr);
    if (navigator.pdfViewerEnabled === false) {
      // Ein Browser ohne eingebauten Betrachter zeichnete sonst eine grosse
      // graue Leerfläche. Dann lieber der Weg zum Inhalt als das Loch.
      const kasten = document.createElement('div');
      kasten.className = 'beleg-blatt leer';
      kasten.style.cssText = 'flex-direction:column; gap:10px; color:var(--soft)';
      kasten.innerHTML = `${esc(aufnahme.name || 'PDF')}
        <a class="beleg-tab" href="${adr}" target="_blank" rel="noopener"
           >Im neuen Tab ansehen ↗</a>`;
      flaeche.appendChild(kasten);
    } else {
      // Die Fläche gibt die Höhe vor und scrollt NICHT selbst: der Betrachter
      // im Rahmen bringt seinen eigenen Balken mit, und zwei Balken nebeneinander
      // sind einer zu viel.
      flaeche.style.cssText = 'height:min(40dvh, 420px); min-height:170px; '
        + 'overflow:hidden';
      const rahmen = document.createElement('iframe');
      rahmen.className = 'beleg-blatt';
      rahmen.title = aufnahme.name || 'Beleg';
      rahmen.style.cssText = 'flex:1 1 auto; width:100%; height:100%';
      // Ohne die Anhänge zeichnet der Browser seine eigene schwarze Leiste mit
      // Seitenvorschau, Zoom, Drucken und Herunterladen mitten in eine ruhige
      // Maske — und nimmt der Seite die halbe Fläche. Hier soll nur der Beleg
      // stehen; entschieden wird darunter.
      rahmen.src = `${adr}#toolbar=0&navpanes=0&scrollbar=0&view=FitH`;
      flaeche.appendChild(rahmen);
    }
  } else if (flaeche) {
    blaetter.forEach((blob, i) => {
      const adr = URL.createObjectURL(blob);
      adressen.push(adr);
      const bild = document.createElement('img');
      bild.className = 'beleg-bild';
      bild.alt = `Seite ${i + 1}`;
      bild.src = adr;
      flaeche.appendChild(bild);
    });
  }

  return new Promise(erfuellen => {
    let entschieden = false;
    const schliessen = (wert) => {
      if (entschieden) return;
      entschieden = true;
      dlg.close();
      erfuellen(wert);
    };
    const feld = dlg.querySelector('#sbName');
    const geldFeld = dlg.querySelector('#sbBetrag');
    // N267 — DAS eine Betragsfeld der App: Tausenderpunkte, Komma statt Punkt,
    // das €-Zeichen im Feld. Bindet auch, während `.sb-eur` noch `hidden`
    // steht — das Element ist im DOM, nur unsichtbar; die Formatierung greift
    // dann sofort, sobald „Betrag eintragen" es aufmacht.
    const geldGriff = geldFeld ? geldEingabe(geldFeld) : null;

    /* N283(b) — die eingehängten Felder. Sie stehen im Fenster, nicht davor:
       eine Zielwahl als eigener Dialog fragt dasselbe eine Ebene früher und
       zwingt den Nutzer, dieselbe Datei zweimal einzuordnen.

       Was in den Dateinamen eingeht (`imNamen`), holt den Vorschlag neu — die
       Maske zeigt live, wie die Datei nach der Änderung heisst. Getippt der
       Nutzer selbst im Namensfeld, bleibt seine Fassung stehen: eine Auswahl
       darf eine Eingabe nie überschreiben. */
    let letzterVorschlag = startwert;
    const namenAuffrischen = async () => {
      if (!felder.some(f => f.imNamen)) return;
      if ((feld?.value || '') !== letzterVorschlag) return;   // selbst getippt
      const neu = await namenHolen(
        { ...zielJetzt(), betrag: betragVon(geldFeld) || ziel.betrag },
        aufnahme, jahrHinweis);
      if (!neu || !feld || feld.value !== letzterVorschlag) return;
      feld.value = neu;
      letzterVorschlag = neu;
    };

    felder.forEach((f, i) => {
      if (f.typ === 'wahl') {
        const halter = dlg.querySelector(`[data-zwahl="${i}"]`);
        if (!halter) return;
        auswahlfeld(halter, {
          optionen: f.optionen || [], wert: String(f.wert ?? ''), label: f.label,
          aenderung: wert => {
            zusatz[f.name] = f.zahl ? Number(wert) : wert;
            namenAuffrischen();
          },
        });
        if (f.zahl) zusatz[f.name] = Number(zusatz[f.name]) || null;
        return;
      }
      const eingabe = dlg.querySelector(`[data-zfeld="${i}"]`);
      eingabe?.addEventListener('input', () => { zusatz[f.name] = eingabe.value; });
      eingabe?.addEventListener('change', namenAuffrischen);
    });

    // N267 — „doch, das ist eine Kostenposition": das Feld aufmachen und den
    // Hinweis wegnehmen, der gerade das Gegenteil behauptet hat.
    dlg.querySelector('[data-doch]')?.addEventListener('click', e => {
      e.target.hidden = true;
      dlg.querySelector('[data-ohne]').hidden = true;
      const huelle = dlg.querySelector('.sb-eur');
      huelle.hidden = false;
      dlg.querySelector('.sb-geld').removeAttribute('data-zu');
      geldFeld?.focus();
    });

    const ablegen = () => {
      const neu = (feld?.value || '').trim();
      // Unverändert heisst: der Server benennt wie gewohnt. Nur eine echte
      // Änderung gegenüber dem, was im Feld stand, wird mitgeschickt.
      schliessen({
        beschreibung: (!neu || neu === letzterVorschlag) ? null : ohneEndung(neu),
        // `null` heisst ausdrücklich „ohne Kostenposition" — auch dann, wenn
        // die Erkennung einen Betrag vorgeschlagen hatte und der Nutzer ihn
        // wieder herausgelöscht hat. Der Aufrufer soll beides unterscheiden
        // können, deshalb steht der Schlüssel immer da.
        betrag: betragVon(geldFeld),
        // N283(b) — die Werte der eingehängten Felder. Ohne Steckplatz bleibt
        // das Objekt leer; kein Aufrufer muss etwas daran ändern.
        zusatz,
      });
    };
    dlg.querySelector('[data-ok]').addEventListener('click', ablegen);
    feld?.addEventListener('keydown', e => {
      if (e.key === 'Enter') { e.preventDefault(); ablegen(); }
    });
    dlg.querySelector('[data-ab]').addEventListener('click', () => schliessen(null));
    // Tippen daneben und Escape brechen ab — nichts wird abgelegt.
    dlg.addEventListener('click', e => { if (e.target === dlg) schliessen(null); });
    dlg.addEventListener('close', () => {
      adressen.forEach(adr => URL.revokeObjectURL(adr));
      try { geldGriff?.zerstoere(); } catch { /* Dialog geht ohnehin weg */ }
      schliessen(null);
    });
  });
}
