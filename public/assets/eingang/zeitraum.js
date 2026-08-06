/* N216 — Der Abrechnungszeitraum am Pruefblatt: Vorschlagen, Auswaehlen,
   Anlegen (CXXV/CCLVIII/CLXXII).

   `zeitraeumeFuellen` beschriftet das Feld nach dem aktuellen Beleg-Datum;
   `zeitraumHinweisZeigen` schreibt die dezente Warnzeile darunter; die
   „…anlegen"-Option loest ueber `zeitraumAnlegenUndWaehlen` das POST zum
   Anlegen eines Vorschlags aus. */

import { S, els, ANLEGEN, melde } from './state.js';
import { api } from '../immo.js';
import { auswahlfeld } from '../auswahl.js';
import { belegTag, dmy, isoTag, passenderZeitraum, umfasst,
         zumDatum, befund, dok } from './helpers.js';
import { stand } from './liste.js';
import { planZeichnen } from './plan.js';

/** Der Zeitraum-Katalog einer Immobilie — inkl. echten von/bis-Daten. */
export async function zeitraeumeFuer(slug) {
  if (!slug) return [];
  if (S.zeitraeumeJeObjekt.has(slug)) return S.zeitraeumeJeObjekt.get(slug);
  try {
    const antwort = await api(`/objekte/${encodeURIComponent(slug)}`);
    const zs = (antwort.zeitraeume || []).map(z => {
      const [von, bis] = String(z.label).split('–');
      return { ...z, von: zumDatum(von), bis: zumDatum(bis) };
    });
    S.zeitraeumeJeObjekt.set(slug, zs);
    return zs;
  } catch {
    return [];       // ohne Zeitraeume bleibt das Feld eben leer
  }
}

/** CCLVIII: Der Server sagt, welcher Abrechnungszeitraum zum Beleg-Datum passt —
    entweder ein vorhandener (`id`) oder die Grenzen zum Anlegen (`vorschlag`).
    Faellt die Abfrage aus (etwa vor dem Deploy), bleibt es beim rein
    client-seitigen Vorschlag, und die Seite verhaelt sich wie zuvor. */
export async function zeitraumErkennen(slug, tag) {
  if (!slug || !tag) return null;
  try {
    return await api(`/objekte/${encodeURIComponent(slug)}`
      + `/zeitraum-fuer?datum=${isoTag(tag)}`);
  } catch {
    return null;
  }
}

export async function zeitraeumeFuellen(d) {
  // Die gerade eingestellte Immobilie zaehlt, nicht die gespeicherte.
  const slug = (S.erfassung && S.erfassung.id === d.id ? S.erfassung.objekt.wert() : '')
    || d.objekt || '';
  const zs = await zeitraeumeFuer(slug);
  if (S.gewaehlt !== d.id) return;          // inzwischen etwas anderes gewaehlt
  S.zeitraumListe = zs;
  const { tag } = belegTag(stand() || befund(d));
  const treffer = await zeitraumErkennen(slug, tag);
  if (S.gewaehlt !== d.id) return;          // die Abfrage hat gewartet
  // Der Server ist die massgebliche Quelle; faellt er aus, greift der
  // client-seitige Abgleich als Rueckfall (kein „…anlegen", aber Vorauswahl).
  const vorhanden = treffer && !treffer.vorschlag
    ? zs.find(z => z.id === treffer.id) || null
    : (treffer ? null : passenderZeitraum(zs, tag));
  S.zeitraumVorschlag = treffer && treffer.vorschlag ? treffer : null;

  const optionen = [{ wert: '', text: 'ohne Abrechnung' },
    ...zs.map(z => ({ wert: String(z.id),
      text: z.label + (vorhanden && vorhanden.id === z.id ? ' · Vorschlag' : '') }))];
  // Kein passender Zeitraum da → den vorgeschlagenen zum Anlegen anbieten.
  if (S.zeitraumVorschlag) {
    optionen.push({ wert: ANLEGEN,
      text: `${S.zeitraumVorschlag.jahr} anlegen (${S.zeitraumVorschlag.label})` });
  }
  // Der gespeicherte Zeitraum gilt nur, wenn er zu dieser Immobilie gehoert —
  // sonst zeigte das Feld nach einem Wechsel auf eine fremde Abrechnung.
  const gesetzt = zs.some(z => z.id === d.zeitraum_id) ? d.zeitraum_id : null;
  const wert = String(gesetzt || (vorhanden ? vorhanden.id : '') || '');
  if (!S.zeitraumFeld) {
    S.zeitraumFeld = auswahlfeld(els.bZeitraum, {
      optionen, wert, label: 'Abrechnungszeitraum',
      aenderung: () => zeitraumGewaehlt(),
    });
  } else {
    S.zeitraumFeld.fuelle(optionen, wert);
  }
  planZeichnen();
}

