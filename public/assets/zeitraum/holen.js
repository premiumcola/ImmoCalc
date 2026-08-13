/* Ein Anfrage-Bündel je Ladevorgang (N369).

   Die Zeitraum-Seite baut sich aus vielen Bausteinen, und mehrere davon
   brauchen dieselbe Auskunft. Gemessen wurden bis zu vier identische GETs auf
   `heizoel/bewertung`, `heizverteiler` und `waerme/split` je Zeichnung —
   einmal aus `laden()`, einmal je aufgeklapptem Öl-Panel (Öl, Warmwasser,
   Heizkörper-Wärmemenge). Dazu ein Wettlauf auf `zeitraeume/{id}/wasser`:
   zwei Aufrufer prüften denselben Wert-Cache, bevor ihn einer gefüllt hatte.

   `einmal()` merkt sich das PROMISE, nicht das Ergebnis — damit greift die
   Bündelung schon, während die erste Anfrage noch läuft, und der Wettlauf ist
   strukturell weg. `neuerLauf()` verwirft das Bündel; es steht am Anfang von
   `laden()`, sodass jeder Ladevorgang frische Daten sieht und nur innerhalb
   eines Laufs gebündelt wird. */
import { api } from '../immo.js';

let buendel = new Map();

/** Verwirft das Bündel — am Anfang jedes Ladevorgangs. */
export function neuerLauf() {
  buendel = new Map();
}

function merken(schluessel, starten) {
  if (!buendel.has(schluessel)) {
    buendel.set(schluessel, starten().catch(fehler => {
      // Fehler werden nicht gemerkt: ein misslungener Aufruf darf den
      // nächsten Versuch nicht blockieren.
      buendel.delete(schluessel);
      throw fehler;
    }));
  }
  return buendel.get(schluessel);
}

/** Holt `pfad` höchstens einmal je Ladevorgang. */
export function einmal(pfad) {
  return merken(pfad, () => api(pfad));
}

/** Dasselbe für eine rechnende POST-Abfrage, die nichts speichert.
 *
 *  `heizkosten/rechnen` ist so eine: sie schreibt nichts, liefert nur die
 *  Verteilung — und wurde je Seitenaufbau sechsmal mit identischem Rumpf
 *  gestellt (drei Öl-Panels × zwei Zeichnungen). Der Rumpf gehört in den
 *  Schlüssel, sonst bündelte man verschiedene Fragen zu einer. */
export function einmalPost(pfad, body) {
  const schluessel = `POST ${pfad} ${JSON.stringify(body ?? null)}`;
  return merken(schluessel, () => api(pfad, { method: 'POST', body }));
}
