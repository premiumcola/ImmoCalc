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
    setzt sie neu; die Endung würde dort aber als Teil der Sache hängenbleiben. */
const ohneEndung = name => String(name || '').replace(/\.[^.\s]+$/, '');

/** Fragt den Server, wie der Beleg heissen würde. Bei jedem Fehler `''` —
    die Maske zeigt dann ein leeres Feld statt gar nicht zu erscheinen. */
async function namenHolen(ziel, aufnahme, jahrHinweis) {
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

/**
 * Zeigt die Maske und wartet auf die Entscheidung.
 *
 * `vorbereitet` ist das Paket aus `belegVorbereiten`. Gibt zurück:
 *   * `{ beschreibung }` — ablegen; `beschreibung` ist `null`, wenn der Nutzer
 *     den Vorschlag unverändert gelassen hat (dann benennt der Server wie eh),
 *     sonst der geänderte Name.
 *   * `null` — abgebrochen, es wird nichts abgelegt.
 */
export async function belegBestaetigen(vorbereitet, deckeWeg = null) {
  const { aufnahme, ziel, jahrHinweis, ki } = vorbereitet;
  const vorschlag = await namenHolen(ziel, aufnahme, jahrHinweis);
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

  const dlg = baueDialog(
    `<div class="beleg-kopf">
       <span class="bt">Beleg prüfen und ablegen${ziel.kostenart
         ? `<span class="bpfad">${esc(ziel.kostenart)}</span>` : ''}</span>
       <button class="bx" data-ab title="Abbrechen" aria-label="Abbrechen">✕</button>
     </div>
     <div class="beleg-ki"${kiHtml ? '' : ' hidden'}>${kiHtml}</div>
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
     ${blaetter.length
       ? '<div class="beleg-flaeche" data-blaetter></div>' : ''}
     <div class="sb-fuss">
       <button type="button" class="sb-weiter" data-ok>Ablegen</button>
     </div>`);
  dlg.classList.add('beleg-dlg', 'scanbest-dlg');

  // Die Seiten als Bilder — genau das, was gleich hochgeladen wird.
  const adressen = [];
  const flaeche = dlg.querySelector('[data-blaetter]');
  if (flaeche) {
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
    const ablegen = () => {
      const neu = (feld?.value || '').trim();
      // Unverändert heisst: der Server benennt wie gewohnt. Nur eine echte
      // Änderung gegenüber dem, was im Feld stand, wird mitgeschickt.
      schliessen({ beschreibung: (!neu || neu === startwert)
        ? null : ohneEndung(neu) });
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
      schliessen(null);
    });
  });
}
