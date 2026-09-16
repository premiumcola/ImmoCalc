/* N479 — „Wie wird gerechnet?" als Erklärung dort, wo gerechnet wird.

   Die Übersicht stand bisher als eigener Punkt in den Einstellungen. Dort war
   sie falsch: sie ist keine Einstellung, es gibt nichts zu schalten. Nutzer:
   „Rechenlogik und Verteilerschlüssel sollte stattdessen als Information im
   Nebenkosten-Bereich auftauchen."

   Das Modul bringt seinen eigenen Stil mit (`stilEinbauen`, nach dem Vorbild
   von `installHilfeStil` in immo.js) — so lässt sich der Knopf auf jeder Seite
   setzen, ohne den CSS-Block mitzukopieren. */
import { baueDialog } from './immo.js';

const STIL = `
.rlinfo{display:inline-flex;align-items:center;gap:6px;border:none;
        background:var(--teal-l);color:var(--teal-d);border-radius:999px;
        padding:7px 12px;min-height:34px;cursor:pointer;
        font:600 11.5px var(--body);letter-spacing:.01em}
.rlinfo:hover{background:#D2E6E0}
.rlinfo:focus-visible{outline:2px solid var(--teal);outline-offset:2px}
.rlinfo svg{width:14px;height:14px;flex:none}
.rl-dlg .dbody,dialog.immo-dlg.rl-dlg{max-height:min(82dvh,820px)}
.rl-inhalt{max-height:min(68dvh,700px);overflow:auto;margin:0 -2px;padding:0 2px}
.rl-vor{font:400 12.5px var(--body);color:var(--soft);line-height:1.5;
        margin:0 0 14px}
.rlschritt{display:flex;gap:11px;background:var(--sheet);border-radius:12px;
           padding:12px 13px;margin-bottom:8px}
.rlnum{flex:none;width:27px;height:27px;border-radius:9px;background:var(--teal-l);
       color:var(--teal-d);font:600 13px var(--mono);display:flex;
       align-items:center;justify-content:center}
.rlnum.sm{width:23px;height:23px;border-radius:7px;font-size:11.5px}
.rltxt{min-width:0}
.rltitel{font:600 13.5px var(--disp);letter-spacing:-.01em;margin-bottom:4px}
.rlbeschr{font:400 12px var(--body);color:var(--soft);line-height:1.55}
.rlbeschr b{color:var(--ink);font-weight:600}
/* Formelkasten: monospace, teal, bricht bei schmalem Schirm um statt zu
   überlaufen. display:block, damit der Abstand am inline-Element greift. */
.rlformel{display:block;background:var(--teal-l);color:var(--teal-d);
          border-radius:10px;padding:10px 12px;margin-top:9px;
          font:500 11.5px var(--mono);line-height:1.65;word-break:break-word}
.rlformel b{color:var(--teal-d);font-weight:600}
.rlkarte{background:var(--sheet);border-radius:12px;padding:11px 13px;
         margin-bottom:7px}
.rlkkopf{display:flex;align-items:center;gap:9px;margin-bottom:7px}
.rlkname{font:600 13px var(--disp);letter-spacing:-.01em}
.rlkformel{display:block;font:500 11px var(--mono);color:var(--soft);
           line-height:1.55;word-break:break-word}
.rluruhig{background:var(--sheet);border-radius:12px;padding:12px 13px;
          margin-top:8px}
.rllabel{font:600 10px var(--mono);letter-spacing:.07em;text-transform:uppercase;
         color:var(--soft);margin:16px 0 7px}`;

const SCHRITTE = [
  ['Zeitraum festlegen',
   `Start- und Enddatum frei wählen — regulär, Rumpf- oder
    Zwischenabrechnung. Das Enddatum ist der <b>Soll-Stichtag</b>, auf den alle
    Zähler bezogen werden.`],
  ['Betrag je Position bestimmen',
   `Je nach Wertquelle: <b>Scan / extern</b> — der Betrag steht auf der
    Rechnung und wird übernommen. <b>Zähler</b> — der Verbrauch wird auf den
    Stichtag interpoliert, nicht gemessene Zähler als Rest berechnet.
    <b>Manuell</b> — freie Position, etwa eine Gutschrift.`,
   `Interpolierter Verbrauch = Ist-Differenz × Soll-Tage / Ist-Tage<br>
    146,874 × 365 / 376 = <b>142,577</b>`],
  ['Auf die Parteien verteilen',
   `Jede Position trägt genau einen Verteilerschlüssel (siehe unten).
    Beispiel Wasser: Rate = Kosten / Gesamtverbrauch, der Anteil einer Partei
    ist ihr Verbrauch × Rate.`],
  ['Ergebnis je Partei',
   `Alle Anteile einer Partei aufsummieren, die Vorauszahlungen gegenrechnen.
    Haushaltsnahe Leistungen nach <b>§ 35a</b> werden separat ausgewiesen.`,
   'Saldo = umgelegte Kosten − Vorauszahlungen'],
];