/** Reagiert auf die Auswahl im Zeitraum-Feld. Ist es die „…anlegen"-Option,
    wird der vorgeschlagene Zeitraum erst angelegt und dann gewaehlt; sonst
    genuegt das Neuzeichnen. */
export function zeitraumGewaehlt() {
  if (S.zeitraumFeld && S.zeitraumFeld.wert() === ANLEGEN && S.zeitraumVorschlag) {
    zeitraumAnlegenUndWaehlen(S.zeitraumVorschlag);
    return;
  }
  planZeichnen();
}

/** CCLVIII: legt den vorgeschlagenen Zeitraum an (POST) und waehlt ihn im Feld.
    Danach laeuft der Beleg ueber den unveraenderten Uebernehmen-Weg in diesen
    Zeitraum. Server und Anlegen nutzen dieselbe Grenzen-Regel — es entsteht
    genau der Zeitraum, der vorgeschlagen wurde. */
export async function zeitraumAnlegenUndWaehlen(vorschlag) {
  const d = S.gewaehlt !== null ? dok(S.gewaehlt) : null;
  if (!d) return;
  const slug = (S.erfassung && S.erfassung.id === d.id ? S.erfassung.objekt.wert() : '')
    || d.objekt || '';
  if (!slug) return;
  els.bZeitHinweis.textContent = `Abrechnungszeitraum ${vorschlag.label} wird angelegt …`;
  els.bZeitHinweis.classList.remove('warn');
  try {
    const neu = await api(`/objekte/${encodeURIComponent(slug)}/zeitraeume`,
      { method: 'POST', body: { jahr: vorschlag.jahr } });
    S.zeitraeumeJeObjekt.delete(slug);       // Cache verwerfen — der neue muss rein
    const zs = await zeitraeumeFuer(slug);
    if (S.gewaehlt !== d.id) return;
    S.zeitraumListe = zs;
    S.zeitraumVorschlag = null;
    const optionen = [{ wert: '', text: 'ohne Abrechnung' },
      ...zs.map(z => ({ wert: String(z.id),
        text: z.label + (z.id === neu.id ? ' · Vorschlag' : '') }))];
    if (S.zeitraumFeld) S.zeitraumFeld.fuelle(optionen, String(neu.id));
    melde(`✓ Abrechnungszeitraum ${neu.label} angelegt`, 'gut');
    planZeichnen();
  } catch (fehler) {
    // Auswahl zuruecknehmen, damit kein Sentinel im Stand haengen bleibt.
    if (S.zeitraumFeld) S.zeitraumFeld.setze('');
    els.bZeitHinweis.textContent = '⚠ Zeitraum ließ sich nicht anlegen: '
      + String(fehler.message || fehler);
    els.bZeitHinweis.classList.add('warn');
    planZeichnen();
  }
}

/** Ehrlich, aber nicht verbietend (CLXXII): eine Nachtragsrechnung darf an
    einen Zeitraum, in den ihr Datum nicht faellt — gesagt wird es trotzdem.
    Und faellt das Datum in gar keinen Zeitraum, wird nicht still der erste
    genommen, sondern es steht da. */
export function zeitraumHinweisZeigen() {
  const d = S.gewaehlt !== null ? dok(S.gewaehlt) : null;
  const zs = S.zeitraumListe;
  if (!d || d.vermisst) { els.bZeitHinweis.textContent = ''; return; }
  const { tag, genau } = belegTag(stand() || befund(d));
  const id = S.zeitraumFeld ? S.zeitraumFeld.wert() : '';
  const z = id ? zs.find(x => String(x.id) === id) : null;
  let text = '';
  let warnen = false;
  if (!zs.length) {
    text = 'Für diese Immobilie ist noch kein Abrechnungszeitraum angelegt.';
  } else if (!tag) {
    text = 'Ohne Belegdatum lässt sich der Zeitraum nur raten — '
         + 'trag das Datum der Rechnung ein.';
  } else if (z && !umfasst(z, tag)) {
    text = `${dmy(tag)} liegt außerhalb von ${z.label} — als Nachtrag möglich.`;
    warnen = true;
  } else if (!passenderZeitraum(zs, tag)) {
    text = `${dmy(tag)} fällt in keinen angelegten Abrechnungszeitraum.`;
    warnen = true;
  } else if (!genau) {
    text = 'Aus Jahr und Monat geschätzt — mit dem genauen Rechnungsdatum '
         + 'stimmt die Zuordnung sicher.';
  }
  els.bZeitHinweis.textContent = text;
  els.bZeitHinweis.classList.toggle('warn', warnen);
}
