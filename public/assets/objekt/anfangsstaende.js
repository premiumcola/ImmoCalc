/* N216/N390/N394 — die Zähler-Übersichtskarte unter den Abrechnungszeit-
   räumen (`erststandHtml`). Der Anfangsstand hängt an KEINEM Zeitraum — er
   ist der Stand vor der ersten Abrechnung.

   N390 — der eigene Erfassungs-Dialog ist entfallen: `zeitraum/zaehler-
   konfig.js` konnte Anfangsstände schon immer mit erfassen (Name,
   Messeinheit, Bezug, Kostenart, Verrechnung UND Anfangsstand — alles am
   selben Zähler).

   N394 — „Zähler konfigurieren" (eigene Zeile in der Zeitraum-Liste) und
   diese Karte öffneten seit N390 exakt denselben Dialog über zwei getrennte
   Zugänge — eine Dopplung im Zugang, nicht nur im Text. Jetzt EINE Karte,
   die je nach Stand der Anfangsstände unterschiedlich formuliert ist, aber
   den Zähler-Konfigurator immer vollständig erreichbar hält (auch wenn kein
   Zähler einen Anfangsstand braucht — dann bliebe sonst kein Weg mehr
   hinein). `laden.js` fügt keine eigene „Zähler konfigurieren"-Zeile mehr
   in die Zeitraum-Liste ein. */

import { esc } from '../immo.js';
import { HAKEN_ICON } from '../objekt-baum.js?v=2';
import { istGrundstueck } from '../objekt-state.js?v=2';
import { GAUGE_ICON, zaehlerListe, erststandZiel } from './state.js';

const KONFIG_HINWEIS = 'Benennen, Einheiten zuordnen, Verrechnung festlegen.';

export function erststandHtml(zielId) {
  if (istGrundstueck()) return '';
  // Nur gemessene, aktive Zähler brauchen einen Anfangsstand.
  // N141b — `rest` errechnet sich, `direkt` traegt den fertigen Periodenverbrauch
  // statt eines Zaehlerstands (N120): beide brauchen keinen Anfangsstand. Vorher
  // mahnte die Zeile dauerhaft zwei Zaehler an, bei denen nie etwas zu tun ist.
  const OHNE_ANFANG = new Set(['rest', 'direkt']);
  const mess = (zaehlerListe || []).filter(
    z => z.aktiv !== false && !OHNE_ANFANG.has(z.typ));
  const ohne = mess.filter(z => !z.anfangsstand);

  if (!zaehlerListe.length) {
    const zielAttr = zielId != null ? ` data-z="${esc(String(zielId))}"` : '';
    return `<button class="erststand offen" data-erststand="1"${zielAttr}>
        <span class="es-ik">${GAUGE_ICON}</span>
        <span class="es-tx">
          <span class="es-t">Zähler konfigurieren</span>
          <span class="es-d">Noch keine Zähler angelegt — ${esc(KONFIG_HINWEIS
            .toLowerCase())} und den Anfangsstand vor der ersten Abrechnung
            eintragen.</span>
        </span>
        <span class="es-arr" aria-hidden="true">›</span>
      </button>`;
  }

  // Nichts fehlt (auch wenn KEIN Zähler einen Anfangsstand braucht — dann
  // ist `mess.length === 0`, ebenso „nichts offen"). Ruhige Bestätigung,
  // trotzdem anklickbar: der Konfigurator bleibt so für Umbenennen/
  // Verrechnung erreichbar, statt in einer Sackgasse zu enden.
  if (!ohne.length) {
    const anfangSatz = mess.length
      ? `${mess.length === 1 ? 'Für den Zähler ist' : `Für alle ${mess.length} Zähler ist`}
         ein Anfangsstand vor der ersten Abrechnung erfasst. ` : '';
    return `<button class="erststand fertig" data-erststand="1">
        <span class="es-ik ok">${HAKEN_ICON}</span>
        <span class="es-tx">
          <span class="es-t">Zähler eingerichtet</span>
          <span class="es-d">${anfangSatz}${esc(KONFIG_HINWEIS)}</span>
        </span></button>`;
  }

  const text = ohne.length === mess.length
    ? (mess.length === 1
        ? 'Dem Zähler fehlt noch der Anfangsstand vor der ersten Abrechnung.'
        : `Allen ${mess.length} Zählern fehlt noch der Anfangsstand vor der `
          + 'ersten Abrechnung.')
    : `${ohne.length} von ${mess.length} Zählern `
      + `${ohne.length === 1 ? 'hat' : 'haben'} noch keinen Anfangsstand.`;
  return `<button class="erststand offen" data-erststand="1">
      <span class="es-ik">${GAUGE_ICON}</span>
      <span class="es-tx">
        <span class="es-t">Zähler einrichten</span>
        <span class="es-d">${esc(text)} ${esc(KONFIG_HINWEIS)}</span>
      </span>
      <span class="es-arr" aria-hidden="true">›</span>
    </button>`;
}

/* Die Zähler-Rubrik an Ort und Stelle neu zeichnen: nach dem Schließen des
   Zähler-Konfigurators soll die Karte oben stimmen, ohne die ganze Seite neu
   zu laden (siehe zaehler-konfig.js). */
export function erststandAuffrischen() {
  const alt = document.querySelector('.erststand');
  if (!alt) return;
  const html = erststandHtml(erststandZiel);
  if (!html) return alt.remove();
  const halter = document.createElement('div');
  halter.innerHTML = html;
  const neu = halter.firstElementChild;
  if (neu) alt.replaceWith(neu);
}