const SCHLUESSEL = [
  ['Nach Wohnfläche',
   'Anteil = Kosten × Fläche der Einheit / Gesamtfläche'],
  ['Nach Personen',
   'Anteil = Kosten × Personen der Partei / Gesamtpersonen'],
  ['Nach Bewohnermonaten',
   `Bewohnermonate = Personen × anwesende Monate<br>
    Anteil = Kosten × Bewohnermonate der Partei / Summe aller Bewohnermonate`],
  ['Nach Einheiten', 'Anteil = Kosten / Anzahl Einheiten'],
  ['Nach Verbrauch',
   'Rate = Kosten / Gesamtverbrauch<br>Anteil = Verbrauch der Partei × Rate'],
  ['Fester Prozent-Split',
   'Anteil = Kosten × Prozentsatz (z. B. 2. OG 50 %)'],
  ['Individuell / Direktzuordnung',
   'Ganze Position genau einer Partei (z. B. Gartenwasser)'],
  ['Heizkosten (HeizkostenV)',
   `Grundanteil nach Fläche + Verbrauchsanteil nach Wärmezählern
    (typ. 30/70 oder 50/50)`],
];

const SYMBOL = `<svg viewBox="0 0 24 24" aria-hidden="true" fill="none"
  stroke="currentColor" stroke-width="1.9" stroke-linecap="round"
  stroke-linejoin="round"><circle cx="12" cy="12" r="9"/>
  <path d="M12 11v5.4M12 7.6h.01"/></svg>`;

let stilDa = false;
function stilEinbauen() {
  if (stilDa) return;
  stilDa = true;
  const s = document.createElement('style');
  s.textContent = STIL;
  document.head.appendChild(s);
}

/* Der Knopf als Markup-Schnipsel — er wird in eine Kopfzeile eingesetzt und
   bei jedem Neuzeichnen mit ersetzt. Deshalb hängt der Klick-Lauscher nicht
   am Knopf, sondern über `rechenlogikFaenger()` am Dokument. */
export function rechenlogikKnopf(text = 'Wie wird gerechnet?') {
  stilEinbauen();
  return `<button type="button" class="rlinfo" data-rechenlogik>${SYMBOL}${text}</button>`;
}

export function rechenlogikOeffnen() {
  stilEinbauen();
  const schritte = SCHRITTE.map(([titel, text, formel], i) => `
    <div class="rlschritt">
      <span class="rlnum">${i + 1}</span>
      <div class="rltxt">
        <div class="rltitel">${titel}</div>
        <div class="rlbeschr">${text}</div>
        ${formel ? `<span class="rlformel">${formel}</span>` : ''}
      </div>
    </div>`).join('');

  const schluessel = SCHLUESSEL.map(([name, formel], i) => `
    <div class="rlkarte">
      <div class="rlkkopf"><span class="rlnum sm">${i + 1}</span>
        <span class="rlkname">${name}</span></div>
      <span class="rlkformel">${formel}</span>
    </div>`).join('');

  const dlg = baueDialog(`
    <div class="dt">Wie wird gerechnet?</div>
    <div class="rl-inhalt">
      <p class="rl-vor">So kommt jede Nebenkostenabrechnung zustande — von der
        Rechnung bis zum Saldo je Partei. Rechnen musst du nichts davon selbst;
        die Übersicht zeigt, was ImmoCalc im Hintergrund tut.</p>
      <div class="rllabel">Vier Schritte je Abrechnung</div>
      ${schritte}
      <div class="rllabel">Die acht Verteilerschlüssel</div>
      ${schluessel}
      <div class="rluruhig">
        <div class="rltitel" style="margin-bottom:4px">Zeitanteiligkeit</div>
        <div class="rlbeschr">Querliegend über alle Schlüssel: Deckt die
          Nutzungszeit einer Partei nicht den ganzen Zeitraum ab, wird ihr
          Anteil taggenau gekürzt.</div>
        <span class="rlformel">Faktor = Nutzungstage der Partei / Tage im Zeitraum</span>
      </div>
    </div>`);
  dlg.classList.add('rl-dlg');
  return dlg;
}

/* Ein delegierter Lauscher am Dokument — einmal pro Seite aufrufen. Nötig,
   weil die Kopfzeilen bei jedem Neuzeichnen neu gebaut werden und ein Lauscher
   am Knopf selbst dabei verloren ginge. */
let faengerDa = false;
export function rechenlogikFaenger() {
  if (faengerDa) return;
  faengerDa = true;
  document.addEventListener('click', e => {
    if (e.target.closest('[data-rechenlogik]')) rechenlogikOeffnen();
  });
}
