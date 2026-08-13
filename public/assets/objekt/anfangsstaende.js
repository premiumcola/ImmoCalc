/* N216/N390 — Anfangszählerstände: die Übersichtskarte unter den
   Abrechnungszeiträumen (`erststandHtml`). Der Anfangsstand hängt an KEINEM
   Zeitraum — er ist der Stand vor der ersten Abrechnung.

   N390 — der eigene Erfassungs-Dialog ist entfallen: `zeitraum/zaehler-
   konfig.js` konnte Anfangsstände schon immer mit erfassen (Name,
   Messeinheit, Bezug, Kostenart, Verrechnung UND Anfangsstand — alles am
   selben Zähler), zwei Dialoge fragten dieselben Felder doppelt ab. Die
   Karte hier öffnet jetzt jenen Dialog mit `{ fokus: 'anfangsstand' }` —
   dieselbe Abfrage, dieselbe Anzeige, nur mit vorab aufgeklappten
   Kategorien, in denen noch etwas fehlt (siehe handlers.js). */

import { esc } from '../immo.js';
import { HAKEN_ICON } from '../objekt-baum.js?v=2';
import { istGrundstueck } from '../objekt-state.js?v=2';
import { GAUGE_ICON, zaehlerListe, erststandZiel } from './state.js';

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
  // Zähler vorhanden, aber keiner misst (nur Rest/inaktiv) — kein Anfangsstand nötig.
  if (zaehlerListe.length && mess.length === 0) return '';

  // Alles hinterlegt — ruhige Bestätigung. N141: trotzdem anklickbar, damit die
  // Übersicht (und ein Ändern) erreichbar bleibt, statt in einer Sackgasse zu
  // enden. Kein Pfeil, kein Drängen — nur ein leiser Weg hinein.
  if (mess.length && !ohne.length) {
    return `<button class="erststand fertig" data-erststand="1">
        <span class="es-ik ok">${HAKEN_ICON}</span>
        <span class="es-tx">
          <span class="es-t">Anfangszählerstände hinterlegt</span>
          <span class="es-d">${mess.length === 1
            ? 'Für den Zähler ist ein Erststand'
            : `Für alle ${mess.length} Zähler ist ein Erststand`} vor der ersten
            Abrechnung erfasst — Übersicht ansehen.</span>
        </span></button>`;
  }

  const text = !zaehlerListe.length
    ? 'Noch keine Zähler angelegt — für verbrauchsabhängige Kosten die Zähler '
      + 'und ihren Anfangsstand vor der ersten Abrechnung einrichten.'
    : ohne.length === mess.length
      ? (mess.length === 1
          ? 'Dem Zähler fehlt noch der Anfangsstand vor der ersten Abrechnung.'
          : `Allen ${mess.length} Zählern fehlt noch der Anfangsstand vor der `
            + 'ersten Abrechnung.')
      : `${ohne.length} von ${mess.length} Zählern `
        + `${ohne.length === 1 ? 'hat' : 'haben'} noch keinen Anfangsstand.`;

  const zielAttr = zielId != null ? ` data-z="${esc(String(zielId))}"` : '';
  return `<button class="erststand offen" data-erststand="1"${zielAttr}>
      <span class="es-ik">${GAUGE_ICON}</span>
      <span class="es-tx">
        <span class="es-t">Anfangszählerstand erfassen</span>
        <span class="es-d">${esc(text)}</span>
      </span>
      <span class="es-arr" aria-hidden="true">›</span>
    </button>`;
}

/* Die Anfangsstand-Rubrik an Ort und Stelle neu zeichnen: nach dem Speichern
   soll der Zähler oben stimmen, ohne die ganze Seite neu zu laden. Wird nach
   dem Schließen des Zähler-Konfigurators aufgerufen (siehe zaehler-konfig.js). */
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
